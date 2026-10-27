# Gun Game HUD panel

A small panel with the next weapon of the ladder and the frags towards it (`1/2`); on the last step only the frags. `gungame.py` (with `qlx_gunGameHud 1`) writes the client cvars `mod_gg_on`, `mod_gg_next`, `mod_gg_prog`; `gungame.menu` draws them. Design: `docs/superpowers/specs/2026-10-26-gungame-hud-design.md`.

Build (the stock `ui/intro.menu` is id's and is not in this repo):

    python hud/build_intro_menu.py <QL>/baseq3/pak00.pk3 <out dir>

Install: copy `<out dir>/ui/intro.menu` to `<QL home>/<steamid>/baseq3/ui/intro.menu` and restart the game. It shows with any HUD, because the client always loads `ui/intro.menu`.

Position, per player in their own console: `seta mod_gg_pos top` (default when unset), `bottom`, `left`, `right`, `center`, `topleft`, `topright`, `bottomleft`, `bottomright` or `off`. Free x/y is not possible: a menu's rect is fixed in the file and menus cannot read numbers from cvars, so every position is a copy of the panel in `ui/intro.menu`.

Only one mod can override `ui/intro.menu`; a future mod panel goes into the same file.
