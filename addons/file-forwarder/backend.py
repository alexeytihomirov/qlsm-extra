"""Deploys forwarder.sh (assets/) to game hosts and runs it on demand.

- host.payload_sync (after host setup / Update Plugins) and the "Apply to
  host" task run playbooks/sync_file_forwarder.yml for a host whose
  `enabled` host setting is on (the addon must also be on globally).
- "Sync now" / "Sync now and delete delivered" run playbooks/run_forwarder.yml
  with ff_mode=run|purge and return forwarder.sh's last-run line.
- The status route runs playbooks/status_file_forwarder.yml.

The install SFTP key (keypair.py) reaches the sync playbook only as a 0600
temp file, `ff_private_key_file`, removed after the run: qlsm's ansible
runner logs the whole extravars JSON, so the key itself is never an extravar.

Contract with the playbooks (Task 3 writes them):
- sync_file_forwarder.yml gets config_render.playbook_vars() minus
  ff_private_key, plus ff_private_key_file (a path on the qlsm side, for
  `copy: src=`); every task that touches the key needs `no_log: true`.
- run_forwarder.yml gets {ff_mode: run|purge} and shows forwarder.sh's
  output in its stdout; the last `time=... exit=N` line is the summary.
- status_file_forwarder.yml prints the lines FF_VERSION=<VERSION file>,
  FF_TIMER=<systemctl is-active of the timer> and FF_LAST_RUN=<last-run
  line> (e.g. as a debug msg list). Only those three values, matched against
  strict formats, ever reach a response.

Every route needs a logged-in qlsm user (@jwt_required, like the packer's
internal routes; qlsm has no separate admin role).
"""
import os
import re
import shutil
import tempfile
import uuid

from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import jwt_required

from . import config_render, keypair

bp = Blueprint('file_forwarder_addon', __name__)

SYNC_PLAYBOOK = 'sync_file_forwarder.yml'
RUN_PLAYBOOK = 'run_forwarder.yml'
STATUS_PLAYBOOK = 'status_file_forwarder.yml'

APPLY_TIMEOUT_SECONDS = 900
# A run uploads at most MAX_RAW_MB_PER_RUN of raw demos plus the small files.
SYNC_TIMEOUT_SECONDS = 3600
_LOCK_MARGIN_SECONDS = 60

# Set by register().
CTX = None
TASKS = {}

_STATUS_RE = re.compile(r'FF_(VERSION|TIMER|LAST_RUN)=([^"\r\n\\]*)')
_VERSION_RE = re.compile(r'^[A-Za-z0-9.+-]{1,32}$')
_SUMMARY_RE = re.compile(
    r'time=[0-9TZ:.-]{1,32} mode=(?:run|purge) uploaded=[0-9]{1,9} failed=[0-9]{1,9} '
    r'deleted=[0-9]{1,9} kept_unconfirmed=[0-9]{1,9} exit=[0-9]{1,3}')
_LOG_TAIL = 2000


def _error(message, status):
    return jsonify({'error': {'message': message}}), status


def _get_host(host_id):
    from ui.database import get_host
    return get_host(host_id)


def _redact(text, settings_values=None):
    """Drop any line of the private key from text bound for a log."""
    text = (text or '')[-_LOG_TAIL:]
    values = settings_values if settings_values is not None else CTX.settings.get('global', 0)
    private = values.get(keypair.PRIVATE_KEY_SETTING) or ''
    for line in private.splitlines():
        line = line.strip()
        if len(line) >= 16:
            text = text.replace(line, '[redacted]')
    return text.replace('PRIVATE KEY', '[redacted]')


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
    """Install / update the forwarder on a host. Returns {success, message}."""
    host = _get_host(host_id)
    if not host:
        return {'success': False, 'message': 'Host not found.'}
    try:
        keypair.ensure_keypair(CTX.settings)
        values = CTX.settings.get('global', 0)
        variables = config_render.playbook_vars(values)
    except ValueError as e:
        CTX.logger.error('file-forwarder: not applied to host %s: %s', host.name, e)
        return {'success': False, 'message': str(e)}

    private = variables.pop('ff_private_key')
    key_dir = tempfile.mkdtemp(prefix='ff-key-')
    try:
        key_path = os.path.join(key_dir, 'id_ed25519_qldemos')
        fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w', encoding='ascii', newline='\n') as f:
            f.write(private)
        variables['ff_private_key_file'] = key_path
        success, _stdout, stderr = _run(host, SYNC_PLAYBOOK, variables)
    finally:
        shutil.rmtree(key_dir, ignore_errors=True)

    if not success:
        CTX.logger.error('file-forwarder: sync playbook failed for host %s: %s',
                         host.name, _redact(stderr, values))
        return {'success': False, 'message': 'The sync playbook failed; see the qlsm log.'}
    CTX.logger.info('file-forwarder: applied to host %s', host.name)
    return {'success': True, 'message': f'File forwarder applied to {host.name}.'}


def summary_line(stdout):
    found = _SUMMARY_RE.findall(stdout or '')
    if found:
        return found[-1]
    if 'locked: another run holds' in (stdout or ''):
        return 'locked: another forwarder run is in progress on the host'
    return None


def sync_host(host_id, purge=False):
    """Run forwarder.sh now (purge: also delete everything confirmed delivered).

    Returns its summary line, prefixed with "failed: " when the run failed.
    """
    host = _get_host(host_id)
    if not host:
        return 'failed: host not found'
    success, stdout, stderr = _run(host, RUN_PLAYBOOK, {'ff_mode': 'purge' if purge else 'run'})
    summary = summary_line(stdout)
    if success:
        return summary or 'ok (no summary line in the playbook output)'
    CTX.logger.error('file-forwarder: %s failed on host %s: %s',
                     'purge' if purge else 'sync', host.name, _redact(stderr))
    return f'failed: {summary or "see the qlsm log"}'


