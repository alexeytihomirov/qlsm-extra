"""demo-stream addon 1.5.0: one Live Demo Stream instance panel (stream switch
and delay), a working switch-off, one settings section.

The generic form panel submits the whole form, so `PUT instances/{id}` always
carries both fields; what it does depends on what changed against the current
state (the enabled flag stored here, the delay as the hub reports it).
"""
import importlib
import itertools
import json
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from ui import db
from ui.models import Host, HostStatus, InstanceStatus, QLInstance
from conftest import ADDONS_DIR, auth_headers, make_user

URL = '/api/addons/demo-stream'
HUB = 'https://stats.example'
TOKEN = 'ingest-secret-token'
SERVER_ID = 7
_NAMES = itertools.count(1)
GET = 'qlsm_addon_demo_stream.stats_hub.requests.get'
PUT = 'qlsm_addon_demo_stream.stats_hub.requests.put'


@pytest.fixture
def addon_id():
    return 'demo-stream'


@pytest.fixture
def auth(app):
    make_user(app, 'demoop', 'pw')
    return auth_headers(app, 'demoop')


def _make_instance(app, status=InstanceStatus.RUNNING):
    with app.app_context():
        n = next(_NAMES)
        host = Host(name=f'germany{n}', ip_address=f'10.0.0.{n}', provider='vultr',
                    status=HostStatus.ACTIVE)
        db.session.add(host)
        db.session.flush()
        instance = QLInstance(name=f'duel srv {n}', port=27960, hostname='duel', host_id=host.id,
                              status=status)
        db.session.add(instance)
        db.session.commit()
        return instance.id


def _configure(app, instance_id, enabled):
    """Relay, hub and host tunnel set up; the instance has a server_id and a
    token from an earlier enable; `enabled` is whether it streams now."""
    with app.app_context():
        from qlsm_addon_demo_stream.settings import (
            set_host_tunnel_enabled, set_instance_demo_stream_enabled,
            set_instance_demo_stream_token, set_instance_server_id, set_relay_host,
            set_relay_port, set_stats_hub_ingest_token, set_stats_hub_url)
        set_relay_host('stats.example')
        set_relay_port('27999')
        set_stats_hub_url(HUB)
        set_stats_hub_ingest_token(TOKEN)
        host_id = db.session.get(QLInstance, instance_id).host_id
        set_host_tunnel_enabled(host_id, True)
        set_instance_server_id(instance_id, SERVER_ID)
        set_instance_demo_stream_token(instance_id, 'stream-token')
        set_instance_demo_stream_enabled(instance_id, enabled)
        db.session.commit()
    return instance_id


WIRED = ('set sv_hostname "duel"\nset sv_demoStream "1"\nset sv_demoStreamHost "127.0.0.1"\n'
         'set sv_demoStreamPort "27999"\nset sv_demoStreamToken "stream-token"\n')


def _cfg(app, instance_id):
    with app.app_context():
        instance = db.session.get(QLInstance, instance_id)
        return Path('configs') / instance.host.name / str(instance_id) / 'server.cfg'


@pytest.fixture
def streaming(app, tmp_path, monkeypatch):
    """Streaming with server.cfg wired the way the enable writes it."""
    monkeypatch.chdir(tmp_path)
    iid = _configure(app, _make_instance(app), enabled=True)
    cfg = _cfg(app, iid)
    cfg.parent.mkdir(parents=True)
    cfg.write_text(WIRED, encoding='utf-8')
    return iid


@pytest.fixture
def off(app):
    return _configure(app, _make_instance(app), enabled=False)


@pytest.fixture
def queued(monkeypatch):
    """Locks always granted, enqueue_task recorded instead of run."""
    import ui.task_lock
    import ui.tasks
    monkeypatch.setattr(ui.task_lock, 'acquire_lock', lambda *a, **k: True)
    calls = []
    monkeypatch.setattr(ui.tasks, 'enqueue_task',
                        lambda task, *args, **kwargs: calls.append((task, args, kwargs)) or Mock(id='job-1'))
    return calls


