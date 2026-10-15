"""SQLite store for host-metrics: schema, insert, minute rollup, retention, series, events.

Stdlib only. One writer (the collector) and separate readers (query CLI) via WAL.
"""
import sqlite3
from pathlib import Path

SCHEMA_VERSION = 1

HOST_COLS = ["load1", "psi10", "mem_total", "mem_avail", "swap_used", "disk_used",
             "disk_total", "rx_bps", "tx_bps", "rx_pps", "tx_pps"]
CORE_COLS = ["user", "system", "iowait", "steal", "busy"]
INST_COLS = ["cpu", "mem", "core", "players", "state", "map", "frames", "late",
             "max_ms", "p99_ms", "tick_ms"]

HOST_MIN_EXTRA = ["load1_max", "mem_avail_min"]
CORE_MIN_EXTRA = ["busy_max", "steal_max"]
INST_MIN_COLS = ["cpu_avg", "cpu_max", "mem_max", "core", "players_max", "busy_ticks",
                 "cpu_busy_avg", "frames", "late", "max_ms", "p99_max"]

RANGES = {"1h": 3600, "6h": 21600, "24h": 86400, "7d": 604800, "30d": 2592000}
RAW_RANGES = ("1h", "6h")

SCHEMA = """
CREATE TABLE IF NOT EXISTS host_raw(
  ts INTEGER PRIMARY KEY, load1 REAL, psi10 REAL, mem_total INTEGER, mem_avail INTEGER,
  swap_used INTEGER, disk_used INTEGER, disk_total INTEGER,
  rx_bps REAL, tx_bps REAL, rx_pps REAL, tx_pps REAL);
CREATE TABLE IF NOT EXISTS core_raw(
  ts INTEGER, core INTEGER, user REAL, system REAL, iowait REAL, steal REAL, busy REAL,
  PRIMARY KEY(ts, core));
CREATE TABLE IF NOT EXISTS inst_raw(
  ts INTEGER, port INTEGER, cpu REAL, mem INTEGER, core INTEGER, players INTEGER,
  state TEXT, map TEXT, frames INTEGER, late INTEGER, max_ms REAL, p99_ms REAL, tick_ms REAL,
  PRIMARY KEY(ts, port));
CREATE TABLE IF NOT EXISTS host_min(
  ts INTEGER PRIMARY KEY, load1 REAL, psi10 REAL, mem_total INTEGER, mem_avail REAL,
  swap_used REAL, disk_used REAL, disk_total INTEGER,
  rx_bps REAL, tx_bps REAL, rx_pps REAL, tx_pps REAL,
  load1_max REAL, mem_avail_min INTEGER);
CREATE TABLE IF NOT EXISTS core_min(
  ts INTEGER, core INTEGER, user REAL, system REAL, iowait REAL, steal REAL, busy REAL,
  busy_max REAL, steal_max REAL, PRIMARY KEY(ts, core));
CREATE TABLE IF NOT EXISTS inst_min(
  ts INTEGER, port INTEGER, cpu_avg REAL, cpu_max REAL, mem_max INTEGER, core INTEGER,
  players_max INTEGER, busy_ticks INTEGER, cpu_busy_avg REAL, frames INTEGER, late INTEGER,
  max_ms REAL, p99_max REAL, PRIMARY KEY(ts, port));
CREATE TABLE IF NOT EXISTS events(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, kind TEXT, scope TEXT, port INTEGER,
  severity TEXT, state TEXT NOT NULL DEFAULT 'open' CHECK(state IN ('open','closed')),
  message TEXT, closed_ts INTEGER);
CREATE INDEX IF NOT EXISTS events_ts ON events(ts);
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
"""


