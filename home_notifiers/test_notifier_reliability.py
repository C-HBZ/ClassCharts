import contextlib
import io
import os
import sys
import tempfile
import types
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

import requests

import calendar_home_notifier
import homework_notifier
import notifier_reliability


VALID_ICAL = b"""BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:test-event
DTSTART;VALUE=DATE:20261127
SUMMARY:Homework
END:VEVENT
END:VCALENDAR
"""


class FakeResponse:
    def __init__(self, content, status_code=200):
        self.content = content
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            error = requests.HTTPError(f'HTTP {self.status_code}')
            error.response = self
            raise error


class NotifierReliabilityTests(unittest.TestCase):
    def test_calendar_retries_transient_failure_and_caches_valid_feed(self):
        with tempfile.TemporaryDirectory() as directory:
            cache_path = Path(directory) / 'calendar.ics'
            with patch.object(
                notifier_reliability.requests,
                'get',
                side_effect=[
                    requests.ConnectionError('temporary DNS failure'),
                    FakeResponse(VALID_ICAL),
                ],
            ) as get, patch.object(notifier_reliability.time, 'sleep'):
                calendar = notifier_reliability.fetch_calendar(
                    'https://calendar.example/feed',
                    cache_path=cache_path,
                )

            self.assertEqual(get.call_count, 2)
            self.assertEqual(str(calendar.walk('VEVENT')[0]['SUMMARY']), 'Homework')
            self.assertEqual(cache_path.read_bytes(), VALID_ICAL)

    def test_calendar_uses_fresh_cache_after_transient_failures(self):
        with tempfile.TemporaryDirectory() as directory:
            cache_path = Path(directory) / 'calendar.ics'
            cache_path.write_bytes(VALID_ICAL)
            output = io.StringIO()

            with patch.object(
                notifier_reliability.requests,
                'get',
                side_effect=requests.ConnectionError('network down'),
            ), patch.object(notifier_reliability.time, 'sleep'), contextlib.redirect_stdout(output):
                calendar = notifier_reliability.fetch_calendar(
                    'https://calendar.example/feed',
                    cache_path=cache_path,
                )

            self.assertEqual(str(calendar.walk('VEVENT')[0]['SUMMARY']), 'Homework')
            self.assertIn('WARNING: using cached calendar', output.getvalue())

    def test_calendar_refuses_stale_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            cache_path = Path(directory) / 'calendar.ics'
            cache_path.write_bytes(VALID_ICAL)
            old_time = notifier_reliability.time.time() - 40 * 60 * 60
            os.utime(cache_path, (old_time, old_time))

            with patch.object(
                notifier_reliability.requests,
                'get',
                side_effect=requests.ConnectionError('network down'),
            ), patch.object(notifier_reliability.time, 'sleep'):
                with self.assertRaisesRegex(RuntimeError, 'no valid cached calendar'):
                    notifier_reliability.fetch_calendar(
                        'https://calendar.example/feed',
                        cache_path=cache_path,
                    )

    def test_calendar_does_not_retry_permanent_http_error(self):
        with patch.object(
            notifier_reliability.requests,
            'get',
            return_value=FakeResponse(b'', status_code=404),
        ) as get:
            with self.assertRaisesRegex(RuntimeError, 'HTTP 404'):
                notifier_reliability.fetch_calendar(
                    'https://calendar.example/feed',
                    cache_path=Path('/nonexistent/cache.ics'),
                )

        self.assertEqual(get.call_count, 1)

    def test_online_tts_failure_falls_back_to_offline_audio(self):
        fake_gtts = types.ModuleType('gtts')
        fake_gtts.__path__ = []
        fake_tts = types.ModuleType('gtts.tts')

        class FakeGTTSError(Exception):
            pass

        fake_tts.gTTSError = FakeGTTSError
        output = io.StringIO()

        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(sys.modules, {'gtts': fake_gtts, 'gtts.tts': fake_tts}), \
                    patch.object(
                        notifier_reliability,
                        '_generate_online_audio',
                        side_effect=FakeGTTSError('unavailable'),
                    ), patch.object(
                        notifier_reliability,
                        '_generate_offline_audio',
                        return_value=(str(Path(directory) / 'announcement.wav'), 'audio/wav'),
                    ) as offline, contextlib.redirect_stdout(output):
                result = notifier_reliability.generate_audio(
                    'Hello',
                    Path(directory) / 'announcement.mp3',
                )

        self.assertEqual(result[1], 'audio/wav')
        offline.assert_called_once()
        self.assertIn('using offline speech', output.getvalue())

    def test_online_tts_retries_then_returns_mp3(self):
        fake_gtts = types.ModuleType('gtts')
        fake_gtts.__path__ = []
        fake_tts = types.ModuleType('gtts.tts')
        save_attempts = []
        tts_calls = []

        class FakeGTTSError(Exception):
            pass

        class FakeGtts:
            def __init__(self, text, lang, tld):
                tts_calls.append((text, lang, tld))

            def save(self, path):
                save_attempts.append(path)
                if len(save_attempts) < 3:
                    raise FakeGTTSError('temporary service error')
                Path(path).write_bytes(b'mp3 audio')

        fake_gtts.gTTS = FakeGtts
        fake_tts.gTTSError = FakeGTTSError

        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / 'announcement.mp3'
            with patch.dict(sys.modules, {'gtts': fake_gtts, 'gtts.tts': fake_tts}), \
                    patch.object(notifier_reliability.time, 'sleep'):
                result = notifier_reliability.generate_audio(
                    'Hello',
                    output_path,
                    tld='com.au',
                )

            self.assertEqual(result, (str(output_path), 'audio/mp3'))
            self.assertEqual(len(save_attempts), 3)
            self.assertEqual(tts_calls, [('Hello', 'en', 'com.au')] * 3)
            self.assertEqual(output_path.read_bytes(), b'mp3 audio')

    def test_offline_tts_creates_wav_and_returns_cast_mime_type(self):
        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / 'announcement.mp3'

            def write_wav(command, **kwargs):
                self.assertEqual(kwargs['input'], 'Hello')
                Path(command[2]).write_bytes(b'wav audio')

            with patch.object(notifier_reliability.shutil, 'which', return_value='/usr/bin/espeak-ng'), \
                    patch.object(notifier_reliability.subprocess, 'run', side_effect=write_wav):
                result = notifier_reliability._generate_offline_audio(
                    'Hello',
                    output_path,
                )

            self.assertEqual(result, (str(output_path.with_suffix('.wav')), 'audio/wav'))
            self.assertEqual(output_path.with_suffix('.wav').read_bytes(), b'wav audio')

    def test_success_marker_is_date_specific_and_atomic(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(Path, 'home', return_value=Path(directory)):
                self.assertFalse(
                    notifier_reliability.already_succeeded(
                        'homework',
                        date(2026, 11, 27),
                    )
                )
                notifier_reliability.record_success(
                    'homework',
                    date(2026, 11, 27),
                )
                self.assertTrue(
                    notifier_reliability.already_succeeded(
                        'homework',
                        date(2026, 11, 27),
                    )
                )
                self.assertFalse(
                    notifier_reliability.already_succeeded(
                        'homework',
                        date(2026, 11, 28),
                    )
                )

    def test_notifier_logging_timestamps_output_and_prunes_expired_archives(self):
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / 'homework.log'
            expired_archive = Path(f'{log_path}.old')
            expired_archive.write_text('old log')
            old_time = notifier_reliability.time.time() - 6 * 24 * 60 * 60
            os.utime(expired_archive, (old_time, old_time))

            def failing_run():
                print('Checking homework...')
                raise RuntimeError('speaker unavailable')

            with patch.object(sys, 'stdout', io.StringIO()), \
                    patch.object(sys, 'stderr', io.StringIO()):
                result = notifier_reliability.run_with_logging(
                    'logging_test',
                    failing_run,
                    log_path=log_path,
                    retention_days=5,
                )

            log_lines = log_path.read_text().splitlines()
            self.assertEqual(result, 1)
            self.assertFalse(expired_archive.exists())
            self.assertTrue(any('Checking homework...' in line for line in log_lines))
            self.assertTrue(any('RuntimeError: speaker unavailable' in line for line in log_lines))
            for line in log_lines:
                self.assertRegex(
                    line,
                    r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}[+-]\d{4} (INFO|ERROR) ',
                )

    def test_speaker_ips_deduplicate_and_playback_continues_after_device_failure(self):
        speaker_ips = notifier_reliability.parse_speaker_ips(
            ' 192.168.1.21, 192.168.1.22, 192.168.1.23,192.168.1.21 '
        )
        first_cast = types.SimpleNamespace(
            cast_info=types.SimpleNamespace(host='192.168.1.21')
        )
        second_cast = types.SimpleNamespace(
            cast_info=types.SimpleNamespace(host='192.168.1.22')
        )
        browser = object()
        announced_ips = []
        output = io.StringIO()

        def announce(cast, speaker_ip):
            announced_ips.append(speaker_ip)
            if speaker_ip == '192.168.1.21':
                raise OSError('speaker unavailable')

        with patch(
            'pychromecast.get_chromecasts',
            return_value=([first_cast, second_cast], browser),
        ) as get_chromecasts, patch(
            'pychromecast.discovery.stop_discovery'
        ) as stop_discovery, contextlib.redirect_stdout(output):
            result = notifier_reliability.play_on_speakers(
                speaker_ips,
                announce,
            )

        self.assertEqual(
            speaker_ips,
            ('192.168.1.21', '192.168.1.22', '192.168.1.23'),
        )
        self.assertEqual(result, 1)
        self.assertEqual(announced_ips, ['192.168.1.21', '192.168.1.22'])
        get_chromecasts.assert_called_once_with(
            known_hosts=['192.168.1.21', '192.168.1.22', '192.168.1.23'],
            tries=1,
            retry_wait=1,
            timeout=5,
        )
        stop_discovery.assert_called_once_with(browser)
        self.assertIn('No Chromecast responded', output.getvalue())
        self.assertIn('Playback failed at 192.168.1.21', output.getvalue())

    def test_calendar_test_playback_does_not_record_success_marker(self):
        with patch.object(sys, 'argv', ['calendar_home_notifier.py', '--test-playback']), \
                patch.object(calendar_home_notifier, 'already_succeeded', return_value=True) as already_succeeded, \
                patch.object(calendar_home_notifier, 'fetch_todays_matching_titles', return_value=[]), \
                patch.object(calendar_home_notifier, 'generate_tts', return_value=('audio.mp3', 'audio/mp3')), \
                patch.object(calendar_home_notifier, 'cast_to_speaker') as cast, \
                patch.object(calendar_home_notifier, 'record_success') as record_success:
            calendar_home_notifier.main()

        already_succeeded.assert_not_called()
        cast.assert_called_once_with('audio.mp3', 'audio/mp3')
        record_success.assert_not_called()

    def test_homework_test_playback_does_not_record_success_marker(self):
        with patch.object(sys, 'argv', ['homework_notifier.py', '--test-playback']), \
                patch.object(homework_notifier, 'already_succeeded', return_value=True) as already_succeeded, \
                patch.object(homework_notifier, 'fetch_tomorrows_homework', return_value=([], [])), \
                patch.object(homework_notifier, 'generate_tts', return_value=('audio.mp3', 'audio/mp3')), \
                patch.object(homework_notifier, 'cast') as cast, \
                patch.object(homework_notifier, 'record_success') as record_success:
            homework_notifier.main()

        already_succeeded.assert_not_called()
        cast.assert_called_once_with('audio.mp3', 'audio/mp3')
        record_success.assert_not_called()


if __name__ == '__main__':
    unittest.main()
