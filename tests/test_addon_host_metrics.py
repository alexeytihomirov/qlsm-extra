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
NOTIFY_DEFAULTS = {'notify_enabled': True, 'notify_min_severity': 'warning'}
SETTINGS = dict(DEFAULTS, **NOTIFY_DEFAULTS)


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
    assert manifest['version'] == '1.1.0'
    assert manifest['scopes'] == ['global', 'host']
    fields = {f['key']: f for f in manifest['settings']['global']}
    assert {k: f['default'] for k, f in fields.items()} == SETTINGS
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
    assert ui['page'] == {'label': 'Host Metrics', 'icon': 'gauge', 'component': 'Page.js',
                          'nav': {'label': 'Hosts health', 'icon': 'gauge'}}
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
    assert client.get(f'{API}/settings', headers=auth).get_json()['data'] == SETTINGS


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
    dict(DEFAULTS, notify_min_severity='loud'),
    dict(DEFAULTS, notify_enabled='maybe'),
])
def test_settings_route_refuses_bad_input(app, client, auth, body):
    response = client.put(f'{API}/settings', headers=auth, json=body)
    assert response.status_code == 400
    assert client.get(f'{API}/settings', headers=auth).get_json()['data'] == SETTINGS


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
                    'expected_version': '1.1.0', 'error': None}
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
    assert data['expected_version'] == '1.1.0' and data['error']
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
    assert extravars['hm_version'] == '1.1.0'
    config = json.loads(extravars['hm_config_json'])
    assert config['version'] == '1.1.0' and config['redis_db'] == 1
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

def _snapshot(version='1.1.0', busy=30.0):
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

    def set(self, key, value, ex=None):
        self.store[key] = value

    def delete(self, *keys):
        for key in keys:
            self.store.pop(key, None)


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


def test_remote_command_is_quoted_and_checks_the_script(app):
    ssh = _backend().hm_ssh
    command = ssh.remote_command(['series', '--range', '24h', '--port', '27960'])
    assert command == ('test -f /home/ql/host-metrics/hm_query.py || exit 127; '
                       'nice -n 19 python3 /home/ql/host-metrics/hm_query.py '
                       'series --range 24h --port 27960')
    assert "'a b; ls'" in ssh.remote_command(['a b; ls'])


def test_remote_command_for_a_non_root_user_goes_through_sudo(app):
    ssh = _backend().hm_ssh
    assert ssh.remote_command(['snapshot'], 'ubuntu') == (
        'sudo -n -u ql test -f /home/ql/host-metrics/hm_query.py || exit 127; '
        'sudo -n -u ql nice -n 19 python3 /home/ql/host-metrics/hm_query.py snapshot')
    assert ssh.remote_command(['snapshot'], 'root') == ssh.remote_command(['snapshot'])
    for bad in ('', 'Root', 'a b', 'x;ls', '$(id)', '1abc', 'a' * 33, None):
        with pytest.raises(ValueError):
            ssh.remote_command(['snapshot'], bad)


def test_invalid_ssh_user_is_unreachable_and_never_executed(app, client, auth, monkeypatch):
    host_id = _host(app, 'h-bad')
    with app.app_context():
        from ui.models import Host
        from ui import db
        Host.query.get(host_id).ssh_user = 'x;rm -rf /'
        db.session.commit()
    fake = _fake_exec({'h-bad': (0, _snapshot(), '')})
    monkeypatch.setattr(_backend().hm_ssh, 'exec_json', fake)
    row = client.get(f'{API}/hosts?refresh=1', headers=auth).get_json()['data']['hosts'][0]
    assert row['state'] == 'unreachable' and row['error'] == _backend().hm_ssh.INVALID_USER_ERROR
    assert fake.calls == []


def test_is_no_sudo_rcs_and_messages(app):
    is_no_sudo = _backend().is_no_sudo
    assert is_no_sudo(127, 'sudo: a password is required')
    assert is_no_sudo(1, 'sudo: a password is required')
    assert is_no_sudo(127, 'sudo: a terminal is required to read the password')
    assert not is_no_sudo(127, '')
    assert not is_no_sudo(127, 'python3: No such file or directory')
    assert not is_no_sudo(0, 'sudo: a password is required')


