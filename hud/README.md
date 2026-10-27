# Mod HUD panel

Three text lines on the player's screen that any plugin fills from the server (`modhud_util.py`), with icons as glyphs of our own font. Gun Game shows the next weapon and the frags towards it on line 1; `modhud.py` writes lines by hand (`!hud`). Design: `docs/superpowers/specs/2026-10-27-mod-hud-panel-design.md`.

## Client package

`zz_modhud.pk3` holds `ui/intro.menu` (stock + nine panels + auto-clear) and `fonts/droidsansfallbackfull.ttf` (stock + our glyphs). The stock files are id's and are not in this repo; build the pk3 from a local pak00:

    python hud/build_modhud.py <QL>/baseq3/pak00.pk3 <out dir>

(needs fontTools, Pillow, numpy, opencv-python). It also writes `glyphs.png`; the copy in this folder is the token table.

Install by hand for now: copy `zz_modhud.pk3` to `<QL>/baseq3/` (the install dir; a pk3 in `<QL>/<steamid>/baseq3/` is not loaded) and remove an old loose `<QL>/<steamid>/baseq3/ui/intro.menu` (the earlier Gun Game panel), which would win over the pk3. Restart the game. Workshop delivery is a separate, later step.

## Position

Each player in their own console: `seta mod_hud_pos top` (default when unset), `center`, `bottom`, `left`, `topleft`, `bottomleft`, `right`, `topright`, `bottomright` or `off`. Left places align text to the left, right places to the right, the middle column centres it. Free x/y is not possible: a menu rect is fixed in the file. Players who used `mod_gg_pos` set `mod_hud_pos` instead. If nothing shows with the cvar unset, set it explicitly (`seta mod_hud_pos top`): whether the menu's empty-value test matches is not verified in QL.

The panel hides itself on the next connect or map load on any server (`onOpen` of the Join Match menu), so a panel left by our server never sticks on someone else's.

## Text and icons

Colours with `^1`..`^7`; icons as tokens, `{{` for a literal `{`:

![glyphs](glyphs.png)

Weapon tokens equal Gun Game's ladder keys. `{ra}`, `{ya}` and `{ga}` share one shape; colour them (`^1{ra}`, `^3{ya}`, `^2{ga}`). Frame pieces are typed as characters: `━ ┃ ┏ ┓ ┗ ┛ ┣ ┫ ╭ ╮ ╯ ╰`; the stock font already has `─ │ ┌ ┐ └ ┘ ═ ║ ╔ ╗` and blocks `█ ░ ▒ ▓`. The text is proportional, so frames suit headers and separators, not boxes around text.

In game: `!hud 1 ^3{mh}^7 0:35  ^1{ra}^7 0:12`, `!hud clear`, `!hudicons`.

## For plugin authors

```python
import modhud_util
sent = {}  # client id -> fields this plugin last asked for
info = minqlx.configstring(minqlx.CS_SYSTEMINFO, cached=False)
modhud_util.send(minqlx, sent, player.id, modhud_util.fields(["{rl} 1/2", "second line"]), info)
modhud_util.send(minqlx, sent, player.id, modhud_util.blank(), info)  # clear
```

- Game thread only; send on events, a countdown at most once a second.
- In the `map` hook call `modhud_util.reset_clients()` and send your lines again (clients still loading refuse; send again on `player_loaded`): Join Match hides every panel on each map load.
- In `player_disconnect` call `modhud_util.forget(player.id)`.
- Each line is cut at 120 bytes, and a whole command is cut under the engine's 1022-byte limit (the longest line gives way).
- The panel is one per client and what each client shows is tracked once (`modhud_util.CLIENT`) for every plugin: the last write wins and replaces all three lines. A blank only goes out from a plugin that showed the panel itself, so `!hud clear` does not remove Gun Game's line.
- Add `"depends_on": ["modhud_util.py"]` to the plugin's `.ql-plugin.json`.
