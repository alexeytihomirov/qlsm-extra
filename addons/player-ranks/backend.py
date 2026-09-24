"""Player Ranks, as an addon.

Core knows nothing about ratings -- it only renders whatever columns
`live_status_columns` in qlsm-addon.json declares and fetches this addon's
own per-provider route (addons/README.md). Everything about *what* a rating
is, where it comes from, and how it's cached lives here.

Two sources (qlstats, Slipgate) are installation-wide switches: their
enabled/base_url/rating_system live in `settings.global` and apply to every
instance identically, edited from the addon's own Settings-page panel
(`global_sources`, a plain managed panel -- core's generic /state endpoint
handles it, no route in this file). The other two (Thunderdome elo-service,
server_status) genuinely vary per instance (a different service/pool per
host is the normal case) and stay on the instance's own 'Ranks' tab, handled
here: `update_instance_config` validates elo_service_base_url's shape before
writing, and `get_instance_config` suggests values read from server.cfg the
first time an instance is opened (server_cfg.py), before the tab has ever
been saved.
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

    payload = {
        'configured': True,
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
