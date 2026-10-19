"""Stats Hub set-up of a brand-new instance, before its first deploy.

Runs from qlsm's `instance.created` hook (qlsm with the Add Instance addon
tab; an older core never calls it). What it does is what the Telemetry and
Live Demo Stream panels do on enable, minus the apply + restart: the first
deploy that follows already carries the `+set` launch args, so a new server
is in the hub from its first start with no extra restart.

One server ID per instance: it is reserved here once (or taken from the
form) and stored as telemetry's reserved ID before the demo stream is set
up; demo-stream's own set-up takes telemetry's ID whenever both use the same
stats-hub, so nothing reserves a second one. That is also why telemetry-relay
drives both: core dispatches hooks in addon-id order, demo-stream before
telemetry-relay, so a demo-stream handler of its own would run before any ID
exists. The form's Stats Hub tab is this addon's, and its values reach only
this addon's handler.

Every step that cannot be done (relay off on the host, no tunnel, hub
unreachable) is skipped with a line in the instance log saying what to
switch on; the instance is created and deployed either way.
"""
import sys

import requests
from flask import current_app

from ui import db
from ui.models import QLInstance

from .instance_ops import _write_telemetry_cvars
from .settings import (
    get_reserved_server_id,
    instance_ids_sharing_server_id,
    is_auto_enable_new_instances,
    is_relay_enabled,
    is_stats_hub_configured_for_host,
    reserve_server_id,
    set_instance_server_id,
    set_reserved_server_id,
)

ADDON_ID = 'telemetry-relay'
DEMO_STREAM_ADDON_ID = 'demo-stream'


def tab_defaults():
    """What the Add Instance tab starts with: both switches follow the
    "Switch on new instances" setting, no manual server ID."""
    auto = is_auto_enable_new_instances()
    return {'telemetry': auto, 'demo_stream': auto, 'server_id': ''}


def parse_options(options):
    """(telemetry, demo_stream, manual_server_id, notes) from the tab's
    values. A missing switch follows the setting (an API client sends no
    tab at all). A malformed server ID is ignored with a note and a fresh
    one is reserved instead: the instance is being created either way, and
    a reserved ID the operator can replace later beats a server left out of
    the hub."""
    options = options if isinstance(options, dict) else {}
    defaults = tab_defaults()
    notes = []
    switches = []
    for key in ('telemetry', 'demo_stream'):
        value = options.get(key, defaults[key])
        if not isinstance(value, bool):
            notes.append(f'Stats Hub: "{key}" must be true or false; used the default.')
            value = defaults[key]
        switches.append(value)

    raw = options.get('server_id', '')
    manual_id = None
    if isinstance(raw, bool) or raw is None:
        raw = ''
    text = str(raw).strip()
    if text:
        try:
            manual_id = int(text)
        except ValueError:
            manual_id = None
        if manual_id is None or manual_id <= 0:
            notes.append(f'Stats Hub: server ID "{text}" is not a positive whole number; '
                         'reserved a new one instead.')
            manual_id = None
    return switches[0], switches[1], manual_id, notes


def _addon_enabled(addon_id):
    from ui.addons import get_addon

    addon = get_addon(addon_id)
    return bool(addon and addon.loaded and addon.ctx and addon.globally_enabled)


def _resolve_server_id(instance, manual_id, notes):
    """The manual ID, else one already reserved for the instance, else a
    fresh reservation; stored as telemetry's reserved ID. None (with a note)
    when the hub cannot be asked."""
    if manual_id is None and get_reserved_server_id(instance.id) is not None:
        return get_reserved_server_id(instance.id)
    if manual_id is not None:
        sharing = instance_ids_sharing_server_id(manual_id, exclude_instance_id=instance.id)
        if sharing:
            notes.append(f"Stats Hub: server ID {manual_id} is also used by instance(s) "
                         f"{', '.join(str(i) for i in sharing)}; their matches share one id on the hub.")
        server_id = manual_id
    else:
        try:
            server_id = reserve_server_id(instance.name, instance.host_id)
        except (requests.RequestException, ValueError, KeyError) as exc:
            current_app.logger.error(
                f"telemetry-relay: no server ID reserved for new instance {instance.id}: {exc}")
            notes.append(f"Stats Hub: could not reserve a server ID from stats-hub ({exc}); "
                         "switch telemetry on in the instance's Stats Hub entry once the hub answers.")
            return None
    set_reserved_server_id(instance.id, server_id)
    db.session.commit()
    return server_id


