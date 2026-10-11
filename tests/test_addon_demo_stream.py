"""demo-stream addon: host TLS tunnel settings, ops and playbook templates."""
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
