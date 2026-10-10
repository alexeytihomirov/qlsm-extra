"""The per-match labels the Demos listing carries: "{match_id}.meta.json"
files (written by qlmatch-packer's pack.mjs) and the engine-filename fallback.

What matters here is the contract an operator relies on:
- a pack whose name came from qlx_qlmatchNameTemplate still lands in its
  match, because its meta claims it by name;
- the directory listing alone decides what exists - a meta never brings a
  deleted file back, and an orphaned meta is simply ignored;
- metas are read in ONE remote exec, and not at all once cached;
- a broken or unreadable meta costs the labels, never the listing.
"""
import json
import stat
from unittest.mock import MagicMock, patch

import paramiko
import pytest

FETCH_MODULE = 'qlsm_addon_demo_management.ansible_instance_demos'
META_MODULE = 'qlsm_addon_demo_management.demo_meta'
TRANSPORT_MODULE = 'qlsm_addon_demo_management.instance_demo_transport'
ADDON = '/api/addons/demo-management'

MATCH = '20260917T174655Z'
POV_A = f'{MATCH}_bloodrun_p0_alex_1789667191_1.dm_91'
POV_B = f'{MATCH}_bloodrun_p1_steemorol__69pixels_1789667191_2.dm_91'
PACK = 'duel_alex-vs-steemorol_bloodrun.qlmatch'  # templated: no match id
META = {
    'format': 'qlsm-demo-meta', 'version': 1, 'match_id': MATCH,
    'map': 'bloodrun', 'gametype': 'duel', 'duration_ms': 600000,
    'players': [{'name': 'alex', 'team': '0'}, {'name': 'steemorol', 'team': '0'}],
    'povs': [
        {'file': POV_A, 'client_num': 0, 'name': 'alex'},
        {'file': POV_B, 'client_num': 1, 'name': 'steemorol'},
    ],
    'pack': PACK,
}


@pytest.fixture
def addon_id():
    return 'demo-management'


@pytest.fixture
def meta_mod(app):
    import importlib
    return importlib.import_module(META_MODULE)


@pytest.fixture
def fake_redis(monkeypatch, meta_mod):
    """A dict-backed stand-in for the shared Redis client."""
    store = {}
    client = MagicMock()
    client.mget.side_effect = lambda keys: [store.get(k) for k in keys]

    def pipeline(transaction=False):
        pipe = MagicMock()
        pipe.set.side_effect = lambda k, v, ex=None: store.__setitem__(k, v)
        return pipe
    client.pipeline.side_effect = pipeline
    monkeypatch.setattr(meta_mod, '_redis', lambda: client)
    return store


@pytest.fixture
def no_redis(monkeypatch, meta_mod):
    monkeypatch.setattr(meta_mod, '_redis', lambda: None)


# ---- pure helpers ------------------------------------------------------

def test_started_at_comes_from_the_match_id(meta_mod):
    assert meta_mod.started_at_from_match_id(MATCH) == '2026-09-17T17:46:55Z'
    assert meta_mod.started_at_from_match_id('20261399T000000Z') is None
    assert meta_mod.started_at_from_match_id('nope') is None


def test_parse_meta_rejects_anything_that_is_not_this_matchs_meta(meta_mod):
    good = json.dumps(META).encode()
    assert meta_mod.parse_meta(good, MATCH)['pack'] == PACK
    assert meta_mod.parse_meta(good, '20260101T000000Z') is None
    assert meta_mod.parse_meta(b'{not json', MATCH) is None
    assert meta_mod.parse_meta(json.dumps({**META, 'format': 'other'}).encode(), MATCH) is None
    assert meta_mod.parse_meta(json.dumps({**META, 'version': 99}).encode(), MATCH) is None


