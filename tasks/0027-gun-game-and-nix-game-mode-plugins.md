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
- [ ] Gun Game плагин + manifest + тесты
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

## Результат

## Как проверить
