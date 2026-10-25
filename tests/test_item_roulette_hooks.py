"""item_roulette: the touch -> pickup wiring against fake engine objects."""
from types import SimpleNamespace

import pytest

from tests._minqlx_stub import bare_instance, import_plugin

pytestmark = pytest.mark.standalone

ir = import_plugin("item_roulette")
W = ir.WEAPON_FIELDS
RL = W.index("rl")
LG = W.index("lg")

ITEMS = {
    3: SimpleNamespace(classname="item_armor_body", pickup_name="Heavy Armor", quantity=100, gi_type=ir.IT_ARMOR, gi_tag=0),
    13: SimpleNamespace(classname="weapon_rocketlauncher", pickup_name="Rocket Launcher", quantity=10, gi_type=ir.IT_WEAPON, gi_tag=RL + 1),
    24: SimpleNamespace(classname="ammo_rockets", pickup_name="Rockets", quantity=5, gi_type=ir.IT_AMMO, gi_tag=RL + 1),
    29: SimpleNamespace(classname="item_quad", pickup_name="Quad Damage", quantity=30, gi_type=ir.IT_POWERUP, gi_tag=4),
}


class FakeEngine(SimpleNamespace):
    pass


def make_engine(now_ms=100000):
    return FakeEngine(
        Item=lambda index: ITEMS[index],
        Weapons=tuple,
        Powerups=tuple,
        level=SimpleNamespace(time=now_ms),
        EVENT_DISPATCHERS={"damage": object()},
        Priority=SimpleNamespace(LOW=3),
    )


def make_player(pid=1, health=100, armor=50, held=("g", "mg", "rl", "lg"), ammo=None, weapon=RL + 1):
    counts = ammo or {"mg": 50, "rl": 10, "lg": 100}
    return SimpleNamespace(
        id=pid,
        health=health,
        armor=armor,
        weapons=tuple(f in held for f in W),
        ammo=tuple(counts.get(f, 0) for f in W),
        powerups=(0, 0, 0, 0, 0, 0),
        weapon=weapon,
        prints=[],
        center_print=lambda msg, _p=None: None,
    )


def with_prints(player):
    player.center_print = player.prints.append
    return player


def entity(classname, modelindex):
    return SimpleNamespace(classname=classname, s=SimpleNamespace(modelindex=modelindex))


def make_plugin(monkeypatch, engine, cvars=None, take=True):
    monkeypatch.setattr(ir, "minqlx", engine)
    monkeypatch.setattr(ir.random, "random", lambda: 0.0 if take else 0.99)
    settings = {name: value for name, value in ir.CVAR_DEFAULTS}
    settings["qlx_itemRouletteEnabled"] = "1"
    settings.update(cvars or {})

    def get_cvar(name, return_type=str, default=None):
        value = settings.get(name, default)
        if return_type is bool:
            return value not in (None, "0", "", "false")
        return value

    hooks = []
    plugin = bare_instance(
        ir.item_roulette,
        _touch={}, _curses={}, _rule_cache={}, _damage_hooked=False, _next_drain=0,
        get_cvar=get_cvar,
        add_hook=lambda event, handler, priority=None: hooks.append(("add", event)),
        remove_hook=lambda event, handler, priority=None: hooks.append(("remove", event)),
        logger=SimpleNamespace(warning=lambda *a, **k: None),
    )
    plugin.hooks = hooks
    return plugin


def test_red_armor_take_subtracts_from_the_pre_pickup_armor(monkeypatch):
    plugin = make_plugin(monkeypatch, make_engine(), take=True)
    player = with_prints(make_player(armor=150))
    plugin.handle_item_touch(player, entity("item_armor_body", 3))
    player.armor = 200  # what the engine did
    plugin.handle_item_pickup(player, "item_armor_body")
    assert player.armor == 84
    assert player.prints == ["^1-66 ARMOR"]


def test_red_armor_give_at_stock_leaves_the_engine_result(monkeypatch):
    plugin = make_plugin(monkeypatch, make_engine(), take=False)
    player = with_prints(make_player(armor=150))
    plugin.handle_item_touch(player, entity("item_armor_body", 3))
    player.armor = 200
    plugin.handle_item_pickup(player, "item_armor_body")
    assert player.armor == 200
    assert player.prints == []


def test_disabled_plugin_records_nothing_on_touch(monkeypatch):
    plugin = make_plugin(monkeypatch, make_engine(), cvars={"qlx_itemRouletteEnabled": "0"})
    plugin.handle_item_touch(make_player(), entity("item_armor_body", 3))
    assert plugin._touch == {}


def test_weapon_take_removes_it_and_switches_to_the_best_other_weapon(monkeypatch):
    plugin = make_plugin(monkeypatch, make_engine(), take=True)
    player = with_prints(make_player(weapon=RL + 1))
    plugin.handle_item_touch(player, entity("weapon_rocketlauncher", 13))
    player.ammo = tuple(a + (10 if i == RL else 0) for i, a in enumerate(player.ammo))  # engine added ammo
    plugin.handle_item_pickup(player, "weapon_rocketlauncher")
    assert player.weapons[RL] is False and player.weapons[LG] is True
    assert player.ammo[RL] == 10
    assert player.weapon == LG + 1
    assert player.prints == ["^1LOST ROCKET LAUNCHER"]


def test_ammo_take_uses_the_default_rule(monkeypatch):
    plugin = make_plugin(monkeypatch, make_engine(), take=True)
    player = with_prints(make_player())
    plugin.handle_item_touch(player, entity("ammo_rockets", 24))
    plugin.handle_item_pickup(player, "ammo_rockets")
    assert player.ammo[RL] == 4
    assert player.prints == ["^1-6 ROCKETS"]


def test_quad_take_denies_the_powerup_and_curses_the_player(monkeypatch):
    engine = make_engine(now_ms=100000)
    plugin = make_plugin(monkeypatch, engine, take=True)
    player = with_prints(make_player(pid=2))
    plugin.handle_item_touch(player, entity("item_quad", 29))
    player.powerups = (30000, 0, 0, 0, 0, 0)  # what the engine did
    plugin.handle_item_pickup(player, "item_quad")
    assert player.powerups == (0, 0, 0, 0, 0, 0)
    assert plugin._curses[2] == {"kind": "quad", "until": 130000, "factor": 0.5}
    assert ("add", "damage") in plugin.hooks
    assert player.prints == ["^1CURSED QUAD: WEAK DAMAGE 30s"]


def test_cursed_quad_hit_refunds_the_victim(monkeypatch):
    engine = make_engine(now_ms=100000)
    plugin = make_plugin(monkeypatch, engine, take=True)
    plugin._curses[2] = {"kind": "quad", "until": 130000, "factor": 0.5}
    attacker = make_player(pid=2)
    victim = make_player(pid=3, health=70, armor=40)  # after a 90 damage hit
    plugin.handle_damage(victim, attacker, 90, 0, 7)
    assert (victim.armor, victim.health) == (70, 85)


def test_expired_curse_is_dropped_and_damage_hook_removed(monkeypatch):
    engine = make_engine(now_ms=200000)
    plugin = make_plugin(monkeypatch, engine, take=True)
    plugin._curses[2] = {"kind": "quad", "until": 130000, "factor": 0.5}
    plugin._damage_hooked = True
    plugin.handle_frame()
    assert plugin._curses == {}
    assert ("remove", "damage") in plugin.hooks
