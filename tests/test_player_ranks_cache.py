import sys
from pathlib import Path

ADDON_DIR = Path(__file__).resolve().parent.parent / 'addons' / 'player-ranks'
if str(ADDON_DIR) not in sys.path:
    sys.path.insert(0, str(ADDON_DIR))

from cache import cache_key, get_cached, invalidate_instance, set_cached  # noqa: E402


class FakeRedis:
    def __init__(self):
        self.store = {}

    def get(self, key):
        return self.store.get(key)

    def setex(self, key, ttl, value):
        self.store[key] = value

    def keys(self, pattern):
        prefix = pattern.rstrip('*')
        return [k for k in self.store if k.startswith(prefix)]

    def delete(self, *keys):
        for k in keys:
            self.store.pop(k, None)


def test_cache_key_is_stable_for_same_inputs():
    a = cache_key(1, 'qlstats', 'http://x', 'elo', 'duel', ['1', '2'])
    b = cache_key(1, 'qlstats', 'http://x', 'elo', 'duel', ['2', '1'])
    assert a == b  # roster order should not matter


def test_cache_key_differs_on_config_change():
    a = cache_key(1, 'qlstats', 'http://x', 'elo', 'duel', ['1'])
    b = cache_key(1, 'qlstats', 'http://y', 'elo', 'duel', ['1'])
    assert a != b


def test_cache_key_differs_per_instance():
    a = cache_key(1, 'qlstats', 'http://x', 'elo', 'duel', ['1'])
    b = cache_key(2, 'qlstats', 'http://x', 'elo', 'duel', ['1'])
    assert a != b


def test_get_cached_without_redis_is_none():
    assert get_cached(None, 'anykey') is None


def test_set_cached_without_redis_does_not_raise():
    set_cached(None, 'anykey', {'data': {}}, 60)  # should not raise


def test_round_trip_through_fake_redis():
    redis_client = FakeRedis()
    key = cache_key(1, 'qlstats', 'http://x', 'elo', 'duel', ['1'])
    assert get_cached(redis_client, key) is None
    set_cached(redis_client, key, {'data': {}, 'configured': True}, 60)
    assert get_cached(redis_client, key) == {'data': {}, 'configured': True}


def test_invalidate_instance_only_clears_that_instance():
    redis_client = FakeRedis()
    key1 = cache_key(1, 'qlstats', 'http://x', 'elo', 'duel', ['1'])
    key2 = cache_key(2, 'qlstats', 'http://x', 'elo', 'duel', ['1'])
    set_cached(redis_client, key1, {'data': {}}, 60)
    set_cached(redis_client, key2, {'data': {}}, 60)

    invalidate_instance(redis_client, 1)

    assert get_cached(redis_client, key1) is None
    assert get_cached(redis_client, key2) is not None


def test_invalidate_instance_without_redis_does_not_raise():
    invalidate_instance(None, 1)  # should not raise
