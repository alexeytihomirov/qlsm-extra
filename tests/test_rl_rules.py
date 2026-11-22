"""Roguelike rules: markers, runs, rooms, occupancy, teleporter offers, lives."""
import math
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

import rl_rules  # noqa: E402

pytestmark = pytest.mark.standalone

# The markers of ql-map-generator/qls/rl_spike.qls.json, z = floor + z_offset.
FULL = (
    [("rl_hub_start", (384, 640, 24))]
    + [("rl_move1_start", (1408, 256, 216)), ("rl_move1_finish", (2944, 256, 216)),
       ("rl_move1_pit", (2240, 64, 24))]
    + [("rl_move1_door_%d" % i, (x, y, 216))
       for i, (x, y) in enumerate([(3040, 160), (3040, 352), (3152, 160), (3152, 352)])]
    + [("rl_dodge1_start", (512, 1792, 24)), ("rl_dodge1_turret_0", (64, 1344, 184)),
       ("rl_dodge1_turret_1", (960, 2240, 184))]
    + [("rl_dodge1_door_%d" % i, (x, 2240, 24)) for i, x in enumerate([320, 448, 576, 704])]
    + [("rl_arena1_start", (2176, 1408, 24))]
    + [("rl_arena1_mob_%d" % i, (x, y, 24))
       for i, (x, y) in enumerate([(1664, 2432), (2688, 2432), (1664, 1920), (2688, 1920)])]
    + [("rl_arena1_door_%d" % i, (x, 2496, 24)) for i, x in enumerate([1984, 2112, 2240, 2368])]
)


def world(seed=1):
    w = rl_rules.World(rl_rules.parse_markers(FULL), rng=random.Random(seed))
    w.test_now = 0.0
    return w


def room_of(w, cid):
    return w.layout.rooms[w.run(cid).room]


def tick(w, cid, pos, alive=0, dt=0.05):
    w.test_now += dt
    return w.tick(cid, pos, w.test_now, alive)


def clear_current_room(w, cid):
    room = room_of(w, cid)
    if room.type == "move":
        ev = tick(w, cid, room.finish)
    elif room.type == "dodge":
        ev = tick(w, cid, room.start, dt=rl_rules.DODGE_SURVIVE_S + 1)
    else:
        ev = []
        for _ in range(1000):
            ev = tick(w, cid, room.start, alive=0, dt=0.1)
            if any(e[0] == "cleared" for e in ev):
                break
    assert any(e[0] == "cleared" for e in ev), ev
    return ev


def step_on(w, cid, door):
    pos = room_of(w, cid).doors[door]
    return tick(w, cid, pos)


def only_door(w, cid):
    offers = w.run(cid).offers
    assert len(offers) == 1, offers
    return next(iter(offers))


def third(w):
    taken = set(w.occupied())
    (room,) = [r for r in w.layout.rooms if r not in taken]
    return room


def test_tables():
    for name, mob in rl_rules.MOBS.items():
        assert mob.name == name and mob.attack in rl_rules.ATTACKS
    for wave in rl_rules.ARENA_WAVES:
        assert all(name in rl_rules.MOBS for name, _ in wave)
    assert set(rl_rules.KITS) == {"move", "dodge", "arena"}
    assert rl_rules.TURRET.attack.damage == 50


def test_parse_markers_types_and_skips():
    lay = rl_rules.parse_markers(FULL + [("rl_move2_start", (0, 0, 0))])
    assert set(lay.rooms) == {"move1", "dodge1", "arena1"}
    assert lay.rooms["move1"].type == "move" and len(lay.rooms["move1"].doors) == 4
    assert lay.skipped == ["move2"]
    assert rl_rules.parse_markers([m for m in FULL if m[0] != "rl_hub_start"]) is None


def test_parse_markers_room_needs_what_its_type_needs():
    named = [m for m in FULL if m[0] not in ("rl_move1_pit", "rl_dodge1_turret_0", "rl_dodge1_turret_1")]
    lay = rl_rules.parse_markers(named)
    assert set(lay.rooms) == {"arena1"} and lay.skipped == ["dodge1", "move1"]
    move = rl_rules.parse_markers(FULL).rooms["move1"]
    assert move.pit_z == 24 and move.finish == (2944, 256, 216)
    no_rooms = [m for m in FULL if m[0] == "rl_hub_start" or "_door_" in m[0]]
    assert rl_rules.parse_markers(no_rooms) is None


