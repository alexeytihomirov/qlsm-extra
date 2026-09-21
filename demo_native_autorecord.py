# demo_native_autorecord.py - launches the external qlmatch-packer when the
# engine finishes a match's demos.
#
# Since the demo-cut redesign in the minqlxtended fork (commits 10bff3c, 49f1eec and 2b7e094,
# branch demo-match-capture), the engine finds, cuts and finalises match
# demos entirely on its own: sv_demoRecord 1 records every client (upstream
# semantics), sv_demoCut 1 turns on the match machinery - game_events.c
# detects the countdown/start/end crossings in C and demo_match.c arms,
# cuts and match-names the files. No plugin arms anything anymore; the
# demo_arm()/demo_disarm() Python bindings are gone from the build.
#
# What is left for Python is the one thing that is not the engine's
# business: packaging. When every file of a match has reached final form
# (cut + indexed), the engine fires demo_match_finalized(match_id), and
# this plugin launches the external qlmatch-packer (addons/qlmatch-packer/
# assets/, deployed to /home/ql/qlmatch-packer/ by that addon's own
# host.payload_sync hook) as a SEPARATE process - it parses the POVs,
# builds the .qlmatch zip, renders the filename template and delivers via
# rclone, keeping all of that out of the QLDS process per the .qlmatch
# contract's "separate process / worker, never on the QLDS frame"
# requirement. The packer derives map/gametype/rosters from the demos
# themselves, so this plugin passes only the match_id and the demo dir.
#
# When the packer or node is missing on the host, this plugin logs a
# warning and leaves the match's cut .dm_91 files as-is - .qlmatch is
# entirely the qlmatch-packer addon's format.
#
# CVARs:
#   qlx_qlmatchNameTemplate      ""   - output name template, no extension
#                                       (placeholders: see qlmatch-packer
#                                       README; empty = {match_id}_{map})
#   qlx_qlmatchRcloneTargets     ""   - comma-separated rclone destinations
#                                       for the finished .qlmatch (empty =
#                                       no delivery, file stays local only)
#   qlx_qlmatchPackerPath        "/home/ql/qlmatch-packer/pack.mjs"

import os
import shutil
import subprocess

try:
    import minqlxtended as minqlx
except ImportError:
    import minqlx

try:
    from demo_native_manifest import QLMATCH_PACKER_SCRIPT, packer_command
except ImportError:
    from .demo_native_manifest import QLMATCH_PACKER_SCRIPT, packer_command

# One packer run covers parsing N POVs + zipping + rclone uploads; the
# packer's own internal rclone timeout is 10 min per target, so give the
# whole run comfortably more before declaring it hung. This wait happens on
# the @minqlx.thread worker below, never on the game thread.
PACKER_TIMEOUT_SEC = 30 * 60


