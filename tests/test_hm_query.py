"""Query CLI: snapshot input block for the verdict, series, events, error exits."""
import json
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.standalone

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "addons" / "host-metrics" / "assets"))

import hm_query  # noqa: E402
import hm_store  # noqa: E402

NOW = 1_700_000_040 + 3 * 86400  # multiple of 60
PORT = 27960
BUSY_FROM = NOW - 3 * 3600  # one busy hour: [BUSY_FROM, BUSY_FROM + 3600)
MB = 1024 * 1024


def _fill(path):
    conn = hm_store.open_db(path)
    host, core, inst = [], [], []
    for ts in range(NOW - 2 * 86400, NOW, 60):
        busy = BUSY_FROM <= ts < BUSY_FROM + 3600
        host.append((ts, 1.0, 0.0, 4096 * MB, 3000 * MB, 0, 10, 100, 1.0, 1.0, 1.0, 1.0, 2.0,
                     2900 * MB))
        core.append((ts, -1, 10.0, 5.0, 0.0, 1.0 if ts != NOW - 120 else 9.0, 12.0, 15.0, 2.0))
        core.append((ts, 0, 10.0, 5.0, 0.0, 0.0, 60.0 if busy else 20.0, 70.0, 0.0))
        core.append((ts, 1, 2.0, 1.0, 0.0, 0.0, 5.0, 8.0, 0.0))
        if busy:
            inst.append((ts, PORT, 50.0, 60.0, 90 * MB, 0, 4, 6, 50.0, 60, 0, 5.0, 3.0))
        elif ts == NOW - 20 * 3600:  # only 2 busy ticks: must not enter busy_p95
            inst.append((ts, PORT, 10.0, 12.0, 80 * MB, 0, 2, 2, 99.0, 60, 0, 5.0, 3.0))
        else:
            inst.append((ts, PORT, 10.0, 12.0, 80 * MB, 0, 0, 0, None, 60, 0, 5.0, 3.0))
    with conn:
        conn.executemany("INSERT INTO host_min(ts,load1,psi10,mem_total,mem_avail,swap_used,"
                         "disk_used,disk_total,rx_bps,tx_bps,rx_pps,tx_pps,load1_max,"
                         "mem_avail_min) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", host)
        conn.executemany("INSERT INTO core_min(ts,core,user,system,iowait,steal,busy,busy_max,"
                         "steal_max) VALUES (?,?,?,?,?,?,?,?,?)", core)
        conn.executemany("INSERT INTO inst_min(ts,port,cpu_avg,cpu_max,mem_max,core,players_max,"
                         "busy_ticks,cpu_busy_avg,frames,late,max_ms,p99_max)"
                         " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", inst)
    # last raw tick
    cores = [{"core": -1, "user": 10.0, "system": 5.0, "iowait": 0.0, "steal": 1.0, "busy": 15.0},
             {"core": 0, "user": 10.0, "system": 5.0, "iowait": 0.0, "steal": 0.0, "busy": 20.0}]
    insts = [{"port": PORT, "cpu": 11.0, "mem": 81 * MB, "core": 0, "players": 0,
              "state": "warmup", "map": "campgrounds", "frames": 10, "late": 0,
              "max_ms": 4.0, "p99_ms": 3.0, "tick_ms": 4.0},
             {"port": 27961, "cpu": 1.0, "mem": 50 * MB, "core": 1, "players": 0,
              "state": "warmup", "map": "x", "frames": 10, "late": 0, "max_ms": 4.0,
              "p99_ms": 3.0, "tick_ms": 4.0}]
    host_row = {"load1": 1.0, "psi10": 0.0, "mem_total": 4096 * MB, "mem_avail": 3100 * MB,
                "swap_used": 0, "disk_used": 10, "disk_total": 100, "rx_bps": 1.0,
                "tx_bps": 1.0, "rx_pps": 1.0, "tx_pps": 1.0}
    hm_store.insert_tick(conn, NOW - 5, host_row, cores, insts)
    # an instance that stopped long ago must not show in the last rows
    hm_store.insert_tick(conn, NOW - 3600, None, None,
                         [{"port": 27999, "cpu": 1.0, "mem": 1, "core": 1, "players": 0,
                           "state": "warmup", "map": "x"}])
    hm_store.insert_event(conn, NOW - 150 * 60, "frames_late", "instance", PORT, "warn", "busy")
    hm_store.insert_event(conn, NOW - 10 * 3600, "frames_late", "instance", PORT, "warn", "idle")
    hm_store.insert_event(conn, NOW - 150 * 60, "core_saturated", "core", None, "warn", "c0")
    hm_store.insert_event(conn, NOW - 10 * 3600, "core_saturated", "core", None, "warn", "idle")
    hm_store.insert_event(conn, NOW - 5 * 3600, "steal_high", "host", None, "warn", "steal")
    hm_store.insert_event(conn, NOW - 40 * 3600, "frames_late", "instance", PORT, "warn", "old")
    conn.close()


@pytest.fixture
def db(tmp_path):
    p = tmp_path / "m.db"
    _fill(p)
    return p


