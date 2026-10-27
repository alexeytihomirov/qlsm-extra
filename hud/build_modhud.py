"""Build zz_modhud.pk3: ui/intro.menu with the mod HUD panel + the fallback font with our glyphs.
    python hud/build_modhud.py <pak00.pk3> <out dir>
Writes <out dir>/zz_modhud.pk3 and <out dir>/glyphs.png. The stock files are id's; the repo only
holds our template, glyph definitions and this builder.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

# mod_hud_pos value -> (anchor x, top y, text align, widescreen) on the 640x480 virtual screen.
# Left column: text starts at x; right column: text ends at x; centre: text centred on x.
POSITIONS = {
    "top": (320, 8, "center", "CENTER"),
    "center": (320, 150, "center", "CENTER"),
    "bottom": (320, 300, "center", "CENTER"),
    "left": (8, 200, "left", "LEFT"),
    "topleft": (8, 8, "left", "LEFT"),
    "bottomleft": (8, 300, "left", "LEFT"),
    "right": (632, 200, "right", "RIGHT"),
    "topright": (632, 8, "right", "RIGHT"),
    "bottomright": (632, 300, "right", "RIGHT"),
}
LINE_STEP = 14
ITEM_WIDTH = 300
JOIN_MENU = 'name "joingame_menu"'
ON_OPEN = '\n\t\tonOpen { setcvar mod_hud_on 0 }'

LINE_ITEM = """
		itemDef {{
			name "modhud_l{n}"
			type ITEM_TYPE_TEXT
			rect 0 {y} {w} {h}
			cvar "mod_hud_l{n}"
			textstyle ITEM_TEXTSTYLE_SHADOWED
			textscale .25
			textalign ITEM_ALIGN_{align}
			textalignx {ax}
			textaligny 12
			forecolor 1 1 1 1
			visible 1
			decoration
			cvarTest "mod_hud_pos"
			showCvar {{ {values} }}
			cvarTest2 "mod_hud_on"
			showCvar2 {{ "1" }}
		}}
"""


def pos_values(pos):
    """Unset mod_hud_pos (empty string) means top. Show tests only: hideCvar next to showCvar2
    broke an item live (Gun Game panel, 2026-10-27)."""
    return '"" ; "top"' if pos == "top" else '"{}"'.format(pos)


def expand(template, pos):
    x, y, align, wide = POSITIONS[pos]
    left, ax = {"left": (x, 0), "center": (x - ITEM_WIDTH // 2, ITEM_WIDTH // 2),
                "right": (x - ITEM_WIDTH, ITEM_WIDTH)}[align]
    lines = "".join(LINE_ITEM.format(n=n, y=(n - 1) * LINE_STEP, w=ITEM_WIDTH, h=LINE_STEP,
                                     align=align.upper(), ax=ax, values=pos_values(pos))
                    for n in (1, 2, 3))
    return (template
            .replace("@LINES@", lines)
            .replace("@NAME@", "modhud_" + pos)
            .replace("@WIDE@", "WIDESCREEN_" + wide)
            .replace("@X@", str(left))
            .replace("@Y@", str(y))
            .replace("@W@", str(ITEM_WIDTH))
            .replace("@H@", str(3 * LINE_STEP)))


def add_auto_clear(stock_text):
    """Join Match opens on every connect and map load (not on Esc): hide a panel any server left."""
    if stock_text.count(JOIN_MENU) != 1:
        raise ValueError("stock ui/intro.menu has no single joingame_menu")
    i = stock_text.index(JOIN_MENU) + len(JOIN_MENU)
    end = stock_text.find("menuDef", i)
    if "onOpen" in stock_text[i:end if end >= 0 else len(stock_text)]:
        raise ValueError("joingame_menu already has an onOpen")
    return stock_text[:i] + ON_OPEN + stock_text[i:]


def build_menu(stock_text, template):
    """Stock text with the auto-clear and our menuDefs (one per position) before its closing brace."""
    text = add_auto_clear(stock_text)
    cut = text.rindex("}")
    ours = "".join(expand(template, pos) for pos in POSITIONS)
    return text[:cut] + "\n" + ours + text[cut:]
