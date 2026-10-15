"""qlmatch-packer no longer delivers: rclone moved to the file-forwarder addon.

An old plugin on a game host may still launch pack.mjs with
`--rclone-targets <value>`; that must not break packing (flag accepted and
ignored, rclone never called).
"""
import importlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

ADDON_DIR = Path(__file__).resolve().parent.parent / 'addons' / 'qlmatch-packer'
PACK_MJS = ADDON_DIR / 'assets' / 'pack.mjs'
IGNORE_MSG = 'packer: --rclone-targets is ignored, delivery moved to the file-forwarder addon'


def _node_ok():
    node = shutil.which('node')
    if not node:
        return False
    out = subprocess.run([node, '--version'], capture_output=True, text=True).stdout.strip()
    m = re.match(r'v(\d+)\.', out)
    return bool(m) and int(m.group(1)) >= 22


@pytest.mark.standalone
def test_manifest_version_is_1_3_2():
    manifest = json.loads((ADDON_DIR / 'qlsm-addon.json').read_text(encoding='utf-8'))
    assert manifest['version'] == '1.3.2'
    assert 'rclone' not in manifest['description'].lower()


@pytest.mark.standalone
def test_addon_has_no_rclone_text_except_the_ignore_message():
    offenders = []
    for path in ADDON_DIR.rglob('*'):
        if not path.is_file() or 'node_modules' in path.parts:
            continue
        try:
            text = path.read_text(encoding='utf-8')
        except (UnicodeDecodeError, OSError):
            continue
        for n, line in enumerate(text.splitlines(), 1):
            if 'rclone' in line.lower():
                # only the tolerated legacy flag may be named: pack.mjs (accepts and ignores it) and its README
                if path.name in ('pack.mjs', 'README.md') and ('--rclone-targets' in line):
                    continue
                offenders.append(f'{path.relative_to(ADDON_DIR)}:{n}: {line.strip()}')
    assert offenders == []


@pytest.mark.standalone
def test_pack_mjs_has_no_exit_code_4_or_rclone_spawn():
    text = PACK_MJS.read_text(encoding='utf-8')
    assert 'spawnSync("rclone"' not in text
    assert 'RCLONE_TIMEOUT_MS' not in text
    assert not re.search(r'^//\s+4\s', text, re.M)


@pytest.mark.standalone
@pytest.mark.skipif(not _node_ok(), reason='node >= 22 not available')
def test_pack_mjs_accepts_and_ignores_rclone_targets(tmp_path):
    # Failing rclone stub first in PATH: any call to it would be visible.
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    marker = tmp_path / 'rclone-called'
    stub = bin_dir / 'rclone'
    stub.write_text(f'#!/bin/sh\necho called >> "{marker.as_posix()}"\nexit 9\n', encoding='utf-8')
    (bin_dir / 'rclone.cmd').write_text(f'@echo called >> "{marker}"\r\n@exit /b 9\r\n', encoding='utf-8')
    stub.chmod(0o755)
    demo_dir = tmp_path / 'demos'
    demo_dir.mkdir()
    env = dict(os.environ, PATH=str(bin_dir) + os.pathsep + os.environ.get('PATH', ''))

    proc = subprocess.run(
        ['node', str(PACK_MJS), '--dir', str(demo_dir), '--match-id', '20260917T174655Z',
         '--rclone-targets', 'x:y'],
        capture_output=True, text=True, env=env, timeout=60,
    )
    # No POV files in the fixture dir: exit 3 ("nothing to do"), NOT 5 (the
    # old failure for an unknown argument) and never 4.
    assert proc.returncode == 3, proc.stderr
    assert IGNORE_MSG in proc.stderr
    assert proc.stderr.count('--rclone-targets is ignored') == 1
    assert not marker.exists()


@pytest.fixture
def addon_id():
    return 'qlmatch-packer'


def test_read_packer_cvars_returns_only_the_name_template(app, tmp_path, monkeypatch):
    ops = importlib.import_module('qlsm_addon_qlmatch_packer.rebuild_ops')
    monkeypatch.chdir(tmp_path)
    cfg_dir = tmp_path / 'configs' / 'h1' / '7'
    cfg_dir.mkdir(parents=True)
    (cfg_dir / 'server.cfg').write_text(
        'set qlx_qlmatchNameTemplate "{date}_{map}"\nset qlx_qlmatchRcloneTargets "gd:x"\n', encoding='utf-8')
    instance = SimpleNamespace(id=7, host=SimpleNamespace(name='h1'))
    assert ops._read_packer_cvars(instance) == '{date}_{map}'
    instance_missing = SimpleNamespace(id=8, host=SimpleNamespace(name='h1'))
    assert ops._read_packer_cvars(instance_missing) == ''


def test_rebuild_full_command_has_no_rclone(app, tmp_path, monkeypatch):
    ops = importlib.import_module('qlsm_addon_qlmatch_packer.rebuild_ops')
    monkeypatch.chdir(tmp_path)
    cfg_dir = tmp_path / 'configs' / 'h1' / '7'
    cfg_dir.mkdir(parents=True)
    (cfg_dir / 'server.cfg').write_text(
        'set qlx_qlmatchNameTemplate "{date}_{map}"\nset qlx_qlmatchRcloneTargets "gd:x"\n', encoding='utf-8')
    instance = SimpleNamespace(id=7, host=SimpleNamespace(name='h1'))
    monkeypatch.setattr(ops, '_validate_qlmatch_filename', lambda f: None)
    monkeypatch.setattr(ops, '_instance_and_dir', lambda i: (instance, 'host', '/demos'))
    monkeypatch.setattr(ops, '_read_manifest_or_raise', lambda i, f: {'match_id': '20260917T174655Z', 'map': 'bloodrun'})
    monkeypatch.setattr(ops, '_raw_povs_present', lambda *a: True)
    seen = []

    def fake_run(host, command, timeout=None):
        seen.append(command)
        return 0, '', ''

    monkeypatch.setattr(ops, 'run_remote_command', fake_run)
    ops.rebuild_full_logic(7, 'a.qlmatch')
    assert len(seen) == 1
    assert 'rclone' not in seen[0].lower()
    assert '--name-template' in seen[0]
