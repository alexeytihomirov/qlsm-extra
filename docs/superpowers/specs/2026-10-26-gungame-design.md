# Gun Game plugin - design

Date: 2026-10-26. Task `qlsm-extra-0027`. A minqlxtended plugin for fun instances: every frag moves the killer along a configurable weapon ladder; a frag on the last step wins the match. NIX (Xonotic's "everyone has the same weapon, it changes every N seconds") is part of the same task but gets its own short spec after this one; it reuses the weapon-giving and item-hiding parts.

Decisions taken with the operator:

| Question | Decision |
|----------|----------|
| Game type | FFA only |
| Ladder | Configurable cvar, frags needed configurable per step, any QL weapon (incl. hmg, bfg) |
| Default ladder | Strong to weak: `rl:2 rg:2 lg:2 pg:2 sg:2 gl:2 mg:2 g:1` |
| Map items | Weapons and powerups gone, armor and health stay |
| How they go | The plugin hides them at map load; `item_touch` STOP as a safety net |
| Death by gauntlet | Victim goes down one step |
| Suicide and world deaths (own splash, lava, fall, `/kill`) | Down one step; cvar switch, on by default |
| Gauntlet | Always in hand on every step; a gauntlet frag counts for the killer like any frag |
| Player joining mid-match | Starts at step 1 |
| Notifications | Step changes to the player only, leader news to everyone; channel per event configurable (`print` = server echo line, `center`), to try variants |

## Verified facts this design rests on

All in the fork checkout `_build/minqlxtended-fork` (branch `demo-match-capture`, `python/minqlxtended/`) unless said otherwise.

- Events `kill(victim, killer, mod)`, `death(victim, killer, mod)` (killer None for world deaths, the victim itself on suicide), `player_spawn`, `item_touch(player, entity)` (gated; `STOP_EVENT` keeps the touch from the game, the item stays), `item_pickup`, `new_game`, `map`, `game_start`, `game_end` (`_events.py`).
- `MeansOfDeath.GAUNTLET` exists and is what `pummel.py` (qlsm pool) checks.
- Player setters `weapons`, `weapon`, `ammo`, `score`, `center_print`, `tell` (`_player.py`). `Plugin.msg` and `tell` send the server command `print "..."` (`_commands.py:451`, `ChatChannel.DEFAULT_FMT`), i.e. the echo-style line; `center_print` sends `cp`.
- Hiding a map item on the stock fork: writable entity fields (`EF_NODRAW`, `SVF_NOCLIENT`, `contents 0`) plus `link_entity`, as `qlsm-extra/match_restore.py` `_stock_hide_item` does in production.
- Weapon keys and their field order: `qlsm-extra/item_roulette.py` `WEAPON_FIELDS` (`g mg sg gl rl lg rg pg bfg gh ng pl cg hmg hands`), same as `minqlxtended.Weapons`.
- Native QL cvars `g_infiniteAmmo`, `fraglimit`, `g_dropPowerups` exist (`skills/ql-live/reference/data/cvar-details-full.txt` in the monorepo). There is **no** cvar that stops a dying player dropping a weapon.
- Test server: qlsm instance 26 `Frontier Fun NN #5`, 185.11.244.225:27964, FFA, hidden from the browser, password (task journal).

## Files

| File | What |
|------|------|
| `gungame.py` | The plugin. Pure functions on top (no engine access), plugin class below |
| `gungame.ql-plugin.json` | Manifest: label, description, cvars for the qlsm UI |
| `tests/test_gungame.py` | Unit tests of the pure functions with the existing `tests/_minqlx_stub.py` |

Same layout as `item_roulette.py` / `item_roulette.ql-plugin.json`.

## Cvars

| Cvar | Default | Meaning |
|------|---------|---------|
| `qlx_gunGameEnabled` | `0` | Master switch |
| `qlx_gunGameLadder` | `rl:2 rg:2 lg:2 pg:2 sg:2 gl:2 mg:2 g:1` | Space-separated `weapon:frags`; weapon keys as in `item_roulette`; frags an integer >= 1 |
| `qlx_gunGameGauntletDemote` | `1` | A gauntlet death takes the victim one step down |
| `qlx_gunGameSuicideDemote` | `1` | Suicide and world deaths take the player one step down |
| `qlx_gunGameStepNotify` | `print` | Where the player hears about their own step: `print`, `center`, `print,center`, `off` |
| `qlx_gunGameLeaderNotify` | `print` | Where everyone hears about the leader: same values |

Seeded with `set_cvar_once`, so instance config wins. Ammo is not the plugin's business: the instance config sets `g_infiniteAmmo 1`.

## Pure functions

- `parse_ladder(text) -> list[(weapon_key, frags)]`, raises `ValueError` with a readable reason on: empty ladder, unknown weapon key, frags missing / not an integer / < 1, `hands`.
- `parse_channels(text) -> set[str]` from `print`, `center`, `off`; unknown words are ignored, `off` or nothing -> empty set.
- `advance(state, ladder, event) -> (state, outcome)` where state is `(step, frags_on_step)` (step is 0-based) and event is one of `frag`, `demote`. Outcomes: `none`, `up`, `down`, `win`. Rules:
  - `frag`: `frags_on_step + 1`; when it reaches the step's frags, the step goes up and frags reset to 0 (`up`); on the last step that is `win` instead.
  - `demote`: step - 1 (floor 0), frags reset to 0 (`down`; at step 0 the frags still reset and the outcome is `none` if they were already 0).
- `loadout(ladder, step) -> weapon_key` (the gauntlet is added by the plugin on top).

## Plugin behaviour

Active only when `qlx_gunGameEnabled` is 1 and `g_gametype` is 0 (FFA); otherwise every handler returns at once.

**State.** `dict steam_id -> (step, frags_on_step)` for the current match. Cleared on `new_game` and at match start. Rejoining, going to spectators and back: the step is kept. A player first seen mid-match starts at step 0.

**Ladder.** Read and parsed at match start (and at plugin load). An invalid ladder logs a warning and the last valid one stays (the default if none was valid yet). A change mid-match applies from the next match.

**Map load.** Every map item whose classname starts with `weapon_` or is a powerup (`item_quad`, `item_enviro`, `item_haste`, `item_invis`, `item_regen`, `item_flight`, ...) is hidden with the `_stock_hide_item` technique. Armor, health and ammo boxes stay (ammo is pointless with infinite ammo but harmless).

**`item_touch`.** Weapons and powerups return `STOP_EVENT`: covers anything the hide missed and weapons dropped by dying players (no cvar stops those drops; they stay visible until they expire, which the live check will judge).

**`player_spawn`.** Gives gauntlet + the weapon of the player's step and selects that weapon. In warmup everyone gets the step-0 weapon and frags do not count.

**`kill` (match in progress).**
1. Killer gets `advance(..., frag)`. On `up`: new loadout on the next frame (`next_frame`, not inside the kill handler), step notify. On `win`: leader notify "X wins", match ends (below).
2. If `mod` is `GAUNTLET` and `qlx_gunGameGauntletDemote`: victim gets `advance(..., demote)`, step notify.
3. Leader check: when the top step changes hands or someone reaches the last step, leader notify.

**`death` without a killer, or killer == victim.** If `qlx_gunGameSuicideDemote`: `advance(..., demote)`, step notify. `mod` `SWITCH_TEAMS` (the engine kills a player who changes team) never demotes.

**Score writes.** The engine changes the score itself on a kill (+1) and a suicide (-1) around the event, so every score write happens on the next frame.

**Score.** After every change the player's `score` is set to their step number (1-based), so the standard scoreboard shows progress.

**Match end.** At match start the plugin saves `fraglimit` and sets it to 0, so the instance's own limit cannot end a match while scores are step numbers. On `win` it sets the winner's score to ladder length + 1 (one above anyone else on the last step, so there is no tie) and `fraglimit` to the same number, so the engine ends the match through its own exit rules. To be confirmed on the test server; fallback: `timelimit` to the elapsed minute. The saved `fraglimit` is restored on `new_game` and plugin unload.

**Notifications.** Texts (colour codes as QL): step to the player "Step 3/8: ^3LG^7 (0/2)", demote "Down to step 2/8: ^3RG^7", leader "^3X^7 leads: step 5/8", last step "^3X^7: last step!" (short: a centre print does not wrap), win "^3X^7 wins Gun Game!". Channels from the two notify cvars.

**Game-thread rules** (`skills/minqlx-plugin-review/SKILL.md`): no I/O, no redis, no threads; handlers are dict lookups and a few setters. `item_touch` is gated and hot: one classname check, return.

## Tests

Unit (only `tests/test_gungame.py` is run): `parse_ladder` valid / each invalid case; `parse_channels`; `advance` up, win on the last step, demote with floor and frags reset, frags reset on up; `loadout`.

Live, on instance 26 with the operator (and bots for numbers): weapons and powerups gone from the map, armor and health there; spawn loadout; steps go up and down; gauntlet demote; suicide demote; scoreboard shows the step; dropped weapons cannot be picked up; win ends the match; notify channels `print` / `center` / `off` switched live.

## Out of scope

- NIX (own spec next).
- Team variants (FFA only, by decision).
- Persistent stats across matches, `!gg` command, sounds. Can come after the first live round.
