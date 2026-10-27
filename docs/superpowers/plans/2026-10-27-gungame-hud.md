# Gun Game HUD Panel Implementation Plan

> **Superseded 2026-10-27** by `docs/superpowers/plans/2026-10-27-mod-hud-panel.md`: everything this plan built is removed. Kept as history.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A server-driven Gun Game panel on the player's screen: current and next weapon icons, step and frags, leader line; position chosen by the player.

**Architecture:** Pure functions in `gungame.py` build the panel fields and the `cs` command; the plugin marks players dirty on events and one `next_frame` flush per frame sends only changed fields per player. A menu template plus a build script produce `ui/intro.menu` (stock text + three position copies of our panel).

**Tech Stack:** Python 3, minqlxtended fork API, pytest with `tests/_minqlx_stub.py`; QL menu script.

**Spec:** `docs/superpowers/specs/2026-10-26-gungame-hud-design.md` (parent: `docs/superpowers/specs/2026-10-26-gungame-design.md`)

Worktree: `D:/QuakeLiveData/QL Server/.worktrees/qlsm-extra-gungame`, branch `feat/gungame`; every command runs from there. Commits go to `main` by `git push origin HEAD:main` after `git pull --ff-only origin main` (another session also pushes `main`).

## Global Constraints

- Client cvars: `mod_gg_on`, `mod_gg_w`, `mod_gg_next`, `mod_gg_step`, `mod_gg_lead` (server-written), `mod_gg_pos` (player-only, never written by the server).
- Values: `mod_gg_on` `1` or empty; `mod_gg_step` `Step 3/9   1/2` (three spaces); `mod_gg_lead` `Leader: <name> 5/9`, `You lead`, or empty.
- Command: `cs <CS_SYSTEMINFO> "<configstring(CS_SYSTEMINFO, cached=False)>\\k\\v..."`; values stripped of `\`, `"`, `;`. QL colour codes (`^3`) are allowed in values.
- New server cvar `qlx_gunGameHud`, default `1`.
- Bots (steam_id 0) never get commands. No timers.
- Only `tests/test_gungame.py`, `tests/test_gungame_hooks.py` and the new `tests/test_gungame_hud_menu.py` are run. Not the whole suite.
- Regenerate `qlsm-repository.json` with `python generate_manifest.py` before every commit that touches `gungame.py` (the pre-commit hook checks hashes).
- Commits without AI attribution.

## Review Focus

1. A player who joins mid-match after a leader exists must get the leader line on first spawn (flush computes from current state, not from the event).
2. A player who was never sent a panel must get no command when cleared (diff against an empty cache sends nothing).
3. Team switch from spectator to free must show the panel again on spawn (cache entry dropped on clear, so everything resends).
4. `mod_gg_lead` must not carry a nickname with `"` / `\` / `;` into the command (cleaning applies to every value).
5. `qlx_gunGameHud 0` set mid-match: the next flush per player clears; step-up centre prints come back.

---

### Task 1: Pure panel functions

**Files:**
- Modify: `gungame.py` (pure section, after `win_text`)
- Test: `tests/test_gungame.py`

**Interfaces:**
- Produces:
  - `HUD_FIELDS = ("mod_gg_on", "mod_gg_w", "mod_gg_next", "mod_gg_step", "mod_gg_lead")`
  - `hud_fields(ladder, state, lead) -> dict` with all five keys. `lead` is the finished leader string (may be empty).
  - `lead_text(own_key, leader_key, leader_name, leader_step, total) -> str`: `""` when `leader_key` is None, `"You lead"` when equal to `own_key`, else `"Leader: ^3{name}^7 {step}/{total}"` (step 1-based).
  - `hud_blank() -> dict`: all five keys mapped to `""`.
  - `hud_diff(sent, fields) -> dict`: keys whose value differs from `sent.get(key, "")`.
  - `hud_clean(value) -> str`: drops `\`, `"`, `;`.
  - `hud_command(cs_index, systeminfo, fields) -> str`: `'cs {i} "{info}\\k1\\v1\\k2\\v2"'`, keys in `HUD_FIELDS` order, values cleaned.

- [ ] **Step 1: Write the failing tests**

