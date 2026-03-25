import re
import html
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
# HELPERS
# =========================
def clean_text(val):
    return html.unescape(str(val)).replace("\\-", "-").strip()


def safe_int(val):
    try:
        return int(str(val).strip())
    except:
        return 0


def safe_float(val):
    try:
        return float(str(val).replace("%", "").strip())
    except:
        return 0.0


# =========================
# HTML EXTRACTOR
# =========================
def extract_html(html_content: str) -> str:
    try:
        match = re.search(
            r"pageSanitizer\.sanitize\((['\"])([\s\S]*?)\1\)",
            html_content,
            re.DOTALL,
        )

        if match:
            escaped_html = match.group(2)

            html_decoded = re.sub(
                r'\\x([0-9a-fA-F]{2})',
                lambda m: chr(int(m.group(1), 16)),
                escaped_html
            )

            html_decoded = html_decoded.encode().decode("unicode_escape")

            html_decoded = html_decoded.replace("\\/", "/")
            html_decoded = html_decoded.replace("\\<", "<")
            html_decoded = html_decoded.replace("\\>", ">")
            html_decoded = html_decoded.replace('\\"', '"')
            html_decoded = html_decoded.replace("\\'", "'")

            html_decoded = html.unescape(html_decoded)

            soup = BeautifulSoup(html_decoded, "html.parser")
            return str(soup)

    except:
        pass

    return html_content


# =========================
# ATTENDANCE PARSER
# =========================
def parse_attendance(html_content: str) -> Dict[str, Any]:
    html_decoded = extract_html(html_content)
    soup = BeautifulSoup(html_decoded, "html.parser")

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

    # ---------- STUDENT INFO ----------
    for row in soup.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) < 2:
            continue

        for i in range(0, len(cells) - 1, 2):
            label_raw = cells[i].get_text(" ", strip=True)
            label = label_raw.replace(":", "").strip().lower()

            value = clean_text(cells[i + 1].get_text(" ", strip=True))

            if "registration number" in label:
                data["student_info"]["registration_number"] = value

            elif label == "name":
                data["student_info"]["name"] = value

            elif "program" in label:
                data["student_info"]["program"] = value

            elif "department" in label:
                data["student_info"]["department"] = value

            elif "specialization" in label:
                data["student_info"]["specialization"] = value

            elif "semester" in label:
                data["student_info"]["semester"] = value

            elif "batch" in label:
                match = re.search(r"\d+", value)
                if match:
                    data["student_info"]["batch"] = match.group(0)

            elif "enrollment status" in label:
                parts = value.split(" / ")
                if len(parts) == 2:
                    data["student_info"]["enrollment_status"] = parts[0]
                    data["student_info"]["enrollment_date"] = parts[1]

    # ---------- ATTENDANCE ----------
    tables = soup.find_all("table")

    total_conducted = 0
    total_absent = 0

    for table in tables:
        text = table.get_text()

        if "Course Code" in text and "Hours Conducted" in text:
            rows = table.find_all("tr")[1:]

            for row in rows:
                cells = row.find_all("td")
                if len(cells) < 9:
                    continue

                course_code = re.search(r"\d{2}[A-Z]{3}\d{3}[A-Z]", cells[0].text)
                if not course_code:
                    continue

                course_code = course_code.group(0)
                category = cells[2].get_text(strip=True)

                conducted = safe_int(cells[6].text)
                absent = safe_int(cells[7].text)
                percentage = safe_float(cells[8].text)

                total_conducted += conducted
                total_absent += absent

                key = f"{course_code}Regular{category}"

                data["attendance"]["courses"][key] = {
                    "course_title": cells[1].get_text(strip=True),
                    "category": category,
                    "faculty_name": cells[3].get_text(strip=True),
                    "slot": cells[4].get_text(strip=True),
                    "room_no": cells[5].get_text(strip=True),
                    "hours_conducted": conducted,
                    "hours_absent": absent,
                    "attendance_percentage": percentage,
                }

    if total_conducted:
        data["attendance"]["overall_attendance"] = round(
            ((total_conducted - total_absent) / total_conducted) * 100, 2
        )

    data["attendance"]["total_hours_conducted"] = total_conducted
    data["attendance"]["total_hours_absent"] = total_absent

    # ---------- MARKS (RESTORED + IMPROVED) ----------
    # ---------- MARKS (FIXED + SAFE) ----------
    for table in tables:
        if "Test Performance" not in table.get_text():
            continue

        rows = table.find_all("tr")[1:]

        for row in rows:
            cells = row.find_all("td")
            if len(cells) < 3:
                continue

            course_code = re.sub(r"Regular", "", cells[0].get_text(strip=True))
            course_type = cells[1].get_text(strip=True)

            if not re.match(r"\d{2}[A-Z]{3}\d{3}[A-Z]", course_code):
                continue

            tests = []

            inner_cells = cells[2].find_all(["td", "div"])

            for c in inner_cells:
                text = c.get_text("\n", strip=True)

                if not text or "/" not in text:
                    continue

                lines = text.split("\n")

                if len(lines) < 2:
                    continue

                try:
                    name_part = lines[0].strip()
                    marks_part = lines[1].strip()

                    # Split test name and max marks
                    if "/" not in name_part:
                        continue

                    name, maxm = name_part.split("/", 1)

                    name = clean_text(name)  # FIX: removes \-
                    maxm = safe_float(maxm)
                    obtained = safe_float(marks_part)

                    if maxm == 0:
                        percentage = 0
                    else:
                        percentage = round((obtained / maxm) * 100, 2)

                    tests.append({
                        "test_name": name,
                        "obtained_marks": obtained,
                        "max_marks": maxm,
                        "percentage": percentage
                    })

                except:
                    continue

            key = course_code + course_type

            data["marks"][key] = {
                "course_type": course_type,
                "tests": tests
            }

    return data

