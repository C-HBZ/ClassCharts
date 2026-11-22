#!/usr/bin/env python3
"""
Daily Google Calendar -> Google Home TTS announcer.

Fetches today's events from a Google Calendar public iCal feed,
filters for Lewis and Austin, generates spoken audio and plays
it through a Google Home / Chromecast speaker.

Can be run standalone on a Raspberry Pi.
"""

import argparse
import os
import re
import socket
import tempfile
import threading
import time
from datetime import date
from http.server import HTTPServer, SimpleHTTPRequestHandler

import requests
import recurring_ical_events
from icalendar import Calendar

# ------------------------------------------------------------
# Configuration
# ------------------------------------------------------------

CALENDAR_ICAL_URL = os.environ.get('CALENDAR_ICAL_URL')

if not CALENDAR_ICAL_URL:
    raise RuntimeError('Missing environment variable: CALENDAR_ICAL_URL')

SPEAKER_NAME = os.getenv('HOME_SPEAKER_NAME', 'Lounge speaker')
SPEAKER_IP = os.getenv('HOME_SPEAKER_IP', '')

KEYWORDS = re.compile(r'lewis|austin', re.IGNORECASE)
CHILD_NAME = re.compile(r'\b(lewis|austin)\b', re.IGNORECASE)
HOMEWORK_KEYWORD = re.compile(r'homework', re.IGNORECASE)

SERVE_PORT = 8090
TTS_FILE = os.path.join(tempfile.gettempdir(), 'cal_announcement.mp3')

# ------------------------------------------------------------
# Calendar
# ------------------------------------------------------------

def _fetch_calendar():
    try:
        response = requests.get(CALENDAR_ICAL_URL, timeout=15)
        response.raise_for_status()
    except requests.RequestException:
        raise RuntimeError(
            'Could not retrieve the calendar feed; check the network and '
            'CALENDAR_ICAL_URL configuration.'
        ) from None

    try:
        return Calendar.from_ical(response.content)
    except ValueError:
        raise RuntimeError(
            'Could not parse the calendar feed; check that it is a valid iCal feed.'
        ) from None


def debug_dump_events():
    """Print every event occurring today, including recurrences."""

    cal = _fetch_calendar()
    today = date.today()

    print(f'--- DEBUG: today = {today} ---')

    events = recurring_ical_events.of(cal).at(today)

    for component in events:
        summary = str(component.get('SUMMARY', '')).strip()
        dtstart = component.get('DTSTART')
        dtend = component.get('DTEND')

        start_raw = dtstart.dt if dtstart else 'N/A'
        end_raw = dtend.dt if dtend else 'N/A'

        print(
            f'  EVENT: "{summary}" | '
            f'start={start_raw} | end={end_raw}'
        )

    print('--- END DEBUG ---')


def parse_event_description(component):
    description = str(component.get('DESCRIPTION', '') or '')
    description = description.replace('\\n', '\n').replace('\\N', '\n')
    fields = {}

    for line in description.splitlines():
        match = re.match(
            r'^\s*(Pupil|Subject|Title|Due)\s*:\s*(.*?)\s*$',
            line,
            re.IGNORECASE
        )
        if match:
            fields[match.group(1).lower()] = match.group(2)

    return fields


def _child_name(value):
    match = CHILD_NAME.search(value or '')
    return match.group(1).capitalize() if match else None


def _is_homework_event(summary, fields):
    return bool(
        HOMEWORK_KEYWORD.search(summary)
        or all(fields.get(field) for field in ('pupil', 'subject', 'title'))
    )


def _format_homework(fields, due_label):
    subject = fields.get('subject', '').replace('_', ' ').strip()
    title = fields.get('title', '').replace('_', ' ').strip()

    if not subject or not title:
        return None

    return f'Homework for {subject}, "{title}", due {due_label}'


