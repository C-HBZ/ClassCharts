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

## Prerequisites

- A ClassCharts parent account
- A Google account with Google Calendar
- A Google Cloud project with a service account (see Google Setup below)
- Python 3.9 or newer
- For GitHub Actions: A personal GitHub account (optional; can use Raspberry Pi or local machine instead)

---

## Quick Start: GitHub Actions (Recommended)

This is the simplest way to run the sync automatically without managing a server.

### 1 — Fork the repository

1. Go to [github.com/C-HBZ/ClassCharts](https://github.com/C-HBZ/ClassCharts) (or the original repo)
2. Click **Fork** (top right) to create a copy in your personal GitHub account
3. Clone your fork locally or open it in GitHub Codespaces

### 2 — Set up repository secrets

1. Go to your fork's **Settings** → **Secrets and variables** → **Actions**
2. Click **New repository secret** for each of the following:

**Required secrets:**

| Secret name | Value |
|---|---|
| `CLASSCHARTS_EMAIL` | Your ClassCharts parent login email |
| `CLASSCHARTS_PASSWORD` | Your ClassCharts parent login password |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Full JSON contents of your [Google service account key](#create-a-google-cloud-service-account) |
| `GCAL_ID_PARENT` | Your personal Google Calendar ID (usually your Gmail address) |

**For each child**, add:

| Secret name | Value |
|---|---|
| `GCAL_ID_<FIRSTNAME>` | Their school calendar ID (replace `<FIRSTNAME>` with their actual first name in ClassCharts) |

**Optional**, for homework colours:

| Secret name | Value |
|---|---|
| `HOMEWORK_COLOR_<FIRSTNAME>` | Google Calendar colour ID (1–11; see [Colour Reference](#colour-reference)) |

### 3 — Create the workflow file

1. In your fork, create the folder structure: `.github/workflows/`
2. Create a file `.github/workflows/classcharts-sync.yml`:

```yaml
name: ClassCharts Sync

on:
  schedule:
    # Run every night at 01:00 UTC
    - cron: '0 1 * * *'
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
          # Add GCAL_ID_<CHILD> for each child:
          # GCAL_ID_AUSTIN: ${{ secrets.GCAL_ID_AUSTIN }}
          # GCAL_ID_LEWIS: ${{ secrets.GCAL_ID_LEWIS }}
          # Add optional HOMEWORK_COLOR_<CHILD> for colours:
          # HOMEWORK_COLOR_AUSTIN: ${{ secrets.HOMEWORK_COLOR_AUSTIN }}
          # HOMEWORK_COLOR_LEWIS: ${{ secrets.HOMEWORK_COLOR_LEWIS }}
        run: python3 classcharts_sync.py
```

Uncomment and customize the child calendar ID lines for your actual children, and add any homework colour preferences.

### 4 — Test it

1. Go to your fork's **Actions** tab
2. Select **ClassCharts Sync** → **Run workflow** → **Run workflow**
3. Wait for completion and check the logs
4. Scheduled runs will now happen automatically each night at 1:00 AM UTC

To change the schedule, edit the `cron` line. Common examples:
- `0 1 * * *` — Daily at 01:00 UTC
- `0 */6 * * *` — Every 6 hours
- `0 6 * * MON-FRI` — Weekdays at 06:00 UTC

---

## Alternative: Raspberry Pi or Linux Setup

If you prefer to run the sync on a Raspberry Pi or your own Linux machine without GitHub Actions, follow these steps.

### 1 — Copy the files

```bash
mkdir -p ~/classcharts
cd ~/classcharts
cp /path/to/classcharts_sync.py .
cp /path/to/.env.template .env
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

Edit `~/.classcharts/.env` with your configuration:

```bash
cat > ~/classcharts/.env << 'EOF'
CLASSCHARTS_EMAIL=your_email@example.com
CLASSCHARTS_PASSWORD=your_password
GOOGLE_SERVICE_ACCOUNT_JSON={"type":"service_account",...}
GCAL_ID_PARENT=your_gmail@gmail.com
GCAL_ID_AUSTIN=austin_calendar_id@group.calendar.google.com
GCAL_ID_LEWIS=lewis_calendar_id@group.calendar.google.com
HOMEWORK_COLOR_AUSTIN=9
HOMEWORK_COLOR_LEWIS=3
EOF

chmod 600 ~/classcharts/.env
```

Replace placeholders with your actual values.

### 6 — Test run

Before scheduling, test with a dry run:

```bash
cd ~/classcharts
source venv/bin/activate
python3 classcharts_sync.py --dry-run
```

If that looks correct:

```bash
python3 classcharts_sync.py
```

### 7 — Schedule nightly with cron

```bash
crontab -e
```

Add this line:

```
0 1 * * * /home/pi/classcharts/venv/bin/python3 /home/pi/classcharts/classcharts_sync.py >> /home/pi/classcharts/sync.log 2>&1
```

Check the log:

```bash
tail -50 ~/classcharts/sync.log
```

---

## Required Configuration Variables

**ClassCharts login:**
- `CLASSCHARTS_EMAIL` — Your parent account email
- `CLASSCHARTS_PASSWORD` — Your parent account password

**Google Calendar:**
- `GOOGLE_SERVICE_ACCOUNT_JSON` — Service account JSON key (all on one line)
- `GCAL_ID_PARENT` — Your personal calendar ID (usually your Gmail address)
- `GCAL_ID_<FIRSTNAME>` — For each child, their school calendar ID (one variable per child)

**Optional:**
- `HOMEWORK_COLOR_<FIRSTNAME>` — Colour ID (1–11) for homework events (one per child, optional)

---

## Google Calendar Setup

### Create a Google Cloud service account

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Create a new project (or select an existing one)
3. Go to **APIs & Services** → **Library**
4. Search for **Google Calendar API** and enable it
5. Go to **IAM & Admin** → **Service Accounts** → **Create Service Account**
6. Fill in details and click through to finish
7. Click the service account → **Keys** → **Add Key** → **Create new key** → **JSON**
8. Download the JSON file
9. Open the file and copy the entire contents (all on one line)
10. Paste this as `GOOGLE_SERVICE_ACCOUNT_JSON` in your `.env` file or GitHub secret

### Share your calendars with the service account

The service account has an email address ending in `@...iam.gserviceaccount.com` (visible in the JSON file as `client_email`).

For each calendar (parent + all children's school calendars):

1. Open Google Calendar on desktop
2. Click the **⋮** next to the calendar → **Settings and sharing**
3. Under **Share with specific people**, add the service account email
4. Set permission to **Make changes to events**
5. Repeat for all calendars

### Find your Calendar IDs

In the same calendar Settings page, scroll to **Integrate calendar**. The Calendar ID is shown there:
- Your primary Gmail calendar: usually your Gmail address
- Other calendars: a long ID ending in `@group.calendar.google.com`

---

## Colour Reference

Use these IDs in `HOMEWORK_COLOR_<FIRSTNAME>` environment variables:

| ID | Colour | ID | Colour |
|---|---|---|---|
| 1 | Lavender | 7 | Peacock |
| 2 | Sage | 8 | Graphite |
| 3 | Grape | 9 | Blueberry |
| 4 | Flamingo | 10 | Basil |
| 5 | Banana | 11 | Tomato |
| 6 | Tangerine | | |

---

## How pupils are discovered

The script automatically fetches all pupils from your ClassCharts account at runtime:

1. For each pupil, it reads their first name
2. It looks for an environment variable `GCAL_ID_<FIRSTNAME>` (case-insensitive)
3. If found, it syncs that pupil's timetable into the corresponding calendar
4. If not found, it skips that pupil

**This means:**
- No hardcoded names in the script — it's safe to make the repo public
- Adding a new child to ClassCharts? Just add the corresponding `GCAL_ID_<FIRSTNAME>` secret and it syncs automatically
- The script discovers and adapts at runtime; no code changes needed

---

## Troubleshooting

| Issue | Solution |
|---|---|
| `ERROR: pip install requests` | Install packages: run step 2/4 again |
| `Missing required secret: CLASSCHARTS_PASSWORD` | Add missing secrets to GitHub Actions or `.env` file |
| `No pupils found` | Add `GCAL_ID_<FIRSTNAME>` for each child in ClassCharts |
| `401 Unauthorized` on Google Calendar | Check that the service account email is shared with each calendar |
| Duplicate events | From old GAS script? Delete them manually once; this script will manage them going forward |
| `No lessons returned` | ClassCharts may be down or school hasn't published the timetable yet |

---

## License

See [LICENSE](LICENSE)
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

## Privacy

This repo contains **no hardcoded family names, child names, or personal identifiers**. The script source code is safe to make completely public. All personal data is stored exclusively in environment variables (`.env` file or repository/Codespaces secrets):
- Child names and calendar IDs
- Homework colour preferences
- ClassCharts login credentials
- Google service account key

Just keep your `.env` file and repository secrets private.

---

## Prerequisites

- A ClassCharts parent account
- A Google account with Google Calendar
- A Google Cloud project with a service account (see Google Setup below)
- Python 3.9 or newer (Raspberry Pi OS ships with this)
- For GitHub Actions: A personal GitHub account

---

## Raspberry Pi Setup

If you prefer to run the sync on a Raspberry Pi or your own Linux machine instead of GitHub Actions, follow these steps.

### 1 — Copy the files

Create a dedicated directory and copy the project files into it:

```bash
mkdir -p ~/classcharts
cp classcharts_sync.py ~/classcharts/
cp .env.template      ~/classcharts/.env
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

### 5 — Fill in the environment variables

The script reads configuration from environment variables. You can set these in a `.env` file (which the script loads automatically) or as Codespaces secrets.

**Required variables:**

| Variable | What it is | Example |
|---|---|---|
| `CLASSCHARTS_EMAIL` | Your ClassCharts parent login email | `parent@example.com` |
| `CLASSCHARTS_PASSWORD` | Your ClassCharts parent login password | (your password) |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Full JSON contents of your service account key | (see Google Setup below) |
| `GCAL_ID_PARENT` | Your personal Google Calendar ID (usually your Gmail address) | `parent@gmail.com` |

**For each child's timetable calendar**, add a variable named `GCAL_ID_<FIRSTNAME>` matching their first name in ClassCharts:

| Child's first name | Environment variable | Calendar ID |
|---|---|---|
| (your 1st child) | `GCAL_ID_<FIRSTNAME>` | (their school calendar ID) |
| (your 2nd child) | `GCAL_ID_<FIRSTNAME>` | (their school calendar ID) |
| (your 3rd child) | `GCAL_ID_<FIRSTNAME>` | (their school calendar ID) |

The script automatically discovers all pupils in your ClassCharts account and syncs each one into their corresponding calendar (matched by first name, case-insensitive).

**If using `.env` file on a Raspberry Pi**, create one:

```bash
cat > ~/classcharts/.env << 'EOF'
CLASSCHARTS_EMAIL=parent@example.com
CLASSCHARTS_PASSWORD=your_password
GOOGLE_SERVICE_ACCOUNT_JSON={"type":"service_account",...}
GCAL_ID_PARENT=parent@gmail.com
GCAL_ID_FIRSTNAME1=child1_calendar_id@group.calendar.google.com
GCAL_ID_FIRSTNAME2=child2_calendar_id@group.calendar.google.com
HOMEWORK_COLOR_FIRSTNAME1=9
HOMEWORK_COLOR_FIRSTNAME2=3
EOF

chmod 600 ~/classcharts/.env
```

(Replace `FIRSTNAME1`, `FIRSTNAME2`, etc. and the colour IDs with your actual setup.)

**If using Codespaces secrets**, go to **Settings → Secrets and Variables → Codespaces** and add each variable there instead.

**If using GitHub Actions**, see the [GitHub Actions Setup](#github-actions-setup) section below.

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
5. Repeat for all your calendars (parent calendar + each child's school calendar)

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

## GitHub Actions Setup

This is the simplest way to run the sync automatically on any schedule without managing a server or Raspberry Pi.

### 1 — Fork the repository

1. Go to [github.com/C-HBZ/ClassCharts](https://github.com/C-HBZ/ClassCharts) (or the original repo)
2. Click **Fork** (top right) to create a copy in your personal GitHub account
3. Clone your fork locally or open it in Codespaces
the following required secrets:

| Secret name | Value |
|---|---|
| `CLASSCHARTS_EMAIL` | Your ClassCharts parent login email |
| `CLASSCHARTS_PASSWORD` | Your ClassCharts parent login password |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Full JSON contents of your [Google service account key](#create-a-google-cloud-service-account) |
| `GCAL_ID_PARENT` | Your personal Google Calendar ID (usually your Gmail address) |

3. For **each of your children**, add a secret for their school calendar ID:

| Secret name | Value |
|---|---|
| `GCAL_ID_<FIRSTNAME>` | Their school calendar ID (replace `<FIRSTNAME>` with their actual first name) |

4. (Optional) For **homework colour preferences**, add for each child:

| Secret name | Value |
|---|---|
| `HOMEWORK_COLOR_<FIRSTNAME>` | Google Calendar colour ID (1–11; see [colour reference below](#colours)) or leave blankur [Google service account key](#create-a-google-cloud-service-account) |
| `GCAL_ID_PARENT` | Your personal Google Calendar ID (usually your Gmail address) |
| `GCAL_ID_ALICE` | (your first child's school calendar ID) |
| `GCAL_ID_BOB` | (your second child's school calendar ID) |
| (etc.) | (add more `GCAL_ID_<FIRSTNAME>` for each child) |

### 3 — Create the workflow file

1. In your fork, create the folder structure: `.github/workflows/`
2. Create a file `.github/workflows/classcharts-sync.yml` with the following content:

```yaml
name: ClassCharts Sync

on:
  schedule:
    # Run every night at 01:00 UTC (adjust the time as needed)
    - cron: '0 1 * * *'
  # Allow manual triggering from the Actions tab
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
```yaml
name: ClassCharts Sync

on:
  schedule:
    # Run every night at 01:00 UTC (adjust the time as needed)
    - cron: '0 1 * * *'
  # Allow manual triggering from the Actions tab
  workflow_dispatch:

jobs:
  sync:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout code
        uses: actions/checkout@v4
Google Calendar has 11 colour options:

| ID | Colour | ID | Colour |
|---|---|---|---|
| 1 | Lavender | 7 | Peacock |
| 2 | Sage | 8 | Graphite |
| 3 | Grape | 9 | Blueberry |
| 4 | Flamingo | 10 | Basil |
| 5 | Banana | 11 | Tomato |
| 6 | Tangerine | | |

---

### 5 — Verify it works
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
          GCAL_ID_ALICE: ${{ secrets.GCAL_ID_ALICE }}
          GCAL_ID_BOB: ${{ secrets.GCAL_ID_BOB }}
          HOMEWORK_COLOR_ALICE: ${{ secrets.HOMEWORK_COLOR_ALICE }}
          HOMEWORK_COLOR_BOB: ${{ secrets.HOMEWORK_COLOR_BOB }}
        run: python3 classcharts_sync.py
```

**Note:** Replace `ALICE`, `BOB`, etc. with your actual children's first names (as they appear in ClassCharts). If you have the optional `HOMEWORK_COLOR_` secrets, include them above (or omit if not used).

### 4 — ColourCE_ACCOUNT_JSON: ${{ secrets.GOOGLE_SERVICE_ACCOUNT_JSON }}
          GCAL_ID_PARENT: ${{ secrets.GCAL_ID_PARENT }}
          GCAL_ID_ALICE: ${{ secrets.GCAL_ID_ALICE }}
          GCAL_ID_BOB: ${{ secrets.GCAL_ID_BOB }}
        run: python3 classcharts_sync.py
```

**Note:** If you have more or fewer children, add/remove the corresponding `GCAL_ID_*` environment variables in both the secrets and the workflow file.

### 4 — Verify it works

1. Go to your fork's **Actions** tab
2. Click **ClassCharts Sync** → **Run workflow** → **Run workflow** to test it manually
3. Wait for the run to complete. Click into it to view logs
4. Once you confirm it worked, the scheduled runs will happen automatically every night at 1:00 AM UTC

**To change the schedule**, edit the `cron` line in `.github/workflows/classcharts-sync.yml`. Common examples:
- `0 1 * * *` — Daily at 01:00 UTC
- `0 */6 * * *` — Every 6 hours
- `0 6 * * MON-FRI` — Weekdays at 06:00 UTC

---

## Local & Docker Environments

Both `.env` file and GitHub Actions use environment variables. You can also run the sync in other environments (local machine, Docker container, etc.) by setting these same environment variables.

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

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| `ERROR: pip install requests` | Packages not installed — run step 4 again |
| `Missing required Codespaces secret: GCAL_ID_PARENT` | `GCAL_ID_PARENT` is not set — add it to `.env` or Codespaces secrets |
| `No pupils found with available Google Calendars` | No `GCAL_ID_<FIRSTNAME>` variables found for discovered pupils — add them for each child |
| `401 Unauthorized` on Google Calendar | Service account not shared with one of the calendars — redo the sharing step for all three (parent + child calendars) |
| `403 Forbidden` on ClassCharts | Password changed or account locked — check ClassCharts login in a browser |
| Events duplicating | Old GAS-created events have no fingerprint tag; they are invisible to this script. Delete them manually once, then this script manages everything going forward |
| No lessons returned | ClassCharts may be unavailable or the school hasn't published the timetable for that week yet |

---

## How pupils are discovered

The script automatically fetches all pupils from your ClassCharts account at runtime. For each pupil, it:

1. Reads their full name and first name from ClassCharts
2. Looks for an environment variable named `GCAL_ID_<FIRSTNAME>` (case-insensitive match on first name)
3. If found, syncs that pupil's timetable into the corresponding Google Calendar
4. If not found, skips that pupil (no error, just skipped)

**This means:**
- Adding a new child to ClassCharts will automatically sync them on the next run (as long as you've added the `GCAL_ID_<FIRSTNAME>` variable)
- Removing a child from ClassCharts will stop syncing them (but won't delete their events)
- The script source code contains no hardcoded names — it's safe to make the repo public
