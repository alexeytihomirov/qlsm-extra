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

import paramiko

from ui.addons import dispatch
from .instance_demo_transport import (
    demo_dir_for_instance, fetch_files, list_dir_entries, open_sftp, resolve_instance_and_host,
)

log = logging.getLogger(__name__)

# Matches demo_build_pov_name()'s output in demo_match.c (sanitised to
# [A-Za-z0-9_-] plus the literal ".dm_91" suffix). Other addons extend this
# set via the demo_management.file_kinds hook -- see _demo_filename_re().
_BASE_EXTENSIONS = ('dm_91',)

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
    return re.compile(r'\A[A-Za-z0-9._-]+\.(?:%s)\Z' % pattern)


def list_instance_demos(instance_id):
    """List server-side demo files recognised for an instance (.dm_91 plus
    whatever other addons contributed).

    Returns a tuple: (success: bool, demos: list[dict], error_msg: str or None)
    where each dict is {"name": str, "size": int, "mtime": float}, newest
    first.
    """
    client = None
    try:
        instance, host, instance_error = resolve_instance_and_host(instance_id)
        if instance_error:
            log.error(f"Cannot list demos for instance {instance_id}: {instance_error}")
            return False, [], instance_error

        demo_dir = demo_dir_for_instance(instance)
        log.info(f"Listing demos for instance {instance_id} on host {host.name}...")

        client, sftp = open_sftp(host)
        demos = list_dir_entries(sftp, demo_dir, _demo_filename_re())
        demos.sort(key=lambda d: d.get('mtime') or 0, reverse=True)
        return True, demos, None

    except (paramiko.AuthenticationException, paramiko.SSHException, OSError) as exc:
        log.error(f"SSH failure listing demos for instance {instance_id}: {exc}")
        return False, [], "Failed to list demos from remote host."
    except Exception as e:
        log.exception(f"Exception listing demos for instance {instance_id}: {e}")
        return False, [], "Failed to list demos."
    finally:
        if client is not None:
            client.close()


def fetch_instance_demos(instance_id, filenames):
    """Fetch one or more demo files from the remote host into memory. See
    instance_demo_transport.fetch_files for the return shape."""
    return fetch_files(instance_id, filenames, _demo_filename_re(), MAX_DEMO_BATCH)
