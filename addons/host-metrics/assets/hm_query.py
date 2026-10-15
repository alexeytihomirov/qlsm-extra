#!/usr/bin/env python3
"""Query CLI of host-metrics: prints one JSON object read from the collector's SQLite DB.

    hm_query.py [--db PATH] snapshot
    hm_query.py [--db PATH] series --range R [--port N]
    hm_query.py [--db PATH] events --range R
    hm_query.py [--db PATH] events --since TS

Exit 0 on success, 2 on bad arguments (argparse), 3 when there is no usable DB
(`{"version": ..., "error": "no_data"}`). Stdlib only. The DB is opened read-only
because the collector writes it concurrently.
"""
import argparse
import json
import math
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import hm_store  # noqa: E402

DEFAULT_DB = "/var/lib/host-metrics/metrics.db"
LOOKBACK_S = 7 * 86400
CURRENT_S = 600  # an instance counts in the verdict only when it has a raw row this recent
EVENTS_WINDOW_S = 86400
BUSY_MIN_TICKS = 3
BUSY_EVENT_KINDS = ("frames_late", "core_saturated")


def _version():
    try:
        text = (Path(__file__).resolve().parent / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return "unknown"
    return text or "unknown"


def _p95(values):
    """Nearest-rank 95th percentile, None for an empty list."""
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return None
    return vals[max(math.ceil(0.95 * len(vals)) - 1, 0)]


def _rows(conn, sql, args=()):
    cur = conn.execute(sql, args)
    names = [d[0] for d in cur.description]
    return [dict(zip(names, r)) for r in cur.fetchall()]


def _busy_minutes(conn, since):
    """Minutes (floored to 60 s) in which some instance had players on in a running match."""
    minutes = {r[0] for r in conn.execute(
        "SELECT DISTINCT ts FROM inst_min WHERE ts>=? AND busy_ticks>0", (since,))}
    # the newest minute is not rolled up yet, so look at the raw rows as well
    minutes.update(r[0] for r in conn.execute(
        "SELECT DISTINCT ts/60*60 FROM inst_raw WHERE ts>=? AND state='in_progress'"
        " AND players>=2", (since,)))
    return minutes


def _events_24h(conn, now):
    since = now - EVENTS_WINDOW_S
    busy = _busy_minutes(conn, since - 60)
    total = {}
    busy_counts = {k: 0 for k in BUSY_EVENT_KINDS}
    for ts, kind in conn.execute("SELECT ts, kind FROM events WHERE ts>=?", (since,)):
        total[kind] = total.get(kind, 0) + 1
        if kind in busy_counts and ts // 60 * 60 in busy:
            busy_counts[kind] += 1
    return total, busy_counts


def _core_other_p95(conn, since):
    """Per core: p95 of per-minute core busy minus the cpu_avg of instances pinned to it."""
    pinned = {}
    for ts, core, cpu in conn.execute(
            "SELECT ts, core, cpu_avg FROM inst_min WHERE ts>=? AND core IS NOT NULL", (since,)):
        key = (ts, core)
        pinned[key] = pinned.get(key, 0.0) + (cpu or 0.0)
    per_core = {}
    for ts, core, busy in conn.execute(
            "SELECT ts, core, busy FROM core_min WHERE ts>=? AND core>=0 AND busy IS NOT NULL",
            (since,)):
        per_core.setdefault(core, []).append(max(busy - pinned.get((ts, core), 0.0), 0.0))
    return {c: _p95(v) for c, v in sorted(per_core.items())}


def _core_p95_24h(conn, now):
    """Per core (-1 = all): p95 of the per-minute busy average over the last 24 h."""
    per_core = {}
    for core, busy in conn.execute(
            "SELECT core, busy FROM core_min WHERE ts>=? AND busy IS NOT NULL",
            (now - EVENTS_WINDOW_S,)):
        per_core.setdefault(core, []).append(busy)
    return {c: _p95(v) for c, v in sorted(per_core.items())}


def _frames_24h(conn, now):
    """Per port: (late, frames) summed over the minute rows of the last 24 h."""
    return {port: (late or 0, frames or 0) for port, late, frames in conn.execute(
        "SELECT port, SUM(late), SUM(frames) FROM inst_min WHERE ts>=? GROUP BY port",
        (now - EVENTS_WINDOW_S,))}


def _inst_block(conn, since, now):
    """Instances running now (a raw row in the last CURRENT_S); their load references
    (busy_p95, rss_max) still come from the 7-day minute rows."""
    current = {port: core for port, core, _ts in conn.execute(
        "SELECT port, core, MAX(ts) FROM inst_raw WHERE ts>=? GROUP BY port",
        (now - CURRENT_S,))}
    out = []
    frames = _frames_24h(conn, now)
    for port in sorted(current):
        late_24h, frames_24h = frames.get(port, (0, 0))
        busy = [r[0] for r in conn.execute(
            "SELECT cpu_busy_avg FROM inst_min WHERE ts>=? AND port=? AND busy_ticks>=?"
            " AND cpu_busy_avg IS NOT NULL", (since, port, BUSY_MIN_TICKS))]
        rss = conn.execute("SELECT MAX(mem_max) FROM inst_min WHERE ts>=? AND port=?",
                           (since, port)).fetchone()[0]
        out.append({"port": port, "core": current[port],
                    "busy_p95": _p95(busy), "rss_max": rss,
                    "late_24h": late_24h, "frames_24h": frames_24h})
    return out


def snapshot(conn, now):
    since = now - LOOKBACK_S
    host_rows = _rows(conn, "SELECT * FROM host_raw ORDER BY ts DESC LIMIT 1")
    host = host_rows[0] if host_rows else None
    core_ts = conn.execute("SELECT MAX(ts) FROM core_raw").fetchone()[0]
    cores_last = _rows(conn, "SELECT * FROM core_raw WHERE ts=? ORDER BY core",
                       (core_ts,)) if core_ts is not None else []
    inst_ts = conn.execute("SELECT MAX(ts) FROM inst_raw").fetchone()[0]
    insts_last = _rows(
        conn, "SELECT * FROM inst_raw WHERE ts>=? AND ts=(SELECT MAX(r.ts) FROM inst_raw r"
        " WHERE r.port=inst_raw.port) ORDER BY port", (inst_ts - 60,)) if inst_ts is not None else []

    cores = {r[0] for r in conn.execute(
        "SELECT DISTINCT core FROM core_min WHERE ts>=? AND core>=0", (since,))}
    cores.update(r["core"] for r in cores_last if r["core"] >= 0)
    steal = _p95(r[0] for r in conn.execute(
        "SELECT steal FROM core_min WHERE ts>=? AND core=-1", (since,)))
    total, busy_counts = _events_24h(conn, now)
    return {
        "now": now,
        # seconds since the collector's newest sample; the backend marks a host stale on it
        "data_age_s": now - host["ts"] if host else None,
        "host": host,
        "cores_last": cores_last,
        "insts_last": insts_last,
        "cores": len(cores),
        "mem_total": host["mem_total"] if host else None,
        "mem_avail_now": host["mem_avail"] if host else None,
        "steal_p95": steal,
        "core_other_p95": _core_other_p95(conn, since),
        "core_p95_24h": _core_p95_24h(conn, now),
        "insts": _inst_block(conn, since, now),
        "events_24h": total,
        "events_24h_busy": busy_counts,
        "hardware": hm_store.get_hardware(conn),
    }


def _parser():
    p = argparse.ArgumentParser(prog="hm_query.py", description=__doc__.splitlines()[0])
    p.add_argument("--db", default=DEFAULT_DB)
    p.add_argument("--now", type=int, default=None, help=argparse.SUPPRESS)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("snapshot")
    s = sub.add_parser("series")
    s.add_argument("--range", required=True, choices=list(hm_store.RANGES))
    s.add_argument("--port", type=int, default=None)
    e = sub.add_parser("events")
    e.add_argument("--range", choices=list(hm_store.RANGES))
    e.add_argument("--since", type=_since)
    return p


def _since(text):
    try:
        val = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError("not an integer: %r" % (text,))
    if val < 0:
        raise argparse.ArgumentTypeError("must be >= 0: %r" % (text,))
    return val


def _out(obj):
    sys.stdout.write(json.dumps(obj, separators=(",", ":")) + "\n")


def main(argv=None):
    parser = _parser()
    args = parser.parse_args(argv)
    if args.cmd == "events" and (args.range is None) == (args.since is None):
        parser.error("events needs exactly one of --range and --since")
    version = _version()
    now = args.now if args.now is not None else int(time.time())
    if not Path(args.db).is_file():
        _out({"version": version, "error": "no_data"})
        return 3
    try:
        conn = hm_store.open_db(args.db, readonly=True)
        try:
            if args.cmd == "snapshot":
                body = snapshot(conn, now)
            elif args.cmd == "series":
                body = hm_store.series(conn, now, args.range, port=args.port)
                body["range"] = args.range
                body["now"] = now
            elif args.since is not None:
                body = {"now": now, "since": args.since,
                        "events": hm_store.events_changed_since(conn, args.since)}
            else:
                body = {"range": args.range, "now": now,
                        "events": hm_store.events(conn, now - hm_store.RANGES[args.range])}
        finally:
            conn.close()
    except sqlite3.Error:
        _out({"version": version, "error": "no_data"})
        return 3
    body["version"] = version
    _out(body)
    return 0


if __name__ == "__main__":
    sys.exit(main())
