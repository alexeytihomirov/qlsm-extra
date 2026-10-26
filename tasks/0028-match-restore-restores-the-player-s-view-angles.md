---
id: qlsm-extra-0028
title: match_restore restores the player's view angles
status: in-progress
created: 2026-10-26
updated: 2026-10-26
verified:
depends_on: []
related: [root-0036, skills/ql-live/reference/server-driven-hud-and-view.md]
---

# match_restore restores the player's view angles

## Цель

`!restore` puts every player's view direction (pitch, yaw) back together with the position and velocity. Old checkpoints without angles restore as before.

## Контекст

`match_restore.py` never saved the view ("View angles not required for cfg restore"). `root-0036` verified live on germany 27960 (2026-10-26) that a server plugin can turn a client's view: `gc = minqlxtended.GameClient(id)`, `gc.ps.delta_angles = [short(pitch) - cmd[0], short(yaw) - cmd[1], 0 - cmd[2]]`, `short(a) = int(a * 65536 / 360) & 65535`; the current view is `gc.ps.viewangles`. Details: `skills/ql-live/reference/server-driven-hud-and-view.md`, "Turning a player's view".

Design (mirrors the velocity path, which already survives the pause):

- Export: `pa` (pitch) and `ya` (yaw), two decimals, next to `vx/vy/vz` in the player row. No row key when there is no `GameClient` (stock minqlx) or the engine is not ready.
- `restore/codec.py` `canonicalize` keeps `pa`/`ya` (it rebuilds rows from a whitelist, so they would be dropped otherwise).
- Apply: in the kinematics phase (after the pause, same place as the velocity) the angle is written, remembered in `_restore_pending_views` and queued for `RESTORE_VEL_FRAMES` frames in the existing frame hook (`_view_apply_queue`). On unpause `_flush_restore_views` writes it again. The unpause write matters: the formula uses `pers.cmd_angles`, which keeps changing with the mouse, so the delta computed during the pause is stale once the client's commands run again.
- Without `minqlx.GameClient` every view call is a no-op.

## Шаги

- [x] Worktree `qlsm-extra-view-angles` from `origin/main` (local `main` of the shared checkout was 19 commits behind, so the branch was reset to `origin/main`; merge-base checked)
- [x] Export `pa`/`ya`, codec keeps them
- [x] Apply in the kinematics phase, queue, unpause flush, clear on abort / map change / new session
- [x] Tests `tests/test_match_restore_view_angles.py`; the three existing match_restore tests got the new bare-instance fields
- [x] `generate_manifest.py`, `check_manifest_hashes.py`
- [x] Merge into `main`, push, `git ls-remote` (3d0643d)
- [x] Deploy through qlsm (plugin update on germany)
- [x] Draft field `!restore player <slot> view <pitch> <yaw>` (the cfg draft had no way to carry angles; `export` only writes JSON to the log)
- [ ] Live check with the operator on germany 27960

## Журнал

- 2026-10-26 - created; related root-0036
- 2026-10-26 - tests: view_angles + velocities + pause_clock + item_pickups + restore_codec_respawn, all green (only these files, not the whole suite)
- 2026-10-26 - merged into origin/main (3d0643d). Deploy to germany waits for the operator: the plugin update goes through the qlsm Repositories page, no verified API path is documented
- 2026-10-26 - deployed to germany 27960 from inside `qlsm-web-1` (same code as the Repositories download route, common-pool refresh queued for host 1 only, not the 8-host push). The instance keeps its own copy in `configs/GermanyHetzner/1/scripts/`, and the instance-selected path copies basenames only, so `restore/codec.py` was staged by hand next to `match_restore.py`; then `restart_instance`. Verified on the host: `/home/ql/qlds-27960/minqlxtended-plugins/` has `_write_player_view` and `"pa"`, plugin loaded at 21:14:56 CET with no error (the `match_restore_util` PluginLoadError is old noise). Server was empty (warmup, 0 players) during the restart

- 2026-10-26 - live check round 1: `export` on germany wrote `"pa":1.76,"ya":22.71` into the JSON (export works); `!restore apply` said "no players in draft" because my check steps were wrong: `export` does not fill the draft. Added the `view` draft field, redeploying

## Результат

- Commit `3d0643d` on `origin/main` of `alexeytihomirov/qlsm-extra` (confirmed with `git ls-remote`). Deployed on germany 27960 (`sD test server`) 2026-10-26 21:14 CET; other hosts get it through Check for Updates. Live check by the operator is pending.

## Как проверить

Germany 27960 (`sD test server`), operator in the game:

1. Join, start a match (or warm-up with another player/bot), run to a spot and look at a recognisable landmark.
2. `/rcon qlx !restore export` (or `qlx restore export` over RCON): the log line must contain `"pa"` and `"ya"` for your row.
3. Turn away about 180 degrees and move.
4. Apply the checkpoint with `!restore apply` (the draft from step 2).
5. Expected: you are back at the position and look at the same landmark as in step 2 (also after the unpause, even if you moved the mouse during the pause).