def _hub(delay=30.0, default=30.0, override=False):
    body = {'ok': True, 'server_id': SERVER_ID, 'delay_sec': delay,
            'default_delay_sec': default, 'override': override}
    return Mock(status_code=200, json=Mock(return_value=body))


def _tasks():
    # backend.py is loaded as the addon package module itself
    return importlib.import_module('qlsm_addon_demo_stream').TASKS


def _message(resp):
    body = resp.get_json()
    return body['error']['message'] if 'error' in body else body['message']


def _status(app, instance_id):
    with app.app_context():
        return db.session.get(QLInstance, instance_id).status


# ---- GET instances/{id} ---------------------------------------------------

def test_get_returns_enabled_and_delay(client, auth, streaming, off):
    with patch(GET, return_value=_hub(delay=5.0, override=True)):
        on = client.get(f'{URL}/instances/{streaming}', headers=auth).get_json()['data']
    assert on == {'enabled': True, 'delay_sec': '5'}
    with patch(GET) as get:
        stopped = client.get(f'{URL}/instances/{off}', headers=auth).get_json()['data']
    assert stopped == {'enabled': False, 'delay_sec': ''}
    get.assert_not_called()


# ---- PUT instances/{id}: one test per spec table row ------------------------

def test_put_delay_only_calls_hub_no_task(client, auth, streaming, queued):
    with patch(GET, return_value=_hub()), \
            patch(PUT, return_value=_hub(delay=5.0, override=True)) as put:
        resp = client.put(f'{URL}/instances/{streaming}',
                          json={'enabled': True, 'delay_sec': '5'}, headers=auth)
    assert resp.status_code == 200, resp.get_json()
    assert put.call_args.kwargs['json'] == {'delay_sec': 5.0}
    assert queued == []
    assert 'Stream delay set to 5 s' in _message(resp)


def test_put_enable_queues_task_with_delay(app, client, auth, off, queued):
    with patch(GET) as get, patch(PUT) as put:
        resp = client.put(f'{URL}/instances/{off}',
                          json={'enabled': True, 'delay_sec': '5'}, headers=auth)
    assert resp.status_code == 202, resp.get_json()
    (task, args, kwargs), = queued
    assert task is _tasks()['enable_instance_demo_stream']
    assert args == (off,)
    assert kwargs['delay_sec'] == 5.0 and kwargs['previous_status'] == 'running'
    assert _status(app, off) == InstanceStatus.CONFIGURING
    get.assert_not_called()
    put.assert_not_called()


def test_put_enable_with_blank_delay_passes_none(client, auth, off, queued):
    resp = client.put(f'{URL}/instances/{off}',
                      json={'enabled': True, 'delay_sec': ''}, headers=auth)
    assert resp.status_code == 202
    assert queued[0][2]['delay_sec'] is None


def _enable_ops(monkeypatch, tmp_path, order):
    ops = importlib.import_module('qlsm_addon_demo_stream.instance_ops')
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(ops, 'is_relay_configured', lambda: True)
    monkeypatch.setattr(ops, 'is_stats_hub_configured_for_host', lambda host_id: True)
    monkeypatch.setattr(ops, 'is_host_tunnel_enabled', lambda host_id: True)
    monkeypatch.setattr(ops, '_resolve_server_id', lambda instance, host_id: SERVER_ID)
    monkeypatch.setattr(ops, '_register_route', lambda *a: order.append('route'))
    import ui.tasks
    monkeypatch.setattr(ui.tasks, 'enqueue_task',
                        lambda task, *a, **k: order.append('apply') or Mock(id='job-1'))
    return ops


