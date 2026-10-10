"""Server-side demo listing for QLDS instances.

minqlxtended's native demo-match capture (see ql-assets/patches/minqlxtended/
minqlxtended-patches/demo_match.c) writes finished .dm_91 files under
fs_homepath/sv_demoDir, which for a qlsm-managed instance is
/home/ql/qlds-<port>/demos (sv_demoDir defaults to "demos" and is not
overridden anywhere in this repo). That per-POV .dm_91 output is the same
directory the plain sv_demoRecord path already writes flat, single-file
demos to, so both show up in the same listing here without any extra
plumbing.

By default this module recognises ONLY .dm_91 -- it has no opinion on any
packed/derived format built from those files. Another addon can extend the
recognised set via the demo_management.file_kinds hook (see
_demo_filename_re() below); qlmatch-packer is the bundled example,
contributing .qlmatch/.replay.json.gz so those show up here too, but only
while that addon is loaded and enabled.

This module lists those files so an operator can verify a manual
demo-recording test actually produced a file, without SSHing into the host
by hand.

Listing and fetching both talk directly to the host over SFTP (paramiko),
the same key-authenticated, no-persisted-host-key management channel as
service_runtime.py's runtime probe and rcon_transport.py's live rcon - not
ansible-playbook: these are simple stat/read operations with no templating
or privilege escalation to justify Ansible's overhead, so a plain SFTP
listdir + open is both faster and simpler to reason about than shelling out
to ansible-playbook for a two-line remote operation. The SFTP plumbing
itself lives in this addon's own instance_demo_transport.py - a private copy,
not a core module: qlmatch-packer carries its own, for the reasons in qlsm's
addons/README.md ("Where the line falls").

Lives inside the demo-management addon (moved from ui/task_logic/ in core,
and out of qlsm's image entirely once the addon moved to qlsm-extra). The
addon's own JWT-protected panel calls straight into this module -
uninstalling this addon now genuinely removes demo listing/download.
"""
import logging
import re
import stat as stat_module
import time

import paramiko

from ui.addons import dispatch
from .demo_meta import (
    META_FILENAME_RE, META_MAX_BYTES, annotate, cache_get_many, cache_put_many, parse_meta,
)
from .instance_demo_transport import (
    demo_dir_for_instance, fetch_files, list_dir_entries_bytes, open_sftp, read_small_files,
    resolve_instance_and_host,
)

log = logging.getLogger(__name__)

# demo_build_pov_name()'s output in demo_match.c ends in ".dm_91". Other
# addons extend this set via the demo_management.file_kinds hook -- see
# _demo_filename_re().
_BASE_EXTENSIONS = ('dm_91',)

# What a demo's base name may contain. The engine now keeps UTF-8 player
# names (Cyrillic etc.) in POV filenames, so this is a deny-list of what
# makes a name unsafe as a path component rather than an ASCII allow-list:
#   - no "/" or "\" -- the name is joined onto demo_dir by concatenation,
#     so a separator would escape it;
#   - no C0/C1 control characters or DEL (NUL, newline, escape sequences in
#     logs, header injection in Content-Disposition);
#   - no leading "." -- that also rules out "." and "..", and hides dotfiles
#     such as pack.mjs's ".{match_id}.meta.json.part";
#   - no leading "-", so a name can never read as an option if it ever ends
#     up on a command line.
# Bounded length: ext4 caps a name at 255 BYTES, and a Cyrillic character is
# two, so 240 characters is a loose upper bound, not the real limit.
_NAME_BODY = r'(?![.-])[^/\\\x00-\x1f\x7f-\x9f]{1,240}'

# Generous but bounded: a batch this large would already take minutes to
# fetch one-by-one over SFTP, so this is a sanity cap, not a realistic usage
# ceiling.
MAX_DEMO_BATCH = 200


def _demo_filename_re():
    """Regex matching every filename this addon recognises as a "demo" for
    listing/download purposes: the base .dm_91 extension plus whatever other
    loaded+enabled addons contributed via demo_management.file_kinds.

    Built fresh on every call -- cheap (a handful of string ops), and avoids
    a regex compiled once at import time going stale when an addon gets
    enabled/disabled at runtime without a QLSM restart.
    """
    extensions = list(_BASE_EXTENSIONS)
    try:
        for contributed in dispatch('demo_management.file_kinds', 0):
            if isinstance(contributed, str) and contributed:
                extensions.append(contributed)
    except Exception as e:
        log.warning('demo_management.file_kinds hook skipped: %s', e)
    pattern = '|'.join(re.escape(ext) for ext in extensions)
    # \A/\Z (not ^/$): this value reaches both a remote and a local
    # filesystem path built by string concatenation, and $ still matches
    # before a trailing newline under .fullmatch().
    return re.compile(r'\A%s\.(?:%s)\Z' % (_NAME_BODY, pattern))


