"""Telemetry relay, as an addon.

**Migration state.** This ships *alongside* the built-in telemetry-relay code,
not instead of it: the feature is live in production on host `germany`, so the
core endpoints, tasks and modal stay until this addon has been verified
against a real host. Until then both appear in the UI, the addon's entries
suffixed "(addon)".

Because of that, this backend deliberately **delegates to the existing
`ui.telemetry_relay_settings` and `ui.task_logic.ansible_telemetry_relay`
modules rather than copying their logic.** Two implementations of a
production feature drifting apart is a far worse failure than an addon
importing from core for one release. The physical move of those modules into
this directory happens in the same change that deletes the core endpoints --
see the spec's phase 4.

Note that **no panel here is `managed`** -- every one has its own load/submit
route reading the same AppSetting keys the built-in code reads. That is on
purpose: a managed panel would store the stats-hub URL and ingest token in
AddonState while the shared relay logic kept reading AppSetting, giving a
production credential two sources of truth that silently disagree. One store,
one reader, for as long as both code paths exist.
"""
import re
import time
import uuid
from datetime import timedelta

from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import jwt_required

bp = Blueprint('telemetry_relay_addon', __name__)


def _host_or_404(host_id):
    from ui.database import get_host

    host = get_host(host_id)
    if not host:
        return None, (jsonify({"error": {"message": "Host not found"}}), 404)
    return host, None


@bp.route('/hosts/<int:host_id>', methods=['GET'], endpoint='get_host_relay')
@jwt_required()
def get_host_relay(host_id):
    """Everything the host panel's form needs, in one round trip."""
    from .settings import (
        get_host_forward_url, get_host_stats_hub_ingest_token, get_host_stats_hub_url,
        is_relay_enabled,
    )

    _, error = _host_or_404(host_id)
    if error:
        return error

    return jsonify({"data": {
        'enabled': is_relay_enabled(host_id),
        'url_override': get_host_stats_hub_url(host_id) or '',
        'ingest_token_override': get_host_stats_hub_ingest_token(host_id) or '',
        'forward_url': get_host_forward_url(host_id) or '',
    }})


_FORWARD_URL_RE = re.compile(r'^https?://[A-Za-z0-9.\-]+(:\d{1,5})?/?$')


def _forward_url_error(value):
    """Blank, or http(s)://host[:port] with nothing after it: the sidecar adds
    /api/ingest/... itself."""
    if not isinstance(value, str):
        return "forward_url must be a string."
    value = value.strip()
    if value and not _FORWARD_URL_RE.match(value):
        return "forward_url must look like http://host:port (no path), or be blank."
    return None


@bp.route('/hosts/<int:host_id>/status', methods=['GET'], endpoint='get_host_relay_status')
@jwt_required()
def get_host_relay_status(host_id):
    """Live sidecar probe, shaped for the panel's status badge.

    One SSH round trip, so this is a separate endpoint from the form load --
    the panel fetches it once per open rather than on every keystroke.
    """
    host, error = _host_or_404(host_id)
    if error:
        return error

    result = _relay_status(host)
    if result is None:
        return jsonify({"error": {"message": "Host not found"}}), 404
    ok, label, routed = result
    return jsonify({"data": {'ok': ok, 'label': label, 'routed_instances': routed}})


def _relay_status(host):
    """(ok, label, routed instances) of the relay sidecar, or None when the
    host is gone. One SSH probe and one stats-hub call."""
    from .relay_ops import get_relay_status_logic
    from .settings import get_host_forward_url

    status = get_relay_status_logic(host.id)
    if status is None:
        return None

    if not status.get('enabled'):
        label = 'Sidecar disabled'
    elif status.get('reachable'):
        routed = len(status.get('routed_instances') or [])
        label = f'Reachable, {routed} instance(s) routed'
    else:
        label = status.get('error') or 'Unreachable'
    label = f'{label}; {_access_line(host)}'
    forward = get_host_forward_url(host.id)
    if forward:
        # stats-hub sees the POSTs from the relay's address, not this host's.
        label = f'{label}; sends through {forward}'
    return (bool(status.get('enabled') and status.get('reachable')), label,
            status.get('routed_instances') or [])


def _allow_or_error(host):
    """None once stats-hub lets the host in, else the error response."""
    from .settings import HubAccessError, allow_host

    try:
        allow_host(host)
    except HubAccessError as exc:
        return jsonify({"error": {"message": f"stats-hub did not let this host in: {exc}"}}), exc.status
    return None


def _access_line(host):
    """'Firewall ok; telemetry 5 s ago' from stats-hub, or why it is unknown."""
    from .settings import HubAccessError, firewall_label, host_access_status

    try:
        state = host_access_status(host)
    except HubAccessError as exc:
        return f'firewall status: {exc.label}'
    seen = state.get('last_telemetry_at')
    telemetry = (f'telemetry {max(0, int(time.time() - seen))} s ago'
                 if isinstance(seen, (int, float)) else 'no telemetry seen')
    return f'{firewall_label(state)}; {telemetry}'


