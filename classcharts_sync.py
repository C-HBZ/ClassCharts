#!/usr/bin/env python3
"""
classcharts_sync.py  —  ClassCharts → Google Calendar Sync

Runs four sync passes in sequence each time it is invoked:

  1. TIMETABLE   Fingerprint-based sync of each pupil's lessons into their
                 own named Google Calendar (Austin_School / Lewis_School).
                 Subject → colour mapping mirrors the original GAS script.
                 Stale events (no longer in ClassCharts) are deleted; new
                 ones are created; unchanged ones are left alone.

  2. NO SCHOOL   Marks any Mon–Fri inside the sync window that has zero
                 lessons for ALL pupils with an all-day "No School" event
                 in the parent's default calendar.  Previously created
                 markers are cleaned up first.

  3. PE / ENRICHMENT
                 Creates timed events in the parent's default calendar for
                 any lesson matching a watched keyword (PE, Enrichment).
                 Cleans up stale entries tagged by this script first.

  4. HOMEWORK    Creates a 09:00–10:00 event on the due date for each
                 outstanding homework item, in the parent's default calendar.
                 Austin events are coloured Blueberry; Lewis events Grape.
                 Already-synced items (identified by extended-property tag)
                 are never duplicated.

Authentication
--------------
ClassCharts:
  CLASSCHARTS_EMAIL        parent account e-mail    (Codespaces secret)
  CLASSCHARTS_PASSWORD     parent account password  (Codespaces secret)

Google Calendar (service-account):
  GOOGLE_SERVICE_ACCOUNT_JSON   full contents of the key JSON file
                                (Codespaces secret)

  The service account must be granted "Make changes to events" on:
    • Austin_School
    • Lewis_School
    • the parent's primary/default calendar

Usage
-----
  python3 classcharts_sync.py            # live run
  python3 classcharts_sync.py --dry-run  # prints planned changes, no writes
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
import time
import urllib.parse
from zoneinfo import ZoneInfo

try:
    from dotenv import load_dotenv
    load_dotenv()          # loads .env from the same directory as this script
except ImportError:
    pass                   # dotenv not installed — fall back to system env vars

try:
    import requests
except ImportError:
    sys.exit("ERROR: pip install requests")

try:
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
except ImportError:
    sys.exit("ERROR: pip install google-api-python-client google-auth")

# ════════════════════════════════════════════════════════════════════════════
#  CONFIGURATION  —  edit this section if your setup changes
# ════════════════════════════════════════════════════════════════════════════

SYNC_DAYS = 28          # how many days ahead to sync
TIMEZONE  = "Europe/London"

# ────────────────────────────────────────────────────────────────────────────
# NOTE: Pupils are now auto-discovered from the ClassCharts API at runtime.
# There is no need to hardcode pupil names in this file.
#
# Each pupil's display name is derived from their first name in ClassCharts,
# and each is automatically matched to their Google Calendar ID (via
# GCAL_ID_AUSTIN, GCAL_ID_LEWIS, etc., in a case-insensitive mapping).
# ────────────────────────────────────────────────────────────────────────────

# PE / Enrichment watched keywords (case-insensitive whole-word match)
WATCHED_SUBJECTS: list[dict] = [
    {"keyword": "pe",         "label": "PE"},
    {"keyword": "enrichment", "label": "Enrichment"},
]

# Google Calendar colorId for homework events.
# REST API colorIds: 1=Lavender 2=Sage 3=Grape 4=Flamingo 5=Banana
#                   6=Tangerine 7=Peacock 8=Graphite 9=Blueberry 10=Basil 11=Tomato
#
# Map is by pupil first name (lowercase). If a pupil is not listed here,
# homework events will not be coloured.
HOMEWORK_COLOUR: dict[str, str] = {
    "austin": "9",   # Blueberry
    "lewis":  "3",   # Grape
}

# Subject → Google Calendar colorId mapping (mirrors original GAS colour rules)
# Match is case-insensitive substring on the subject name.
SUBJECT_COLOUR_RULES: list[dict] = [
    # Languages
    {"keywords": ["english"],                                    "colorId": "5"},  # Banana
    {"keywords": ["welsh"],                                      "colorId": "5"},
    {"keywords": ["german"],                                     "colorId": "5"},
    {"keywords": ["french"],                                     "colorId": "5"},
    # Mathematics
    {"keywords": ["maths", "math"],                             "colorId": "9"},  # Blueberry
    # Sciences
    {"keywords": ["biology", "chemistry", "physics", "science"],"colorId": "7"},  # Peacock
    # Humanities
    {"keywords": ["geography", "history", "religious", "r.e."], "colorId": "6"},  # Tangerine
    # Creative & Performing Arts
    {"keywords": ["art", "music", "drama", "textiles"],          "colorId": "2"},  # Sage
    # Technology / D&T / Computing
    {"keywords": ["design tech", "des. tech", "design & tech",
                  "design and tech", "computing", "technology"], "colorId": "8"},  # Graphite
    # PE / Health / Wellbeing / Enrichment
    {"keywords": ["p.e.", " pe ", "pe:", "physical education",
                  "health", "wellbeing", "enrichment"],          "colorId": "3"},  # Grape
]

# Delays between API calls to avoid rate-limit triggers
CC_SLEEP_S   = 0.5    # between ClassCharts requests
GCal_SLEEP_S = 0.35   # between Google Calendar write operations

# ════════════════════════════════════════════════════════════════════════════
#  Extended-property tag keys  (replace GAS event.setTag)
# ════════════════════════════════════════════════════════════════════════════
TAG_TIMETABLE   = "cc_timetable"        # value "true" on timetable events
TAG_FINGERPRINT = "cc_fingerprint"      # fingerprint string
TAG_NO_SCHOOL   = "cc_no_school_marker" # value "true" on No School events
TAG_PE_ENR      = "cc_pe_enrichment"    # value "true" on PE/Enrichment events
TAG_HOMEWORK    = "cc_homework"         # value "true" on homework events
TAG_HW_ID       = "cc_hw_id"           # ClassCharts homework id for dedup
TAG_HW_HASH     = "cc_hw_hash"         # content hash — detects title/date/subject changes
TAG_PE_FP       = "cc_pe_fp"           # fingerprint on PE/Enrichment events

# ════════════════════════════════════════════════════════════════════════════
#  ClassCharts helpers
# ════════════════════════════════════════════════════════════════════════════

_CC_BASE   = "https://www.classcharts.com"
_CC_PARENT = f"{_CC_BASE}/apiv2parent"

_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


def cc_login() -> tuple[requests.Session, list[dict]]:
    """
    Log in to ClassCharts as a parent using the new web-form flow
    (POST /parent/login → 302 → parent_session_credentials cookie).

    Returns (http_session, pupils_list).
    pupils_list entries: {name, first_name, last_name, id}
    """
    email    = os.environ["CLASSCHARTS_EMAIL"]
    password = os.environ["CLASSCHARTS_PASSWORD"]

    s = requests.Session()
    s.headers.update({"User-Agent": _BROWSER_UA})

    # Collect the initial session cookie
    s.get(f"{_CC_BASE}/parent/login", timeout=15)
    time.sleep(CC_SLEEP_S)

    resp = s.post(
        f"{_CC_BASE}/parent/login",
        data={
            "_method":         "POST",
            "email":           email,
            "logintype":       "existing",
            "password":        password,
            "recaptcha-token": "no-token-available",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        allow_redirects=False,
        timeout=15,
    )
    if resp.status_code not in (302, 200):
        raise RuntimeError(f"ClassCharts login: unexpected HTTP {resp.status_code}")

    raw = resp.cookies.get("parent_session_credentials")
    if not raw:
        raise RuntimeError("ClassCharts login: parent_session_credentials cookie not found")

    sid = json.loads(urllib.parse.unquote(raw))["session_id"]
    s.headers.update({"Authorization": f"Basic {sid}"})
    time.sleep(CC_SLEEP_S)

    pupils_resp = s.get(f"{_CC_PARENT}/pupils", timeout=15)
    if pupils_resp.status_code != 200:
        raise RuntimeError(f"ClassCharts pupils: HTTP {pupils_resp.status_code}")

    pupils_raw = pupils_resp.json().get("data", [])
    pupils = []
    for p in pupils_raw:
        first = (p.get("first_name") or "").strip()
        last  = (p.get("last_name")  or "").strip()
        pupils.append({
            "name":       f"{first} {last}".strip() or p.get("name", "Unknown"),
            "first_name": first,
            "last_name":  last,
            "id":         p["id"],
        })

    return s, pupils


def cc_get_timetable(
    cc: requests.Session,
    student_id: int,
    from_date: str,
    to_date: str,
) -> list[dict]:
    """
    Fetch and parse a pupil's timetable.
    Returns a list of lesson dicts:
      {subject, room, teacher, period_name, start (datetime), end (datetime), date (str)}
    """
    time.sleep(CC_SLEEP_S)
    resp = cc.get(
        f"{_CC_PARENT}/timetable/{student_id}?from={from_date}&to={to_date}",
        timeout=15,
    )
    if resp.status_code != 200:
        print(f"  ⚠  timetable HTTP {resp.status_code} for student {student_id}")
        return []

    body = resp.json()
    if body.get("success") != 1:
        print(f"  ⚠  timetable API error for student {student_id}: {body}")
        return []

    raw = body.get("data", [])
    lessons: list[dict] = []
    items = raw if isinstance(raw, list) else [
        lesson
        for day in raw.values() if isinstance(day, list)
        for lesson in day
    ]
    for item in items:
        parsed = _parse_lesson(item)
        if parsed:
            lessons.append(parsed)
    return sorted(lessons, key=lambda l: l["start"])


def cc_get_homework(
    cc: requests.Session,
    student_id: int,
    from_date: str,
    to_date: str,
) -> list[dict]:
    """
    Fetch outstanding homework items due in [from_date, to_date].
    Returns list of {id, subject, title, due_date (str YYYY-MM-DD)}.
    """
    time.sleep(CC_SLEEP_S)
    resp = cc.get(
        f"{_CC_PARENT}/homeworks/{student_id}"
        f"?display_date=due_date&from={from_date}&to={to_date}",
        timeout=15,
    )
    if resp.status_code != 200:
        print(f"  ⚠  homework HTTP {resp.status_code} for student {student_id}")
        return []

    body = resp.json()
    if body.get("success") != 1:
        print(f"  ⚠  homework API error for student {student_id}: {body}")
        return []

    today = datetime.date.today()
    hw_list = []
    for hw in body.get("data", []):
        due_raw = hw.get("due_date") or hw.get("due") or hw.get("deadline")
        if not due_raw:
            continue
        due_str = str(due_raw)[:10]
        try:
            due = datetime.date.fromisoformat(due_str)
        except ValueError:
            continue
        if due < today:
            continue
        # subject can be None if the school didn't attach a lesson
        subject = hw.get("subject") or hw.get("lesson") or "Form"
        hw_list.append({
            "id":       hw.get("id", ""),
            "subject":  subject,
            "title":    hw.get("title")   or hw.get("meta_title") or "No title",
            "due_date": due_str,
        })

    hw_list.sort(key=lambda h: h["due_date"])
    return hw_list


def _parse_lesson(item: dict) -> dict | None:
    start_str = item.get("start_time") or item.get("start") or item.get("from")
    end_str   = item.get("end_time")   or item.get("end")   or item.get("to")
    date_str  = item.get("date")       or item.get("lesson_date")
    if not start_str or not end_str:
        return None
    try:
        s = str(start_str).strip().replace(" ", "T")
        e = str(end_str).strip().replace(" ", "T")
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
        "subject":     (item.get("subject_name") or item.get("lesson_name") or item.get("subject") or "Unknown"),
        "room":        (item.get("room_name")    or item.get("room")        or item.get("location") or ""),
        "teacher":     (item.get("teacher_name") or item.get("teacher")    or ""),
        "period_name": (item.get("period_name")  or item.get("period")     or ""),
        "start":       start,
        "end":         end,
        "date":        (date_str or start.date().isoformat()),
    }


# ════════════════════════════════════════════════════════════════════════════
#  Google Calendar helpers
# ════════════════════════════════════════════════════════════════════════════

_GCAL_SCOPES = ["https://www.googleapis.com/auth/calendar"]


def gcal_service():
    """Build and return an authenticated Google Calendar API service object."""
    sa_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not sa_json:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON secret not set")
    info = json.loads(sa_json)
    creds = service_account.Credentials.from_service_account_info(
        info, scopes=_GCAL_SCOPES
    )
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def gcal_get_calendar_ids() -> dict[str, str]:
    """
    Return a dict mapping all available calendar ID keys to their values.
    This includes 'parent' and all pupil calendars (e.g., 'austin', 'lewis').
    
    Reads from Codespaces secrets: GCAL_ID_PARENT, GCAL_ID_AUSTIN, GCAL_ID_LEWIS, etc.
    Returns whatever is set; only raises if GCAL_ID_PARENT is missing.
    """
    ids: dict[str, str] = {}
    
    # Parent calendar is required
    parent_id = os.environ.get("GCAL_ID_PARENT")
    if not parent_id:
        raise RuntimeError(
            f"Missing required Codespaces secret: GCAL_ID_PARENT\n"
            f"Add it via: GitHub repo → Settings → Secrets → Codespaces"
        )
    ids["parent"] = parent_id
    
    # Pupil calendars: scan for GCAL_ID_<FIRST_NAME> patterns
    # (e.g., GCAL_ID_AUSTIN, GCAL_ID_LEWIS)
    for env_var, value in os.environ.items():
        if env_var.startswith("GCAL_ID_") and env_var != "GCAL_ID_PARENT":
            first_name = env_var[8:].lower()  # strip "GCAL_ID_" prefix and lowercase
            if value:
                ids[first_name] = value
    
    return ids


def build_pupils_config(cc_pupils: list[dict], cal_ids: dict) -> list[dict]:
    """
    Build a PUPILS config dynamically from discovered ClassCharts pupils.
    
    Maps each pupil to their Google Calendar ID by matching first name
    against environment variable names (case-insensitive).
    For example, a pupil with first_name='Austin' looks for GCAL_ID_AUSTIN.
    
    Returns a list of pupil configs, filtered to only those with available
    Google Calendar IDs.
    """
    pupils_config = []
    
    for pupil in cc_pupils:
        first_name = pupil.get("first_name", "").strip()
        if not first_name:
            continue
        
        # Try to find a matching calendar ID by first name
        cal_key = first_name.lower()
        cal_id = cal_ids.get(cal_key)
        
        if not cal_id:
            # Calendar ID not configured for this pupil; skip them
            continue
        
        # Build config entry for this pupil
        # Use first_name as both the display name and the key for homework colours
        pupils_config.append({
            "name": pupil.get("name", "Unknown"),  # full name from ClassCharts
            "first_name": first_name,              # used for calendar lookup and homework colour
            "calendar_id": cal_id,                 # direct Google Calendar ID (not a name)
        })
    
    return pupils_config


def gcal_list_tagged_events(
    service,
    calendar_id: str,
    tag_key: str,
    tag_value: str,
    time_min: datetime.datetime,
    time_max: datetime.datetime,
) -> list[dict]:
    """Return all events in [time_min, time_max] that have a matching private extended property."""
    events = []
    page_token = None
    while True:
        result = service.events().list(
            calendarId=calendar_id,
            timeMin=time_min.isoformat(),
            timeMax=time_max.isoformat(),
            privateExtendedProperty=f"{tag_key}={tag_value}",
            singleEvents=True,
            maxResults=2500,
            pageToken=page_token,
        ).execute()
        events.extend(result.get("items", []))
        page_token = result.get("nextPageToken")
        if not page_token:
            break
    return events


def gcal_delete_event(service, calendar_id: str, event_id: str, dry_run: bool) -> None:
    if dry_run:
        print(f"    [DRY-RUN] DELETE event {event_id}")
        return
    try:
        service.events().delete(calendarId=calendar_id, eventId=event_id).execute()
    except HttpError as exc:
        print(f"    ⚠  Failed to delete event {event_id}: {exc}")
        return
    time.sleep(GCal_SLEEP_S)


def gcal_create_event(
    service,
    calendar_id: str,
    body: dict,
    dry_run: bool,
) -> None:
    if dry_run:
        summary = body.get("summary", "?")
        start   = body.get("start", {})
        print(f"    [DRY-RUN] CREATE  '{summary}'  {start}")
        return
    try:
        service.events().insert(calendarId=calendar_id, body=body).execute()
    except HttpError as exc:
        print(f"    ⚠  Failed to create event '{body.get('summary', '?')}': {exc}")
        return
    time.sleep(GCal_SLEEP_S)


def _dt_to_rfc3339(dt: datetime.datetime) -> str:
    """Return RFC 3339 string; add UTC offset if naive (assume Europe/London)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo(TIMEZONE))
    return dt.isoformat()


