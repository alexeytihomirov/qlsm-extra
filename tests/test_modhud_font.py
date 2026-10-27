"""modhud: glyphs added to the fallback font, icon tracing and the glyph sheet."""
import importlib.util
import io
import zipfile

import pytest

from tests._minqlx_stub import REPO_ROOT, import_plugin

pytestmark = pytest.mark.standalone

pytest.importorskip("fontTools")
pytest.importorskip("cv2")
Image = pytest.importorskip("PIL.Image")

from fontTools.fontBuilder import FontBuilder  # noqa: E402
from fontTools.pens.ttGlyphPen import TTGlyphPen  # noqa: E402
from fontTools.ttLib import TTFont  # noqa: E402

_spec = importlib.util.spec_from_file_location("build_modhud", REPO_ROOT / "hud" / "build_modhud.py")
bm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bm)
mu = import_plugin("modhud_util")


def base_font(em=256):
    k = em // 256
    fb = FontBuilder(em, isTTF=True)
    fb.setupGlyphOrder([".notdef", "A"])
    fb.setupCharacterMap({0x41: "A"})
    pen = TTGlyphPen(None)
    for x, y in [(10, 0), (10, 180), (140, 180), (140, 0)]:
        (pen.lineTo if pen.points else pen.moveTo)((x * k, y * k))
    pen.closePath()
    fb.setupGlyf({".notdef": TTGlyphPen(None).glyph(), "A": pen.glyph()})
    fb.setupHorizontalMetrics({".notdef": (128 * k, 0), "A": (150 * k, 10 * k)})
    fb.setupHorizontalHeader(ascent=267 * k, descent=-68 * k)
    fb.setupOS2()
    fb.setupPost()
    out = io.BytesIO()
    fb.save(out)
    return out.getvalue()


def square_with_hole():
    im = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    for x in range(8, 56):
        for y in range(8, 56):
            if not (24 <= x < 40 and 24 <= y < 40):
                im.putpixel((x, y), (200, 0, 0, 255))
    return im


def glyph_for(font, cp):
    return font["glyf"][font.getBestCmap()[cp]]


def test_trace_keeps_hole_and_empty_is_empty():
    contours = bm.trace(square_with_hole())
    assert len(contours) == 2
    assert bm.trace(Image.new("RGBA", (64, 64), (0, 0, 0, 0))) == []


def test_every_token_and_frame_gets_a_glyph():
    font = TTFont(io.BytesIO(bm.add_glyphs(base_font(), {"rl": square_with_hole()})))
    cmap = font.getBestCmap()
    for char in list(mu.TOKENS.values()) + bm.FRAMES:
        assert ord(char) in cmap
    rl = glyph_for(font, 0xE004)
    rl.recalcBounds(font["glyf"])
    assert rl.numberOfContours == 2
    assert rl.yMin >= -40 and rl.yMax <= 230 and rl.yMax > 175
    missing = glyph_for(font, 0xE000)  # no icon given for {g}
    assert missing.numberOfContours == 0 and font["hmtx"][cmap[0xE000]][0] > 0


def test_icon_hole_wound_against_outer():
    font = TTFont(io.BytesIO(bm.add_glyphs(base_font(), {"rl": square_with_hole()})))
    rl = glyph_for(font, 0xE004)
    coords, ends, _ = rl.getCoordinates(font["glyf"])
    areas, start = [], 0
    for end in ends:
        pts = list(coords[start:end + 1])
        areas.append(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1])))
        start = end + 1
    assert sorted(a > 0 for a in areas) == [False, True]  # outer clockwise, hole counter-clockwise


def test_stock_glyph_untouched_and_scaled_em():
    font = TTFont(io.BytesIO(bm.add_glyphs(base_font(2048), {"rl": square_with_hole()})))
    a = glyph_for(font, 0x41)
    assert a.getCoordinates(font["glyf"])[0].array.tolist() == [10 * 8, 0, 10 * 8, 1440, 1120, 1440, 1120, 0]
    rl = glyph_for(font, 0xE004)
    rl.recalcBounds(font["glyf"])
    assert -40 * 8 <= rl.yMin and rl.yMax <= 230 * 8 and rl.yMax > 175 * 8


def small_square():
    im = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    for x in range(26, 38):
        for y in range(28, 36):
            im.putpixel((x, y), (200, 0, 0, 255))
    return im


