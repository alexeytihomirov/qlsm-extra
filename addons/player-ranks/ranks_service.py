"""Orchestrates one GET .../ranks/<provider_id> call: check that provider's
own show/hide toggle, resolve the game type, check the cache, call the
provider, cache the result. See addons/README.md's live_status_columns
contract for the response shape this builds and docs/superpowers/specs/2026-09-22-
qlsm-player-rating-sources-design.md section 9.4 for the rules this follows.

qlstats and Slipgate keep their connection details (base_url, rating system,
key) in settings.global, since qlstats.net/slipgate.gg do not vary per
server. Whether each is shown is per instance: an instance whose Ranks tab
was saved by this version decides for itself; any other instance follows the
installation-wide default (see _source_enabled). x76 (elo-service) is
configured entirely per instance.
"""
import json

from flask import current_app

from .cache import TTL_NEGATIVE, TTL_SUCCESS, cache_key, get_cached, set_cached
from .providers import RateLimited, build_registry
from .steam_ids import parse_steam_ids

_PROVIDER_IDS = ('qlstats', 'slipgate', 'elo_service')
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
    """The exact key first (cheap, no SCAN); falls back to a pattern match on
    just the instance_id suffix if that misses. Mirrors what core's own
    server_status_routes.py does (it iterates `server:status:*` and keys off
    the trailing segment, never the host_id) -- an instance whose `host_id`
    in the DB has drifted from what the poller wrote (reassigned host, stale
    row) still shows up there, so this route should be equally tolerant
    instead of going blind over a mismatch core itself doesn't care about."""
    if redis_client is None:
        return None
    raw = None
    if host_id is not None:
        try:
            raw = redis_client.get(f'server:status:{host_id}:{instance_id}')
        except Exception:
            raw = None
    if not raw:
        try:
            matches = redis_client.keys(f'server:status:*:{instance_id}')
            if matches:
                raw = redis_client.get(matches[0])
        except Exception:
            raw = None
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


def _source_enabled(provider_id, global_cfg, instance_cfg):
    """qlstats/Slipgate: an instance whose source checkboxes were never saved
    follows the installation-wide default; once saved, its own checkbox
    decides. `sources_saved` is needed because settings.get() fills a missing
    bool with False, so "never saved" and "unticked" would look the same.
    x76 is always per-instance."""
    if provider_id in _GLOBAL_PROVIDERS and not instance_cfg.get('sources_saved'):
        return bool(global_cfg.get(f'{provider_id}_enabled'))
    return bool(instance_cfg.get(f'{provider_id}_enabled'))


def _instantiate(provider_id, entry, base_url, api_key, rating_system, display):
    extra = {}
    if provider_id == 'qlstats':
        extra['rating_system'] = rating_system
    if provider_id == 'elo_service':
        extra['display'] = display
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

    if not _source_enabled(provider_id, global_cfg, instance_cfg):
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

    display = (instance_cfg.get('elo_service_display') or 'sort_score').strip()
    provider = _instantiate(provider_id, entry, base_url, api_key, rating_system, display)
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


# Icon for each source's stacked entry in the combined column (see
# fetch_all_ranks) -- the same icon each source's old standalone column
# header used to carry.
_ENTRY_ICON = {
    'qlstats': {'icon_url': 'logos/qlstats.svg'},
    'slipgate': {'icon_url': 'logos/slipgate.svg'},
    'elo_service': {'icon_url': 'logos/elo_service.svg'},
}


def fetch_all_ranks(instance, raw_steam_ids):
    """The combined `.../ranks` route: every source in one request instead
    of one request per source. Each per-player cell comes back as
    `entries: [{display, title?, icon?, icon_url?}, ...]`, one entry per
    source that actually has something to say about that player -- the
    `live_status_columns` "stacked cell" variant (addons/README.md).

    Reuses fetch_ranks() for each source so caching, per-source
    enabled/key/game-type resolution and error handling stay exactly as
    they are for the standalone per-provider route -- this just fans out to
    all of them and reshapes the result, it doesn't duplicate any of that
    logic.
    """
    any_configured = False
    per_provider_data = {}
    for provider_id in _PROVIDER_IDS:
        result = fetch_ranks(instance, provider_id, raw_steam_ids)
        if result.get('configured'):
            any_configured = True
        per_provider_data[provider_id] = result.get('data') or {}

    if not any_configured:
        return {'data': {}, 'configured': False}

    data = {}
    for steam_id in parse_steam_ids(raw_steam_ids):
        entries = []
        for provider_id in _PROVIDER_IDS:
            cell = per_provider_data[provider_id].get(steam_id)
            if not cell:
                continue
            entry = {'display': cell['display'], **_ENTRY_ICON.get(provider_id, {})}
            if cell.get('title'):
                entry['title'] = cell['title']
            entries.append(entry)
        if entries:
            data[steam_id] = {'entries': entries}

    return {'data': data, 'configured': True}
