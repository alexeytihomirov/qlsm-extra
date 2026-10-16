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
        assert resp.get_json()['data'] == {'enabled': expected, 'new_server_id': False}


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
    assert m['version'] == '1.6.0'
    ui = m['ui']
    assert 'instance_tabs' not in ui
    (entry,) = ui['instance_menu']
    assert (entry['id'], entry['label']) == ('telemetry', 'Telemetry')
    assert entry['status'] == 'GET instances/{instance_id}/status'
    panel = ui['panels'][entry['panel']]
    assert (panel['load'], panel['submit']) == ('GET instances/{instance_id}',
                                                'PUT instances/{instance_id}')
    assert [(f['key'], f['type'], f['label']) for f in panel['fields']] == [
        ('enabled', 'bool', 'Send telemetry'),
        ('new_server_id', 'bool', 'Reserve a new server ID')]
    assert panel['fields'][1]['default'] is False

    (host_entry,) = ui['host_menu']
    assert host_entry['status'] == 'GET hosts/{host_id}/status'
    host_keys = [f['key'] for f in ui['panels'][host_entry['panel']]['fields']]
    assert host_keys == ['enabled', 'url_override', 'ingest_token_override', 'forward_url']


# ---- instances enabled before 1.5.0 (routed key only) ---------------------

def _legacy_instance(app, cfg_text, server_id=12):
    """Only the pre-1.5.0 routed row `stats_hub_server_id:<id>`, no reserved key."""
    from ui.models import AppSetting
    iid = _make_instance(app, cfg_text)
    with app.app_context():
        db.session.add(AppSetting(key=f'stats_hub_server_id:{iid}', value=str(server_id)))
        db.session.commit()
        assert AppSetting.query.get(f'stats_hub_reserved_server_id:{iid}') is None
    return iid


def test_legacy_id_survives_disable_then_enable(app, queued, monkeypatch):
    ops = _ops()
    monkeypatch.setattr(ops, 'push_relay_config_logic', lambda host_id: True)
    reserve = Mock(side_effect=AssertionError('reserved again'))
    monkeypatch.setattr(ops, 'reserve_server_id', reserve)
    iid = _legacy_instance(app, ON_CFG)
    with app.app_context():
        assert ops.disable_instance_telemetry_logic(iid)[0]
        assert _settings().get_instance_server_id(iid) is None
        ok, message = ops.enable_instance_telemetry_logic(iid)
        assert ok, message
        assert _settings().get_instance_server_id(iid) == 12
    reserve.assert_not_called()
    assert 'set qlx_statsHubServerId "12"' in _cfg_text(app, iid)


def test_legacy_id_survives_hand_disable(app, queued, monkeypatch):
    """Switched off in the Plugins tab: the config_applied sync clears the
    routed key; the ID moves to the reserved key and the enable reuses it."""
    from ui.models import AppSetting
    ops = _ops()
    monkeypatch.setattr(ops, 'push_relay_config_logic', lambda host_id: True)
    reserve = Mock(side_effect=AssertionError('reserved again'))
    monkeypatch.setattr(ops, 'reserve_server_id', reserve)
    iid = _legacy_instance(app, OFF_CFG)
    with app.app_context():
        ops.sync_instance_server_id_from_config(db.session.get(QLInstance, iid))
        assert _settings().get_instance_server_id(iid) is None
        assert AppSetting.query.get(f'stats_hub_reserved_server_id:{iid}').value == '12'
        ok, message = ops.enable_instance_telemetry_logic(iid)
        assert ok, message
        assert _settings().get_instance_server_id(iid) == 12
    reserve.assert_not_called()


def test_backfill_copies_routed_ids_once(app):
    from ui.models import AppSetting
    legacy = _legacy_instance(app, ON_CFG, server_id=21)
    current = _make_instance(app, ON_CFG, server_id=22)
    with app.app_context():
        s = _settings()
        s.set_reserved_server_id(current, 30)   # already recorded: left alone
        db.session.add(AppSetting(key='stats_hub_server_id:junk', value='5'))
        db.session.commit()
        assert s.backfill_reserved_server_ids() == 1
        db.session.commit()
        assert AppSetting.query.get(f'stats_hub_reserved_server_id:{legacy}').value == '21'
        assert s.get_reserved_server_id(current) == 30
        assert AppSetting.query.get('stats_hub_reserved_server_id:junk') is None
        assert s.backfill_reserved_server_ids() == 0


def test_status_enabled_without_server_id(app, client, auth):
    iid = _make_instance(app, ON_CFG, server_id=None)
    resp = client.get(f'{URL}/instances/{iid}/status', headers=auth)
    assert resp.get_json()['data'] == {'ok': False, 'label': 'On, no server ID yet; save to repair'}