def test_icons_get_one_height_whatever_their_size_in_the_image():
    # Live (#27): icons "jumped" in size, the stock images fill their 64 px differently.
    font = TTFont(io.BytesIO(bm.add_glyphs(base_font(), {"rl": square_with_hole(), "rg": small_square()})))
    heights = []
    for cp in (0xE004, 0xE006):
        g = glyph_for(font, cp)
        g.recalcBounds(font["glyf"])
        heights.append((g.yMin, g.yMax))
    assert heights[0][1] - heights[0][0] == pytest.approx(heights[1][1] - heights[1][0], abs=40)
    assert heights[0][0] == pytest.approx(bm.ICON_BOTTOM, abs=2)


def test_flag_is_drawn_without_an_icon():
    font = TTFont(io.BytesIO(bm.add_glyphs(base_font(), {})))
    assert glyph_for(font, 0xE01B).numberOfContours == 2
    assert "flag" not in bm.ICON_SOURCES


def digit_font():
    """2048 em, every digit and "/" a 1000-high box."""
    fb = FontBuilder(2048, isTTF=True)
    names = [".notdef"] + ["d%d" % i for i in range(11)]
    fb.setupGlyphOrder(names)
    fb.setupCharacterMap({ord(c): "d%d" % i for i, c in enumerate("0123456789/")})
    glyphs = {".notdef": TTGlyphPen(None).glyph()}
    for name in names[1:]:
        pen = TTGlyphPen(None)
        for x, y in [(100, 0), (100, 1000), (900, 1000), (900, 0)]:
            (pen.lineTo if pen.points else pen.moveTo)((x, y))
        pen.closePath()
        glyphs[name] = pen.glyph()
    fb.setupGlyf(glyphs)
    fb.setupHorizontalMetrics({n: (1000, 100) for n in names})
    fb.setupHorizontalHeader(ascent=2100, descent=-500)
    fb.setupOS2()
    fb.setupPost()
    out = io.BytesIO()
    fb.save(out)
    return out.getvalue()


def test_small_digits_are_70_percent_of_the_source():
    font = TTFont(io.BytesIO(bm.add_glyphs(base_font(), {}, digit_font())))
    for char in mu.SMALL.values():
        g = glyph_for(font, ord(char))
        g.recalcBounds(font["glyf"])
        assert (g.yMin, g.yMax) == (0, 88)  # 1000 * 0.7 * 256 / 2048, rounded
        assert font["hmtx"][font.getBestCmap()[ord(char)]][0] == 88


def test_frames_span_the_line_height():
    font = TTFont(io.BytesIO(bm.add_glyphs(base_font(), {})))
    bar = glyph_for(font, 0x2503)
    bar.recalcBounds(font["glyf"])
    assert (bar.yMin, bar.yMax) == (-68, 267)


def test_sheet_and_pk3(tmp_path):
    font = bm.add_glyphs(base_font(), {"rl": square_with_hole()})
    bm.render_sheet(font, tmp_path / "glyphs.png")
    assert Image.open(tmp_path / "glyphs.png").size[0] > 200

    pak = tmp_path / "pak00.pk3"
    with zipfile.ZipFile(pak, "w") as z:
        z.writestr("ui/intro.menu", '{\n\tmenuDef {\n\t\tname "joingame_menu"\n\t}\n}\n')
        z.writestr(bm.FONT, base_font())
        buf = io.BytesIO()
        square_with_hole().save(buf, "PNG")
        z.writestr("icons/iconw_rocket.png", buf.getvalue())
    assert bm.main([str(pak), str(tmp_path / "out")]) == 0
    with zipfile.ZipFile(tmp_path / "out" / "zz_modhud.pk3") as z:
        assert sorted(z.namelist()) == sorted(["ui/intro.menu", bm.FONT])
        assert "modhud_topright" in z.read("ui/intro.menu").decode("utf-8")
    assert (tmp_path / "out" / "glyphs.png").is_file()
    # The players' archive: unpack into <QL>/<steamid>/ and the files land where QL reads them.
    with zipfile.ZipFile(tmp_path / "out" / bm.CLIENT_ZIP) as z:
        names = sorted(z.namelist())
        assert names == sorted(["baseq3/ui/intro.menu", "baseq3/" + bm.FONT, bm.CLIENT_README])
        readme = z.read(bm.CLIENT_README).decode("utf-8")
    # Players' part only: install, positions, binds; no admin commands, no token list.
    for needle in ("mod_hud_pos", "topright", "bind F7", "UNINSTALL"):
        assert needle in readme
    for needle in ("!hud", "{rl}", "@"):
        assert needle not in readme
