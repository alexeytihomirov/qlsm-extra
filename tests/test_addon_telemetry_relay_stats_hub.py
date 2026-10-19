"""telemetry-relay 1.9.0: the Stats Hub entries.

One instance entry, one host entry and one settings section serve telemetry
and the live demo stream together. The routes are telemetry-relay's
(`hub/...`) and drive demo-stream in-process, so both addons are installed
here; the tests at the end install telemetry-relay alone or switch
demo-stream off to check the panel degrades instead of breaking.

One save, at most one apply + restart: everything an instance save changes
goes into one `apply_stats_hub_instance` task, which runs each feature's
enable/disable without its own apply and then queues exactly one.
"""
import importlib
import itertools
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from ui import db
from ui.models import Host, HostStatus, InstanceStatus, QLInstance
from conftest import auth_headers, make_user

URL = '/api/addons/telemetry-relay/hub'
HUB = 'https://hub.example'
TOKEN = 'ingest-secret-token'
SERVER_ID = 7
PEM = '-----BEGIN CERTIFICATE-----\nAAA\n-----END CERTIFICATE-----\n'
DEMO_GET = 'qlsm_addon_demo_stream.stats_hub.requests.get'
DEMO_PUT = 'qlsm_addon_demo_stream.stats_hub.requests.put'
_NAMES = itertools.count(1)


@pytest.fixture
def addon_id():
    return ('demo-stream', 'telemetry-relay')


@pytest.fixture(autouse=True)
def in_tmp(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)


@pytest.fixture
def auth(app):
    make_user(app, 'hubop', 'pw')
    return auth_headers(app, 'hubop')


def _tele(name=None):
    return importlib.import_module('qlsm_addon_telemetry_relay' + (f'.{name}' if name else ''))


def _demo(name=None):
    return importlib.import_module('qlsm_addon_demo_stream' + (f'.{name}' if name else ''))


@pytest.fixture
def queued(monkeypatch):
    """Locks always granted, enqueue_task recorded instead of run."""
    import ui.task_lock
    import ui.tasks
    monkeypatch.setattr(ui.task_lock, 'acquire_lock', lambda *a, **k: True)
    monkeypatch.setattr(ui.task_lock, 'release_lock', lambda *a, **k: True)
    calls = []
    monkeypatch.setattr(ui.tasks, 'enqueue_task',
                        lambda task, *args, **kwargs: calls.append((task, args, kwargs)) or Mock(id='job-1'))
    return calls


def _names(calls):
    return [getattr(task, '__name__', str(task)) for task, _, _ in calls]


def _hub_delay(delay=30.0, default=30.0, override=False):
    body = {'ok': True, 'server_id': SERVER_ID, 'delay_sec': delay,
            'default_delay_sec': default, 'override': override}
    return Mock(status_code=200, json=Mock(return_value=body))


def _addon_on(app, addon, host_id=None, instance_id=None):
    from ui.addons import get_addon
    with app.app_context():
        settings = get_addon(addon).ctx.settings
        settings.set_enabled('global', 0, True)
        if host_id is not None:
            settings.set_enabled('host', host_id, True)
        if instance_id is not None:
            settings.set_enabled('instance', instance_id, True)


