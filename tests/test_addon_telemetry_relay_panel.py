"""telemetry-relay addon 1.5.0: Telemetry is an instance menu entry with a
"Send telemetry" switch (no server_id field), and switching it off works.

The switch reads qlx_statsHubUnifiedEnabled from the instance's server.cfg;
`PUT instances/{id}` queues the enable or the disable depending on what
changed. The disable keeps the reserved server ID so a re-enable gets the
same one.
"""
import importlib
import itertools
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from ui import db
from ui.models import Host, HostStatus, InstanceStatus, QLInstance
from conftest import ADDONS_DIR, auth_headers, make_user

URL = '/api/addons/telemetry-relay'
_NAMES = itertools.count(1)
ON_CFG = 'set sv_hostname "duel"\nset qlx_statsHubUnifiedEnabled "1"\nset qlx_statsHubServerId "12"\n'
OFF_CFG = 'set sv_hostname "duel"\nset qlx_statsHubUnifiedEnabled "0"\nset qlx_statsHubServerId "12"\n'


@pytest.fixture
def addon_id():
    return 'telemetry-relay'


@pytest.fixture
def auth(app):
    make_user(app, 'telop', 'pw')
    return auth_headers(app, 'telop')


def _settings():
    return importlib.import_module('qlsm_addon_telemetry_relay.settings')


def _ops():
    return importlib.import_module('qlsm_addon_telemetry_relay.instance_ops')


def _make_instance(app, cfg_text=None, server_id=None, relay=True, status=InstanceStatus.RUNNING):
    """An instance on its own host; hub and relay set up; server.cfg written
    when cfg_text is given; server_id stored when given."""
    with app.app_context():
        n = next(_NAMES)
        host = Host(name=f'tele{n}', ip_address=f'10.0.1.{n}', provider='vultr',
                    status=HostStatus.ACTIVE)
        db.session.add(host)
        db.session.flush()
        inst = QLInstance(name=f'duel {n}', port=27960, hostname='duel', host_id=host.id,
                          status=status)
        db.session.add(inst)
        db.session.commit()
        s = _settings()
        s.set_stats_hub_url('https://hub.example')
        s.set_stats_hub_ingest_token('tok')
        s.set_relay_enabled(host.id, relay)
        if server_id:
            s.set_instance_server_id(inst.id, server_id)
        db.session.commit()
        if cfg_text is not None:
            cfg = Path('configs') / host.name / str(inst.id) / 'server.cfg'
            cfg.parent.mkdir(parents=True, exist_ok=True)
            cfg.write_text(cfg_text, encoding='utf-8')
        return inst.id


def _cfg_text(app, iid):
    with app.app_context():
        inst = db.session.get(QLInstance, iid)
        return (Path('configs') / inst.host.name / str(iid) / 'server.cfg').read_text(encoding='utf-8')


@pytest.fixture(autouse=True)
def in_tmp(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)


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


def _task_names(calls):
    return [getattr(task, '__name__', str(task)) for task, _, _ in calls]


# ---- GET ------------------------------------------------------------------

def test_get_instance_enabled_from_cfg(app, client, auth):
    on = _make_instance(app, ON_CFG, server_id=12)
    off = _make_instance(app, OFF_CFG, server_id=12)
    missing = _make_instance(app)
    for iid, expected in ((on, True), (off, False), (missing, False)):
        resp = client.get(f'{URL}/instances/{iid}', headers=auth)
        assert resp.status_code == 200
        assert resp.get_json()['data'] == {'enabled': expected}


# ---- PUT ------------------------------------------------------------------

def test_put_enable_queues_enable(app, client, auth, queued):
    iid = _make_instance(app, OFF_CFG, server_id=None)
    resp = client.put(f'{URL}/instances/{iid}', json={'enabled': True}, headers=auth)
    assert resp.status_code == 202, resp.get_json()
    assert _task_names(queued) == ['enable_instance_telemetry_task']
    assert queued[0][1] == (iid,) and queued[0][2]['previous_status'] == 'running'
    with app.app_context():
        assert db.session.get(QLInstance, iid).status == InstanceStatus.CONFIGURING


