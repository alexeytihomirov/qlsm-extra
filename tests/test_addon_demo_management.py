"""The demo-management addon's own endpoints (.dm_91 listing/download only).

The security-relevant filename validation lives in
addons/demo-management/ansible_instance_demos.py -- test_demos_validation.py
covers it directly. What is tested here is the addon's own HTTP wiring: auth,
argument checking, and that a download really comes back as a file rather
than JSON (the component saves a blob, so a JSON body would silently produce
a corrupt "download"). The external Bearer-token match API used to live in
this addon too; it moved to the qlmatch-packer addon along with the .qlmatch
format itself.

Moved here from qlsm's own tests/ when the addon left qlsm's image -- see
conftest.py for how a qlsm checkout is found.
"""
import io
import zipfile
from unittest.mock import patch

import pytest

from ui import db
from ui.models import Host, HostStatus, InstanceStatus, QLInstance
from conftest import auth_headers, make_user

ADDON = '/api/addons/demo-management'


@pytest.fixture
def addon_id():
    return 'demo-management'

DEMOS = [
    {'name': '2026-09-14_duel_aerowalk.dm_91', 'size': 4718592, 'mtime': 1757800000},
    {'name': '2026-09-13_ca_toxicity.dm_91', 'size': 12058624, 'mtime': 1757700000},
]


@pytest.fixture
def auth(app):
    make_user(app, 'demoop', 'pw')
    return auth_headers(app, 'demoop')


@pytest.fixture
def instance_id(app):
    with app.app_context():
        host = Host(name='germany', ip_address='10.0.0.1', provider='vultr',
                    status=HostStatus.ACTIVE)
        db.session.add(host)
        db.session.flush()
        instance = QLInstance(name='duel srv', port=27960, hostname='duel', host_id=host.id,
                              status=InstanceStatus.RUNNING)
        db.session.add(instance)
        db.session.commit()
        return instance.id


# ---- auth + not-found --------------------------------------------------

def test_listing_requires_auth(client, instance_id):
    assert client.get(f'{ADDON}/instances/{instance_id}/demos').status_code == 401


def test_unknown_instance_is_404(client, auth):
    assert client.get(f'{ADDON}/instances/9999/demos', headers=auth).status_code == 404


# ---- listing -----------------------------------------------------------

def test_listing_returns_rows_under_the_key_the_manifest_declares(client, auth, instance_id):
    """The manifest says `rows: "demos"`; if the payload key ever changed the
    table would silently render empty."""
    with patch('qlsm_addon_demo_management.ansible_instance_demos.list_instance_demos',
               return_value=(True, DEMOS, None)):
        resp = client.get(f'{ADDON}/instances/{instance_id}/demos', headers=auth)

    assert resp.status_code == 200
    body = resp.get_json()['data']
    assert [d['name'] for d in body['demos']] == [d['name'] for d in DEMOS]
    assert body['instance_name'] == 'duel srv'


def test_listing_surfaces_a_backend_failure(client, auth, instance_id):
    with patch('qlsm_addon_demo_management.ansible_instance_demos.list_instance_demos',
               return_value=(False, None, 'ssh down')):
        resp = client.get(f'{ADDON}/instances/{instance_id}/demos', headers=auth)

    assert resp.status_code == 500
    assert resp.get_json()['error']['message'] == 'ssh down'


# ---- single download ---------------------------------------------------

def test_download_returns_a_file_not_json(client, auth, instance_id):
    name = DEMOS[0]['name']
    with patch('qlsm_addon_demo_management.ansible_instance_demos.fetch_instance_demos',
               return_value=(True, {name: b'DEMOBYTES'}, [], None)):
        resp = client.get(f'{ADDON}/instances/{instance_id}/demos/download',
                          query_string={'filename': name}, headers=auth)

    assert resp.status_code == 200
    assert resp.data == b'DEMOBYTES'
    # The panel reads the filename off this header before saving the blob.
    assert name in resp.headers['Content-Disposition']