def _env(app, tele=False, stream=False, relay=True, tunnel=True, status=InstanceStatus.RUNNING,
         demo=True):
    """A host and an instance; both addons on globally and pointed at one
    hub. `tele` / `stream`: switched on the way their enables leave them."""
    with app.app_context():
        n = next(_NAMES)
        host = Host(name=f'hub{n}', ip_address=f'10.0.3.{n}', provider='vultr',
                    status=HostStatus.ACTIVE)
        db.session.add(host)
        db.session.flush()
        inst = QLInstance(name=f'duel {n}', port=27960, hostname='duel', host_id=host.id,
                          status=status)
        db.session.add(inst)
        db.session.commit()
        hid, iid = host.id, inst.id
        ts = _tele('settings')
        ts.set_stats_hub_url(HUB)
        ts.set_stats_hub_ingest_token(TOKEN)
        ts.set_relay_enabled(hid, relay)
        if tele:
            ts.set_instance_server_id(iid, SERVER_ID)
        if demo:
            ds = _demo('settings')
            ds.set_relay_host('relay.example')
            ds.set_relay_port('27999')
            ds.set_stats_hub_url(HUB)
            ds.set_stats_hub_ingest_token(TOKEN)
            ds.set_host_tunnel_enabled(hid, tunnel)
            if stream:
                ds.set_instance_server_id(iid, SERVER_ID)
                ds.set_instance_demo_stream_token(iid, 'stream-token')
                ds.set_instance_demo_stream_enabled(iid, True)
                ds.set_instance_stream_port(iid, '27999')
        db.session.commit()
        cfg = Path('configs') / host.name / str(iid) / 'server.cfg'
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text('set sv_hostname "duel"\n', encoding='utf-8')
    _addon_on(app, 'telemetry-relay', hid if tele else None, iid if tele else None)
    if demo:
        _addon_on(app, 'demo-stream', hid if stream else None, iid if stream else None)
    return hid, iid


def _status(app, iid):
    with app.app_context():
        return db.session.get(QLInstance, iid).status


# ---- instance entry: GET --------------------------------------------------

def test_get_instance_shows_both_features(app, client, auth):
    _, both = _env(app, tele=True, stream=True)
    _, none = _env(app)
    with patch(DEMO_GET, return_value=_hub_delay(delay=5.0, override=True)):
        on = client.get(f'{URL}/instances/{both}', headers=auth).get_json()['data']
    assert on == {'enabled': True, 'new_server_id': False, 'stream': True, 'delay_sec': '5'}
    with patch(DEMO_GET) as get:
        off = client.get(f'{URL}/instances/{none}', headers=auth).get_json()['data']
    assert off == {'enabled': False, 'new_server_id': False, 'stream': False, 'delay_sec': ''}
    get.assert_not_called()


# ---- instance entry: PUT, one task and one restart --------------------------

def test_put_both_on_queues_one_task(app, client, auth, queued):
    _, iid = _env(app)
    resp = client.put(f'{URL}/instances/{iid}', headers=auth, json={
        'enabled': True, 'new_server_id': False, 'stream': True, 'delay_sec': '5'})
    assert resp.status_code == 202, resp.get_json()
    assert _names(queued) == ['apply_stats_hub_instance']
    (_task, args, kwargs), = queued
    assert args == (iid,)
    assert (kwargs['telemetry'], kwargs['stream'], kwargs['delay_sec']) == ('enable', 'enable', 5.0)
    assert kwargs['new_server_id'] is False and kwargs['previous_status'] == 'running'
    assert _status(app, iid) == InstanceStatus.CONFIGURING


def test_put_both_off_queues_one_task(app, client, auth, queued):
    _, iid = _env(app, tele=True, stream=True)
    resp = client.put(f'{URL}/instances/{iid}', headers=auth, json={
        'enabled': False, 'new_server_id': False, 'stream': False, 'delay_sec': ''})
    assert resp.status_code == 202, resp.get_json()
    (_task, _args, kwargs), = queued
    assert (kwargs['telemetry'], kwargs['stream'], kwargs['delay_sec']) == ('disable', 'disable', None)


def test_put_stream_only_leaves_telemetry_alone(app, client, auth, queued):
    _, iid = _env(app)
    resp = client.put(f'{URL}/instances/{iid}', headers=auth, json={
        'enabled': False, 'new_server_id': False, 'stream': True, 'delay_sec': ''})
    assert resp.status_code == 202, resp.get_json()
    (_task, _args, kwargs), = queued
    assert (kwargs['telemetry'], kwargs['stream']) == (None, 'enable')


