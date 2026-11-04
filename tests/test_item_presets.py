"""item_presets: helpers, draft edits, apply and Redis commands against fakes."""
import json
from types import SimpleNamespace

import pytest

from tests._minqlx_stub import bare_instance, import_plugin

pytestmark = pytest.mark.standalone

ip = import_plugin("item_presets")
USAGE = "usage"


ITEM_LIST = (None, "item_armor_body", "item_armor_combat", "item_health_mega",
             "weapon_rocketlauncher", "weapon_lightning", "item_invis", "ammo_rockets")


def ent(number, classname, origin, wait=0, spawnflags=0, modelindex=None):
    if modelindex is None:
        modelindex = ITEM_LIST.index(classname) if classname in ITEM_LIST else 0
    return SimpleNamespace(classname=classname, wait=wait, spawnflags=spawnflags,
                           s=SimpleNamespace(number=number, origin=tuple(origin), modelindex=modelindex))


class Engine:
    """Live item entities; spawn_entity drops the item 20 units to the floor.
    CS_ITEMS holds the map's own items, like SaveRegisteredItems leaves it."""

    CS_ITEMS = 27

    def __init__(self, items=()):
        self.items_live = {e.s.number: e for e in items}
        self.next_number = 200
        self.commands = []
        self.refuse = set()
        self.pending = set()
        self.Return = SimpleNamespace(USAGE=USAGE)
        self.cs = {self.CS_ITEMS: self.map_bits(items)}

    @staticmethod
    def map_bits(items):
        bits = ["0"] * len(ITEM_LIST)
        for e in items:
            bits[e.s.modelindex] = "1"
        return "".join(bits)

    def configstring(self, index, cached=True):
        return self.cs.get(index, "")

    def set_configstring(self, index, value):
        self.cs[index] = value

    def entities(self, inuse=True, etype=None, start=0, stop=1024):
        """Fresh spawns stay out of an etype filter until finish_spawning()."""
        return [e for n, e in self.items_live.items()
                if start <= n < stop and (etype is None or n not in self.pending)]

    def finish_spawning(self):
        """FinishSpawningItem: the item gets its bg_itemlist index."""
        for n in self.pending:
            e = self.items_live.get(n)
            if e is not None:
                e.s.modelindex = ITEM_LIST.index(e.classname) if e.classname in ITEM_LIST else 0
        self.pending.clear()

    def items(self):
        return [SimpleNamespace(classname=c) for c in ITEM_LIST]

    def spawn_entity(self, classname, keys):
        if classname in self.refuse:
            return None
        x, y, z = keys["origin"]
        e = ent(self.next_number, classname, (x, y, z - 20), keys.get("wait", 0), keys.get("spawnflags", 0),
                modelindex=0)
        e.keys = dict(keys)
        self.items_live[e.s.number] = e
        self.pending.add(e.s.number)
        self.next_number += 1
        return e

    def remove_entity(self, number):
        self.items_live.pop(int(number))

    def console_command(self, cmd):
        self.commands.append(cmd)

    def restart(self, map_items):
        """map_restart: every entity freed, the map's items back, numbers reused."""
        self.items_live = {e.s.number: e for e in map_items}
        self.next_number = max([200] + [n + 1 for n in self.items_live])
        self.cs[self.CS_ITEMS] = self.map_bits(map_items)


class FakeRedis:
    def __init__(self):
        self.kv, self.h = {}, {}

    def get(self, k):
        return self.kv.get(k)

    def set(self, k, v):
        self.kv[k] = v

    def delete(self, k):
        self.kv.pop(k, None)

    def hget(self, k, f):
        return self.h.get(k, {}).get(f)

    def hset(self, k, f, v):
        self.h.setdefault(k, {})[f] = v

    def hdel(self, k, f):
        return 1 if self.h.get(k, {}).pop(f, None) is not None else 0

    def hkeys(self, k):
        return list(self.h.get(k, {}))


class FakePlayer:
    def __init__(self, pos=(0, 0, 24), pid=1):
        self.id = pid
        self.position = tuple(pos)
        self.tells = []

    def tell(self, text):
        self.tells.append(text)


