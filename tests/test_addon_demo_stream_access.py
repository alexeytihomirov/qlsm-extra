"""demo-stream addon: the host is let in to stats-hub's firewall when the tunnel
is enabled and let out when both the tunnel and the telemetry relay are off
(ql-stats-hub-0014). The hub is mocked at the `requests` level."""
from unittest.mock import Mock, patch

import pytest
import requests

from ui import db
from ui.models import AppSetting, Host, HostStatus
from conftest import auth_headers, make_user

URL = '/api/addons/demo-stream'
HUB = 'https://hub.example'
MOD = 'qlsm_addon_demo_stream.stats_hub'
PEM = '-----BEGIN CERTIFICATE-----\nX\n-----END CERTIFICATE-----\n'
OK_PUT = {'ok': True, 'ip': '10.0.0.1', 'name': 'germany', 'changed': True}


@pytest.fixture
def addon_id():
    return 'demo-stream'


@pytest.fixture
def auth(app):
    make_user(app, 'demoop2', 'pw')
    return auth_headers(app, 'demoop2')


@pytest.fixture(autouse=True)
def host_lock_is_free():
    """No Redis in tests: the host lock is taken (a test patching it again wins)."""
    with patch('ui.task_lock.acquire_lock', return_value=True), patch('ui.task_lock.release_lock'):
        yield


@pytest.fixture
def host_id(app):
    with app.app_context():
        host = Host(name='germany', ip_address='10.0.0.1', provider='vultr',
                    status=HostStatus.ACTIVE)
        db.session.add(host)
        db.session.commit()
        return host.id


def _set_relay_and_hub():
    from qlsm_addon_demo_stream.settings import (
        set_relay_host, set_relay_port, set_stats_hub_ingest_token, set_stats_hub_url)
    set_relay_host('70.34.223.191')
    set_relay_port('27999')
    set_stats_hub_url(HUB)
    set_stats_hub_ingest_token('tok')
    db.session.commit()


def _answer(status=200, body=None):
    resp = Mock(status_code=status)
    resp.json.return_value = body if body is not None else {}
    return resp


def test_enable_allows_before_queueing(app, client, auth, host_id):
    with app.app_context():
        _set_relay_and_hub()
    order = []
    with patch(f'{MOD}.requests.put',
               side_effect=lambda *a, **k: order.append('put') or _answer(body=OK_PUT)) as put, \
            patch('qlsm_addon_demo_stream.tunnel_ops.fetch_hub_tls_cert', return_value=PEM), \
            patch('ui.task_lock.acquire_lock', return_value=True), \
            patch('ui.tasks.enqueue_task', side_effect=lambda *a, **k: order.append('queue')):
        resp = client.put(f'{URL}/hosts/{host_id}', json={'enabled': True, 'local_port': ''},
                          headers=auth)
    assert resp.status_code == 202
    assert order == ['put', 'queue']
    assert put.call_args.args[0] == f'{HUB}/api/admin/firewall/hosts/10.0.0.1'
    assert put.call_args.kwargs['json'] == {'name': 'germany'}


def test_enable_hub_error_queues_nothing(app, client, auth, host_id):
    with app.app_context():
        _set_relay_and_hub()
    with patch(f'{MOD}.requests.put', return_value=_answer(409, {'detail': 'refused'})), \
            patch('qlsm_addon_demo_stream.tunnel_ops.fetch_hub_tls_cert', return_value=PEM), \
            patch('ui.task_lock.acquire_lock', return_value=True), \
            patch('ui.tasks.enqueue_task') as enqueue:
        resp = client.put(f'{URL}/hosts/{host_id}', json={'enabled': True, 'local_port': ''},
                          headers=auth)
    assert resp.status_code == 502
    assert 'refused' in resp.get_json()['error']['message']
    enqueue.assert_not_called()
    with app.app_context():
        assert db.session.get(Host, host_id).status == HostStatus.ACTIVE


def test_enable_without_ip_is_409(app, client, auth, host_id):
    with app.app_context():
        _set_relay_and_hub()
        db.session.get(Host, host_id).ip_address = ''
        db.session.commit()
    with patch('qlsm_addon_demo_stream.tunnel_ops.fetch_hub_tls_cert', return_value=PEM), \
            patch('ui.tasks.enqueue_task') as enqueue:
        resp = client.put(f'{URL}/hosts/{host_id}', json={'enabled': True, 'local_port': ''},
                          headers=auth)
    assert resp.status_code == 409
    assert 'no IP address' in resp.get_json()['error']['message']
    enqueue.assert_not_called()


def test_save_while_off_calls_nothing(app, client, auth, host_id):
    with patch(f'{MOD}.requests.put') as put, patch(f'{MOD}.requests.delete') as dele:
        resp = client.put(f'{URL}/hosts/{host_id}', json={'enabled': False, 'local_port': ''},
                          headers=auth)
    assert resp.status_code == 200
    put.assert_not_called()
    dele.assert_not_called()