def test_put_delay_only_is_one_hub_call_no_task(app, client, auth, queued):
    _, iid = _env(app, tele=True, stream=True)
    with patch(DEMO_GET, return_value=_hub_delay()), \
            patch(DEMO_PUT, return_value=_hub_delay(delay=5.0, override=True)) as put:
        resp = client.put(f'{URL}/instances/{iid}', headers=auth, json={
            'enabled': True, 'new_server_id': False, 'stream': True, 'delay_sec': '5'})
    assert resp.status_code == 200, resp.get_json()
    assert put.call_args.kwargs['json'] == {'delay_sec': 5.0}
    assert queued == []


def test_put_delay_with_telemetry_change_sets_delay_then_queues(app, client, auth, queued):
    _, iid = _env(app, stream=True)
    with patch(DEMO_GET, return_value=_hub_delay()), \
            patch(DEMO_PUT, return_value=_hub_delay(delay=5.0, override=True)) as put:
        resp = client.put(f'{URL}/instances/{iid}', headers=auth, json={
            'enabled': True, 'new_server_id': False, 'stream': True, 'delay_sec': '5'})
    assert resp.status_code == 202, resp.get_json()
    put.assert_called_once()
    (_task, _args, kwargs), = queued
    assert (kwargs['telemetry'], kwargs['stream']) == ('enable', None)


def test_put_no_change(app, client, auth, queued):
    _, iid = _env(app, tele=True, stream=True)
    with patch(DEMO_GET, return_value=_hub_delay()), patch(DEMO_PUT) as put:
        resp = client.put(f'{URL}/instances/{iid}', headers=auth, json={
            'enabled': True, 'new_server_id': False, 'stream': True, 'delay_sec': ''})
    assert resp.status_code == 200 and resp.get_json()['message'] == 'No changes.'
    assert queued == []
    put.assert_not_called()


def test_put_new_server_id_takes_the_stream_along(app, client, auth, queued):
    _, iid = _env(app, tele=True, stream=True)
    with patch(DEMO_GET, return_value=_hub_delay()):
        resp = client.put(f'{URL}/instances/{iid}', headers=auth, json={
            'enabled': True, 'new_server_id': True, 'stream': True, 'delay_sec': ''})
    assert resp.status_code == 202, resp.get_json()
    (_task, _args, kwargs), = queued
    assert (kwargs['telemetry'], kwargs['new_server_id'], kwargs['stream']) == ('enable', True, 'enable')


def test_put_refused_stream_queues_nothing(app, client, auth, queued):
    _, iid = _env(app, tunnel=False)
    resp = client.put(f'{URL}/instances/{iid}', headers=auth, json={
        'enabled': True, 'new_server_id': False, 'stream': True, 'delay_sec': ''})
    assert resp.status_code == 400
    assert 'Stats Hub' in resp.get_json()['error']['message']
    assert queued == []


@pytest.mark.parametrize('body', [
    {'enabled': True, 'stream': 'yes'},
    {'enabled': 'true', 'stream': True},
    {'enabled': True, 'stream': True, 'delay_sec': '999'},
])
def test_put_bad_values_400(app, client, auth, queued, body):
    _, iid = _env(app)
    resp = client.put(f'{URL}/instances/{iid}', headers=auth, json=body)
    assert resp.status_code == 400
    assert queued == []


# ---- the task: telemetry, stream, one apply ---------------------------------

@pytest.fixture
def hub_calls(monkeypatch):
    """Telemetry reserves 41; the stream registers its route and sets the delay."""
    calls = {'routes': [], 'delays': [], 'pushes': []}
    monkeypatch.setattr(_tele('instance_ops'), 'reserve_server_id', lambda label, host_id: 41)
    monkeypatch.setattr(_tele('instance_ops'), 'push_relay_config_logic',
                        lambda host_id: calls['pushes'].append(host_id) or True)
    monkeypatch.setattr(_demo('instance_ops'), '_register_route',
                        lambda host_id, server_id, name, token: calls['routes'].append(server_id))

    def set_delay(host_id, server_id, delay_sec):
        calls['delays'].append((server_id, delay_sec))
        return {'delay_sec': delay_sec, 'default_delay_sec': 30.0, 'override': True}
    monkeypatch.setattr(_demo('instance_ops'), 'set_server_delay', set_delay)
    return calls


