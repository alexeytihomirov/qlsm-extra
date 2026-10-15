"""frame_timing - interval between server frames, published to Redis for the host-metrics addon.

The "frame" hook only reads time.perf_counter() and adds one gap to a histogram (integer
updates). A worker thread swaps the histogram for a fresh one every 10 s and writes the old
one to Redis as minqlx:frame_stats:<net_port> with a 30 s TTL. A frame is late when its gap
is longer than 1.5 x the tick (tick = 1000 / sv_fps ms). The gap that spans a map change is
not counted.

FrameStats is pure and tested without a server (tests/test_frame_timing.py).
"""

import json
import math
import threading
import time

try:
    import minqlxtended as minqlx
except ImportError:
    import minqlx

WRITE_INTERVAL_SEC = 10
KEY_TTL_SEC = 30
ERROR_LOG_INTERVAL_SEC = 60
DEFAULT_SV_FPS = 40.0
LATE_FACTOR = 1.5
BUCKETS = 100  # 1 ms buckets 0..99, one more for everything above


def tick_ms_from_sv_fps(value):
    try:
        fps = float(value)
    except (TypeError, ValueError):
        fps = DEFAULT_SV_FPS
    if not fps > 0:
        fps = DEFAULT_SV_FPS
    return 1000.0 / fps


class FrameStats:
    def __init__(self, tick_ms):
        self.tick_ms = float(tick_ms)
        self._late_over = LATE_FACTOR * self.tick_ms
        self._hist = [0] * (BUCKETS + 1)
        self._frames = 0
        self._late = 0
        self._max = 0.0

    def add(self, gap_ms):
        self._frames += 1
        if gap_ms > self._late_over:
            self._late += 1
        if gap_ms > self._max:
            self._max = gap_ms
        self._hist[min(int(gap_ms), BUCKETS)] += 1

    def _percentile(self, fraction):
        if not self._frames:
            return 0.0
        rank = math.ceil(self._frames * fraction)
        seen = 0
        for i, count in enumerate(self._hist):
            seen += count
            if seen >= rank:
                return self._max if i == BUCKETS else float(i + 1)
        return self._max

    def snapshot(self):
        return {
            "frames": self._frames,
            "late": self._late,
            "max_ms": round(self._max, 3),
            "p50_ms": self._percentile(0.5),
            "p99_ms": self._percentile(0.99),
            "tick_ms": round(self.tick_ms, 3),
        }


class frame_timing(minqlx.Plugin):
    def __init__(self):
        super().__init__()
        self._clock = time.perf_counter
        self._cvar = self.get_cvar
        self._last = None
        self._skip_next = False
        self._seq = 0
        self._last_error_log = None
        self._tick_ms = tick_ms_from_sv_fps(self._cvar("sv_fps"))
        self._stats = FrameStats(self._tick_ms)
        self._window_started = self._clock()

        self.add_hook("frame", self.handle_frame)
        self.add_hook("map", self.handle_map)
        self.add_hook("new_game", self.handle_new_game)
        self.add_hook("unload", self.handle_unload)

        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def handle_frame(self):
        now = self._clock()
        last = self._last
        self._last = now
        if self._skip_next:
            self._skip_next = False
            return
        if last is not None:
            self._stats.add((now - last) * 1000.0)

    def handle_map(self, mapname, factory):
        self._skip_next = True

    def handle_new_game(self):
        self._skip_next = True
        self._tick_ms = tick_ms_from_sv_fps(self._cvar("sv_fps"))
        self._stats = FrameStats(self._tick_ms)

    def handle_unload(self, plugin):
        if plugin == self.__class__.__name__:
            self._stop_event.set()

    def _publish(self):
        old = self._stats
        self._stats = FrameStats(self._tick_ms)
        now = self._clock()
        window = now - self._window_started
        self._window_started = now
        self._seq += 1
        payload = old.snapshot()
        payload["seq"] = self._seq
        payload["window_s"] = round(window, 3)
        payload["updated"] = int(time.time())
        key = "minqlx:frame_stats:{}".format(self._cvar("net_port"))
        self.db.set(key, json.dumps(payload))
        self.db.expire(key, KEY_TTL_SEC)

    def _loop(self):
        while not self._stop_event.wait(WRITE_INTERVAL_SEC):
            try:
                self._publish()
            except Exception as e:
                now = time.monotonic()
                if self._last_error_log is None or now - self._last_error_log >= ERROR_LOG_INTERVAL_SEC:
                    self._last_error_log = now
                    self.logger.error("frame_timing: publish failed: %s", e)