def map_items():
    return [
        ent(10, "item_health_mega", (0, 0, 16)),
        ent(11, "item_armor_combat", (500, 0, 16), wait=30, spawnflags=4),
        ent(12, "weapon_rocketlauncher", (1000, 0, 16)),
    ]


def make(monkeypatch, state="warmup", enabled="1", engine=None, db=None):
    engine = engine or Engine(map_items())
    monkeypatch.setattr(ip, "minqlx", engine)
    cvars = {"qlx_itemPresetsEnabled": enabled, "qlx_itemEditRadius": "64", "net_port": "27960"}

    def get_cvar(name, return_type=str, default=None):
        value = cvars.get(name, default)
        if return_type is bool:
            return value not in (None, "0", "")
        return value

    delays = []
    plugin = bare_instance(
        ip.item_presets,
        _map="bloodrun", _draft=ip.empty_draft(), _active=None, _ours={}, _picked={}, _known=None,
        get_cvar=get_cvar, game=SimpleNamespace(state=state, map="bloodrun"),
        db=db if db is not None else FakeRedis(),
        delay=lambda s, f, *a: delays.append((s, f)),
        logger=SimpleNamespace(warning=lambda *a, **k: None, info=lambda *a, **k: None),
    )
    plugin.engine, plugin.cvars, plugin.delays = engine, cvars, delays
    return plugin


def live(plugin):
    return sorted((e.classname, e.s.origin) for e in plugin.engine.items_live.values())


# --- helpers ---

def test_resolve_type_short_names_classnames_and_aliases():
    known = {"weapon_rocketlauncher", "item_invisibility", "ammo_rockets"}
    assert ip.resolve_type("RL", known) == "weapon_rocketlauncher"
    assert ip.resolve_type("invis", known) == "item_invisibility"
    assert ip.resolve_type("ammo_rockets", known) == "ammo_rockets"
    assert ip.resolve_type("ra", known) is None
    assert ip.resolve_type("nope", known) is None


def test_resolve_type_ammo_short_names():
    pairs = {
        "bullets": "ammo_bullets", "shells": "ammo_shells", "grenades": "ammo_grenades",
        "rockets": "ammo_rockets", "lightning": "ammo_lightning", "slugs": "ammo_slugs",
        "cells": "ammo_cells", "bfgammo": "ammo_bfg", "nails": "ammo_nails",
        "mines": "ammo_mines", "belt": "ammo_belt",
    }
    known = set(pairs.values())
    for short, classname in pairs.items():
        assert ip.resolve_type(short, known) == classname


def test_nearest_respects_radius():
    items = map_items()
    assert ip.nearest(items, (10, 0, 16), 64).s.number == 10
    assert ip.nearest(items, (250, 0, 16), 64) is None


def test_preset_round_trip():
    draft = {"removed": [{"cn": "item_health_mega", "o": [0.0, 0.0, 16.0]}],
             "added": [{"cn": "item_armor_body", "o": [1.0, 2.0, 3.0], "k": {"wait": 30}}]}
    raw = ip.dump_preset("bloodrun", "x", draft)
    assert json.loads(raw)["map"] == "bloodrun"
    assert ip.parse_preset(raw) == draft


def test_parse_preset_rejects_bad_origin():
    with pytest.raises((ValueError, KeyError, TypeError)):
        ip.parse_preset('{"added": [{"cn": "item_quad", "o": [1, 2]}]}')


# --- edits ---

def test_add_spawns_at_player_and_records(monkeypatch):
    p = make(monkeypatch)
    player = FakePlayer((300, 300, 40))
    p.cmd_item(player, ["!item", "add", "ra"], None)
    assert p._draft["added"] == [{"cn": "item_armor_body", "o": [300.0, 300.0, 40.0]}]
    assert ("item_armor_body", (300.0, 300.0, 20.0)) in live(p)


def test_position_method_is_supported(monkeypatch):
    p = make(monkeypatch)
    player = FakePlayer()
    player.position = lambda: (5, 6, 7)
    p.cmd_item(player, ["!item", "add", "rl"], None)
    assert p._draft["added"][0]["o"] == [5.0, 6.0, 7.0]


