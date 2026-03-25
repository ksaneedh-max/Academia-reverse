import re
from typing import Dict, Any
from bs4 import BeautifulSoup


KNOWN_LABELS = {
    "Registration Number",
    "Name",
    "Program",
    "Department",
    "Specialization",
    "Semester",
    "Batch",
    "Feedback Status",
    "Enrollment Status / DOE",
    "Photo-ID",
    "Mobile",
}


# =========================
# DEBUG / SAFE HELPERS
# =========================
def _snip(text: str, limit: int = 220) -> str:
    text = text or ""
    text = text.replace("\n", "\\n").replace("\r", "\\r")
    return text[:limit] + ("..." if len(text) > limit else "")


def _decode_js_fragment(fragment: str) -> str:
    """
    Decode a JavaScript string fragment that may contain:
    - \\xNN hex escapes
    - unicode escapes
    - normal HTML text
    """
    fragment = fragment or ""

    # Decode \xNN first
    fragment = re.sub(
        r"\\x([0-9a-fA-F]{2})",
        lambda m: chr(int(m.group(1), 16)),
        fragment,
    )

    # Then decode unicode escapes
    try:
        fragment = fragment.encode("utf-8").decode("unicode_escape")
    except Exception:
        pass

    return fragment


def _iter_label_value_pairs(cells):
    """
    Safely iterate label/value pairs from a row that may contain:
    - label | value
    - label | : | value
    - label | value | label | : | value
    """
    i = 0
    n = len(cells)

    while i < n - 1:
        label = cells[i].get_text(" ", strip=True).replace(":", "").strip()

        if not label:
            i += 1
            continue

        # If the next cell is just a colon, use the cell after that as value.
        next_text = cells[i + 1].get_text(" ", strip=True) if i + 1 < n else ""
        if next_text == ":" and i + 2 < n:
            value = cells[i + 2].get_text(" ", strip=True)
            step = 3
        else:
            value = next_text
            step = 2

        yield label, value, i, step
        i += step


# =========================
# ULTRA SAFE HTML EXTRACTION
# =========================
def extract_html(html_content: str) -> str:
    print("\n========== [EXTRACT_HTML START] ==========")
    print("[DEBUG] Raw HTML length:", len(html_content))

    try:
        match = re.search(
            r"pageSanitizer\.sanitize\((['\"])([\s\S]*?)\1\)",
            html_content,
            re.DOTALL,
        )

        if match:
            print("✓ Found sanitize block")

            escaped_html = match.group(2)

            # STEP 1: decode \xNN
            html_decoded = re.sub(
                r'\\x([0-9a-fA-F]{2})',
                lambda m: chr(int(m.group(1), 16)),
                escaped_html
            )

            # STEP 2: decode unicode
            html_decoded = html_decoded.encode().decode("unicode_escape")

            # STEP 3: FIX CRITICAL ISSUE (THIS WAS MISSING)
            html_decoded = html_decoded.replace("\\/", "/")
            html_decoded = html_decoded.replace("\\<", "<")
            html_decoded = html_decoded.replace("\\>", ">")
            html_decoded = html_decoded.replace('\\"', '"')
            html_decoded = html_decoded.replace("\\'", "'")

            print("[DEBUG] After FULL CLEAN:")
            print("HAS <table>:", "<table" in html_decoded)
            print("Sample:", html_decoded[:300])

            return html_decoded

    except Exception as e:
        print("[ERROR] extraction failed:", e)

    print("⚠ fallback raw html")
    return html_content

# =========================
# SAFE NUMBER HELPERS
# =========================
def safe_int(val):
    try:
        return int(str(val).strip())
    except Exception:
        return 0


def safe_float(val):
    try:
        return float(str(val).replace("%", "").strip())
    except Exception:
        return 0.0


