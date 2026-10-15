"""Deploys the host-metrics collector (assets/) to game hosts.

- host.payload_sync (after host setup) and the "Apply to host" task run
  playbooks/sync_host_metrics.yml for a host whose `enabled` host setting is
  on (the addon must also be on globally). A host whose switch is off is not
  touched here; turn the switch off and Apply to host stops its service.
  Update Plugins does not fire host.payload_sync: use Apply to host after an
  addon update or a settings change.
- The status route runs playbooks/status_host_metrics.yml.
- On a qlsm core with poller.tick and ctx.notify, on_tick puts host problems under
  the notification bell (notifier.py); an older core gets neither and loses nothing
  else.

Contract with the playbooks: sync gets hm_enabled (bool), hm_version (the
manifest version, written to VERSION) and hm_config_json (settings.
collector_config as JSON text). status prints HM_VERSION=, HM_SERVICE= and
HM_DB_BYTES=; only those values, matched against strict formats, reach a
response.

Every route needs a logged-in qlsm user (@jwt_required).
"""
import json
import re
import statistics
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, wait
from types import SimpleNamespace

from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import jwt_required

from . import notifier as hm_notifier
from . import settings as hm_settings
from . import ssh as hm_ssh
from . import verdict as hm_verdict

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
    out = {key: str(values.get(key, hm_settings.DEFAULTS[key])) for key in hm_settings.FIELDS}
    try:
        enabled, severity = hm_settings.notify_settings(values)
    except ValueError:
        enabled, severity = (hm_settings.NOTIFY_DEFAULTS['notify_enabled'],
                             hm_settings.NOTIFY_DEFAULTS['notify_min_severity'])
    out.update(notify_enabled=enabled, notify_min_severity=severity)
    return out


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
        values = CTX.settings.set('global', 0, {k: v if isinstance(v, bool) else str(v)
                                                for k, v in checked.items()})
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


# ---- read routes (hm_query.py over SSH) -----------------------------------------

HOSTS_CACHE_KEY = 'addon:host-metrics:hosts'
HOSTS_CACHE_TTL = 30
FETCH_WORKERS = 8
QUERY_TIMEOUT_SECONDS = 5.0     # snapshot, all hosts in parallel for the list
SERIES_TIMEOUT_SECONDS = 20.0   # series / events of one host (30 days of minutes)
STALE_AFTER_SECONDS = 120       # collector ticks every 10 s
RANGES = ('1h', '6h', '24h', '7d', '30d')


def _redis():
    return current_app.extensions.get('redis')


def _cache_get(key):
    client = _redis()
    if client is None:
        return None
    try:
        raw = client.get(key)
        return json.loads(raw) if raw else None
    except Exception:
        return None


def _cache_set(key, payload, ttl):
    client = _redis()
    if client is None:
        return
    try:
        client.setex(key, ttl, json.dumps(payload))
    except Exception:
        pass