def test_enable_task_sets_delay_last(app, monkeypatch, tmp_path):
    order = []
    ops = _enable_ops(monkeypatch, tmp_path, order)

    def set_delay(host_id, server_id, delay_sec):
        order.append(('delay', server_id, delay_sec))
        return {'delay_sec': delay_sec, 'default_delay_sec': 30.0, 'override': True}
    monkeypatch.setattr(ops, 'set_server_delay', set_delay)
    iid = _make_instance(app, InstanceStatus.CONFIGURING)
    with app.app_context():
        ok, message = ops.enable_instance_demo_stream_logic(
            iid, previous_status='running', delay_sec=5.0)
    assert ok is True
    assert order == ['route', 'apply', ('delay', SERVER_ID, 5.0)]
    assert 'Stream delay set to 5 s' in message


def test_enable_task_without_delay_leaves_the_hub_alone(app, monkeypatch, tmp_path):
    order = []
    ops = _enable_ops(monkeypatch, tmp_path, order)
    monkeypatch.setattr(ops, 'set_server_delay', lambda *a: order.append('delay'))
    iid = _make_instance(app, InstanceStatus.CONFIGURING)
    with app.app_context():
        ok, _ = ops.enable_instance_demo_stream_logic(iid, previous_status='running')
    assert ok is True and order == ['route', 'apply']


def test_enable_task_delay_failure_does_not_fail_the_enable(app, monkeypatch, tmp_path):
    order = []
    ops = _enable_ops(monkeypatch, tmp_path, order)
    from qlsm_addon_demo_stream.stats_hub import HubDelayError

    def down(*a):
        raise HubDelayError('Could not reach stats-hub (ConnectionError).', 502, 'x')
    monkeypatch.setattr(ops, 'set_server_delay', down)
    iid = _make_instance(app, InstanceStatus.CONFIGURING)
    with app.app_context():
        ok, message = ops.enable_instance_demo_stream_logic(
            iid, previous_status='running', delay_sec=5.0)
        enabled = importlib.import_module(
            'qlsm_addon_demo_stream.settings').is_instance_demo_stream_enabled(iid)
    assert ok is True and enabled is True
    assert 'Live demo stream enabled' in message
    assert 'delay was not set' in message and 'Could not reach stats-hub' in message


def test_put_disable_queues_disable_task(app, client, auth, streaming, queued):
    with patch(GET) as get, patch(PUT) as put:
        resp = client.put(f'{URL}/instances/{streaming}',
                          json={'enabled': False, 'delay_sec': '5'}, headers=auth)
    assert resp.status_code == 202, resp.get_json()
    (task, args, kwargs), = queued
    assert task is _tasks()['disable_instance_demo_stream']
    assert args == (streaming,) and kwargs['previous_status'] == 'running'
    assert _status(app, streaming) == InstanceStatus.CONFIGURING
    get.assert_not_called()
    put.assert_not_called()


def test_disable_logic_writes_sv_demoStream_0_and_restarts(app, streaming, monkeypatch, tmp_path):
    ops = importlib.import_module('qlsm_addon_demo_stream.instance_ops')
    settings = importlib.import_module('qlsm_addon_demo_stream.settings')
    monkeypatch.chdir(tmp_path)
    with app.app_context():
        instance = db.session.get(QLInstance, streaming)
        instance.status = InstanceStatus.CONFIGURING
        db.session.commit()
        cfg = tmp_path / 'configs' / instance.host.name / str(streaming) / 'server.cfg'
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text('set sv_hostname "duel"\nset sv_demoStream "1"\n'
                   'set sv_demoStreamHost "127.0.0.1"\nset sv_demoStreamToken "stream-token"\n',
                   encoding='utf-8')
    import ui.tasks
    applied = []
    monkeypatch.setattr(ui.tasks, 'enqueue_task',
                        lambda task, *a, **k: applied.append((task, a, k)) or Mock(id='job-9'))
    with app.app_context():
        ok, message = ops.disable_instance_demo_stream_logic(streaming, previous_status='running')
        assert settings.is_instance_demo_stream_enabled(streaming) is False
        assert settings.get_instance_demo_stream_token(streaming) == 'stream-token'
        assert settings.get_instance_server_id(streaming) == SERVER_ID
    assert ok is True and 'job-9' in message
    text = cfg.read_text(encoding='utf-8')
    assert 'set sv_demoStream "0"' in text
    assert 'set sv_demoStreamToken "stream-token"' in text
    assert 'set sv_hostname "duel"' in text
    (task, args, kwargs), = applied
    assert task is ui.tasks.apply_instance_config
    assert args == (streaming,) and kwargs['restart'] is True


