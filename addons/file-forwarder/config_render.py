"""Turn the addon's settings into forwarder.conf and the sync playbook's vars.

Pure functions, no qlsm imports: the conf file is sourced by `sh` on the game
host (assets/forwarder.sh), so every value is checked against a strict
character set here and written single-quoted. A bad value raises ValueError
with a message naming the setting; it never reaches a host.

The variable names and defaults are the ones forwarder.sh's header documents.
"""
import json
import os
import re

ADDON_DIR = os.path.dirname(os.path.abspath(__file__))

# Pinned defaults of the addon, not settings (an addon release changes them).
SFTP_USER = 'qldemos-in'
REMOTE_NAME = 'qldemos'
SRC_GLOBS = '/home/ql/qlds-*/demos'
STATE_DIR = '/home/ql/.forwarder-state'
MIN_AGE_MIN = 2
DELIVERED_GRACE_HOURS = 24
MAX_RAW_REMOTE_MB = 5000
RCLONE = 'rclone'
MANIFEST_FILE = os.path.join(ADDON_DIR, 'qlsm-addon.json')

# Rows are separated by ";" or a newline: qlsm's declarative form renders a
# string setting as a one-line <input>, which drops newlines.
DEFAULT_PATTERNS = '*.qlmatch qlmatch keep; *.replay.json.gz qlmatch keep; *.dm_91 raw expire'

# No default VPS address: each install types its own once, and saving it
# scans and pins that host's SSH keys (`vps_known_hosts`, see hostkeys.py).
DEFAULTS = {
    'vps_host': '',
    'retention_days': '14',
    'max_raw_mb_per_run': '2048',
    'interval_minutes': '10',
    'patterns': DEFAULT_PATTERNS,
}
EDITABLE_KEYS = tuple(DEFAULTS)
KNOWN_HOSTS_SETTING = 'vps_known_hosts'

# The rest of a pinned known_hosts line after the host name.
_KEY_LINE_TAIL = r' (ssh-ed25519|ecdsa-sha2-nistp(256|384|521)|ssh-rsa) [A-Za-z0-9+/]+={0,2}'

NOT_CONFIGURED = ('The VPS address or its host keys are not set (or not valid): enter the address in '
                  'Settings -> Addons -> File Forwarder and save, so its host keys are scanned. '
                  'Apply to host refuses until then.')

# key -> (label, min, max)
_INT_FIELDS = {
    'retention_days': ('retention_days', 1, 3650),
    'max_raw_mb_per_run': ('max_raw_mb_per_run', 1, 1048576),
    'interval_minutes': ('interval_minutes', 1, 1440),
}

# A find(1) -name glob: no path separator, whitespace, quote, `:` (the row
# separator in PATTERNS) or shell metacharacter.
_GLOB_RE = re.compile(r'^[A-Za-z0-9_.*?\[\]-]+$')
# forwarder.sh refuses anything else (and a leading `.` or `-`); `..` is
# refused here too, anywhere in the name.
_REMOTE_DIR_RE = re.compile(r'^[A-Za-z0-9_][A-Za-z0-9_.-]*$')
_KINDS = ('keep', 'expire')
# A DNS name or an IPv4 address.
_HOST_RE = re.compile(r'^[A-Za-z0-9]([A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$')


def _int_setting(settings, key):
    label, low, high = _INT_FIELDS[key]
    value = settings.get(key, DEFAULTS[key])
    if isinstance(value, bool):
        raise ValueError(f'{label} must be a whole number')
    if isinstance(value, int):
        number = value
    elif isinstance(value, str) and re.fullmatch(r' *[0-9]{1,9} *', value):
        number = int(value)
    else:
        raise ValueError(f'{label} must be a whole number')
    if not low <= number <= high:
        raise ValueError(f'{label} must be between {low} and {high}')
    return number


def parse_patterns(text):
    """`glob remote_dir keep|expire` rows -> [(glob, remote_dir, kind)]."""
    if not isinstance(text, str):
        raise ValueError('patterns must be text')
    rows = []
    for raw in re.split(r'[;\n]', text):
        fields = raw.split()
        if not fields:
            continue
        if len(fields) != 3:
            raise ValueError(f'pattern row "{raw.strip()}" must be: glob remote_dir keep|expire')
        glob, remote_dir, kind = fields
        if not _GLOB_RE.match(glob):
            raise ValueError(f'pattern glob "{glob}" may only use letters, digits and _ . * ? [ ] -')
        if not _REMOTE_DIR_RE.match(remote_dir) or '..' in remote_dir:
            raise ValueError(f'remote_dir "{remote_dir}" may only use A-Za-z0-9_.- '
                             '(no leading . or -, no ..)')
        if kind not in _KINDS:
            raise ValueError(f'pattern row "{raw.strip()}" must end in keep or expire')
        rows.append((glob, remote_dir, kind))
    if not rows:
        raise ValueError('patterns must hold at least one row')
    return rows