# =========================
# ATTENDANCE PARSER
# =========================
def parse_attendance(html_content: str) -> Dict[str, Any]:
    print("\n\n================ [PARSE ATTENDANCE START] ================")

    html_decoded = extract_html(html_content)

    print("\n[DEBUG] FINAL HTML CHECK:")
    print("HAS TABLE:", "<table" in html_decoded)
    print("HAS COURSE CODE:", "Course Code" in html_decoded)
    print("HAS TEST PERFORMANCE:", "Test Performance" in html_decoded)
    print("HTML LENGTH:", len(html_decoded))

    soup = BeautifulSoup(html_decoded, "html.parser")
    tables = soup.find_all("table")
    print("[DEBUG] Total tables found:", len(tables))

    data = {
        "student_info": {},
        "attendance": {
            "courses": {},
            "overall_attendance": 0.0,
            "total_hours_conducted": 0,
            "total_hours_absent": 0,
        },
        "marks": {},
        "summary": {},
    }

    # ---------------- STUDENT INFO ----------------
    print("\n[DEBUG] Parsing student info...")

    for row_idx, row in enumerate(soup.find_all("tr")):
        cells = row.find_all("td")
        if len(cells) < 1:
            continue

        for label, value, start_idx, step in _iter_label_value_pairs(cells):
            if label not in KNOWN_LABELS and "Photo-ID" not in label:
                continue

            print(f"[DEBUG] Student info row {row_idx}: {label} -> {_snip(value, 80)}")

            if label == "Registration Number":
                data["student_info"]["registration_number"] = value
            elif label == "Name":
                data["student_info"]["name"] = value
            elif label == "Program":
                data["student_info"]["program"] = value
            elif label == "Department":
                data["student_info"]["department"] = value
            elif label == "Specialization":
                data["student_info"]["specialization"] = value
            elif label == "Semester":
                data["student_info"]["semester"] = value
            elif label == "Batch":
                data["student_info"]["batch"] = value
            elif label == "Feedback Status":
                # value may be "Completed" or "<font ...>Completed"
                data["student_info"]["feedback_status"] = value
            elif label == "Enrollment Status / DOE":
                parts = [p.strip() for p in value.split(" / ") if p.strip()]
                if len(parts) == 2:
                    data["student_info"]["enrollment_status"] = parts[0]
                    data["student_info"]["enrollment_date"] = parts[1]
            elif "Photo-ID" in label:
                # Photo cell often has an <img>
                img_cell_idx = start_idx + 1
                if img_cell_idx < len(cells):
                    img_tag = cells[img_cell_idx].find("img")
                    if img_tag and img_tag.get("src"):
                        data["student_info"]["photo_url"] = img_tag.get("src")

    print("[DEBUG] Student info keys:", list(data["student_info"].keys()))
    print("[DEBUG] Student info extracted:", bool(data["student_info"]))

    # ---------------- ATTENDANCE TABLE ----------------
    print("\n[DEBUG] Searching attendance table...")

    attendance_table = None
    attendance_table_index = -1

    for idx, table in enumerate(tables):
        text = table.get_text(" ", strip=True)
        print(f"[DEBUG] Table {idx} length:", len(text))
        if "Course Code" in text and ("Hours Conducted" in text or "Attn %" in text):
            attendance_table = table
            attendance_table_index = idx
            print(f"✓ Attendance table FOUND at index {idx}")
            break

    if not attendance_table:
        print("❌ Attendance table NOT FOUND")

    total_conducted = 0
    total_absent = 0

    if attendance_table:
        rows = attendance_table.find_all("tr")
        print("[DEBUG] Attendance rows total:", len(rows))

        # Skip header row if present
        data_rows = rows[1:] if len(rows) > 0 else []
        print("[DEBUG] Attendance rows after header skip:", len(data_rows))

        for i, row in enumerate(data_rows):
            cells = row.find_all("td")

            if len(cells) < 9:
                print(f"[WARN] Attendance row {i} skipped (not enough columns: {len(cells)})")
                continue

            try:
                course_code_raw = cells[0].get_text(" ", strip=True)
                print(f"[DEBUG] Row {i} raw course cell:", _snip(course_code_raw, 120))

                # Extract exact course code if it is embedded with "Regular"
                code_match = re.search(r"\d{2}[A-Z]{3}\d{3}[A-Z]", course_code_raw)
                course_code = code_match.group(0) if code_match else course_code_raw.strip()

                category = cells[2].get_text(" ", strip=True)
                conducted = safe_int(cells[6].get_text(" ", strip=True))
                absent = safe_int(cells[7].get_text(" ", strip=True))
                percentage = safe_float(cells[8].get_text(" ", strip=True))

                total_conducted += conducted
                total_absent += absent

                key = f"{course_code}{category}"

                data["attendance"]["courses"][key] = {
                    "course_title": cells[1].get_text(" ", strip=True),
                    "category": category,
                    "faculty_name": cells[3].get_text(" ", strip=True),
                    "slot": cells[4].get_text(" ", strip=True),
                    "room_no": cells[5].get_text(" ", strip=True),
                    "hours_conducted": conducted,
                    "hours_absent": absent,
                    "attendance_percentage": percentage,
                }

                print(f"[DEBUG] Parsed attendance row {i}: {key}")

            except Exception as e:
                print(f"[ERROR] Failed parsing attendance row {i}: {e}")

    print("\n[DEBUG] Attendance courses parsed:", len(data["attendance"]["courses"]))

    if total_conducted > 0:
        data["attendance"]["overall_attendance"] = round(
            ((total_conducted - total_absent) / total_conducted) * 100, 2
        )

    data["attendance"]["total_hours_conducted"] = total_conducted
    data["attendance"]["total_hours_absent"] = total_absent

    print("[DEBUG] Attendance total conducted:", total_conducted)
    print("[DEBUG] Attendance total absent:", total_absent)
    print("[DEBUG] Attendance overall %:", data["attendance"]["overall_attendance"])

    # ---------------- MARKS ----------------
    print("\n[DEBUG] Searching marks tables...")

    marks_tables = []

    for idx, table in enumerate(soup.find_all('table')):
        text = table.get_text(" ", strip=True)

        print(f"[DEBUG] Table {idx} preview: {text[:80]}")

        # relaxed detection
        if (
            "Course Code" in text
            or "Test" in text
            or "Performance" in text
            or "Marks" in text
        ):
            marks_tables.append(table)

    print(f"[DEBUG] Marks tables found: {len(marks_tables)}")

    # ---------------- PARSE MARKS (FINAL FIXED MATCH OLD RESPONSE) ----------------
    for table in marks_tables:

        table_text = table.get_text()

        # ✅ STRICT FILTER → ONLY ACTUAL MARKS TABLE
        if "Course Code" not in table_text or "Test Performance" not in table_text:
            continue

        print("\n[DEBUG] ✅ Valid marks table detected")

        rows = table.find_all('tr')

        for row_idx, row in enumerate(rows[1:]):  # skip header
            cells = row.find_all('td')

            if len(cells) < 3:
                continue

            try:
                course_code_raw = cells[0].get_text(strip=True)
                # 🔥 FIX: Remove "Regular" from code
                course_code = re.sub(r'Regular', '', course_code_raw).strip()
                course_type = cells[1].get_text(strip=True)

                print(f"[DEBUG] Marks row {row_idx}: {course_code} | {course_type}")

                # ✅ STRICT COURSE CODE VALIDATION
                if not re.match(r'^\d{2}[A-Z]{3}\d{3}[A-Z]$', course_code):
                    print("[DEBUG] ❌ Invalid course code → skipped")
                    continue

                # ✅ STRICT TYPE FILTER
                if course_type not in ["Theory", "Practical"]:
                    print("[DEBUG] ❌ Invalid course type → skipped")
                    continue

                tests = []

                performance_cell = cells[2]
                inner_table = performance_cell.find('table')

                if inner_table:
                    for inner_row in inner_table.find_all('tr'):
                        for cell in inner_row.find_all('td'):
                            text = cell.get_text("\n", strip=True)
                            lines = [l.strip() for l in text.split("\n") if l.strip()]

                            if len(lines) >= 2 and "/" in lines[0]:
                                try:
                                    name, max_marks = lines[0].split("/")
                                    name = name.replace("\\-", "-")
                                    obtained = safe_float(lines[1])
                                    max_marks = safe_float(max_marks)

                                    tests.append({
                                        "test_name": name,
                                        "obtained_marks": obtained,
                                        "max_marks": max_marks,
                                        "percentage": round((obtained / max_marks) * 100, 2) if max_marks else 0
                                    })

                                    print(f"[DEBUG] ✅ Parsed test: {name} {obtained}/{max_marks}")

                                except Exception as e:
                                    print(f"[WARN] Test parse failed: {e}")
                                    continue

                # ✅ IMPORTANT FIX 1 → DO NOT SKIP EMPTY TESTS
                if not tests:
                    print("[DEBUG] ⚠ No tests found → keeping empty (like old response)")

                # ✅ IMPORTANT FIX 2 → RESTORE 'Regular' IN KEY
                # CLEAN course_code (remove "Regular" if present)
                course_code = re.sub(r'Regular', '', course_code).strip()

                # CORRECT key format (matches old response)
                regn_type = "Regular"
                key = course_code + regn_type + course_type

                data['marks'][key] = {
                    "course_type": course_type,
                    "tests": tests  # can be []
                }

                print(f"[DEBUG] ✅ Added marks entry: {key}")

            except Exception as e:
                print(f"[WARN] Marks row failed: {e}")
                continue

    print(f"[DEBUG] ✅ Final marks entries parsed: {len(data['marks'])}")

    print("\n================ [PARSE ATTENDANCE END] ================\n")
    return data

