"""telemetry-relay addon: the host is let in to stats-hub's firewall when the
relay is enabled and let out when both the relay and the demo-stream tunnel
are off (ql-stats-hub-0014). The hub is mocked at the `requests` level."""
import re
import time
from unittest.mock import Mock, patch

import pytest
import requests

from ui import db
from ui.models import AppSetting, Host, HostStatus
from conftest import auth_headers, make_user

URL = '/api/addons/telemetry-relay'
HUB = 'https://hub.example'
MOD = 'qlsm_addon_telemetry_relay.stats_hub'


@pytest.fixture
def addon_id():
    return 'telemetry-relay'


@pytest.fixture
def auth(app):
    make_user(app, 'relayop', 'pw')
    return auth_headers(app, 'relayop')


@pytest.fixture(autouse=True)
def host_lock_is_free():
    """No Redis in tests: the host lock is taken (a test patching it again wins)."""
    with patch('ui.task_lock.acquire_lock', return_value=True), patch('ui.task_lock.release_lock'):
        yield


@pytest.fixture
def host_id(app):
    with app.app_context():
        host = Host(name='Germany #1', ip_address='10.0.0.1', provider='vultr',
                    status=HostStatus.ACTIVE)
        db.session.add(host)
        db.session.commit()
        return host.id


def _set_hub():
    from qlsm_addon_telemetry_relay.settings import set_stats_hub_ingest_token, set_stats_hub_url
    set_stats_hub_url(HUB)
    set_stats_hub_ingest_token('tok')
    db.session.commit()


def _answer(status=200, body=None):
    resp = Mock(status_code=status)
    resp.json.return_value = body if body is not None else {}
    return resp


OK_PUT = {'ok': True, 'ip': '10.0.0.1', 'name': 'germany-1', 'changed': True}


def test_hub_host_name(app):
    with app.app_context():
        from qlsm_addon_telemetry_relay.stats_hub import hub_host_name
        assert hub_host_name(Host(id=3, name='Germany #1')) == 'germany-1'
        assert hub_host_name(Host(id=3, name='Нижний')) == 'host-3'
        assert hub_host_name(Host(id=3, name='a' * 40)) == 'a' * 32
        assert hub_host_name(Host(id=3, name='--x--')) == 'x'


def test_enable_allows_before_queueing(app, client, auth, host_id):
    with app.app_context():
        _set_hub()
    order = []
    with patch(f'{MOD}.requests.put', side_effect=lambda *a, **k: order.append('put') or _answer(body=OK_PUT)) as put, \
            patch('ui.task_lock.acquire_lock', return_value=True), \
            patch('ui.tasks.enqueue_task', side_effect=lambda *a, **k: order.append('queue')):
        resp = client.put(f'{URL}/hosts/{host_id}', json={'enabled': True}, headers=auth)
    assert resp.status_code == 202
    assert order == ['put', 'queue']
    assert put.call_args.args[0] == f'{HUB}/api/admin/firewall/hosts/10.0.0.1'
    assert put.call_args.kwargs['json'] == {'name': 'germany-1'}
    assert put.call_args.kwargs['headers'] == {'Authorization': 'Bearer tok'}
    assert put.call_args.kwargs['allow_redirects'] is False


def test_enable_hub_error_queues_nothing(app, client, auth, host_id):
    with app.app_context():
        _set_hub()
    with patch(f'{MOD}.requests.put', return_value=_answer(503, {'detail': 'firewall management is not set up'})), \
            patch('ui.tasks.enqueue_task') as enqueue:
        resp = client.put(f'{URL}/hosts/{host_id}', json={'enabled': True}, headers=auth)
    assert resp.status_code == 502
    assert 'firewall management is not set up' in resp.get_json()['error']['message']
    enqueue.assert_not_called()
    with app.app_context():
        assert db.session.get(Host, host_id).status == HostStatus.ACTIVE


def test_enable_unreachable_hub_queues_nothing(app, client, auth, host_id):
    with app.app_context():
        _set_hub()
    with patch(f'{MOD}.requests.put', side_effect=requests.ConnectionError('x tok')), \
            patch('ui.tasks.enqueue_task') as enqueue:
        resp = client.put(f'{URL}/hosts/{host_id}', json={'enabled': True}, headers=auth)
    assert resp.status_code == 502
    assert 'tok' not in resp.get_json()['error']['message']
    enqueue.assert_not_called()


def test_enable_without_ip_is_409(app, client, auth, host_id):
    with app.app_context():
        _set_hub()
        db.session.get(Host, host_id).ip_address = None
        db.session.commit()
    with patch('ui.tasks.enqueue_task') as enqueue:
        resp = client.put(f'{URL}/hosts/{host_id}', json={'enabled': True}, headers=auth)
    assert resp.status_code == 409
    assert 'no IP address' in resp.get_json()['error']['message']
    enqueue.assert_not_called()


def test_already_enabled_save_allows_too(app, client, auth, host_id):
    with app.app_context():
        _set_hub()
        from qlsm_addon_telemetry_relay.settings import set_relay_enabled
        set_relay_enabled(host_id, True)
        db.session.commit()
    with patch(f'{MOD}.requests.put', return_value=_answer(body=OK_PUT)) as put, \
            patch('qlsm_addon_telemetry_relay.relay_ops.push_relay_config_logic'):
        resp = client.put(f'{URL}/hosts/{host_id}', json={'enabled': True}, headers=auth)
    assert resp.status_code == 200
    put.assert_called_once()


