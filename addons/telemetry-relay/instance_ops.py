"""Enables and disables telemetry-relay wiring for a single QL instance.

Enable: reserve a cluster-wide server_id from ql-stats-hub (or reuse the one
reserved before), flip qlx_statsHubUnifiedEnabled on, push the host's relay
routes, and apply+restart the instance (same mechanism the Plugins tab
config-save flow already uses). Disable: flip it off, drop the relay route,
apply+restart; the reserved server_id is kept for the next enable.

The instance itself never stores or sends the stats-hub URL/ingest token -
those live only in per-host settings (ui/telemetry_relay_settings.py) and
are read by the relay sidecar and by _reserve_server_id below. The
stream_telemetry_unified plugin talks to a fixed local relay address
(see ansible_telemetry_relay.RELAY_LOCAL_URL) hardcoded in its own
qlx_statsHubUrl default - not per-instance data, so there is nothing left
to write into server.cfg for it.
"""
import os
import re

import requests
from flask import current_app

from ui import db
from ui.models import InstanceStatus, QLInstance
from .relay_ops import push_relay_config_logic
from .settings import (
    get_instance_server_id,
    get_reserved_server_id,
    instance_ids_sharing_server_id,
    is_instance_demo_stream_enabled,
    is_relay_enabled,
    is_stats_hub_configured_for_host,
    read_cvars_from_text,
    reserve_server_id,
    set_instance_server_id,
    set_new_server_id_at,
    set_reserved_server_id,
    strip_cvars_from_text,
    upsert_cvars_in_text,
    utcnow,
)

_RESERVE_TIMEOUT_SEC = 10
# Cvars the instance-level plugin used to have written into its server.cfg
# directly (stats-hub URL / ingest token). Now host-only - stripped from any
# server.cfg still carrying them from before this change so the file doesn't
# keep advertising stale/duplicated secrets.
_LEGACY_INSTANCE_CVARS = ('qlx_statsHubUrl', 'qlx_statsHubToken')
_TELEMETRY_CVARS = ('qlx_statsHubUnifiedEnabled', 'qlx_statsHubServerId')


def _config_path(instance):
    return os.path.join('configs', instance.host.name, str(instance.id), 'server.cfg')


def read_instance_telemetry_cvars(instance):
    """qlx_statsHubUnifiedEnabled / qlx_statsHubServerId as qlsm's copy of the
    instance's server.cfg carries them; {} when there is no server.cfg."""
    try:
        with open(_config_path(instance), 'r', encoding='utf-8') as f:
            text = f.read()
    except FileNotFoundError:
        return {}
    return read_cvars_from_text(text, _TELEMETRY_CVARS)


def sync_instance_server_id_from_config(instance):
    """Keeps this instance's telemetry-relay routing entry
    (`stats_hub_server_id:<instance_id>`, see telemetry_relay_settings.py)
    in sync with whatever qlx_statsHubServerId/qlx_statsHubUnifiedEnabled
    its server.cfg actually carries on disk.

    Without this, an operator who wires telemetry purely through the
    Plugins-tab cvar editor (set qlx_statsHubUnifiedEnabled + qlx_statsHubServerId
    by hand, never calling enable_instance_telemetry_logic /
    POST .../telemetry) ends up with a server.cfg that looks fully
    configured while the relay's routing table stays empty on this host -
    every POST is silently dropped as "no_route" even though the relay
    sidecar, its stats-hub URL/token, and the plugin cvars are all
    individually correct. Real incident, see
    qlsm-telemetry-relay-server-id-db-desync in project memory. Call from
    apply_instance_config_logic after every successful config apply, so any
    path that ends up writing server.cfg (raw editor, Plugins tab, or the
    assisted enable_instance_telemetry_logic flow itself) keeps this in
    sync automatically, in whatever order the operator did the setup steps.
    """
    if not instance.host or not os.path.exists(_config_path(instance)):
        return

    cvars = read_instance_telemetry_cvars(instance)
    enabled = cvars.get('qlx_statsHubUnifiedEnabled') == '1'
    try:
        server_id = int(cvars.get('qlx_statsHubServerId') or 0)
    except ValueError:
        server_id = 0

    effective_id = server_id if (enabled and server_id > 0) else None
    if get_instance_server_id(instance.id) == effective_id:
        return  # already in sync, don't push relay config for nothing

    set_instance_server_id(instance.id, effective_id)
    sharing = instance_ids_sharing_server_id(effective_id, exclude_instance_id=instance.id)
    if sharing:
        # Not blocked: the operator may mean it. But two instances on one id
        # post as one `server-<id>` match on the hub and their matches mix.
        message = (
            f"Warning: stats-hub server id {effective_id} is also used by instance(s) "
            f"{', '.join(str(i) for i in sharing)}; their matches share one id on the hub. "
            f"Give each instance its own qlx_statsHubServerId."
        )
        current_app.logger.warning(f"telemetry-relay: instance {instance.id}: {message}")
        instance.logs = f"{message}\n{instance.logs or ''}"
    db.session.commit()
    push_relay_config_logic(instance.host_id)


def _status_after_failure(previous_status):
    """The status a failed enable goes back to: the one the endpoint saw
    before it set CONFIGURING, or ERROR when that is missing or invalid (the
    same outcome as core's instance_job_failure_handler)."""
    try:
        return InstanceStatus(previous_status)
    except ValueError:
        return InstanceStatus.ERROR