def test_task_enables_both_with_one_apply(app, queued, hub_calls):
    _, iid = _env(app, status=InstanceStatus.CONFIGURING)
    with app.app_context():
        ok, message = _tele('hub_ui').apply_instance_logic(
            iid, previous_status='running', telemetry='enable', stream='enable', delay_sec=5.0)
        assert ok, message
        assert _tele('settings').get_instance_server_id(iid) == 41
        assert _demo('settings').get_instance_server_id(iid) == 41
        assert _demo('settings').is_instance_demo_stream_enabled(iid)
        logs = db.session.get(QLInstance, iid).logs
    assert _names(queued) == ['apply_instance_config']
    assert queued[0][2]['restart'] is True
    assert hub_calls['routes'] == [41] and hub_calls['delays'] == [(41, 5.0)]
    assert 'Telemetry enabled, server_id=41.' in logs
    assert 'Live demo stream enabled, server_id=41.' in logs
    assert 'restarting once' in logs


def test_task_disables_both_with_one_apply(app, queued, hub_calls):
    _, iid = _env(app, tele=True, stream=True, status=InstanceStatus.CONFIGURING)
    with app.app_context():
        ok, _ = _tele('hub_ui').apply_instance_logic(
            iid, previous_status='running', telemetry='disable', stream='disable')
        assert ok
        assert not _demo('settings').is_instance_demo_stream_enabled(iid)
        assert _tele('settings').get_reserved_server_id(iid) == SERVER_ID
    assert _names(queued) == ['apply_instance_config']


def test_task_new_server_id_moves_the_stream_too(app, queued, hub_calls):
    _, iid = _env(app, tele=True, stream=True, status=InstanceStatus.CONFIGURING)
    with app.app_context():
        ok, _ = _tele('hub_ui').apply_instance_logic(
            iid, previous_status='running', telemetry='enable', new_server_id=True, stream='enable')
        assert ok
        assert _tele('settings').get_instance_server_id(iid) == 41
        assert _demo('settings').get_instance_server_id(iid) == 41
    assert hub_calls['routes'] == [41]
    assert _names(queued) == ['apply_instance_config']


def test_task_with_nothing_done_restores_the_status(app, queued, hub_calls, monkeypatch):
    _, iid = _env(app, relay=False, tunnel=False, status=InstanceStatus.CONFIGURING)
    with app.app_context():
        ok, _ = _tele('hub_ui').apply_instance_logic(
            iid, previous_status='running', telemetry='enable', stream='enable')
    assert not ok
    assert queued == []
    assert _status(app, iid) == InstanceStatus.RUNNING


# ---- instance entry: statuses ---------------------------------------------

@pytest.mark.parametrize('tele, stream, label', [
    (False, False, 'Off'), (True, False, 'On'), (False, True, 'On'), (True, True, 'On')])
def test_instance_menu_status_is_on_off(app, client, auth, tele, stream, label):
    _, iid = _env(app, tele=tele, stream=stream)
    with patch(DEMO_GET) as get:
        data = client.get(f'{URL}/instances/{iid}/menu-status', headers=auth).get_json()['data']
    assert data == {'ok': label == 'On', 'label': label}
    get.assert_not_called()


def test_instance_panel_status_names_both(app, client, auth):
    _, iid = _env(app, tele=True, stream=True)
    with patch(DEMO_GET, return_value=_hub_delay()):
        data = client.get(f'{URL}/instances/{iid}/status', headers=auth).get_json()['data']
    assert data['ok'] is True
    assert data['label'].startswith(f'Telemetry: Server ID {SERVER_ID}, relay on. Live demo stream: Streaming')


