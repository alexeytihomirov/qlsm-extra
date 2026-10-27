# Shared mod HUD panel - design

Date: 2026-10-27. Task `qlsm-extra-0029`. Origin: `root-0036` (what a server can draw on a stock client). Replaces the Gun Game-only panel of `docs/superpowers/specs/2026-10-26-gungame-hud-design.md`.

## Goal

One HUD panel of up to three text lines that any of our plugins can fill: the server sends the text, icons are glyphs of our own font inside that text, each player picks where on the screen the panel sits. Gun Game is the first user. Next users (not in this task): lobby (next pairs), training servers (item timers), tournament match notice.

## Decisions (operator, 2026-10-27)

| Question | Decision |
|----------|----------|
| Shape | Up to 3 lines, no background for now |
| Position | 9 places as in Gun Game, chosen by the player (`seta mod_hud_pos`), the server never writes it |
| Icons | Glyphs of our font inline in the text: all weapons, mega, armors, powerups, flag, heavy and rounded frame pieces, `▰▱` bars |
| Fonts | Only the fallback font `fonts/droidsansfallbackfull.ttf` is replaced; the stock fonts stay untouched |
| Timers (later users) | Both: countdown (resent once a second) and "appears at" game clock time (sent once per pickup) |
| Configuring | In-game admin commands to write lines and to list the icon tokens; a token table with a glyph picture in the repo |
| Background, text sizes | Later, separate step |
| Workshop delivery | Later, separate test; until then the pk3 is copied by hand |

## Verified facts this rests on

All in `skills/ql-live/reference/server-driven-hud-and-view.md` (root monorepo), verified live 2026-10-26/27:

- A crafted `cs <CS_SYSTEMINFO> "<fresh systeminfo>\key\value..."` sets cvars on one client; a HUD text item shows a cvar and repaints at once.
- `ui/intro.menu` is always loaded, before `cg_hudFiles`, so our block shows with any player HUD.
- `cvarTest`+`showCvar` with `cvarTest2`+`showCvar2` on one item is an AND; `hideCvar` next to `showCvar2` breaks the item.
- UTF-8 text reaches the HUD (blocks, shapes, box drawing, arrows, Cyrillic).
- A pk3 in `<home>/<steamid>/baseq3/` is not loaded; a pk3 in the install dir `Quake Live/baseq3/` is, and a `zz_*` pk3 overrides `pak00.pk3` files.
- A pk3 with only a patched `fonts/droidsansfallbackfull.ttf` makes our glyphs (Private Use Area and missing standard code points) draw inline, tinted by the text colour, at the text's size.
- `joingame_menu` ("Join Match", in `ui/intro.menu`) opens on connect and on every map load, not on Esc. Its `onOpen { setcvar x 0 }` runs; `setcvar x ""` does nothing.
- Server-set cvars outlive the connection until the game restarts; a reset to the stock "default" is not a clear (the client keeps the first server value as default).

Not verified, checked in the live step: right and centre text alignment of a cvar text item; the longest `cs` command the client accepts (Q3 limit is 1024 bytes per server command, an assumption for QL); glyph outlines traced from the stock icons are recognisable at HUD size; chat draws the glyphs too.

## Client package

One pk3, `zz_modhud.pk3`, built by `hud/build_modhud.py <pak00.pk3> <out dir>`. The repo holds only our templates, glyph definitions and the builder; id's files (`ui/intro.menu`, the fallback font) are read from the player's or our pak00 at build time.

| File in the pk3 | Content |
|-----------------|---------|
| `ui/intro.menu` | Stock file + one `onOpen` line in `joingame_menu` + 9 `menuDef`s of the panel |
| `fonts/droidsansfallbackfull.ttf` | Stock fallback font + our glyphs |

Install for now: copy `zz_modhud.pk3` to `<QL>/baseq3/` (install dir) and **delete the loose `<QL>/<steamid>/baseq3/ui/intro.menu`** of the Gun Game panel: the home dir is searched before the install dir, so a loose file there would win over the pk3 (Q3 search order, assumption; the live step confirms).

## Menu

One `menuDef` per position (`modhud_<pos>`), each with three text items, line `n` showing cvar `mod_hud_l<n>`.

- Item tests: `cvarTest "mod_hud_pos"` + `showCvar { <pos values> }` (top also matches `""`, i.e. unset) and `cvarTest2 "mod_hud_on"` + `showCvar2 { "1" }`. Only show tests (no `hideCvar`).
- `mod_hud_pos off` (or any unknown value) shows nothing.
- Text: `textscale .25`, `textstyle ITEM_TEXTSTYLE_SHADOWED`, white; colour via `^1`..`^7` in the text. Line step 14 px. Starting values, tuned live.
- Columns and anchors on the 640x480 virtual screen (starting values):

| Position | Anchor x | Top y | Align | widescreen |
|----------|----------|-------|-------|------------|
| top | 320 | 8 | centre | CENTER |
| center | 320 | 150 | centre | CENTER |
| bottom | 320 | 300 | centre | CENTER |
| left | 8 | 200 | left | LEFT |
| topleft | 8 | 8 | left | LEFT |
| bottomleft | 8 | 300 | left | LEFT |
| right | 632 | 200 | right | RIGHT |
| topright | 632 | 8 | right | RIGHT |
| bottomright | 632 | 300 | right | RIGHT |

  Items are 300 px wide; left: rect starts at x; right: rect ends at x (`ITEM_ALIGN_RIGHT`); centre: rect centred on x (`ITEM_ALIGN_CENTER`).
- Auto-clear: `joingame_menu` gets `onOpen { setcvar mod_hud_on 0 }`, so a panel left by any server goes away on the next connect or map load anywhere. The lines keep their text but are hidden.