def test_remove_map_item_is_recorded_and_freed(monkeypatch):
    p = make(monkeypatch)
    p.cmd_item(FakePlayer((10, 0, 24)), ["!item", "remove"], None)
    assert p._draft["removed"] == [{"cn": "item_health_mega", "o": [0.0, 0.0, 16.0]}]
    assert 10 not in p.engine.items_live


def test_remove_added_item_drops_its_entry(monkeypatch):
    p = make(monkeypatch)
    p.cmd_item(FakePlayer((300, 300, 40)), ["!item", "add", "ra"], None)
    p.engine.finish_spawning()
    p.cmd_item(FakePlayer((300, 300, 40)), ["!item", "remove"], None)
    assert p._draft == ip.empty_draft()
    assert p._ours == {}


def test_replace_keeps_the_spot(monkeypatch):
    p = make(monkeypatch)
    p.cmd_item(FakePlayer((500, 0, 24)), ["!item", "replace", "ra"], None)
    assert p._draft["removed"] == [{"cn": "item_armor_combat", "o": [500.0, 0.0, 16.0]}]
    assert p._draft["added"] == [{"cn": "item_armor_body", "o": [500.0, 0.0, 16.0]}]


def test_move_map_item_copies_keys(monkeypatch):
    p = make(monkeypatch)
    player = FakePlayer((500, 0, 24))
    p.cmd_item(player, ["!item", "move"], None)
    assert p._picked == {1: 11}
    player.position = (800, 800, 40)
    p.cmd_item(player, ["!item", "move"], None)
    assert p._draft["removed"] == [{"cn": "item_armor_combat", "o": [500.0, 0.0, 16.0]}]
    assert p._draft["added"] == [{"cn": "item_armor_combat", "o": [800.0, 800.0, 40.0],
                                  "k": {"wait": 30, "spawnflags": 4}}]
    spawned = [e for e in p.engine.items_live.values() if e.s.number >= 200][0]
    assert spawned.keys["wait"] == 30


def test_move_added_item_rewrites_its_entry(monkeypatch):
    p = make(monkeypatch)
    player = FakePlayer((300, 300, 40))
    p.cmd_item(player, ["!item", "add", "lg"], None)
    p.engine.finish_spawning()
    p.cmd_item(player, ["!item", "move"], None)
    player.position = (-300, -300, 40)
    p.cmd_item(player, ["!item", "move"], None)
    assert p._draft == {"removed": [], "added": [{"cn": "weapon_lightning", "o": [-300.0, -300.0, 40.0]}]}


def test_refused_spawn_is_reported_and_not_recorded(monkeypatch):
    p = make(monkeypatch)
    p.engine.refuse.add("item_armor_body")
    player = FakePlayer((300, 300, 40))
    p.cmd_item(player, ["!item", "add", "ra"], None)
    assert p._draft["added"] == []
    assert "refused" in player.tells[-1]


@pytest.mark.parametrize("state,enabled,why", [
    ("in_progress", "1", "warmup"),
    ("warmup", "0", "off"),
])
def test_edits_refused_outside_warmup_or_when_off(monkeypatch, state, enabled, why):
    p = make(monkeypatch, state=state, enabled=enabled)
    player = FakePlayer((10, 0, 24))
    p.cmd_item(player, ["!item", "remove"], None)
    assert 10 in p.engine.items_live
    assert why in player.tells[-1]


def test_unknown_type_lists_short_names(monkeypatch):
    p = make(monkeypatch)
    player = FakePlayer()
    p.cmd_item(player, ["!item", "add", "zzz"], None)
    assert "unknown item" in player.tells[-1] and "rl" in player.tells[-1]


def test_nothing_in_radius(monkeypatch):
    p = make(monkeypatch)
    player = FakePlayer((250, 250, 24))
    p.cmd_item(player, ["!item", "remove"], None)
    assert "no item within 64" in player.tells[-1]


def test_list_works_in_a_match(monkeypatch):
    p = make(monkeypatch, state="in_progress")
    p._draft["added"].append({"cn": "item_quad", "o": [1.0, 2.0, 3.0]})
    player = FakePlayer()
    p.cmd_item(player, ["!item", "list"], None)
    assert any("+ item_quad @ 1 2 3" in t for t in player.tells)


