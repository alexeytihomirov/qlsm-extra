"""Capacity verdict of one host. Pure function, stdlib only, no qlsm imports.

Input comes from `hm_query.py snapshot`; see the "Verdict" section of
docs/superpowers/specs/2026-10-15-host-metrics-addon-design.md.
"""
import math

DEFAULTS = {
    "verdict_target_pct": 70.0,
    "mem_reserve_pct": 20.0,
    "steal_tight_pct": 5.0,
    "steal_overload_pct": 15.0,
}
# Memory reference when the host has no instance RSS yet: measured instances use
# 80-91 MB, x1.6 margin (ruling R20).
REF_RSS_BYTES = 150 * 1048576


def _num(settings, key):
    try:
        return float(settings.get(key, DEFAULTS[key]))
    except (TypeError, ValueError):
        return DEFAULTS[key]


def _g(x):
    return "%g" % round(x, 1)


def _other(core_other, core):
    for key in (core, str(core)):
        if key in core_other and core_other[key] is not None:
            return float(core_other[key])
    return 0.0


def _cpu_slots(inp, load, target):
    """Return (slots, tightest core text). Unpinned instances go to the least-loaded core."""
    cores = max(int(inp.get("cores") or 0), 1)
    core_other = inp.get("core_other_p95") or {}
    used = [_other(core_other, c) for c in range(cores)]
    count = [0] * cores
    insts = inp.get("insts") or []
    for inst in insts:
        c = inst.get("core")
        if c is None or not (0 <= int(c) < cores):
            continue
        c = int(c)
        used[c] += load
        count[c] += 1
    for inst in insts:
        c = inst.get("core")
        if c is not None and 0 <= int(c) < cores:
            continue
        c = min(range(cores), key=lambda i: (used[i], i))
        used[c] += load
        count[c] += 1
    free = [max(int(math.floor((target - u) / load)), 0) for u in used]
    # core named in the reason: the one with the fewest free slots (lowest index on ties)
    tight = min(range(cores), key=lambda i: (free[i], i))
    other = used[tight] - count[tight] * load
    text = "core %d: %d x %s%% + %s%% other of %s%%" % (
        tight, count[tight], _g(load), _g(other), _g(target))
    return sum(free), text


def verdict(inp, settings, fleet_busy_median):
    target = _num(settings, "verdict_target_pct")
    reserve = _num(settings, "mem_reserve_pct")
    steal_tight = _num(settings, "steal_tight_pct")
    steal_over = _num(settings, "steal_overload_pct")
    insts = inp.get("insts") or []
    steal = inp.get("steal_p95")
    busy_ev = inp.get("events_24h_busy") or {}

    busy = [float(i["busy_p95"]) for i in insts if i.get("busy_p95") is not None]
    if busy:
        load, ref_source = max(busy), "host"
    elif fleet_busy_median is not None:
        load, ref_source = float(fleet_busy_median), "fleet"
    else:
        load, ref_source = None, None

    slots = None
    cpu_text = None
    mem_slots = None
    mem_text = None
    if load is not None and load > 0:
        cpu_slots, cpu_text = _cpu_slots(inp, load, target)
        slots = cpu_slots
    rss = [float(i["rss_max"]) for i in insts if i.get("rss_max")]
    rss_label = "largest instance"
    if not rss:
        # empty host (or instances without a full minute yet): a typical instance
        rss, rss_label = [float(REF_RSS_BYTES)], "reference instance"
    total = inp.get("mem_total")
    avail = inp.get("mem_avail_now")
    if total is not None and avail is not None:
        free_mem = float(avail) - reserve / 100.0 * float(total)
        mem_slots = max(int(math.floor(free_mem / max(rss))), 0)
        mem_text = "memory: %d MB available - %s%% reserve, %s %d MB" % (
            float(avail) / 1048576, _g(reserve), rss_label, max(rss) / 1048576)
        if slots is not None:
            slots = min(slots, mem_slots)

    def result(status, reason):
        return {"status": status, "slots": slots, "reason": reason,
                "ref_load": load, "ref_source": ref_source}

    late = int(busy_ev.get("frames_late") or 0)
    sat = int(busy_ev.get("core_saturated") or 0)
    if late or sat:
        what = "frames_late %d" % late if late else "core_saturated %d" % sat
        return result("overloaded", "%s with players in the last 24 h" % what)
    if steal is not None and steal > steal_over:
        return result("overloaded", "steal p95 %s%% > %s%%" % (_g(steal), _g(steal_over)))

    if slots == 0:
        if mem_slots == 0:
            return result("tight", "0 slots, " + mem_text)
        return result("tight", "0 slots, " + cpu_text)
    if steal is not None and steal > steal_tight:
        return result("tight", "steal p95 %s%% > %s%%, noisy neighbour" % (_g(steal), _g(steal_tight)))

    if slots is None:
        return result("unknown", "no data yet")
    if mem_slots is not None and slots == mem_slots and (cpu_text is None or mem_slots < cpu_slots):
        return result("ok", "room for %d more, %s" % (slots, mem_text))
    return result("ok", "room for %d more, %s" % (slots, cpu_text))