def _is_num(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def data_age(snapshot):
    """Seconds since the collector's newest sample: `data_age_s`, or now - host.ts from an
    older hm_query; None when the snapshot has no host row."""
    age = snapshot.get('data_age_s')
    if _is_num(age):
        return age
    host = snapshot.get('host')
    now = snapshot.get('now')
    if isinstance(host, dict) and _is_num(host.get('ts')) and _is_num(now):
        return now - host['ts']
    return None


def is_no_sudo(rc, stderr):
    """sudo -n refused (no passwordless sudo): `sudo:` + a password/terminal message on stderr.
    The command's `|| exit 127` turns sudo's rc 1 into 127, so both rcs count."""
    text = stderr or ''
    return (rc in (1, hm_ssh.MISSING_RC) and 'sudo:' in text
            and ('password is required' in text or 'terminal is required' in text))


def no_sudo_error(conn):
    return 'SSH user %s has no passwordless sudo' % conn.ssh_user


def classify(rc, parsed, stderr, expected_version):
    """(state, version, snapshot) of one host's `snapshot` answer. `stale`: the collector
    stopped writing (its last data is kept and shown, but gets no slot count)."""
    if is_no_sudo(rc, stderr):
        return 'no_sudo', None, None
    if rc == hm_ssh.MISSING_RC or 'No such file' in (stderr or ''):
        return 'not_installed', None, None
    version = parsed.get('version') if parsed else None
    if rc == 3:
        return 'no_data', version, None
    if rc != 0 or parsed is None or parsed.get('error'):
        return 'unreachable', version, None
    age = data_age(parsed)
    if age is not None and age > STALE_AFTER_SECONDS:
        return 'stale', version, parsed
    state = 'ok' if version == expected_version else 'outdated'
    return state, version, parsed


def stale_verdict(snapshot):
    age = data_age(snapshot) or 0
    return {'status': 'unknown', 'slots': None,
            'reason': 'collector data is %d min old' % (age // 60),
            'ref_load': None, 'ref_source': None}


def _fetch_snapshot(conn, expected_version):
    """Runs in a worker thread: plain data only, no app context, no database."""
    if getattr(conn, 'error', None):
        return {'state': 'unreachable', 'version': None, 'snapshot': None, 'error': conn.error}
    try:
        rc, parsed, stderr = hm_ssh.exec_json(conn, ['snapshot'], timeout=QUERY_TIMEOUT_SECONDS)
    except Exception:
        return {'state': 'unreachable', 'version': None, 'snapshot': None}
    state, version, snapshot = classify(rc, parsed, stderr, expected_version)
    result = {'state': state, 'version': version, 'snapshot': snapshot}
    if state == 'no_sudo':
        result['error'] = no_sudo_error(conn)
    return result


def _fleet_busy_median(rows):
    values = []
    for row in rows:
        for inst in ((row['snapshot'] or {}).get('insts') or []):
            value = inst.get('busy_p95') if isinstance(inst, dict) else None
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                values.append(float(value))
    return statistics.median(values) if values else None


CONNECTION_ERROR = 'The SSH target of this host could not be resolved.'


def _safe_connection(host):
    """A connection, or a placeholder carrying `error` when the target cannot be built
    (one misconfigured host must not fail the whole list)."""
    try:
        return hm_ssh.connection(host)
    except Exception as e:
        CTX.logger.warning('host-metrics: no ssh connection for host %s: %s', host.name, e)
        return SimpleNamespace(id=host.id, name=host.name, error=CONNECTION_ERROR)


def build_hosts(connections, values, expected_version):
    if connections:
        with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as pool:
            fetched = list(pool.map(lambda c: _fetch_snapshot(c, expected_version), connections))
    else:
        fetched = []
    rows = [dict({'error': None}, **f, id=c.id, name=c.name) for c, f in zip(connections, fetched)]
    median = _fleet_busy_median(rows)
    try:
        knobs = hm_settings.verdict_settings(values)
    except ValueError:
        knobs = hm_settings.verdict_settings({})
    for row in rows:
        row['verdict'] = None
        if row['state'] == 'stale':
            row['verdict'] = stale_verdict(row['snapshot'])
        elif row['snapshot'] is not None:
            try:
                row['verdict'] = hm_verdict.verdict(row['snapshot'], knobs, median)
            except Exception:
                # an older collector may lack fields the verdict needs
                CTX.logger.warning('host-metrics: no verdict for host %s', row['name'], exc_info=True)
    return [{k: row[k] for k in ('id', 'name', 'state', 'version', 'snapshot', 'verdict', 'error')}
            for row in rows]


@bp.route('/hosts', methods=['GET'], endpoint='list_hosts')
@jwt_required()
def list_hosts():
    refresh = request.args.get('refresh') == '1'
    if not refresh:
        cached = _cache_get(HOSTS_CACHE_KEY)
        if cached is not None:
            return jsonify({'data': {'hosts': cached}})
    from ui.models import Host

    # Rows become plain data here, in the request thread.
    connections = [_safe_connection(h) for h in Host.query.order_by(Host.id).all()]
    hosts = build_hosts(connections, CTX.settings.get('global', 0), CTX.manifest.get('version') or '')
    _cache_set(HOSTS_CACHE_KEY, hosts, HOSTS_CACHE_TTL)
    return jsonify({'data': {'hosts': hosts}})


def _passthrough(host_id, argv):
    host = _get_host(host_id)
    if not host:
        return _error('Host not found.', 404)
    conn = _safe_connection(host)
    if getattr(conn, 'error', None):
        return _error(conn.error, 502)
    try:
        rc, parsed, stderr = hm_ssh.exec_json(conn, argv, timeout=SERIES_TIMEOUT_SECONDS)
    except Exception as e:
        CTX.logger.warning('host-metrics: query to host %s failed: %s', host.name, e)
        return _error('The host did not answer.', 502)
    if is_no_sudo(rc, stderr):
        return _error(no_sudo_error(conn), 502)
    if rc == hm_ssh.MISSING_RC or 'No such file' in (stderr or ''):
        return _error('Host metrics are not installed on this host.', 409)
    if rc not in (0, 3) or parsed is None:
        CTX.logger.warning('host-metrics: host %s query rc %s: %s', host.name, rc, stderr)
        return _error('The host returned no usable answer.', 502)
    return jsonify({'data': parsed})


def _range_arg():
    value = request.args.get('range', '')
    return value if value in RANGES else None


@bp.route('/hosts/<int:host_id>/series', methods=['GET'], endpoint='host_series')
@jwt_required()
def host_series(host_id):
    range_ = _range_arg()
    if range_ is None:
        return _error('range must be one of: %s.' % ', '.join(RANGES), 400)
    argv = ['series', '--range', range_]
    port = request.args.get('port')
    if port is not None:
        if not (port.isascii() and port.isdigit() and 1 <= int(port) <= 65535):
            return _error('port must be a number from 1 to 65535.', 400)
        argv += ['--port', str(int(port))]
    return _passthrough(host_id, argv)


@bp.route('/hosts/<int:host_id>/events', methods=['GET'], endpoint='host_events')
@jwt_required()
def host_events(host_id):
    range_ = _range_arg()
    if range_ is None:
        return _error('range must be one of: %s.' % ', '.join(RANGES), 400)
    return _passthrough(host_id, ['events', '--range', range_])


# ---- bell notifications (qlsm's poller.tick + ctx.notify, newer cores only) -------
#
# on_tick runs in the `flask run-status-poller` process, inline in its 15 s loop: real
# work only every NOTIFY_EVERY_TICKS-th tick, all hosts' snapshots in parallel (the 5 s
# path of the host list) and a hard budget, so a slow or dead host cannot stall the
# poller. State-based (ruling R8, notifier.py): desired keys from the snapshots, notify
# them all, resolve open ones absent twice in a row. Redis keeps the absent counts and
# each host's outage start, so a poller restart does not reset the 5-minute clock.

NOTIFY_EVERY_TICKS = 4
NOTIFY_BUDGET_SECONDS = 8.0
NOTIFY_GATHER_SECONDS = 6.5     # waiting for the hosts; the rest is for the DB writes
NOTIFY_STATE_KEY = 'addon:host-metrics:notify:absent'
NOTIFY_DOWN_KEY = 'addon:host-metrics:notify:%d:down'
NOTIFY_STATE_TTL = 7 * 86400

_TICKS = [0]


def _wall():
    return time.time()


def _notify_capable():
    return hasattr(CTX, 'notify') and hasattr(CTX, 'resolve')


def on_tick():
    """poller.tick handler. Never raises: a failure is logged and the poller goes on."""
    try:
        count = _TICKS[0]
        _TICKS[0] = count + 1
        if count % NOTIFY_EVERY_TICKS:
            return
        notify_check()
    except Exception:
        try:
            CTX.logger.warning('host-metrics: notification check failed', exc_info=True)
        except Exception:
            pass


def _redis_json(client, key):
    raw = client.get(key)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None


def _open_keys():
    """Keys of this addon's open notifications, read through core's model; None on a core
    without it (then nothing is resolved)."""
    try:
        from ui.models import Notification
    except ImportError:
        return None
    source = getattr(CTX, 'addon_id', None) or 'host-metrics'
    rows = (Notification.query.with_entities(Notification.key)
            .filter_by(source=source, resolved_at=None).all())
    return {row[0] for row in rows if row[0]}


def _result(future):
    if future is None or not future.done() or future.cancelled():
        return None
    try:
        return future.result()
    except Exception:
        return None


def _gather(connections, expected_version):
    """{host_id: snapshot row}; a host not back within NOTIFY_GATHER_SECONDS gets None
    (the worker threads finish on their own SSH timeouts, the check does not wait)."""
    if not connections:
        return {}
    pool = ThreadPoolExecutor(max_workers=max(1, min(FETCH_WORKERS * 2, len(connections))))
    try:
        jobs = {c.id: pool.submit(_fetch_snapshot, c, expected_version) for c in connections}
        wait(list(jobs.values()), timeout=NOTIFY_GATHER_SECONDS)
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    return {host_id: _result(future) for host_id, future in jobs.items()}


def notify_check():
    """One reconciliation pass (app context). Reads first, every DB write at the end."""
    if not _notify_capable():
        return
    started = time.monotonic()
    client = _redis()
    if client is None:
        return
    from ui.models import Host

    try:
        enabled, min_severity = hm_settings.notify_settings(CTX.settings.get('global', 0))
    except ValueError as e:
        CTX.logger.warning('host-metrics: notification settings invalid, treated as off: %s', e)
        enabled, min_severity = False, 'warning'
    hosts = Host.query.order_by(Host.id).all()
    active = [h for h in hosts if CTX.settings.get('host', h.id).get('enabled')] if enabled else []
    connections = [_safe_connection(h) for h in active]
    active_ids = {h.id for h in active}
    for h in hosts:
        if h.id not in active_ids:
            client.delete(NOTIFY_DOWN_KEY % h.id)   # a later switch-on starts a fresh clock
    snaps = _gather(connections, CTX.manifest.get('version') or '')

    wall_now = _wall()
    desired, unknown = {}, set()
    for conn in connections:
        snap = snaps.get(conn.id) or {'state': 'unreachable', 'snapshot': None}
        snapshot = snap.get('snapshot')
        down_redis = NOTIFY_DOWN_KEY % conn.id
        down, item = hm_notifier.down_update(
            conn.id, conn.name, snap.get('state'), data_age(snapshot) if snapshot else None,
            _redis_json(client, down_redis), wall_now, min_severity)
        if down:
            client.setex(down_redis, NOTIFY_STATE_TTL, json.dumps(down))
        else:
            client.delete(down_redis)
        if item:
            desired[hm_notifier.down_key(conn.id)] = item
        events = (hm_notifier.host_events_desired(conn.id, conn.name, snapshot, min_severity)
                  if snap.get('state') in hm_notifier.FRESH_STATES else None)
        if events is None:
            unknown.add(conn.id)
        else:
            desired.update(events)

    # ---- DB writes (ctx.notify / ctx.resolve commit), nothing else touches the DB below
    resolve_keys, absent = hm_notifier.reconcile(
        desired, {c.id for c in connections}, unknown, _open_keys(),
        _redis_json(client, NOTIFY_STATE_KEY) or {})
    client.setex(NOTIFY_STATE_KEY, NOTIFY_STATE_TTL, json.dumps(absent))
    writes = [('resolve', k, None) for k in resolve_keys]
    writes += [('notify', k, desired[k]) for k in sorted(desired)]
    for action, k, item in writes:
        if time.monotonic() - started > NOTIFY_BUDGET_SECONDS:
            CTX.logger.warning('host-metrics: notification check over %.0f s, rest next check',
                               NOTIFY_BUDGET_SECONDS)
            break
        try:
            if action == 'resolve':
                CTX.resolve(k)
            else:
                severity, title, body = item
                CTX.notify(severity, title, body, hm_notifier.link(hm_notifier.host_of_key(k)), k)
        except Exception as e:
            CTX.logger.warning('host-metrics: %s of %s failed (retried next check): %s',
                               action, k, e)


def _core_has_hook(name):
    """An older qlsm core lacks poller.tick, and ctx.on() raises for an unknown hook."""
    try:
        from ui.addons.hooks import HOOK_SCOPES
    except Exception:
        return False
    return name in HOOK_SCOPES


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

    if _core_has_hook('poller.tick'):
        # bell notifications; on_tick itself checks that the core has ctx.notify
        ctx.on('poller.tick', on_tick)
