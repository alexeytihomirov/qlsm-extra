"""demo-stream addon: the per-instance stream delay, read and written through
ql-stats-hub's own API.

Saving the delay is one HTTP call to the hub. It must never touch server.cfg,
take the instance lock, change the instance status or queue a task.
"""
import logging
from unittest.mock import Mock, patch

import pytest
import requests

from ui import db
from ui.models import AppSetting, Host, HostStatus, InstanceStatus, QLInstance
from conftest import auth_headers, make_user

URL = '/api/addons/demo-stream'
HUB = 'https://stats.example'
TOKEN = 'ingest-secret-token'
SERVER_ID = 7
HUB_DELAY_URL = f'{HUB}/api/demo-stream/servers/{SERVER_ID}/delay'
GET = 'qlsm_addon_demo_stream.stats_hub.requests.get'
PUT = 'qlsm_addon_demo_stream.stats_hub.requests.put'


@pytest.fixture
def addon_id():
    return 'demo-stream'


@pytest.fixture
def auth(app):
    make_user(app, 'demoop', 'pw')
    return auth_headers(app, 'demoop')


@pytest.fixture
def instance_id(app):
    with app.app_context():
        host = Host(name='germany', ip_address='10.0.0.1', provider='vultr',
                    status=HostStatus.ACTIVE)
        db.session.add(host)
        db.session.flush()
        instance = QLInstance(name='duel srv', port=27960, hostname='duel', host_id=host.id,
                              status=InstanceStatus.RUNNING)
        db.session.add(instance)
        db.session.commit()
        return instance.id


@pytest.fixture
def streaming(app, instance_id):
    """An instance that is streaming: hub configured, server_id stored."""
    with app.app_context():
        from qlsm_addon_demo_stream.settings import (
            set_instance_demo_stream_enabled, set_instance_server_id,
            set_stats_hub_ingest_token, set_stats_hub_url)
        set_stats_hub_url(HUB)
        set_stats_hub_ingest_token(TOKEN)
        set_instance_demo_stream_enabled(instance_id, True)
        set_instance_server_id(instance_id, SERVER_ID)
        db.session.commit()
    return instance_id


def _hub(status=200, delay=30.0, default=30.0, override=False, body=None):
    if body is None:
        body = {'ok': True, 'server_id': SERVER_ID, 'delay_sec': delay,
                'default_delay_sec': default, 'override': override}
    return Mock(status_code=status, json=Mock(return_value=body))


def _message(resp):
    return resp.get_json()['error']['message']


# ---- GET ------------------------------------------------------------------

def test_get_delay_on_hub_default_is_blank(client, auth, streaming):
    with patch(GET, return_value=_hub()) as get:
        resp = client.get(f'{URL}/instances/{streaming}/delay', headers=auth)
    assert resp.status_code == 200
    assert resp.get_json()['data'] == {
        'delay_sec': '', 'default_delay_sec': '30', 'effective_delay_sec': '30',
        'override': False,
    }
    assert get.call_args.args[0] == HUB_DELAY_URL
    assert get.call_args.kwargs['headers'] == {'Authorization': f'Bearer {TOKEN}'}
    assert get.call_args.kwargs['timeout'] == 5


def test_get_delay_with_override_shows_the_value(client, auth, streaming):
    with patch(GET, return_value=_hub(delay=12.5, override=True)):
        resp = client.get(f'{URL}/instances/{streaming}/delay', headers=auth)
    assert resp.get_json()['data'] == {
        'delay_sec': '12.5', 'default_delay_sec': '30', 'effective_delay_sec': '12.5',
        'override': True,
    }


def test_get_delay_uses_the_host_override_target(app, client, auth, streaming):
    with app.app_context():
        from qlsm_addon_demo_stream.stats_hub import (
            set_host_stats_hub_ingest_token, set_host_stats_hub_url)
        host_id = db.session.get(QLInstance, streaming).host_id
        set_host_stats_hub_url(host_id, 'https://other-hub.example/')
        set_host_stats_hub_ingest_token(host_id, 'host-token')
        db.session.commit()
    with patch(GET, return_value=_hub()) as get:
        client.get(f'{URL}/instances/{streaming}/delay', headers=auth)
    assert get.call_args.args[0] == \
        f'https://other-hub.example/api/demo-stream/servers/{SERVER_ID}/delay'
    assert get.call_args.kwargs['headers'] == {'Authorization': 'Bearer host-token'}


