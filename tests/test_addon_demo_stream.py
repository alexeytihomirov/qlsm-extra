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
        from qlsm_addon_demo_stream.settings import (
            get_telemetry_server_id, set_telemetry_server_id)
        assert get_telemetry_server_id(instance_id) is None
        db.session.add(AppSetting(key=f'stats_hub_server_id:{instance_id}', value='42'))
        db.session.commit()
        assert get_telemetry_server_id(instance_id) == 42
        set_telemetry_server_id(instance_id, None)
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
