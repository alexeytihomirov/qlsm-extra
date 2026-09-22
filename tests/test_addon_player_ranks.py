"""The player-ranks addon's own HTTP wiring: config load/save (incl.
server.cfg prefill), the /ranks route's contract (configured/reason,
steam_ids validation, caching), all through a real qlsm app with the addon
installed the way an operator would (see conftest.py).

Provider network calls are stubbed via a fake entry in the provider registry
rather than mocking `requests` here -- provider-specific HTTP behavior
(qlstats' games<=0 rule, Slipgate's bulk vs public split, elo-service's
sort_score-or-mu) is covered directly in test_player_ranks_providers.py.
"""
import json
from unittest.mock import patch

import pytest

from ui import db
from ui.models import Host, HostStatus, InstanceStatus, QLInstance
from conftest import auth_headers, make_user

ADDON = '/api/addons/player-ranks'


@pytest.fixture
def addon_id():
    return 'player-ranks'


@pytest.fixture
def auth(app):
    make_user(app, 'ranksop', 'pw')
    return auth_headers(app, 'ranksop')


@pytest.fixture
def host_and_instance_id(app):
    with app.app_context():
        host = Host(name='germany', ip_address='10.0.0.1', provider='vultr',
                    status=HostStatus.ACTIVE)
        db.session.add(host)
        db.session.flush()
        instance = QLInstance(name='duel srv', port=27960, hostname='duel', host_id=host.id,
                              status=InstanceStatus.RUNNING)
        db.session.add(instance)
        db.session.commit()
        return host.id, instance.id


@pytest.fixture
def instance_id(host_and_instance_id):
    return host_and_instance_id[1]


@pytest.fixture
def host_id(host_and_instance_id):
    return host_and_instance_id[0]


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


@pytest.fixture(autouse=True)
def no_real_redis(app):
    """Every test here runs against this stub unless it opts into
    `fake_redis` below -- without it, `create_app()`'s own Redis client
    (real if the dev machine happens to have one on localhost:6379, a slow
    connection-refused stub otherwise) leaks addon test keys into
    whatever Redis is actually running."""
    app.extensions['redis'] = None


@pytest.fixture
def fake_redis(app):
    redis_client = FakeRedis()
    app.extensions['redis'] = redis_client
    return redis_client


def _set_status(fake_redis, host_id, instance_id, gametype='duel', players=None):
    fake_redis.store[f'server:status:{host_id}:{instance_id}'] = json.dumps({
        'gametype': gametype, 'players': players or [],
    })


class StubProvider:
    """A provider double: records calls, returns whatever the test wants."""
    calls = []
    fixed_result = {}

    def __init__(self, base_url=None, api_key=None, extra=None):
        self.base_url, self.api_key, self.extra = base_url, api_key, extra

    def map_game_type(self, qlsm_gametype):
        return qlsm_gametype

    def fetch_ratings(self, steam_ids, game_type):
        type(self).calls.append((tuple(steam_ids), game_type))
        return dict(type(self).fixed_result)


@pytest.fixture
def stub_registry():
    StubProvider.calls = []
    StubProvider.fixed_result = {}
    registry = {
        'qlstats': {'label': 'qlstats', 'factory': StubProvider, 'requires_api_key': False},
        'elo_service': {'label': 'Thunderdome elo-service', 'factory': StubProvider, 'requires_api_key': True},
    }
    with patch('qlsm_addon_player_ranks.ranks_service.build_registry', return_value=registry):
        yield StubProvider


STEAM_A = '76561197993968023'
STEAM_B = '76561197960287930'


# ---- auth + not-found --------------------------------------------------

def test_config_requires_auth(client, instance_id):
    assert client.get(f'{ADDON}/instances/{instance_id}/config').status_code == 401


def test_ranks_requires_auth(client, instance_id):
    assert client.get(f'{ADDON}/instances/{instance_id}/ranks').status_code == 401


def test_config_unknown_instance_is_404(client, auth):
    assert client.get(f'{ADDON}/instances/9999/config', headers=auth).status_code == 404


def test_ranks_unknown_instance_is_404(client, auth):
    assert client.get(f'{ADDON}/instances/9999/ranks', headers=auth).status_code == 404


# ---- config load/save ---------------------------------------------------