# ---- new server ID (1.5.1) ------------------------------------------------

@pytest.mark.parametrize('cfg', [ON_CFG, OFF_CFG])
def test_put_new_server_id_queues_enable_with_the_flag(app, client, auth, queued, cfg):
    iid = _make_instance(app, cfg, server_id=12)
    resp = client.put(f'{URL}/instances/{iid}', json={'enabled': True, 'new_server_id': True},
                      headers=auth)
    assert resp.status_code == 202, resp.get_json()
    assert _task_names(queued) == ['enable_instance_telemetry_task']
    assert queued[0][1] == (iid,) and queued[0][2]['new_server_id'] is True
    assert resp.get_json()['data'] == {'enabled': True, 'new_server_id': False}


def test_put_plain_enable_does_not_ask_for_a_new_id(app, client, auth, queued):
    iid = _make_instance(app, OFF_CFG, server_id=12)
    resp = client.put(f'{URL}/instances/{iid}', json={'enabled': True, 'new_server_id': False},
                      headers=auth)
    assert resp.status_code == 202
    assert queued[0][2].get('new_server_id', False) is False


@pytest.mark.parametrize('cfg', [ON_CFG, OFF_CFG])
def test_put_new_server_id_while_switching_off_409(app, client, auth, queued, cfg):
    iid = _make_instance(app, cfg, server_id=12)
    resp = client.put(f'{URL}/instances/{iid}', json={'enabled': False, 'new_server_id': True},
                      headers=auth)
    assert resp.status_code == 409
    assert 'Switch telemetry on' in resp.get_json()['error']['message']
    assert queued == []


def test_put_new_server_id_must_be_bool(app, client, auth, queued):
    iid = _make_instance(app, ON_CFG, server_id=12)
    resp = client.put(f'{URL}/instances/{iid}', json={'enabled': True, 'new_server_id': 'yes'},
                      headers=auth)
    assert resp.status_code == 400
    assert queued == []


def test_put_new_server_id_while_busy_409(app, client, auth, queued):
    iid = _make_instance(app, ON_CFG, server_id=12, status=InstanceStatus.RESTARTING)
    resp = client.put(f'{URL}/instances/{iid}', json={'enabled': True, 'new_server_id': True},
                      headers=auth)
    assert resp.status_code == 409
    assert queued == []


def test_new_server_id_is_never_stored(app, client, auth, queued):
    from ui.models import AppSetting
    iid = _make_instance(app, ON_CFG, server_id=12)
    with app.app_context():
        before = {r.key: r.value for r in AppSetting.query.all()}
    client.put(f'{URL}/instances/{iid}', json={'enabled': True, 'new_server_id': True}, headers=auth)
    with app.app_context():
        after = {r.key: r.value for r in AppSetting.query.all()}
    assert after == before
    assert client.get(f'{URL}/instances/{iid}', headers=auth).get_json()['data'] == {
        'enabled': True, 'new_server_id': False}


DUP_CFG = ('set sv_hostname "duel"\nset qlx_statsHubUnifiedEnabled "1"\n'
           'set qlx_statsHubServerId "12"\nset sv_demoStream "1"\nset qlx_statsHubServerId "12"\n')


def test_enable_with_new_server_id_reserves_a_fresh_one(app, queued, monkeypatch):
    ops = _ops()
    monkeypatch.setattr(ops, 'push_relay_config_logic', lambda host_id: True)
    reserve = Mock(return_value=44)
    monkeypatch.setattr(ops, 'reserve_server_id', reserve)
    iid = _make_instance(app, DUP_CFG, server_id=12, status=InstanceStatus.CONFIGURING)
    with app.app_context():
        ok, message = ops.enable_instance_telemetry_logic(
            iid, previous_status='running', new_server_id=True)
        assert ok, message
        s = _settings()
        assert s.get_instance_server_id(iid) == 44
        assert s.get_reserved_server_id(iid) == 44
    reserve.assert_called_once()
    assert 'server_id=44' in message and '12' in message
    text = _cfg_text(app, iid)
    assert text.count('qlx_statsHubServerId') == 1
    assert 'set qlx_statsHubServerId "44"' in text
    assert [kw.get('restart') for _, _, kw in queued] == [True]


