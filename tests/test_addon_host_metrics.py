"""The host-metrics addon inside qlsm: manifest, settings routes, host switch,
status parsing, apply (queued under the host lock) and payload sync."""
import json
import sys
from pathlib import Path

import pytest

ADDON_DIR = Path(__file__).resolve().parent.parent / 'addons' / 'host-metrics'
API = '/api/addons/host-metrics'
MODULE = 'qlsm_addon_host_metrics'

DEFAULTS = {
    'core_saturated_pct': '95', 'steal_event_pct': '10', 'mem_low_pct': '10', 'disk_low_pct': '90',
    'frames_late_pct': '1', 'frame_gap_ms': '100', 'event_window_s': '60',
    'verdict_target_pct': '70', 'mem_reserve_pct': '20', 'steal_tight_pct': '5',
    'steal_overload_pct': '15',
}


@pytest.fixture
def addon_id():
    return 'host-metrics'


def _backend():
    return sys.modules[MODULE]


def test_manifest_validates(app):
    from ui.addons import get_addon
    from ui.addons.manifest import read_manifest

    manifest, errors = read_manifest(str(ADDON_DIR))
    assert errors == []
    assert manifest['id'] == 'host-metrics'
    assert manifest['version'] == '1.0.0'
    assert manifest['scopes'] == ['global', 'host']
    fields = {f['key']: f for f in manifest['settings']['global']}
    assert {k: f['default'] for k, f in fields.items()} == DEFAULTS
    host_fields = {f['key']: f for f in manifest['settings']['host']}
    assert host_fields['enabled']['type'] == 'bool' and host_fields['enabled']['default'] is True
    with app.app_context():
        addon = get_addon('host-metrics', app)
        assert addon.loaded, addon.errors
        assert addon.errors == []


def _route_exists(app, method, path):
    adapter = app.url_map.bind('localhost')
    try:
        adapter.match(f'{API}/{path}', method=method)
        return True
    except Exception:
        return False


def test_ui_block_and_routes(app):
    raw = json.loads((ADDON_DIR / 'qlsm-addon.json').read_text(encoding='utf-8'))
    ui = raw['ui']
    assert raw['ui_api'] >= 3
    assert ui['page'] == {'label': 'Host Metrics', 'icon': 'gauge', 'component': 'Page.js'}
    assert ui['host_menu'] == [{'id': 'host-metrics', 'label': 'Host Metrics', 'icon': 'gauge',
                                'component': 'HostPanel.js', 'renders': 'modal'}]
    assert ui['settings_section'][0]['panel'] in ui['panels']
    for route in ('GET settings', 'PUT settings', 'GET hosts/1', 'PUT hosts/1',
                  'GET hosts/1/status', 'POST hosts/1/apply'):
        method, _, path = route.partition(' ')
        assert _route_exists(app, method, path), route


@pytest.fixture
def auth(app):
    from conftest import auth_headers, make_user
    make_user(app, 'hmop', 'pw')
    return auth_headers(app, 'hmop')


def _host(app, name='game-1'):
    from ui import db
    from ui.models import Host, HostStatus
    with app.app_context():
        host = Host(name=name, ip_address='10.0.0.1', provider='standalone',
                    runtime='minqlxtended', status=HostStatus.ACTIVE)
        db.session.add(host)
        db.session.commit()
        return host.id


def _ctx(app):
    from ui.addons import get_addon
    return get_addon('host-metrics', app).ctx


def _enable(app, host_id=None, host_enabled=True, global_enabled=True):
    with app.app_context():
        settings = _ctx(app).settings
        settings.set_enabled('global', 0, global_enabled)
        if host_id is not None:
            settings.set('host', host_id, {'enabled': host_enabled})


class FakePlaybook:
    def __init__(self, success=True, stdout='', stderr=''):
        self.calls = []
        self.result = (success, stdout, stderr)

    def __call__(self, host, name, extravars=None):
        self.calls.append((host.id, name, dict(extravars or {})))
        return self.result


@pytest.mark.parametrize('method, path', [
    ('GET', 'settings'),
    ('PUT', 'settings'),
    ('GET', 'hosts/1'),
    ('PUT', 'hosts/1'),
    ('GET', 'hosts/1/status'),
    ('POST', 'hosts/1/apply'),
])
def test_every_route_needs_a_logged_in_operator(client, method, path):
    assert client.open(f'{API}/{path}', method=method, json={}).status_code == 401


