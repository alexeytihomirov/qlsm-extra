"""Telemetry-relay's own state: is the sidecar on, for this host.

The *mechanics* of talking to ql-stats-hub -- key storage, the reserve call,
the cvar helpers -- stayed in core as ui/stats_hub.py when this feature moved
into an addon, because the live demo stream needs the same mechanics too.
But the actual stats-hub target (URL, ingest token, per-host override,
per-instance server ID) is telemetry's own: bound to the 'telemetry' feature
below, under the exact AppSetting keys this addon has always used, so it can
be configured independently of wherever the demo stream's own target points
(they may not be the same stats-hub cluster). See ui/stats_hub.py's
module docstring for why the split exists.

What is left here besides that binding is the one thing only telemetry-relay
cares about: whether the ql-telemetry-relay sidecar is installed and enabled
on a given host.

State lives in the generic AppSetting key/value table under the same key
prefix it has always used -- renaming it would orphan every deployed host's
current setting.
"""
from functools import partial

from ui import db
from ui.models import AppSetting

# Re-exported, bound to the 'telemetry' feature, so this addon's other
# modules have one obvious place to import from with the same call
# signatures they had before the feature split.
from ui.stats_hub import (  # noqa: F401
    read_cvars_from_text,
    strip_cvars_from_text,
    upsert_cvars_in_text,
)
from ui import stats_hub as _stats_hub

get_stats_hub_url = partial(_stats_hub.get_stats_hub_url, 'telemetry')
set_stats_hub_url = partial(_stats_hub.set_stats_hub_url, 'telemetry')
get_stats_hub_ingest_token = partial(_stats_hub.get_stats_hub_ingest_token, 'telemetry')
set_stats_hub_ingest_token = partial(_stats_hub.set_stats_hub_ingest_token, 'telemetry')
is_stats_hub_configured = partial(_stats_hub.is_stats_hub_configured, 'telemetry')
get_host_stats_hub_url = partial(_stats_hub.get_host_stats_hub_url, 'telemetry')
set_host_stats_hub_url = partial(_stats_hub.set_host_stats_hub_url, 'telemetry')
get_host_stats_hub_ingest_token = partial(_stats_hub.get_host_stats_hub_ingest_token, 'telemetry')
set_host_stats_hub_ingest_token = partial(_stats_hub.set_host_stats_hub_ingest_token, 'telemetry')
get_effective_stats_hub_url = partial(_stats_hub.get_effective_stats_hub_url, 'telemetry')
get_effective_stats_hub_ingest_token = partial(_stats_hub.get_effective_stats_hub_ingest_token, 'telemetry')
is_stats_hub_configured_for_host = partial(_stats_hub.is_stats_hub_configured_for_host, 'telemetry')
get_instance_server_id = partial(_stats_hub.get_instance_server_id, 'telemetry')
set_instance_server_id = partial(_stats_hub.set_instance_server_id, 'telemetry')
reserve_server_id = partial(_stats_hub.reserve_server_id, 'telemetry')

_RELAY_ENABLED_PREFIX = 'telemetry_relay_enabled:'


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


def is_relay_enabled(host_id):
    return _get(f'{_RELAY_ENABLED_PREFIX}{host_id}') == '1'


def set_relay_enabled(host_id, enabled):
    _set(f'{_RELAY_ENABLED_PREFIX}{host_id}', '1' if enabled else '')
