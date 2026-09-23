"""Player Ranks, as an addon.

Core knows nothing about ratings -- it only renders whatever columns
`live_status_columns` in qlsm-addon.json declares and fetches this addon's
own per-provider route (addons/README.md). Everything about *what* a rating
is, where it comes from, and how it's cached lives here.

Each of the 4 built-in sources (qlstats, Slipgate, Thunderdome elo-service,
server_status) has its own show/hide toggle and its own column -- an
instance can show any combination at once, up to core's 3-contributed-
columns cap. The 'Ranks' instance tab uses a custom load/submit rather than
a managed panel: `update_instance_config` validates each enabled source's
base_url shape before writing, and `get_instance_config` suggests values
read from server.cfg the first time an instance is opened (server_cfg.py),
before the tab has ever been saved -- neither is something the generic
managed-panel machinery does for free.
"""
from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import jwt_required

bp = Blueprint('player_ranks_addon', __name__)

_URL_FIELDS = ('qlstats_base_url', 'slipgate_base_url', 'elo_service_base_url')


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

    addon = get_addon('player-ranks')
    stored = addon.ctx.settings.get('instance', instance_id)
    if stored.get('configured'):
        return jsonify({"data": {**stored, "suggested": False}})

    from .server_cfg import suggest_from_server_cfg

    suggestion = suggest_from_server_cfg(instance)
    if not suggestion:
        return jsonify({"data": {**stored, "suggested": False}})
    return jsonify({"data": {**stored, **suggestion, "suggested": True}})


@bp.route('/instances/<int:instance_id>/config', methods=['PUT'], endpoint='update_instance_config')
@jwt_required()
def update_instance_config(instance_id):
    from ui import db
    from ui.addons import get_addon
    from ui.addons.settings import AddonSettingsError

    from .cache import invalidate_instance

    instance, error = _instance_or_404(instance_id)
    if error:
        return error

    body = request.get_json(silent=True) or {}

    for field in _URL_FIELDS:
        value = (body.get(field) or '').strip()
        if value and not (value.startswith('http://') or value.startswith('https://')):
            return jsonify({"error": {"message": f'"{field}" must start with http:// or https://'}}), 400

    rating_system = (body.get('qlstats_rating_system') or 'elo').strip()
    if rating_system not in ('elo', 'elo_b'):
        return jsonify({"error": {"message": '"qlstats_rating_system" must be "elo" or "elo_b"'}}), 400

    payload = {
        'configured': True,
        'qlstats_enabled': bool(body.get('qlstats_enabled')),
        'qlstats_base_url': (body.get('qlstats_base_url') or '').strip(),
        'qlstats_rating_system': rating_system,
        'slipgate_enabled': bool(body.get('slipgate_enabled')),
        'slipgate_base_url': (body.get('slipgate_base_url') or '').strip(),
        'slipgate_api_key': body.get('slipgate_api_key') or '',
        'elo_service_enabled': bool(body.get('elo_service_enabled')),
        'elo_service_base_url': (body.get('elo_service_base_url') or '').strip(),
        'elo_service_api_key': body.get('elo_service_api_key') or '',
        'elo_service_game_type': (body.get('elo_service_game_type') or '').strip(),
        'server_status_enabled': bool(body.get('server_status_enabled')),
    }

    addon = get_addon('player-ranks')
    try:
        settings = addon.ctx.settings.set('instance', instance_id, payload)
    except AddonSettingsError as e:
        db.session.rollback()
        return jsonify({"error": {"message": str(e)}}), 400

    # Invalidate before responding -- otherwise toggling a source or fixing a
    # key looks like it did nothing for up to TTL_SUCCESS seconds.
    invalidate_instance(current_app.extensions.get('redis'), instance_id)
    return jsonify({"data": {**settings, "suggested": False}})


@bp.route('/instances/<int:instance_id>/ranks/<provider_id>', methods=['GET'], endpoint='get_instance_ranks')
@jwt_required()
def get_instance_ranks(instance_id, provider_id):
    instance, error = _instance_or_404(instance_id)
    if error:
        return error

    from .ranks_service import fetch_ranks

    payload = fetch_ranks(instance, provider_id, request.args.get('steam_ids', ''))
    return jsonify(payload)


def register(ctx):
    ctx.blueprint(bp)
    # No lifecycle hooks needed: core already drops this addon's AddonState
    # rows on instance/host delete (cleanup_scope), and nothing else here
    # keeps instance-keyed state that would outlive that row.
