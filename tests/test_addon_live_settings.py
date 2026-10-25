"""live-settings addon: the HTTP wiring of the Live Settings tab.

The rcon round trip is patched out (it needs a running engine; the protocol
is covered by the ql-live skill's rcon_query script and qlsm's own service).
What is tested here: the rows come from the plugins' sidecars and the pinned
list with the server.cfg value read from qlsm's copy; an apply sends `set`
for every change, reports the engine's answer per cvar, rewrites server.cfg
and queues core's sync without a restart; the history comes back on GET.
"""
import importlib
import itertools
import json
import sys
from unittest.mock import Mock

import pytest

from ui import db
from ui.models import Host, HostStatus, InstanceStatus, QLInstance
from conftest import auth_headers, make_user

URL = '/api/addons/live-settings'
_NAMES = itertools.count(1)

SIDECAR = {
    'label': 'Item Roulette',
    'cvars': [
        {'cvar': 'qlx_itemRouletteEnabled', 'label': 'Enabled', 'type': 'bool', 'default': False},
        {'cvar': 'qlx_itemRouletteTakeChance', 'label': 'Take chance (%)', 'type': 'number',
         'default': 50, 'min': 0, 'max': 100},
        {'cvar': 'bad name', 'type': 'string'},
    ],
}
CFG = 'set sv_hostname "duel"\nset qlx_itemRouletteEnabled "1"\nset qlx_itemRouletteTakeChance "25"\nset timelimit 15\n'


@pytest.fixture
def addon_id():
    return 'live-settings'


@pytest.fixture
def auth(app):
    make_user(app, 'liveop', 'pw')
    return auth_headers(app, 'liveop')


def _backend():
    # The registry loads backend.py *as* the addon's package module (see
    # qlsm's ui/addons/registry.py), so this is the object the routes run in.
    return sys.modules['qlsm_addon_live_settings']


def _rcon():
    return importlib.import_module('qlsm_addon_live_settings.rcon_client')


@pytest.fixture
def enabled(app):
    from ui.addons import get_addon
    with app.app_context():
        get_addon('live-settings', app).ctx.settings.set_enabled('global', 0, True)


@pytest.fixture
def workdir(tmp_path, monkeypatch):
    """Run from an empty directory so configs/ and data/ land in tmp, and
    point the manifest pool at a tmp dir holding one sidecar."""
    monkeypatch.chdir(tmp_path)
    import ui.plugin_manifest as pm
    pool = tmp_path / 'pool'
    pool.mkdir()
    (pool / 'item_roulette.ql-plugin.json').write_text(json.dumps(SIDECAR), encoding='utf-8')
    for const in ('MINQLX_PLUGINS_POOL_DIR', 'MINQLXTENDED_PLUGINS_POOL_DIR',
                  'MINQLX_OPERATOR_POOL_DIR', 'MINQLXTENDED_OPERATOR_POOL_DIR'):
        monkeypatch.setattr(pm, const, str(pool))
    return tmp_path


def _make_instance(app, workdir, cfg_text=CFG, status=InstanceStatus.RUNNING, pinned=None):
    with app.app_context():
        n = next(_NAMES)
        host = Host(name=f'live{n}', ip_address=f'10.0.2.{n}', provider='vultr',
                    status=HostStatus.ACTIVE, runtime='minqlxtended')
        db.session.add(host)
        db.session.flush()
        inst = QLInstance(name=f'srv {n}', port=27960, hostname='duel', host_id=host.id,
                          status=status, qlx_plugins='essentials, item_roulette',
                          zmq_rcon_port=28960, zmq_rcon_password='rc-secret')
        db.session.add(inst)
        db.session.commit()
        if cfg_text is not None:
            cfg_dir = workdir / 'configs' / host.name / str(inst.id)
            cfg_dir.mkdir(parents=True)
            (cfg_dir / 'server.cfg').write_text(cfg_text, encoding='utf-8', newline='')
        if pinned:
            from ui.addons import get_addon
            get_addon('live-settings', app).ctx.settings.set(
                'instance', inst.id, {'pinned_cvars': pinned})
        return inst.id


