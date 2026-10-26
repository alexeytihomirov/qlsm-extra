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
- [ ] Merge into `main`, push, `git ls-remote`
- [ ] Deploy through qlsm (plugin update on germany)
- [ ] Live check with the operator on germany 27960

## Журнал

- 2026-10-26 - created; related root-0036
- 2026-10-26 - tests: view_angles + velocities + pause_clock + item_pickups + restore_codec_respawn, all green (only these files, not the whole suite)

## Результат

## Как проверить

Germany 27960 (`sD test server`), operator in the game:

1. Join, start a match (or warm-up with another player/bot), run to a spot and look at a recognisable landmark.
2. `/rcon qlx !restore export` (or `qlx restore export` over RCON): the log line must contain `"pa"` and `"ya"` for your row.
3. Turn away about 180 degrees and move.
4. Apply the checkpoint with `!restore apply` (the draft from step 2).
5. Expected: you are back at the position and look at the same landmark as in step 2 (also after the unpause, even if you moved the mouse during the pause).
