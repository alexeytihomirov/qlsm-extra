"""Orchestrates one GET .../ranks/<provider_id> call: check that provider's
own show/hide toggle, resolve the game type, check the cache, call the
provider, cache the result. See addons/README.md's live_status_columns
contract for the response shape this builds and docs/superpowers/specs/2026-09-22-
qlsm-player-rating-sources-design.md section 9.4 for the rules this follows.

qlstats and Slipgate keep their connection details (base_url, rating system,
key) in settings.global, since qlstats.net/slipgate.gg do not vary per
server. Whether each is shown is per instance, on that instance's Ranks tab
(see source_enabled). x76 (elo-service) is configured entirely per instance.
"""
import json

from flask import current_app

from .cache import TTL_NEGATIVE, TTL_SUCCESS, cache_key, get_cached, set_cached
from .providers import RateLimited, build_registry
from .providers.elo_service import DEFAULT_DISPLAY
from .steam_ids import parse_steam_ids

_PROVIDER_IDS = ('qlstats', 'slipgate', 'elo_service')
# Sources whose connection details are installation-wide (settings.global);
# whether they are shown is still chosen per instance.
GLOBAL_PROVIDERS = ('qlstats', 'slipgate')
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


def source_enabled(provider_id, instance_cfg):
    """Whether this instance shows the source: its own checkbox, nothing else.
    A new instance has every source off."""
    return bool(instance_cfg.get(f'{provider_id}_enabled'))


# Keys 0.3.x stored that the manifest no longer declares. The settings API
# drops undeclared keys on read, so the migration reads the raw rows.
_LEGACY_INSTANCE_KEYS = ('configured', 'sources_saved')
_LEGACY_GLOBAL_KEYS = tuple(f'{p}_enabled' for p in GLOBAL_PROVIDERS)


def migrate_instance(global_cfg, stored):
    """The qlstats/Slipgate checkboxes an instance must store so it keeps
    showing what the 0.3.x rule gave it, or None when nothing changes.

    The old rule: an instance whose checkboxes were never saved
    (`sources_saved` falsy) followed the installation-wide "on by default"
    switch; a saved one used its own. `global_cfg` and `stored` are the raw
    stored dicts. A checkbox already present on an unsaved instance was
    written by this migration and is kept, so running it twice is a no-op."""
    saved = bool(stored.get('sources_saved'))
    values = {}
    for provider_id in GLOBAL_PROVIDERS:
        key = f'{provider_id}_enabled'
        if saved or key in stored:
            values[key] = bool(stored.get(key))
        else:
            values[key] = bool(global_cfg.get(key))
    if all(key in stored and stored[key] == value for key, value in values.items()):
        return None
    if all(not value and key not in stored for key, value in values.items()):
        return None  # absent already reads as off
    return values


def _raw_settings(addon_id, scope, scope_id):
    from ui.models import AddonState

    row = AddonState.query.filter_by(addon_id=addon_id, scope=scope, scope_id=scope_id).first()
    return row, (dict(row.settings) if row is not None else {})


def _strip(row, keys):
    kept = {k: v for k, v in row.settings.items() if k not in keys}
    if len(kept) != len(row.settings):
        row.settings_json = json.dumps(kept, ensure_ascii=False, sort_keys=True)
        return True
    return False


def migrate_instance_row(settings, instance_id, global_cfg, commit=True):
    """Apply migrate_instance() to one instance's stored row and drop its
    legacy keys. Returns True when anything was written."""
    from ui import db

    row, stored = _raw_settings(settings.addon_id, 'instance', instance_id)
    values = migrate_instance(global_cfg, stored)
    changed = False
    if values:
        settings.set('instance', instance_id, values, commit=False)
        row, _ = _raw_settings(settings.addon_id, 'instance', instance_id)
        changed = True
    if row is not None and _strip(row, _LEGACY_INSTANCE_KEYS):
        changed = True
    if changed and commit:
        db.session.commit()
    return changed


def migrate_all(settings):
    """Run once per startup over every instance qlsm knows (not only those
    with stored rows: a never-opened instance showed the global default too),
    then drop the global switches. Idempotent. If a concurrent request created
    the same row first (unique constraint), that request migrated: roll back
    and leave it."""
    from sqlalchemy.exc import IntegrityError

    from ui import db
    from ui.models import QLInstance

    try:
        _, global_cfg = _raw_settings(settings.addon_id, 'global', 0)
        for (instance_id,) in db.session.query(QLInstance.id).all():
            migrate_instance_row(settings, instance_id, global_cfg, commit=False)
        global_row, _ = _raw_settings(settings.addon_id, 'global', 0)
        if global_row is not None:
            _strip(global_row, _LEGACY_GLOBAL_KEYS)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()


def ensure_migrated(settings, instance_id=None):
    """Lazy fallback for the routes if the startup pass did not run. While the
    old global switches are still stored the whole migration runs (it is
    atomic and removes them); otherwise this is one cheap read and a no-op, so
    an instance created later can never inherit an old default."""
    _, global_cfg = _raw_settings(settings.addon_id, 'global', 0)
    if any(key in global_cfg for key in _LEGACY_GLOBAL_KEYS):
        migrate_all(settings)


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
    is_global = provider_id in GLOBAL_PROVIDERS
    cfg = global_cfg if is_global else instance_cfg

    if not source_enabled(provider_id, instance_cfg):
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

    display = (instance_cfg.get('elo_service_display') or DEFAULT_DISPLAY).strip()
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
        if result.get('color'):
            cell['color'] = str(result['color'])
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
            if cell.get('color'):
                entry['color'] = cell['color']
            entries.append(entry)
        if entries:
            data[steam_id] = {'entries': entries}

    return {'data': data, 'configured': True}