# =========================
# TIMETABLE PARSER
# =========================
def parse_timetable(html_content: str) -> Dict[str, Any]:
    print("\n\n================ [PARSE TIMETABLE START] ================")

    html_decoded = extract_html(html_content)

    print("\n[DEBUG] TIMETABLE HTML CHECK:")
    print("HAS TABLE:", "<table" in html_decoded)
    print("HTML LENGTH:", len(html_decoded))

    soup = BeautifulSoup(html_decoded, "html.parser")
    tables = soup.find_all("table")
    print("[DEBUG] Total tables found:", len(tables))

    data = {
        "student_info": {
            "registration_number": "",
            "name": "",
            "batch": "",
            "mobile": "",
            "program": "",
            "department": "",
            "semester": "",
        },
        "courses": [],
        "advisors": {},
        "total_credits": 0,
    }

    # ---------------- STUDENT INFO ----------------
    print("\n[DEBUG] Parsing timetable student info...")

    for t_idx, table in enumerate(tables):
        for row_idx, row in enumerate(table.find_all("tr")):
            cells = row.find_all("td")
            if len(cells) < 2:
                continue

            for label, value, start_idx, step in _iter_label_value_pairs(cells):
                if label in KNOWN_LABELS or label == "Mobile":
                    print(f"[DEBUG] Timetable row {row_idx}: {label} -> {_snip(value, 80)}")

                if "Registration Number" in label:
                    data["student_info"]["registration_number"] = value
                elif label == "Name":
                    data["student_info"]["name"] = value
                elif "Batch" in label:
                    # handles "Batch" as well as "Combo / Batch"
                    if "/" in value:
                        data["student_info"]["batch"] = value.split("/")[-1].strip()
                    else:
                        data["student_info"]["batch"] = value
                elif label == "Mobile":
                    data["student_info"]["mobile"] = value
                elif label == "Program":
                    data["student_info"]["program"] = value
                elif "Department" in label:
                    data["student_info"]["department"] = value
                elif label == "Semester":
                    data["student_info"]["semester"] = value

    # ---------------- COURSES ----------------
    print("\n[DEBUG] Parsing timetable courses...")

    for t_idx, table in enumerate(tables):
        for row_idx, row in enumerate(table.find_all("tr")):
            cells = row.find_all("td")

            if len(cells) >= 11:
                try:
                    first_cell = cells[0].get_text(" ", strip=True)
                    if not first_cell.isdigit():
                        continue

                    course_code = cells[1].get_text(" ", strip=True)
                    code_match = re.search(r"\d{2}[A-Z]{3}\d{3}[A-Z]", course_code)
                    if not code_match:
                        continue

                    course_code = code_match.group(0)
                    credit = safe_int(cells[3].get_text(" ", strip=True))

                    course = {
                        "s_no": first_cell,
                        "course_code": course_code,
                        "course_title": cells[2].get_text(" ", strip=True),
                        "credit": credit,
                        "regn_type": cells[4].get_text(" ", strip=True),
                        "category": cells[5].get_text(" ", strip=True),
                        "course_type": cells[6].get_text(" ", strip=True),
                        "faculty_name": cells[7].get_text(" ", strip=True),
                        "slot": cells[8].get_text(" ", strip=True),
                        "room_no": cells[9].get_text(" ", strip=True),
                        "academic_year": cells[10].get_text(" ", strip=True),
                    }

                    data["courses"].append(course)
                    print(f"[DEBUG] Parsed timetable course row {row_idx}: {course_code}")

                except Exception as e:
                    print(f"[WARN] Timetable parse error (table {t_idx}, row {row_idx}): {e}")

    # ---------------- TOTAL CREDITS ----------------
    seen = set()
    for c in data["courses"]:
        if c["course_code"] not in seen:
            seen.add(c["course_code"])
            data["total_credits"] += c["credit"]

    print("[DEBUG] Timetable courses parsed:", len(data["courses"]))
    print("[DEBUG] Timetable unique course codes:", len(seen))
    print("[DEBUG] Timetable total credits:", data["total_credits"])
    print("================ [PARSE TIMETABLE END] ================\n")

    return data