@pytest.mark.parametrize('state, body, hub', [
    ('streaming', {'enabled': True, 'delay_sec': ''}, _hub()),
    ('streaming', {'enabled': True, 'delay_sec': '5'}, _hub(delay=5.0, override=True)),
    ('streaming', {'enabled': True, 'delay_sec': ' 5.0 '}, _hub(delay=5.0, override=True)),
    ('off', {'enabled': False, 'delay_sec': ''}, None),
])
def test_put_no_change_200(request, client, auth, queued, state, body, hub):
    iid = request.getfixturevalue(state)
    with patch(GET, return_value=hub), patch(PUT) as put:
        resp = client.put(f'{URL}/instances/{iid}', json=body, headers=auth)
    assert resp.status_code == 200, resp.get_json()
    assert _message(resp) == 'No changes.'
    put.assert_not_called()
    assert queued == []


@pytest.mark.parametrize('drift', [
    'no token', 'port', 'host', 'sv_demoStream 0', 'no server.cfg',
])
def test_put_save_repairs_drifted_wiring(app, client, auth, streaming, queued, drift):
    cfg = _cfg(app, streaming)
    if drift == 'no token':
        with app.app_context():
            from qlsm_addon_demo_stream.settings import set_instance_demo_stream_token
            set_instance_demo_stream_token(streaming, None)
            db.session.commit()
    elif drift == 'port':
        cfg.write_text(WIRED.replace('"27999"', '"28001"'), encoding='utf-8')
    elif drift == 'host':
        cfg.write_text(WIRED.replace('"127.0.0.1"', '"10.0.0.5"'), encoding='utf-8')
    elif drift == 'sv_demoStream 0':
        cfg.write_text(WIRED.replace('sv_demoStream "1"', 'sv_demoStream "0"'), encoding='utf-8')
    else:
        cfg.unlink()
    with patch(GET) as get, patch(PUT) as put:
        resp = client.put(f'{URL}/instances/{streaming}',
                          json={'enabled': True, 'delay_sec': ''}, headers=auth)
    assert resp.status_code == 202, resp.get_json()
    (task, args, kwargs), = queued
    assert task is _tasks()['enable_instance_demo_stream']
    assert args == (streaming,) and kwargs['delay_sec'] is None
    get.assert_not_called()
    put.assert_not_called()


def test_put_repair_follows_the_host_tunnel_port(app, client, auth, streaming, queued):
    with app.app_context():
        from qlsm_addon_demo_stream.settings import set_host_tunnel_port
        set_host_tunnel_port(db.session.get(QLInstance, streaming).host_id, '28001')
        db.session.commit()
    resp = client.put(f'{URL}/instances/{streaming}',
                      json={'enabled': True, 'delay_sec': '5'}, headers=auth)
    assert resp.status_code == 202
    assert queued[0][0] is _tasks()['enable_instance_demo_stream']
    assert queued[0][2]['delay_sec'] == 5.0


def test_put_save_repairs_a_route_the_hub_lost(client, auth, streaming, queued):
    lost = Mock(status_code=404, json=Mock(return_value={'detail': 'unknown server_id'}))
    with patch(GET, return_value=lost) as get, patch(PUT) as put:
        resp = client.put(f'{URL}/instances/{streaming}',
                          json={'enabled': True, 'delay_sec': ''}, headers=auth)
    assert resp.status_code == 202, resp.get_json()
    assert queued[0][0] is _tasks()['enable_instance_demo_stream']
    assert get.call_count == 1
    put.assert_not_called()


