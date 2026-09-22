"""Player Ranks, as an addon.

Core knows nothing about ratings -- it only renders whatever column
`live_status_columns` in qlsm-addon.json declares and fetches this addon's
own `/ranks` route (addons/README.md). Everything about *what* a rating is,
where it comes from, and how it's cached lives here.

The 'Ranks' instance tab uses a custom load/submit rather than a managed
panel: `update_instance_config` validates the provider id against the live
registry and the base_url shape before writing, and `get_instance_config`
suggests values read from server.cfg the first time an instance is opened
(server_cfg.py) -- neither is something the generic managed-panel machinery
does for free.
"""
from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import jwt_required

bp = Blueprint('player_ranks_addon', __name__)


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
    if stored.get('provider'):
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
    from .providers import build_registry

    instance, error = _instance_or_404(instance_id)
    if error:
        return error

    body = request.get_json(silent=True) or {}
    provider = (body.get('provider') or '').strip()
    base_url = (body.get('base_url') or '').strip()
    rating_system = (body.get('rating_system') or 'elo').strip()

    if provider and provider not in build_registry():
        return jsonify({"error": {"message": f'Unknown rating source "{provider}"'}}), 400
    if base_url and not (base_url.startswith('http://') or base_url.startswith('https://')):
        return jsonify({"error": {"message": "Base URL must start with http:// or https://"}}), 400
    if rating_system not in ('elo', 'elo_b'):
        return jsonify({"error": {"message": 'rating_system must be "elo" or "elo_b"'}}), 400

    addon = get_addon('player-ranks')
    try:
        settings = addon.ctx.settings.set('instance', instance_id, {
            'provider': provider,
            'base_url': base_url,
            'api_key': body.get('api_key') or '',
            'rating_system': rating_system,
            'game_type': (body.get('game_type') or '').strip(),
        })
    except AddonSettingsError as e:
        db.session.rollback()
        return jsonify({"error": {"message": str(e)}}), 400

    # Invalidate before responding -- otherwise switching providers or fixing
    # a key looks like it did nothing for up to TTL_SUCCESS seconds.
    invalidate_instance(current_app.extensions.get('redis'), instance_id)
    return jsonify({"data": {**settings, "suggested": False}})


@bp.route('/instances/<int:instance_id>/ranks', methods=['GET'], endpoint='get_instance_ranks')
@jwt_required()
def get_instance_ranks(instance_id):
    instance, error = _instance_or_404(instance_id)
    if error:
        return error

    from .ranks_service import fetch_ranks

    payload = fetch_ranks(instance, request.args.get('steam_ids', ''))
    return jsonify(payload)


def register(ctx):
    ctx.blueprint(bp)
    # No lifecycle hooks needed: core already drops this addon's AddonState
    # rows on instance/host delete (cleanup_scope), and nothing else here
    # keeps instance-keyed state that would outlive that row.