def test_get_delay_unknown_instance_404(client, auth):
    assert client.get(f'{URL}/instances/9999/delay', headers=auth).status_code == 404


def test_get_delay_needs_a_login(client, streaming):
    assert client.get(f'{URL}/instances/{streaming}/delay').status_code == 401
    assert client.put(f'{URL}/instances/{streaming}/delay',
                      json={'delay_sec': '5'}).status_code == 401


def test_get_delay_not_streaming_renders_blank_without_calling_the_hub(client, auth, instance_id):
    with patch(GET) as get:
        resp = client.get(f'{URL}/instances/{instance_id}/delay', headers=auth)
        status = client.get(f'{URL}/instances/{instance_id}/delay/status', headers=auth)
    assert resp.status_code == 200
    assert resp.get_json()['data']['delay_sec'] == ''
    assert status.get_json()['data'] == {'ok': False, 'label': 'Stats-hub not configured'}
    get.assert_not_called()


def test_delay_status_says_not_streaming(app, client, auth, streaming):
    with app.app_context():
        from qlsm_addon_demo_stream.settings import set_instance_server_id
        set_instance_server_id(streaming, None)
        db.session.commit()
    with patch(GET) as get:
        resp = client.get(f'{URL}/instances/{streaming}/delay', headers=auth)
        status = client.get(f'{URL}/instances/{streaming}/delay/status', headers=auth)
    assert resp.status_code == 200 and resp.get_json()['data']['delay_sec'] == ''
    assert status.get_json()['data'] == {'ok': False, 'label': 'Not streaming'}
    get.assert_not_called()


def test_delay_status_shows_effective_and_default(client, auth, streaming):
    with patch(GET, return_value=_hub()):
        status = client.get(f'{URL}/instances/{streaming}/delay/status', headers=auth)
    assert status.get_json()['data'] == {'ok': True, 'label': 'Delay 30 s (hub default)'}
    with patch(GET, return_value=_hub(delay=5.0, override=True)):
        status = client.get(f'{URL}/instances/{streaming}/delay/status', headers=auth)
    assert status.get_json()['data'] == {'ok': True, 'label': 'Delay 5 s (hub default 30 s)'}


@pytest.mark.parametrize('hub, label', [
    (dict(return_value=_hub(status=404, body={'detail': 'unknown server_id'})),
     'No route on stats-hub'),
    (dict(return_value=_hub(status=404, body={'detail': 'Not Found'})),
     'Stats-hub has no delay API or no route'),
    (dict(return_value=_hub(status=401, body={'detail': 'unauthorized'})),
     'Ingest token rejected'),
    (dict(side_effect=requests.ConnectionError('hub down')), 'Stats-hub unreachable'),
])
def test_delay_status_never_errors_on_a_hub_failure(client, auth, streaming, hub, label):
    with patch(GET, **hub):
        status = client.get(f'{URL}/instances/{streaming}/delay/status', headers=auth)
    assert status.status_code == 200
    assert status.get_json()['data'] == {'ok': False, 'label': label}


def test_get_delay_hub_failure_is_a_readable_error(client, auth, streaming):
    with patch(GET, side_effect=requests.Timeout('timed out')):
        resp = client.get(f'{URL}/instances/{streaming}/delay', headers=auth)
    assert resp.status_code == 502
    assert 'Could not reach stats-hub' in _message(resp)


# ---- PUT ------------------------------------------------------------------

@pytest.mark.parametrize('sent, to_hub', [
    ('12', 12.0), (' 12.5 ', 12.5), (0, 0.0), (300, 300.0), ('0', 0.0), ('300', 300.0),
    (7.5, 7.5),
])
def test_put_delay_number_goes_to_the_hub(client, auth, streaming, sent, to_hub):
    with patch(PUT, return_value=_hub(delay=to_hub, override=True)) as put:
        resp = client.put(f'{URL}/instances/{streaming}/delay', json={'delay_sec': sent},
                          headers=auth)
    assert resp.status_code == 200
    assert put.call_args.args[0] == HUB_DELAY_URL
    assert put.call_args.kwargs['json'] == {'delay_sec': to_hub}
    assert put.call_args.kwargs['headers'] == {'Authorization': f'Bearer {TOKEN}'}
    assert put.call_args.kwargs['timeout'] == 5
    data = resp.get_json()['data']
    assert data['override'] is True
    assert float(data['delay_sec']) == to_hub


