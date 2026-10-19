"""Live demo stream, as an addon.

Unlike demo-management's port, this one **adds** a UI rather than
reproducing one: the feature had two instance endpoints and two settings
endpoints and no frontend whatsoever -- nothing in frontend-react references
it. So there was no parity risk, and a declarative panel is strictly more
than what existed before.

Owns the feature outright, like telemetry-relay: `.settings`, `.stats_hub`
and `.instance_ops` are this addon's own, no longer core's -- core's four
built-in demo-stream endpoints were deleted once this addon's endpoints fully
replaced them (see addons/README.md in qlsm).
"""
import math
import uuid

from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import jwt_required

bp = Blueprint('demo_stream_addon', __name__)


def _instance_or_error(instance_id):
    from ui.database import get_instance

    instance = get_instance(instance_id)
    if not instance:
        return None, (jsonify({"error": {"message": "Instance not found."}}), 404)
    if not instance.host:
        return None, (jsonify({"error": {"message": "Instance has no associated host."}}), 400)
    return instance, None


def _relay_error(host, port):
    """The relay address check shared by PUT relay and PUT settings."""
    if not isinstance(host, str) or not isinstance(port, str):
        return jsonify({"error": {"message": "host and port must be strings."}}), 400
    if port and not port.strip().isdigit():
        return jsonify({"error": {"message": "port must be a number."}}), 400
    return None


def _stats_hub_error(url, token):
    """The stats-hub target check shared by PUT stats-hub and PUT settings."""
    if not isinstance(url, str) or not isinstance(token, str):
        return jsonify({"error": {"message": "url and ingest_token must be strings."}}), 400
    return None


@bp.route('/relay', methods=['GET'], endpoint='get_relay')
@jwt_required()
def get_relay():
    from .settings import get_relay_host, get_relay_port

    return jsonify({"data": {'host': get_relay_host() or '', 'port': get_relay_port() or ''}})


@bp.route('/relay', methods=['PUT'], endpoint='update_relay')
@jwt_required()
def update_relay():
    """Cluster-wide relay address."""
    from ui import db
    from .settings import set_relay_host, set_relay_port

    data = request.get_json(silent=True) or {}
    host = data.get('host', '')
    port = data.get('port', '')
    error = _relay_error(host, port)
    if error:
        return error

    set_relay_host(host)
    set_relay_port(port)
    db.session.commit()
    return jsonify({"data": {'host': host.strip(), 'port': port.strip()}})


@bp.route('/stats-hub', methods=['GET'], endpoint='get_stats_hub')
@jwt_required()
def get_stats_hub():
    """This addon's own stats-hub target - independent of telemetry-relay's,
    see .stats_hub's module docstring for why they are not shared."""
    from .settings import get_stats_hub_ingest_token, get_stats_hub_url

    return jsonify({"data": {
        'url': get_stats_hub_url() or '',
        'ingest_token': get_stats_hub_ingest_token() or '',
    }})


@bp.route('/stats-hub', methods=['PUT'], endpoint='update_stats_hub')
@jwt_required()
def update_stats_hub():
    from ui import db
    from .settings import set_stats_hub_ingest_token, set_stats_hub_url

    data = request.get_json(silent=True) or {}
    url = data.get('url', '')
    token = data.get('ingest_token', '')
    error = _stats_hub_error(url, token)
    if error:
        return error

    set_stats_hub_url(url)
    set_stats_hub_ingest_token(token)
    db.session.commit()
    return jsonify({"data": {'url': url.strip().rstrip('/'), 'ingest_token': token.strip()}})


def _settings_data():
    from .settings import get_relay_host, get_relay_port, get_stats_hub_url

    # The ingest token is a secret: never sent back, a blank PUT keeps it.
    return {
        'relay_host': get_relay_host() or '',
        'relay_port': get_relay_port() or '',
        'stats_hub_url': get_stats_hub_url() or '',
        'ingest_token': '',
    }


@bp.route('/settings', methods=['GET'], endpoint='get_settings')
@jwt_required()
def get_settings():
    """The one settings section: relay address and stats-hub target."""
    return jsonify({"data": _settings_data()})


@bp.route('/settings', methods=['PUT'], endpoint='update_settings')
@jwt_required()
def update_settings():
    """PUT relay and PUT stats-hub in one form, with their validation. A
    blank ingest token keeps the stored one (the form never loads it)."""
    from ui import db
    from .settings import (
        set_relay_host, set_relay_port, set_stats_hub_ingest_token, set_stats_hub_url,
    )

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": {"message": "The request body must be a JSON object."}}), 400
    host = data.get('relay_host', '')
    port = data.get('relay_port', '')
    url = data.get('stats_hub_url', '')
    token = data.get('ingest_token', '')
    error = _relay_error(host, port) or _stats_hub_error(url, token)
    if error:
        return error

    set_relay_host(host)
    set_relay_port(port)
    set_stats_hub_url(url)
    if token.strip():
        set_stats_hub_ingest_token(token)
    db.session.commit()
    return jsonify({"data": _settings_data(), "message": "Live Demo Stream settings saved."})


