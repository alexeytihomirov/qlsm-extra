"""Collector loop: tick() on a fixture tree with advancing counters, fake Redis and clock."""
import json
import shutil
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.standalone

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "addons" / "host-metrics" / "assets"))

import hm_collect  # noqa: E402
import hm_readers  # noqa: E402
import hm_store  # noqa: E402

FIXTURE = REPO / "tests" / "fixtures" / "host-metrics" / "germany"
SLICE = "sys/fs/cgroup/system.slice/system-qlds.slice"
T0 = 1_700_000_000


class FakeRedis:
    """Keys per logical db; `data` is db 1 (port 27960 of the fixture runs on db 1)."""

    def __init__(self):
        self.dbs = {1: {}}
        self.data = self.dbs[1]
        self.down = False

    def get(self, key, db):
        if self.down:
            raise OSError("redis down")
        v = self.dbs.get(db, {}).get(key)
        return None if v is None else (v if isinstance(v, bytes) else json.dumps(v).encode())


class Env:
    def __init__(self, tmp_path):
        self.root = tmp_path / "root"
        shutil.copytree(FIXTURE, self.root)
        self.now = float(T0)
        self.mono_now = 1000.0
        self.redis = FakeRedis()
        self.db = tmp_path / "m.db"
        self.usage = 1_000_000_000
        self._write_usage(27960, self.usage)

    def clock(self):
        return self.now

    def mono(self):
        return self.mono_now

    def collector(self, store=True):
        cfg = {"db_path": str(self.db), "thresholds": {}}
        return hm_collect.Collector(
            cfg, root=str(self.root), redis=self.redis, clock=self.clock, mono=self.mono,
            affinity=lambda port: 1, disk=lambda: {"used": 10, "total": 100}, store=store)

    def _inst_dir(self, port):
        return self.root / SLICE / ("qlds@%d.service" % port)

    def _write_usage(self, port, usec):
        d = self._inst_dir(port)
        d.mkdir(parents=True, exist_ok=True)
        (d / "cpu.stat").write_text("usage_usec %d\nuser_usec 1\n" % usec)
        (d / "memory.current").write_text("90624000\n")
        (d / "memory.events").write_text("low 0\nhigh 0\nmax 0\noom 0\noom_kill 0\n")

    def advance(self, seconds=10, usage_s=None, port=27960):
        self.now += seconds
        self.mono_now += seconds
        if usage_s is not None:
            self.usage += int(usage_s * 1_000_000)
            self._write_usage(port, self.usage)

    def set_usage(self, usec, port=27960):
        self.usage = usec
        self._write_usage(port, usec)

    def remove_instance(self, port):
        shutil.rmtree(self._inst_dir(port))

    def set_redis_db(self, port, db, pid):
        """The unit's process as qlsm starts it: `+set qlx_redisDatabase <db>` in its argv."""
        (self._inst_dir(port) / "cgroup.procs").write_text("%d\n" % pid)
        d = self.root / "proc" / str(pid)
        d.mkdir(parents=True, exist_ok=True)
        argv = ["qzeroded.x64", "+set", "net_port", str(port),
                "+set", "qlx_redisDatabase", str(db)]
        (d / "cmdline").write_bytes(b"\0".join(a.encode() for a in argv) + b"\0")


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


def _inst(sample, port=27960):
    return next(i for i in sample["insts"] if i["port"] == port)