```python
L3 = gg.parse_ladder("rl:2 lg:1 g:1")

def test_hud_fields_first_middle_last():
    assert gg.hud_fields(L3, (0, 1), "You lead") == {
        "mod_gg_on": "1", "mod_gg_w": "rl", "mod_gg_next": "lg",
        "mod_gg_step": "Step 1/3   1/2", "mod_gg_lead": "You lead"}
    assert gg.hud_fields(L3, (1, 0), "")["mod_gg_next"] == "g"
    last = gg.hud_fields(L3, (2, 0), "")
    assert last["mod_gg_w"] == "g" and last["mod_gg_next"] == "" and last["mod_gg_step"] == "Step 3/3   0/1"

def test_lead_text():
    assert gg.lead_text("1", None, None, 0, 3) == ""
    assert gg.lead_text("1", "1", "A", 2, 3) == "You lead"
    assert gg.lead_text("1", "2", "Bob", 2, 3) == "Leader: ^3Bob^7 2/3"

def test_hud_diff_and_blank():
    assert gg.hud_diff({}, gg.hud_blank()) == {}
    assert gg.hud_diff({"mod_gg_on": "1", "mod_gg_w": "rl"}, {"mod_gg_on": "1", "mod_gg_w": "lg"}) == {"mod_gg_w": "lg"}

def test_hud_command_cleans_values_and_keeps_order():
    cmd = gg.hud_command(1, "\\sv_pure\\1", {"mod_gg_lead": 'Leader: a"b\\c;d 2/3', "mod_gg_on": "1"})
    assert cmd == 'cs 1 "\\sv_pure\\1\\mod_gg_on\\1\\mod_gg_lead\\Leader: abcd 2/3"'
```

- [ ] **Step 2: Run, expect FAIL** - `rtk proxy python -m pytest tests/test_gungame.py -q` - AttributeError on `hud_fields`.
- [ ] **Step 3: Implement the functions above.** `mod_gg_step` format `"Step {}/{}   {}/{}"`.
- [ ] **Step 4: Run, expect PASS** - same command.
- [ ] **Step 5: Commit** - `gungame: pure HUD panel fields and cs command` (with `qlsm-repository.json`).

### Task 2: Plugin sends, diffs and clears the panel

**Files:**
- Modify: `gungame.py` (class `gungame`, header comment, `CVAR_DEFAULTS`)
- Modify: `gungame.ql-plugin.json` (cvar `qlx_gunGameHud`)
- Test: `tests/test_gungame_hooks.py`

**Interfaces:**
- Consumes: Task 1 functions.
- Produces (instance state): `_hud_sent: dict[int, dict]` (client id -> fields last sent), `_hud_dirty: set[int]`, `_leader_name: str|None`, `_ended: bool`.
- Methods: `_hud_mark(player)`, `_hud_mark_all()`, `_hud_flush()` (wrapped with `minqlx.next_frame` as `_hud_flush_soon`, scheduled once per frame via a `_hud_pending` flag), `_hud_on(player) -> bool`, `_hud_send(player_id, fields, info)`, `_hud_clear_now(player_id)`.
- Hooks added: `team_switch(player, old_team, new_team)`, `player_disconnect(player, reason)`.

Rules (from the spec):
- `_hud_on(player)`: `_active()` and `qlx_gunGameHud` true and not `_ended` and `player.team == "free"` and steam_id != 0.
- Flush: one `configstring(CS_SYSTEMINFO, cached=False)` per flush; for each dirty id still in `self.players()`: fields = `hud_fields(...)` if `_hud_on` else `hud_blank()`; diff against `_hud_sent.get(id, {})`; send if non-empty; store merged. A blank result drops the cache entry.
- Mark: spawn (the player), `handle_kill` (killer and victim), `handle_death` suicide (victim), `_update_leader` change (all), `handle_new_game` and `handle_game_start` (all), `team_switch` (that player), `game_end` (set `_ended`, mark all).
- `player_disconnect`: `_hud_clear_now(id)` - send `hud_blank()` diff right away, best effort, drop cache.
- Unload: `_hud_clear_now` for every cached id.
- `_leader_name` set in `_update_leader` (the name it announces), cleared in `_reset`; `_ended` cleared in `_reset`.
- Step-up centre: in `handle_kill` the `up` notify passes `center=False` when `qlx_gunGameHud` is true; `_notify(target, text, cvar, center=True)`.

- [ ] **Step 1: Write the failing tests** (fake engine gets `send_server_command(cid, cmd)` recording to a list, `configstring(i, cached=True)` returning `"\\sv_pure\\1"`, `CS_SYSTEMINFO = 1`; the `make_plugin` fake gets the new state attributes; flush is called directly):
  - `test_kill_sends_one_command_per_player_with_changed_fields`: A kills B with RL, flush; two commands, A's contains `mod_gg_step\\Step 1/3   1/2`, B's contains `mod_gg_on\\1`; second flush with no event sends nothing.
  - `test_bots_get_no_panel`: bot killer, flush, no commands.
  - `test_leader_change_marks_everyone`: three players, A takes the lead, flush; B and C each get `mod_gg_lead\\Leader: ^3A^7 2/3`, A gets `You lead`.
  - `test_spectator_and_game_end_clear`: after a sent panel, `handle_team_switch(a, "free", "spectator")` + flush sends `mod_gg_on\\` (empty) and drops the cache; `handle_game_end(False)` + flush clears B.
  - `test_never_shown_player_gets_no_clear`: disabled plugin, spawn, flush, no commands.
  - `test_hud_off_keeps_centre_step_print`: `qlx_gunGameHud 0`, `qlx_gunGameStepNotify center`, step up -> one centre delay for the killer and no commands; with `qlx_gunGameHud 1` -> no centre delay for the step.
  - `test_disconnect_clears_at_once`: sent panel, `handle_player_disconnect(a, "left")` sends blank immediately (no flush) and drops the cache.
  - Add `handle_team_switch: 3`, `handle_player_disconnect: 2` to `DISPATCH_ARITY`.