@bp.route('/hosts/<int:host_id>', methods=['PUT'], endpoint='update_host_relay')
@jwt_required()
def update_host_relay(host_id):
    """Applies the host panel in one submit: overrides first, then the
    enable/disable toggle if it actually changed.

    Order matters. Writing the overrides before flipping the switch means a
    relay being turned on is configured with the values the operator just
    typed, not the previous ones -- the built-in UI got this right by having
    two separate buttons, and collapsing them into one form is exactly where
    it would be easy to get wrong.
    """
    from ui import db
    from ui.database import update_host
    from ui.models import HostStatus
    from ui.task_lock import acquire_lock, release_lock
    from .relay_ops import push_relay_config_logic
    from ui.task_logic.job_failure_handlers import host_job_failure_handler
    from ui.tasks import enqueue_task
    from .settings import (
        is_relay_enabled, set_host_forward_url, set_host_stats_hub_ingest_token,
        set_host_stats_hub_url,
    )

    host, error = _host_or_404(host_id)
    if error:
        return error

    data = request.get_json(silent=True) or {}
    url = data.get('url_override', '')
    token = data.get('ingest_token_override', '')
    if not isinstance(url, str) or not isinstance(token, str):
        return jsonify({"error": {"message": "url_override and ingest_token_override must be strings."}}), 400
    # A client that does not send forward_url keeps the stored one.
    has_forward = 'forward_url' in data
    if has_forward:
        forward_error = _forward_url_error(data['forward_url'])
        if forward_error:
            return jsonify({"error": {"message": forward_error}}), 400
    wanted = bool(data.get('enabled', False))

    set_host_stats_hub_url(host_id, url)
    set_host_stats_hub_ingest_token(host_id, token)
    if has_forward:
        set_host_forward_url(host_id, data['forward_url'])
    db.session.commit()

    if wanted == is_relay_enabled(host_id):
        # Nothing to install or remove -- just re-push the config so an edited
        # URL/token reaches a relay that is already running.
        if wanted:
            error = _allow_or_error(host)
            if error:
                return error
        push_relay_config_logic(host_id)
        return jsonify({"data": {"enabled": wanted}, "message": "Relay configuration updated."})

    if host.status != HostStatus.ACTIVE:
        return jsonify({"error": {
            "message": f"Host must be ACTIVE to change the relay. Current state: {host.status.value}"
        }}), 400

    lock_token = str(uuid.uuid4())
    if not acquire_lock('host', host.id, lock_token, ttl=180):
        return jsonify({"error": {
            "message": f'Another operation is running on host "{host.name}". Please wait for it to complete.'
        }}), 409
    if wanted:
        # The hub must accept the host before the relay starts sending to it;
        # only now, with the job certain to be queued, so a refused save leaves
        # no stale entry behind.
        error = _allow_or_error(host)
        if error:
            release_lock('host', host.id, lock_token)
            return error
    try:
        update_host(host.id, status=HostStatus.CONFIGURING)
        enqueue_task(TASKS['configure_host_relay'], host.id, wanted,
                     lock_token=lock_token, on_failure=host_job_failure_handler)
    except Exception as e:
        release_lock('host', host.id, lock_token)
        current_app.logger.error(f'Addon telemetry-relay: failed to queue host {host_id}: {e}', exc_info=True)
        return jsonify({"error": {"message": "Failed to initiate relay configuration"}}), 500

    return jsonify({
        "data": {"enabled": wanted},
        "message": "Telemetry relay configuration started.",
    }), 202


@bp.route('/stats-hub', methods=['GET'], endpoint='get_stats_hub')
@jwt_required()
def get_stats_hub():
    from .settings import (
        get_stats_hub_ingest_token, get_stats_hub_url, is_auto_enable_new_instances,
    )

    return jsonify({"data": {
        'url': get_stats_hub_url() or '',
        'ingest_token': get_stats_hub_ingest_token() or '',
        'auto_enable_new_instances': is_auto_enable_new_instances(),
    }})


@bp.route('/stats-hub', methods=['PUT'], endpoint='update_stats_hub')
@jwt_required()
def update_stats_hub():
    """Cluster-wide stats-hub target. Same AppSetting keys the built-in
    Settings page writes, so the two cannot disagree while both exist."""
    from ui import db
    from .settings import (
        is_auto_enable_new_instances, set_auto_enable_new_instances,
        set_stats_hub_ingest_token, set_stats_hub_url,
    )

    data = request.get_json(silent=True) or {}
    url = data.get('url', '')
    token = data.get('ingest_token', '')
    if not isinstance(url, str) or not isinstance(token, str):
        return jsonify({"error": {"message": "url and ingest_token must be strings."}}), 400
    auto = data.get('auto_enable_new_instances')
    if auto is not None and not isinstance(auto, bool):
        return jsonify({"error": {"message": "auto_enable_new_instances must be true or false."}}), 400

    set_stats_hub_url(url)
    set_stats_hub_ingest_token(token)
    if auto is not None:
        set_auto_enable_new_instances(auto)
    db.session.commit()
    return jsonify({"data": {
        'url': url.strip().rstrip('/'),
        'ingest_token': token.strip(),
        'auto_enable_new_instances': is_auto_enable_new_instances(),
    }})


@bp.route('/add-instance', methods=['GET'], endpoint='get_add_instance_defaults')
@jwt_required()
def get_add_instance_defaults():
    """Prefill of the Add Instance form's Stats Hub tab (`host_id` is passed
    by core and not needed yet): both switches follow "Switch on new
    instances", no manual server ID."""
    from .new_instance import tab_defaults

    return jsonify({"data": tab_defaults()})


def _instance_or_error(instance_id):
    from ui.database import get_instance

    instance = get_instance(instance_id)
    if not instance:
        return None, (jsonify({"error": {"message": "Instance not found."}}), 404)
    if not instance.host:
        return None, (jsonify({"error": {"message": "Instance has no associated host."}}), 400)
    return instance, None