# ════════════════════════════════════════════════════════════════════════════
#  Colour resolution
# ════════════════════════════════════════════════════════════════════════════

def resolve_colour(subject: str) -> str | None:
    """Return a Google Calendar REST colorId string for the given subject name."""
    padded = f" {subject.lower()} "
    for rule in SUBJECT_COLOUR_RULES:
        for kw in rule["keywords"]:
            if kw.lower() in padded:
                return rule["colorId"]
    return None


# ════════════════════════════════════════════════════════════════════════════
#  Fingerprinting
# ════════════════════════════════════════════════════════════════════════════

def lesson_fingerprint(lesson: dict) -> str:
    return "|".join([
        _dt_to_rfc3339(lesson["start"]),
        _dt_to_rfc3339(lesson["end"]),
        lesson["subject"].strip(),
        lesson["room"].strip(),
        lesson["teacher"].strip(),
        lesson["period_name"].strip(),
    ])


# ════════════════════════════════════════════════════════════════════════════
#  Sync pass 1 — Timetable → Austin_School / Lewis_School
# ════════════════════════════════════════════════════════════════════════════

def sync_timetable(
    cc: requests.Session,
    cc_pupils_by_name: dict,
    service,
    pupils_config: list[dict],
    window_start: datetime.datetime,
    window_end: datetime.datetime,
    from_str: str,
    to_str: str,
    dry_run: bool,
) -> None:
    print("\n── PASS 1: Timetable ─────────────────────────────────────")
    for config in pupils_config:
        pupil = cc_pupils_by_name.get(config["name"].lower())
        if not pupil:
            print(f"  ⚠  Pupil '{config['name']}' not found in ClassCharts — skipping")
            continue

        cal_id = config["calendar_id"]

        print(f"\n  {config['name']} → timetable sync")

        # Step 1 — fetch existing tagged events
        existing = gcal_list_tagged_events(
            service, cal_id, TAG_TIMETABLE, "true", window_start, window_end
        )
        existing_by_fp: dict[str, str] = {}   # fingerprint → event_id
        for ev in existing:
            fp = (ev.get("extendedProperties") or {}).get("private", {}).get(TAG_FINGERPRINT)
            if fp:
                existing_by_fp[fp] = ev["id"]
        print(f"    Existing tagged events: {len(existing_by_fp)}")

        # Step 2 — fetch desired timetable from ClassCharts
        lessons = cc_get_timetable(cc, pupil["id"], from_str, to_str)
        print(f"    ClassCharts lessons:    {len(lessons)}")

        wanted: dict[str, dict] = {lesson_fingerprint(l): l for l in lessons}

        # Step 3 — delete stale
        deleted = 0
        for fp, ev_id in existing_by_fp.items():
            if fp not in wanted:
                gcal_delete_event(service, cal_id, ev_id, dry_run)
                deleted += 1

        # Step 4 — create missing
        created = unchanged = 0
        for fp, lesson in wanted.items():
            if fp in existing_by_fp:
                unchanged += 1
                continue

            colour = resolve_colour(lesson["subject"])
            desc_lines = [
                f"Subject:  {lesson['subject']}",
                f"Room:     {lesson['room']}"        if lesson["room"]        else None,
                f"Teacher:  {lesson['teacher']}"     if lesson["teacher"]     else None,
                f"Period:   {lesson['period_name']}" if lesson["period_name"] else None,
            ]
            body: dict = {
                "summary":   lesson["subject"],
                "start":     {"dateTime": _dt_to_rfc3339(lesson["start"]), "timeZone": TIMEZONE},
                "end":       {"dateTime": _dt_to_rfc3339(lesson["end"]),   "timeZone": TIMEZONE},
                "location":  lesson["room"] or None,
                "description": "\n".join(l for l in desc_lines if l),
                "extendedProperties": {"private": {TAG_TIMETABLE: "true", TAG_FINGERPRINT: fp}},
            }
            if colour:
                body["colorId"] = colour

            gcal_create_event(service, cal_id, body, dry_run)
            created += 1

        print(f"    Created {created} | Deleted {deleted} | Unchanged {unchanged}")