def _disable(app, host_id, tunnel_on=False, delete=None):
    with app.app_context():
        _set_hub()
        if tunnel_on:
            db.session.add(AppSetting(key=f'demo_stream_tunnel_enabled:{host_id}', value='1'))
            db.session.commit()
        from qlsm_addon_telemetry_relay.relay_ops import configure_host_telemetry_relay_logic
        with patch('qlsm_addon_telemetry_relay.relay_ops._run_host_ansible_playbook',
                   return_value=(True, '', '')), \
                patch(f'{MOD}.requests.delete', **(delete or {'return_value': _answer(body={})})) as dele:
            ok = configure_host_telemetry_relay_logic(host_id, False)
        return ok, dele, db.session.get(Host, host_id).logs


def test_disable_releases_when_tunnel_off(app, host_id):
    ok, dele, _logs = _disable(app, host_id)
    assert ok is True
    assert dele.call_args.args[0] == f'{HUB}/api/admin/firewall/hosts/10.0.0.1'


def test_disable_keeps_host_when_tunnel_on(app, host_id):
    ok, dele, _logs = _disable(app, host_id, tunnel_on=True)
    assert ok is True
    dele.assert_not_called()


def test_failed_release_is_a_warning(app, host_id):
    ok, _dele, logs = _disable(app, host_id, delete={'side_effect': requests.ConnectionError()})
    assert ok is True
    assert logs.startswith('Telemetry relay disabled.')
    assert 'stats-hub firewall' in logs


def test_enable_does_not_release(app, host_id):
    with app.app_context():
        _set_hub()
        from qlsm_addon_telemetry_relay.relay_ops import configure_host_telemetry_relay_logic
        with patch('qlsm_addon_telemetry_relay.relay_ops._run_host_ansible_playbook',
                   return_value=(True, '', '')), \
                patch(f'{MOD}.requests.delete') as dele:
            assert configure_host_telemetry_relay_logic(host_id, True) is True
        dele.assert_not_called()


def test_status_shows_firewall_and_telemetry(app, client, auth, host_id):
    with app.app_context():
        _set_hub()
    state = {'ip': '10.0.0.1', 'listed': True, 'name': 'germany-1',
             'ports': {'8090': 'ok', '27999': 'ok'}, 'public': {},
             'last_telemetry_at': time.time() - 5, 'demo_stream_links': 0}
    probe = {'enabled': True, 'reachable': True, 'routed_instances': [1]}
    with patch('qlsm_addon_telemetry_relay.relay_ops.get_relay_status_logic', return_value=probe), \
            patch(f'{MOD}.requests.get', return_value=_answer(body=state)):
        resp = client.get(f'{URL}/hosts/{host_id}/status', headers=auth)
    label = resp.get_json()['data']['label']
    assert label.startswith('Reachable, 1 instance(s) routed')
    assert 'Firewall ok' in label
    assert re.search(r'; telemetry \d+ s ago$', label)


def test_status_hub_error_does_not_fail_the_probe(app, client, auth, host_id):
    with app.app_context():
        _set_hub()
    probe = {'enabled': True, 'reachable': True, 'routed_instances': []}
    with patch('qlsm_addon_telemetry_relay.relay_ops.get_relay_status_logic', return_value=probe), \
            patch(f'{MOD}.requests.get', return_value=_answer(404)):
        resp = client.get(f'{URL}/hosts/{host_id}/status', headers=auth)
    data = resp.get_json()['data']
    assert data['ok'] is True
    assert 'firewall status: Stats-hub has no firewall API' in data['label']


def test_busy_host_lock_lets_nothing_in(app, client, auth, host_id):
    with app.app_context():
        _set_hub()
    with patch(f'{MOD}.requests.put') as put, \
            patch('ui.task_lock.acquire_lock', return_value=False), \
            patch('ui.tasks.enqueue_task') as enqueue:
        resp = client.put(f'{URL}/hosts/{host_id}', json={'enabled': True}, headers=auth)
    assert resp.status_code == 409
    put.assert_not_called()
    enqueue.assert_not_called()


def test_refused_allow_releases_the_lock(app, client, auth, host_id):
    with app.app_context():
        _set_hub()
    with patch(f'{MOD}.requests.put', return_value=_answer(503, {'detail': 'x'})), \
            patch('ui.task_lock.acquire_lock', return_value=True), \
            patch('ui.task_lock.release_lock') as release, \
            patch('ui.tasks.enqueue_task'):
        resp = client.put(f'{URL}/hosts/{host_id}', json={'enabled': True}, headers=auth)
    assert resp.status_code == 502
    release.assert_called_once()


def test_status_call_uses_the_short_timeout(app, host_id):
    with app.app_context():
        _set_hub()
        from qlsm_addon_telemetry_relay.stats_hub import STATUS_TIMEOUT_SEC, host_access_status
        with patch(f'{MOD}.requests.get', return_value=_answer(body={'ports': {}})) as get:
            host_access_status(db.session.get(Host, host_id))
        assert get.call_args.kwargs['timeout'] == STATUS_TIMEOUT_SEC == 10
