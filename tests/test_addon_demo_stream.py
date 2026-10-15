"""demo-stream addon: host TLS tunnel settings, ops and playbook templates."""
from unittest.mock import Mock, patch

import pytest

from ui import db
from ui.models import AppSetting, Host, HostStatus, InstanceStatus, QLInstance
from conftest import ADDONS_DIR, auth_headers, make_user


@pytest.fixture
def addon_id():
    return 'demo-stream'


@pytest.fixture
def auth(app):
    make_user(app, 'demoop', 'pw')
    return auth_headers(app, 'demoop')


@pytest.fixture(autouse=True)
def hub_lets_hosts_in():
    """Enabling the tunnel first asks stats-hub's firewall API to let the host in
    (tests/test_addon_demo_stream_access.py covers that); here it always agrees."""
    answer = Mock(status_code=200)
    answer.json.return_value = {'ok': True, 'ip': '10.0.0.1', 'name': 'germany', 'changed': False}
    with patch('requests.put', return_value=answer):
        yield


@pytest.fixture
def host_id(app):
    with app.app_context():
        host = Host(name='germany', ip_address='10.0.0.1', provider='vultr',
                    status=HostStatus.ACTIVE)
        db.session.add(host)
        db.session.commit()
        return host.id


@pytest.fixture
def instance_id(app, host_id):
    with app.app_context():
        instance = QLInstance(name='duel srv', port=27960, hostname='duel', host_id=host_id,
                              status=InstanceStatus.RUNNING)
        db.session.add(instance)
        db.session.commit()
        return instance.id


# ---- Task 1: settings --------------------------------------------------

def test_tunnel_port_defaults_to_27999(app, host_id):
    with app.app_context():
        from qlsm_addon_demo_stream.settings import get_host_tunnel_port, is_host_tunnel_enabled
        assert get_host_tunnel_port(host_id) == '27999'
        assert is_host_tunnel_enabled(host_id) is False


def test_tunnel_settings_use_the_spec_keys(app, host_id):
    with app.app_context():
        from qlsm_addon_demo_stream.settings import (
            is_host_tunnel_enabled, set_host_tunnel_enabled, set_host_tunnel_port)
        set_host_tunnel_enabled(host_id, True)
        set_host_tunnel_port(host_id, '28000')
        db.session.commit()
        assert AppSetting.query.get(f'demo_stream_tunnel_enabled:{host_id}').value == '1'
        assert AppSetting.query.get(f'demo_stream_tunnel_port:{host_id}').value == '28000'
        assert is_host_tunnel_enabled(host_id) is True
        set_host_tunnel_enabled(host_id, False)
        set_host_tunnel_port(host_id, '')
        db.session.commit()
        assert AppSetting.query.get(f'demo_stream_tunnel_enabled:{host_id}') is None
        assert AppSetting.query.get(f'demo_stream_tunnel_port:{host_id}') is None


def test_telemetry_server_id_reads_telemetry_key(app, instance_id):
    with app.app_context():
        from qlsm_addon_demo_stream.settings import get_telemetry_server_id
        assert get_telemetry_server_id(instance_id) is None
        row = AppSetting(key=f'stats_hub_server_id:{instance_id}', value='42')
        db.session.add(row)
        db.session.commit()
        assert get_telemetry_server_id(instance_id) == 42
        db.session.delete(row)
        db.session.commit()
        assert get_telemetry_server_id(instance_id) is None


# ---- Task 2: tunnel_ops ------------------------------------------------

PEM = '-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----\n'


def _set_hub(url='https://stats.example'):
    from qlsm_addon_demo_stream.settings import set_stats_hub_url
    set_stats_hub_url(url)
    db.session.commit()


def _resp(status=200, text=''):
    return Mock(status_code=status, text=text)


def test_extravars_carry_the_five_spec_keys(app):
    with app.app_context():
        from qlsm_addon_demo_stream.settings import set_relay_host, set_relay_port
        from qlsm_addon_demo_stream.tunnel_ops import build_tunnel_extravars
        set_relay_host('70.34.223.191')
        set_relay_port('27999')
        db.session.commit()
        assert build_tunnel_extravars(True, '27999', PEM) == {
            'demo_stream_tunnel_enabled': True,
            'demo_stream_tunnel_port': '27999',
            'demo_stream_relay_host': '70.34.223.191',
            'demo_stream_relay_port': '27999',
            'demo_stream_hub_cert_pem': PEM,
        }