def _cfg_enabled(instance):
    """The switch: qlx_statsHubUnifiedEnabled as the instance ends up with it
    (launch args, then qlsm's copy of server.cfg)."""
    from .instance_ops import read_instance_telemetry_cvars

    return read_instance_telemetry_cvars(instance).get('qlx_statsHubUnifiedEnabled') == '1'


# A form-only switch: saving with it on reserves a fresh server ID. It is
# never stored and a GET reads it back as off (same pattern as
# file-forwarder's rescan_keys). The open form ignores the PUT response, so
# the box stays ticked until the panel is reopened; a save within
# NEW_SERVER_ID_GUARD of the last new ID is refused rather than reserving
# yet another one.
NEW_SERVER_ID_KEY = 'new_server_id'
NEW_SERVER_ID_GUARD = timedelta(minutes=10)


@bp.route('/instances/<int:instance_id>', methods=['GET'], endpoint='get_instance_telemetry')
@jwt_required()
def get_instance_telemetry(instance_id):
    instance, error = _instance_or_error(instance_id)
    if error:
        return error
    return jsonify({"data": {"enabled": _cfg_enabled(instance), NEW_SERVER_ID_KEY: False}})


@bp.route('/instances/<int:instance_id>/status', methods=['GET'], endpoint='get_instance_telemetry_status')
@jwt_required()
def get_instance_telemetry_status(instance_id):
    """Badge for the old Telemetry panel. Local reads only."""
    instance, error = _instance_or_error(instance_id)
    if error:
        return error
    ok, label = _telemetry_status(instance)
    return jsonify({"data": {'ok': ok, 'label': label}})


def _telemetry_status(instance):
    """(ok, label) of telemetry for this instance. Local reads only."""
    from .settings import get_instance_server_id, is_relay_enabled

    if not is_relay_enabled(instance.host_id):
        return False, 'Relay off on host'
    if not _cfg_enabled(instance):
        return False, 'Off'
    server_id = get_instance_server_id(instance.id)
    if not server_id:
        return False, 'On, no server ID yet; save to repair'
    return True, f'Server ID {server_id}, relay on'


BUSY_STATUSES = ('DEPLOYING', 'CONFIGURING', 'RESTARTING', 'DELETING', 'STOPPING', 'STARTING')


def _enable_blocked(instance):
    """An error response when telemetry cannot be switched on yet, else None.

    Refuses early with a readable reason rather than queueing a task that
    would fail on the host: the relay must already be on, since the instance
    points its cvars at a sidecar that has to exist.
    """
    from .settings import is_relay_enabled, is_stats_hub_configured_for_host

    if not is_relay_enabled(instance.host_id):
        return jsonify({"error": {
            "message": "Enable the telemetry relay on this instance's host first."
        }}), 409
    if not is_stats_hub_configured_for_host(instance.host_id):
        return jsonify({"error": {
            "message": "Set the stats-hub URL and ingest token (globally or on this host) first."
        }}), 409
    return None


def _queue_instance_task(instance, task_key, what, data=None, message=None, **task_kwargs):
    """Busy check, instance lock, CONFIGURING, enqueue: shared by enable and
    disable. Returns the response, carrying `data` when given; `message`
    replaces the default "Telemetry <what> queued" one."""
    from ui.database import update_instance
    from ui.models import InstanceStatus
    from ui.task_lock import acquire_lock, release_lock
    from ui.task_logic.job_failure_handlers import instance_job_failure_handler
    from ui.tasks import enqueue_task

    if instance.status in [InstanceStatus[name] for name in BUSY_STATUSES]:
        return jsonify({"error": {
            "message": f'Instance "{instance.name}" is busy ({instance.status.value}). Try again shortly.'
        }}), 409

    lock_token = str(uuid.uuid4())
    if not acquire_lock('instance', instance.id, lock_token, ttl=180):
        return jsonify({"error": {
            "message": f'Another operation is running on instance "{instance.name}".'
        }}), 409
    try:
        previous_status = instance.status.value
        update_instance(instance.id, status=InstanceStatus.CONFIGURING)
        enqueue_task(TASKS[task_key], instance.id,
                     previous_status=previous_status, **task_kwargs,
                     lock_token=lock_token, on_failure=instance_job_failure_handler)
    except Exception as e:
        release_lock('instance', instance.id, lock_token)
        current_app.logger.error(f'Addon telemetry-relay: failed to queue instance {instance.id}: {e}',
                                 exc_info=True)
        return jsonify({"error": {"message": f"Failed to queue telemetry {what}."}}), 500

    body = {"message": message or f'Telemetry {what} queued for "{instance.name}".'}
    if data is not None:
        body["data"] = data
    return jsonify(body), 202


def _wiring_drift(instance):
    """Why an enabled instance needs the enable run again, or None when the
    stored server ID and server.cfg agree with what the enable writes."""
    from .instance_ops import (
        cfg_telemetry_cvars, launch_args_active, read_instance_telemetry_cvars,
    )
    from .settings import get_instance_server_id

    server_id = get_instance_server_id(instance.id)
    if not server_id:
        return 'no stored server ID'
    cvars = read_instance_telemetry_cvars(instance)
    if cvars.get('qlx_statsHubUnifiedEnabled') != '1':
        return 'qlx_statsHubUnifiedEnabled is not 1 in server.cfg'
    if cvars.get('qlx_statsHubServerId') != str(server_id):
        return 'qlx_statsHubServerId does not match the stored server ID'
    if not launch_args_active(instance.id):
        return 'launch args not switched on for this instance'
    if cfg_telemetry_cvars(instance):
        return 'server.cfg still sets qlx_statsHub* (now passed as launch args)'
    return None


