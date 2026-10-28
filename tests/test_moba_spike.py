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


@pytest.mark.parametrize("raw,clean", [("sarge", "sarge"), ("sa rge;quit", "sargequit"), ("", "sarge")])
def test_bot_name_sanitized(raw, clean):
    assert ms.safe_bot_name(raw) == clean