# --- apply ---

def test_apply_after_restart_is_idempotent(monkeypatch):
    p = make(monkeypatch)
    p.cmd_item(FakePlayer((10, 0, 24)), ["!item", "remove"], None)
    p.cmd_item(FakePlayer((300, 300, 40)), ["!item", "add", "ra"], None)
    expected = live(p)

    p.engine.restart(map_items())
    p.delays.clear()
    p.handle_new_game()      # next_frame is immediate in the stub
    assert live(p) == expected
    assert [s for s, _ in p.delays] == [ip.RESCAN_S]
    p._apply()               # the 0.5 s rescan changes nothing
    assert live(p) == expected


def test_apply_respawns_when_a_reused_number_is_another_item(monkeypatch):
    p = make(monkeypatch)
    p.cmd_item(FakePlayer((300, 300, 40)), ["!item", "add", "ra"], None)
    # restart frees our entity 200; the number comes back as a different item
    p.engine.restart(map_items() + [ent(200, "item_quad", (9000, 0, 0))])
    p._apply()
    assert ("item_armor_body", (300.0, 300.0, 20.0)) in live(p)
    assert ("item_quad", (9000, 0, 0)) in live(p)


def test_two_applies_before_the_item_finishes_spawning_do_not_duplicate(monkeypatch):
    p = make(monkeypatch)
    p._draft["added"].append({"cn": "item_quad", "o": [1.0, 1.0, 40.0]})
    p._apply()   # new_game pass
    p._apply()   # active-preset fetch lands a frame later, item not ET_ITEM yet
    assert [e.classname for e in p.engine.items_live.values()].count("item_quad") == 1


def cs_bit(p, classname):
    bits = p.engine.cs[p.engine.CS_ITEMS]
    i = ITEM_LIST.index(classname)
    return bits[i] if i < len(bits) else "0"


def test_added_item_type_is_registered_for_clients(monkeypatch):
    # Clients load an item's model only if its CS_ITEMS bit is set; the map
    # sets bits for its own items only (axis model / grey icon otherwise).
    p = make(monkeypatch)
    assert cs_bit(p, "ammo_rockets") == "0"
    p.cmd_item(FakePlayer((300, 300, 40)), ["!item", "add", "ammo_rockets"], None)
    assert [s for s, _ in p.delays] == [ip.RESCAN_S]
    p.engine.finish_spawning()
    p.delays[0][1]()
    assert cs_bit(p, "ammo_rockets") == "1"
    assert cs_bit(p, "item_health_mega") == "1"   # the map's own bits stay
    assert cs_bit(p, "item_armor_body") == "0"


def test_registration_comes_back_after_a_restart(monkeypatch):
    p = make(monkeypatch)
    p.cmd_item(FakePlayer((500, 0, 24)), ["!item", "replace", "ra"], None)
    p.engine.restart(map_items())    # G_InitGame rewrites CS_ITEMS from the map
    assert cs_bit(p, "item_armor_body") == "0"
    p.delays.clear()
    p.handle_new_game()
    p.engine.finish_spawning()
    p.delays[0][1]()
    assert cs_bit(p, "item_armor_body") == "1"


def test_disabled_does_not_apply(monkeypatch):
    p = make(monkeypatch, enabled="0")
    p._draft["removed"].append({"cn": "item_health_mega", "o": [0.0, 0.0, 16.0]})
    p.handle_new_game()
    assert 10 in p.engine.items_live


def test_removed_match_uses_tolerance_and_classname(monkeypatch):
    p = make(monkeypatch)
    p._draft["removed"] = [{"cn": "item_health_mega", "o": [5.0, 0.0, 16.0]},
                           {"cn": "item_quad", "o": [500.0, 0.0, 16.0]}]
    p._apply()
    assert 10 not in p.engine.items_live and 11 in p.engine.items_live


# --- presets ---

