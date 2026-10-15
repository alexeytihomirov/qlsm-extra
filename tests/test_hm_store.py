"""SQLite store: insert, minute rollup, retention, downsampled series, events."""
import sqlite3
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.standalone

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "addons" / "host-metrics" / "assets"))

import hm_store  # noqa: E402

T0 = 1_700_000_040  # multiple of 60


def _host(i):
    return {"load1": float(i % 6), "psi10": 0.0, "mem_total": 1000, "mem_avail": 500 + i % 6,
            "swap_used": 0, "disk_used": 10, "disk_total": 100,
            "rx_bps": 1.0, "tx_bps": 2.0, "rx_pps": 3.0, "tx_pps": 4.0, "oom_delta": 0}


def _tick(conn, i, ts=None, **inst):
    ts = T0 + 10 * i if ts is None else ts
    cores = [{"core": -1, "user": 10.0, "system": 5.0, "iowait": 0.0, "steal": float(i % 6),
              "busy": 10.0 + i % 6},
             {"core": 0, "user": 20.0, "system": 5.0, "iowait": 0.0, "steal": 0.0, "busy": 25.0}]
    base = {"port": 27960, "cpu": 50.0, "mem": 100, "core": 0, "players": 4,
            "state": "in_progress", "map": "x", "frames": 10, "late": 1, "max_ms": 5.0,
            "p99_ms": 3.0, "tick_ms": 4.0, "extra": 1}
    base.update(inst)
    hm_store.insert_tick(conn, ts, _host(i), cores, [base])


@pytest.fixture
def conn(tmp_path):
    c = hm_store.open_db(tmp_path / "m.db")
    yield c
    c.close()


def test_open_db_wal_version_and_readonly(tmp_path):
    p = tmp_path / "m.db"
    c = hm_store.open_db(p)
    assert c.execute("PRAGMA user_version").fetchone()[0] == 1
    assert c.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    _tick(c, 0)
    ro = hm_store.open_db(p, readonly=True)
    assert ro.execute("SELECT COUNT(*) FROM host_raw").fetchone()[0] == 1
    with pytest.raises(sqlite3.OperationalError):
        ro.execute("DELETE FROM host_raw")
    with pytest.raises(sqlite3.OperationalError):
        hm_store.open_db(tmp_path / "missing.db", readonly=True)
    assert not (tmp_path / "missing.db").exists()


def test_rollup_120_ticks_gives_20_minutes_with_avg_and_max(conn):
    for i in range(120):
        _tick(conn, i)
    assert hm_store.rollup(conn, T0 + 1200) == 20
    assert conn.execute("SELECT COUNT(*) FROM host_min").fetchone()[0] == 20
    h = conn.execute("SELECT load1, load1_max, mem_avail, mem_avail_min FROM host_min"
                     " WHERE ts=?", (T0,)).fetchone()
    assert h == (2.5, 5.0, 502.5, 500)
    c = conn.execute("SELECT steal, steal_max, busy, busy_max FROM core_min"
                     " WHERE ts=? AND core=-1", (T0,)).fetchone()
    assert c == (2.5, 5.0, 12.5, 15.0)
    assert conn.execute("SELECT COUNT(*) FROM core_min").fetchone()[0] == 40
    # idempotent
    assert hm_store.rollup(conn, T0 + 1200) == 0
    assert conn.execute("SELECT COUNT(*) FROM host_min").fetchone()[0] == 20


def test_rollup_skips_incomplete_minute(conn):
    for i in range(9):
        _tick(conn, i)
    assert hm_store.rollup(conn, T0 + 90) == 1
    assert hm_store.rollup(conn, T0 + 120) == 1  # the rest of minute 2, ticks 6-8 complete it


def test_busy_averaging_counts_only_busy_ticks(conn):
    for i in range(6):
        busy = i < 3
        _tick(conn, i, cpu=80.0 if busy else 10.0,
              state="in_progress" if busy else "warmup", players=4 if busy else 0)
    hm_store.rollup(conn, T0 + 60)
    r = conn.execute("SELECT busy_ticks, cpu_busy_avg, cpu_avg, cpu_max, frames, late,"
                     " players_max FROM inst_min").fetchone()
    assert r[0] == 3 and r[1] == 80.0 and r[2] == 45.0 and r[3] == 80.0
    assert r[4] == 60 and r[5] == 6 and r[6] == 4


def test_busy_requires_two_players_and_null_when_none(conn):
    for i in range(6):
        _tick(conn, i, players=1)
    hm_store.rollup(conn, T0 + 60)
    r = conn.execute("SELECT busy_ticks, cpu_busy_avg FROM inst_min").fetchone()
    assert r == (0, None)


