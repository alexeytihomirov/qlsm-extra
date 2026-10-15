"""Static checks for the file-forwarder playbooks and systemd units.

Nothing here runs Ansible against a host. The one syntax-check test runs only
when `ansible-playbook` is on PATH.
"""
import importlib.util
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.standalone

ADDON = Path(__file__).resolve().parent.parent / 'addons' / 'file-forwarder'
PLAYBOOKS = ADDON / 'playbooks'
ASSETS = ADDON / 'assets'
NAMES = ('sync_file_forwarder.yml', 'run_forwarder.yml', 'status_file_forwarder.yml')


def _load(name):
    return yaml.safe_load((PLAYBOOKS / name).read_text(encoding='utf-8'))


def _tasks(name):
    return [task for play in _load(name) for task in play.get('tasks', [])]


def _config_render():
    spec = importlib.util.spec_from_file_location('ff_config_render_under_test', ADDON / 'config_render.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('name', NAMES)
def test_playbook_parses_and_targets_all_hosts(name):
    plays = _load(name)
    assert isinstance(plays, list) and plays
    for play in plays:
        assert play['hosts'] == 'all'
        assert play['become'] is True or play['become'] == 'yes'
        assert play['gather_facts'] is False
        assert play['tasks']


def test_sync_no_log_on_every_key_and_rclone_config_task():
    touched = 0
    for task in _tasks('sync_file_forwarder.yml'):
        text = json.dumps(task)
        writes_conf = any(m in task for m in ('copy', 'template', 'command', 'shell', 'lineinfile')) and             ('rclone.conf' in text or 'fwd_rclone_conf' in text) and 'RCLONE_CONFIG' not in text
        if 'ff_private_key_file' in text or writes_conf:
            touched += 1
            assert task.get('no_log') is True, f'task without no_log: {task.get("name")}'
    assert touched >= 2  # the key task and the rclone config task


def test_sync_never_touches_the_user_global_rclone_config():
    text = (PLAYBOOKS / 'sync_file_forwarder.yml').read_text(encoding='utf-8')
    assert '.config/rclone' not in text
    assert 'fwd_rclone_conf: /home/ql/file-forwarder/rclone.conf' in text
    assert text.count('RCLONE_CONFIG: "{{ fwd_rclone_conf }}"') >= 1


def test_sync_downloads_rclone_deb_safely():
    tasks = _tasks('sync_file_forwarder.yml')
    blocks = [t for t in tasks if 'block' in t]
    assert blocks and 'always' in blocks[0]  # cleanup also on failure
    gets = [t2 for t in blocks for t2 in t['block'] if 'get_url' in t2]
    assert len(gets) == 1
    args = gets[0]['get_url']
    assert not str(args['dest']).startswith('/tmp/')
    assert args['force'] in (True, 'yes')
    assert str(args['checksum']).startswith('sha256:https://downloads.rclone.org/')
    assert any('tempfile' in t2 for t in blocks for t2 in t['block'])


def test_unit_assets():
    service = (ASSETS / 'file-forwarder.service').read_text(encoding='utf-8')
    timer = (ASSETS / 'file-forwarder.timer').read_text(encoding='utf-8')
    assert 'User=ql' in service
    assert 'Type=oneshot' in service
    assert 'ExecStart=/bin/sh /home/ql/file-forwarder/forwarder.sh run' in service
    assert 'FORWARDER_CONF=/home/ql/file-forwarder/forwarder.conf' in service
    assert 'Environment=RCLONE_CONFIG=/home/ql/file-forwarder/rclone.conf' in service
    assert 'Persistent=true' in timer
    assert 'OnBootSec=2min' in timer
    assert 'OnUnitActiveSec={{ ff_interval_minutes }}min' in timer


def test_no_private_key_text_in_playbooks_assets_or_docs():
    # backend.py/keypair.py name the PEM marker on purpose (log redaction, key
    # generation); everything that ships to a host or is read by operators must not.
    for path in ADDON.rglob('*'):
        if path.is_file() and path.suffix not in ('.pyc', '.py'):
            assert 'PRIVATE KEY' not in path.read_text(encoding='utf-8', errors='replace'), str(path)


@pytest.mark.skipif(shutil.which('ansible-playbook') is None, reason='ansible-playbook not installed')
@pytest.mark.parametrize('name', NAMES)
def test_ansible_syntax_check(name):
    result = subprocess.run(['ansible-playbook', '--syntax-check', '-i', 'localhost,', str(PLAYBOOKS / name)],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_status_prints_three_lines_and_never_touches_ssh():
    text = (PLAYBOOKS / 'status_file_forwarder.yml').read_text(encoding='utf-8')
    for marker in ('FF_VERSION=', 'FF_TIMER=', 'FF_LAST_RUN=', 'FF_RCLONE='):
        assert marker in text
    assert '.ssh' not in text
    assert 'rclone.conf' not in text
    assert 'systemctl is-active file-forwarder.timer' in text
    assert '/home/ql/file-forwarder/VERSION' in text
    assert '/home/ql/.forwarder-state/last-run' in text


def test_run_asserts_mode_before_running():
    tasks = _tasks('run_forwarder.yml')
    assert 'assert' in tasks[0]
    assert "'run'" in json.dumps(tasks[0]) and "'purge'" in json.dumps(tasks[0])
    text = (PLAYBOOKS / 'run_forwarder.yml').read_text(encoding='utf-8')
    assert 'forwarder.sh {{ ff_mode }}' in text
    assert 'FORWARDER_CONF' in text
    assert 'RCLONE_CONFIG: /home/ql/file-forwarder/rclone.conf' in text
    assert 'last-run' in text


def test_ff_private_key_never_referenced_by_playbooks():
    for name in NAMES:
        text = (PLAYBOOKS / name).read_text(encoding='utf-8')
        assert not re.search(r'\bff_private_key\b', text), name


def test_every_extravar_is_provided_by_the_backend():
    config_render = _config_render()
    provided = set(config_render.playbook_vars({
        'sftp_private_key': 'x', 'vps_host': 'vps.example.org',
        'vps_known_hosts': 'vps.example.org ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIL4aIb56D/YdmM5b3fAmOwwLcxxQj8RGyvz4kITSjJc0'}))
    provided.discard('ff_private_key')  # backend turns it into a file path
    backend = (ADDON / 'backend.py').read_text(encoding='utf-8')
    for extra, assignment in (('ff_private_key_file', "variables['ff_private_key_file'] ="),
                              ('ff_mode', "{'ff_mode':")):
        assert assignment in backend, f'backend no longer passes {extra}'
        provided.add(extra)

    used = set()
    paths = [PLAYBOOKS / n for n in NAMES] + [ASSETS / 'file-forwarder.service', ASSETS / 'file-forwarder.timer']
    for path in paths:
        used |= set(re.findall(r'\bff_[a-z0-9_]+\b', path.read_text(encoding='utf-8')))
    assert used, 'no extravars found'
    unknown = used - provided
    assert not unknown, f'not provided by the backend: {sorted(unknown)}'
    # the sync playbook (or the unit templates it renders) must consume everything the backend sends
    sync = ''.join(p.read_text(encoding='utf-8') for p in
                   (PLAYBOOKS / 'sync_file_forwarder.yml', ASSETS / 'file-forwarder.service', ASSETS / 'file-forwarder.timer'))
    for name in provided - {'ff_mode'}:
        assert re.search(r'\b' + name + r'\b', sync), f'sync playbook ignores {name}'
