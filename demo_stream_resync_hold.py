"""demo_stream_resync_hold - repeat the full snapshot after a live demo stream resync.

The engine (alexeytihomirov/minqlxtended, src/features/stream.c) repairs a streamed POV after a
reconnect, a gap or a periodic keyframe with ONE full snapshot: stream_force_resyncs() sets
client_t.deltaMessage to -1 for a single server frame. The snapshots right behind it are deltas
again, based on messages from before the full one (the client's acknowledgements lag by its
ping). A relay that starts decoding at that full snapshot has never seen those messages, so its
delta chain can die until the next keyframe.

This plugin keeps deltaMessage at -1 for the following frames, until the client acknowledges a
message the plugin itself forced to be full, or a cap of a few messages runs out. From then on
every delta the client asks for is based on a full snapshot the relay has. A hold is never
interrupted: one delta in the middle could be the message the client acknowledges next.

Where it sits in the server frame (fork file:line): My_G_RunFrame (src/server/hooks.c:681) calls
FrameDispatcher() - this plugin's "frame" hook - and then Stream_Frame(), both before the game
frame; the engine sends snapshots after the game frame and reads client packets before it. So a
value written here is still there when the snapshot is built, and the engine's own request from
the same frame is NOT visible here: it is set after this hook and overwritten by the client's
next packet before the hook runs again. A resync is therefore detected one frame later, from
stream_status():

- "flag": a slot whose `resyncing` flag went from set to clear got its full block out. Certain.
- "counter": the `resyncs` counter rose by more than the number of flags that cleared, so a
  resync was armed and spent inside one Stream_Frame (a keyframe, or the first slot after a
  reconnect). Which slot it was cannot be seen from Python. The plugin keeps, per slot, the time
  of the last full snapshot it knows of and takes the slot whose time is about one
  sv_demoStreamKeyframeSec old, as the engine does. That is a reconstruction, not a signal: it
  is off when a full block was dropped on the way to the relay, and then the oldest slot is
  taken and counted as a guess.
- "first sight": a slot that was already open when the plugin started watching has an unknown
  last full snapshot; it gets one hold, which also makes its time known.

The anchor of a hold is the first message this plugin itself forces, never the engine's full
snapshot: the hold is then right whichever slot the engine meant and however late it starts.

Load on the server is bounded the way the engine bounds its own resyncs
(sv_demoStreamResyncPerFrame): at most qlx_demoStreamResyncHoldPerFrame holds run at once, so at
most that many full snapshots are forced in one server frame; the others wait their turn.
Nothing is started, and running holds are cancelled, while the relay is behind.

The class ResyncHold is pure logic and is tested with a fake engine (tests/test_demo_stream_resync_hold.py).
"""

import collections
import time

try:
    import minqlxtended as minqlx
except ImportError:
    import minqlx

