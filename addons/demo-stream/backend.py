"""Live demo stream, as an addon.

Unlike the telemetry-relay and demo-management ports, this one **adds** a UI
rather than reproducing one: the built-in feature has two instance endpoints
and two settings endpoints and no frontend whatsoever -- nothing in
frontend-react references it. So there is no parity risk here, and a
declarative panel is strictly more than what exists today.

Same migration rule as the other two: this delegates to
`ui.demo_stream_settings` and `ui.task_logic.demo_stream_instance` instead of
copying them, so the addon and the built-in endpoints cannot drift while both
exist. The files move into this directory when core's copies are deleted.
"""
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


@bp.route('/relay', methods=['GET'], endpoint='get_relay')
@jwt_required()
def get_relay():
    from ui.demo_stream_settings import get_relay_host, get_relay_port

    return jsonify({"data": {'host': get_relay_host() or '', 'port': get_relay_port() or ''}})


@bp.route('/relay', methods=['PUT'], endpoint='update_relay')
@jwt_required()
def update_relay():
    """Cluster-wide relay address, stored under the same AppSetting keys the
    built-in Settings endpoint uses -- one store, so the two cannot disagree
    while both code paths exist."""
    from ui import db
    from ui.demo_stream_settings import set_relay_host, set_relay_port

    data = request.get_json(silent=True) or {}
    host = data.get('host', '')
    port = data.get('port', '')
    if not isinstance(host, str) or not isinstance(port, str):
        return jsonify({"error": {"message": "host and port must be strings."}}), 400
    if port and not port.strip().isdigit():
        return jsonify({"error": {"message": "port must be a number."}}), 400

    set_relay_host(host)
    set_relay_port(port)
    db.session.commit()
    return jsonify({"data": {'host': host.strip(), 'port': port.strip()}})


@bp.route('/stats-hub', methods=['GET'], endpoint='get_stats_hub')
@jwt_required()
def get_stats_hub():
    """This addon's own stats-hub target - independent of telemetry-relay's,
    see ui/stats_hub.py's module docstring for why they are not shared."""
    from ui.stats_hub import get_stats_hub_ingest_token, get_stats_hub_url

    return jsonify({"data": {
        'url': get_stats_hub_url('demo_stream') or '',
        'ingest_token': get_stats_hub_ingest_token('demo_stream') or '',
    }})


@bp.route('/stats-hub', methods=['PUT'], endpoint='update_stats_hub')
@jwt_required()
def update_stats_hub():
    from ui import db
    from ui.stats_hub import set_stats_hub_ingest_token, set_stats_hub_url

    data = request.get_json(silent=True) or {}
    url = data.get('url', '')
    token = data.get('ingest_token', '')
    if not isinstance(url, str) or not isinstance(token, str):
        return jsonify({"error": {"message": "url and ingest_token must be strings."}}), 400

    set_stats_hub_url('demo_stream', url)
    set_stats_hub_ingest_token('demo_stream', token)
    db.session.commit()
    return jsonify({"data": {'url': url.strip().rstrip('/'), 'ingest_token': token.strip()}})


@bp.route('/instances/<int:instance_id>', methods=['GET'], endpoint='get_instance_stream')
@jwt_required()
def get_instance_stream(instance_id):
    from ui.demo_stream_settings import is_instance_demo_stream_enabled

    instance, error = _instance_or_error(instance_id)
    if error:
        return error
    return jsonify({"data": {'enabled': is_instance_demo_stream_enabled(instance.id)}})


@bp.route('/instances/<int:instance_id>/status', methods=['GET'], endpoint='get_instance_stream_status')
@jwt_required()
def get_instance_stream_status(instance_id):
    """Badge for the panel: says why it cannot be switched on, before the
    operator tries and gets a task that fails somewhere they cannot see."""
    from ui.demo_stream_settings import (
        get_instance_demo_stream_token, is_instance_demo_stream_enabled, is_relay_configured,
    )

    instance, error = _instance_or_error(instance_id)
    if error:
        return error

    if not is_relay_configured():
        return jsonify({"data": {'ok': False, 'label': 'Relay address not set'}})
    if not is_instance_demo_stream_enabled(instance.id):
        return jsonify({"data": {'ok': False, 'label': 'Not streaming'}})
    has_token = bool(get_instance_demo_stream_token(instance.id))
    return jsonify({"data": {
        'ok': has_token,
        'label': 'Streaming' if has_token else 'Enabled, no route registered yet',
    }})


@bp.route('/instances/<int:instance_id>/enable', methods=['POST', 'PUT'], endpoint='enable_instance_stream')
@jwt_required()
def enable_instance_stream(instance_id):
    from ui.database import get_instance, update_instance
    from ui.demo_stream_settings import is_relay_configured
    from ui.models import InstanceStatus
    from ui.task_lock import acquire_lock, release_lock
    from ui.task_logic.job_failure_handlers import instance_job_failure_handler
    from ui.tasks import enable_instance_demo_stream_task, enqueue_task

    instance, error = _instance_or_error(instance_id)
    if error:
        return error

    if not (request.get_json(silent=True) or {}).get('enabled', True):
        # The built-in feature has no disable path -- it only ever wires the
        # cvars in. Saying so beats a toggle that silently does nothing.
        return jsonify({"error": {
            "message": "Turning the stream back off is not supported yet; "
                       "remove the sv_demoStream* lines from server.cfg instead."
        }}), 400

    if not is_relay_configured():
        return jsonify({"error": {
            "message": "Set the demo-stream relay host and port in Settings first."
        }}), 409

    busy = [InstanceStatus.DEPLOYING, InstanceStatus.CONFIGURING, InstanceStatus.RESTARTING,
            InstanceStatus.DELETING, InstanceStatus.STOPPING, InstanceStatus.STARTING]
    if instance.status in busy:
        return jsonify({"error": {
            "message": f'Instance "{instance.name}" is busy ({instance.status.value}). Try again shortly.'
        }}), 409

    lock_token = str(uuid.uuid4())
    if not acquire_lock('instance', instance.id, lock_token, ttl=180):
        return jsonify({"error": {
            "message": f'Another operation is running on instance "{instance.name}".'
        }}), 409
    try:
        update_instance(instance.id, status=InstanceStatus.CONFIGURING)
        enqueue_task(enable_instance_demo_stream_task, instance.id,
                     lock_token=lock_token, on_failure=instance_job_failure_handler)
    except Exception as e:
        release_lock('instance', instance.id, lock_token)
        current_app.logger.error(f'Addon demo-stream: failed to queue instance {instance_id}: {e}',
                                 exc_info=True)
        return jsonify({"error": {"message": "Failed to queue demo-stream enable."}}), 500

    return jsonify({"message": f'Demo-stream enable queued for "{instance.name}".'}), 202


def register(ctx):
    ctx.blueprint(bp)

    @ctx.on('instance.delete')
    def forget_instance(instance_id):
        """Drop the legacy AppSetting keys the shared logic still reads --
        core's own AddonState cleanup does not know about them."""
        from ui.demo_stream_settings import (
            set_instance_demo_stream_enabled, set_instance_demo_stream_token,
        )
        from ui.stats_hub import set_instance_server_id
        set_instance_demo_stream_enabled(instance_id, False)
        set_instance_demo_stream_token(instance_id, None)
        set_instance_server_id('demo_stream', instance_id, None)