@pytest.mark.parametrize('body', [{'delay_sec': ''}, {'delay_sec': '   '}, {'delay_sec': None}, {}])
def test_put_delay_blank_resets_to_the_hub_default(client, auth, streaming, body):
    with patch(PUT, return_value=_hub()) as put:
        resp = client.put(f'{URL}/instances/{streaming}/delay', json=body, headers=auth)
    assert resp.status_code == 200
    assert put.call_args.kwargs['json'] == {'delay_sec': None}
    assert resp.get_json()['data']['delay_sec'] == ''
    assert 'hub default' in resp.get_json()['message']


@pytest.mark.parametrize('bad', ['-1', '300.1', '301', 'abc', '12s', 'nan', 'inf', -0.5, 1000,
                                 True, [5], {'v': 5}])
def test_put_delay_validates_locally(client, auth, streaming, bad):
    with patch(PUT) as put:
        resp = client.put(f'{URL}/instances/{streaming}/delay', json={'delay_sec': bad},
                          headers=auth)
    assert resp.status_code == 400
    assert _message(resp) == \
        'delay_sec must be a number of seconds from 0 to 300, or blank for the hub default.'
    put.assert_not_called()


def test_put_delay_not_streaming_is_409_with_what_to_do(client, auth, streaming, app):
    with app.app_context():
        from qlsm_addon_demo_stream.settings import set_instance_demo_stream_enabled
        set_instance_demo_stream_enabled(streaming, False)
        db.session.commit()
    with patch(PUT) as put:
        resp = client.put(f'{URL}/instances/{streaming}/delay', json={'delay_sec': '5'},
                          headers=auth)
    assert resp.status_code == 409
    assert 'not streaming yet' in _message(resp)
    assert 'Live Demo Stream' in _message(resp)
    put.assert_not_called()


def test_put_delay_without_stats_hub_is_409(client, auth, instance_id):
    with patch(PUT) as put:
        resp = client.put(f'{URL}/instances/{instance_id}/delay', json={'delay_sec': '5'},
                          headers=auth)
    assert resp.status_code == 409
    assert 'stats-hub URL and ingest token' in _message(resp)
    put.assert_not_called()


@pytest.mark.parametrize('status, body', [(404, {'detail': 'Not Found'}),
                                          (405, {'detail': 'Method Not Allowed'}),
                                          (404, None)])
def test_put_delay_hub_404_names_both_causes(client, auth, streaming, status, body):
    hub = _hub(status=status, body=body)
    if body is None:
        hub.json.side_effect = ValueError('not json')
    with patch(PUT, return_value=hub):
        resp = client.put(f'{URL}/instances/{streaming}/delay', json={'delay_sec': '5'},
                          headers=auth)
    assert resp.status_code == 502
    assert 'older than the per-server delay API' in _message(resp)
    assert f'no demo-stream route for server_id {SERVER_ID}' in _message(resp)


def test_put_delay_hub_unknown_server_id_says_reenable(client, auth, streaming):
    with patch(PUT, return_value=_hub(status=404, body={'detail': 'unknown server_id'})):
        resp = client.put(f'{URL}/instances/{streaming}/delay', json={'delay_sec': '5'},
                          headers=auth)
    assert resp.status_code == 409
    assert f'no demo-stream route for server_id {SERVER_ID}' in _message(resp)
    assert 'Live Demo Stream' in _message(resp)


