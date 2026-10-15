"""The VPS's SSH host keys: scanned from qlsm, pinned as a setting.

scan() runs `ssh-keyscan` in the qlsm container when the operator saves a new
VPS address (or asks for a re-scan); the result is stored as the setting
`vps_known_hosts` and becomes the hosts' known_hosts file. fingerprints()
gives the SHA256 fingerprints the operator compares once with the provider
console, computed here from the key blobs (no ssh-keygen needed).
"""
import base64
import binascii
import hashlib
import subprocess

KEY_TYPES = 'ed25519,ecdsa,rsa'
_TYPE_NAMES = {
    'ssh-ed25519': 'ED25519',
    'ssh-rsa': 'RSA',
    'ecdsa-sha2-nistp256': 'ECDSA',
    'ecdsa-sha2-nistp384': 'ECDSA',
    'ecdsa-sha2-nistp521': 'ECDSA',
}


class HostKeyScanError(Exception):
    """ssh-keyscan failed, timed out or returned no key."""


def _key_lines(text):
    """(host, type, blob) of every well-formed known_hosts line; comments dropped."""
    out = []
    for line in (text or '').splitlines():
        fields = line.split()
        if len(fields) != 3 or line.lstrip().startswith('#') or fields[1] not in _TYPE_NAMES:
            continue
        try:
            blob = base64.b64decode(fields[2], validate=True)
        except (binascii.Error, ValueError):
            continue
        if blob:
            out.append((fields[0], fields[1], blob))
    return out


def known_hosts_lines(text):
    """The canonical known_hosts text: one `host type key` line each, LF-terminated."""
    lines = [f'{host} {kind} {base64.b64encode(blob).decode()}' for host, kind, blob in _key_lines(text)]
    return ''.join(line + '\n' for line in lines)


def scan(host, timeout=10):
    """known_hosts lines of `host`, or HostKeyScanError."""
    if not host or host.startswith('-'):
        raise HostKeyScanError('no valid VPS address')
    args = ['ssh-keyscan', '-T', str(timeout), '-t', KEY_TYPES, host]
    try:
        # -T is per connection and ssh-keyscan opens one per key type.
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout * 3 + 5)
    except FileNotFoundError:
        raise HostKeyScanError('ssh-keyscan is not installed in the qlsm container (openssh-client)')
    except subprocess.TimeoutExpired:
        raise HostKeyScanError(f'ssh-keyscan timed out after {timeout * 3 + 5} seconds')
    if result.returncode != 0:
        detail = (result.stderr or '').strip().splitlines()
        raise HostKeyScanError(f'ssh-keyscan exited with {result.returncode}'
                               + (f': {detail[-1][:200]}' if detail else ''))
    text = known_hosts_lines(result.stdout)
    if not text:
        raise HostKeyScanError('ssh-keyscan returned no host key')
    return text


def fingerprints(known_hosts):
    """`"ED25519 SHA256:<base64, no padding>"` for every key line, in order."""
    out = []
    for _host, kind, blob in _key_lines(known_hosts):
        digest = base64.b64encode(hashlib.sha256(blob).digest()).decode().rstrip('=')
        out.append(f'{_TYPE_NAMES[kind]} SHA256:{digest}')
    return out
