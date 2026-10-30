"""tower_defence: markers, hooks and commands against fake players and a fake npc_core."""
import logging
from types import SimpleNamespace

import pytest

from tests._minqlx_stub import bare_instance, import_plugin

pytestmark = pytest.mark.standalone

td = import_plugin("tower_defence")
td_rules = td.td_rules
STOP_ALL = td.minqlx.Return.STOP_ALL


def entity(name, origin=(0, 0, 24)):
    return SimpleNamespace(keys={"targetname": name}, origin=origin)


def full_entities():
    return [
        entity("td_path_10", (9, 0, 24)), entity("td_path_2", (2, 0, 24)), entity("td_pad_1", (500, 0, 24)),
        entity("td_pad_0", (0, 500, 24)), entity("td_creepspawn", (7, 7, 24)), entity("td_base", (8, 8, 24)),
        SimpleNamespace(keys={"classname": "light"}, origin=(1, 1, 1)),
    ]


class FakeCore:
    """npc_core without an engine; tick answers come from a dict keyed by the Npc."""
    BASE_HP = 100000

    def __init__(self):
        self.spawned = []
        self.removed = []
        self.answers = {}
        self.fired = []
        self.flying = 0
        self.cleared = 0
        self.ticks = []
        self.missile_ticks = 0

    def spawn_pair(self, origin, parts, hp_limit, now, solid=True, hull_size=(16, 32), frames=None, fps=0):
        npc = SimpleNamespace(hull=len(self.spawned) if solid else None, visuals=[1000 + len(self.spawned), 2000],
                              hp_limit=hp_limit, pos=origin, vel=(0, 0, 0), last_shot=0.0, parts=parts,
                              solid=solid, hull_size=hull_size, frames=frames, fps=fps)
        self.spawned.append(npc)
        return npc

    def start_path(self, npc, path, speed, now):
        npc.path, npc.speed = path, speed

    def remove(self, npc):
        self.removed.append(npc)

    def tick(self, npc, now):
        self.ticks.append(npc)
        answer = self.answers.get(id(npc), "alive")
        if isinstance(answer, Exception):
            raise answer
        return answer

    def nearest(self, pos, candidates, max_range):
        items = list(candidates)
        return items[0][1] if items else None

    def lead(self, muzzle, target, vel, speed):
        return target

    def speed_of(self, weapon):
        return 900.0

    def fire(self, muzzle, target, weapon, damage, splash, radius, owner, clipmask, visual=None):
        self.fired.append(("fire", weapon, damage, target))

    def fire_at_creeps(self, muzzle, target, weapon, amount, radius, owner, visual=None):
        self.fired.append(("creeps", weapon, amount, target))

    def missiles_in_flight(self):
        return self.flying

    def tick_missiles(self, npcs, now):
        self.missile_ticks += 1

    def clear_missiles(self):
        self.cleared += 1

    def aim_visual(self, npc, part, target):
        npc.aimed = target

    def reset_cache(self):
        pass

    def model_index(self, path):
        return 1

    def preload_weapons(self):
        pass

    CLIP_HITS_PLAYERS = 0x2000001


def player(cid=1, team="red", alive=True, pos=(0.0, 0.0, 24.0)):
    p = SimpleNamespace(id=cid, team=team, is_alive=alive, position=pos, told=[], puts=[])
    p.tell = p.told.append
    p.put = p.puts.append
    return p


@pytest.fixture
def core(monkeypatch):
    fake = FakeCore()
    monkeypatch.setattr(td, "npc_core", fake)
    return fake


@pytest.fixture
def plugin(core):
    return make_plugin([player()])


def make_plugin(players, markers=True):
    sent = []
    p = bare_instance(td.tower_defence, logger=logging.getLogger("td-test"), msg=sent.append,
                      center_print=sent.append, players=lambda: players, sent=sent,
                      get_cvar=lambda name: "td_spike")
    p._init_state()
    if markers:
        p._apply_markers("td_spike", full_entities())
    return p


def channel():
    return SimpleNamespace(reply=lambda text: None)


def add_creep(p, core, name="normal"):
    p._spawn_creep(name, 0.0)
    return p._creeps[-1]


