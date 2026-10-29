"""moba_spike (throwaway phase 0 plugin, root-0034): marker parsing and the lane nudge."""
import math
from types import SimpleNamespace

import pytest

from tests._minqlx_stub import bare_instance, import_plugin

pytestmark = pytest.mark.standalone

ms = import_plugin("moba_spike")


def ent(targetname, origin, classname="info_notnull"):
    keys = {"classname": classname}
    if targetname is not None:
        keys["targetname"] = targetname
    return SimpleNamespace(classname=classname, origin=origin, keys=keys)


class Log:
    def __init__(self):
        self.warnings = []

    def warning(self, msg, *args):
        self.warnings.append(msg % args if args else msg)

    def info(self, *_a):
        pass


def test_layout_missing_markers():
    assert ms.parse_markers([]) == {}
    plugin = bare_instance(ms.moba_spike, logger=Log(), _markers={"x": [(0, 0, 0)]})
    plugin._apply_markers("campgrounds", [])
    assert plugin._markers == {}
    assert any("campgrounds" in w for w in plugin.logger.warnings)


def test_parse_markers_skips_no_origin():
    got = ms.parse_markers([
        ent("moba_core_red", (128.0, 256.0, 24.0)),
        ent("moba_core_blue", None),
        ent("other_target", (1.0, 2.0, 3.0)),
        ent(None, (1.0, 2.0, 3.0)),
        ent("moba_base_red", (320.0, 128.0, 24.0)),
        ent("moba_base_red", (320.0, 384.0, 24.0)),
    ])
    assert got == {
        "moba_core_red": [(128.0, 256.0, 24.0)],
        "moba_base_red": [(320.0, 128.0, 24.0), (320.0, 384.0, 24.0)],
    }


def test_lane_path_orders_numerically():
    markers = {"moba_path_top_%d" % k: [(float(k), 0.0, 0.0)] for k in (10, 2, 9, 0, 1)}
    markers["moba_path_bottom_0"] = [(99.0, 0.0, 0.0)]
    assert [p[0] for p in ms.lane_path(markers, "top")] == [0.0, 1.0, 2.0, 9.0, 10.0]


def test_nudge_advances_within_64():
    path = [(0.0, 0.0, 0.0), (512.0, 0.0, 0.0)]
    idx, _vel = ms.nudge((40.0, 30.0, 24.0), path, 0)
    assert idx == 1
    idx, _vel = ms.nudge((-100.0, 0.0, 24.0), path, 0)
    assert idx == 0


def test_nudge_velocity_length():
    path = [(0.0, 0.0, 0.0), (512.0, 512.0, 0.0)]
    idx, vel = ms.nudge((0.0, 0.0, 24.0), path, 1)
    assert idx == 1
    assert abs(math.hypot(vel[0], vel[1]) - 320.0) <= 1
    assert vel[2] == 0
    assert vel[0] > 0 and vel[1] > 0


def test_nudge_past_last_point_stops():
    path = [(0.0, 0.0, 0.0)]
    idx, vel = ms.nudge((10.0, 0.0, 24.0), path, 0)
    assert idx == 1
    assert vel == (0.0, 0.0, 0.0)


def test_claim_bot_by_flag_not_steam_id():
    # Live on #26: a QL bot reports steam_id 90071996842377216, not 0.
    plugin = bare_instance(ms.moba_spike, _roles={}, _pending=ms.collections.deque([{"role": "tower", "team": "red"}]),
                           _sync_item_hook=lambda: None)
    human = SimpleNamespace(id=3, steam_id=76561198000000000, is_bot=False)
    bot = SimpleNamespace(id=4, steam_id=90071996842377216, is_bot=True, team="red")
    assert plugin._claim(human) is None
    assert plugin._claim(bot) == {"role": "tower", "team": "red"}
    assert plugin._roles == {4: {"role": "tower", "team": "red"}}


def test_claim_requires_matching_team():
    plugin = bare_instance(ms.moba_spike, _roles={},
                           _pending=ms.collections.deque([{"role": "tower", "team": "blue"}]),
                           _sync_item_hook=lambda: None)
    stray_red = SimpleNamespace(id=5, steam_id=1, is_bot=True, team="red")
    blue = SimpleNamespace(id=6, steam_id=1, is_bot=True, team="blue")
    assert plugin._claim(stray_red) is None
    assert plugin._claim(blue) == {"role": "tower", "team": "blue"}


class Channel:
    def __init__(self):
        self.lines = []

    def reply(self, text):
        self.lines.append(text)


def test_creeps_without_spawn_marker_replies():
    added = []
    plugin = bare_instance(ms.moba_spike, _markers={"moba_core_red": [(0.0, 0.0, 0.0)]},
                           _addbot=lambda team, role: added.append(role))
    ch = Channel()
    plugin.cmd_moba_spike(None, ["!moba_spike", "creeps", "red", "3"], ch)
    plugin.cmd_moba_spike(None, ["!moba_spike", "tower", "blue"], ch)
    assert added == []
    assert any("moba_creepspawn_red_top" in l for l in ch.lines)
    assert any("moba_tower_blue_top_1" in l for l in ch.lines)


def test_tower_hp_only_drops_on_damage():
    # Live on #26: QL decays health above 100 by 1/s, so a 1000 HP tower left alone for
    # 15 minutes was down to 100 and the creeps finished it. The plugin keeps its own HP.
    role = {"role": "tower", "team": "blue", "anchor": (0.0, 0.0, 24.0), "idx": 0, "dead": False, "hp": 1000}
    tower = SimpleNamespace(id=1, is_alive=True, position=(0.0, 0.0, 24.0), velocity=(0, 0, 0),
                            health=1000, team="blue")
    plugin = bare_instance(ms.moba_spike, _roles={1: role}, _markers={}, _last_tick=0.0, _nudges=0,
                           _damage_seen=99, _frame_cost=ms.collections.deque(), logger=Log(),
                           players=lambda: [tower])
    plugin.handle_damage(tower, None, 30, 0, 0)
    assert role["hp"] == 970
    tower.health = 940  # decay since the last tick
    plugin.handle_frame()
    assert tower.health == 970


@pytest.mark.parametrize("raw,clean", [("sarge", "sarge"), ("sa rge;quit", "sargequit"), ("", "sarge")])
def test_bot_name_sanitized(raw, clean):
    assert ms.safe_bot_name(raw) == clean