def test_sudo_refusal_maps_to_no_sudo(app, client, auth, monkeypatch):
    host_id = _host(app, 'h-nosudo')
    monkeypatch.setattr(_backend().hm_ssh, 'exec_json', _fake_exec({
        'h-nosudo': (127, None, 'sudo: a password is required')}))
    row = client.get(f'{API}/hosts?refresh=1', headers=auth).get_json()['data']['hosts'][0]
    assert row['state'] == 'no_sudo'
    assert row['error'].startswith('SSH user ') and row['error'].endswith(' has no passwordless sudo')
    assert row['snapshot'] is None
    response = client.get(f'{API}/hosts/{host_id}/series?range=1h', headers=auth)
    assert response.status_code == 502
    assert 'no passwordless sudo' in response.get_json()['error']['message']


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
    assert classify(0, _aged_snapshot(120), '', '1.1.0')[0] == 'ok'
    assert classify(0, _aged_snapshot(121), '', '1.1.0')[0] == 'stale'
    assert classify(0, _aged_snapshot(121), '', '2.0.0')[0] == 'stale'
    assert classify(0, dict(_snapshot(), host=None), '', '1.1.0')[0] == 'ok'


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


# ---- bell notifications (poller.tick, ctx.notify; newer cores only) ---------------

def test_poller_tick_subscription_follows_the_core(app):
    """An old core has no poller.tick: the addon must not subscribe (ctx.on would raise and
    mark it broken). A core that knows the hook gets the handler."""
    from ui.addons import get_addon
    from ui.addons.hooks import HOOK_SCOPES
    with app.app_context():
        addon = get_addon('host-metrics', app)
        assert addon.loaded and addon.errors == []
        assert ('poller.tick' in addon.ctx.handlers) == ('poller.tick' in HOOK_SCOPES)


def test_tick_does_real_work_every_fourth_tick(app, monkeypatch):
    backend = _backend()
    runs = []
    monkeypatch.setattr(backend, 'notify_check', lambda: runs.append(1))
    monkeypatch.setattr(backend, '_TICKS', [0])
    for _ in range(8):
        backend.on_tick()
    assert len(runs) == 2


def test_tick_never_raises(app, monkeypatch):
    backend = _backend()

    def boom():
        raise RuntimeError('database is locked')
    monkeypatch.setattr(backend, 'notify_check', boom)
    monkeypatch.setattr(backend, '_TICKS', [0])
    backend.on_tick()


class Bell:
    def __init__(self):
        self.calls = []

    def notify(self, severity, title, body='', link=None, key=None):
        self.calls.append(('notify', severity, title, body, link, key))

    def resolve(self, key):
        self.calls.append(('resolve', key))

    def take(self):
        calls, self.calls = self.calls, []
        return calls


@pytest.fixture
def bell(app, monkeypatch):
    b = Bell()
    ctx = _ctx(app)
    monkeypatch.setattr(ctx, 'notify', b.notify, raising=False)
    monkeypatch.setattr(ctx, 'resolve', b.resolve, raising=False)
    b.redis = FakeRedis()
    app.extensions['redis'] = b.redis
    b.wall = [100_000.0]
    monkeypatch.setattr(_backend(), '_wall', lambda: b.wall[0])
    _enable(app)
    yield b
    app.extensions.pop('redis', None)


def _tick_snapshot(now=5000, players=None, age=10):
    players = {27960: 4} if players is None else players
    return {'version': '1.1.0', 'now': now, 'data_age_s': age, 'host': {'ts': now - age},
            'insts_last': [{'port': p, 'players': n, 'core': 0} for p, n in players.items()],
            'insts': [], 'cores': 2, 'events_open': []}


def _ev(eid, kind, state='open', ts=4990, closed_ts=None, scope='host', port=None, message='m'):
    return {'id': eid, 'ts': ts, 'kind': kind, 'scope': scope, 'port': port, 'severity': 'warn',
            'state': state, 'message': message, 'closed_ts': closed_ts}


class TickHost:
    """exec_json stand-in: per host a snapshot answer and an events answer."""

    def __init__(self):
        self.snapshot = {}
        self.events = {}
        self.calls = []

    def set(self, name, snapshot=None, events=None, now=5000):
        if snapshot is not None:
            self.snapshot[name] = snapshot
        if events is not None:
            self.events[name] = (0, {'version': '1.1.0', 'now': now, 'since': 0, 'events': events}, '')

    def __call__(self, conn, argv, timeout=5.0):
        self.calls.append((conn.name, list(argv)))
        answer = self.snapshot[conn.name] if argv[0] == 'snapshot' else self.events.get(conn.name)
        if callable(answer):
            answer = answer()
        if isinstance(answer, Exception):
            raise answer
        if answer is None:
            return 0, {'version': '1.1.0', 'now': 5000, 'since': 0, 'events': []}, ''
        return answer


