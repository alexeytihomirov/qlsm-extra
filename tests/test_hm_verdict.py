import importlib.util
from pathlib import Path

import pytest

pytestmark = pytest.mark.standalone

_PATH = Path(__file__).resolve().parent.parent / "addons" / "host-metrics" / "verdict.py"
_spec = importlib.util.spec_from_file_location("hm_verdict", _PATH)
hm_verdict = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(hm_verdict)
verdict = hm_verdict.verdict

MB = 1024 * 1024
SETTINGS = {"verdict_target_pct": 70, "mem_reserve_pct": 20,
            "steal_tight_pct": 5, "steal_overload_pct": 15}


def snap(**over):
    base = {
        "cores": 2,
        "mem_total": 4096 * MB,
        "mem_avail_now": 3000 * MB,
        "steal_p95": 0.0,
        "core_other_p95": {0: 5.0, 1: 5.0},
        "insts": [{"port": 27960, "core": 0, "busy_p95": 30.0, "rss_max": 90 * MB}],
        "events_24h": {},
        "events_24h_busy": {"frames_late": 0, "core_saturated": 0},
    }
    base.update(over)
    return base


def test_room_per_core_ok():
    r = verdict(snap(), SETTINGS, None)
    assert r["status"] == "ok"
    assert r["slots"] == 3
    assert r["ref_load"] == 30.0
    assert r["ref_source"] == "host"
    assert "room for 3" in r["reason"]


def test_reason_names_deciding_core_numbers():
    inp = snap(insts=[{"port": 1, "core": 0, "busy_p95": 31.0, "rss_max": 90 * MB},
                      {"port": 2, "core": 0, "busy_p95": 31.0, "rss_max": 90 * MB}],
               core_other_p95={0: 6.0, 1: 40.0})
    r = verdict(inp, SETTINGS, None)
    # core 0: (70-68)/31 = 0, core 1: (70-40)/31 = 0
    assert r["slots"] == 0
    assert r["status"] == "tight"
    assert "core 0: 2 x 31% + 6% other of 70%" in r["reason"]


def test_string_core_keys_and_string_free_numbers():
    r = verdict(snap(core_other_p95={"0": 5.0, "1": 5.0}), SETTINGS, None)
    assert r["slots"] == 3


def test_steal_tight_keeps_slots():
    r = verdict(snap(steal_p95=7), SETTINGS, None)
    assert r["status"] == "tight"
    assert r["slots"] == 3
    assert "steal p95 7% > 5%" in r["reason"]


def test_steal_overloaded():
    r = verdict(snap(steal_p95=16), SETTINGS, None)
    assert r["status"] == "overloaded"
    assert "steal p95 16% > 15%" in r["reason"]


def test_frames_late_overloaded():
    r = verdict(snap(events_24h_busy={"frames_late": 1, "core_saturated": 0}), SETTINGS, None)
    assert r["status"] == "overloaded"
    assert "frames_late 1" in r["reason"]


def test_core_saturated_overloaded():
    r = verdict(snap(events_24h_busy={"frames_late": 0, "core_saturated": 2}), SETTINGS, None)
    assert r["status"] == "overloaded"


def test_overloaded_beats_tight():
    r = verdict(snap(steal_p95=7, events_24h_busy={"frames_late": 1, "core_saturated": 0}),
                SETTINGS, None)
    assert r["status"] == "overloaded"


def test_memory_cap_gives_zero_slots_and_tight():
    r = verdict(snap(mem_avail_now=500 * MB), SETTINGS, None)
    # 500 - 0.2 * 4096 = negative -> 0
    assert r["slots"] == 0
    assert r["status"] == "tight"
    assert "memory" in r["reason"]


def test_memory_limits_below_cpu_slots():
    r = verdict(snap(mem_avail_now=950 * MB), SETTINGS, None)
    assert r["slots"] == 1  # mem (950-819.2)/90 = 1.45 -> 1, cpu 3
    assert "memory" in r["reason"]
    assert r["status"] == "ok"