def test_extravars_drop_cert_when_disabling(app):
    with app.app_context():
        from qlsm_addon_demo_stream.tunnel_ops import build_tunnel_extravars
        assert build_tunnel_extravars(False, '27999', PEM)['demo_stream_hub_cert_pem'] == ''


def test_fetch_cert_404_says_hub_has_no_tls(app, host_id):
    with app.app_context():
        from qlsm_addon_demo_stream.tunnel_ops import TunnelCertError, fetch_hub_tls_cert
        _set_hub()
        with patch('qlsm_addon_demo_stream.tunnel_ops.requests.get',
                   return_value=_resp(404)):
            with pytest.raises(TunnelCertError, match='no TLS configured'):
                fetch_hub_tls_cert(host_id)


def test_fetch_cert_rejects_non_pem_body(app, host_id):
    with app.app_context():
        from qlsm_addon_demo_stream.tunnel_ops import TunnelCertError, fetch_hub_tls_cert
        _set_hub()
        with patch('qlsm_addon_demo_stream.tunnel_ops.requests.get',
                   return_value=_resp(200, '<html>oops</html>')):
            with pytest.raises(TunnelCertError, match='not a PEM'):
                fetch_hub_tls_cert(host_id)


def test_fetch_cert_returns_pem(app, host_id):
    with app.app_context():
        from qlsm_addon_demo_stream.tunnel_ops import fetch_hub_tls_cert
        _set_hub()
        with patch('qlsm_addon_demo_stream.tunnel_ops.requests.get',
                   return_value=_resp(200, PEM)) as get:
            assert fetch_hub_tls_cert(host_id) == PEM
        assert get.call_args.args[0] == 'https://stats.example/api/demo-stream/tls-cert'


def test_fetch_cert_without_hub_url_asks_for_settings(app, host_id):
    with app.app_context():
        from qlsm_addon_demo_stream.tunnel_ops import TunnelCertError, fetch_hub_tls_cert
        with pytest.raises(TunnelCertError, match='Settings first'):
            fetch_hub_tls_cert(host_id)


def test_configure_success_sets_flag_and_active(app, host_id):
    with app.app_context():
        from qlsm_addon_demo_stream.settings import is_host_tunnel_enabled
        from qlsm_addon_demo_stream.tunnel_ops import configure_host_demo_stream_tunnel_logic
        with patch('qlsm_addon_demo_stream.tunnel_ops._run_host_ansible_playbook',
                   return_value=(True, '', '')) as run:
            assert configure_host_demo_stream_tunnel_logic(host_id, True, '27999', PEM) is True
        assert is_host_tunnel_enabled(host_id) is True
        host = db.session.get(Host, host_id)
        assert host.status == HostStatus.ACTIVE
        assert host.logs.startswith('Demo stream tunnel enabled on port 27999.')
        assert run.call_args.kwargs['playbook_name'].endswith('install_demo_stream_tunnel.yml')


def test_configure_failure_keeps_flag_and_sets_error(app, host_id):
    with app.app_context():
        from qlsm_addon_demo_stream.settings import is_host_tunnel_enabled
        from qlsm_addon_demo_stream.tunnel_ops import configure_host_demo_stream_tunnel_logic
        with patch('qlsm_addon_demo_stream.tunnel_ops._run_host_ansible_playbook',
                   return_value=(False, '', 'boom')):
            assert configure_host_demo_stream_tunnel_logic(host_id, True, '27999', PEM) is False
        assert is_host_tunnel_enabled(host_id) is False
        host = db.session.get(Host, host_id)
        assert host.status == HostStatus.ERROR
        assert host.logs.startswith('Demo stream tunnel configuration failed.')


# ---- Task 3: playbook and templates ------------------------------------

PLAYBOOK_DIR = ADDONS_DIR / 'demo-stream' / 'playbooks'


def _render(name, **variables):
    import jinja2
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(str(PLAYBOOK_DIR / 'templates')),
                             keep_trailing_newline=True)
    return env.get_template(name).render(**variables)


