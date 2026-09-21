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
  PORT on that side). This is one address for the whole cluster, not
  per-host like the telemetry relay sidecar (that one's a local process on
  each game host; this one has nothing local to install).
- Per instance (key suffixed `:<instance_id>`): whether sv_demoStream is
  wired into this instance's server.cfg, and the per-instance secret token
  generated once and registered with stats-hub's
  POST /api/demo-stream/routes so the relay can attribute this instance's
  connection to the right server_id/name.

State lives in the generic AppSetting key/value table under the same key
names it has always used -- renaming them would orphan every deployed
database's current demo-stream settings.
"""
from ui import db
from ui.models import AppSetting

# Re-exported so this addon's other modules have one obvious place to
# import from.
from .stats_hub import (  # noqa: F401
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
