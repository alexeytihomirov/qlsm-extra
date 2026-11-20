"""restore/qlmatch.py list_packs(): a published multi-POV match (<stem>.dm_91 +
<stem>.meta.json version 2, no .qlmatch) is listed like a pack, so
`!restore match` finds its sidecar."""
import json
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from restore import qlmatch  # noqa: E402

pytestmark = pytest.mark.standalone

WINDOW = {'start_server_time': 98575, 'end_server_time': 528525, 'game_start_server_time': 108850}


def _meta(stem, **over):
    body = {
        'format': 'qlsm-demo-meta', 'version': 2, 'match_id': '20261120T025005Z', 'map': 'bloodrun',
        'gametype': 'duel', 'window': WINDOW,
        'players': [{'client_num': 0, 'name': 'Input.Frontier', 'team': '0', 'steam_id64': None},
                    {'client_num': 1, 'name': 'T.club', 'team': '0', 'steam_id64': None}],
        'pack': f'{stem}.dm_91',
    }
    body.update(over)
    return json.dumps(body, indent=2)


def _qlmatch(path, match_id):
    with zipfile.ZipFile(path, 'w') as zf:
        zf.writestr('manifest.json', json.dumps({
            'match_id': match_id, 'map': 'campgrounds', 'window': WINDOW,
            'demos': [{'file': 'demos/a.dm_91', 'name': 'alex'}]}))


def test_multipov_meta_is_listed_next_to_packs(tmp_path):
    (tmp_path / '20261120T025005Z_bloodrun.dm_91').write_bytes(b'demo')
    (tmp_path / '20261120T025005Z_bloodrun.meta.json').write_text(_meta('20261120T025005Z_bloodrun'))
    _qlmatch(tmp_path / '20261119T100000Z_campgrounds.qlmatch', '20261119T100000Z')
    rows = qlmatch.list_packs(str(tmp_path))
    assert [(r['index'], r['match_id'], r['map']) for r in rows] == [
        (1, '20261120T025005Z', 'bloodrun'), (2, '20261119T100000Z', 'campgrounds')]
    row = rows[0]
    assert row['filename'] == '20261120T025005Z_bloodrun.dm_91'
    assert row['players'] == ['Input.Frontier', 'T.club']
    assert row['window'] == WINDOW and row['duration_ms'] == 528525 - 108850
    assert qlmatch.list_packs(str(tmp_path), 'frontier')[0]['match_id'] == '20261120T025005Z'


def test_other_meta_files_are_not_listed(tmp_path):
    # the Demos screen label file (version 1) and a v2 meta naming another file
    (tmp_path / '20261120T025005Z.meta.json').write_text(
        _meta('x', version=1, pack='20261120T025005Z_bloodrun.dm_91'))
    (tmp_path / 'other.meta.json').write_text(_meta('other', pack='else.dm_91'))
    (tmp_path / 'broken.meta.json').write_text('{not json')
    (tmp_path / '.hidden.meta.json.part').write_text(_meta('hidden'))
    assert qlmatch.list_packs(str(tmp_path)) == []
