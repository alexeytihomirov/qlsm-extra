"""Settings of the host-metrics addon -> the collector's config.json, the verdict knobs and
the bell notification switches.

Pure and stdlib only: values arrive as strings (manifest `string` settings) or numbers; a bad
value raises ValueError naming the field, so nothing unchecked reaches config.json.
"""
import json
from pathlib import Path

ADDON_DIR = Path(__file__).resolve().parent

DB_PATH = '/var/lib/host-metrics/metrics.db'
REDIS_SOCKET = '/var/run/redis/redis.sock'
REDIS_DB = 1  # fallback only: the collector reads each instance's db from its cmdline (qlx_redisDatabase)

# key -> (default, minimum, maximum)
THRESHOLD_FIELDS = {
    'core_saturated_pct': (95, 0, 100),
    'steal_event_pct': (10, 0, 100),
    'mem_low_pct': (10, 0, 100),
    'disk_low_pct': (90, 0, 100),
    'frames_late_pct': (1, 0, 100),
    'frame_gap_ms': (100, 1, 3600),
    'event_window_s': (60, 1, 3600),
}
VERDICT_FIELDS = {
    'verdict_target_pct': (70, 0, 100),
    'mem_reserve_pct': (20, 0, 100),
    'steal_tight_pct': (5, 0, 100),
    'steal_overload_pct': (15, 0, 100),
}
FIELDS = dict(THRESHOLD_FIELDS, **VERDICT_FIELDS)
DEFAULTS = {key: str(spec[0]) for key, spec in FIELDS.items()}
# Bell notifications (qlsm cores with ctx.notify): backend only, never in config.json.
NOTIFY_SEVERITIES = ('info', 'warning', 'critical')
NOTIFY_DEFAULTS = {'notify_enabled': True, 'notify_min_severity': 'warning'}
EDITABLE_KEYS = tuple(FIELDS) + tuple(NOTIFY_DEFAULTS)


def addon_version():
    manifest = json.loads((ADDON_DIR / 'qlsm-addon.json').read_text(encoding='utf-8'))
    return manifest['version']


def _number(values, key):
    default, low, high = FIELDS[key]
    message = f'{key} must be a whole number from {low} to {high}.'
    raw = values.get(key)
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return default
    if isinstance(raw, bool) or not isinstance(raw, (int, str)):
        raise ValueError(message)
    text = str(raw).strip()
    if not (text.isascii() and text.isdigit()):
        raise ValueError(message)
    number = int(text)
    if not low <= number <= high:
        raise ValueError(message)
    return number


def _notify_enabled(values):
    raw = values.get('notify_enabled')
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return NOTIFY_DEFAULTS['notify_enabled']
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str) and raw.strip().lower() in ('true', 'false', '1', '0'):
        return raw.strip().lower() in ('true', '1')
    raise ValueError('notify_enabled must be true or false.')


def _notify_min_severity(values):
    raw = values.get('notify_min_severity')
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return NOTIFY_DEFAULTS['notify_min_severity']
    text = raw.strip().lower() if isinstance(raw, str) else None
    if text not in NOTIFY_SEVERITIES:
        raise ValueError('notify_min_severity must be one of: %s.' % ', '.join(NOTIFY_SEVERITIES))
    return text


def notify_settings(values):
    """(enabled, minimum severity) of the bell notifications. Raises ValueError naming the field."""
    return _notify_enabled(values), _notify_min_severity(values)


def validate_settings(values):
    """Every editable key checked; returns {key: int} for the numbers plus notify_enabled
    (bool) and notify_min_severity (str). Raises ValueError naming the field."""
    checked = {key: _number(values, key) for key in FIELDS}
    checked['notify_enabled'], checked['notify_min_severity'] = notify_settings(values)
    return checked


def collector_config(values):
    """The config.json dict for hm_collect.py."""
    return {
        'db_path': DB_PATH,
        'redis_socket': REDIS_SOCKET,
        'redis_db': REDIS_DB,
        'thresholds': {key: _number(values, key) for key in THRESHOLD_FIELDS},
        'version': addon_version(),
    }


def verdict_settings(values):
    """The knobs of verdict.verdict(): backend only, never written to config.json."""
    return {key: float(_number(values, key)) for key in VERDICT_FIELDS}
