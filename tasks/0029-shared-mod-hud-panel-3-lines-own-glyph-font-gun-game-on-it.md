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

## Результат

## Как проверить