def _host_or_404(host_id):
    from ui.database import get_host

    host = get_host(host_id)
    if not host:
        return None, (jsonify({"error": {"message": "Host not found"}}), 404)
    return host, None


@bp.route('/hosts/<int:host_id>', methods=['GET'], endpoint='get_host_tunnel')
@jwt_required()
def get_host_tunnel(host_id):
    from .settings import get_host_relay_override, get_host_tunnel_port, is_host_tunnel_enabled

    _, error = _host_or_404(host_id)
    if error:
        return error
    relay_host, relay_port = get_host_relay_override(host_id)
    return jsonify({"data": {
        'enabled': is_host_tunnel_enabled(host_id),
        'local_port': get_host_tunnel_port(host_id),
        'relay_host': relay_host or '',
        'relay_port': relay_port or '',
    }})


_RELAY_HOST_CHARS = set('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-:[]')


def _host_relay_error(host, port):
    """The per-host relay override check: both blank, or a host name / IP and
    a port number. The values go into stunnel.conf, so nothing else passes."""
    if not isinstance(host, str) or not isinstance(port, str):
        return "relay_host and relay_port must be strings."
    host, port = host.strip(), port.strip()
    if not host and not port:
        return None
    if not host or not port:
        return "Set both relay host and relay port, or leave both blank for the relay in Settings."
    if len(host) > 253 or not set(host) <= _RELAY_HOST_CHARS:
        return "relay_host must be a host name or an IP address."
    if not (port.isascii() and port.isdigit() and 1 <= int(port) <= 65535):
        return "relay_port must be a port number (1-65535)."
    return None


def _host_status(host):
    """(ok, label) for the tunnel's status badge: whether stats-hub lets this
    host in and has a demo-stream link from it. One call to stats-hub."""
    from .settings import HubAccessError, firewall_label, get_host_relay_override, host_access_status

    try:
        state = host_access_status(host)
    except HubAccessError as exc:
        return False, exc.label
    firewall = firewall_label(state)
    relay_host, relay_port = get_host_relay_override(host.id)
    if relay_host:
        # stats-hub sees the link from the relay's address, not this host's, so
        # it cannot be counted here.
        return (firewall == 'Firewall ok',
                f"{firewall}; demo stream through relay {relay_host}:{relay_port}")
    connected = (state.get('demo_stream_links') or 0) > 0
    return (firewall == 'Firewall ok' and connected,
            f"{firewall}; demo stream {'connected' if connected else 'not connected'}")


@bp.route('/hosts/<int:host_id>/status', methods=['GET'], endpoint='get_host_tunnel_status')
@jwt_required()
def get_host_tunnel_status(host_id):
    """Whether stats-hub lets this host in and has a demo-stream link from it,
    shaped for the tunnel panel's status badge. One call to stats-hub."""
    host, error = _host_or_404(host_id)
    if error:
        return error
    ok, label = _host_status(host)
    return jsonify({"data": {'ok': ok, 'label': label}})


def _tunnel_plan(host, data):
    """What a tunnel save has to do, shared by PUT hosts/{id} and the Stats
    Hub host panel of telemetry-relay. Validates, stores the relay override
    (and, with nothing installed and nothing wanted, the port), fetches the
    hub certificate when the tunnel is wanted. Returns a dict:
    `error` (message, status) or None; `tunnel` (wanted, port, cert_pem) when
    the host task has to run, else None; `port` the port asked for."""
    from ui import db
    from .settings import (
        DEFAULT_TUNNEL_PORT, get_effective_relay, is_host_tunnel_enabled,
        set_host_relay_override, set_host_tunnel_port,
    )
    from .tunnel_ops import TunnelCertError, fetch_hub_tls_cert

    host_id = host.id
    port = data.get('local_port', '')
    # 1024 and up: the tunnel runs as user ql and cannot bind privileged ports.
    if not isinstance(port, str) or (
            port.strip() and not (port.strip().isascii() and port.strip().isdigit()
                                  and 1024 <= int(port.strip()) <= 65535)):
        return {'error': ("local_port must be a port number (1024-65535).", 400),
                'tunnel': None, 'port': None}

    port = port.strip() or DEFAULT_TUNNEL_PORT
    wanted = bool(data.get('enabled', False))
    # A client that does not send the relay fields keeps the stored override.
    if 'relay_host' in data or 'relay_port' in data:
        relay_host = data.get('relay_host', '')
        relay_port = data.get('relay_port', '')
        relay_error = _host_relay_error(relay_host, relay_port)
        if relay_error:
            return {'error': (relay_error, 400), 'tunnel': None, 'port': port}
        # Stored before the job is queued, so the playbook renders the value
        # just typed (the tunnel's own port is stored only once it succeeds).
        set_host_relay_override(host_id, relay_host, relay_port)
        db.session.commit()

    if not wanted and not is_host_tunnel_enabled(host_id):
        # Nothing is installed, so there is nothing to wait for: just remember
        # the port. Otherwise the port is stored only once the playbook succeeds.
        set_host_tunnel_port(host_id, port)
        db.session.commit()
        return {'error': None, 'tunnel': None, 'port': port}

    cert_pem = ''
    if wanted:
        if get_effective_relay(host_id)[0] is None:
            return {'error': ("Set the demo-stream relay host and port in Settings first.", 409),
                    'tunnel': None, 'port': port}
        try:
            cert_pem = fetch_hub_tls_cert(host_id)
        except TunnelCertError as exc:
            return {'error': (str(exc), 409), 'tunnel': None, 'port': port}
    return {'error': None, 'tunnel': (wanted, port, cert_pem), 'port': port}