def test_parse_markers_complete():
    m = td.parse_markers(full_entities())
    assert m["path"] == [(2.0, 0.0, 24.0), (9.0, 0.0, 24.0), (8.0, 8.0, 24.0)]  # by number, then the base
    assert m["pads"] == [(0.0, 500.0, 24.0), (500.0, 0.0, 24.0)]
    assert m["spawn"] == (7.0, 7.0, 24.0) and m["base"] == (8.0, 8.0, 24.0)


@pytest.mark.parametrize("missing", ["td_creepspawn", "td_base", "td_path_2", "td_pad_0"])
def test_parse_markers_missing_returns_none(missing):
    ents = [e for e in full_entities() if e.keys.get("targetname") != missing]
    if missing.startswith(("td_path", "td_pad")):
        ents = [e for e in ents if not e.keys.get("targetname", "").startswith(missing[:6])]
    assert td.parse_markers(ents) is None


def test_frame_noop_without_markers(core):
    p = make_plugin([player()], markers=False)
    p.players = None  # any use would raise
    p.handle_frame()
    assert core.spawned == []


def test_build_without_markers_says_off(core):
    p = make_plugin([player()], markers=False)
    pl = player()
    p.cmd_build(pl, ["!build", "pg"], channel())
    assert "off" in pl.told[0]


def test_game_starts_once_the_match_runs(plugin, core):
    plugin._game_state = lambda: "in_progress"
    plugin.handle_frame()
    assert plugin._game.phase == "pause"
    assert len(core.spawned) == 3  # two pads and the base, none of them a hull
    assert not any(n.solid for n in core.spawned)


def test_game_starts_in_warmup_without_readying_up(plugin, monkeypatch):
    calls = []
    monkeypatch.setattr(td.minqlx, "console_command", calls.append)
    plugin._game_state = lambda: "warmup"
    plugin._slow(100.0)
    assert plugin._game.phase == "pause" and calls == []


def test_countdown_does_not_start_the_game(plugin):
    plugin._game_state = lambda: "countdown"
    plugin._slow(100.0)
    assert plugin._game.phase == "idle"


def test_no_player_no_start(core):
    p = make_plugin([])
    p._game_state = lambda: "in_progress"
    p._slow(1.0)
    assert p._game.phase == "idle"


def test_all_leave_cleans_up(core):
    players = [player()]
    p = make_plugin(players)
    p._game.start(0.0)
    a, b = add_creep(p, core), add_creep(p, core)
    p.handle_player_disconnect(players[0], "quit")
    assert a in core.removed and b in core.removed
    assert p._game.phase == "idle" and p._creeps == [] and core.cleared == 1


def test_other_player_left_keeps_the_game(core):
    players = [player(1), player(2)]
    p = make_plugin(players)
    p._game.start(0.0)
    p.handle_player_disconnect(players[0], "quit")
    assert p._game.phase == "pause"


def test_red_gone_to_spectators_cleans_up_too(core):
    p = make_plugin([player(team="spectator")])
    p._game.start(0.0)
    creep = add_creep(p, core)
    p._slow(5.0)
    assert creep in core.removed and p._game.phase == "idle"


def test_next_joiner_starts_wave_one(core):
    players = [player()]
    p = make_plugin(players)
    p._game.start(0.0)
    p._game.wave = 7
    p.handle_player_disconnect(players[0], "quit")
    p._game_state = lambda: "in_progress"
    p._slow(9.0)
    assert p._game.phase == "pause" and p._game.wave == 0


def test_map_change_drops_state(plugin, core):
    plugin._game.start(0.0)
    add_creep(plugin, core)
    plugin._load_markers = lambda mapname: None
    plugin.handle_map("campgrounds", "ffa")
    assert plugin._creeps == [] and plugin._game is None and plugin._markers is None
    assert core.removed == []  # the engine freed them
    plugin.handle_frame()
    assert core.ticks == []


def test_new_game_forgets_entities_without_removing(plugin, core):
    plugin._game.start(0.0)
    add_creep(plugin, core)
    plugin._game.money = 5
    plugin.handle_new_game()
    assert plugin._creeps == [] and plugin._game.phase == "idle" and plugin._game.money == td_rules.START_MONEY
    assert core.removed == []


def test_unload_removes_entities(plugin, core):
    plugin._game.start(0.0)
    creep = add_creep(plugin, core)
    plugin.handle_unload("tower_defence")
    assert creep in core.removed and core.cleared == 1
    assert plugin._game is None