# ---- host entry ------------------------------------------------------------

def test_host_menu_status(app, client, auth):
    off_host, _ = _env(app, relay=False)
    no_stream_host, _ = _env(app, tunnel=False)
    stream_no_tunnel, _ = _env(app, stream=True, tunnel=False)
    full, _ = _env(app, stream=True)

    def label(hid):
        return client.get(f'{URL}/hosts/{hid}/menu-status', headers=auth).get_json()['data']['label']
    assert [label(h) for h in (off_host, no_stream_host, stream_no_tunnel, full)] == \
        ['Off', 'On', 'Off', 'On']


def test_get_host_never_returns_the_token(app, client, auth):
    hid, _ = _env(app)
    with app.app_context():
        _tele('settings').set_host_stats_hub_ingest_token(hid, 'host-secret')
        db.session.commit()
    data = client.get(f'{URL}/hosts/{hid}', headers=auth).get_json()['data']
    assert data['ingest_token_override'] == ''
    assert data['enabled'] is True and data['tunnel_enabled'] is True
    assert 'host-secret' not in str(data)


@pytest.fixture
def host_calls(monkeypatch):
    calls = {'allow': 0, 'push': 0}
    monkeypatch.setattr(_tele('settings'), 'allow_host',
                        lambda host: calls.__setitem__('allow', calls['allow'] + 1))
    monkeypatch.setattr(_tele('relay_ops'), 'push_relay_config_logic',
                        lambda host_id: calls.__setitem__('push', calls['push'] + 1) or True)
    monkeypatch.setattr(_demo('tunnel_ops'), 'fetch_hub_tls_cert', lambda host_id: PEM)
    return calls


def _host_body(**over):
    body = {'enabled': True, 'url_override': '', 'ingest_token_override': '', 'forward_url': '',
            'tunnel_enabled': True, 'local_port': '', 'relay_host': '', 'relay_port': ''}
    body.update(over)
    return body


def test_put_host_relay_and_tunnel_in_one_task(app, client, auth, queued, host_calls):
    hid, _ = _env(app, relay=False, tunnel=False)
    resp = client.put(f'{URL}/hosts/{hid}', headers=auth, json=_host_body())
    assert resp.status_code == 202, resp.get_json()
    assert _names(queued) == ['configure_stats_hub_host']
    (_task, args, kwargs), = queued
    assert args == (hid,)
    assert kwargs['relay'] is True and kwargs['tunnel'] == (True, '27999', PEM)
    assert host_calls['allow'] == 1
    with app.app_context():
        assert db.session.get(Host, hid).status == HostStatus.CONFIGURING


def test_put_host_unchanged_relay_pushes_and_queues_only_the_tunnel(app, client, auth, queued,
                                                                     host_calls):
    hid, _ = _env(app)
    resp = client.put(f'{URL}/hosts/{hid}', headers=auth, json=_host_body())
    assert resp.status_code == 202, resp.get_json()
    (_task, _args, kwargs), = queued
    assert kwargs['relay'] is None and kwargs['tunnel'][0] is True
    assert host_calls['push'] == 1 and host_calls['allow'] == 1