def _disable(app, host_id, relay_on=False, delete=None):
    with app.app_context():
        _set_relay_and_hub()
        if relay_on:
            db.session.add(AppSetting(key=f'telemetry_relay_enabled:{host_id}', value='1'))
            db.session.commit()
        from qlsm_addon_demo_stream.tunnel_ops import configure_host_demo_stream_tunnel_logic
        with patch('qlsm_addon_demo_stream.tunnel_ops._run_host_ansible_playbook',
                   return_value=(True, '', '')), \
                patch(f'{MOD}.requests.delete', **(delete or {'return_value': _answer(body={})})) as dele:
            ok = configure_host_demo_stream_tunnel_logic(host_id, False, '27999', '')
        return ok, dele, db.session.get(Host, host_id).logs


def test_disable_releases_when_relay_off(app, host_id):
    ok, dele, _logs = _disable(app, host_id)
    assert ok is True
    assert dele.call_args.args[0] == f'{HUB}/api/admin/firewall/hosts/10.0.0.1'


def test_disable_keeps_host_when_relay_on(app, host_id):
    ok, dele, _logs = _disable(app, host_id, relay_on=True)
    assert ok is True
    dele.assert_not_called()


def test_failed_release_is_a_warning(app, host_id):
    ok, _dele, logs = _disable(app, host_id, delete={'side_effect': requests.ConnectionError()})
    assert ok is True
    assert logs.startswith('Demo stream tunnel disabled.')
    assert 'stats-hub firewall' in logs


def test_enable_does_not_release(app, host_id):
    with app.app_context():
        _set_relay_and_hub()
        from qlsm_addon_demo_stream.tunnel_ops import configure_host_demo_stream_tunnel_logic
        with patch('qlsm_addon_demo_stream.tunnel_ops._run_host_ansible_playbook',
                   return_value=(True, '', '')), \
                patch(f'{MOD}.requests.delete') as dele:
            assert configure_host_demo_stream_tunnel_logic(host_id, True, '27999', PEM) is True
        dele.assert_not_called()


@pytest.mark.parametrize('links, ports, label, ok', [
    (1, {'8090': 'ok', '27999': 'ok'}, 'Firewall ok; demo stream connected', True),
    (0, {'8090': 'ok', '27999': 'missing'}, 'Firewall missing 27999; demo stream not connected', False),
])
def test_status_labels(app, client, auth, host_id, links, ports, label, ok):
    with app.app_context():
        _set_relay_and_hub()
    state = {'ip': '10.0.0.1', 'listed': True, 'name': 'germany', 'ports': ports, 'public': {},
             'last_telemetry_at': None, 'demo_stream_links': links}
    with patch(f'{MOD}.requests.get', return_value=_answer(body=state)):
        resp = client.get(f'{URL}/hosts/{host_id}/status', headers=auth)
    assert resp.status_code == 200
    assert resp.get_json()['data'] == {'ok': ok, 'label': label}


def test_status_hub_error(app, client, auth, host_id):
    with app.app_context():
        _set_relay_and_hub()
    with patch(f'{MOD}.requests.get', side_effect=requests.ConnectionError()):
        resp = client.get(f'{URL}/hosts/{host_id}/status', headers=auth)
    assert resp.get_json()['data'] == {'ok': False, 'label': 'Stats-hub unreachable'}


def test_manifest_declares_host_status(app):
    import json
    from conftest import ADDONS_DIR
    manifest = json.loads((ADDONS_DIR / 'demo-stream' / 'qlsm-addon.json').read_text(encoding='utf-8'))
    assert manifest['ui']['panels']['host_tunnel']['status'] == {'load': 'GET hosts/{host_id}/status'}


def test_busy_host_lock_lets_nothing_in(app, client, auth, host_id):
    with app.app_context():
        _set_relay_and_hub()
    with patch(f'{MOD}.requests.put') as put, \
            patch('qlsm_addon_demo_stream.tunnel_ops.fetch_hub_tls_cert', return_value=PEM), \
            patch('ui.task_lock.acquire_lock', return_value=False), \
            patch('ui.tasks.enqueue_task') as enqueue:
        resp = client.put(f'{URL}/hosts/{host_id}', json={'enabled': True, 'local_port': ''},
                          headers=auth)
    assert resp.status_code == 409
    put.assert_not_called()
    enqueue.assert_not_called()


def test_refused_allow_releases_the_lock(app, client, auth, host_id):
    with app.app_context():
        _set_relay_and_hub()
    with patch(f'{MOD}.requests.put', return_value=_answer(503, {'detail': 'x'})), \
            patch('qlsm_addon_demo_stream.tunnel_ops.fetch_hub_tls_cert', return_value=PEM), \
            patch('ui.task_lock.acquire_lock', return_value=True), \
            patch('ui.task_lock.release_lock') as release, \
            patch('ui.tasks.enqueue_task'):
        resp = client.put(f'{URL}/hosts/{host_id}', json={'enabled': True, 'local_port': ''},
                          headers=auth)
    assert resp.status_code == 502
    release.assert_called_once()


def test_status_call_uses_the_short_timeout(app, host_id):
    with app.app_context():
        _set_relay_and_hub()
        from qlsm_addon_demo_stream.stats_hub import STATUS_TIMEOUT_SEC, host_access_status
        with patch(f'{MOD}.requests.get', return_value=_answer(body={'ports': {}})) as get:
            host_access_status(db.session.get(Host, host_id))
        assert get.call_args.kwargs['timeout'] == STATUS_TIMEOUT_SEC == 10