@bp.route('/instances/<int:instance_id>', methods=['PUT'], endpoint='update_instance_telemetry')
@jwt_required()
def update_instance_telemetry(instance_id):
    """The Telemetry panel's save: off -> on queues the enable, on -> off the
    disable. Saving an enabled instance whose wiring drifted queues the
    enable again, so a plain save repairs it (one restart). `new_server_id`
    with the switch on queues the enable with a freshly reserved server ID,
    whether telemetry was on or off."""
    instance, error = _instance_or_error(instance_id)
    if error:
        return error

    body = request.get_json(silent=True)
    if not isinstance(body, dict) or not isinstance(body.get('enabled'), bool):
        return jsonify({"error": {"message": "enabled must be true or false."}}), 400
    new_server_id = body.get(NEW_SERVER_ID_KEY, False)
    if not isinstance(new_server_id, bool):
        return jsonify({"error": {"message": f"{NEW_SERVER_ID_KEY} must be true or false."}}), 400
    plan, error = _telemetry_plan(instance, body['enabled'], new_server_id)
    if error:
        return error
    if plan is None:
        return jsonify({"message": "No changes."})
    if plan['telemetry'] == 'disable':
        return _queue_instance_task(instance, 'disable_instance_telemetry', 'disable')
    if plan['new_server_id']:
        return _queue_instance_task(
            instance, 'enable_instance_telemetry', 'enable with a new server ID',
            data={"enabled": True, NEW_SERVER_ID_KEY: False}, new_server_id=True)
    return _queue_instance_task(instance, 'enable_instance_telemetry', 'enable')


def _telemetry_plan(instance, wanted, new_server_id):
    """What saving the telemetry switch has to do: (plan, error response).
    plan None is no change, else {'telemetry': 'enable' | 'disable',
    'new_server_id': bool}. Off -> on enables, on -> off disables; an
    enabled instance whose wiring drifted is enabled again, so a plain save
    repairs it; `new_server_id` with the switch on enables with a freshly
    reserved server ID, whether telemetry was on or off."""
    enabled = _cfg_enabled(instance)

    def enable(new_id=False):
        blocked = _enable_blocked(instance)
        if blocked:
            return None, blocked
        return {'telemetry': 'enable', 'new_server_id': new_id}, None

    if new_server_id:
        from .settings import get_new_server_id_at, utcnow

        if not wanted:
            return None, (jsonify({"error": {
                "message": "Switch telemetry on to get a new server ID."
            }}), 409)
        last = get_new_server_id_at(instance.id)
        if last is not None and utcnow() - last < NEW_SERVER_ID_GUARD:
            return None, (jsonify({"error": {
                "message": "A new server ID was reserved a few minutes ago; reopen the panel."
            }}), 409)
        return enable(new_id=True)

    if wanted and not enabled:
        return enable()
    if enabled and not wanted:
        return {'telemetry': 'disable', 'new_server_id': False}, None
    if not wanted:
        from .instance_ops import cfg_telemetry_cvars
        if cfg_telemetry_cvars(instance):
            # Off, but server.cfg still carries the cvars from before 1.7.0:
            # the disable moves them out of it.
            return {'telemetry': 'disable', 'new_server_id': False}, None
    if wanted:
        drift = _wiring_drift(instance)
        if drift:
            current_app.logger.info(
                f'Addon telemetry-relay: re-enabling instance {instance.id} on save: {drift}')
            return enable()
    return None, None


@bp.route('/instances/<int:instance_id>/enable', methods=['POST', 'PUT'], endpoint='enable_instance_telemetry')
@jwt_required()
def enable_instance_telemetry(instance_id):
    """Kept for one release for anything that still calls it; the panel
    saves through PUT instances/{id} now."""
    instance, error = _instance_or_error(instance_id)
    if error:
        return error
    return _enable_blocked(instance) or _queue_instance_task(
        instance, 'enable_instance_telemetry', 'enable')


# ---- Stats Hub entries (1.9.0): telemetry and the live demo stream -------
# One instance entry, one host entry, one settings section for both
# features; see hub_ui.py. The routes above stay for API clients.

STREAM_UNAVAILABLE = "The live demo stream cannot be switched on here: {why}."


def _error(message, status):
    return jsonify({"error": {"message": message}}), status


def _on_off(on):
    return jsonify({"data": {'ok': bool(on), 'label': 'On' if on else 'Off'}})


@bp.route('/hub/instances/<int:instance_id>', methods=['GET'], endpoint='get_hub_instance')
@jwt_required()
def get_hub_instance(instance_id):
    """The instance entry's form: telemetry switch, new server ID, stream
    switch, delay (the stream fields stay off and blank without a usable
    demo-stream addon)."""
    from .hub_ui import demo_stream_api

    instance, error = _instance_or_error(instance_id)
    if error:
        return error
    data = {'enabled': _cfg_enabled(instance), NEW_SERVER_ID_KEY: False,
            'stream': False, 'delay_sec': ''}
    api, _why = demo_stream_api()
    if api is not None:
        data.update(api.stats_hub_ui_instance(instance))
    return jsonify({"data": data})