def test_put_host_override_is_stored_for_both_addons(app, client, auth, queued, host_calls):
    hid, _ = _env(app, tunnel=False)
    resp = client.put(f'{URL}/hosts/{hid}', headers=auth, json=_host_body(
        url_override='https://other.example/', ingest_token_override='host-tok',
        tunnel_enabled=False))
    assert resp.status_code == 200, resp.get_json()
    with app.app_context():
        ts, dh = _tele('settings'), _demo('stats_hub')
        assert ts.get_host_stats_hub_url(hid) == dh.get_host_stats_hub_url(hid) == 'https://other.example'
        assert ts.get_host_stats_hub_ingest_token(hid) == dh.get_host_stats_hub_ingest_token(hid) == 'host-tok'
    # blank keeps the token; clearing the URL clears both
    client.put(f'{URL}/hosts/{hid}', headers=auth, json=_host_body(
        url_override='https://other.example', tunnel_enabled=False))
    with app.app_context():
        assert _demo('stats_hub').get_host_stats_hub_ingest_token(hid) == 'host-tok'
    client.put(f'{URL}/hosts/{hid}', headers=auth, json=_host_body(tunnel_enabled=False))
    with app.app_context():
        assert _tele('settings').get_host_stats_hub_ingest_token(hid) is None
        assert _demo('stats_hub').get_host_stats_hub_url(hid) is None


def test_put_host_bad_tunnel_port_stores_nothing(app, client, auth, queued, host_calls):
    hid, _ = _env(app)
    resp = client.put(f'{URL}/hosts/{hid}', headers=auth, json=_host_body(
        local_port='80', url_override='https://other.example'))
    assert resp.status_code == 400
    assert queued == []
    with app.app_context():
        assert _tele('settings').get_host_stats_hub_url(hid) is None


def test_host_task_runs_both_and_marks_a_failure(app, monkeypatch):
    hid, _ = _env(app, relay=False, tunnel=False)
    order = []
    monkeypatch.setattr(_tele('relay_ops'), 'configure_host_telemetry_relay_logic',
                        lambda host_id, enabled: order.append(('relay', enabled)) or False)
    monkeypatch.setattr(_demo('tunnel_ops'), 'configure_host_demo_stream_tunnel_logic',
                        lambda host_id, enabled, port, pem: order.append(('tunnel', enabled)) or True)
    with app.app_context():
        ok = _tele('hub_ui').configure_host_logic(hid, relay=True, tunnel=(True, '27999', PEM))
        assert ok is False
        assert db.session.get(Host, hid).status == HostStatus.ERROR
    assert order == [('relay', True), ('tunnel', True)]


# ---- settings section --------------------------------------------------------

def test_settings_get_hides_the_token(app, client, auth):
    _env(app)
    data = client.get(f'{URL}/settings', headers=auth).get_json()['data']
    assert data == {'url': HUB, 'ingest_token': '', 'auto_enable_new_instances': False,
                    'relay_host': 'relay.example', 'relay_port': '27999'}


def test_settings_put_writes_both_addons(app, client, auth):
    _env(app)
    with app.app_context():
        _demo('settings').set_stats_hub_url('https://old.example')
        db.session.commit()
    before = client.get(f'{URL}/settings/status', headers=auth).get_json()['data']
    assert before['ok'] is False and 'https://old.example' in before['label']

    resp = client.put(f'{URL}/settings', headers=auth, json={
        'url': 'https://new.example/', 'ingest_token': 'new-tok', 'auto_enable_new_instances': True,
        'relay_host': 'relay2.example', 'relay_port': '443'})
    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json()['data']['ingest_token'] == ''
    with app.app_context():
        ts, ds = _tele('settings'), _demo('settings')
        assert ts.get_stats_hub_url() == ds.get_stats_hub_url() == 'https://new.example'
        assert ts.get_stats_hub_ingest_token() == ds.get_stats_hub_ingest_token() == 'new-tok'
        assert (ds.get_relay_host(), ds.get_relay_port()) == ('relay2.example', '443')
        assert ts.is_auto_enable_new_instances()

    # A blank token keeps the stored one in both.
    client.put(f'{URL}/settings', headers=auth, json={
        'url': 'https://new.example', 'ingest_token': '', 'relay_host': 'relay2.example',
        'relay_port': '443'})
    with app.app_context():
        assert _demo('settings').get_stats_hub_ingest_token() == 'new-tok'
    after = client.get(f'{URL}/settings/status', headers=auth).get_json()['data']
    assert after == {'ok': True, 'label': 'Telemetry and live demo stream use https://new.example'}
    assert 'new-tok' not in str(after)


