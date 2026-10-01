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
        self.ttls = {}

    def get(self, key):
        return self.store.get(key)

    def setex(self, key, ttl, value):
        self.store[key] = value
        self.ttls[key] = ttl

    def keys(self, pattern):
        import fnmatch
        return [k for k in self.store if fnmatch.fnmatchcase(k, pattern)]

    def delete(self, *keys):
        for k in keys:
            self.store.pop(k, None)
            self.ttls.pop(k, None)


@pytest.fixture(autouse=True)
def fresh_addon_submodules(app):
    """Each `app` replaces sys.modules['qlsm_addon_player_ranks'] with a new
    module object, but its submodules stay cached from the previous test, so
    the new parent has no `ranks_service` attribute and patch() cannot find
    it. Drop the stale submodules and import against the current parent."""
    import importlib
    import sys

    for name in [m for m in sys.modules if m.startswith('qlsm_addon_player_ranks.')]:
        del sys.modules[name]
    importlib.import_module('qlsm_addon_player_ranks.ranks_service')


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
    assert body['qlstats_enabled'] is False
    assert body['slipgate_enabled'] is False
    assert body['elo_service_display'] == 'sort_score'
    assert body['sources_saved'] is False
    assert 'server_status_enabled' not in body
    assert body['suggested'] is False


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


def test_config_save_stores_source_checkboxes_and_display(client, auth, instance_id):
    resp = client.put(f'{ADDON}/instances/{instance_id}/config', headers=auth, json={
        'qlstats_enabled': True, 'slipgate_enabled': False,
        'elo_service_enabled': True, 'elo_service_base_url': 'http://elo.example',
        'elo_service_game_type': 'ffa_auto', 'elo_service_display': 'rank_label',
    })
    assert resp.status_code == 200

    loaded = client.get(f'{ADDON}/instances/{instance_id}/config', headers=auth).get_json()['data']
    assert loaded['qlstats_enabled'] is True
    assert loaded['slipgate_enabled'] is False
    assert loaded['elo_service_display'] == 'rank_label'
    assert loaded['sources_saved'] is True


def test_config_save_defaults_display_to_sort_score(client, auth, instance_id):
    client.put(f'{ADDON}/instances/{instance_id}/config', headers=auth, json={})
    loaded = client.get(f'{ADDON}/instances/{instance_id}/config', headers=auth).get_json()['data']
    assert loaded['elo_service_display'] == 'sort_score'


def test_config_save_rejects_unknown_display(client, auth, instance_id):
    resp = client.put(f'{ADDON}/instances/{instance_id}/config', headers=auth,
                      json={'elo_service_display': 'mu'})
    assert resp.status_code == 400


def test_config_save_requires_base_url_when_x76_is_on(client, auth, instance_id):
    resp = client.put(f'{ADDON}/instances/{instance_id}/config', headers=auth,
                      json={'elo_service_enabled': True, 'elo_service_game_type': 'ffa_auto'})
    assert resp.status_code == 400
    assert 'Base URL' in resp.get_json()['error']['message']


def test_config_save_requires_pool_when_x76_is_on(client, auth, instance_id):
    resp = client.put(f'{ADDON}/instances/{instance_id}/config', headers=auth,
                      json={'elo_service_enabled': True, 'elo_service_base_url': 'http://elo.example'})
    assert resp.status_code == 400
    assert 'pool' in resp.get_json()['error']['message']


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


def test_unsaved_config_shows_the_global_defaults_as_ticked(client, auth, instance_id):
    set_global(client, auth, qlstats_enabled=True)

    body = client.get(f'{ADDON}/instances/{instance_id}/config', headers=auth).get_json()['data']

    assert body['qlstats_enabled'] is True
    assert body['slipgate_enabled'] is False
    assert body['sources_saved'] is False


def test_saved_config_shows_its_own_checkboxes_not_the_global_defaults(client, auth, instance_id):
    set_global(client, auth, qlstats_enabled=True)
    client.put(f'{ADDON}/instances/{instance_id}/config', headers=auth, json={'qlstats_enabled': False})

    body = client.get(f'{ADDON}/instances/{instance_id}/config', headers=auth).get_json()['data']

    assert body['qlstats_enabled'] is False


