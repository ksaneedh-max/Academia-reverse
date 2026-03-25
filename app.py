from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from studentinfo_scrap import AcademiaClient
from tools.fallback_mock_attendance_data import generate_mock_attendance_from_timetable
from tools.studentportal_result import scrape_student_portal
from tools.retry_fetch_failed_login import fetch_all_data_with_retry
from typing import Optional, Union
import time


app = FastAPI(title="Academia Scraper API")

origins = [
    "http://localhost",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "*",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =========================
# MODELS (BACKWARD COMPATIBLE)
# =========================
class SessionData(BaseModel):
    cookies: Optional[dict] = {}
    identifier: Optional[str] = None
    digest: Optional[str] = None
    csrf_token: Optional[str] = None


class LoginRequest(BaseModel):
    email: str
    password: str
    session_data: Optional[Union[SessionData, dict]] = None


class StudentPortalRequest(BaseModel):
    netid: str
    password: str


# =========================
# VALIDATION
# =========================
def is_valid_attendance(data):
    try:
        return (
            isinstance(data, dict)
            and data.get("attendance")
            and data["attendance"].get("courses")
            and len(data["attendance"]["courses"]) > 0
        )
    except:
        return False


# =========================
# MAIN SCRAPE ENDPOINT
# =========================
@app.post("/scrape")
async def scrape_portal(request: LoginRequest):

    client = None
    session_authenticated = False
    session_reused = False

    try:
        client = AcademiaClient(request.email, request.password)

        print("\n" + "="*60)
        print("[SESSION] Starting session handling...")
        print("="*60)

        # =========================
        # NORMALIZE SESSION DATA
        # =========================
        session_dict = None

        if isinstance(request.session_data, dict):
            session_dict = request.session_data

        elif isinstance(request.session_data, SessionData):
            session_dict = request.session_data.dict()

        # =========================
        # VALID SESSION CHECK
        # =========================
        valid_session = (
            session_dict
            and session_dict.get("cookies")
            and session_dict.get("identifier")
            and session_dict.get("digest")
        )

        if valid_session:
            print("[SESSION] Attempting session reuse...")

            client.load_session_data(session_dict)

            try:
                print("[SESSION] Validating session with retry...")

                test_response = None

                for i in range(3):
                    test_response = client.get_attendance()

                    if is_valid_attendance(test_response):
                        print(f"✓ Valid session (attempt {i+1})")
                        session_authenticated = True
                        session_reused = True
                        break

                    print(f"⚠ Attempt {i+1} failed, retrying...")
                    time.sleep(1.5)

                if not session_authenticated:
                    print("❌ Session invalid → clearing cookies")
                    client.session.cookies.clear()
                    client._setup_session()

            except Exception as e:
                print(f"⚠ Session validation error: {str(e)}")
                client.session.cookies.clear()
                client._setup_session()

        else:
            print("[SESSION] No valid session → fresh login")

        # =========================
        # LOGIN
        # =========================
        if not session_authenticated:
            print("\n[LOGIN] Performing fresh login...")

            result_lookup = client.lookup_user()
            result_login = client.login()

            if not result_lookup or not result_login["success"]:
                raise HTTPException(
                    status_code=401,
                    detail=result_login.get("message", "Login failed")
                )

            print("✓ Login successful")

            time.sleep(1.5)  # increased delay for SRM

        # =========================
        # FETCH DATA (WITH RETRY)
        # =========================
        print("[DATA] Fetching attendance...")

        attendance_data = None

        for i in range(3):
            attendance_data = client.get_attendance()

            if is_valid_attendance(attendance_data):
                print(f"✓ Attendance fetched (attempt {i+1})")
                break

            print(f"⚠ Attendance attempt {i+1} failed")
            time.sleep(1.5)

        print("[DATA] Fetching timetable...")
        timetable_data = client.get_timetable()

        print("[DATA] Fetching day order...")
        day_order = client.get_day_order()

        if not isinstance(day_order, int) or day_order <= 0:
            day_order = 3

        # =========================
        # FALLBACK
        # =========================
        if (
            not attendance_data
            or not is_valid_attendance(attendance_data)
        ):
            if timetable_data and "error" not in timetable_data:
                print("[FALLBACK] Generating mock attendance...")
                attendance_data = generate_mock_attendance_from_timetable(timetable_data)
            else:
                print("⚠ No valid attendance or timetable")

        if not attendance_data:
            attendance_data = {}

        attendance_data["day_order"] = day_order

        # =========================
        # SESSION EXPORT (CLEAN)
        # =========================
        session_data = client.get_session_data()

        if isinstance(session_data, dict):
            session_data.pop("additionalProp1", None)

        print("\n" + "="*60)
        print(f"[SESSION] Response ready - {'REUSED' if session_reused else 'NEW'} session")
        print("="*60 + "\n")

        return {
            "status": "success",
            "attendance": attendance_data,
            "timetable": timetable_data,
            "session_data": session_data,
            "session_info": {
                "session_reused": session_reused,
                "session_type": "existing" if session_reused else "new"
            }
        }

    except HTTPException:
        raise

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =========================
# STUDENT PORTAL
# =========================
@app.post("/studentportal_result")
async def scrape_student_portal_endpoint(request: StudentPortalRequest):
    try:
        result = scrape_student_portal(request.netid, request.password)

        if result.get("status") == "error":
            raise HTTPException(status_code=500, detail=result.get("message"))

        return result

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =========================
# LOGOUT
# =========================
@app.post("/logout")
async def logout_session(request: LoginRequest):
    try:
        client = AcademiaClient(request.email, request.password)

        session_dict = None
        if isinstance(request.session_data, dict):
            session_dict = request.session_data
        elif isinstance(request.session_data, SessionData):
            session_dict = request.session_data.dict()

        if session_dict:
            client.load_session_data(session_dict)

        if client.logout():
            return {"status": "success", "message": "Logged out successfully"}

        raise HTTPException(status_code=500, detail="Logout failed")

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =========================
# HEALTH
# =========================
@app.get("/health")
async def health_check():
    return {"status": "ok"}


@app.head("/health")
async def health_head():
    return Response(status_code=200)


@app.head("/")
async def root_head():
    return Response(status_code=200)