def _reply(**values):
    """What the patched rcon returns: {lower name: entry} the way
    cvar_reply.parse_cvar_lines builds it."""
    found, lines = {}, []
    for name, (value, default, latched) in values.items():
        raw = f'"{name}" is:"{value}^7" default:"{default}^7"'
        if latched is not None:
            raw += f' latched:"{latched}"'
        found[name.lower()] = {'name': name, 'value': value, 'default': default,
                               'latched': latched, 'raw': raw}
        lines.append(raw)
    return found, lines


# ---- access -------------------------------------------------------------

def test_requires_auth(client, app, workdir):
    iid = _make_instance(app, workdir)
    assert client.get(f'{URL}/instances/{iid}/cvars').status_code == 401


def test_disabled_addon_refuses(client, auth, app, workdir):
    iid = _make_instance(app, workdir)
    assert client.get(f'{URL}/instances/{iid}/cvars', headers=auth).status_code == 403


def test_unknown_instance_is_404(client, auth, enabled, workdir):
    assert client.get(f'{URL}/instances/9999/cvars', headers=auth).status_code == 404


# ---- listing ------------------------------------------------------------

def test_rows_come_from_sidecars_and_pinned_with_cfg_and_live_values(client, auth, enabled, app, workdir, monkeypatch):
    iid = _make_instance(app, workdir, pinned='timelimit, g_password')
    monkeypatch.setattr(_backend(), 'query_cvars', lambda target, names: _reply(
        qlx_itemRouletteEnabled=('1', '0', None),
        qlx_itemRouletteTakeChance=('25', '50', None),
        timelimit=('15', '0', None),
    ))

    resp = client.get(f'{URL}/instances/{iid}/cvars', headers=auth)
    assert resp.status_code == 200
    data = resp.get_json()['data']
    assert data['rcon']['ok'] is True
    groups = {g['id']: g for g in data['groups']}
    assert list(groups) == ['plugin:item_roulette', 'pinned']
    assert groups['plugin:item_roulette']['label'] == 'Item Roulette'
    rows = {c['name']: c for c in groups['plugin:item_roulette']['cvars']}
    assert set(rows) == {'qlx_itemRouletteEnabled', 'qlx_itemRouletteTakeChance'}  # bad name dropped
    chance = rows['qlx_itemRouletteTakeChance']
    assert chance['type'] == 'number' and chance['min'] == 0 and chance['max'] == 100
    assert chance['default'] == '50'
    assert chance['cfg'] == '25' and chance['live'] == '25' and chance['reported'] is True
    assert rows['qlx_itemRouletteEnabled']['default'] == '0'
    pinned = {c['name']: c for c in groups['pinned']['cvars']}
    assert pinned['timelimit']['cfg'] == '15' and pinned['timelimit']['live'] == '15'
    assert pinned['g_password']['cfg'] is None and pinned['g_password']['reported'] is False
    assert data['history'] == []


def test_stopped_instance_lists_rows_without_live_values(client, auth, enabled, app, workdir):
    iid = _make_instance(app, workdir, status=InstanceStatus.STOPPED)
    data = client.get(f'{URL}/instances/{iid}/cvars', headers=auth).get_json()['data']
    assert data['rcon']['ok'] is False
    assert 'not running' in data['rcon']['error']
    rows = {c['name']: c for c in data['groups'][0]['cvars']}
    assert rows['qlx_itemRouletteTakeChance']['cfg'] == '25'
    assert rows['qlx_itemRouletteTakeChance']['live'] is None


def test_rcon_error_is_reported_not_raised(client, auth, enabled, app, workdir, monkeypatch):
    iid = _make_instance(app, workdir)

    def boom(target, names):
        raise _rcon().RconError('Server is offline or unreachable.')
    monkeypatch.setattr(_backend(), 'query_cvars', boom)
    data = client.get(f'{URL}/instances/{iid}/cvars', headers=auth).get_json()['data']
    assert data['rcon'] == {**data['rcon'], 'ok': False, 'error': 'Server is offline or unreachable.'}


# ---- apply --------------------------------------------------------------

