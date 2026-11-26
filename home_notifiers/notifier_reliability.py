"""Shared reliability helpers for the Raspberry Pi home notifiers."""

import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import requests
from icalendar import Calendar

CALENDAR_ATTEMPTS = 3
CALENDAR_RETRY_DELAYS = (2, 5)
CALENDAR_CACHE_MAX_AGE = 36 * 60 * 60
TTS_ATTEMPTS = 3
TTS_RETRY_DELAYS = (2, 5)


def _calendar_cache_path():
    return Path.home() / '.cache' / 'home_notifiers' / 'calendar.ics'


def _parse_calendar(content):
    try:
        return Calendar.from_ical(content)
    except (TypeError, ValueError):
        return None


def _load_cached_calendar(cache_path, max_age):
    try:
        age_seconds = time.time() - cache_path.stat().st_mtime
        if age_seconds < 0 or age_seconds > max_age:
            return None

        calendar = _parse_calendar(cache_path.read_bytes())
    except OSError:
        return None

    if calendar is None:
        print('[calendar] Ignoring invalid cached calendar.')
        return None

    return calendar, age_seconds


def _save_calendar_cache(cache_path, content):
    cache_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(cache_path.parent, 0o700)

    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=cache_path.parent,
            prefix='.calendar-',
            suffix='.tmp',
            delete=False
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            os.chmod(temporary_path, 0o600)
            temporary_file.write(content)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())

        os.replace(temporary_path, cache_path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _is_transient_request_error(error):
    if isinstance(error, (requests.ConnectionError, requests.Timeout)):
        return True

    if isinstance(error, requests.HTTPError) and error.response is not None:
        status_code = error.response.status_code
        return status_code == 429 or status_code >= 500

    return False


def _request_error_label(error):
    if isinstance(error, requests.HTTPError) and error.response is not None:
        return f'HTTP {error.response.status_code}'
    return type(error).__name__


def fetch_calendar(
    ical_url,
    cache_path=None,
    max_cache_age=CALENDAR_CACHE_MAX_AGE
):
    """Fetch and parse the calendar, falling back only to a fresh valid cache."""

    cache_path = Path(cache_path or _calendar_cache_path())
    last_error = None

    for attempt in range(1, CALENDAR_ATTEMPTS + 1):
        try:
            response = requests.get(ical_url, timeout=(5, 15))
            response.raise_for_status()
        except requests.RequestException as error:
            last_error = error
            if not _is_transient_request_error(error):
                raise RuntimeError(
                    'Calendar request failed '
                    f'({_request_error_label(error)}); check '
                    'CALENDAR_ICAL_URL and the calendar service.'
                ) from None

            if attempt < CALENDAR_ATTEMPTS:
                delay = CALENDAR_RETRY_DELAYS[attempt - 1]
                print(
                    f'[calendar] Temporary request failure '
                    f'({_request_error_label(error)}); retrying in {delay}s.'
                )
                time.sleep(delay)
                continue
        else:
            calendar = _parse_calendar(response.content)
            if calendar is not None:
                _save_calendar_cache(cache_path, response.content)
                print('[calendar] Retrieved calendar and refreshed local cache.')
                return calendar

            last_error = ValueError('calendar response was not valid iCal')
            break

    cached = _load_cached_calendar(cache_path, max_cache_age)
    if cached is not None:
        calendar, age_seconds = cached
        age_hours = age_seconds / 3600
        print(
            '[calendar] WARNING: using cached calendar '
            f'{age_hours:.1f} hours old after '
            f'{_request_error_label(last_error)}.'
        )
        return calendar

    if isinstance(last_error, ValueError):
        detail = 'the server returned invalid iCal'
    else:
        detail = _request_error_label(last_error)

    raise RuntimeError(
        'Could not retrieve a valid calendar after '
        f'{CALENDAR_ATTEMPTS} attempts ({detail}); no valid cached calendar '
        f'younger than {max_cache_age / 3600:.0f} hours is available.'
    ) from None


def _temporary_audio_path(destination):
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_file = tempfile.NamedTemporaryFile(
        dir=destination.parent,
        prefix=f'.{destination.stem}-',
        suffix=destination.suffix,
        delete=False
    )
    temporary_file.close()
    return Path(temporary_file.name)


def _generate_online_audio(message, destination, tld):
    from gtts import gTTS
    from gtts.tts import gTTSError

    last_error = None
    for attempt in range(1, TTS_ATTEMPTS + 1):
        temporary_path = _temporary_audio_path(destination)
        try:
            gTTS(text=message, lang='en', tld=tld).save(str(temporary_path))
            if temporary_path.stat().st_size == 0:
                raise RuntimeError('Google TTS returned an empty audio file')
            os.replace(temporary_path, destination)
            return
        except (gTTSError, requests.RequestException) as error:
            last_error = error
            if attempt < TTS_ATTEMPTS:
                delay = TTS_RETRY_DELAYS[attempt - 1]
                print(
                    '[tts] Online speech service failed '
                    f'({type(error).__name__}); retrying in {delay}s.'
                )
                time.sleep(delay)
        finally:
            temporary_path.unlink(missing_ok=True)

    raise last_error


def _generate_offline_audio(message, destination):
    executable = shutil.which('espeak-ng') or shutil.which('espeak')
    if not executable:
        raise RuntimeError(
            'Offline speech is unavailable; install espeak-ng with '
            '`sudo apt install espeak-ng`.'
        )

    destination = Path(destination).with_suffix('.wav')
    temporary_path = _temporary_audio_path(destination)
    try:
        subprocess.run(
            [executable, '-w', str(temporary_path), '--stdin'],
            input=message,
            text=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            check=True,
            timeout=60
        )
        if temporary_path.stat().st_size == 0:
            raise RuntimeError('Offline speech returned an empty audio file')
        os.replace(temporary_path, destination)
    except subprocess.CalledProcessError as error:
        detail = (error.stderr or '').strip()
        if detail:
            detail = f': {detail[:300]}'
        raise RuntimeError(
            f'Offline speech generation failed{detail}.'
        ) from None
    except (OSError, subprocess.SubprocessError, RuntimeError) as error:
        detail = str(error).strip()
        if detail:
            detail = f': {detail[:300]}'
        raise RuntimeError(
            f'Offline speech generation failed '
            f'({type(error).__name__}){detail}.'
        ) from None
    finally:
        temporary_path.unlink(missing_ok=True)

    return str(destination), 'audio/wav'


def generate_audio(message, mp3_path, tld='com'):
    """Generate speech online with retries, then fall back to local eSpeak."""

    mp3_path = Path(mp3_path)
    print('[tts] Generating audio...')
    online_error = None

    try:
        from gtts.tts import gTTSError
    except ImportError as error:
        online_error = error
    else:
        try:
            _generate_online_audio(message, mp3_path, tld)
        except (gTTSError, requests.RequestException) as error:
            online_error = error
        except ImportError as error:
            online_error = error

    if online_error is not None:
        print(
            '[tts] Online speech unavailable '
            f'({type(online_error).__name__}); using offline speech.'
        )
        audio_path, content_type = _generate_offline_audio(message, mp3_path)
        print(f'[tts] Saved to {audio_path} ({content_type})')
        return audio_path, content_type

    print(f'[tts] Saved to {mp3_path} (audio/mp3)')
    return str(mp3_path), 'audio/mp3'


def _success_marker_path(name, scheduled_date):
    state_dir = Path.home() / '.local' / 'state' / 'home_notifiers'
    return state_dir / f'{name}-{scheduled_date.isoformat()}.success'


def already_succeeded(name, scheduled_date):
    return _success_marker_path(name, scheduled_date).is_file()


def record_success(name, scheduled_date):
    marker_path = _success_marker_path(name, scheduled_date)
    marker_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)

    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=marker_path.parent,
            prefix='.success-',
            delete=False
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            temporary_file.write(b'Playback completed successfully.\n')
            temporary_file.flush()
            os.fsync(temporary_file.fileno())

        os.replace(temporary_path, marker_path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