def test_download_without_a_filename_is_400(client, auth, instance_id):
    resp = client.get(f'{ADDON}/instances/{instance_id}/demos/download', headers=auth)
    assert resp.status_code == 400


def test_download_of_a_missing_file_is_404(client, auth, instance_id):
    name = DEMOS[0]['name']
    with patch('qlsm_addon_demo_management.ansible_instance_demos.fetch_instance_demos',
               return_value=(True, {}, [name], None)):
        resp = client.get(f'{ADDON}/instances/{instance_id}/demos/download',
                          query_string={'filename': name}, headers=auth)
    assert resp.status_code == 404


# ---- batch download ----------------------------------------------------

def test_batch_zips_the_selection(client, auth, instance_id):
    names = [d['name'] for d in DEMOS]
    with patch('qlsm_addon_demo_management.ansible_instance_demos.fetch_instance_demos',
               return_value=(True, {names[0]: b'AAA', names[1]: b'BBB'}, [], None)):
        resp = client.post(f'{ADDON}/instances/{instance_id}/demos/download-batch',
                           headers=auth, json={'filenames': names})

    assert resp.status_code == 200
    with zipfile.ZipFile(io.BytesIO(resp.data)) as zf:
        assert sorted(zf.namelist()) == sorted(names)
        assert zf.read(names[0]) == b'AAA'


def test_the_manifest_mounts_the_addons_own_screen():
    """This addon ships its own component rather than a generic table, so
    there is no `selection_key` to keep in step -- the screen posts
    `filenames` directly, which is what this endpoint reads. The manifest is
    asserted here so a switch back to a declarative panel cannot silently
    drop that agreement, and so the component it names cannot go missing from
    the package."""
    import json
    import os

    addon_dir = os.path.join(
        os.path.dirname(__file__), os.pardir, 'addons', 'demo-management')
    with open(os.path.join(addon_dir, 'qlsm-addon.json'), encoding='utf-8') as f:
        manifest = json.load(f)

    entry = manifest['ui']['instance_menu'][0]
    assert entry['component'] == 'Panel.js'
    assert entry['renders'] == 'modal'
    assert not manifest['ui'].get('panels'), (
        'a declarative panel reappeared -- it must declare '
        'selection_key: "filenames" to match this endpoint'
    )
    # ctx.modal and ctx.apiFor are what a renders:"modal" component needs,
    # and both arrived with ui_api 3.
    assert manifest['ui_api'] >= 3
    assert os.path.isfile(os.path.join(addon_dir, 'ui', 'Panel.js')), (
        'the built component is missing -- run `npm run build` in the addon dir'
    )


def test_the_built_component_carries_no_react_of_its_own():
    """Two React copies on one page break hooks. The bundle must read QLSM's
    off window.__qlsm (see ui-src/runtime.js) and must not leave a bare
    `import ... from "react"` behind either -- the browser loads this file
    with a plain dynamic import() and would fail to resolve it."""
    import os
    import re

    built = os.path.join(
        os.path.dirname(__file__), os.pardir,
        'addons', 'demo-management', 'ui', 'Panel.js')
    with open(built, encoding='utf-8') as f:
        body = f.read()

    assert 'window.__qlsm' in body
    assert not re.search(r'^\s*import\s', body, re.MULTILINE), (
        'the bundle has an unresolvable bare import'
    )
    assert 'export {' in body or 'export default' in body


def test_batch_rejects_an_empty_selection(client, auth, instance_id):
    resp = client.post(f'{ADDON}/instances/{instance_id}/demos/download-batch',
                       headers=auth, json={'filenames': []})
    assert resp.status_code == 400


def test_batch_rejects_a_non_list(client, auth, instance_id):
    resp = client.post(f'{ADDON}/instances/{instance_id}/demos/download-batch',
                       headers=auth, json={'filenames': 'one.dm_91'})
    assert resp.status_code == 400


def test_batch_is_404_when_nothing_was_found(client, auth, instance_id):
    with patch('qlsm_addon_demo_management.ansible_instance_demos.fetch_instance_demos',
               return_value=(True, {}, ['a.dm_91'], None)):
        resp = client.post(f'{ADDON}/instances/{instance_id}/demos/download-batch',
                           headers=auth, json={'filenames': ['a.dm_91']})
    assert resp.status_code == 404


