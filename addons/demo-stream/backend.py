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
    if not isinstance(url, str) or not isinstance(token, str):
        return jsonify({"error": {"message": "url and ingest_token must be strings."}}), 400

    set_stats_hub_url(url)
    set_stats_hub_ingest_token(token)
    db.session.commit()
    return jsonify({"data": {'url': url.strip().rstrip('/'), 'ingest_token': token.strip()}})


def _host_or_404(host_id):
    from ui.database import get_host

    host = get_host(host_id)
    if not host:
        return None, (jsonify({"error": {"message": "Host not found"}}), 404)
    return host, None


@bp.route('/hosts/<int:host_id>', methods=['GET'], endpoint='get_host_tunnel')
@jwt_required()
def get_host_tunnel(host_id):
    from .settings import get_host_tunnel_port, is_host_tunnel_enabled

    _, error = _host_or_404(host_id)
    if error:
        return error
    return jsonify({"data": {
        'enabled': is_host_tunnel_enabled(host_id),
        'local_port': get_host_tunnel_port(host_id),
    }})


@bp.route('/hosts/<int:host_id>', methods=['PUT'], endpoint='update_host_tunnel')
@jwt_required()
def update_host_tunnel(host_id):
    """Stores the local port, then installs/removes the host's stunnel client.
    Enabled-and-wanted always re-queues (the playbook is idempotent), which is
    what lets a port edit reach a tunnel that is already running."""
    from ui import db
    from ui.database import update_host
    from ui.models import HostStatus
    from ui.task_lock import acquire_lock, release_lock
    from ui.task_logic.job_failure_handlers import host_job_failure_handler
    from ui.tasks import enqueue_task
    from .settings import (
        DEFAULT_TUNNEL_PORT, is_host_tunnel_enabled, is_relay_configured,
        set_host_tunnel_port,
    )
    from .tunnel_ops import TunnelCertError, fetch_hub_tls_cert

    host, error = _host_or_404(host_id)
    if error:
        return error

    data = request.get_json(silent=True) or {}
    port = data.get('local_port', '')
    # 1024 and up: the tunnel runs as user ql and cannot bind privileged ports.
    if not isinstance(port, str) or (
            port.strip() and not (port.strip().isascii() and port.strip().isdigit()
                                  and 1024 <= int(port.strip()) <= 65535)):
        return jsonify({"error": {"message": "local_port must be a port number (1024-65535)."}}), 400

    port = port.strip() or DEFAULT_TUNNEL_PORT
    wanted = bool(data.get('enabled', False))

    if not wanted and not is_host_tunnel_enabled(host_id):
        # Nothing is installed, so there is nothing to wait for: just remember
        # the port. Otherwise the port is stored only once the playbook succeeds.
        set_host_tunnel_port(host_id, port)
        db.session.commit()
        return jsonify({"data": {'enabled': False, 'local_port': port},
                        "message": "Tunnel settings saved."})

    cert_pem = ''
    if wanted:
        if not is_relay_configured():
            return jsonify({"error": {
                "message": "Set the demo-stream relay host and port in Settings first."
            }}), 409
        try:
            cert_pem = fetch_hub_tls_cert(host_id)
        except TunnelCertError as exc:
            return jsonify({"error": {"message": str(exc)}}), 409

    if host.status != HostStatus.ACTIVE:
        return jsonify({"error": {
            "message": f"Host must be ACTIVE to change the tunnel. Current state: {host.status.value}"
        }}), 400

    lock_token = str(uuid.uuid4())
    if not acquire_lock('host', host.id, lock_token, ttl=360):
        return jsonify({"error": {
            "message": f'Another operation is running on host "{host.name}". Please wait for it to complete.'
        }}), 409
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


@bp.route('/instances/<int:instance_id>', methods=['GET'], endpoint='get_instance_stream')
@jwt_required()
def get_instance_stream(instance_id):
    from .settings import is_instance_demo_stream_enabled

    instance, error = _instance_or_error(instance_id)
    if error:
        return error
    return jsonify({"data": {'enabled': is_instance_demo_stream_enabled(instance.id)}})


