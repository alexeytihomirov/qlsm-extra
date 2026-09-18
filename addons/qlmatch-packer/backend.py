"""Deploys the external qlmatch-packer + Node runtime to managed hosts, and
extends the demo-management addon with the .qlmatch pack format.

Split out of demo-management so that addon can stay agnostic of any
particular demo format beyond the raw .dm_91 minqlxtended's native capture
writes -- this addon owns everything qlmatch-specific: the Node payload
itself, the format's filename recognition (contributed to demo-management's
demo_management.file_kinds hook), and the external Bearer-token match API
(moved here from demo-management's /instances/<id>/matches* -- see git
history for the old URL if an external caller still points at it).

No settings/UI of its own: qlx_qlmatchNameTemplate / qlx_qlmatchRcloneTargets
live on the demo_native_autorecord plugin's own manifest (Plugins tab), not
here -- this addon only deploys the binary those cvars point at.
"""
import io
import uuid

from flask import Blueprint, current_app, jsonify, request, send_file
from flask_jwt_extended import jwt_required

from ui import limiter

bp = Blueprint('qlmatch_packer_addon', __name__)

_QLMATCH_SUFFIX = '.qlmatch'
_REPLAY_SUFFIX = '.replay.json.gz'  # keep in sync with qlmatch_listing.SIDECAR_EXT

# Long enough to cover one rebuild_ops.REMOTE_NODE_TIMEOUT_SECONDS run plus
# the SSH round trip, with margin -- see telemetry-relay's own lock ttl
# comment for why this must not be shorter than the task it protects.
_REBUILD_LOCK_TTL_SECONDS = 1900
_MAX_BATCH_REBUILD = 20
# A batch runs its items sequentially under one lock (see rebuild_tasks.py),
# so the lock must outlive the whole batch, not just one item.
_BATCH_REBUILD_LOCK_TTL_SECONDS = _REBUILD_LOCK_TTL_SECONDS * _MAX_BATCH_REBUILD

# Set by register(); the endpoints enqueue through these.
TASKS = {}


def _require_instance_external(instance_id):
    from ui.database import get_instance

    instance = get_instance(instance_id)
    if not instance:
        return None, (jsonify({'error': {'message': 'Instance not found.'}}), 404)
    if not instance.host:
        return None, (jsonify({'error': {'message': 'Instance has no associated host.'}}), 400)
    return instance, None


def _external_download_demo(instance_id, filename, expected_suffix):
    from .qlmatch_listing import fetch_qlmatch_files

    if not filename.endswith(expected_suffix):
        return jsonify({'error': {'message': f"filename must end with '{expected_suffix}'."}}), 400

    success, files, missing, error_msg = fetch_qlmatch_files(instance_id, [filename])
    if not success:
        return jsonify({'error': {'message': error_msg}}), 500
    if filename in missing or filename not in files:
        return jsonify({'error': {'message': 'File not found on the remote host.'}}), 404

    return send_file(
        io.BytesIO(files[filename]),
        as_attachment=True,
        download_name=filename,
        mimetype='application/octet-stream',
    )


@bp.route('/instances/<int:instance_id>/matches', methods=['GET'], endpoint='external_list_instance_matches')
@limiter.limit("200 per minute")
def external_list_instance_matches(instance_id):
    """List recorded .qlmatch packs for an instance, flagging replay availability.

    Secured via Bearer token (API key), not JWT cookies - for external
    services, unlike a JWT-protected addon panel would be.
    """
    from ui.routes.settings_routes import require_api_key

    ok, err_response = require_api_key()
    if not ok:
        return err_response

    instance, err_response = _require_instance_external(instance_id)
    if err_response:
        return err_response

    from .qlmatch_listing import list_instance_qlmatches

    success, matches, error_msg = list_instance_qlmatches(instance_id)
    if not success:
        return jsonify({'error': {'message': error_msg}}), 500

    return jsonify({'data': {'matches': matches, 'instance_name': instance.name}})


@bp.route('/instances/<int:instance_id>/matches/download', methods=['GET'], endpoint='external_download_instance_match')
@limiter.limit("200 per minute")
def external_download_instance_match(instance_id):
    """Download a single .qlmatch file by name for an instance. Bearer token."""
    from ui.routes.settings_routes import require_api_key

    ok, err_response = require_api_key()
    if not ok:
        return err_response

    _, err_response = _require_instance_external(instance_id)
    if err_response:
        return err_response

    filename = request.args.get('filename', '')
    return _external_download_demo(instance_id, filename, _QLMATCH_SUFFIX)


