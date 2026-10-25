"""Live Settings: change an instance's cvars on the running server.

Three endpoints behind the Live Settings tab of Edit Configuration:

- GET  instances/<id>/cvars        the rows (plugin cvars from the plugins'
                                   sidecars + the cvars pinned to this
                                   instance), each with its server.cfg value
                                   and, from one rcon round trip, its live
                                   value; plus the apply history.
- POST instances/<id>/cvars/apply  `set name "value"` for every change, read
                                   each back, and -- unless told not to --
                                   write the values into qlsm's server.cfg
                                   and queue core's own config sync without
                                   a restart (the instance then shows
                                   UPDATED, as after any save without
                                   restart). The reply carries the engine's
                                   answers verbatim and the server.cfg diff.
- PUT  instances/<id>/pinned       the pinned list.

The addon never claims more than the engine confirmed: a latched cvar comes
back with its `latched` value and the UI says "on next map"; a plugin cvar
the plugin only reads at load applies after `!reload` or a restart, which the
hint under the table says. Values applied without the server.cfg write are
"live only" and gone after a restart.
"""
import os
import time
import uuid

from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import jwt_required

from . import catalog, last_apply
from .cvar_text import CVAR_NAME_RE, sanitize_value, unified_diff, upsert_cvar
from .rcon_client import RconError, query_cvars, resolve_target, set_cvars

bp = Blueprint('live_settings_addon', __name__)
CTX = None

MAX_CHANGES = 50
MAX_VALUE_LEN = 1024
LOCK_TTL_S = 360


def _error(message, code):
    return jsonify({'error': {'message': message}}), code


def _instance_or_error(instance_id):
    from ui.database import get_instance

    if not CTX.settings.is_enabled('global', 0):
        return None, _error('The Live Settings addon is switched off on the Addons page.', 403)
    instance = get_instance(instance_id)
    if not instance:
        return None, _error('Instance not found.', 404)
    if not instance.host:
        return None, _error('Instance has no associated host.', 400)
    return instance, None


def _rows(instance, with_live=True):
    """Groups with cfg and live values, and how the rcon round trip went."""
    descriptions = catalog.catalog_descriptions()
    groups = catalog.plugin_groups(instance)
    groups.append(catalog.pinned_group(CTX.settings, instance.id, descriptions))
    names = catalog.all_names(groups)
    _path, cfg_text = catalog.read_server_cfg(instance)

    rcon = {'ok': False, 'error': None, 'port': instance.zmq_rcon_port, 'read_at': None, 'lines': []}
    live = None
    if with_live:
        started = time.monotonic()
        try:
            target = resolve_target(instance)
            live, lines = query_cvars(target, names)
            rcon.update(ok=True, read_at=time.time(), lines=lines[:200])
        except RconError as e:
            rcon['error'] = str(e)
        except Exception as e:  # a zmq failure must not take the tab down
            current_app.logger.warning('Addon live-settings: rcon query failed for %s: %s', instance.id, e)
            rcon['error'] = 'RCON query failed; see the qlsm log.'
        rcon['elapsed_ms'] = round((time.monotonic() - started) * 1000)
    catalog.fill_values(groups, cfg_text, live)
    return groups, rcon, cfg_text is not None, sorted(descriptions)


@bp.route('/instances/<int:instance_id>/cvars', methods=['GET'], endpoint='list_cvars')
@jwt_required()
def list_cvars(instance_id):
    instance, error = _instance_or_error(instance_id)
    if error:
        return error
    with_live = request.args.get('live', '1') != '0'
    groups, rcon, has_cfg, suggestions = _rows(instance, with_live=with_live)
    return jsonify({'data': {
        'instance': {
            'id': instance.id, 'name': instance.name,
            'status': getattr(instance.status, 'value', str(instance.status)),
        },
        'groups': groups,
        'rcon': rcon,
        'server_cfg_present': has_cfg,
        'suggestions': suggestions,
        'history': last_apply.load(instance.id)['applies'],
    }})


def _validate_changes(payload):
    changes = payload.get('changes')
    if not isinstance(changes, list) or not changes:
        raise ValueError('changes must be a non-empty list of {name, value}.')
    if len(changes) > MAX_CHANGES:
        raise ValueError(f'At most {MAX_CHANGES} changes per apply.')
    out, seen = [], set()
    for item in changes:
        if not isinstance(item, dict):
            raise ValueError('Each change must be an object with name and value.')
        name = item.get('name')
        if not isinstance(name, str) or not CVAR_NAME_RE.match(name) or len(name) > 64:
            raise ValueError(f'"{name}" is not a cvar name (letters, digits and _ only).')
        value = sanitize_value(item.get('value'))
        if len(value) > MAX_VALUE_LEN:
            raise ValueError(f'The value for {name} is too long.')
        if name.lower() in seen:
            raise ValueError(f'{name} appears twice.')
        seen.add(name.lower())
        out.append((name, value))
    return out