def test_put_consistent_streaming_instance_queues_nothing(client, auth, streaming, queued):
    with patch(GET, return_value=_hub(delay=12.5, override=True)), patch(PUT) as put:
        resp = client.put(f'{URL}/instances/{streaming}',
                          json={'enabled': True, 'delay_sec': '12.5'}, headers=auth)
    assert resp.status_code == 200 and _message(resp) == 'No changes.'
    assert queued == []
    put.assert_not_called()


def test_put_delay_within_tolerance_is_no_change(client, auth, streaming, queued):
    with patch(GET, return_value=_hub(delay=5.0000001, override=True)), patch(PUT) as put:
        resp = client.put(f'{URL}/instances/{streaming}',
                          json={'enabled': True, 'delay_sec': '5'}, headers=auth)
    assert resp.status_code == 200 and _message(resp) == 'No changes.'
    put.assert_not_called()


@pytest.mark.parametrize('bad', ['true', 1, 0, None, 'yes', [True]])
def test_put_enabled_must_be_a_bool(client, auth, streaming, queued, bad):
    with patch(GET) as get, patch(PUT) as put:
        resp = client.put(f'{URL}/instances/{streaming}',
                          json={'enabled': bad, 'delay_sec': ''}, headers=auth)
    assert resp.status_code == 400
    assert _message(resp) == 'enabled must be true or false.'
    assert queued == []
    get.assert_not_called()
    put.assert_not_called()


def test_put_delay_while_off_409(client, auth, off, queued):
    with patch(GET) as get, patch(PUT) as put:
        resp = client.put(f'{URL}/instances/{off}',
                          json={'enabled': False, 'delay_sec': '5'}, headers=auth)
    assert resp.status_code == 409
    assert 'not streaming yet' in _message(resp)
    get.assert_not_called()
    put.assert_not_called()
    assert queued == []


def test_put_disable_while_busy_409(app, client, auth, streaming, queued):
    with app.app_context():
        db.session.get(QLInstance, streaming).status = InstanceStatus.RESTARTING
        db.session.commit()
    resp = client.put(f'{URL}/instances/{streaming}',
                      json={'enabled': False, 'delay_sec': ''}, headers=auth)
    assert resp.status_code == 409
    assert 'busy' in _message(resp)
    assert queued == []
    assert _status(app, streaming) == InstanceStatus.RESTARTING


def test_put_bad_delay_is_400(client, auth, streaming, queued):
    resp = client.put(f'{URL}/instances/{streaming}',
                      json={'enabled': True, 'delay_sec': '301'}, headers=auth)
    assert resp.status_code == 400
    assert queued == []


# ---- status ---------------------------------------------------------------

@pytest.mark.parametrize('hub, label', [
    (dict(return_value=_hub(delay=5.0, override=True)), 'Streaming, delay 5 s'),
    (dict(return_value=_hub(delay=3.0, default=3.0)), 'Streaming, delay 3 s (hub default)'),
    (dict(side_effect=__import__('requests').ConnectionError('down')), 'Streaming'),
])
def test_status_label_with_delay(client, auth, streaming, hub, label):
    with patch(GET, **hub) as get:
        resp = client.get(f'{URL}/instances/{streaming}/status', headers=auth)
    assert resp.get_json()['data'] == {'ok': True, 'label': label}
    assert get.call_count == 1
    assert get.call_args.kwargs['timeout'] == 5


def test_status_when_off_does_not_ask_the_hub(client, auth, off):
    with patch(GET) as get:
        resp = client.get(f'{URL}/instances/{off}/status', headers=auth)
    assert resp.get_json()['data'] == {'ok': False, 'label': 'Not streaming'}
    get.assert_not_called()


# ---- settings -------------------------------------------------------------