def test_empty_host_caps_memory_with_a_150_mb_reference():
    # small VPS: 2 GB, 900 MB available; cpu would allow (70-5)/30 = 2 per core = 4
    inp = snap(insts=[], mem_total=2048 * MB, mem_avail_now=900 * MB)
    r = verdict(inp, SETTINGS, 30.0)
    # (900 - 0.2 * 2048) / 150 = 3.26 -> 3
    assert r["slots"] == 3
    assert r["status"] == "ok"
    assert "reference instance 150 MB" in r["reason"]
    r = verdict(snap(insts=[], mem_total=2048 * MB, mem_avail_now=500 * MB), SETTINGS, 30.0)
    assert r["slots"] == 0 and r["status"] == "tight" and "memory" in r["reason"]


def test_instance_without_rss_yet_uses_the_reference():
    inp = snap(insts=[{"port": 1, "core": 0, "busy_p95": 30.0, "rss_max": None}],
               mem_total=2048 * MB, mem_avail_now=800 * MB)
    r = verdict(inp, SETTINGS, None)
    assert r["slots"] == 2  # (800 - 409.6) / 150 = 2.6


def test_zero_cpu_slots_is_tight():
    inp = snap(core_other_p95={0: 5.0, 1: 60.0})
    r = verdict(inp, SETTINGS, None)
    # core0 (70-35)/30=1, core1 (70-60)/30=0
    assert r["slots"] == 1
    inp = snap(core_other_p95={0: 50.0, 1: 60.0})
    r = verdict(inp, SETTINGS, None)
    assert r["slots"] == 0
    assert r["status"] == "tight"
    assert "core 0" in r["reason"]


def test_unpinned_instance_counts_against_least_loaded_core():
    inp = snap(insts=[{"port": 1, "core": None, "busy_p95": 30.0, "rss_max": 90 * MB}],
               core_other_p95={0: 20.0, 1: 5.0})
    r = verdict(inp, SETTINGS, None)
    # lands on core 1: core0 (70-20)/30=1, core1 (70-35)/30=1
    assert r["slots"] == 2


def test_no_busy_samples_on_host_uses_fleet_median():
    inp = snap(insts=[{"port": 1, "core": 0, "busy_p95": None, "rss_max": 90 * MB}])
    r = verdict(inp, SETTINGS, 30.0)
    assert r["ref_source"] == "fleet"
    assert r["ref_load"] == 30.0
    assert r["slots"] == 3


def test_no_busy_samples_anywhere_gives_no_slot_count():
    inp = snap(insts=[{"port": 1, "core": 0, "busy_p95": None, "rss_max": 90 * MB}])
    r = verdict(inp, SETTINGS, None)
    assert r["slots"] is None
    assert r["status"] == "unknown"
    assert r["ref_load"] is None and r["ref_source"] is None
    assert "no data yet" in r["reason"]


def test_no_data_still_overloaded_by_steal_or_events():
    inp = snap(insts=[], steal_p95=16)
    r = verdict(inp, SETTINGS, None)
    assert r["status"] == "overloaded" and r["slots"] is None
    inp = snap(insts=[], steal_p95=7)
    r = verdict(inp, SETTINGS, None)
    assert r["status"] == "tight" and r["slots"] is None
    inp = snap(insts=[], events_24h_busy={"frames_late": 3, "core_saturated": 0})
    assert verdict(inp, SETTINGS, None)["status"] == "overloaded"


def test_settings_as_numbers_change_result():
    s = dict(SETTINGS, verdict_target_pct=50, steal_tight_pct=1)
    r = verdict(snap(steal_p95=2), s, None)
    # core0 (50-35)/30=0 -> 0 slots
    assert r["slots"] == 1  # core1 (50-5)/30=1
    assert r["status"] == "tight"
