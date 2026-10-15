"""Deploys the host-metrics collector (assets/) to game hosts.

- host.payload_sync (after host setup) and the "Apply to host" task run
  playbooks/sync_host_metrics.yml for a host whose `enabled` host setting is
  on (the addon must also be on globally). A host whose switch is off is not
  touched here; turn the switch off and Apply to host stops its service.
  Update Plugins does not fire host.payload_sync: use Apply to host after an
  addon update or a settings change.
- The status route runs playbooks/status_host_metrics.yml.

Contract with the playbooks: sync gets hm_enabled (bool), hm_version (the
manifest version, written to VERSION) and hm_config_json (settings.
collector_config as JSON text). status prints HM_VERSION=, HM_SERVICE= and
HM_DB_BYTES=; only those values, matched against strict formats, reach a
response.

Every route needs a logged-in qlsm user (@jwt_required).
"""
import json
import re
import uuid

from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import jwt_required

from . import settings as hm_settings

bp = Blueprint('host_metrics_addon', __name__)

SYNC_PLAYBOOK = 'sync_host_metrics.yml'
STATUS_PLAYBOOK = 'status_host_metrics.yml'

APPLY_TIMEOUT_SECONDS = 300
_LOCK_MARGIN_SECONDS = 60

# Set by register().
CTX = None
TASKS = {}

_STATUS_RE = re.compile(r'HM_(VERSION|SERVICE|DB_BYTES)=([^"\r\n\\]*)')
_VERSION_RE = re.compile(r'^[A-Za-z0-9.+-]{1,32}$')
_SERVICE_RE = re.compile(r'^[a-z-]{1,24}$')
_BYTES_RE = re.compile(r'^[0-9]{1,15}$')
_LOG_TAIL = 2000


def _error(message, status):
    return jsonify({'error': {'message': message}}), status


def _get_host(host_id):
    from ui.database import get_host
    return get_host(host_id)


def _run(host, name, extravars=None):
    """ctx.run_playbook normalized to (success, stdout, stderr).

    Core's runner returns a 2-tuple (None, message) when the host lacks SSH
    details instead of its usual 3-tuple.
    """
    result = CTX.run_playbook(host, name, extravars) if extravars else CTX.run_playbook(host, name)
    if len(result) == 2:
        return False, '', result[1] or ''
    success, stdout, stderr = result
    return bool(success), stdout or '', stderr or ''


def host_enabled(host_id):
    """The addon is on globally and this host's `enabled` setting is on."""
    settings = CTX.settings
    if not settings.is_enabled('global', 0):
        return False
    return bool(settings.get('host', host_id).get('enabled'))


def apply_host(host_id):
    """Install / update the collector on a host (or stop it when the host switch
    is off). Returns {success, message}."""
    host = _get_host(host_id)
    if not host:
        return {'success': False, 'message': 'Host not found.'}
    try:
        config = hm_settings.collector_config(CTX.settings.get('global', 0))
    except ValueError as e:
        CTX.logger.error('host-metrics: not applied to host %s: %s', host.name, e)
        return {'success': False, 'message': str(e)}
    enabled = bool(CTX.settings.get('host', host_id).get('enabled'))
    variables = {
        'hm_enabled': enabled,
        'hm_version': config['version'],
        'hm_config_json': json.dumps(config, sort_keys=True),
    }
    success, _stdout, stderr = _run(host, SYNC_PLAYBOOK, variables)
    if not success:
        CTX.logger.error('host-metrics: sync playbook failed for host %s: %s',
                         host.name, stderr[-_LOG_TAIL:])
        return {'success': False, 'message': 'The sync playbook failed; see the qlsm log.'}
    CTX.logger.info('host-metrics: applied to host %s (enabled=%s)', host.name, enabled)
    return {'success': True, 'message': f'Host metrics applied to {host.name}.'}


def parse_status(stdout, expected_version):
    found = {}
    for key, value in _STATUS_RE.findall(stdout or ''):
        found[key] = value.strip()
    version = found.get('VERSION')
    service = found.get('SERVICE')
    db_bytes = found.get('DB_BYTES')
    return {
        'version': version if version and _VERSION_RE.match(version) else None,
        'service': service if service and _SERVICE_RE.match(service) else None,
        'db_bytes': int(db_bytes) if db_bytes and _BYTES_RE.match(db_bytes) else None,
        'expected_version': expected_version,
    }


# ---- routes -------------------------------------------------------------------

def _editable(values):
    return {key: str(values.get(key, hm_settings.DEFAULTS[key])) for key in hm_settings.EDITABLE_KEYS}


