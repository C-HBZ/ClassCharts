#!/usr/bin/env python3
"""
classcharts_test.py — ClassCharts Timetable Diagnostic & Test Script

Tries two independent methods to fetch timetable data:
  1. Parent API  — uses CLASSCHARTS_EMAIL + CLASSCHARTS_PASSWORD
  2. Student API — uses per-pupil CODE + DOB (no parent account needed)

Credentials are read from environment variables (Codespaces Secrets):
  CLASSCHARTS_EMAIL      Parent account e-mail
  CLASSCHARTS_PASSWORD   Parent account password
  CHILD1_DOB             First child's date of birth  (DD/MM/YYYY or YYYY-MM-DD)
  CHILD1_CODE            First child's student access code
  CHILD2_DOB             Second child's date of birth  (DD/MM/YYYY or YYYY-MM-DD)
  CHILD2_CODE            Second child's student access code

Authentication change (late April 2026)
---------------------------------------
ClassCharts migrated from a JSON-response API login endpoint to a web-form
login flow:

  OLD: POST /apiv2parent/login  →  JSON { meta: { session_id } }
  NEW: POST /parent/login       →  302 redirect
                                   Set-Cookie: parent_session_credentials=<JSON>

The session_id is now extracted from that JSON cookie, not from the response
body. Subsequent API requests (/apiv2parent/*) still use:
  Authorization: Basic {session_id}
… exactly as before, PLUS the auth cookies from the login response.

The student flow changed the same way:
  OLD: POST /apiv2student/login  →  JSON { meta: { session_id } }
  NEW: POST /student/login       →  302 redirect
                                    Set-Cookie: student_session_credentials=<JSON>
"""

import os
import sys
import json
import datetime
import urllib.parse

try:
    import requests
except ImportError:
    print("ERROR: 'requests' is not installed.  Run:  pip install requests")
    sys.exit(1)

# ── API base URLs ────────────────────────────────────────────────────────────
BASE_URL     = "https://www.classcharts.com"
PARENT_BASE  = f"{BASE_URL}/apiv2parent"
STUDENT_BASE = f"{BASE_URL}/apiv2student"