def _switch_telemetry_on(instance, server_id, push_routes, notes):
    """Route the ID, open the launch-args layers, strip leftover cvars from
    server.cfg, queue the relay's route push. No apply, no restart: the
    first deploy passes the cvars."""
    set_instance_server_id(instance.id, server_id)
    db.session.commit()
    _write_telemetry_cvars(instance, {
        'qlx_statsHubUnifiedEnabled': '1',
        'qlx_statsHubServerId': str(server_id),
    })
    # The relay drops what it has no route for; the route push is a host
    # playbook (the relay sidecar's config), not an instance apply, so it is
    # queued instead of run inside the create request.
    queued = False
    try:
        from ui.tasks import enqueue_task
        queued = bool(push_routes and enqueue_task(push_routes, instance.host_id))
    except Exception as exc:
        current_app.logger.error(
            f"telemetry-relay: route push for new instance {instance.id} not queued: {exc}")
    if not queued:
        notes.append("Stats Hub: the relay's routes were not pushed; save the host's "
                     "Stats Hub entry once so the relay forwards this server.")
    notes.append(f"Stats Hub: telemetry on, server ID {server_id}.")


def _prepare_demo_stream(instance_id):
    """Demo-stream's own set-up for the instance, or why it was skipped.

    Called by function, not by a hook of its own (see the module
    docstring): demo-stream publishes `prepare_new_instance` on its backend
    module from 1.8.0 on, found through its addon context."""
    from ui.addons import get_addon

    addon = get_addon(DEMO_STREAM_ADDON_ID)
    if not (addon and addon.loaded and addon.ctx):
        return "Stats Hub: live demo stream not switched on: the demo-stream addon is not installed."
    if not addon.globally_enabled:
        return ("Stats Hub: live demo stream not switched on: the Live Demo Stream addon "
                "is switched off on the Addons page.")
    module = sys.modules.get(addon.ctx.module_name or '')
    prepare = getattr(module, 'prepare_new_instance', None)
    if prepare is None:
        return ("Stats Hub: live demo stream not switched on: the installed demo-stream addon "
                "predates 1.8.0; update it, then switch the stream on in the instance's Stats Hub entry.")
    _ok, message = prepare(instance_id)
    return f"Stats Hub: {message}"


def prepare_new_instance(instance_id, options, push_routes=None):
    """The `instance.created` handler. Returns the notes it logged."""
    from ui.task_logic.common import append_log

    instance = db.session.get(QLInstance, instance_id)
    if instance is None or instance.host is None or not _addon_enabled(ADDON_ID):
        return []

    telemetry, demo_stream, manual_id, notes = parse_options(options)
    if not (telemetry or demo_stream):
        return _log(instance, notes, append_log)

    server_id = None
    if is_stats_hub_configured_for_host(instance.host_id):
        server_id = _resolve_server_id(instance, manual_id, notes)
    else:
        notes.append("Stats Hub: set the stats-hub URL and ingest token in Settings first; "
                     "no server ID reserved.")

    if telemetry and server_id is not None:
        if is_relay_enabled(instance.host_id):
            _switch_telemetry_on(instance, server_id, push_routes, notes)
        else:
            notes.append(f"Stats Hub: telemetry not switched on: switch the telemetry relay on in "
                         f"host {instance.host.name}'s Stats Hub entry first. Server ID {server_id} stays reserved for it.")
    elif server_id is not None:
        notes.append(f"Stats Hub: server ID {server_id} reserved, telemetry left off.")

    if demo_stream:
        notes.append(_prepare_demo_stream(instance.id))
    return _log(instance, notes, append_log)


def _log(instance, notes, append_log):
    for note in notes:
        append_log(instance, note)
    db.session.commit()
    return notes
