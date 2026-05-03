# ClassCharts → Google Calendar Sync

Automatically syncs school timetables, PE/Enrichment sessions, homework due dates, and "No School" markers from [ClassCharts](https://www.classcharts.com) into Google Calendar. Designed to run nightly on a Raspberry Pi (or any Linux machine).

---

## What it does

Each time the script runs it performs four passes over the next 28 days:

| Pass | What it creates | Where |
|---|---|---|
| 1 · Timetable | One event per lesson, colour-coded by subject | Each child's own school calendar |
| 2 · No School | All-day "No School" marker for every weekday with no lessons | Parent calendar |
| 3 · PE & Enrichment | Timed alert for every PE or Enrichment lesson | Parent calendar |
| 4 · Homework | One event per homework item, placed on the due date at 09:00 | Parent calendar |

Changes in ClassCharts (amended due dates, room changes, cancelled lessons) are detected on the next run and updated or deleted automatically.

---

## Prerequisites

- A ClassCharts parent account
- A Google account with Google Calendar
- A Google Cloud project with a service account (see Google Setup below)
- Python 3.9 or newer (Raspberry Pi OS ships with this)

---

## Raspberry Pi Setup

### 1 — Copy the files

Create a dedicated directory and copy the two project files into it:

```bash
mkdir -p ~/classcharts
cp classcharts_sync.py ~/classcharts/
cp .env             ~/classcharts/
```

Recommended location: `/home/pi/classcharts/` or `~/classcharts/`

---

### 2 — Install system packages

```bash
sudo apt update && sudo apt install -y python3-pip python3-venv
```

---

### 3 — Create a virtual environment

Using a virtual environment keeps the Pi's system Python clean:

```bash
cd ~/classcharts
python3 -m venv venv
source venv/bin/activate
```

---

### 4 — Install Python dependencies

```bash
pip install requests google-api-python-client google-auth python-dotenv
```

You only need to do this once. If you ever need to rerun it:

```bash
source ~/classcharts/venv/bin/activate
pip install requests google-api-python-client google-auth python-dotenv
```

---

### 5 — Fill in the .env file

Edit `~/classcharts/.env` and replace every placeholder with your real values.  
The file contains comments explaining each variable. At minimum you need:

| Variable | What it is |
|---|---|
| `CLASSCHARTS_EMAIL` | Your ClassCharts parent login email |
| `CLASSCHARTS_PASSWORD` | Your ClassCharts parent login password |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Full JSON contents of your service account key (see below) |
| `GCAL_ID_PARENT` | Your personal Google Calendar ID (usually your Gmail address) |
| `GCAL_ID_AUSTIN` | Calendar ID for the first child's school calendar |
| `GCAL_ID_LEWIS` | Calendar ID for the second child's school calendar |

**Keep this file private.** It contains passwords and a private key:

```bash
chmod 600 ~/classcharts/.env
```

---

## Google Calendar Setup

### Create a Google Cloud service account

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Create a project (or use an existing one)
3. Navigate to **APIs & Services → Library**, search for **Google Calendar API**, and enable it
4. Go to **IAM & Admin → Service Accounts → Create Service Account**
5. Give it any name (e.g. `classcharts-sync`), click through to finish
6. Click the service account → **Keys → Add Key → Create new key → JSON**
7. Download the JSON file — open it, copy the entire contents, and paste it as the value of `GOOGLE_SERVICE_ACCOUNT_JSON` in your `.env` file (all on one line)

### Share your calendars with the service account

The service account has its own email address (visible in the JSON as `client_email`, ends in `@...iam.gserviceaccount.com`). You must share each calendar with it:

1. Open Google Calendar on desktop
2. Click the **⋮** next to each calendar → **Settings and sharing**
3. Under **Share with specific people**, add the service account email
4. Set permission to **Make changes to events**
5. Repeat for all three calendars (parent calendar, Austin's, Lewis's)

### Find your Calendar IDs

In the same calendar Settings page, scroll down to **Integrate calendar**. The Calendar ID is shown there. Your primary Gmail calendar uses your Gmail address as its ID; shared/extra calendars have a long ID ending in `@group.calendar.google.com`.

---

## Test run

Before scheduling, do a dry run to confirm everything connects:

```bash
cd ~/classcharts
source venv/bin/activate
python3 classcharts_sync.py --dry-run
```

You should see all four passes print their planned changes without writing anything to Google Calendar. If that looks correct:

```bash
python3 classcharts_sync.py
```

---

## Schedule nightly with cron

Run the sync every night at 01:00:

```bash
crontab -e
```

Add this line at the bottom (adjust the path if you used a different directory):

```
0 1 * * * /home/pi/classcharts/venv/bin/python3 /home/pi/classcharts/classcharts_sync.py >> /home/pi/classcharts/sync.log 2>&1
```

This uses the virtual environment's Python directly, so there's no need to activate the venv first. Output and errors are appended to `sync.log` so you can review them.

To check the log:

```bash
tail -50 ~/classcharts/sync.log
```

---

## Children and calendars configuration

The children's names, display names, and which calendar to write their timetable into are set near the top of `classcharts_sync.py` in the `PUPILS` list. If you have a different number of children or different names, edit that section:

```python
PUPILS: list[dict] = [
    {"name": "Full Name As In ClassCharts", "display": "FirstName", "calendar": "CalendarKey"},
]
```

The `calendar` value maps to the corresponding `GCAL_ID_*` variable name in your `.env`.

---

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| `ERROR: pip install requests` | Packages not installed — run step 4 again |
| `Missing Codespaces secret(s)` | `.env` file missing or a variable is blank |
| `401 Unauthorized` on Google Calendar | Service account not shared with the calendar — redo the sharing step |
| `403 Forbidden` on ClassCharts | Password changed or account locked — check ClassCharts login in a browser |
| Events duplicating | Old GAS-created events have no fingerprint tag; they are invisible to this script. Delete them manually once, then this script manages everything going forward |
| No lessons returned | ClassCharts may be unavailable or the school hasn't published the timetable for that week yet |
