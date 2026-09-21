# demo_native_manifest.py — argv builder for the external qlmatch-packer,
# used by demo_native_autorecord.py.
#
# Deliberately has NO minqlx import so it can be unit-tested without a live
# QLDS/minqlx process (see tests/test_demo_native_manifest.py) — same split
# addons/telemetry/minqlx/telemetry_unified_sched.py already established for
# this codebase's other pure per-plugin helpers.
#
# This module used to also build the .qlmatch manifest/zip itself, as an
# in-process fallback for when the external packer/Node was missing on a
# host. That fallback was removed once the qlmatch-packer addon became the
# format's sole owner (see addons/qlmatch-packer/): .qlmatch is now entirely
# that addon's format, not something this plugin can produce on its own.
# What's left here is just the pure, testable argv-building for launching
# the external packer as a separate process.

from __future__ import annotations

# Where the qlmatch-packer addon's host.payload_sync hook deploys the
# external Node packer on every managed host. demo_native_autorecord.py
# launches it as a separate process (it adds name templating and rclone
# delivery on top of a plain zip build) - see that addon for the deploy.
QLMATCH_PACKER_SCRIPT = "/home/ql/qlmatch-packer/pack.mjs"


def packer_command(node, packer_script, demo_dir, match_id, map_name="",
                   name_template="", rclone_targets=""):
    """argv for one external qlmatch-packer run. Pure/testable: no cvar
    reads, no spawn — the plugin resolves node/cvars and passes them in.
    Optional values are appended only when non-empty so the packer's own
    defaults apply otherwise — in particular --map: with it absent the
    packer reads mapname out of each POV's own gamestate serverinfo, which
    is authoritative where a caller-side value may be stale or guessed."""
    cmd = [node, packer_script,
           "--dir", demo_dir,
           "--match-id", match_id]
    if map_name:
        cmd += ["--map", map_name]
    if name_template:
        cmd += ["--name-template", name_template]
    if rclone_targets:
        cmd += ["--rclone-targets", rclone_targets]
    return cmd