## Glyphs

Added to the fallback font. Icons are traced from the alpha channel of the stock icons in pak00 (threshold, contour tracing, simplification, scaled to the font's em, baseline-aligned, advance = width + small gap). Frames and bars are drawn as box-drawing pieces filling the line height so neighbours join.

| Token | Code point | Source |
|-------|-----------|--------|
| `{g}` `{mg}` `{sg}` `{gl}` `{rl}` `{lg}` `{rg}` `{pg}` `{bfg}` `{gh}` `{ng}` `{pl}` `{cg}` `{hmg}` | U+E000..E00D | `icons/iconw_gauntlet`, `_machinegun`, `_shotgun`, `_grenade`, `_rocket`, `_lightning`, `_railgun`, `_plasma`, `_bfg`, `_grapple`, `icons/nailgun128`, `proxmine`, `chaingun128`, `weap_hmg` |
| `{mh}` `{ra}` `{ya}` `{ga}` `{shard}` | U+E010..E014 | `icons/iconh_mega`, `iconr_red`, `iconr_yellow`, `iconr_green`, `iconr_shard` |
| `{quad}` `{bs}` `{regen}` `{haste}` `{invis}` `{flight}` | U+E015..E01A | `icons/quad`, `envirosuit`, `regen`, `haste`, `invis`, `flight` |
| `{flag}` | U+E01B | `ui/assets/hud/flag` |
| `{on}` `{off}` | U+25B0, U+25B1 `▰▱` | drawn |
| literal only | U+2501 `━` U+2503 `┃` U+250F `┏` U+2513 `┓` U+2517 `┗` U+251B `┛` U+2523 `┣` U+252B `┫` U+256D..2570 `╭╮╯╰` | drawn |

Weapon tokens equal Gun Game's ladder keys. `{{` gives a literal `{`; an unknown token stays as typed. The builder also renders `hud/glyphs.png` (every glyph with its token) for the README; browsers show Private Use Area code points as boxes, so the picture is the table people read.

## Server side

### `modhud_util.py` (helper, not a plugin)

Shipped with every plugin that uses it (`"depends_on": ["modhud_util.py"]` in the plugin's `.ql-plugin.json`, as `match_restore_util.py`). Pure functions, unit tested without the engine:

- `expand(text)` - tokens to glyphs.
- `fields(lines)` - `{"mod_hud_on": "1", "mod_hud_l1".."l3": ...}`, missing lines empty; `blank()` - `mod_hud_on` "0" and empty lines.
- `clean(value)` - drops `\`, `"`, `;`; `fit(value)` - cuts a line at 120 bytes of UTF-8 on a character boundary.
- `diff(sent, new)`, `command(cs_index, systeminfo, changed)`.

And one sender used from the game thread only, over a dict the calling plugin owns (client id -> fields last sent), so each plugin keeps its own scheduling (Gun Game's dirty set and next-frame flush stay):

- `send(engine, sent, cid, new, systeminfo)` sends one `cs` with only the fields that differ from `sent[cid]` (a missing entry counts as blank, so a never-shown player gets no clear). Delivered show: records it; delivered blank: drops the entry; refused (client not active yet, `send_server_command` False or raising): marks the entry unknown so the next send carries every field, as Gun Game does today.

### `modhud.py` (plugin)

Manual control and the reference user. Commands (permission `qlx_modHudPerm`, default 3):

| Command | Does |
|---------|------|
| `!hud <1-3> <text>` | Line n for everyone; tokens expanded |
| `!hud clear` | Blank for everyone |
| `!hudicons` | Tells the caller every token next to its glyph (a few chat lines) |

On `player_loaded` it sends the lines set by `!hud` (if any). It is not needed by other plugins; a server can run Gun Game without it.

### Several writers

The panel is one per client. If two plugins write it, the last write wins. One mode uses the panel on a server; a plugin that turns its HUD off sends `clear`.

### Rate and size

Send on events; a countdown at most once a second. One command carries the fresh systeminfo (about 420 chars on our hosts) plus the changed fields; with three 120-byte lines it stays under 1024 bytes. The live step sends three full lines to confirm the client takes it.

## Gun Game on the panel

- `gungame.py` builds its fields with `modhud_util.fields` and sends with `modhud_util.send`; line 1 = `{<next weapon>} <frags>/<needed>`, on the last step `<frags>/<needed>`. Lines 2 and 3 stay empty (room for later).
- Removed: `mod_gg_on`, `mod_gg_next`, `mod_gg_prog`, `mod_gg_pos`, `hud/gungame.menu`, `hud/build_intro_menu.py`. `qlx_gunGameHud` stays as the switch. `gungame.ql-plugin.json` gets `depends_on`.
- Players who set `mod_gg_pos` set `mod_hud_pos` instead (README note).

## Testing

- Unit: token expansion, field building, diff, `fit` on multi-byte text, command format (helper); menu text has 9 menuDefs x 3 items with the right tests and the `onOpen` line, font has every code point of the table, PNG rendered (builder); Gun Game HUD tests rewritten for the helper. Only these test files run.
- Live on #26 (operator, pk3 installed by hand): `!hud` lines in all 9 positions (`mod_hud_pos`), centre/right alignment, `!hudicons` and every glyph legible, three full 120-byte lines arrive, panel gone after reconnect, Gun Game line 1 during a round with bots.

## Not in scope

Background boxes and text sizes; lobby, training-timer and tournament-notice users; Workshop delivery (its test decides whether a Workshop pk3 overrides `ui/intro.menu` and the font); coloured icons.
