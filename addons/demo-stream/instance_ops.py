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

disable_instance_demo_stream_logic switches the stream off: sv_demoStream "0"
in server.cfg, apply + restart. The token, server_id and the hub's route are
kept: a stale route is harmless (QLDS simply never connects), and a later
enable reuses them.
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
    get_instance_stream_port,
    get_host_tunnel_port,
    get_telemetry_server_id,
    get_telemetry_stats_hub_url,
    is_host_tunnel_enabled,
    is_instance_demo_stream_enabled,
    is_relay_configured,
    is_stats_hub_configured_for_host,
    reserve_server_id,
    set_instance_demo_stream_enabled,
    set_instance_demo_stream_token,
    set_instance_server_id,
    set_instance_stream_port,
    strip_cvars_from_text,
    upsert_cvars_in_text,
)
from .stats_hub import HubDelayError, format_seconds, set_server_delay

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


def telemetry_server_id_on_same_hub(instance_id, host_id):
    """Telemetry's server_id for this instance when telemetry uses the same
    stats-hub as this addon, else None: an id is only meaningful on the hub
    that issued it."""
    telemetry_id = get_telemetry_server_id(instance_id)
    telemetry_url = get_telemetry_stats_hub_url(host_id)
    own_url = (get_effective_stats_hub_url(host_id) or '').rstrip('/')
    if telemetry_id is not None and telemetry_url and telemetry_url == own_url:
        return telemetry_id
    return None


def _resolve_server_id(instance, host_id):
    """Telemetry's server_id when it has one (one identity per instance across
    both features, only when both addons use the same stats-hub), else this addon's own, else a fresh reservation.

    A new reservation is stored only under this addon's own key: telemetry's
    keys are telemetry's to write. Raises what reserve_server_id raises."""
    telemetry_id = telemetry_server_id_on_same_hub(instance.id, host_id)
    if telemetry_id is not None:
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


DEMO_STREAM_CVARS = ('sv_demoStream', 'sv_demoStreamHost', 'sv_demoStreamPort', 'sv_demoStreamToken')


def launch_args_active(instance_id):
    """True when core passes this addon's instance.launch_args for the
    instance (the addon is switched on for it at every scope). Then the
    sv_demoStream* cvars travel as `+set` on the command line instead of in
    server.cfg, so a preset saved from the instance never carries the token
    and loading one never wipes the wiring."""
    from ui.addons import get_addon

    addon = get_addon('demo-stream')
    return bool(addon and addon.ctx and addon.ctx.settings.is_enabled('instance', instance_id))


def open_launch_args(instance):
    """Switch this addon on for the instance's host and the instance itself,
    so core passes its instance.launch_args. qlsm's UI has only the global
    switch, so nothing else ever sets these two layers; they gate nothing
    else in this addon. Stays off (and server.cfg keeps the cvars) while the
    addon is off globally."""
    from ui.addons import get_addon

    addon = get_addon('demo-stream')
    if not (addon and addon.ctx):
        return
    addon.ctx.settings.set_enabled('host', instance.host_id, True, commit=False)
    addon.ctx.settings.set_enabled('instance', instance.id, True, commit=False)
    db.session.commit()


def demo_stream_launch_cvars(instance):
    """The sv_demoStream* values the enable/disable stored, as `+set` gets
    them: streaming only with the switch on and a token."""
    token = get_instance_demo_stream_token(instance.id)
    if not (is_instance_demo_stream_enabled(instance.id) and token):
        return {'sv_demoStream': '0'}
    return {
        'sv_demoStream': '1',
        'sv_demoStreamHost': '127.0.0.1',
        'sv_demoStreamPort': get_instance_stream_port(instance.id) or get_host_tunnel_port(instance.host_id),
        'sv_demoStreamToken': token,
    }


def _config_path(instance):
    return f"configs/{instance.host.name}/{instance.id}/server.cfg"


