"""npc_core: the pure helpers, and the engine recipes against a fake entity layer."""
import math
from types import SimpleNamespace

import pytest

from tests._minqlx_stub import import_plugin

pytestmark = pytest.mark.standalone

npc_core = import_plugin("npc_core")
LINEAR, STATIONARY = "linear", "stationary"
ORIGIN = (0.0, 0.0, 26.0)


class FakeEngine:
    """Enough of the entity layer for the recipes: entities in a dict, configstrings in a dict."""
    CS_MODELS = 1000
    CS_ITEMS = 2000
    EntityType = SimpleNamespace(GENERAL="general", ITEM="item", MISSILE="missile")
    TrajectoryType = SimpleNamespace(LINEAR=LINEAR, STATIONARY=STATIONARY)
    EntityEvent = SimpleNamespace(MISSILE_MISS="miss")
    Weapon = SimpleNamespace(ROCKET_LAUNCHER=5, PLASMAGUN=8)
    Mod = SimpleNamespace(ROCKET=1, ROCKET_SPLASH=2, PLASMA=3, PLASMA_SPLASH=4)

    def __init__(self):
        self.ents = {}
        self.cs = {}
        self.events = []
        self.removed = []
        self.set_cs = []
        self.level = SimpleNamespace(time=1000)
        self.fail_spawn_after = None

    def spawn_entity(self, classname, keys):
        if self.fail_spawn_after is not None and len(self.ents) >= self.fail_spawn_after:
            return None
        num = 100 + len(self.ents) + len(self.removed)
        e = SimpleNamespace(
            inuse=True, health=0,
            s=SimpleNamespace(number=num, e_type=None, pos_type=None, pos_base=None, pos_delta=(0, 0, 0),
                              pos_time=0, frame=0, apos_base=None, weapon=0, modelindex=0),
            r=SimpleNamespace(current_origin=None, sv_flags=0, contents=0))
        self.ents[num] = e
        return e

    def Entity(self, num):
        return self.ents[num]

    def link_entity(self, num):
        return True

    def remove_entity(self, num):
        self.removed.append(num)
        self.ents[num].inuse = False

    def add_event(self, num, event, parm=0):
        self.events.append((num, event, parm))

    def configstring(self, index, cached=True):
        return self.cs.get(index, "")

    def set_configstring(self, index, value):
        self.cs[index] = value
        self.set_cs.append(index)


@pytest.fixture
def engine(monkeypatch):
    fake = FakeEngine()
    monkeypatch.setattr(npc_core, "minqlx", fake)
    npc_core.reset_cache()
    return fake


def walker(now=0.0, path=((500.0, 0.0, 26.0), (500.0, 500.0, 26.0)), speed=200, hp=100):
    npc = npc_core.spawn_pair(ORIGIN, ("a.md3", "b.md3"), hp, now, frames=(5, 25), fps=20)
    npc_core.start_path(npc, path, speed, now)
    return npc


def test_steer_speed_and_flat():
    vx, vy, vz = npc_core.steer((0, 0, 26), (300, 400, 90), 200)
    assert math.hypot(vx, vy) == pytest.approx(200) and vz == 0


def test_reached():
    assert npc_core.reached((0, 0, 26), (10, 10, 500))
    assert not npc_core.reached((0, 0, 26), (20, 20, 26))


def test_next_frame_wraps():
    assert npc_core.next_frame(5, 25, 1.05, 20) == 5
    assert npc_core.next_frame(5, 25, 0.5, 20) == 15


def test_nearest_respects_range():
    near, far = ((10, 0, 0), "near"), ((50, 0, 0), "far")
    assert npc_core.nearest((0, 0, 0), [far, near], 100) == "near"
    assert npc_core.nearest((0, 0, 0), [far], 40) is None


def test_lead_moves_the_aim_along_the_velocity():
    assert npc_core.lead((0, 0, 0), (900, 0, 0), (0, 200, 0), 900) == (900, 200, 0)


def test_spawn_pair_hull_and_visuals(engine):
    npc = npc_core.spawn_pair(ORIGIN, ("a.md3", "b.md3"), 100, 0.0, hull_size=(48, 170))
    hull = engine.ents[npc.hull]
    assert hull.s.e_type == "item" and hull.r.contents == npc_core.HULL_CONTENTS
    assert hull.r.sv_flags & npc_core.SVF_NOCLIENT
    assert hull.takedamage and hull.health == npc_core.BASE_HP
    assert hull.r.mins == (-48.0, -48.0, -24.0) and hull.r.maxs == (48.0, 48.0, 170.0)
    assert hull.s.pos_base == ORIGIN
    assert [engine.ents[v].s.pos_base for v in npc.visuals] == [(0.0, 0.0, 0.0)] * 2
    assert engine.ents[npc.visuals[0]].s.e_type == "general"


