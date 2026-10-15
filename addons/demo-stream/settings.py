"""DB-backed settings for the live demo stream feature (sv_demoStream).

Moved here from qlsm core's ui/demo_stream_settings.py when this feature
stopped having any core-owned endpoints left (its four built-in endpoints
were deleted from core once this addon's own endpoints fully replaced them;
see addons/README.md in qlsm). Content unchanged by the move.

The *mechanics* of talking to ql-stats-hub -- key storage, the reserve call,
the cvar helpers -- used to stay in core as ui/stats_hub.py, shared with the
telemetry-relay addon via a `feature` argument. Now duplicated as this
addon's own private `.stats_hub` (see that module's docstring for why) instead
of shared: this file re-exports it so this addon's other modules have one
obvious place to import from, with the same call signatures they had before
the duplication.

Two kinds of state, all in AppSetting:
- Global: the central relay's TCP ingest address (host:port) every QLDS
  instance's sv_demoStreamHost/sv_demoStreamPort point at - see
  ql-stats-hub's "Live demo stream" contour (STATS_HUB_DEMO_STREAM_TCP_HOST/
  PORT on that side). This is one address for the whole cluster; the host
  side is a local stunnel client per game host (the tunnel keys below) that
  wraps the engine's plain TCP in TLS to it.
- Per instance (key suffixed `:<instance_id>`): whether sv_demoStream is
  wired into this instance's server.cfg, and the per-instance secret token
  generated once and registered with stats-hub's
  POST /api/demo-stream/routes so the relay can attribute this instance's
  connection to the right server_id/name.

State lives in the generic AppSetting key/value table under the same key
names it has always used -- renaming them would orphan every deployed
database's current demo-stream settings.

The host tunnel (a local stunnel client that wraps the engine's plain TCP in
TLS to stats-hub) adds per-host keys `demo_stream_tunnel_enabled:<host_id>` and
`demo_stream_tunnel_port:<host_id>`. The telemetry server_id and stats-hub URL
are read directly from telemetry's own keys (`stats_hub_server_id:<instance_id>`,
`stats_hub_url`, `telemetry_relay_host_stats_hub_url:<host_id>`), because the
shared core `ui/stats_hub.py` no longer exists; those names must stay in step
with `addons/telemetry-relay/stats_hub.py`. They are never written from here.
"""
from ui import db
from ui.models import AppSetting

# Re-exported so this addon's other modules have one obvious place to
# import from.
from .stats_hub import (  # noqa: F401
    HubAccessError,
    allow_host,
    firewall_label,
    host_access_status,
    release_host,
    get_effective_stats_hub_ingest_token,
    get_effective_stats_hub_url,
    get_instance_server_id,
    get_stats_hub_ingest_token,
    get_stats_hub_url,
    is_stats_hub_configured_for_host,
    read_cvars_from_text,
    reserve_server_id,
    set_instance_server_id,
    set_stats_hub_ingest_token,
    set_stats_hub_url,
    upsert_cvars_in_text,
)

RELAY_HOST_SETTING = 'demo_stream_relay_host'
RELAY_PORT_SETTING = 'demo_stream_relay_port'
_ENABLED_PREFIX = 'demo_stream_enabled:'
_TOKEN_PREFIX = 'demo_stream_token:'


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


def get_relay_host():
    return _get(RELAY_HOST_SETTING)


def set_relay_host(value):
    _set(RELAY_HOST_SETTING, value)


def get_relay_port():
    return _get(RELAY_PORT_SETTING)


def set_relay_port(value):
    _set(RELAY_PORT_SETTING, value)


def is_relay_configured():
    return bool(get_relay_host() and get_relay_port())


def is_instance_demo_stream_enabled(instance_id):
    return _get(f'{_ENABLED_PREFIX}{instance_id}') == '1'


def set_instance_demo_stream_enabled(instance_id, enabled):
    _set(f'{_ENABLED_PREFIX}{instance_id}', '1' if enabled else '')


def get_instance_demo_stream_token(instance_id):
    return _get(f'{_TOKEN_PREFIX}{instance_id}')


def set_instance_demo_stream_token(instance_id, token):
    _set(f'{_TOKEN_PREFIX}{instance_id}', token)


DEFAULT_TUNNEL_PORT = '27999'
_TUNNEL_ENABLED_PREFIX = 'demo_stream_tunnel_enabled:'
_TUNNEL_PORT_PREFIX = 'demo_stream_tunnel_port:'
_TELEMETRY_SERVER_ID_PREFIX = 'stats_hub_server_id:'
_TELEMETRY_URL_KEY = 'stats_hub_url'
_TELEMETRY_HOST_URL_PREFIX = 'telemetry_relay_host_stats_hub_url:'


def is_host_tunnel_enabled(host_id):
    return _get(f'{_TUNNEL_ENABLED_PREFIX}{host_id}') == '1'


def set_host_tunnel_enabled(host_id, enabled):
    _set(f'{_TUNNEL_ENABLED_PREFIX}{host_id}', '1' if enabled else '')


def get_host_tunnel_port(host_id):
    return _get(f'{_TUNNEL_PORT_PREFIX}{host_id}') or DEFAULT_TUNNEL_PORT


def set_host_tunnel_port(host_id, value):
    _set(f'{_TUNNEL_PORT_PREFIX}{host_id}', value)


def get_telemetry_server_id(instance_id):
    value = _get(f'{_TELEMETRY_SERVER_ID_PREFIX}{instance_id}')
    return int(value) if value else None


def get_telemetry_stats_hub_url(host_id):
    """The stats-hub URL telemetry-relay effectively uses for this host (its
    per-host override, else its global one). Read-only: these are telemetry's
    keys and must stay in step with addons/telemetry-relay/stats_hub.py."""
    return (_get(f'{_TELEMETRY_HOST_URL_PREFIX}{host_id}') or _get(_TELEMETRY_URL_KEY) or '') \
        .rstrip('/') or None


_TELEMETRY_RELAY_ENABLED_PREFIX = 'telemetry_relay_enabled:'


def is_telemetry_relay_enabled(host_id):
    """Whether telemetry-relay's sidecar is on for this host. Read-only:
    telemetry's key (must stay in step with addons/telemetry-relay/settings.py),
    read so turning the tunnel off does not take the host out of stats-hub's
    firewall while the relay still needs it."""
    return _get(f'{_TELEMETRY_RELAY_ENABLED_PREFIX}{host_id}') == '1'