# ════════════════════════════════════════════════════════════════════════════
#  Sync pass 2 — No School days → parent default calendar
# ════════════════════════════════════════════════════════════════════════════

def sync_no_school(
    cc: requests.Session,
    cc_pupils_by_name: dict,
    service,
    parent_cal_id: str,
    pupils_config: list[dict],
    window_start: datetime.datetime,
    window_end: datetime.datetime,
    from_str: str,
    to_str: str,
    dry_run: bool,
) -> None:
    print("\n── PASS 2: No School days ────────────────────────────────")

    # Collect all dates that have at least one lesson for any pupil
    school_dates: set[str] = set()
    for config in pupils_config:
        pupil = cc_pupils_by_name.get(config["name"].lower())
        if not pupil:
            continue
        lessons = cc_get_timetable(cc, pupil["id"], from_str, to_str)
        for l in lessons:
            school_dates.add(l["date"])

    print(f"  School dates found (any pupil): {len(school_dates)}")

    # Delete existing No School markers in window
    existing = gcal_list_tagged_events(
        service, parent_cal_id, TAG_NO_SCHOOL, "true", window_start, window_end
    )
    for ev in existing:
        gcal_delete_event(service, parent_cal_id, ev["id"], dry_run)
    if existing:
        print(f"  Removed {len(existing)} stale 'No School' marker(s)")

    # Create new No School markers for weekdays with no lessons
    created = 0
    start_date = window_start.date()
    for i in range(SYNC_DAYS):
        day = start_date + datetime.timedelta(days=i)
        if day.weekday() >= 5:          # skip Sat/Sun
            continue
        if day.isoformat() in school_dates:
            continue                    # there are lessons → school is on

        body = {
            "summary": "No School",
            "start":   {"date": day.isoformat()},
            "end":     {"date": (day + datetime.timedelta(days=1)).isoformat()},
            "colorId": "7",             # Peacock (cyan)
            "extendedProperties": {"private": {TAG_NO_SCHOOL: "true"}},
        }
        gcal_create_event(service, parent_cal_id, body, dry_run)
        created += 1
        if not dry_run:
            print(f"    No School: {day.strftime('%A %-d %B %Y')}")
        else:
            print(f"    [DRY-RUN] No School: {day.strftime('%A %-d %B %Y')}")

    print(f"  Created {created} 'No School' event(s)")


