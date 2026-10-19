"""telemetry-relay 1.8.0: a new instance gets telemetry and the live demo
stream before its first deploy, under ONE server ID, with no apply and no
restart (qlsm `instance.created` + the Add Instance form's Stats Hub tab).

Both addons are installed here: the point is the hand-off between them.
Core dispatches demo-stream before telemetry-relay, so telemetry-relay's
handler reserves the ID and then runs demo-stream's set-up, which takes that
ID instead of reserving its own.
"""
import importlib
import itertools
from pathlib import Path
from unittest.mock import Mock

import pytest

from ui import db
from ui.models import Host, HostStatus, QLInstance
from conftest import auth_headers, make_user



def _core_has_instance_created():
    try:
        return 'instance.created' in importlib.import_module('ui.addons.hooks').HOOK_SCOPES
    except ImportError:
        return True  # no qlsm checkout at all: conftest skips with its own reason


pytestmark = pytest.mark.skipif(
    not _core_has_instance_created(),
    reason='qlsm without the instance.created hook (upstream-pr/add-instance-addon-hook)',
)

HUB = 'https://hub.example'
_NAMES = itertools.count(1)


@pytest.fixture
def addon_id():
    return ('demo-stream', 'telemetry-relay')


@pytest.fixture(autouse=True)
def in_tmp(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)


def _tele(name):
    return importlib.import_module(f'qlsm_addon_telemetry_relay.{name}')


def _demo(name):
    return importlib.import_module(f'qlsm_addon_demo_stream.{name}')


@pytest.fixture
def hub(monkeypatch):
    """Records every server ID reservation and demo-stream route; the
    telemetry side hands out 41, 42, ...; demo-stream reserving one at all
    is the bug this file is about, so it fails the test."""
    calls = {'reserved': [], 'routes': []}
    ids = itertools.count(41)

    def reserve(label, host_id):
        calls['reserved'].append(label)
        return next(ids)

    def demo_reserve(label, host_id):
        calls['reserved'].append(f'demo-stream:{label}')
        return 900

    monkeypatch.setattr(_tele('new_instance'), 'reserve_server_id', reserve)
    monkeypatch.setattr(_demo('instance_ops'), 'reserve_server_id', demo_reserve)
    monkeypatch.setattr(_demo('instance_ops'), '_register_route',
                        lambda host_id, server_id, name, token: calls['routes'].append(server_id))
    return calls


@pytest.fixture
def queued(monkeypatch):
    import ui.tasks
    calls = []
    monkeypatch.setattr(ui.tasks, 'enqueue_task',
                        lambda task, *args, **kwargs: calls.append((task, args)) or Mock(id='job-1'))
    return calls


def _setup(app, relay=True, tunnel=True, auto=True, demo_on=True, demo_hub=HUB):
    """Both addons on globally, hub configured for both, relay and tunnel as
    asked. Returns a function making an instance on that host."""
    with app.app_context():
        from ui.addons import get_addon
        n = next(_NAMES)
        host = Host(name=f'new{n}', ip_address=f'10.0.2.{n}', provider='vultr',
                    status=HostStatus.ACTIVE)
        db.session.add(host)
        db.session.commit()
        ts = _tele('settings')
        ts.set_stats_hub_url(HUB)
        ts.set_stats_hub_ingest_token('tok')
        ts.set_relay_enabled(host.id, relay)
        ts.set_auto_enable_new_instances(auto)
        ds = _demo('settings')
        ds.set_relay_host('relay.example')
        ds.set_relay_port('27999')
        ds.set_stats_hub_url(demo_hub)
        ds.set_stats_hub_ingest_token('tok')
        ds.set_host_tunnel_enabled(host.id, tunnel)
        db.session.commit()
        get_addon('telemetry-relay').ctx.settings.set_enabled('global', 0, True)
        get_addon('demo-stream').ctx.settings.set_enabled('global', 0, demo_on)
        host_id, host_name = host.id, host.name

    def make_instance(cfg='set sv_hostname "duel"\n'):
        with app.app_context():
            inst = QLInstance(name=f'duel {next(_NAMES)}', port=27960, hostname='duel',
                              host_id=host_id)
            db.session.add(inst)
            db.session.commit()
            path = Path('configs') / host_name / str(inst.id) / 'server.cfg'
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(cfg, encoding='utf-8')
            return inst.id
    return make_instance