def test_run_through_three_rooms_ends_in_hub():
    w = world(seed=1)
    ev = w.begin(7, 0.0)
    assert ev[0][0] == "enter"
    for _ in range(3):
        clear_current_room(w, 7)
        offers = w.run(7).offers
        step_on(w, 7, next(iter(offers)))
    assert w.run(7) is None and w.occupied() == {}


def test_offers_are_unvisited_types_then_hub():
    w = world(seed=3)
    w.begin(7, 0.0)
    first = w.run(7).room
    ev = clear_current_room(w, 7)
    (cleared,) = [e for e in ev if e[0] == "cleared"]
    offers = w.run(7).offers
    assert cleared[1] == first and cleared[2] == offers
    assert sorted(offers.values()) == sorted(t for t in ("move", "dodge", "arena") if t != room_of(w, 7).type)
    assert len(set(offers)) == len(offers)
    for _ in range(2):
        door = next(iter(w.run(7).offers))
        step_on(w, 7, door)
        clear_current_room(w, 7)
    assert list(w.run(7).offers.values()) == ["hub"]
    ev = step_on(w, 7, next(iter(w.run(7).offers)))
    (hub,) = [e for e in ev if e[0] == "hub"]
    assert hub[1] == "done" and hub[2] == pytest.approx(w.test_now)


def test_last_free_room_goes_to_one_player_only():
    w = world(seed=1)
    w.begin(1, 0.0)
    w.begin(2, 0.0)
    clear_current_room(w, 1)
    clear_current_room(w, 2)
    door1 = only_door(w, 1)
    door2 = only_door(w, 2)
    target = third(w)
    assert ("enter", target) in step_on(w, 1, door1)
    ev = step_on(w, 2, door2)
    assert not any(e[0] == "enter" for e in ev)
    assert ("full",) in ev
    assert sorted(w.occupied().values()) == [1, 2]
    assert w.occupied()[target] == 1


def test_failed_step_needs_leaving_the_pad():
    w = world(seed=1)
    w.begin(1, 0.0)
    w.begin(2, 0.0)
    clear_current_room(w, 1)
    clear_current_room(w, 2)
    door1, door2 = only_door(w, 1), only_door(w, 2)
    step_on(w, 1, door1)
    step_on(w, 2, door2)  # refused, offers rebuilt to the room 1 left
    if door2 in w.run(2).offers:
        assert not any(e[0] == "enter" for e in step_on(w, 2, door2))
        tick(w, 2, room_of(w, 2).start)
        assert any(e[0] == "enter" for e in step_on(w, 2, door2))


def test_death_on_last_life_goes_to_hub_and_frees_room():
    w = world(seed=1)
    w.begin(7, 0.0)
    room = w.run(7).room
    w.died(7, 1.0)
    w.died(7, 2.0)
    assert w.where(7) == w.layout.rooms[room].start
    assert ("hub", "dead", 3.0) in w.died(7, 3.0)
    assert w.where(7) is None and room not in w.occupied()


def test_death_restarts_room_and_costs_a_life():
    w = world(seed=1)
    w.begin(7, 0.0)
    room = w.run(7).room
    ev = w.died(7, 1.0)
    assert ev == [("lives", 2), ("restart", room)]
    assert w.run(7).lives == 2


def test_pad_before_clear_does_nothing():
    w = world(seed=1)
    w.begin(7, 0.0)
    room = room_of(w, 7)
    for door in range(len(room.doors)):
        assert not any(e[0] in ("enter", "hub", "hint") for e in step_on(w, 7, door))
    assert w.run(7).phase == "play" and w.run(7).room == room.id


def test_pad_without_offer_does_nothing():
    w = world(seed=1)
    w.begin(7, 0.0)
    clear_current_room(w, 7)
    room = room_of(w, 7)
    free = [d for d in range(len(room.doors)) if d not in w.run(7).offers]
    assert free
    for door in free:
        assert step_on(w, 7, door) == []
    assert w.run(7).room == room.id


def test_leave_frees_room_and_reports_hub_left():
    w = world(seed=1)
    w.begin(7, 0.0)
    room = w.run(7).room
    tick(w, 7, room_of(w, 7).start, dt=2.0)
    ev = w.leave(7)
    assert ev == [("hub", "left", pytest.approx(2.0))]
    assert w.run(7) is None and room not in w.occupied()
    assert w.leave(7) == []


