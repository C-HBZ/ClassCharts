#!/bin/bash

set -euo pipefail

REPO="https://raw.githubusercontent.com/C-HBZ/ClassCharts/main/home_notifiers"
DEST="/home/pi/home_notifiers"
UPDATER="/home/pi/update_home_notifiers.sh"

mkdir -p "$DEST"

TMP_DIR="$DEST/.update_home_notifiers.$$"
mkdir -m 700 "$TMP_DIR"

CALENDAR_TMP="$TMP_DIR/calendar_home_notifier.py"
HOMEWORK_TMP="$TMP_DIR/homework_notifier.py"
RELIABILITY_TMP="$TMP_DIR/notifier_reliability.py"
REQUIREMENTS_TMP="$TMP_DIR/requirements.txt"
UPDATER_TMP="$TMP_DIR/update_home_notifiers.sh"

cleanup() {
    rm -f \
        "$CALENDAR_TMP" \
        "$HOMEWORK_TMP" \
        "$RELIABILITY_TMP" \
        "$REQUIREMENTS_TMP" \
        "$UPDATER_TMP"
    rmdir "$TMP_DIR"
}
trap cleanup EXIT

echo "Updating home notifier scripts..."

wget -nv --tries=3 --timeout=20 -O "$CALENDAR_TMP" "$REPO/calendar_home_notifier.py"
wget -nv --tries=3 --timeout=20 -O "$HOMEWORK_TMP" "$REPO/homework_notifier.py"
wget -nv --tries=3 --timeout=20 -O "$RELIABILITY_TMP" "$REPO/notifier_reliability.py"
wget -nv --tries=3 --timeout=20 -O "$REQUIREMENTS_TMP" "$REPO/requirements.txt"
wget -nv --tries=3 --timeout=20 -O "$UPDATER_TMP" "$REPO/update_home_notifiers.sh"
chmod 755 "$UPDATER_TMP"

mv "$CALENDAR_TMP" "$DEST/calendar_home_notifier.py"
mv "$HOMEWORK_TMP" "$DEST/homework_notifier.py"
mv "$RELIABILITY_TMP" "$DEST/notifier_reliability.py"
mv "$REQUIREMENTS_TMP" "$DEST/requirements.txt"
mv "$UPDATER_TMP" "$UPDATER"

echo "Home notifier scripts and updater successfully updated."
