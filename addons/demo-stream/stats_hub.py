"""demo-stream's private copy of the ql-stats-hub *mechanics*: where the
target is stored, how a per-instance server ID is reserved, and the
server.cfg cvar helpers this feature needs.

Used to be ui/stats_hub.py in qlsm core, shared with the telemetry-relay
addon via a `feature` argument. Duplicated instead of kept shared once it
became clear the addon system has no way to declare or enforce a dependency
between addons: a genuinely shared module would vanish out from under both
features at once if the operator uninstalled it, instead of one of them
degrading on its own. See addons/README.md's "Where the line falls" in qlsm
for the full history. This copy and telemetry-relay's are free to diverge
from here on -- there is no promise they stay identical, only that each
keeps working for its own feature.

State lives in the generic AppSetting key/value table, under the exact key
names this feature has used since before the split -- renaming them would
orphan every deployed database's current demo-stream settings.
"""
import math
import re

import requests

from ui import db
from ui.models import AppSetting

_URL_KEY = 'demo_stream_stats_hub_url'
_TOKEN_KEY = 'demo_stream_stats_hub_ingest_token'
_HOST_URL_PREFIX = 'demo_stream_host_stats_hub_url:'
_HOST_TOKEN_PREFIX = 'demo_stream_host_stats_hub_token:'
_SERVER_ID_PREFIX = 'demo_stream_stats_hub_server_id:'

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


# ---- per-server stream delay -------------------------------------------

DELAY_TIMEOUT_SEC = 5
DELAY_MIN_SEC = 0
DELAY_MAX_SEC = 300


class HubDelayError(Exception):
    """The hub did not answer a delay call with a usable 200. `status` is
    what this addon's own endpoint should answer with, `label` the short form
    for the panel's badge. The text never carries the ingest token."""

    def __init__(self, message, status, label):
        super().__init__(message)
        self.status = status
        self.label = label


def _is_seconds(value):
    # bool is an int in Python; True is not a delay.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _server_delay_call(send, host_id, server_id, **kwargs):
    """One GET/PUT on the hub's per-server delay, as
    {'delay_sec', 'default_delay_sec', 'override'}. Raises HubDelayError."""
    url = f"{get_effective_stats_hub_url(host_id)}/api/demo-stream/servers/{server_id}/delay"
    headers = {'Authorization': f'Bearer {get_effective_stats_hub_ingest_token(host_id)}'}
    try:
        # No redirects: requests re-sends a redirected PUT without its body
        # (301) or as a GET (302/303), and either looks like an answer.
        resp = send(url, headers=headers, timeout=DELAY_TIMEOUT_SEC, allow_redirects=False,
                    **kwargs)
    except requests.RequestException as exc:
        # Only the exception type: its text is not ours and is not needed.
        raise HubDelayError(
            f"Could not reach stats-hub ({type(exc).__name__}). Check the stats-hub URL "
            "in Settings and that the hub is up.", 502, 'Stats-hub unreachable') from None

    try:
        body = resp.json()
    except ValueError:
        body = None
    detail = body.get('detail') if isinstance(body, dict) else None

    if 300 <= resp.status_code < 400:
        raise HubDelayError(
            f"stats-hub redirected the delay call (HTTP {resp.status_code}) instead of "
            "answering it. Check the scheme (http or https) and host of the Stats-hub URL "
            "under Settings -> Demo Stream Stats Hub.", 502, 'Stats-hub redirected the call')
    if resp.status_code in (401, 403):
        raise HubDelayError(
            f"stats-hub rejected the ingest token (HTTP {resp.status_code}). Check Ingest "
            "token under Settings -> Demo Stream Stats Hub: it must be the hub's "
            "STATS_HUB_INGEST_TOKEN, not STATS_HUB_API_TOKEN.", 502, 'Ingest token rejected')
    if resp.status_code == 404 and detail == 'unknown server_id':
        raise HubDelayError(
            f"stats-hub has no demo-stream route for server_id {server_id}. Save the "
            "instance's Live Demo Stream panel again to register it (that restarts the "
            "instance).",
            409, 'No route on stats-hub')
    if resp.status_code in (404, 405):
        raise HubDelayError(
            f"stats-hub answered HTTP {resp.status_code} for this server's delay. Either "
            "this stats-hub is older than the per-server delay API and needs an update, or "
            f"it has no demo-stream route for server_id {server_id} (save the instance's "
            "Live Demo Stream panel again to register it, which restarts the instance).",
            502, 'Stats-hub has no delay API or no route')
    if resp.status_code in (400, 422):
        raise HubDelayError(
            f"stats-hub rejected the delay value (HTTP {resp.status_code}). It accepts "
            f"{DELAY_MIN_SEC} to {DELAY_MAX_SEC} seconds.", 400, 'Delay rejected by stats-hub')
    if resp.status_code != 200:
        raise HubDelayError(
            f"stats-hub answered HTTP {resp.status_code} for this server's delay.",
            502, f'Stats-hub error (HTTP {resp.status_code})')

    state = body if isinstance(body, dict) else {}
    delay, default, override = (state.get(key) for key in
                                ('delay_sec', 'default_delay_sec', 'override'))
    if not (_is_seconds(delay) and _is_seconds(default) and isinstance(override, bool)):
        raise HubDelayError(
            "stats-hub answered the delay call with something this addon does not "
            "understand.", 502, 'Unexpected stats-hub answer')
    return {'delay_sec': float(delay), 'default_delay_sec': float(default),
            'override': override}