def test_annotate_ties_a_templated_pack_to_its_match_through_the_meta(meta_mod):
    demos = [{'name': n, 'size': 1, 'mtime': 1.0} for n in (POV_A, POV_B, PACK)]
    infos = meta_mod.annotate(demos, {MATCH: meta_mod.parse_meta(json.dumps(META), MATCH)})

    by_name = {d['name']: d for d in demos}
    assert by_name[PACK]['match_id'] == MATCH
    assert by_name[PACK]['kind'] == 'pack'
    assert by_name[PACK]['started_at'] == '2026-09-17T17:46:55Z'
    assert by_name[POV_B]['pov'] == {'slot': 1, 'player': 'steemorol'}
    assert infos[MATCH]['source'] == 'meta'
    assert infos[MATCH]['gametype'] == 'duel'
    assert infos[MATCH]['duration_ms'] == 600000


def test_annotate_falls_back_to_the_engine_filename_without_a_meta(meta_mod):
    demos = [
        {'name': POV_B, 'size': 1, 'mtime': 1.0},
        {'name': PACK, 'size': 1, 'mtime': 1.0},
        {'name': '20260916-234252_slot00_Input.dm_91', 'size': 1, 'mtime': 1.0},
    ]
    infos = meta_mod.annotate(demos, {})

    pov, pack, plain = demos
    assert pov['match_id'] == MATCH and pov['map'] == 'bloodrun'
    # Underscores in the sanitised name come back as spaces, the two trailing
    # numeric segment tokens are dropped.
    assert pov['pov'] == {'slot': 1, 'player': 'steemorol  69pixels'}
    assert 'match_id' not in pack  # nothing ties a templated name to a match
    assert 'match_id' not in plain
    assert infos == {MATCH: {
        'match_id': MATCH, 'started_at': '2026-09-17T17:46:55Z', 'map': 'bloodrun',
        'gametype': None, 'duration_ms': None, 'players': [{'name': 'steemorol  69pixels', 'team': ''}], 'source': 'filename',
    }}


def test_a_meta_never_brings_back_a_file_the_listing_no_longer_has(meta_mod):
    """POV_A and the pack were deleted on the host; the meta still names them."""
    demos = [{'name': POV_B, 'size': 1, 'mtime': 1.0}]
    meta_mod.annotate(demos, {MATCH: meta_mod.parse_meta(json.dumps(META), MATCH)})
    assert [d['name'] for d in demos] == [POV_B]


# ---- remote read -------------------------------------------------------

def _attr(name, size=10, mtime=1.0):
    entry = paramiko.SFTPAttributes()
    entry.filename = name
    entry.st_size = size
    entry.st_mtime = mtime
    entry.st_mode = stat.S_IFREG | 0o644
    return entry


def _ssh(listing, exec_output=b'', exec_error=None):
    sftp = MagicMock()
    sftp.listdir_attr.return_value = listing
    client = MagicMock()
    client.open_sftp.return_value = sftp
    if exec_error:
        client.exec_command.side_effect = exec_error
    else:
        stdout = MagicMock()
        stdout.read.return_value = exec_output
        stdout.channel.recv_exit_status.return_value = 0
        client.exec_command.return_value = (MagicMock(), stdout, MagicMock())
    return client


def _list(client, contributed=('qlmatch', 'replay.json.gz')):
    from qlsm_addon_demo_management.ansible_instance_demos import list_instance_listing
    with patch(f'{FETCH_MODULE}.dispatch', return_value=list(contributed)), \
         patch(f'{FETCH_MODULE}.resolve_instance_and_host',
               return_value=(MagicMock(port=27960), MagicMock(name='h', ssh_port=22,
                                                              ssh_key_path='/k', ssh_user='u'), None)), \
         patch(f'{TRANSPORT_MODULE}.rcon_target_for_host', return_value='10.0.0.1'), \
         patch(f'{TRANSPORT_MODULE}.paramiko.SSHClient', return_value=client):
        return list_instance_listing(1)


