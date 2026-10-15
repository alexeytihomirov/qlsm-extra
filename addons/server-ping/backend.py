"""Deploys ql-ping-echo (assets/) to game hosts: the browser ping service of spec
2026-10-15 section 4.

- One DTLS key + certificate for all hosts, a `secret` global setting. POST
  generate-cert creates it once (409 when one exists); GET fingerprint gives the
  value for the ql-tournament env (PING_DTLS_FINGERPRINT).
- host.payload_sync (after host setup) and the Apply task run
  playbooks/sync_server_ping.yml for a host whose `enabled` host setting is on (the
  addon must also be on globally). Apply of a host switched off removes the service
  and its firewall chain.
- The status route runs playbooks/status_server_ping.yml.

Contract with the playbooks: sync gets sp_enabled (bool), sp_port (digits),
sp_cert_file (path of a 0600 temp file holding the PEM, deleted after the run;
'' when disabled) and sp_version (the manifest version, written to VERSION). The
PEM itself is never an extravar: core logs the whole ansible-playbook command
line, extravars included, at INFO. status prints SP_VERSION=, SP_SERVICE=, SP_FIREWALL= and
SP_FINGERPRINT=; only those values, matched against strict formats, reach a
response.

Every route needs a logged-in qlsm user (@jwt_required).
"""
import os
import re
import tempfile
import uuid

from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import jwt_required

from . import settings as sp_settings

bp = Blueprint('server_ping_addon', __name__)

SYNC_PLAYBOOK = 'sync_server_ping.yml'
STATUS_PLAYBOOK = 'status_server_ping.yml'

APPLY_TIMEOUT_SECONDS = 300
_LOCK_MARGIN_SECONDS = 60
_LOG_TAIL = 2000

# Set by register().
CTX = None
TASKS = {}

_STATUS_RE = re.compile(r'SP_(VERSION|SERVICE|FIREWALL|FINGERPRINT)=([^"\r\n\\]*)')
_VERSION_RE = re.compile(r'^[A-Za-z0-9.+-]{1,32}$')
_SERVICE_RE = re.compile(r'^[a-z-]{1,24}$')
_FINGERPRINT_RE = re.compile(r'([0-9A-F]{2}(?::[0-9A-F]{2}){31})')

NO_CERT = 'Generate the DTLS certificate first (Server Ping page).'


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


def _global():
    return CTX.settings.get('global', 0)


def _host_switch(host_id):
    return bool(CTX.settings.get('host', host_id).get('enabled'))


def host_enabled(host_id):
    """The addon is on globally and this host's `enabled` setting is on."""
    if not CTX.settings.is_enabled('global', 0):
        return False
    return _host_switch(host_id)


def _current_fingerprint():
    """(fingerprint, error): the stored certificate's fingerprint or why there is none."""
    try:
        return sp_settings.fingerprint(_global().get('dtls_cert')), None
    except ValueError as e:
        return None, str(e)


def deploy_variables(host_id):
    """(extravars without sp_cert_file, PEM or ''), or ValueError naming what is missing."""
    values = _global()
    port = sp_settings.validate_port(values.get('port'))
    enabled = _host_switch(host_id)
    pem = ''
    if enabled:
        pem = values.get('dtls_cert') or ''
        sp_settings.fingerprint(pem)   # refuses an empty or unusable PEM
    variables = {
        'sp_enabled': enabled,
        'sp_port': port,
        'sp_version': sp_settings.addon_version(),
    }
    return variables, pem


def _write_cert_file(pem):
    """The PEM in a private temp file (mkstemp: mode 0600) for the playbook's copy."""
    fd, path = tempfile.mkstemp(prefix='server-ping-', suffix='.pem')
    with os.fdopen(fd, 'w', encoding='ascii', newline='\n') as f:
        f.write(pem.strip() + '\n')
    return path


def apply_host(host_id):
    """Install / update ql-ping-echo on a host (or remove it when the host switch is
    off). Returns {success, message}."""
    host = _get_host(host_id)
    if not host:
        return {'success': False, 'message': 'Host not found.'}
    try:
        variables, pem = deploy_variables(host_id)
    except ValueError as e:
        CTX.logger.error('server-ping: not applied to host %s: %s', host.name, e)
        return {'success': False, 'message': str(e)}
    cert_file = _write_cert_file(pem) if pem else ''
    try:
        success, _stdout, stderr = _run(host, SYNC_PLAYBOOK, dict(variables, sp_cert_file=cert_file))
    finally:
        if cert_file:
            try:
                os.unlink(cert_file)
            except OSError:
                pass
    if not success:
        CTX.logger.error('server-ping: sync playbook failed for host %s: %s',
                         host.name, stderr[-_LOG_TAIL:])
        return {'success': False, 'message': 'The sync playbook failed; see the qlsm log.'}
    CTX.logger.info('server-ping: applied to host %s (enabled=%s)', host.name,
                    variables['sp_enabled'])
    return {'success': True, 'message': f'Server ping applied to {host.name}.'}


