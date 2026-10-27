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


def test_three_position_copies_with_all_icons():
    blocks = menu_blocks(bim.build(STOCK, TEMPLATE))
    assert sorted(blocks) == ["gungame_bottom", "gungame_left", "gungame_top"]
    for text in blocks.values():
        assert text.count('cvarTest2 "mod_gg_w"') == 14
        assert text.count('cvarTest2 "mod_gg_next"') == 14
        assert text.count('cvar "mod_gg_step"') == 1 and text.count('cvar "mod_gg_lead"') == 1
        # A filled item tints its background by backcolor (0 0 0 0 by default = invisible).
        assert text.count("backcolor 1 1 1 1") == 28


def test_position_tests():
    blocks = menu_blocks(bim.build(STOCK, TEMPLATE))
    # Live: hideCvar next to showCvar2 broke the top copy; stock never mixes them, so all tests are show tests.
    assert 'showCvar { "" ; "top" }' in blocks["gungame_top"]
    assert not any("hideCvar" in text for text in blocks.values())
    assert 'showCvar { "left" }' in blocks["gungame_left"]
    assert 'showCvar { "bottom" }' in blocks["gungame_bottom"]
    for text in blocks.values():
        items = text.count("itemDef {")
        assert text.count('cvarTest "mod_gg_pos"') == items


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