def test_put_delay_hub_401_names_the_token_setting_and_never_leaks_it(
        client, auth, streaming, caplog):
    with caplog.at_level(logging.DEBUG), \
            patch(PUT, return_value=_hub(status=401, body={'detail': 'bad token'})):
        resp = client.put(f'{URL}/instances/{streaming}/delay', json={'delay_sec': '5'},
                          headers=auth)
    assert resp.status_code == 502
    assert 'Ingest token' in _message(resp)
    assert 'STATS_HUB_INGEST_TOKEN' in _message(resp)
    assert TOKEN not in resp.get_data(as_text=True)
    assert TOKEN not in caplog.text


@pytest.mark.parametrize('status', [400, 422])
def test_put_delay_hub_rejecting_the_value_is_400(client, auth, streaming, status):
    with patch(PUT, return_value=_hub(status=status, body={'detail': 'out of range'})):
        resp = client.put(f'{URL}/instances/{streaming}/delay', json={'delay_sec': '5'},
                          headers=auth)
    assert resp.status_code == 400
    assert f'HTTP {status}' in _message(resp)


@pytest.mark.parametrize('exc', [requests.ConnectionError(f'hub down {TOKEN}'),
                                 requests.Timeout('timed out')])
def test_put_delay_network_error_is_502(client, auth, streaming, caplog, exc):
    with caplog.at_level(logging.DEBUG), patch(PUT, side_effect=exc):
        resp = client.put(f'{URL}/instances/{streaming}/delay', json={'delay_sec': '5'},
                          headers=auth)
    assert resp.status_code == 502
    assert 'Could not reach stats-hub' in _message(resp)
    assert TOKEN not in resp.get_data(as_text=True)
    assert TOKEN not in caplog.text


@pytest.mark.parametrize('hub', [
    _hub(status=500, body={'detail': 'boom'}),
    _hub(body={'ok': True}),
    _hub(body=['not', 'an', 'object']),
    _hub(body={'delay_sec': 'soon', 'default_delay_sec': 30.0, 'override': True}),
])
def test_put_delay_unexpected_hub_answer_is_502(client, auth, streaming, hub):
    with patch(PUT, return_value=hub):
        resp = client.put(f'{URL}/instances/{streaming}/delay', json={'delay_sec': '5'},
                          headers=auth)
    assert resp.status_code == 502
    assert 'stats-hub' in _message(resp)