# ---- settings routes ------------------------------------------------------------

def test_settings_route_shows_the_defaults(app, client, auth):
    assert client.get(f'{API}/settings', headers=auth).get_json()['data'] == DEFAULTS


def test_settings_route_stores_valid_values(app, client, auth):
    response = client.put(f'{API}/settings', headers=auth, json=dict(DEFAULTS, event_window_s='30'))
    assert response.status_code == 200, response.get_json()
    with app.app_context():
        assert _ctx(app).settings.get('global', 0)['event_window_s'] == '30'
    assert client.get(f'{API}/settings', headers=auth).get_json()['data']['event_window_s'] == '30'


@pytest.mark.parametrize('body', [
    dict(DEFAULTS, core_saturated_pct='abc'),
    dict(DEFAULTS, core_saturated_pct='101'),
    dict(DEFAULTS, frame_gap_ms='0'),
    dict(DEFAULTS, verdict_target_pct='1e2'),
    dict(DEFAULTS, unknown='x'),
])
def test_settings_route_refuses_bad_input(app, client, auth, body):
    response = client.put(f'{API}/settings', headers=auth, json=body)
    assert response.status_code == 400
    assert client.get(f'{API}/settings', headers=auth).get_json()['data'] == DEFAULTS


def test_host_switch_round_trips(app, client, auth):
    host_id = _host(app)
    assert client.get(f'{API}/hosts/{host_id}', headers=auth).get_json()['data'] == {'enabled': True}
    assert client.put(f'{API}/hosts/{host_id}', headers=auth, json={'enabled': False}).status_code == 200
    assert client.get(f'{API}/hosts/{host_id}', headers=auth).get_json()['data'] == {'enabled': False}
    assert client.put(f'{API}/hosts/{host_id}', headers=auth, json={'enabled': 'no'}).status_code == 400
    assert client.get(f'{API}/hosts/9999', headers=auth).status_code == 404


# ---- status -----------------------------------------------------------------------

STATUS_STDOUT = '''
ok: [game-1] => {
    "msg": [
        "HM_VERSION=1.0.0",
        "HM_SERVICE=active",
        "HM_DB_BYTES=1234567"
    ]
}
'''


def test_status_is_parsed_from_the_playbook(app, client, auth, monkeypatch):
    host_id = _host(app)
    fake = FakePlaybook(stdout=STATUS_STDOUT)
    monkeypatch.setattr(_ctx(app), 'run_playbook', fake)
    response = client.get(f'{API}/hosts/{host_id}/status', headers=auth)
    assert response.status_code == 200
    data = response.get_json()['data']
    assert data == {'version': '1.0.0', 'service': 'active', 'db_bytes': 1234567,
                    'expected_version': '1.0.0', 'error': None}
    assert fake.calls == [(host_id, 'status_host_metrics.yml', {})]


@pytest.mark.parametrize('stdout, expected', [
    ('"HM_VERSION="\n"HM_SERVICE=inactive"\n"HM_DB_BYTES="',
     {'version': None, 'service': 'inactive', 'db_bytes': None}),
    ('"HM_VERSION=1.0.0; rm -rf /"\n"HM_SERVICE=ACTIVE;x"\n"HM_DB_BYTES=12abc"',
     {'version': None, 'service': None, 'db_bytes': None}),
    ('"HM_VERSION=0.9.0"', {'version': '0.9.0', 'service': None, 'db_bytes': None}),
    ('garbage', {'version': None, 'service': None, 'db_bytes': None}),
])
def test_parse_status_is_strict(app, stdout, expected):
    status = _backend().parse_status(stdout, '1.0.0')
    assert {k: status[k] for k in expected} == expected
    assert status['expected_version'] == '1.0.0'


def test_status_of_an_unreachable_host_is_200_with_nulls(app, client, auth, monkeypatch):
    host_id = _host(app)
    monkeypatch.setattr(_ctx(app), 'run_playbook', FakePlaybook(success=False, stderr='unreachable'))
    response = client.get(f'{API}/hosts/{host_id}/status', headers=auth)
    assert response.status_code == 200
    data = response.get_json()['data']
    assert data['version'] is None and data['service'] is None and data['db_bytes'] is None
    assert data['expected_version'] == '1.0.0' and data['error']
    assert client.get(f'{API}/hosts/9999/status', headers=auth).status_code == 404