def get_server_delay(host_id, server_id):
    return _server_delay_call(requests.get, host_id, server_id)


def set_server_delay(host_id, server_id, delay_sec):
    """`delay_sec` None puts the server back on the hub default."""
    return _server_delay_call(requests.put, host_id, server_id, json={'delay_sec': delay_sec})


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


# ---- host access through the hub firewall --------------------------------
# The hub lets only listed game hosts reach its ports (ufw). These calls add the
# host, remove it and read its state over the hub API (ql-stats-hub
# docs/FIREWALL.md, "Managed from qlsm through the hub API").

ACCESS_TIMEOUT_SEC = 35  # the hub gives hub-allow 30 s
STATUS_TIMEOUT_SEC = 10  # a panel badge: do not hang the panel on a slow hub


class HubAccessError(Exception):
    """The hub did not let the host in / out / report. `status` is what this
    addon's own endpoint answers with, `label` the short form for a badge.
    The text never carries the ingest token."""

    def __init__(self, message, status, label):
        super().__init__(message)
        self.status = status
        self.label = label


def hub_host_name(host):
    """The name hub-allow lists the host under: [a-z0-9-]{1,32}."""
    name = re.sub(r'[^a-z0-9-]', '-', (host.name or '').lower())
    name = re.sub(r'-+', '-', name).strip('-')[:32].strip('-')
    return name or f'host-{host.id}'


def _access_call(send, host, suffix='', timeout=ACCESS_TIMEOUT_SEC, **kwargs):
    if not (host.ip_address or '').strip():
        raise HubAccessError('This host has no IP address yet.', 409, 'No IP address')
    if not is_stats_hub_configured_for_host(host.id):
        raise HubAccessError('Set the stats-hub URL and ingest token in Settings first.',
                             409, 'Stats-hub not configured')
    url = (f"{get_effective_stats_hub_url(host.id)}/api/admin/firewall/hosts/"
           f"{host.ip_address.strip()}{suffix}")
    headers = {'Authorization': f'Bearer {get_effective_stats_hub_ingest_token(host.id)}'}
    try:
        resp = send(url, headers=headers, timeout=timeout, allow_redirects=False,
                    **kwargs)
    except requests.RequestException as exc:
        raise HubAccessError(
            f"Could not reach stats-hub ({type(exc).__name__}). Check the stats-hub URL "
            "in Settings and that the hub is up.", 502, 'Stats-hub unreachable') from None

    try:
        body = resp.json()
    except ValueError:
        body = None
    detail = body.get('detail') if isinstance(body, dict) else None

    if 300 <= resp.status_code < 400:
        raise HubAccessError(
            f"stats-hub redirected the call (HTTP {resp.status_code}). Check the scheme "
            "and host of the stats-hub URL in Settings.", 502, 'Stats-hub redirected the call')
    if resp.status_code in (401, 403):
        raise HubAccessError(
            f"stats-hub rejected the ingest token (HTTP {resp.status_code}). It must be the "
            "hub's STATS_HUB_INGEST_TOKEN.", 502, 'Ingest token rejected')
    if resp.status_code in (404, 405):
        raise HubAccessError(
            f"stats-hub answered HTTP {resp.status_code}: it is older than the firewall API "
            "and needs an update.", 502, 'Stats-hub has no firewall API')
    if resp.status_code != 200 or not isinstance(body, dict):
        text = f": {detail}" if isinstance(detail, str) else ''
        raise HubAccessError(f"stats-hub could not change its firewall (HTTP "
                             f"{resp.status_code}){text}", 502,
                             f'Stats-hub firewall error (HTTP {resp.status_code})')
    return body


def allow_host(host):
    """Let the host reach the hub. A host already listed (under any name) is
    left as it is."""
    return _access_call(requests.put, host, json={'name': hub_host_name(host)})


def release_host(host):
    return _access_call(requests.delete, host)


def host_access_status(host):
    return _access_call(requests.get, host, '/status', timeout=STATUS_TIMEOUT_SEC)


def firewall_label(state):
    """'Firewall ok' or 'Firewall missing 8090, 27999' from a status answer.
    A port still open to everyone counts as reachable."""
    public = state.get('public') or {}
    missing = [port for port, rule in (state.get('ports') or {}).items()
               if rule == 'missing' and not public.get(port)]
    return 'Firewall ok' if not missing else f"Firewall missing {', '.join(missing)}"