def test_unload_of_another_plugin_is_ignored(plugin, core):
    plugin._game.start(0.0)
    creep = add_creep(plugin, core)
    plugin.handle_unload("gungame")
    assert creep not in core.removed


@pytest.mark.parametrize("who", [player(team="spectator"), player(alive=False)])
def test_build_refused_for_spectator_and_dead(plugin, who):
    who.told.clear()
    plugin._game.start(0.0)
    plugin.cmd_build(who, ["!build", "pg"], channel())
    assert plugin._game.money == td_rules.START_MONEY and who.told and not plugin._game.pads


def test_build_needs_pad_range(plugin):
    plugin._game.start(0.0)
    far = player(pos=(200.0, 200.0, 24.0))
    plugin.cmd_build(far, ["!build", "pg"], channel())
    assert plugin._game.money == td_rules.START_MONEY and far.told


def test_build_needs_a_game(plugin):
    near = player(pos=(0.0, 480.0, 24.0))
    plugin.cmd_build(near, ["!build", "pg"], channel())
    assert plugin._game.money == td_rules.START_MONEY and near.told


def test_build_upgrade_sell_flow(plugin, core):
    plugin._game.start(0.0)
    near = player(pos=(0.0, 480.0, 24.0))
    plugin.cmd_build(near, ["!build", "pg"], channel())
    assert plugin._game.money == 200 and 0 in plugin._turrets
    turret = plugin._turrets[0]
    assert turret.parts == td_rules.TURRETS["pg"].parts and turret.pos == (0.0, 500.0, 26.0)
    plugin.cmd_upgrade(near, ["!upgrade"], channel())
    assert plugin._game.pads[0].level == 1 and plugin._game.money == 100
    plugin.cmd_sell(near, ["!sell"], channel())
    assert plugin._game.money == 240 and turret in core.removed and 0 not in plugin._turrets


def test_refused_build_spawns_nothing(plugin, core):
    plugin._game.start(0.0)
    plugin._game.money = 5
    near = player(pos=(0.0, 480.0, 24.0))
    plugin.cmd_build(near, ["!build", "rl"], channel())
    assert plugin._turrets == {} and core.spawned == []


def test_bad_npc_tick_only_drops_that_npc(plugin, core):
    plugin._game.start(0.0)
    bad, good = add_creep(plugin, core), add_creep(plugin, core)
    core.answers[id(bad)] = ValueError("boom")
    plugin._tick_creeps(1.0)
    assert plugin._creeps == [good] and bad in core.removed


def test_tick_results_reach_the_game(plugin, core):
    plugin._game.start(0.0)
    dead, leak, stuck = add_creep(plugin, core), add_creep(plugin, core, "heavy"), add_creep(plugin, core)
    core.answers.update({id(dead): "dead", id(leak): "arrived", id(stuck): "stuck"})
    plugin._tick_creeps(1.0)
    assert plugin._game.money == td_rules.START_MONEY + 5
    assert plugin._game.lives == td_rules.START_LIVES - 2
    assert plugin._creeps == [] and len(core.removed) == 3


def test_creep_spawn_uses_table_and_players(core):
    p = make_plugin([player(i) for i in range(3)])
    p._slow_players()
    p._game.start(0.0)
    p._game.wave = 1
    creep = add_creep(p, core, "heavy")
    assert creep.hp_limit == 780 and creep.pos == (7.0, 7.0, 26.0)
    assert creep.speed == 120 and creep.hull_size == td_rules.CREEPS["heavy"].hull
    assert creep.frames == (5, 25)
    assert creep.path[0] == (2.0, 0.0, 26.0)


def test_loss_clears_creeps_and_announces(plugin, core):
    plugin._game.start(0.0)
    creep = add_creep(plugin, core)
    plugin._game.lives = 1
    core.answers[id(creep)] = "arrived"
    plugin._tick(1000.0)
    assert plugin._game.phase == "over" and any("lost" in str(m).lower() for m in plugin.sent)


def test_over_to_idle_removes_turrets_and_restarts(plugin, core):
    plugin._game.start(0.0)
    plugin._game.money = 1000
    near = player(pos=(0.0, 480.0, 24.0))
    plugin.cmd_build(near, ["!build", "pg"], channel())
    turret = plugin._turrets[0]
    plugin._game.lives = 1
    plugin._game.leaked("normal")
    plugin._tick(1000.0)
    plugin._tick(1000.0 + td_rules.OVER_S)
    assert turret in core.removed and plugin._turrets == {} and plugin._game.phase == "idle"