class demo_native_autorecord(minqlx.Plugin):
    def __init__(self):
        self.set_cvar_once("qlx_qlmatchNameTemplate", "")
        self.set_cvar_once("qlx_qlmatchRcloneTargets", "")
        self.set_cvar_once("qlx_qlmatchPackerPath", QLMATCH_PACKER_SCRIPT)

        self.add_hook("demo_match_finalized", self.on_demo_match_finalized, priority=minqlx.Priority.LOWEST)

    def _demo_dir(self):
        # Mirrors demo_match.c's own final_path construction exactly
        # (demo_seg_build_final(): "%s/%s/...", fs_homepath, sv_demoDir or
        # "demos") rather than hardcoding a guess - both cvars are plain
        # engine cvars. sv_demoDir defaults to "demos" in upstream demos.c's
        # own Cvar_Get() registration, matched here for the case a build
        # somehow doesn't expose it (should not normally happen since C
        # registers it unconditionally at startup).
        #
        # These get_cvar() reads run on the finalize thread, not the game
        # thread. That is within the demo_match_finalized contract: a cvar is a
        # stable process-wide string, unlike live game state (players(), Player,
        # Entity/GameClient, client_t), which this handler must not touch.
        homepath = (self.get_cvar("fs_homepath") or "").strip()
        subdir = (self.get_cvar("sv_demoDir") or "").strip() or "demos"
        if not homepath:
            self.logger.warning("demo_native_autorecord: fs_homepath cvar empty, cannot locate demo dir")
            return None
        return os.path.join(homepath, subdir)

    def on_demo_match_finalized(self, match_id):
        demo_dir = self._demo_dir()
        if not demo_dir:
            self.logger.warning(
                "demo_native_autorecord: match_id=%s finalized but demo dir "
                "unavailable; not building a .qlmatch for it", match_id)
            return minqlx.Return.NONE
        self._build_package(demo_dir, match_id)
        return minqlx.Return.NONE

    # The DemoMatchFinalizedDispatcher call site runs on the engine's finalize
    # thread (not the game thread), so this handler runs off the game thread
    # already. It still must not block whatever's calling it (the finalize
    # thread has its own work to get back to), so the actual work - spawning +
    # waiting on the external packer process - is offloaded again, one more
    # hop, via @minqlx.thread.
    @minqlx.thread
    def _build_package(self, demo_dir, match_id):
        if not self._run_external_packer(demo_dir, match_id):
            self.logger.warning(
                "demo_native_autorecord: qlmatch-packer unavailable for match %s; "
                "no .qlmatch written, cut .dm_91 files remain in %s",
                match_id, demo_dir,
            )

    def _run_external_packer(self, demo_dir, match_id):
        """Runs the external qlmatch-packer as a separate process. Returns
        True when the packer was actually launched (whatever its outcome -
        the packer owns pack/deliver error handling and its exit code is
        logged here); False when it isn't runnable on this host at all (no
        packer deployed, or no node) - the caller logs that as a lost
        .qlmatch, there is no other way to build one. Only ever called from
        the @minqlx.thread worker above, never on the game thread."""
        packer = (self.get_cvar("qlx_qlmatchPackerPath") or "").strip()
        if not packer or not os.path.isfile(packer):
            self.logger.warning(
                "demo_native_autorecord: qlmatch-packer not found at %r", packer)
            return False
        node = shutil.which("node")
        if not node:
            self.logger.warning("demo_native_autorecord: node not in PATH")
            return False

        # No map name passed: the packer reads mapname out of each POV's own
        # gamestate serverinfo, which is authoritative where a plugin-side
        # guess would not be.
        cmd = packer_command(
            node, packer, demo_dir, match_id,
            name_template=(self.get_cvar("qlx_qlmatchNameTemplate") or "").strip(),
            rclone_targets=(self.get_cvar("qlx_qlmatchRcloneTargets") or "").strip(),
        )
        log_path = os.path.join(demo_dir, "%s.packer.log" % match_id)
        try:
            # subprocess.run waits AND reaps (kills on timeout, then reaps);
            # stdout/stderr go to a per-match log file next to the demos so
            # a bad pack/delivery is inspectable after the fact.
            with open(log_path, "ab") as log_fh:
                result = subprocess.run(cmd, stdout=log_fh, stderr=subprocess.STDOUT,
                                        timeout=PACKER_TIMEOUT_SEC)
        except subprocess.TimeoutExpired:
            self.logger.warning(
                "demo_native_autorecord: qlmatch-packer timed out after %ds for match %s (log: %s)",
                PACKER_TIMEOUT_SEC, match_id, log_path)
            return True
        except OSError as exc:
            self.logger.warning(
                "demo_native_autorecord: could not launch qlmatch-packer (%s)", exc)
            return False

        # Packer exit codes (see qlmatch-packer/pack.mjs header): 0 ok,
        # 2 window validation failed (no zip, BY CONTRACT), 3 no POV files,
        # 4 pack ok but >=1 rclone delivery failed, 5 usage/IO error - only
        # that last one means the packer never really ran.
        if result.returncode == 0:
            self.logger.info(
                "demo_native_autorecord: qlmatch-packer finished for match %s (log: %s)",
                match_id, log_path)
        elif result.returncode == 5:
            self.logger.warning(
                "demo_native_autorecord: qlmatch-packer exited 5 (usage/IO) for match %s "
                "(log: %s)", match_id, log_path)
            return False
        else:
            self.logger.warning(
                "demo_native_autorecord: qlmatch-packer exited %d for match %s (log: %s)",
                result.returncode, match_id, log_path)
        return True
