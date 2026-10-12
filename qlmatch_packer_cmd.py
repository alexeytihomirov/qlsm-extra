# qlmatch_packer_cmd.py - argv builder for the external qlmatch-packer,
# used by qlmatch_packer.py.
#
# Deliberately has NO minqlx import so it can be unit-tested without a live
# QLDS/minqlx process (tests/test_qlmatch_packer_plugin.py).

from __future__ import annotations

# Where the qlmatch-packer addon's host.payload_sync hook deploys the
# external Node packer on every managed host. qlmatch_packer.py launches it
# as a separate process.
QLMATCH_PACKER_SCRIPT = "/home/ql/qlmatch-packer/pack.mjs"


def packer_command(node, packer_script, demo_dir, match_id, map_name="",
                   name_template=""):
    """argv for one external qlmatch-packer run. Pure/testable: no cvar
    reads, no spawn - the plugin resolves node/cvars and passes them in.
    Optional values are appended only when non-empty so the packer's own
    defaults apply otherwise - in particular --map: with it absent the
    packer reads mapname out of each POV's own gamestate serverinfo, which
    is authoritative where a caller-side value may be stale or guessed.
    Delivery is not the packer's job: the file-forwarder addon ships the
    finished files off the host."""
    cmd = [node, packer_script,
           "--dir", demo_dir,
           "--match-id", match_id]
    if map_name:
        cmd += ["--map", map_name]
    if name_template:
        cmd += ["--name-template", name_template]
    return cmd