def test_first_tick_has_no_rates_second_has_rates(env):
    col = env.collector()
    s1 = col.tick()
    assert s1["ts"] == T0
    assert s1["cores"][0]["core"] == -1
    assert s1["cores"][0]["busy"] is None
    assert s1["host"]["rx_bps"] is None
    assert _inst(s1)["cpu"] is None
    assert s1["host"]["mem_total"] > 0 and s1["host"]["disk_total"] == 100
    env.advance(10, usage_s=1)
    # advance the aggregate cpu line so a rate exists
    stat = env.root / "proc/stat"
    lines = stat.read_text().splitlines()
    lines[0] = "cpu  48075331 59663 19512832 883475785 688454 0 3228592 0 0 0"
    stat.write_text("\n".join(lines) + "\n")
    s2 = col.tick()
    assert s2["cores"][0]["core"] == -1
    assert s2["cores"][0]["busy"] == pytest.approx(10.0)
    assert _inst(s2)["cpu"] == pytest.approx(10.0)
    rows = col.conn.execute("SELECT COUNT(*) FROM inst_raw").fetchone()[0]
    assert rows == 2


def test_instance_cpu_percent_of_one_core(env):
    col = env.collector()
    col.tick()
    env.advance(10, usage_s=5)
    assert _inst(col.tick())["cpu"] == pytest.approx(50.0)
    env.advance(10, usage_s=20)
    assert _inst(col.tick())["cpu"] == pytest.approx(200.0)


def test_tick_after_counter_reset_skips_rate(env):
    col = env.collector()
    col.tick()
    env.advance(10, usage_s=5)
    col.tick()
    env.advance(10)
    env.set_usage(1_000_000)  # instance restarted: counter dropped
    s = col.tick()
    assert _inst(s)["cpu"] is None
    env.advance(10, usage_s=2)
    assert _inst(col.tick())["cpu"] == pytest.approx(20.0)
    # host reboot: /proc/stat drops
    stat = env.root / "proc/stat"
    lines = stat.read_text().splitlines()
    lines[0] = "cpu  10 0 10 100 0 0 0 0 0 0"
    stat.write_text("\n".join(lines) + "\n")
    env.advance(10)
    s = col.tick()
    assert all(c["busy"] is None for c in s["cores"] if c["core"] == -1)
    for c in s["cores"]:
        assert c["busy"] is None or 0 <= c["busy"] <= 100