def _run(capsys, *argv):
    code = hm_query.main(list(argv))
    out = capsys.readouterr().out
    return code, json.loads(out)


def test_snapshot_input_block(db, capsys):
    code, s = _run(capsys, "--db", str(db), "--now", str(NOW), "snapshot")
    assert code == 0
    assert s["version"] == "unknown" or isinstance(s["version"], str)
    assert s["now"] == NOW
    assert s["cores"] == 2
    assert s["mem_total"] == 4096 * MB
    assert s["mem_avail_now"] == 3100 * MB
    assert s["steal_p95"] == 1.0
    # core 0: busy 20 - cpu_avg 10 = 10 normally, 60 - 50 = 10 in the busy hour; core 1: 5
    assert s["core_other_p95"] == {"0": 10.0, "1": 5.0}
    # 27961 is running now (raw row 5 s ago) without minute history; 27999 stopped an hour ago
    assert s["insts"] == [{"port": PORT, "core": 0, "busy_p95": 50.0, "rss_max": 90 * MB,
                           "late_24h": 0, "frames_24h": 60 * 1440},
                          {"port": 27961, "core": 1, "busy_p95": None, "rss_max": None,
                           "late_24h": 0, "frames_24h": 0}]
    assert s["events_24h"] == {"frames_late": 2, "core_saturated": 2, "steal_high": 1}
    assert s["events_24h_busy"] == {"frames_late": 1, "core_saturated": 1}


def test_snapshot_core_p95_24h_includes_all_cores_key(db, capsys):
    _, s = _run(capsys, "--db", str(db), "--now", str(NOW), "snapshot")
    # JSON keys are strings; -1 is the all-cores row. Core 0 is busy (60) for 60 of the
    # 1440 minutes in the window, which is under 5 %, so its nearest-rank p95 is 20.
    assert s["core_p95_24h"] == {"-1": 12.0, "0": 20.0, "1": 5.0}


def test_snapshot_late_and_frames_24h_sum_the_window_only(tmp_path, capsys):
    p = tmp_path / "m.db"
    conn = hm_store.open_db(p)
    rows = [(NOW - 30 * 3600, PORT, 1.0, 1.0, MB, 0, 0, 0, None, 1000, 500, 1.0, 1.0),  # outside
            (NOW - 3600, PORT, 1.0, 1.0, MB, 0, 0, 0, None, 600, 6, 1.0, 1.0),
            (NOW - 1800, PORT, 1.0, 1.0, MB, 0, 0, 0, None, 600, 4, 1.0, 1.0),
            (NOW - 1800, 27961, 1.0, 1.0, MB, 1, 0, 0, None, 600, None, 1.0, 1.0)]
    with conn:
        conn.executemany("INSERT INTO inst_min(ts,port,cpu_avg,cpu_max,mem_max,core,players_max,"
                         "busy_ticks,cpu_busy_avg,frames,late,max_ms,p99_max)"
                         " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    hm_store.insert_tick(conn, NOW - 30, None, None,
                         [{"port": PORT, "cpu": 1.0, "mem": 1, "core": 0},
                          {"port": 27961, "cpu": 1.0, "mem": 1, "core": 1}])
    conn.close()
    _, s = _run(capsys, "--db", str(p), "--now", str(NOW), "snapshot")
    by_port = {i["port"]: i for i in s["insts"]}
    assert (by_port[PORT]["late_24h"], by_port[PORT]["frames_24h"]) == (10, 1200)
    assert (by_port[27961]["late_24h"], by_port[27961]["frames_24h"]) == (0, 600)
    assert s["core_p95_24h"] == {}


