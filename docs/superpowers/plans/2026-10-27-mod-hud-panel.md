# Shared mod HUD panel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A 3-line HUD panel in 9 player-chosen places that any plugin fills from the server, with icons as glyphs of our own fallback font; Gun Game moves onto it.

**Architecture:** `modhud_util.py` (pure helpers + one `send` function over a caller-owned dict) is shipped with every user plugin. `modhud.py` is a small plugin with admin commands. `hud/build_modhud.py` builds `zz_modhud.pk3` (patched `ui/intro.menu` + patched fallback font) and `hud/glyphs.png` from a local pak00. Gun Game keeps its dirty/flush scheduling and swaps its field and command code for the helper.

**Tech Stack:** Python 3.12, minqlxtended plugin API, pytest; builder only: fontTools, Pillow, numpy, opencv-python.

**Spec:** `docs/superpowers/specs/2026-10-27-mod-hud-panel-design.md`

## Global Constraints

- Client cvars: `mod_hud_on`, `mod_hud_l1`, `mod_hud_l2`, `mod_hud_l3`, `mod_hud_pos` (player only). Field order in a command: on, l1, l2, l3.
- Shown when `mod_hud_on` is `"1"`; blank = `mod_hud_on "0"` and empty lines (menus cannot set `""`).
- Line limit 120 bytes of UTF-8, cut on a character boundary; values lose `\`, `"`, `;`.
- Positions: `top` (also unset), `center`, `bottom`, `left`, `topleft`, `bottomleft`, `right`, `topright`, `bottomright`; anchors and aligns as in the spec table; `textscale .25`, line step 14, item width 300.
- Menu tests: only `showCvar`/`showCvar2`, never `hideCvar`.
- `joingame_menu` gets `onOpen { setcvar mod_hud_on 0 }`.
- Glyph code points and tokens exactly as the spec table; weapon tokens = Gun Game ladder keys.
- Only `fonts/droidsansfallbackfull.ttf` is patched; id's files never enter the repo.
- `!hud`, `!hudicons` permission from `qlx_modHudPerm`, default 3.
- Tests: run only the named test files, never the whole suite.

## Review Focus

1. A line of Cyrillic or glyphs longer than 120 bytes must be cut between characters, never inside one (`test_fit_cuts_on_char_boundary`).
2. A player who never had the panel must get no blank command when a plugin clears (`test_send_blank_to_never_shown_sends_nothing`).
3. A send refused because the client is still loading must lead to a full resend later (`test_send_refused_marks_full_resend`).
4. `!hud 4 x`, `!hud`, `!hud 1` (no text) must answer with usage and send nothing (`test_hud_bad_args`).
5. A stock `ui/intro.menu` without `joingame_menu`, or already carrying an `onOpen` there, must make the builder fail loudly, not ship a panel without auto-clear (`test_onopen_requires_joingame_menu`).

---

### Task 1: `modhud_util.py`

**Files:**
- Create: `modhud_util.py`, `modhud_util.ql-plugin.json` (label/description "Helper of plugins that use the mod HUD panel, downloaded with them. Not a plugin.")
- Test: `tests/test_modhud_util.py`

**Interfaces:**
- Produces: `FIELDS: tuple[str, ...]`, `TOKENS: dict[str, str]` (token name -> glyph char), `MAX_LINE_BYTES = 120`, `expand(text: str) -> str`, `fit(text: str, limit: int = MAX_LINE_BYTES) -> str`, `clean(value) -> str`, `fields(lines: list[str]) -> dict[str, str]`, `blank() -> dict[str, str]`, `diff(sent: dict, new: dict) -> dict`, `command(cs_index: int, systeminfo: str, changed: dict) -> str`, `send(engine, sent: dict, cid: int, new: dict, systeminfo: str) -> None`.

- [ ] Step 1: failing tests:
  - `expand("{rl} 1/2") == "\ue004 1/2"`, `expand("{mh}{ra}") == "\ue010\ue011"`, `expand("{on}{off}") == "\u25b0\u25b1"`, `expand("{{rl}") == "{rl}"`, `expand("{nope}") == "{nope}"`.
  - `test_fit_cuts_on_char_boundary`: `fit("Ж" * 100)` encodes to 120 bytes; `fit("a" + "\ue004" * 50)` is 118 bytes and decodes.
  - `fields(["a"]) == {"mod_hud_on": "1", "mod_hud_l1": "a", "mod_hud_l2": "", "mod_hud_l3": ""}`; a 4th line is dropped; values are expanded, cleaned, fitted.
  - `blank() == {"mod_hud_on": "0", "mod_hud_l1": "", "mod_hud_l2": "", "mod_hud_l3": ""}`.
  - `diff({}, blank()) == {}` (missing = blank); `diff({k: None for k in FIELDS}, blank()) == blank()`.
  - `command(1, "\\sv_pure\\1", {"mod_hud_l1": 'a"b', "mod_hud_on": "1"}) == 'cs 1 "\\sv_pure\\1\\mod_hud_on\\1\\mod_hud_l1\\ab"'`.
  - `send`: records `dict(new)` after a delivered show; pops after a delivered blank; `test_send_blank_to_never_shown_sends_nothing`; `test_send_refused_marks_full_resend` (engine returns False -> `sent[cid] == dict.fromkeys(FIELDS)`, next `send` sends all four fields); an exception from `send_server_command` counts as refused.
