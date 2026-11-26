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

import recurring_ical_events

from notifier_reliability import (
    already_succeeded,
    fetch_calendar,
    generate_audio,
    record_success,
)

# ------------------------------------------------------------
# Configuration
# ------------------------------------------------------------

CALENDAR_ICAL_URL = os.environ.get('CALENDAR_ICAL_URL')

if not CALENDAR_ICAL_URL:
    raise RuntimeError('Missing environment variable: CALENDAR_ICAL_URL')

SPEAKER_NAME = 'ALLnoOffice'

KEYWORDS = re.compile(r'lewis|austin', re.IGNORECASE)
CHILD_NAME = re.compile(r'\b(lewis|austin)\b', re.IGNORECASE)
HOMEWORK_KEYWORD = re.compile(r'homework', re.IGNORECASE)

SERVE_PORT = 8090
TTS_FILE = os.path.join(tempfile.gettempdir(), 'cal_announcement.mp3')
TTS_TLD = 'ca'

# ------------------------------------------------------------
# Calendar
# ------------------------------------------------------------

def _fetch_calendar():
    return fetch_calendar(CALENDAR_ICAL_URL)


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
    return generate_audio(message, TTS_FILE, tld=TTS_TLD)

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
            print(f'[http] {fmt % args}', flush=True)

    server = HTTPServer(('', port), Handler)

    t = threading.Timer(duration, server.shutdown)
    t.start()

    server.serve_forever()


def cast_to_speaker(audio_path, content_type):
    import pychromecast

    local_ip = get_local_ip()

    filename = os.path.basename(audio_path)

    audio_url = (
        f'http://{local_ip}:{SERVE_PORT}/{filename}'
    )

    thread = threading.Thread(
        target=_serve_file,
        args=(audio_path, SERVE_PORT),
        daemon=True,
    )

    thread.start()

    time.sleep(0.5)

    kwargs = {
        'friendly_names': [SPEAKER_NAME],
        'timeout': 15
    }

    print(f'[cast] Discovering speaker group "{SPEAKER_NAME}" on network...')

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

    print('[cast] Setting speaker volume to 50%.')
    cast.set_volume(0.5)

    mc = cast.media_controller

    mc.play_media(audio_url, content_type)

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

    parser.add_argument(
        '--force',
        action='store_true',
        help='Announce even if today has already been announced successfully.'
    )

    args = parser.parse_args()
    scheduled_date = date.today()

    if not args.dry_run and not args.force and already_succeeded(
        'calendar',
        scheduled_date
    ):
        print(
            f'[status] Calendar announcement for {scheduled_date} '
            'already completed; skipping duplicate.'
        )
        return

    print('Fetching calendar...')

    if args.debug:
        debug_dump_events()

    titles = fetch_todays_matching_titles()

    message = build_message(titles)

    print(f'Message: {message}')

    if args.dry_run:
        print('[dry-run] Skipping cast.')
        return

    audio_path, content_type = generate_tts(message)

    cast_to_speaker(audio_path, content_type)
    record_success('calendar', scheduled_date)
    print(f'[status] Success recorded for {scheduled_date}.')


if __name__ == '__main__':
    main()
