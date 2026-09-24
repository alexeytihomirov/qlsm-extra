"""The player-ranks addon's own HTTP wiring: config load/save (incl.
server.cfg prefill), each /ranks/<provider_id> route's contract
(configured/reason, steam_ids validation, caching), all through a real qlsm
app with the addon installed the way an operator would (see conftest.py).

qlstats and Slipgate are installation-wide switches (settings.global, edited
through core's generic /api/addons/player-ranks/state endpoint -- see
set_global() below); Thunderdome elo-service and server_status stay
per-instance, edited through this addon's own /instances/<id>/config.

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


def set_global(client, auth, **settings):
    """qlstats/Slipgate live in settings.global -- a managed panel backed by
    core's own generic state endpoint, not this addon's code."""
    resp = client.put(f'{ADDON}/state', headers=auth,
                      query_string={'scope': 'global', 'scope_id': 0},
                      json={'settings': settings})
    assert resp.status_code == 200, resp.get_json()
    return resp.get_json()['data']


# ---- auth + not-found --------------------------------------------------

def test_config_requires_auth(client, instance_id):
    assert client.get(f'{ADDON}/instances/{instance_id}/config').status_code == 401


def test_ranks_requires_auth(client, instance_id):
    assert client.get(f'{ADDON}/instances/{instance_id}/ranks/qlstats').status_code == 401


def test_config_unknown_instance_is_404(client, auth):
    assert client.get(f'{ADDON}/instances/9999/config', headers=auth).status_code == 404


def test_ranks_unknown_instance_is_404(client, auth):
    assert client.get(f'{ADDON}/instances/9999/ranks/qlstats', headers=auth).status_code == 404


# ---- config load/save (instance: elo_service + server_status only) -------

def test_default_config_has_everything_off_and_is_not_suggested(client, auth, instance_id):
    resp = client.get(f'{ADDON}/instances/{instance_id}/config', headers=auth)
    body = resp.get_json()['data']
    assert body['elo_service_enabled'] is False
    assert body['server_status_enabled'] is False
    assert body['suggested'] is False
    assert 'qlstats_enabled' not in body  # global now, not part of instance config


def test_config_load_suggests_from_server_cfg_when_unsaved(client, auth, instance_id, app, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg_dir = tmp_path / 'configs' / 'germany' / str(instance_id)
    cfg_dir.mkdir(parents=True)
    (cfg_dir / 'server.cfg').write_text('set qlx_rankedServiceUrl "http://localhost:5002"\n', encoding='utf-8')

    resp = client.get(f'{ADDON}/instances/{instance_id}/config', headers=auth)
    body = resp.get_json()['data']

    assert body['elo_service_enabled'] is True
    assert body['elo_service_base_url'] == 'http://localhost:5002'
    assert body['suggested'] is True


def test_config_save_rejects_bad_base_url(client, auth, instance_id):
    resp = client.put(f'{ADDON}/instances/{instance_id}/config', headers=auth,
                      json={'elo_service_enabled': True, 'elo_service_base_url': 'not-a-url'})
    assert resp.status_code == 400


def test_config_save_accepts_valid_values_and_round_trips(client, auth, instance_id):
    resp = client.put(f'{ADDON}/instances/{instance_id}/config', headers=auth, json={
        'elo_service_enabled': True, 'elo_service_base_url': 'http://elo.example',
        'elo_service_game_type': 'ffa_auto',
    })
    assert resp.status_code == 200

    loaded = client.get(f'{ADDON}/instances/{instance_id}/config', headers=auth).get_json()['data']
    assert loaded['elo_service_enabled'] is True
    assert loaded['elo_service_game_type'] == 'ffa_auto'
    assert loaded['suggested'] is False  # a saved config is never re-suggested


def test_saved_config_with_everything_off_is_no_longer_suggested(
    client, auth, instance_id, tmp_path, monkeypatch,
):
    monkeypatch.chdir(tmp_path)
    cfg_dir = tmp_path / 'configs' / 'germany' / str(instance_id)
    cfg_dir.mkdir(parents=True)
    (cfg_dir / 'server.cfg').write_text('set qlx_rankedServiceUrl "http://localhost:5002"\n', encoding='utf-8')

    client.put(f'{ADDON}/instances/{instance_id}/config', headers=auth, json={})
    loaded = client.get(f'{ADDON}/instances/{instance_id}/config', headers=auth).get_json()['data']
    assert loaded['elo_service_enabled'] is False
    assert loaded['suggested'] is False


# ---- config load/save (global: qlstats + Slipgate) ------------------------

def test_global_sources_default_off(client, auth):
    resp = client.get(f'{ADDON}/state', headers=auth, query_string={'scope': 'global', 'scope_id': 0})
    settings = resp.get_json()['data']['settings']
    assert settings['qlstats_enabled'] is False
    assert settings['slipgate_enabled'] is False


def test_enabling_qlstats_globally_applies_to_every_instance(
    client, auth, app, host_and_instance_id, stub_registry, fake_redis,
):
    """The whole point of the redesign: one switch, every instance -- no
    per-instance PUT .../config needed at all for qlstats/Slipgate."""
    host_id, instance_id = host_and_instance_id
    with app.app_context():
        second = QLInstance(name='second srv', port=27961, hostname='second', host_id=host_id,
                            status=InstanceStatus.RUNNING)
        db.session.add(second)
        db.session.commit()
        second_id = second.id

    set_global(client, auth, qlstats_enabled=True, qlstats_base_url='http://qlstats.net')

    stub_registry.fixed_result = {STEAM_A: {'display': '2181'}}
    for iid in (instance_id, second_id):
        _set_status(fake_redis, host_id=host_id, instance_id=iid, gametype='duel')
        resp = client.get(f'{ADDON}/instances/{iid}/ranks/qlstats',
                          query_string={'steam_ids': STEAM_A}, headers=auth)
        assert resp.get_json()['data'][STEAM_A]['display'] == '2181'


def test_qlstats_disabled_globally_is_unconfigured_on_every_instance(client, auth, instance_id):
    resp = client.get(f'{ADDON}/instances/{instance_id}/ranks/qlstats',
                      query_string={'steam_ids': STEAM_A}, headers=auth)
    assert resp.get_json() == {'data': {}, 'configured': False}


def test_slipgate_missing_api_key_is_not_required_globally(
    client, auth, instance_id, host_id, fake_redis,
):
    """Slipgate works without a key (public per-player lookup) -- only
    elo_service hard-requires one."""
    _set_status(fake_redis, host_id=host_id, instance_id=instance_id, gametype='duel')
    set_global(client, auth, slipgate_enabled=True)
    StubProvider.calls = []
    StubProvider.fixed_result = {STEAM_A: {'display': '1650'}}
    registry = {'slipgate': {'label': 'Slipgate', 'factory': StubProvider, 'requires_api_key': False}}
    with patch('qlsm_addon_player_ranks.ranks_service.build_registry', return_value=registry):
        resp = client.get(f'{ADDON}/instances/{instance_id}/ranks/slipgate',
                          query_string={'steam_ids': STEAM_A}, headers=auth)
    assert resp.get_json()['data'][STEAM_A]['display'] == '1650'


# ---- /ranks/<provider_id> contract ----------------------------------------

def test_ranks_disabled_provider_is_unconfigured(client, auth, instance_id):
    resp = client.get(f'{ADDON}/instances/{instance_id}/ranks/qlstats',
                      query_string={'steam_ids': STEAM_A}, headers=auth)
    assert resp.get_json() == {'data': {}, 'configured': False}


def test_ranks_unknown_provider_id_is_unconfigured_with_reason(client, auth, instance_id):
    resp = client.get(f'{ADDON}/instances/{instance_id}/ranks/totally-made-up',
                      query_string={'steam_ids': STEAM_A}, headers=auth)
    body = resp.get_json()
    assert body['configured'] is False
    assert body['reason'] == 'unknown_provider'


def test_ranks_missing_required_api_key_is_unconfigured_with_reason(client, auth, instance_id, stub_registry):
    client.put(f'{ADDON}/instances/{instance_id}/config', headers=auth,
              json={'elo_service_enabled': True, 'elo_service_base_url': 'http://elo.example'})
    resp = client.get(f'{ADDON}/instances/{instance_id}/ranks/elo_service',
                      query_string={'steam_ids': STEAM_A}, headers=auth)
    body = resp.get_json()
    assert body['configured'] is False
    assert body['reason'] == 'missing_api_key'


def test_ranks_empty_steam_ids_is_configured_with_no_data(client, auth, instance_id, stub_registry):
    set_global(client, auth, qlstats_enabled=True)
    resp = client.get(f'{ADDON}/instances/{instance_id}/ranks/qlstats', headers=auth)
    assert resp.get_json() == {'data': {}, 'configured': True}
    assert stub_registry.calls == []  # never even asked the provider


def test_ranks_with_no_live_gametype_is_configured_with_no_data(client, auth, instance_id, stub_registry):
    set_global(client, auth, qlstats_enabled=True)
    resp = client.get(f'{ADDON}/instances/{instance_id}/ranks/qlstats',
                      query_string={'steam_ids': STEAM_A}, headers=auth)
    assert resp.get_json() == {'data': {}, 'configured': True}
    assert stub_registry.calls == []


def test_ranks_calls_provider_with_resolved_data(client, auth, instance_id, host_id, stub_registry, fake_redis):
    _set_status(fake_redis, host_id=host_id, instance_id=instance_id, gametype='duel')
    stub_registry.fixed_result = {STEAM_A: {'display': '2181', 'title': 'duel, 13732 games'}}
    set_global(client, auth, qlstats_enabled=True)

    resp = client.get(f'{ADDON}/instances/{instance_id}/ranks/qlstats',
                      query_string={'steam_ids': f'{STEAM_A},{STEAM_B}'}, headers=auth)

    body = resp.get_json()
    assert body['configured'] is True
    assert body['data'][STEAM_A] == {'display': '2181', 'title': 'duel, 13732 games'}
    assert STEAM_B not in body['data']
    assert stub_registry.calls == [((STEAM_A, STEAM_B), 'duel')]


def test_two_providers_enabled_at_once_both_return_data(
    client, auth, instance_id, host_id, stub_registry, fake_redis,
):
    """qlstats (global) and elo_service (per-instance) can both be on at
    once, each with its own independent result."""
    _set_status(fake_redis, host_id=host_id, instance_id=instance_id, gametype='duel')
    set_global(client, auth, qlstats_enabled=True)
    client.put(f'{ADDON}/instances/{instance_id}/config', headers=auth, json={
        'elo_service_enabled': True, 'elo_service_base_url': 'http://elo.example',
        'elo_service_api_key': 'secret',
    })

    stub_registry.fixed_result = {STEAM_A: {'display': '2181'}}
    qlstats_resp = client.get(f'{ADDON}/instances/{instance_id}/ranks/qlstats',
                              query_string={'steam_ids': STEAM_A}, headers=auth)
    stub_registry.fixed_result = {STEAM_A: {'display': '1500'}}
    elo_resp = client.get(f'{ADDON}/instances/{instance_id}/ranks/elo_service',
                          query_string={'steam_ids': STEAM_A}, headers=auth)

    assert qlstats_resp.get_json()['data'][STEAM_A]['display'] == '2181'
    assert elo_resp.get_json()['data'][STEAM_A]['display'] == '1500'


def test_disabling_one_provider_hides_only_its_own_column(
    client, auth, instance_id, host_id, stub_registry, fake_redis,
):
    _set_status(fake_redis, host_id=host_id, instance_id=instance_id, gametype='duel')
    set_global(client, auth, qlstats_enabled=True)
    client.put(f'{ADDON}/instances/{instance_id}/config', headers=auth, json={
        'elo_service_enabled': True, 'elo_service_base_url': 'http://elo.example',
        'elo_service_api_key': 'secret',
    })
    client.put(f'{ADDON}/instances/{instance_id}/config', headers=auth, json={
        'elo_service_enabled': False,
    })

    qlstats_resp = client.get(f'{ADDON}/instances/{instance_id}/ranks/qlstats',
                              query_string={'steam_ids': STEAM_A}, headers=auth)
    elo_resp = client.get(f'{ADDON}/instances/{instance_id}/ranks/elo_service',
                          query_string={'steam_ids': STEAM_A}, headers=auth)

    assert qlstats_resp.get_json()['configured'] is True
    assert elo_resp.get_json() == {'data': {}, 'configured': False}


def test_ranks_result_is_cached_between_calls(client, auth, instance_id, host_id, stub_registry, fake_redis):
    _set_status(fake_redis, host_id=host_id, instance_id=instance_id, gametype='duel')
    stub_registry.fixed_result = {STEAM_A: {'display': '1000'}}
    set_global(client, auth, qlstats_enabled=True)

    client.get(f'{ADDON}/instances/{instance_id}/ranks/qlstats', query_string={'steam_ids': STEAM_A}, headers=auth)
    client.get(f'{ADDON}/instances/{instance_id}/ranks/qlstats', query_string={'steam_ids': STEAM_A}, headers=auth)

    assert len(stub_registry.calls) == 1  # second call served from cache


def test_config_save_invalidates_cache(client, auth, instance_id, host_id, stub_registry, fake_redis):
    _set_status(fake_redis, host_id=host_id, instance_id=instance_id, gametype='duel')
    stub_registry.fixed_result = {STEAM_A: {'display': '1000'}}
    set_global(client, auth, qlstats_enabled=True)
    client.get(f'{ADDON}/instances/{instance_id}/ranks/qlstats', query_string={'steam_ids': STEAM_A}, headers=auth)

    set_global(client, auth, qlstats_enabled=True, qlstats_base_url='http://other.example')
    client.get(f'{ADDON}/instances/{instance_id}/ranks/qlstats', query_string={'steam_ids': STEAM_A}, headers=auth)

    assert len(stub_registry.calls) == 2  # global config changed -> re-fetched, not served stale


def test_ranks_caps_steam_ids_at_64(client, auth, instance_id, host_id, stub_registry, fake_redis):
    _set_status(fake_redis, host_id=host_id, instance_id=instance_id, gametype='duel')
    set_global(client, auth, qlstats_enabled=True)

    many_ids = ','.join(f'7656119{str(i).zfill(10)}' for i in range(100))
    client.get(f'{ADDON}/instances/{instance_id}/ranks/qlstats', query_string={'steam_ids': many_ids}, headers=auth)

    assert len(stub_registry.calls[0][0]) == 64


def test_ranks_survives_provider_exception(client, auth, instance_id, host_id, fake_redis):
    _set_status(fake_redis, host_id=host_id, instance_id=instance_id, gametype='duel')
    set_global(client, auth, qlstats_enabled=True)

    class ExplodingProvider(StubProvider):
        def fetch_ratings(self, steam_ids, game_type):
            raise RuntimeError('boom')

    registry = {'qlstats': {'label': 'qlstats', 'factory': ExplodingProvider, 'requires_api_key': False}}
    with patch('qlsm_addon_player_ranks.ranks_service.build_registry', return_value=registry):
        resp = client.get(f'{ADDON}/instances/{instance_id}/ranks/qlstats',
                          query_string={'steam_ids': STEAM_A}, headers=auth)

    assert resp.status_code == 200
    assert resp.get_json() == {'data': {}, 'configured': True}