def parse_status(stdout, expected_version):
    found = {}
    for key, value in _STATUS_RE.findall(stdout or ''):
        found[key] = value.strip()
    version = found.get('VERSION')
    version = version if version and _VERSION_RE.match(version) else None
    timer = found.get('TIMER')
    last_run = found.get('LAST_RUN')
    last_run = last_run if last_run and _SUMMARY_RE.fullmatch(last_run) else None
    return {
        'version': version,
        'timer_active': timer == 'active',
        'last_run': last_run,
        'up_to_date': version is not None and version == expected_version,
    }


# ---- routes -------------------------------------------------------------------

@bp.route('/public-key', methods=['GET'], endpoint='public_key')
@jwt_required()
def public_key():
    try:
        public = keypair.ensure_keypair(CTX.settings)
    except ValueError as e:
        return _error(str(e), 500)
    return jsonify({'data': {
        'public_key': public,
        'keys': [{'name': 'Install key, add once to qldemos-in on the VPS', 'public_key': public}],
    }})


def _editable(values):
    return {key: str(values.get(key, config_render.DEFAULTS[key])) for key in config_render.EDITABLE_KEYS}


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
    unknown = sorted(k for k in body if k not in config_render.EDITABLE_KEYS)
    if unknown:
        return _error(f'Not editable here: {", ".join(unknown)}.', 400)
    merged = dict(_editable(CTX.settings.get('global', 0)), **body)
    try:
        checked = config_render.validate_settings(merged)
    except ValueError as e:
        return _error(str(e), 400)
    stored = {
        'vps_host': checked['vps_host'],
        'retention_days': str(checked['retention_days']),
        'max_raw_mb_per_run': str(checked['max_raw_mb_per_run']),
        'interval_minutes': str(checked['interval_minutes']),
        'patterns': config_render.format_patterns(checked['patterns']),
    }
    try:
        values = CTX.settings.set('global', 0, stored)
    except ValueError as e:
        db.session.rollback()
        return _error(str(e), 400)
    return jsonify({'data': _editable(values),
                    'message': 'Saved. Use Apply to host to roll it out now.'})


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
        CTX.logger.warning('file-forwarder: status playbook failed for host %s: %s',
                           host.name, _redact(stderr))
        error = 'Could not read the status from the host; see the qlsm log.'
    if status['up_to_date']:
        state = 'up to date'
    elif status['version']:
        state = f'outdated, addon is {expected}'
    else:
        state = 'unknown' if error else 'not installed'
    row = {
        'host': host.name,
        'version': status['version'] or '-',
        'state': state,
        'timer': 'active' if status['timer_active'] else ('unknown' if error else 'inactive'),
        'last_run': status['last_run'] or (error or '-'),
    }
    return jsonify({'data': dict(status, expected_version=expected, error=error, rows=[row])})


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
        current_app.logger.error('Addon file-forwarder: failed to queue %s for host %s: %s',
                                 task_name, host_id, e, exc_info=True)
        return _error('Failed to queue the task.', 500)
    return None


@bp.route('/hosts/<int:host_id>/apply', methods=['POST'], endpoint='apply_host_route')
@jwt_required()
def apply_host_route(host_id):
    host = _get_host(host_id)
    if not host:
        return _error('Host not found.', 404)
    if not host_enabled(host_id):
        return _error('The file forwarder is off for this host (or for QLSM); turn it on first.', 409)
    error = _enqueue(host_id, 'apply_task', APPLY_TIMEOUT_SECONDS + _LOCK_MARGIN_SECONDS)
    if error:
        return error
    return jsonify({'data': {'queued': True}, 'message': f'Apply queued for {host.name}.'}), 202


def _sync_route(host_id, purge):
    host = _get_host(host_id)
    if not host:
        return _error('Host not found.', 404)
    error = _enqueue(host_id, 'sync_task', SYNC_TIMEOUT_SECONDS + _LOCK_MARGIN_SECONDS, purge=purge)
    if error:
        return error
    what = 'Sync and delete of delivered files' if purge else 'Sync'
    return jsonify({'data': {'queued': True}, 'message': f'{what} queued for {host.name}.'}), 202


@bp.route('/hosts/<int:host_id>/sync', methods=['POST'], endpoint='sync_host_route')
@jwt_required()
def sync_host_route(host_id):
    return _sync_route(host_id, purge=False)


@bp.route('/hosts/<int:host_id>/purge', methods=['POST'], endpoint='purge_host_route')
@jwt_required()
def purge_host_route(host_id):
    return _sync_route(host_id, purge=True)


def register(ctx):
    global CTX
    CTX = ctx
    ctx.blueprint(bp)

    @ctx.task(timeout=APPLY_TIMEOUT_SECONDS, lock_scope='host')
    def apply_task(host_id):
        return apply_host(host_id)

    @ctx.task(timeout=SYNC_TIMEOUT_SECONDS, lock_scope='host')
    def sync_task(host_id, purge=False):
        return sync_host(host_id, purge=purge)

    TASKS['apply_task'] = apply_task
    TASKS['sync_task'] = sync_task

    @ctx.on('host.payload_sync')
    def sync_file_forwarder(host_id):
        """Install / update the forwarder after host setup or Update Plugins.

        host.payload_sync is ungated in core, so the enable check is here.
        """
        if not host_enabled(host_id):
            return
        apply_host(host_id)