def test_config_saved_by_an_older_version_shows_the_global_defaults(client, auth, app, instance_id):
    from ui.addons import get_addon

    set_global(client, auth, slipgate_enabled=True)
    with app.app_context():
        get_addon('player-ranks').ctx.settings.set('instance', instance_id, {'configured': True})

    body = client.get(f'{ADDON}/instances/{instance_id}/config', headers=auth).get_json()['data']

    assert body['slipgate_enabled'] is True
    assert body['suggested'] is False


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
              json={'elo_service_enabled': True, 'elo_service_base_url': 'http://elo.example',
                    'elo_service_game_type': 'ffa_auto'})
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


def test_ranks_finds_status_blob_even_if_instance_host_id_drifted(
    client, auth, instance_id, stub_registry, fake_redis,
):
    """core's own /api/server-status reads server:status:* by the trailing
    instance_id segment and never checks host_id -- this route must be
    equally tolerant of a QLInstance.host_id that no longer matches whatever
    host_id segment the status poller actually wrote (reassigned host, stale
    row), or ratings silently go blank while core's own player list, built
    from the same Redis data, keeps working fine."""
    wrong_host_id = 999999
    _set_status(fake_redis, host_id=wrong_host_id, instance_id=instance_id, gametype='duel')
    stub_registry.fixed_result = {STEAM_A: {'display': '2181'}}
    set_global(client, auth, qlstats_enabled=True)

    resp = client.get(f'{ADDON}/instances/{instance_id}/ranks/qlstats',
                      query_string={'steam_ids': STEAM_A}, headers=auth)

    assert resp.get_json()['data'][STEAM_A]['display'] == '2181'


def test_two_providers_enabled_at_once_both_return_data(
    client, auth, instance_id, host_id, stub_registry, fake_redis,
):
    """qlstats (global) and elo_service (per-instance) can both be on at
    once, each with its own independent result."""
    _set_status(fake_redis, host_id=host_id, instance_id=instance_id, gametype='duel')
    set_global(client, auth, qlstats_enabled=True)
    client.put(f'{ADDON}/instances/{instance_id}/config', headers=auth, json={
        'qlstats_enabled': True,
        'elo_service_enabled': True, 'elo_service_base_url': 'http://elo.example',
        'elo_service_api_key': 'secret', 'elo_service_game_type': 'duel',
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
        'qlstats_enabled': True,
        'elo_service_enabled': True, 'elo_service_base_url': 'http://elo.example',
        'elo_service_api_key': 'secret', 'elo_service_game_type': 'duel',
    })
    client.put(f'{ADDON}/instances/{instance_id}/config', headers=auth, json={
        'qlstats_enabled': True,
        'elo_service_enabled': False,
    })

    qlstats_resp = client.get(f'{ADDON}/instances/{instance_id}/ranks/qlstats',
                              query_string={'steam_ids': STEAM_A}, headers=auth)
    elo_resp = client.get(f'{ADDON}/instances/{instance_id}/ranks/elo_service',
                          query_string={'steam_ids': STEAM_A}, headers=auth)

    assert qlstats_resp.get_json()['configured'] is True
    assert elo_resp.get_json() == {'data': {}, 'configured': False}


def _ranks(client, auth, instance_id, provider_id):
    return client.get(f'{ADDON}/instances/{instance_id}/ranks/{provider_id}',
                      query_string={'steam_ids': STEAM_A}, headers=auth).get_json()


def test_saved_instance_can_turn_a_globally_enabled_source_off(
    client, auth, instance_id, host_id, stub_registry, fake_redis,
):
    _set_status(fake_redis, host_id=host_id, instance_id=instance_id, gametype='duel')
    set_global(client, auth, qlstats_enabled=True)
    client.put(f'{ADDON}/instances/{instance_id}/config', headers=auth, json={'qlstats_enabled': False})

    assert _ranks(client, auth, instance_id, 'qlstats') == {'data': {}, 'configured': False}


