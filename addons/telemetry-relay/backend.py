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
import time
import uuid

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
        get_host_stats_hub_ingest_token, get_host_stats_hub_url, is_relay_enabled,
    )

    _, error = _host_or_404(host_id)
    if error:
        return error

    return jsonify({"data": {
        'enabled': is_relay_enabled(host_id),
        'url_override': get_host_stats_hub_url(host_id) or '',
        'ingest_token_override': get_host_stats_hub_ingest_token(host_id) or '',
    }})


@bp.route('/hosts/<int:host_id>/status', methods=['GET'], endpoint='get_host_relay_status')
@jwt_required()
def get_host_relay_status(host_id):
    """Live sidecar probe, shaped for the panel's status badge.

    One SSH round trip, so this is a separate endpoint from the form load --
    the panel fetches it once per open rather than on every keystroke.
    """
    from .relay_ops import get_relay_status_logic

    host, error = _host_or_404(host_id)
    if error:
        return error

    status = get_relay_status_logic(host_id)
    if status is None:
        return jsonify({"error": {"message": "Host not found"}}), 404

    if not status.get('enabled'):
        label = 'Sidecar disabled'
    elif status.get('reachable'):
        routed = len(status.get('routed_instances') or [])
        label = f'Reachable, {routed} instance(s) routed'
    else:
        label = status.get('error') or 'Unreachable'
    label = f'{label}; {_access_line(host)}'

    return jsonify({"data": {
        'ok': bool(status.get('enabled') and status.get('reachable')),
        'label': label,
        'routed_instances': status.get('routed_instances') or [],
    }})


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
        is_relay_enabled, set_host_stats_hub_ingest_token, set_host_stats_hub_url,
    )

    host, error = _host_or_404(host_id)
    if error:
        return error

    data = request.get_json(silent=True) or {}
    url = data.get('url_override', '')
    token = data.get('ingest_token_override', '')
    if not isinstance(url, str) or not isinstance(token, str):
        return jsonify({"error": {"message": "url_override and ingest_token_override must be strings."}}), 400
    wanted = bool(data.get('enabled', False))

    set_host_stats_hub_url(host_id, url)
    set_host_stats_hub_ingest_token(host_id, token)
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
    from .settings import get_stats_hub_ingest_token, get_stats_hub_url

    return jsonify({"data": {
        'url': get_stats_hub_url() or '',
        'ingest_token': get_stats_hub_ingest_token() or '',
    }})


@bp.route('/stats-hub', methods=['PUT'], endpoint='update_stats_hub')
@jwt_required()
def update_stats_hub():
    """Cluster-wide stats-hub target. Same AppSetting keys the built-in
    Settings page writes, so the two cannot disagree while both exist."""
    from ui import db
    from .settings import set_stats_hub_ingest_token, set_stats_hub_url

    data = request.get_json(silent=True) or {}
    url = data.get('url', '')
    token = data.get('ingest_token', '')
    if not isinstance(url, str) or not isinstance(token, str):
        return jsonify({"error": {"message": "url and ingest_token must be strings."}}), 400

    set_stats_hub_url(url)
    set_stats_hub_ingest_token(token)
    db.session.commit()
    return jsonify({"data": {'url': url.strip().rstrip('/'), 'ingest_token': token.strip()}})


def _instance_or_error(instance_id):
    from ui.database import get_instance

    instance = get_instance(instance_id)
    if not instance:
        return None, (jsonify({"error": {"message": "Instance not found."}}), 404)
    if not instance.host:
        return None, (jsonify({"error": {"message": "Instance has no associated host."}}), 400)
    return instance, None


def _cfg_enabled(instance):
    """The switch: qlx_statsHubUnifiedEnabled in qlsm's copy of server.cfg."""
    from .instance_ops import read_instance_telemetry_cvars

    return read_instance_telemetry_cvars(instance).get('qlx_statsHubUnifiedEnabled') == '1'


@bp.route('/instances/<int:instance_id>', methods=['GET'], endpoint='get_instance_telemetry')
@jwt_required()
def get_instance_telemetry(instance_id):
    instance, error = _instance_or_error(instance_id)
    if error:
        return error
    return jsonify({"data": {"enabled": _cfg_enabled(instance)}})