@bp.route('/settings', methods=['GET'], endpoint='get_settings')
@jwt_required()
def get_settings():
    return jsonify({'data': _editable(CTX.settings.get('global', 0))})


@bp.route('/settings', methods=['PUT'], endpoint='put_settings')
@jwt_required()
def put_settings():
    from ui import db

    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return _error('Expected a JSON object.', 400)
    unknown = sorted(k for k in body if k not in hm_settings.EDITABLE_KEYS)
    if unknown:
        return _error(f'Not editable here: {", ".join(unknown)}.', 400)
    merged = dict(_editable(CTX.settings.get('global', 0)), **body)
    try:
        checked = hm_settings.validate_settings(merged)
    except ValueError as e:
        return _error(str(e), 400)
    try:
        values = CTX.settings.set('global', 0, {k: str(v) for k, v in checked.items()})
    except ValueError as e:
        db.session.rollback()
        return _error(str(e), 400)
    return jsonify({'data': _editable(values),
                    'message': 'Saved. Thresholds reach a host with Apply to host.'})


@bp.route('/hosts/<int:host_id>', methods=['GET'], endpoint='get_host_switch')
@jwt_required()
def get_host_switch(host_id):
    if not _get_host(host_id):
        return _error('Host not found.', 404)
    return jsonify({'data': {'enabled': bool(CTX.settings.get('host', host_id).get('enabled'))}})


@bp.route('/hosts/<int:host_id>', methods=['PUT'], endpoint='put_host_switch')
@jwt_required()
def put_host_switch(host_id):
    if not _get_host(host_id):
        return _error('Host not found.', 404)
    body = request.get_json(silent=True) or {}
    enabled = body.get('enabled')
    if not isinstance(enabled, bool):
        return _error('enabled must be true or false.', 400)
    CTX.settings.set('host', host_id, {'enabled': enabled})
    return jsonify({'data': {'enabled': enabled}})


@bp.route('/hosts/<int:host_id>/status', methods=['GET'], endpoint='host_status')
@jwt_required()
def host_status(host_id):
    host = _get_host(host_id)
    if not host:
        return _error('Host not found.', 404)
    expected = CTX.manifest.get('version') or ''
    success, stdout, stderr = _run(host, STATUS_PLAYBOOK)
    status = parse_status(stdout, expected)
    error = None
    if not success:
        CTX.logger.warning('host-metrics: status playbook failed for host %s: %s',
                           host.name, stderr[-_LOG_TAIL:])
        error = 'Could not read the status from the host; see the qlsm log.'
    return jsonify({'data': dict(status, error=error)})


def _enqueue(host_id, task_name, ttl, **task_kwargs):
    from ui.task_lock import acquire_lock, release_lock
    from ui.tasks import enqueue_task

    token = str(uuid.uuid4())
    if not acquire_lock('host', host_id, token, ttl=ttl):
        return _error('Another operation is already running on this host. Please wait.', 409)
    try:
        enqueue_task(TASKS[task_name], host_id, lock_token=token, **task_kwargs)
    except Exception as e:
        release_lock('host', host_id, token)
        current_app.logger.error('Addon host-metrics: failed to queue %s for host %s: %s',
                                 task_name, host_id, e, exc_info=True)
        return _error('Failed to queue the task.', 500)
    return None


def _queued(message):
    # The message is also inside `data`: the host dialog gets only that key
    # from ctx.api.
    return jsonify({'data': {'queued': True, 'message': message}, 'message': message}), 202


@bp.route('/hosts/<int:host_id>/apply', methods=['POST'], endpoint='apply_host_route')
@jwt_required()
def apply_host_route(host_id):
    host = _get_host(host_id)
    if not host:
        return _error('Host not found.', 404)
    error = _enqueue(host_id, 'apply_task', APPLY_TIMEOUT_SECONDS + _LOCK_MARGIN_SECONDS)
    if error:
        return error
    return _queued(f'Apply queued for {host.name}.')


def register(ctx):
    global CTX
    CTX = ctx
    ctx.blueprint(bp)

    @ctx.task(timeout=APPLY_TIMEOUT_SECONDS, lock_scope='host')
    def apply_task(host_id):
        return apply_host(host_id)

    TASKS['apply_task'] = apply_task

    @ctx.on('host.payload_sync')
    def sync_host_metrics(host_id):
        """Install / update the collector after host setup.

        host.payload_sync is ungated in core, so the enable check is here.
        """
        if not host_enabled(host_id):
            return
        apply_host(host_id)
