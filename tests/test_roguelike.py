"""roguelike: hooks, events and rooms against fake players and a fake npc_core."""
import logging
import random
from collections import namedtuple
from types import SimpleNamespace

import pytest

from tests._minqlx_stub import bare_instance, import_plugin

pytestmark = pytest.mark.standalone

rl = import_plugin("roguelike")
rl_rules = rl.rl_rules
STOP_ALL = rl.minqlx.Return.STOP_ALL
Pos = namedtuple("Pos", "x y z")


def entity(name, origin):
    return SimpleNamespace(keys={"targetname": name, "classname": "info_notnull"}, origin=origin)


def spike_entities():
    ents = [entity("rl_hub_start", (384, 640, 24))]
    ents += [entity("rl_move1_start", (1408, 256, 216)), entity("rl_move1_finish", (2944, 256, 216)),
             entity("rl_move1_pit", (2240, 64, 24))]
    ents += [entity("rl_move1_door_%d" % i, (x, y, 216))
             for i, (x, y) in enumerate([(3040, 160), (3040, 352), (3152, 160), (3152, 352)])]
    ents += [entity("rl_dodge1_start", (512, 1792, 24)), entity("rl_dodge1_turret_0", (64, 1344, 184)),
             entity("rl_dodge1_turret_1", (960, 2240, 184))]
    ents += [entity("rl_dodge1_door_%d" % i, (x, 2240, 24)) for i, x in enumerate([320, 448, 576, 704])]
    ents += [entity("rl_arena1_start", (2176, 1408, 24))]
    ents += [entity("rl_arena1_mob_%d" % i, (x, y, 24))
             for i, (x, y) in enumerate([(1664, 2432), (2688, 2432), (1664, 1920), (2688, 1920)])]
    ents += [entity("rl_arena1_door_%d" % i, (x, 2496, 24)) for i, x in enumerate([1984, 2112, 2240, 2368])]
    ents.append(SimpleNamespace(keys={"classname": "info_player_deathmatch"}, origin=(384, 160, 24)))
    return ents


class FakeCore:
    BASE_HP = 100000
    CLIP_HITS_PLAYERS = 0x2000001

    def __init__(self):
        self.spawned = []
        self.removed = []
        self.answers = {}
        self.fired = []
        self.chased = []
        self.taken = {}
        self.plums = []
        self.missiles_removed = []
        self.missile_ticks = []
        self.reset = 0

    def spawn_pair(self, origin, parts, hp_limit, now, solid=True, hull_size=(16, 32), frames=None, fps=0):
        n = len(self.spawned)
        npc = SimpleNamespace(hull=n if solid else None, visuals=[1000 + n, 2000 + n], hp_limit=hp_limit,
                              pos=origin, vel=(0, 0, 0), last_shot=0.0, parts=parts, solid=solid)
        self.spawned.append(npc)
        return npc

    def remove(self, npc):
        self.removed.append(npc)

    def chase(self, npc, target, speed, now, turn=None):
        self.chased.append((npc, target))

    def tick_chaser(self, npc, now):
        answer = self.answers.get(id(npc), "alive")
        if isinstance(answer, Exception):
            raise answer
        return answer

    def lead(self, muzzle, target, vel, speed):
        return target

    def speed_of(self, weapon):
        return 900.0

    def fire(self, muzzle, target, weapon, damage, splash, radius, owner, clipmask, visual=None, speed=None):
        self.fired.append((weapon, damage, owner))
        return 500 + len(self.fired)

    def missile_gone(self, num):
        return False

    def remove_missile(self, num):
        self.missiles_removed.append(num)

    def tick_missiles(self, npcs, now, only=None):
        self.missile_ticks.append(set(only) if only is not None else None)

    def clear_missiles(self):
        pass

    def aim_visual(self, npc, part, target):
        pass

    def reset_cache(self):
        self.reset += 1

    def damage_taken(self, npc):
        return self.taken.get(id(npc), 0)

    def damage_plum(self, pos, amount, client, now):
        self.plums.append((amount, client))

    def model_index(self, path):
        return 1

    def preload_weapons(self):
        pass


def player(cid=1, team="red", alive=True, pos=(384.0, 640.0, 24.0)):
    p = SimpleNamespace(id=cid, name="p%d" % cid, team=team, is_alive=alive, position=Pos(*pos),
                        velocity=(0, 0, 0), weapons=None, weapon=None, health=100,
                        told=[], centered=[], puts=[])
    p.tell = p.told.append
    p.center_print = p.centered.append
    p.put = p.puts.append
    return p