def test_snapshot_only_ports_running_in_the_last_10_minutes(tmp_path, capsys):
    p = tmp_path / "m.db"
    conn = hm_store.open_db(p)
    # both ports have a busy week behind them; 27961 was moved off this host 11 minutes ago
    rows = [(NOW - 3600, port, 50.0, 60.0, 90 * MB, core, 4, 6, 50.0, 60, 0, 5.0, 3.0)
            for port, core in ((PORT, 0), (27961, 1))]
    with conn:
        conn.executemany("INSERT INTO inst_min(ts,port,cpu_avg,cpu_max,mem_max,core,players_max,"
                         "busy_ticks,cpu_busy_avg,frames,late,max_ms,p99_max)"
                         " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    hm_store.insert_tick(conn, NOW - 660, None, None, [{"port": 27961, "cpu": 1.0, "mem": 1, "core": 1}])
    hm_store.insert_tick(conn, NOW - 590, None, None, [{"port": PORT, "cpu": 1.0, "mem": 1, "core": 0}])
    conn.close()
    _, s = _run(capsys, "--db", str(p), "--now", str(NOW), "snapshot")
    assert [i["port"] for i in s["insts"]] == [PORT]
    assert s["insts"][0]["busy_p95"] == 50.0  # the load reference still uses the 7-day minutes


def test_snapshot_data_age(db, tmp_path, capsys):
    _, s = _run(capsys, "--db", str(db), "--now", str(NOW), "snapshot")
    assert s["data_age_s"] == 5
    _, s = _run(capsys, "--db", str(db), "--now", str(NOW + 600), "snapshot")
    assert s["data_age_s"] == 605
    p = tmp_path / "e.db"
    hm_store.open_db(p).close()
    _, s = _run(capsys, "--db", str(p), "--now", str(NOW), "snapshot")
    assert s["data_age_s"] is None


def test_snapshot_last_rows(db, capsys):
    _, s = _run(capsys, "--db", str(db), "--now", str(NOW), "snapshot")
    assert s["host"]["ts"] == NOW - 5
    assert s["host"]["mem_avail"] == 3100 * MB
    assert [c["core"] for c in s["cores_last"]] == [-1, 0]
    assert [i["port"] for i in s["insts_last"]] == [PORT, 27961]
    assert s["insts_last"][0]["map"] == "campgrounds"


def test_snapshot_feeds_the_verdict(db, capsys):
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "hm_verdict", REPO / "addons" / "host-metrics" / "verdict.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _, s = _run(capsys, "--db", str(db), "--now", str(NOW), "snapshot")
    r = mod.verdict(s, {}, None)
    assert r["ref_load"] == 50.0
    assert r["status"] == "overloaded"  # frames_late with players on


def test_snapshot_busy_event_at_the_unrolled_minute(tmp_path, capsys):
    p = tmp_path / "m.db"
    conn = hm_store.open_db(p)
    ts = NOW - 30
    hm_store.insert_tick(conn, ts, None, None,
                         [{"port": PORT, "cpu": 50.0, "mem": 1, "core": 0, "players": 4,
                           "state": "in_progress"}])
    hm_store.insert_event(conn, ts, "frames_late", "instance", PORT, "warn", "m")
    conn.close()
    _, s = _run(capsys, "--db", str(p), "--now", str(NOW), "snapshot")
    assert s["events_24h_busy"]["frames_late"] == 1


def test_series_and_port_filter(db, capsys):
    code, r = _run(capsys, "--db", str(db), "--now", str(NOW), "series", "--range", "24h")
    assert code == 0
    assert r["res"] == "min" and r["range"] == "24h"
    assert PORT == r["insts"][str(PORT)][0]["port"]
    code, r = _run(capsys, "--db", str(db), "--now", str(NOW), "series", "--range", "1h",
                   "--port", str(PORT))
    assert r["res"] == "raw"
    assert list(r["insts"]) == [str(PORT)]


def test_events_range(db, capsys):
    code, r = _run(capsys, "--db", str(db), "--now", str(NOW), "events", "--range", "24h")
    assert code == 0
    assert len(r["events"]) == 5
    assert r["events"][0]["ts"] >= r["events"][-1]["ts"]
    code, r = _run(capsys, "--db", str(db), "--now", str(NOW), "events", "--range", "7d")
    assert len(r["events"]) == 6


def test_bad_range_and_unknown_args_exit_2(db):
    for argv in (["--db", str(db), "series", "--range", "2h"],
                 ["--db", str(db), "events"],
                 ["--db", str(db), "bogus"],
                 ["--db", str(db), "snapshot", "--what"]):
        with pytest.raises(SystemExit) as e:
            hm_query.main(argv)
        assert e.value.code == 2


def test_missing_db_exit_3(tmp_path, capsys):
    p = tmp_path / "nope.db"
    code, r = _run(capsys, "--db", str(p), "snapshot")
    assert code == 3
    assert r["error"] == "no_data" and "version" in r
    assert not p.exists()


def test_db_without_schema_exit_3(tmp_path, capsys):
    import sqlite3
    p = tmp_path / "empty.db"
    sqlite3.connect(str(p)).close()
    code, r = _run(capsys, "--db", str(p), "snapshot")
    assert code == 3 and r["error"] == "no_data"


def test_empty_store_snapshot_has_no_load(tmp_path, capsys):
    p = tmp_path / "m.db"
    hm_store.open_db(p).close()
    code, s = _run(capsys, "--db", str(p), "--now", str(NOW), "snapshot")
    assert code == 0
    assert s["host"] is None and s["insts"] == [] and s["steal_p95"] is None
    assert s["events_24h_busy"] == {"frames_late": 0, "core_saturated": 0}


def test_version_file(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(hm_query, "__file__", str(tmp_path / "hm_query.py"))
    assert hm_query._version() == "unknown"
    (tmp_path / "VERSION").write_text("1.2.3\n")
    code, r = _run(capsys, "--db", str(tmp_path / "nope.db"), "snapshot")
    assert code == 3 and r["version"] == "1.2.3"


def test_snapshot_hardware_from_store(db, capsys):
    conn = hm_store.open_db(db)
    hm_store.set_hardware(conn, NOW, {"cpu_model": "AMD EPYC-Rome Processor", "vcpus": 2})
    conn.close()
    code, s = _run(capsys, "--db", str(db), "--now", str(NOW), "snapshot")
    assert code == 0
    assert s["hardware"] == {"cpu_model": "AMD EPYC-Rome Processor", "vcpus": 2}


def test_snapshot_hardware_none_before_first_read(db, capsys):
    code, s = _run(capsys, "--db", str(db), "--now", str(NOW), "snapshot")
    assert code == 0 and s["hardware"] is None