def test_put_delay_takes_no_lock_changes_no_status_queues_nothing(
        app, client, auth, streaming, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with app.app_context():
        settings_before = {row.key: row.value for row in AppSetting.query.all()}
    with patch(PUT, return_value=_hub(delay=5.0, override=True)), \
            patch('ui.task_lock.acquire_lock') as lock, \
            patch('ui.tasks.enqueue_task') as enqueue, \
            patch('ui.database.update_instance') as update:
        resp = client.put(f'{URL}/instances/{streaming}/delay', json={'delay_sec': '5'},
                          headers=auth)
    assert resp.status_code == 200
    lock.assert_not_called()
    enqueue.assert_not_called()
    update.assert_not_called()
    with app.app_context():
        instance = db.session.get(QLInstance, streaming)
        assert instance.status == InstanceStatus.RUNNING
        assert not instance.logs
        # the delay lives on the hub only: nothing is stored on the qlsm side
        assert {row.key: row.value for row in AppSetting.query.all()} == settings_before
    # server.cfg is not written
    assert not (tmp_path / 'configs').exists()


# ---- review fixes: redirects, strict hub body, round trip, bad body --------

REDIRECTS = [301, 302, 303, 307, 308]


@pytest.mark.parametrize('status', REDIRECTS)
def test_get_delay_does_not_follow_redirects(client, auth, streaming, status):
    with patch(GET, return_value=_hub(status=status, body={})) as get:
        resp = client.get(f'{URL}/instances/{streaming}/delay', headers=auth)
        badge = client.get(f'{URL}/instances/{streaming}/delay/status', headers=auth)
    assert get.call_args.kwargs['allow_redirects'] is False
    assert resp.status_code == 502
    assert 'redirected' in _message(resp)
    assert 'Settings -> Live Demo Stream' in _message(resp)
    assert badge.get_json()['data'] == {'ok': False, 'label': 'Stats-hub redirected the call'}


@pytest.mark.parametrize('status', REDIRECTS)
def test_put_delay_does_not_follow_redirects(client, auth, streaming, status):
    with patch(PUT, return_value=_hub(status=status, body={})) as put:
        resp = client.put(f'{URL}/instances/{streaming}/delay', json={'delay_sec': '5'},
                          headers=auth)
    assert put.call_args.kwargs['allow_redirects'] is False
    assert resp.status_code == 502
    assert 'redirected' in _message(resp)
    assert 'Settings -> Live Demo Stream' in _message(resp)


@pytest.mark.parametrize('sent, hub', [
    ('5', dict(delay=30.0, override=False)),   # hub left it on the default
    ('5', dict(delay=7.0, override=True)),     # hub holds another value
    ('', dict(delay=5.0, override=True)),      # reset did not take
])
def test_put_delay_hub_state_not_matching_the_request_is_502(client, auth, streaming, sent, hub):
    with patch(PUT, return_value=_hub(**hub)):
        resp = client.put(f'{URL}/instances/{streaming}/delay', json={'delay_sec': sent},
                          headers=auth)
    assert resp.status_code == 502
    assert 'did not apply' in _message(resp)


def test_put_delay_accepts_a_hub_value_within_tolerance(client, auth, streaming):
    with patch(PUT, return_value=_hub(delay=5.0000001, override=True)):
        resp = client.put(f'{URL}/instances/{streaming}/delay', json={'delay_sec': '5'},
                          headers=auth)
    assert resp.status_code == 200


@pytest.mark.parametrize('fields', [
    {'override': 'false'}, {'override': 1}, {'override': None},
    {'delay_sec': True}, {'delay_sec': '30'}, {'delay_sec': None},
    {'delay_sec': float('nan')}, {'delay_sec': float('inf')}, {'delay_sec': 10 ** 400},
    {'default_delay_sec': False}, {'default_delay_sec': '30'},
    {'default_delay_sec': float('nan')}, {'default_delay_sec': float('-inf')},
])
def test_hub_body_is_parsed_strictly(client, auth, streaming, fields):
    body = {'ok': True, 'server_id': SERVER_ID, 'delay_sec': 30.0,
            'default_delay_sec': 30.0, 'override': False}
    body.update(fields)
    with patch(GET, return_value=_hub(body=body)):
        resp = client.get(f'{URL}/instances/{streaming}/delay', headers=auth)
        badge = client.get(f'{URL}/instances/{streaming}/delay/status', headers=auth)
    assert resp.status_code == 502
    assert 'does not understand' in _message(resp)
    assert badge.get_json()['data'] == {'ok': False, 'label': 'Unexpected stats-hub answer'}


def test_hub_body_with_integer_seconds_is_fine(client, auth, streaming):
    body = {'delay_sec': 12, 'default_delay_sec': 30, 'override': True}
    with patch(GET, return_value=_hub(body=body)):
        resp = client.get(f'{URL}/instances/{streaming}/delay', headers=auth)
    assert resp.get_json()['data']['delay_sec'] == '12'


@pytest.mark.parametrize('value, shown', [
    (250.1234, '250.1234'), (0.123456789, '0.123456789'), (299.99999, '299.99999'),
    (30.0, '30'), (0.0, '0'), (300.0, '300'), (12.5, '12.5'),
])
def test_untouched_save_writes_back_the_same_value(client, auth, streaming, value, shown):
    with patch(GET, return_value=_hub(delay=value, override=True)):
        loaded = client.get(f'{URL}/instances/{streaming}/delay', headers=auth).get_json()['data']
    assert loaded['delay_sec'] == shown
    with patch(PUT, return_value=_hub(delay=value, override=True)) as put:
        resp = client.put(f'{URL}/instances/{streaming}/delay',
                          json={'delay_sec': loaded['delay_sec']}, headers=auth)
    assert resp.status_code == 200
    assert put.call_args.kwargs['json'] == {'delay_sec': value}


@pytest.mark.parametrize('body', [[1], 5, 'x', True])
def test_put_delay_non_object_body_is_400(client, auth, streaming, body):
    with patch(PUT) as put:
        resp = client.put(f'{URL}/instances/{streaming}/delay', json=body, headers=auth)
    assert resp.status_code == 400
    assert _message(resp) == 'The request body must be a JSON object with delay_sec.'
    put.assert_not_called()
