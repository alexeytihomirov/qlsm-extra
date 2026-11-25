"""qlmatch-packer pack.mjs: a multi-POV capture (engine sv_demoMultiPov 1) is published as
<name>.dm_91 + <name>.meta.json (version 2), never as a .qlmatch."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from test_packer_no_rclone import _node_ok

pytestmark = [pytest.mark.standalone, pytest.mark.skipif(not _node_ok(), reason='node >= 22 required')]

TESTS_DIR = Path(__file__).resolve().parent
PACK_MJS = TESTS_DIR.parent / 'addons' / 'qlmatch-packer' / 'assets' / 'pack.mjs'
MATCH_ID = '20261120T025005Z'
G = '5fba1c75-35ee-4790-92ac-b09854cd77d9'
S1 = '76561197999064274'
S2 = '76561198253037119'
MULTI_STEM = f'{MATCH_ID}_bloodrun_multipov_1795142965_1'

ROSTER = {
    '0': {'n': 'Input.Frontier', 't': '0', 'st': S1},
    '1': {'n': 'T.club', 't': '0', 'st': S2},
    '2': {'n': 'bot', 't': '0', 'st': '90071996842377218'},
    '8': {'n': 'multipov', 't': '3'},
}


def _write(demo_dir, spec):
    spec_path = demo_dir.parent / f'spec-{len(list(demo_dir.parent.glob("spec-*")))}.json'
    spec_path.write_text(json.dumps(spec))
    subprocess.run([shutil.which('node'), str(TESTS_DIR / 'packer_fixture.mjs'), str(demo_dir), MATCH_ID,
                    str(spec_path)], check=True)


def _pack(demo_dir, *extra):
    return subprocess.run([shutil.which('node'), str(PACK_MJS), '--dir', str(demo_dir), '--match-id', MATCH_ID,
                           *extra], capture_output=True, text=True)


def _multipov():
    return {'client_num': 8, 'stem': MULTI_STEM, 'roster': ROSTER, 'index': {'match_guid': G}}


@pytest.fixture
def demo_dir(tmp_path):
    d = tmp_path / 'demos'
    d.mkdir()
    return d


def _files(demo_dir):
    return sorted(p.relative_to(demo_dir).as_posix() for p in demo_dir.rglob('*') if p.is_file())


def test_multipov_capture_is_published_as_dm91_with_meta_v2(demo_dir):
    _write(demo_dir, {'map': 'bloodrun', 'guid': G, 'maxclients': 8, 'povs': [_multipov()]})
    out = _pack(demo_dir)
    assert out.returncode == 0, out.stderr
    name = f'{MATCH_ID}_bloodrun'
    assert _files(demo_dir) == sorted([
        f'{MATCH_ID}.meta.json', f'{name}.dm_91', f'{name}.meta.json', f'index/{name}.snaps.json',
        f'{MATCH_ID}_bloodrun.replay.json.gz'])

    meta = json.loads((demo_dir / f'{name}.meta.json').read_text())
    assert meta['format'] == 'qlsm-demo-meta' and meta['version'] == 2
    assert meta['match_id'] == MATCH_ID and meta['map'] == 'bloodrun' and meta['gametype'] == 'duel'
    assert meta['match_guid'] == G
    assert meta['duration_ms'] == 59000
    assert meta['window'] == {'start_server_time': 1000, 'end_server_time': 61000, 'game_start_server_time': 2000}
    assert meta['pack'] == f'{name}.dm_91'
    assert meta['written_at']
    assert meta['players'] == [
        {'client_num': 0, 'name': 'Input.Frontier', 'team': '0', 'steam_id64': S1},
        {'client_num': 1, 'name': 'T.club', 'team': '0', 'steam_id64': S2},
        {'client_num': 2, 'name': 'bot', 'team': '0', 'steam_id64': None},
    ]

    v1 = json.loads((demo_dir / f'{MATCH_ID}.meta.json').read_text())
    assert v1['version'] == 1 and v1['pack'] == f'{name}.dm_91'
    assert v1['povs'] == [{'file': f'{name}.dm_91', 'client_num': 8, 'name': 'multipov'}]
    assert [p['steam_id64'] for p in v1['players']] == [S1, S2, None]


def test_published_file_is_recognised_again_on_a_rerun(demo_dir):
    _write(demo_dir, {'map': 'bloodrun', 'guid': G, 'maxclients': 8, 'povs': [_multipov()]})
    assert _pack(demo_dir).returncode == 0
    before = _files(demo_dir)
    out = _pack(demo_dir)
    assert out.returncode == 0, out.stderr
    assert _files(demo_dir) == before
    assert 'no .qlmatch' in out.stdout


def test_engine_name_alone_marks_a_multipov_capture(demo_dir):
    _write(demo_dir, {'map': 'bloodrun', 'guid': G, 'povs': [_multipov()]})  # no sv_maxclients
    assert _pack(demo_dir).returncode == 0
    assert (demo_dir / f'{MATCH_ID}_bloodrun.dm_91').exists()
    assert not list(demo_dir.glob('*.qlmatch'))


def test_single_per_client_pov_still_builds_a_qlmatch(demo_dir):
    _write(demo_dir, {'map': 'bloodrun', 'guid': G, 'maxclients': 8,
                      'povs': [{'client_num': 0, 'roster': ROSTER, 'index': {'match_guid': G}}]})
    assert _pack(demo_dir).returncode == 0
    assert (demo_dir / f'{MATCH_ID}_bloodrun.qlmatch').exists()
    assert not (demo_dir / f'{MATCH_ID}_bloodrun.meta.json').exists()


def test_multipov_next_to_other_files_falls_back_to_a_qlmatch(demo_dir):
    _write(demo_dir, {'map': 'bloodrun', 'guid': G, 'maxclients': 8, 'povs': [
        _multipov(), {'client_num': 0, 'roster': ROSTER, 'index': {'match_guid': G}}]})
    assert _pack(demo_dir).returncode == 0
    assert (demo_dir / f'{MATCH_ID}_bloodrun.qlmatch').exists()
    assert (demo_dir / f'{MULTI_STEM}.dm_91').exists()


def test_template_without_stamp_does_not_overwrite_an_earlier_match(demo_dir):
    (demo_dir / 'bloodrun.dm_91').write_bytes(b'older match')
    _write(demo_dir, {'map': 'bloodrun', 'guid': G, 'maxclients': 8, 'povs': [_multipov()]})
    out = _pack(demo_dir, '--name-template', '{map}')
    assert out.returncode == 0, out.stderr
    assert (demo_dir / 'bloodrun.dm_91').read_bytes() == b'older match'
    stem = f'bloodrun_{MATCH_ID}'
    assert json.loads((demo_dir / f'{stem}.meta.json').read_text())['pack'] == f'{stem}.dm_91'
    assert (demo_dir / f'{stem}.dm_91').exists()


def test_template_equal_to_match_id_writes_only_the_v2_meta(demo_dir):
    _write(demo_dir, {'map': 'bloodrun', 'guid': G, 'maxclients': 8, 'povs': [_multipov()]})
    assert _pack(demo_dir, '--name-template', '{match_id}').returncode == 0
    meta = json.loads((demo_dir / f'{MATCH_ID}.meta.json').read_text())
    assert meta['version'] == 2 and meta['pack'] == f'{MATCH_ID}.dm_91'


def test_template_players_come_from_the_recording(demo_dir):
    _write(demo_dir, {'map': 'bloodrun', 'guid': G, 'maxclients': 8, 'povs': [_multipov()]})
    assert _pack(demo_dir, '--name-template', '{match_id}_{gametype}_{map}_{players}').returncode == 0
    assert (demo_dir / f'{MATCH_ID}_duel_bloodrun_Input.Frontier-T.club-bot.dm_91').exists()


def test_published_name_is_the_qlmatch_name_of_the_same_match(tmp_path):
    # The site lists a multi-POV match and a per-client .qlmatch the same way: <name>.dm_91 and
    # <name>.qlmatch share <name>, no "_multipov" suffix (ql-tournament-0217, qlsm-extra-0034).
    template = '{match_id}_{gametype}_{map}_{players}'
    names = {}
    for kind, pov in (('multi', _multipov()),
                      ('per_client', {'client_num': 0, 'roster': ROSTER, 'index': {'match_guid': G}})):
        d = tmp_path / kind
        d.mkdir()
        _write(d, {'map': 'bloodrun', 'guid': G, 'maxclients': 8, 'povs': [pov]})
        assert _pack(d, '--name-template', template).returncode == 0
        names[kind] = {p.name for p in d.iterdir() if p.suffix in ('.dm_91', '.qlmatch')}
    base = f'{MATCH_ID}_duel_bloodrun_Input.Frontier-T.club-bot'
    assert names['multi'] == {f'{base}.dm_91'}
    assert f'{base}.qlmatch' in names['per_client']