def test_put_enable_refused_while_relay_off(app, client, auth, queued):
    iid = _make_instance(app, OFF_CFG, relay=False)
    resp = client.put(f'{URL}/instances/{iid}', json={'enabled': True}, headers=auth)
    assert resp.status_code == 409
    assert queued == []


def test_put_disable_queues_disable(app, client, auth, queued):
    iid = _make_instance(app, ON_CFG, server_id=12)
    resp = client.put(f'{URL}/instances/{iid}', json={'enabled': False}, headers=auth)
    assert resp.status_code == 202, resp.get_json()
    assert _task_names(queued) == ['disable_instance_telemetry_task']
    assert queued[0][2]['previous_status'] == 'running'


def test_put_no_change_200(app, client, auth, queued):
    on = _make_instance(app, ON_CFG, server_id=12)
    off = _make_instance(app, OFF_CFG, server_id=None)
    for iid, enabled in ((on, True), (off, False)):
        resp = client.put(f'{URL}/instances/{iid}', json={'enabled': enabled}, headers=auth)
        assert resp.status_code == 200
        assert resp.get_json()['message'] == 'No changes.'
    assert queued == []


@pytest.mark.parametrize('stored, cfg', [
    (None, ON_CFG),                                   # no stored server ID
    (13, ON_CFG),                                     # cfg ID differs from the stored one
    (12, 'set qlx_statsHubUnifiedEnabled "1"\n'),     # no server ID in cfg
])
def test_put_enabled_with_drift_queues_enable(app, client, auth, queued, stored, cfg):
    iid = _make_instance(app, cfg, server_id=stored)
    resp = client.put(f'{URL}/instances/{iid}', json={'enabled': True}, headers=auth)
    assert resp.status_code == 202
    assert _task_names(queued) == ['enable_instance_telemetry_task']


def test_put_while_busy_409(app, client, auth, queued):
    iid = _make_instance(app, ON_CFG, server_id=12, status=InstanceStatus.RESTARTING)
    resp = client.put(f'{URL}/instances/{iid}', json={'enabled': False}, headers=auth)
    assert resp.status_code == 409
    assert queued == []


@pytest.mark.parametrize('body', [{'enabled': 'false'}, {'enabled': 0}, {}, ['x']])
def test_put_enabled_must_be_bool(app, client, auth, queued, body):
    iid = _make_instance(app, ON_CFG, server_id=12)
    resp = client.put(f'{URL}/instances/{iid}', json=body, headers=auth)
    assert resp.status_code == 400
    assert queued == []


def test_old_enable_route_still_queues_enable(app, client, auth, queued):
    iid = _make_instance(app, OFF_CFG)
    resp = client.post(f'{URL}/instances/{iid}/enable', json={}, headers=auth)
    assert resp.status_code == 202
    assert _task_names(queued) == ['enable_instance_telemetry_task']


# ---- disable logic --------------------------------------------------------

