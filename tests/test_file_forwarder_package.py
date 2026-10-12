"""Release artefacts: packages/file-forwarder.zip and the repository index."""
import hashlib
import json
import re
import zipfile
from pathlib import Path

import pytest

pytestmark = pytest.mark.standalone

ROOT = Path(__file__).resolve().parent.parent
ZIP = ROOT / 'packages' / 'file-forwarder.zip'
REPO_JSON = ROOT / 'qlsm-repository.json'
PRIVATE_KEY_BLOCK = re.compile(r'-----BEGIN [A-Z ]*PRIVATE KEY-----\s*[A-Za-z0-9+/=\r\n]{20,}')
EXPECTED = [
    'qlsm-addon.json', 'backend.py', 'config_render.py', 'keypair.py',
    'assets/forwarder.sh', 'assets/known_hosts_vps',
    'assets/file-forwarder.service', 'assets/file-forwarder.timer',
    'playbooks/run_forwarder.yml', 'playbooks/status_file_forwarder.yml',
    'playbooks/sync_file_forwarder.yml',
    'ui/HostPanel.js', 'ui/PublicKey.js',
]


def _names():
    with zipfile.ZipFile(ZIP) as zf:
        return zf.namelist()


def _entry(addon_id):
    data = json.loads(REPO_JSON.read_text(encoding='utf-8'))
    return next(e for e in data['addons'] if e['id'] == addon_id)


def test_zip_contents():
    names = _names()
    for want in EXPECTED:
        assert want in names, want
    assert not [n for n in names if '__pycache__' in n]


def test_no_private_key_block():
    with zipfile.ZipFile(ZIP) as zf:
        for n in zf.namelist():
            text = zf.read(n).decode('utf-8', errors='ignore')
            assert not PRIVATE_KEY_BLOCK.search(text), n


def test_lf_line_endings():
    with zipfile.ZipFile(ZIP) as zf:
        for n in zf.namelist():
            if n.endswith(('.sh', '.service', '.timer', '.yml')):
                assert b'\r\n' not in zf.read(n), n


@pytest.mark.parametrize('addon_id', ['file-forwarder', 'qlmatch-packer'])
def test_entry_matches_package(addon_id):
    entry = _entry(addon_id)
    manifest = json.loads((ROOT / 'addons' / addon_id / 'qlsm-addon.json').read_text(encoding='utf-8'))
    assert entry['version'] == manifest['version']
    assert entry['sha256'] == hashlib.sha256((ROOT / entry['zip']).read_bytes()).hexdigest()
