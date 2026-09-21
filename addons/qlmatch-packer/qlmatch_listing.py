"""Listing/manifest logic specific to the .qlmatch pack format.

Moved out of demo-management's ansible_instance_demos.py when qlmatch-packer
became its own addon: demo-management only knows raw .dm_91 by default (see
its demo_management.file_kinds hook dispatch), everything that has to
understand the .qlmatch zip's internal manifest.json lives here instead.
Uses the same SFTP plumbing demo-management uses, via this addon's own
private copy (see .instance_demo_transport's docstring for why it is a copy
and not shared).
"""
import json
import re
import zipfile

import paramiko

from .instance_demo_transport import (
    demo_dir_for_instance, fetch_files, list_dir_entries, open_sftp, resolve_instance_and_host,
)
from ui.task_logic.common import log

# The .qlmatch packs (qlmatch-packer's templated names all sanitise to this
# charset), the packer's per-match "{match_id}.packer.log", and its
# merged-replay sidecar "{match_id}_{map}.replay.json.gz". Anchored with
# \A/\Z (not ^/$) since this value reaches a remote/local path built by
# string concatenation and $ still matches before a trailing newline under
# .fullmatch().
QLMATCH_FILENAME_RE = re.compile(r'\A[A-Za-z0-9._-]+\.(?:qlmatch|packer\.log|replay\.json\.gz)\Z')

# Suffixes contributed to demo-management's demo_management.file_kinds hook
# (without the leading dot -- matches the alternation group above). Deliberately
# excludes packer.log: that file is still written on the host and still
# matched by QLMATCH_FILENAME_RE below (SFTP ops still need to recognise it),
# it's just never surfaced in the Demos widget listing.
FILE_KIND_EXTENSIONS = ['qlmatch', 'replay.json.gz']

# Mirrors restore/qlmatch.py's SIDECAR_EXT / sidecar_path_for(): the packer
# always names a pack's replay sidecar "{match_id}_{map}.replay.json.gz",
# regardless of what qlx_qlmatchNameTemplate made the .qlmatch's own filename
# look like (see qlmatch-to-replay.mjs / pack.mjs) - so a .qlmatch and its
# sidecar can NOT be paired by string-editing the .qlmatch filename; the
# match_id/map have to come from the pack's own manifest.json.
SIDECAR_EXT = '.replay.json.gz'

MAX_QLMATCH_BATCH = 200

# manifest.json is immutable for a given (filename, size, mtime): a pack is
# never edited in place, only rewritten wholesale by rebuild-sidecar/
# rebuild-full, which always changes mtime (and usually size). Keying the
# cache on all three means a stale entry can never be read back for new
# content, so every listing/grouping call after the first for an unchanged
# pack skips the remote SFTP open + zip read entirely -- with dozens of
# packs that open was the dominant cost of the Demos list, since each one is
# its own network round trip on top of the directory listing itself.
_MANIFEST_CACHE = {}
_MANIFEST_CACHE_MAX = 4000


def qlmatch_sidecar_name(match_id, map_name):
    """The replay sidecar filename for a given manifest match_id/map."""
    return f"{match_id}_{map_name}{SIDECAR_EXT}"


def _manifest_from_pack(sftp, demo_dir, filename, cache_key=None):
    """Read {match_id, map, raw_demo_names} out of a .qlmatch pack's
    manifest.json, using an already-open SFTP session (caller owns
    connect/close - this must never open its own, so a listing that checks
    many packs pays for one SSH handshake total, not one per pack).

    Opens the remote pack through a seekable SFTP file handle and hands it
    straight to zipfile, so only the central directory and the small
    manifest.json member are fetched - not the multi-MB demos/*.dm_91
    payload the rest of the zip carries.

    `cache_key`, when given, is typically (instance_id, filename, size,
    mtime): a hit skips the SFTP round trip entirely. Errors are never
    cached, so a transient failure (pack mid-write, network hiccup) retries
    on the next call instead of sticking.

    Returns a tuple: (manifest: dict or None, error_msg: str or None) where
    manifest is {"match_id": str, "map": str, "raw_demo_names": list[str]} --
    the last being the basenames of the raw .dm_91 POV files this pack was
    built from (per manifest["demos"][*]["file"]), so callers can relate a
    pack back to its still-on-disk sources (packing copies them into the
    zip, it never deletes the originals -- see pack.mjs / rebuild_ops.py).
    """
    if cache_key is not None and cache_key in _MANIFEST_CACHE:
        return _MANIFEST_CACHE[cache_key], None

    try:
        with sftp.open(f"{demo_dir}/{filename}", 'rb') as fh:
            with zipfile.ZipFile(fh) as zf:
                raw = zf.read('manifest.json')
    except FileNotFoundError:
        return None, "Qlmatch file not found on the remote host."
    except (KeyError, zipfile.BadZipFile) as exc:
        return None, f"Could not read manifest.json from pack: {exc}"

    try:
        manifest = json.loads(raw.decode('utf-8'))
    except (ValueError, UnicodeDecodeError) as exc:
        return None, f"Malformed manifest.json: {exc}"

    if not isinstance(manifest, dict):
        return None, "Malformed manifest.json: not an object."

    match_id = str(manifest.get('match_id') or '')
    map_name = str(manifest.get('map') or '')
    if not match_id or not map_name:
        return None, "manifest.json missing match_id or map."

    raw_demo_names = []
    for entry in manifest.get('demos') or []:
        file_field = entry.get('file') if isinstance(entry, dict) else None
        if isinstance(file_field, str) and file_field:
            raw_demo_names.append(file_field.rsplit('/', 1)[-1])

    result = {'match_id': match_id, 'map': map_name, 'raw_demo_names': raw_demo_names}
    if cache_key is not None:
        if len(_MANIFEST_CACHE) >= _MANIFEST_CACHE_MAX:
            _MANIFEST_CACHE.clear()
        _MANIFEST_CACHE[cache_key] = result
    return result, None