def test_move_fall_returns_fall_and_keeps_clock():
    w = world(seed=1)
    w.force(7, "move1", 0.0)
    room = room_of(w, 7)
    w.test_now = 10.0
    ev = tick(w, 7, (2240, 64, room.pit_z + rl_rules.PIT_MARGIN - 1))
    assert ev == [("fall",)]
    assert tick(w, 7, room.start, dt=1.0) == []
    w.test_now = rl_rules.MOVE_LIMIT_S - 0.5
    assert tick(w, 7, room.start, dt=0.0) == []
    w.test_now = rl_rules.MOVE_LIMIT_S
    assert tick(w, 7, room.start, dt=0.0) == [("lives", 2), ("restart", "move1")]


def test_move_timeout_costs_life_and_restarts():
    w = world(seed=1)
    w.force(7, "move1", 0.0)
    start = room_of(w, 7).start
    w.test_now = rl_rules.MOVE_LIMIT_S
    assert tick(w, 7, start, dt=0.0) == [("lives", 2), ("restart", "move1")]
    w.test_now += rl_rules.MOVE_LIMIT_S - 1
    assert tick(w, 7, start, dt=0.0) == []
    w.test_now += 1
    assert tick(w, 7, start, dt=0.0) == [("lives", 1), ("restart", "move1")]
    w.test_now += rl_rules.MOVE_LIMIT_S
    ev = tick(w, 7, start, dt=0.0)
    assert ev == [("hub", "dead", pytest.approx(w.test_now))]
    assert w.run(7) is None and w.occupied() == {}


def test_move_clears_at_the_finish():
    w = world(seed=1)
    w.force(7, "move1", 0.0)
    room = room_of(w, 7)
    near = (room.finish[0] + rl_rules.FINISH_RANGE - 1, room.finish[1], room.finish[2])
    ev = tick(w, 7, near)
    assert ev[0][:2] == ("cleared", "move1") and w.run(7).phase == "cleared"


def test_dodge_clears_at_30s():
    w = world(seed=1)
    w.force(7, "dodge1", 0.0)
    start = room_of(w, 7).start
    w.test_now = rl_rules.DODGE_SURVIVE_S - 0.1
    assert tick(w, 7, start, dt=0.0) == []
    w.test_now = rl_rules.DODGE_SURVIVE_S
    ev = tick(w, 7, start, dt=0.0)
    assert ev[0][:2] == ("cleared", "dodge1")


def _arena(w, cid=7):
    w.force(cid, "arena1", 0.0)
    return room_of(w, cid).start


def test_arena_spawns_waves_one_mob_per_0_7s_and_clears():
    w = world(seed=1)
    start = _arena(w)
    spawned = []
    alive = 0
    t = 0.0
    while t < 60:
        ev = w.tick(7, start, t, alive)
        for e in ev:
            if e[0] == "spawn_mob":
                spawned.append((t, e[1], e[2]))
                alive += 1
        if any(e[0] == "cleared" for e in ev):
            break
        if len(spawned) == 4 and alive == 4:
            alive = 0  # the first wave dies at once
        if len(spawned) == 10 and alive:
            alive = 0
        t = round(t + 0.05, 2)
    assert [s[1] for s in spawned] == ["chaser"] * 8 + ["shooter"] * 2
    first_wave = [s[0] for s in spawned[:4]]
    gaps = [b - a for a, b in zip(first_wave, first_wave[1:])]
    assert all(g == pytest.approx(rl_rules.MOB_SPAWN_S, abs=0.051) for g in gaps)
    assert all(0 <= s[2] < 4 for s in spawned)
    assert len({s[2] for s in spawned[:4]}) == 4
    assert w.run(7).phase == "cleared"


def test_arena_not_cleared_while_mobs_alive():
    w = world(seed=1)
    start = _arena(w)
    t, alive = 0.0, 0
    for _ in range(2000):
        ev = w.tick(7, start, t, alive)
        alive += sum(1 for e in ev if e[0] == "spawn_mob")
        assert not any(e[0] == "cleared" for e in ev)
        t += 0.05
    assert alive == 4 and w.run(7).phase == "play"


def test_arena_holds_spawn_at_15_alive(monkeypatch):
    monkeypatch.setattr(rl_rules, "ARENA_WAVES", [[("chaser", 20)]])
    w = world(seed=1)
    start = _arena(w)
    t, alive = 0.0, 0
    for _ in range(400):
        ev = w.tick(7, start, t, alive)
        alive += sum(1 for e in ev if e[0] == "spawn_mob")
        t += 0.05
    assert alive == rl_rules.MAX_MOBS
    ev = w.tick(7, start, t + 1, alive - 1)
    assert [e[0] for e in ev] == ["spawn_mob"]


