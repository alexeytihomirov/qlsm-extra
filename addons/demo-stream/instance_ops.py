"""Enables the live demo stream feature (sv_demoStream) for a single QL
instance: take a server_id (telemetry's, when it has one and points at the same
stats-hub; else one reserved from the demo stream's own stats-hub target -
see .stats_hub's module docstring, the two features may not be the same
stats-hub cluster), generate a per-instance secret token, register
{token -> server_id} with ql-stats-hub's "Live demo stream" contour, point the
instance's sv_demoStream* cvars at the host's local stunnel (127.0.0.1, see
below) and apply+restart (same mechanism the Plugins tab config-save flow
already uses).

The instance does not talk to the relay directly: the engine speaks plain TCP,
the hub requires TLS, so sv_demoStreamHost/Port point at the host's local
stunnel client (127.0.0.1:<host tunnel port>, set up by tunnel_ops.py), and the
host tunnel must be enabled first. The server_id is shared with telemetry when
telemetry already has one for the instance (telemetry's `stats_hub_server_id:`
key is only ever read here, never written); otherwise this addon reserves its
own and keeps it in `demo_stream_stats_hub_server_id:`.

Moved here from qlsm core's ui/task_logic/demo_stream_instance.py once this
feature's own endpoints fully replaced core's built-in ones (see settings.py
here and addons/README.md in qlsm). Content unchanged by the move, apart from
dropping the `feature` indirection that used to route through the shared
ui/stats_hub.py -- .stats_hub here already only ever serves this feature.

No disable_instance_demo_stream_logic - mirrors the telemetry-relay addon's
own asymmetry (see its enable flow's docstring): an operator can flip
sv_demoStream back to "0" by hand through the raw config editor, same as any
other cvar. A stale registered route on stats-hub is harmless - QLDS simply
never reconnects, so there is nothing that needs to notice and clean it up
the way telemetry's server_id routing table does.
"""
import os
import secrets

import requests
from flask import current_app

from ui import db
from ui.models import InstanceStatus, QLInstance
from .settings import (
    get_effective_stats_hub_ingest_token,
    get_effective_stats_hub_url,
    get_instance_demo_stream_token,
    get_instance_server_id,
    get_host_tunnel_port,
    get_telemetry_server_id,
    get_telemetry_stats_hub_url,
    is_host_tunnel_enabled,
    is_relay_configured,
    is_stats_hub_configured_for_host,
    reserve_server_id,
    set_instance_demo_stream_enabled,
    set_instance_demo_stream_token,
    set_instance_server_id,
    upsert_cvars_in_text,
)

_ROUTES_TIMEOUT_SEC = 10

TUNNEL_REQUIRED_MESSAGE = (
    "Enable the Demo Stream Tunnel on this instance's host first "
    "(Hosts -> Demo Stream Tunnel). Plain TCP to the relay is no longer configured."
)


def _register_route(host_id, server_id, server_name, token):
    url = f"{get_effective_stats_hub_url(host_id)}/api/demo-stream/routes"
    headers = {'Authorization': f'Bearer {get_effective_stats_hub_ingest_token(host_id)}'}
    resp = requests.post(
        url,
        json={'token': token, 'server_id': server_id, 'server_name': server_name},
        headers=headers,
        timeout=_ROUTES_TIMEOUT_SEC,
    )
    resp.raise_for_status()


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


def _resolve_server_id(instance, host_id):
    """Telemetry's server_id when it has one (one identity per instance across
    both features, only when both addons use the same stats-hub), else this addon's own, else a fresh reservation.

    A new reservation is stored only under this addon's own key: telemetry's
    key is cleared by its config_applied hook when telemetry is not configured,
    so a write there would be lost. Raises what reserve_server_id raises."""
    telemetry_id = get_telemetry_server_id(instance.id)
    telemetry_url = get_telemetry_stats_hub_url(host_id)
    own_url = (get_effective_stats_hub_url(host_id) or '').rstrip('/')
    # An id is only meaningful on the hub that issued it.
    if telemetry_id is not None and telemetry_url and telemetry_url == own_url:
        if get_instance_server_id(instance.id) != telemetry_id:
            set_instance_server_id(instance.id, telemetry_id)
            db.session.commit()
        return telemetry_id

    server_id = get_instance_server_id(instance.id)
    if server_id is None:
        server_id = reserve_server_id(instance.name, host_id)
        set_instance_server_id(instance.id, server_id)
        db.session.commit()
    return server_id


def enable_instance_demo_stream_logic(instance_id, previous_status=None):
    """Returns (ok: bool, message: str)."""
    instance = db.session.get(QLInstance, instance_id)
    if not instance:
        return False, "Instance or associated host not found."
    if not instance.host:
        return _finish(instance, False, "Instance or associated host not found.", previous_status)

    host_id = instance.host_id
    if not is_relay_configured():
        return _finish(instance, False, "Configure the demo-stream relay host/port in Settings first.", previous_status)
    if not is_stats_hub_configured_for_host(host_id):
        return _finish(instance, False, "Configure the stats-hub URL/ingest token (globally or for this host) in Settings first.", previous_status)

    if not is_host_tunnel_enabled(host_id):
        return _finish(instance, False, TUNNEL_REQUIRED_MESSAGE, previous_status)

    try:
        server_id = _resolve_server_id(instance, host_id)
    except (requests.RequestException, ValueError, KeyError) as exc:
        current_app.logger.error(
            f"Failed to reserve stats-hub server_id for instance {instance.id}: {exc}"
        )
        return _finish(instance, False, f"Could not reserve a server_id from stats-hub: {exc}", previous_status)

    token = get_instance_demo_stream_token(instance.id)
    if not token:
        token = secrets.token_hex(24)

    try:
        _register_route(host_id, server_id, instance.name, token)
    except requests.RequestException as exc:
        current_app.logger.error(
            f"Failed to register demo-stream route for instance {instance.id}: {exc}"
        )
        return _finish(instance, False, f"Could not register the demo-stream route with stats-hub: {exc}", previous_status)

    set_instance_demo_stream_token(instance.id, token)
    db.session.commit()

    config_path = f"configs/{instance.host.name}/{instance.id}/server.cfg"
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            text = f.read()
    except FileNotFoundError:
        text = ''

    text = upsert_cvars_in_text(text, {
        'sv_demoStream': '1',
        'sv_demoStreamHost': '127.0.0.1',
        'sv_demoStreamPort': get_host_tunnel_port(host_id),
        'sv_demoStreamToken': token,
    })
    os.makedirs(os.path.dirname(config_path), exist_ok=True)
    with open(config_path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(text)

    set_instance_demo_stream_enabled(instance.id, True)
    db.session.commit()

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
            instance, False, f"server_id {server_id} reserved and route registered, but queuing the config apply/restart failed.",
            previous_status,
        )

    return _finish(
        instance, True,
        f"Live demo stream enabled, server_id={server_id}. Applying config and restarting (job {job.id}).",
    )
