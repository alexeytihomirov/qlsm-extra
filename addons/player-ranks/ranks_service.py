"""Orchestrates one GET .../ranks/<provider_id> call: check that provider's
own show/hide toggle, resolve the game type, check the cache, call the
provider, cache the result. See addons/README.md's live_status_columns
contract for the response shape this builds and docs/superpowers/specs/2026-09-22-
qlsm-player-rating-sources-design.md section 9.4 for the rules this follows.

qlstats and Slipgate are installation-wide: their enabled/base_url/
rating_system live in settings.global and are the same for every instance
(2026-09-23 operator decision -- per-instance config for these two was pure
friction, since qlstats.net/slipgate.gg and a rating system don't actually
vary per server). Thunderdome elo-service and server_status stay per
instance, resolved from settings.instance as before.
"""
import json

from flask import current_app

from .cache import TTL_NEGATIVE, TTL_SUCCESS, cache_key, get_cached, set_cached
from .providers import RateLimited, build_registry
from .steam_ids import parse_steam_ids

_PROVIDER_IDS = ('qlstats', 'slipgate', 'elo_service', 'server_status')
_GLOBAL_PROVIDERS = {'qlstats', 'slipgate'}
_API_KEY_FIELD = {
    'slipgate': 'slipgate_api_key',
    'elo_service': 'elo_service_api_key',
}

_NOT_CONFIGURED = {'data': {}, 'configured': False}
_UNKNOWN_PROVIDER = {'data': {}, 'configured': False, 'reason': 'unknown_provider'}


def _redis():
    return current_app.extensions.get('redis')


def _read_status_blob(redis_client, host_id, instance_id):
    if redis_client is None or host_id is None:
        return None
    try:
        raw = redis_client.get(f'server:status:{host_id}:{instance_id}')
    except Exception:
        return None
    if not raw:
        return None
    try:
        blob = json.loads(raw)
    except ValueError:
        return None
    return blob if isinstance(blob, dict) else None


def _global_key_for(provider_id, global_cfg):
    field = _API_KEY_FIELD.get(provider_id)
    if not field:
        return None
    return (global_cfg.get(field) or '').strip() or None


def _instantiate(provider_id, entry, base_url, api_key, rating_system, players_blob):
    extra = {}
    if provider_id == 'qlstats':
        extra['rating_system'] = rating_system
    if provider_id == 'server_status':
        extra['players'] = players_blob
    return entry['factory'](base_url=base_url, api_key=api_key, extra=extra)


def fetch_ranks(instance, provider_id, raw_steam_ids):
    """Returns the exact dict the /ranks/<provider_id> route serializes as JSON."""
    from ui.addons import get_addon

    if provider_id not in _PROVIDER_IDS:
        return dict(_UNKNOWN_PROVIDER)

    addon_ctx = get_addon('player-ranks').ctx
    global_cfg = addon_ctx.settings.get('global', 0)
    instance_cfg = addon_ctx.settings.get('instance', instance.id)
    is_global = provider_id in _GLOBAL_PROVIDERS
    cfg = global_cfg if is_global else instance_cfg

    if not cfg.get(f'{provider_id}_enabled'):
        return dict(_NOT_CONFIGURED)

    registry = build_registry()
    entry = registry.get(provider_id)
    if entry is None:
        return dict(_UNKNOWN_PROVIDER)

    if is_global:
        # No per-instance override for a globally-configured source -- the
        # key lives in settings.global alongside enabled/base_url.
        api_key = _global_key_for(provider_id, global_cfg)
    else:
        api_key = (instance_cfg.get(f'{provider_id}_api_key') or '').strip() or _global_key_for(provider_id, global_cfg)
    if entry['requires_api_key'] and not api_key:
        return {'data': {}, 'configured': False, 'reason': 'missing_api_key'}

    redis_client = _redis()
    status = _read_status_blob(redis_client, instance.host_id, instance.id)
    live_gametype = (status or {}).get('gametype')
    base_url = (cfg.get(f'{provider_id}_base_url') or '').strip() or None
    rating_system = (global_cfg.get('qlstats_rating_system') or 'elo').strip()
    game_type_override = (instance_cfg.get('elo_service_game_type') or '').strip() if provider_id == 'elo_service' else ''

    provider = _instantiate(
        provider_id, entry, base_url, api_key, rating_system, (status or {}).get('players') or [],
    )
    # Explicit override wins outright; otherwise the source's own mapping of
    # the live game type, or None ("don't query, not an error").
    resolved_game_type = game_type_override or (
        provider.map_game_type(live_gametype) if live_gametype else None
    )

    steam_ids = parse_steam_ids(raw_steam_ids)
    if not steam_ids:
        return {'data': {}, 'configured': True}

    key = cache_key(instance.id, provider_id, base_url, rating_system, resolved_game_type, steam_ids)
    cached = get_cached(redis_client, key)
    if cached is not None:
        return cached

    if resolved_game_type is None:
        payload = {'data': {}, 'configured': True}
        set_cached(redis_client, key, payload, TTL_NEGATIVE)
        return payload

    try:
        raw = provider.fetch_ratings(steam_ids, resolved_game_type) or {}
    except RateLimited as e:
        payload = {'data': {}, 'configured': True}
        set_cached(redis_client, key, payload, max(TTL_NEGATIVE, e.retry_after))
        current_app.logger.warning(
            'player-ranks: %s instance=%s rate limited, retry_after=%ss',
            provider_id, instance.id, e.retry_after)
        return payload
    except Exception as e:
        # Deliberately generic: only source + instance + exception type are
        # logged, never headers/bodies/config (design doc 9.4) -- this must
        # never crash the endpoint over a rating source being unreachable.
        current_app.logger.warning(
            'player-ranks: %s instance=%s failed: %s', provider_id, instance.id, type(e).__name__)
        payload = {'data': {}, 'configured': True}
        set_cached(redis_client, key, payload, TTL_NEGATIVE)
        return payload

    data = {}
    for steam_id, result in raw.items():
        if not isinstance(result, dict) or result.get('display') is None:
            continue
        cell = {'display': str(result['display'])}
        if result.get('title'):
            cell['title'] = str(result['title'])
        data[str(steam_id)] = cell

    payload = {'data': data, 'configured': True}
    set_cached(redis_client, key, payload, TTL_SUCCESS)
    return payload
