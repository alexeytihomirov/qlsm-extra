"""Collector service for host-metrics: one sample every 10 s into the SQLite store.

Stdlib only (Python 3.10+). Runs as host-metrics.service. `Collector.tick()` reads
/proc, the instance cgroups and Redis, writes the sample and evaluates events.
"""
import argparse
import json
import sys
import time

import hm_events
import hm_readers
import hm_store

TICK_S = 10
AFFINITY_REFRESH_S = 60
DEFAULT_CONFIG = "/etc/host-metrics/config.json"
STATUS_KEY = "minqlx:server_status:%d"
FRAMES_KEY = "minqlx:frame_stats:%d"


def _log(msg):
    sys.stderr.write("host-metrics: %s\n" % msg)
    sys.stderr.flush()


def _rate(prev, cur, dt):
    """Per-second rate of a counter, None on the first sample or a counter reset."""
    if prev is None or cur is None or dt <= 0 or cur < prev:
        return None
    return (cur - prev) / dt


class Collector:
    def __init__(self, config, root="/", redis=None, clock=time.time,
                 affinity=hm_readers.read_affinity, disk=None, store=True,
                 mono=time.monotonic, redis_db_of=hm_readers.read_redis_db):
        self.config = config
        self.root = root
        self.clock = clock
        self.mono = mono   # deltas use this, never the wall clock (it can step)
        self.affinity = affinity
        self.redis_db_of = redis_db_of
        self.default_db = int(config.get("redis_db", 1))
        self.disk = disk or (lambda: hm_readers.read_disk("/"))
        if redis is None and config.get("redis_socket"):
            redis = hm_readers.RedisSocket(config["redis_socket"], self.default_db)
        self.redis = redis
        self.conn = None
        self.tracker = None
        self.started = int(self.clock())
        if store:
            self.conn = hm_store.open_db(config["db_path"])
            # events left open by a previous process are stale (R9)
            hm_store.close_all_open(self.conn, self.started)
            self.tracker = hm_events.EventTracker(self.conn, config.get("thresholds") or {})
        self._prev_ts = None
        self._prev_cpu = None
        self._prev_net = None
        self._prev_oom = None
        self._prev_inst = {}      # port -> (usage_usec, oom_kills)
        self._last_seq = {}       # port -> last frame_stats seq
        self._affinity = {}       # port -> (core, read at)
        self._redis_db = {}       # port -> (qlx_redisDatabase, read at); resolved values only
        self._last_roll = int(self.clock()) // 60

    # ---- host ----

    def _cores(self, dt):
        cur = hm_readers.read_cpu_times(self.root)
        prev = self._prev_cpu
        self._prev_cpu = cur
        rows = []
        for idx in sorted(cur, key=lambda i: (i != -1, i)):
            pct = None
            if prev is not None and idx in prev and dt > 0:
                pct = hm_readers.cpu_percent(prev[idx], cur[idx])
            row = {"core": idx}
            for k in hm_store.CORE_COLS:
                row[k] = None if pct is None else pct[k]
            rows.append(row)
        if not rows or rows[0]["core"] != -1:
            rows.insert(0, {"core": -1, **{k: None for k in hm_store.CORE_COLS}})
        return rows

    def _host(self, ts, dt):
        host = {k: None for k in hm_store.HOST_COLS}
        try:
            host["load1"] = hm_readers.read_load(self.root)
            host["psi10"] = hm_readers.read_psi_cpu_some10(self.root)
            mem = hm_readers.read_mem(self.root)
            host["mem_total"] = mem["total"]
            host["mem_avail"] = mem["available"]
            host["swap_used"] = mem["swap_used"]
        except (OSError, ValueError) as e:
            _log("mem/load read failed: %s" % e)
        try:
            d = self.disk()
            host["disk_used"], host["disk_total"] = d["used"], d["total"]
        except OSError as e:
            _log("disk read failed: %s" % e)
        net = None
        try:
            iface = hm_readers.default_iface(self.root)
            if iface:
                net = hm_readers.read_net(self.root, iface)
        except (OSError, KeyError, ValueError, IndexError) as e:
            _log("net read failed: %s" % e)
        prev = self._prev_net
        self._prev_net = net
        if net and prev:
            host["rx_bps"] = _rate(prev["rx_bytes"], net["rx_bytes"], dt)
            host["tx_bps"] = _rate(prev["tx_bytes"], net["tx_bytes"], dt)
            host["rx_pps"] = _rate(prev["rx_packets"], net["rx_packets"], dt)
            host["tx_pps"] = _rate(prev["tx_packets"], net["tx_packets"], dt)
        return host

    def _oom_delta(self):
        try:
            cur = hm_readers.read_oom_kills(self.root)
        except (OSError, ValueError):
            return 0
        prev, self._prev_oom = self._prev_oom, cur
        if prev is None or cur < prev:
            return 0
        return cur - prev

    # ---- instances ----

    def _redis_json(self, key, db):
        """Parsed JSON, None when the key is missing or unparsable. Raises OSError."""
        raw = self.redis.get(key, db)
        if raw is None:
            return None
        try:
            val = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            return None
        return val if isinstance(val, dict) else None

    def _core_of(self, port, now):
        cached = self._affinity.get(port)
        if cached and now - cached[1] < AFFINITY_REFRESH_S:
            return cached[0]
        try:
            core = self.affinity(port)
        except Exception as e:  # noqa: BLE001 - affinity is best effort
            _log("affinity %d failed: %s" % (port, e))
            core = None
        self._affinity[port] = (core, now)
        return core

    def _db_of(self, port, now):
        """The instance's own Redis db (qlsm gives each instance one), from its cmdline.

        Refreshed with the affinity, once a minute. Unknown (process not up yet,
        unreadable /proc) -> the config's redis_db for this tick, retried next tick.
        """
        cached = self._redis_db.get(port)
        if cached and now - cached[1] < AFFINITY_REFRESH_S:
            return cached[0]
        try:
            db = self.redis_db_of(self.root, port)
        except Exception as e:  # noqa: BLE001 - best effort, falls back to the config
            _log("redis db of %d failed: %s" % (port, e))
            db = None
        if db is None:
            self._redis_db.pop(port, None)
            return self.default_db
        self._redis_db[port] = (db, now)
        return db

    def _inst(self, port, now, dt, redis_ok):
        cg = hm_readers.read_instance(self.root, port)
        if cg is None:
            self._prev_inst.pop(port, None)
            return None
        prev = self._prev_inst.get(port)
        self._prev_inst[port] = (cg["usage_usec"], cg["oom_kills"])
        cpu = None
        oom_delta = 0
        if prev is not None:
            rate = _rate(prev[0], cg["usage_usec"], dt)
            if rate is not None:
                cpu = rate / 10000.0
            if cg["oom_kills"] >= prev[1]:
                oom_delta = cg["oom_kills"] - prev[1]
        row = {"port": port, "cpu": cpu, "mem": cg["mem_bytes"],
               "core": self._core_of(port, now), "players": None, "state": None,
               "map": None, "frames": None, "late": None, "max_ms": None,
               "p99_ms": None, "tick_ms": None, "oom_delta": oom_delta}
        if not (redis_ok and self.redis is not None):
            return row
        try:
            db = self._db_of(port, now)
            status = self._redis_json(STATUS_KEY % port, db)
            if status is not None:
                players = status.get("players")
                row["players"] = len(players) if isinstance(players, list) else None
                row["state"] = status.get("state")
                row["map"] = status.get("map")
            fs = self._redis_json(FRAMES_KEY % port, db)
            if fs is not None:
                seq = fs.get("seq")
                if seq != self._last_seq.get(port):
                    self._last_seq[port] = seq
                    for k in ("frames", "late", "max_ms", "p99_ms", "tick_ms"):
                        row[k] = fs.get(k)
        except OSError as e:
            _log("redis unavailable for port %d: %s" % (port, e))
            row["redis_failed"] = True
        return row

    def tick(self):
        now = self.mono()
        ts = int(self.clock())
        dt = None if self._prev_ts is None else now - self._prev_ts
        self._prev_ts = now
        # too short an interval (wake just before a boundary) gives garbage rates: skip them
        d = dt if dt is not None and dt >= TICK_S / 2 else 0

        cores = self._cores(d)
        host = self._host(ts, d)
        oom_delta = self._oom_delta()

        insts = []
        redis_ok = True
        ports = hm_readers.list_instances(self.root)
        for port in ports:
            row = self._inst(port, now, d, redis_ok)
            if row is None:
                continue
            if row.pop("redis_failed", False):
                redis_ok = False   # do not wait on the socket again this tick
            insts.append(row)
        for gone in set(self._prev_inst) - set(ports):
            self._prev_inst.pop(gone, None)
            self._last_seq.pop(gone, None)
            self._affinity.pop(gone, None)
            self._redis_db.pop(gone, None)

        sample = {"ts": ts, "host": host, "cores": cores, "insts": insts,
                  "oom_delta": oom_delta}
        if self.conn is not None:
            hm_store.insert_tick(self.conn, ts, host, cores, insts)
            self.tracker.evaluate(ts, sample)
        return sample

    # ---- loop ----

    def maintain(self, ts):
        """Rollup and retention, once per minute."""
        minute = int(ts) // 60
        if minute == self._last_roll or self.conn is None:
            return
        self._last_roll = minute
        hm_store.rollup(self.conn, ts)
        hm_store.prune(self.conn, ts)

    def run_forever(self):
        while True:
            try:
                now = self.clock()
                time.sleep(max(TICK_S - now % TICK_S, 0.01))
                self.tick()
                self.maintain(self.clock())
            except Exception as e:  # noqa: BLE001 - the service must never die
                _log("tick failed: %r" % (e,))
                time.sleep(1)


def main(argv=None):
    ap = argparse.ArgumentParser(description="host-metrics collector")
    ap.add_argument("--config", default=DEFAULT_CONFIG)
    ap.add_argument("--once", action="store_true", help="run one tick and exit")
    ap.add_argument("--dry-run", action="store_true",
                    help="with --once: print the sample as JSON, do not open the DB")
    args = ap.parse_args(argv)
    if args.dry_run and not args.once:
        ap.error("--dry-run needs --once")
    with open(args.config, "r", encoding="utf-8") as f:
        config = json.load(f)
    col = Collector(config, root=config.get("root", "/"), store=not args.dry_run)
    if args.once:
        sample = col.tick()
        if args.dry_run:
            print(json.dumps(sample, indent=2, sort_keys=True))
        return 0
    col.run_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
