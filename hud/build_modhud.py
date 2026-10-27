"""Build zz_modhud.pk3: ui/intro.menu with the mod HUD panel + the fallback font with our glyphs.
    python hud/build_modhud.py <pak00.pk3> <out dir>
Writes <out dir>/zz_modhud.pk3 and <out dir>/glyphs.png. The stock files are id's; the repo only
holds our template, glyph definitions and this builder.
"""
import io
import math
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import modhud_util  # noqa: E402

FONT = "fonts/droidsansfallbackfull.ttf"
PK3 = "zz_modhud.pk3"
# What players get: unpack into <QL>/<steamid>/; loose files there win over pak00 and keep the
# player pure on every server (a pk3 does neither, see README.md).
CLIENT_ZIP = "modhud-client.zip"
CLIENT_README = "FRONTIER-HUD-README.txt"
TOKEN_NAMES = {
    "g": "Gauntlet", "mg": "Machine Gun", "sg": "Shotgun", "gl": "Grenade Launcher",
    "rl": "Rocket Launcher", "lg": "Lightning Gun", "rg": "Railgun", "pg": "Plasma Gun",
    "bfg": "BFG10K", "gh": "Grappling Hook", "ng": "Nailgun", "pl": "Proximity Launcher",
    "cg": "Chaingun", "hmg": "Heavy Machine Gun", "mh": "Mega Health", "ra": "Red Armor",
    "ya": "Yellow Armor", "ga": "Green Armor", "shard": "Armor Shard", "quad": "Quad Damage",
    "bs": "Battle Suit", "regen": "Regeneration", "haste": "Haste", "invis": "Invisibility",
    "flight": "Flight", "flag": "Flag (colour it with ^1 / ^4)", "on": "bar segment, full",
    "off": "bar segment, empty",
}

# Token -> stock icon in pak00 (extension tried: .png, .tga). Silhouettes are traced from alpha.
ICON_SOURCES = {
    "g": "icons/iconw_gauntlet", "mg": "icons/iconw_machinegun", "sg": "icons/iconw_shotgun",
    "gl": "icons/iconw_grenade", "rl": "icons/iconw_rocket", "lg": "icons/iconw_lightning",
    "rg": "icons/iconw_railgun", "pg": "icons/iconw_plasma", "bfg": "icons/iconw_bfg",
    "gh": "icons/iconw_grapple", "ng": "icons/nailgun128", "pl": "icons/proxmine",
    "cg": "icons/chaingun128", "hmg": "icons/weap_hmg",
    "mh": "icons/iconh_mega", "ra": "icons/iconr_red", "ya": "icons/iconr_yellow",
    "ga": "icons/iconr_green", "shard": "icons/iconr_shard", "quad": "icons/quad",
    "bs": "icons/envirosuit", "regen": "icons/regen", "haste": "icons/haste",
    "invis": "icons/invis", "flight": "icons/flight",
}
# {flag} is drawn (_drawn_shapes): pak00's flag images trace to dots or a filled badge.
# Frame pieces typed as literal characters: heavy lines, corners and tees; rounded corners.
FRAMES = ["━", "┃", "┏", "┓", "┗", "┛", "┣", "┫",
          "╭", "╮", "╯", "╰"]

