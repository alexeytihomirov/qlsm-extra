---
id: qlsm-extra-0027
title: Gun Game and NIX game mode plugins
status: in-progress
created: 2026-10-26
updated: 2026-10-26
verified:
depends_on: []
related: [root-0033, root-0034, qlsm-extra/docs/superpowers/specs/2026-10-26-gungame-design.md]
---

# Gun Game and NIX game mode plugins

## Цель

Два minqlxtended-плагина в qlsm-extra для fun-инстансов:
- **Gun Game** (CS GunGame): за фраг игрок переходит на следующее оружие лестницы, победа - фраг с последней ступени (обычно гаунтлет).
- **NIX** (Xonotic): у всех одно и то же оружие, оно меняется для всех каждые N секунд, подбор оружия отключён.

## Контекст

Обсуждение режимов 2026-10-26 (чат), оператор: "Gun Game, NIX - будем пробовать". Готовых minqlx-плагинов с этими режимами не нашлось. Опора в форке (`_build/minqlxtended-fork/python/minqlxtended/_player.py`, `_events.py`): события `kill`, `death`, `player_spawn`, `item_touch` (отменяемое, гейтед); сеттеры `weapons`, `weapon`, `ammo`; `center_print`, `play_sound`. Нативные cvar'ы QL для базы factory: `g_startingWeapons`, `g_startingAmmo_*`, `g_infiniteAmmo`, `g_spawnItem*` (`skills/ql-live/reference/data/cvar-details-full.txt`). Соседний образец кода: `qlsm-extra/item_roulette.py` (тот же форк, `item_touch` + сеттеры).

Открытые вопросы дизайна: лестница оружия и её настройка cvar'ом; что делать с предметами на карте; FFA или и командный вариант; понижение ступени за смерть от гаунтлета / суицид; NIX - интервал, патроны, предупреждение перед сменой.

## Шаги

- [x] Дизайн с оператором (brainstorming) -> спека
- [x] Gun Game плагин + manifest + тесты
- [ ] NIX плагин + manifest + тесты
- [ ] Factory / пресет fun-инстанса
- [ ] Проверка на живом fun-инстансе

## Журнал