# Most full snapshots one hold may force (qlx_demoStreamResyncHoldMaxFrames). 8 server frames
# are 200 ms at sv_fps 40: enough for a client with a round trip under about 175 ms.
DEFAULT_MAX_HOLD_FRAMES = 8
# The cvar is clamped to this, whatever the operator types.
MAX_HOLD_FRAMES_LIMIT = 16
# Most holds that run at once = most full snapshots forced in one server frame, all players
# together (qlx_demoStreamResyncHoldPerFrame), and what the cvar is clamped to.
DEFAULT_HOLDS_PER_FRAME = 2
HOLDS_PER_FRAME_LIMIT = 8
# Frames a slot must run without a hold after one ended, before a keyframe ("counter") or
# "first sight" hold may start. A "flag" hold repairs a real loss and does not wait.
HOLD_COOLDOWN_FRAMES = 20
# A hold whose client is sent nothing (unsent fragments, snaps below sv_fps) does not use up its
# cap, but it ends after this many times the cap in server frames.
HOLD_STALL_FACTOR = 4
# A keyframe or "first sight" hold that has waited this many frames for its turn is dropped: by
# then the engine's full snapshot it belonged to is long gone and it would only cost the player
# a full snapshot. A "flag" hold repairs a real loss and waits as long as it takes.
WAIT_MAX_AGE_FRAMES = 60
# The engine's default and limits for sv_demoStreamKeyframeSec (stream.c, stream_keyframe_ms).
DEFAULT_KEYFRAME_SEC = 10
KEYFRAME_SEC_MIN = 2
KEYFRAME_SEC_MAX = 60
# A slot counts as due for a keyframe when its last known full snapshot is this close to one interval old.
KEYFRAME_SLACK_SEC = 0.5
# The relay is "behind" when the oldest queued block waits this long, or this much is queued, or
# the engine dropped blocks since the last frame (ring full, too far behind, relay stalled).
BEHIND_LAG_MS = 250
BEHIND_PENDING_BYTES = 256 * 1024
# ... and stays "behind" for this many frames after the last such frame.
BEHIND_RECOVER_FRAMES = 40
# The cvars are re-read this often, and stream_status() is polled this often while the stream
# is switched off.
SLOW_POLL_FRAMES = 40
# The frame hook switches itself off after this many errors in a row instead of logging 40 a
# second, and tries again after this many seconds or when the on/off cvar is toggled.
MAX_ERRORS_IN_A_ROW = 5
BROKEN_RETRY_SEC = 60.0
# client_t.state of a client that is in the game (CS_ACTIVE); used when the runtime does not export it.
CS_ACTIVE_FALLBACK = 4
# How many hold starts, hold ends and link changes "!resynchold log" remembers, and how many
# lines of it one call sends to a chat channel.
EVENT_LOG_SIZE = 64
CHAT_LOG_LINES = 10

_WHY_ORDER = {"flag": 0, "counter": 1, "counter, guessed": 1, "first sight": 2}


class _Slot:
    __slots__ = ("gen", "resyncing", "last_full", "target", "start_seq", "start_frame", "want", "why",
                 "want_frame", "cooldown_until")

    def __init__(self, gen, last_full):
        self.gen = gen
        self.resyncing = False       # the engine's flag as seen on the previous frame
        self.last_full = last_full   # when the last full snapshot we know of went out; None = unknown
        self.target = None           # message number that ends the running hold, None = no hold
        self.start_seq = 0           # first message of the running hold
        self.start_frame = 0
        self.want = False            # a hold is owed and waits for its turn
        self.why = ""
        self.want_frame = 0
        self.cooldown_until = 0