def test_enable_with_new_server_id_while_off_reserves_a_fresh_one(app, queued, monkeypatch):
    ops = _ops()
    monkeypatch.setattr(ops, 'push_relay_config_logic', lambda host_id: True)
    reserve = Mock(return_value=45)
    monkeypatch.setattr(ops, 'reserve_server_id', reserve)
    iid = _make_instance(app, OFF_CFG, server_id=12, status=InstanceStatus.CONFIGURING)
    with app.app_context():
        assert ops.disable_instance_telemetry_logic(iid)[0]
        ok, message = ops.enable_instance_telemetry_logic(iid, new_server_id=True)
        assert ok, message
        assert _settings().get_instance_server_id(iid) == 45
        assert _settings().get_reserved_server_id(iid) == 45
    reserve.assert_called_once()
    assert 'set qlx_statsHubServerId "45"' in _cfg_text(app, iid)


def test_new_server_id_message_mentions_the_demo_stream(app, queued, monkeypatch):
    from ui.models import AppSetting
    ops = _ops()
    monkeypatch.setattr(ops, 'push_relay_config_logic', lambda host_id: True)
    monkeypatch.setattr(ops, 'reserve_server_id', Mock(return_value=46))
    iid = _make_instance(app, ON_CFG, server_id=12, status=InstanceStatus.CONFIGURING)
    with app.app_context():
        db.session.add(AppSetting(key=f'demo_stream_enabled:{iid}', value='1'))
        db.session.commit()
        ok, message = ops.enable_instance_telemetry_logic(iid, new_server_id=True)
    assert ok and 'Live Demo Stream' in message


def test_new_server_id_reserve_failure_keeps_the_old_id(app, queued, monkeypatch):
    import requests
    ops = _ops()
    monkeypatch.setattr(ops, 'push_relay_config_logic', lambda host_id: True)
    monkeypatch.setattr(ops, 'reserve_server_id', Mock(side_effect=requests.ConnectionError('down')))
    iid = _make_instance(app, ON_CFG, server_id=12, status=InstanceStatus.CONFIGURING)
    with app.app_context():
        ok, message = ops.enable_instance_telemetry_logic(iid, previous_status='running',
                                                          new_server_id=True)
        assert ok is False and 'Could not reserve' in message
        assert _settings().get_instance_server_id(iid) == 12
    assert queued == []


# ---- server.cfg upsert ----------------------------------------------------

def test_upsert_leaves_one_line_per_cvar():
    s = _settings()
    text = ('set a "1"\nset qlx_statsHubServerId "1"\nset b "2"\n'
            'set qlx_statsHubServerId "1"\n  seta qlx_statsHubUnifiedEnabled 0\n')
    out = s.upsert_cvars_in_text(text, {'qlx_statsHubServerId': '9',
                                        'qlx_statsHubUnifiedEnabled': '1', 'new': 'x'})
    assert out == ('set a "1"\nset b "2"\nset qlx_statsHubServerId "9"\n'
                   '  set qlx_statsHubUnifiedEnabled "1"\nset new "x"\n')
    assert s.upsert_cvars_in_text('set qlx_statsHubServerId "1"\n', {'qlx_statsHubServerId': '1'}) \
        == 'set qlx_statsHubServerId "1"\n'


@pytest.mark.parametrize('line', [
    'seta qlx_statsHubUnifiedEnabled "0"',
    'seta qlx_statsHubUnifiedEnabled 0',
    'set qlx_statsHubUnifiedEnabled 0',
    'set qlx_statsHubUnifiedEnabled "0" // switched off by hand',
    'set   qlx_statsHubUnifiedEnabled\t"0"',
])
def test_upsert_then_read_round_trips(line):
    s = _settings()
    text = f'set sv_hostname "duel"\n{line}\n'
    assert s.read_cvars_from_text(text, ['qlx_statsHubUnifiedEnabled']) == {
        'qlx_statsHubUnifiedEnabled': '0'}
    out = s.upsert_cvars_in_text(text, {'qlx_statsHubUnifiedEnabled': '1'})
    assert out == 'set sv_hostname "duel"\nset qlx_statsHubUnifiedEnabled "1"\n'
    assert s.read_cvars_from_text(out, ['qlx_statsHubUnifiedEnabled']) == {
        'qlx_statsHubUnifiedEnabled': '1'}
    assert s.strip_cvars_from_text(text, ['qlx_statsHubUnifiedEnabled']) == 'set sv_hostname "duel"\n'