- [ ] **Step 2: Run, expect FAIL** - `rtk proxy python -m pytest tests/test_gungame_hooks.py -q`.
- [ ] **Step 3: Implement** the rules above; header comment gets `qlx_gunGameHud`; `gungame.ql-plugin.json` gets the cvar with description "Server-driven HUD panel (needs our ui/intro.menu on the client); while on, a step up is not centre-printed".
- [ ] **Step 4: Run, expect PASS** - `rtk proxy python -m pytest tests/test_gungame.py tests/test_gungame_hooks.py -q`.
- [ ] **Step 5: Commit** - `gungame: HUD panel over client cvars`.

### Task 3: Menu template and intro.menu builder

**Files:**
- Create: `hud/gungame.menu` (template), `hud/build_intro_menu.py`, `hud/README.md` (how to build and install, 10 lines)
- Test: `tests/test_gungame_hud_menu.py`

**Interfaces:**
- `build(stock_text: str, template: str) -> str`: inserts the three expanded copies before the last `}` of the stock text; the stock text before that point is unchanged.
- `expand(template, pos) -> str` for `pos` in `("top", "left", "bottom")`: replaces `@POS_TEST@` with the position test lines, `@X@`/`@Y@` with the copy's origin, `@NAME@` with `gungame_<pos>`.
- `WEAPON_ICONS`: `g icons/iconw_gauntlet.tga`, `mg iconw_machinegun`, `sg iconw_shotgun`, `gl iconw_grenade`, `rl iconw_rocket`, `lg iconw_lightning`, `rg iconw_railgun`, `pg iconw_plasma`, `bfg iconw_bfg`, `gh iconw_grapple`, `ng icons/nailgun128.tga`, `pl icons/proxmine.tga`, `cg icons/chaingun128.tga`, `hmg icons/weap_hmg.tga` (all present in pak00 `icons/`). The template holds one `@ICONS_CUR@` and one `@ICONS_NEXT@` marker that `expand` fills with one item per key.
- CLI: `python hud/build_intro_menu.py <pak00 dir or .pk3> <out dir>` writes `<out>/ui/intro.menu`; reads `ui/intro.menu` from a directory or from inside the zip.

Position tests: top `cvarTest "mod_gg_pos"` + `hideCvar { "left" ; "bottom" ; "off" }`; left `showCvar { "left" }`; bottom `showCvar { "bottom" }`. Content tests: `cvarTest2 "mod_gg_on"` + `showCvar2 { "1" }`, icons `cvarTest2 "mod_gg_w"` / `"mod_gg_next"` + `showCvar2 { "<key>" }`. Panel 240x44: current icon 32x32, text `mod_gg_step` right of it, next icon 20x20 at the right, `mod_gg_lead` on a second line; background `backcolor 0 0 0 0.35`. Origins: top (200, 8), left (8, 150), bottom (200, 380).

- [ ] **Step 1: Write the failing tests**: `build` keeps the stock prefix byte-for-byte and ends with `}`; output has exactly three `menuDef` blocks named `gungame_top/left/bottom`; each has 28 icon items (14 cur + 14 next); the top copy contains `hideCvar { "left" ; "bottom" ; "off" }`; no `@` placeholders remain.
- [ ] **Step 2: Run, expect FAIL** - `rtk proxy python -m pytest tests/test_gungame_hud_menu.py -q`.
- [ ] **Step 3: Implement** template, builder, README.
- [ ] **Step 4: Run, expect PASS**; then build for real: `python hud/build_intro_menu.py D:/QuakeLiveData/pak00 <scratchpad>/gg_hud` and eyeball the tail.
- [ ] **Step 5: Commit** - `gungame: HUD menu template and intro.menu builder`.

### Task 4: Deploy and live check

- [ ] **Step 1:** Final review of the branch diff (one fresh reviewer), fix Critical/Important.
- [ ] **Step 2:** Deploy `gungame.py` to qlsm instance 26 through the config save (scratchpad `gg_install.py`, same ADD_LINES plus `qlx_gunGameHud 1`), re-add 4 bots.
- [ ] **Step 3:** Hand the operator: the built `intro.menu` path, the target folder `<QL>/<steamid>/baseq3/ui/`, then: connect to `185.11.244.225:27964`, see the panel top; frag a bot, step text changes; `seta mod_gg_pos left`, `bottom`, `off`, unset; spectate, panel gone.
- [ ] **Step 4:** Journal in `tasks/0027-gun-game-and-nix-game-mode-plugins.md`; record `cvarTest2`/`hideCvar` results in `skills/ql-live/reference/server-driven-hud-and-view.md` (monorepo) once seen.
