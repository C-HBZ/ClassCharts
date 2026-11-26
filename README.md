# ClassCharts → Google Calendar Sync

Automatically syncs school timetables, PE/Enrichment sessions, homework due dates, and "No School" markers from [ClassCharts](https://www.classcharts.com) into Google Calendar.

---

## What it does

Each time the script runs it performs five passes:

| Pass | What it creates | Where | Period |
|---|---|---|---|
| 1 · Timetable | One event per lesson, colour-coded by subject | Each child's own school calendar | Next 28 days |
| 2 · No School | All-day "No School" marker for every weekday with no lessons | Parent calendar | Next 28 days |
| 2b · No TimeTBL | All-day "No TimeTBL" marker for Mon–Fri if no timetable exists (e.g. summer break) | Parent calendar | Current week |
| 3 · PE & Enrichment | Timed alert for every PE or Enrichment lesson | Parent calendar | Next 28 days |
| 4 · Homework | One event per homework item, placed on the due date at 09:00 | Parent calendar | Next 60 days |

Changes in ClassCharts (amended due dates, room changes, cancelled lessons) are detected on the next run and updated or deleted automatically.

### Pass 2b — No TimeTBL (when no timetable exists)

During school holidays or breaks when timetable data is not yet available in ClassCharts, Pass 2b creates all-day "No TimeTBL" markers for the current week (Monday–Friday) in the parent calendar. This is distinct from "No School" which marks individual days when school is open but a specific day has no lessons. Each sync run:
- Deletes any stale "No TimeTBL" markers from the current week
- Checks if ANY child has lessons in the current week
- If no timetable exists anywhere, creates "No TimeTBL" events (Mon–Fri)
- If a timetable is added, the events are automatically cleaned up on the next run

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
Pupil Subject Description
```

The script applies intelligent abbreviation rules to keep titles short enough for wall-mounted or compact calendar displays.

### Subject label (max 8 characters)

Rules applied in order:

1. **Explicit abbreviation** — if the subject matches an entry in `SUBJECT_ABBREVIATIONS` (e.g. `"textiles & food"` → `"T&F"`), that abbreviation is used.
2. **Already short** — if the full subject name is 8 characters or fewer, it is used as-is (e.g. `"Maths"`, `"English"`).
3. **Multi-word subject** — the first word is taken as the label (e.g. `"Computing Technology"` → `"Computing"`).
4. **Apostrophe truncation** — if the chosen label is still over 8 characters, it is cut to 7 characters with a trailing apostrophe to signal the truncation (e.g. `"Chemistry"` → `"Chemist'"`).

You can add subjects to `SUBJECT_ABBREVIATIONS` in the script for full control over any subject label.

### Homework label

The final part of the title is chosen to describe the homework action or useful task:

1. **Assessment intent** — titles mentioning an exam use `Exam`; otherwise titles mentioning a test, assessment, mock, revision, or revising use `Test`.
2. **Recognised task or object** — known terms such as `Paper`, `Equipment`, `Pastry`, `Spreadsheet`, `Poster`, and `Booklet` are used instead of an unhelpful trailing word (for example, `"Puff pastry Christmas tree"` → `Pastry`).
3. **Safe fallback** — generic homework titles, dates, status words, and titles without a recognised task use `Homework`, rather than guessing from the last word.

The label is based on the full homework title, while the full title remains in the event description. Recognised labels are kept intact for readability, even when a useful word is longer than 9 characters.

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

## Raspberry Pi Home Notifiers

The independent scripts in [`home_notifiers/`](home_notifiers/) announce calendar events and homework through a Google Home / Chromecast speaker. They do not import or call the ClassCharts sync script and are not run by the GitHub Actions workflow.

### Scripts

- `calendar_home_notifier.py` announces today's events for Lewis or Austin. Ordinary events are selected by title; homework events (identified by “homework” in the title or by the structured homework fields) use the description's `Pupil`, `Subject`, and `Title` fields and are announced as due today. Online Google TTS uses Canadian English (`tld='ca'`). `--debug` prints all events found for today, and `--dry-run` prints the announcement without generating audio or using the speaker.
- `homework_notifier.py` finds tomorrow's homework events (identified by “homework” in the event title or by the structured homework fields), identifies Lewis or Austin from the event description's `Pupil` field (or the title if that field is absent), and announces the description's subject and homework title as due tomorrow. Online Google TTS uses Australian English (`tld='com.au'`). Its `--dry-run` option prints the announcement without generating audio or using the speaker.

Homework event descriptions are expected to contain fields like:

```text
Pupil: Lewis SURNAME
Subject: History
Title: Chapter 4
Due: YYYY-MM-DD
```

The spoken homework format is `Lewis. Homework for History, "Chapter 4", due today` in the morning notifier and `Lewis. Homework for History, "Chapter 4", due tomorrow` in the evening notifier. Leading subject names and generic “Homework” prefixes are removed from the title so the subject and word homework are not spoken twice. The due wording is based on which day the script checks; it does not calculate the wording from the `Due` field.

### Raspberry Pi installation and configuration

Copy both notifier scripts and their shared helper into `/home/pi/home_notifiers/`, and install the updater outside that directory so it can safely update the notifier files. Then install the dependencies with the Pi's system Python:

```bash
mkdir -p /home/pi/home_notifiers
sudo install -m 755 /path/to/ClassCharts/home_notifiers/calendar_home_notifier.py /home/pi/home_notifiers/
sudo install -m 755 /path/to/ClassCharts/home_notifiers/homework_notifier.py /home/pi/home_notifiers/
sudo install -m 644 /path/to/ClassCharts/home_notifiers/notifier_reliability.py /home/pi/home_notifiers/
sudo install -m 755 /path/to/ClassCharts/home_notifiers/update_home_notifiers.sh /home/pi/update_home_notifiers.sh
sudo apt update
sudo apt install -y python3-pip espeak-ng
/usr/bin/python3 -m pip install --user -r /path/to/ClassCharts/home_notifiers/requirements.txt
```

`espeak-ng` is a small, open-source text-to-speech (TTS) program that runs locally on the Pi. It is the offline fallback when Google's online TTS service is unavailable; its voice is more synthetic, but it does not need internet access. It is an operating-system package, not a Python package, so it is installed with `apt` and is documented in `requirements.txt` rather than listed as a pip dependency. The Python dependencies (`requests`, `recurring-ical-events`, `icalendar`, `gTTS`, and `PyChromecast`) are installed by the pip command above.

On Raspberry Pi OS versions whose system Python blocks `pip install --user` as externally managed, add `--break-system-packages` to that pip command. This keeps the installed packages in the Pi user's site directory while allowing the cron commands to continue using `/usr/bin/python3`.

Codespaces secrets are not automatically available on the Pi. Create a private environment file for the local notifier:

```bash
mkdir -p /home/pi/home_notifiers
nano /home/pi/home_notifiers/notifier.env
```

Put these exports in `notifier.env`, replacing the calendar placeholder with your private iCal feed URL:

```bash
export CALENDAR_ICAL_URL='REPLACE_WITH_YOUR_PRIVATE_ICAL_FEED_URL'
```

`CALENDAR_ICAL_URL` is required. Both scripts target the Google Home speaker group named `ALLnoOffice` via Cast discovery, so the individual speaker IP and name do not belong in `notifier.env`. Name-based discovery uses mDNS and works when the Pi and speaker group are visible on the same local network; it can be less reliable than a known IP if multicast discovery is blocked, but an individual speaker's IP cannot be used as the group address. Treat the calendar feed URL like a password: do not print it, paste it into source code, or commit it. Restrict access to the config file:

```bash
chmod 700 /home/pi/home_notifiers
chmod 600 /home/pi/home_notifiers/notifier.env
```

Do not put secret values in this README, source files, or any file tracked by Git.

### Manual runs and dry-run tests

With the variables set in the shell, run:

```bash
cd /home/pi
. /home/pi/home_notifiers/notifier.env
/usr/bin/python3 /home/pi/home_notifiers/calendar_home_notifier.py --dry-run
/usr/bin/python3 /home/pi/home_notifiers/calendar_home_notifier.py --debug --dry-run
/usr/bin/python3 /home/pi/home_notifiers/homework_notifier.py --dry-run
```

Each dry run retrieves the calendar and prints the proposed announcement, but does not generate audio or connect to Chromecast. To announce immediately, run the corresponding script without `--dry-run`.
After a successful announcement, the script records a per-date marker under `/home/pi/.local/state/home_notifiers/` so later scheduled retries do not repeat it. Use `--force` to deliberately announce again.

### Raspberry Pi cron schedule and logs

Add these lines to the Pi user's crontab with `crontab -e`. These jobs run on the Pi, not in Codespaces:

```cron
15 7 * * * . /home/pi/home_notifiers/notifier.env && /usr/bin/python3 -u /home/pi/home_notifiers/calendar_home_notifier.py >> /home/pi/home_notifiers/notifier.log 2>&1
25 7 * * * . /home/pi/home_notifiers/notifier.env && /usr/bin/python3 -u /home/pi/home_notifiers/calendar_home_notifier.py >> /home/pi/home_notifiers/notifier.log 2>&1
35 7 * * * . /home/pi/home_notifiers/notifier.env && /usr/bin/python3 -u /home/pi/home_notifiers/calendar_home_notifier.py >> /home/pi/home_notifiers/notifier.log 2>&1
0 17 * * 0-4 . /home/pi/home_notifiers/notifier.env && /usr/bin/python3 -u /home/pi/home_notifiers/homework_notifier.py >> /home/pi/home_notifiers/homework.log 2>&1
5 17 * * 0-4 . /home/pi/home_notifiers/notifier.env && /usr/bin/python3 -u /home/pi/home_notifiers/homework_notifier.py >> /home/pi/home_notifiers/homework.log 2>&1
15 17 * * 0-4 . /home/pi/home_notifiers/notifier.env && /usr/bin/python3 -u /home/pi/home_notifiers/homework_notifier.py >> /home/pi/home_notifiers/homework.log 2>&1
0 16 * * 0 /home/pi/update_home_notifiers.sh >> /home/pi/home_notifiers/update.log 2>&1
```

Cron's first five fields are minute, hour, day of month, month, and day of week. The three calendar runs give temporary failures another chance at 07:25 and 07:35; the homework runs retry at 17:05 and 17:15 Sunday through Thursday (`0-4`). Successful runs are marked, so later runs on the same target date exit without repeating the announcement. The scripts retry transient calendar/TTS network failures themselves and can use a valid cached calendar feed up to 36 hours old. If online TTS remains unavailable, installed `espeak-ng` generates speech locally. Each notifier's output and errors are appended to its log; `-u` makes output appear promptly. If all attempts fail, the script exits with an error and the log must be checked (cron email is only delivered if the Pi has a local mail setup).

The last line runs the updater at 16:00 every Sunday (`0`), before that day's homework announcement. It stages all downloads before replacing the program files, and does not touch `notifier.env`, logs, the calendar cache, or success markers. Review automatic updates before enabling them if you prefer to pin a known revision.

The notifier logs are `/home/pi/home_notifiers/notifier.log` and `/home/pi/home_notifiers/homework.log`.

### Troubleshooting

- **Calendar retrieval:** the scripts retry transient failures and use a valid cached feed only while it is less than 36 hours old. If all attempts fail, verify internet access and `CALENDAR_ICAL_URL`; the private feed URL is intentionally omitted from error output.
- **Audio generation:** online Google TTS is retried first. If it remains unavailable, install `espeak-ng` (`sudo apt install espeak-ng`) for offline speech; check the log for a final generation error.
- **Chromecast playback:** confirm the `ALLnoOffice` group is available in Google Home, the Pi and group are on the same local network, and the router allows mDNS/multicast discovery. The scripts target the group by name; individual speaker IPs are not used.
- **Retries exhausted:** inspect the appropriate log file. The retry cron runs should recover temporary outages, but persistent calendar, TTS, Pi, or speaker failures still require intervention; cron itself does not guarantee delivery.
- Review the appropriate log file listed above for other errors. Use a dry run to isolate calendar retrieval and filtering from audio and speaker issues.

---

## License

See [LICENSE](LICENSE)