def test_spawn_pair_not_solid_has_no_hull(engine):
    npc = npc_core.spawn_pair(ORIGIN, ("a.md3",), 0, 0.0, solid=False)
    assert npc.hull is None and len(engine.ents) == 1
    npc_core.remove(npc)
    assert engine.removed == npc.visuals


def test_spawn_pair_failure_leaves_nothing(engine):
    engine.fail_spawn_after = 2
    with pytest.raises(RuntimeError):
        npc_core.spawn_pair(ORIGIN, ("a.md3", "b.md3"), 100, 0.0)
    assert sorted(engine.removed) == sorted(engine.ents)


def test_tick_dead_at_limit(engine):
    npc = walker()
    assert npc_core.tick(npc, 0.05) == "alive"
    npc_core.damage(npc, 99)
    assert npc_core.damage_taken(npc) == 99
    assert npc_core.tick(npc, 0.1) == "alive"
    npc_core.damage(npc, 1)
    assert npc_core.tick(npc, 0.15) == "dead"


def test_tick_arrived_past_last_point(engine):
    npc = walker(path=((500.0, 0.0, 26.0),))
    engine.ents[npc.hull].r.current_origin = (495.0, 0.0, 26.0)
    assert npc_core.tick(npc, 1.0) == "arrived"


def test_tick_overshoot_counts_as_reached(engine):
    npc = walker(path=((500.0, 0.0, 26.0),))
    engine.ents[npc.hull].r.current_origin = (560.0, 0.0, 26.0)
    assert npc_core.tick(npc, 1.0) == "arrived"


def test_tick_stuck_after_3s(engine):
    npc = walker()
    assert npc_core.tick(npc, 2.9) == "alive"
    assert npc_core.tick(npc, 3.1) == "stuck"


def test_tick_moving_is_not_stuck(engine):
    npc = walker()
    engine.ents[npc.hull].r.current_origin = (100.0, 0.0, 26.0)
    assert npc_core.tick(npc, 3.1) == "alive"
    assert npc_core.tick(npc, 6.0) == "alive"
    assert npc_core.tick(npc, 6.2) == "stuck"


def test_tick_resteers_a_stopped_hull(engine):
    npc = walker()
    hull = engine.ents[npc.hull]
    hull.s.pos_type = STATIONARY
    assert npc_core.tick(npc, 1.0) == "alive"
    assert hull.s.pos_type == LINEAR


def test_tick_advances_waypoint_and_resteers(engine):
    npc = walker()
    hull = engine.ents[npc.hull]
    hull.r.current_origin = (500.0, 0.0, 26.0)
    engine.level.time = 5000
    assert npc_core.tick(npc, 2.5) == "alive"
    assert npc.idx == 1
    assert hull.s.pos_delta == pytest.approx((0.0, 200.0, 0.0))
    assert hull.s.pos_base == (500.0, 0.0, 26.0) and hull.s.pos_time == 5000
    visual = engine.ents[npc.visuals[1]]
    assert visual.s.pos_base == (500.0, 0.0, 0.0) and visual.s.pos_delta == hull.s.pos_delta
    assert visual.s.apos_base[1] == pytest.approx(90.0)


def test_tick_animates_only_the_first_part(engine):
    npc = walker()
    npc_core.tick(npc, 0.5)
    assert engine.ents[npc.visuals[0]].s.frame == 15
    assert engine.ents[npc.visuals[1]].s.frame == 0


def test_tick_hull_gone_is_stuck(engine):
    npc = walker()
    engine.ents[npc.hull].inuse = False
    assert npc_core.tick(npc, 0.1) == "stuck"


def test_model_index_reuses_slot(engine):
    engine.cs[engine.CS_MODELS + 1] = "models/map.md3"
    assert npc_core.model_index("a.md3") == 2
    assert npc_core.model_index("a.md3") == 2
    assert engine.set_cs == [engine.CS_MODELS + 2]
    npc_core.reset_cache()
    assert npc_core.model_index("a.md3") == 2
    assert engine.set_cs == [engine.CS_MODELS + 2]


def test_preload_weapons_sets_the_bits(engine):
    engine.cs[engine.CS_ITEMS] = "0010"
    npc_core.preload_weapons()
    bits = engine.cs[engine.CS_ITEMS]
    assert bits[2] == bits[13] == bits[16] == "1" and bits.count("1") == 3


def test_fire_sets_the_missile_up(engine):
    shooter = npc_core.spawn_pair(ORIGIN, ("a.md3",), 100, 0.0)
    num = npc_core.fire((0, 0, 50), (100, 0, 50), "pg", 15, 0, 0, shooter.hull,
                        npc_core.CLIP_HITS_PLAYERS, visual=shooter.visuals[0])
    m = engine.ents[num]
    assert m.s.e_type == "missile" and m.s.weapon == 8
    assert m.s.pos_delta == pytest.approx((2000.0, 0.0, 0.0))
    assert m.s.pos_time == 950 and m.nextthink == 0
    assert m.clipmask == npc_core.CLIP_HITS_PLAYERS and m.r.owner_num == npc_core.ENTITYNUM_NONE
    assert (shooter.visuals[0], npc_core.EV_FIRE_WEAPON, 0) in engine.events