@pytest.fixture
def core(monkeypatch):
    fake = FakeCore()
    monkeypatch.setattr(rl, "npc_core", fake)
    monkeypatch.setattr(rl.minqlx, "Weapons", tuple, raising=False)
    monkeypatch.setattr(rl.minqlx, "Vector3", tuple, raising=False)
    return fake


def make_plugin(players, markers=True, seed=1):
    sent = []
    by_id = {p.id: p for p in players}
    p = bare_instance(rl.roguelike, logger=logging.getLogger("rl-test"), msg=sent.append,
                      center_print=sent.append, players=lambda: list(by_id.values()), sent=sent,
                      player=lambda cid: by_id.get(cid), get_cvar=lambda name: "rl_spike", by_id=by_id,
                      _load_markers=lambda mapname: None)
    p._init_state()
    p._rng = random.Random(seed)
    if markers:
        p._apply_markers("rl_spike", spike_entities())
    return p


def enter(plugin, pl, room, now=0.0):
    plugin._apply(pl.id, plugin._world.force(pl.id, room, now), now)


def kill_all(core, plugin, room):
    for npc in plugin._rooms[room].mobs:
        core.answers[id(npc)] = "dead"


def test_frame_noop_without_layout(core):
    pl = player()
    plugin = make_plugin([pl], markers=False)
    plugin._tick(1.0)
    assert core.spawned == [] and pl.puts == [] and plugin._world is None


def test_markers_without_rooms_switch_the_mode_off(core):
    plugin = make_plugin([player()], markers=False)
    plugin._apply_markers("rl_spike", [entity("rl_hub_start", (0, 0, 24))])
    assert plugin._world is None


def test_hub_pad_starts_run_and_teleports(core):
    pl = player()
    plugin = make_plugin([pl])
    plugin._tick(1.0)
    run = plugin._world.run(1)
    assert run is not None
    start = plugin._world.layout.rooms[run.room].start
    assert tuple(pl.position) == start
    assert plugin._rooms[run.room].cid == 1


def test_enter_sets_kit_of_room_type(core):
    pl = player()
    plugin = make_plugin([pl])
    enter(plugin, pl, "arena1")
    fields = rl.WEAPON_FIELDS
    assert [f for f, on in zip(fields, pl.weapons) if on] == ["g", "mg", "sg"]
    assert pl.weapon == fields.index("mg") + 1 and pl.health == 100
    enter(plugin, pl, "dodge1", 1.0)
    assert [f for f, on in zip(fields, pl.weapons) if on] == ["g"]


def test_dodge_room_builds_two_turrets_and_they_fire(core):
    pl = player()
    plugin = make_plugin([pl])
    enter(plugin, pl, "dodge1")
    turrets = plugin._rooms["dodge1"].turrets
    assert len(turrets) == 2 and not any(t.solid for t in turrets)
    pl.position = Pos(512.0, 1792.0, 24.0)
    plugin._tick(5.0)
    assert [f[0] for f in core.fired] == ["rl", "rl"]
    assert core.fired[0][1] == rl_rules.TURRET.attack.damage


def _arena_with_mobs(core, plugin, pl, now=0.0):
    enter(plugin, pl, "arena1", now)
    pl.position = Pos(2176.0, 1408.0, 24.0)
    t = now
    while len(plugin._rooms["arena1"].mobs) < 2:
        t += 0.05
        plugin._tick(t)
    return t


def test_arena_mobs_chase_the_room_player(core):
    pl = player()
    plugin = make_plugin([pl])
    _arena_with_mobs(core, plugin, pl)
    mob = plugin._rooms["arena1"].mobs[0]
    assert mob.solid and mob.pos[2] == 24 + rl.MOB_LIFT
    assert any(n is mob and target[:2] == (2176.0, 1408.0) for n, target in core.chased)


def test_bite_fires_pg_from_next_to_the_player(core):
    pl = player()
    plugin = make_plugin([pl])
    t = _arena_with_mobs(core, plugin, pl)
    mob = plugin._rooms["arena1"].mobs[0]
    mob.pos = (2196.0, 1408.0, 28.0)  # 20 u away
    core.fired.clear()
    plugin._tick(t + 2.0)
    assert ("pg", rl_rules.ATTACKS["bite"].damage, mob.hull) in core.fired


def test_disconnect_mid_room_removes_entities_and_frees_room(core):
    pl = player()
    plugin = make_plugin([pl])
    _arena_with_mobs(core, plugin, pl)
    mobs = list(plugin._rooms["arena1"].mobs)
    assert len(mobs) == 2
    plugin.handle_player_disconnect(pl, "quit")
    assert all(m in core.removed for m in mobs)
    assert plugin._world.occupied() == {} and "arena1" not in plugin._rooms


