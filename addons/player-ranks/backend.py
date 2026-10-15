"""Player Ranks, as an addon.

Core knows nothing about ratings -- it only renders whatever columns
`live_status_columns` in qlsm-addon.json declares and fetches this addon's
own per-provider route (addons/README.md). Everything about *what* a rating
is, where it comes from, and how it's cached lives here.

qlstats and Slipgate keep their connection details in `settings.global`,
edited from the addon's own Settings-page panel (`global_sources`, a plain
managed panel -- core's generic /state endpoint handles it, no route in this
file). Which sources an instance shows is chosen on the instance's own
'Ranks' tab, handled here: `update_instance_config` validates the x76 fields
before writing, and `get_instance_config` suggests x76 values read from
server.cfg (server_cfg.py) while the instance's x76 URL is still blank.
A new instance starts with every source off; 0.3.x instances that followed
the old "on by default" switches are migrated at startup (ranks_service).
"""
from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import jwt_required

bp = Blueprint('player_ranks_addon', __name__)

_URL_FIELDS = ('elo_service_base_url',)


def _instance_or_404(instance_id):
    from ui.database import get_instance

    instance = get_instance(instance_id)
    if not instance:
        return None, (jsonify({"error": {"message": "Instance not found"}}), 404)
    return instance, None


@bp.route('/instances/<int:instance_id>/config', methods=['GET'], endpoint='get_instance_config')
@jwt_required()
def get_instance_config(instance_id):
    from ui.addons import get_addon

    instance, error = _instance_or_404(instance_id)
    if error:
        return error

    from .ranks_service import ensure_migrated

    addon = get_addon('player-ranks')
    ensure_migrated(addon.ctx.settings, instance_id)
    values = addon.ctx.settings.get('instance', instance_id)

    if (values.get('elo_service_base_url') or '').strip():
        return jsonify({"data": {**values, "suggested": False}})

    from .server_cfg import suggest_from_server_cfg

    suggestion = suggest_from_server_cfg(instance)
    if not suggestion:
        return jsonify({"data": {**values, "suggested": False}})
    # Pre-fills the x76 fields only; the x76 checkbox keeps its stored value,
    # so saving the tab for another reason never turns x76 on.
    suggestion.pop('elo_service_enabled', None)
    return jsonify({"data": {**values, **suggestion, "suggested": True}})


@bp.route('/instances/<int:instance_id>/config', methods=['PUT'], endpoint='update_instance_config')
@jwt_required()
def update_instance_config(instance_id):
    from ui import db
    from ui.addons import get_addon
    from ui.addons.settings import AddonSettingsError

    from .cache import invalidate_instance
    from .providers.elo_service import DEFAULT_DISPLAY
    from .ranks_service import GLOBAL_PROVIDERS, ensure_migrated

    instance, error = _instance_or_404(instance_id)
    if error:
        return error

    body = request.get_json(silent=True) or {}

    for field in _URL_FIELDS:
        value = (body.get(field) or '').strip()
        if value and not (value.startswith('http://') or value.startswith('https://')):
            return jsonify({"error": {"message": f'"{field}" must start with http:// or https://'}}), 400

    x76_enabled = bool(body.get('elo_service_enabled'))
    x76_base_url = (body.get('elo_service_base_url') or '').strip()
    x76_pool = (body.get('elo_service_game_type') or '').strip()
    if x76_enabled and not x76_base_url:
        return jsonify({"error": {"message": 'x76: Base URL is required when x76 is ticked'}}), 400
    if x76_enabled and not x76_pool:
        return jsonify({"error": {"message": "x76: pool is required when x76 is ticked (e.g. 'ffa_auto')"}}), 400

    payload = {
        'elo_service_enabled': x76_enabled,
        'elo_service_base_url': x76_base_url,
        'elo_service_api_key': body.get('elo_service_api_key') or '',
        'elo_service_game_type': x76_pool,
        'elo_service_display': body.get('elo_service_display') or DEFAULT_DISPLAY,
    }

    addon = get_addon('player-ranks')

    # The qlstats/Slipgate checkboxes are only decided by a save that carries
    # them; a caller sending just the x76 fields leaves them as they are.
    for provider_id in GLOBAL_PROVIDERS:
        key = f'{provider_id}_enabled'
        if key in body:
            payload[key] = bool(body[key])

    # Before the first write, so an old instance's inherited defaults are
    # stored explicitly and not lost to the new rule.
    ensure_migrated(addon.ctx.settings, instance_id)

    try:
        settings = addon.ctx.settings.set('instance', instance_id, payload)
    except AddonSettingsError as e:
        db.session.rollback()
        return jsonify({"error": {"message": str(e)}}), 400

    # Invalidate before responding -- otherwise toggling a source or fixing a
    # key looks like it did nothing for up to TTL_SUCCESS seconds.
    invalidate_instance(current_app.extensions.get('redis'), instance_id)
    return jsonify({"data": {**settings, "suggested": False}})


@bp.route('/instances/<int:instance_id>/ranks', methods=['GET'], endpoint='get_instance_ranks_all')
@jwt_required()
def get_instance_ranks_all(instance_id):
    """The column the UI actually fetches: every enabled source in one
    request (addons/README.md's `entries` cell variant), instead of the
    one-request-per-source `/ranks/<provider_id>` below."""
    instance, error = _instance_or_404(instance_id)
    if error:
        return error

    from ui.addons import get_addon

    from .ranks_service import ensure_migrated, fetch_all_ranks

    ensure_migrated(get_addon('player-ranks').ctx.settings, instance_id)
    payload = fetch_all_ranks(instance, request.args.get('steam_ids', ''))
    return jsonify(payload)


@bp.route('/instances/<int:instance_id>/ranks/<provider_id>', methods=['GET'], endpoint='get_instance_ranks')
@jwt_required()
def get_instance_ranks(instance_id, provider_id):
    """Kept for direct per-source debugging/testing; the live Rank column
    uses the combined route above instead."""
    instance, error = _instance_or_404(instance_id)
    if error:
        return error

    from ui.addons import get_addon

    from .ranks_service import ensure_migrated, fetch_ranks

    ensure_migrated(get_addon('player-ranks').ctx.settings, instance_id)
    payload = fetch_ranks(instance, provider_id, request.args.get('steam_ids', ''))
    return jsonify(payload)


def register(ctx):
    ctx.blueprint(bp)

    def migrate_at_startup(state):
        # Runs when core mounts the blueprint. The database may not be ready
        # yet (first boot, tests); the routes migrate lazily then.
        from ui import db
        from ui.models import AddonState, QLInstance

        from .ranks_service import migrate_all

        try:
            with state.app.app_context():
                inspector = db.inspect(db.engine)
                if not all(inspector.has_table(m.__tablename__) for m in (AddonState, QLInstance)):
                    state.app.logger.info('player-ranks: no database tables yet, startup migration skipped')
                    return
                migrate_all(ctx.settings)
        except Exception:
            state.app.logger.warning('player-ranks: startup migration skipped', exc_info=True)
            with state.app.app_context():
                db.session.rollback()

    bp.record_once(migrate_at_startup)
    # No lifecycle hooks needed: core already drops this addon's AddonState
    # rows on instance/host delete (cleanup_scope), and nothing else here
    # keeps instance-keyed state that would outlive that row.