LISTING = [_attr(POV_A), _attr(POV_B), _attr(PACK), _attr(f'{MATCH}.meta.json', 500, 2.0)]
EXEC_OUT = f'{MATCH}.meta.json\0'.encode() + json.dumps(META).encode() + b'\0'


def test_metas_are_read_in_one_exec_and_never_listed_as_demos(app, fake_redis):
    client = _ssh(LISTING, EXEC_OUT)
    with app.test_request_context():
        success, listing, error = _list(client)

    assert success and error is None
    assert client.exec_command.call_count == 1
    assert sorted(d['name'] for d in listing['demos']) == sorted([POV_A, POV_B, PACK])
    pack = next(d for d in listing['demos'] if d['name'] == PACK)
    assert pack['match_id'] == MATCH
    assert listing['infos'][MATCH]['source'] == 'meta'
    assert listing['timing']['meta_read'] == 1
    assert {'connect_ms', 'listdir_ms', 'meta_ms', 'total_ms'} <= set(listing['timing'])


def test_a_cached_meta_is_not_read_again(app, fake_redis):
    with app.test_request_context():
        _list(_ssh(LISTING, EXEC_OUT))
        client = _ssh(LISTING, b'')
        success, listing, _ = _list(client)

    assert success
    client.exec_command.assert_not_called()
    assert listing['timing']['meta_cached'] == 1
    assert next(d for d in listing['demos'] if d['name'] == PACK)['match_id'] == MATCH


def test_a_rewritten_meta_is_read_again(app, fake_redis):
    """The cache key carries size+mtime, so a full rebuild's new meta wins."""
    with app.test_request_context():
        _list(_ssh(LISTING, EXEC_OUT))
        changed = LISTING[:3] + [_attr(f'{MATCH}.meta.json', 501, 3.0)]
        client = _ssh(changed, EXEC_OUT)
        _list(client)
    assert client.exec_command.call_count == 1


def test_an_unreadable_meta_costs_the_labels_not_the_listing(app, no_redis):
    client = _ssh(LISTING, exec_error=paramiko.SSHException('channel closed'))
    with app.test_request_context():
        success, listing, error = _list(client)

    assert success and error is None
    assert sorted(d['name'] for d in listing['demos']) == sorted([POV_A, POV_B, PACK])
    assert listing['infos'][MATCH]['source'] == 'filename'


def test_the_endpoint_puts_the_match_info_on_its_group(app, client, no_redis):
    from conftest import auth_headers, make_user
    from ui import db
    from ui.models import Host, HostStatus, InstanceStatus, QLInstance

    make_user(app, 'op', 'pw')
    headers = auth_headers(app, 'op')
    with app.app_context():
        host = Host(name='h', ip_address='10.0.0.1', provider='vultr', status=HostStatus.ACTIVE,
                    ssh_key_path='/k', ssh_user='u')
        db.session.add(host)
        db.session.flush()
        inst = QLInstance(name='i', port=27960, hostname='i', host_id=host.id, status=InstanceStatus.RUNNING)
        db.session.add(inst)
        db.session.commit()
        instance_id = inst.id

    ssh = _ssh(LISTING, EXEC_OUT)
    with patch(f'{FETCH_MODULE}.dispatch', return_value=['qlmatch']), \
         patch(f'{TRANSPORT_MODULE}.rcon_target_for_host', return_value='10.0.0.1'), \
         patch(f'{TRANSPORT_MODULE}.paramiko.SSHClient', return_value=ssh), \
         patch('ui.addons.dispatch', return_value=[]):
        resp = client.get(f'{ADDON}/instances/{instance_id}/demos', headers=headers)

    assert resp.status_code == 200
    groups = resp.get_json()['data']['matches']
    assert len(groups) == 1
    assert sorted(groups[0]['member_names']) == sorted([POV_A, POV_B, PACK])
    assert groups[0]['info']['gametype'] == 'duel'
    assert groups[0]['info']['players'][0]['name'] == 'alex'