@bp.route('/instances/<int:instance_id>/status', methods=['GET'], endpoint='get_instance_telemetry_status')
@jwt_required()
def get_instance_telemetry_status(instance_id):
    """Badge for the panel and the menu entry. Local reads only."""
    from .settings import get_instance_server_id, is_relay_enabled

    instance, error = _instance_or_error(instance_id)
    if error:
        return error
    if not is_relay_enabled(instance.host_id):
        return jsonify({"data": {'ok': False, 'label': 'Relay off on host'}})
    if not _cfg_enabled(instance):
        return jsonify({"data": {'ok': False, 'label': 'Off'}})
    server_id = get_instance_server_id(instance.id)
    if not server_id:
        return jsonify({"data": {'ok': False, 'label': 'On, no server ID yet; save to repair'}})
    return jsonify({"data": {'ok': True, 'label': f'Server ID {server_id}, relay on'}})


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


def _queue_instance_task(instance, task_key, what):
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
                     previous_status=previous_status,
                     lock_token=lock_token, on_failure=instance_job_failure_handler)
    except Exception as e:
        release_lock('instance', instance.id, lock_token)
        current_app.logger.error(f'Addon telemetry-relay: failed to queue instance {instance.id}: {e}',
                                 exc_info=True)
        return jsonify({"error": {"message": f"Failed to queue telemetry {what}."}}), 500

    return jsonify({"message": f'Telemetry {what} queued for "{instance.name}".'}), 202


def _wiring_drift(instance):
    """Why an enabled instance needs the enable run again, or None when the
    stored server ID and server.cfg agree with what the enable writes."""
    from .instance_ops import read_instance_telemetry_cvars
    from .settings import get_instance_server_id

    server_id = get_instance_server_id(instance.id)
    if not server_id:
        return 'no stored server ID'
    cvars = read_instance_telemetry_cvars(instance)
    if cvars.get('qlx_statsHubUnifiedEnabled') != '1':
        return 'qlx_statsHubUnifiedEnabled is not 1 in server.cfg'
    if cvars.get('qlx_statsHubServerId') != str(server_id):
        return 'qlx_statsHubServerId does not match the stored server ID'
    return None


@bp.route('/instances/<int:instance_id>', methods=['PUT'], endpoint='update_instance_telemetry')
@jwt_required()
def update_instance_telemetry(instance_id):
    """The Telemetry panel's save: off -> on queues the enable, on -> off the
    disable. Saving an enabled instance whose wiring drifted queues the
    enable again, so a plain save repairs it (one restart)."""
    instance, error = _instance_or_error(instance_id)
    if error:
        return error

    body = request.get_json(silent=True)
    if not isinstance(body, dict) or not isinstance(body.get('enabled'), bool):
        return jsonify({"error": {"message": "enabled must be true or false."}}), 400
    wanted = body['enabled']
    enabled = _cfg_enabled(instance)

    if wanted and not enabled:
        return _enable_blocked(instance) or _queue_instance_task(
            instance, 'enable_instance_telemetry', 'enable')
    if enabled and not wanted:
        return _queue_instance_task(instance, 'disable_instance_telemetry', 'disable')
    if wanted:
        drift = _wiring_drift(instance)
        if drift:
            current_app.logger.info(
                f'Addon telemetry-relay: re-enabling instance {instance.id} on save: {drift}')
            return _enable_blocked(instance) or _queue_instance_task(
                instance, 'enable_instance_telemetry', 'enable')
    return jsonify({"message": "No changes."})


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


# Set by register(); the endpoints enqueue through these rather than through
# ui.tasks, which no longer knows telemetry exists.
TASKS = {}


def register(ctx):
    ctx.blueprint(bp)

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
    def enable_instance_telemetry_task(instance_id, previous_status=None):
        """Reserve a stats-hub server_id and wire the instance's cvars."""
        from .instance_ops import enable_instance_telemetry_logic

        return enable_instance_telemetry_logic(instance_id, previous_status=previous_status)

    @ctx.task(timeout=300, lock_scope='instance')
    def disable_instance_telemetry_task(instance_id, previous_status=None):
        """Switch telemetry off; the reserved server_id is kept."""
        from .instance_ops import disable_instance_telemetry_logic

        return disable_instance_telemetry_logic(instance_id, previous_status=previous_status)

    TASKS['configure_host_relay'] = configure_host_relay
    TASKS['enable_instance_telemetry'] = enable_instance_telemetry_task
    TASKS['disable_instance_telemetry'] = disable_instance_telemetry_task

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
            set_host_stats_hub_ingest_token, set_host_stats_hub_url, set_relay_enabled,
        )
        set_relay_enabled(host_id, False)
        set_host_stats_hub_url(host_id, '')
        set_host_stats_hub_ingest_token(host_id, '')

    @ctx.on('instance.delete')
    def forget_instance(instance_id):
        from .settings import set_instance_server_id, set_reserved_server_id
        set_instance_server_id(instance_id, None)
        set_reserved_server_id(instance_id, None)