def test_default_config_has_no_provider_and_is_not_suggested(client, auth, instance_id):
    resp = client.get(f'{ADDON}/instances/{instance_id}/config', headers=auth)
    body = resp.get_json()['data']
    assert body['provider'] == ''
    assert body['suggested'] is False


def test_config_load_suggests_from_server_cfg_when_unsaved(client, auth, instance_id, app, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg_dir = tmp_path / 'configs' / 'germany' / str(instance_id)
    cfg_dir.mkdir(parents=True)
    (cfg_dir / 'server.cfg').write_text('set qlx_balanceUrl "qlstats.net"\n', encoding='utf-8')

    resp = client.get(f'{ADDON}/instances/{instance_id}/config', headers=auth)
    body = resp.get_json()['data']

    assert body['provider'] == 'qlstats'
    assert body['base_url'] == 'http://qlstats.net'
    assert body['suggested'] is True


def test_config_save_rejects_unknown_provider(client, auth, instance_id):
    resp = client.put(f'{ADDON}/instances/{instance_id}/config', headers=auth,
                      json={'provider': 'totally-made-up'})
    assert resp.status_code == 400


def test_config_save_rejects_bad_base_url(client, auth, instance_id):
    resp = client.put(f'{ADDON}/instances/{instance_id}/config', headers=auth,
                      json={'provider': 'qlstats', 'base_url': 'not-a-url'})
    assert resp.status_code == 400


def test_config_save_accepts_valid_values_and_round_trips(client, auth, instance_id):
    resp = client.put(f'{ADDON}/instances/{instance_id}/config', headers=auth, json={
        'provider': 'qlstats', 'base_url': 'http://qlstats.net', 'rating_system': 'elo_b',
    })
    assert resp.status_code == 200

    loaded = client.get(f'{ADDON}/instances/{instance_id}/config', headers=auth).get_json()['data']
    assert loaded['provider'] == 'qlstats'
    assert loaded['rating_system'] == 'elo_b'
    assert loaded['suggested'] is False  # a saved provider is never re-suggested


def test_saved_config_is_no_longer_suggested_even_with_server_cfg_present(
    client, auth, instance_id, tmp_path, monkeypatch,
):
    monkeypatch.chdir(tmp_path)
    cfg_dir = tmp_path / 'configs' / 'germany' / str(instance_id)
    cfg_dir.mkdir(parents=True)
    (cfg_dir / 'server.cfg').write_text('set qlx_balanceUrl "qlstats.net"\n', encoding='utf-8')

    client.put(f'{ADDON}/instances/{instance_id}/config', headers=auth,
              json={'provider': 'server_status'})
    loaded = client.get(f'{ADDON}/instances/{instance_id}/config', headers=auth).get_json()['data']
    assert loaded['provider'] == 'server_status'
    assert loaded['suggested'] is False


# ---- /ranks contract ------------------------------------------------------

def test_ranks_no_provider_is_unconfigured(client, auth, instance_id):
    resp = client.get(f'{ADDON}/instances/{instance_id}/ranks',
                      query_string={'steam_ids': STEAM_A}, headers=auth)
    assert resp.get_json() == {'data': {}, 'configured': False}


def test_ranks_missing_required_api_key_is_unconfigured_with_reason(client, auth, instance_id, stub_registry):
    client.put(f'{ADDON}/instances/{instance_id}/config', headers=auth,
              json={'provider': 'elo_service', 'base_url': 'http://elo.example'})
    resp = client.get(f'{ADDON}/instances/{instance_id}/ranks',
                      query_string={'steam_ids': STEAM_A}, headers=auth)
    body = resp.get_json()
    assert body['configured'] is False
    assert body['reason'] == 'missing_api_key'


def test_ranks_empty_steam_ids_is_configured_with_no_data(client, auth, instance_id, stub_registry):
    client.put(f'{ADDON}/instances/{instance_id}/config', headers=auth, json={'provider': 'qlstats'})
    resp = client.get(f'{ADDON}/instances/{instance_id}/ranks', headers=auth)
    assert resp.get_json() == {'data': {}, 'configured': True}
    assert stub_registry.calls == []  # never even asked the provider


def test_ranks_with_no_live_gametype_is_configured_with_no_data(client, auth, instance_id, stub_registry):
    client.put(f'{ADDON}/instances/{instance_id}/config', headers=auth, json={'provider': 'qlstats'})
    resp = client.get(f'{ADDON}/instances/{instance_id}/ranks',
                      query_string={'steam_ids': STEAM_A}, headers=auth)
    assert resp.get_json() == {'data': {}, 'configured': True}
    assert stub_registry.calls == []


def test_ranks_calls_provider_with_resolved_data(client, auth, instance_id, host_id, stub_registry, fake_redis):
    _set_status(fake_redis, host_id=host_id, instance_id=instance_id, gametype='duel')
    stub_registry.fixed_result = {STEAM_A: {'display': '2181', 'title': 'duel, 13732 games'}}
    client.put(f'{ADDON}/instances/{instance_id}/config', headers=auth, json={'provider': 'qlstats'})

    resp = client.get(f'{ADDON}/instances/{instance_id}/ranks',
                      query_string={'steam_ids': f'{STEAM_A},{STEAM_B}'}, headers=auth)

    body = resp.get_json()
    assert body['configured'] is True
    assert body['data'][STEAM_A] == {'display': '2181', 'title': 'duel, 13732 games'}
    assert STEAM_B not in body['data']
    assert stub_registry.calls == [((STEAM_A, STEAM_B), 'duel')]


def test_ranks_result_is_cached_between_calls(client, auth, instance_id, host_id, stub_registry, fake_redis):
    _set_status(fake_redis, host_id=host_id, instance_id=instance_id, gametype='duel')
    stub_registry.fixed_result = {STEAM_A: {'display': '1000'}}
    client.put(f'{ADDON}/instances/{instance_id}/config', headers=auth, json={'provider': 'qlstats'})

    client.get(f'{ADDON}/instances/{instance_id}/ranks', query_string={'steam_ids': STEAM_A}, headers=auth)
    client.get(f'{ADDON}/instances/{instance_id}/ranks', query_string={'steam_ids': STEAM_A}, headers=auth)

    assert len(stub_registry.calls) == 1  # second call served from cache


def test_config_save_invalidates_cache(client, auth, instance_id, host_id, stub_registry, fake_redis):
    _set_status(fake_redis, host_id=host_id, instance_id=instance_id, gametype='duel')
    stub_registry.fixed_result = {STEAM_A: {'display': '1000'}}
    client.put(f'{ADDON}/instances/{instance_id}/config', headers=auth, json={'provider': 'qlstats'})
    client.get(f'{ADDON}/instances/{instance_id}/ranks', query_string={'steam_ids': STEAM_A}, headers=auth)

    client.put(f'{ADDON}/instances/{instance_id}/config', headers=auth,
              json={'provider': 'qlstats', 'base_url': 'http://other.example'})
    client.get(f'{ADDON}/instances/{instance_id}/ranks', query_string={'steam_ids': STEAM_A}, headers=auth)

    assert len(stub_registry.calls) == 2  # config changed -> re-fetched, not served stale


def test_ranks_caps_steam_ids_at_64(client, auth, instance_id, host_id, stub_registry, fake_redis):
    _set_status(fake_redis, host_id=host_id, instance_id=instance_id, gametype='duel')
    client.put(f'{ADDON}/instances/{instance_id}/config', headers=auth, json={'provider': 'qlstats'})

    many_ids = ','.join(f'7656119{str(i).zfill(10)}' for i in range(100))
    client.get(f'{ADDON}/instances/{instance_id}/ranks', query_string={'steam_ids': many_ids}, headers=auth)

    assert len(stub_registry.calls[0][0]) == 64


def test_ranks_survives_provider_exception(client, auth, instance_id, host_id, fake_redis):
    _set_status(fake_redis, host_id=host_id, instance_id=instance_id, gametype='duel')
    client.put(f'{ADDON}/instances/{instance_id}/config', headers=auth, json={'provider': 'qlstats'})

    class ExplodingProvider(StubProvider):
        def fetch_ratings(self, steam_ids, game_type):
            raise RuntimeError('boom')

    registry = {'qlstats': {'label': 'qlstats', 'factory': ExplodingProvider, 'requires_api_key': False}}
    with patch('qlsm_addon_player_ranks.ranks_service.build_registry', return_value=registry):
        resp = client.get(f'{ADDON}/instances/{instance_id}/ranks',
                          query_string={'steam_ids': STEAM_A}, headers=auth)

    assert resp.status_code == 200
    assert resp.get_json() == {'data': {}, 'configured': True}

