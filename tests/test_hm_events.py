"""Windowed event tracker."""
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.standalone

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "addons" / "host-metrics" / "assets"))

import hm_events  # noqa: E402
import hm_store  # noqa: E402

T0 = 1_700_000_000
TH = {"core_saturated_pct": 95, "steal_event_pct": 10, "mem_low_pct": 10, "disk_low_pct": 90,
      "frames_late_pct": 1, "frame_gap_ms": 100, "event_window_s": 60}


@pytest.fixture
def conn(tmp_path):
    c = hm_store.open_db(tmp_path / "m.db")
    yield c
    c.close()


@pytest.fixture
def tracker(conn):
    return hm_events.EventTracker(conn, TH)


def _sample(busy=50.0, steal=0.0, avail=500, disk=10, oom=0, insts=None):
    return {"ts": 0,
            "host": {"mem_total": 1000, "mem_avail": avail, "disk_used": disk, "disk_total": 100},
            "cores": [{"core": -1, "busy": busy, "steal": steal},
                      {"core": 0, "busy": busy, "steal": steal}],
            "insts": insts if insts is not None else [], "oom_delta": oom}


def _run(tracker, seconds, **kw):
    for t in range(0, seconds + 1, 10):
        tracker.evaluate(T0 + t, _sample(**kw))
    return T0 + seconds


def _kinds(conn, kind=None):
    return [e for e in hm_store.events(conn, 0) if kind is None or e["kind"] == kind]


def test_core_busy_50s_no_event(tracker, conn):
    _run(tracker, 50, busy=96.0)
    assert _kinds(conn) == []


def test_core_busy_60s_opens_then_closes(tracker, conn):
    end = _run(tracker, 60, busy=96.0)
    ev = _kinds(conn, "core_saturated")
    assert len(ev) == 1 and ev[0]["state"] == "open"
    assert ev[0]["scope"] == "core" and ev[0]["port"] is None and ev[0]["severity"] == "warn"
    tracker.evaluate(end + 10, _sample(busy=50.0))
    ev = _kinds(conn, "core_saturated")
    assert len(ev) == 1 and ev[0]["state"] == "closed" and ev[0]["closed_ts"] == end + 10


def test_flapping_makes_no_event(tracker, conn):
    for i in range(30):
        tracker.evaluate(T0 + 10 * i, _sample(busy=96.0 if i % 2 == 0 else 50.0))
    assert _kinds(conn) == []


def test_steal_high_window(tracker, conn):
    _run(tracker, 60, steal=12.0)
    assert len(_kinds(conn, "steal_high")) == 1


def test_mem_low_window(tracker, conn):
    _run(tracker, 60, avail=50)
    ev = _kinds(conn, "mem_low")
    assert len(ev) == 1 and ev[0]["scope"] == "host"


def test_disk_low_at_once_and_closes(tracker, conn):
    tracker.evaluate(T0, _sample(disk=95))
    ev = _kinds(conn, "disk_low")
    assert len(ev) == 1 and ev[0]["state"] == "open" and ev[0]["severity"] == "crit"
    tracker.evaluate(T0 + 10, _sample(disk=95))
    assert len(_kinds(conn, "disk_low")) == 1
    tracker.evaluate(T0 + 20, _sample(disk=50))
    assert _kinds(conn, "disk_low")[0]["state"] == "closed"


def test_oom_kill_is_a_point_event(tracker, conn):
    tracker.evaluate(T0, _sample(oom=1))
    ev = _kinds(conn, "oom_kill")
    assert len(ev) == 1 and ev[0]["state"] == "closed" and ev[0]["severity"] == "crit"
    tracker.evaluate(T0 + 10, _sample(oom=0))
    tracker.evaluate(T0 + 20, _sample(oom=2))
    assert len(_kinds(conn, "oom_kill")) == 2


def _inst(port, frames=100, late=0, max_ms=5.0):
    return {"port": port, "frames": frames, "late": late, "max_ms": max_ms}


def test_frames_late_only_for_that_port(tracker, conn):
    for t in range(0, 61, 10):
        tracker.evaluate(T0 + t, _sample(insts=[_inst(27960, late=2), _inst(27961)]))
    ev = _kinds(conn, "frames_late")
    assert len(ev) == 1 and ev[0]["port"] == 27960 and ev[0]["scope"] == "instance"


def test_frames_late_by_gap(tracker, conn):
    for t in range(0, 61, 10):
        tracker.evaluate(T0 + t, _sample(insts=[_inst(27960, max_ms=150.0)]))
    assert len(_kinds(conn, "frames_late")) == 1


def test_frames_null_is_inactive(tracker, conn):
    for t in range(0, 61, 10):
        tracker.evaluate(T0 + t, _sample(insts=[_inst(27960, late=5)] if t < 30 else
                                         [_inst(27960, frames=None, late=None, max_ms=None)]))
    assert _kinds(conn, "frames_late") == []


def test_instance_new_and_gone(tracker, conn):
    tracker.evaluate(T0, _sample(insts=[_inst(27960)]))
    assert _kinds(conn) == []  # first call only initialises
    tracker.evaluate(T0 + 10, _sample(insts=[_inst(27960), _inst(27961)]))
    new = _kinds(conn, "instance_new")
    assert len(new) == 1 and new[0]["port"] == 27961 and new[0]["severity"] == "info"
    tracker.evaluate(T0 + 20, _sample(insts=[_inst(27960)]))
    gone = _kinds(conn, "instance_gone")
    assert len(gone) == 1 and gone[0]["port"] == 27961
    tracker.evaluate(T0 + 30, _sample(insts=[_inst(27960)]))
    assert len(_kinds(conn, "instance_gone")) == 1