def test_settings_get_put_merges_relay_and_stats_hub(app, client, auth):
    resp = client.put(f'{URL}/settings', json={
        'relay_host': ' stats.example ', 'relay_port': '27999',
        'stats_hub_url': 'https://stats.example/', 'ingest_token': TOKEN,
    }, headers=auth)
    assert resp.status_code == 200, resp.get_json()
    assert TOKEN not in resp.get_data(as_text=True)

    loaded = client.get(f'{URL}/settings', headers=auth)
    assert loaded.get_json()['data'] == {
        'relay_host': 'stats.example', 'relay_port': '27999',
        'stats_hub_url': 'https://stats.example', 'ingest_token': '',
    }

    # the form submits what it loaded: a blank token keeps the stored one
    resp = client.put(f'{URL}/settings', json={**loaded.get_json()['data'],
                                               'relay_port': '28000'}, headers=auth)
    assert resp.status_code == 200
    with app.app_context():
        from qlsm_addon_demo_stream.settings import (
            get_relay_port, get_stats_hub_ingest_token)
        assert get_stats_hub_ingest_token() == TOKEN
        assert get_relay_port() == '28000'

    # the old routes still answer
    assert client.get(f'{URL}/relay', headers=auth).get_json()['data'] == {
        'host': 'stats.example', 'port': '28000'}


@pytest.mark.parametrize('body, needle', [
    ({'relay_port': 'abc'}, 'port must be a number'),
    ({'relay_host': 5}, 'must be strings'),
    ({'stats_hub_url': ['x']}, 'must be strings'),
    ({'ingest_token': 7}, 'must be strings'),
])
def test_settings_put_validates_like_the_old_routes(client, auth, body, needle):
    resp = client.put(f'{URL}/settings', json=body, headers=auth)
    assert resp.status_code == 400
    assert needle in _message(resp)


def test_settings_need_a_login(client):
    assert client.get(f'{URL}/settings').status_code == 401
    assert client.put(f'{URL}/settings', json={}).status_code == 401


# ---- manifest -------------------------------------------------------------

def test_manifest_one_instance_entry_with_status():
    m = json.loads((ADDONS_DIR / 'demo-stream' / 'qlsm-addon.json').read_text(encoding='utf-8'))
    assert m['version'] == '1.6.0'
    ui = m['ui']
    (entry,) = ui['instance_menu']
    assert entry['id'] == 'demo-stream' and entry['label'] == 'Live Demo Stream'
    assert entry['status'] == 'GET instances/{instance_id}/status'
    panel = ui['panels'][entry['panel']]
    assert (panel['load'], panel['submit']) == ('GET instances/{instance_id}',
                                                'PUT instances/{instance_id}')
    assert panel['status'] == {'load': 'GET instances/{instance_id}/status'}
    assert [(f['key'], f['type']) for f in panel['fields']] == [
        ('enabled', 'bool'), ('delay_sec', 'string')]

    sections = ui['settings_section']
    sections = sections if isinstance(sections, list) else [sections]
    (section,) = sections
    assert section['label'] == 'Live Demo Stream'
    settings_panel = ui['panels'][section['panel']]
    assert (settings_panel['load'], settings_panel['submit']) == ('GET settings', 'PUT settings')
    assert [(f['key'], f['type']) for f in settings_panel['fields']] == [
        ('relay_host', 'string'), ('relay_port', 'string'),
        ('stats_hub_url', 'string'), ('ingest_token', 'secret')]

    (host_entry,) = ui['host_menu']
    assert host_entry['status'] == 'GET hosts/{host_id}/status'

    # no panel left pointing at the old routes
    routes = json.dumps(ui['panels'])
    for old in ('/delay', '/enable', '"GET relay"', '"GET stats-hub"'):
        assert old not in routes, old


# ---- stream server ID drifted from telemetry's (1.5.1) ----------------------

TELEMETRY_ID = 1


def _telemetry_id(app, instance_id, server_id=TELEMETRY_ID, hub=HUB):
    """Telemetry's own keys, as telemetry-relay writes them."""
    from ui.models import AppSetting
    with app.app_context():
        db.session.add(AppSetting(key=f'stats_hub_reserved_server_id:{instance_id}',
                                  value=str(server_id)))
        db.session.add(AppSetting(key=f'stats_hub_server_id:{instance_id}', value=str(server_id)))
        db.session.add(AppSetting(key='stats_hub_url', value=hub))
        db.session.commit()


