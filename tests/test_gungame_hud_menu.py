"""gungame HUD: menu template and the intro.menu builder."""
import importlib.util
import re
import zipfile

import pytest

from tests._minqlx_stub import REPO_ROOT

pytestmark = pytest.mark.standalone

_spec = importlib.util.spec_from_file_location("build_intro_menu", REPO_ROOT / "hud" / "build_intro_menu.py")
bim = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bim)

TEMPLATE = (REPO_ROOT / "hud" / "gungame.menu").read_text(encoding="utf-8")
STOCK = '#include "ui/menudef.h"\n\n{\n\tmenuDef {\n\t\tname "joingame_menu"\n\t}\n}\n'


def menu_blocks(text):
    """name -> text of each of our menuDefs, up to the next one."""
    parts = re.split(r'(?=\tmenuDef \{\n\t\tname "gungame_)', text)
    return {re.search(r'name "(gungame_\w+)"', p).group(1): p for p in parts if 'name "gungame_' in p}


def test_build_keeps_stock_prefix_and_closing_brace():
    out = bim.build(STOCK, TEMPLATE)
    cut = STOCK.rindex("}")
    assert out.startswith(STOCK[:cut])
    assert out.rstrip().endswith("}")


POSITIONS = ["top", "bottom", "left", "right", "center", "topleft", "topright", "bottomleft", "bottomright"]


def test_nine_position_copies_with_next_icon_and_progress():
    blocks = menu_blocks(bim.build(STOCK, TEMPLATE))
    assert sorted(blocks) == sorted("gungame_" + p for p in POSITIONS)
    for text in blocks.values():
        assert text.count('cvarTest2 "mod_gg_next"') == 14
        assert text.count('cvar "mod_gg_prog"') == 1
        for gone in ("mod_gg_w", "mod_gg_step", "mod_gg_lead"):
            assert gone not in text
        # A filled item tints its background by backcolor (0 0 0 0 by default = invisible).
        assert text.count("backcolor 1 1 1 1") == 14


def test_position_tests():
    blocks = menu_blocks(bim.build(STOCK, TEMPLATE))
    # Live: hideCvar next to showCvar2 broke the top copy; stock never mixes them, so all tests are show tests.
    assert not any("hideCvar" in text for text in blocks.values())
    for pos in POSITIONS:
        want = 'showCvar { "" ; "top" }' if pos == "top" else 'showCvar { "%s" }' % pos
        text = blocks["gungame_" + pos]
        assert text.count('cvarTest "mod_gg_pos"') == text.count("itemDef {") == text.count(want)


def test_panels_stay_on_the_virtual_screen():
    w, h = bim.PANEL_SIZE
    for x, y, _ in bim.POSITIONS.values():
        assert 0 <= x and x + w <= 640 and 0 <= y and y + h <= 480


def test_no_placeholders_left():
    assert "@" not in bim.build(STOCK, TEMPLATE)


def test_icons_cover_every_ladder_weapon():
    gg_keys = {"g", "mg", "sg", "gl", "rl", "lg", "rg", "pg", "bfg", "gh", "ng", "pl", "cg", "hmg"}
    assert set(bim.WEAPON_ICONS) == gg_keys


def test_cli_reads_pk3_and_writes_ui_intro_menu(tmp_path):
    pk3 = tmp_path / "pak00.pk3"
    with zipfile.ZipFile(pk3, "w") as z:
        z.writestr("ui/intro.menu", STOCK)
    out = tmp_path / "out"
    bim.main([str(pk3), str(out)])
    assert (out / "ui" / "intro.menu").read_text(encoding="utf-8") == bim.build(STOCK, TEMPLATE)
