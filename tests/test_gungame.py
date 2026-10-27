"""gungame: ladder parsing, step logic, texts."""
import pytest

from tests._minqlx_stub import import_plugin

pytestmark = pytest.mark.standalone

gg = import_plugin("gungame")
L3 = [("rl", 2), ("lg", 1), ("g", 1)]


# --- ladder / channels ---------------------------------------------------

def test_parse_ladder_default():
    assert gg.parse_ladder(gg.DEFAULT_LADDER) == [
        ("rl", 2), ("rg", 2), ("lg", 2), ("pg", 2), ("sg", 2), ("gl", 2), ("mg", 2), ("g", 1)]


def test_parse_ladder_accepts_hmg_bfg_and_extra_spaces():
    assert gg.parse_ladder("  hmg:3   bfg:1 ") == [("hmg", 3), ("bfg", 1)]


@pytest.mark.parametrize("bad", ["", "   ", "xx:2", "rl", "rl:", "rl:0", "rl:-1", "rl:a", "hands:1"])
def test_parse_ladder_rejects(bad):
    with pytest.raises(ValueError):
        gg.parse_ladder(bad)


def test_parse_channels():
    assert gg.parse_channels("print") == {"print"}
    assert gg.parse_channels("print,center") == {"print", "center"}
    assert gg.parse_channels(" center , junk ") == {"center"}
    assert gg.parse_channels("off") == frozenset()
    assert gg.parse_channels("") == frozenset()


# --- steps ---------------------------------------------------------------

def test_advance_frag_counts_then_steps_up():
    assert gg.advance((0, 0), L3, "frag") == ((0, 1), "none")
    assert gg.advance((0, 1), L3, "frag") == ((1, 0), "up")


def test_advance_frag_on_last_step_wins():
    assert gg.advance((2, 0), L3, "frag") == ((2, 1), "win")


def test_advance_demote_floor_and_reset():
    assert gg.advance((1, 0), L3, "demote") == ((0, 0), "down")
    assert gg.advance((0, 1), L3, "demote") == ((0, 0), "down")
    assert gg.advance((0, 0), L3, "demote") == ((0, 0), "none")


def test_advance_skip_jumps_a_whole_step():
    assert gg.advance((0, 1), L3, "skip") == ((1, 0), "up")
    assert gg.advance((1, 0), L3, "skip") == ((2, 0), "up")
    assert gg.advance((2, 0), L3, "skip") == ((2, 1), "win")


def test_advance_back_takes_one_frag():
    assert gg.advance((0, 1), L3, "back") == ((0, 0), "back")
    assert gg.advance((1, 0), L3, "back") == ((0, 1), "down")  # into the previous step, one frag short
    assert gg.advance((0, 0), L3, "back") == ((0, 0), "none")


def test_parse_ms():
    assert gg.parse_ms("500") == 500
    assert gg.parse_ms(" 0 ") == 0
    assert gg.parse_ms("-5") == 0
    assert gg.parse_ms("abc") == 0
    assert gg.parse_ms(None) == 0


def test_loadout_and_weapons():
    assert gg.loadout(L3, 1) == "lg"
    held = gg.loadout_weapons("lg")
    assert len(held) == len(gg.WEAPON_FIELDS)
    assert [f for f, h in zip(gg.WEAPON_FIELDS, held) if h] == ["g", "lg"]
    assert [f for f, h in zip(gg.WEAPON_FIELDS, gg.loadout_weapons("g")) if h] == ["g"]


def test_is_blocked_item():
    assert gg.is_blocked_item("weapon_rocketlauncher")
    assert gg.is_blocked_item("item_quad")
    assert not gg.is_blocked_item("item_armor_body")
    assert not gg.is_blocked_item("item_health_mega")
    assert not gg.is_blocked_item("ammo_rockets")


def test_pick_leader_keeps_current_on_tie_and_needs_step_one():
    assert gg.pick_leader({1: (0, 1), 2: (0, 0)}, None) is None
    assert gg.pick_leader({1: (2, 0), 2: (1, 1)}, None) == 1
    assert gg.pick_leader({1: (2, 0), 2: (2, 1)}, 1) == 1
    assert gg.pick_leader({1: (2, 0), 2: (3, 0)}, 1) == 2


# --- texts ---------------------------------------------------------------

def test_texts():
    assert gg.step_text(L3, (1, 0)) == "Step 2/3: ^3LG^7 (0/1)"
    assert gg.demote_text(L3, (0, 0)) == "Down to step 1/3: ^3RL^7"
    assert gg.leader_text("Bob", 2, 3) == "^3Bob^7 leads: step 2/3"
    assert gg.last_step_text("Bob") == "^3Bob^7: last step!"
    assert gg.win_text("Bob") == "^3Bob^7 wins Gun Game!"


# --- HUD panel -----------------------------------------------------------

S12 = ""  # small "1/2"


def test_hud_line_next_weapon_and_progress():
    # Next weapon in yellow, frags towards it in small digits.
    assert gg.hud_line(L3, (0, 1)) == "^3{lg}^7 " + S12
    assert gg.hud_line(L3, (1, 0)) == "^3{g}^7 "
    # Last step: no next weapon, progress only.
    assert gg.hud_line(L3, (2, 0)) == ""


def test_hud_ladder_line_marks_done_current_and_left():
    # Icons carry their own side bearings: no spaces, so nine of them fit the right places.
    assert gg.hud_ladder(L3, 0) == "^7┃^3{rl}^7┃{lg}{g}"
    assert gg.hud_ladder(L3, 1) == "^2{rl}^7┃^3{lg}^7┃{g}"
    assert gg.hud_ladder(L3, 2) == "^2{rl}{lg}^7┃^3{g}^7┃"
    default = gg.parse_ladder(gg.DEFAULT_LADDER)
    assert len(mu_fields(default)["mod_hud_l2"].encode("utf-8")) < 80


def mu_fields(ladder):
    return gg.hud_fields(ladder, (4, 1))


def test_hud_fields_are_the_shared_panel():
    assert gg.hud_fields(L3, (0, 1)) == {
        "mod_hud_on": "1", "mod_hud_l1": "^3^7 " + S12,
        # The shared helper parts touching icons with a hair space (U+200A).
        "mod_hud_l2": "^7┃ ^3 ^7┃  ", "mod_hud_l3": ""}