@pytest.fixture
def queued(monkeypatch):
    """Core's lock and queue, patched: no Redis in this suite."""
    backend = _backend()
    import ui.task_lock
    import ui.tasks
    calls = {'enqueue': [], 'locks': []}
    monkeypatch.setattr(ui.task_lock, 'acquire_lock', lambda *a, **k: calls['locks'].append(a) or True)
    monkeypatch.setattr(ui.task_lock, 'release_lock', lambda *a, **k: None)

    def fake_enqueue(func, *args, **kwargs):
        calls['enqueue'].append((func, args, kwargs))
        return Mock(id='job-1')
    monkeypatch.setattr(ui.tasks, 'enqueue_task', fake_enqueue)
    return calls


def test_apply_sets_reads_back_writes_cfg_and_queues_sync(client, auth, enabled, app, workdir, monkeypatch, queued):
    iid = _make_instance(app, workdir)
    sent = []

    def fake_set(target, changes):
        sent.extend(changes)
        assert target.ip == f'10.0.2.{iid}' or target.ip.startswith('10.0.2.')
        assert target.port == 28960
        return _reply(qlx_itemRouletteTakeChance=('30', '50', None),
                      sv_maxclients=('16', '24', '20'))
    monkeypatch.setattr(_backend(), 'set_cvars', fake_set)

    resp = client.post(f'{URL}/instances/{iid}/cvars/apply', headers=auth, json={
        'changes': [{'name': 'qlx_itemRouletteTakeChance', 'value': '30'},
                    {'name': 'sv_maxclients', 'value': '20'}],
        'persist': True,
    })
    assert resp.status_code == 200, resp.get_json()
    data = resp.get_json()['data']
    assert sent == [('qlx_itemRouletteTakeChance', '30'), ('sv_maxclients', '20')]
    by_name = {e['name']: e for e in data['entries']}
    assert by_name['qlx_itemRouletteTakeChance']['state'] == 'live'
    assert by_name['qlx_itemRouletteTakeChance']['reply'] == '"qlx_itemRouletteTakeChance" is:"30^7" default:"50^7"'
    assert by_name['sv_maxclients']['state'] == 'latched'
    assert by_name['sv_maxclients']['latched'] == '20'

    persist = data['persist_result']
    assert persist['ok'] is True and persist['job_id'] == 'job-1'
    assert '-set qlx_itemRouletteTakeChance "25"' in persist['diff']
    assert '+set qlx_itemRouletteTakeChance "30"' in persist['diff']
    assert '+set sv_maxclients "20"' in persist['diff']

    with app.app_context():
        inst = db.session.get(QLInstance, iid)
        cfg = (workdir / 'configs' / inst.host.name / str(iid) / 'server.cfg').read_text(encoding='utf-8')
        assert inst.status == InstanceStatus.CONFIGURING
    assert cfg == 'set sv_hostname "duel"\nset qlx_itemRouletteEnabled "1"\nset qlx_itemRouletteTakeChance "30"\nset timelimit 15\nset sv_maxclients "20"\n'

    (func, args, kwargs), = queued['enqueue']
    assert func.__name__ == 'apply_instance_config'
    assert args == (iid,)
    assert kwargs['restart'] is False
    assert kwargs['previous_status'] == 'running'
    assert kwargs['lock_token']
    assert queued['locks'][0][:2] == ('instance', iid)

    history = client.get(f'{URL}/instances/{iid}/cvars?live=0', headers=auth).get_json()['data']['history']
    assert len(history) == 1 and history[0]['entries'][0]['name'] == 'qlx_itemRouletteTakeChance'
    assert history[0]['persist_result']['diff'] == persist['diff']


def test_apply_without_persist_leaves_cfg_alone(client, auth, enabled, app, workdir, monkeypatch, queued):
    iid = _make_instance(app, workdir)
    monkeypatch.setattr(_backend(), 'set_cvars',
                        lambda target, changes: _reply(timelimit=('20', '0', None)))
    resp = client.post(f'{URL}/instances/{iid}/cvars/apply', headers=auth, json={
        'changes': [{'name': 'timelimit', 'value': '20'}], 'persist': False,
    })
    assert resp.status_code == 200
    data = resp.get_json()['data']
    assert data['persist'] is False and data['persist_result'] is None
    assert queued['enqueue'] == []
    with app.app_context():
        inst = db.session.get(QLInstance, iid)
        cfg = (workdir / 'configs' / inst.host.name / str(iid) / 'server.cfg').read_text(encoding='utf-8')
        assert inst.status == InstanceStatus.RUNNING
    assert cfg == CFG