# =========================
# TIMETABLE PARSER
# =========================
def parse_timetable(html_content: str) -> Dict[str, Any]:
    html_decoded = extract_html(html_content)
    soup = BeautifulSoup(html_decoded, "html.parser")

    tables = soup.find_all("table")

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

    # ---------- STUDENT INFO ----------
    for row in soup.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) < 2:
            continue

        for i in range(0, len(cells) - 1, 2):

            label_raw = cells[i].get_text(" ", strip=True)
            label = label_raw.replace(":", "").strip().lower()

            value = clean_text(cells[i + 1].get_text(" ", strip=True))

            if "registration number" in label:
                data["student_info"]["registration_number"] = value

            elif label == "name":
                data["student_info"]["name"] = value

            elif "batch" in label:
                match = re.search(r"\d+", value)
                if match:
                    data["student_info"]["batch"] = match.group(0)

            elif "mobile" in label:
                data["student_info"]["mobile"] = value

            elif "program" in label:
                data["student_info"]["program"] = value

            elif "department" in label:
                data["student_info"]["department"] = value

            elif "semester" in label:
                data["student_info"]["semester"] = value

    # ---------- COURSES ----------
    for table in tables:
        if "Course Code" not in table.get_text():
            continue

        tds = table.find_all("td")
        i = 0

        while i + 10 < len(tds):
            if not tds[i].get_text(strip=True).isdigit():
                i += 1
                continue

            data["courses"].append({
                "s_no": tds[i].get_text(strip=True),
                "course_code": tds[i + 1].get_text(strip=True),
                "course_title": tds[i + 2].get_text(strip=True),
                "credit": safe_int(tds[i + 3].get_text(strip=True)),
                "regn_type": tds[i + 4].get_text(strip=True),
                "category": tds[i + 5].get_text(strip=True),
                "course_type": tds[i + 6].get_text(strip=True),
                "faculty_name": tds[i + 7].get_text(strip=True),
                "slot": clean_text(tds[i + 8].get_text(strip=True)),
                "room_no": tds[i + 9].get_text(strip=True),
                "academic_year": clean_text(tds[i + 10].get_text(strip=True)),
            })

            i += 11

    # ---------- ADVISORS ----------
    for table in tables:
        if "Faculty Advisor" in table.get_text() and "Academic Advisor" in table.get_text():
            for td in table.find_all("td"):
                strong = td.find("strong")
                if not strong:
                    continue

                parts = strong.get_text("\n", strip=True).split("\n")
                if len(parts) < 2:
                    continue

                name, role = parts[0], parts[1]
                fonts = td.find_all("font")

                email = fonts[0].get_text(strip=True) if len(fonts) >= 1 else ""
                phone = fonts[1].get_text(strip=True) if len(fonts) >= 2 else ""

                if "Faculty Advisor" in role:
                    data["advisors"]["faculty_advisor"] = {
                        "name": name,
                        "email": email,
                        "phone": phone,
                    }

                elif "Academic Advisor" in role:
                    data["advisors"]["academic_advisor"] = {
                        "name": name,
                        "email": email,
                        "phone": phone,
                    }

    # ---------- TOTAL CREDITS ----------
    seen = set()
    for c in data["courses"]:
        if c["course_code"] not in seen:
            seen.add(c["course_code"])
            data["total_credits"] += c["credit"]

    return data