@bp.route('/hub/instances/<int:instance_id>', methods=['PUT'], endpoint='update_hub_instance')
@jwt_required()
def update_hub_instance(instance_id):
    """One save for telemetry and the stream. Everything that needs the
    instance's config applied goes into one task with one apply + restart;
    a delay-only change is one hub call and no restart. Nothing is queued
    when either half refuses the save."""
    from .hub_ui import demo_stream_api

    instance, error = _instance_or_error(instance_id)
    if error:
        return error

    body = request.get_json(silent=True)
    if not isinstance(body, dict) or not isinstance(body.get('enabled'), bool):
        return _error("enabled must be true or false.", 400)
    new_server_id = body.get(NEW_SERVER_ID_KEY, False)
    if not isinstance(new_server_id, bool):
        return _error(f"{NEW_SERVER_ID_KEY} must be true or false.", 400)
    stream_wanted = body.get('stream')
    if stream_wanted is not None and not isinstance(stream_wanted, bool):
        return _error("stream must be true or false.", 400)

    plan, error = _telemetry_plan(instance, body['enabled'], new_server_id)
    if error:
        return error

    api, why = demo_stream_api()
    stream = {'action': None, 'delay': None}
    if api is not None:
        force = None
        if plan and plan['new_server_id'] and stream_wanted is not False \
                and api.stats_hub_ui_is_streaming(instance.id):
            force = 'following the new telemetry server ID'
        stream = api.stats_hub_ui_instance_plan(instance, stream_wanted, body.get('delay_sec'),
                                                force_enable=force)
        if stream['error']:
            return _error(*stream['error'])
    elif stream_wanted:
        return _error(STREAM_UNAVAILABLE.format(why=why), 409)

    task_stream = stream['action'] if stream['action'] in ('enable', 'disable') else None
    if stream['action'] == 'delay':
        # One hub call, no restart; done before any task is queued so a hub
        # refusal leaves the whole save undone.
        result, status = api.stats_hub_ui_set_delay(instance, stream['delay'])
        if plan is None or status >= 400:
            return jsonify(result), status
    if plan is None and task_stream is None:
        return jsonify({"message": "No changes."})

    return _queue_instance_task(
        instance, 'apply_stats_hub_instance', 'Stats Hub change',
        message=f'Stats Hub change queued for "{instance.name}" (one apply and restart).',
        telemetry=plan['telemetry'] if plan else None,
        new_server_id=bool(plan and plan['new_server_id']),
        stream=task_stream,
        delay_sec=stream['delay'] if task_stream == 'enable' else None)


@bp.route('/hub/instances/<int:instance_id>/status', methods=['GET'],
          endpoint='get_hub_instance_status')
@jwt_required()
def get_hub_instance_status(instance_id):
    """The entry's badge inside the panel: both features in one line."""
    from .hub_ui import demo_stream_api

    instance, error = _instance_or_error(instance_id)
    if error:
        return error
    tele_on = _cfg_enabled(instance)
    tele_ok, tele_label = _telemetry_status(instance)
    api, why = demo_stream_api()
    if api is None:
        return jsonify({"data": {
            'ok': tele_on and tele_ok,
            'label': f'Telemetry: {tele_label}. Live demo stream: not available, {why}.'}})
    stream_on = api.stats_hub_ui_is_streaming(instance.id)
    stream_ok, stream_label = api.stats_hub_ui_instance_status(instance)
    ok = (tele_on or stream_on) and (tele_ok or not tele_on) and (stream_ok or not stream_on)
    return jsonify({"data": {
        'ok': ok, 'label': f'Telemetry: {tele_label}. Live demo stream: {stream_label}.'}})


@bp.route('/hub/instances/<int:instance_id>/menu-status', methods=['GET'],
          endpoint='get_hub_instance_menu_status')
@jwt_required()
def get_hub_instance_menu_status(instance_id):
    """On when telemetry or the live demo stream is switched on for the
    instance, else Off. Local reads only: it is fetched every time the menu
    opens; the panel's own badge has the detail."""
    from .hub_ui import demo_stream_api

    instance, error = _instance_or_error(instance_id)
    if error:
        return error
    if _cfg_enabled(instance):
        return _on_off(True)
    api, _why = demo_stream_api()
    return _on_off(api is not None and api.stats_hub_ui_is_streaming(instance.id))


_TUNNEL_DEFAULTS = {'tunnel_enabled': False, 'local_port': '', 'relay_host': '', 'relay_port': ''}


@bp.route('/hub/hosts/<int:host_id>', methods=['GET'], endpoint='get_hub_host')
@jwt_required()
def get_hub_host(host_id):
    """The host entry's form: relay and tunnel. The ingest token override is
    a secret and never sent back (blank keeps the stored one)."""
    from .hub_ui import demo_stream_api
    from .settings import get_host_forward_url, get_host_stats_hub_url, is_relay_enabled

    _, error = _host_or_404(host_id)
    if error:
        return error
    data = {
        'enabled': is_relay_enabled(host_id),
        'url_override': get_host_stats_hub_url(host_id) or '',
        'ingest_token_override': '',
        'forward_url': get_host_forward_url(host_id) or '',
        **_TUNNEL_DEFAULTS,
    }
    api, _why = demo_stream_api()
    if api is not None:
        data.update(api.stats_hub_ui_host(host_id))
    return jsonify({"data": data})