def test_status_shows_a_stream_id_that_drifted_from_telemetry(app, client, auth, streaming):
    _telemetry_id(app, streaming)
    with patch(GET) as get:
        resp = client.get(f'{URL}/instances/{streaming}/status', headers=auth)
    assert resp.get_json()['data'] == {
        'ok': False,
        'label': f'Streaming on server ID {SERVER_ID}, telemetry uses {TELEMETRY_ID}; save to repair'}
    get.assert_not_called()


def test_status_names_telemetrys_reserved_id_when_telemetry_is_off(app, client, auth, streaming):
    from ui.models import AppSetting
    _telemetry_id(app, streaming)
    with app.app_context():
        db.session.delete(AppSetting.query.get(f'stats_hub_server_id:{streaming}'))
        db.session.commit()
    resp = client.get(f'{URL}/instances/{streaming}/status', headers=auth)
    assert resp.get_json()['data'] == {
        'ok': False,
        'label': f"Streaming on server ID {SERVER_ID}, telemetry's reserved ID is {TELEMETRY_ID}; "
                 "save to repair"}


def test_status_ignores_telemetry_on_another_hub(client, app, auth, streaming):
    _telemetry_id(app, streaming, hub='https://other.example')
    with patch(GET, return_value=_hub()):
        resp = client.get(f'{URL}/instances/{streaming}/status', headers=auth)
    assert resp.get_json()['data']['ok'] is True


def test_put_save_repairs_a_stream_id_that_drifted_from_telemetry(app, client, auth, streaming,
                                                                    queued):
    _telemetry_id(app, streaming)
    with patch(GET) as get, patch(PUT) as put:
        resp = client.put(f'{URL}/instances/{streaming}',
                          json={'enabled': True, 'delay_sec': '5'}, headers=auth)
    assert resp.status_code == 202, resp.get_json()
    (task, args, kwargs), = queued
    assert task is _tasks()['enable_instance_demo_stream']
    assert args == (streaming,) and kwargs['delay_sec'] == 5.0
    get.assert_not_called()
    put.assert_not_called()


def test_enable_adopts_telemetrys_server_id(app, streaming, monkeypatch):
    ops = importlib.import_module('qlsm_addon_demo_stream.instance_ops')
    _telemetry_id(app, streaming)
    routes = []
    monkeypatch.setattr(ops, '_register_route',
                        lambda host_id, server_id, name, token: routes.append((server_id, token)))
    monkeypatch.setattr(ops, 'reserve_server_id', Mock(side_effect=AssertionError('reserved')))
    import ui.tasks
    monkeypatch.setattr(ui.tasks, 'enqueue_task', lambda *a, **k: Mock(id='job-1'))
    with app.app_context():
        ok, message = ops.enable_instance_demo_stream_logic(streaming)
        from qlsm_addon_demo_stream.settings import get_instance_server_id
        assert ok, message
        assert get_instance_server_id(streaming) == TELEMETRY_ID
    assert routes == [(TELEMETRY_ID, 'stream-token')]
    assert f'server_id={TELEMETRY_ID}' in message


def test_upsert_leaves_one_line_per_cvar():
    from qlsm_addon_demo_stream.stats_hub import read_cvars_from_text, upsert_cvars_in_text
    text = 'set sv_demoStream "0"\nset a "1"\nseta sv_demoStream 0 // off\nset sv_demoStreamHost x\n'
    assert read_cvars_from_text(text, ['sv_demoStream', 'sv_demoStreamHost']) == {
        'sv_demoStream': '0', 'sv_demoStreamHost': 'x'}
    out = upsert_cvars_in_text(text, {'sv_demoStream': '1'})
    assert out == 'set a "1"\nset sv_demoStream "1"\nset sv_demoStreamHost x\n'
    assert read_cvars_from_text(out, ['sv_demoStream']) == {'sv_demoStream': '1'}