def test_stunnel_conf_matches_spec():
    text = _render('stunnel.conf.j2', demo_stream_tunnel_port='27999',
                   demo_stream_relay_host='70.34.223.191', demo_stream_relay_port='27999')
    lines = text.splitlines()
    for line in ('client = yes', 'foreground = yes', 'pid =', '[demo-stream]',
                 'accept = 127.0.0.1:27999', 'connect = 70.34.223.191:27999',
                 'verifyPeer = yes', 'CAfile = /home/ql/demo-stream-tunnel/hub.pem',
                 'sslVersionMin = TLSv1.2'):
        assert line in lines
    # global options must precede the service section
    assert lines.index('pid =') < lines.index('[demo-stream]')


def test_unit_runs_as_ql_and_restarts_always():
    lines = _render('ql-demo-stream-tunnel.service.j2').splitlines()
    assert 'User=ql' in lines
    assert 'Restart=always' in lines
    exec_start = [l for l in lines if l.startswith('ExecStart=')]
    assert len(exec_start) == 1
    assert exec_start[0].startswith('ExecStart=/usr/bin/stunnel4 ')
    assert exec_start[0].endswith(' /home/ql/demo-stream-tunnel/stunnel.conf')
    assert 'WantedBy=multi-user.target' in lines


def _playbook_tasks():
    import yaml
    play = yaml.safe_load((PLAYBOOK_DIR / 'install_demo_stream_tunnel.yml').read_text('utf-8'))[0]
    tasks = []
    for task in play['tasks']:
        tasks.append(task)
        tasks.extend(task.get('block', []))
    return tasks


def test_playbook_stops_unit_only_when_present():
    tasks = _playbook_tasks()
    stats = [t for t in tasks if 'ansible.builtin.stat' in t
             and t['ansible.builtin.stat']['path'] == '/etc/systemd/system/ql-demo-stream-tunnel.service']
    assert stats, 'no stat task for the unit file'
    register = stats[0]['register']
    stops = [t for t in tasks if 'ansible.builtin.systemd' in t
             and t['ansible.builtin.systemd'].get('state') == 'stopped']
    assert stops, 'no stop task'
    when = stops[0]['when']
    when = ' '.join(when) if isinstance(when, list) else when
    assert 'not demo_stream_tunnel_enabled' in when
    assert register in when


def test_fetch_cert_rejects_truncated_pem(app, host_id):
    with app.app_context():
        from qlsm_addon_demo_stream.tunnel_ops import TunnelCertError, fetch_hub_tls_cert
        _set_hub()
        with patch('qlsm_addon_demo_stream.tunnel_ops.requests.get',
                   return_value=_resp(200, '-----BEGIN CERTIFICATE-----\nMIIB\n')):
            with pytest.raises(TunnelCertError, match='not a PEM'):
                fetch_hub_tls_cert(host_id)


def test_playbook_enable_assert_requires_relay_port():
    asserts = [t['ansible.builtin.assert']['that'] for t in _playbook_tasks()
               if 'ansible.builtin.assert' in t]
    assert asserts
    assert 'demo_stream_relay_port | length > 0' in asserts[0]


# ---- Task 4: host endpoints --------------------------------------------

URL = '/api/addons/demo-stream'


def _set_relay_and_hub():
    from qlsm_addon_demo_stream.settings import set_relay_host, set_relay_port
    set_relay_host('70.34.223.191')
    set_relay_port('27999')
    _set_hub()
    # enabling the tunnel lets the host in to the hub's firewall: needs the token too
    from qlsm_addon_demo_stream.settings import set_stats_hub_ingest_token
    set_stats_hub_ingest_token('tok')
    db.session.commit()


def test_get_host_tunnel_defaults(client, auth, host_id):
    resp = client.get(f'{URL}/hosts/{host_id}', headers=auth)
    assert resp.status_code == 200
    assert resp.get_json()['data'] == {'enabled': False, 'local_port': '27999'}


def test_get_host_tunnel_unknown_host_404(client, auth):
    assert client.get(f'{URL}/hosts/9999', headers=auth).status_code == 404


def test_put_unknown_host_404(client, auth):
    resp = client.put(f'{URL}/hosts/9999', json={'enabled': False, 'local_port': ''}, headers=auth)
    assert resp.status_code == 404


@pytest.mark.parametrize('bad', ['0', '1023', '65536', '70000', '27 999', 'abc', 27999])
def test_put_rejects_bad_port(app, client, auth, host_id, bad):
    resp = client.put(f'{URL}/hosts/{host_id}', json={'enabled': False, 'local_port': bad},
                      headers=auth)
    assert resp.status_code == 400
    assert resp.get_json()['error']['message'] == 'local_port must be a port number (1024-65535).'
    with app.app_context():
        from qlsm_addon_demo_stream.settings import get_host_tunnel_port
        assert get_host_tunnel_port(host_id) == '27999'


