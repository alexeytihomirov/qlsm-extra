# Gun Game HUD panel

`gungame.py` (with `qlx_gunGameHud 1`) writes the client cvars `mod_gg_on`, `mod_gg_w`, `mod_gg_next`, `mod_gg_step`, `mod_gg_lead`; `gungame.menu` draws them. Design: `docs/superpowers/specs/2026-10-26-gungame-hud-design.md`.

Build (the stock `ui/intro.menu` is id's and is not in this repo):

    python hud/build_intro_menu.py <QL>/baseq3/pak00.pk3 <out dir>

Install: copy `<out dir>/ui/intro.menu` to `<QL home>/<steamid>/baseq3/ui/intro.menu` and restart the game. It shows with any HUD, because the client always loads `ui/intro.menu`.

Position, per player in their own console: `seta mod_gg_pos top` (default when unset), `left`, `bottom` or `off`.

Only one mod can override `ui/intro.menu`; a future mod panel goes into the same file.