def test_saved_instance_can_turn_a_globally_disabled_source_on(
    client, auth, instance_id, host_id, stub_registry, fake_redis,
):
    _set_status(fake_redis, host_id=host_id, instance_id=instance_id, gametype='duel')
    stub_registry.fixed_result = {STEAM_A: {'display': '2181'}}
    client.put(f'{ADDON}/instances/{instance_id}/config', headers=auth, json={'qlstats_enabled': True})

    assert _ranks(client, auth, instance_id, 'qlstats')['data'][STEAM_A]['display'] == '2181'


def test_instance_saved_by_an_older_version_still_follows_the_global_switch(
    client, auth, app, instance_id, host_id, stub_registry, fake_redis,
):
    """0.2.0 stored `configured` but no source checkboxes. Such an instance
    must keep its qlstats column after the update."""
    from ui.addons import get_addon

    _set_status(fake_redis, host_id=host_id, instance_id=instance_id, gametype='duel')
    stub_registry.fixed_result = {STEAM_A: {'display': '2181'}}
    set_global(client, auth, qlstats_enabled=True)
    with app.app_context():
        get_addon('player-ranks').ctx.settings.set('instance', instance_id, {'configured': True})

    assert _ranks(client, auth, instance_id, 'qlstats')['data'][STEAM_A]['display'] == '2181'


def test_x76_display_choice_reaches_the_provider(client, auth, instance_id, host_id, fake_redis):
    class RecordingStub(StubProvider):
        seen_extra = []

        def __init__(self, base_url=None, api_key=None, extra=None):
            super().__init__(base_url, api_key, extra)
            type(self).seen_extra.append(extra)

    _set_status(fake_redis, host_id=host_id, instance_id=instance_id, gametype='duel')
    client.put(f'{ADDON}/instances/{instance_id}/config', headers=auth, json={
        'elo_service_enabled': True, 'elo_service_base_url': 'http://elo.example',
        'elo_service_api_key': 'secret', 'elo_service_game_type': 'ffa_auto',
        'elo_service_display': 'rank_label',
    })
    registry = {'elo_service': {'label': 'x76', 'factory': RecordingStub, 'requires_api_key': True}}
    with patch('qlsm_addon_player_ranks.ranks_service.build_registry', return_value=registry):
        _ranks(client, auth, instance_id, 'elo_service')

    assert RecordingStub.seen_extra == [{'display': 'rank_label'}]


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


def test_provider_failure_is_cached_with_the_short_ttl(client, auth, instance_id, host_id, fake_redis):
    import requests

    _set_status(fake_redis, host_id=host_id, instance_id=instance_id, gametype='duel')
    set_global(client, auth, qlstats_enabled=True)

    class FailingProvider(StubProvider):
        def fetch_ratings(self, steam_ids, game_type):
            raise requests.ConnectionError('down')

    registry = {'qlstats': {'label': 'qlstats', 'factory': FailingProvider, 'requires_api_key': False}}
    with patch('qlsm_addon_player_ranks.ranks_service.build_registry', return_value=registry):
        resp = client.get(f'{ADDON}/instances/{instance_id}/ranks/qlstats',
                          query_string={'steam_ids': STEAM_A}, headers=auth)

    assert resp.get_json() == {'data': {}, 'configured': True}
    rank_ttls = [ttl for key, ttl in fake_redis.ttls.items() if key.startswith('addon:player-ranks:')]
    assert rank_ttls == [15]


# ---- /ranks (combined, every source in one request) ----------------------

def test_ranks_all_requires_auth(client, instance_id):
    assert client.get(f'{ADDON}/instances/{instance_id}/ranks').status_code == 401


def test_ranks_all_unknown_instance_is_404(client, auth):
    assert client.get(f'{ADDON}/instances/9999/ranks', headers=auth).status_code == 404