def open_db(path, readonly=False):
    """Open the store. Writers get WAL and the schema; readonly never creates or writes."""
    if readonly:
        uri = Path(path).resolve().as_uri() + "?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=5.0)
        conn.execute("PRAGMA busy_timeout = 5000")
        return conn
    conn = sqlite3.connect(str(path), timeout=5.0)
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.executescript(SCHEMA)
    conn.execute("PRAGMA user_version = %d" % SCHEMA_VERSION)
    conn.commit()
    return conn


def _insert(conn, table, ts, row, cols, key=None):
    names = ["ts"] + ([key[0]] if key else []) + cols
    vals = [ts] + ([key[1]] if key else []) + [row.get(c) for c in cols]
    conn.execute("INSERT OR REPLACE INTO %s(%s) VALUES (%s)"
                 % (table, ",".join(names), ",".join("?" * len(names))), vals)


def insert_tick(conn, ts, host, cores, insts):
    """Write one sample. Dict keys that are not columns are ignored."""
    with conn:
        if host:
            _insert(conn, "host_raw", ts, host, HOST_COLS)
        for c in cores or []:
            _insert(conn, "core_raw", ts, c, CORE_COLS, ("core", c["core"]))
        for i in insts or []:
            _insert(conn, "inst_raw", ts, i, INST_COLS, ("port", i["port"]))


def rollup(conn, until_ts):
    """Roll every complete minute not yet rolled. Returns the number of minutes rolled."""
    end = int(until_ts) // 60 * 60
    row = conn.execute("SELECT value FROM meta WHERE key='rolled_until'").fetchone()
    if row:
        start = int(row[0])
    else:
        first = conn.execute("SELECT MIN(ts) FROM host_raw").fetchone()[0]
        firsts = [first]
        for t in ("core_raw", "inst_raw"):
            firsts.append(conn.execute("SELECT MIN(ts) FROM %s" % t).fetchone()[0])
        firsts = [f for f in firsts if f is not None]
        if not firsts:
            return 0
        start = min(firsts) // 60 * 60
    if end <= start:
        return 0
    with conn:
        for t in ("host_min", "core_min", "inst_min"):
            conn.execute("DELETE FROM %s WHERE ts>=? AND ts<?" % t, (start, end))
        conn.execute(
            "INSERT INTO host_min SELECT ts/60*60, AVG(load1), AVG(psi10), MAX(mem_total),"
            " AVG(mem_avail), AVG(swap_used), AVG(disk_used), MAX(disk_total),"
            " AVG(rx_bps), AVG(tx_bps), AVG(rx_pps), AVG(tx_pps), MAX(load1), MIN(mem_avail)"
            " FROM host_raw WHERE ts>=? AND ts<? GROUP BY ts/60", (start, end))
        conn.execute(
            "INSERT INTO core_min SELECT ts/60*60, core, AVG(user), AVG(system), AVG(iowait),"
            " AVG(steal), AVG(busy), MAX(busy), MAX(steal)"
            " FROM core_raw WHERE ts>=? AND ts<? GROUP BY ts/60, core", (start, end))
        conn.execute(
            "INSERT INTO inst_min SELECT ts/60*60, port, AVG(cpu), MAX(cpu), MAX(mem),"
            " MAX(core), MAX(players),"
            " SUM(CASE WHEN state='in_progress' AND players>=2 THEN 1 ELSE 0 END),"
            " AVG(CASE WHEN state='in_progress' AND players>=2 THEN cpu END),"
            " SUM(frames), SUM(late), MAX(max_ms), MAX(p99_ms)"
            " FROM inst_raw WHERE ts>=? AND ts<? GROUP BY ts/60, port", (start, end))
        conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('rolled_until',?)", (str(end),))
    minutes = set()
    for t in ("host_min", "core_min", "inst_min"):
        minutes.update(r[0] for r in conn.execute(
            "SELECT DISTINCT ts FROM %s WHERE ts>=? AND ts<?" % t, (start, end)))
    return len(minutes)