def test_apply_with_unchanged_cfg_values_queues_nothing(client, auth, enabled, app, workdir, monkeypatch, queued):
    iid = _make_instance(app, workdir)
    monkeypatch.setattr(_backend(), 'set_cvars',
                        lambda target, changes: _reply(qlx_itemRouletteTakeChance=('25', '50', None)))
    resp = client.post(f'{URL}/instances/{iid}/cvars/apply', headers=auth, json={
        'changes': [{'name': 'qlx_itemRouletteTakeChance', 'value': '25'}],
    })
    assert resp.status_code == 200
    assert resp.get_json()['data']['persist_result']['unchanged'] is True
    assert queued['enqueue'] == []


def test_apply_when_instance_is_busy_keeps_values_live_only(client, auth, enabled, app, workdir, monkeypatch, queued):
    iid = _make_instance(app, workdir)
    import ui.task_lock
    monkeypatch.setattr(ui.task_lock, 'acquire_lock', lambda *a, **k: False)
    monkeypatch.setattr(_backend(), 'set_cvars',
                        lambda target, changes: _reply(timelimit=('20', '0', None)))
    data = client.post(f'{URL}/instances/{iid}/cvars/apply', headers=auth, json={
        'changes': [{'name': 'timelimit', 'value': '20'}],
    }).get_json()['data']
    assert data['entries'][0]['state'] == 'live'
    assert data['persist_result']['ok'] is False
    assert 'Another operation' in data['persist_result']['skipped']
    assert queued['enqueue'] == []


def test_apply_refuses_bad_input_and_stopped_instance(client, auth, enabled, app, workdir, monkeypatch):
    iid = _make_instance(app, workdir)
    bad = client.post(f'{URL}/instances/{iid}/cvars/apply', headers=auth,
                      json={'changes': [{'name': 'rm -rf', 'value': '1'}]})
    assert bad.status_code == 400
    empty = client.post(f'{URL}/instances/{iid}/cvars/apply', headers=auth, json={'changes': []})
    assert empty.status_code == 400

    stopped = _make_instance(app, workdir, status=InstanceStatus.STOPPED)
    resp = client.post(f'{URL}/instances/{stopped}/cvars/apply', headers=auth,
                       json={'changes': [{'name': 'timelimit', 'value': '20'}]})
    assert resp.status_code == 409
    assert 'not running' in resp.get_json()['error']['message']


def test_apply_strips_quotes_and_reports_no_reply(client, auth, enabled, app, workdir, monkeypatch, queued):
    iid = _make_instance(app, workdir)
    sent = []
    monkeypatch.setattr(_backend(), 'set_cvars', lambda target, changes: (sent.extend(changes), ({}, []))[1])
    data = client.post(f'{URL}/instances/{iid}/cvars/apply', headers=auth, json={
        'changes': [{'name': 'g_password', 'value': 'a"b\nc'}], 'persist': False,
    }).get_json()['data']
    assert sent == [('g_password', 'abc')]
    assert data['entries'][0]['state'] == 'no_reply'


# ---- pinned -------------------------------------------------------------

def test_pinned_list_is_validated_and_stored(client, auth, enabled, app, workdir):
    iid = _make_instance(app, workdir)
    ok = client.put(f'{URL}/instances/{iid}/pinned', headers=auth,
                    json={'cvars': ['timelimit', ' fraglimit ', 'TIMELIMIT']})
    assert ok.status_code == 200
    assert ok.get_json()['data']['cvars'] == ['timelimit', 'fraglimit']

    bad = client.put(f'{URL}/instances/{iid}/pinned', headers=auth, json={'cvars': ['a b']})
    assert bad.status_code == 400

    data = client.get(f'{URL}/instances/{iid}/cvars?live=0', headers=auth).get_json()['data']
    pinned = [c['name'] for c in data['groups'][-1]['cvars']]
    assert pinned == ['timelimit', 'fraglimit']