class ResyncHold:
    """The hold logic. Call frame() once per server frame, before the engine sends snapshots.

    status: what minqlxtended.stream_status() returns (enabled, connected, resyncs, lag, pending,
    dropped_ring, dropped_lag, dropped_stall, slots with slot / active / resyncing / gen), or
    None when the runtime has no demo stream.
    client_of(slot): the engine's client view (state, delta_message, message_acknowledge,
    netchan.outgoing_sequence, netchan.unsent_fragments), or None.
    now: a monotonic clock in seconds.
    """

    def __init__(self, cs_active=CS_ACTIVE_FALLBACK, clock=time.time):
        self.cs_active = cs_active
        self.clock = clock           # wall clock, for the log only
        self.events = collections.deque(maxlen=EVENT_LOG_SIZE)
        self.per_slot = {}           # slot -> [holds, full snapshots forced]
        self.frame_no = 0
        self.started = 0     # holds begun
        self.acked = 0       # holds ended by the client's acknowledgement
        self.capped = 0      # holds ended by the cap
        self.cancelled = 0   # holds ended by a disconnect, a new gamestate, a link drop, a relay that is behind
        self.forced = 0      # full snapshots sent under a hold, all holds together
        self.retargeted = 0  # holds whose anchor moved because the engine resynced again
        self.by_counter = 0  # holds started for a keyframe
        self.guessed = 0     # ... of them, with no slot that looked due
        self.longest = 0     # most full snapshots one hold forced
        self.dropped_waits = 0  # waiting holds given up: too old, or the relay fell behind
        self.behind_frames = 0
        self._slots = {}
        self._resyncs = None
        self._dropped = None
        self._connected = None
        self._down_resyncs = 0
        self._behind_until = 0
        self._behind = False
        self._fresh = True

    def holding(self):
        return sorted(slot for slot, st in self._slots.items() if st.target is not None)

    def waiting(self):
        return sorted(slot for slot, st in self._slots.items() if st.want)

    def reset(self):
        """Forget every slot. For a map change, a switch-off and a stream that is off."""
        for slot in list(self._slots):
            self.drop_slot(slot)
        self._resyncs = None
        self._dropped = None
        self._behind_until = 0
        self._behind = False
        self._fresh = True

    def drop_slot(self, slot):
        st = self._slots.pop(slot, None)
        if st is not None and st.target is not None:
            self.cancelled += 1
            self._note(slot, "hold ended: slot closed")

    def _note(self, slot, text):
        self.events.append((self.clock(), self.frame_no, slot, text))

    def _end(self, slot, st, why, sent):
        sent = max(0, sent)
        self.forced += sent
        self.per_slot.setdefault(slot, [0, 0])[1] += sent
        self.longest = max(self.longest, sent)
        self._note(slot, "hold ended: {}, {} full snapshots forced".format(why, sent))
        st.target = None
        st.cooldown_until = self.frame_no + HOLD_COOLDOWN_FRAMES

    def _ask(self, slot, st, why):
        if st.target is None and not st.want:
            st.want = True
            st.why = why
            st.want_frame = self.frame_no
        elif st.want and _WHY_ORDER[why] < _WHY_ORDER[st.why]:
            st.why = why

    def _relay_behind(self, status):
        dropped = sum(int(getattr(status, name, 0) or 0) for name in ("dropped_ring", "dropped_lag", "dropped_stall"))
        grew = self._dropped is not None and dropped > self._dropped
        self._dropped = dropped
        if grew or int(getattr(status, "lag", 0) or 0) >= BEHIND_LAG_MS \
                or int(getattr(status, "pending", 0) or 0) >= BEHIND_PENDING_BYTES:
            self._behind_until = self.frame_no + BEHIND_RECOVER_FRAMES
        behind = self.frame_no < self._behind_until
        if behind != self._behind:
            self._behind = behind
            self._note(-1, "relay is behind, holds stopped" if behind else "relay caught up")
        if behind:
            self.behind_frames += 1
        return behind

    def frame(self, status, client_of, max_frames=DEFAULT_MAX_HOLD_FRAMES, now=None,
              keyframe_sec=DEFAULT_KEYFRAME_SEC, per_frame=DEFAULT_HOLDS_PER_FRAME):
        self.frame_no += 1
        if now is None:
            now = time.monotonic()
        if status is None or not status.enabled:
            self.reset()
            return

        resyncs = int(status.resyncs)
        forced_by_engine = 0
        if self._resyncs is not None and resyncs > self._resyncs:
            forced_by_engine = resyncs - self._resyncs
        self._resyncs = resyncs  # a smaller value is a counter reset (qlx_stream reset)
        behind = self._relay_behind(status)
        connected = bool(status.connected)
        if connected != self._connected:
            if self._connected is not None:
                self._note(-1, "link up, the engine forced {} full snapshots while it was down".format(
                    self._down_resyncs) if connected else "link down")
            self._connected = connected
            self._down_resyncs = 0
        if not connected:
            self._down_resyncs += forced_by_engine

        current = {}
        for s in status.slots:
            if s.active:
                current[int(s.slot)] = (int(s.gen), bool(s.resyncing))

        # A slot that closed or got a new gamestate starts from scratch.
        for slot in list(self._slots):
            cur = current.get(slot)
            if cur is None or cur[0] != self._slots[slot].gen:
                self.drop_slot(slot)

        # A flag is cleared only when a full block went out: these slots were resynced for certain.
        cleared = [slot for slot, st in self._slots.items() if st.resyncing and not current[slot][1]]
        unexplained = forced_by_engine - len(cleared)

        clients = {}
        for slot, (gen, resyncing) in current.items():
            st = self._slots.get(slot)
            if st is None:
                # Open before we started watching: its last full snapshot is unknown. Opened
                # while we watched: the engine's keyframe timer for it starts now, as ours does.
                st = self._slots[slot] = _Slot(gen, None if self._fresh else now)
                if self._fresh:
                    self._ask(slot, st, "first sight")
            client = client_of(slot)
            if client is None or client.state != self.cs_active or not connected:
                if st.target is not None:
                    self.cancelled += 1
                    self._end(slot, st, "link down" if not connected else "client not active",
                              int(client.netchan.outgoing_sequence) - st.start_seq if client is not None else 0)
                st.want = False
                continue
            clients[slot] = client
            if st.target is None and client.delta_message <= 0:
                st.last_full = now  # the client asked for a full snapshot itself
        self._fresh = False

        for slot in cleared:
            st = self._slots[slot]
            st.last_full = now
            client = clients.get(slot)
            if client is None:
                continue
            if st.target is None:
                self._ask(slot, st, "flag")
            else:
                # The engine resynced again during the hold: something was lost again, so the
                # anchor moves to the next message. The cap keeps counting from the start.
                st.target = int(client.netchan.outgoing_sequence)
                self.retargeted += 1
                self._note(slot, "anchor moved to {} (flag)".format(st.target))

        if unexplained > 0 and connected and not behind:
            # Armed and spent inside one Stream_Frame, so the flag was never seen set. As many
            # slots are taken as the engine resynced, never more: the ones whose last full
            # snapshot is one keyframe interval old.
            candidates = [slot for slot in clients
                          if not self._slots[slot].resyncing and not current[slot][1] and slot not in cleared
                          and self._slots[slot].target is None and not self._slots[slot].want]

            def age(slot):
                last = self._slots[slot].last_full
                return float("inf") if last is None else now - last

            candidates.sort(key=lambda slot: (-age(slot), slot))
            due_age = max(0.0, keyframe_sec - KEYFRAME_SLACK_SEC) if keyframe_sec > 0 else 0.0
            for slot in candidates[:unexplained]:
                looks_due = age(slot) >= due_age
                self._ask(slot, self._slots[slot], "counter" if looks_due else "counter, guessed")
                self._slots[slot].last_full = now

        for slot, (gen, resyncing) in current.items():
            self._slots[slot].resyncing = resyncing

        # Holds that wait: give up the ones that are no longer worth a full snapshot.
        for slot, st in self._slots.items():
            if st.want and st.why != "flag" and (behind or self.frame_no - st.want_frame > WAIT_MAX_AGE_FRAMES):
                st.want = False
                self.dropped_waits += 1
                self._note(slot, "waiting hold ({}) dropped: {}".format(
                    st.why, "relay is behind" if behind else "waited too long"))

        # Holds that are running: end them, or force this frame's snapshot.
        running = 0
        for slot, client in clients.items():
            st = self._slots[slot]
            if st.target is None:
                continue
            sent = int(client.netchan.outgoing_sequence) - st.start_seq
            if behind:
                self.cancelled += 1
                self._end(slot, st, "relay is behind", sent)
            elif int(client.message_acknowledge) >= st.target:
                self.acked += 1
                self._end(slot, st, "acknowledged {}".format(int(client.message_acknowledge)), sent)
            elif sent >= max_frames:
                self.capped += 1
                self._end(slot, st, "cap", sent)
            elif self.frame_no - st.start_frame >= max_frames * HOLD_STALL_FACTOR:
                self.capped += 1
                self._end(slot, st, "cap, the client was sent only {} snapshots".format(sent), sent)
            else:
                running += 1
                self._force(client, st, now)

        # Holds that wait: start as many as the per-frame budget leaves room for.
        if behind or running >= per_frame:
            return
        queue = sorted((slot for slot in clients if self._slots[slot].want),
                       key=lambda slot: (_WHY_ORDER[self._slots[slot].why], self._slots[slot].want_frame, slot))
        for slot in queue:
            if running >= per_frame:
                break
            st = self._slots[slot]
            if st.why != "flag" and self.frame_no < st.cooldown_until:
                continue
            client = clients[slot]
            st.want = False
            # The anchor is the message about to be sent: the first one this plugin forces.
            st.target = st.start_seq = int(client.netchan.outgoing_sequence)
            st.start_frame = self.frame_no
            self.started += 1
            if st.why.startswith("counter"):
                self.by_counter += 1
                if st.why != "counter":
                    self.guessed += 1
            self.per_slot.setdefault(slot, [0, 0])[0] += 1
            self._note(slot, "hold started ({}), anchor {}, acknowledged {}".format(
                st.why, st.target, int(client.message_acknowledge)))
            running += 1
            self._force(client, st, now)

    @staticmethod
    def _force(client, st, now):
        # With unsent fragments the engine sends this client no snapshot this frame
        # (SV_SendClientMessages, and the same test in stream_force_resyncs): nothing to force.
        if not getattr(client.netchan, "unsent_fragments", False):
            client.delta_message = -1
            st.last_full = now

    def log_lines(self, count=EVENT_LOG_SIZE):
        out = []
        for stamp, frame_no, slot, text in list(self.events)[-count:]:
            clock = time.strftime("%H:%M:%S", time.gmtime(stamp)) + ".{:03d}".format(int(stamp * 1000) % 1000)
            out.append("{}Z frame {} {}: {}".format(
                clock, frame_no, "stream" if slot < 0 else "slot {}".format(slot), text))
        return out

    def summary(self):
        per_slot = " ".join("{}:{}/{}".format(slot, n[0], n[1]) for slot, n in sorted(self.per_slot.items()))
        return ("holds {} (acknowledged {}, hit the cap {}, cancelled {}), full snapshots forced {}, "
                "longest hold {}, moved anchors {}, started for a keyframe {} (guessed slot {}), "
                "waits dropped {}, frames with the relay behind {}, holding now: {}, waiting: {}, "
                "per slot holds/forced: {}").format(
                    self.started, self.acked, self.capped, self.cancelled, self.forced,
                    self.longest, self.retargeted, self.by_counter, self.guessed, self.dropped_waits, self.behind_frames,
                    ",".join(str(s) for s in self.holding()) or "none",
                    ",".join(str(s) for s in self.waiting()) or "none", per_slot or "none")