def fetch_todays_matching_titles():
    cal = _fetch_calendar()
    today = date.today()

    events = recurring_ical_events.of(cal).at(today)

    titles = []

    for component in events:
        summary = str(component.get('SUMMARY', '')).strip()
        fields = parse_event_description(component)

        if _is_homework_event(summary, fields):
            if fields.get('pupil'):
                child = _child_name(fields['pupil'])
            else:
                child = _child_name(summary)

            if not child:
                continue

            homework = _format_homework(fields, 'today')
            titles.append(f'{child}. {homework}' if homework else summary)
        elif KEYWORDS.search(summary):
            titles.append(summary)

    return titles

# ------------------------------------------------------------
# Message builder
# ------------------------------------------------------------

def build_message(titles):
    count = len(titles)

    if count == 0:
        return 'There are 0 events today for the boys.'

    return (
        f'There are {count} events today for the boys. '
        f'{", ".join(titles)}'
    )

# ------------------------------------------------------------
# Text to speech
# ------------------------------------------------------------

def generate_tts(message):
    from gtts import gTTS

    print('[tts] Generating audio...')

    gTTS(text=message, lang='en').save(TTS_FILE)

    print(f'[tts] Saved to {TTS_FILE}')

# ------------------------------------------------------------
# Chromecast
# ------------------------------------------------------------

def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    try:
        s.connect(('8.8.8.8', 80))
        return s.getsockname()[0]

    finally:
        s.close()


def _serve_file(filepath, port, duration=90):
    directory = os.path.dirname(filepath)

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(
                *args,
                directory=directory,
                **kwargs
            )

        def log_message(self, fmt, *args):
            pass

    server = HTTPServer(('', port), Handler)

    t = threading.Timer(duration, server.shutdown)
    t.start()

    server.serve_forever()


def cast_to_speaker(message):
    import pychromecast

    local_ip = get_local_ip()

    filename = os.path.basename(TTS_FILE)

    audio_url = (
        f'http://{local_ip}:{SERVE_PORT}/{filename}'
    )

    thread = threading.Thread(
        target=_serve_file,
        args=(TTS_FILE, SERVE_PORT),
        daemon=True,
    )

    thread.start()

    time.sleep(0.5)

    kwargs = {
        'friendly_names': [SPEAKER_NAME],
        'timeout': 15
    }

    if SPEAKER_IP:
        print(
            f'[cast] Connecting to {SPEAKER_NAME} '
            f'at {SPEAKER_IP}...'
        )
        kwargs['known_hosts'] = [SPEAKER_IP]

    else:
        print(
            f'[cast] Discovering "{SPEAKER_NAME}" '
            'on network...'
        )

    chromecasts, browser = (
        pychromecast.get_listed_chromecasts(**kwargs)
    )

    if not chromecasts:
        pychromecast.discovery.stop_discovery(browser)

        raise RuntimeError(
            f'Could not find "{SPEAKER_NAME}". '
            'Check the speaker is powered on and accessible.'
        )

    cast = chromecasts[0]

    cast.wait()

    pychromecast.discovery.stop_discovery(browser)

    print(
        f'[cast] Connected to {cast.name}. '
        f'Playing {audio_url}'
    )

    mc = cast.media_controller

    mc.play_media(audio_url, 'audio/mp3')

    mc.block_until_active(timeout=15)

    time.sleep(2)

    while cast.media_controller.status.player_is_playing:
        time.sleep(1)

    cast.quit_app()

    print('[cast] Playback complete.')

# ------------------------------------------------------------
# Main
# ------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description='Announce boys calendar events on Google Home'
    )

    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Fetch calendar and print message only.'
    )

    parser.add_argument(
        '--debug',
        action='store_true',
        help='Print all events found in the calendar.'
    )

    args = parser.parse_args()

    print('Fetching calendar...')

    if args.debug:
        debug_dump_events()

    titles = fetch_todays_matching_titles()

    message = build_message(titles)

    print(f'Message: {message}')

    if args.dry_run:
        print('[dry-run] Skipping cast.')
        return

    generate_tts(message)

    cast_to_speaker(message)


if __name__ == '__main__':
    main()