def read_qlmatch_manifest(instance_id, filename):
    """Read {match_id, map, raw_demo_names} out of a single named .qlmatch
    pack's manifest.json.

    Opens its own one-off SFTP session - fine for a single lookup (e.g. the
    download-by-name endpoints), but NOT what list_instance_qlmatches uses
    for a whole directory: see _manifest_from_pack for why. Never goes
    through the manifest cache -- a single lookup doesn't have a `demos`
    row's (size, mtime) handy to key it, and callers of this path (e.g.
    rebuild-full endpoints) want the freshest read anyway.

    Returns a tuple: (success: bool, manifest: dict or None, error_msg: str
    or None) where manifest is {"match_id": str, "map": str, "raw_demo_names":
    list[str]} -- see _manifest_from_pack for what the last means.
    """
    if not isinstance(filename, str) or not filename.endswith('.qlmatch') \
            or not QLMATCH_FILENAME_RE.fullmatch(filename):
        return False, None, f"Invalid qlmatch filename: {filename!r}"

    client = None
    try:
        instance, host, instance_error = resolve_instance_and_host(instance_id)
        if instance_error:
            log.error(f"Cannot read qlmatch manifest for instance {instance_id}: {instance_error}")
            return False, None, instance_error

        demo_dir = demo_dir_for_instance(instance)
        client, sftp = open_sftp(host)

        manifest, error_msg = _manifest_from_pack(sftp, demo_dir, filename)
        if error_msg:
            return False, None, error_msg
        return True, manifest, None

    except (paramiko.AuthenticationException, paramiko.SSHException, OSError) as exc:
        log.error(f"SSH failure reading qlmatch manifest for instance {instance_id}: {exc}")
        return False, None, "Failed to read qlmatch manifest from remote host."
    except Exception as e:
        log.exception(f"Exception reading qlmatch manifest for instance {instance_id}: {e}")
        return False, None, "Failed to read qlmatch manifest."
    finally:
        if client is not None:
            client.close()


def list_instance_qlmatches(instance_id):
    """List .qlmatch packs for an instance, flagging replay-sidecar availability.

    Lists the demos/ directory and reads every pack's manifest.json within a
    SINGLE SFTP session - one read_qlmatch_manifest() call per pack would
    each open their own SSH connection, which turns an instance with a
    handful of packs into a handful of sequential SSH handshakes (seconds)
    for what should be one `listdir` and a few small in-session reads (well
    under a second).

    Returns a tuple: (success: bool, matches: list[dict], error_msg: str or
    None) where each dict is {"name", "size", "mtime", "has_replay",
    "replay_name"}, newest first.
    """
    client = None
    try:
        instance, host, instance_error = resolve_instance_and_host(instance_id)
        if instance_error:
            log.error(f"Cannot list qlmatches for instance {instance_id}: {instance_error}")
            return False, [], instance_error

        demo_dir = demo_dir_for_instance(instance)
        log.info(f"Listing qlmatches for instance {instance_id} on host {host.name}...")

        client, sftp = open_sftp(host)
        demos = list_dir_entries(sftp, demo_dir, QLMATCH_FILENAME_RE)
        names = {d['name'] for d in demos}

        matches = []
        for d in demos:
            if not d['name'].endswith('.qlmatch'):
                continue
            cache_key = (instance_id, d['name'], d.get('size'), d.get('mtime'))
            manifest, _error_msg = _manifest_from_pack(sftp, demo_dir, d['name'], cache_key=cache_key)
            replay_name = (
                qlmatch_sidecar_name(manifest['match_id'], manifest['map'])
                if manifest else None
            )
            matches.append({
                'name': d['name'],
                'size': d['size'],
                'mtime': d['mtime'],
                'has_replay': bool(replay_name) and replay_name in names,
                'replay_name': replay_name if replay_name in names else None,
            })

        matches.sort(key=lambda m: m.get('mtime') or 0, reverse=True)
        return True, matches, None

    except (paramiko.AuthenticationException, paramiko.SSHException, OSError) as exc:
        log.error(f"SSH failure listing qlmatches for instance {instance_id}: {exc}")
        return False, [], "Failed to list qlmatches from remote host."
    except Exception as e:
        log.exception(f"Exception listing qlmatches for instance {instance_id}: {e}")
        return False, [], "Failed to list qlmatches."
    finally:
        if client is not None:
            client.close()


def fetch_qlmatch_files(instance_id, filenames):
    """Fetch one or more .qlmatch/.replay.json.gz/.packer.log files from an
    instance's demo dir into memory. See .instance_demo_transport.fetch_files."""
    return fetch_files(instance_id, filenames, QLMATCH_FILENAME_RE, MAX_QLMATCH_BATCH)