@bp.route('/hub/hosts/<int:host_id>', methods=['PUT'], endpoint='update_hub_host')
@jwt_required()
def update_hub_host(host_id):
    """One save for the relay and the tunnel. The stats-hub override is
    stored for both addons, so they keep pointing at the same hub. Whatever
    has to run on the host (relay and/or tunnel playbook) goes into one host
    task under one lock."""
    from ui import db
    from ui.database import update_host
    from ui.models import HostStatus
    from ui.task_lock import acquire_lock, release_lock
    from ui.task_logic.job_failure_handlers import host_job_failure_handler
    from ui.tasks import enqueue_task

    from .hub_ui import demo_stream_api
    from .relay_ops import push_relay_config_logic
    from .settings import (
        get_host_stats_hub_ingest_token, get_host_stats_hub_url, is_relay_enabled,
        set_host_forward_url, set_host_stats_hub_ingest_token, set_host_stats_hub_url,
    )

    host, error = _host_or_404(host_id)
    if error:
        return error

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return _error("The request body must be a JSON object.", 400)
    url = data.get('url_override', '')
    token = data.get('ingest_token_override', '')
    if not isinstance(url, str) or not isinstance(token, str):
        return _error("url_override and ingest_token_override must be strings.", 400)
    if 'forward_url' in data:
        forward_error = _forward_url_error(data['forward_url'])
        if forward_error:
            return _error(forward_error, 400)
    relay_wanted = bool(data.get('enabled', False))
    tunnel_wanted = data.get('tunnel_enabled')

    api, why = demo_stream_api()
    tunnel_task = None
    if api is not None and tunnel_wanted is not None:
        tunnel_data = {'enabled': bool(tunnel_wanted), 'local_port': data.get('local_port', '')}
        for key in ('relay_host', 'relay_port'):
            if key in data:
                tunnel_data[key] = data[key]
        tunnel = api.stats_hub_ui_host_plan(host, tunnel_data)
        if tunnel['error']:
            return _error(*tunnel['error'])
        tunnel_task = tunnel['tunnel']
    elif tunnel_wanted:
        return _error(f"The demo stream tunnel cannot be switched on here: {why}.", 409)

    set_host_stats_hub_url(host_id, url)
    if not url.strip():
        # No override URL, no override token: blank keeps a stored token, so
        # clearing the URL is how the pair goes back to the Settings values.
        set_host_stats_hub_ingest_token(host_id, '')
    elif token.strip():
        set_host_stats_hub_ingest_token(host_id, token)
    if 'forward_url' in data:
        set_host_forward_url(host_id, data['forward_url'])
    if api is not None:
        api.stats_hub_ui_save_host_hub(host_id, get_host_stats_hub_url(host_id) or '',
                                       get_host_stats_hub_ingest_token(host_id) or '')
    db.session.commit()

    allowed = False
    relay_task = None
    if relay_wanted == is_relay_enabled(host_id):
        # Nothing to install or remove: re-push the config so an edited
        # URL/token reaches a relay that is already running.
        if relay_wanted:
            error = _allow_or_error(host)
            if error:
                return error
            allowed = True
        push_relay_config_logic(host_id)
    else:
        relay_task = relay_wanted

    result = {'enabled': relay_wanted,
              'tunnel_enabled': bool(tunnel_wanted) if api is not None else False}
    if relay_task is None and tunnel_task is None:
        return jsonify({"data": result, "message": "Stats Hub host settings saved."})

    if host.status != HostStatus.ACTIVE:
        return _error(f"Host must be ACTIVE to change the relay or the tunnel. "
                      f"Current state: {host.status.value}", 400)
    lock_token = str(uuid.uuid4())
    if not acquire_lock('host', host.id, lock_token, ttl=480):
        return _error(f'Another operation is running on host "{host.name}". '
                      'Please wait for it to complete.', 409)
    if not allowed and (relay_task or (tunnel_task and tunnel_task[0])):
        # The hub must accept the host before the relay or the tunnel sends
        # to it; only now, with the job certain to be queued.
        error = _allow_or_error(host)
        if error:
            release_lock('host', host.id, lock_token)
            return error
    try:
        update_host(host.id, status=HostStatus.CONFIGURING)
        enqueue_task(TASKS['configure_stats_hub_host'], host.id, relay=relay_task,
                     tunnel=tunnel_task, lock_token=lock_token,
                     on_failure=host_job_failure_handler)
    except Exception as e:
        release_lock('host', host.id, lock_token)
        current_app.logger.error(f'Addon telemetry-relay: failed to queue Stats Hub host {host_id}: {e}',
                                 exc_info=True)
        return _error("Failed to initiate the Stats Hub host configuration", 500)
    return jsonify({"data": result, "message": "Stats Hub host configuration started."}), 202


@bp.route('/hub/hosts/<int:host_id>/status', methods=['GET'], endpoint='get_hub_host_status')
@jwt_required()
def get_hub_host_status(host_id):
    """The host entry's badge inside the panel: relay probe (SSH) and, when
    the tunnel is on, its link at stats-hub."""
    from .hub_ui import demo_stream_api

    host, error = _host_or_404(host_id)
    if error:
        return error
    result = _relay_status(host)
    if result is None:
        return _error("Host not found", 404)
    relay_ok, relay_label, _routed = result
    api, why = demo_stream_api()
    if api is None:
        tunnel_ok, tunnel_label = True, f'not available, {why}'
    elif not api.stats_hub_ui_tunnel_enabled(host_id):
        tunnel_ok, tunnel_label = True, 'off'
    else:
        tunnel_ok, tunnel_label = api.stats_hub_ui_host_status(host)
    return jsonify({"data": {'ok': relay_ok and tunnel_ok,
                             'label': f'Relay: {relay_label}. Tunnel: {tunnel_label}.'}})


@bp.route('/hub/hosts/<int:host_id>/menu-status', methods=['GET'],
          endpoint='get_hub_host_menu_status')