def test_restart_resets_room_clock_and_waves():
    w = world(seed=1)
    start = _arena(w)
    t, alive = 0.0, 0
    while alive < 3:
        alive += sum(1 for e in w.tick(7, start, t, alive) if e[0] == "spawn_mob")
        t += 0.05
    assert w.died(7, t) == [("lives", 2), ("restart", "arena1")]
    spawned = []
    t2 = t
    while t2 < t + 10:
        spawned += [e for e in w.tick(7, start, t2, len(spawned)) if e[0] == "spawn_mob"]
        t2 += 0.05
    assert len(spawned) == 4  # the first wave again, whole

    w.force(8, "move1", 0.0)
    w.died(8, 40.0)
    mstart = w.layout.rooms["move1"].start
    assert w.tick(8, mstart, 40.0 + rl_rules.MOVE_LIMIT_S - 1, 0) == []


def test_begin_when_all_rooms_taken_returns_full():
    w = world(seed=1)
    for cid in (1, 2, 3):
        assert w.begin(cid, 0.0)[0][0] == "enter"
    assert len(w.occupied()) == 3
    assert w.begin(4, 0.0) == [("full",)]
    assert w.run(4) is None


def test_begin_twice_is_ignored():
    w = world(seed=1)
    w.begin(1, 0.0)
    room = w.run(1).room
    assert w.begin(1, 1.0) == []
    assert w.run(1).room == room and len(w.occupied()) == 1


def test_hint_once_per_approach():
    w = world(seed=1)
    w.begin(7, 0.0)
    clear_current_room(w, 7)
    room = room_of(w, 7)
    door = next(iter(w.run(7).offers))
    d = room.doors[door]
    near = (d[0] + rl_rules.HINT_RANGE - 4, d[1], d[2])
    assert tick(w, 7, near) == [("hint", door)]
    assert tick(w, 7, near) == []
    assert tick(w, 7, room.start) == []
    assert tick(w, 7, near) == [("hint", door)]


def test_offers_rebuilt_when_room_frees():
    w = world(seed=1)
    for cid in (1, 2, 3):
        w.begin(cid, 0.0)
    clear_current_room(w, 1)
    assert list(w.run(1).offers.values()) == ["hub"]  # a way out while every other room is taken
    room2 = w.run(2).room
    w.leave(2)
    start = room_of(w, 1).start
    tick(w, 1, start, dt=rl_rules.OFFER_RETRY_S / 2)
    ev = tick(w, 1, start, dt=rl_rules.OFFER_RETRY_S)
    offers = w.run(1).offers
    assert ev == [("offers", offers)]
    assert list(offers.values()) == [w.layout.rooms[room2].type]


def test_force_moves_a_run_and_refuses_a_taken_room():
    w = world(seed=1)
    assert w.force(1, "arena1", 0.0) == [("enter", "arena1")]
    assert w.force(2, "arena1", 0.0) == []
    assert w.force(1, "dodge1", 1.0) == [("enter", "dodge1")]
    assert w.occupied() == {"dodge1": 1}
    assert w.force(1, "nope", 1.0) == []


def test_drop_all():
    w = world(seed=1)
    w.begin(1, 0.0)
    w.begin(2, 0.0)
    w.drop_all()
    assert w.occupied() == {} and w.run(1) is None and w.where(2) is None


def test_doors_far_enough_apart_for_the_ranges():
    lay = rl_rules.parse_markers(FULL)
    for room in lay.rooms.values():
        for i, a in enumerate(room.doors):
            for b in room.doors[i + 1:]:
                assert math.hypot(a[0] - b[0], a[1] - b[1]) >= 2 * rl_rules.HINT_RANGE


def test_runs_blocking_each_other_can_leave_through_the_hub():
    w = world(seed=1)
    for cid in (1, 2, 3):
        w.begin(cid, 0.0)
    clear_current_room(w, 1)
    room = w.run(1).room
    tick(w, 1, room_of(w, 1).start, dt=rl_rules.OFFER_RETRY_S * 2)
    assert list(w.run(1).offers.values()) == ["hub"]  # still nothing free: the exit stays put
    ev = step_on(w, 1, only_door(w, 1))
    assert [e[:2] for e in ev] == [("hub", "left")]
    assert w.run(1) is None and room not in w.occupied()