def test_put_enable_without_relay_is_409(client, auth, host_id):
    resp = client.put(f'{URL}/hosts/{host_id}', json={'enabled': True, 'local_port': ''},
                      headers=auth)
    assert resp.status_code == 409
    assert 'relay host and port' in resp.get_json()['error']['message']


def test_put_enable_when_hub_has_no_tls_is_409_and_queues_nothing(app, client, auth, host_id):
    from qlsm_addon_demo_stream.tunnel_ops import TunnelCertError
    with app.app_context():
        _set_relay_and_hub()
    with patch('qlsm_addon_demo_stream.tunnel_ops.fetch_hub_tls_cert',
               side_effect=TunnelCertError('stats-hub has no TLS configured (x)')), \
            patch('ui.tasks.enqueue_task') as enqueue:
        resp = client.put(f'{URL}/hosts/{host_id}', json={'enabled': True, 'local_port': ''},
                          headers=auth)
    assert resp.status_code == 409
    assert 'no TLS' in resp.get_json()['error']['message']
    enqueue.assert_not_called()


def test_put_enable_queues_playbook_with_cert(app, client, auth, host_id):
    with app.app_context():
        _set_relay_and_hub()
    with patch('qlsm_addon_demo_stream.tunnel_ops.fetch_hub_tls_cert', return_value=PEM), \
            patch('ui.task_lock.acquire_lock', return_value=True), \
            patch('ui.tasks.enqueue_task') as enqueue:
        resp = client.put(f'{URL}/hosts/{host_id}', json={'enabled': True, 'local_port': '28000'},
                          headers=auth)
    assert resp.status_code == 202
    assert enqueue.call_args.args[1:] == (host_id, True, '28000', PEM)
    with app.app_context():
        assert db.session.get(Host, host_id).status == HostStatus.CONFIGURING


def test_put_enable_on_non_active_host_is_400(app, client, auth, host_id):
    with app.app_context():
        _set_relay_and_hub()
        db.session.get(Host, host_id).status = HostStatus.ERROR
        db.session.commit()
    with patch('qlsm_addon_demo_stream.tunnel_ops.fetch_hub_tls_cert', return_value=PEM), \
            patch('ui.tasks.enqueue_task') as enqueue:
        resp = client.put(f'{URL}/hosts/{host_id}', json={'enabled': True, 'local_port': ''},
                          headers=auth)
    assert resp.status_code == 400
    enqueue.assert_not_called()


def test_put_enable_busy_lock_is_409(app, client, auth, host_id):
    with app.app_context():
        _set_relay_and_hub()
    with patch('qlsm_addon_demo_stream.tunnel_ops.fetch_hub_tls_cert', return_value=PEM), \
            patch('ui.task_lock.acquire_lock', return_value=False), \
            patch('ui.tasks.enqueue_task') as enqueue:
        resp = client.put(f'{URL}/hosts/{host_id}', json={'enabled': True, 'local_port': ''},
                          headers=auth)
    assert resp.status_code == 409
    enqueue.assert_not_called()


def test_put_port_change_on_enabled_tunnel_requeues_playbook(app, client, auth, host_id):
    with app.app_context():
        from qlsm_addon_demo_stream.settings import set_host_tunnel_enabled
        _set_relay_and_hub()
        set_host_tunnel_enabled(host_id, True)
        db.session.commit()
    with patch('qlsm_addon_demo_stream.tunnel_ops.fetch_hub_tls_cert', return_value=PEM), \
            patch('ui.task_lock.acquire_lock', return_value=True), \
            patch('ui.tasks.enqueue_task') as enqueue:
        resp = client.put(f'{URL}/hosts/{host_id}', json={'enabled': True, 'local_port': '28001'},
                          headers=auth)
    assert resp.status_code == 202
    enqueue.assert_called_once()
    assert enqueue.call_args.args[1:] == (host_id, True, '28001', PEM)


