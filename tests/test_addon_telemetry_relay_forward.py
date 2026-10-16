"""telemetry-relay addon: a host's forward URL (a relay in front of stats-hub
for a host whose own path to the hub is cut). Only the sidecar's routes use
it; qlsm's own calls to stats-hub keep the stats-hub URL."""
from unittest.mock import Mock, patch

import pytest

from ui import db
from ui.models import AppSetting, Host, HostStatus, QLInstance, InstanceStatus
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


@pytest.fixture
def host_id(app):
    with app.app_context():
        host = Host(name='NN', ip_address='10.0.0.9', provider='self', status=HostStatus.ACTIVE)
        db.session.add(host)
        db.session.commit()
        db.session.add(QLInstance(name='duel', port=27960, hostname='duel', host_id=host.id,
                                  status=InstanceStatus.RUNNING))
        db.session.commit()
        return host.id


def _set_hub():
    from qlsm_addon_telemetry_relay.settings import set_stats_hub_ingest_token, set_stats_hub_url
    set_stats_hub_url(HUB)
    set_stats_hub_ingest_token('tok')
    db.session.commit()


def _route_ids(host_id):
    from qlsm_addon_telemetry_relay.settings import set_instance_server_id
    instance = QLInstance.query.filter_by(host_id=host_id).first()
    set_instance_server_id(instance.id, 30)
    db.session.commit()


def test_routes_go_to_the_forward_url_when_set(app, host_id):
    with app.app_context():
        from qlsm_addon_telemetry_relay.relay_ops import build_relay_routes_for_host
        from qlsm_addon_telemetry_relay.settings import set_host_forward_url
        _set_hub()
        _route_ids(host_id)
        assert build_relay_routes_for_host(host_id)['30']['telemetry'] == f'{HUB}/api/ingest/telemetry'
        set_host_forward_url(host_id, ' http://91.99.3.72:80/ ')
        db.session.commit()
        route = build_relay_routes_for_host(host_id)['30']
        assert route['telemetry'] == 'http://91.99.3.72:80/api/ingest/telemetry'
        # where players connect is still this host
        assert route['server_address'] == '10.0.0.9:27960'
        assert AppSetting.query.get(f'telemetry_relay_host_forward_url:{host_id}').value == 'http://91.99.3.72:80'


def test_get_and_put_forward_url(app, client, auth, host_id):
    with app.app_context():
        _set_hub()
    assert client.get(f'{URL}/hosts/{host_id}', headers=auth).get_json()['data']['forward_url'] == ''
    with patch('qlsm_addon_telemetry_relay.relay_ops.push_relay_config_logic'):
        resp = client.put(f'{URL}/hosts/{host_id}', headers=auth,
                          json={'enabled': False, 'url_override': '', 'ingest_token_override': '',
                                'forward_url': 'http://91.99.3.72:80'})
        assert resp.status_code == 200
        assert client.get(f'{URL}/hosts/{host_id}', headers=auth).get_json()['data']['forward_url'] == \
            'http://91.99.3.72:80'
        # a client that does not send it keeps it
        client.put(f'{URL}/hosts/{host_id}', headers=auth, json={'enabled': False})
        assert client.get(f'{URL}/hosts/{host_id}', headers=auth).get_json()['data']['forward_url'] == \
            'http://91.99.3.72:80'


@pytest.mark.parametrize('bad', ['91.99.3.72:80', 'ftp://x:1', 'http://x/api', 'http://a b', 'http://x:80?y', 80])
def test_put_rejects_a_bad_forward_url(app, client, auth, host_id, bad):
    resp = client.put(f'{URL}/hosts/{host_id}', headers=auth, json={'enabled': False, 'forward_url': bad})
    assert resp.status_code == 400
    with app.app_context():
        from qlsm_addon_telemetry_relay.settings import get_host_forward_url
        assert get_host_forward_url(host_id) is None


def test_firewall_calls_keep_the_stats_hub_url(app, client, auth, host_id):
    """Enabling the relay lets the host in through the stats-hub URL, never the forward one."""
    with app.app_context():
        _set_hub()
    answer = Mock(status_code=200)
    answer.json.return_value = {'ok': True, 'ip': '10.0.0.9', 'name': 'nn', 'changed': True}
    with patch(f'{MOD}.requests.put', return_value=answer) as put, \
            patch('ui.task_lock.acquire_lock', return_value=True), \
            patch('ui.tasks.enqueue_task'):
        resp = client.put(f'{URL}/hosts/{host_id}', headers=auth,
                          json={'enabled': True, 'forward_url': 'http://91.99.3.72:80'})
    assert resp.status_code == 202
    assert put.call_args.args[0] == f'{HUB}/api/admin/firewall/hosts/10.0.0.9'


def test_host_delete_forgets_the_forward_url(app, host_id):
    with app.app_context():
        from qlsm_addon_telemetry_relay.settings import set_host_forward_url
        from ui.addons.registry import dispatch
        set_host_forward_url(host_id, 'http://91.99.3.72:80')
        db.session.commit()
        dispatch('host.delete', host_id, host_id)
        db.session.commit()
        assert AppSetting.query.get(f'telemetry_relay_host_forward_url:{host_id}') is None