@bp.route('/hosts/<int:host_id>', methods=['PUT'], endpoint='update_host_tunnel')
@jwt_required()
def update_host_tunnel(host_id):
    """Stores the local port, then installs/removes the host's stunnel client.
    Enabled-and-wanted always re-queues (the playbook is idempotent), which is
    what lets a port edit reach a tunnel that is already running."""
    from ui.database import update_host
    from ui.models import HostStatus
    from ui.task_lock import acquire_lock, release_lock
    from ui.task_logic.job_failure_handlers import host_job_failure_handler
    from ui.tasks import enqueue_task
    from .settings import HubAccessError, allow_host

    host, error = _host_or_404(host_id)
    if error:
        return error

    plan = _tunnel_plan(host, request.get_json(silent=True) or {})
    if plan['error']:
        message, status = plan['error']
        return jsonify({"error": {"message": message}}), status
    if plan['tunnel'] is None:
        return jsonify({"data": {'enabled': False, 'local_port': plan['port']},
                        "message": "Tunnel settings saved."})
    wanted, port, cert_pem = plan['tunnel']

    if host.status != HostStatus.ACTIVE:
        return jsonify({"error": {
            "message": f"Host must be ACTIVE to change the tunnel. Current state: {host.status.value}"
        }}), 400

    lock_token = str(uuid.uuid4())
    if not acquire_lock('host', host.id, lock_token, ttl=360):
        return jsonify({"error": {
            "message": f'Another operation is running on host "{host.name}". Please wait for it to complete.'
        }}), 409
    if wanted:
        # The hub must accept the host before the tunnel starts streaming to it;
        # only now, with the job certain to be queued, so a refused save leaves
        # no stale entry behind.
        try:
            allow_host(host)
        except HubAccessError as exc:
            release_lock('host', host.id, lock_token)
            return jsonify({"error": {"message": f"stats-hub did not let this host in: {exc}"}}), exc.status
    try:
        update_host(host.id, status=HostStatus.CONFIGURING)
        enqueue_task(TASKS['configure_host_tunnel'], host.id, wanted, port, cert_pem,
                     lock_token=lock_token, on_failure=host_job_failure_handler)
    except Exception as e:
        release_lock('host', host.id, lock_token)
        current_app.logger.error(f'Addon demo-stream: failed to queue host {host_id}: {e}',
                                 exc_info=True)
        return jsonify({"error": {"message": "Failed to initiate tunnel configuration"}}), 500

    return jsonify({
        "data": {'enabled': wanted, 'local_port': port},
        "message": "Demo stream tunnel configuration started.",
    }), 202


def _hub_delay_state(instance):
    """The hub's delay state for this streaming instance, or None when it
    cannot be asked (not streaming, no stats-hub, hub error). One call."""
    from .stats_hub import HubDelayError, get_server_delay

    server_id, _ = _delay_target(instance)
    if server_id is None:
        return None
    try:
        return get_server_delay(instance.host_id, server_id)
    except HubDelayError:
        return None


def _hub_delay_state_or_lost_route(instance):
    """(state, None) like _hub_delay_state, or (None, reason) when the hub
    says it has no route for this instance's server_id: the enable has to
    run again to register it. Same single hub call."""
    from .stats_hub import HubDelayError, get_server_delay

    server_id, _ = _delay_target(instance)
    if server_id is None:
        return None, None
    try:
        return get_server_delay(instance.host_id, server_id), None
    except HubDelayError as exc:
        if exc.label == 'No route on stats-hub':
            return None, 'stats-hub has no route for its server_id'
        return None, None


def _delay_field(state):
    """The panel's delay_sec: the override, blank on the hub default."""
    return _seconds(state['delay_sec']) if state and state['override'] else ''


@bp.route('/instances/<int:instance_id>', methods=['GET'], endpoint='get_instance_stream')
@jwt_required()
def get_instance_stream(instance_id):
    """The Live Demo Stream panel: the stream switch and the hub delay
    (blank when not streaming, on the hub default, or the hub cannot be asked)."""
    from .settings import is_instance_demo_stream_enabled

    instance, error = _instance_or_error(instance_id)
    if error:
        return error
    enabled = is_instance_demo_stream_enabled(instance.id)
    state = _hub_delay_state(instance) if enabled else None
    return jsonify({"data": {'enabled': enabled, 'delay_sec': _delay_field(state)}})


