"""Demo filenames with non-ASCII player names.

The engine keeps UTF-8 player names (Cyrillic etc.) in POV filenames now, so
the filename filter is a deny-list of what is unsafe in a path component, not
an ASCII allow-list. These tests pin both halves: such a demo is listed and
downloadable, and every traversal / control-character / dotfile shape is
still refused before any SSH session is opened.

Separately: paramiko decodes a whole SFTP directory listing as strict UTF-8,
so one file name in another encoding used to fail the entire listing. That
case now falls back to a byte-level `find` listing that skips just that name.
"""
import stat
from unittest.mock import MagicMock, patch

import paramiko
import pytest
from flask_jwt_extended import create_access_token

from ui import db
from ui.database import create_host, create_instance
from ui.models import HostStatus

FETCH_MODULE = 'qlsm_addon_demo_management.ansible_instance_demos'
TRANSPORT_MODULE = 'qlsm_addon_demo_management.instance_demo_transport'

CYRILLIC_POV = '20261003T100000Z_bloodrun_p1_Вася_Пупкин_1790982403_2.dm_91'


@pytest.fixture
def addon_id():
    return 'demo-management'


def _attr(name, size=10, mtime=1.0):
    entry = paramiko.SFTPAttributes()
    entry.filename = name
    entry.st_size = size
    entry.st_mtime = mtime
    entry.st_mode = stat.S_IFREG | 0o644
    return entry


def _ssh_client(sftp, exec_output=b''):
    client = MagicMock()
    client.open_sftp.return_value = sftp
    stdout = MagicMock()
    stdout.read.return_value = exec_output
    stdout.channel.recv_exit_status.return_value = 0
    client.exec_command.return_value = (MagicMock(), stdout, MagicMock())
    return client


def _list(client):
    from qlsm_addon_demo_management.ansible_instance_demos import list_instance_listing
    host = MagicMock(name='h', ssh_port=22, ssh_key_path='/k', ssh_user='u')
    with patch(f'{FETCH_MODULE}.dispatch', return_value=[]), \
         patch(f'{FETCH_MODULE}.resolve_instance_and_host', return_value=(MagicMock(port=27960), host, None)), \
         patch(f'{TRANSPORT_MODULE}.rcon_target_for_host', return_value='10.0.0.1'), \
         patch(f'{TRANSPORT_MODULE}.paramiko.SSHClient', return_value=client):
        return list_instance_listing(1)


# ---- the filter itself -------------------------------------------------

@pytest.mark.parametrize('name', [
    CYRILLIC_POV,
    'ник с пробелом.dm_91',
    '日本語.dm_91',
    'emoji_🔥.dm_91',
    '20261002-120000_slot00_x.dm_91',
])
def test_non_ascii_demo_names_are_recognised(app, name):
    from qlsm_addon_demo_management.ansible_instance_demos import _demo_filename_re
    with app.app_context(), patch(f'{FETCH_MODULE}.dispatch', return_value=[]):
        assert _demo_filename_re().fullmatch(name)


@pytest.mark.parametrize('name', [
    '../x.dm_91', '..dm_91', '.dm_91', '.hidden.dm_91', '-rf.dm_91',
    'a/b.dm_91', 'a\\b.dm_91', '../../Вася.dm_91',
    'a\n.dm_91', 'a.dm_91\n', 'a\x00.dm_91', 'a\x7f.dm_91', 'a\x85.dm_91', 'a\x1b[31m.dm_91',
    'Вася.txt', 'a' * 241 + '.dm_91',
])
def test_unsafe_names_are_still_refused_without_touching_ssh(app, name):
    from qlsm_addon_demo_management.ansible_instance_demos import fetch_instance_demos
    with app.app_context(), patch(f'{FETCH_MODULE}.dispatch', return_value=[]), \
         patch(f'{TRANSPORT_MODULE}.paramiko.SSHClient') as mock_cls:
        success, files, _missing, error = fetch_instance_demos(1, [name])
    assert success is False
    assert files == {}
    assert 'Invalid filename' in error
    mock_cls.assert_not_called()


# ---- listing -----------------------------------------------------------

def test_a_cyrillic_pov_is_listed_and_labelled(app):
    sftp = MagicMock()
    sftp.listdir_attr.return_value = [_attr(CYRILLIC_POV)]
    with app.test_request_context():
        success, listing, error = _list(_ssh_client(sftp))

    assert success and error is None
    [demo] = listing['demos']
    assert demo['name'] == CYRILLIC_POV
    assert demo['match_id'] == '20261003T100000Z'
    assert demo['map'] == 'bloodrun'
    assert demo['pov'] == {'slot': 1, 'player': 'Вася Пупкин'}


def test_one_non_utf8_name_no_longer_loses_the_whole_listing(app):
    sftp = MagicMock()
    sftp.listdir_attr.side_effect = UnicodeDecodeError('utf-8', b'\xcf', 0, 1, 'invalid start byte')
    find_output = (
        CYRILLIC_POV.encode('utf-8') + b'\x00' + b'4096\x00' + b'1790982403.5\x00'
        + b'\xcf\xf0\xe8\xe2\xe5\xf2.dm_91\x00' + b'10\x00' + b'1790982400.0\x00'  # CP1251
        + b'notes.txt\x00' + b'5\x00' + b'1790982401.0\x00'
    )
    client = _ssh_client(sftp, find_output)
    with app.test_request_context():
        success, listing, error = _list(client)

    assert success and error is None
    assert [d['name'] for d in listing['demos']] == [CYRILLIC_POV]
    assert listing['demos'][0]['size'] == 4096
    assert listing['timing']['skipped_names'] == 1
    command = client.exec_command.call_args[0][0]
    assert command.startswith("find /home/ql/qlds-27960/demos ")


# ---- download ----------------------------------------------------------

def test_a_cyrillic_demo_downloads_with_a_utf8_filename(client, app):
    with app.app_context():
        host = create_host(name='demo-host', provider='vultr', status=HostStatus.ACTIVE)
        instance = create_instance(name='demo-inst', host_id=host.id, port=27960, hostname='demo.host')
        db.session.commit()
        instance_id = instance.id
        token = create_access_token(identity='testuser')

    with patch(f'{FETCH_MODULE}.fetch_instance_demos',
               return_value=(True, {CYRILLIC_POV: b'demo-bytes'}, [], None)):
        resp = client.get(
            f'/api/addons/demo-management/instances/{instance_id}/demos/download',
            query_string={'filename': CYRILLIC_POV},
            headers={'Authorization': f'Bearer {token}'},
        )

    assert resp.status_code == 200
    assert resp.data == b'demo-bytes'
    disposition = resp.headers['Content-Disposition']
    # RFC 6266 / 5987: an ASCII fallback plus the real name percent-encoded.
    assert "filename*=UTF-8''" in disposition
    assert '%D0%92%D0%B0%D1%81%D1%8F' in disposition  # "Вася"
    disposition.encode('latin-1')  # the header itself stays latin-1 safe