- [ ] Step 2: run `python -m pytest tests/test_modhud_util.py -q`, expect import failure.
- [ ] Step 3: implement. `diff` compares against `sent.get(k, blank()[k])`. Glyph table from the spec (U+E000.. weapons in ladder order g mg sg gl rl lg rg pg bfg gh ng pl cg hmg; U+E010.. mh ra ya ga shard quad bs regen haste invis flight flag).
- [ ] Step 4: tests pass.
- [ ] Step 5: commit `modhud: helper for the shared HUD panel`.

### Task 2: menu builder

**Files:**
- Create: `hud/modhud.menu` (one menuDef template: `@NAME@`, `@WIDE@`, `@LINES@`), `hud/build_modhud.py` (menu part)
- Test: `tests/test_modhud_menu.py`

**Interfaces:**
- Consumes: none.
- Produces: `POSITIONS: dict[str, tuple[int, int, str, str]]` (x, top y, align `left|center|right`, widescreen), `LINE_STEP = 14`, `ITEM_WIDTH = 300`, `build_menu(stock_text: str, template: str) -> str`.

- [ ] Step 1: failing tests (stock = minimal text with `joingame_menu`, as Gun Game's test): 9 menuDefs `modhud_<pos>`, each 3 items with `cvar "mod_hud_l1".."l3"`; every item has `cvarTest "mod_hud_pos"` with `showCvar { "" ; "top" }` for top else `{ "<pos>" }`, and `cvarTest2 "mod_hud_on"` + `showCvar2 { "1" }`; no `hideCvar`; right items `ITEM_ALIGN_RIGHT` and rect ending at x; centre items centred; all rects inside 0..640 x 0..480; `onOpen { setcvar mod_hud_on 0 }` follows `name "joingame_menu"` exactly once; `test_onopen_requires_joingame_menu` (missing menu or existing onOpen -> `ValueError`); stock prefix kept and closing brace last.
- [ ] Step 2: run `python -m pytest tests/test_modhud_menu.py -q`, expect failure.
- [ ] Step 3: implement `build_menu` like Gun Game's `build` (our menuDefs before the stock closing brace).
- [ ] Step 4: tests pass.
- [ ] Step 5: commit `modhud: intro.menu builder with nine 3-line panels and auto-clear`.

### Task 3: glyph font, pk3 and sheet

**Files:**
- Modify: `hud/build_modhud.py` (font, sheet, `main`)
- Test: `tests/test_modhud_font.py` (`pytest.importorskip` for fontTools, cv2, PIL)

**Interfaces:**
- Consumes: `modhud_util.TOKENS`, `build_menu`.
- Produces: `ICON_SOURCES: dict[str, str]` (token -> pak00 path without extension), `trace(rgba: PIL.Image) -> list[list[tuple[int, int]]]` (contours in image pixels, y down), `add_glyphs(font_bytes: bytes, icons: dict[str, Image]) -> bytes`, `render_sheet(font_bytes: bytes, path) -> None`, `main(argv) -> int` (`build_modhud.py <pak00.pk3> <out dir>` writes `<out>/zz_modhud.pk3` and `<out>/glyphs.png`).

- [ ] Step 1: failing tests with a synthetic base font (fontTools `FontBuilder`, em 256, glyphs `.notdef` and `A`) and synthetic RGBA icons (a filled square with a square hole): every code point of `TOKENS` and the literal frame list is in the result's cmap; the traced hole survives (glyph has 2 contours); icon glyph height within the line (yMin >= -20, yMax <= 210 on a 256 em, scaled for other ems); `A` unchanged; `trace` of an empty image returns `[]` and the glyph becomes an empty glyph with an advance.
- [ ] Step 2: run `python -m pytest tests/test_modhud_font.py -q`, expect failure.
- [ ] Step 3: implement. Tracing: alpha > 127 mask, `cv2.findContours(RETR_CCOMP, CHAIN_APPROX_NONE)`, `cv2.approxPolyDP` epsilon 0.75 px, drop contours under 4 px area; map 64 px to 200 units at em 256 with bottom at -10, flip y; outer contours clockwise, holes counter-clockwise (TrueType). Frames: heavy lines 28 units thick, light-box geometry centred on the em, full line height (-68..267) so pieces join; rounded corners as 8-segment arcs. Advance = glyph width + 20 units. Sheet: Pillow `ImageFont.truetype` on the patched font, a grid of glyph + token text.
- [ ] Step 4: tests pass; then run the builder on the real pak00 (`E:/Steam/steamapps/common/Quake Live/baseq3/pak00.pk3`) into the session scratchpad, open `glyphs.png` and check every icon is recognisable; copy it to `hud/glyphs.png`.
- [ ] Step 5: commit `modhud: glyph font, pk3 and glyph sheet builder`.

### Task 4: `modhud.py` plugin

**Files:**
- Create: `modhud.py`, `modhud.ql-plugin.json` (commands, cvar `qlx_modHudPerm`, `"depends_on": ["modhud_util.py"]`)
- Test: `tests/test_modhud_plugin.py`

**Interfaces:**
- Consumes: Task 1.
- Produces: plugin class `modhud` with `cmd_hud(player, msg, channel)`, `cmd_hudicons(player, msg, channel)`, `handle_player_loaded(player)`, `handle_player_disconnect(player, reason)`; state `_lines: list[str]` (3), `_sent: dict`.

- [ ] Step 1: failing tests with Gun Game's fake engine pattern: `!hud 2 hello {rl}` sends one command per human (not bots) with `mod_hud_on\1` and `mod_hud_l2\hello \ue004`; `!hud clear` sends blank to those shown and resets lines; `test_hud_bad_args` (`!hud`, `!hud 4 x`, `!hud 1`) -> usage return, no command; a player loading after `!hud` gets the lines on `player_loaded`; nothing sent on `player_loaded` when no lines are set; `!hudicons` tells the caller lines that together contain every token name and its glyph, each tell under 150 chars.
- [ ] Step 2: run `python -m pytest tests/test_modhud_plugin.py -q`, expect failure.
- [ ] Step 3: implement (import `modhud_util` the way `match_restore.py` imports its helper).
- [ ] Step 4: tests pass.
- [ ] Step 5: commit `modhud: plugin with !hud and !hudicons`.

### Task 5: Gun Game on the panel

**Files:**
- Modify: `gungame.py` (HUD section ~170-205 and `_hud_send`/`_hud_clear_now`), `gungame.ql-plugin.json` (`depends_on`, `qlx_gunGameHud` description), `tests/test_gungame.py`, `tests/test_gungame_hooks.py` (HUD section), `hud/README.md`, `generate_manifest.py` (`DEFAULT_PLUGINS` + `modhud.py`, `modhud_util.py`), `qlsm-repository.json` (regenerated), task file
- Delete: `hud/gungame.menu`, `hud/build_intro_menu.py`, `tests/test_gungame_hud_menu.py`

**Interfaces:**
- Consumes: `modhud_util.fields/blank/diff/send/FIELDS`.
- Produces: `gungame.hud_line(ladder, state) -> str` (`"{lg} 1/2"` before expansion; last step `"0/1"`), `hud_fields(ladder, state) -> dict` = `modhud_util.fields([hud_line(...)])`.

- [ ] Step 1: rewrite the HUD tests to the new fields: `hud_line(L3, (0, 1)) == "{lg} 1/2"`, `hud_line(L3, (2, 0)) == "0/1"`; hook tests expect `\\mod_hud_on\\1\\mod_hud_l1\\\ue005 1/2` etc. and blank `mod_hud_on\\0`; keep every existing scenario (bots, bystander, spectator, game end, disconnect, loading retries, HUD off).
- [ ] Step 2: run `python -m pytest tests/test_gungame.py tests/test_gungame_hooks.py -q`, expect failures.
- [ ] Step 3: replace the HUD helpers with the helper module; `_hud_send` becomes `modhud_util.send(minqlx, self._hud_sent, player_id, fields, info)`; delete the old builder, template and its test; README: install `zz_modhud.pk3`, `mod_hud_pos`, token table picture, `!hud`; run `python generate_manifest.py`.
- [ ] Step 4: `python -m pytest tests/test_gungame.py tests/test_gungame_hooks.py tests/test_modhud_util.py tests/test_modhud_menu.py tests/test_modhud_font.py tests/test_modhud_plugin.py -q` pass; `python check_manifest_hashes.py` clean.
- [ ] Step 5: commit `gungame: HUD on the shared mod panel`.

### Task 6: ship and live check

- [ ] Merge `feat/modhud` into `main`, push, confirm with `git ls-remote origin main`.
- [ ] Deploy on #26 via qlsm (repository sync, download `gungame.py`, `modhud.py`, `modhud_util.py`, add `modhud` to `qlx_plugins`, apply with restart); confirm the files on the host by hash.
- [ ] Operator client: `zz_modhud.pk3` into `Quake Live/baseq3/`, loose `<steamid>/baseq3/ui/intro.menu` moved aside (backup kept).
- [ ] Operator checks (spec "Testing"); fix and journal; task to `done-unverified`, `done` after the operator confirms.