def _instance_status(instance):
    """(ok, label) for the stream's status badge: says why it cannot be
    switched on, before the operator tries and gets a task that fails
    somewhere they cannot see; when streaming, the delay in effect (one hub
    call)."""
    from .settings import (
        get_instance_demo_stream_token, is_host_tunnel_enabled,
        is_instance_demo_stream_enabled, is_relay_configured,
    )

    if not is_relay_configured():
        return False, 'Relay address not set'
    if not is_host_tunnel_enabled(instance.host_id):
        return False, 'Tunnel not enabled on host'
    if not is_instance_demo_stream_enabled(instance.id):
        return False, 'Not streaming'
    if not get_instance_demo_stream_token(instance.id):
        return False, 'Enabled, no route registered yet'
    ids = _server_id_drift(instance)
    if ids:
        from .settings import is_telemetry_routing
        telemetry = (f'telemetry uses {ids[1]}' if is_telemetry_routing(instance.id, ids[1])
                     else f"telemetry's reserved ID is {ids[1]}")
        return False, f'Streaming on server ID {ids[0]}, {telemetry}; save to repair'
    state = _hub_delay_state(instance)
    label = 'Streaming'
    if state:
        label += f", delay {_seconds(state['delay_sec'])} s"
        if not state['override']:
            label += ' (hub default)'
    return True, label


@bp.route('/instances/<int:instance_id>/status', methods=['GET'], endpoint='get_instance_stream_status')
@jwt_required()
def get_instance_stream_status(instance_id):
    """Badge for the panel and the menu entry, see _instance_status."""
    instance, error = _instance_or_error(instance_id)
    if error:
        return error
    ok, label = _instance_status(instance)
    return jsonify({"data": {'ok': ok, 'label': label}})


BUSY_STATUSES = ('DEPLOYING', 'CONFIGURING', 'RESTARTING', 'DELETING', 'STOPPING', 'STARTING')


def _enable_blocked_error(instance):
    """(message, status) when the stream cannot be switched on yet, else None."""
    from .instance_ops import TUNNEL_REQUIRED_MESSAGE
    from .settings import is_host_tunnel_enabled, is_relay_configured

    if not is_relay_configured():
        return "Set the demo-stream relay host and port in Settings first.", 409
    if not is_host_tunnel_enabled(instance.host_id):
        return TUNNEL_REQUIRED_MESSAGE, 400
    return None


def _enable_blocked(instance):
    """An error response when the stream cannot be switched on yet, else None."""
    blocked = _enable_blocked_error(instance)
    if blocked:
        return jsonify({"error": {"message": blocked[0]}}), blocked[1]
    return None


def _queue_instance_task(instance, task_key, what, **task_kwargs):
    """Busy check, instance lock, CONFIGURING, enqueue: shared by enable and
    disable. Returns the response."""
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
        current_app.logger.error(f'Addon demo-stream: failed to queue instance {instance.id}: {e}',
                                 exc_info=True)
        return jsonify({"error": {"message": f"Failed to queue demo-stream {what}."}}), 500

    return jsonify({"message": f'Demo-stream {what} queued for "{instance.name}".'}), 202


def _server_id_drift(instance):
    """(stream's server_id, telemetry's) when the stream runs under another
    server_id than telemetry uses on the same stats-hub, else None. The hub
    ties a stream to its telemetry by server_id; the enable picks
    telemetry's, so running it again repairs this."""
    from .instance_ops import telemetry_server_id_on_same_hub
    from .settings import get_instance_server_id

    own = get_instance_server_id(instance.id)
    telemetry = telemetry_server_id_on_same_hub(instance.id, instance.host_id)
    if own is not None and telemetry is not None and own != telemetry:
        return own, telemetry
    return None


def _wiring_drift(instance):
    """Why a streaming instance needs the enable run again, or None when its
    stored token, server_id and server.cfg agree with what the enable writes.
    Local reads only: the stored settings and server.cfg, no hub call."""
    from .settings import (
        get_host_tunnel_port, get_instance_demo_stream_token, read_cvars_from_text,
    )

    if not get_instance_demo_stream_token(instance.id):
        return 'no stored stream token'
    ids = _server_id_drift(instance)
    if ids:
        return f"stream server_id {ids[0]} differs from telemetry's {ids[1]}"
    from .instance_ops import (
        DEMO_STREAM_CVARS, demo_stream_launch_cvars, launch_args_active, read_cfg_text,
    )

    if not launch_args_active(instance.id):
        return 'launch args not switched on for this instance'
    if read_cvars_from_text(read_cfg_text(instance) or '', DEMO_STREAM_CVARS):
        return 'server.cfg still sets sv_demoStream* (now passed as launch args)'
    cvars = demo_stream_launch_cvars(instance)
    if cvars.get('sv_demoStream') != '1':
        return 'sv_demoStream is not 1 in server.cfg'
    if cvars.get('sv_demoStreamHost') != '127.0.0.1':
        return 'sv_demoStreamHost is not 127.0.0.1 in server.cfg'
    if cvars.get('sv_demoStreamPort') != get_host_tunnel_port(instance.host_id):
        return "sv_demoStreamPort does not match the host tunnel's port"
    return None