def test_put_disable_when_already_off_saves_only(app, client, auth, host_id):
    with patch('qlsm_addon_demo_stream.tunnel_ops.fetch_hub_tls_cert') as fetch, \
            patch('ui.tasks.enqueue_task') as enqueue:
        resp = client.put(f'{URL}/hosts/{host_id}', json={'enabled': False, 'local_port': '28002'},
                          headers=auth)
    assert resp.status_code == 200
    assert resp.get_json()['data'] == {'enabled': False, 'local_port': '28002'}
    with app.app_context():
        from qlsm_addon_demo_stream.settings import get_host_tunnel_port
        assert get_host_tunnel_port(host_id) == '28002'
    enqueue.assert_not_called()
    fetch.assert_not_called()


def test_put_disable_when_on_queues_disable(app, client, auth, host_id):
    with app.app_context():
        from qlsm_addon_demo_stream.settings import set_host_tunnel_enabled
        set_host_tunnel_enabled(host_id, True)
        db.session.commit()
    with patch('qlsm_addon_demo_stream.tunnel_ops.fetch_hub_tls_cert') as fetch, \
            patch('ui.task_lock.acquire_lock', return_value=True), \
            patch('ui.tasks.enqueue_task') as enqueue:
        resp = client.put(f'{URL}/hosts/{host_id}', json={'enabled': False, 'local_port': ''},
                          headers=auth)
    assert resp.status_code == 202
    assert enqueue.call_args.args[1:] == (host_id, False, '27999', '')
    fetch.assert_not_called()


def test_host_delete_forgets_tunnel_keys(app, host_id):
    with app.app_context():
        from qlsm_addon_demo_stream.settings import set_host_tunnel_enabled, set_host_tunnel_port
        from ui.addons.registry import dispatch
        set_host_tunnel_enabled(host_id, True)
        set_host_tunnel_port(host_id, '28000')
        db.session.commit()
        dispatch('host.delete', host_id, host_id)
        db.session.commit()
        assert AppSetting.query.get(f'demo_stream_tunnel_enabled:{host_id}') is None
        assert AppSetting.query.get(f'demo_stream_tunnel_port:{host_id}') is None


# ---- Task 5: instance enable through the tunnel -------------------------

def _setup_enable(host_id, instance_id, tunnel=True, port='27999'):
    from qlsm_addon_demo_stream.settings import (
        set_host_tunnel_enabled, set_host_tunnel_port, set_stats_hub_ingest_token)
    _set_relay_and_hub()
    set_stats_hub_ingest_token('tok')
    set_host_tunnel_enabled(host_id, tunnel)
    set_host_tunnel_port(host_id, port)
    db.session.commit()


def _run_enable(instance_id):
    from qlsm_addon_demo_stream.instance_ops import enable_instance_demo_stream_logic
    with patch('qlsm_addon_demo_stream.instance_ops._register_route') as route, \
            patch('ui.tasks.enqueue_task', return_value=Mock(id='job1')):
        result = enable_instance_demo_stream_logic(instance_id)
    return result, route


def _set_key(key, value):
    db.session.add(AppSetting(key=key, value=value))
    db.session.commit()


def test_enable_endpoint_400_without_host_tunnel(app, client, auth, instance_id):
    with app.app_context():
        _set_relay_and_hub()
    resp = client.post(f'{URL}/instances/{instance_id}/enable', json={}, headers=auth)
    assert resp.status_code == 400
    assert 'Demo Stream Tunnel' in resp.get_json()['error']['message']