@bp.route('/instances/<int:instance_id>/matches/replay', methods=['GET'], endpoint='external_download_instance_match_replay')
@limiter.limit("200 per minute")
def external_download_instance_match_replay(instance_id):
    """Download the .replay.json.gz sidecar for a recorded match, by name. Bearer token."""
    from ui.routes.settings_routes import require_api_key

    ok, err_response = require_api_key()
    if not ok:
        return err_response

    _, err_response = _require_instance_external(instance_id)
    if err_response:
        return err_response

    filename = request.args.get('filename', '')
    return _external_download_demo(instance_id, filename, _REPLAY_SUFFIX)


def _require_instance_internal(instance_id):
    from ui.database import get_instance

    instance = get_instance(instance_id)
    if not instance:
        return None, (jsonify({'error': {'message': 'Instance not found.'}}), 404)
    return instance, None


def _enqueue_rebuild(instance_id, task_name, *task_args, lock_ttl=_REBUILD_LOCK_TTL_SECONDS):
    """Acquire the instance lock and enqueue one of TASKS[task_name], or
    return a ready-made error response if that is not currently possible.

    Mirrors telemetry-relay's update_host_relay/enable_instance_telemetry:
    acquire synchronously so a busy instance gets an immediate 409 instead of
    a queued job that fails later, release on any enqueue failure.
    """
    from ui.task_lock import acquire_lock, release_lock
    from ui.tasks import enqueue_task

    lock_token = str(uuid.uuid4())
    if not acquire_lock('instance', instance_id, lock_token, ttl=lock_ttl):
        return None, (jsonify({'error': {
            'message': 'Another operation is already running on this instance. Please wait.',
        }}), 409)
    try:
        enqueue_task(TASKS[task_name], instance_id, *task_args, lock_token=lock_token)
    except Exception as e:
        release_lock('instance', instance_id, lock_token)
        current_app.logger.error(
            'Addon qlmatch-packer: failed to queue %s for instance %s: %s', task_name, instance_id, e,
            exc_info=True,
        )
        return None, (jsonify({'error': {'message': 'Failed to queue rebuild.'}}), 500)
    return lock_token, None


@bp.route(
    '/instances/<int:instance_id>/matches/<path:filename>/rebuild-sidecar',
    methods=['POST'], endpoint='rebuild_match_sidecar',
)
@jwt_required()
def rebuild_match_sidecar(instance_id, filename):
    instance, error = _require_instance_internal(instance_id)
    if error:
        return error
    _lock_token, error = _enqueue_rebuild(instance_id, 'rebuild_sidecar', filename)
    if error:
        return error
    return jsonify({'data': {'queued': True}, 'message': f'Sidecar rebuild queued for "{filename}".'}), 202


@bp.route(
    '/instances/<int:instance_id>/matches/<path:filename>/rebuild-full',
    methods=['POST'], endpoint='rebuild_match_full',
)
@jwt_required()
def rebuild_match_full(instance_id, filename):
    instance, error = _require_instance_internal(instance_id)
    if error:
        return error
    _lock_token, error = _enqueue_rebuild(instance_id, 'rebuild_full', filename)
    if error:
        return error
    return jsonify({'data': {'queued': True}, 'message': f'Full rebuild queued for "{filename}".'}), 202


def _batch_filenames_from_request():
    data = request.get_json(silent=True) or {}
    filenames = data.get('filenames')
    if not isinstance(filenames, list) or not filenames or not all(isinstance(f, str) for f in filenames):
        return None, (jsonify({'error': {'message': 'filenames must be a non-empty list of strings.'}}), 400)
    if len(filenames) > _MAX_BATCH_REBUILD:
        return None, (jsonify({'error': {
            'message': f'Cannot rebuild more than {_MAX_BATCH_REBUILD} matches at once.',
        }}), 400)
    return filenames, None