@pytest.fixture
def hosts(app, monkeypatch):
    fake = TickHost()
    monkeypatch.setattr(_backend().hm_ssh, 'exec_json', fake)
    return fake


def _check(app):
    with app.app_context():
        _backend().notify_check()


def _last_key(host_id):
    return f'addon:host-metrics:notify:{host_id}'


def test_first_check_starts_from_now_without_replay(app, bell, hosts):
    host_id = _host(app, 'h1')
    hosts.set('h1', snapshot=(0, _tick_snapshot(now=5000), ''),
              events=[_ev(1, 'disk_low', ts=100)])
    _check(app)
    assert [argv[0] for _, argv in hosts.calls] == ['snapshot']
    assert int(bell.redis.store[_last_key(host_id)]) == 5000
    assert bell.take() == []


def test_open_event_notifies_once_and_close_resolves(app, bell, hosts):
    host_id = _host(app, 'h1')
    bell.redis.store[_last_key(host_id)] = '4900'
    late = _ev(7, 'frames_late', scope='instance', port=27960,
               message='port 27960 late frames 3.0%, max gap 140 ms')
    hosts.set('h1', snapshot=(0, _tick_snapshot(), ''), events=[late], now=5000)
    _check(app)
    assert ['events', '--since', '4840'] in [argv for _, argv in hosts.calls]
    calls = bell.take()
    assert len(calls) == 1
    _, severity, title, body, link, key = calls[0]
    assert severity == 'warning'
    assert key == f'host-metrics:{host_id}:frames_late:port:27960'
    assert link == f'/addons/host-metrics?host={host_id}'
    assert 'h1' in title and '27960' in title
    assert body and '140 ms' in body
    assert int(bell.redis.store[_last_key(host_id)]) == 5000

    # the next check sees the same event again (one minute of overlap): nothing new
    hosts.set('h1', events=[late], now=5060)
    _check(app)
    assert bell.take() == []

    closed = dict(late, state='closed', closed_ts=5070)
    hosts.set('h1', events=[closed], now=5120)
    _check(app)
    assert bell.take() == [('resolve', f'host-metrics:{host_id}:frames_late:port:27960')]
    hosts.set('h1', events=[closed], now=5180)
    _check(app)
    assert bell.take() == []


def test_long_open_event_closing_much_later_resolves_without_a_new_notify(app, bell, hosts):
    host_id = _host(app, 'h1')
    bell.redis.store[_last_key(host_id)] = '4900'
    disk = _ev(3, 'disk_low')
    hosts.set('h1', snapshot=(0, _tick_snapshot(), ''), events=[disk], now=5000)
    _check(app)
    assert len(bell.take()) == 1
    for now in range(5060, 9000, 60):     # still open, no longer in the since window
        hosts.set('h1', events=[], now=now)
        _check(app)
    hosts.set('h1', events=[dict(disk, state='closed', closed_ts=9010)], now=9020)
    _check(app)
    assert bell.take() == [('resolve', f'host-metrics:{host_id}:disk_low:host')]


def test_busy_kinds_need_players_on(app, bell, hosts):
    host_id = _host(app, 'h1')
    bell.redis.store[_last_key(host_id)] = '4900'
    hosts.set('h1', snapshot=(0, _tick_snapshot(players={27960: 0, 27961: 3}), ''), events=[
        _ev(1, 'frames_late', scope='instance', port=27960),
        _ev(2, 'core_saturated', scope='core', message='core 1 busy 99% (limit 95%)'),
    ])
    _check(app)
    calls = bell.take()
    assert [c[5] for c in calls] == [f'host-metrics:{host_id}:core_saturated:core:1']
    assert calls[0][1] == 'warning'

    hosts.set('h1', snapshot=(0, _tick_snapshot(players={}), ''), events=[
        _ev(3, 'core_saturated', scope='core', message='core 0 busy 99% (limit 95%)')])
    _check(app)
    assert bell.take() == []