@bp.route('/instances/<int:instance_id>', methods=['PUT'], endpoint='update_instance_stream')
@jwt_required()
def update_instance_stream(instance_id):
    """The Live Demo Stream panel's save. The form sends both fields every
    time; what happens depends on what changed against the current state:
    off -> on queues the enable (which sets the delay last), on -> off queues
    the disable, a delay change while streaming is one hub call. Saving a
    streaming instance whose wiring drifted (no token, server.cfg not what
    the enable writes) queues the enable again: a plain save repairs it."""
    instance, error = _instance_or_error(instance_id)
    if error:
        return error

    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({"error": {
            "message": "The request body must be a JSON object with enabled and delay_sec."
        }}), 400

    plan = _stream_plan(instance, body)
    if plan['error']:
        message, status = plan['error']
        return jsonify({"error": {"message": message}}), status
    if plan['action'] == 'enable':
        return _queue_instance_task(instance, 'enable_instance_demo_stream', 'enable',
                                    delay_sec=plan['delay'])
    if plan['action'] == 'disable':
        return _queue_instance_task(instance, 'disable_instance_demo_stream', 'disable')
    if plan['action'] == 'delay':
        return _set_delay(instance, plan['delay'])
    return jsonify({"message": "No changes."})


def _stream_plan(instance, body, force_enable=None):
    """What saving {enabled, delay_sec} for this instance has to do; shared by
    PUT instances/{id} and telemetry-relay's Stats Hub panel. A dict:
    `action` None (no change), 'enable', 'disable' or 'delay' (one hub call,
    no restart); `delay` the parsed delay (None: hub default); `error`
    (message, status) or None. `force_enable` (a reason) runs the enable of
    a streaming instance again, e.g. to follow a new telemetry server ID."""
    from .settings import is_instance_demo_stream_enabled

    def fail(message, status):
        return {'action': None, 'delay': None, 'error': (message, status)}

    try:
        delay = _parse_delay(body.get('delay_sec'))
    except (ValueError, OverflowError):
        return fail(DELAY_VALUE_MESSAGE, 400)
    if 'enabled' in body and not isinstance(body['enabled'], bool):
        return fail("enabled must be true or false.", 400)

    enabled = is_instance_demo_stream_enabled(instance.id)
    wanted = body.get('enabled', enabled)

    def plan(action):
        if action == 'enable':
            blocked = _enable_blocked_error(instance)
            if blocked:
                return fail(*blocked)
        return {'action': action, 'delay': delay, 'error': None}

    if not enabled and wanted:
        return plan('enable')
    if enabled and not wanted:
        return plan('disable')
    if not enabled:
        if delay is not None:
            return fail(NOT_STREAMING_MESSAGE, 409)
        from .instance_ops import DEMO_STREAM_CVARS, read_cfg_text
        from .settings import read_cvars_from_text
        if read_cvars_from_text(read_cfg_text(instance) or '', DEMO_STREAM_CVARS):
            # Off, but server.cfg still carries the cvars (the token among
            # them) from before 1.7.0: the disable moves them out of it.
            return plan('disable')
        return plan(None)

    # Streaming and staying on. Drifted wiring first (local state, then the
    # hub saying it has no route): the enable re-registers the route,
    # rewrites the cvars and restarts once, and takes the delay along as on
    # off -> on (setting an unchanged delay again is harmless).
    drift = force_enable or _wiring_drift(instance)
    state = None
    if not drift:
        state, drift = _hub_delay_state_or_lost_route(instance)
    if drift:
        current_app.logger.info(
            f'Addon demo-stream: re-enabling instance {instance.id} on save: {drift}')
        return plan('enable')

    # Then the delay, compared with what the hub reports, the way the GET
    # showed it. Blank with nothing to compare with is no change.
    if delay is None and (state is None or not state['override']):
        return plan(None)
    if delay is not None and state is not None and state['override'] \
            and abs(state['delay_sec'] - delay) <= DELAY_MATCH_TOLERANCE_SEC:
        return plan(None)
    return plan('delay')


@bp.route('/instances/<int:instance_id>/enable', methods=['POST', 'PUT'], endpoint='enable_instance_stream')
@jwt_required()
def enable_instance_stream(instance_id):
    """Kept for one release for anything that still calls it; the panel
    saves through PUT instances/{id} now."""
    instance, error = _instance_or_error(instance_id)
    if error:
        return error

    if not (request.get_json(silent=True) or {}).get('enabled', True):
        return jsonify({"error": {
            "message": "This route only switches the stream on; "
                       "save the instance's Stats Hub entry to switch it off."
        }}), 400

    blocked = _enable_blocked(instance)
    if blocked:
        return blocked
    return _queue_instance_task(instance, 'enable_instance_demo_stream', 'enable')


DELAY_MATCH_TOLERANCE_SEC = 0.001
DELAY_VALUE_MESSAGE = ("delay_sec must be a number of seconds from 0 to 300, "
                       "or blank for the hub default.")
NOT_STREAMING_MESSAGE = ("This instance is not streaming yet. Switch the stream on in its Stats "
                         "Hub menu entry first; the delay can be set once that has finished.")