def read_cfg_text(instance):
    try:
        with open(_config_path(instance), 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        return None


def _write_cvars(instance, cvars):
    """Launch-args mode: drop the sv_demoStream* lines from server.cfg, the
    `+set` values carry them. Otherwise write them into server.cfg."""
    open_launch_args(instance)
    text = read_cfg_text(instance)
    if launch_args_active(instance.id):
        if text is None:
            return
        new = strip_cvars_from_text(text, DEMO_STREAM_CVARS)
    else:
        new = upsert_cvars_in_text(text or '', cvars)
    if new == text:
        return
    config_path = _config_path(instance)
    os.makedirs(os.path.dirname(config_path), exist_ok=True)
    with open(config_path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(new)


def _queue_apply_restart(instance_id):
    from ui.tasks import apply_instance_config, enqueue_task
    from ui.task_logic.job_failure_handlers import instance_job_failure_handler

    return enqueue_task(
        apply_instance_config,
        instance_id,
        restart=True,
        on_failure=instance_job_failure_handler,
    )


def _set_delay_after_enable(instance, host_id, server_id, delay_sec):
    """The enable's last step: the delay asked for in the same save. A hub
    failure here does not undo the enable; it is logged and reported."""
    if delay_sec is None:
        return ''
    try:
        state = set_server_delay(host_id, server_id, delay_sec)
    except HubDelayError as exc:
        current_app.logger.error(
            f"Demo-stream enabled for instance {instance.id} but its delay was not set: {exc}")
        return f" The stream delay was not set: {exc}"
    return f" Stream delay set to {format_seconds(state['delay_sec'])} s."


def enable_instance_demo_stream_logic(instance_id, previous_status=None, delay_sec=None):
    """Returns (ok: bool, message: str). `delay_sec` (seconds) is set on the
    hub as the last step; None leaves the hub's delay alone."""
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
    set_instance_stream_port(instance.id, get_host_tunnel_port(host_id))
    db.session.commit()

    _write_cvars(instance, {
        'sv_demoStream': '1',
        'sv_demoStreamHost': '127.0.0.1',
        'sv_demoStreamPort': get_host_tunnel_port(host_id),
        'sv_demoStreamToken': token,
    })

    set_instance_demo_stream_enabled(instance.id, True)
    db.session.commit()

    job = _queue_apply_restart(instance.id)
    if not job:
        return _finish(
            instance, False, f"server_id {server_id} reserved and route registered, but queuing the config apply/restart failed.",
            previous_status,
        )

    delay_note = _set_delay_after_enable(instance, host_id, server_id, delay_sec)
    return _finish(
        instance, True,
        f"Live demo stream enabled, server_id={server_id}. Applying config and restarting (job {job.id}).{delay_note}",
    )


def disable_instance_demo_stream_logic(instance_id, previous_status=None):
    """Returns (ok: bool, message: str). Sets sv_demoStream "0" and restarts;
    the token, server_id and hub route stay for a later enable."""
    instance = db.session.get(QLInstance, instance_id)
    if not instance:
        return False, "Instance or associated host not found."
    if not instance.host:
        return _finish(instance, False, "Instance or associated host not found.", previous_status)

    _write_cvars(instance, {'sv_demoStream': '0'})
    set_instance_demo_stream_enabled(instance.id, False)
    db.session.commit()

    job = _queue_apply_restart(instance.id)
    if not job:
        return _finish(
            instance, False, "sv_demoStream set to 0, but queuing the config apply/restart failed.",
            previous_status,
        )

    return _finish(
        instance, True,
        f"Live demo stream disabled. Applying config and restarting (job {job.id}).",
    )


def prepare_new_instance(instance_id):
    """The enable for an instance that has not been deployed yet, called by
    telemetry-relay's `instance.created` handler (see that addon's
    new_instance.py) after it stored the instance's server ID. Same steps as
    enable_instance_demo_stream_logic minus the apply + restart and the
    status handling: the first deploy passes the `+set` launch args.

    The server ID comes from _resolve_server_id, so it is telemetry's
    whenever both addons use the same stats-hub; only a different stats-hub
    gets an ID of its own. Returns (ok, message); never raises for a
    missing prerequisite or an unreachable hub."""
    instance = db.session.get(QLInstance, instance_id)
    if not instance or not instance.host:
        return False, "live demo stream not switched on: instance or host not found."
    host_id = instance.host_id
    if not is_relay_configured():
        return False, ("live demo stream not switched on: configure the demo-stream relay "
                       "host/port in Settings first.")
    if not is_stats_hub_configured_for_host(host_id):
        return False, ("live demo stream not switched on: configure the demo stream's "
                       "stats-hub URL/ingest token in Settings first.")
    if not is_host_tunnel_enabled(host_id):
        return False, ("live demo stream not switched on: enable the Demo Stream Tunnel on host "
                       f"{instance.host.name} first, then switch it on in the instance's panel.")

    shared = telemetry_server_id_on_same_hub(instance.id, host_id) is not None
    try:
        server_id = _resolve_server_id(instance, host_id)
    except (requests.RequestException, ValueError, KeyError) as exc:
        current_app.logger.error(
            f"Demo-stream: no server_id for new instance {instance.id}: {exc}")
        return False, f"live demo stream not switched on: could not reserve a server_id ({exc})."

    token = get_instance_demo_stream_token(instance.id) or secrets.token_hex(24)
    try:
        _register_route(host_id, server_id, instance.name, token)
    except requests.RequestException as exc:
        current_app.logger.error(
            f"Demo-stream: route for new instance {instance.id} not registered: {exc}")
        return False, f"live demo stream not switched on: could not register its route ({exc})."

    set_instance_demo_stream_token(instance.id, token)
    set_instance_stream_port(instance.id, get_host_tunnel_port(host_id))
    db.session.commit()
    _write_cvars(instance, {
        'sv_demoStream': '1',
        'sv_demoStreamHost': '127.0.0.1',
        'sv_demoStreamPort': get_host_tunnel_port(host_id),
        'sv_demoStreamToken': token,
    })
    set_instance_demo_stream_enabled(instance.id, True)
    db.session.commit()
    own = '' if shared else " (its own stats-hub, so its own server ID)"
    return True, f"live demo stream on, server ID {server_id}{own}."
