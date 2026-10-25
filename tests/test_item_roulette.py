"""item_roulette: the pure decisions behind "a pickup gives or takes"."""
import pytest

from tests._minqlx_stub import import_plugin

pytestmark = pytest.mark.standalone

ir = import_plugin("item_roulette")

W = ir.WEAPON_FIELDS
RL = W.index("rl")
LG = W.index("lg")
G = W.index("g")


def weapons(*held):
    return tuple(f in held for f in W)


def ammo(**counts):
    return tuple(counts.get(f, 0) for f in W)


# --- rules ---------------------------------------------------------------

def test_parse_rules_give_slash_take():
    assert ir.parse_rules("ra=100/66 ga=*/33") == {"ra": (100, 66), "ga": (None, 33)}


def test_parse_rules_single_number_is_give_only():
    assert ir.parse_rules("sg=10 lg=*") == {"sg": (10, None), "lg": (None, None)}


def test_parse_rules_ignores_garbage_tokens():
    assert ir.parse_rules("ra=100/66 junk x=/ y=a/b  ") == {"ra": (100, 66)}


def test_rule_for_falls_back_to_default():
    rules = ir.parse_rules("default=*/6 lg=*/66")
    assert ir.rule_for(rules, "lg") == (None, 66)
    assert ir.rule_for(rules, "rl") == (None, 6)
    assert ir.rule_for({}, "rl") == (None, None)


def test_parse_factors():
    assert ir.parse_factors("quad=0.5 bs=1.5 regen=1") == {"quad": 0.5, "bs": 1.5, "regen": 1.0}
    assert ir.parse_factors("quad=abc bs=") == {}


def test_roll_take_uses_percent_chance():
    assert ir.roll_take(50, 0.49) is True
    assert ir.roll_take(50, 0.50) is False
    assert ir.roll_take(0, 0.0) is False
    assert ir.roll_take(100, 0.999) is True


# --- armor / health / ammo amounts ----------------------------------------

def test_give_stock_amount_leaves_the_engine_result():
    assert ir.plan_amount(pre=50, stock=100, give=100, take=66, outcome="give", cap=200) is None
    assert ir.plan_amount(pre=50, stock=100, give=None, take=66, outcome="give", cap=200) is None


def test_give_custom_amount_adds_with_cap():
    assert ir.plan_amount(pre=50, stock=100, give=120, take=66, outcome="give", cap=200) == 170
    assert ir.plan_amount(pre=150, stock=100, give=120, take=66, outcome="give", cap=200) == 200


def test_take_subtracts_down_to_floor():
    assert ir.plan_amount(pre=100, stock=100, give=100, take=66, outcome="take", cap=200) == 34
    assert ir.plan_amount(pre=20, stock=100, give=100, take=66, outcome="take", cap=200) == 0
    assert ir.plan_amount(pre=20, stock=25, give=25, take=66, outcome="take", cap=100, floor=1) == 1


def test_take_without_amount_just_denies_the_gain():
    assert ir.plan_amount(pre=70, stock=100, give=100, take=None, outcome="take", cap=200) == 70


def test_health_cap_200_for_bubbles_and_mega_only():
    assert ir.health_cap("item_health_small") == 200
    assert ir.health_cap("item_health_mega") == 200
    assert ir.health_cap("item_health") == 100
    assert ir.health_cap("item_health_large") == 100


def test_plan_ammo_take_only_touches_that_weapon():
    pre = ammo(rl=25, lg=100)
    out = ir.plan_ammo(pre, LG, give=None, take=66, outcome="take")
    assert out == ammo(rl=25, lg=34)


def test_plan_ammo_take_floors_at_zero():
    assert ir.plan_ammo(ammo(rl=3), RL, give=None, take=6, outcome="take") == ammo(rl=0)


def test_plan_ammo_give_stock_is_left_to_the_engine():
    assert ir.plan_ammo(ammo(rl=3), RL, give=None, take=6, outcome="give") is None


def test_plan_ammo_give_custom_caps_at_200():
    assert ir.plan_ammo(ammo(rl=190), RL, give=50, take=6, outcome="give") == ammo(rl=200)


# --- weapons ---------------------------------------------------------------

def test_weapon_take_removes_a_weapon_the_player_had():
    new_w, new_a, had = ir.plan_weapon(weapons("g", "mg", "rl"), ammo(mg=50, rl=25), RL, give=None, outcome="take")
    assert new_w == weapons("g", "mg")
    assert new_a == ammo(mg=50, rl=25)
    assert had is True


def test_weapon_take_without_the_weapon_only_denies_it():
    new_w, new_a, had = ir.plan_weapon(weapons("g", "mg"), ammo(mg=50), RL, give=None, outcome="take")
    assert new_w == weapons("g", "mg")
    assert new_a == ammo(mg=50)
    assert had is False


def test_weapon_give_stock_leaves_the_engine_result():
    assert ir.plan_weapon(weapons("g"), ammo(), RL, give=None, outcome="give") == (None, None, False)


def test_weapon_give_custom_ammo_sets_pre_plus_give():
    new_w, new_a, had = ir.plan_weapon(weapons("g", "rl"), ammo(rl=5), RL, give=30, outcome="give")
    assert new_w is None
    assert new_a == ammo(rl=35)
    assert had is True


def test_best_weapon_prefers_by_order_and_needs_ammo():
    held = weapons("g", "mg", "lg", "rl")
    assert ir.best_weapon(held, ammo(mg=50, lg=0, rl=10), exclude=RL) == W.index("mg")
    assert ir.best_weapon(held, ammo(mg=50, lg=20, rl=10), exclude=RL) == LG
    assert ir.best_weapon(weapons("g", "rl"), ammo(rl=10), exclude=RL) == G


# --- curses ------------------------------------------------------------------

def test_curse_kind_by_classname():
    assert ir.curse_kind("item_quad") == "quad"
    assert ir.curse_kind("item_enviro") == "battlesuit"
    assert ir.curse_kind("item_invis") == "invisibility"
    assert ir.curse_kind("item_invisibility") == "invisibility"
    assert ir.curse_kind("item_regen") == "regeneration"
    assert ir.curse_kind("item_haste") == "haste"
    assert ir.curse_kind("item_armor_body") is None


def test_quad_refund_splits_like_the_engine_when_armor_remains():
    assert ir.quad_refund(damage=90, factor=0.5, armor_after=40) == (30, 15)


def test_quad_refund_goes_to_health_when_armor_is_gone():
    assert ir.quad_refund(damage=90, factor=0.5, armor_after=0) == (0, 45)


def test_quad_refund_nothing_at_factor_one_or_more():
    assert ir.quad_refund(damage=90, factor=1.0, armor_after=40) == (0, 0)
    assert ir.quad_refund(damage=90, factor=3.0, armor_after=40) == (0, 0)


def test_battlesuit_extra_eats_armor_first_then_health():
    assert ir.battlesuit_extra(damage=100, factor=1.5, armor=20, health=80) == (0, 50)
    assert ir.battlesuit_extra(damage=20, factor=1.5, armor=50, health=80) == (40, 80)


def test_battlesuit_extra_never_kills():
    assert ir.battlesuit_extra(damage=200, factor=2.0, armor=0, health=30) == (0, 1)
    assert ir.battlesuit_extra(damage=200, factor=1.0, armor=0, health=30) == (0, 30)