def parse_status(stdout, expected_version, expected_fingerprint):
    found = {}
    for key, value in _STATUS_RE.findall(stdout or ''):
        found[key] = value.strip()
    version = found.get('VERSION')
    service = found.get('SERVICE')
    firewall = found.get('FIREWALL')
    fp_match = _FINGERPRINT_RE.search(found.get('FINGERPRINT') or '')
    return {
        'version': version if version and _VERSION_RE.match(version) else None,
        'service': service if service and _SERVICE_RE.match(service) else None,
        'firewall': {'yes': True, 'no': False}.get(firewall),
        'fingerprint': fp_match.group(1) if fp_match else None,
        'expected_version': expected_version,
        'expected_fingerprint': expected_fingerprint,
    }


# ---- routes -------------------------------------------------------------------

@bp.route('/settings', methods=['GET'], endpoint='get_settings')
@jwt_required()
def get_settings():
    return jsonify({'data': {'port': str(_global().get('port') or sp_settings.DEFAULT_PORT)}})


@bp.route('/settings', methods=['PUT'], endpoint='put_settings')
@jwt_required()
def put_settings():
    from ui import db

    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return _error('Expected a JSON object.', 400)
    unknown = sorted(k for k in body if k != 'port')
    if unknown:
        return _error(f'Not editable here: {", ".join(unknown)}.', 400)
    try:
        port = sp_settings.validate_port(body.get('port'))
        CTX.settings.set('global', 0, {'port': port})
    except ValueError as e:
        db.session.rollback()
        return _error(str(e), 400)
    return jsonify({'data': {'port': port},
                    'message': 'Saved. The port reaches a host with Apply.'})


def _fingerprint_payload():
    fp, error = _current_fingerprint()
    # ok / label feed the status badge of the declarative settings form.
    return {
        'fingerprint': fp,
        'error': None if fp else error,
        'ok': bool(fp),
        'label': f'DTLS fingerprint {fp}' if fp else (error or 'No DTLS certificate yet.'),
    }


@bp.route('/fingerprint', methods=['GET'], endpoint='get_fingerprint')
@jwt_required()
def get_fingerprint():
    return jsonify({'data': _fingerprint_payload()})


@bp.route('/generate-cert', methods=['POST'], endpoint='generate_cert')
@jwt_required()
def generate_cert():
    from ui import db

    existing = _global().get('dtls_cert') or ''
    if existing.strip():
        return _error('A DTLS certificate already exists; it is shared by every host and '
                      'its fingerprint is configured in ql-tournament, so it is not replaced.', 409)
    pem = sp_settings.generate_cert_pem()
    try:
        CTX.settings.set('global', 0, {'dtls_cert': pem})
    except ValueError as e:
        db.session.rollback()
        return _error(str(e), 400)
    CTX.logger.info('server-ping: DTLS certificate generated')
    return jsonify({'data': _fingerprint_payload(),
                    'message': 'Certificate generated. Put the fingerprint into the '
                               'ql-tournament env and Apply to every host.'})


@bp.route('/hosts', methods=['GET'], endpoint='list_hosts')
@jwt_required()
def list_hosts():
    from ui.models import Host

    hosts = [{'id': h.id, 'name': h.name, 'enabled': _host_switch(h.id)}
             for h in Host.query.order_by(Host.id).all()]
    return jsonify({'data': {'hosts': hosts}})


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
    expected_fp, _ = _current_fingerprint()
    success, stdout, stderr = _run(host, STATUS_PLAYBOOK)
    status = parse_status(stdout, CTX.manifest.get('version') or '', expected_fp)
    error = None
    if not success:
        CTX.logger.warning('server-ping: status playbook failed for host %s: %s',
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
        current_app.logger.error('Addon server-ping: failed to queue %s for host %s: %s',
                                 task_name, host_id, e, exc_info=True)
        return _error('Failed to queue the task.', 500)
    return None


@bp.route('/hosts/<int:host_id>/apply', methods=['POST'], endpoint='apply_host_route')
@jwt_required()
def apply_host_route(host_id):
    host = _get_host(host_id)
    if not host:
        return _error('Host not found.', 404)
    try:
        deploy_variables(host_id)
    except ValueError as e:
        return _error(NO_CERT if not (_global().get('dtls_cert') or '').strip() else str(e), 409)
    error = _enqueue(host_id, 'apply_task', APPLY_TIMEOUT_SECONDS + _LOCK_MARGIN_SECONDS)
    if error:
        return error
    message = f'Apply queued for {host.name}.'
    # The message is also inside `data`: ctx.api returns only that key.
    return jsonify({'data': {'queued': True, 'message': message}, 'message': message}), 202


def register(ctx):
    global CTX
    CTX = ctx
    ctx.blueprint(bp)

    @ctx.task(timeout=APPLY_TIMEOUT_SECONDS, lock_scope='host')
    def apply_task(host_id):
        return apply_host(host_id)

    TASKS['apply_task'] = apply_task

    @ctx.on('host.payload_sync')
    def sync_server_ping(host_id):
        """Install / update ql-ping-echo after host setup (a full setup restores
        iptables.rules and drops the QLPING-INPUT hook; this puts it back).

        host.payload_sync is ungated in core, so the enable check is here.
        """
        if not host_enabled(host_id):
            return
        apply_host(host_id)
