#!/usr/bin/env python3
"""Refresh qlsm-repository.json and rebuild packages/*.zip.

Plugins: recompute each listed entry's sha256 from the .py next to this
script (LF-normalized, matching qlsm's CRLF-insensitive comparison), and
copy `depends_on` from the plugin's own `.ql-plugin.json` sidecar. A plugin
listed in PACKAGE_FOLDERS also gets `package_files`: every file under its
folder, LF-normalized sha256 each, so qlsm downloads the whole folder
alongside the .py (see ui/plugin_repositories.py's `package_files`, added
once qlsm could fetch more than a single bare `<name>.py` per entry).

Addons: zip each directory under addons/<id>/ into packages/<id>.zip
(with qlsm-addon.json at the archive root), then refresh that entry's
version / sha256 / label / description from the addon's own manifest.

Run this (and commit the result) whenever a listed .py, package folder, or
any addon source changes.
"""
from __future__ import annotations

import hashlib
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MANIFEST = ROOT / 'qlsm-repository.json'
ADDONS_DIR = ROOT / 'addons'
PACKAGES_DIR = ROOT / 'packages'

# Plugins qlsm can fetch as a single bare filename (+ optional sidecar).
DEFAULT_PLUGINS = [
    'tournament_access.py',
    'chat_rcon.py',
    'chat_rcon_acl.py',
    'lobby.py',
    'match_restore.py',
    'match_restore_util.py',
    'match_restore_lab.py',
]

# filename -> folder (relative to this script) that must be downloaded
# alongside it. match_restore.py does `from restore import codec` etc., so it
# needs the whole restore/ package on disk next to it, not just another
# root-level .py `depends_on` could name.
PACKAGE_FOLDERS = {
    'match_restore.py': 'restore',
}


def _normalize_eol(data: bytes) -> bytes:
    return data.replace(b'\r\n', b'\n').replace(b'\r', b'\n')


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path, *, normalize_eol: bool = False) -> str:
    data = path.read_bytes()
    if normalize_eol:
        data = _normalize_eol(data)
    return _sha256_bytes(data)