def test_spectate_mid_room_frees_room(core):
    pl = player()
    plugin = make_plugin([pl])
    _arena_with_mobs(core, plugin, pl)
    plugin.handle_team_switch(pl, "red", "spectator")
    assert plugin._world.occupied() == {} and plugin._rooms == {}


def test_spawn_after_death_teleports_to_room_start(core):
    pl = player()
    plugin = make_plugin([pl])
    enter(plugin, pl, "arena1")
    plugin.handle_death(pl, None, {})
    pl.position = Pos(384.0, 160.0, 24.0)
    plugin.handle_player_spawn(pl)
    assert tuple(pl.position) == plugin._world.layout.rooms["arena1"].start
    assert pl.weapon == rl.WEAPON_FIELDS.index("mg") + 1


def test_death_restarts_the_room_clean(core):
    pl = player()
    plugin = make_plugin([pl])
    _arena_with_mobs(core, plugin, pl)
    mobs = list(plugin._rooms["arena1"].mobs)
    plugin.handle_death(pl, None, {})
    assert all(m in core.removed for m in mobs)
    assert plugin._rooms["arena1"].mobs == [] and plugin._world.run(1).lives == 2


def test_spawn_after_last_life_stays_in_hub(core):
    pl = player()
    plugin = make_plugin([pl])
    enter(plugin, pl, "arena1")
    for _ in range(3):
        plugin.handle_death(pl, None, {})
    assert plugin._world.run(1) is None and plugin._rooms == {}
    hub_spawn = Pos(384.0, 160.0, 24.0)
    pl.position = hub_spawn
    plugin.handle_player_spawn(pl)
    assert pl.position == hub_spawn
    assert [f for f, on in zip(rl.WEAPON_FIELDS, pl.weapons) if on] == ["g"]
    assert any("dead" in s or "lives" in s.lower() for s in plugin.sent)


def test_map_change_drops_state_without_removing_entities(core):
    pl = player()
    plugin = make_plugin([pl])
    _arena_with_mobs(core, plugin, pl)
    plugin.handle_map("rl_spike", "tdm")
    assert core.removed == [] and plugin._rooms == {} and core.reset == 1
    plugin._apply_markers("rl_spike", spike_entities())
    assert plugin._world.run(1) is None


def test_new_game_drops_runs(core):
    pl = player()
    plugin = make_plugin([pl])
    enter(plugin, pl, "arena1")
    plugin.handle_new_game()
    assert core.removed == [] and plugin._rooms == {} and plugin._world.run(1) is None


def test_unload_removes_entities_once(core):
    pl = player()
    plugin = make_plugin([pl])
    _arena_with_mobs(core, plugin, pl)
    plugin._tick(100.0)  # hub pad model exists by now
    live = [n for n in core.spawned if n not in core.removed]
    plugin.handle_unload("roguelike")
    assert sorted(map(id, core.removed)) == sorted(map(id, live))
    plugin.handle_unload("roguelike")
    plugin._tick(200.0)
    assert len(core.removed) == len(live)


def test_bad_room_tick_only_resets_that_room(core):
    a, b = player(1), player(2)
    plugin = make_plugin([a, b])
    _arena_with_mobs(core, plugin, a)
    enter(plugin, b, "dodge1")
    b.position = Pos(512.0, 1792.0, 24.0)
    before = vars(plugin._world.run(2)).copy()
    core.answers[id(plugin._rooms["arena1"].mobs[0])] = RuntimeError("boom")
    plugin._tick(50.0)
    assert plugin._world.run(1) is None and "arena1" not in plugin._rooms
    assert tuple(a.position) == (384.0, 160.0, 24.0)
    assert any("error" in s.lower() for s in a.told)
    after = vars(plugin._world.run(2))
    assert after["room"] == before["room"] == "dodge1" and after["lives"] == before["lives"]
    assert "dodge1" in plugin._rooms


def test_stuck_mob_counts_as_killed(core):
    pl = player()
    plugin = make_plugin([pl])
    t = _arena_with_mobs(core, plugin, pl)
    mob = plugin._rooms["arena1"].mobs[0]
    core.answers[id(mob)] = "stuck"
    plugin._tick(t + 0.05)
    assert mob in core.removed and mob not in plugin._rooms["arena1"].mobs


def test_arena_clears_and_shows_exit_pads(core):
    pl = player()
    plugin = make_plugin([pl])
    enter(plugin, pl, "arena1")
    pl.position = Pos(2176.0, 1408.0, 24.0)
    t = 0.0
    for _ in range(2000):
        t += 0.05
        plugin._tick(t)
        for npc in plugin._rooms["arena1"].mobs:
            core.answers[id(npc)] = "dead"
        if plugin._world.run(1).phase == "cleared":
            break
    room = plugin._rooms["arena1"]
    assert plugin._world.run(1).phase == "cleared" and room.mobs == []
    assert len(room.pads) == len(plugin._world.run(1).offers) == 2