def _turret_shot(engine, weapon="pg", amount=20, radius=0):
    owner = npc_core.spawn_pair(ORIGIN, ("a.md3",), 100, 0.0)
    num = npc_core.fire_at_creeps((0.0, 0.0, 26.0), (2000.0, 0.0, 26.0), weapon, amount, radius, owner.hull)
    m = engine.ents[num]
    assert m.damage == 0 and m.splash_damage == 0 and m.clipmask == npc_core.CLIP_HITS_CREEPS
    m.s.pos_time = 1000
    return num


def test_missile_hits_a_hull_and_explodes(engine):
    creep = npc_core.spawn_pair((100.0, 0.0, 26.0), ("a.md3",), 100, 0.0)
    num = _turret_shot(engine)
    engine.level.time = 1100
    npc_core.tick_missiles([creep], 1.0)
    m = engine.ents[num]
    assert npc_core.damage_taken(creep) == 20
    assert m.s.e_type == "general" and m.clipmask == 0
    assert (num, "miss", 5) in engine.events
    npc_core.tick_missiles([creep], 1.2)
    assert num not in engine.removed
    npc_core.tick_missiles([creep], 1.6)
    assert num in engine.removed
    assert npc_core.missiles_in_flight() == 0


def test_fast_missile_does_not_jump_over_a_hull(engine):
    creep = npc_core.spawn_pair((100.0, 0.0, 26.0), ("a.md3",), 100, 0.0)
    _turret_shot(engine)
    engine.level.time = 1500  # 1000 u in one step
    npc_core.tick_missiles([creep], 1.0)
    assert npc_core.damage_taken(creep) == 20


def test_rocket_splashes_neighbours_with_falloff(engine):
    hit = npc_core.spawn_pair((100.0, 0.0, 26.0), ("a.md3",), 100, 0.0)
    near = npc_core.spawn_pair((100.0, 60.0, 26.0), ("a.md3",), 100, 0.0)
    far = npc_core.spawn_pair((100.0, 900.0, 26.0), ("a.md3",), 100, 0.0)
    _turret_shot(engine, "rl", 100, 120)
    engine.level.time = 1100
    npc_core.tick_missiles([hit, near, far], 1.0)
    assert npc_core.damage_taken(hit) == 100
    assert 0 < npc_core.damage_taken(near) < 100
    assert npc_core.damage_taken(far) == 0


def test_missile_gone_on_a_wall_is_dropped(engine):
    num = _turret_shot(engine)
    engine.ents[num].inuse = False
    npc_core.tick_missiles([], 1.0)
    assert npc_core.missiles_in_flight() == 0 and num not in engine.removed


def test_engine_run_missile_is_not_hit_tested(engine):
    creep = npc_core.spawn_pair((100.0, 0.0, 26.0), ("a.md3",), 100, 0.0)
    npc_core.fire((0.0, 0.0, 26.0), (200.0, 0.0, 26.0), "pg", 15, 0, 0, creep.hull, npc_core.CLIP_HITS_PLAYERS)
    engine.level.time = 1100
    npc_core.tick_missiles([creep], 1.0)
    assert npc_core.damage_taken(creep) == 0 and npc_core.missiles_in_flight() == 1


def test_clear_missiles_removes_live_ones(engine):
    num = _turret_shot(engine)
    npc_core.clear_missiles()
    assert num in engine.removed and npc_core.missiles_in_flight() == 0


def test_aim_visual_turns_a_part(engine):
    npc = npc_core.spawn_pair(ORIGIN, ("a.md3", "b.md3"), 0, 0.0, solid=False)
    npc_core.aim_visual(npc, 1, (0.0, 100.0, 0.0))
    assert engine.ents[npc.visuals[1]].s.apos_base == pytest.approx((0.0, 90.0, 0.0))
    assert engine.ents[npc.visuals[0]].s.apos_base is None


def test_damage_plum_event_and_cleanup(engine):
    num = npc_core.damage_plum((1.0, 2.0, 3.0), 45, 3, 1.0)
    e = engine.ents[num]
    assert (e.s.client_num, e.s.time, e.s.generic1) == (3, 45, npc_core.PLUM_WEAPON)
    assert e.s.pos_base == (1.0, 2.0, 3.0) and e.s.e_type == "general"
    assert (num, npc_core.EV_DAMAGEPLUM, 0) in engine.events
    assert npc_core.missiles_in_flight() == 0
    npc_core.tick_missiles([], 1.2)
    assert num not in engine.removed
    npc_core.tick_missiles([], 1.6)
    assert num in engine.removed