def _listing_entries(client, sftp, demo_dir, demo_re, timing):
    """One directory listing, split into (demo entries, meta entries).

    Both are regular files directly under demo_dir; metas are matched by
    demo_meta.META_FILENAME_RE and never shown as demos themselves.

    SFTP's listdir_attr is the normal path. If any name in the directory is
    not valid UTF-8, paramiko fails the WHOLE listing while decoding it, so
    that case falls back to one remote `find` that decodes names one by one
    and skips the undecodable ones (counted in timing["skipped_names"]).
    """
    try:
        rows = [
            {'name': e.filename, 'size': e.st_size, 'mtime': e.st_mtime}
            for e in sftp.listdir_attr(demo_dir)
            if e.st_mode is not None and stat_module.S_ISREG(e.st_mode)
        ]
    except FileNotFoundError:
        rows = []
    except UnicodeDecodeError:
        rows, skipped = list_dir_entries_bytes(client, demo_dir)
        timing['skipped_names'] = skipped
        log.warning(f"{demo_dir} has {skipped} non-UTF-8 file name(s); "
                    "listed the rest with find and left those out")

    demos, metas = [], []
    for row in rows:
        if demo_re.fullmatch(row['name']):
            demos.append(row)
        elif META_FILENAME_RE.fullmatch(row['name']):
            metas.append(row)
    return demos, metas


def _load_metas(instance_id, client, demo_dir, meta_entries, timing):
    """{match_id: parsed meta} for every listed meta file.

    Redis first (keyed by name+size+mtime, so never stale); the misses are
    read in one remote exec on the already-open connection. Any failure here
    only costs the labels - the listing itself still succeeds, falling back
    to the engine's filename contract.
    """
    if not meta_entries:
        return {}
    cached = cache_get_many(instance_id, meta_entries)
    misses = [e for e in meta_entries if e['name'] not in cached]
    timing['meta_cached'] = len(cached)
    timing['meta_read'] = len(misses)

    parsed = dict(cached)
    if misses:
        started = time.monotonic()
        try:
            raw = read_small_files(client, demo_dir, [e['name'] for e in misses], META_MAX_BYTES)
        except (paramiko.SSHException, OSError) as exc:
            log.warning(f"Reading demo metas for instance {instance_id} failed: {exc}")
            raw = {}
        to_cache = []
        for entry in misses:
            if entry['name'] not in raw:
                continue  # vanished, or the exec failed: retry next listing
            match_id = META_FILENAME_RE.fullmatch(entry['name']).group(1)
            meta = parse_meta(raw[entry['name']], match_id)
            parsed[entry['name']] = meta
            to_cache.append((entry, meta))
        cache_put_many(instance_id, to_cache)
        timing['meta_read_ms'] = round((time.monotonic() - started) * 1000)

    return {meta['match_id']: meta for meta in parsed.values() if meta}


def list_instance_listing(instance_id):
    """List an instance's demo dir with every file labelled.

    Returns (success, listing, error_msg). listing is
    {"demos": [...], "infos": {match_id: info}, "timing": {...}}; each demo
    is {"name", "size", "mtime"} plus the labels demo_meta.annotate() adds,
    newest first. "timing" holds per-phase milliseconds, logged here and
    passed through to the caller so a slow listing says where it went.
    """
    timing = {}
    started = time.monotonic()

    def mark(phase, since):
        now = time.monotonic()
        timing[f'{phase}_ms'] = round((now - since) * 1000)
        return now

    client = None
    try:
        instance, host, instance_error = resolve_instance_and_host(instance_id)
        if instance_error:
            log.error(f"Cannot list demos for instance {instance_id}: {instance_error}")
            return False, None, instance_error

        demo_dir = demo_dir_for_instance(instance)
        demo_re = _demo_filename_re()

        step = time.monotonic()
        client, sftp = open_sftp(host)
        step = mark('connect', step)

        demos, meta_entries = _listing_entries(client, sftp, demo_dir, demo_re, timing)
        step = mark('listdir', step)
        timing['files'] = len(demos)
        timing['metas'] = len(meta_entries)

        metas = _load_metas(instance_id, client, demo_dir, meta_entries, timing)
        mark('meta', step)

        infos = annotate(demos, metas)
        demos.sort(key=lambda d: d.get('mtime') or 0, reverse=True)
        mark('total', started)
        log.debug(f"Listed demos for instance {instance_id} on host {host.name}: {timing}")
        return True, {'demos': demos, 'infos': infos, 'timing': timing}, None

    except (paramiko.AuthenticationException, paramiko.SSHException, OSError) as exc:
        log.error(f"SSH failure listing demos for instance {instance_id}: {exc}")
        return False, None, "Failed to list demos from remote host."
    except Exception as e:
        log.exception(f"Exception listing demos for instance {instance_id}: {e}")
        return False, None, "Failed to list demos."
    finally:
        if client is not None:
            client.close()


def list_instance_demos(instance_id):
    """List server-side demo files recognised for an instance (.dm_91 plus
    whatever other addons contributed).

    Returns a tuple: (success: bool, demos: list[dict], error_msg: str or None)
    where each dict is {"name", "size", "mtime"} plus demo_meta's labels,
    newest first. Thin wrapper over list_instance_listing for callers that
    only want the files.
    """
    success, listing, error = list_instance_listing(instance_id)
    return success, (listing['demos'] if success else []), error


def fetch_instance_demos(instance_id, filenames):
    """Fetch one or more demo files from the remote host into memory. See
    instance_demo_transport.fetch_files for the return shape."""
    return fetch_files(instance_id, filenames, _demo_filename_re(), MAX_DEMO_BATCH)