# ════════════════════════════════════════════════════════════════════════════
#  Sync pass 3 — PE & Enrichment → parent default calendar
# ════════════════════════════════════════════════════════════════════════════

def _subject_matches_watched(subject: str) -> dict | None:
    """Return the matching WATCHED_SUBJECTS entry, or None."""
    padded = f" {subject.lower()} "
    for watch in WATCHED_SUBJECTS:
        kw = watch["keyword"].lower()
        if padded.strip() == kw or f" {kw} " in padded:
            return watch
    return None


def sync_pe_enrichment(
    cc: requests.Session,
    cc_pupils_by_name: dict,
    service,
    parent_cal_id: str,
    pupils_config: list[dict],
    window_start: datetime.datetime,
    window_end: datetime.datetime,
    from_str: str,
    to_str: str,
    dry_run: bool,
) -> None:
    print("\n── PASS 3: PE & Enrichment ───────────────────────────────")

    # Fetch existing tagged PE/Enrichment events and build fingerprint lookup
    existing = gcal_list_tagged_events(
        service, parent_cal_id, TAG_PE_ENR, "true", window_start, window_end
    )
    existing_by_fp: dict[str, str] = {}  # fingerprint → event_id
    for ev in existing:
        fp = (ev.get("extendedProperties") or {}).get("private", {}).get(TAG_PE_FP)
        if fp:
            existing_by_fp[fp] = ev["id"]

    # Build the full set of wanted PE/Enrichment events
    wanted: dict[str, dict] = {}  # fingerprint → event body
    for config in pupils_config:
        pupil = cc_pupils_by_name.get(config["name"].lower())
        if not pupil:
            continue

        lessons = cc_get_timetable(cc, pupil["id"], from_str, to_str)
        for lesson in lessons:
            match = _subject_matches_watched(lesson["subject"])
            if not match:
                continue

            fp    = f"{config['first_name']}|{_dt_to_rfc3339(lesson['start'])}"
            title = f"{config['first_name']}: {match['label']}"
            desc_lines = [
                f"Pupil:    {config['name']}",
                f"Subject:  {lesson['subject']}",
                f"Room:     {lesson['room']}"        if lesson["room"]        else None,
                f"Teacher:  {lesson['teacher']}"     if lesson["teacher"]     else None,
                f"Period:   {lesson['period_name']}" if lesson["period_name"] else None,
            ]
            body = {
                "summary":   title,
                "start":     {"dateTime": _dt_to_rfc3339(lesson["start"]), "timeZone": TIMEZONE},
                "end":       {"dateTime": _dt_to_rfc3339(lesson["end"]),   "timeZone": TIMEZONE},
                "location":  lesson["room"] or None,
                "description": "\n".join(l for l in desc_lines if l),
                "extendedProperties": {"private": {TAG_PE_ENR: "true", TAG_PE_FP: fp}},
            }
            wanted[fp] = body

    # Delete stale events no longer in ClassCharts
    deleted = 0
    for fp, ev_id in existing_by_fp.items():
        if fp not in wanted:
            gcal_delete_event(service, parent_cal_id, ev_id, dry_run)
            deleted += 1

    # Create new events not yet in Google Calendar
    created = unchanged = 0
    for fp, body in wanted.items():
        if fp in existing_by_fp:
            unchanged += 1
            continue
        gcal_create_event(service, parent_cal_id, body, dry_run)
        created += 1

    if deleted:
        print(f"  Removed {deleted} stale PE/Enrichment event(s)")
    print(f"  Created {created} | Unchanged {unchanged} | Deleted {deleted} PE/Enrichment event(s)")