def test_disable_keeps_server_id(app, queued, monkeypatch):
    ops = _ops()
    pushes = []

    def push(host_id):
        # the route is gone by the time the relay config is pushed
        pushes.append(_settings().get_instance_server_id(iid))
        return True
    monkeypatch.setattr(ops, 'push_relay_config_logic', push)
    iid = _make_instance(app, ON_CFG, server_id=12, status=InstanceStatus.CONFIGURING)

    with app.app_context():
        ok, message = ops.disable_instance_telemetry_logic(iid, previous_status='running')
        assert ok, message
        s = _settings()
        assert s.get_instance_server_id(iid) is None          # no relay route
        assert s.get_reserved_server_id(iid) == 12             # ID kept
    assert pushes == [None]
    text = _cfg_text(app, iid)
    assert 'set qlx_statsHubUnifiedEnabled "0"' in text
    assert 'set qlx_statsHubServerId "12"' in text
    assert 'set sv_hostname "duel"' in text
    assert [kw.get('restart') for _, _, kw in queued] == [True]

    # the config_applied sync after the apply does not undo it
    monkeypatch.setattr(ops, 'push_relay_config_logic', lambda host_id: pushes.append('sync') or True)
    with app.app_context():
        ops.sync_instance_server_id_from_config(db.session.get(QLInstance, iid))
        assert _settings().get_reserved_server_id(iid) == 12
    assert pushes == [None]

    # re-enable takes the same ID without asking the hub
    monkeypatch.setattr(ops, 'push_relay_config_logic', lambda host_id: True)
    monkeypatch.setattr(ops, 'reserve_server_id', Mock(side_effect=AssertionError('reserved again')))
    with app.app_context():
        ok, message = ops.enable_instance_telemetry_logic(iid)
        assert ok, message
        assert _settings().get_instance_server_id(iid) == 12
    assert 'set qlx_statsHubUnifiedEnabled "1"' in _cfg_text(app, iid)


def test_disable_relay_push_failure_still_applies(app, queued, monkeypatch):
    ops = _ops()
    monkeypatch.setattr(ops, 'push_relay_config_logic', lambda host_id: False)
    iid = _make_instance(app, ON_CFG, server_id=12, status=InstanceStatus.CONFIGURING)
    with app.app_context():
        ok, message = ops.disable_instance_telemetry_logic(iid, previous_status='running')
    assert ok and 'relay' in message
    assert len(queued) == 1


def test_instance_delete_forgets_reserved_id(app):
    iid = _make_instance(app, ON_CFG, server_id=12)
    with app.app_context():
        from ui.addons.registry import dispatch
        s = _settings()
        assert s.get_reserved_server_id(iid) == 12
        dispatch('instance.delete', iid, iid)
        db.session.commit()
        assert s.get_instance_server_id(iid) is None
        assert s.get_reserved_server_id(iid) is None


# ---- status ---------------------------------------------------------------

@pytest.mark.parametrize('cfg, stored, relay, ok, label', [
    (ON_CFG, 12, True, True, 'Server ID 12, relay on'),
    (OFF_CFG, None, True, False, 'Off'),
    (ON_CFG, 12, False, False, 'Relay off on host'),
])
def test_status_labels(app, client, auth, cfg, stored, relay, ok, label):
    iid = _make_instance(app, cfg, server_id=stored, relay=relay)
    resp = client.get(f'{URL}/instances/{iid}/status', headers=auth)
    assert resp.status_code == 200
    assert resp.get_json()['data'] == {'ok': ok, 'label': label}


# ---- manifest -------------------------------------------------------------

def test_manifest_telemetry_in_instance_menu():
    m = json.loads((ADDONS_DIR / 'telemetry-relay' / 'qlsm-addon.json').read_text(encoding='utf-8'))
    assert m['version'] == '1.5.0'
    ui = m['ui']
    assert 'instance_tabs' not in ui
    (entry,) = ui['instance_menu']
    assert (entry['id'], entry['label']) == ('telemetry', 'Telemetry')
    assert entry['status'] == 'GET instances/{instance_id}/status'
    panel = ui['panels'][entry['panel']]
    assert (panel['load'], panel['submit']) == ('GET instances/{instance_id}',
                                                'PUT instances/{instance_id}')
    assert [(f['key'], f['type'], f['label']) for f in panel['fields']] == [
        ('enabled', 'bool', 'Send telemetry')]
    assert 'server_id' not in json.dumps(panel)

    (host_entry,) = ui['host_menu']
    assert host_entry['status'] == 'GET hosts/{host_id}/status'
    host_keys = [f['key'] for f in ui['panels'][host_entry['panel']]['fields']]
    assert host_keys == ['enabled', 'url_override', 'ingest_token_override']