def test_enable_writes_loopback_and_tunnel_port(app, host_id, instance_id, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with app.app_context():
        _setup_enable(host_id, instance_id, port='28000')
        _set_key(f'demo_stream_stats_hub_server_id:{instance_id}', '7')
        (ok, _msg), _route = _run_enable(instance_id)
        assert ok is True
    cfg = (tmp_path / 'configs' / 'germany' / str(instance_id) / 'server.cfg').read_text('utf-8')
    assert 'set sv_demoStreamHost "127.0.0.1"' in cfg
    assert 'set sv_demoStreamPort "28000"' in cfg
    assert '70.34.223.191' not in cfg


def test_enable_logic_refuses_without_tunnel(app, host_id, instance_id, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with app.app_context():
        _setup_enable(host_id, instance_id, tunnel=False)
        (ok, msg), route = _run_enable(instance_id)
        assert ok is False
        assert 'Demo Stream Tunnel' in msg
        route.assert_not_called()
    assert not (tmp_path / 'configs').exists()


def test_enable_reuses_telemetry_server_id(app, host_id, instance_id, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with app.app_context():
        _setup_enable(host_id, instance_id)
        _set_key('stats_hub_url', 'https://stats.example')
        _set_key(f'stats_hub_server_id:{instance_id}', '42')
        with patch('qlsm_addon_demo_stream.instance_ops.reserve_server_id') as reserve:
            (ok, _msg), route = _run_enable(instance_id)
        assert ok is True
        reserve.assert_not_called()
        assert route.call_args.args[1] == 42
        assert AppSetting.query.get(f'demo_stream_stats_hub_server_id:{instance_id}').value == '42'


def test_enable_prefers_telemetry_server_id_over_own(app, host_id, instance_id, tmp_path,
                                                     monkeypatch):
    monkeypatch.chdir(tmp_path)
    with app.app_context():
        _setup_enable(host_id, instance_id)
        _set_key(f'demo_stream_stats_hub_server_id:{instance_id}', '7')
        _set_key('stats_hub_url', 'https://stats.example/')
        _set_key(f'stats_hub_server_id:{instance_id}', '42')
        (ok, _msg), route = _run_enable(instance_id)
        assert ok is True
        assert route.call_args.args[1] == 42
        assert AppSetting.query.get(f'demo_stream_stats_hub_server_id:{instance_id}').value == '42'


def test_enable_reserves_into_own_key_only(app, host_id, instance_id, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with app.app_context():
        _setup_enable(host_id, instance_id)
        with patch('qlsm_addon_demo_stream.instance_ops.reserve_server_id', return_value=99):
            (ok, _msg), route = _run_enable(instance_id)
        assert ok is True
        assert route.call_args.args[1] == 99
        assert AppSetting.query.get(f'demo_stream_stats_hub_server_id:{instance_id}').value == '99'
        # telemetry's key is never written by this addon
        assert AppSetting.query.get(f'stats_hub_server_id:{instance_id}') is None


def test_status_reports_tunnel_off(app, client, auth, instance_id):
    with app.app_context():
        _set_relay_and_hub()
    resp = client.get(f'{URL}/instances/{instance_id}/status', headers=auth)
    assert resp.get_json()['data'] == {'ok': False, 'label': 'Tunnel not enabled on host'}


# ---- Task 6: manifest ---------------------------------------------------

def test_manifest_declares_host_tunnel_panel():
    import json
    m = json.loads((ADDONS_DIR / 'demo-stream' / 'qlsm-addon.json').read_text(encoding='utf-8'))
    assert m['version'] == '1.5.0'
    assert m['ui_api'] == 1
    assert m['ui']['host_menu'][0]['panel'] == 'host_tunnel'
    p = m['ui']['panels']['host_tunnel']
    assert (p['load'], p['submit']) == ('GET hosts/{host_id}', 'PUT hosts/{host_id}')
    assert [f['key'] for f in p['fields']] == ['enabled', 'local_port']
    assert next(f for f in p['fields'] if f['key'] == 'local_port')['placeholder'] == '27999'
    relay_port = next(f for f in m['ui']['panels']['settings']['fields'] if f['key'] == 'relay_port')
    assert relay_port['placeholder'] == '27999'


# ---- Final review fix wave ----------------------------------------------

def test_enable_does_not_reuse_telemetry_id_from_a_different_hub(app, host_id, instance_id,
                                                                 tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with app.app_context():
        _setup_enable(host_id, instance_id)
        _set_key('stats_hub_url', 'https://other-hub.example')
        _set_key(f'stats_hub_server_id:{instance_id}', '42')
        with patch('qlsm_addon_demo_stream.instance_ops.reserve_server_id',
                   return_value=99) as reserve:
            (ok, _msg), route = _run_enable(instance_id)
        assert ok is True
        reserve.assert_called_once()
        assert route.call_args.args[1] == 99


def test_enable_telemetry_host_override_url_is_compared(app, host_id, instance_id,
                                                        tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with app.app_context():
        _setup_enable(host_id, instance_id)
        _set_key('stats_hub_url', 'https://other-hub.example')
        _set_key(f'telemetry_relay_host_stats_hub_url:{host_id}', 'https://stats.example')
        _set_key(f'stats_hub_server_id:{instance_id}', '42')
        (ok, _msg), route = _run_enable(instance_id)
        assert ok is True
        assert route.call_args.args[1] == 42


def test_put_boundary_ports_accepted(app, client, auth, host_id):
    for good in ('1024', '65535'):
        resp = client.put(f'{URL}/hosts/{host_id}', json={'enabled': False, 'local_port': good},
                          headers=auth)
        assert resp.status_code == 200
        with app.app_context():
            from qlsm_addon_demo_stream.settings import get_host_tunnel_port
            assert get_host_tunnel_port(host_id) == good


def _store_port(host_id, port):
    from qlsm_addon_demo_stream.settings import set_host_tunnel_port
    set_host_tunnel_port(host_id, port)
    db.session.commit()


def _stored_port(host_id):
    from qlsm_addon_demo_stream.settings import get_host_tunnel_port
    return get_host_tunnel_port(host_id)


def test_put_409_keeps_old_port(app, client, auth, host_id):
    with app.app_context():
        _store_port(host_id, '28000')
    resp = client.put(f'{URL}/hosts/{host_id}', json={'enabled': True, 'local_port': '28001'},
                      headers=auth)  # no relay configured
    assert resp.status_code == 409
    with app.app_context():
        assert _stored_port(host_id) == '28000'


def test_put_400_non_active_keeps_old_port(app, client, auth, host_id):
    with app.app_context():
        _set_relay_and_hub()
        _store_port(host_id, '28000')
        db.session.get(Host, host_id).status = HostStatus.ERROR
        db.session.commit()
    with patch('qlsm_addon_demo_stream.tunnel_ops.fetch_hub_tls_cert', return_value=PEM):
        resp = client.put(f'{URL}/hosts/{host_id}', json={'enabled': True, 'local_port': '28001'},
                          headers=auth)
    assert resp.status_code == 400
    with app.app_context():
        assert _stored_port(host_id) == '28000'


def test_put_enable_does_not_store_port_before_playbook_and_uses_lock_ttl_360(
        app, client, auth, host_id):
    with app.app_context():
        _set_relay_and_hub()
        _store_port(host_id, '28000')
    with patch('qlsm_addon_demo_stream.tunnel_ops.fetch_hub_tls_cert', return_value=PEM), \
            patch('ui.task_lock.acquire_lock', return_value=True) as lock, \
            patch('ui.tasks.enqueue_task'):
        resp = client.put(f'{URL}/hosts/{host_id}', json={'enabled': True, 'local_port': '28001'},
                          headers=auth)
    assert resp.status_code == 202
    assert lock.call_args.kwargs['ttl'] == 360
    with app.app_context():
        assert _stored_port(host_id) == '28000'


def test_playbook_failure_keeps_old_port_and_success_stores_new(app, host_id):
    with app.app_context():
        from qlsm_addon_demo_stream.tunnel_ops import configure_host_demo_stream_tunnel_logic
        _store_port(host_id, '28000')
        with patch('qlsm_addon_demo_stream.tunnel_ops._run_host_ansible_playbook',
                   return_value=(False, '', 'boom')):
            configure_host_demo_stream_tunnel_logic(host_id, True, '28001', PEM)
        assert _stored_port(host_id) == '28000'
        with patch('qlsm_addon_demo_stream.tunnel_ops._run_host_ansible_playbook',
                   return_value=(True, '', '')):
            configure_host_demo_stream_tunnel_logic(host_id, True, '28001', PEM)
        assert _stored_port(host_id) == '28001'


def test_playbook_waits_for_the_listener_when_enabled():
    waits = [t for t in _playbook_tasks() if 'ansible.builtin.wait_for' in t]
    assert len(waits) == 1
    args = waits[0]['ansible.builtin.wait_for']
    assert args['host'] == '127.0.0.1'
    assert 'demo_stream_tunnel_port' in str(args['port'])
    assert args['timeout'] == 15
    enable_block = next(t for t in _playbook_tasks() if t.get('block') and 'when' in t)
    assert waits[0] in enable_block['block']


def test_manifest_panel_mentions_repinning():
    import json
    m = json.loads((ADDONS_DIR / 'demo-stream' / 'qlsm-addon.json').read_text(encoding='utf-8'))
    assert 'certificate changes' in m['ui']['panels']['host_tunnel']['description']


def test_gitattributes_pins_j2_to_lf():
    root = ADDONS_DIR.parent
    assert '*.j2 text eol=lf' in (root / '.gitattributes').read_text(encoding='utf-8').splitlines()