def test_kinds_and_severities(app, bell, hosts):
    host_id = _host(app, 'h1')
    bell.redis.store[_last_key(host_id)] = '4900'
    hosts.set('h1', snapshot=(0, _tick_snapshot(), ''), events=[
        _ev(1, 'oom_kill', state='closed', closed_ts=4990, message='1 OOM kill(s) in the last tick'),
        _ev(2, 'disk_low', message='/ used 93.0% (limit 90%)'),
        _ev(3, 'steal_high', message='host steal 12% (limit 10%)'),
        _ev(4, 'mem_low', message='MemAvailable 8.0% (limit 10%)'),
        _ev(5, 'instance_new', state='closed', closed_ts=4990, scope='instance', port=27962),
        _ev(6, 'instance_gone', state='closed', closed_ts=4990, scope='instance', port=27963),
    ])
    _check(app)
    calls = bell.take()
    notified = {c[5]: c[1] for c in calls if c[0] == 'notify'}
    assert notified == {
        f'host-metrics:{host_id}:oom_kill:host': 'critical',
        f'host-metrics:{host_id}:disk_low:host': 'critical',
        f'host-metrics:{host_id}:steal_high:host': 'warning',
        f'host-metrics:{host_id}:mem_low:host': 'warning',
    }
    for call in calls:
        if call[0] == 'notify':
            assert call[2].startswith('h1: ') and call[3]


def test_a_second_oom_gets_its_own_notification(app, bell, hosts):
    host_id = _host(app, 'h1')
    key = f'host-metrics:{host_id}:oom_kill:host'
    bell.redis.store[_last_key(host_id)] = '4900'
    first = _ev(1, 'oom_kill', state='closed', closed_ts=4990)
    hosts.set('h1', snapshot=(0, _tick_snapshot(), ''), events=[first], now=5000)
    _check(app)
    assert [c[0] for c in bell.take()] == ['resolve', 'notify']
    hosts.set('h1', events=[first], now=5060)
    _check(app)
    assert bell.take() == []
    hosts.set('h1', events=[_ev(2, 'oom_kill', state='closed', ts=5100, closed_ts=5100)], now=5120)
    _check(app)
    assert [(c[0], c[-1]) for c in bell.take()] == [('resolve', key), ('notify', key)]


def test_short_event_between_checks_is_notified_and_resolved(app, bell, hosts):
    host_id = _host(app, 'h1')
    bell.redis.store[_last_key(host_id)] = '4900'
    hosts.set('h1', snapshot=(0, _tick_snapshot(), ''),
              events=[_ev(1, 'mem_low', state='closed', closed_ts=4995)])
    _check(app)
    assert [c[0] for c in bell.take()] == ['notify', 'resolve']


def test_min_severity_and_switch(app, bell, hosts):
    host_id = _host(app, 'h1')
    bell.redis.store[_last_key(host_id)] = '4900'
    hosts.set('h1', snapshot=(0, _tick_snapshot(), ''), events=[
        _ev(1, 'steal_high'), _ev(2, 'disk_low')])
    with app.app_context():
        _ctx(app).settings.set('global', 0, {'notify_min_severity': 'critical'})
    _check(app)
    assert [c[5] for c in bell.take()] == [f'host-metrics:{host_id}:disk_low:host']

    with app.app_context():
        _ctx(app).settings.set('global', 0, {'notify_enabled': False})
    hosts.calls.clear()
    _check(app)
    assert hosts.calls == [] and bell.take() == []


def test_a_switched_off_host_is_not_checked(app, bell, hosts):
    host_id = _host(app, 'h1')
    _enable(app, host_id, host_enabled=False)
    _check(app)
    assert hosts.calls == []


def test_unreachable_for_five_minutes_is_critical_once_and_resolved_once(app, bell, hosts):
    host_id = _host(app, 'h1')
    key = f'host-metrics:{host_id}:stale:host'
    hosts.set('h1', snapshot=TimeoutError('timed out'))
    for _ in range(5):              # 0..240 s: not yet
        _check(app)
        bell.wall[0] += 60
    _check(app)                     # 300 s: not more than 5 min yet
    assert bell.take() == []
    bell.wall[0] += 60
    _check(app)                     # 360 s
    calls = bell.take()
    assert [(c[0], c[1], c[5]) for c in calls] == [('notify', 'critical', key)]
    assert 'h1' in calls[0][2] and calls[0][4] == f'/addons/host-metrics?host={host_id}'
    bell.wall[0] += 60
    _check(app)
    assert bell.take() == []

    hosts.set('h1', snapshot=(0, _tick_snapshot(), ''))
    bell.wall[0] += 60
    _check(app)
    assert bell.take() == [('resolve', key)]
    bell.wall[0] += 60
    _check(app)
    assert bell.take() == []