def test_zip_name_is_sanitized_from_the_instance_name(client, auth, instance_id):
    """The instance name goes into a filename, so spaces and punctuation must
    not survive into the Content-Disposition header."""
    with patch('qlsm_addon_demo_management.ansible_instance_demos.fetch_instance_demos',
               return_value=(True, {'a.dm_91': b'A'}, [], None)):
        resp = client.post(f'{ADDON}/instances/{instance_id}/demos/download-batch',
                           headers=auth, json={'filenames': ['a.dm_91']})

    assert 'duel-srv-demos.zip' in resp.headers['Content-Disposition']


# ---- match grouping ----------------------------------------------------
#
# The engine names every file of one match "<match_id>_..." (demo_match.c), so
# the listing can cluster a duel's POVs into one row without any other addon
# being involved. Covered here rather than left to a look at the modal because
# an operator reads this list to find a match's files, and one row per POV is
# what they had before.

POVS = [
    {'name': '20260917T174655Z_bloodrun_p0_x_1789667191_1.dm_91', 'size': 100, 'mtime': 1789667400},
    {'name': '20260917T174655Z_bloodrun_p1_steemorol__69pixels_1789667191_2.dm_91',
     'size': 200, 'mtime': 1789667400},
    {'name': '20260917T174655Z.packer.log', 'size': 77, 'mtime': 1789667401},
    {'name': '20260916-234252_slot00_Input.dm_91', 'size': 300, 'mtime': 1789600000},
]


def _listing(client, auth, instance_id, demos):
    with patch('qlsm_addon_demo_management.ansible_instance_demos.list_instance_demos',
               return_value=(True, demos, None)):
        resp = client.get(f'{ADDON}/instances/{instance_id}/demos', headers=auth)
    assert resp.status_code == 200
    return resp.get_json()['data']


def test_one_match_id_becomes_one_group_with_all_of_its_files(client, auth, instance_id):
    groups = _listing(client, auth, instance_id, POVS)['matches']
    assert len(groups) == 1
    group = groups[0]
    assert group['group_id'] == '20260917T174655Z'
    # The map comes off the POV filename, so the row says what was played.
    assert group['label'].startswith('bloodrun')
    # Every file of the match, including one whose extension another addon
    # contributed: membership is the match_id, not a format whitelist.
    assert sorted(group['member_names']) == sorted(d['name'] for d in POVS[:3])


def test_a_plain_sv_demorecord_capture_is_never_grouped(client, auth, instance_id):
    """Its name is "%Y%m%d-%H%M%S_...", which cannot carry a match_id."""
    groups = _listing(client, auth, instance_id, POVS)['matches']
    grouped = {n for g in groups for n in g['member_names']}
    assert '20260916-234252_slot00_Input.dm_91' not in grouped


def test_a_lone_file_stays_a_plain_row(client, auth, instance_id):
    assert _listing(client, auth, instance_id, [POVS[0]])['matches'] == []


def test_grouping_leaves_a_match_another_addon_claimed_alone(client, auth, instance_id):
    """qlmatch-packer's group carries rebuild actions this module cannot offer,
    so a match it already claimed must not also get a second, bare row."""
    claimed = {
        'group_id': '20260917T174655Z',
        'label': 'bloodrun - claimed',
        'addon_id': 'qlmatch-packer',
        'member_names': [POVS[0]['name']],
        'actions': [],
    }
    # backend.py imports dispatch inside the view, so the patch has to land on
    # ui.addons, not on a module attribute of the addon.
    with patch('ui.addons.dispatch', return_value=[claimed]):
        with patch('qlsm_addon_demo_management.ansible_instance_demos.list_instance_demos',
                   return_value=(True, POVS, None)):
            resp = client.get(f'{ADDON}/instances/{instance_id}/demos', headers=auth)

    groups = resp.get_json()['data']['matches']
    assert [g['addon_id'] for g in groups] == ['qlmatch-packer']
