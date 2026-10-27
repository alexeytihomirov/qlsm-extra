# Gun Game HUD panel - design

> **Superseded 2026-10-27** by `docs/superpowers/specs/2026-10-27-mod-hud-panel-design.md` (task `qlsm-extra-0029`): the Gun Game-only panel (`mod_gg_*`, `hud/gungame.menu`, `hud/build_intro_menu.py`) is removed; Gun Game draws on the shared mod HUD panel. Kept as history.

Date: 2026-10-26. Task `qlsm-extra-0027`. Extends `docs/superpowers/specs/2026-10-26-gungame-design.md`: a Gun Game panel on the player's screen, driven by the server, so the state no longer depends on centre prints.

Decisions taken with the operator:

| Question | Decision |
|----------|----------|
| Panel | Small (84x40): the next weapon's icon and the frags towards it (`1/2`); on the last step the frags only. Revised 2026-10-27 after the first live look: the current weapon, `Step N/M` and the leader line were dropped |
| Position | Chosen by each player in their own console: `seta mod_gg_pos` to `top` (unset = top), `bottom`, `left`, `right`, `center`, `topleft`, `topright`, `bottomleft`, `bottomright`, `off`. The server never writes it. Free x/y is impossible: a menu rect is fixed and menus cannot read numbers from cvars |
| Centre prints | Only rare events (leader, last step, win, demotion). A plain step up stops going to the centre while the HUD is on; chat stays |
| Delivery | Overridden `ui/intro.menu` (stock content + our block), copied by hand into `<QL>/<steamid>/baseq3/ui/` for now. Workshop later, separate task |

## Verified facts this design rests on

From `skills/ql-live/reference/server-driven-hud-and-view.md` (verified live 2026-10-26, root-0036):

- `send_server_command(cid, 'cs <CS_SYSTEMINFO> "<fresh systeminfo>\\key\\value..."')` sets client cvars on that client only; the HUD repaints at once. Systeminfo is read fresh each time (`configstring(CS_SYSTEMINFO, cached=False)`); `\`, `"` and `;` are stripped from values.
- A HUD text item shows a cvar (`ITEM_TYPE_TEXT` + `cvar`); `cvarTest` + `showCvar` shows an item on equality.
- `ui/intro.menu` is always loaded before `cg_hudFiles`, so a block there shows with any player HUD.
- Stock images draw (`ui/assets/...`); weapon icons are in pak00 as `icons/iconw_<name>`.

Seen live 2026-10-27 (operator's client, #26):

- `cvarTest` + `showCvar` with `cvarTest2` + `showCvar2` on one item is an AND in a HUD (left and bottom copies drew the right icon only).
- `hideCvar` on an item that also has `showCvar2` does not work (the top copy drew stacked icons, no back or text). Stock menus only pair hide with hide2 and show with show2.

Fork API (minqlxtended `demo-match-capture`): `send_server_command(client_id, cmd)`, `configstring(index, cached=True)`, `CS_SYSTEMINFO`; events `player_disconnect(player, reason)`, `team_switch(player, old_team, new_team)`.

## Files

| File | What |
|------|------|
| `hud/gungame.menu` | Template of our `menuDef`: one panel with a `@POS@` test value and `@X@`/`@Y@` placeholders |
| `hud/build_intro_menu.py` | `python hud/build_intro_menu.py <pak00 dir or .pk3> <out dir>`: reads stock `ui/intro.menu`, appends the panel once per position (9), writes `<out>/ui/intro.menu`. The repo never holds id's file |
| `gungame.py` | Panel fields, send/diff/clear logic, `qlx_gunGameHud` |
| `tests/test_gungame.py`, `tests/test_gungame_hooks.py` | Pure functions and hook wiring |

## Client cvars

All `mod_gg_*`. The server writes every one except `mod_gg_pos`.

| Cvar | Value |
|------|-------|
| `mod_gg_on` | `1` while Gun Game runs and the player is in the game; empty clears the panel |
| `mod_gg_next` | Ladder key of the next step (`rl`, `g`, ...); empty on the last step |
| `mod_gg_prog` | Frags on the current step / needed, `1/2` |
| `mod_gg_pos` | Player's own, see Position above |

## Menu

Per position copy, every item carries two tests:

- position: the top copy `cvarTest mod_gg_pos` + `showCvar { "" ; "top" }` (unset = empty string); every other copy `showCvar { "<its value>" }`. Show tests only (see the live facts above);
- content: background and text items `cvarTest2 mod_gg_on` + `showCvar2 { "1" }`; each weapon icon `cvarTest2 mod_gg_next` + `showCvar2 { "<key>" }`, one item per ladder key (14).

Text items use `textstyle` shadowed so they read over any map. Rects are in the 640x480 virtual screen; exact sizes are tuned in the live test.

## Plugin behaviour

- Pure `hud_fields(ladder, state) -> dict` builds the three server-written fields. `hud_diff(sent, fields) -> dict` returns only changed ones. `hud_command(systeminfo, fields) -> str` builds the `cs` command with values cleaned.
- Sending: handlers mark players dirty; one `next_frame` flush per frame sends one command per dirty player with only the changed fields, and records what was sent per client. Bots (steam_id 0) are skipped. No timers: without events nothing is sent.
- Marked dirty: the player on spawn, on a kill or death that changed their state, on match start (`new_game` after a reset), on `player_loaded`. A send refused because the client is still loading leaves an "unknown" cache entry, so the next send repeats every field.
- Cleared (`mod_gg_on` empty, other fields empty): on `team_switch` to spectator, on `game_end`, on unload, on `new_game` when Gun Game is not active (players who still have a panel), on `player_disconnect` (best effort). The sent-cache entry is dropped with it.
- `qlx_gunGameHud` (default `1`): `0` turns the panel off entirely (clears it) and restores step-up centre prints. While `1`, a step up goes to chat only (if `qlx_gunGameStepNotify` has `print`); demotion, leader, last step and win keep their channels.

Known limit: a player who leaves for another server keeps the panel until their game restarts; the server cannot clear a client cvar after the disconnect.

## Tests

- Pure: fields for first, middle and last step; diff; cleaning of `\ " ;`; command format with the fresh systeminfo.
- Hooks: a kill marks killer and victim, one flush sends one command per player with only changed fields, bots skipped, a bystander gets nothing from others' steps, spectator / game_end / disabled clear, `qlx_gunGameHud 0` sends nothing and keeps centre step prints.
- Build script: output contains the stock text unchanged plus three panel copies with distinct position tests.
- Live on NN #5 with the operator: `cvarTest2` AND in a HUD, `hideCvar`, the three positions, repaint on frags.

## Out of scope

Workshop delivery, own images (need a pk3), frag dots (a third test per item), configurable panel layout beyond the three positions.