# ---- apply logic and payload sync ------------------------------------------------

def _payload_sync(app, host_id):
    from ui.addons import dispatch
    with app.app_context():
        dispatch('host.payload_sync', host_id, host_id)


def test_payload_sync_skips_a_disabled_host(app, monkeypatch):
    host_id = _host(app)
    _enable(app, host_id, host_enabled=False)
    fake = FakePlaybook()
    monkeypatch.setattr(_ctx(app), 'run_playbook', fake)
    _payload_sync(app, host_id)
    assert fake.calls == []


def test_payload_sync_skips_when_the_addon_is_off(app, monkeypatch):
    host_id = _host(app)
    _enable(app, host_id, global_enabled=False)
    fake = FakePlaybook()
    monkeypatch.setattr(_ctx(app), 'run_playbook', fake)
    _payload_sync(app, host_id)
    assert fake.calls == []


def test_payload_sync_deploys_an_enabled_host(app, monkeypatch):
    host_id = _host(app)
    _enable(app, host_id)
    fake = FakePlaybook()
    monkeypatch.setattr(_ctx(app), 'run_playbook', fake)
    _payload_sync(app, host_id)

    assert len(fake.calls) == 1
    called_host, name, extravars = fake.calls[0]
    assert (called_host, name) == (host_id, 'sync_host_metrics.yml')
    assert extravars['hm_enabled'] is True
    assert extravars['hm_version'] == '1.0.0'
    config = json.loads(extravars['hm_config_json'])
    assert config['version'] == '1.0.0' and config['redis_db'] == 1
    assert config['thresholds']['event_window_s'] == 60
    assert not any(k.startswith('verdict') for k in config['thresholds'])


def test_apply_with_bad_settings_runs_nothing(app, monkeypatch):
    host_id = _host(app)
    _enable(app, host_id)
    with app.app_context():
        _ctx(app).settings.set('global', 0, {'event_window_s': 'soon'})
        fake = FakePlaybook()
        monkeypatch.setattr(_ctx(app), 'run_playbook', fake)
        result = _backend().apply_host(host_id)
    assert result['success'] is False and 'event_window_s' in result['message']
    assert fake.calls == []


def test_apply_of_a_switched_off_host_sends_hm_enabled_false(app, monkeypatch):
    host_id = _host(app)
    _enable(app, host_id, host_enabled=False)
    fake = FakePlaybook()
    monkeypatch.setattr(_ctx(app), 'run_playbook', fake)
    with app.app_context():
        result = _backend().apply_host(host_id)
    assert result['success'] is True
    assert fake.calls[0][2]['hm_enabled'] is False


def test_a_failed_playbook_is_reported(app, monkeypatch):
    host_id = _host(app)
    monkeypatch.setattr(_ctx(app), 'run_playbook', FakePlaybook(success=False, stderr='boom'))
    with app.app_context():
        result = _backend().apply_host(host_id)
    assert result['success'] is False


# ---- enqueueing --------------------------------------------------------------------

@pytest.fixture
def queue(monkeypatch):
    import ui.task_lock
    import ui.tasks
    calls = []
    monkeypatch.setattr(ui.task_lock, 'acquire_lock', lambda *a, **k: True)
    monkeypatch.setattr(ui.task_lock, 'release_lock', lambda *a, **k: True)
    monkeypatch.setattr(ui.tasks, 'enqueue_task',
                        lambda task, *args, **kwargs: calls.append((task.__name__, args, kwargs)))
    return calls


def test_apply_enqueues_the_apply_task(app, client, auth, queue):
    host_id = _host(app)
    response = client.post(f'{API}/hosts/{host_id}/apply', headers=auth)
    assert response.status_code == 202, response.get_json()
    assert 'queued for' in response.get_json()['data']['message']
    assert len(queue) == 1
    name, args, kwargs = queue[0]
    assert name == 'apply_task' and args[0] == host_id and kwargs['lock_token']


def test_a_busy_host_gets_409(app, client, auth, monkeypatch):
    import ui.task_lock
    monkeypatch.setattr(ui.task_lock, 'acquire_lock', lambda *a, **k: False)
    host_id = _host(app)
    assert client.post(f'{API}/hosts/{host_id}/apply', headers=auth).status_code == 409


