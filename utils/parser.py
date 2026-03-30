import re
from typing import Dict, Optional, Any, List
from bs4 import BeautifulSoup


# ⚡ Precompiled regex (faster)
ATTENDANCE_REGEX = re.compile(
    r"innerHTML = pageSanitizer\.sanitize\('(.+?)'\);",
    re.DOTALL
)

HEX_REGEX = re.compile(r'\\x([0-9a-fA-F]{2})')

COURSE_CODE_REGEX = re.compile(r'^\d{2}[A-Z]{3}\d{3}[A-Z]$')


def _decode_html(escaped_html: str) -> str:
    """Fast JS string decoding"""
    html_decoded = (
        escaped_html
        .replace("\\'", "'")
        .replace('\\"', '"')
        .replace('\\/', '/')
        .replace('\\-', '-')
        .replace('\\n', '\n')
        .replace('\\t', '\t')
        .replace('\\r', '\r')
    )

    return HEX_REGEX.sub(lambda m: chr(int(m.group(1), 16)), html_decoded)


def parse_attendance(html_content: str) -> Dict[str, Any]:
    """Parse attendance HTML to structured JSON"""

    match = ATTENDANCE_REGEX.search(html_content)
    if not match:
        return {"error": "Could not parse HTML"}

    html_decoded = _decode_html(match.group(1))
    soup = BeautifulSoup(html_decoded, 'html.parser')

    data = {
        "student_info": {},
        "attendance": {
            "courses": {},
            "overall_attendance": 0.0,
            "total_hours_conducted": 0,
            "total_hours_absent": 0
        },
        "marks": {},
        "summary": {}
    }

    # --- STUDENT INFO ---
    for row in soup.find_all('tr'):
        cells = row.find_all('td')
        if len(cells) < 2:
            continue

        key_text = cells[0].get_text(strip=True).replace(':', '')
        value_text = cells[1].get_text(strip=True)

        if key_text == 'Registration Number':
            data['student_info']['registration_number'] = value_text
        elif key_text == 'Name':
            data['student_info']['name'] = value_text
        elif key_text == 'Program':
            data['student_info']['program'] = value_text
        elif key_text == 'Department':
            data['student_info']['department'] = value_text
        elif key_text == 'Specialization':
            data['student_info']['specialization'] = value_text
        elif key_text == 'Semester':
            data['student_info']['semester'] = value_text
        elif key_text == 'Batch':
            data['student_info']['batch'] = value_text
        elif key_text == 'Feedback Status':
            data['student_info']['feedback_status'] = value_text
        elif key_text == 'Enrollment Status / DOE':
            parts = value_text.split(' / ')
            if len(parts) == 2:
                data['student_info']['enrollment_status'] = parts[0]
                data['student_info']['enrollment_date'] = parts[1]
        elif key_text == 'Photo-ID':
            img_tag = cells[1].find('img')
            if img_tag and img_tag.get('src'):
                data['student_info']['photo_url'] = img_tag.get('src')

    # --- ATTENDANCE TABLE ---
    attendance_table = soup.find('table', {'bgcolor': '#FAFAD2'})
    if attendance_table:
        total_conducted = 0
        total_absent = 0

        for row in attendance_table.find_all('tr')[1:]:
            cells = row.find_all('td')
            if len(cells) < 9:
                continue

            course_code_parts = cells[0].get_text(strip=True).split('\n')
            course_code = course_code_parts[0]

            category = cells[2].get_text(strip=True)
            course_key = course_code + category

            hours_conducted = int(cells[6].get_text(strip=True))
            hours_absent = int(cells[7].get_text(strip=True))

            total_conducted += hours_conducted
            total_absent += hours_absent

            percent_text = cells[8].get_text(strip=True)
            attendance_percent = float(percent_text) if percent_text.replace('.', '').isdigit() else 0.0

            data['attendance']['courses'][course_key] = {
                'course_title': cells[1].get_text(strip=True),
                'category': category,
                'faculty_name': cells[3].get_text(strip=True),
                'slot': cells[4].get_text(strip=True),
                'room_no': cells[5].get_text(strip=True),
                'hours_conducted': hours_conducted,
                'hours_absent': hours_absent,
                'attendance_percentage': attendance_percent
            }

        if total_conducted > 0:
            data['attendance']['overall_attendance'] = round(
                ((total_conducted - total_absent) / total_conducted) * 100, 2
            )

        data['attendance']['total_hours_conducted'] = total_conducted
        data['attendance']['total_hours_absent'] = total_absent

    # --- MARKS ---
    for table in soup.find_all('table', {'border': '1'}):
        text = table.get_text()
        if 'Course Code' not in text or 'Test Performance' not in text:
            continue

        for row in table.find_all('tr')[1:]:
            cells = row.find_all('td')
            if len(cells) < 3:
                continue

            course_code = cells[0].get_text(strip=True)
            course_type = cells[1].get_text(strip=True)

            if not COURSE_CODE_REGEX.match(course_code):
                continue

            if course_type not in ['Theory', 'Practical']:
                continue

            marks_key = course_code + course_type
            tests = []

            inner_table = cells[2].find('table')
            if inner_table:
                for inner_row in inner_table.find_all('tr'):
                    for inner_cell in inner_row.find_all('td'):
                        text = inner_cell.get_text(separator='\n', strip=True)
                        lines = [l.strip() for l in text.split('\n') if l.strip()]

                        if len(lines) >= 2 and '/' in lines[0]:
                            test_name, max_marks = lines[0].split('/')
                            obtained = lines[1]

                            max_marks = float(max_marks) if max_marks.replace('.', '').isdigit() else 0.0
                            obtained = float(obtained) if obtained.replace('.', '').isdigit() else 0.0

                            tests.append({
                                'test_name': test_name,
                                'obtained_marks': obtained,
                                'max_marks': max_marks,
                                'percentage': round((obtained / max_marks) * 100, 2) if max_marks > 0 else 0.0
                            })

            data['marks'][marks_key] = {
                'course_type': course_type,
                'tests': tests
            }

    return data