def test_upsert_leaves_similar_names_and_comments_alone():
    s = _settings()
    text = ('// set qlx_statsHubServerId "5"\n'
            'set qlx_statsHubServerIdX "5"\n'
            'set qlx_statsHubServerId "5" // old\n'
            '// seta qlx_statsHubServerId 6\n')
    out = s.upsert_cvars_in_text(text, {'qlx_statsHubServerId': '9'})
    assert out == ('// set qlx_statsHubServerId "5"\n'
                   'set qlx_statsHubServerIdX "5"\n'
                   'set qlx_statsHubServerId "9"\n'
                   '// seta qlx_statsHubServerId 6\n')
    assert s.read_cvars_from_text(out, ['qlx_statsHubServerId', 'qlx_statsHubServerIdX']) == {
        'qlx_statsHubServerId': '9', 'qlx_statsHubServerIdX': '5'}
    assert s.strip_cvars_from_text(out, ['qlx_statsHubServerId']) == (
        '// set qlx_statsHubServerId "5"\nset qlx_statsHubServerIdX "5"\n'
        '// seta qlx_statsHubServerId 6\n')


def test_seta_off_cfg_is_read_as_off_and_enabled_once(app, client, auth, queued):
    """A hand-written `seta ... 0` is seen as off; after the enable writes
    `set ... "1"` a save finds nothing to repair."""
    iid = _make_instance(app, 'seta qlx_statsHubUnifiedEnabled 0\nseta qlx_statsHubServerId 12\n',
                         server_id=12)
    assert client.get(f'{URL}/instances/{iid}', headers=auth).get_json()['data']['enabled'] is False
    with app.app_context():
        inst = db.session.get(QLInstance, iid)
        cfg = Path('configs') / inst.host.name / str(iid) / 'server.cfg'
    cfg.write_text(_settings().upsert_cvars_in_text(
        cfg.read_text(encoding='utf-8'), {'qlx_statsHubUnifiedEnabled': '1',
                                          'qlx_statsHubServerId': '12'}), encoding='utf-8')
    resp = client.put(f'{URL}/instances/{iid}', json={'enabled': True}, headers=auth)
    assert resp.status_code == 200 and resp.get_json()['message'] == 'No changes.'
    assert queued == []


# ---- new server ID guard: the form keeps the box ticked -------------------

def _reserved_minutes_ago(app, iid, minutes):
    from datetime import timedelta
    with app.app_context():
        s = _settings()
        s.set_new_server_id_at(iid, s.utcnow() - timedelta(minutes=minutes))
        db.session.commit()


def test_put_new_server_id_again_within_ten_minutes_409(app, client, auth, queued):
    iid = _make_instance(app, ON_CFG, server_id=12)
    _reserved_minutes_ago(app, iid, 3)
    resp = client.put(f'{URL}/instances/{iid}', json={'enabled': True, 'new_server_id': True},
                      headers=auth)
    assert resp.status_code == 409
    assert resp.get_json()['error']['message'] == (
        'A new server ID was reserved a few minutes ago; reopen the panel.')
    assert queued == []


def test_put_new_server_id_after_ten_minutes_queues_again(app, client, auth, queued):
    iid = _make_instance(app, ON_CFG, server_id=12)
    _reserved_minutes_ago(app, iid, 11)
    resp = client.put(f'{URL}/instances/{iid}', json={'enabled': True, 'new_server_id': True},
                      headers=auth)
    assert resp.status_code == 202, resp.get_json()
    assert queued[0][2]['new_server_id'] is True


def test_plain_save_is_not_blocked_by_the_guard(app, client, auth, queued):
    iid = _make_instance(app, ON_CFG, server_id=12)
    _reserved_minutes_ago(app, iid, 1)
    resp = client.put(f'{URL}/instances/{iid}', json={'enabled': True, 'new_server_id': False},
                      headers=auth)
    assert resp.status_code == 200 and resp.get_json()['message'] == 'No changes.'


def test_enable_with_new_server_id_records_the_time_and_delete_forgets_it(app, queued, monkeypatch):
    from datetime import timedelta
    ops = _ops()
    monkeypatch.setattr(ops, 'push_relay_config_logic', lambda host_id: True)
    monkeypatch.setattr(ops, 'reserve_server_id', Mock(return_value=47))
    iid = _make_instance(app, ON_CFG, server_id=12, status=InstanceStatus.CONFIGURING)
    with app.app_context():
        s = _settings()
        assert s.get_new_server_id_at(iid) is None
        assert ops.enable_instance_telemetry_logic(iid)[0]          # plain enable: nothing recorded
        assert s.get_new_server_id_at(iid) is None
        assert ops.enable_instance_telemetry_logic(iid, new_server_id=True)[0]
        when = s.get_new_server_id_at(iid)
        assert when is not None and s.utcnow() - when < timedelta(minutes=1)
        from ui.addons.registry import dispatch
        dispatch('instance.delete', iid, iid)
        db.session.commit()
        assert s.get_new_server_id_at(iid) is None