def test_damage_numbers_only_for_room_player(core):
    a, b = player(1), player(2)
    plugin = make_plugin([a, b])
    t = _arena_with_mobs(core, plugin, a)
    enter(plugin, b, "dodge1")
    b.position = Pos(512.0, 1792.0, 24.0)
    core.taken[id(plugin._rooms["arena1"].mobs[0])] = 40
    plugin._tick(t + 1.0)
    assert core.plums == [(40, 1)]


def test_missiles_ticked_per_room(core):
    pl = player()
    plugin = make_plugin([pl])
    enter(plugin, pl, "dodge1")
    pl.position = Pos(512.0, 1792.0, 24.0)
    plugin._tick(5.0)
    plugin._tick(5.1)
    assert core.missile_ticks[-1] == plugin._rooms["dodge1"].missiles and len(core.missile_ticks[-1]) == 2


def test_full_is_told_at_most_every_5s(core):
    players = [player(i) for i in (1, 2, 3, 4)]
    plugin = make_plugin(players)
    for p, room in zip(players, ("move1", "dodge1", "arena1")):
        enter(plugin, p, room)
    hub = players[3]
    plugin._tick(1.0)
    plugin._tick(2.0)
    plugin._tick(6.5)
    assert len(hub.told) == 2


def test_join_goes_red_blue_refused(core):
    pl = player(team="spectator")
    plugin = make_plugin([pl])
    plugin.handle_player_loaded(pl)
    assert pl.puts == ["red"]
    assert plugin.handle_team_switch_attempt(pl, "spectator", "blue", None) == STOP_ALL


def test_hooks_return_at_once_without_layout(core):
    pl = player()
    plugin = make_plugin([pl], markers=False)
    plugin.handle_death(pl, None, {})
    plugin.handle_player_spawn(pl)
    plugin.handle_player_disconnect(pl, "quit")
    plugin.handle_team_switch(pl, "red", "spectator")
    assert pl.weapons is None and core.spawned == []


def test_cmd_rl_and_rlroom(core):
    pl = player()
    plugin = make_plugin([pl])
    replies = []
    ch = SimpleNamespace(reply=replies.append)
    plugin.cmd_rlroom(pl, ["!rlroom", "dodge1"], ch)
    assert plugin._world.run(1).room == "dodge1"
    plugin.cmd_rl(pl, ["!rl"], ch)
    assert "dodge1" in replies[-1] and "3" in replies[-1]
    off = make_plugin([pl], markers=False)
    off.cmd_rl(pl, ["!rl"], ch)
    assert "off" in replies[-1]


def test_unload_sends_players_in_rooms_to_the_hub(core):
    pl = player()
    plugin = make_plugin([pl])
    enter(plugin, pl, "arena1")
    plugin.handle_unload("roguelike")
    assert tuple(pl.position) == (384.0, 160.0, 24.0)
    assert [f for f, on in zip(rl.WEAPON_FIELDS, pl.weapons) if on] == ["g"]


def test_one_players_error_does_not_stop_other_rooms(core, monkeypatch):
    a, b = player(1), player(2)
    plugin = make_plugin([a, b])
    enter(plugin, a, "arena1")
    a.position = Pos(2176.0, 1408.0, 24.0)
    enter(plugin, b, "dodge1")
    b.position = Pos(512.0, 1792.0, 24.0)

    def broken(*args, **kwargs):
        raise RuntimeError("no free entity")

    monkeypatch.setattr(core, "spawn_pair", broken)
    plugin._tick(5.0)
    assert [f[0] for f in core.fired] == ["rl", "rl"]  # b's turrets still fired
    assert plugin._world.run(1) is None and plugin._world.run(2).room == "dodge1"


def test_rlroom_refused_for_a_spectator(core):
    pl = player(team="spectator")
    plugin = make_plugin([pl])
    replies = []
    plugin.cmd_rlroom(pl, ["!rlroom", "arena1"], SimpleNamespace(reply=replies.append))
    assert plugin._world.run(1) is None and replies


def test_team_switch_death_is_a_leave_not_a_lost_life(core):
    pl = player()
    plugin = make_plugin([pl])
    enter(plugin, pl, "arena1")
    plugin.handle_death(pl, None, {})
    plugin.handle_death(pl, None, {})
    plugin.handle_death(pl, None, "SWITCH_TEAMS")  # QL kills a player who changes team
    assert plugin._world.run(1).lives == 1
    plugin.handle_team_switch(pl, "red", "spectator")
    assert plugin._world.run(1) is None
    assert any("left the room" in s for s in plugin.sent) and not any("out of lives" in s for s in plugin.sent)