# ---------------- TIMETABLE ----------------

def parse_timetable(html_content: str) -> Dict[str, Any]:
    """Parse timetable HTML"""

    match = ATTENDANCE_REGEX.search(html_content)
    if not match:
        return {"error": "Could not parse HTML"}

    html_decoded = _decode_html(match.group(1))
    soup = BeautifulSoup(html_decoded, 'html.parser')

    data = {
        "student_info": {
            "registration_number": "",
            "name": "",
            "batch": "",
            "mobile": "",
            "program": "",
            "department": "",
            "semester": ""
        },
        "courses": [],
        "advisors": {},
        "total_credits": 0
    }

    # --- STUDENT INFO ---
    for table in soup.find_all('table'):
        for row in table.find_all('tr'):
            cells = row.find_all('td')
            for i in range(0, len(cells)-1, 2):
                label = cells[i].get_text(strip=True).replace(':', '')
                value = re.sub(r'\s+', ' ', cells[i+1].get_text(separator=' ', strip=True))

                if 'Registration Number' in label:
                    data['student_info']['registration_number'] = value
                elif label == 'Name':
                    data['student_info']['name'] = value
                elif 'Batch' in label:
                    data['student_info']['batch'] = value.split("/")[-1].strip()
                elif label == 'Mobile':
                    data['student_info']['mobile'] = value
                elif label == 'Program':
                    data['student_info']['program'] = value
                elif 'Department' in label:
                    data['student_info']['department'] = value
                elif label == 'Semester':
                    data['student_info']['semester'] = value

    # --- COURSES ---
    COURSE_PATTERN = re.compile(
        r'<td>(\d+)</td><td>([^<]+)</td><td>([^<]+)</td><td>(\d+)</td>'
        r'<td>([^<]+)</td><td>([^<]+)</td><td>([^<]+)</td><td>([^<]+)</td>'
        r'<td[^>]*>([^<]+)</td><td>([^<]*)</td><td>([^<]+)</td>'
    )

    unique_courses = set()

    for match in COURSE_PATTERN.findall(html_decoded):
        try:
            s_no, code, title, credit, regn, category, ctype, faculty, slot, room, year = match

            credit_val = int(credit) if credit.isdigit() else 0

            data['courses'].append({
                's_no': s_no,
                'course_code': code.strip(),
                'course_title': title.strip(),
                'credit': credit_val,
                'regn_type': regn.strip(),
                'category': category.strip(),
                'course_type': ctype.strip(),
                'faculty_name': faculty.strip(),
                'slot': slot.strip(),
                'room_no': room.strip(),
                'academic_year': year.strip()
            })

            if code not in unique_courses:
                data['total_credits'] += credit_val
                unique_courses.add(code)

        except Exception:
            continue

    # --- ADVISORS ---
    for table in soup.find_all('table'):
        for cell in table.find_all('td', {'align': 'center'}):
            lines = [l.strip() for l in cell.get_text(separator='\n', strip=True).split('\n') if l.strip()]

            if any('Faculty Advisor' in l for l in lines):
                idx = next((i for i, l in enumerate(lines) if 'Faculty Advisor' in l), -1)
                if idx > 0:
                    data['advisors']['faculty_advisor'] = {
                        'name': lines[idx - 1],
                        'email': next((l for l in lines if '@srmist.edu.in' in l), ''),
                        'phone': next((l for l in lines if l.replace('-', '').isdigit()), '')
                    }

            elif any('Academic Advisor' in l for l in lines):
                idx = next((i for i, l in enumerate(lines) if 'Academic Advisor' in l), -1)
                if idx > 0:
                    data['advisors']['academic_advisor'] = {
                        'name': lines[idx - 1],
                        'email': next((l for l in lines if '@srmist.edu.in' in l), ''),
                        'phone': next((l for l in lines if l.replace('-', '').isdigit()), '')
                    }

    return data