# ── Headers that mimic a real browser (Chrome 124 / Windows 10) ─────────────
BROWSER_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept":          "application/json, text/plain, */*",
    "Accept-Language": "en-GB,en-US;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Origin":          BASE_URL,
    "Referer":         f"{BASE_URL}/",
    "X-Requested-With": "XMLHttpRequest",
    "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    "Sec-Ch-Ua-Mobile":   "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
}


# ════════════════════════════════════════════════════════════════════════════
#  Utility helpers
# ════════════════════════════════════════════════════════════════════════════

def print_section(title: str) -> None:
    print(f"\n{'─' * 62}")
    print(f"  {title}")
    print(f"{'─' * 62}")


def safe_json(resp: requests.Response) -> dict | None:
    """
    Parse a response as JSON. Returns None and prints a warning if the
    response is HTML (Cloudflare challenge, login redirect, etc.).
    """
    text = resp.text.strip()
    if text.startswith("<!") or text.lower().startswith("<html"):
        print("  ⚠  Got HTML back (possible CDN challenge or redirect).")
        print(f"     First 300 chars: {text[:300]}")
        return None
    try:
        return resp.json()
    except ValueError as exc:
        print(f"  ⚠  Could not parse JSON: {exc}")
        print(f"     Body snippet: {text[:300]}")
        return None


def extract_session_from_cookie(
    response: requests.Response,
    cookie_name: str,
) -> str | None:
    """
    The new ClassCharts auth flow (post-April 2026) returns a 302 redirect.
    The session_id is inside a JSON-encoded cookie, e.g.:
      Set-Cookie: parent_session_credentials=%7B%22session_id%22%3A%22abc…%22%7D

    This helper finds that cookie in the response (or in the session's cookie
    jar if redirects were followed) and extracts the session_id.
    """
    # Try the response's own Set-Cookie header first (if allow_redirects=False)
    raw = response.cookies.get(cookie_name)
    if raw:
        try:
            data = json.loads(urllib.parse.unquote(raw))
            return data.get("session_id")
        except (ValueError, AttributeError):
            pass

    # Fall back: check Set-Cookie header directly (some redirect chains drop
    # the cookie into the jar with URL-encoding already stripped)
    for header_val in response.headers.get("set-cookie", "").split(","):
        if cookie_name in header_val:
            for part in header_val.split(";"):
                part = part.strip()
                if part.startswith(cookie_name + "="):
                    raw2 = part[len(cookie_name) + 1:]
                    try:
                        data2 = json.loads(urllib.parse.unquote(raw2))
                        sid = data2.get("session_id")
                        if sid:
                            return sid
                    except (ValueError, AttributeError):
                        pass
    return None


def print_lessons(lessons: list, max_show: int = 15) -> None:
    if not lessons:
        print("    (no lessons returned for this date range)")
        return
    print(f"    {len(lessons)} lesson(s) found:")
    for lesson in lessons[:max_show]:
        dt      = lesson["start"][:16].replace("T", " ")
        subject = lesson["subject"][:35].ljust(35)
        room    = lesson["room"] or "—"
        print(f"    {dt}  {subject}  {room}")
    if len(lessons) > max_show:
        print(f"    … and {len(lessons) - max_show} more")


# ════════════════════════════════════════════════════════════════════════════
#  Parent API  (new flow: POST /parent/login → 302 → cookie)
# ════════════════════════════════════════════════════════════════════════════

def login_parent(
    email: str,
    password: str,
) -> tuple[str | None, list[dict], requests.Session]:
    """
    Log in as a parent using the new web-form flow (post-April 2026).

    Flow:
      1. GET /parent/login to collect the cc-session cookie
      2. POST /parent/login with credentials → 302 redirect
      3. Parse parent_session_credentials cookie (JSON) → session_id
      4. GET /apiv2parent/pupils with Authorization: Basic {session_id}

    Returns (session_id, pupils, http_session) on success,
            (None, [], http_session) on failure.
    """
    session = requests.Session()
    session.headers.update(BROWSER_HEADERS)

    print(f"  [1/3] GET {BASE_URL}/parent/login  (collect cookies) …")
    try:
        pre = session.get(f"{BASE_URL}/parent/login", timeout=15)
        print(f"        HTTP {pre.status_code} | "
              f"cookies: {list(session.cookies.keys()) or 'none'}")
    except requests.RequestException as exc:
        print(f"        WARNING: pre-fetch failed: {exc}")

    print(f"  [2/3] POST {BASE_URL}/parent/login  (credentials) …")
    payload = {
        "_method":        "POST",
        "email":          email,
        "logintype":      "existing",
        "password":       password,
        "recaptcha-token": "no-token-available",
    }
    try:
        resp = session.post(
            f"{BASE_URL}/parent/login",
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            allow_redirects=False,   # We need to capture the 302 cookies
            timeout=15,
        )
    except requests.RequestException as exc:
        print(f"  ✗  Request error: {exc}")
        return None, [], session

    print(f"        HTTP {resp.status_code}")

    if resp.status_code not in (302, 200):
        print(f"  ✗  Unexpected status {resp.status_code}.")
        print(f"     Body: {resp.text[:300]}")
        return None, [], session

    # Extract session_id from the JSON cookie
    session_id = extract_session_from_cookie(resp, "parent_session_credentials")

    # If allow_redirects=False missed it, check if the session jar has it
    if not session_id:
        raw = session.cookies.get("parent_session_credentials")
        if raw:
            try:
                session_id = json.loads(urllib.parse.unquote(raw)).get("session_id")
            except (ValueError, AttributeError):
                pass

    if not session_id:
        print(f"  ✗  No parent_session_credentials cookie found.")
        print(f"     Set-Cookie: {resp.headers.get('set-cookie', '(none)')[:300]}")
        print(f"     Jar: {dict(session.cookies)}")
        # Check if ClassCharts returned JSON (old-style response still active)
        if resp.text.strip().startswith("{"):
            body = safe_json(resp)
            if body and body.get("meta", {}).get("session_id"):
                session_id = body["meta"]["session_id"]
                print(f"  ℹ  Fell back to JSON body session_id (old endpoint still alive)")
        if not session_id:
            return None, [], session

    print(f"  ✓  session_id = {session_id[:8]}…")

    # Store auth cookies for subsequent requests
    # (requests.Session already has them; we also pass them explicitly)
    session.headers.update({"Authorization": f"Basic {session_id}"})

    print(f"  [3/3] GET {PARENT_BASE}/pupils …")
    try:
        pr = session.get(f"{PARENT_BASE}/pupils", timeout=15)
    except requests.RequestException as exc:
        print(f"  ✗  Pupils request error: {exc}")
        return session_id, [], session

    print(f"        HTTP {pr.status_code}")
    pb = safe_json(pr)
    if pb is None:
        return session_id, [], session

    pupils: list[dict] = []
    for s in (pb.get("data") or []):
        first = (s.get("first_name") or "").strip()
        last  = (s.get("last_name")  or "").strip()
        name  = f"{first} {last}".strip() or s.get("name", "Unknown")
        pupils.append({"name": name, "student_id": str(s["id"])})

    print(f"  ✓  Pupils: {[p['name'] for p in pupils]}")
    return session_id, pupils, session


def get_timetable_parent(
    http_session: requests.Session,
    student_id: str,
    from_date: str,
    to_date: str,
) -> list[dict]:
    url = (
        f"{PARENT_BASE}/timetable/{student_id}"
        f"?from={from_date}&to={to_date}"
    )
    try:
        resp = http_session.get(url, timeout=15)
    except requests.RequestException as exc:
        print(f"    ✗  Request error: {exc}")
        return []

    print(f"    HTTP {resp.status_code}")
    body = safe_json(resp)
    if body is None:
        return []
    if body.get("success") != 1:
        print(f"    ✗  API error: {json.dumps(body)[:300]}")
        return []

    return _parse_timetable(body.get("data", {}))


# ════════════════════════════════════════════════════════════════════════════
#  Student API  (new flow: POST /student/login → 302 → cookie)
# ════════════════════════════════════════════════════════════════════════════

def _to_dd_mm_yyyy(dob: str) -> str:
    """Convert YYYY-MM-DD → DD/MM/YYYY. Passes DD/MM/YYYY through unchanged."""
    parts = dob.split("-")
    if len(parts) == 3 and len(parts[0]) == 4:
        return f"{parts[2]}/{parts[1]}/{parts[0]}"
    return dob


def login_student(
    code: str,
    dob: str,
) -> tuple[str | None, int | None, requests.Session]:
    """
    Log in as a student using the new web-form flow (post-April 2026).

    Flow:
      1. POST /student/login → 302 redirect
      2. Parse student_session_credentials cookie (JSON) → session_id
      3. POST /apiv2student/ping → refreshed session_id + student info
      4. GET /apiv2student/getStudentInfo → student numeric ID

    Returns (session_id, student_id, http_session) on success,
            (None, None, http_session) on failure.

    Note: student code must be uppercase; dob in DD/MM/YYYY format.
    """
    session = requests.Session()
    session.headers.update(BROWSER_HEADERS)

    dob_fmt = _to_dd_mm_yyyy(dob)
    code_uc = code.strip().upper()

    payload = {
        "_method":         "POST",
        "code":            code_uc,
        "dob":             dob_fmt,
        "remember_me":     "1",
        "recaptcha-token": "no-token-available",
    }

    print(f"  POST {BASE_URL}/student/login  "
          f"(code={code_uc[:4]}…, dob={dob_fmt})")
    try:
        resp = session.post(
            f"{BASE_URL}/student/login",
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            allow_redirects=False,
            timeout=15,
        )
    except requests.RequestException as exc:
        print(f"  ✗  Request error: {exc}")
        return None, None, session

    print(f"  HTTP {resp.status_code}")

    if resp.status_code not in (302, 200):
        print(f"  ✗  Unexpected status {resp.status_code}")
        print(f"     Body: {resp.text[:300]}")
        return None, None, session

    session_id = extract_session_from_cookie(resp, "student_session_credentials")

    if not session_id:
        raw = session.cookies.get("student_session_credentials")
        if raw:
            try:
                session_id = json.loads(urllib.parse.unquote(raw)).get("session_id")
            except (ValueError, AttributeError):
                pass

    if not session_id:
        print(f"  ✗  No student_session_credentials cookie found.")
        print(f"     Set-Cookie: {resp.headers.get('set-cookie', '(none)')[:400]}")
        print(f"     Jar: {dict(session.cookies)}")
        # Fallback: old JSON response
        if resp.text.strip().startswith("{"):
            body = safe_json(resp)
            if body and (body.get("meta") or {}).get("session_id"):
                session_id = body["meta"]["session_id"]
                print(f"  ℹ  Fell back to JSON body session_id")
        if not session_id:
            return None, None, session

    print(f"  ✓  session_id = {session_id[:8]}…")
    session.headers.update({"Authorization": f"Basic {session_id}"})

    # Ping refreshes the session_id AND returns user info including student ID.
    print(f"  POST {STUDENT_BASE}/ping  (refresh session + get student info) …")
    try:
        ping_resp = session.post(
            f"{STUDENT_BASE}/ping",
            data={"include_data": "true"},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=15,
        )
        print(f"  HTTP {ping_resp.status_code}")
        ping_body = safe_json(ping_resp)
        if ping_body:
            if (ping_body.get("meta") or {}).get("session_id"):
                session_id = ping_body["meta"]["session_id"]
                session.headers.update({"Authorization": f"Basic {session_id}"})
                print(f"  ✓  Refreshed session_id = {session_id[:8]}…")

            # student numeric ID is in data.user.id
            uid = ((ping_body.get("data") or {}).get("user") or {}).get("id")
            if uid:
                student_numeric_id = int(uid)
                print(f"  ✓  student numeric id = {student_numeric_id}")
    except requests.RequestException as exc:
        print(f"  ⚠  Ping failed: {exc}")

    return session_id, student_numeric_id, session


def get_timetable_student(
    http_session: requests.Session,
    student_id: int | str,
    from_date: str,
    to_date: str,
) -> list[dict]:
    url = (
        f"{STUDENT_BASE}/timetable/{student_id}"
        f"?from={from_date}&to={to_date}"
    )
    try:
        resp = http_session.get(url, timeout=15)
    except requests.RequestException as exc:
        print(f"    ✗  Request error: {exc}")
        return []

    print(f"    HTTP {resp.status_code}")
    body = safe_json(resp)
    if body is None:
        return []
    if body.get("success") != 1:
        print(f"    ✗  API error: {json.dumps(body)[:300]}")
        return []

    return _parse_timetable(body.get("data", {}))


# ════════════════════════════════════════════════════════════════════════════
#  Timetable parsing  (mirrors the logic in the original GAS script)
# ════════════════════════════════════════════════════════════════════════════

def _parse_timetable(raw) -> list[dict]:
    lessons: list[dict] = []
    if isinstance(raw, list):
        for item in raw:
            parsed = _parse_lesson(item)
            if parsed:
                lessons.append(parsed)
    elif isinstance(raw, dict):
        for _date_key, day_lessons in raw.items():
            if isinstance(day_lessons, list):
                for item in day_lessons:
                    parsed = _parse_lesson(item)
                    if parsed:
                        lessons.append(parsed)
    return sorted(lessons, key=lambda l: l["start"])


def _parse_lesson(lesson: dict) -> dict | None:
    start_str = (
        lesson.get("start_time") or
        lesson.get("start")      or
        lesson.get("from")
    )
    end_str = (
        lesson.get("end_time") or
        lesson.get("end")      or
        lesson.get("to")
    )
    date_str = lesson.get("date") or lesson.get("lesson_date")

    if not start_str or not end_str:
        return None

    try:
        s = str(start_str).strip()
        e = str(end_str).strip()
        # API now returns ISO 8601 with tz offset: "2026-05-05T09:00:00+01:00"
        # Also handle legacy formats: bare "HH:MM:SS" or "YYYY-MM-DD HH:MM:SS"
        s = s.replace(" ", "T")
        e = e.replace(" ", "T")
        if "T" in s:
            start = datetime.datetime.fromisoformat(s)
            end   = datetime.datetime.fromisoformat(e)
        elif date_str:
            start = datetime.datetime.fromisoformat(f"{date_str}T{s}")
            end   = datetime.datetime.fromisoformat(f"{date_str}T{e}")
        else:
            return None
    except (ValueError, TypeError):
        return None

    return {
        "subject": (
            lesson.get("subject_name") or
            lesson.get("lesson_name")  or
            lesson.get("subject")      or "Unknown"
        ),
        "room": (
            lesson.get("room_name") or
            lesson.get("room")      or
            lesson.get("location")  or ""
        ),
        "teacher": (
            lesson.get("teacher_name") or
            lesson.get("teacher")       or ""
        ),
        "period_name": (
            lesson.get("period_name") or
            lesson.get("period")       or ""
        ),
        "start": start.isoformat(),
        "end":   end.isoformat(),
    }


# ════════════════════════════════════════════════════════════════════════════
#  Main
# ════════════════════════════════════════════════════════════════════════════

def main() -> None:
    from_date = datetime.date.today().isoformat()
    to_date   = (datetime.date.today() + datetime.timedelta(days=14)).isoformat()

    print(f"\n{'═' * 62}")
    print(f"  ClassCharts Timetable Test  —  {datetime.date.today()}")
    print(f"  Date range : {from_date}  →  {to_date}")
    print(f"{'═' * 62}")

    # ── Method 1: Parent API ─────────────────────────────────────────────────
    print_section("Method 1: Parent API  (new /parent/login web-form flow)")

    email    = os.environ.get("CLASSCHARTS_EMAIL")
    password = os.environ.get("CLASSCHARTS_PASSWORD")

    if email and password:
        session_id, pupils, http_sess = login_parent(email, password)

        if session_id and pupils:
            for pupil in pupils:
                print(f"\n  ── Timetable: {pupil['name']} ──────────────────")
                lessons = get_timetable_parent(
                    http_sess, pupil["student_id"], from_date, to_date,
                )
                print_lessons(lessons)
        elif session_id:
            print("\n  ⚠  Got a session token but no pupils were returned.")
        else:
            print("\n  ✗  Parent login failed.")
            print("     If you see 'Email address or password provided is incorrect',")
            print("     your browser may be using a saved password that differs from")
            print("     the CLASSCHARTS_PASSWORD secret.  To verify:")
            print("     1. Open classcharts.com/parent/login in a private/incognito window")
            print("     2. Type the password manually (don't auto-fill)")
            print("     3. If that fails, reset your password and update the secret.")
    else:
        print("  Skipped — CLASSCHARTS_EMAIL or CLASSCHARTS_PASSWORD not set.")

    # ── Method 2: Student API ────────────────────────────────────────────────
    print_section("Method 2: Student API  (new /student/login web-form flow)")

    students = [
        ("Austin",
         os.environ.get("AUSTIN_CODE"),
         os.environ.get("AUSTIN_DOB")),
        ("Lewis",
         os.environ.get("LEWIS_CODE"),
         os.environ.get("LEWIS_DOB")),
    ]

    any_attempted = False
    for name, code, dob in students:
        missing = [
            var for var, val in
            [(f"{name.upper()}_CODE", code),
             (f"{name.upper()}_DOB",  dob)]
            if not val
        ]
        if missing:
            print(f"\n  {name}: skipped — missing env var(s): {', '.join(missing)}")
            continue

        any_attempted = True
        print(f"\n  ── Student: {name} ─────────────────────────────────")
        session_id, student_id, http_sess = login_student(code, dob)  # type: ignore[arg-type]
        if not session_id:
            print(f"  ✗  Login failed for {name}.")
            continue

        # Use ID from ping; fall back to env var secret
        if not student_id:
            env_id = os.environ.get(f"{name.upper()}_ID")
            if env_id:
                student_id = int(env_id)
                print(f"  ℹ  Using {name.upper()}_ID secret: {student_id}")

        if student_id:
            print(f"  Fetching timetable (student id {student_id}) …")
            lessons = get_timetable_student(
                http_sess, student_id, from_date, to_date,
            )
            print_lessons(lessons)
        else:
            print(f"  ⚠  Could not determine student numeric ID for {name}.")

    if not any_attempted:
        print("\n  Skipped — no student credentials found in environment.")

    # ── Diagnostics note ────────────────────────────────────────────────────
    print_section("Diagnostics")
    print("""
  The ClassCharts authentication flow changed in late April 2026:

  OLD (broken):
    POST /apiv2parent/login  →  JSON { meta: { session_id } }

  NEW (this script):
    POST /parent/login       →  302 redirect
    Set-Cookie: parent_session_credentials=<URL-encoded JSON>
    Parse JSON cookie → session_id
    All subsequent API calls: Authorization: Basic {session_id}

  Student flow changed the same way:
    POST /student/login  →  302 → student_session_credentials cookie

  If you're still seeing failures above, check:
  • Bad 302 / unexpected status  →  wrong credentials in Codespaces secrets
  • No cookie found              →  ClassCharts changed the cookie name again
  • 401 on timetable             →  session expired; re-run the script
""")
    print(f"{'═' * 62}")
    print("  Done.")
    print(f"{'═' * 62}\n")


if __name__ == "__main__":
    main()
