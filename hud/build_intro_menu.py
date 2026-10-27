"""Build ui/intro.menu with the Gun Game panel: stock intro.menu + three position copies.

    python hud/build_intro_menu.py <pak00 dir or pak00.pk3> <out dir>

Writes <out dir>/ui/intro.menu. The stock file is id's; the repo only holds our template.
"""
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent

# Ladder key -> stock pak00 image (referenced as .tga, the client finds the shipped format).
WEAPON_ICONS = {
    "g": "icons/iconw_gauntlet.tga",
    "mg": "icons/iconw_machinegun.tga",
    "sg": "icons/iconw_shotgun.tga",
    "gl": "icons/iconw_grenade.tga",
    "rl": "icons/iconw_rocket.tga",
    "lg": "icons/iconw_lightning.tga",
    "rg": "icons/iconw_railgun.tga",
    "pg": "icons/iconw_plasma.tga",
    "bfg": "icons/iconw_bfg.tga",
    "gh": "icons/iconw_grapple.tga",
    "ng": "icons/nailgun128.tga",
    "pl": "icons/proxmine.tga",
    "cg": "icons/chaingun128.tga",
    "hmg": "icons/weap_hmg.tga",
}

# pos -> (x, y, widescreen) of the 240x44 panel on the 640x480 screen.
POSITIONS = {
    "top": (200, 8, "WIDESCREEN_CENTER"),
    "left": (8, 150, "WIDESCREEN_LEFT"),
    "bottom": (200, 380, "WIDESCREEN_CENTER"),
}

# Unset mod_gg_pos means top, so the top copy hides on the other values instead.
POS_TESTS = {
    "top": 'cvarTest "mod_gg_pos"\n\t\t\thideCvar { "left" ; "bottom" ; "off" }',
    "left": 'cvarTest "mod_gg_pos"\n\t\t\tshowCvar { "left" }',
    "bottom": 'cvarTest "mod_gg_pos"\n\t\t\tshowCvar { "bottom" }',
}

ICON_ITEM = """
		itemDef {{
			name "gg_{slot}_{key}"
			rect {rect}
			style WINDOW_STYLE_FILLED
			background "{image}"
			visible 1
			decoration
			{pos_test}
			cvarTest2 "{cvar}"
			showCvar2 {{ "{key}" }}
		}}
"""


def icon_items(slot, cvar, rect, pos_test):
    return "".join(
        ICON_ITEM.format(slot=slot, key=key, rect=rect, image=image, pos_test=pos_test, cvar=cvar)
        for key, image in WEAPON_ICONS.items())


def expand(template, pos):
    x, y, wide = POSITIONS[pos]
    pos_test = POS_TESTS[pos]
    return (template
            .replace("@ICONS_CUR@", icon_items("cur", "mod_gg_w", "4 6 32 32", pos_test))
            .replace("@ICONS_NEXT@", icon_items("next", "mod_gg_next", "216 4 20 20", pos_test))
            .replace("@POS_TEST@", pos_test)
            .replace("@NAME@", "gungame_" + pos)
            .replace("@WIDE@", wide)
            .replace("@X@", str(x))
            .replace("@Y@", str(y)))


def build(stock_text, template):
    """Stock text with our three menuDefs before its closing brace."""
    cut = stock_text.rindex("}")
    ours = "".join(expand(template, pos) for pos in POSITIONS)
    return stock_text[:cut] + "\n" + ours + stock_text[cut:]


def read_stock(source):
    source = Path(source)
    if source.is_dir():
        return (source / "ui" / "intro.menu").read_text(encoding="utf-8", errors="replace")
    with zipfile.ZipFile(source) as z:
        return z.read("ui/intro.menu").decode("utf-8", errors="replace")


def main(argv):
    if len(argv) != 2:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    template = (HERE / "gungame.menu").read_text(encoding="utf-8")
    out = Path(argv[1]) / "ui" / "intro.menu"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build(read_stock(argv[0]), template), encoding="utf-8", newline="\n")
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
