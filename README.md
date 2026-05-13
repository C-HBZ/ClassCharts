# ClassCharts → Google Calendar Sync

Automatically syncs school timetables, PE/Enrichment sessions, homework due dates, and "No School" markers from [ClassCharts](https://www.classcharts.com) into Google Calendar.

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

## Privacy

This repo contains **no hardcoded family names, child names, or personal identifiers**. The script source code is safe to make completely public. All personal data is stored exclusively in environment variables (`.env` file or repository/Codespaces secrets):

- Child names and calendar IDs
- Homework colour preferences
- ClassCharts login credentials
- Google service account key

Just keep your `.env` file and repository secrets private.

---

## Homework event titles

Homework events in the parent calendar use this format:

```
Pupil: Subject: Description
```

The script applies intelligent abbreviation rules to keep titles short enough for wall-mounted or compact calendar displays.

### Subject label (max 8 characters)

Rules applied in order:

1. **Explicit abbreviation** — if the subject matches an entry in `SUBJECT_ABBREVIATIONS` (e.g. `"textiles & food"` → `"T&F"`), that abbreviation is used.
2. **Already short** — if the full subject name is 8 characters or fewer, it is used as-is (e.g. `"Maths"`, `"English"`).
3. **Multi-word subject** — the first word is taken as the label (e.g. `"Computing Technology"` → `"Computing"`).
4. **Apostrophe truncation** — if the chosen label is still over 8 characters, it is cut to 7 characters with a trailing apostrophe to signal the truncation (e.g. `"Chemistry"` → `"Chemist'"`).

You can add subjects to `SUBJECT_ABBREVIATIONS` in the script for full control over any subject label.

### Description label (max 9 characters)

The description is extracted from the homework title using the following rules (applied in order):

1. **Bilingual titles** — if the title contains ` / ` or ` | `, the last segment is kept (e.g. `"Asesiad Llafar / Speaking Test"` → `"Speaking Test"`).
2. **Prepositional tail** — trailing phrases starting with *for*, *about*, *on*, or *of* are stripped (e.g. `"Test for alkalis and acids"` → `"Test"`).
3. **Noise words** — trailing format/medium words (info, sheet, handout, reminder, resource, document, guide, etc.) are stripped repeatedly (e.g. `"Exam Revision Info"` → `"Exam Revision"`).
4. **Head noun** — the last word of the remaining phrase is capitalised and used as the label (e.g. `"Exam Revision"` → `"Revision"`).
5. **Apostrophe truncation** — if the head noun exceeds 9 characters, it is cut to 8 characters with a trailing apostrophe (e.g. `"Electrochemistry"` → `"Electroc'"`).

You can extend `HOMEWORK_TRAILING_NOISE` in the script to add further words to strip.

---

## Prerequisites

- A ClassCharts parent account
- A Google account with Google Calendar
- A Google Cloud project with a service account (see Google Setup below)
- Python 3.9 or newer
- For GitHub Actions: a personal GitHub account (optional; a Raspberry Pi or local machine works too)

---

## Quick Start: GitHub Actions (Recommended)

### 1 — Fork the repository

1. Go to [github.com/C-HBZ/ClassCharts](https://github.com/C-HBZ/ClassCharts)
2. Click **Fork** to create a copy in your GitHub account

### 2 — Set up repository secrets

Go to your fork's **Settings → Secrets and variables → Actions** and add:

**Required:**

| Secret name | Value |
|---|---|
| `CLASSCHARTS_EMAIL` | Your ClassCharts parent login email |
| `CLASSCHARTS_PASSWORD` | Your ClassCharts parent login password |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Full JSON contents of your Google service account key |
| `GCAL_ID_PARENT` | Your personal Google Calendar ID (usually your Gmail address) |

**For each child** (replace `<FIRSTNAME>` with their first name as it appears in ClassCharts):

| Secret name | Value |
|---|---|
| `GCAL_ID_<FIRSTNAME>` | Their school calendar ID |

**Optional homework colours:**

| Secret name | Value |
|---|---|
| `HOMEWORK_COLOR_<FIRSTNAME>` | Google Calendar colour ID (1–11; see [Colour Reference](#colour-reference)) |

### 3 — Create the workflow file

Create `.github/workflows/classcharts-sync.yml` in your fork:

```yaml
name: ClassCharts Sync

on:
  schedule:
    - cron: '0 1 * * *'   # Daily at 01:00 UTC — adjust as needed
  workflow_dispatch:

jobs:
  sync:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout code
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: pip install requests google-api-python-client google-auth python-dotenv

      - name: Run ClassCharts sync
        env:
          CLASSCHARTS_EMAIL: ${{ secrets.CLASSCHARTS_EMAIL }}
          CLASSCHARTS_PASSWORD: ${{ secrets.CLASSCHARTS_PASSWORD }}
          GOOGLE_SERVICE_ACCOUNT_JSON: ${{ secrets.GOOGLE_SERVICE_ACCOUNT_JSON }}
          GCAL_ID_PARENT: ${{ secrets.GCAL_ID_PARENT }}
          # Add one line per child:
          # GCAL_ID_CHILD1: ${{ secrets.GCAL_ID_CHILD1 }}
          # GCAL_ID_CHILD2: ${{ secrets.GCAL_ID_CHILD2 }}
          # Optional homework colours:
          # HOMEWORK_COLOR_CHILD1: ${{ secrets.HOMEWORK_COLOR_CHILD1 }}
          # HOMEWORK_COLOR_CHILD2: ${{ secrets.HOMEWORK_COLOR_CHILD2 }}
        run: python3 classcharts_sync.py
```

### 4 — Test it

Go to **Actions → ClassCharts Sync → Run workflow** to trigger a manual run and verify the output.

Common schedule examples:
- `0 1 * * *` — Daily at 01:00 UTC
- `0 */6 * * *` — Every 6 hours
- `0 6 * * MON-FRI` — Weekdays at 06:00 UTC

---

## Alternative: Raspberry Pi or Linux Setup

### 1 — Copy the files

```bash
mkdir -p ~/classcharts
cp classcharts_sync.py ~/classcharts/
```

### 2 — Install system packages

```bash
sudo apt update && sudo apt install -y python3-pip python3-venv
```

### 3 — Create a virtual environment

```bash
cd ~/classcharts
python3 -m venv venv
source venv/bin/activate
```

### 4 — Install Python dependencies

```bash
pip install requests google-api-python-client google-auth python-dotenv
```

### 5 — Configure environment variables

Create `~/classcharts/.env`:

```bash
cat > ~/classcharts/.env << 'EOF'
CLASSCHARTS_EMAIL=parent@example.com
CLASSCHARTS_PASSWORD=your_password
GOOGLE_SERVICE_ACCOUNT_JSON={"type":"service_account",...}
GCAL_ID_PARENT=parent@gmail.com
GCAL_ID_CHILD1=child1_calendar_id@group.calendar.google.com
GCAL_ID_CHILD2=child2_calendar_id@group.calendar.google.com
HOMEWORK_COLOR_CHILD1=9
HOMEWORK_COLOR_CHILD2=3
EOF

chmod 600 ~/classcharts/.env
```

### 6 — Test run

```bash
cd ~/classcharts
source venv/bin/activate
python3 classcharts_sync.py --dry-run
python3 classcharts_sync.py
```

### 7 — Schedule with cron

```bash
crontab -e
```

Add:

```
0 1 * * * /home/pi/classcharts/venv/bin/python3 /home/pi/classcharts/classcharts_sync.py >> /home/pi/classcharts/sync.log 2>&1
```

Check the log:

```bash
tail -50 ~/classcharts/sync.log
```

---

## Google Calendar Setup

### Create a Google Cloud service account

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Create a new project (or select an existing one)
3. Go to **APIs & Services → Library**, search for **Google Calendar API**, and enable it
4. Go to **IAM & Admin → Service Accounts → Create Service Account**
5. Give it any name (e.g. `classcharts-sync`) and click through to finish
6. Click the service account → **Keys → Add Key → Create new key → JSON**
7. Download the JSON file, open it, copy the entire contents (all on one line), and paste it as `GOOGLE_SERVICE_ACCOUNT_JSON`

### Share your calendars with the service account

The `client_email` field in the JSON (ending in `@...iam.gserviceaccount.com`) must be shared with every calendar:

1. Open Google Calendar on desktop
2. Click **⋮** next to each calendar → **Settings and sharing**
3. Under **Share with specific people**, add the service account email
4. Set permission to **Make changes to events**
5. Repeat for all calendars (parent + each child's school calendar)

### Find your Calendar IDs

In the same Settings page, scroll to **Integrate calendar**. The Calendar ID is shown there:
- Primary Gmail calendar: usually your Gmail address
- Other calendars: a long ID ending in `@group.calendar.google.com`

---

## How pupils are discovered

The script automatically fetches all pupils from your ClassCharts account at runtime:

1. Reads each pupil's first name from ClassCharts
2. Looks for a matching `GCAL_ID_<FIRSTNAME>` environment variable (case-insensitive)
3. If found, syncs that pupil's timetable into the corresponding calendar
4. If not found, skips that pupil

No hardcoded names in the script — it's safe to make the repo public. Adding a new child only requires adding the corresponding `GCAL_ID_<FIRSTNAME>` secret.

---

## Colour Reference

| ID | Colour | ID | Colour |
|---|---|---|---|
| 1 | Lavender | 7 | Peacock |
| 2 | Sage | 8 | Graphite |
| 3 | Grape | 9 | Blueberry |
| 4 | Flamingo | 10 | Basil |
| 5 | Banana | 11 | Tomato |
| 6 | Tangerine | | |

---

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| `ERROR: pip install requests` | Packages not installed — run the install step again |
| `Missing required secret: CLASSCHARTS_PASSWORD` | Add the missing secret to GitHub Actions or `.env` |
| `No pupils found` | Add `GCAL_ID_<FIRSTNAME>` for each child |
| `401 Unauthorized` on Google Calendar | Service account not shared with one of the calendars |
| Duplicate events | Old GAS-created events have no fingerprint tag — delete them manually once |
| No lessons returned | ClassCharts may be down or timetable not yet published |

---

## License

See [LICENSE](LICENSE)
