"""Windowed event tracker for host-metrics.

Stdlib only. The collector calls evaluate() once per tick with the sample; events are
stored through hm_store. A condition opens an event after it was continuously active for
the window, and closes on the first inactive tick. One open row per (kind, scope_key).
"""
import hm_store

SEVERITY = {
    "instance_new": "info", "instance_gone": "info",
    "core_saturated": "warn", "steal_high": "warn", "mem_low": "warn", "frames_late": "warn",
    "oom_kill": "crit", "disk_low": "crit",
}
# open and closed in the same tick
POINT_KINDS = {"oom_kill", "instance_new", "instance_gone"}
# opened on the first active tick, closed when the condition clears
AT_ONCE_KINDS = POINT_KINDS | {"disk_low"}

DEFAULTS = {
    "core_saturated_pct": 95, "steal_event_pct": 10, "mem_low_pct": 10, "disk_low_pct": 90,
    "frames_late_pct": 1, "frame_gap_ms": 100, "event_window_s": 60,
}


def _split_scope(scope_key):
    """scope_key 'host' | 'core:<n>' | 'port:<n>' -> (scope, port)."""
    if scope_key.startswith("port:"):
        return "instance", int(scope_key[5:])
    if scope_key.startswith("core:"):
        return "core", None
    return "host", None


class EventTracker:
    def __init__(self, store_conn, thresholds):
        self.conn = store_conn
        self.th = dict(DEFAULTS)
        self.th.update(thresholds or {})
        self._since = {}      # (kind, scope_key) -> ts the condition became active
        self._open = {}       # (kind, scope_key) -> event id
        self._ports = None    # ports seen so far; None until the first evaluate()

    def observe(self, ts, kind, scope_key, active, message):
        key = (kind, scope_key)
        if not active:
            self._since.pop(key, None)
            eid = self._open.pop(key, None)
            if eid is not None:
                hm_store.close_event(self.conn, eid, ts)
            return
        if key in self._open:
            return
        since = self._since.setdefault(key, ts)
        if kind not in AT_ONCE_KINDS and ts - since < self.th["event_window_s"]:
            return
        scope, port = _split_scope(scope_key)
        eid = hm_store.insert_event(self.conn, ts, kind, scope, port,
                                    SEVERITY.get(kind, "warn"), message)
        if kind in POINT_KINDS:
            hm_store.close_event(self.conn, eid, ts)
            self._since.pop(key, None)
        else:
            self._open[key] = eid

    def evaluate(self, ts, sample):
        th = self.th
        host = sample.get("host") or {}

        for c in sample.get("cores") or []:
            n = c.get("core")
            if n is None or n < 0:
                continue
            busy, steal = c.get("busy"), c.get("steal")
            sk = "core:%d" % n
            self.observe(ts, "core_saturated", sk,
                         busy is not None and busy > th["core_saturated_pct"],
                         "core %d busy %.0f%% (limit %s%%)" % (n, busy or 0, th["core_saturated_pct"]))
            self.observe(ts, "steal_high", sk,
                         steal is not None and steal > th["steal_event_pct"],
                         "core %d steal %.0f%% (limit %s%%)" % (n, steal or 0, th["steal_event_pct"]))

        total, avail = host.get("mem_total"), host.get("mem_avail")
        if total and avail is not None:
            pct = avail * 100.0 / total
            self.observe(ts, "mem_low", "host", pct < th["mem_low_pct"],
                         "MemAvailable %.1f%% (limit %s%%)" % (pct, th["mem_low_pct"]))
        else:
            self.observe(ts, "mem_low", "host", False, "")

        used, dtotal = host.get("disk_used"), host.get("disk_total")
        if dtotal and used is not None:
            pct = used * 100.0 / dtotal
            self.observe(ts, "disk_low", "host", pct > th["disk_low_pct"],
                         "/ used %.1f%% (limit %s%%)" % (pct, th["disk_low_pct"]))
        else:
            self.observe(ts, "disk_low", "host", False, "")

        oom = sample.get("oom_delta")
        if oom is None:
            oom = host.get("oom_delta")
        oom = oom or 0
        self.observe(ts, "oom_kill", "host", oom > 0, "%d OOM kill(s) in the last tick" % oom)

        ports = set()
        for i in sample.get("insts") or []:
            port = i["port"]
            ports.add(port)
            frames, late, max_ms = i.get("frames"), i.get("late"), i.get("max_ms")
            active = False
            msg = ""
            if frames:
                late_pct = (late or 0) * 100.0 / frames
                active = (late_pct > th["frames_late_pct"]
                          or (max_ms is not None and max_ms > th["frame_gap_ms"]))
                msg = "port %d late frames %.1f%%, max gap %s ms" % (
                    port, late_pct, "?" if max_ms is None else "%.0f" % max_ms)
            self.observe(ts, "frames_late", "port:%d" % port, active, msg)

        if self._ports is not None:
            for p in sorted(ports - self._ports):
                self.observe(ts, "instance_new", "port:%d" % p, True, "instance %d appeared" % p)
            for p in sorted(self._ports - ports):
                self.observe(ts, "instance_gone", "port:%d" % p, True, "instance %d disappeared" % p)
                # a gone instance can no longer be late
                self.observe(ts, "frames_late", "port:%d" % p, False, "")
        self._ports = ports
