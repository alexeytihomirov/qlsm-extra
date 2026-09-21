"""telemetry-relay's private copy of the ql-stats-hub *mechanics*: where the
target is stored, how a per-instance server ID is reserved, and the
server.cfg cvar helpers this feature needs.

Used to be ui/stats_hub.py in qlsm core, shared with the demo-stream addon
via a `feature` argument. Duplicated instead of kept shared once it became
clear the addon system has no way to declare or enforce a dependency between
addons: a genuinely shared module would vanish out from under both features
at once if the operator uninstalled it, instead of one of them degrading on
its own. See addons/README.md's "Where the line falls" in qlsm for the full
history. This copy and demo-stream's are free to diverge from here on --
there is no promise they stay identical, only that each keeps working for
its own feature.

State lives in the generic AppSetting key/value table, under the exact key
names this feature has used since before the split -- renaming them would
orphan every deployed database's current telemetry settings.
"""
import re

import requests

from ui import db
from ui.models import AppSetting

_URL_KEY = 'stats_hub_url'
_TOKEN_KEY = 'stats_hub_ingest_token'
_HOST_URL_PREFIX = 'telemetry_relay_host_stats_hub_url:'
_HOST_TOKEN_PREFIX = 'telemetry_relay_host_stats_hub_token:'
_SERVER_ID_PREFIX = 'stats_hub_server_id:'

RESERVE_TIMEOUT_SEC = 10


def _get(key):
    row = AppSetting.query.get(key)
    return row.value.strip() if row and row.value and row.value.strip() else None


def _set(key, value):
    """Create/update/clear a setting. Does not commit."""
    value = (value or '').strip()
    row = AppSetting.query.get(key)
    if not value:
        if row:
            db.session.delete(row)
        return
    if row:
        row.value = value
    else:
        db.session.add(AppSetting(key=key, value=value))


# ---- cluster-wide target ----------------------------------------------

def get_stats_hub_url():
    return _get(_URL_KEY)


def set_stats_hub_url(value):
    _set(_URL_KEY, (value or '').strip().rstrip('/'))


def get_stats_hub_ingest_token():
    return _get(_TOKEN_KEY)


def set_stats_hub_ingest_token(value):
    _set(_TOKEN_KEY, value)


def is_stats_hub_configured():
    return bool(get_stats_hub_url() and get_stats_hub_ingest_token())


# ---- per-host override -------------------------------------------------

def get_host_stats_hub_url(host_id):
    """This host's stats-hub URL override, or None if it inherits the
    global default."""
    return _get(f"{_HOST_URL_PREFIX}{host_id}")


def set_host_stats_hub_url(host_id, value):
    _set(f"{_HOST_URL_PREFIX}{host_id}", (value or '').strip().rstrip('/'))


def get_host_stats_hub_ingest_token(host_id):
    """This host's ingest-token override, or None if it inherits the
    global default."""
    return _get(f"{_HOST_TOKEN_PREFIX}{host_id}")


def set_host_stats_hub_ingest_token(host_id, value):
    _set(f"{_HOST_TOKEN_PREFIX}{host_id}", value)


def get_effective_stats_hub_url(host_id):
    """This host's override if set, else the global default."""
    return get_host_stats_hub_url(host_id) or get_stats_hub_url()


def get_effective_stats_hub_ingest_token(host_id):
    """This host's override if set, else the global default."""
    return get_host_stats_hub_ingest_token(host_id) or get_stats_hub_ingest_token()


def is_stats_hub_configured_for_host(host_id):
    return bool(get_effective_stats_hub_url(host_id)
                and get_effective_stats_hub_ingest_token(host_id))


# ---- per-instance server id --------------------------------------------

def get_instance_server_id(instance_id):
    value = _get(f"{_SERVER_ID_PREFIX}{instance_id}")
    return int(value) if value else None


def set_instance_server_id(instance_id, server_id):
    _set(f"{_SERVER_ID_PREFIX}{instance_id}",
         str(int(server_id)) if server_id else None)


def reserve_server_id(label, host_id):
    """Reserve a stats-hub server ID for this feature's target on this host."""
    url = f"{get_effective_stats_hub_url(host_id)}/api/admin/server-ids/reserve"
    headers = {'Authorization': f'Bearer {get_effective_stats_hub_ingest_token(host_id)}'}
    resp = requests.post(url, json={'label': label}, headers=headers, timeout=RESERVE_TIMEOUT_SEC)
    resp.raise_for_status()
    return int(resp.json()['server_id'])


# ---- server.cfg cvar helpers -------------------------------------------

def upsert_cvars_in_text(text, cvars):
    """Replace/append `set <cvar> "value"` lines in raw server.cfg text.

    Only touches the given cvar names - every other line (including cvars
    the operator set by hand through the Plugins tab) is left alone.
    """
    lines = text.splitlines()
    remaining = dict(cvars)
    out = []
    for line in lines:
        m = re.match(r'^(\s*set\s+)([A-Za-z0-9_]+)(\s+)"(.*)"(\s*)$', line)
        if m and m.group(2) in remaining:
            value = remaining.pop(m.group(2))
            out.append(f'{m.group(1)}{m.group(2)}{m.group(3)}"{value}"{m.group(5)}')
        else:
            out.append(line)
    for cvar, value in remaining.items():
        out.append(f'set {cvar} "{value}"')
    return '\n'.join(out) + '\n'


def strip_cvars_from_text(text, cvar_names):
    """Removes `set <cvar> ...` lines for the given cvar names entirely
    (as opposed to upsert_cvars_in_text, which sets a value) - used to clean
    up cvars a server.cfg should no longer carry at all."""
    names = set(cvar_names)
    out = []
    for line in text.splitlines():
        m = re.match(r'^\s*set\s+([A-Za-z0-9_]+)\s+"', line)
        if m and m.group(1) in names:
            continue
        out.append(line)
    return '\n'.join(out) + ('\n' if out else '')


def read_cvars_from_text(text, cvar_names):
    """Returns {name: value} for whichever of `cvar_names` appear as
    `set <name> "value"` lines. Last occurrence wins, matching how the
    engine execs a cfg top to bottom."""
    names = set(cvar_names)
    found = {}
    for line in text.splitlines():
        m = re.match(r'^\s*set\s+([A-Za-z0-9_]+)\s+"(.*)"\s*$', line)
        if m and m.group(1) in names:
            found[m.group(1)] = m.group(2)
    return found