def prune(conn, now, raw_keep_s=172800, min_keep_s=2592000):
    raw_cut = now - raw_keep_s
    min_cut = now - min_keep_s
    with conn:
        for t in ("host_raw", "core_raw", "inst_raw"):
            conn.execute("DELETE FROM %s WHERE ts<?" % t, (raw_cut,))
        for t in ("host_min", "core_min", "inst_min"):
            conn.execute("DELETE FROM %s WHERE ts<?" % t, (min_cut,))
        conn.execute("DELETE FROM events WHERE ts<? AND state='closed'", (min_cut,))


def _rows(conn, sql, args):
    cur = conn.execute(sql, args)
    names = [d[0] for d in cur.description]
    return [dict(zip(names, r)) for r in cur.fetchall()]


def _combine(name, vals):
    vals = [v for v in vals if v is not None]
    if not vals:
        return None
    if not all(isinstance(v, (int, float)) for v in vals):
        return vals[-1]
    if name.endswith("_max"):
        return max(vals)
    if name.endswith("_min"):
        return min(vals)
    return sum(vals) / len(vals)


def _downsample(rows, max_points):
    """Average rows into at most max_points equal-count buckets."""
    n = len(rows)
    if n <= max_points or max_points < 1:
        return rows
    out = []
    for b in range(max_points):
        chunk = rows[b * n // max_points:(b + 1) * n // max_points]
        if not chunk:
            continue
        merged = {}
        for k in chunk[0]:
            if k in ("port", "core"):
                merged[k] = chunk[0][k]
            elif k == "ts":
                merged[k] = int(sum(r[k] for r in chunk) / len(chunk))
            else:
                merged[k] = _combine(k, [r[k] for r in chunk])
        out.append(merged)
    return out


def series(conn, now, range_name, port=None, max_points=600):
    """Series for a range. cores is a flat list of rows carrying a `core` key (-1 = all)."""
    if range_name not in RANGES:
        raise ValueError("bad range: %r" % (range_name,))
    since = now - RANGES[range_name]
    res = "raw" if range_name in RAW_RANGES else "min"
    suffix = "_raw" if res == "raw" else "_min"
    host = _rows(conn, "SELECT * FROM host%s WHERE ts>=? AND ts<=? ORDER BY ts" % suffix,
                 (since, now))
    cores_all = _rows(conn, "SELECT * FROM core%s WHERE ts>=? AND ts<=? ORDER BY core, ts"
                      % suffix, (since, now))
    if port is None:
        inst_all = _rows(conn, "SELECT * FROM inst%s WHERE ts>=? AND ts<=? ORDER BY port, ts"
                         % suffix, (since, now))
    else:
        inst_all = _rows(conn, "SELECT * FROM inst%s WHERE ts>=? AND ts<=? AND port=? ORDER BY ts"
                         % suffix, (since, now, int(port)))
    cores = []
    by_core = {}
    for r in cores_all:
        by_core.setdefault(r["core"], []).append(r)
    for c in sorted(by_core):
        cores.extend(_downsample(by_core[c], max_points))
    insts = {}
    for r in inst_all:
        insts.setdefault(r["port"], []).append(r)
    insts = {p: _downsample(v, max_points) for p, v in insts.items()}
    return {"res": res, "host": _downsample(host, max_points), "cores": cores, "insts": insts}


def insert_event(conn, ts, kind, scope, port, severity, message):
    """Open an event, return its id."""
    with conn:
        cur = conn.execute(
            "INSERT INTO events(ts,kind,scope,port,severity,state,message)"
            " VALUES(?,?,?,?,?,'open',?)", (ts, kind, scope, port, severity, message))
    return cur.lastrowid


def close_event(conn, event_id, ts):
    with conn:
        conn.execute("UPDATE events SET state='closed', closed_ts=? WHERE id=?", (ts, event_id))


def events(conn, since):
    """Events with ts >= since, newest first."""
    return _rows(conn, "SELECT * FROM events WHERE ts>=? ORDER BY ts DESC, id DESC", (since,))