def _created(app, iid, options=None):
    with app.app_context():
        from ui.addons import dispatch
        dispatch('instance.created', iid, iid, options or {})


def _launch_args(app, iid):
    with app.app_context():
        from ui.addons import dispatch
        return dispatch('instance.launch_args', iid, iid)


def _logs(app, iid):
    with app.app_context():
        return db.session.get(QLInstance, iid).logs or ''


def test_auto_enable_gives_both_features_one_server_id_and_no_restart(app, hub, queued):
    iid = _setup(app)(cfg='set sv_hostname "duel"\nset sv_demoStream "0"\n')
    _created(app, iid)

    assert len(hub['reserved']) == 1 and not hub['reserved'][0].startswith('demo-stream:')
    assert hub['routes'] == [41]
    args = _launch_args(app, iid)
    assert '+set qlx_statsHubUnifiedEnabled "1"' in args
    assert '+set qlx_statsHubServerId "41"' in args
    assert '+set sv_demoStream "1"' in args
    with app.app_context():
        assert _demo('settings').get_instance_server_id(iid) == 41
        assert _tele('settings').get_instance_server_id(iid) == 41
    # Only the relay's route push is queued -- no apply, no restart.
    assert [task.__name__ for task, _ in queued] == ['push_host_relay_routes']
    # The stale stream line the preset brought is gone; +set carries it now.
    with app.app_context():
        inst = db.session.get(QLInstance, iid)
        cfg = (Path('configs') / inst.host.name / str(iid) / 'server.cfg').read_text(encoding='utf-8')
    assert cfg == 'set sv_hostname "duel"\n'
    assert 'telemetry on, server ID 41' in _logs(app, iid)
    assert 'live demo stream on, server ID 41.' in _logs(app, iid)


def test_setting_off_and_no_tab_values_leaves_the_instance_alone(app, hub, queued):
    iid = _setup(app, auto=False)()
    _created(app, iid)
    assert hub['reserved'] == [] and queued == []
    assert _launch_args(app, iid) == []


def test_tab_values_override_the_setting(app, hub, queued):
    iid = _setup(app, auto=False)()
    _created(app, iid, {'telemetry': True, 'demo_stream': False, 'server_id': ''})
    assert len(hub['reserved']) == 1
    assert hub['routes'] == []
    assert _launch_args(app, iid) == [
        '+set qlx_statsHubUnifiedEnabled "1"', '+set qlx_statsHubServerId "41"']


def test_a_manual_server_id_is_used_instead_of_reserving(app, hub, queued):
    iid = _setup(app)()
    _created(app, iid, {'telemetry': True, 'demo_stream': True, 'server_id': ' 77 '})
    assert hub['reserved'] == []
    assert hub['routes'] == [77]
    assert '+set qlx_statsHubServerId "77"' in _launch_args(app, iid)


def test_a_malformed_manual_server_id_is_reported_and_replaced(app, hub, queued):
    iid = _setup(app)()
    _created(app, iid, {'telemetry': True, 'demo_stream': False, 'server_id': 'abc'})
    assert len(hub['reserved']) == 1
    assert 'server ID "abc" is not a positive whole number' in _logs(app, iid)


def test_stream_only_still_reserves_one_id_through_telemetry(app, hub, queued):
    """Telemetry off but the stream on: the ID is reserved (and kept) by
    telemetry-relay, so a later telemetry enable reuses the same one."""
    iid = _setup(app)()
    _created(app, iid, {'telemetry': False, 'demo_stream': True})
    assert len(hub['reserved']) == 1 and not hub['reserved'][0].startswith('demo-stream:')
    assert hub['routes'] == [41]
    with app.app_context():
        assert _tele('settings').get_instance_server_id(iid) is None
        assert _tele('settings').get_reserved_server_id(iid) == 41