def _delay_target(instance):
    """(server_id, None) when the hub can be asked about this instance's
    delay, else (None, (badge label, what the operator has to do first))."""
    from .settings import (
        get_instance_server_id, is_instance_demo_stream_enabled,
        is_stats_hub_configured_for_host,
    )

    if not is_stats_hub_configured_for_host(instance.host_id):
        return None, ('Stats-hub not configured',
                      "Set the stats-hub URL and ingest token in Settings first "
                      "(Stats Hub).")
    server_id = get_instance_server_id(instance.id)
    if server_id is None or not is_instance_demo_stream_enabled(instance.id):
        return None, ('Not streaming', NOT_STREAMING_MESSAGE)
    return server_id, None


def _seconds(value):
    from .stats_hub import format_seconds

    return format_seconds(value)


def _delay_data(state):
    return {
        'delay_sec': _seconds(state['delay_sec']) if state['override'] else '',
        'default_delay_sec': _seconds(state['default_delay_sec']),
        'effective_delay_sec': _seconds(state['delay_sec']),
        'override': state['override'],
    }


def _parse_delay(value):
    """None for blank (back to the hub default) or a float in range; raises
    ValueError/OverflowError for anything else."""
    from .stats_hub import DELAY_MAX_SEC, DELAY_MIN_SEC

    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ValueError(value)
    number = float(value)
    if not math.isfinite(number) or not DELAY_MIN_SEC <= number <= DELAY_MAX_SEC:
        raise ValueError(value)
    return number


def _delay_hub_error(instance_id, exc):
    current_app.logger.error(f'Addon demo-stream: delay call for instance {instance_id} failed: {exc}')
    return jsonify({"error": {"message": str(exc)}}), exc.status


@bp.route('/instances/<int:instance_id>/delay', methods=['GET'], endpoint='get_instance_delay')
@jwt_required()
def get_instance_delay(instance_id):
    """The stream delay stats-hub applies to this instance. It lives on the
    hub only; nothing about it is stored here."""
    from .stats_hub import HubDelayError, get_server_delay

    instance, error = _instance_or_error(instance_id)
    if error:
        return error
    server_id, _ = _delay_target(instance)
    if server_id is None:
        # Not an error: the form still renders, the badge says why it is empty.
        return jsonify({"data": {'delay_sec': '', 'default_delay_sec': '',
                                 'effective_delay_sec': '', 'override': False}})
    try:
        state = get_server_delay(instance.host_id, server_id)
    except HubDelayError as exc:
        return _delay_hub_error(instance.id, exc)
    return jsonify({"data": _delay_data(state)})


@bp.route('/instances/<int:instance_id>/delay/status', methods=['GET'],
          endpoint='get_instance_delay_status')
@jwt_required()
def get_instance_delay_status(instance_id):
    """Badge for the delay panel: the delay in effect and the hub default, or
    why there is none to show."""
    from .stats_hub import HubDelayError, get_server_delay

    instance, error = _instance_or_error(instance_id)
    if error:
        return error
    server_id, blocked = _delay_target(instance)
    if server_id is None:
        return jsonify({"data": {'ok': False, 'label': blocked[0]}})
    try:
        state = get_server_delay(instance.host_id, server_id)
    except HubDelayError as exc:
        return jsonify({"data": {'ok': False, 'label': exc.label}})
    effective = _seconds(state['delay_sec'])
    default = 'hub default' if not state['override'] \
        else f"hub default {_seconds(state['default_delay_sec'])} s"
    return jsonify({"data": {'ok': True, 'label': f'Delay {effective} s ({default})'}})


@bp.route('/instances/<int:instance_id>/delay', methods=['PUT'], endpoint='update_instance_delay')
@jwt_required()
def update_instance_delay(instance_id):
    """One call to stats-hub. No server.cfg change, no instance lock, no
    restart: the hub applies the delay to the running stream."""
    instance, error = _instance_or_error(instance_id)
    if error:
        return error

    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({"error": {
            "message": "The request body must be a JSON object with delay_sec."
        }}), 400
    try:
        delay = _parse_delay(body.get('delay_sec'))
    except (ValueError, OverflowError):
        return jsonify({"error": {"message": DELAY_VALUE_MESSAGE}}), 400

    return _set_delay(instance, delay)


def _set_delay(instance, delay):
    """One call to stats-hub that sets (or, for None, resets) the delay and
    checks the hub applied it. Returns the response."""
    body, status = _set_delay_result(instance, delay)
    return jsonify(body), status


def _set_delay_result(instance, delay):
    """_set_delay as (JSON body, HTTP status), for telemetry-relay's Stats
    Hub panel too."""
    from .stats_hub import HubDelayError, set_server_delay

    server_id, blocked = _delay_target(instance)
    if server_id is None:
        return {"error": {"message": blocked[1]}}, 409
    try:
        state = set_server_delay(instance.host_id, server_id, delay)
    except HubDelayError as exc:
        current_app.logger.error(
            f'Addon demo-stream: delay call for instance {instance.id} failed: {exc}')
        return {"error": {"message": str(exc)}}, exc.status

    # A 200 that does not show what was asked for is not a save: say so
    # rather than let the form report "Saved".
    applied = not state['override'] if delay is None else (
        state['override'] and abs(state['delay_sec'] - delay) <= DELAY_MATCH_TOLERANCE_SEC)
    if not applied:
        current_app.logger.error(
            f'Addon demo-stream: stats-hub answered 200 for instance {instance.id} but '
            f'reports delay {state["delay_sec"]} (override={state["override"]}), asked {delay}')
        return {"error": {
            "message": "stats-hub answered but did not apply the delay: it reports "
                       f"{_seconds(state['delay_sec'])} s"
                       f"{'' if state['override'] else ' (hub default)'}. "
                       "Check the stats-hub and try again."
        }}, 502

    effective = _seconds(state['delay_sec'])
    message = f"Stream delay set to {effective} s." if state['override'] \
        else f"Stream delay back on the hub default ({effective} s)."
    return {"data": _delay_data(state), "message": message}, 200