def test_down_clock_survives_a_poller_restart(app, bell, hosts, monkeypatch):
    """The clock lives in Redis: a restart (fresh module state) does not reset it."""
    host_id = _host(app, 'h1')
    hosts.set('h1', snapshot=TimeoutError('timed out'))
    _check(app)
    bell.wall[0] += 240
    monkeypatch.setattr(_backend(), '_TICKS', [0])
    _check(app)
    assert bell.take() == []
    bell.wall[0] += 120
    _check(app)
    assert [c[5] for c in bell.take()] == [f'host-metrics:{host_id}:stale:host']


def test_stale_collector_counts_from_its_last_data(app, bell, hosts):
    host_id = _host(app, 'h1')
    hosts.set('h1', snapshot=(0, _tick_snapshot(age=900), ''))
    _check(app)
    calls = bell.take()
    assert [(c[0], c[1], c[5]) for c in calls] == [
        ('notify', 'critical', f'host-metrics:{host_id}:stale:host')]
    assert '15 min' in calls[0][3]


def test_slow_host_does_not_stall_the_check(app, bell, hosts, monkeypatch):
    import threading
    import time
    _host(app, 'h-slow')
    fast_id = _host(app, 'h-fast')
    bell.redis.store[_last_key(fast_id)] = '4900'
    release = threading.Event()

    def slow():
        release.wait(5)
        return 0, _tick_snapshot(), ''
    hosts.set('h-slow', snapshot=slow)
    hosts.set('h-fast', snapshot=(0, _tick_snapshot(), ''), events=[_ev(1, 'disk_low')])
    monkeypatch.setattr(_backend(), 'NOTIFY_GATHER_SECONDS', 0.3)
    started = time.monotonic()
    try:
        _check(app)
    finally:
        release.set()
    assert time.monotonic() - started < 2
    assert [c[5] for c in bell.take()] == [f'host-metrics:{fast_id}:disk_low:host']


def test_failed_events_query_keeps_the_last_check(app, bell, hosts):
    host_id = _host(app, 'h1')
    bell.redis.store[_last_key(host_id)] = '4900'
    hosts.set('h1', snapshot=(0, _tick_snapshot(), ''))
    hosts.events['h1'] = (2, None, 'usage: hm_query.py')   # a 1.0 collector: no --since
    _check(app)
    assert bell.redis.store[_last_key(host_id)] == '4900'
    assert bell.take() == []


def test_a_failing_notify_does_not_stop_the_check(app, bell, hosts, monkeypatch):
    host_id = _host(app, 'h1')
    bell.redis.store[_last_key(host_id)] = '4900'
    hosts.set('h1', snapshot=(0, _tick_snapshot(), ''), events=[_ev(1, 'disk_low'), _ev(2, 'mem_low')])

    def notify(severity, title, body='', link=None, key=None):
        if 'disk_low' in key:
            raise RuntimeError('database is locked')
        bell.calls.append(('notify', severity, title, body, link, key))
    monkeypatch.setattr(_ctx(app), 'notify', notify, raising=False)
    _check(app)
    assert [c[5] for c in bell.take()] == [f'host-metrics:{host_id}:mem_low:host']


def test_a_core_without_notify_gets_no_check(app, hosts, monkeypatch):
    from types import SimpleNamespace
    _host(app, 'h1')
    ctx = _ctx(app)
    old_ctx = SimpleNamespace(settings=ctx.settings, logger=ctx.logger, manifest=ctx.manifest)
    monkeypatch.setattr(_backend(), 'CTX', old_ctx)
    _check(app)
    assert hosts.calls == []


def test_notify_settings_round_trip(app, client, auth):
    response = client.put(f'{API}/settings', headers=auth,
                          json=dict(SETTINGS, notify_enabled=False, notify_min_severity='critical'))
    assert response.status_code == 200, response.get_json()
    data = client.get(f'{API}/settings', headers=auth).get_json()['data']
    assert data['notify_enabled'] is False and data['notify_min_severity'] == 'critical'