- 2026-10-26 - created from the game-modes discussion
- 2026-10-26 - operator decisions (Gun Game): ladder configurable; frags needed per weapon configurable per step; death by gauntlet demotes one step; FFA only. Test server: a hidden 5th instance on NijniyNovgorod (host id 3)
- 2026-10-26 - test server created via qlsm API (draft from instance 25 + POST /api/instances/, JWT minted in qlsm-web-1, script in session scratchpad `nn5_create.py`): qlsm instance id 26 `Frontier Fun NN #5`, 185.11.244.225:27964, FFA (`serverstartup map campgrounds ffa`, ffa-only mappool), sv_maxClients 16, `sv_master 0`, `g_password` set (operator's choice), plugins of #4 minus tournament_access / tournament_match_notice / referee_call. qlsm auto-enabled stats-hub telemetry + live stream, server ID 33 (operator OK with that)
- 2026-10-26 - verified: qlds@27964 active since 15:51:03 MSK, rcon (zmq 28892) sv_master 0, g_password set, mapname campgrounds, g_gametype 0, sv_maxclients 16, qlx_matchNoticeEnabled 0; telemetry plugin active match_id server-33; instances 27960-27963 untouched (same PIDs and start times as before). Not observed: absence from the in-game server browser
- 2026-10-26 - operator checked the test server in game: "всё работает"
- 2026-10-26 - decision: map weapons and powerups are not available (pickup blocked / not spawned), armor and health items stay
- 2026-10-26 - decision: suicide and world deaths (own splash, lava, fall, /kill) demote one step; cvar-switchable, on by default
- 2026-10-26 - decision: default ladder strong -> weak `rl:2 rg:2 lg:2 pg:2 sg:2 gl:2 mg:2 g:1`; the ladder cvar accepts any QL weapon key incl. hmg and bfg (same keys as item_roulette: g mg sg gl rl lg rg pg bfg gh ng pl cg hmg)
- 2026-10-26 - decision: notifications configurable to try variants; step up/down goes to the player only, leader news to everyone; "echo" style = server `print` line (what ChatChannel/TellChannel already send, `_commands.py:451`), centre print as the other channel
- 2026-10-26 - decisions: weapons/powerups hidden by the plugin at map load (match_restore `_stock_hide_item` technique) + `item_touch` STOP as a safety net; gauntlet always in hand, a gauntlet frag counts for the killer like any frag; a mid-match joiner starts at step 1; state per SteamID for the match (rejoin keeps the step); score = step number; win ends the match via fraglimit (to verify live, fallback timelimit)
- 2026-10-26 - spec written: `docs/superpowers/specs/2026-10-26-gungame-design.md` (worktree `.worktrees/qlsm-extra-gungame`, branch feat/gungame from origin/main d8c3ff3); waiting for operator review
- 2026-10-26 - operator approved the spec. Spec refined: fraglimit 0 during the match, winner score = ladder length + 1 (no tie on the last step), SWITCH_TEAMS deaths never demote, score writes on the next frame. Plan: `docs/superpowers/plans/2026-10-26-gungame.md`

- 2026-10-26 - gungame.py + gungame.ql-plugin.json + tests (43 unit/hook tests), repository entry, README row. Fork detail found: `map` fires on a fresh load only, `new_game` also on restarts (items respawn), so items are hidden on new_game and fraglimit is restored on game_end / map / unload
- 2026-10-26 - fresh review (opus) found: game_start handler took an argument the fork never passes (plugin would not load), bots shared one state (steam_id 0), fraglimit lost if enabled mid-match, frags counted after a win, hidden powerups come back on respawn. All fixed with failing-first tests (61 pass); map items now freed with minqlx.remove_entity. Merged to main 4b19628, pushed
- 2026-10-26 - installed on instance 26 via qlsm API (repo sync, download, draft, save with restart): qlds@27964 restarted 17:53:15 MSK; rcon: qlx_gunGameEnabled 1, g_infiniteAmmo 1, default ladder, g_gametype 0; log: `Loading plugin 'gungame'`, `gungame: took 8 weapons and powerups off the map`, no gungame traceback. gungame.py also pushed to every host's pool (off by default, enabled only on #26). Waiting for the operator's live round
- 2026-10-26 - live round 1 (operator): weapons change, a gauntlet frag on the last step ends the match; dropped weapons do not appear. Problems: map weapons and powerups were back after every restart (`took 0` in the log: a restart respawns items a couple of frames after new_game), and the server crashed twice at a match start
- 2026-10-26 - crash diagnosis (journal + /proc maps + nm of minqlxtended.x64.so on NN): `Sys_Error: Segmentation fault` in `makePlayerTuple+0x36` <- `PyMinqlxtended_PlayerInfo` <- python <- `ClientCommandDispatcher` <- `My_SV_ExecuteClientCommand` <- qagame, during ShutdownGame / Game Initialization of a restart, with bots on. A bot client command reaches the Python dispatcher while `g_entities` does not point at the live qagame. Engine fork bug, not gungame; appeared once `bot_enable 1` was set on #26 (bots were needed for the test)
- 2026-10-26 - operator asks: weapon delay in ms, remove map weapons/powerups for real, 100 armor on spawn, gauntlet frag = whole step up (switchable). Done in 08a1f62 (qlx_gunGameWeaponDelay 0, qlx_gunGameSpawnArmor 100, qlx_gunGameGauntletSkip 1, item rescan 0.5 s after new_game), 70 tests; deployed to #26 18:40 MSK (`_scan_items: took 8`), new cvars visible over rcon. Note: a pool download alone does not refresh the instance's own plugin copy; a config save through qlsm does
- 2026-10-26 - live round 2 (operator): "почти всё ок". Asked: the delay must sit between taking the old weapon and giving the new one (the old one fired during the pause); a suicide costs one frag, not a whole step. Done in 828d665 (gauntlet only during the delay; `advance(..., "back")`: one frag back, into the previous step one frag short when the step has none), 72 tests; deployed to #26 18:52 MSK. The crash goes to root-0035 (engine fork, operator chose to fix the fork)
- 2026-10-26 - live round 3 (operator, #26 with bots, several match starts): "всё ок". Gun Game accepted; delay between disarm and new weapon, suicide -1 frag, no crash (engine fix root-0035). Next: NIX spec
- 2026-10-26 - operator: NIX is not needed for now (on hold); Gun Game stays on #26 with bots for further testing and improvements
- 2026-10-26 - operator: centre notifications (Step/LeaderNotify center) not visible. Cvars were right; hypothesis (Q3 cgame logic, QL cgame closed): the obituary's own "You fragged X" centre print in the same snapshot replaces ours. Fix b1f22c6: centre prints go out CENTER_DELAY_S=0.2 s later. Same commit, per operator: leader re-picked on any step-down (new leader announced, or cleared below step 2); item_touch hooked only while active (engine gates the event on a hook), synced on load and every new_game, so enabling mid-map blocks pickups from the next restart. 73 tests. Deployed on #26 22:04 MSK, operator's rcon values written into server.cfg (ladder with hmg, WeaponDelay 500, both notify center), 4 bots re-added. Waiting for operator to confirm centre prints
- 2026-10-27 - operator confirmed centre prints; last-step text shortened (GAUNTLET line did not fit). HUD panel: spec docs/superpowers/specs/2026-10-26-gungame-hud-design.md, plan docs/superpowers/plans/2026-10-27-gungame-hud.md, executed inline. Client cvars mod_gg_*, qlx_gunGameHud (default 1, step-up no longer centre-printed), hud/gungame.menu + hud/build_intro_menu.py (stock intro.menu + top/left/bottom copies, player picks with mod_gg_pos). Final review: 3 Important fixed (send to a loading client returned False but was cached - now resent in full on player_loaded; icons need backcolor 1 1 1 1; leader line follows the leader's own step). 100 tests. main eea2fd2. Deploy to #26 queued 04:10 MSK; live check with operator pending
- 2026-10-27 - deployed on #26 (restart 04:15 MSK, rcon qlx_gunGameHud=1, 4 bots), intro.menu copied into the operator's QL profile. Live: left and bottom copies draw right (icons, step text, next icon) - so cvarTest2+showCvar2 is an AND in a HUD. Top copy (cvarTest + hideCvar, unset mod_gg_pos) drew only two stacked HMG-looking icons, no back or text: hideCvar next to showCvar2 does not work. Fixed: top copy uses showCvar { "" ; "top" }; bottom moved to y 340 (overlapped the ammo box). Recheck of top pending
- 2026-10-27 - operator: show only the next weapon and the progress to it; positions incl. right and custom x/y. Free x/y impossible (menu rect fixed, no numbers from cvars); operator chose a 3x3 grid via mod_gg_pos (top default, bottom, left, right, center, topleft, topright, bottomleft, bottomright, off) and progress only on the last step. Fields now mod_gg_on/mod_gg_next/mod_gg_prog, panel 84x40, leader line dropped. db6ae1a, 98 tests, deployed on #26 (restart 04:39 MSK, pool sha256 2af5a192 = local, 4 bots), menu copied into the operator's profile. Live check pending
- 2026-10-27 - Gun Game-only panel removed (`mod_gg_*`, `mod_gg_pos`, `hud/gungame.menu`, `hud/build_intro_menu.py`); Gun Game draws line 1 of the shared mod HUD panel, task `qlsm-extra-0029`. Players install `zz_modhud.pk3` and drop the old loose `ui/intro.menu`.

## Результат

## Как проверить