@jwt_required()
def get_hub_host_menu_status(host_id):
    """On when the relay is on, and the tunnel too once any instance on the
    host streams; else Off. Local reads only."""
    from ui.models import QLInstance

    from .hub_ui import demo_stream_api
    from .settings import is_relay_enabled

    _, error = _host_or_404(host_id)
    if error:
        return error
    if not is_relay_enabled(host_id):
        return _on_off(False)
    api, _why = demo_stream_api()
    if api is None or api.stats_hub_ui_tunnel_enabled(host_id):
        return _on_off(True)
    streaming = any(api.stats_hub_ui_is_streaming(instance.id)
                    for instance in QLInstance.query.filter_by(host_id=host_id).all())
    return _on_off(not streaming)


@bp.route('/hub/settings', methods=['GET'], endpoint='get_hub_settings')
@jwt_required()
def get_hub_settings():
    """The settings section: hub URL, ingest token (never sent back),
    switch on new instances, the demo stream relay."""
    from .hub_ui import demo_stream_api
    from .settings import get_stats_hub_url, is_auto_enable_new_instances

    data = {'url': get_stats_hub_url() or '', 'ingest_token': '',
            'auto_enable_new_instances': is_auto_enable_new_instances(),
            'relay_host': '', 'relay_port': ''}
    api, _why = demo_stream_api()
    if api is not None:
        demo = api.stats_hub_ui_settings()
        data.update(relay_host=demo['relay_host'], relay_port=demo['relay_port'])
    return jsonify({"data": data})


@bp.route('/hub/settings', methods=['PUT'], endpoint='update_hub_settings')
@jwt_required()
def update_hub_settings():
    """Stores the hub URL and token for both addons (a blank token keeps the
    stored one), so telemetry and the stream register on the same hub."""
    from ui import db

    from .hub_ui import demo_stream_api
    from .settings import (
        get_stats_hub_ingest_token, get_stats_hub_url, set_auto_enable_new_instances,
        set_stats_hub_ingest_token, set_stats_hub_url,
    )

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return _error("The request body must be a JSON object.", 400)
    url = data.get('url', '')
    token = data.get('ingest_token', '')
    if not isinstance(url, str) or not isinstance(token, str):
        return _error("url and ingest_token must be strings.", 400)
    auto = data.get('auto_enable_new_instances')
    if auto is not None and not isinstance(auto, bool):
        return _error("auto_enable_new_instances must be true or false.", 400)
    relay_host = data.get('relay_host', '')
    relay_port = data.get('relay_port', '')
    api, _why = demo_stream_api()
    if api is not None:
        relay_error = api.stats_hub_ui_validate_settings(relay_host, relay_port)
        if relay_error:
            return _error(relay_error, 400)

    set_stats_hub_url(url)
    if token.strip():
        set_stats_hub_ingest_token(token)
    if auto is not None:
        set_auto_enable_new_instances(auto)
    if api is not None:
        db.session.flush()
        api.stats_hub_ui_save_settings(relay_host, relay_port, get_stats_hub_url() or '',
                                       get_stats_hub_ingest_token() or '')
    db.session.commit()
    return get_hub_settings()


@bp.route('/hub/settings/status', methods=['GET'], endpoint='get_hub_settings_status')
@jwt_required()
def get_hub_settings_status():
    """Whether both addons are set up and point at the same hub. Never
    shows a token."""
    from .hub_ui import demo_stream_api
    from .settings import get_stats_hub_ingest_token, get_stats_hub_url

    url = get_stats_hub_url()
    token = get_stats_hub_ingest_token()

    def status(ok, label):
        return jsonify({"data": {'ok': ok, 'label': label}})

    if not url or not token:
        return status(False, 'Stats-hub URL or ingest token not set')
    api, why = demo_stream_api()
    if api is None:
        return status(True, f'Telemetry uses {url}; live demo stream not available, {why}')
    demo = api.stats_hub_ui_settings()
    if demo['stats_hub_url'] != url:
        return status(False, f"The live demo stream still uses {demo['stats_hub_url'] or 'no stats-hub'}; "
                             'Save to point it at the URL above')
    if not api.stats_hub_ui_ingest_token_equals(token):
        return status(False, 'The live demo stream has another ingest token; Save to use the one above')
    if not (demo['relay_host'] and demo['relay_port']):
        return status(False, f'Telemetry and live demo stream use {url}; demo stream relay not set')
    return status(True, f'Telemetry and live demo stream use {url}')


# Set by register(); the endpoints enqueue through these rather than through
# ui.tasks, which no longer knows telemetry exists.
TASKS = {}