def test_save_writes_preset_and_active(monkeypatch):
    p = make(monkeypatch)
    p.cmd_item(FakePlayer((10, 0, 24)), ["!item", "remove"], None)
    player = FakePlayer()
    p.cmd_preset(player, ["!preset", "save", "no-mh"], None)
    stored = ip.parse_preset(p.db.hget("minqlx:item_presets:bloodrun", "no-mh"))
    assert stored["removed"][0]["cn"] == "item_health_mega"
    assert json.loads(p.db.get("minqlx:item_presets:active:27960")) == {"map": "bloodrun", "name": "no-mh"}
    assert p._active == "no-mh"


def test_load_sets_draft_and_restarts(monkeypatch):
    p = make(monkeypatch)
    p.db.hset("minqlx:item_presets:bloodrun", "x",
              ip.dump_preset("bloodrun", "x", {"removed": [], "added": [{"cn": "item_quad", "o": [1.0, 1.0, 1.0]}]}))
    p.cmd_preset(FakePlayer(), ["!preset", "load", "x"], None)
    assert p._active == "x" and p._draft["added"][0]["cn"] == "item_quad"
    assert p.engine.commands == ["map_restart"]


def test_load_missing_preset(monkeypatch):
    p = make(monkeypatch)
    player = FakePlayer()
    p.cmd_preset(player, ["!preset", "load", "nope"], None)
    assert "no preset" in player.tells[-1] and p.engine.commands == []


def test_off_clears_and_restarts(monkeypatch):
    p = make(monkeypatch)
    p.db.set("minqlx:item_presets:active:27960", '{"map": "bloodrun", "name": "x"}')
    p._active, p._draft["added"] = "x", [{"cn": "item_quad", "o": [1.0, 1.0, 1.0]}]
    p.cmd_preset(FakePlayer(), ["!preset", "off"], None)
    assert p._active is None and p._draft == ip.empty_draft()
    assert p.db.get("minqlx:item_presets:active:27960") is None
    assert p.engine.commands == ["map_restart"]


def test_delete_active_preset(monkeypatch):
    p = make(monkeypatch)
    p.db.hset("minqlx:item_presets:bloodrun", "x", ip.dump_preset("bloodrun", "x", ip.empty_draft()))
    p.db.set("minqlx:item_presets:active:27960", '{"map": "bloodrun", "name": "x"}')
    p._active = "x"
    p.cmd_preset(FakePlayer(), ["!preset", "delete", "x"], None)
    assert p.db.hkeys("minqlx:item_presets:bloodrun") == []
    assert p.db.get("minqlx:item_presets:active:27960") is None and p._active is None


def test_list_marks_active(monkeypatch):
    p = make(monkeypatch, state="in_progress")
    for name in ("b", "a"):
        p.db.hset("minqlx:item_presets:bloodrun", name, "{}")
    p._active = "b"
    player = FakePlayer()
    p.cmd_preset(player, ["!preset", "list"], None)
    assert "a, ^3b^7 (active)" in player.tells[-1]


def test_bad_name_refused(monkeypatch):
    p = make(monkeypatch)
    player = FakePlayer()
    p.cmd_preset(player, ["!preset", "save", "a b;c"], None)
    assert p.db.h == {}


def test_map_load_restores_active_preset_of_that_map_only(monkeypatch):
    p = make(monkeypatch)
    p.db.hset("minqlx:item_presets:bloodrun", "x",
              ip.dump_preset("bloodrun", "x", {"removed": [{"cn": "item_health_mega", "o": [0.0, 0.0, 16.0]}],
                                               "added": []}))
    p.db.set("minqlx:item_presets:active:27960", '{"map": "bloodrun", "name": "x"}')
    p.handle_map("campgrounds", "duel")
    assert p._active is None and 10 in p.engine.items_live
    p.handle_map("BloodRun", "duel")
    assert p._active == "x" and 10 not in p.engine.items_live


def test_redis_error_is_reported(monkeypatch):
    class Broken(FakeRedis):
        def hset(self, *a):
            raise ConnectionError("down")

    p = make(monkeypatch, db=Broken())
    player = FakePlayer()
    p.cmd_preset(player, ["!preset", "save", "x"], None)
    assert "save failed" in player.tells[-1]