def test_ranks_all_nothing_enabled_is_unconfigured(client, auth, instance_id):
    resp = client.get(f'{ADDON}/instances/{instance_id}/ranks',
                      query_string={'steam_ids': STEAM_A}, headers=auth)
    assert resp.get_json() == {'data': {}, 'configured': False}


def test_ranks_all_empty_steam_ids_is_configured_with_no_data(client, auth, instance_id, stub_registry):
    set_global(client, auth, qlstats_enabled=True)
    resp = client.get(f'{ADDON}/instances/{instance_id}/ranks', headers=auth)
    assert resp.get_json() == {'data': {}, 'configured': True}
    assert stub_registry.calls == []


def test_ranks_all_one_source_wraps_it_as_a_single_entry(
    client, auth, instance_id, host_id, stub_registry, fake_redis,
):
    _set_status(fake_redis, host_id=host_id, instance_id=instance_id, gametype='duel')
    stub_registry.fixed_result = {STEAM_A: {'display': '2181', 'title': 'duel, 13732 games'}}
    set_global(client, auth, qlstats_enabled=True)

    resp = client.get(f'{ADDON}/instances/{instance_id}/ranks',
                      query_string={'steam_ids': STEAM_A}, headers=auth)

    body = resp.get_json()
    assert body['configured'] is True
    assert body['data'][STEAM_A] == {'entries': [
        {'display': '2181', 'title': 'duel, 13732 games', 'icon_url': 'logos/qlstats.svg'},
    ]}


def test_ranks_all_combines_two_sources_in_one_request_in_declared_order(
    client, auth, instance_id, host_id, fake_redis,
):
    # qlstats (installation-wide) and x76 (per-instance), each stubbed with
    # its own result, combined by one call to the combined route.
    class X76Stub(StubProvider):
        calls = []
        fixed_result = {STEAM_A: {'display': '1500'}}

    _set_status(fake_redis, host_id=host_id, instance_id=instance_id, gametype='duel')
    StubProvider.calls = []
    StubProvider.fixed_result = {STEAM_A: {'display': '2181', 'title': 'duel, 13732 games'}}
    registry = {
        'qlstats': {'label': 'qlstats', 'factory': StubProvider, 'requires_api_key': False},
        'elo_service': {'label': 'x76', 'factory': X76Stub, 'requires_api_key': True},
    }
    set_global(client, auth, qlstats_enabled=True)
    client.put(f'{ADDON}/instances/{instance_id}/config', headers=auth, json={
        'qlstats_enabled': True,
        'elo_service_enabled': True, 'elo_service_base_url': 'http://elo.example',
        'elo_service_api_key': 'secret', 'elo_service_game_type': 'ffa_auto',
    })

    with patch('qlsm_addon_player_ranks.ranks_service.build_registry', return_value=registry):
        resp = client.get(f'{ADDON}/instances/{instance_id}/ranks',
                          query_string={'steam_ids': STEAM_A}, headers=auth)

    body = resp.get_json()
    assert body['configured'] is True
    assert body['data'][STEAM_A]['entries'] == [
        {'display': '2181', 'title': 'duel, 13732 games', 'icon_url': 'logos/qlstats.svg'},
        {'display': '1500', 'icon_url': 'logos/elo_service.svg'},
    ]
    # One client request fanned out to both sources server-side, each asked once.
    assert StubProvider.calls == [((STEAM_A,), 'duel')]
    assert X76Stub.calls == [((STEAM_A,), 'ffa_auto')]


def test_ranks_all_skips_a_player_no_source_has_anything_for(
    client, auth, instance_id, host_id, stub_registry, fake_redis,
):
    _set_status(fake_redis, host_id=host_id, instance_id=instance_id, gametype='duel')
    stub_registry.fixed_result = {}  # qlstats knows nobody
    set_global(client, auth, qlstats_enabled=True)

    resp = client.get(f'{ADDON}/instances/{instance_id}/ranks',
                      query_string={'steam_ids': STEAM_A}, headers=auth)

    assert resp.get_json() == {'data': {}, 'configured': True}