def test_a_failed_enqueue_releases_the_lock(app, client, auth, monkeypatch):
    import ui.task_lock
    import ui.tasks
    released = []
    monkeypatch.setattr(ui.task_lock, 'acquire_lock', lambda *a, **k: True)
    monkeypatch.setattr(ui.task_lock, 'release_lock', lambda *a, **k: released.append(a))

    def boom(*a, **k):
        raise RuntimeError('redis down')
    monkeypatch.setattr(ui.tasks, 'enqueue_task', boom)
    host_id = _host(app)
    assert client.post(f'{API}/hosts/{host_id}/apply', headers=auth).status_code == 500
    assert len(released) == 1


def test_apply_on_an_unknown_host_is_404(client, auth, queue):
    assert client.post(f'{API}/hosts/9999/apply', headers=auth).status_code == 404
    assert queue == []


# ---- read routes over ssh ---------------------------------------------------------

def _snapshot(version='1.0.0', busy=30.0):
    return {'version': version, 'now': 1, 'cores': 2, 'mem_total': 8 * 2**30,
            'mem_avail_now': 6 * 2**30, 'steal_p95': 0.0, 'core_other_p95': {},
            'insts': [{'port': 27960, 'core': 0, 'busy_p95': busy, 'rss_max': 2**30}],
            'events_24h': {}, 'events_24h_busy': {}}


class FakeRedis:
    def __init__(self):
        self.store = {}

    def get(self, key):
        return self.store.get(key)

    def setex(self, key, ttl, value):
        self.store[key] = value


def _fake_exec(per_host):
    calls = []

    def exec_json(conn, argv, timeout=5.0):
        calls.append((conn.name, list(argv)))
        answer = per_host[conn.name]
        if isinstance(answer, Exception):
            raise answer
        return answer
    exec_json.calls = calls
    return exec_json


def test_hosts_lists_unreachable_and_not_installed_hosts(app, client, auth, monkeypatch):
    _host(app, 'h-ok')
    _host(app, 'h-missing')
    _host(app, 'h-down')
    fake = _fake_exec({
        'h-ok': (0, _snapshot(), ''),
        'h-missing': (127, None, ''),
        'h-down': TimeoutError('timed out'),
    })
    monkeypatch.setattr(_backend().hm_ssh, 'exec_json', fake)
    response = client.get(f'{API}/hosts?refresh=1', headers=auth)
    assert response.status_code == 200, response.get_json()
    rows = {h['name']: h for h in response.get_json()['data']['hosts']}
    assert {n: r['state'] for n, r in rows.items()} == {
        'h-ok': 'ok', 'h-missing': 'not_installed', 'h-down': 'unreachable'}
    assert rows['h-ok']['verdict']['status'] in ('ok', 'tight', 'overloaded', 'unknown')
    assert rows['h-missing']['snapshot'] is None and rows['h-missing']['verdict'] is None


def test_hosts_marks_an_older_collector_outdated_but_keeps_data(app, client, auth, monkeypatch):
    _host(app, 'h-old')
    monkeypatch.setattr(_backend().hm_ssh, 'exec_json',
                        _fake_exec({'h-old': (0, _snapshot(version='0.9.0'), '')}))
    row = client.get(f'{API}/hosts?refresh=1', headers=auth).get_json()['data']['hosts'][0]
    assert row['state'] == 'outdated' and row['version'] == '0.9.0' and row['snapshot']


def test_hosts_rc3_is_no_data_and_missing_file_stderr_is_not_installed(app, client, auth, monkeypatch):
    _host(app, 'h-empty')
    _host(app, 'h-nofile')
    monkeypatch.setattr(_backend().hm_ssh, 'exec_json', _fake_exec({
        'h-empty': (3, {'version': '1.0.0', 'error': 'no_data'}, ''),
        'h-nofile': (2, None, 'python3: can not open file: No such file or directory'),
    }))
    rows = {h['name']: h for h in client.get(f'{API}/hosts?refresh=1', headers=auth)
            .get_json()['data']['hosts']}
    assert rows['h-empty']['state'] == 'no_data' and rows['h-empty']['version'] == '1.0.0'
    assert rows['h-nofile']['state'] == 'not_installed'