@bp.route('/instances/<int:instance_id>/status', methods=['GET'], endpoint='get_instance_stream_status')
@jwt_required()
def get_instance_stream_status(instance_id):
    """Badge for the panel: says why it cannot be switched on, before the
    operator tries and gets a task that fails somewhere they cannot see."""
    from .settings import (
        get_instance_demo_stream_token, is_host_tunnel_enabled,
        is_instance_demo_stream_enabled, is_relay_configured,
    )

    instance, error = _instance_or_error(instance_id)
    if error:
        return error

    if not is_relay_configured():
        return jsonify({"data": {'ok': False, 'label': 'Relay address not set'}})
    if not is_host_tunnel_enabled(instance.host_id):
        return jsonify({"data": {'ok': False, 'label': 'Tunnel not enabled on host'}})
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
    from .instance_ops import TUNNEL_REQUIRED_MESSAGE
    from .settings import is_host_tunnel_enabled, is_relay_configured
    from ui.models import InstanceStatus
    from ui.task_lock import acquire_lock, release_lock
    from ui.task_logic.job_failure_handlers import instance_job_failure_handler
    from ui.tasks import enqueue_task

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

    if not is_host_tunnel_enabled(instance.host_id):
        return jsonify({"error": {"message": TUNNEL_REQUIRED_MESSAGE}}), 400

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
        enqueue_task(TASKS['enable_instance_demo_stream'], instance.id,
                     lock_token=lock_token, on_failure=instance_job_failure_handler)
    except Exception as e:
        release_lock('instance', instance.id, lock_token)
        current_app.logger.error(f'Addon demo-stream: failed to queue instance {instance_id}: {e}',
                                 exc_info=True)
        return jsonify({"error": {"message": "Failed to queue demo-stream enable."}}), 500

    return jsonify({"message": f'Demo-stream enable queued for "{instance.name}".'}), 202


# Set by register(); the enable_instance_stream endpoint enqueues through
# this rather than through ui.tasks, which no longer knows demo-stream
# exists.
TASKS = {}


def register(ctx):
    ctx.blueprint(bp)

    @ctx.task(timeout=300, lock_scope='instance')
    def enable_instance_demo_stream_task(instance_id):
        """RQ task entry point for wiring an instance's sv_demoStream* cvars
        at the central demo-stream relay and registering its route with
        stats-hub."""
        from .instance_ops import enable_instance_demo_stream_logic

        return enable_instance_demo_stream_logic(instance_id)

    TASKS['enable_instance_demo_stream'] = enable_instance_demo_stream_task

    @ctx.task(timeout=300, lock_scope='host')
    def configure_host_tunnel_task(host_id, enabled, port, cert_pem):
        """RQ task entry point for installing/removing a host's stunnel client."""
        from .tunnel_ops import configure_host_demo_stream_tunnel_logic

        return configure_host_demo_stream_tunnel_logic(host_id, enabled, port, cert_pem)

    TASKS['configure_host_tunnel'] = configure_host_tunnel_task

    @ctx.on('host.delete')
    def forget_host(host_id):
        """Drop the host's tunnel AppSetting keys."""
        from .settings import set_host_tunnel_enabled, set_host_tunnel_port
        set_host_tunnel_enabled(host_id, False)
        set_host_tunnel_port(host_id, '')

    @ctx.on('instance.delete')
    def forget_instance(instance_id):
        """Drop this addon's AppSetting keys -- core's own AddonState
        cleanup does not know about them."""
        from .settings import (
            set_instance_demo_stream_enabled, set_instance_demo_stream_token,
            set_instance_server_id,
        )
        set_instance_demo_stream_enabled(instance_id, False)
        set_instance_demo_stream_token(instance_id, None)
        set_instance_server_id(instance_id, None)
