import json

import pytest

from tests._minqlx_stub import bare_instance, import_plugin

pytestmark = pytest.mark.standalone

ft = import_plugin("frame_timing")
FrameStats = ft.FrameStats


def test_late_counts_gaps_over_one_and_a_half_ticks():
    s = FrameStats(tick_ms=25.0)
    for g in (25, 25, 37.4, 37.6, 80):
        s.add(g)
    snap = s.snapshot()
    assert snap["frames"] == 5 and snap["late"] == 2 and snap["max_ms"] == 80


def test_percentiles_from_histogram():
    s = FrameStats(tick_ms=25.0)
    for _ in range(98):
        s.add(25.2)
    s.add(60.0)
    s.add(150.0)
    snap = s.snapshot()
    assert snap["p50_ms"] == 26 and snap["p99_ms"] == 61 and snap["max_ms"] == 150


def test_overflow_percentile_reports_max():
    s = FrameStats(tick_ms=25.0)
    for _ in range(10):
        s.add(250.0)
    snap = s.snapshot()
    assert snap["p50_ms"] == 250 and snap["p99_ms"] == 250


def test_empty_snapshot_is_zeros():
    snap = FrameStats(tick_ms=25.0).snapshot()
    assert snap["frames"] == 0 and snap["late"] == 0 and snap["max_ms"] == 0
    assert snap["p50_ms"] == 0 and snap["p99_ms"] == 0 and snap["tick_ms"] == 25.0


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


class FakeDb:
    def __init__(self):
        self.values = {}
        self.ttl = {}

    def set(self, key, value):
        self.values[key] = value

    def expire(self, key, seconds):
        self.ttl[key] = seconds


def make_plugin(sv_fps="40", port="27960"):
    clock = FakeClock()
    cvars = {"sv_fps": sv_fps, "net_port": port}
    plugin = bare_instance(
        ft.frame_timing,
        _clock=clock,
        _cvar=lambda name: cvars.get(name),
        db=FakeDb(),
        _last=None,
        _skip_next=False,
        _seq=0,
        _window_started=0.0,
        _last_error_log=None,
    )
    plugin._tick_ms = 25.0
    plugin._stats = FrameStats(25.0)
    plugin._cvars = cvars
    return plugin, clock


def test_gap_after_map_hook_is_excluded():
    plugin, clock = make_plugin()
    clock.t = 0.0
    plugin.handle_frame()
    plugin.handle_map("campgrounds", None)
    clock.t = 5.0
    plugin.handle_frame()
    clock.t = 5.025
    plugin.handle_frame()
    plugin._publish()
    published = json.loads(plugin.db.values["minqlx:frame_stats:27960"])
    assert published["frames"] == 1 and published["max_ms"] == pytest.approx(25, abs=0.5)
    assert plugin.db.ttl["minqlx:frame_stats:27960"] == 30
    assert published["seq"] == 1 and published["late"] == 0


def test_tick_follows_sv_fps():
    plugin, clock = make_plugin(sv_fps="80")
    plugin.handle_new_game()
    assert plugin._tick_ms == 12.5
    clock.t = 0.0
    plugin.handle_frame()
    plugin.handle_new_game()
    plugin._skip_next = False
    plugin._last = 0.0
    clock.t = 0.020
    plugin.handle_frame()
    snap = plugin._stats.snapshot()
    assert snap["frames"] == 1 and snap["late"] == 1 and snap["tick_ms"] == 12.5


def test_bad_sv_fps_falls_back():
    plugin, _ = make_plugin(sv_fps="abc")
    plugin.handle_new_game()
    assert plugin._tick_ms == 25.0