def _entries(changes, found):
    entries = []
    for name, value in changes:
        reported = found.get(name.lower())
        if reported is None:
            state = 'no_reply'
        elif reported['latched'] is not None:
            state = 'latched'
        elif reported['value'] == value:
            state = 'live'
        else:
            state = 'mismatch'
        entries.append({
            'name': name, 'value': value, 'command': f'set {name} "{value}"',
            'reply': reported['raw'] if reported else None,
            'live': reported['value'] if reported else None,
            'latched': reported['latched'] if reported else None,
            'state': state,
        })
    return entries


def _persist(instance, changes):
    """Write the values into qlsm's server.cfg and queue core's sync without
    a restart. Returns a dict describing what happened; never raises for the
    expected refusals (busy instance, host setup running, no server.cfg)."""
    from ui.database import update_instance
    from ui.models import HostStatus, InstanceStatus
    from ui.task_lock import acquire_lock, release_lock
    from ui.task_logic.job_failure_handlers import instance_job_failure_handler
    from ui.tasks import apply_instance_config, enqueue_task

    if instance.host.status == HostStatus.CONFIGURING:
        return {'ok': False, 'skipped': 'Host setup is running; server.cfg was not written.'}
    path, before = catalog.read_server_cfg(instance)
    if before is None:
        return {'ok': False, 'skipped': f'qlsm has no copy of {path}; nothing written.'}

    after = before
    for name, value in changes:
        after = upsert_cvar(after, name, value)
    diff = unified_diff(before, after, 'server.cfg')
    if not diff:
        return {'ok': True, 'unchanged': True, 'diff': '',
                'message': 'server.cfg already held these values; nothing to sync.'}

    lock_token = str(uuid.uuid4())
    if not acquire_lock('instance', instance.id, lock_token, ttl=LOCK_TTL_S):
        return {'ok': False, 'diff': diff,
                'skipped': 'Another operation is running on this instance; server.cfg was not written. '
                           'The values are live only until you apply again.'}
    transferred = False
    try:
        with open(path, 'w', encoding='utf-8', newline='') as f:
            f.write(after)
        previous_status = getattr(instance.status, 'value', str(instance.status))
        update_instance(instance.id, status=InstanceStatus.CONFIGURING)
        job = enqueue_task(
            apply_instance_config, instance.id,
            restart=False, previous_status=previous_status,
            lock_token=lock_token, on_failure=instance_job_failure_handler,
        )
        if not job:
            update_instance(instance.id, status=InstanceStatus(previous_status))
            return {'ok': False, 'diff': diff,
                    'skipped': 'server.cfg was written but the sync task could not be queued; '
                               'save the configuration once to sync it.'}
        transferred = True
        return {'ok': True, 'diff': diff, 'job_id': job.id,
                'message': 'server.cfg written; sync to the host queued (no restart).'}
    finally:
        if not transferred:
            release_lock('instance', instance.id, lock_token)


@bp.route('/instances/<int:instance_id>/cvars/apply', methods=['POST'], endpoint='apply_cvars')
@jwt_required()
def apply_cvars(instance_id):
    instance, error = _instance_or_error(instance_id)
    if error:
        return error
    payload = request.get_json(silent=True) or {}
    try:
        changes = _validate_changes(payload)
    except ValueError as e:
        return _error(str(e), 400)
    persist = bool(payload.get('persist', True))

    try:
        target = resolve_target(instance)
    except RconError as e:
        return _error(str(e), 409)
    try:
        found, lines = set_cvars(target, changes)
    except RconError as e:
        return _error(str(e), 502)
    except Exception as e:
        current_app.logger.warning('Addon live-settings: rcon apply failed for %s: %s', instance.id, e)
        return _error('RCON apply failed; see the qlsm log.', 502)

    entries = _entries(changes, found)
    persist_result = None
    if persist:
        try:
            persist_result = _persist(instance, changes)
        except Exception as e:
            current_app.logger.error('Addon live-settings: server.cfg write failed for %s: %s',
                                     instance.id, e, exc_info=True)
            persist_result = {'ok': False, 'skipped': f'server.cfg write failed: {e}'}

    entry = last_apply.record(instance.id, {
        'persist': persist,
        'entries': entries,
        'persist_result': persist_result,
        'lines': lines[:200],
    })
    current_app.logger.info('Addon live-settings: applied %d cvar(s) on instance %s (persist=%s)',
                            len(changes), instance.id, persist)
    return jsonify({'data': entry})


@bp.route('/instances/<int:instance_id>/pinned', methods=['PUT'], endpoint='set_pinned')
@jwt_required()
def set_pinned(instance_id):
    instance, error = _instance_or_error(instance_id)
    if error:
        return error
    payload = request.get_json(silent=True) or {}
    names = payload.get('cvars')
    if not isinstance(names, list):
        return _error('cvars must be a list of names.', 400)
    try:
        stored = catalog.set_pinned_cvars(CTX.settings, instance.id, names)
    except ValueError as e:
        return _error(str(e), 400)
    return jsonify({'data': {'cvars': stored}})


def register(ctx):
    global CTX
    CTX = ctx
    ctx.blueprint(bp)