def test_settings_put_bad_relay_port_400(app, client, auth):
    _env(app)
    resp = client.put(f'{URL}/settings', headers=auth, json={
        'url': HUB, 'ingest_token': '', 'relay_host': 'relay.example', 'relay_port': 'x'})
    assert resp.status_code == 400


def test_hub_routes_need_a_login(app, client):
    hid, iid = _env(app)
    for path in (f'instances/{iid}', f'instances/{iid}/status', f'instances/{iid}/menu-status',
                 f'hosts/{hid}', f'hosts/{hid}/menu-status', 'settings', 'settings/status'):
        assert client.get(f'{URL}/{path}').status_code == 401, path


# ---- demo-stream missing or off: the telemetry half still works -------------

class TestWithoutDemoStream:
    @pytest.fixture
    def addon_id(self):
        return 'telemetry-relay'

    def test_get_and_status_degrade(self, app, client, auth):
        hid, iid = _env(app, tele=True, demo=False)
        data = client.get(f'{URL}/instances/{iid}', headers=auth).get_json()['data']
        assert data == {'enabled': True, 'new_server_id': False, 'stream': False, 'delay_sec': ''}
        status = client.get(f'{URL}/instances/{iid}/status', headers=auth).get_json()['data']
        assert 'not installed' in status['label'] and status['ok'] is True
        menu = client.get(f'{URL}/instances/{iid}/menu-status', headers=auth).get_json()['data']
        assert menu['label'] == 'On'
        assert client.get(f'{URL}/hosts/{hid}/menu-status', headers=auth).get_json()['data']['label'] == 'On'
        assert client.get(f'{URL}/hosts/{hid}', headers=auth).get_json()['data']['tunnel_enabled'] is False
        assert client.get(f'{URL}/settings', headers=auth).status_code == 200
        settings_status = client.get(f'{URL}/settings/status', headers=auth).get_json()['data']
        assert 'not installed' in settings_status['label']

    def test_put_telemetry_only_and_refuse_the_stream(self, app, client, auth, queued):
        _, iid = _env(app, demo=False)
        refused = client.put(f'{URL}/instances/{iid}', headers=auth, json={
            'enabled': True, 'new_server_id': False, 'stream': True, 'delay_sec': ''})
        assert refused.status_code == 409
        assert 'not installed' in refused.get_json()['error']['message']
        assert queued == []
        resp = client.put(f'{URL}/instances/{iid}', headers=auth, json={
            'enabled': True, 'new_server_id': False, 'stream': False, 'delay_sec': '5'})
        assert resp.status_code == 202, resp.get_json()
        (_task, _args, kwargs), = queued
        assert (kwargs['telemetry'], kwargs['stream']) == ('enable', None)

    def test_settings_put_saves_telemetry(self, app, client, auth):
        _env(app, demo=False)
        resp = client.put(f'{URL}/settings', headers=auth, json={
            'url': 'https://new.example', 'ingest_token': 'tok2', 'relay_host': '', 'relay_port': ''})
        assert resp.status_code == 200
        with app.app_context():
            assert _tele('settings').get_stats_hub_url() == 'https://new.example'


def test_demo_stream_switched_off_degrades(app, client, auth, queued):
    _, iid = _env(app)
    from ui.addons import get_addon
    with app.app_context():
        get_addon('demo-stream').ctx.settings.set_enabled('global', 0, False)
    status = client.get(f'{URL}/instances/{iid}/status', headers=auth).get_json()['data']
    assert 'switched off on the Addons page' in status['label']
    resp = client.put(f'{URL}/instances/{iid}', headers=auth, json={
        'enabled': False, 'new_server_id': False, 'stream': True, 'delay_sec': ''})
    assert resp.status_code == 409
    assert queued == []