def format_patterns(rows):
    """The canonical stored form of a pattern table."""
    return '; '.join(' '.join(row) for row in rows)


def _vps_host(settings):
    host = settings.get('vps_host', DEFAULTS['vps_host'])
    if not isinstance(host, str) or not _HOST_RE.match(host.strip()):
        raise ValueError('vps_host must be a host name or an IPv4 address')
    # Lowercase: ssh-keyscan prints the host lowercased, and known_hosts()
    # matches the stored lines against this exact name.
    return host.strip().lower()


def validate_settings(settings):
    """Every editable setting checked and normalized, or ValueError."""
    return {
        'vps_host': _vps_host(settings),
        'retention_days': _int_setting(settings, 'retention_days'),
        'max_raw_mb_per_run': _int_setting(settings, 'max_raw_mb_per_run'),
        'interval_minutes': _int_setting(settings, 'interval_minutes'),
        'patterns': parse_patterns(settings.get('patterns', DEFAULTS['patterns'])),
    }


def render_conf(settings):
    """forwarder.conf text for the given settings."""
    values = validate_settings(settings)
    patterns = ' '.join(':'.join(row) for row in values['patterns'])
    lines = [
        '# Written by the qlsm file-forwarder addon from its settings. Do not edit on the',
        '# host: "Apply to host" and every host setup overwrite this file.',
        f"REMOTE='{REMOTE_NAME}'",
        f"SRC_GLOBS='{SRC_GLOBS}'",
        f"PATTERNS='{patterns}'",
        f"RETENTION_DAYS='{values['retention_days']}'",
        f"DELIVERED_GRACE_HOURS='{DELIVERED_GRACE_HOURS}'",
        f"MIN_AGE_MIN='{MIN_AGE_MIN}'",
        f"MAX_RAW_MB_PER_RUN='{values['max_raw_mb_per_run']}'",
        f"MAX_RAW_REMOTE_MB='{MAX_RAW_REMOTE_MB}'",
        f"STATE_DIR='{STATE_DIR}'",
        f"RCLONE='{RCLONE}'",
    ]
    return '\n'.join(lines) + '\n'


def known_hosts(settings):
    """The pinned known_hosts text for the configured address, or ValueError(NOT_CONFIGURED).

    Every line must be exactly `<vps_host> <key type> <base64>`: keys scanned
    for an earlier address never reach a host, and nothing else does either.
    Core's generic state route can write `vps_known_hosts` directly, and the
    text becomes an Ansible extravar (`copy: content:`), so a `{{ ... }}` in
    it would be templated there.
    """
    host = settings.get('vps_host')
    host = host.strip().lower() if isinstance(host, str) else ''
    text = settings.get(KNOWN_HOSTS_SETTING)
    text = text if isinstance(text, str) else ''
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not host or not _HOST_RE.match(host) or not lines:
        raise ValueError(NOT_CONFIGURED)
    line_re = re.compile(re.escape(host) + _KEY_LINE_TAIL)
    if not all(line_re.fullmatch(line) for line in lines):
        raise ValueError(NOT_CONFIGURED)
    return '\n'.join(lines) + '\n'


def vps_ready(settings):
    """An address is set and its host keys are pinned."""
    try:
        known_hosts(settings)
    except ValueError:
        return False
    return True


def addon_version():
    with open(MANIFEST_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)['version']


def playbook_vars(settings):
    """Everything sync_file_forwarder.yml needs.

    Holds the private key (`ff_private_key`). The caller must NOT pass this
    dict to a playbook as extravars: qlsm's ansible runner logs the whole
    `-e` JSON. backend.py writes the key to a 0600 file and passes its path
    as `ff_private_key_file` instead.
    """
    private = (settings.get('sftp_private_key') or '').strip()
    if not private:
        raise ValueError('the SFTP key has not been generated yet')
    pinned = known_hosts(settings)
    values = validate_settings(settings)
    return {
        'ff_conf_text': render_conf(settings),
        # OpenSSH refuses a private key file without its final newline.
        'ff_private_key': private + '\n',
        'ff_known_hosts': pinned,
        'ff_version': addon_version(),
        'ff_interval_minutes': values['interval_minutes'],
        'ff_vps_host': values['vps_host'],
        'ff_sftp_user': SFTP_USER,
        'ff_remote_name': REMOTE_NAME,
    }
