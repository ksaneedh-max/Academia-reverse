from typing import Dict, Any
from concurrent.futures import ThreadPoolExecutor


def _parallel_fetch(client):
    """Fetch day_order, attendance, timetable in parallel (FAST)"""
    with ThreadPoolExecutor(max_workers=3) as executor:
        future_day = executor.submit(client.get_day_order)
        future_att = executor.submit(client.get_attendance)
        future_tt = executor.submit(client.get_timetable)

        day_order = future_day.result()
        attendance_data = future_att.result()
        timetable_data = future_tt.result()

    return day_order, attendance_data, timetable_data


def fetch_all_data_with_retry(client, max_retries: int = 2, save_debug_html: bool = False) -> Dict[str, Any]:
    """
    Optimized fetch with parallel execution + smart retry.
    """

    for attempt in range(max_retries):
        if attempt > 0:
            print(f"\n{'='*60}")
            print(f"[RETRY] Attempt {attempt + 1}/{max_retries}")
            print("="*60)

            # ⚡ LIGHT refresh first (no full login)
            try:
                print("[RETRY] Light session refresh...")
                client._setup_session(skip_login_page=True)
            except Exception as e:
                print(f"[RETRY] Light refresh failed: {e}")

        try:
            # 🚀 PARALLEL FETCH
            print("[DATA] Fetching all data in parallel...")
            day_order, attendance_data, timetable_data = _parallel_fetch(client)

            # --- DAY ORDER ---
            if day_order is not None:
                print(f"✓ [DATA] Day order retrieved: {day_order}")
            else:
                print("⚠ [DATA] Day order not available")

            if not isinstance(day_order, int) or day_order <= 0:
                day_order = 4

            # --- VALIDATE PARSING ---
            attendance_failed = (
                isinstance(attendance_data, dict) and
                attendance_data.get('error') == "Could not parse HTML"
            )

            timetable_failed = (
                isinstance(timetable_data, dict) and
                timetable_data.get('error') == "Could not parse HTML"
            )

            if attendance_failed or timetable_failed:
                print("\n" + "⚠"*30)
                print("[PARSE ERROR] Detected!")
                if attendance_failed:
                    print("✗ Attendance parsing failed")
                if timetable_failed:
                    print("✗ Timetable parsing failed")
                print("⚠"*30 + "\n")

                # DEBUG SAVE (unchanged logic)
                if save_debug_html:
                    try:
                        import os
                        os.makedirs("debug_html", exist_ok=True)

                        if attendance_failed:
                            url = f'{client.BASE_URL}/srm_university/academia-academic-services/page/My_Attendance'
                            response = client.session.get(url, headers=client._get_page_headers())
                            with open(f"debug_html/attendance_failed_attempt_{attempt + 1}.html", "w", encoding="utf-8") as f:
                                f.write(response.text)

                        if timetable_failed:
                            url = f'{client.BASE_URL}/srm_university/academia-academic-services/page/My_Time_Table_2023_24'
                            response = client.session.get(url, headers=client._get_page_headers())
                            with open(f"debug_html/timetable_failed_attempt_{attempt + 1}.html", "w", encoding="utf-8") as f:
                                f.write(response.text)

                    except Exception as debug_error:
                        print(f"[DEBUG] Save failed: {debug_error}")

                # 🔥 SMART RETRY FLOW
                if attempt < max_retries - 1:
                    # Only last retry does full login
                    if attempt == max_retries - 2:
                        print("[RETRY] Performing FULL re-authentication...")

                        try:
                            client.session.cookies.clear()
                            client._setup_session()

                            if not client.lookup_user():
                                return {
                                    "success": False,
                                    "error": "Lookup failed during retry",
                                    "day_order": None,
                                    "attendance_data": None,
                                    "timetable_data": None
                                }

                            login_result = client.login()
                            if not login_result.get("success"):
                                return {
                                    "success": False,
                                    "error": login_result.get("message"),
                                    "day_order": None,
                                    "attendance_data": None,
                                    "timetable_data": None
                                }

                            print("✓ Full re-auth successful")

                        except Exception as e:
                            return {
                                "success": False,
                                "error": f"Re-auth failed: {str(e)}",
                                "day_order": None,
                                "attendance_data": None,
                                "timetable_data": None
                            }

                    continue
                else:
                    return {
                        "success": False,
                        "error": "Parse failures after retries",
                        "day_order": day_order,
                        "attendance_data": attendance_data,
                        "timetable_data": timetable_data
                    }

            # ✅ SUCCESS
            print("✓ [DATA] All data fetched successfully")
            return {
                "success": True,
                "day_order": day_order,
                "attendance_data": attendance_data,
                "timetable_data": timetable_data
            }

        except Exception as e:
            print(f"✗ Fetch error: {e}")
            if attempt == max_retries - 1:
                return {
                    "success": False,
                    "error": str(e),
                    "day_order": None,
                    "attendance_data": None,
                    "timetable_data": None
                }

    return {
        "success": False,
        "error": "Max retries exceeded",
        "day_order": None,
        "attendance_data": None,
        "timetable_data": None
    }
