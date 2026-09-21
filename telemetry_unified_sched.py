# telemetry_unified_sched.py — pure-function helpers for stream_telemetry_unified.py.
#
# Deliberately has NO minqlx/minqlxtended import, so it can be unit-tested without a
# running QLDS/minqlx process (see tests/test_telemetry_unified_sched.py).
#
# Covers the two audit-cited mechanisms that are easiest to get subtly wrong:
#   - FovCache: steam_id-keyed cache with TTL + explicit invalidation
#     (docs/AUDIT-2026-07.md section 4, proposal #2).
#   - on_stride / effective_interval: shared frame-scheduler math
#     (docs/AUDIT-2026-07.md section 4, proposal #7, and the ready-player interval
#     sizing that proposal #1 depends on).

from __future__ import annotations


class FovCache:
    """steam_id -> (value, cached_at) cache with a TTL safety net.

    Primary invalidation is expected to be event-driven (the `userinfo` hook on
    cg_fov change, plus connect/disconnect calling `invalidate`); the TTL is only a
    fallback for minqlxtended builds where the driving hook isn't wired up, so a
    stale value can't live forever.
    """

    def __init__(self, ttl_sec=30.0):
        self._ttl_sec = ttl_sec
        self._entries = {}

    def get(self, steam_id, now):
        """Returns (value, hit). `hit` is False on cache miss or TTL expiry."""
        if not steam_id:
            return None, False
        entry = self._entries.get(steam_id)
        if entry is None:
            return None, False
        value, cached_at = entry
        if now - cached_at >= self._ttl_sec:
            return None, False
        return value, True

    def put(self, steam_id, value, now):
        if steam_id:
            self._entries[steam_id] = (value, now)

    def invalidate(self, steam_id):
        if steam_id:
            self._entries.pop(steam_id, None)

    def __len__(self):
        return len(self._entries)


def on_stride(frame_tick, stride, phase=0):
    """True on every `stride`-th frame tick — matches the plugins' existing
    `frame_tick % stride == 0` convention. `stride <= 0` means "every frame".

    `phase` shifts which tick within the stride fires, so co-scheduled feeds can
    be spread across frames instead of clustering on common multiples (e.g.
    positions on even ticks, session flush on tick % 4 == 1)."""
    if stride <= 0:
        return True
    return frame_tick % stride == phase % stride


def derive_ingest_url(base_url, feed):
    """Derive a sibling `/api/ingest/<feed>` URL from qlx_statsHubUrl.

    Mirrors the (previously copy-pasted) logic of pickup_telemetry's
    `_item_events_url` and session_events' `_session_events_url`: the cvar
    usually points at `/api/ingest/telemetry`, but bare hosts and other
    `/api/ingest/*` paths must work too."""
    url = (base_url or "").strip()
    if not url:
        return ""
    if url.endswith("/api/ingest/telemetry"):
        return url[: -len("telemetry")] + feed
    if "/api/ingest/" in url:
        base = url.rsplit("/api/ingest/", 1)[0]
        return base + "/api/ingest/" + feed
    return url.rstrip("/") + "/api/ingest/" + feed


def effective_interval(ready_player_count, active_interval, idle_interval):
    """Send cadence: idle (slower) heartbeat with nobody ready, active otherwise."""
    if ready_player_count <= 0:
        return idle_interval
    return active_interval


class FeedState:
    """Per-feed bookkeeping shared by the positions/items/session POST feeds
    (review 2026-07-17, P3-1): enable-edge tracking, in-flight/stuck-post
    detection with a generation counter (P1-1), and the consecutive-failure
    circuit breaker. Owns state transitions only — queues, payload building,
    HTTP and logging stay in the plugin, which is why each mutating method
    returns just enough for the caller to decide what side effect (log line,
    cvar disable, connection close) to perform.
    """

    def __init__(self, name, stuck_sec, fail_threshold, cvar=None):
        self.name = name
        self.stuck_sec = stuck_sec
        self.fail_threshold = fail_threshold
        self.cvar = cvar
        self.was_enabled = False
        self.post_in_flight = False
        self.post_in_flight_since = 0.0
        self.post_generation = 0
        self.posts_ok = 0
        self.posts_fail = 0
        self.consecutive_fail = 0
        self.tripped = False

    def sync_enabled(self, enabled):
        """Updates was_enabled; returns "enabled"/"disabled" on an edge, else None."""
        edge = None
        if enabled and not self.was_enabled:
            edge = "enabled"
        elif not enabled and self.was_enabled:
            edge = "disabled"
        self.was_enabled = enabled
        return edge

    def reset_circuit(self):
        """Re-arms the breaker (call on a disabled->enabled edge). Returns True
        if it actually changed anything, so the caller only logs when it did."""
        if not self.tripped and not self.consecutive_fail:
            return False
        self.tripped = False
        self.consecutive_fail = 0
        return True

    def record_result(self, ok):
        """Returns True the moment this call trips the breaker (caller then
        logs and disables self.cvar)."""
        if ok:
            self.consecutive_fail = 0
            return False
        self.consecutive_fail += 1
        if self.tripped or self.consecutive_fail < self.fail_threshold:
            return False
        self.tripped = True
        return True

    def check_stuck(self, now):
        """Returns age_sec and bumps the generation (so a late-finishing worker
        sees itself as stale and skips touching shared state) if the in-flight
        post has been running longer than stuck_sec; else returns None."""
        if not self.post_in_flight:
            return None
        if not self.post_in_flight_since or now - self.post_in_flight_since <= self.stuck_sec:
            return None
        age = now - self.post_in_flight_since
        self.post_generation += 1
        self.post_in_flight = False
        self.post_in_flight_since = 0.0
        self.posts_fail += 1
        return age

    def begin_post(self, now):
        """Marks a post in flight; returns the generation token to hand to the
        worker thread."""
        self.post_in_flight = True
        self.post_in_flight_since = now
        return self.post_generation

    def complete(self, generation, ok):
        """Worker calls this on completion (success or failure). Returns False
        if `generation` is stale — the worker must not touch anything else
        shared (queue, connection, counters) on behalf of a stuck-reset slot
        a newer post may already own."""
        if generation != self.post_generation:
            return False
        if ok:
            self.posts_ok += 1
        else:
            self.posts_fail += 1
        self.post_in_flight = False
        self.post_in_flight_since = 0.0
        return True
