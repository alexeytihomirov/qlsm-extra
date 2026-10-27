"""modhud: ui/intro.menu builder (nine 3-line panels and the Join Match auto-clear)."""
import importlib.util
import re

import pytest

from tests._minqlx_stub import REPO_ROOT

pytestmark = pytest.mark.standalone

_spec = importlib.util.spec_from_file_location("build_modhud", REPO_ROOT / "hud" / "build_modhud.py")
bm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bm)

TEMPLATE = (REPO_ROOT / "hud" / "modhud.menu").read_text(encoding="utf-8")
STOCK = ('#include "ui/menudef.h"\n\n{\n\tmenuDef {\n\t\tname "joingame_menu"\n\t\tvisible 0\n\t}\n'
         '\tmenuDef {\n\t\tname "other"\n\t\tonOpen { show x }\n\t}\n}\n')
POSITIONS = ["top", "center", "bottom", "left", "topleft", "bottomleft", "right", "topright", "bottomright"]


def menu_blocks(text):
    parts = re.split(r'(?=\tmenuDef \{\n\t\tname "modhud_)', text)
    return {re.search(r'name "(modhud_\w+)"', p).group(1): p for p in parts if 'name "modhud_' in p}


def items(block):
    return re.findall(r"itemDef \{.*?\n\t\t\}", block, re.S)


def test_keeps_stock_prefix_and_closing_brace():
    out = bm.build_menu(STOCK, TEMPLATE)
    assert out.startswith('#include "ui/menudef.h"\n\n{\n\tmenuDef {\n\t\tname "joingame_menu"')
    assert out.rstrip().endswith("}")
    assert 'name "other"\n\t\tonOpen { show x }' in out


def test_onopen_clear_added_to_join_menu_once():
    out = bm.build_menu(STOCK, TEMPLATE)
    assert out.count('name "joingame_menu"\n\t\tonOpen { setcvar mod_hud_on 0 }') == 1
    assert out.count("setcvar mod_hud_on 0") == 1


@pytest.mark.parametrize("stock", [
    '{\n\tmenuDef {\n\t\tname "other"\n\t}\n}\n',
    '{\n\tmenuDef {\n\t\tname "joingame_menu"\n\t\tonOpen { show x }\n\t}\n}\n',
])
def test_onopen_requires_joingame_menu(stock):
    with pytest.raises(ValueError):
        bm.build_menu(stock, TEMPLATE)


def test_nine_panels_with_three_lines():
    blocks = menu_blocks(bm.build_menu(STOCK, TEMPLATE))
    assert sorted(blocks) == sorted("modhud_" + p for p in POSITIONS)
    for text in blocks.values():
        its = items(text)
        assert len(its) == 3
        for n, item in enumerate(its, 1):
            assert 'cvar "mod_hud_l%d"' % n in item
            assert 'cvarTest2 "mod_hud_on"' in item and 'showCvar2 { "1" }' in item
            assert "textscale .25" in item


def test_position_tests_are_show_tests_only():
    blocks = menu_blocks(bm.build_menu(STOCK, TEMPLATE))
    assert not any("hideCvar" in text for text in blocks.values())
    for pos in POSITIONS:
        want = 'showCvar { "" ; "top" }' if pos == "top" else 'showCvar { "%s" }' % pos
        text = blocks["modhud_" + pos]
        assert text.count('cvarTest "mod_hud_pos"') == text.count(want) == 3


def menu_rect(block):
    return [int(v) for v in re.search(r"\n\t\trect (\d+) (\d+) (\d+) (\d+)", block).groups()]


def test_alignment_and_anchors():
    blocks = menu_blocks(bm.build_menu(STOCK, TEMPLATE))
    for pos, (x, y, align, wide) in bm.POSITIONS.items():
        block = blocks["modhud_" + pos]
        mx, my, mw, mh = menu_rect(block)
        assert my == y and mw == bm.ITEM_WIDTH and mh == 3 * bm.LINE_STEP
        assert "widescreen WIDESCREEN_" + wide in block
        want = {"left": x, "center": x - bm.ITEM_WIDTH // 2, "right": x - bm.ITEM_WIDTH}[align]
        assert mx == want
        # Live (#26, 2026-10-27): a cvar text item with textalign CENTER or RIGHT is not drawn
        # at all; `align` is ignored. Text always starts at the block's left edge.
        assert "textalign " not in block and "align ITEM" not in block
        assert block.count("textalignx 0\n") == 3
        assert 0 <= mx and mx + mw <= 640 and 0 <= my and my + mh <= 480


def test_spec_anchor_table():
    assert bm.POSITIONS == {
        "top": (320, 8, "center", "CENTER"), "center": (320, 150, "center", "CENTER"),
        "bottom": (320, 300, "center", "CENTER"), "left": (8, 200, "left", "LEFT"),
        "topleft": (8, 8, "left", "LEFT"), "bottomleft": (8, 300, "left", "LEFT"),
        "right": (632, 200, "right", "RIGHT"), "topright": (632, 8, "right", "RIGHT"),
        "bottomright": (632, 300, "right", "RIGHT"),
    }
    assert (bm.LINE_STEP, bm.ITEM_WIDTH) == (14, 300)
