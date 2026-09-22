"""Redis cache for /instances/<id>/ranks responses.

Keyed by instance + a fingerprint of (provider, base_url, rating_system,
resolved game type) + a fingerprint of the roster -- deliberately excluding
the API key, so a secret is never part of anything sitting in Redis' own
keyspace (design doc 9.4/9.8). Works without Redis: every function here is a
no-op (cache miss) when the client is None, same contract as
ui/routes/server_status_routes.py's workshop-preview cache.
"""
import hashlib
import json

CACHE_PREFIX = 'addon:player-ranks'
TTL_SUCCESS = 60
TTL_NEGATIVE = 15


def _fingerprint(*parts):
    joined = '\x1f'.join('' if p is None else str(p) for p in parts)
    return hashlib.sha256(joined.encode('utf-8')).hexdigest()[:16]


def cache_key(instance_id, provider_id, base_url, rating_system, game_type, steam_ids):
    config_fp = _fingerprint(provider_id, base_url, rating_system, game_type)
    roster_fp = _fingerprint(','.join(sorted(steam_ids)))
    return f'{CACHE_PREFIX}:{instance_id}:{config_fp}:{roster_fp}'


def get_cached(redis_client, key):
    if redis_client is None:
        return None
    try:
        raw = redis_client.get(key)
    except Exception:
        return None
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None


def set_cached(redis_client, key, payload, ttl):
    if redis_client is None:
        return
    try:
        redis_client.setex(key, ttl, json.dumps(payload))
    except Exception:
        pass


def invalidate_instance(redis_client, instance_id):
    """Called on config save so switching providers/keys doesn't leave a
    stale answer serving for up to TTL_SUCCESS seconds."""
    if redis_client is None:
        return
    try:
        keys = redis_client.keys(f'{CACHE_PREFIX}:{instance_id}:*')
        if keys:
            redis_client.delete(*keys)
    except Exception:
        pass
