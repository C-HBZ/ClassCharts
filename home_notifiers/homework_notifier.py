#!/usr/bin/env python3

import argparse
import os
import re
import socket
import tempfile
import threading
import time
from datetime import date, timedelta
from http.server import HTTPServer, SimpleHTTPRequestHandler

import pychromecast
import recurring_ical_events
import requests
from gtts import gTTS
from icalendar import Calendar

# ------------------------------------------------------------
# Configuration
# ------------------------------------------------------------

CALENDAR_ICAL_URL = os.environ.get('CALENDAR_ICAL_URL')

if not CALENDAR_ICAL_URL:
    raise RuntimeError('Missing environment variable: CALENDAR_ICAL_URL')

SPEAKER_NAME = os.getenv('HOME_SPEAKER_NAME', 'Lounge speaker')
SPEAKER_IP = os.getenv('HOME_SPEAKER_IP', '')

HOMEWORK_KEYWORD = re.compile(r'homework', re.IGNORECASE)
CHILD_NAME = re.compile(r'\b(lewis|austin)\b', re.IGNORECASE)

SERVE_PORT = 8091

TTS_FILE = os.path.join(
    tempfile.gettempdir(),
    'homework.mp3'
)

# ------------------------------------------------------------
# Calendar
# ------------------------------------------------------------

def fetch_calendar():
    try:
        response = requests.get(
            CALENDAR_ICAL_URL,
            timeout=15
        )
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


def _clean_homework_title(subject, title):
    clean = title.strip()

    subject_re = re.compile(
        r'^' + re.escape(subject.strip()) + r'\s*(?:[-:]\s*)?',
        re.IGNORECASE
    )
    clean = subject_re.sub('', clean, count=1).strip()

    clean = re.sub(
        r'^homework\s*(?:[-:]\s*)?',
        '',
        clean,
        count=1,
        flags=re.IGNORECASE
    ).strip()

    clean = re.sub(r'\s*\(\d+\s*booklets?\)\s*$', '', clean, flags=re.IGNORECASE).strip()
    if re.fullmatch(r'\d+', clean):
        return ''

    return clean


def _format_homework(fields, due_label):
    subject = fields.get('subject', '').replace('_', ' ').strip()
    title = fields.get('title', '').replace('_', ' ').strip()

    if not subject or not title:
        return None

    clean_title = _clean_homework_title(subject, title)

    if not clean_title:
        return f'Homework for {subject}, due {due_label}'

    return f'Homework for {subject}, "{clean_title}", due {due_label}'


def fetch_tomorrows_homework():
    cal = fetch_calendar()

    tomorrow = date.today() + timedelta(days=1)

    events = recurring_ical_events.of(cal).at(tomorrow)

    lewis = []
    austin = []

    for component in events:
        summary = str(
            component.get('SUMMARY', '')
        ).strip()

        fields = parse_event_description(component)
        if not _is_homework_event(summary, fields):
            continue

        if fields.get('pupil'):
            child = _child_name(fields['pupil'])
        else:
            child = _child_name(summary)

        if not child:
            continue

        homework = _format_homework(fields, 'tomorrow') or summary

        if child == 'Lewis':
            lewis.append(homework)
        elif child == 'Austin':
            austin.append(homework)

    return lewis, austin

# ------------------------------------------------------------
# Message builder
# ------------------------------------------------------------

def build_message(lewis, austin):
    if not lewis and not austin:
        return 'No homework tomorrow for either Lewis or Austin'

    parts = []

    if lewis:
        parts.append(f"Lewis. {'. '.join(lewis)}")

    if austin:
        parts.append(f"Austin. {'. '.join(austin)}")

    return ' '.join(parts)

# ------------------------------------------------------------
# Text to speech
# ------------------------------------------------------------

def generate_tts(message):
    print('[tts] Generating audio...')

    gTTS(
        text=message,
        lang='en'
    ).save(TTS_FILE)

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


def serve_file(filepath, port, duration=90):
    directory = os.path.dirname(filepath)

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(
                *args,
                directory=directory,
                **kwargs
            )

        def log_message(self, fmt, *args):
            print(f'[http] {fmt % args}', flush=True)

    server = HTTPServer(('', port), Handler)

    threading.Timer(
        duration,
        server.shutdown
    ).start()

    server.serve_forever()


def cast():
    local_ip = get_local_ip()

    filename = os.path.basename(TTS_FILE)

    audio_url = (
        f'http://{local_ip}:{SERVE_PORT}/{filename}'
    )

    threading.Thread(
        target=serve_file,
        args=(TTS_FILE, SERVE_PORT),
        daemon=True
    ).start()

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
        print(f'[cast] Discovering "{SPEAKER_NAME}" on network...')

    chromecasts, browser = (
        pychromecast.get_listed_chromecasts(**kwargs)
    )

    if not chromecasts:
        pychromecast.discovery.stop_discovery(browser)
        raise RuntimeError(
            f'Could not find "{SPEAKER_NAME}". '
            'Check the speaker is powered on and accessible.'
        )

    cast_device = chromecasts[0]

    cast_device.wait()

    pychromecast.discovery.stop_discovery(browser)

    mc = cast_device.media_controller

    print(
        f'[cast] Connected to {cast_device.name}. '
        f'Playing {audio_url}'
    )

    print('[cast] Setting speaker volume to 50%.')
    cast_device.set_volume(0.5)

    mc.play_media(
        audio_url,
        'audio/mp3'
    )

    playback_deadline = time.monotonic() + 30
    while not mc.status.player_is_playing:
        if time.monotonic() >= playback_deadline:
            raise RuntimeError(
                'Chromecast did not start audio playback within 30 seconds '
                f'(player state: {mc.status.player_state}). Check that the '
                'speaker can access the Pi at the printed audio URL.'
            )
        time.sleep(0.25)

    print('[cast] Audio playback started.')

    try:
        while mc.status.player_is_playing:
            time.sleep(0.25)
    finally:
        cast_device.quit_app()

    print('[cast] Playback complete.')


# ------------------------------------------------------------
# Main
# ------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Announce Lewis and Austin's homework for tomorrow"
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Fetch tomorrow’s homework and print the message without audio or casting.'
    )
    args = parser.parse_args()

    print('Checking homework for tomorrow...')

    lewis, austin = fetch_tomorrows_homework()

    message = build_message(lewis, austin)

    print(f'Message: {message}')

    if args.dry_run:
        print('[dry-run] Skipping audio generation and cast.')
        return

    generate_tts(message)

    cast()


if __name__ == '__main__':
    main()
