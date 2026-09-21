"""Rebuild logic for .qlmatch packs and their replay sidecars.

Runs the Node scripts (pack.mjs / qlmatch-to-replay.mjs) over SSH on the game
host, triggered by an operator from the qlsm UI -- there is no automatic
trigger on demo_match_finalized (see qlmatch-packer's own assets/README.md).
Also useful e.g. after a bug fix in vendor/qldemo's replay generation, to
regenerate sidecars for matches that already finished and are just sitting
on disk.
"""
import os
import posixpath
import re
import shlex

from .instance_demo_transport import (
    demo_dir_for_instance, list_dir_entries, open_sftp, resolve_instance_and_host, run_remote_command,
)
from .cvar_text import read_cvars_from_text

from .qlmatch_listing import QLMATCH_FILENAME_RE, qlmatch_sidecar_name, read_qlmatch_manifest

# Where the qlmatch-packer addon's host.payload_sync hook deploys the
# external Node packer -- see playbooks/sync_qlmatch_packer.yml.
PACKER_REMOTE_DIR = '/home/ql/qlmatch-packer'

# Generous ceiling for one pack.mjs run over SSH (parsing N POVs + zipping +
# rclone uploads, whose own per-target rclone timeout is 10 min).
REMOTE_NODE_TIMEOUT_SECONDS = 1800


class RebuildError(RuntimeError):
    """A rebuild failure with a message safe to show the operator."""


def _instance_and_dir(instance_id):
    instance, host, error = resolve_instance_and_host(instance_id)
    if error:
        raise RebuildError(error)
    return instance, host, demo_dir_for_instance(instance)


def _validate_qlmatch_filename(filename):
    if not isinstance(filename, str) or not filename.endswith('.qlmatch') \
            or not QLMATCH_FILENAME_RE.fullmatch(filename):
        raise RebuildError(f'Invalid qlmatch filename: {filename!r}')


def _read_manifest_or_raise(instance_id, filename):
    ok, manifest, error = read_qlmatch_manifest(instance_id, filename)
    if not ok:
        raise RebuildError(error)
    return manifest


def _read_packer_cvars(instance):
    """(name_template, rclone_targets) from the instance's own server.cfg on
    qlsm's local disk (the config source of truth qlsm pushes to hosts) --
    the same two cvars pack.mjs itself reads, set by hand in server.cfg
    (there is no Plugins-tab UI for them), so a rebuild matches whatever the
    operator already configured instead of falling back to the packer's bare
    defaults."""
    config_path = os.path.join('configs', instance.host.name, str(instance.id), 'server.cfg')
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            text = f.read()
    except FileNotFoundError:
        return '', ''
    cvars = read_cvars_from_text(text, ('qlx_qlmatchNameTemplate', 'qlx_qlmatchRcloneTargets'))
    return cvars.get('qlx_qlmatchNameTemplate', ''), cvars.get('qlx_qlmatchRcloneTargets', '')


def rebuild_sidecar_logic(instance_id, filename):
    """Regenerate the .replay.json.gz sidecar for an existing .qlmatch pack.

    Does not touch the game server or need raw .dm_91 files -- runs
    qlmatch-to-replay.mjs directly against the pack already on disk, the
    same script pack.mjs itself calls after a fresh capture (see its own
    "safe to run by hand for older packs" docstring).
    """
    _validate_qlmatch_filename(filename)
    _instance, host, demo_dir = _instance_and_dir(instance_id)
    manifest = _read_manifest_or_raise(instance_id, filename)
    sidecar_name = qlmatch_sidecar_name(manifest['match_id'], manifest['map'])

    pack_path = posixpath.join(demo_dir, filename)
    sidecar_path = posixpath.join(demo_dir, sidecar_name)
    command = (
        f"cd {shlex.quote(PACKER_REMOTE_DIR)} && "
        f"node qlmatch-to-replay.mjs {shlex.quote(pack_path)} -o {shlex.quote(sidecar_path)}"
    )
    exit_status, stdout, stderr = run_remote_command(host, command, timeout=REMOTE_NODE_TIMEOUT_SECONDS)
    if exit_status != 0:
        raise RebuildError((stderr or stdout or f'exit status {exit_status}').strip()[:500])
    return {'filename': filename, 'sidecar_name': sidecar_name}


def _raw_povs_present(host, demo_dir, match_id):
    """Whether any '{match_id}_*.dm_91' file the packer would consume is
    still on disk -- mirrors pack.mjs's own discoverPovFiles() selection."""
    client, sftp = open_sftp(host)
    try:
        pattern = re.compile(re.escape(match_id) + r'_.*\.dm_91')
        return bool(list_dir_entries(sftp, demo_dir, pattern))
    finally:
        client.close()


def rebuild_full_logic(instance_id, filename):
    """Re-run the packer from scratch: raw .dm_91 -> new .qlmatch + sidecar.

    Refuses early if the raw per-POV files are no longer on disk -- the
    packer would fail on the host anyway (exit 3, "no POV files found"), and
    a readable refusal here beats a queued job that fails minutes later for
    a reason the operator has to go dig a log out for.
    """
    _validate_qlmatch_filename(filename)
    instance, host, demo_dir = _instance_and_dir(instance_id)
    manifest = _read_manifest_or_raise(instance_id, filename)
    match_id, map_name = manifest['match_id'], manifest['map']

    if not _raw_povs_present(host, demo_dir, match_id):
        raise RebuildError(
            f'No raw .dm_91 files for match {match_id} remain in {demo_dir} -- '
            'full rebuild needs them; only "Rebuild sidecar" is possible now.'
        )

    name_template, rclone_targets = _read_packer_cvars(instance)
    command_parts = [
        'cd', shlex.quote(PACKER_REMOTE_DIR), '&&', 'node', 'pack.mjs',
        '--dir', shlex.quote(demo_dir), '--match-id', shlex.quote(match_id), '--map', shlex.quote(map_name),
    ]
    if name_template:
        command_parts += ['--name-template', shlex.quote(name_template)]
    if rclone_targets:
        command_parts += ['--rclone-targets', shlex.quote(rclone_targets)]
    command = ' '.join(command_parts)

    exit_status, stdout, stderr = run_remote_command(host, command, timeout=REMOTE_NODE_TIMEOUT_SECONDS)
    if exit_status != 0:
        raise RebuildError((stderr or stdout or f'exit status {exit_status}').strip()[:500])
    return {'filename': filename, 'match_id': match_id, 'map': map_name}