@bp.route('/instances/<int:instance_id>/matches/rebuild-sidecar-batch', methods=['POST'], endpoint='rebuild_batch_sidecar')
@jwt_required()
def rebuild_batch_sidecar(instance_id):
    instance, error = _require_instance_internal(instance_id)
    if error:
        return error
    filenames, error = _batch_filenames_from_request()
    if error:
        return error
    _lock_token, error = _enqueue_rebuild(
        instance_id, 'rebuild_batch', 'sidecar', filenames, lock_ttl=_BATCH_REBUILD_LOCK_TTL_SECONDS,
    )
    if error:
        return error
    return jsonify({'data': {'queued': True}, 'message': f'Sidecar rebuild queued for {len(filenames)} match(es).'}), 202


@bp.route('/instances/<int:instance_id>/matches/rebuild-full-batch', methods=['POST'], endpoint='rebuild_batch_full')
@jwt_required()
def rebuild_batch_full(instance_id):
    instance, error = _require_instance_internal(instance_id)
    if error:
        return error
    filenames, error = _batch_filenames_from_request()
    if error:
        return error
    _lock_token, error = _enqueue_rebuild(
        instance_id, 'rebuild_batch', 'full', filenames, lock_ttl=_BATCH_REBUILD_LOCK_TTL_SECONDS,
    )
    if error:
        return error
    return jsonify({'data': {'queued': True}, 'message': f'Full rebuild queued for {len(filenames)} match(es).'}), 202


def register(ctx):
    ctx.blueprint(bp)

    from .rebuild_ops import REMOTE_NODE_TIMEOUT_SECONDS

    @ctx.task(timeout=REMOTE_NODE_TIMEOUT_SECONDS, lock_scope='instance')
    def rebuild_sidecar(instance_id, filename):
        from .rebuild_tasks import rebuild_sidecar_task_logic
        return rebuild_sidecar_task_logic(instance_id, filename)

    @ctx.task(timeout=REMOTE_NODE_TIMEOUT_SECONDS, lock_scope='instance')
    def rebuild_full(instance_id, filename):
        from .rebuild_tasks import rebuild_full_task_logic
        return rebuild_full_task_logic(instance_id, filename)

    @ctx.task(timeout=REMOTE_NODE_TIMEOUT_SECONDS * _MAX_BATCH_REBUILD, lock_scope='instance')
    def rebuild_batch(instance_id, kind, filenames):
        from .rebuild_tasks import rebuild_batch_task_logic
        return rebuild_batch_task_logic(instance_id, kind, filenames)

    TASKS['rebuild_sidecar'] = rebuild_sidecar
    TASKS['rebuild_full'] = rebuild_full
    TASKS['rebuild_batch'] = rebuild_batch

    @ctx.on('demo_management.match_groups')
    def contribute_match_groups(instance_id, demos):
        from .match_groups import build_match_groups
        return build_match_groups(instance_id, demos)

    @ctx.on('host.payload_sync')
    def sync_qlmatch_packer(host_id):
        """Deploy the external qlmatch-packer (assets/) + its Node.js runtime
        to a host after a successful setup / plugin-update run.

        demo_native_autorecord.py launches this as a separate process to
        build the .qlmatch package for every finished native-demo match; see
        playbooks/sync_qlmatch_packer.yml for the deploy itself.
        """
        from ui.database import get_host

        host = get_host(host_id)
        if not host:
            return
        success, _stdout, stderr = ctx.run_playbook(host, 'sync_qlmatch_packer.yml')
        if not success:
            ctx.logger.error('qlmatch-packer sync failed for host %s: %s', host.name, stderr)

    @ctx.on('demo_management.file_kinds')
    def contribute_file_kinds():
        """Tell demo-management to also recognise/list/download the file
        types this addon's packer produces, alongside the raw .dm_91 it
        knows about by default. Deliberately excludes .packer.log -- that
        file is still written on the host, it's just never surfaced in the
        Demos widget. The replay sidecar is gated by this addon's own
        settings (gear icon on the Addons page) -- turning it off just makes
        demo-management stop recognising it, the packer keeps writing it on
        the host regardless."""
        from .qlmatch_listing import FILE_KIND_EXTENSIONS

        values = ctx.settings.get('global', 0)
        gates = {'replay.json.gz': 'show_replay_json'}
        return [ext for ext in FILE_KIND_EXTENSIONS if values.get(gates.get(ext, ''), True)]