def test_fleet_median_reaches_a_host_without_busy_samples(app, client, auth, monkeypatch):
    _host(app, 'h-a')
    _host(app, 'h-b')
    monkeypatch.setattr(_backend().hm_ssh, 'exec_json', _fake_exec({
        'h-a': (0, _snapshot(busy=40.0), ''), 'h-b': (0, _snapshot(busy=None), '')}))
    rows = {h['name']: h for h in client.get(f'{API}/hosts?refresh=1', headers=auth)
            .get_json()['data']['hosts']}
    assert rows['h-b']['verdict']['ref_source'] == 'fleet'
    assert rows['h-b']['verdict']['ref_load'] == 40.0


def test_hosts_uses_cache_within_ttl(app, client, auth, monkeypatch):
    _host(app, 'h-ok')
    app.extensions['redis'] = FakeRedis()
    fake = _fake_exec({'h-ok': (0, _snapshot(), '')})
    monkeypatch.setattr(_backend().hm_ssh, 'exec_json', fake)
    try:
        first = client.get(f'{API}/hosts', headers=auth).get_json()
        assert len(fake.calls) == 1
        second = client.get(f'{API}/hosts', headers=auth).get_json()
        assert len(fake.calls) == 1 and second == first
        client.get(f'{API}/hosts?refresh=1', headers=auth)
        assert len(fake.calls) == 2
    finally:
        app.extensions.pop('redis', None)


def test_series_rejects_bad_range_and_port(app, client, auth, monkeypatch):
    host_id = _host(app)
    fake = _fake_exec({'game-1': (0, {'version': '1.0.0'}, '')})
    monkeypatch.setattr(_backend().hm_ssh, 'exec_json', fake)
    for query in ('range=2h', 'range=24h&port=abc', 'range=24h&port=0', 'range=24h&port=1;ls', ''):
        response = client.get(f'{API}/hosts/{host_id}/series?{query}', headers=auth)
        assert response.status_code == 400, query
    assert client.get(f'{API}/hosts/{host_id}/events?range=bogus', headers=auth).status_code == 400
    assert fake.calls == []


def test_series_argv_is_fixed(app, client, auth, monkeypatch):
    host_id = _host(app)
    fake = _fake_exec({'game-1': (0, {'version': '1.0.0', 'x': 1}, '')})
    monkeypatch.setattr(_backend().hm_ssh, 'exec_json', fake)
    response = client.get(f'{API}/hosts/{host_id}/series?range=24h&port=27960', headers=auth)
    assert response.status_code == 200
    assert response.get_json()['data'] == {'version': '1.0.0', 'x': 1}
    assert fake.calls == [('game-1', ['series', '--range', '24h', '--port', '27960'])]
    client.get(f'{API}/hosts/{host_id}/events?range=7d', headers=auth)
    assert fake.calls[-1] == ('game-1', ['events', '--range', '7d'])


def test_series_of_unreachable_or_uninstalled_host(app, client, auth, monkeypatch):
    host_id = _host(app)

    def down(conn, argv, timeout=5.0):
        raise TimeoutError('t')
    monkeypatch.setattr(_backend().hm_ssh, 'exec_json', down)
    assert client.get(f'{API}/hosts/{host_id}/series?range=1h', headers=auth).status_code == 502
    monkeypatch.setattr(_backend().hm_ssh, 'exec_json', lambda c, a, timeout=5.0: (127, None, ''))
    assert client.get(f'{API}/hosts/{host_id}/series?range=1h', headers=auth).status_code == 409
    assert client.get(f'{API}/hosts/9999/series?range=1h', headers=auth).status_code == 404


def test_remote_command_is_quoted_and_checks_the_script():
    ssh = _backend().hm_ssh
    command = ssh.remote_command(['series', '--range', '24h', '--port', '27960'])
    assert command == ('test -f /home/ql/host-metrics/hm_query.py || exit 127; '
                       'nice -n 19 python3 /home/ql/host-metrics/hm_query.py '
                       'series --range 24h --port 27960')
    assert "'a b; ls'" in ssh.remote_command(['a b; ls'])


def test_series_and_events_get_a_longer_timeout_than_the_snapshot(app, client, auth, monkeypatch):
    host_id = _host(app, 'h-t')
    seen = []

    def exec_json(conn, argv, timeout=5.0):
        seen.append((argv[0], timeout))
        return 0, (_snapshot() if argv[0] == 'snapshot' else {'version': '1.0.0'}), ''
    monkeypatch.setattr(_backend().hm_ssh, 'exec_json', exec_json)
    client.get(f'{API}/hosts?refresh=1', headers=auth)
    client.get(f'{API}/hosts/{host_id}/series?range=30d', headers=auth)
    client.get(f'{API}/hosts/{host_id}/events?range=30d', headers=auth)
    assert seen == [('snapshot', 5.0), ('series', 20.0), ('events', 20.0)]


