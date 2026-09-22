#!/usr/bin/env python3
"""Verify qlsm-repository.json sha256 values match files on disk.

Same hashing rules as generate_manifest.py:
  - plugin .py and package_files: LF-normalized sha256
  - addon zip packages: raw sha256 (no EOL normalize)

Exit 0 when every listed hash matches. Exit 1 with a per-path report
otherwise. Intended for the pre-commit hook and for manual runs.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from generate_manifest import MANIFEST, ROOT, _sha256_file


def _check(path: Path, expected: str, *, normalize_eol: bool) -> str | None:
    """Return an error line, or None if ok."""
    try:
        rel = path.relative_to(ROOT).as_posix()
    except ValueError:
        rel = str(path)
    if not path.is_file():
        return f'  MISSING  {rel}  (manifest expects sha256={expected})'
    actual = _sha256_file(path, normalize_eol=normalize_eol)
    if actual != expected:
        return (
            f'  MISMATCH {rel}\n'
            f'    manifest: {expected}\n'
            f'    on disk:  {actual}'
        )
    return None


def check_manifest(manifest_path: Path = MANIFEST) -> list[str]:
    errors: list[str] = []
    if not manifest_path.is_file():
        return [f'  MISSING  {manifest_path.name} (nothing to verify)']

    try:
        data = json.loads(manifest_path.read_text(encoding='utf-8'))
    except ValueError as e:
        return [f'  INVALID {manifest_path.name}: {e}']

    if not isinstance(data, dict):
        return [f'  INVALID {manifest_path.name}: root must be an object']

    for entry in data.get('plugins') or []:
        if not isinstance(entry, dict):
            continue
        filename = entry.get('filename')
        sha = entry.get('sha256')
        if isinstance(filename, str) and isinstance(sha, str):
            err = _check(ROOT / filename, sha, normalize_eol=True)
            if err:
                errors.append(err)
        package_files = entry.get('package_files')
        if isinstance(package_files, dict):
            for relpath, file_sha in package_files.items():
                if not isinstance(relpath, str) or not isinstance(file_sha, str):
                    continue
                err = _check(ROOT / relpath, file_sha, normalize_eol=True)
                if err:
                    errors.append(err)

    for entry in data.get('addons') or []:
        if not isinstance(entry, dict):
            continue
        zip_rel = entry.get('zip')
        sha = entry.get('sha256')
        if isinstance(zip_rel, str) and isinstance(sha, str):
            err = _check(ROOT / zip_rel, sha, normalize_eol=False)
            if err:
                errors.append(err)

    return errors


def main() -> int:
    errors = check_manifest()
    if not errors:
        print(f'{MANIFEST.name}: all sha256 hashes match on-disk files.')
        return 0
    print(
        f'{MANIFEST.name}: {len(errors)} hash mismatch(es) vs files on disk.\n'
        'Re-run `python generate_manifest.py` and commit the updated '
        'qlsm-repository.json (and packages/*.zip if addons changed).\n',
        file=sys.stderr,
    )
    for err in errors:
        print(err, file=sys.stderr)
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