def test_dry_run_prints_sample_without_db(env, tmp_path, capsys, monkeypatch):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"db_path": str(env.db), "root": str(env.root), "redis_socket": None, "thresholds": {}}))
    monkeypatch.setattr(hm_collect.hm_readers, "read_disk", lambda p="/": {"used": 1, "total": 2})
    rc = hm_collect.main(["--config", str(cfg), "--once", "--dry-run"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert {"ts", "host", "cores", "insts", "oom_delta"} <= set(out)
    assert not env.db.exists()


def test_tick_without_redis_keys_writes_nulls(env):
    col = env.collector()
    s = col.tick()
    i = _inst(s)
    assert i["players"] is None and i["state"] is None and i["frames"] is None
    row = col.conn.execute("SELECT players, state, map, frames, mem FROM inst_raw").fetchone()
    assert row[:4] == (None, None, None, None) and row[4] == 90624000
    # redis unreachable: still a row, nulls, loop keeps running
    env.redis.down = True
    env.advance(10)
    s = col.tick()
    assert _inst(s)["players"] is None and _inst(s)["frames"] is None
    assert col.conn.execute("SELECT COUNT(*) FROM inst_raw").fetchone()[0] == 2


def test_players_state_and_map_from_server_status(env):
    env.redis.data["minqlx:server_status:27960"] = {
        "players": [{"name": "a"}, {"name": "b"}], "maxplayers": 16,
        "state": "in_progress", "map": "campgrounds"}
    s = env.collector().tick()
    i = _inst(s)
    assert (i["players"], i["state"], i["map"]) == (2, "in_progress", "campgrounds")


def test_frame_stats_only_when_seq_changes(env):
    key = "minqlx:frame_stats:27960"
    env.redis.data[key] = {"seq": 1, "frames": 500, "late": 3, "max_ms": 40.0,
                           "p99_ms": 12.0, "tick_ms": 8.0}
    col = env.collector()
    i1 = _inst(col.tick())
    assert (i1["frames"], i1["late"], i1["max_ms"], i1["tick_ms"]) == (500, 3, 40.0, 8.0)
    env.advance(10)
    i2 = _inst(col.tick())
    assert i2["frames"] is None and i2["late"] is None and i2["p99_ms"] is None
    env.redis.data[key]["seq"] = 2
    env.advance(10)
    assert _inst(col.tick())["frames"] == 500


def test_two_instances_read_their_own_redis_db(env):
    env._write_usage(27961, 5_000_000)
    env.set_redis_db(27961, 2, 5151)
    env.redis.dbs[1]["minqlx:server_status:27960"] = {
        "players": [{"name": "a"}], "state": "warmup", "map": "campgrounds"}
    env.redis.dbs[1]["minqlx:frame_stats:27960"] = {"seq": 1, "frames": 400, "late": 1}
    env.redis.dbs[2] = {
        "minqlx:server_status:27961": {"players": [{"name": "b"}, {"name": "c"}, {"name": "d"}],
                                       "state": "in_progress", "map": "toxicity"},
        "minqlx:frame_stats:27961": {"seq": 7, "frames": 500, "late": 9},
        # a stale key of the other port in the wrong db must not be read
        "minqlx:server_status:27960": {"players": [], "state": "x", "map": "wrong"},
    }
    s = env.collector().tick()
    a, b = _inst(s, 27960), _inst(s, 27961)
    assert (a["players"], a["map"], a["frames"], a["late"]) == (1, "campgrounds", 400, 1)
    assert (b["players"], b["state"], b["map"], b["frames"], b["late"]) == (
        3, "in_progress", "toxicity", 500, 9)


def test_redis_db_falls_back_to_config_and_refreshes_with_affinity(env):
    env._write_usage(27961, 5_000_000)  # no cgroup.procs: db unknown
    env.redis.dbs[4] = {"minqlx:server_status:27961": {"players": [], "state": "warmup", "map": "a"}}
    env.redis.dbs[5] = {"minqlx:server_status:27961": {"players": [], "state": "warmup", "map": "b"}}
    col = hm_collect.Collector(
        {"db_path": str(env.db), "thresholds": {}, "redis_db": 4}, root=str(env.root),
        redis=env.redis, clock=env.clock, mono=env.mono, affinity=lambda port: 1,
        disk=lambda: {"used": 10, "total": 100})
    assert _inst(col.tick(), 27961)["map"] == "a"
    env.set_redis_db(27961, 5, 5151)
    env.advance(10)
    assert _inst(col.tick(), 27961)["map"] == "b"  # a fallback is not cached
    env.set_redis_db(27961, 4, 5151)
    env.advance(10)
    assert _inst(col.tick(), 27961)["map"] == "b"  # a resolved db is cached ...
    env.advance(60)
    assert _inst(col.tick(), 27961)["map"] == "a"  # ... until the minute refresh


def test_instance_appears_and_disappears(env):
    col = env.collector()
    col.tick()
    env._write_usage(27961, 5_000_000)
    env.advance(10)
    s = col.tick()
    assert _inst(s, 27961)["cpu"] is None  # no rate on the first tick
    env.remove_instance(27961)
    env.advance(10)
    s = col.tick()
    assert [i["port"] for i in s["insts"]] == [27960]
    kinds = [(e["kind"], e["port"]) for e in hm_store.events(col.conn, 0)]
    assert sorted(kinds) == [("instance_gone", 27961), ("instance_new", 27961)]


def test_oom_delta_at_top_level_and_event(env):
    col = env.collector()
    assert col.tick()["oom_delta"] == 0
    vm = env.root / "proc/vmstat"
    text = vm.read_text()
    assert "oom_kill 0" in text
    vm.write_text(text.replace("oom_kill 0", "oom_kill 2"))
    env.advance(10)
    s = col.tick()
    assert s["oom_delta"] == 2
    assert [e["kind"] for e in hm_store.events(col.conn, 0)] == ["oom_kill"]


def test_startup_closes_stale_open_events(env):
    conn = hm_store.open_db(env.db)
    hm_store.insert_event(conn, T0 - 100, "mem_low", "host", None, "warn", "stale")
    conn.close()
    col = env.collector()
    ev = hm_store.events(col.conn, 0)
    assert ev[0]["state"] == "closed" and ev[0]["closed_ts"] == T0


def test_maintain_rolls_up_once_a_minute(env):
    col = env.collector()
    for _ in range(7):
        col.tick()
        env.advance(10)
    col.maintain(env.now)
    assert col.conn.execute("SELECT COUNT(*) FROM host_min").fetchone()[0] >= 1


def _net_bump(env, nbytes):
    p = env.root / "proc/net/dev"
    p.write_text(p.read_text().replace("29897441311", str(29897441311 + nbytes)))


def test_wall_clock_step_back_does_not_inflate_rates(env):
    col = env.collector()
    col.tick()
    env.advance(10, usage_s=5)
    _net_bump(env, 10_000)
    env.now -= 19.9  # wall clock stepped back 9.9 s net while monotonic advanced 10 s
    s = col.tick()
    assert _inst(s)["cpu"] == pytest.approx(50.0)
    assert s["host"]["rx_bps"] == pytest.approx(1000.0)


def test_short_interval_skips_rates(env):
    col = env.collector()
    col.tick()
    env.advance(1, usage_s=5)
    _net_bump(env, 10_000)
    s = col.tick()
    assert _inst(s)["cpu"] is None
    assert s["host"]["rx_bps"] is None
    assert all(c["busy"] is None for c in s["cores"])
    env.advance(10, usage_s=5)
    assert _inst(col.tick())["cpu"] == pytest.approx(50.0)


# ---- hardware (B4) ----

def test_hardware_read_on_first_tick_and_hourly(env):
    col = env.collector()
    col.tick()
    hw = hm_store.get_hardware(col.conn)
    assert hw["cpu_model"] == "AMD EPYC-Rome Processor" and hw["provider"] == "Hetzner"
    (env.root / "sys/class/dmi/id/sys_vendor").write_text("Vultr\n")
    env.advance(10)
    col.tick()
    assert hm_store.get_hardware(col.conn)["provider"] == "Hetzner"   # not re-read yet
    env.advance(3600)
    col.tick()
    assert hm_store.get_hardware(col.conn)["provider"] == "Vultr"


def test_hardware_failure_never_breaks_tick_and_logs_once(env, monkeypatch, capsys):
    def boom(root="/"):
        raise RuntimeError("no hw")
    monkeypatch.setattr(hm_readers, "read_hardware", boom)
    col = env.collector()
    assert col.tick()["ts"] == T0
    env.advance(3600)
    assert col.tick()["ts"] == T0 + 3600
    assert capsys.readouterr().err.count("hardware read failed") == 1
    assert hm_store.get_hardware(col.conn) is None


def test_hardware_failure_retries_next_minute_not_hourly_and_logs_per_state_change(
        env, monkeypatch, capsys):
    calls = []
    real = hm_readers.read_hardware

    def flaky(root="/"):
        calls.append(1)
        if len(calls) <= 2:
            raise RuntimeError("transient")
        return real(root)

    monkeypatch.setattr(hm_readers, "read_hardware", flaky)
    col = env.collector()
    col.tick()
    assert len(calls) == 1
    env.advance(10)
    col.tick()
    assert len(calls) == 1                       # not retried every tick
    env.advance(60)
    col.tick()
    assert len(calls) == 2 and hm_store.get_hardware(col.conn) is None
    env.advance(60)
    col.tick()                                    # third attempt succeeds, well before an hour
    assert len(calls) == 3 and hm_store.get_hardware(col.conn)["provider"] == "Hetzner"
    err = capsys.readouterr().err
    assert err.count("hardware read failed") == 1  # second failure is the same state
    env.advance(120)
    col.tick()
    assert len(calls) == 3                        # hourly again after success