def _load_sidecar_meta(filename: str) -> dict:
    sidecar = ROOT / (filename[:-3] + '.ql-plugin.json')
    if not sidecar.is_file():
        return {}
    try:
        data = json.loads(sidecar.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    out = {}
    if isinstance(data.get('label'), str) and data['label'].strip():
        out['label'] = data['label'].strip()
    if isinstance(data.get('description'), str) and data['description'].strip():
        out['description'] = data['description'].strip()
    # depends_on is what tells qlsm a listed file is a helper of another listed
    # plugin: it gets no row of its own in the Repositories page and is
    # downloaded together with whatever needs it. The sidecar is the source of
    # truth (the Plugins tab reads the same field from it), so it is copied
    # rather than maintained by hand in the manifest.
    depends_on = data.get('depends_on')
    if isinstance(depends_on, list):
        names = [d.strip() for d in depends_on
                 if isinstance(d, str) and d.strip().endswith('.py') and '/' not in d]
        if names:
            out['depends_on'] = names
    return out


def _package_files(folder: str) -> dict:
    """{"<folder>/<relpath>": sha256, ...} for every file under `folder`,
    LF-normalized the same way the main .py's own hash is -- must match what
    ui.plugin_repositories._is_safe_package_relpath will accept on the qlsm
    side (POSIX-style relative paths, no leading dot)."""
    root = ROOT / folder
    out = {}
    for path in sorted(root.rglob('*')):
        if not path.is_file():
            continue
        if path.name in ('.DS_Store', 'Thumbs.db') or '__pycache__' in path.parts:
            continue
        relpath = f'{folder}/{path.relative_to(root).as_posix()}'
        out[relpath] = _sha256_file(path, normalize_eol=True)
    return out


def _plugin_entries(existing: list) -> list:
    by_name = {
        e['filename']: e for e in existing
        if isinstance(e, dict) and isinstance(e.get('filename'), str)
    }
    names = [e['filename'] for e in existing if isinstance(e, dict) and e.get('filename')]
    if not names:
        names = list(DEFAULT_PLUGINS)

    entries = []
    missing = []
    for filename in names:
        path = ROOT / filename
        prev = by_name.get(filename, {})
        entry = {
            'filename': filename,
            'runtime': prev.get('runtime') or 'minqlx',
        }
        meta = _load_sidecar_meta(filename)
        for key in ('label', 'description', 'version', 'requires_qlsm_version'):
            value = prev.get(key) or meta.get(key)
            if value:
                entry[key] = value
        # Sidecar wins here, unlike the fields above: a dependency list kept
        # only in the manifest would go stale the moment the plugin's own
        # sidecar changed.
        depends_on = meta.get('depends_on') or prev.get('depends_on')
        if depends_on:
            entry['depends_on'] = depends_on
        folder = PACKAGE_FOLDERS.get(filename)
        if folder:
            entry['package_files'] = _package_files(folder)
        if not path.is_file():
            missing.append(filename)
            if prev.get('sha256'):
                entry['sha256'] = prev['sha256']
        else:
            entry['sha256'] = _sha256_file(path, normalize_eol=True)
        entries.append(entry)
    return entries, missing


def _zip_addon(addon_dir: Path, zip_path: Path) -> None:
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(addon_dir.rglob('*')):
            if not path.is_file():
                continue
            # Skip local junk if any slips in
            if path.name in ('.DS_Store', 'Thumbs.db') or '__pycache__' in path.parts:
                continue
            arcname = path.relative_to(addon_dir).as_posix()
            zf.write(path, arcname)


def _addon_entries(existing: list) -> list:
    by_id = {
        e['id']: e for e in existing
        if isinstance(e, dict) and isinstance(e.get('id'), str)
    }
    entries = []
    if not ADDONS_DIR.is_dir():
        return entries

    for addon_dir in sorted(p for p in ADDONS_DIR.iterdir() if p.is_dir()):
        manifest_path = addon_dir / 'qlsm-addon.json'
        if not manifest_path.is_file():
            print(f'WARNING: {addon_dir.name}/ has no qlsm-addon.json -- skipped',
                  file=sys.stderr)
            continue
        try:
            addon_manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        except ValueError as e:
            print(f'WARNING: {manifest_path} is not valid JSON ({e}) -- skipped',
                  file=sys.stderr)
            continue
        addon_id = addon_manifest.get('id') or addon_dir.name
        zip_rel = f'packages/{addon_id}.zip'
        zip_path = ROOT / zip_rel
        _zip_addon(addon_dir, zip_path)

        prev = by_id.get(addon_id, {})
        entry = {
            'id': addon_id,
            'zip': zip_rel,
            'sha256': _sha256_file(zip_path),
        }
        version = addon_manifest.get('version') or prev.get('version')
        if version:
            entry['version'] = version
        label = addon_manifest.get('name') or prev.get('label')
        if label:
            entry['label'] = label
        description = addon_manifest.get('description') or prev.get('description')
        if description:
            entry['description'] = description
        if prev.get('requires_qlsm_version'):
            entry['requires_qlsm_version'] = prev['requires_qlsm_version']
        entries.append(entry)
        print(f'Packed {zip_rel} ({zip_path.stat().st_size} bytes)')
    return entries


def main() -> int:
    if MANIFEST.is_file():
        data = json.loads(MANIFEST.read_text(encoding='utf-8'))
    else:
        data = {}
    if not isinstance(data, dict):
        data = {}

    plugins, missing = _plugin_entries(data.get('plugins') or [])
    addons = _addon_entries(data.get('addons') or [])

    out = {'plugins': plugins, 'addons': addons}
    MANIFEST.write_text(json.dumps(out, indent=2) + '\n', encoding='utf-8')

    for name in missing:
        print(f'WARNING: {name} is listed but missing on disk -- sha256 left as-is',
              file=sys.stderr)
    print(f'Updated {MANIFEST.name}: {len(plugins)} plugins, {len(addons)} addons.')
    return 1 if missing else 0


if __name__ == '__main__':
    raise SystemExit(main())