def _aged_snapshot(age, with_field=True):
    snap = dict(_snapshot(), now=10_000, host={'ts': 10_000 - age, 'mem_total': 1})
    if with_field:
        snap['data_age_s'] = age
    return snap


def test_old_collector_data_is_stale_without_slots(app, client, auth, monkeypatch):
    _host(app, 'h-fresh')
    _host(app, 'h-stale')
    _host(app, 'h-stale-old-query')
    monkeypatch.setattr(_backend().hm_ssh, 'exec_json', _fake_exec({
        'h-fresh': (0, _aged_snapshot(120), ''),
        'h-stale': (0, _aged_snapshot(185), ''),
        # an older hm_query without data_age_s: the age comes from now - host.ts
        'h-stale-old-query': (0, _aged_snapshot(3600, with_field=False), ''),
    }))
    rows = {h['name']: h for h in client.get(f'{API}/hosts?refresh=1', headers=auth)
            .get_json()['data']['hosts']}
    assert rows['h-fresh']['state'] == 'ok' and rows['h-fresh']['verdict']['slots'] is not None
    stale = rows['h-stale']
    assert stale['state'] == 'stale' and stale['snapshot']['host']['ts'] == 10_000 - 185
    assert stale['verdict']['status'] == 'unknown' and stale['verdict']['slots'] is None
    assert stale['verdict']['reason'] == 'collector data is 3 min old'
    old = rows['h-stale-old-query']
    assert old['state'] == 'stale' and old['verdict']['reason'] == 'collector data is 60 min old'


def test_classify_stale_only_after_120_s(app):
    classify = _backend().classify
    assert classify(0, _aged_snapshot(120), '', '1.0.0')[0] == 'ok'
    assert classify(0, _aged_snapshot(121), '', '1.0.0')[0] == 'stale'
    assert classify(0, _aged_snapshot(121), '', '2.0.0')[0] == 'stale'
    assert classify(0, dict(_snapshot(), host=None), '', '1.0.0')[0] == 'ok'


@pytest.mark.parametrize('path', ['hosts', 'hosts/1/series?range=1h', 'hosts/1/events?range=1h'])
def test_read_routes_need_login(client, path):
    assert client.get(f'{API}/{path}').status_code == 401


def _break_connection_for(monkeypatch, bad_name):
    ssh = _backend().hm_ssh
    real = ssh.connection

    def connection(host):
        if host.name == bad_name:
            raise ValueError('self host has no management address')
        return real(host)
    monkeypatch.setattr(ssh, 'connection', connection)


def test_a_host_whose_connection_cannot_be_built_is_unreachable(app, client, auth, monkeypatch):
    _host(app, 'h-a')
    _host(app, 'h-bad')
    _host(app, 'h-c')
    _break_connection_for(monkeypatch, 'h-bad')
    monkeypatch.setattr(_backend().hm_ssh, 'exec_json', _fake_exec({
        'h-a': (0, _snapshot(), ''), 'h-c': (127, None, '')}))
    response = client.get(f'{API}/hosts?refresh=1', headers=auth)
    assert response.status_code == 200, response.get_json()
    rows = {h['name']: h for h in response.get_json()['data']['hosts']}
    assert {n: r['state'] for n, r in rows.items()} == {
        'h-a': 'ok', 'h-bad': 'unreachable', 'h-c': 'not_installed'}
    assert rows['h-bad']['error'] and 'management address' not in rows['h-bad']['error']
    assert rows['h-a']['error'] is None


def test_series_of_a_host_whose_connection_cannot_be_built_is_502(app, client, auth, monkeypatch):
    host_id = _host(app, 'h-bad')
    _break_connection_for(monkeypatch, 'h-bad')
    fake = _fake_exec({})
    monkeypatch.setattr(_backend().hm_ssh, 'exec_json', fake)
    for path in ('series?range=1h', 'events?range=1h'):
        response = client.get(f'{API}/hosts/{host_id}/{path}', headers=auth)
        assert response.status_code == 502 and response.get_json()['error']['message']
    assert fake.calls == []
