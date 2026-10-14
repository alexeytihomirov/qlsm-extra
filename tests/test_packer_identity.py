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
