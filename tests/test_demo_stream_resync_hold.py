"""demo_stream_resync_hold: the hold logic against a fake engine, without a server.

The fake engine keeps the fork's frame order (src/server/hooks.c, My_G_RunFrame): client
packets, then the plugin's frame hook, then Stream_Frame (keyframes, forced resyncs), then the
snapshots go out. A client acknowledges a message `ping_frames` frames after it was sent and its
next packet overwrites deltaMessage, as SV_UserMove does.
"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _minqlx_stub import REPO_ROOT, bare_instance, import_plugin  # noqa: E402

pytestmark = pytest.mark.standalone

CS_ACTIVE = 4
FRAME_SEC = 0.025


@pytest.fixture(scope="module")
def mod():
    return import_plugin("demo_stream_resync_hold")


class FakeClient:
    def __init__(self, ping_frames):
        self.state = CS_ACTIVE
        self.delta_message = 0
        self.message_acknowledge = 0
        self.netchan = SimpleNamespace(outgoing_sequence=100, unsent_fragments=False)
        self.ping_frames = ping_frames
        self.in_flight = []   # (frame the acknowledgement arrives, message number)
        self.sent = {}        # message number -> base message, or None for a full snapshot
        self.asked = 0        # deltaMessage as the client's last packet left it


class FakeEngine:
    def __init__(self, mod, pings, keyframe_frames=0, budget=1, fresh=False):
        self.hold = mod.ResyncHold(cs_active=CS_ACTIVE)
        # fresh=False: the plugin was already watching when the slots opened.
        self.hold._fresh = fresh
        self.clients = {slot: FakeClient(p) for slot, p in pings.items()}
        self.active = {slot: True for slot in pings}
        self.gen = {slot: 1 for slot in pings}
        self.pending = {slot: False for slot in pings}
        self.last_full = {slot: 0 for slot in pings}
        self.enabled = True
        self.link_up = True
        self.resyncs = 0
        self.lag = 0
        self.queued = 0
        self.dropped_ring = 0
        self.dropped_lag = 0
        self.resync_all = False
        self.keyframe_frames = keyframe_frames
        self.budget = budget
        self.cursor = 0
        self.frame = 0
        self.plugin_on = True
        self.max_frames = mod.DEFAULT_MAX_HOLD_FRAMES
        self.per_frame = mod.DEFAULT_HOLDS_PER_FRAME
        self.hub = {slot: set() for slot in pings}        # message numbers the relay received
        self.hub_full = {slot: [] for slot in pings}
        self.engine_forced = {slot: [] for slot in pings}  # messages the engine itself forced full
        self.plugin_forced = {slot: [] for slot in pings}  # frames in which the plugin's -1 was sent
        self.plugin_forced_per_frame = []

    def status(self):
        slots = tuple(SimpleNamespace(slot=s, active=self.active[s], resyncing=self.pending[s], gen=self.gen[s])
                      for s in sorted(self.clients))
        return SimpleNamespace(enabled=self.enabled, connected=self.link_up, resyncs=self.resyncs, slots=slots,
                               lag=self.lag, pending=self.queued, dropped_ring=self.dropped_ring,
                               dropped_lag=self.dropped_lag, dropped_stall=0)

    def client_of(self, slot):
        return self.clients.get(slot)

    def step(self):
        self.frame += 1
        # 1. client packets
        for cl in self.clients.values():
            if cl.state != CS_ACTIVE:
                continue
            arrived = [m for at, m in cl.in_flight if at <= self.frame]
            cl.in_flight = [(at, m) for at, m in cl.in_flight if at > self.frame]
            if arrived:
                cl.message_acknowledge = max(cl.message_acknowledge, max(arrived))
            cl.delta_message = cl.asked = cl.message_acknowledge
        # 2. the plugin's frame hook
        if self.plugin_on:
            self.hold.frame(self.status(), self.client_of, self.max_frames, self.frame * FRAME_SEC,
                            self.keyframe_frames * FRAME_SEC, self.per_frame)
        by_plugin = {slot for slot, cl in self.clients.items() if cl.delta_message == -1 and cl.asked > 0}
        # 3. Stream_Frame
        by_engine = set()
        if self.enabled:
            if self.resync_all:
                self.resync_all = False
                for slot in self.clients:
                    if self.active[slot]:
                        self.pending[slot] = True
            if self.keyframe_frames and self.link_up:
                for slot in self.clients:
                    if self.active[slot] and not self.pending[slot] and \
                            self.frame - self.last_full[slot] >= self.keyframe_frames:
                        self.pending[slot] = True
            budget = self.budget
            order = sorted(self.clients)
            for n in range(len(order)):
                slot = order[(self.cursor + n) % len(order)]
                if budget <= 0:
                    break
                if not self.pending[slot] or not self.active[slot]:
                    continue
                cl = self.clients[slot]
                if cl.state != CS_ACTIVE or cl.netchan.unsent_fragments:
                    continue
                cl.delta_message = -1
                by_engine.add(slot)
                self.cursor = (order.index(slot) + 1) % len(order)
                budget -= 1
                self.resyncs += 1
        # 4. snapshots
        forced_now = 0
        for slot, cl in self.clients.items():
            if cl.state != CS_ACTIVE or cl.netchan.unsent_fragments:
                continue
            seq = cl.netchan.outgoing_sequence
            full = cl.delta_message <= 0
            cl.sent[seq] = None if full else cl.delta_message
            cl.netchan.outgoing_sequence = seq + 1
            cl.in_flight.append((self.frame + cl.ping_frames, seq))
            if slot in by_engine:
                self.engine_forced[slot].append(seq)
            if slot in by_plugin:
                forced_now += 1
                self.plugin_forced[slot].append(self.frame)
            if not (self.enabled and self.active[slot]):
                continue
            if not self.link_up:
                self.pending[slot] = True   # stream_note_drop: a gap, ask for a resync
                continue
            self.hub[slot].add(seq)
            if full:
                self.hub_full[slot].append(seq)
                self.pending[slot] = False
                self.last_full[slot] = self.frame
        self.plugin_forced_per_frame.append(forced_now)

    def run(self, frames):
        for _ in range(frames):
            self.step()

    def fulls(self, slot, since):
        cl = self.clients[slot]
        return sorted(m for m, base in cl.sent.items() if base is None and m >= since)

    def undecodable(self, slot, first_full):
        """Messages after `first_full` the relay cannot decode, starting from that full snapshot."""
        cl = self.clients[slot]
        ok = {first_full}
        bad = []
        for m in sorted(x for x in cl.sent if x > first_full and x in self.hub[slot]):
            base = cl.sent[m]
            if base is None or base in ok:
                ok.add(m)
            else:
                bad.append(m)
        return bad

    def reconnect(self, down_frames):
        self.link_up = False
        self.run(down_frames)
        self.link_up = True
        self.resync_all = True   # the epoch bump: Stream_ResyncAll on the next Stream_Frame


def stagger(mod, eng, phases):
    """Give each slot its own keyframe phase, known to the plugin as if it saw the slots open."""
    eng.run(8)   # the first messages of a fake client are full snapshots; let them pass
    for slot, when in phases.items():
        eng.last_full[slot] = when
        eng.hold._slots[slot].last_full = when * FRAME_SEC


def test_without_the_plugin_the_chain_behind_a_single_full_snapshot_is_broken(mod):
    eng = FakeEngine(mod, {0: 2})
    eng.plugin_on = False
    eng.run(10)
    start = eng.clients[0].netchan.outgoing_sequence
    eng.reconnect(5)
    eng.run(40)
    first = min(m for m in eng.hub_full[0] if m >= start)
    assert eng.undecodable(0, first), "the model must reproduce the measured problem"


def test_hold_starts_on_a_resync_and_ends_when_the_client_acknowledges(mod):
    eng = FakeEngine(mod, {0: 2})
    eng.run(10)
    start = eng.clients[0].netchan.outgoing_sequence
    eng.reconnect(5)
    eng.run(40)
    first = min(m for m in eng.hub_full[0] if m >= start)
    assert eng.undecodable(0, first) == []
    h = eng.hold
    assert h.started == 1 and h.acked == 1 and h.capped == 0
    assert h.holding() == []
    assert 1 <= h.forced <= mod.DEFAULT_MAX_HOLD_FRAMES
    assert h.forced == len(eng.plugin_forced[0])
    # after the hold the engine is left alone: no more full snapshots
    assert max(eng.fulls(0, start)) < start + 5 + 2 + h.forced + 2


def test_delta_message_is_kept_at_minus_one_on_every_frame_of_the_hold(mod):
    eng = FakeEngine(mod, {0: 4})
    eng.run(10)
    eng.resync_all = True
    eng.step()          # the engine forces one full snapshot
    forced_at = eng.clients[0].netchan.outgoing_sequence - 1
    seen = []
    for _ in range(12):
        eng.step()
        seen.append(eng.clients[0].sent[eng.clients[0].netchan.outgoing_sequence - 1] is None)
    run = seen.index(False)
    assert run >= 4 and all(seen[:run]) and not any(seen[run:])
    assert eng.undecodable(0, forced_at) == []
    assert eng.hold.forced == run and eng.hold.longest == run


def test_hold_stops_at_the_cap_when_the_acknowledgement_never_comes(mod):
    eng = FakeEngine(mod, {0: 30})   # round trip far above the cap
    eng.run(40)
    eng.resync_all = True
    eng.run(30)
    h = eng.hold
    assert h.started == 1 and h.capped == 1 and h.acked == 0
    assert h.forced == mod.DEFAULT_MAX_HOLD_FRAMES == len(eng.plugin_forced[0])
    assert h.holding() == []


def test_cap_is_configurable(mod):
    eng = FakeEngine(mod, {0: 30})
    eng.max_frames = 3
    eng.run(40)
    eng.resync_all = True
    eng.run(30)
    assert eng.hold.forced == 3 and eng.hold.capped == 1


def test_no_second_hold_while_one_runs_and_never_continuous(mod):
    eng = FakeEngine(mod, {0: 30})
    eng.run(40)
    for _ in range(120):         # the engine asks for a resync on every single frame
        eng.resync_all = True
        eng.step()
    h = eng.hold
    assert len(h.holding()) <= 1
    assert h.started >= 2
    # every hold is followed by the cooldown, so far fewer than 120 frames were forced
    per_cycle = mod.DEFAULT_MAX_HOLD_FRAMES + mod.HOLD_COOLDOWN_FRAMES
    assert len(eng.plugin_forced[0]) <= (120 // per_cycle + 1) * mod.DEFAULT_MAX_HOLD_FRAMES
    assert h.started - h.acked - h.capped - h.cancelled == len(h.holding())


def test_a_flag_resync_during_a_hold_moves_the_anchor_but_not_the_cap(mod):
    eng = FakeEngine(mod, {0: 3})
    eng.run(10)
    eng.resync_all = True
    eng.run(3)
    assert eng.hold.holding() == [0]
    eng.pending[0] = True        # blocks were lost during the hold (stream_note_drop)
    eng.run(30)
    h = eng.hold
    assert h.started == 1 and h.retargeted == 1
    assert h.forced <= mod.DEFAULT_MAX_HOLD_FRAMES


def test_nothing_when_the_cvar_is_off_or_the_stream_is_off(mod):
    eng = FakeEngine(mod, {0: 2})
    eng.plugin_on = False        # what the plugin does with the cvar off: frame() is not called
    eng.run(10)
    eng.reconnect(5)
    eng.run(20)
    assert eng.hold.started == 0 and eng.plugin_forced[0] == []

    off = FakeEngine(mod, {0: 2})
    off.enabled = False
    off.run(10)
    off.resyncs += 5             # a counter that moves must not matter
    off.run(10)
    assert off.hold.started == 0 and off.plugin_forced[0] == []
    off.hold.frame(None, off.client_of)
    assert off.hold.started == 0


def test_link_down_forces_nothing(mod):
    eng = FakeEngine(mod, {0: 2})
    eng.run(10)
    eng.link_up = False
    eng.run(50)                  # the engine itself resyncs on every frame here
    assert eng.resyncs >= 40
    assert eng.hold.started == 0 and eng.plugin_forced[0] == []


def test_a_client_that_leaves_mid_hold_is_dropped(mod):
    eng = FakeEngine(mod, {0: 30})
    eng.run(40)
    eng.resync_all = True
    eng.run(3)
    assert eng.hold.holding() == [0]
    eng.clients[0].state = 1     # zombie
    eng.clients[0].delta_message = 55
    eng.run(3)
    assert eng.hold.holding() == [] and eng.hold.cancelled == 1
    assert eng.clients[0].delta_message == 55, "a client that left is not written to"

    gone = FakeEngine(mod, {0: 30})
    gone.run(40)
    gone.resync_all = True
    gone.run(3)
    gone.hold.drop_slot(0)       # the player_disconnect hook
    assert gone.hold.holding() == [] and gone.hold.cancelled == 1


def test_map_change_cancels_holds(mod):
    eng = FakeEngine(mod, {0: 30})
    eng.run(40)
    eng.resync_all = True
    eng.run(3)
    assert eng.hold.holding() == [0]
    eng.gen[0] += 1              # a new gamestate reopens the slot
    forced = len(eng.plugin_forced[0])
    eng.run(3)
    assert eng.hold.holding() == [] and eng.hold.cancelled == 1 and len(eng.plugin_forced[0]) == forced

    reset = FakeEngine(mod, {0: 30})
    reset.run(40)
    reset.resync_all = True
    reset.run(3)
    reset.hold.reset()           # the map hook
    assert reset.hold.holding() == [] and reset.hold.cancelled == 1


def test_slots_that_are_not_streamed_are_never_touched(mod):
    """Bots get no messages, so the engine never opens a stream slot for them."""
    eng = FakeEngine(mod, {0: 2, 1: 2})
    eng.active[1] = False
    eng.run(10)
    eng.reconnect(5)
    eng.run(40)
    assert eng.fulls(1, 105) == [] and eng.plugin_forced[1] == []
    assert eng.hold.started == 1


def test_reconnect_with_several_povs_holds_each_exactly_once(mod):
    eng = FakeEngine(mod, {0: 2, 1: 3, 2: 1, 3: 2})
    eng.run(10)
    start = {s: eng.clients[s].netchan.outgoing_sequence for s in eng.clients}
    eng.reconnect(5)
    eng.run(60)
    assert eng.hold.started == 4 and eng.hold.acked == 4
    assert max(eng.plugin_forced_per_frame) <= eng.per_frame
    for slot in eng.clients:
        first = min(m for m in eng.hub_full[slot] if m >= start[slot])
        assert eng.undecodable(slot, first) == []


def test_reconnect_without_lost_blocks_with_several_povs(mod):
    eng = FakeEngine(mod, {0: 2, 1: 3, 2: 2})
    eng.run(10)
    eng.resync_all = True        # the link flapped between two frames: no gap, only the epoch
    eng.run(60)
    assert eng.hold.started == 3 and eng.hold.acked == 3


def _held_keyframes(eng, slot, since, within):
    """(engine keyframes of the slot, how many of them got a hold within `within` messages)."""
    cl = eng.clients[slot]
    keyframes = [m for m in eng.engine_forced[slot] if m >= since]
    held = 0
    for m in keyframes:
        # some later message starts a run of full snapshots from which the chain never breaks
        if any(cl.sent.get(k) is None and eng.undecodable(slot, k) == [] for k in range(m + 1, m + 1 + within)):
            held += 1
    return len(keyframes), held


def test_keyframes_with_several_povs_keep_their_own_phase(mod):
    eng = FakeEngine(mod, {0: 2, 1: 3, 2: 2}, keyframe_frames=100)
    stagger(mod, eng, {0: 0, 1: 30, 2: 60})   # as slots opened at different times
    since = {s: eng.clients[s].netchan.outgoing_sequence for s in eng.clients}
    eng.run(1000)
    h = eng.hold
    assert h.started == h.acked and h.capped == 0 and h.guessed == 0
    for slot in eng.clients:
        keyframes, held = _held_keyframes(eng, slot, since[slot], within=2)
        assert keyframes >= 8 and held == keyframes, "slot {}: {} of {}".format(slot, held, keyframes)
        assert eng.hold.per_slot[slot][0] == keyframes
    # a keyframe of one slot does not pull the other slots into the same frame
    first = sorted(eng.plugin_forced[slot][0] for slot in eng.clients)
    assert first[1] - first[0] >= 20 and first[2] - first[1] >= 20


def test_first_sight_makes_unknown_slots_known(mod):
    """Loaded in the middle of a stream: one hold per slot, then keyframes are held without a guess."""
    eng = FakeEngine(mod, {0: 2, 1: 2, 2: 3}, keyframe_frames=100, fresh=True)
    eng.plugin_on = False
    eng.run(8)
    eng.last_full = {0: 0, 1: 40, 2: 70}
    eng.run(322)                             # keyframes already ran without the plugin
    eng.plugin_on = True
    eng.run(12)
    assert eng.hold.started == 3 and eng.hold.by_counter == 0
    assert max(eng.plugin_forced_per_frame) <= eng.per_frame
    since = {s: eng.clients[s].netchan.outgoing_sequence for s in eng.clients}
    eng.run(800)
    assert eng.hold.guessed == 0
    for slot in eng.clients:
        keyframes, held = _held_keyframes(eng, slot, since[slot], within=2)
        assert keyframes >= 6 and held == keyframes


def test_sixteen_povs_stay_within_the_per_frame_budget(mod):
    pings = {slot: 2 + slot % 3 for slot in range(16)}
    eng = FakeEngine(mod, pings, keyframe_frames=80)        # sv_demoStreamKeyframeSec 2, the minimum
    stagger(mod, eng, {slot: (slot * 37) % 80 for slot in pings})
    since = {s: eng.clients[s].netchan.outgoing_sequence for s in eng.clients}
    eng.run(600)
    eng.clients[5].state = 1                 # a player leaves and another joins out of phase
    eng.run(3)
    eng.clients[5].state = CS_ACTIVE
    eng.gen[5] += 1
    eng.last_full[5] = eng.frame
    since[5] = eng.clients[5].netchan.outgoing_sequence + 4
    eng.run(1000)
    assert max(eng.plugin_forced_per_frame) <= eng.per_frame == 2
    for slot in eng.clients:
        keyframes, held = _held_keyframes(eng, slot, since[slot], within=12)
        assert keyframes >= 10 and held == keyframes, "slot {}: {} of {}".format(slot, held, keyframes)
    # one hold per slot per keyframe: 2-5 forced snapshots per slot per 80 frames
    forced = sum(eng.plugin_forced_per_frame)
    assert forced <= 16 * (1608 // 80 + 1) * 5


def test_forced_share_is_bounded_at_the_shortest_interval_and_the_longest_cap(mod):
    eng = FakeEngine(mod, {slot: 60 for slot in range(16)}, keyframe_frames=80)   # nobody ever acknowledges in time
    eng.max_frames = mod.MAX_HOLD_FRAMES_LIMIT
    stagger(mod, eng, {slot: slot * 5 for slot in range(16)})
    eng.run(2000)
    assert max(eng.plugin_forced_per_frame) <= 2
    cycle = mod.MAX_HOLD_FRAMES_LIMIT + mod.HOLD_COOLDOWN_FRAMES
    for slot in eng.clients:
        assert len(eng.plugin_forced[slot]) <= (2000 // cycle + 1) * mod.MAX_HOLD_FRAMES_LIMIT
    assert eng.hold.capped > 0 and eng.hold.acked == 0


def test_a_keyframe_during_a_resync_storm_still_gets_its_hold(mod):
    """Three slots flagged and waiting, a fourth slot's keyframe forced: the counter rose by one
    and no flag cleared, so one resync is unexplained."""
    eng = FakeEngine(mod, {0: 2, 1: 2, 2: 2, 3: 2}, keyframe_frames=100)
    stagger(mod, eng, {0: 20, 1: 20, 2: 20, 3: 0})
    eng.run(50)
    for slot in (0, 1, 2):
        eng.pending[slot] = True
        eng.clients[slot].netchan.unsent_fragments = True   # the engine skips them: flagged, not forced
    eng.run(60)
    assert len(eng.engine_forced[3]) == 1
    keyframe = eng.engine_forced[3][0]
    assert eng.hold.per_slot.get(3, [0, 0])[0] == 1
    assert eng.clients[3].sent[keyframe + 1] is None
    assert all(eng.plugin_forced[slot] == [] for slot in (0, 1, 2))


def test_nothing_is_held_while_the_relay_is_behind(mod):
    eng = FakeEngine(mod, {0: 30, 1: 2})
    eng.run(40)
    eng.resync_all = True
    eng.run(4)
    assert eng.hold.holding()
    eng.lag = mod.BEHIND_LAG_MS      # the relay falls behind: the running holds are cancelled
    eng.step()
    assert eng.hold.holding() == [] and eng.hold.cancelled >= 1
    forced = sum(eng.plugin_forced_per_frame)
    for _ in range(30):              # the engine resyncs on every frame; nothing may start
        eng.resync_all = True
        eng.step()
    assert sum(eng.plugin_forced_per_frame) == forced and eng.hold.holding() == []

    eng.lag = 0
    eng.pending[1] = True            # the gap is repaired when the relay has caught up
    eng.run(mod.BEHIND_RECOVER_FRAMES + 10)
    assert eng.hold.per_slot[1][0] >= 2
    text = chr(10).join(eng.hold.log_lines())
    assert "relay is behind, holds stopped" in text and "relay caught up" in text


def test_dropped_blocks_and_a_deep_ring_count_as_behind(mod):
    for field, value in (("dropped_ring", 1), ("dropped_lag", 3), ("queued", None)):
        eng = FakeEngine(mod, {0: 2})
        eng.run(10)
        setattr(eng, field, mod.BEHIND_PENDING_BYTES if value is None else value)
        eng.resync_all = True
        eng.run(10)
        assert eng.hold.started == 0, field
        assert eng.hold.behind_frames > 0


def test_frames_without_a_snapshot_do_not_use_up_the_cap(mod):
    eng = FakeEngine(mod, {0: 6})
    eng.max_frames = 4
    eng.run(20)
    eng.resync_all = True
    eng.run(3)                   # the hold has forced two snapshots
    assert eng.hold.holding() == [0] and len(eng.plugin_forced[0]) == 2
    eng.clients[0].netchan.unsent_fragments = True   # the engine sends this client nothing for a while
    eng.run(3)                   # five frames into the hold: a frame count would have hit the cap of 4
    assert eng.hold.holding() == [0] and eng.hold.capped == 0
    assert len(eng.plugin_forced[0]) == 2
    eng.clients[0].netchan.unsent_fragments = False
    eng.run(20)
    h = eng.hold
    assert h.acked == 1 and h.capped == 0
    assert h.forced == len(eng.plugin_forced[0]) <= 4


def test_a_hold_whose_client_is_never_sent_anything_ends(mod):
    eng = FakeEngine(mod, {0: 200})
    eng.run(20)
    eng.resync_all = True
    eng.run(2)
    eng.clients[0].netchan.unsent_fragments = True
    eng.run(mod.DEFAULT_MAX_HOLD_FRAMES * mod.HOLD_STALL_FACTOR + 2)
    assert eng.hold.holding() == [] and eng.hold.capped == 1


def test_a_flag_resync_does_not_wait_for_the_cooldown_but_a_keyframe_does(mod):
    eng = FakeEngine(mod, {0: 2})
    eng.run(10)
    eng.resync_all = True
    eng.run(6)
    assert eng.hold.started == 1 and eng.hold.holding() == []
    eng.pending[0] = True            # a real loss right after the hold ended
    eng.run(3)
    assert eng.hold.started == 2

    slow = FakeEngine(mod, {0: 2})
    slow.run(10)
    slow.resync_all = True
    slow.run(6)
    slow.resync_all = True           # the counter path: a keyframe-like resync
    slow.run(5)
    assert slow.hold.started == 1 and slow.hold.waiting() == [0]
    slow.run(mod.HOLD_COOLDOWN_FRAMES)
    assert slow.hold.started == 2


def _blocked_queue(mod):
    """Slot 0 holds for a long time with room for one hold only; slot 1 waits behind it."""
    eng = FakeEngine(mod, {0: 60, 1: 2})
    eng.per_frame = 1
    eng.max_frames = mod.MAX_HOLD_FRAMES_LIMIT
    eng.run(20)
    eng.resync_all = True
    eng.run(4)
    assert eng.hold.holding() == [0] and eng.hold.waiting() == [1]
    return eng


def test_a_waiting_hold_is_forgotten_when_its_player_leaves(mod):
    eng = _blocked_queue(mod)
    eng.hold.drop_slot(1)            # the player_disconnect hook
    eng.run(40)
    assert eng.hold.waiting() == [] and eng.plugin_forced[1] == []

    idle = _blocked_queue(mod)
    idle.clients[1].state = 1        # not active any more, the slot is still listed
    idle.run(40)
    assert idle.hold.waiting() == [] and idle.plugin_forced[1] == []


def test_a_waiting_hold_is_forgotten_when_the_slot_is_reused_or_the_map_changes(mod):
    eng = _blocked_queue(mod)
    eng.gen[1] += 1                  # a new gamestate: another player, or the same one on a new map
    eng.run(40)
    assert eng.hold.waiting() == [] and eng.plugin_forced[1] == []

    reset = _blocked_queue(mod)
    reset.hold.reset()               # the map hook
    assert reset.hold.waiting() == [] and reset.hold.holding() == []
    assert reset.hold._behind is False and reset.hold._behind_until == 0


def test_reset_clears_the_behind_state(mod):
    eng = FakeEngine(mod, {0: 2})
    eng.run(10)
    eng.lag = mod.BEHIND_LAG_MS
    eng.run(3)
    assert eng.hold._behind
    eng.hold.reset()
    assert eng.hold._behind is False and eng.hold._behind_until == 0
    eng.lag = 0
    eng.pending[0] = True            # a healthy relay after the reset: holds work at once
    eng.run(4)
    assert eng.hold.started == 1


def test_waits_from_before_a_behind_episode_do_not_start_after_it(mod):
    eng = FakeEngine(mod, {0: 2})
    eng.run(10)
    eng.resync_all = True
    eng.run(6)
    eng.resync_all = True            # a keyframe-like resync: its hold waits for the cooldown
    eng.run(3)
    assert eng.hold.started == 1 and eng.hold.waiting() == [0]
    eng.lag = mod.BEHIND_LAG_MS      # the relay falls behind: the keyframe wait is given up
    eng.step()
    assert eng.hold.waiting() == [] and eng.hold.dropped_waits == 1
    for _ in range(100):             # the engine keeps resyncing while the relay is behind
        eng.resync_all = True
        eng.step()
    eng.lag = 0
    eng.run(mod.BEHIND_RECOVER_FRAMES + 30)
    assert eng.hold.started == 1, "nothing left over from the episode may start"
    assert "waits dropped 1" in eng.hold.summary()
    assert "waiting hold (counter) dropped: relay is behind" in chr(10).join(eng.hold.log_lines())


def test_a_flag_wait_survives_a_behind_episode(mod):
    eng = FakeEngine(mod, {0: 2})
    eng.run(10)
    eng.lag = mod.BEHIND_LAG_MS
    eng.run(3)
    eng.pending[0] = True            # a real loss, repaired by the engine while the relay is behind
    eng.run(5)
    assert eng.hold.waiting() == [0] and eng.hold.started == 0
    eng.lag = 0
    eng.run(mod.BEHIND_RECOVER_FRAMES + 5)
    assert eng.hold.started == 1 and eng.hold.dropped_waits == 0


def test_a_wait_that_gets_too_old_behind_the_budget_is_dropped_and_counted(mod):
    eng = FakeEngine(mod, {slot: 60 for slot in range(8)})   # nobody acknowledges: every hold runs to the cap
    eng.per_frame = 1
    eng.max_frames = mod.MAX_HOLD_FRAMES_LIMIT
    eng.run(20)
    for slot in range(8):
        eng.hold._ask(slot, eng.hold._slots[slot], "counter")
    eng.run(200)
    h = eng.hold
    # one hold at a time, 16 frames each: only the first few fit into 60 frames of waiting
    fit = mod.WAIT_MAX_AGE_FRAMES // mod.MAX_HOLD_FRAMES_LIMIT + 1
    assert h.started <= fit + 1 and h.dropped_waits == 8 - h.started >= 3
    assert h.waiting() == [] and max(eng.plugin_forced_per_frame) == 1
    assert "waits dropped {}".format(h.dropped_waits) in h.summary()
    assert "dropped: waited too long" in chr(10).join(h.log_lines())


def test_a_flag_wait_does_not_age_out(mod):
    eng = FakeEngine(mod, {slot: 60 for slot in range(8)})
    eng.per_frame = 1
    eng.max_frames = mod.MAX_HOLD_FRAMES_LIMIT
    eng.run(20)
    for slot in range(8):
        eng.hold._ask(slot, eng.hold._slots[slot], "flag")
    eng.run(200)
    assert eng.hold.started == 8 and eng.hold.dropped_waits == 0


def test_the_queue_serves_flag_then_keyframe_then_first_sight_oldest_first(mod):
    eng = FakeEngine(mod, {slot: 2 for slot in range(5)})
    eng.per_frame = 1
    eng.run(20)
    h = eng.hold
    for slot, why, age in ((4, "first sight", 9), (3, "counter", 2), (1, "counter", 6), (2, "flag", 1), (0, "flag", 4)):
        h._ask(slot, h._slots[slot], why)
        h._slots[slot].want_frame = h.frame_no - age
    eng.run(40)
    order = [int(line.split("slot ")[1].split(":")[0]) for line in h.log_lines() if "hold started" in line]
    assert order == [0, 2, 1, 3, 4]


def test_one_dropped_block_holds_everything_off_for_a_while_and_then_lets_go(mod):
    eng = FakeEngine(mod, {0: 2})
    eng.run(10)
    eng.dropped_ring = 1             # grew once and stays at 1
    eng.pending[0] = True
    eng.run(mod.BEHIND_RECOVER_FRAMES - 2)
    assert eng.hold.started == 0 and eng.hold._behind
    eng.run(10)
    assert not eng.hold._behind and eng.hold.started == 1   # the flag wait from the episode
    assert eng.hold.behind_frames == mod.BEHIND_RECOVER_FRAMES
    eng.pending[0] = True            # and the gate is open again
    eng.run(5)
    assert eng.hold.started == 2


def test_log_shows_each_recovery_per_slot(mod):
    eng = FakeEngine(mod, {0: 2, 1: 3})
    eng.run(10)
    eng.reconnect(6)
    eng.run(40)
    text = chr(10).join(eng.hold.log_lines())
    assert "stream: link down" in text
    assert "stream: link up, the engine forced 4 full snapshots while it was down" in text
    for slot in (0, 1):
        assert "slot {}: hold started (flag), anchor ".format(slot) in text
        assert "slot {}: hold ended: acknowledged ".format(slot) in text
    assert eng.hold.per_slot[0][0] == 1 and eng.hold.per_slot[1][0] == 1
    assert "per slot holds/forced: 0:1/" in eng.hold.summary()


def test_summary_and_cvar_parsing(mod):
    h = mod.ResyncHold()
    text = h.summary()
    assert "holds 0" in text and "holding now: none" in text
    assert mod.clamp_max_frames("8") == 8
    assert mod.clamp_max_frames("0") == 1
    assert mod.clamp_max_frames("500") == mod.MAX_HOLD_FRAMES_LIMIT
    assert mod.clamp_max_frames("abc") == mod.DEFAULT_MAX_HOLD_FRAMES
    assert mod.clamp_max_frames(None) == mod.DEFAULT_MAX_HOLD_FRAMES
    assert mod.clamp_per_frame("0") == 1 and mod.clamp_per_frame("99") == mod.HOLDS_PER_FRAME_LIMIT
    assert mod.clamp_per_frame(None) == mod.DEFAULT_HOLDS_PER_FRAME == 2
    assert mod.keyframe_seconds("10") == 10 and mod.keyframe_seconds("0") == 0
    assert mod.keyframe_seconds("1") == 2 and mod.keyframe_seconds("600") == 60
    assert mod.keyframe_seconds(None) == mod.DEFAULT_KEYFRAME_SEC
    assert mod.cvar_on("1") and not mod.cvar_on("0") and not mod.cvar_on("") and not mod.cvar_on(None)


class _Logger:
    def __init__(self):
        self.lines = []

    def warning(self, *a):
        self.lines.append(a)

    def exception(self, *a):
        self.lines.append(a)


def _plugin(mod, cvars, **attrs):
    reads = []

    def get_cvar(name):
        reads.append(name)
        return cvars.get(name)

    base = dict(hold=mod.ResyncHold(), logger=_Logger(), get_cvar=get_cvar, cvar_reads=reads,
                _supported=True, _enabled=False, _max_frames=8, _per_frame=2, _keyframe_sec=10,
                _stream_on=False, _errors=0, _broken_at=None, _tick=0, plugin_version="1.2")
    base.update(attrs)
    return bare_instance(mod.demo_stream_resync_hold, **base)


def test_plugin_class_matches_module_name(mod):
    assert hasattr(mod, "demo_stream_resync_hold")


def test_frame_hook_with_the_cvar_off_never_asks_the_engine(mod, monkeypatch):
    calls = []
    monkeypatch.setattr(mod.minqlx, "stream_status", lambda: calls.append(1), raising=False)
    p = _plugin(mod, {"qlx_demoStreamResyncHold": "0"})
    for _ in range(100):
        p.handle_frame()
    assert calls == []


def test_frame_hook_polls_slowly_while_the_stream_is_off(mod, monkeypatch):
    calls = []

    def status():
        calls.append(1)
        return SimpleNamespace(enabled=False, connected=False, resyncs=0, slots=())

    monkeypatch.setattr(mod.minqlx, "stream_status", status, raising=False)
    p = _plugin(mod, {"qlx_demoStreamResyncHold": "1"})
    for _ in range(mod.SLOW_POLL_FRAMES * 3):
        p.handle_frame()
    assert len(calls) == 3


def test_frame_hook_stops_after_repeated_errors_and_retries_later(mod, monkeypatch):
    calls = []
    clock = [1000.0]

    def boom():
        calls.append(1)
        raise RuntimeError("no engine")

    monkeypatch.setattr(mod.minqlx, "stream_status", boom, raising=False)
    monkeypatch.setattr(mod.time, "monotonic", lambda: clock[0])
    p = _plugin(mod, {"qlx_demoStreamResyncHold": "1"}, _stream_on=True)
    for _ in range(200):
        p.handle_frame()
    assert len(calls) == mod.MAX_ERRORS_IN_A_ROW and p._broken_at is not None
    # the cvars are read on the slow tick only, not on every failing frame
    assert len(p.cvar_reads) == (200 // mod.SLOW_POLL_FRAMES) * 4

    clock[0] += mod.BROKEN_RETRY_SEC + 1      # a minute later it tries again by itself
    p.handle_frame()
    assert len(calls) == mod.MAX_ERRORS_IN_A_ROW + 1


def test_an_error_while_reading_the_cvars_is_counted_too(mod, monkeypatch):
    monkeypatch.setattr(mod.minqlx, "stream_status",
                        lambda: SimpleNamespace(enabled=True, connected=True, resyncs=0, slots=()), raising=False)
    clock = [1000.0]
    monkeypatch.setattr(mod.time, "monotonic", lambda: clock[0])
    p = _plugin(mod, {"qlx_demoStreamResyncHold": "1"}, _enabled=True, _stream_on=True)

    def broken_get_cvar(name):
        raise RuntimeError("no cvar")

    p.get_cvar = broken_get_cvar
    for _ in range(mod.SLOW_POLL_FRAMES * (mod.MAX_ERRORS_IN_A_ROW - 1)):
        p.handle_frame()
    assert p._errors == mod.MAX_ERRORS_IN_A_ROW - 1 and p._broken_at is None
    for _ in range(mod.SLOW_POLL_FRAMES * 3):
        p.handle_frame()
    assert p._broken_at is not None and p._errors == mod.MAX_ERRORS_IN_A_ROW
    assert len(p.logger.lines) == mod.MAX_ERRORS_IN_A_ROW + 1   # one line per error and one for the switch-off


def test_toggling_the_cvar_off_and_on_rearms_a_broken_plugin(mod, monkeypatch):
    cvars = {"qlx_demoStreamResyncHold": "1"}
    monkeypatch.setattr(mod.time, "monotonic", lambda: 1000.0)
    p = _plugin(mod, cvars, _enabled=True, _broken_at=999.0, _errors=5)
    p._read_cvars()
    assert p._broken_at == 999.0             # still on: nothing changes
    cvars["qlx_demoStreamResyncHold"] = "0"
    p._read_cvars()
    cvars["qlx_demoStreamResyncHold"] = "1"
    p._read_cvars()
    assert p._broken_at is None and p._errors == 0


def test_an_error_does_not_lose_the_resync_counter(mod, monkeypatch):
    eng = FakeEngine(mod, {0: 2})
    fail = [False]

    def status():
        if fail[0]:
            raise RuntimeError("once")
        return eng.status()

    monkeypatch.setattr(mod.minqlx, "stream_status", status, raising=False)
    monkeypatch.setattr(mod.minqlx, "Client", eng.client_of, raising=False)
    p = _plugin(mod, {"qlx_demoStreamResyncHold": "1"}, hold=eng.hold, _enabled=True, _stream_on=True)
    eng.plugin_on = False
    for n in range(20):
        fail[0] = n == 10
        if n == 9:
            eng.resync_all = True    # the keyframe-like resync happens in the frame that fails next
        eng.frame += 0               # the fake engine's own step follows the hook
        p.handle_frame()
        eng.step()
    assert eng.hold.started == 1


def test_status_command_prints_one_line(mod):
    p = _plugin(mod, {"qlx_demoStreamResyncHold": "1", "qlx_demoStreamResyncHoldMaxFrames": "6",
                      "sv_demoStreamKeyframeSec": "10"})
    out = []
    p.cmd_resynchold(None, ["!resynchold"], SimpleNamespace(reply=out.append))
    assert len(out) == 1 and ": on, cap 6 per hold, 2 holds at once, keyframes every 10 s, holds 0" in out[0]


def test_log_command_sends_a_chat_channel_only_a_few_lines(mod):
    p = _plugin(mod, {"qlx_demoStreamResyncHold": "1"})
    for n in range(40):
        p.hold._note(0, "event {}".format(n))
    chat = []
    p.cmd_resynchold(None, ["!resynchold", "log"], SimpleNamespace(reply=chat.append))
    assert len(chat) == mod.CHAT_LOG_LINES and chat[-1].endswith("event 39")

    class ConsoleChannel:
        def __init__(self):
            self.lines = []

        def reply(self, line):
            self.lines.append(line)

    console = ConsoleChannel()
    p.cmd_resynchold(None, ["!resynchold", "log"], console)
    assert len(console.lines) == 40


def test_manifest_matches_the_plugin(mod):
    sidecar = json.loads((REPO_ROOT / "demo_stream_resync_hold.ql-plugin.json").read_text(encoding="utf-8"))
    cvars = {c["cvar"]: c for c in sidecar["cvars"]}
    assert set(cvars) == {"qlx_demoStreamResyncHold", "qlx_demoStreamResyncHoldMaxFrames",
                          "qlx_demoStreamResyncHoldPerFrame"}
    assert cvars["qlx_demoStreamResyncHold"]["default"] is False
    assert cvars["qlx_demoStreamResyncHoldMaxFrames"]["default"] == mod.DEFAULT_MAX_HOLD_FRAMES
    assert cvars["qlx_demoStreamResyncHoldMaxFrames"]["max"] == mod.MAX_HOLD_FRAMES_LIMIT
    assert cvars["qlx_demoStreamResyncHoldPerFrame"]["default"] == mod.DEFAULT_HOLDS_PER_FRAME
    assert cvars["qlx_demoStreamResyncHoldPerFrame"]["max"] == mod.HOLDS_PER_FRAME_LIMIT
    text = json.dumps(sidecar, ensure_ascii=False)
    assert chr(0x2014) not in text and chr(0x2013) not in text
    repo = json.loads((REPO_ROOT / "qlsm-repository.json").read_text(encoding="utf-8"))
    assert any(e.get("filename") == "demo_stream_resync_hold.py" for e in repo["plugins"])
