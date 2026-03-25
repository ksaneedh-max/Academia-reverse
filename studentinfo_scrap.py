import requests
import json
import re
from typing import Dict, Optional, Any
import time
import random

# importing parser utility functions
from utils.parser import *
# login error handler
from tools.handle_login_error_codes import handle_login_response


class AcademiaClient:
    """Client for interacting with SRM Academia portal"""

    BASE_URL = "https://academia.srmist.edu.in"

    def __init__(self, email: str, password: str):
        """
        Initialize the Academia client

        Args:
            email: User email address
            password: User password
        """
        self.email = email
        self.password = password
        self.session = requests.Session()
        self.identifier = None
        self.digest = None
        self.csrf_token = None
        self.last_error = None
        self._setup_session()

    def _setup_session(self):
        """Set up session with base cookies and fresh tokens"""
        print("[DEBUG] Starting session setup...")
        USER_AGENTS = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        ]

        print("[DEBUG] Setting up headers and cookies...")
        self.session.headers.update({
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Cache-Control": "max-age=0",
        })

        current_time = int(time.time())

        initial_cookies = {
            "_uetvid": "b3000840e89c11ef8036e75565fa990c",
            "zalb_74c3a1eecc": "62cd2f9337f58b07cdaa2f90f0ac1087",
            "zccpn": "da3eb9d9-c3f1-418c-a4a7-30a74a3aec85",
            "_zcsr_tmp": "da3eb9d9-c3f1-418c-a4a7-30a74a3aec85",
            "cli_rgn": "IN",
            "zalb_f0e8db9d3d": "983d6a65b2f29022f18db52385bfc639",
            "_ga": f"GA1.3.390342211.{current_time - 86400}",
            "_gid": f"GA1.3.{random.randint(1000000000, 9999999999)}.{current_time}",
            "_ga_S234BK01XY": f"GS1.3.{current_time}.1.0.{current_time}.60.0.0",
            "_ga_QNCRQG0GFE": f"GS2.1.s{current_time}$o13$g1$t{current_time + 271}$j58$l0$h0",
            "_ga_HQWPLLNMKY": f"GS2.3.s{current_time}$o23$g0$t{current_time}$j60$l0$h0",
        }

        self.session.cookies.update(initial_cookies)
        print("[DEBUG] Initial cookies setup completed")

        # Add slight delay to simulate human behavior
        time.sleep(random.uniform(0.5, 1.5))

        print("[DEBUG] Attempting to fetch login page for CSRF token...")
        try:
            login_page_url = f"{self.BASE_URL}/accounts/p/10002227248/signin"
            params = {
                "hide_fp": "true",
                "orgtype": "40",
                "service_language": "en",
                "css_url": "/49910842/academia-academic-services/downloadPortalCustomCss/login",
                "dcc": "true",
                "serviceurl": f"{self.BASE_URL}/portal/academia-academic-services/redirectFromLogin",
            }

            response = self.session.get(login_page_url, params=params, timeout=15)
            print(f"[DEBUG] Login page response status: {response.status_code}")
            response.raise_for_status()

            if "iamcsr" in self.session.cookies:
                self.csrf_token = self.session.cookies.get("iamcsr")
                print("✓ CSRF Token obtained")
            else:
                print("⚠ Warning: No CSRF token found in cookies")

            if "JSESSIONID" in self.session.cookies:
                print("✓ Session ID obtained")
            else:
                print("[DEBUG] JSESSIONID not found in cookies")

        except Exception as e:
            print(f"⚠ Warning: Failed to initialize session: {str(e)}")
            print(f"[DEBUG] Exception type: {type(e).__name__}")
            print(f"[DEBUG] Exception details: {repr(e)}")

    def _activate_portal_mode(self):
        """
        Switch session headers to the same style the portal requests use
        after login.
        """
        self.session.headers.update({
            "X-Requested-With": "XMLHttpRequest",
            "Referer": f"{self.BASE_URL}/",
            "Origin": self.BASE_URL,
            "Accept": "*/*",
        })

    def _looks_like_login_page(self, text: str) -> bool:
        """Detect the login shell instead of the actual portal page."""
        if not text:
            return True
        lower = text.lower()
        return (
            "academic web services login" in lower
            or "<title>academia - academic web services login</title>" in lower
            or "signin" in lower and "passwordauth" in lower
        )

    def _get_common_headers(self) -> Dict[str, str]:
        """Get common headers for requests"""
        headers = {
            "Accept": "*/*",
            "Accept-Encoding": "gzip, deflate, br",
            "Accept-Language": "en-US,en;q=0.9,en-IN;q=0.8",
            "Connection": "keep-alive",
            "Origin": self.BASE_URL,
            "Referer": f"{self.BASE_URL}/accounts/p/10002227248/signin",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
            "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
        }

        if self.csrf_token:
            headers["X-ZCSRF-TOKEN"] = f"iamcsrcoo={self.csrf_token}"

        return headers

    def lookup_user(self) -> bool:
        """Perform user lookup to get identifier and digest"""
        print("Step 1: Performing user lookup...")

        url = f"{self.BASE_URL}/accounts/p/40-10002227248/signin/v2/lookup/{self.email}"

        cli_time = str(int(time.time() * 1000))
        print(f"[DEBUG] CLI time: {cli_time}")

        data = {
            "mode": "primary",
            "cli_time": cli_time,
            "orgtype": "40",
            "service_language": "en",
            "serviceurl": f"{self.BASE_URL}/portal/academia-academic-services/redirectFromLogin",
        }

        try:
            print("[DEBUG] Sending POST request for user lookup...")
            response = self.session.post(url, headers=self._get_common_headers(), data=data, timeout=15)
            response.raise_for_status()

            lookup_data = response.json()
            self.identifier = lookup_data.get("lookup", {}).get("identifier")
            self.digest = lookup_data.get("lookup", {}).get("digest")

            if self.identifier and self.digest:
                print("✓ Lookup successful")
                print("✓ Digest obtained\n")
                return True
            else:
                print("✗ Failed to get user identifier or digest\n")
                return False

        except json.JSONDecodeError:
            print("✗ Lookup failed: JSON parsing error")
            return False
        except Exception as e:
            print(f"✗ Lookup failed: {str(e)}")
            print(f"[DEBUG] Exception type: {type(e).__name__}")
            print(f"[DEBUG] Exception traceback: {repr(e)}")
            print()
            return False

    def _close_active_sessions(self, redirect_uri: str, service_url: str, service_language: str, orgtype: str) -> bool:
        """Close active sessions when prompted by the portal"""
        print("Step 2b: Closing active sessions...")

        try:
            response = self.session.get(redirect_uri, timeout=15)
            response.raise_for_status()
            print("✓ Visited sessions reminder page")
        except Exception as e:
            print(f"⚠ Warning: Failed to visit announcement page: {str(e)}")

        delete_url = f"{self.BASE_URL}/accounts/p/40-10002227248/webclient/v1/account/self/user/self/activesessions"

        headers = self._get_common_headers()
        headers["Referer"] = redirect_uri

        try:
            response = self.session.delete(delete_url, headers=headers, timeout=15)
            response.raise_for_status()
            print(f"✓ Active sessions deleted (Status: {response.status_code})")
        except Exception as e:
            print(f"⚠ Warning: Failed to delete sessions: {str(e)}")

        print("Step 2c: Confirming session closure...")
        next_url = f"{self.BASE_URL}/accounts/p/40-10002227248/announcement/sessions-reminder/next"
        next_params = {
            "status": "2",
            "serviceurl": service_url,
            "service_language": service_language,
            "orgtype": orgtype,
        }

        next_headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9,en-IN;q=0.8",
            "Connection": "keep-alive",
            "Referer": redirect_uri,
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        }

        try:
            response = self.session.get(next_url, params=next_params, headers=next_headers, timeout=15)
            response.raise_for_status()
            print(f"✓ Session closure confirmed (Status: {response.status_code})\n")
            return True

        except Exception as e:
            print(f"✗ Failed to confirm session closure: {str(e)}\n")
            return False

    def _close_blocked_sessions(self, redirect_uri: str) -> bool:
        """Close blocked sessions when prompted by the portal"""
        print("Step 2b: Closing blocked sessions...")

        try:
            response = self.session.get(redirect_uri, timeout=15)
            response.raise_for_status()
            print("✓ Visited blocked sessions page")
        except Exception as e:
            print(f"⚠ Warning: Failed to visit announcement page: {str(e)}")

        delete_url = f"{self.BASE_URL}/accounts/p/40-10002227248/webclient/v1/announcement/pre/blocksessions"

        headers = self._get_common_headers()
        headers["Referer"] = redirect_uri

        try:
            response = self.session.delete(delete_url, headers=headers, timeout=15)
            response.raise_for_status()
            print(f"✓ Blocked sessions deleted (Status: {response.status_code})\n")
            return True
        except Exception as e:
            print(f"✗ Failed to delete blocked sessions: {str(e)}\n")
            return False

    def login(self) -> dict:
        """Login with password using digest from lookup"""
        if not self.identifier or not self.digest:
            print("✗ No identifier/digest found. Run lookup_user() first.\n")
            return {
                "success": False,
                "message": "No identifier/digest found",
            }

        print("Step 2: Logging in...")

        url = f"{self.BASE_URL}/accounts/p/40-10002227248/signin/v2/primary/{self.identifier}/password"
        cli_time = str(int(time.time() * 1000))

        params = {
            "digest": self.digest,
            "cli_time": cli_time,
            "orgtype": "40",
            "service_language": "en",
            "serviceurl": f"{self.BASE_URL}/portal/academia-academic-services/redirectFromLogin",
        }

        body = json.dumps({
            "passwordauth": {
                "password": self.password
            }
        })

        headers = self._get_common_headers()
        headers["Content-Type"] = "application/json;charset=UTF-8"

        try:
            response = self.session.post(url, headers=headers, params=params, data=body, timeout=15)
            response.raise_for_status()

            if response.status_code == 200:
                login_data = response.json()

                handled = handle_login_response(login_data)
                if handled.get("success") is False:
                    self.last_error = handled.get("message")
                    print(f"✗ Login failed: {self.last_error}\n")
                    return {
                        "success": False,
                        "message": handled.get("message"),
                        "type": handled.get("type"),
                        "code": handled.get("code"),
                        "raw": handled.get("raw"),
                    }

                code = login_data.get("code")
                passwordauth = login_data.get("passwordauth", {})
                inner_code = passwordauth.get("code")

                if code in ["SI200", "SIGIN_SUCCESS"] or inner_code == "SIGIN_SUCCESS":
                    print("✓ Login successful!\n")
                    self._activate_portal_mode()
                    return {"success": True}

                elif (
                    code in ["POST_ANNOUCEMENT_REDIRECTION", "SI302", "SI303"]
                    or inner_code == "POST_ANNOUCEMENT_REDIRECTION"
                ):
                    print(f"✓ Login successful - handling redirect (code: {code})...")
                    redirect_uri = passwordauth.get("redirect_uri")

                    if redirect_uri:
                        is_block_sessions = "block-sessions" in redirect_uri

                        service_url = params.get("serviceurl")
                        service_language = params.get("service_language")
                        orgtype = params.get("orgtype")

                        if is_block_sessions:
                            success = self._close_blocked_sessions(redirect_uri)
                        else:
                            success = self._close_active_sessions(
                                redirect_uri,
                                service_url,
                                service_language,
                                orgtype,
                            )

                        if success:
                            print("Step 2d: Completing login flow...")

                            redirect_headers = {
                                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                                "Accept-Language": "en-US,en;q=0.9,en-IN;q=0.8",
                                "Connection": "keep-alive",
                                "Referer": redirect_uri,
                                "Sec-Fetch-Dest": "document",
                                "Sec-Fetch-Mode": "navigate",
                                "Sec-Fetch-Site": "same-origin",
                                "Sec-Fetch-User": "?1",
                                "Upgrade-Insecure-Requests": "1",
                                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                            }

                            try:
                                final_response = self.session.get(
                                    service_url,
                                    headers=redirect_headers,
                                    timeout=15,
                                )

                                if final_response.status_code == 200:
                                    print("✓ Login flow completed successfully!\n")

                                    # 🔥 CRITICAL FIX — ACTIVATE PORTAL SESSION
                                    print("[DEBUG] Activating FULL portal session...")

                                    # STEP 1 — REQUIRED (do not remove)
                                    self.session.get(
                                        self.BASE_URL + "/portal/academia-academic-services/redirectFromLogin"
                                    )

                                    # STEP 2 — LIGHT fallback check (safe)
                                    test_resp = self.session.get(
                                        self.BASE_URL + "/srm_university/academia-academic-services"
                                    )

                                    # Retry only if session not active
                                    if self._looks_like_login_page(test_resp.text):
                                        print("[DEBUG] Session not active, retrying activation...")
                                        self.session.get(
                                            self.BASE_URL + "/portal/academia-academic-services/redirectFromLogin"
                                        )

                                    self._activate_portal_mode()
                                    return {"success": True}
                                else:
                                    print(f"⚠ Warning: Unusual status code: {final_response.status_code}")
                                    self._activate_portal_mode()
                                    return {"success": True}

                            except Exception as e:
                                print(f"⚠ Warning: Final redirect failed: {str(e)}")
                                self._activate_portal_mode()
                                return {"success": True}

                        else:
                            print("✗ Failed to close sessions\n")
                            return {"success": False}

                    else:
                        print("✗ No redirect_uri found in response\n")
                        return {"success": False}

                elif "error" in login_data:
                    error_msg = login_data.get("error", {}).get("message", "Unknown error")
                    self.last_error = error_msg
                    print(f"✗ Login failed: {error_msg}\n")
                    return {
                        "success": False,
                        "message": error_msg,
                    }

                else:
                    print(f"⚠ Unexpected response code: {code}")
                    print(f"Response: {json.dumps(login_data, indent=2)}\n")
                    return {
                        "success": False,
                        "message": "Unexpected login response",
                        "raw": login_data,
                    }

            else:
                print(f"✗ Login failed with status code: {response.status_code}\n")
                return {
                    "success": False,
                    "message": f"HTTP {response.status_code}",
                }

        except Exception as e:
            print(f"✗ Login failed: {str(e)}\n")
            return {
                "success": False,
                "message": str(e),
            }

    def logout(self) -> bool:
        """Logout from the academia portal"""
        print("Logging out...")

        url = f"{self.BASE_URL}/accounts/p/10002227248/logout"
        params = {
            "servicename": "ZohoCreator",
            "serviceurl": self.BASE_URL,
        }

        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9,en-IN;q=0.8",
            "Connection": "keep-alive",
            "Referer": f"{self.BASE_URL}/",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        }

        try:
            response = self.session.get(url, headers=headers, params=params, timeout=15)
            if response.status_code in [200, 302, 303]:
                print("✓ Logout successful!\n")
                self.session.cookies.clear()
                self.identifier = None
                self.digest = None
                self.csrf_token = None
                return True
            else:
                print(f"✗ Logout failed with status: {response.status_code}\n")
                return False

        except Exception as e:
            print(f"✗ Logout failed: {str(e)}\n")
            return False

    def _get_page_headers(self, referer: Optional[str] = None) -> Dict[str, str]:
        """Get headers for page requests"""
        headers = {
            "Accept": "*/*",
            "Accept-Encoding": "gzip, deflate, br",
            "Accept-Language": "en-US,en;q=0.9,en-IN;q=0.8",
            "Connection": "keep-alive",
            "Referer": referer or f"{self.BASE_URL}/",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
            "X-Requested-With": "XMLHttpRequest",
        }

        if self.csrf_token:
            headers["X-ZCSRF-TOKEN"] = f"iamcsrcoo={self.csrf_token}"

        return headers

    def get_attendance(self) -> Optional[Dict[str, Any]]:
        """Fetch and parse attendance data"""
        print("Fetching attendance data...")
        # 🔥 CRITICAL FIX — ensure session is active before API call
        print("[DEBUG] Ensuring portal session active...")
        # removed unnecessary keepalive call

        url = f"{self.BASE_URL}/srm_university/academia-academic-services/page/My_Attendance"

        try:
            response = self.session.get(
                url,
                headers=self._get_page_headers(referer=f"{self.BASE_URL}/"),
                timeout=15,
            )
            response.raise_for_status()

            print(f"✓ Attendance data retrieved (Status: {response.status_code})")
            print(f"[DEBUG] Attendance response length: {len(response.text)}")
            print(f"[DEBUG] Attendance response preview: {response.text[:250]}\n")

            if self._looks_like_login_page(response.text):
                print("✗ Attendance request returned login page instead of portal HTML\n")
                self.last_error = "login_page"
                return None

            parsed = parse_attendance(response.text)
            return parsed

        except Exception as e:
            print(f"✗ Failed to fetch attendance: {str(e)}\n")
            return None

    def get_timetable(self) -> Optional[Dict[str, Any]]:
        """Fetch and parse timetable data"""
        print("Fetching timetable data...")

        url = f"{self.BASE_URL}/srm_university/academia-academic-services/page/My_Time_Table_2023_24"

        try:
            response = self.session.get(
                url,
                headers=self._get_page_headers(referer=f"{self.BASE_URL}/"),
                timeout=15,
            )
            response.raise_for_status()

            print(f"✓ Timetable data retrieved (Status: {response.status_code})")
            print(f"[DEBUG] Timetable response length: {len(response.text)}")
            print(f"[DEBUG] Timetable response preview: {response.text[:250]}\n")

            if self._looks_like_login_page(response.text):
                print("✗ Timetable request returned login page instead of portal HTML\n")
                self.last_error = "login_page"
                return None

            parsed = parse_timetable(response.text)
            return parsed

        except Exception as e:
            print(f"✗ Failed to fetch timetable: {str(e)}\n")
            return None

    def get_day_order(self) -> Optional[int]:
        """Fetch current day order from welcome page"""
        print("Fetching day order...")

        url = f"{self.BASE_URL}/srm_university/academia-academic-services/page/WELCOME"

        try:
            response = self.session.get(
                url,
                headers=self._get_page_headers(referer=f"{self.BASE_URL}/"),
                timeout=15,
            )
            response.raise_for_status()

            text = response.text

            if self._looks_like_login_page(text):
                print("✗ Day order request returned login page instead of portal HTML\n")
                self.last_error = "login_page"
                return None

            patterns = [
                r"Day\\x20Order\\x3A(\d+)",
                r"Day\s*Order\s*[:\-]?\s*(\d+)",
                r"Day Order\s*[:\-]?\s*(\d+)",
            ]

            for pattern in patterns:
                match = re.search(pattern, text)
                if match:
                    day_order = int(match.group(1))
                    print(f"✓ Day Order retrieved: {day_order}\n")
                    return day_order

            print("✗ Could not find day order in response\n")
            print(f"[DEBUG] Day order preview: {text[:250]}\n")
            return None

        except Exception as e:
            print(f"✗ Failed to fetch day order: {str(e)}\n")
            return None

    def get_session_data(self) -> dict:
        """Export session data for reuse"""
        return {
            "cookies": self.session.cookies.get_dict(),
            "identifier": self.identifier,
            "digest": self.digest,
            "csrf_token": self.csrf_token,
        }

    def load_session_data(self, session_data: dict) -> None:
        """Load previously saved session data"""
        if session_data.get("cookies"):
            self.session.cookies.update(session_data["cookies"])
        self.identifier = session_data.get("identifier")
        self.digest = session_data.get("digest")
        self.csrf_token = session_data.get("csrf_token")


def main():
    """Main execution function"""

    EMAIL = "as0711@srmist.edu.in"
    PASSWORD = "pass"

    client = AcademiaClient(EMAIL, PASSWORD)

    try:
        if not client.lookup_user():
            return
        print("succesfully completed lookup")

        result_login = client.login()
        if not result_login["success"]:
            print("error msg:", result_login["message"])
            return

        day_order = client.get_day_order()

        attendance_data = client.get_attendance()
        if attendance_data and day_order is not None:
            attendance_data["day_order"] = day_order

        if attendance_data:
            print("\n" + "=" * 50)
            print("✓ Attendance data retrieved successfully")
            print("=" * 50)

        timetable_data = client.get_timetable()
        if timetable_data:
            print("\n" + "=" * 50)
            print("✓ Timetable data retrieved successfully")
            print("=" * 50)

    finally:
        client.logout()


if __name__ == "__main__":
    main()