def test_relay_off_on_the_host_degrades_with_a_note(app, hub, queued):
    iid = _setup(app, relay=False)()
    _created(app, iid)
    assert queued == []
    assert '+set qlx_statsHubUnifiedEnabled "1"' not in _launch_args(app, iid)
    assert 'enable the Telemetry Relay on host' in _logs(app, iid)
    # the stream still goes out under the reserved ID
    assert hub['routes'] == [41]


def test_no_tunnel_on_the_host_degrades_with_a_note(app, hub, queued):
    iid = _setup(app, tunnel=False)()
    _created(app, iid)
    assert hub['routes'] == []
    assert 'enable the Demo Stream Tunnel on host' in _logs(app, iid)
    assert '+set qlx_statsHubServerId "41"' in _launch_args(app, iid)


def test_demo_stream_switched_off_globally_is_reported(app, hub, queued):
    iid = _setup(app, demo_on=False)()
    _created(app, iid)
    assert hub['routes'] == []
    assert 'Live Demo Stream addon is switched off' in _logs(app, iid)


def test_a_different_demo_stream_hub_gets_its_own_id(app, hub, queued):
    iid = _setup(app, demo_hub='https://other-hub.example')()
    _created(app, iid)
    assert hub['reserved'][-1].startswith('demo-stream:')
    assert 'its own stats-hub, so its own server ID' in _logs(app, iid)


def test_add_instance_defaults_follow_the_setting(app, client):
    _setup(app, auto=True)
    make_user(app, 'telop', 'pw')
    headers = auth_headers(app, 'telop')
    resp = client.get('/api/addons/telemetry-relay/add-instance?host_id=1', headers=headers)
    assert resp.get_json()['data'] == {'telemetry': True, 'demo_stream': True, 'server_id': ''}

    resp = client.put('/api/addons/telemetry-relay/stats-hub', headers=headers, json={
        'url': HUB, 'ingest_token': 'tok', 'auto_enable_new_instances': False})
    assert resp.get_json()['data']['auto_enable_new_instances'] is False
    resp = client.get('/api/addons/telemetry-relay/add-instance?host_id=1', headers=headers)
    assert resp.get_json()['data']['telemetry'] is False

    resp = client.put('/api/addons/telemetry-relay/stats-hub', headers=headers, json={
        'url': HUB, 'ingest_token': 'tok', 'auto_enable_new_instances': 'yes'})
    assert resp.status_code == 400


def test_create_request_reaches_the_handler_before_the_deploy(app, client, hub, monkeypatch):
    """End to end through core's POST /api/instances/: the tab's values
    reach telemetry-relay, and by the time the deploy is queued the launch
    args already carry the server ID."""
    import ui.routes.instance_routes as routes
    _setup(app, auto=False)
    with app.app_context():
        host_id = Host.query.order_by(Host.id.desc()).first().id
    seen = []

    def enqueue(task, *args, **kwargs):
        if getattr(task, '__name__', '') == 'deploy_instance':
            seen.append(_launch_args(app, args[0]))
        return Mock(id='job-1')
    monkeypatch.setattr(routes, 'enqueue_task', enqueue)
    monkeypatch.setattr(routes, 'acquire_lock', lambda *a, **k: True)
    import ui.tasks
    monkeypatch.setattr(ui.tasks, 'enqueue_task', lambda *a, **k: Mock(id='job-2'))
    make_user(app, 'telop', 'pw')
    resp = client.post('/api/instances/', headers=auth_headers(app, 'telop'), json={
        'name': 'fresh', 'host_id': host_id, 'port': 27960, 'hostname': 'fresh',
        'configs': {'server.cfg': '', 'mappool.txt': '', 'access.txt': '', 'workshop.txt': ''},
        'addon_options': {'telemetry-relay': {'telemetry': True, 'demo_stream': True}},
    })
    assert resp.status_code == 201, resp.get_json()
    assert len(seen) == 1
    assert '+set qlx_statsHubServerId "41"' in seen[0]
    assert '+set sv_demoStream "1"' in seen[0]
    assert len(hub['reserved']) == 1
