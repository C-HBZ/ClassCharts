#!/bin/bash

set -e

REPO="https://raw.githubusercontent.com/C-HBZ/ClassCharts/main/home_notifiers"
DEST="/home/pi/home_notifiers"

mkdir -p "$DEST"

echo "Updating home notifier scripts..."

wget -q -O "$DEST/calendar_home_notifier.py" "$REPO/calendar_home_notifier.py"
wget -q -O "$DEST/homework_notifier.py" "$REPO/homework_notifier.py"
wget -q -O "$DEST/requirements.txt" "$REPO/requirements.txt"

echo "Home notifier scripts successfully updated."