# Set by register(); the instance endpoints enqueue through
# this rather than through ui.tasks, which no longer knows demo-stream
# exists.
TASKS = {}


def prepare_new_instance(instance_id):
    """Switch the stream on for an instance that is about to get its first
    deploy, without an apply or restart. Not a hook of this addon: called by
    telemetry-relay's `instance.created` handler once it stored the
    instance's server ID (hooks run in addon-id order, this addon first, so
    a handler here would run before that ID exists). Looked up on this
    module by name; returns (ok, message)."""
    from .instance_ops import prepare_new_instance as prepare

    return prepare(instance_id)


# ---- Stats Hub UI (1.9.0) -----------------------------------------------
# Since 1.9.0 this addon has no menu entry or settings section of its own:
# telemetry-relay's "Stats Hub" entries show the stream next to telemetry
# and save both with one apply. A tier-1 panel only reaches its own addon's
# routes, so telemetry-relay calls the functions below in-process, found on
# this module through its addon context (the same way it calls
# prepare_new_instance). STATS_HUB_UI_API is what it checks for; raise it
# only for a change an older telemetry-relay must not call. Nothing here
# commits unless it says so, and none of it queues an apply or a restart.

STATS_HUB_UI_API = 1


def stats_hub_ui_settings():
    """Relay address and this addon's stats-hub URL. Never the token."""
    from .settings import (
        get_relay_host, get_relay_port, get_stats_hub_ingest_token, get_stats_hub_url,
    )

    return {'relay_host': get_relay_host() or '', 'relay_port': get_relay_port() or '',
            'stats_hub_url': get_stats_hub_url() or '',
            'has_ingest_token': bool(get_stats_hub_ingest_token())}


def stats_hub_ui_ingest_token_equals(token):
    """Whether this addon's global ingest token is `token` (compared here, so
    the value never leaves the addon)."""
    from .settings import get_stats_hub_ingest_token

    return (get_stats_hub_ingest_token() or '') == (token or '').strip()


def stats_hub_ui_validate_settings(relay_host, relay_port):
    """An error message for the relay fields, else None."""
    if not isinstance(relay_host, str) or not isinstance(relay_port, str):
        return "relay_host and relay_port must be strings."
    if relay_port and not relay_port.strip().isdigit():
        return "relay_port must be a number."
    return None


def stats_hub_ui_save_settings(relay_host, relay_port, url, token):
    """Stores the relay and the stats-hub target; a blank token keeps the
    stored one. Validate first. Does not commit."""
    from .settings import (
        set_relay_host, set_relay_port, set_stats_hub_ingest_token, set_stats_hub_url,
    )

    set_relay_host(relay_host)
    set_relay_port(relay_port)
    set_stats_hub_url(url)
    if token.strip():
        set_stats_hub_ingest_token(token)


def stats_hub_ui_host_hub(host_id):
    """This addon's per-host stats-hub URL override ('' for none)."""
    from .stats_hub import get_host_stats_hub_url

    return get_host_stats_hub_url(host_id) or ''


def stats_hub_ui_save_host_hub(host_id, url, token):
    """This addon's per-host stats-hub override; `token` None keeps the
    stored one, '' clears it. Does not commit."""
    from .stats_hub import set_host_stats_hub_ingest_token, set_host_stats_hub_url

    set_host_stats_hub_url(host_id, url)
    if token is not None:
        set_host_stats_hub_ingest_token(host_id, token)


def stats_hub_ui_host(host_id):
    """The tunnel fields of the host panel."""
    from .settings import get_host_relay_override, get_host_tunnel_port, is_host_tunnel_enabled

    relay_host, relay_port = get_host_relay_override(host_id)
    return {'tunnel_enabled': is_host_tunnel_enabled(host_id),
            'local_port': get_host_tunnel_port(host_id),
            'relay_host': relay_host or '', 'relay_port': relay_port or ''}


def stats_hub_ui_tunnel_enabled(host_id):
    from .settings import is_host_tunnel_enabled

    return is_host_tunnel_enabled(host_id)


def stats_hub_ui_host_status(host):
    """(ok, label) of the tunnel; one stats-hub call."""
    return _host_status(host)


def stats_hub_ui_host_plan(host, data):
    """_tunnel_plan for {enabled, local_port, relay_host, relay_port}."""
    return _tunnel_plan(host, data)