def _finish(instance, ok, message, previous_status=None):
    if instance is not None:
        instance.logs = f"{message}\n{instance.logs or ''}"
        if not ok and instance.status == InstanceStatus.CONFIGURING:
            instance.status = _status_after_failure(previous_status)
        db.session.commit()
    return ok, message


def enable_instance_telemetry_logic(instance_id, previous_status=None, new_server_id=False):
    """Returns (ok: bool, message: str). `new_server_id` reserves a fresh
    server_id from stats-hub instead of reusing the stored one (two servers
    sharing one); the old one is simply abandoned."""
    instance = db.session.get(QLInstance, instance_id)
    if not instance:
        return False, "Instance or associated host not found."
    if not instance.host:
        return _finish(instance, False, "Instance or associated host not found.", previous_status)

    host_id = instance.host_id
    if not is_stats_hub_configured_for_host(host_id):
        return _finish(instance, False, "Configure the stats-hub URL/ingest token (globally or for this host) in Settings first.", previous_status)
    if not is_relay_enabled(host_id):
        return _finish(instance, False, "Enable the telemetry relay for this host first.", previous_status)

    old_server_id = get_instance_server_id(instance.id) or get_reserved_server_id(instance.id)
    server_id = None if new_server_id else old_server_id
    if server_id is None:
        try:
            server_id = reserve_server_id(instance.name, host_id)
        except (requests.RequestException, ValueError, KeyError) as exc:
            current_app.logger.error(
                f"Failed to reserve stats-hub server_id for instance {instance.id}: {exc}"
            )
            return _finish(instance, False, f"Could not reserve a server_id from stats-hub: {exc}", previous_status)
        if new_server_id:
            # The panel's switch stays ticked after the save; the endpoint
            # refuses another new ID for a while after this one.
            set_new_server_id_at(instance.id, utcnow())
    set_instance_server_id(instance.id, server_id)
    db.session.commit()

    config_path = _config_path(instance)
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            text = f.read()
    except FileNotFoundError:
        text = ''

    text = strip_cvars_from_text(text, _LEGACY_INSTANCE_CVARS)
    text = upsert_cvars_in_text(text, {
        'qlx_statsHubUnifiedEnabled': '1',
        'qlx_statsHubServerId': str(server_id),
    })
    os.makedirs(os.path.dirname(config_path), exist_ok=True)
    with open(config_path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(text)

    if not push_relay_config_logic(host_id):
        return _finish(instance, False, (
            f"server_id {server_id} reserved and server.cfg updated, but pushing the "
            "relay's routes to the host failed - re-run once the host is reachable."
        ), previous_status)

    from ui.tasks import apply_instance_config, enqueue_task
    from ui.task_logic.job_failure_handlers import instance_job_failure_handler

    job = enqueue_task(
        apply_instance_config,
        instance.id,
        restart=True,
        on_failure=instance_job_failure_handler,
    )
    if not job:
        return _finish(
            instance, False, f"server_id {server_id} reserved, but queuing the config apply/restart failed.",
            previous_status,
        )

    note = ''
    if new_server_id:
        note = f" New server ID reserved (was {old_server_id})." if old_server_id else ''
        if is_instance_demo_stream_enabled(instance.id):
            note += (" The Live Demo Stream keeps its previous server ID until its panel "
                     "is saved once (one more restart).")
    return _finish(
        instance, True,
        f"Telemetry enabled, server_id={server_id}.{note} Applying config and restarting (job {job.id}).",
    )


def disable_instance_telemetry_logic(instance_id, previous_status=None):
    """Switches telemetry off: qlx_statsHubUnifiedEnabled 0, the relay route
    dropped, apply + restart. The reserved server_id is kept (and stays in
    server.cfg) so a re-enable gets the same one. Returns (ok, message)."""
    instance = db.session.get(QLInstance, instance_id)
    if not instance:
        return False, "Instance or associated host not found."
    if not instance.host:
        return _finish(instance, False, "Instance or associated host not found.", previous_status)

    server_id = get_reserved_server_id(instance.id)
    set_reserved_server_id(instance.id, server_id)
    set_instance_server_id(instance.id, None)
    db.session.commit()

    config_path = _config_path(instance)
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            text = f.read()
    except FileNotFoundError:
        text = ''
    text = upsert_cvars_in_text(text, {'qlx_statsHubUnifiedEnabled': '0'})
    os.makedirs(os.path.dirname(config_path), exist_ok=True)
    with open(config_path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(text)

    # A failed push leaves a route the instance no longer sends to; the
    # switch-off itself is what matters, so the apply still runs.
    warning = '' if push_relay_config_logic(instance.host_id) else (
        " Pushing the relay's routes failed; the relay keeps this instance's "
        "route until its next push.")

    from ui.tasks import apply_instance_config, enqueue_task
    from ui.task_logic.job_failure_handlers import instance_job_failure_handler

    job = enqueue_task(
        apply_instance_config,
        instance.id,
        restart=True,
        on_failure=instance_job_failure_handler,
    )
    if not job:
        return _finish(instance, False, "Telemetry switched off in server.cfg, but queuing the "
                       "config apply/restart failed." + warning, previous_status)

    kept = f" server_id {server_id} stays reserved." if server_id else ''
    return _finish(
        instance, True,
        f"Telemetry disabled.{kept}{warning} Applying config and restarting (job {job.id}).",
    )