# ════════════════════════════════════════════════════════════════════════════
#  Sync pass 4 — Homework → parent default calendar
# ════════════════════════════════════════════════════════════════════════════

def sync_homework(
    cc: requests.Session,
    cc_pupils_by_name: dict,
    service,
    parent_cal_id: str,
    pupils_config: list[dict],
    window_start: datetime.datetime,
    window_end: datetime.datetime,
    from_str: str,
    to_str: str,
    dry_run: bool,
) -> None:
    print("\n── PASS 4: Homework ──────────────────────────────────────")

    # Fetch all existing homework events; build lookup by cc_hw_id → (event_id, stored_hash)
    existing = gcal_list_tagged_events(
        service, parent_cal_id, TAG_HOMEWORK, "true", window_start, window_end
    )
    existing_by_hw_id: dict[str, tuple[str, str]] = {}
    for ev in existing:
        priv  = (ev.get("extendedProperties") or {}).get("private", {})
        hw_id = priv.get(TAG_HW_ID)
        if hw_id:
            existing_by_hw_id[hw_id] = (ev["id"], priv.get(TAG_HW_HASH, ""))
    print(f"  Existing homework events in window: {len(existing_by_hw_id)}")

    # Track every CC homework ID seen this run (for orphan cleanup at the end)
    cc_hw_ids_seen: set[str] = set()

    created = updated = skipped = 0
    tz = ZoneInfo(TIMEZONE)

    for config in pupils_config:
        pupil = cc_pupils_by_name.get(config["name"].lower())
        if not pupil:
            continue

        hw_list = cc_get_homework(cc, pupil["id"], from_str, to_str)
        colour  = HOMEWORK_COLOUR.get(config["first_name"].lower())

        for hw in hw_list:
            hw_id = str(hw["id"])
            cc_hw_ids_seen.add(hw_id)

            # Content hash covers every field that could change on an amendment
            hw_hash = f"{hw_id}|{hw['due_date']}|{hw['title']}|{hw['subject']}"

            due      = datetime.date.fromisoformat(hw["due_date"])
            start_dt = datetime.datetime(due.year, due.month, due.day, 9,  0, 0, tzinfo=tz)
            end_dt   = datetime.datetime(due.year, due.month, due.day, 10, 0, 0, tzinfo=tz)

            # Sanitise title: prevent injection of special characters into calendar
            raw_title  = f"{config['first_name']}: {hw['subject']}: {hw['title']}"
            safe_title = " ".join(raw_title.split())

            desc = (
                f"Pupil:   {config['name']}\n"
                f"Subject: {hw['subject']}\n"
                f"Title:   {hw['title']}\n"
                f"Due:     {hw['due_date']}"
            )

            body: dict = {
                "summary":     safe_title,
                "start":       {"dateTime": start_dt.isoformat(), "timeZone": TIMEZONE},
                "end":         {"dateTime": end_dt.isoformat(),   "timeZone": TIMEZONE},
                "description": desc,
                "extendedProperties": {"private": {
                    TAG_HOMEWORK: "true",
                    TAG_HW_ID:   hw_id,
                    TAG_HW_HASH: hw_hash,
                }},
            }
            if colour:
                body["colorId"] = colour

            if hw_id in existing_by_hw_id:
                ev_id, stored_hash = existing_by_hw_id[hw_id]
                if stored_hash == hw_hash:
                    skipped += 1
                    continue
                # Something changed (due date, title, subject) — replace the event
                gcal_delete_event(service, parent_cal_id, ev_id, dry_run)
                gcal_create_event(service, parent_cal_id, body, dry_run)
                updated += 1
            else:
                gcal_create_event(service, parent_cal_id, body, dry_run)
                created += 1

    # Remove orphaned events for homework cancelled/deleted in ClassCharts
    removed = 0
    for hw_id, (ev_id, _) in existing_by_hw_id.items():
        if hw_id not in cc_hw_ids_seen:
            gcal_delete_event(service, parent_cal_id, ev_id, dry_run)
            removed += 1
    if removed:
        print(f"  Removed {removed} cancelled homework event(s)")

    print(f"  Created {created} | Updated {updated} | Skipped {skipped} | Removed {removed}")