def stats_hub_ui_configure_host(host_id, wanted, port, cert_pem):
    """The tunnel's host task body, run inside telemetry-relay's host task.
    Returns ok."""
    from .tunnel_ops import configure_host_demo_stream_tunnel_logic

    return configure_host_demo_stream_tunnel_logic(host_id, wanted, port, cert_pem)


def stats_hub_ui_is_streaming(instance_id):
    from .settings import is_instance_demo_stream_enabled

    return is_instance_demo_stream_enabled(instance_id)


def stats_hub_ui_instance(instance):
    """The stream fields of the instance panel (one hub call when streaming)."""
    from .settings import is_instance_demo_stream_enabled

    enabled = is_instance_demo_stream_enabled(instance.id)
    state = _hub_delay_state(instance) if enabled else None
    return {'stream': enabled, 'delay_sec': _delay_field(state)}


def stats_hub_ui_instance_status(instance):
    """(ok, label) of the stream."""
    return _instance_status(instance)


def stats_hub_ui_instance_plan(instance, enabled, delay_sec, force_enable=None):
    """_stream_plan for the instance panel's stream fields; `enabled` None
    keeps the stream as it is."""
    body = {'delay_sec': delay_sec}
    if enabled is not None:
        body['enabled'] = enabled
    return _stream_plan(instance, body, force_enable=force_enable)


def stats_hub_ui_set_delay(instance, delay):
    """(JSON body, status) of a delay-only save: one hub call, no restart."""
    return _set_delay_result(instance, delay)


def stats_hub_ui_enable(instance_id, previous_status=None, delay_sec=None):
    """The stream's enable without its own apply/restart (the caller queues
    one for everything it changed). Returns (ok, message)."""
    from .instance_ops import enable_instance_demo_stream_logic

    return enable_instance_demo_stream_logic(instance_id, previous_status=previous_status,
                                             delay_sec=delay_sec, queue_apply=False)


def stats_hub_ui_disable(instance_id, previous_status=None):
    """The stream's disable without its own apply/restart. (ok, message)."""
    from .instance_ops import disable_instance_demo_stream_logic

    return disable_instance_demo_stream_logic(instance_id, previous_status=previous_status,
                                              queue_apply=False)


def register(ctx):
    ctx.blueprint(bp)

    @ctx.task(timeout=300, lock_scope='instance')
    def enable_instance_demo_stream_task(instance_id, previous_status=None, delay_sec=None):
        """RQ task entry point for wiring an instance's sv_demoStream* cvars
        at the central demo-stream relay and registering its route with
        stats-hub; sets the stream delay on the hub last when given."""
        from .instance_ops import enable_instance_demo_stream_logic

        return enable_instance_demo_stream_logic(instance_id, previous_status=previous_status,
                                                 delay_sec=delay_sec)

    TASKS['enable_instance_demo_stream'] = enable_instance_demo_stream_task

    @ctx.task(timeout=300, lock_scope='instance')
    def disable_instance_demo_stream_task(instance_id, previous_status=None):
        """RQ task entry point for switching an instance's stream off."""
        from .instance_ops import disable_instance_demo_stream_logic

        return disable_instance_demo_stream_logic(instance_id, previous_status=previous_status)

    TASKS['disable_instance_demo_stream'] = disable_instance_demo_stream_task

    @ctx.task(timeout=300, lock_scope='host')
    def configure_host_tunnel_task(host_id, enabled, port, cert_pem):
        """RQ task entry point for installing/removing a host's stunnel client."""
        from .tunnel_ops import configure_host_demo_stream_tunnel_logic

        return configure_host_demo_stream_tunnel_logic(host_id, enabled, port, cert_pem)

    TASKS['configure_host_tunnel'] = configure_host_tunnel_task

    @ctx.on('instance.launch_args')
    def demo_stream_launch_args(instance_id):
        """sv_demoStream* as `+set` from this addon's own state, so the token
        lives in no file a preset could carry or overwrite. Core only asks
        when the addon is on for the instance (see
        instance_ops.launch_args_active); a server.cfg line for the same cvar
        still wins, it is exec'd later."""
        from ui.database import get_instance

        from .instance_ops import demo_stream_launch_cvars

        instance = get_instance(instance_id)
        if instance is None or not instance.host:
            return []
        return [f'+set {name} "{value}"'
                for name, value in demo_stream_launch_cvars(instance).items()]

    @ctx.on('host.delete')
    def forget_host(host_id):
        """Drop the host's tunnel AppSetting keys."""
        from .settings import set_host_relay_override, set_host_tunnel_enabled, set_host_tunnel_port
        set_host_tunnel_enabled(host_id, False)
        set_host_tunnel_port(host_id, '')
        set_host_relay_override(host_id, '', '')

    @ctx.on('instance.delete')
    def forget_instance(instance_id):
        """Drop this addon's AppSetting keys -- core's own AddonState
        cleanup does not know about them."""
        from .settings import (
            set_instance_demo_stream_enabled, set_instance_demo_stream_token,
            set_instance_server_id, set_instance_stream_port,
        )
        set_instance_demo_stream_enabled(instance_id, False)
        set_instance_stream_port(instance_id, None)
        set_instance_demo_stream_token(instance_id, None)
        set_instance_server_id(instance_id, None)