def test_turret_fires_at_a_creep_and_holds_at_the_missile_cap(plugin, core):
    plugin._game.start(0.0)
    near = player(pos=(0.0, 480.0, 24.0))
    plugin.cmd_build(near, ["!build", "pg"], channel())
    add_creep(plugin, core)
    core.flying = td.MAX_MISSILES
    plugin._fire_turrets(100.0)
    assert core.fired == []
    core.flying = 0
    plugin._fire_turrets(100.0)
    assert [f[:3] for f in core.fired] == [("creeps", "pg", 20)]
    plugin._fire_turrets(100.1)  # interval 0.3 s
    assert len(core.fired) == 1


def test_shooter_fires_at_a_live_red_player_only_in_range(plugin, core):
    plugin._game.start(0.0)
    add_creep(plugin, core, "shooter")
    add_creep(plugin, core, "normal")
    plugin._targets = [(100.0, 0.0, 24.0)]
    plugin._fire_creeps(100.0)
    assert [f[:2] for f in core.fired] == [("fire", "pg")]


def test_blue_switch_refused(plugin):
    pl = player(team="spectator")
    assert plugin.handle_team_switch_attempt(pl, "spectator", "blue", "b") == STOP_ALL


def test_any_goes_to_red(plugin):
    pl = player(team="spectator")
    assert plugin.handle_team_switch_attempt(pl, "spectator", "any", "any") == STOP_ALL
    assert pl.puts == ["red"]


def test_red_and_spectator_switches_pass(plugin):
    pl = player()
    assert plugin.handle_team_switch_attempt(pl, "spectator", "red", "r") is None
    assert plugin.handle_team_switch_attempt(pl, "red", "spectator", "s") is None


def test_team_hook_idle_without_markers(core):
    p = make_plugin([], markers=False)
    assert p.handle_team_switch_attempt(player(), "spectator", "blue", "b") is None


def test_player_loaded_goes_to_red(plugin):
    pl = player(team="spectator")
    plugin.handle_player_loaded(pl)
    assert pl.puts == ["red"]


def test_wave_jump_clears_creeps(plugin, core):
    plugin._game.start(0.0)
    creep = add_creep(plugin, core)
    plugin.cmd_tdwave(player(), ["!tdwave", "15"], channel())
    assert creep in core.removed and plugin._game.wave == 14


def test_wave_jump_rejects_a_bad_number(plugin):
    plugin._game.start(0.0)
    assert plugin.cmd_tdwave(player(), ["!tdwave", "16"], channel()) == td.minqlx.Return.USAGE
    assert plugin.cmd_tdwave(player(), ["!tdwave", "x"], channel()) == td.minqlx.Return.USAGE


def test_late_markers_of_another_map_are_ignored(core):
    p = make_plugin([player()], markers=False)
    p._apply_markers("campgrounds", full_entities())
    assert p._markers is None and p._game is None


def test_markers_missing_on_this_map_turn_the_mode_off(plugin):
    plugin._apply_markers("td_spike", [])
    assert plugin._markers is None and plugin._game is None


def test_markers_after_unload_are_ignored(plugin, core):
    plugin.handle_unload("tower_defence")
    plugin._apply_markers("td_spike", full_entities())
    assert plugin._game is None


def test_player_on_blue_counts_and_is_put_on_red_once(core):
    other = player(2, team="blue", pos=(1.0, 2.0, 3.0))
    p = make_plugin([other])
    p._game.start(0.0)
    p._slow(1.0)
    p._slow(2.0)
    assert other.puts == ["red"]
    assert p._game.phase == "pause"  # blue alone does not end the game
    assert p._targets == [(1.0, 2.0, 3.0)]


def test_blue_player_can_build(plugin):
    plugin._game.start(0.0)
    near = player(team="blue", pos=(0.0, 480.0, 24.0))
    plugin.cmd_build(near, ["!build", "pg"], channel())
    assert plugin._game.money == 200


def test_last_red_leaving_with_blue_left_keeps_the_game(core):
    red, blue = player(1), player(2, team="blue")
    p = make_plugin([red, blue])
    p._game.start(0.0)
    p.handle_player_disconnect(red, "quit")
    assert p._game.phase == "pause"