# ════════════════════════════════════════════════════════════════════════════
#  Main
# ════════════════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(description="ClassCharts → Google Calendar sync")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show planned changes without writing to Google Calendar",
    )
    args = parser.parse_args()
    dry_run: bool = args.dry_run

    tz = ZoneInfo(TIMEZONE)
    today = datetime.datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)
    window_end = today + datetime.timedelta(days=SYNC_DAYS)

    from_str = today.date().isoformat()
    to_str   = window_end.date().isoformat()

    print(f"\n{'═'*60}")
    print(f"  ClassCharts → Google Calendar Sync")
    print(f"  {'DRY RUN — no changes will be made' if dry_run else 'LIVE RUN'}")
    print(f"  Window: {from_str}  →  {to_str}  ({SYNC_DAYS} days)")
    print(f"{'═'*60}")

    # ── ClassCharts login ────────────────────────────────────────────────
    print("\nLogging in to ClassCharts…")
    cc, cc_pupils = cc_login()
    cc_pupils_by_name = {p["name"].lower(): p for p in cc_pupils}
    print(f"Pupils: {[p['name'] for p in cc_pupils]}")

    # ── Google Calendar service ──────────────────────────────────────────
    print("Connecting to Google Calendar…")
    service = gcal_service()

    try:
        cal_ids = gcal_get_calendar_ids()
    except RuntimeError as exc:
        print(f"✗  {exc}")
        sys.exit(1)

    # Build pupils config dynamically from discovered pupils + available calendar IDs
    pupils_config = build_pupils_config(cc_pupils, cal_ids)
    if not pupils_config:
        print("✗  No pupils found with available Google Calendars — check GCAL_ID_* secrets")
        sys.exit(1)

    pupil_names = [p["name"] for p in pupils_config]
    print(f"Calendars: parent={cal_ids['parent'][:30]}… | {len(pupils_config)} pupil(s) with calendars")

    # ── Four sync passes ─────────────────────────────────────────────────
    sync_timetable(
        cc, cc_pupils_by_name, service, pupils_config,
        today, window_end, from_str, to_str, dry_run,
    )

    # Pass 2–4 share the same cc session; timetable re-fetches are needed
    # inside each pass so results aren't cross-contaminated.
    sync_no_school(
        cc, cc_pupils_by_name, service, cal_ids["parent"], pupils_config,
        today, window_end, from_str, to_str, dry_run,
    )

    sync_pe_enrichment(
        cc, cc_pupils_by_name, service, cal_ids["parent"], pupils_config,
        today, window_end, from_str, to_str, dry_run,
    )

    # Homework due dates can extend beyond the timetable window, so fetch
    # 60 days ahead rather than the 28-day timetable window.
    hw_end    = today + datetime.timedelta(days=60)
    hw_to_str = hw_end.date().isoformat()
    sync_homework(
        cc, cc_pupils_by_name, service, cal_ids["parent"], pupils_config,
        today, hw_end, from_str, hw_to_str, dry_run,
    )

    print(f"\n{'═'*60}")
    print("  Sync complete.")
    print(f"{'═'*60}\n")


if __name__ == "__main__":
    main()