def register(ctx):
    ctx.blueprint(bp)

    def backfill_at_startup(state):
        # Instances enabled before 1.5.0 have only the routed server ID key;
        # copy it to the reserved key so a disable keeps it. The database may
        # not be ready yet (first boot, tests): then set_instance_server_id
        # copies it when the routed key is cleared.
        from ui import db
        from ui.models import AppSetting

        from .settings import backfill_reserved_server_ids

        try:
            with state.app.app_context():
                if not db.inspect(db.engine).has_table(AppSetting.__tablename__):
                    return
                if backfill_reserved_server_ids():
                    db.session.commit()
        except Exception:
            state.app.logger.warning('telemetry-relay: reserved server ID backfill skipped', exc_info=True)
            with state.app.app_context():
                db.session.rollback()

    bp.record_once(backfill_at_startup)

    @ctx.task(timeout=120, lock_scope='host')
    def configure_host_relay(host_id, enabled):
        """Install or remove the relay sidecar on a host.

        ctx.task wraps this with the app context and the lock release, the
        same way ui/tasks.py wraps core's own tasks -- and publishes it as a
        module attribute so the RQ worker can resolve it by name. Without that
        last part the job queues and never runs; see
        tests/test_addon_tasks_are_dequeuable.py.
        """
        from .relay_ops import configure_host_telemetry_relay_logic

        return configure_host_telemetry_relay_logic(host_id, enabled)

    @ctx.task(timeout=300, lock_scope='instance')
    def enable_instance_telemetry_task(instance_id, previous_status=None, new_server_id=False):
        """Reserve a stats-hub server_id (a fresh one with `new_server_id`)
        and wire the instance's cvars."""
        from .instance_ops import enable_instance_telemetry_logic

        return enable_instance_telemetry_logic(instance_id, previous_status=previous_status,
                                               new_server_id=new_server_id)

    @ctx.task(timeout=300, lock_scope='instance')
    def disable_instance_telemetry_task(instance_id, previous_status=None):
        """Switch telemetry off; the reserved server_id is kept."""
        from .instance_ops import disable_instance_telemetry_logic

        return disable_instance_telemetry_logic(instance_id, previous_status=previous_status)

    @ctx.task(timeout=120)
    def push_host_relay_routes(host_id):
        """Re-render the relay's routes on a host (a new instance's server ID).
        Touches the relay sidecar's config only, no game server."""
        from .relay_ops import push_relay_config_logic

        return push_relay_config_logic(host_id)

    @ctx.task(timeout=600, lock_scope='instance')
    def apply_stats_hub_instance(instance_id, previous_status=None, telemetry=None,
                                 new_server_id=False, stream=None, delay_sec=None):
        """A Stats Hub instance save: telemetry and the stream as asked,
        then one apply + restart for both (hub_ui.py)."""
        from .hub_ui import apply_instance_logic

        return apply_instance_logic(instance_id, previous_status=previous_status,
                                    telemetry=telemetry, new_server_id=new_server_id,
                                    stream=stream, delay_sec=delay_sec)

    @ctx.task(timeout=450, lock_scope='host')
    def configure_stats_hub_host(host_id, relay=None, tunnel=None):
        """A Stats Hub host save: relay and/or tunnel playbook in one task."""
        from .hub_ui import configure_host_logic

        return configure_host_logic(host_id, relay=relay, tunnel=tunnel)

    TASKS['apply_stats_hub_instance'] = apply_stats_hub_instance
    TASKS['configure_stats_hub_host'] = configure_stats_hub_host
    TASKS['configure_host_relay'] = configure_host_relay
    TASKS['push_host_relay_routes'] = push_host_relay_routes
    TASKS['enable_instance_telemetry'] = enable_instance_telemetry_task
    TASKS['disable_instance_telemetry'] = disable_instance_telemetry_task

    @ctx.on('instance.launch_args')
    def telemetry_launch_args(instance_id):
        """qlx_statsHub* as `+set` from this addon's own state, so they live
        in no file a preset could carry or overwrite. Core only asks when the
        addon is on for the instance (see instance_ops.launch_args_active);
        a server.cfg line for the same cvar still wins, it is exec'd later."""
        from .instance_ops import telemetry_launch_cvars

        return [f'+set {name} "{value}"'
                for name, value in telemetry_launch_cvars(instance_id).items()]

    # qlsm with the Add Instance addon tab only; an older core has no such
    # hook and ctx.on() would mark the whole addon broken.
    from ui.addons.hooks import HOOK_SCOPES
    if 'instance.created' in HOOK_SCOPES:
        @ctx.on('instance.created')
        def prepare_new_instance(instance_id, options):
            """Telemetry and the live demo stream for a new instance under one
            server ID, before its first deploy; see new_instance.py."""
            from .new_instance import prepare_new_instance as prepare

            prepare(instance_id, options, push_routes=TASKS.get('push_host_relay_routes'))

    @ctx.on('instance.config_applied')
    def resync_server_id(instance_id):
        """Keep the relay's routing entry in step with what server.cfg
        actually carries.

        Runs after every config apply, including the one an operator triggers
        by editing qlx_statsHubServerId by hand in the Plugins tab and never
        touching the assisted flow. Without it that server.cfg looks fully
        configured while the relay's routing table stays empty and every POST
        is dropped as "no_route" -- a real incident, see
        qlsm-telemetry-relay-server-id-db-desync in project memory.
        """
        from ui.database import get_instance

        from .instance_ops import sync_instance_server_id_from_config

        instance = get_instance(instance_id)
        if instance is not None:
            sync_instance_server_id_from_config(instance)

    @ctx.on('host.delete')
    def forget_host(host_id):
        """Drop this host's relay settings when the host goes away.

        Core clears the addon's own AddonState rows; these are the legacy
        AppSetting keys the shared logic still reads, which nothing else
        would clean up.
        """
        from .settings import (
            set_host_forward_url, set_host_stats_hub_ingest_token, set_host_stats_hub_url,
            set_relay_enabled,
        )
        set_relay_enabled(host_id, False)
        set_host_forward_url(host_id, '')
        set_host_stats_hub_url(host_id, '')
        set_host_stats_hub_ingest_token(host_id, '')

    @ctx.on('instance.delete')
    def forget_instance(instance_id):
        from .settings import (
            set_instance_server_id, set_new_server_id_at, set_reserved_server_id,
        )
        set_instance_server_id(instance_id, None)
        set_reserved_server_id(instance_id, None)
        set_new_server_id_at(instance_id, None)
