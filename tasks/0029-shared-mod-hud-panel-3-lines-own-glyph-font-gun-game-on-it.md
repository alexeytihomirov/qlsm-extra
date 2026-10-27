---
id: qlsm-extra-0029
title: Shared mod HUD panel (3 lines, own glyph font), Gun Game on it
status: in-progress
created: 2026-10-27
updated: 2026-10-27
verified:
depends_on: []
related: [root-0036, qlsm-extra-0027, docs/superpowers/specs/2026-10-27-mod-hud-panel-design.md]
---

# Shared mod HUD panel (3 lines, own glyph font), Gun Game on it

## Цель

Одна плашка на 3 строки в 9 местах экрана, которой пользуется любой наш плагин: текст и иконки-символы присылает сервер, место выбирает игрок. Gun Game показывает свой HUD через неё. Клиентская часть - один pk3 (меню + запасной шрифт с нашими символами).

## Контекст

Возможности и ограничения проверены в `root-0036` (`skills/ql-live/reference/server-driven-hud-and-view.md`): cvar'ы с сервера через `cs`, UTF-8 символы, свой запасной шрифт из pk3 в папке установки, автоочистка через `onOpen` у `joingame_menu`. Дизайн согласован с оператором 2026-10-27: `docs/superpowers/specs/2026-10-27-mod-hud-panel-design.md` (в этом репозитории).

## Шаги

- [x] Дизайн согласован в чате
- [x] Spec написан и одобрен оператором
- [x] План реализации
- [x] Реализация (helper, plugin, builder, Gun Game)
- [x] Независимое ревью ветки
- [x] Merge в main, push, деплой на #26, pk3 у оператора
- [ ] Живая проверка оператором
- [ ] Живая проверка на #26
- [ ] Workshop-тест (отдельно, позже)

## Журнал

- 2026-10-27 - created. Branch `feat/modhud` from `origin/main` (b54f55b; local `main` was 42 behind, Gun Game HUD already on origin/main), worktree `D:/QuakeLiveData/QL Server/.worktrees/qlsm-extra-modhud`.
- 2026-10-27 - Operator approved the spec; shared `main` checkout fast-forwarded to origin/main (b54f55b) on request. Plan `docs/superpowers/plans/2026-10-27-mod-hud-panel.md`, executed inline: modhud_util (bbf9b7d), menu builder (2863f46), glyph font + pk3 + `hud/glyphs.png` (65595ae; `{flag}` drawn: pak00 flag images trace badly), modhud plugin (7b20340), Gun Game on the panel + manifest (c5c88a0). 125 tests of the touched modules pass; `tests/test_descriptions.py` has 6 pre-existing failures on untouched sidecars. pk3 built from the real pak00 (25 icons). Whole-branch review dispatched.
- 2026-10-27 - Review (opus): C1 panel hidden after every map load (Join Match onOpen vs a cache that says "shown"), I1 stale lines of another server shown, I2 modhud + gungame caches diverge, I3 commands over 1022 bytes dropped silently (minqlxtended `reliable.c`), I4 unset `mod_hud_pos` may never match `showCvar { "" }`. Fixed C1-I3 in 8218e35 (shared `modhud_util.CLIENT`, full first show, `reset_clients()` on map, `fitted_command`), 136 tests pass. I4 and "does Join Match open on map_restart" go first in the live check. Minors M1-M6 deferred (control chars in clean, no unload hook in modhud, repeated spaces in !hud, empty-after-clean line, case of onOpen check, missing icon only warned).
- 2026-10-27 - Operator: old Gun Game panel must go entirely. Old HUD spec/plan marked superseded, last `mod_gg_pos` hint dropped. Rebased onto origin/main e3005f2 (qlsm-extra-0030 removed lobby and tournament_access), manifest regenerated, 136 tests pass, pushed: origin/main = 663157d (ls-remote). Shared checkout fast-forwarded.
- 2026-10-27 - Deployed to #26 only (script in qlsm-web-1: repo sync, download_plugin x3 overwrite, `modhud` appended to instance 26 qlx_plugins, apply_plugin_updates_task(host 3, pool, {26: files}, restart 26), job 37220f6e). qlds@27964 restarted 17:14:58 MSK; sha256 on host = manifest (gungame fe90fefd, modhud 125d178d, modhud_util 329572f7); cmdline has `gungame, modhud`; log `Loading plugin 'modhud'` with no traceback; rcon qlx_modHudPerm 3, qlx_gunGameHud 1, qlx_gunGameEnabled 1. Operator client: `Quake Live/baseq3/zz_modhud.pk3` installed, old loose `<steamid>/baseq3/ui/intro.menu` moved to the session scratchpad (`client_backup/intro.menu.gungame`).
- 2026-10-27 - Operator: connect to #26 refused with "Unpure client detected". Cause: the client reads `ui/intro.menu` and the font from `zz_modhud.pk3`, a pk3 the `sv_pure 1` server does not have (the operator's other local pk3s are never read on that server, so they pass; the server's baseq3 holds only pak00 and bin, everything else comes from workshop.txt). Debug exception (manual, #26 only): the same pk3 (sha256 be9cfc23..., equal on client and server) installed as `/home/ql/qlds-27964/baseq3/zz_modhud.pk3`, restart queued through qlsm (job 946aabaf). Consequence for delivery: the pk3 must be on the server too, i.e. a Workshop item listed in workshop.txt; a hand-copied client pk3 alone locks the player out of pure servers.
- 2026-10-27 - Live check 1: no panel. Client cvars were right (`mod_hud_on 1`, `mod_hud_l1` = RG glyph + 0/2, onOpen had created mod_hud_on with default 0, so the pk3 menu loaded). Debug rounds with a loose `ui/intro.menu` (D1-D5, E1-E6, `make_debug_menu.py` in the session scratchpad): Gun Game's plain text item draws, our size draws, `showCvar` lists draw; `textalign ITEM_ALIGN_CENTER`/`RIGHT` => item not drawn, `align` ignored; everything with the `mod_hud_on` test hidden because `mod_hud_on` was 0 even after a full disconnect + connect: Join Match opens after player_loaded and hides the panel sent on load. Fix: text left-aligned in every place; `modhud_util.loaded`/`joined` resend the panel on the first spawn or team switch after a load (gungame, modhud). 139 tests. Facts in `skills/ql-live/reference/server-driven-hud-and-view.md` (monorepo root, local).
- 2026-10-27 - Deployed c3a2d51 to #26 (restart 17:56:47 MSK, hashes = manifest, server and client pk3 25c6f5d7). Live check 2 (operator): Gun Game line shows after connect; all 8 explicit places correct, three `!hud` lines with coloured icons; `!hudicons` glyphs draw in chat and console. Empty `mod_hud_pos` showed nothing (review I4 confirmed). Debug F1-F3: hide-only tests catch the empty value, hide + show2 never draws. Fix: top place uses `hideCvar { other places ; "off" }` + `hideCvar2 { "0" }`; pk3 8a66cfda. Map change and match start not reported yet.
- 2026-10-27 - Live check 3 (operator, ec3d626, pk3 8a66cfda, restart 18:22:09 MSK): unset `mod_hud_pos` shows top; `off` hides; panel back after a map change and after the match start; none in duel (Gun Game is FFA only, expected). Operator: topright text starts just right of the middle. Cause: left-aligned text in a 300-wide block ending at the edge. Fix: right places start the text RIGHT_ROOM 120 before the edge, middle places CENTER_LEAD 50 left of the centre; pk3 146fe6c4.

## Результат

## Как проверить
