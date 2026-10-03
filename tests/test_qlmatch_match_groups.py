"""qlmatch-packer's contribution to the Demos listing (the
demo_management.match_groups hook).

The cost that made the listing slow was here: every .qlmatch's manifest.json
read over SFTP (several round trips per pack) on a second SSH connection,
with an in-process cache a redeploy wiped. Now a pack demo-management already
tied to its match (via the match's .meta.json or a match-id-prefixed name)
needs no remote access at all, and an older pack is read once, ever.
"""
from unittest.mock import MagicMock, patch

import pytest

MODULE = 'qlsm_addon_qlmatch_packer.match_groups'
LISTING_MODULE = 'qlsm_addon_qlmatch_packer.qlmatch_listing'
MATCH = '20260917T174655Z'
POV = f'{MATCH}_bloodrun_p0_alex_1_1.dm_91'


@pytest.fixture
def addon_id():
    return 'qlmatch-packer'


@pytest.fixture
def groups_mod(app, monkeypatch):
    import importlib
    listing = importlib.import_module(LISTING_MODULE)
    store = {}
    redis = MagicMock()
    redis.get.side_effect = store.get
    redis.set.side_effect = lambda k, v, ex=None: store.__setitem__(k, v)
    monkeypatch.setattr(listing, '_redis', lambda: redis)
    monkeypatch.setattr(listing, '_MANIFEST_CACHE', {})
    return importlib.import_module(MODULE)


def test_a_pack_already_tied_to_its_match_opens_no_sftp(groups_mod):
    demos = [
        {'name': 'duel_alex.qlmatch', 'size': 9, 'mtime': 2.0, 'match_id': MATCH, 'map': 'bloodrun'},
        {'name': POV, 'size': 5, 'mtime': 1.0, 'match_id': MATCH, 'map': 'bloodrun'},
        {'name': f'{MATCH}_bloodrun.replay.json.gz', 'size': 3, 'mtime': 2.0, 'match_id': MATCH},
    ]
    with patch(f'{MODULE}.open_sftp') as open_sftp:
        groups = groups_mod.build_match_groups(1, demos)

    open_sftp.assert_not_called()
    assert len(groups) == 1
    assert groups[0]['group_id'] == MATCH
    assert groups[0]['qlmatch_name'] == 'duel_alex.qlmatch'
    assert sorted(groups[0]['member_names']) == sorted(d['name'] for d in demos)
    assert [a['id'] for a in groups[0]['actions']] == [
        'qlmatch-packer.rebuild-sidecar', 'qlmatch-packer.rebuild-full']


def test_an_older_pack_is_read_once_then_served_from_cache(groups_mod):
    demos = [
        {'name': 'duel_alex.qlmatch', 'size': 9, 'mtime': 2.0},
        {'name': POV, 'size': 5, 'mtime': 1.0, 'match_id': MATCH, 'map': 'bloodrun'},
    ]
    manifest = {'match_id': MATCH, 'map': 'bloodrun', 'raw_demo_names': [POV],
                'gametype': '1', 'pov_names': ['alex']}
    resolve = (MagicMock(port=27960), MagicMock(), None)

    def read(sftp, demo_dir, name, cache_key=None):
        import importlib
        importlib.import_module(LISTING_MODULE)._remember(cache_key, manifest)
        return manifest, None

    with patch(f'{MODULE}.resolve_instance_and_host', return_value=resolve), \
         patch(f'{MODULE}.open_sftp', return_value=(MagicMock(), MagicMock())) as open_sftp, \
         patch(f'{MODULE}._manifest_from_pack', side_effect=read):
        first = groups_mod.build_match_groups(1, [dict(d) for d in demos])
        second = groups_mod.build_match_groups(1, [dict(d) for d in demos])

    assert open_sftp.call_count == 1
    assert first == second
    group = first[0]
    assert sorted(group['member_names']) == sorted(d['name'] for d in demos)
    assert group['info'] == {'match_id': MATCH, 'map': 'bloodrun', 'gametype': 'duel',
                             'players': [{'name': 'alex', 'team': ''}], 'source': 'pack'}


def test_a_pack_that_cannot_be_resolved_stays_a_plain_row(groups_mod):
    demos = [{'name': 'mystery.qlmatch', 'size': 9, 'mtime': 2.0}]
    with patch(f'{MODULE}.resolve_instance_and_host', return_value=(MagicMock(port=1), MagicMock(), None)), \
         patch(f'{MODULE}.open_sftp', return_value=(MagicMock(), MagicMock())), \
         patch(f'{MODULE}._manifest_from_pack', return_value=(None, 'bad zip')):
        assert groups_mod.build_match_groups(1, demos) == []