# mod_hud_pos value -> (anchor x, top y, block placement, widescreen) on the 640x480 virtual
# screen. The text always starts at the block's left edge: a cvar text item with textalign
# CENTER or RIGHT is not drawn at all in QL (live, #26, 2026-10-27) and `align` is ignored. So
# the block starts at x (left), CENTER_LEAD left of x (middle) or RIGHT_ROOM left of x (right),
# which places short lines where the player expects them.
POSITIONS = {
    "top": (320, 8, "center", "CENTER"),
    "center": (320, 190, "center", "CENTER"),  # three lines end just above the crosshair (y 240)
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
RIGHT_ROOM = 120   # right places: the text starts this far from the anchor (about 25 characters)
CENTER_LEAD = 50   # middle places: the text starts this far left of the centre
JOIN_MENU = 'name "joingame_menu"'
# Hide a panel any server left, and tell this server the player has our files (modhud_util.HELLO).
ON_OPEN = '\n\t\tonOpen { setcvar mod_hud_on 0 ; exec "cmd modhud 1" }'

LINE_ITEM = """
		itemDef {{
			name "modhud_l{n}"
			type ITEM_TYPE_TEXT
			rect 0 {y} {w} {h}
			cvar "mod_hud_l{n}"
			textstyle ITEM_TEXTSTYLE_SHADOWED
			textscale .25
			textalignx 0
			textaligny 12
			forecolor 1 1 1 1
			visible 1
			decoration
			{tests}
		}}
"""


def pos_tests(pos):
    """Item tests for one place. Live (#26, 2026-10-27): an empty value never matches a list, so
    top, the place for an unset mod_hud_pos, hides on every other place (and on "off" or
    mod_hud_on 0); a hide test next to a show test breaks the item, so top uses hide tests only
    and every other place show tests only."""
    if pos == "top":
        others = " ; ".join('"{}"'.format(p) for p in POSITIONS if p != "top") + ' ; "off"'
        return ('cvarTest "mod_hud_pos"\n\t\t\thideCvar {{ {} }}\n'
                '\t\t\tcvarTest2 "mod_hud_on"\n\t\t\thideCvar2 {{ "0" }}').format(others)
    return ('cvarTest "mod_hud_pos"\n\t\t\tshowCvar {{ "{}" }}\n'
            '\t\t\tcvarTest2 "mod_hud_on"\n\t\t\tshowCvar2 {{ "1" }}').format(pos)


def expand(template, pos):
    x, y, align, wide = POSITIONS[pos]
    left, width = {"left": (x, ITEM_WIDTH), "center": (x - CENTER_LEAD, ITEM_WIDTH),
                   "right": (x - RIGHT_ROOM, RIGHT_ROOM)}[align]
    lines = "".join(LINE_ITEM.format(n=n, y=(n - 1) * LINE_STEP, w=width, h=LINE_STEP,
                                     tests=pos_tests(pos))
                    for n in (1, 2, 3))
    return (template
            .replace("@LINES@", lines)
            .replace("@NAME@", "modhud_" + pos)
            .replace("@WIDE@", "WIDESCREEN_" + wide)
            .replace("@X@", str(left))
            .replace("@Y@", str(y))
            .replace("@W@", str(width))
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


# --- glyphs -------------------------------------------------------------------
# Shapes are designed on a 256 em (QL's fallback font) and scaled to the font's em.
# TrueType winding: outer contours clockwise, holes counter-clockwise (y up).

def _twice_area(points):
    return sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(points, points[1:] + points[:1]))


def _wind(points, clockwise):
    return points[::-1] if (_twice_area(points) > 0) == clockwise else points


def trace(rgba):
    """Silhouette of an icon: [(points in image pixels, y down), is_hole] from alpha > 127."""
    import cv2
    import numpy as np

    mask = (np.array(rgba.convert("RGBA"))[:, :, 3] > 127).astype(np.uint8)
    contours, hierarchy = cv2.findContours(mask, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)
    out = []
    for i, contour in enumerate(contours):
        if cv2.contourArea(contour) < 4:
            continue
        points = cv2.approxPolyDP(contour, 0.75, True).reshape(-1, 2)
        if len(points) >= 3:
            out.append(([(int(x), int(y)) for x, y in points], hierarchy[0][i][3] != -1))
    return out


def _icon_shape(rgba, k):
    """Traced icon on the line: 64 px -> 200 units, bottom at -10, 10 units of side bearing."""
    traced = trace(rgba) if rgba is not None else []
    if not traced:
        return [], round(100 * k)
    xs = [x for points, _ in traced for x, _ in points]
    size = rgba.size[1]
    s = 200 * k / size
    contours = []
    for points, hole in traced:
        mapped = [((x - min(xs)) * s + 10 * k, (size - 1 - y) * s - 10 * k) for x, y in points]
        contours.append(_wind(mapped, clockwise=not hole))
    return contours, round((max(xs) - min(xs)) * s + 20 * k)


def _rect(x0, y0, x1, y1):
    return [(x0, y0), (x0, y1), (x1, y1), (x1, y0)]


def _arc(cx, cy, r, a0, a1, n=8):
    return [(cx + r * math.cos(math.radians(a0 + (a1 - a0) * i / n)),
             cy + r * math.sin(math.radians(a0 + (a1 - a0) * i / n))) for i in range(1, n)]


def _frame_shapes(k, asc, desc):
    """Box-drawing pieces filling the line height so neighbours join."""
    w = round(154 * k)
    cx, cy = w / 2, (asc + desc) / 2
    h = 14 * k  # heavy: 28 units thick
    vert = _rect(cx - h, desc, cx + h, asc)
    shapes = {
        "━": [_rect(0, cy - h, w, cy + h)],
        "┃": [vert],
        "┏": [_rect(cx - h, cy - h, w, cy + h), _rect(cx - h, desc, cx + h, cy + h)],
        "┓": [_rect(0, cy - h, cx + h, cy + h), _rect(cx - h, desc, cx + h, cy + h)],
        "┗": [_rect(cx - h, cy - h, w, cy + h), _rect(cx - h, cy - h, cx + h, asc)],
        "┛": [_rect(0, cy - h, cx + h, cy + h), _rect(cx - h, cy - h, cx + h, asc)],
        "┣": [vert, _rect(cx, cy - h, w, cy + h)],
        "┫": [vert, _rect(0, cy - h, cx, cy + h)],
    }
    t, r = 7 * k, 0.4 * w  # rounded corners: light, 14 units thick
    ccx, ccy = cx + r, cy - r
    corner = ([(w, cy + t), (cx + r, cy + t)] + _arc(ccx, ccy, r + t, 90, 180)
              + [(cx - t, cy - r), (cx - t, desc), (cx + t, desc), (cx + t, cy - r)]
              + _arc(ccx, ccy, r - t, 180, 90) + [(cx + r, cy - t), (w, cy - t)])
    flip_x = [(w - x, y) for x, y in corner]
    shapes["╭"] = [corner]
    shapes["╮"] = [flip_x]
    shapes["╰"] = [[(x, asc + desc - y) for x, y in corner]]
    shapes["╯"] = [[(x, asc + desc - y) for x, y in flip_x]]
    return {char: ([_wind(c, True) for c in contours], w) for char, contours in shapes.items()}


def _drawn_shapes(k):
    """{on}/{off} bars and {flag}: a pole and a cloth with a notch."""
    def scaled(points):
        return [(x * k, y * k) for x, y in points]

    outer = scaled([(10, 40), (60, 200), (220, 200), (170, 40)])
    inner = scaled([(40, 65), (155, 65), (190, 175), (75, 175)])
    pole = scaled(_rect(20, -10, 44, 200))
    cloth = scaled([(44, 90), (44, 200), (200, 200), (160, 145), (200, 90)])
    return {"▰": ([_wind(outer, True)], round(230 * k)),
            "▱": ([_wind(outer, True), _wind(inner, False)], round(230 * k)),
            modhud_util.TOKENS["flag"]: ([_wind(pole, True), _wind(cloth, True)], round(220 * k))}


def _glyph(contours):
    from fontTools.pens.ttGlyphPen import TTGlyphPen

    pen = TTGlyphPen(None)
    for points in contours:
        pen.moveTo((round(points[0][0]), round(points[0][1])))
        for x, y in points[1:]:
            pen.lineTo((round(x), round(y)))
        pen.closePath()
    return pen.glyph()


def add_glyphs(font_bytes, icons):
    """The font with a glyph for every token (icons: token -> RGBA image) and every frame piece."""
    from fontTools.ttLib import TTFont

    font = TTFont(io.BytesIO(font_bytes))
    k = font["head"].unitsPerEm / 256
    asc, desc = font["hhea"].ascent, font["hhea"].descent
    shapes = {char: _icon_shape(icons.get(token), k)
              for token, char in modhud_util.TOKENS.items() if token in ICON_SOURCES}
    shapes.update(_drawn_shapes(k))
    shapes.update(_frame_shapes(k, asc, desc))
    order = list(font.getGlyphOrder())
    glyf, hmtx = font["glyf"], font["hmtx"]
    for char, (contours, advance) in shapes.items():
        name = "modhud_{:04X}".format(ord(char))
        glyph = _glyph(contours)
        lsb = 0
        if glyph.numberOfContours:
            glyph.recalcBounds(glyf)
            lsb = glyph.xMin
        if name not in glyf.glyphs:
            order.append(name)
        glyf.glyphs[name] = glyph
        hmtx.metrics[name] = (advance, lsb)
        for table in font["cmap"].tables:
            if table.isUnicode():
                table.cmap[ord(char)] = name
    font.setGlyphOrder(order)
    glyf.glyphOrder = order
    out = io.BytesIO()
    font.save(out)
    return out.getvalue()


def render_sheet(font_bytes, path):
    """Every glyph with its token (or code point): the table people read, since browsers and
    editors draw Private Use Area characters as boxes."""
    from PIL import Image, ImageDraw, ImageFont

    big = ImageFont.truetype(io.BytesIO(font_bytes), 44)
    small = ImageFont.load_default()
    cells = [("{%s}" % token, char) for token, char in modhud_util.TOKENS.items()]
    cells += [("U+%04X" % ord(char), char) for char in FRAMES]
    cols, cw, ch = 8, 104, 84
    rows = (len(cells) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * cw, rows * ch), (32, 32, 36))
    draw = ImageDraw.Draw(sheet)
    for i, (label, char) in enumerate(cells):
        x, y = (i % cols) * cw, (i // cols) * ch
        draw.text((x + 14, y + 4), char, font=big, fill=(240, 240, 240))
        draw.text((x + 14, y + 64), label, font=small, fill=(250, 200, 80))
    sheet.save(path)


def _read_icons(pak):
    from PIL import Image

    names = set(pak.namelist())
    icons = {}
    for token, base in ICON_SOURCES.items():
        for ext in (".png", ".tga"):
            if base + ext in names:
                icons[token] = Image.open(io.BytesIO(pak.read(base + ext))).convert("RGBA")
                break
    return icons


def main(argv):
    if len(argv) != 2:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    out = Path(argv[1])
    with zipfile.ZipFile(argv[0]) as pak:
        stock = pak.read("ui/intro.menu").decode("latin-1")
        icons = _read_icons(pak)
        font = add_glyphs(pak.read(FONT), icons)
    menu = build_menu(stock, (HERE / "modhud.menu").read_text(encoding="utf-8"))
    out.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out / PK3, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("ui/intro.menu", menu.encode("latin-1"))
        z.writestr(FONT, font)
    render_sheet(font, out / "glyphs.png")
    tokens = "\n".join("{%-8s %s" % (name + "}", TOKEN_NAMES[name]) for name in modhud_util.TOKENS)
    readme = (HERE / "client-readme.txt").read_text(encoding="utf-8").replace("@TOKENS@", tokens)
    with zipfile.ZipFile(out / CLIENT_ZIP, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("baseq3/ui/intro.menu", menu.encode("latin-1"))
        z.writestr("baseq3/" + FONT, font)
        z.writestr(CLIENT_README, readme.replace("\n", "\r\n").encode("utf-8-sig"))
    missing = sorted(set(ICON_SOURCES) - set(icons))
    print("wrote {} ({} icons, missing: {})".format(out / PK3, len(icons), ", ".join(missing) or "none"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