def test_insert_tick_ignores_unknown_keys_and_nulls(conn):
    hm_store.insert_tick(conn, T0, {"load1": 1.0, "bogus": 1}, [],
                         [{"port": 27961, "state": None, "oom_delta": 2}])
    assert conn.execute("SELECT players, frames FROM inst_raw").fetchone() == (None, None)


def test_prune_drops_old_raw_keeps_minutes(conn):
    now = T0 + 3 * 86400
    for i in range(12):
        _tick(conn, i)
        _tick(conn, i, ts=now - 600 + 10 * i)
    hm_store.rollup(conn, now)
    hm_store.prune(conn, now)
    assert conn.execute("SELECT MIN(ts) FROM host_raw").fetchone()[0] >= now - 172800
    assert conn.execute("SELECT COUNT(*) FROM host_raw").fetchone()[0] == 12
    assert conn.execute("SELECT COUNT(*) FROM inst_raw").fetchone()[0] == 12
    assert conn.execute("SELECT COUNT(*) FROM host_min").fetchone()[0] >= 2
    hm_store.prune(conn, now + 31 * 86400)
    assert conn.execute("SELECT COUNT(*) FROM host_min").fetchone()[0] == 0


def test_series_30d_downsamples_to_max_points(conn):
    now = T0 + 43200 * 60
    with conn:
        conn.executemany("INSERT INTO host_min(ts, load1, load1_max, mem_avail_min)"
                         " VALUES (?,?,?,?)", [(T0 + 60 * i, 1.0, float(i), i)
                                               for i in range(43200)])
        conn.executemany("INSERT INTO core_min(ts, core, busy, busy_max) VALUES (?,?,?,?)",
                         [(T0 + 60 * i, -1, 1.0, 2.0) for i in range(43200)])
        conn.executemany("INSERT INTO inst_min(ts, port, cpu_avg) VALUES (?,?,?)",
                         [(T0 + 60 * i, 27960, 1.0) for i in range(43200)])
    s = hm_store.series(conn, now, "30d")
    assert s["res"] == "min"
    assert 0 < len(s["host"]) <= 600
    assert len(s["cores"]) <= 600 and len(s["insts"][27960]) <= 600
    assert max(r["load1_max"] for r in s["host"]) == 43199.0  # max kept as max
    assert min(r["mem_avail_min"] for r in s["host"]) == 0


def test_series_1h_port_filter_and_raw(conn):
    now = T0 + 600
    for i in range(60):
        _tick(conn, i)
        _tick(conn, i, port=27961)
    s = hm_store.series(conn, now, "1h", port=27960)
    assert s["res"] == "raw"
    assert list(s["insts"]) == [27960]
    assert len(s["insts"][27960]) == 60
    assert len(hm_store.series(conn, now, "1h")["insts"]) == 2
    assert {r["core"] for r in s["cores"]} == {-1, 0}
    with pytest.raises(ValueError):
        hm_store.series(conn, now, "2h")


def test_events_open_close_newest_first(conn):
    a = hm_store.insert_event(conn, 100, "steal_high", "host", None, "warn", "a")
    b = hm_store.insert_event(conn, 200, "instance_new", "instance", 27960, "info", "b")
    assert isinstance(a, int) and b != a
    hm_store.close_event(conn, a, 150)
    ev = hm_store.events(conn, 0)
    assert [e["id"] for e in ev] == [b, a]
    assert ev[1]["state"] == "closed" and ev[1]["closed_ts"] == 150
    assert ev[0]["state"] == "open" and ev[0]["port"] == 27960
    assert [e["id"] for e in hm_store.events(conn, 150)] == [b]


def test_downsample_keeps_spikes_and_sums_counts(conn):
    n = 1200
    with conn:
        conn.executemany(
            "INSERT INTO inst_raw(ts, port, max_ms, p99_ms, players, frames, late)"
            " VALUES (?,?,?,?,?,?,?)",
            [(T0 + 10 * i, 27960, 900.0 if i == 7 else 5.0, 50.0 if i == 7 else 3.0,
              4 if i == 7 else 1, 10, 1) for i in range(n)])
    rows = hm_store.series(conn, T0 + 10 * n, "6h", max_points=600)["insts"][27960]
    assert len(rows) == 600
    assert max(r["max_ms"] for r in rows) == 900.0
    assert max(r["p99_ms"] for r in rows) == 50.0
    assert sum(r["late"] for r in rows) == n
    assert sum(r["frames"] for r in rows) == 10 * n
