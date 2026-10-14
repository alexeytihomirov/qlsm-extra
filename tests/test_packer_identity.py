"""qlmatch-packer match-identity.mjs: match_guid and player steam ids for the manifest."""
import json
import subprocess
import shutil
from pathlib import Path

import pytest

from test_packer_no_rclone import _node_ok

MODULE = Path(__file__).resolve().parent.parent / 'addons' / 'qlmatch-packer' / 'assets' / 'match-identity.mjs'

G = '3F2504E0-4F89-41D3-9A0C-0305E82C3301'
G2 = '11111111-2222-4333-8444-555555555555'
S1 = '76561198000000001'
S2 = '76561198000000002'

pytestmark = [pytest.mark.standalone, pytest.mark.skipif(not _node_ok(), reason='node >= 22 required')]


def _run(entries, roster):
    """roster: {clientNum: {name, team}}; entries use plain 'guid' for guidFromGamestate."""
    js_entries = [
        {'clientNum': e['clientNum'], 'index': e.get('index'), 'guidFromGamestate': e.get('guidFromGamestate', '')}
        for e in entries
    ]
    code = (
        f"import {{matchIdentity}} from {json.dumps(MODULE.as_uri())};"
        f"const r = new Map(Object.entries({json.dumps(roster)}).map(([k, v]) => [Number(k), v]));"
        f"console.log(JSON.stringify(matchIdentity({json.dumps(js_entries)}, r)))"
    )
    out = subprocess.run([shutil.which('node'), '--input-type=module', '-e', code],
                         capture_output=True, text=True, check=True).stdout
    return json.loads(out)


ROSTER = {0: {'name': 'a', 'team': '1'}, 1: {'name': 'b', 'team': '2'}}


def test_guid_from_indexes_when_they_agree():
    out = _run([
        {'clientNum': 0, 'index': {'match_guid': G, 'steam_id64': S1}},
        {'clientNum': 1, 'index': {'match_guid': G, 'steam_id64': S2}},
    ], ROSTER)
    assert out['match_guid'] == G.lower()
    assert out['players'] == [
        {'steam_id64': S1, 'name': 'a', 'team': '1', 'client_num': 0},
        {'steam_id64': S2, 'name': 'b', 'team': '2', 'client_num': 1}]


def test_disagreeing_indexes_drop_the_guid_with_a_warning():
    out = _run([
        {'clientNum': 0, 'index': {'match_guid': G, 'steam_id64': S1}},
        {'clientNum': 1, 'index': {'match_guid': G2, 'steam_id64': S2}},
    ], ROSTER)
    assert out['match_guid'] is None and out['warnings']


def test_gamestate_guid_when_no_index_has_one():
    out = _run([
        {'clientNum': 0, 'index': {}, 'guidFromGamestate': G},
        {'clientNum': 1, 'index': None},
    ], ROSTER)
    assert out['match_guid'] == G.lower()


def test_roster_player_without_own_pov_has_null_steam_id():
    roster = dict(ROSTER)
    roster[2] = {'name': 'c', 'team': '2'}
    out = _run([
        {'clientNum': 0, 'index': {'match_guid': G, 'steam_id64': S1}},
        {'clientNum': 1, 'index': {'match_guid': G, 'steam_id64': S2}},
    ], roster)
    assert out['players'][2]['steam_id64'] is None


def test_malformed_values_are_absent():
    out = _run([
        {'clientNum': 0, 'index': {'match_guid': 'not-a-guid', 'steam_id64': '123'}},
    ], ROSTER)
    assert out['match_guid'] is None and out['warnings'] == []
    assert out['players'][0]['steam_id64'] is None


def test_later_gamestate_guid_used_when_first_is_invalid():
    # documented rule: the first VALID guidFromGamestate wins
    out = _run([
        {'clientNum': 0, 'index': None, 'guidFromGamestate': 'garbage'},
        {'clientNum': 1, 'index': None, 'guidFromGamestate': G},
    ], ROSTER)
    assert out['match_guid'] == G.lower()


# ---- end to end: pack.mjs on a synthesized gamestate-only POV set -----------

import zipfile  # noqa: E402

TESTS_DIR = Path(__file__).resolve().parent
PACK_MJS = TESTS_DIR.parent / 'addons' / 'qlmatch-packer' / 'assets' / 'pack.mjs'
MATCH_ID = '20260101T000000Z'


def _pack(tmp_path, extra_args=()):
    spec = {
        'map': 'bloodrun', 'guid': G,
        'povs': [
            # POV 0 knows clients 0 and 2 only; POV 1 knows 0, 1 and 2, so the
            # roster is built in the order 0, 2, 1 (insertion order != client order)
            {'client_num': 0, 'roster': {'0': {'n': 'alpha', 't': '1'}, '2': {'n': 'gamma', 't': '1'}},
             'index': {'match_guid': G, 'steam_id64': S1}},
            {'client_num': 1, 'roster': {'0': {'n': 'alpha', 't': '1'}, '1': {'n': 'beta', 't': '2'},
                                         '2': {'n': 'gamma', 't': '1'}},
             'index': {'match_guid': G, 'steam_id64': S2}},
        ],
    }
    spec_path = tmp_path / 'spec.json'
    spec_path.write_text(json.dumps(spec))
    demo_dir = tmp_path / 'demos'
    demo_dir.mkdir()
    node = shutil.which('node')
    subprocess.run([node, str(TESTS_DIR / 'packer_fixture.mjs'), str(demo_dir), MATCH_ID, str(spec_path)],
                   check=True)
    subprocess.run([node, str(PACK_MJS), '--dir', str(demo_dir), '--match-id', MATCH_ID, *extra_args],
                   check=True, capture_output=True, text=True)
    return demo_dir


def test_pack_end_to_end_manifest_v2_and_unchanged_names(tmp_path):
    demo_dir = _pack(tmp_path)
    pack = demo_dir / f'{MATCH_ID}_bloodrun.qlmatch'
    assert pack.exists()
    manifest = json.loads(zipfile.ZipFile(pack).read('manifest.json'))
    assert manifest['version'] == 2
    assert manifest['match_guid'] == G.lower()
    by_cn = {p['client_num']: p for p in manifest['players']}
    assert by_cn[0]['steam_id64'] == S1 and by_cn[1]['steam_id64'] == S2
    assert by_cn[2]['steam_id64'] is None

    meta = json.loads((demo_dir / f'{MATCH_ID}.meta.json').read_text())
    assert meta['version'] == 1 and meta['match_guid'] == G.lower()
    # original roster insertion order (0, 2, 1) is kept in meta
    assert [(p['name'], p['steam_id64']) for p in meta['players']] == [
        ('alpha', S1), ('gamma', None), ('beta', S2)]


def test_pack_name_template_players_keeps_roster_insertion_order(tmp_path):
    demo_dir = _pack(tmp_path, ['--name-template', '{match_id}_{players}'])
    # before this change: [...roster.values()] order = alpha, gamma, beta
    assert (demo_dir / f'{MATCH_ID}_alpha-gamma-beta.qlmatch').exists()