def clamp_int(raw, default, low, high):
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return default
    return max(low, min(high, value))


def clamp_max_frames(raw):
    return clamp_int(raw, DEFAULT_MAX_HOLD_FRAMES, 1, MAX_HOLD_FRAMES_LIMIT)


def clamp_per_frame(raw):
    return clamp_int(raw, DEFAULT_HOLDS_PER_FRAME, 1, HOLDS_PER_FRAME_LIMIT)


def keyframe_seconds(raw):
    """sv_demoStreamKeyframeSec the way the engine reads it: 0 or less is off, else 2..60.

    Off means no periodic keyframes. The counter path still runs then: it is also how the first
    slot after a reconnect is found.
    """
    try:
        value = int(float(str(raw).strip()))
    except (TypeError, ValueError):
        return DEFAULT_KEYFRAME_SEC
    if value <= 0:
        return 0
    return max(KEYFRAME_SEC_MIN, min(KEYFRAME_SEC_MAX, value))


def cvar_on(raw):
    return str(raw if raw is not None else "").strip().lower() not in ("", "0", "false", "off", "no")


class demo_stream_resync_hold(minqlx.Plugin):
    def __init__(self):
        self.plugin_version = "1.2"
        # Off until it has been measured on a populated server and in team modes.
        self.set_cvar_once("qlx_demoStreamResyncHold", "0")
        self.set_cvar_once("qlx_demoStreamResyncHoldMaxFrames", str(DEFAULT_MAX_HOLD_FRAMES))
        self.set_cvar_once("qlx_demoStreamResyncHoldPerFrame", str(DEFAULT_HOLDS_PER_FRAME))

        self.hold = ResyncHold(cs_active=getattr(minqlx, "CS_ACTIVE", CS_ACTIVE_FALLBACK))
        self._supported = hasattr(minqlx, "stream_status") and hasattr(minqlx, "Client")
        self._enabled = False
        self._max_frames = DEFAULT_MAX_HOLD_FRAMES
        self._per_frame = DEFAULT_HOLDS_PER_FRAME
        self._keyframe_sec = DEFAULT_KEYFRAME_SEC
        self._stream_on = False
        self._errors = 0
        self._broken_at = None
        self._tick = 0
        self._read_cvars()
        if not self._supported:
            self.logger.warning(
                "demo_stream_resync_hold: this runtime has no stream_status() / Client view, the plugin does nothing")

        self.add_hook("frame", self.handle_frame)
        self.add_hook("map", self.handle_map)
        self.add_hook("player_disconnect", self.handle_player_disconnect)
        self.add_command("resynchold", self.cmd_resynchold, 5, usage="[log]")

    def _read_cvars(self):
        was_enabled = self._enabled
        self._enabled = cvar_on(self.get_cvar("qlx_demoStreamResyncHold"))
        self._max_frames = clamp_max_frames(self.get_cvar("qlx_demoStreamResyncHoldMaxFrames"))
        self._per_frame = clamp_per_frame(self.get_cvar("qlx_demoStreamResyncHoldPerFrame"))
        self._keyframe_sec = keyframe_seconds(self.get_cvar("sv_demoStreamKeyframeSec"))
        if self._enabled and not was_enabled and self._broken_at is not None:
            self._rearm()  # switching it off and on again is the operator's retry

    def _rearm(self):
        self._broken_at = None
        self._errors = 0

    @staticmethod
    def _client_of(slot):
        try:
            return minqlx.Client(slot)
        except Exception:
            return None

    def handle_frame(self):
        if not self._supported:
            return
        hold = self.hold
        self._tick += 1
        slow_tick = self._tick % SLOW_POLL_FRAMES == 0
        now = time.monotonic()
        try:
            if slow_tick:
                self._read_cvars()
            if not self._enabled:
                if hold._slots:
                    hold.reset()
            elif self._broken_at is not None and now - self._broken_at < BROKEN_RETRY_SEC:
                return
            else:
                if self._broken_at is not None:
                    self._rearm()
                if self._stream_on or slow_tick:
                    status = minqlx.stream_status()
                    self._stream_on = bool(status.enabled)
                    hold.frame(status, self._client_of, self._max_frames, now, self._keyframe_sec, self._per_frame)
            if slow_tick:
                self._errors = 0  # a whole second's worth of work went through
        except Exception:
            if self._broken_at is not None:
                return  # already switched off; the next retry reports again
            self._errors += 1
            self.logger.exception("demo_stream_resync_hold: frame hook failed")
            if self._errors >= MAX_ERRORS_IN_A_ROW:
                self._broken_at = now
                hold.reset()
                self.logger.warning(
                    "demo_stream_resync_hold: %d errors in a row, switched off for %d s "
                    "(or until qlx_demoStreamResyncHold is set to 0 and back to 1)",
                    self._errors, int(BROKEN_RETRY_SEC))

    def handle_map(self, *args, **kwargs):
        self.hold.reset()

    def handle_player_disconnect(self, player, reason):
        try:
            self.hold.drop_slot(int(player.id))
        except Exception:
            pass

    def cmd_resynchold(self, player, msg, channel):
        self._read_cvars()
        if not self._supported:
            state = "unsupported runtime"
        elif not self._enabled:
            state = "off"
        elif self._broken_at is not None:
            state = "switched off after errors"
        else:
            state = "on"
        if len(msg) > 1 and msg[1].lower() == "log":
            # The console gets the whole log; a chat channel a few lines, so nobody is flooded.
            to_console = type(channel).__name__ == "ConsoleChannel"
            lines = self.hold.log_lines(EVENT_LOG_SIZE if to_console else CHAT_LOG_LINES)
            for line in lines or ["no holds yet"]:
                channel.reply(line)
            return
        channel.reply("demo_stream_resync_hold {}: {}, cap {} per hold, {} holds at once, keyframes every {} s, {}".format(
            self.plugin_version, state, self._max_frames, self._per_frame, self._keyframe_sec, self.hold.summary()))
