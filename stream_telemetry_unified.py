# stream_telemetry_unified.py — single-hook, shared-scheduler merge of
# stream_telemetry + pickup_telemetry + session_events.
#
# Production default (lean runtime pack + hub Statistics → Apply):
#   set qlx_plugins "...,stream_telemetry_unified"   (before motd)
#   set qlx_statsHubUnifiedEnabled "1"
#   set qlx_statsHubFeedPositions / qlx_statsHubFeedItems / qlx_statsHubFeedSession
#     as feed switches (still off by default until Apply)
#
# Legacy trio files remain in git for rollback but are NOT packed and are stripped
# from qlx_plugins on Apply. Never load trio alongside unified (double POST).
#
# Per-feed cvar rename (DevInbox #255, one-release compat window): the three feed
# switches used to reuse the legacy standalone plugins' own cvar names
# (qlx_streamTelemetryEnabled / qlx_pickupTelemetryEnabled / qlx_sessionEventsEnabled).
# That trio is gone from the runtime pack now, so the borrowed names just made the
# unified plugin's own settings look like they belonged to three different plugins.
# Renamed to one consistent namespace: qlx_statsHubFeedPositions / qlx_statsHubFeedItems
# / qlx_statsHubFeedSession. For one release, each new cvar falls back to reading its
# legacy name when left unset (see _feed_flag) so already-deployed instances that only
# have the old names set in server.cfg keep working unchanged until their next hub
# Apply. Once a new cvar is explicitly set (by hub Apply with the updated manifest, or
# by hand), it wins over the legacy fallback.
#
# This is a perf/scheduling refactor of the three plugins below. Wire payloads to
# /api/ingest/telemetry, /api/ingest/item-events, /api/ingest/session-events keep every
# field the originals send, plus ADDITIVE extensions (safe for older stats-hub, which
# ignores unknown fields/kinds):
#   - positions player rows: "ping"; weapons rows gain "d" (damage dealt, was discarded)
#   - session events: new kinds "spawn", "team_switch", "round_start", "round_end"
#     (registered only when the build has the matching dispatcher)
#
# WHY: all three register their own `frame` hook at PRI_LOWEST and do overlapping
# per-frame work on the game thread (positions/accuracy collection, item-event queue
# flush checks, chat/vote/pause polling) — three separate Python call overheads and,
# worse, stream_telemetry's own frame hook collected the full per-player row set twice
# per send-worthy frame (once to count ready players, once to build the payload).
# See docs/AUDIT-2026-07.md section 4 ("Перфоманс и протокол телеметрии") for the full
# writeup this file implements (proposals #1, #2, #7).
#
# CVARs — reused as-is from the three plugins (same names/semantics/defaults, see their
# header comments for the full list): qlx_statsHubInterval, qlx_statsHubIdleInterval,
# qlx_statsHubAccuracyInterval, qlx_statsHubMatchId, qlx_statsHubServerId,
# qlx_statsHubTournamentId, qlx_pickupTelemetryDebug. The three per-feed switches are
# this plugin's own namespace now: qlx_statsHubFeedPositions (positions/accuracy),
# qlx_statsHubFeedItems (item pickup/drop), qlx_statsHubFeedSession
# (session/chat/vote/pause) — see the rename note above for the legacy-name
# fallback.
#
# qlx_statsHubUrl/qlx_statsHubToken (host-scope change, DevInbox telemetry-relay
# host-scoping task): qlsm no longer writes these into any instance's server.cfg,
# and the Plugins tab no longer surfaces them as instance settings (see
# stream_telemetry_unified.ql-plugin.json). qlx_statsHubUrl defaults to the fixed
# local relay address (_LOCAL_RELAY_URL) - every instance on a host talks to the
# same loopback sidecar, which is what actually holds the real stats-hub URL/
# ingest token (qlsm per-host settings) and forwards upstream. qlx_statsHubToken
# is no longer required for _base_ready() - the relay never validated it as
# inbound auth (see relay.py do_POST) - but is still read/sent as-is if a cfg
# hand-edit sets it, for a non-default direct-to-stats-hub setup.
#
# New in this file (the one deliberately-new cvar, per operator's "keep it minimal" ask):
#   qlx_statsHubUnifiedEnabled "0" — master switch for this plugin only. Independent of
#   the three legacy plugins' own loop (they don't read it and this plugin's frame hook
#   is a no-op while it's off), so dropping this file into qlx_plugins is inert until you
#   flip it.
#
# IMPORTANT — do not double-post: while the legacy-name fallback is in effect,
# qlx_streamTelemetryEnabled/qlx_pickupTelemetryEnabled/qlx_sessionEventsEnabled are
# still the SAME cvars the three standalone plugins read. If you load
# stream_telemetry_unified on a box that also has stream_telemetry/pickup_telemetry/
# session_events in qlx_plugins with those legacy cvars on, you get every feed posted
# twice. The supported opt-in path is: on one test instance, replace the three plugin
# names with stream_telemetry_unified in that instance's qlx_plugins line, then set
# qlx_statsHubUnifiedEnabled "1". Do not touch the default qlx_plugins line in
# baseq3/server1.cfg (which keeps the three separate plugins).
#
# Design (audit proposals #1/#2/#7):
#   1. Double-collect fix: a cheap per-frame pass (`_count_ready_players`) only calls
#      `player.position` + the same in-world checks stream_telemetry already used to
#      gate readiness — it does NOT touch state.*/powerups/cvars/ammo/velocity/weapon
#      indices. The expensive full per-player row build (`_collect_players`, same fields
#      as stream_telemetry) now runs exactly once, and only right before a send actually
#      fires (interval elapsed, no post in flight).
#   2. FOV/userinfo cache: `_cached_fov` keys by steam_id, refreshed on the `userinfo`
#      hook (cg_fov change) and on connect/disconnect, with a 30s TTL as a belt-and-
#      suspenders fallback in case the `userinfo` hook isn't available on a given
#      minqlxtended build (checked defensively via EVENT_DISPATCHERS, same pattern
#      pickup_telemetry already uses for `item_event`).
#   7. One `frame` hook drives all three sub-schedules off one `_frame_tick` counter:
#      positions/accuracy at the existing stride (2), item-event queue flush every frame
#      (cheap len() check, same as pickup_telemetry today), and — the actual fix for
#      audit risk #5 — session_events' pause/game_time poll, which today runs completely
#      unthrottled, now runs on a stride (every 4th tick) like the session batch flush
#      already did.
#
# Preserved from stream_telemetry.py verbatim (see docs/STABILITY-PLAN.md /
# docs/minqlxtended-qlhub-patches.md for the incident history behind these):
#   - HTTP POST + json.dumps offloaded to @minqlx.thread
#   - keep-alive HTTP connection reuse for the positions/telemetry feed
#   - `_post_in_flight` bool guard + failsafe timeout per feed (no shared lock)
#   - circuit breaker (10 consecutive failures -> disable that feed's cvar), extended
#     here to all three feeds instead of just positions, off-thread via
#     `minqlx.next_frame` when available (audit proposal #9) instead of writing the
#     cvar from the POST worker thread
#   - decoupled accuracy-cadence from position-cadence (one payload, not two POSTs)
#   - CS_ACTIVE guard before touching client->ps / viewangles / weapon_stats
#
# NOT yet validated on a live VPS/QLDS process — see
# docs/minqlxtended-qlhub-patches.md ("stream_telemetry_unified") for the bench/
# validation procedure before trusting this on a real match.

import http.client
import json
import re
import time
from urllib.parse import urlparse

try:
    import minqlxtended as minqlx
except ImportError:
    import minqlx

# Raised by stock minqlxtended natives/views when the vm is not ready.
_ENGINE_ERR = getattr(minqlx, "EngineStateError", RuntimeError)

try:
    import stats_hub_pause
except ImportError:
    try:
        from . import stats_hub_pause
    except ImportError:
        stats_hub_pause = None

try:
    from telemetry_unified_sched import (
        FeedState,
        FovCache,
        derive_ingest_url,
        effective_interval,
        on_stride,
    )
except ImportError:
    from .telemetry_unified_sched import (
        FeedState,
        FovCache,
        derive_ingest_url,
        effective_interval,
        on_stride,
    )


class stream_telemetry_unified(minqlx.Plugin):
    _COLOR_RE = re.compile(r"\^[0-9a-zA-Z]")
    # Fixed address of the per-host ql-telemetry-relay sidecar (loopback
    # only - see qlsm's ansible_telemetry_relay.RELAY_LOCAL_URL). A program
    # constant, not per-instance config: every instance on a host talks to
    # the same local relay, which is what actually holds the real
    # stats-hub URL/ingest token (per-host settings in qlsm, not cvars
    # here) and forwards upstream.
    _LOCAL_RELAY_URL = "http://127.0.0.1:8190/api/ingest/telemetry"
    _ENABLE_GRACE_SEC = 2.0
    _CIRCUIT_FAIL_THRESHOLD = 10
    _HEALTH_LOG_SEC = 60.0
    _FOV_CACHE_TTL_SEC = 30.0

    # Shared frame scheduler strides (audit proposal #7).
    _FRAME_STRIDE_POSITIONS = 2   # matches stream_telemetry._FRAME_STRIDE today
    _FRAME_STRIDE_SESSION = 4     # matches session_events' existing flush stride;
                                   # now ALSO gates the pause/game_time poll (was unstrided)
    _FRAME_PHASE_SESSION = 1      # positions fire on even ticks; session work on
                                   # tick % 4 == 1 so the two never share a frame

    # Stuck-post thresholds must stay above the worst-case time a legitimate worker
    # can still be running, or the frame driver "recovers" a slot that's still in
    # use and a second worker starts on the same queue head (review 2026-07-17,
    # P1-1). Positions: connect+send+read timeout is 2s each way -> ~4s worst case.
    # Items: _ITEMS_POST_MAX_RETRIES retries * _ITEMS_POST_TIMEOUT_SEC + backoff ->
    # ~15.5s worst case. Session: connect+read timeout 5s each -> ~10s worst case.
    _POSITIONS_POST_STUCK_SEC = 7.0
    _ITEMS_POST_STUCK_SEC = 20.0
    _SESSION_POST_STUCK_SEC = 12.0

    _ITEMS_MAX_QUEUE = 1024
    _ITEMS_QUEUE_WARN = 64
    _ITEMS_BATCH_SIZE = 12
    _ITEMS_POST_TIMEOUT_SEC = 5.0
    _ITEMS_POST_MAX_RETRIES = 3
    _ITEMS_POST_RETRY_BACKOFF_SEC = (0.05, 0.15, 0.35)

    _SESSION_MAX_QUEUE = 512
    _SESSION_QUEUE_WARN = 64
    _SESSION_BATCH_SIZE = 8
    _SESSION_POST_TIMEOUT_SEC = 5.0

    _BASE_READY_CACHE_TTL_SEC = 0.25

    _GI_TYPE_LABELS = {
        1: "weapon",
        2: "ammo",
        3: "armor",
        4: "health",
        5: "powerup",
        6: "holdable",
        7: "persistant_powerup",
        8: "team",
    }

    # weapon_t index -> short label (matches stats-hub zmq_weapon_stats aliases).
    _WEAPON_BY_INDEX = {
        1: "GA", 2: "MG", 3: "SG", 4: "GL", 5: "RL", 6: "LG",
        7: "RG", 8: "PG", 9: "BFG", 11: "NG", 12: "PL", 13: "CG", 14: "HMG",
    }
    _RESTORE_AMMO_KEYS = ("rl", "lg", "rg", "pg", "gl", "sg", "mg", "cg")
    _LOADOUT_WEAPON_ORDER = (
        "g", "mg", "sg", "gl", "rl", "lg", "rg", "pg", "bfg", "gh", "ng", "pl", "cg", "hmg", "hands",
    )

    def __init__(self):
        # --- shared scheduler state ---
        self._frame_tick = 0
        self._handle_frame_errors = 0
        self._last_health_log = 0.0
        self._logged_active = False
        # Self-telemetry: time spent in _handle_frame_inner between health logs,
        # to prove (or disprove) the "no sv_fps drops" requirement on live data.
        self._frame_time_sum = 0.0
        self._frame_time_max = 0.0
        self._frame_time_samples = 0
        # Last-checked (tripped, tripped, tripped, fail, fail, fail, errors) tuple
        # for positions/items/session, used by _maybe_log_health to log only on
        # a circuit transition or a new failure/error since the last check —
        # not unconditionally every _HEALTH_LOG_SEC.
        self._health_prev_state = (False, False, False, 0, 0, 0, 0)

        # --- fov/userinfo cache (audit proposal #2) ---
        self._fov_cache = FovCache(ttl_sec=self._FOV_CACHE_TTL_SEC)
        self._userinfo_hook_available = False

        # --- _base_ready() result cache (review 2026-07-17, P2-3): the three
        # _xxx_enabled() checks plus chat archiving all call _base_ready(), which
        # reads 3 cvars — cache briefly instead of re-parsing every call. ---
        self._base_ready_cache = None

        # --- per-feed post/circuit-breaker bookkeeping (review 2026-07-17, P3-1):
        # was_enabled edge, in-flight/stuck-post + generation counter (P1-1), and
        # consecutive-failure circuit breaker — one FeedState per feed instead of
        # three copies of the same fields plus a separate self._circuit dict. ---
        # cvar= is the circuit breaker's auto-disable target (_disable_cvar_safely):
        # always the new namespaced cvar, never the legacy one — a trip must pin the
        # feed off going forward even while it's currently running on the legacy-name
        # fallback (see _feed_flag), so it has to write the cvar that wins the
        # precedence check.
        self._positions_state = FeedState(
            "positions", self._POSITIONS_POST_STUCK_SEC, self._CIRCUIT_FAIL_THRESHOLD,
            cvar="qlx_statsHubFeedPositions",
        )
        self._items_state = FeedState(
            "items", self._ITEMS_POST_STUCK_SEC, self._CIRCUIT_FAIL_THRESHOLD,
            cvar="qlx_statsHubFeedItems",
        )
        self._session_state = FeedState(
            "session", self._SESSION_POST_STUCK_SEC, self._CIRCUIT_FAIL_THRESHOLD,
            cvar="qlx_statsHubFeedSession",
        )

        # --- positions/accuracy telemetry state (stream_telemetry equivalent) ---
        self._positions_armed_at = 0.0
        self._positions_last_send = 0.0
        self._positions_last_accuracy_send = 0.0
        self._positions_http_conn = None
        self._positions_http_conn_key = None
        self._positions_yaw_missing_warned = False
        self._positions_skip_log_tick = 0

        # --- item pickup/drop telemetry state (pickup_telemetry equivalent) ---
        self._items_queue = []
        self._items_queue_warned = False
        self._items_queue_full_drops = 0
        # Native item_event comes from the patched runtime; on a stock
        # minqlxtended (>= v1.1.0) the same payload is synthesized by pairing
        # the gated item_touch with item_pickup (same C call stack, touch
        # always dispatches first), so either shape feeds the pickup feed.
        self._item_native_event = self._has_dispatcher("item_event")
        self._item_events_available = self._item_native_event or (
            self._has_dispatcher("item_touch") and self._has_dispatcher("item_pickup")
        )
        self._last_item_touch = {}

        # --- session/chat/vote/pause events state (session_events equivalent) ---
        self._session_queue = []
        self._session_queue_warned = False
        self._session_match_running = False
        self._last_game_time_ms = None
        self._match_start_wall = None
        self._pause_accumulated_ms = 0
        self._pause_lifecycle_open = False
        self._pause_wall_at = None
        self._pause_reason = None
        self._last_sv_paused = None

        # --- cvars (shared with the three standalone plugins, plus the one new switch) ---
        # The three per-feed cvars are deliberately NOT registered here: leaving them
        # unset (rather than set_cvar_once-ing a default) is what lets _feed_flag tell
        # "operator/hub never touched the new cvar" apart from "operator explicitly
        # disabled it", so the legacy-name fallback only applies in the former case.
        # The legacy names keep their set_cvar_once default below so they always read
        # as a real bool even on a box that never had a standalone plugin loaded.
        self.set_cvar_once("qlx_statsHubUnifiedEnabled", "0")
        self.set_cvar_once("qlx_streamTelemetryEnabled", "0")
        self.set_cvar_once("qlx_pickupTelemetryEnabled", "0")
        self.set_cvar_once("qlx_pickupTelemetryDebug", "0")
        self.set_cvar_once("qlx_sessionEventsEnabled", "0")
        self.set_cvar_once("qlx_statsHubUrl", self._LOCAL_RELAY_URL)
        self.set_cvar_once("qlx_statsHubToken", "")
        self.set_cvar_once("qlx_statsHubInterval", "0.1")
        self.set_cvar_once("qlx_statsHubIdleInterval", "1.0")
        self.set_cvar_once("qlx_statsHubAccuracyInterval", "2")
        self.set_cvar_once("qlx_statsHubMatchId", "")
        self.set_cvar_once("qlx_statsHubServerId", "0")
        self.set_cvar_once("qlx_statsHubTournamentId", "0")

        if not self._item_events_available:
            self.logger.warning(
                "stream_telemetry_unified: no item_event dispatcher and no "
                "item_touch/item_pickup pair — minqlxtended too old? "
                "(pickup feed will stay empty)"
            )

        # --- hooks: exactly one `frame` hook drives all three sub-schedules ---
        self.add_hook("frame", self.handle_frame, priority=minqlx.Priority.LOWEST)
        # Two client_command hooks on purpose: the pause latch must see every command
        # first (PRI_HIGHEST, as in stream_telemetry), while chat archiving must run
        # after blockers like quiet.py (PRI_LOWEST, as in session_events) so blocked
        # messages are not recorded.
        self.add_hook("client_command", self.on_client_command, priority=minqlx.Priority.HIGHEST)
        self.add_hook("client_command", self.on_client_command_chat, priority=minqlx.Priority.LOWEST)
        if self._item_native_event:
            self.add_hook("item_event", self.on_item_event, priority=minqlx.Priority.LOWEST)
        elif self._item_events_available:
            self.add_hook("item_touch", self.on_item_touch_stock, priority=minqlx.Priority.LOWEST)
            self.add_hook("item_pickup", self.on_item_pickup_stock, priority=minqlx.Priority.LOWEST)
        self.add_hook("player_connect", self.on_player_connect, priority=minqlx.Priority.LOWEST)
        self.add_hook("player_disconnect", self.on_player_disconnect, priority=minqlx.Priority.LOWEST)
        self.add_hook("vote_started", self.on_vote_started, priority=minqlx.Priority.LOWEST)
        self.add_hook("vote", self.on_vote, priority=minqlx.Priority.LOWEST)
        self.add_hook("vote_ended", self.on_vote_ended, priority=minqlx.Priority.LOWEST)
        self.add_hook("death", self.on_death, priority=minqlx.Priority.LOWEST)
        # Optional dispatchers (build-dependent) — same defensive pattern as
        # item_event/userinfo; the session feed just gets fewer kinds without them.
        if self._has_dispatcher("player_spawn"):
            self.add_hook("player_spawn", self.on_player_spawn, priority=minqlx.Priority.LOWEST)
        if self._has_dispatcher("team_switch"):
            self.add_hook("team_switch", self.on_team_switch, priority=minqlx.Priority.LOWEST)
        if self._has_dispatcher("round_start"):
            self.add_hook("round_start", self.on_round_start, priority=minqlx.Priority.LOWEST)
        if self._has_dispatcher("round_end"):
            self.add_hook("round_end", self.on_round_end, priority=minqlx.Priority.LOWEST)
        self.add_hook("game_countdown", self.on_game_countdown, priority=minqlx.Priority.LOWEST)
        self.add_hook("game_start", self.on_game_start, priority=minqlx.Priority.LOWEST)
        self.add_hook("game_end", self.on_game_end, priority=minqlx.Priority.LOWEST)
        self.add_hook("map", self._on_map, priority=minqlx.Priority.LOWEST)
        if self._has_dispatcher("userinfo"):
            try:
                self.add_hook("userinfo", self.on_userinfo, priority=minqlx.Priority.LOWEST)
                self._userinfo_hook_available = True
            except Exception as exc:  # defensive: never let cache-invalidation wiring break load
                self.logger.warning(
                    "stream_telemetry_unified: userinfo hook registration failed (%s) — "
                    "fov cache relies on %ss TTL fallback only",
                    exc,
                    self._FOV_CACHE_TTL_SEC,
                )
        if not self._userinfo_hook_available:
            self.logger.warning(
                "stream_telemetry_unified: userinfo hook unavailable — fov cache relies "
                "on %ss TTL fallback only (still avoids per-frame cvars parsing)",
                self._FOV_CACHE_TTL_SEC,
            )

    # ======================================================================
    # Shared helpers (identical across all three source plugins — kept once)
    # ======================================================================

    @staticmethod
    def _has_dispatcher(name):
        dispatchers = getattr(minqlx, "EVENT_DISPATCHERS", None)
        if dispatchers is None:
            return False
        try:
            dispatchers[name]
        except (KeyError, TypeError):
            return False
        return True

    @staticmethod
    def _is_bot(player):
        steam = str(getattr(player, "steam_id", "")).strip()
        return not steam or steam[0] == "9"

    @staticmethod
    def _steam_str(player):
        steam = getattr(player, "steam_id", None)
        if steam is None or steam == "":
            return ""
        if isinstance(steam, float):
            return "{:.0f}".format(steam)
        text = str(steam).strip()
        if "." in text:
            text = text.split(".", 1)[0]
        return text

    @classmethod
    def _display_name(cls, player):
        name = getattr(player, "clean_name", None) or getattr(player, "name", None) or ""
        name = cls._COLOR_RE.sub("", str(name)).strip()
        return name[:64] or None

    def _map_name(self):
        for attr in ("map", "map_name"):
            val = getattr(self.game, attr, None)
            if val:
                return str(val)
        return getattr(self.game, "map_title", None) or None

    def _gametype(self):
        gt = getattr(self.game, "type_short", None) or getattr(self.game, "type", None)
        return str(gt) if gt else None

    def _server_id(self):
        raw = (self.get_cvar("qlx_statsHubServerId") or "0").strip()
        try:
            sid = int(raw)
        except ValueError:
            return None
        return sid if sid > 0 else None

    def _tournament_id(self):
        raw = (self.get_cvar("qlx_statsHubTournamentId") or "0").strip()
        try:
            tid = int(raw)
        except ValueError:
            return None
        return tid if tid > 0 else None

    def _match_id(self):
        fixed = (self.get_cvar("qlx_statsHubMatchId") or "").strip()
        if fixed:
            return fixed
        server_id = self._server_id()
        if server_id is not None:
            return "server-{}".format(server_id)
        try:
            port = int(self.get_cvar("net_port") or "27960")
        except ValueError:
            port = 27960
        if port >= 37960:
            return "lobby-{}".format(port - 37960)
        return "server-{}".format(port - 27960)

    def _base_ready(self):
        """Common connectivity prerequisites shared by all three sub-features.

        Cached briefly (P2-3): called from _positions_enabled/_items_enabled/
        _session_enabled/_feature_flags — up to several times per frame plus once
        per chat command — and it's 3 cvar reads each time. A stale cache costs at
        most _BASE_READY_CACHE_TTL_SEC of delay reacting to a hub Apply, which is
        already covered by the existing _ENABLE_GRACE_SEC grace period.
        """
        now = time.time()
        cached = self._base_ready_cache
        if cached is not None and now - cached[1] < self._BASE_READY_CACHE_TTL_SEC:
            return cached[0]
        if self.get_cvar("qlx_statsHubUnifiedEnabled", bool) is False:
            result = False
        elif not (self.get_cvar("qlx_statsHubUrl") or "").strip():
            result = False
        else:
            result = True
        self._base_ready_cache = (result, now)
        return result

    def _feed_flag(self, new_cvar, legacy_cvar):
        """Per-feed on/off, new namespaced cvar wins when explicitly set; falls back
        to the legacy standalone-plugin cvar name when the new one is untouched
        (DevInbox #255 — see the rename note in the file header). `new_cvar` is
        deliberately never registered via set_cvar_once, so an unset cvar reads back
        as None here rather than a real default, which is what makes "never touched"
        distinguishable from "explicitly disabled"."""
        raw = self.get_cvar(new_cvar)
        if raw is not None and str(raw).strip() != "":
            return self.get_cvar(new_cvar, bool) is not False
        return self.get_cvar(legacy_cvar, bool) is not False

    def _positions_enabled(self):
        if not self._base_ready():
            return False
        if not self._feed_flag("qlx_statsHubFeedPositions", "qlx_streamTelemetryEnabled"):
            return False
        if self._server_id() is None:
            return False
        return True

    def _items_enabled(self):
        if not self._base_ready():
            return False
        if not self._item_events_available:
            return False
        if not self._feed_flag("qlx_statsHubFeedItems", "qlx_pickupTelemetryEnabled"):
            return False
        return True

    def _session_enabled(self):
        if not self._base_ready():
            return False
        if not self._feed_flag("qlx_statsHubFeedSession", "qlx_sessionEventsEnabled"):
            return False
        return True

    def _any_enabled(self):
        return self._positions_enabled() or self._items_enabled() or self._session_enabled()

    def _feature_flags(self):
        """One-pass (positions, items, session) flags for the frame path — one
        `_base_ready()` cvar read instead of one per feed, and the drive methods
        get the flag passed in instead of re-deriving it (audit #7 follow-up)."""
        if not self._base_ready():
            return False, False, False
        positions = (
            self._feed_flag("qlx_statsHubFeedPositions", "qlx_streamTelemetryEnabled")
            and self._server_id() is not None
        )
        items = (
            self._item_events_available
            and self._feed_flag("qlx_statsHubFeedItems", "qlx_pickupTelemetryEnabled")
        )
        session = self._feed_flag("qlx_statsHubFeedSession", "qlx_sessionEventsEnabled")
        return positions, items, session

    def _on_map(self, mapname, factory):
        if self._logged_active or not self._any_enabled():
            return minqlx.Return.NONE
        self._logged_active = True
        self.logger.info(
            "stream_telemetry_unified: active match_id=%s positions=%s items=%s session=%s url=%s",
            self._match_id(),
            self._positions_enabled(),
            self._items_enabled(),
            self._session_enabled(),
            (self.get_cvar("qlx_statsHubUrl") or "").strip(),
        )
        return minqlx.Return.NONE

    def _disable_cvar_safely(self, cvar_name):
        next_frame = getattr(minqlx, "next_frame", None)
        if callable(next_frame):
            @next_frame
            def _apply():
                try:
                    minqlx.set_cvar(cvar_name, "0")
                except (AttributeError, TypeError, ValueError) as exc:
                    self.logger.error(
                        "stream_telemetry_unified: failed to disable cvar %s: %s", cvar_name, exc
                    )
            _apply()
            return
        try:
            minqlx.set_cvar(cvar_name, "0")
        except (AttributeError, TypeError, ValueError) as exc:
            self.logger.error("stream_telemetry_unified: failed to disable cvar %s: %s", cvar_name, exc)

    def _reset_circuit(self, state):
        """Re-arm a feed's breaker on its disabled->enabled edge, so a feed the
        operator manually re-enables after a trip can trip (and log) again."""
        if not state.reset_circuit():
            return
        self.logger.info("stream_telemetry_unified: circuit breaker (%s) reset on enable", state.name)

    def _record_post_result(self, state, ok):
        if not state.record_result(ok):
            return
        self.logger.error(
            "stream_telemetry_unified: circuit breaker (%s) after %s consecutive failures — "
            "disabling %s",
            state.name,
            state.consecutive_fail,
            state.cvar,
        )
        self._disable_cvar_safely(state.cvar)

    def on_client_command(self, player, cmd):
        # Pause-latch tracking is unconditional (matches both originals) — cheap and
        # needed regardless of which sub-features are currently enabled.
        if stats_hub_pause is not None:
            stats_hub_pause.note_client_command(cmd, player=player, plugin=self)
        return minqlx.Return.NONE

    def on_client_command_chat(self, player, cmd):
        if self._session_enabled() and cmd:
            lower = cmd.lower()
            if lower.startswith("say "):
                self._enqueue_session("say", player, text=cmd[4:].strip())
            elif lower.startswith("say_team "):
                self._enqueue_session("say_team", player, text=cmd[9:].strip())
            elif lower.startswith("tell "):
                parts = cmd.split(None, 2)
                if len(parts) >= 3:
                    self._enqueue_session(
                        "tell", player, text=parts[2].strip(), meta={"target": parts[1]}
                    )
        return minqlx.Return.NONE

    def handle_frame(self):
        try:
            positions_en, items_en, session_en = self._feature_flags()
            if not (positions_en or items_en or session_en):
                # Still run the edge syncs so turning the master switch (or every
                # sub-toggle) off is logged, counters reset, and re-enabling later
                # is seen as a fresh disabled->enabled edge — matches stream_
                # telemetry, whose handle_frame kept running one pass while
                # _was_enabled was set. Without the items/session half of this
                # (P1-4), _items_was_enabled/_session_was_enabled stayed True
                # across an off/on cycle, so _drive_item_events/_drive_session_
                # events never saw the edge and _reset_circuit() never fired —
                # a tripped breaker from before the toggle stayed tripped after.
                if self._positions_state.was_enabled:
                    self._sync_positions_enable_state(False)
                if self._items_state.was_enabled:
                    self._items_state.sync_enabled(False)
                if self._session_state.was_enabled:
                    self._session_state.sync_enabled(False)
                return minqlx.Return.NONE
            started = time.perf_counter()
            try:
                return self._handle_frame_inner(positions_en, items_en, session_en)
            finally:
                elapsed = time.perf_counter() - started
                self._frame_time_sum += elapsed
                self._frame_time_samples += 1
                if elapsed > self._frame_time_max:
                    self._frame_time_max = elapsed
        except Exception as exc:
            self._handle_frame_errors += 1
            if self._handle_frame_errors <= 3 or self._handle_frame_errors % 100 == 0:
                self.logger.exception(
                    "stream_telemetry_unified: handle_frame error (#%s): %s",
                    self._handle_frame_errors,
                    exc,
                )
            return minqlx.Return.NONE

    def _handle_frame_inner(self, positions_en, items_en, session_en):
        self._frame_tick += 1
        self._maybe_log_health()
        if on_stride(self._frame_tick, self._FRAME_STRIDE_POSITIONS):
            self._drive_positions(positions_en)
        self._drive_item_events(items_en)
        self._drive_session_events(session_en)
        return minqlx.Return.NONE

    def _maybe_log_health(self):
        now = time.time()
        if now - self._last_health_log < self._HEALTH_LOG_SEC:
            return
        self._last_health_log = now

        positions_tripped = self._positions_state.tripped
        items_tripped = self._items_state.tripped
        session_tripped = self._session_state.tripped
        positions_fail = self._positions_state.posts_fail
        items_fail = self._items_state.posts_fail
        session_fail = self._session_state.posts_fail
        errors = self._handle_frame_errors

        (prev_pt, prev_it, prev_st, prev_pf, prev_if, prev_sf, prev_err) = self._health_prev_state
        self._health_prev_state = (
            positions_tripped, items_tripped, session_tripped,
            positions_fail, items_fail, session_fail, errors,
        )

        # Only log on an actual change since the last check — a circuit tripping
        # (or recovering), a new failure, or a new handle_frame error — never
        # unconditionally, so a healthy server stays silent (was: one line/min
        # forever regardless of state, pure log spam).
        should_log = (
            positions_tripped != prev_pt
            or items_tripped != prev_it
            or session_tripped != prev_st
            or positions_fail > prev_pf
            or items_fail > prev_if
            or session_fail > prev_sf
            or errors > prev_err
        )

        if should_log:
            frame_avg_ms = 0.0
            if self._frame_time_samples:
                frame_avg_ms = 1000.0 * self._frame_time_sum / self._frame_time_samples
            frame_max_ms = 1000.0 * self._frame_time_max
            self.logger.info(
                "stream_telemetry_unified: health positions(ok=%s fail=%s circuit=%s) "
                "items(ok=%s fail=%s queue=%s circuit=%s) "
                "session(ok=%s fail=%s queue=%s circuit=%s) errors=%s "
                "frame(avg=%.3fms max=%.3fms n=%s)",
                self._positions_state.posts_ok,
                positions_fail,
                "tripped" if positions_tripped else "ok",
                self._items_state.posts_ok,
                items_fail,
                len(self._items_queue),
                "tripped" if items_tripped else "ok",
                self._session_state.posts_ok,
                session_fail,
                len(self._session_queue),
                "tripped" if session_tripped else "ok",
                errors,
                frame_avg_ms,
                frame_max_ms,
                self._frame_time_samples,
            )

        self._frame_time_sum = 0.0
        self._frame_time_max = 0.0
        self._frame_time_samples = 0

    # ======================================================================
    # Positions / accuracy telemetry (stream_telemetry.py equivalent)
    # ======================================================================

    def _interval(self):
        try:
            return max(0.1, float(self.get_cvar("qlx_statsHubInterval") or "0.1"))
        except ValueError:
            return 0.1

    def _idle_interval(self):
        try:
            return max(0.5, float(self.get_cvar("qlx_statsHubIdleInterval") or "1.0"))
        except ValueError:
            return 1.0

    def _accuracy_interval(self):
        try:
            return max(0.5, float(self.get_cvar("qlx_statsHubAccuracyInterval") or "2"))
        except ValueError:
            return 2.0

    @staticmethod
    def _player_in_world(player):
        """Player on map with coords — duel/warmup may not report CS_ACTIVE yet."""
        try:
            if stream_telemetry_unified._is_bot(player):
                return False
            steam = stream_telemetry_unified._steam_str(player)
            if not steam:
                return False
            team = (getattr(player, "team", None) or "").strip().lower()
            if team in ("spectator", "spec"):
                return False
            pos = player.position
            if not pos or len(pos) < 3:
                return False
            return True
        except (AttributeError, TypeError, ValueError, minqlx.EngineStateError):
            return False

    @staticmethod
    def _player_cs_active(player):
        # connection_state is a ConnectionState enum (string-comparable), not an
        # int - minqlx.CS_ACTIVE doesn't exist (CS_* are config-string indices,
        # an unrelated constant family). "active" is the documented check
        # (Player.connection_state's own docstring).
        conn = getattr(player, "connection_state", None)
        if conn is None:
            return True
        try:
            return conn == "active"
        except (TypeError, ValueError, AttributeError):
            return True

    def _count_ready_players(self):
        """Cheap readiness pass (audit proposal #1): only what `_player_in_world`
        already needs (position() + team/steam checks) — no state.*/powerups()/cvars/
        ammo/velocity/weapon access. Used purely to size the send interval; the full
        row collect happens exactly once, only when a send is actually due."""
        count = 0
        for player in self.players():
            if self._player_in_world(player):
                count += 1
        return count

    def _view_angles(self, player):
        # Pre-port this read a custom CS_ACTIVE-guarded PlayerState.viewangles
        # field (patch-minqlxtended-viewangles.py). v1.0.0 exposes the same
        # data natively as GameClient.ps.viewangles (PlayerStateView, a live
        # ps.viewangles mirror) - no patch needed, just a different access
        # path. Caller already CS_ACTIVE-guards this call (see
        # _player_cs_active in _collect_players), matching the old patch's
        # own guard.
        try:
            client = minqlx.Entity(int(player.id)).client
            if client is not None:
                viewangles = client.ps.viewangles
                if viewangles is not None and len(viewangles) >= 2:
                    return float(viewangles[0]), float(viewangles[1])
        # EngineStateError (v1.0.0, RuntimeError subclass) is raised by qlx_gclient()/
        # qlx_entity() whenever the game VM/level pointer is transiently unavailable,
        # e.g. during a mid-match map hot-reload. Native attribute reads must tolerate it.
        except (AttributeError, TypeError, ValueError, IndexError, minqlx.EngineStateError):
            pass
        for attr in ("angles", "view_angles"):
            val = getattr(player, attr, None)
            if val is None:
                continue
            try:
                if len(val) >= 2:
                    return float(val[0]), float(val[1])
            except (TypeError, ValueError):
                pass
        return None, None

    def _weapon_stats(self, player):
        """Per-weapon [{w,h,s,d}] from native GameClient.expanded_stats (shots>0 only).

        Pre-port this read a custom CS_ACTIVE-guarded PlayerState.weapon_stats
        16-tuple (patch-minqlxtended-viewangles.py, same patch as
        _view_angles's field). v1.0.0 exposes the same counters natively as
        three per-weapon Weapons tuples (shots_fired/shots_hit/damage_dealt)
        on GameClient.expanded_stats - no patch needed. The old patch applied
        its own CS_ACTIVE guard C-side before either field was readable;
        replicated here via _player_cs_active since expanded_stats has no
        such guard built in.

        `d` (damage dealt) is included when present so stats-hub can build
        damage graphs with zero extra engine reads."""
        if not self._player_cs_active(player):
            return []
        try:
            client = minqlx.Entity(int(player.id)).client
            if client is None:
                return []
            stats = client.expanded_stats
            shots_fired = stats.shots_fired
            shots_hit = stats.shots_hit
            damage_dealt = stats.damage_dealt
        # See _view_angles: native reads can raise EngineStateError transiently.
        except (AttributeError, TypeError, ValueError, minqlx.EngineStateError):
            return []
        out = []
        for idx, name in self._WEAPON_BY_INDEX.items():
            # _WEAPON_BY_INDEX keys are weapon_t values (1..14, skipping the
            # grappling hook); _LOADOUT_WEAPON_ORDER is the same weapon_t
            # order (1..15) as a 0-based tuple of the native Weapons named
            # fields, so index idx-1 names the field for weapon_t idx.
            field = self._LOADOUT_WEAPON_ORDER[idx - 1]
            try:
                shots = int(getattr(shots_fired, field))
                hits = int(getattr(shots_hit, field))
            except (AttributeError, TypeError, ValueError):
                continue
            if shots <= 0:
                continue
            entry = {"w": name, "s": shots, "h": hits}
            try:
                damage = int(getattr(damage_dealt, field))
            except (AttributeError, TypeError, ValueError):
                damage = 0
            if damage > 0:
                entry["d"] = damage
            out.append(entry)
        return out

    @classmethod
    def _loadout_mask_from_weapons(cls, weapons):
        """Match restore.codec / loadout_to_mask (bit 0 unused)."""
        if weapons is None:
            return None
        mask = 0
        for idx, key in enumerate(cls._LOADOUT_WEAPON_ORDER):
            try:
                if bool(weapons[idx]):
                    mask |= 1 << (idx + 1)
            except (TypeError, IndexError, ValueError):
                continue
        return int(mask)

    def _player_weapon_idx(self, player):
        try:
            w = player.weapon
            if w is None:
                return None
            return int(w)
        except (AttributeError, TypeError, ValueError, minqlx.EngineStateError):
            return None

    def _player_loadout_mask(self, player):
        try:
            state = getattr(player, "state", None)
            weapons = getattr(state, "weapons", None) if state else None
            return self._loadout_mask_from_weapons(weapons)
        except (AttributeError, TypeError, ValueError, minqlx.EngineStateError):
            return None

    def _player_ammo_dict(self, player):
        try:
            state = getattr(player, "state", None)
            ammo = getattr(state, "ammo", None) if state else None
            if ammo is None:
                return None
            out = {}
            for key in self._RESTORE_AMMO_KEYS:
                try:
                    val = getattr(ammo, key, None)
                    if val is not None:
                        out[key] = int(val)
                except (TypeError, ValueError, AttributeError):
                    continue
            return out or None
        except (AttributeError, TypeError, ValueError, minqlx.EngineStateError):
            return None

    @staticmethod
    def _player_velocity(player):
        try:
            state = getattr(player, "state", None)
            vel = getattr(state, "velocity", None) if state else None
            if vel is None or len(vel) < 3:
                return None, None, None
            return float(vel[0]), float(vel[1]), float(vel[2])
        except (AttributeError, TypeError, ValueError, minqlx.EngineStateError):
            return None, None, None

    @staticmethod
    def _active_powerups(player):
        names = []
        try:
            pu = player.powerups
        except (AttributeError, TypeError, ValueError, minqlx.EngineStateError):
            return names
        mapping = (
            ("quad", "quad"),
            ("regeneration", "regen"),
            ("battlesuit", "battle"),
            ("haste", "haste"),
            ("invisibility", "invis"),
            ("invulnerability", "invuln"),
        )
        for attr, label in mapping:
            try:
                remaining = int(getattr(pu, attr, 0) or 0)
            except (TypeError, ValueError):
                remaining = 0
            if remaining > 0:
                names.append(label)
        return names

    @staticmethod
    def _parse_fov(player):
        try:
            cvars = getattr(player, "cvars", None) or {}
            raw = cvars.get("cg_fov") if isinstance(cvars, dict) else None
            if raw is not None:
                val = float(raw)
                if 60 <= val <= 140:
                    return val
        except (AttributeError, TypeError, ValueError):
            pass
        return None

    def _cached_fov(self, player, steam):
        """FOV cache keyed by steam_id (audit proposal #2). Primary invalidation is
        the `userinfo` hook (cg_fov change) + connect/disconnect; TTL below is only a
        safety net for builds where the userinfo hook isn't wired up."""
        now = time.time()
        fov, hit = self._fov_cache.get(steam, now)
        if hit:
            return fov
        fov = self._parse_fov(player)
        self._fov_cache.put(steam, fov, now)
        return fov

    def _invalidate_fov_cache(self, steam):
        self._fov_cache.invalidate(steam)

    def on_userinfo(self, player, changed, infostring):
        try:
            if isinstance(changed, dict) and "cg_fov" in changed:
                self._invalidate_fov_cache(self._steam_str(player))
        except Exception:
            pass
        return None

    def _collect_players(self, include_weapons=False):
        """Full per-player row build — same fields as stream_telemetry.py. Only
        called once per send, right before POSTing (see _drive_positions)."""
        rows = []
        skipped = 0
        for player in self.players():
            if not self._player_in_world(player):
                skipped += 1
                continue
            try:
                pos = player.position
            except (AttributeError, TypeError, ValueError):
                skipped += 1
                continue
            if not pos or len(pos) < 3:
                skipped += 1
                continue
            steam = self._steam_str(player)
            pitch, yaw = None, None
            if self._player_cs_active(player):
                try:
                    pitch, yaw = self._view_angles(player)
                except (AttributeError, TypeError, ValueError, minqlx.EngineStateError):
                    pass
            fov = self._cached_fov(player, steam)
            health = None
            armor = None
            # player.health/armor/score/kills/deaths/ping all resolve through
            # _live_entity / gclient / _live_stats in v1.0.0, so each one can raise
            # EngineStateError while the game VM is transiently unavailable.
            try:
                health = int(player.health)
            except (AttributeError, TypeError, ValueError, minqlx.EngineStateError):
                pass
            try:
                armor = int(player.armor)
            except (AttributeError, TypeError, ValueError, minqlx.EngineStateError):
                pass
            try:
                score = int(player.score)
            except (AttributeError, TypeError, ValueError, minqlx.EngineStateError):
                score = None
            try:
                kills = int(player.kills)
            except (AttributeError, TypeError, ValueError, minqlx.EngineStateError):
                kills = None
            try:
                deaths = int(player.deaths)
            except (AttributeError, TypeError, ValueError, minqlx.EngineStateError):
                deaths = None
            try:
                ping = int(player.ping)
            except (AttributeError, TypeError, ValueError, minqlx.EngineStateError):
                ping = None
            row = {
                "steam_id64": steam,
                "nickname": self._display_name(player),
                "team": (
                    str(getattr(player, "team"))
                    if getattr(player, "team", None) not in (None, "")
                    else None
                ),
                "x": float(pos[0]),
                "y": float(pos[1]),
                "z": float(pos[2]),
                "pitch": pitch,
                "yaw": yaw,
                "alive": bool(getattr(player, "is_alive", True)),
            }
            if fov is not None:
                row["fov"] = fov
            if health is not None:
                row["health"] = health
            if armor is not None:
                row["armor"] = armor
            if score is not None:
                row["score"] = score
            if kills is not None:
                row["kills"] = kills
            if deaths is not None:
                row["deaths"] = deaths
            if ping is not None and ping >= 0:
                row["ping"] = ping
            powerups = self._active_powerups(player)
            if powerups:
                row["powerups"] = powerups
            if include_weapons:
                weapons = self._weapon_stats(player)
                if weapons:
                    row["weapons"] = weapons
            weapon_idx = self._player_weapon_idx(player)
            if weapon_idx is not None:
                row["weapon"] = weapon_idx
            loadout = self._player_loadout_mask(player)
            if loadout is not None:
                row["loadout"] = loadout
            ammo = self._player_ammo_dict(player)
            if ammo:
                row["ammo"] = ammo
            vx, vy, vz = self._player_velocity(player)
            if vx is not None and vy is not None and vz is not None:
                row["vx"] = round(vx, 1)
                row["vy"] = round(vy, 1)
                row["vz"] = round(vz, 1)
            rows.append(row)
        if skipped and self._positions_telemetry_ready():
            self._positions_skip_log_tick += 1
            if self._positions_skip_log_tick % 200 == 1:
                self.logger.debug(
                    "stream_telemetry_unified: skipped %s players (no position/in-world)",
                    skipped,
                )
        return rows

    def _positions_telemetry_ready(self):
        if not self._positions_enabled():
            return False
        if time.time() < self._positions_armed_at:
            return False
        return True

    def _build_positions_payload(self):
        now = time.time()
        include_weapons = (now - self._positions_last_accuracy_send) >= self._accuracy_interval()
        payload = {
            "match_id": self._match_id(),
            "map_name": self._map_name(),
            "gametype": self._gametype(),
            "players": self._collect_players(include_weapons=include_weapons),
            # See stream_telemetry.py's _build_payload for why this is captured
            # here instead of relying on stats-hub's ingest-time stamp.
            "sample_wall_ms": int(now * 1000),
        }
        if include_weapons:
            self._positions_last_accuracy_send = now
        game_state = getattr(self.game, "state", None) if self.game else None
        if game_state:
            payload["game_state"] = str(game_state)
            payload["warmup"] = str(game_state).lower() == "warmup"
        payload["paused"] = (
            stats_hub_pause.paused_active(self) if stats_hub_pause is not None else False
        )
        game_time = getattr(self.game, "time", None) if self.game else None
        if game_time is not None:
            try:
                ms = int(game_time)
                if ms > 0:
                    payload["game_time_ms"] = ms
            except (TypeError, ValueError):
                pass
        server_id = self._server_id()
        if server_id is not None:
            payload["server_id"] = server_id
        tournament_id = self._tournament_id()
        if tournament_id is not None:
            payload["tournament_id"] = tournament_id
        return payload

    def _warn_if_yaw_missing(self, payload):
        if self._positions_yaw_missing_warned:
            return
        players = payload.get("players") or []
        if not players:
            return
        has_yaw = any(p.get("yaw") is not None for p in players)
        if has_yaw:
            return
        self._positions_yaw_missing_warned = True
        self.logger.warning(
            "stream_telemetry_unified: yaw is null for all players — GameClient.ps.viewangles "
            "unreadable; check the minqlx build is v1.0.0+ (native attribute, no patch needed)"
        )

    def _close_positions_http_conn(self):
        conn = self._positions_http_conn
        self._positions_http_conn = None
        self._positions_http_conn_key = None
        if conn is not None:
            try:
                conn.close()
            except OSError:
                pass

    def _get_positions_http_conn(self, url):
        parsed = urlparse(url)
        scheme = (parsed.scheme or "http").lower()
        host = parsed.hostname
        if not host:
            raise ValueError("invalid stats hub url")
        port = parsed.port
        if port is None:
            port = 443 if scheme == "https" else 80
        path = parsed.path or "/"
        if parsed.query:
            path = "{}?{}".format(path, parsed.query)
        key = (scheme, host, port)
        if self._positions_http_conn is not None and self._positions_http_conn_key == key:
            return self._positions_http_conn, path
        self._close_positions_http_conn()
        if scheme == "https":
            self._positions_http_conn = http.client.HTTPSConnection(host, port, timeout=2)
        else:
            self._positions_http_conn = http.client.HTTPConnection(host, port, timeout=2)
        self._positions_http_conn_key = key
        return self._positions_http_conn, path

    @minqlx.thread
    def _post_positions(self, url, token, payload, generation):
        # url/token are snapshotted by the caller on the game thread (P1-3): this
        # method must not touch self.get_cvar()/self.game from the worker thread.
        # `generation` guards against a worker that finishes after a stuck-post
        # reset already reclaimed its slot (P1-1) — see FeedState.check_stuck.
        state = self._positions_state
        try:
            body = json.dumps(payload).encode("utf-8")
            conn, path = self._get_positions_http_conn(url)
            conn.request(
                "POST",
                path,
                body=body,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": "Bearer {}".format(token),
                    "Connection": "keep-alive",
                },
            )
            resp = conn.getresponse()
            resp.read()
            ok = resp.status < 400
            if state.complete(generation, ok):
                if ok:
                    self._record_post_result(state, True)
                else:
                    self.logger.debug("stream_telemetry_unified: positions HTTP %s", resp.status)
                    self._record_post_result(state, False)
            # else: stale — a stuck-post reset already closed/replaced the
            # connection and freed this slot for a newer request.
        except (http.client.HTTPException, OSError, ValueError) as exc:
            if state.complete(generation, False):
                self.logger.debug("stream_telemetry_unified: positions post failed: %s", exc)
                self._record_post_result(state, False)
                self._close_positions_http_conn()

    def _clear_stuck_positions_post(self, age_sec):
        state = self._positions_state
        self.logger.error(
            "stream_telemetry_unified: positions post stuck %.1fs — resetting in_flight "
            "(posts_ok=%s posts_fail=%s)",
            age_sec,
            state.posts_ok,
            state.posts_fail,
        )
        self._record_post_result(state, False)
        self._close_positions_http_conn()

    def _sync_positions_enable_state(self, enabled):
        edge = self._positions_state.sync_enabled(enabled)
        if edge == "enabled":
            self._positions_armed_at = time.time() + self._ENABLE_GRACE_SEC
            self._reset_circuit(self._positions_state)
            self.logger.info(
                "stream_telemetry_unified: positions enabled grace=%.1fs match_id=%s map=%s",
                self._ENABLE_GRACE_SEC,
                self._match_id(),
                self._map_name(),
            )
        elif edge == "disabled":
            self.logger.info(
                "stream_telemetry_unified: positions disabled (posts_ok=%s posts_fail=%s)",
                self._positions_state.posts_ok,
                self._positions_state.posts_fail,
            )
            self._positions_state.posts_ok = 0
            self._positions_state.posts_fail = 0
        return enabled

    def _drive_positions(self, enabled):
        self._sync_positions_enable_state(enabled)
        if not enabled:
            return
        now = time.time()
        if now < self._positions_armed_at:
            return
        if not self.game or self.game.state not in ("warmup", "countdown", "in_progress"):
            return
        state = self._positions_state
        if state.post_in_flight:
            age = state.check_stuck(now)
            if age is not None:
                self._clear_stuck_positions_post(age)
            return
        # Cheap pre-check before touching any player: if even the fastest possible
        # cadence hasn't elapsed, no send can fire — skips the per-player readiness
        # pass on roughly half the stride ticks at the default 10 Hz.
        active_interval = self._interval()
        idle_interval = self._idle_interval()
        since_last = now - self._positions_last_send
        if since_last < min(active_interval, idle_interval):
            return
        ready_players = self._count_ready_players()
        interval = effective_interval(ready_players, active_interval, idle_interval)
        if since_last < interval:
            return
        url = (self.get_cvar("qlx_statsHubUrl") or "").strip()
        token = (self.get_cvar("qlx_statsHubToken") or "").strip()
        payload = self._build_positions_payload()
        self._warn_if_yaw_missing(payload)
        self._positions_last_send = now
        generation = state.begin_post(now)
        self._post_positions(url, token, payload, generation)

    # ======================================================================
    # Item pickup/drop telemetry (pickup_telemetry.py equivalent)
    # ======================================================================

    def _item_events_url(self):
        return derive_ingest_url(self.get_cvar("qlx_statsHubUrl"), "item-events")

    def _warn_items_queue_pressure(self):
        size = len(self._items_queue)
        if size < self._ITEMS_QUEUE_WARN:
            self._items_queue_warned = False
            return
        if self._items_queue_warned:
            return
        self._items_queue_warned = True
        self.logger.warning(
            "stream_telemetry_unified: item queue backlog %s events (post_in_flight=%s)",
            size,
            self._items_state.post_in_flight,
        )

    def on_item_touch_stock(self, player, entity):
        """Stock runtime: stash the touched entity; the pickup that follows (same
        C call stack) rebuilds the item_event payload from it."""
        try:
            origin = entity.r.current_origin
            self._last_item_touch[int(player.id)] = (
                int(entity.number),
                str(entity.classname or ""),
                int(entity.s.modelindex),
                float(origin.x),
                float(origin.y),
                float(origin.z),
            )
        except (AttributeError, TypeError, ValueError, _ENGINE_ERR):
            pass
        return minqlx.Return.NONE

    def on_item_pickup_stock(self, player, item):
        info = self._last_item_touch.pop(int(player.id), None)
        if not info:
            return minqlx.Return.NONE
        eid, classname, bg_index, x, y, z = info
        gi_type = gi_tag = gi_quantity = 0
        try:
            bg_item = minqlx.Item(int(bg_index))
            gi_type = int(bg_item.gi_type)
            gi_tag = int(bg_item.gi_tag)
            gi_quantity = int(bg_item.quantity)
        except (AttributeError, TypeError, ValueError, _ENGINE_ERR):
            pass
        try:
            game_time = int(minqlx.level.time)
        except (AttributeError, TypeError, ValueError, _ENGINE_ERR):
            game_time = 0
        return self.on_item_event(
            "pickup", eid, player, classname or str(item or ""),
            gi_type, gi_tag, gi_quantity, x, y, z, game_time,
        )

    def on_item_event(
        self,
        action,
        item_entity_id,
        player,
        classname,
        gi_type,
        gi_tag=0,
        gi_quantity=0,
        x=0.0,
        y=0.0,
        z=0.0,
        game_time=0,
    ):
        try:
            return self._on_item_event_inner(
                action, item_entity_id, player, classname, gi_type,
                gi_tag, gi_quantity, x, y, z, game_time,
            )
        except Exception as exc:
            self._handle_frame_errors += 1
            if self._handle_frame_errors <= 3 or self._handle_frame_errors % 50 == 0:
                self.logger.exception(
                    "stream_telemetry_unified: item_event error (#%s): %s",
                    self._handle_frame_errors,
                    exc,
                )
            return minqlx.Return.NONE

    def _on_item_event_inner(
        self, action, item_entity_id, player, classname, gi_type,
        gi_tag, gi_quantity, x, y, z, game_time,
    ):
        if not self._items_enabled():
            return minqlx.Return.NONE
        if not self.game or self.game.state not in ("warmup", "in_progress"):
            return minqlx.Return.NONE
        if not player:
            return minqlx.Return.NONE
        steam = self._steam_str(player)
        if not steam:
            return minqlx.Return.NONE
        act = str(action or "pickup").strip().lower()
        if self.get_cvar("qlx_pickupTelemetryDebug", bool):
            self.logger.info(
                "stream_telemetry_unified: %s entity_id=%s item=%s gi_type=%s gi_tag=%s "
                "gi_quantity=%s pos=(%.1f,%.1f,%.1f)",
                act,
                int(item_entity_id),
                str(classname or ""),
                int(gi_type or 0),
                int(gi_tag or 0),
                int(gi_quantity or 0),
                float(x),
                float(y),
                float(z),
            )
        if len(self._items_queue) >= self._ITEMS_MAX_QUEUE:
            # Rate-limited (P2-2): a stuck relay drops one event per pickup, which
            # at MG/SG pickup rates during a chaotic warmup can be dozens/sec —
            # logging every single one floods the log for no extra information.
            self._items_queue_full_drops += 1
            if self._items_queue_full_drops <= 3 or self._items_queue_full_drops % 100 == 0:
                self.logger.error(
                    "stream_telemetry_unified: item queue full (%s), refusing new event "
                    "(dropped=%s) entity_id=%s item=%s",
                    self._ITEMS_MAX_QUEUE,
                    self._items_queue_full_drops,
                    int(item_entity_id),
                    str(classname or ""),
                )
            return minqlx.Return.NONE
        self._items_queue.append(
            {
                "action": act,
                "item": str(classname or ""),
                "item_entity_id": int(item_entity_id),
                "gi_type": int(gi_type or 0),
                "gi_tag": int(gi_tag or 0),
                "gi_quantity": int(gi_quantity or 0),
                "gi_category": self._GI_TYPE_LABELS.get(int(gi_type or 0)),
                "steam_id64": steam,
                "nickname": getattr(player, "name", None),
                "x": float(x),
                "y": float(y),
                "z": float(z),
                "game_time": int(game_time),
            }
        )
        self._warn_items_queue_pressure()
        self._flush_items_async()
        return minqlx.Return.NONE

    @staticmethod
    def _items_relay_accepted(resp_status, resp_body):
        if resp_status >= 400:
            return False
        if not resp_body:
            return True
        try:
            ack = json.loads(resp_body.decode("utf-8"))
        except (ValueError, UnicodeError):
            return True
        if not isinstance(ack, dict):
            return True
        if ack.get("ok") is False:
            return False
        if ack.get("forwarded") is True:
            return True
        if ack.get("forwarded") is False:
            return False
        if ack.get("status") == "busy" or ack.get("queued") is False:
            return False
        return True

    def _flush_items_async(self):
        # Payload snapshot (match_id/map/gametype/server_id/url/token) is built
        # here, on the game thread, and handed to the worker (P1-3) — the worker
        # must not call self.get_cvar()/self.game itself. Only ever called from
        # the game thread (on_item_event, _drive_item_events); the worker no
        # longer self-retriggers (see _post_items_batch), so there is no
        # cross-thread caller here to race against.
        state = self._items_state
        if state.post_in_flight or not self._items_queue:
            return
        ingest_url = self._item_events_url()
        token = (self.get_cvar("qlx_statsHubToken") or "").strip()
        if not ingest_url:
            self.logger.warning("stream_telemetry_unified: missing stats hub url (items)")
            return
        batch = self._items_queue[: self._ITEMS_BATCH_SIZE]
        payload = {
            "match_id": self._match_id(),
            "map_name": getattr(self.game, "map", None),
            "gametype": getattr(self.game, "type_short", None),
            "events": batch,
        }
        server_id = self._server_id()
        if server_id is not None:
            payload["server_id"] = server_id
        generation = state.begin_post(time.time())
        self._post_items_batch(ingest_url, token, payload, len(batch), generation)

    @staticmethod
    def _post_once(ingest_url, token, body, timeout_sec):
        parsed = urlparse(ingest_url)
        host = parsed.hostname
        if not host:
            raise ValueError("missing ingest host")
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        path = parsed.path or "/"
        if parsed.scheme == "https":
            conn = http.client.HTTPSConnection(host, port, timeout=timeout_sec)
        else:
            conn = http.client.HTTPConnection(host, port, timeout=timeout_sec)
        try:
            conn.request(
                "POST",
                path,
                body=body,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": "Bearer {}".format(token),
                    "Connection": "close",
                },
            )
            resp = conn.getresponse()
            resp_body = resp.read()
            return resp.status, resp_body
        finally:
            try:
                conn.close()
            except OSError:
                pass

    @minqlx.thread
    def _post_items_batch(self, ingest_url, token, payload, batch_len, generation):
        # ingest_url/token/payload are a snapshot taken by _flush_items_async on
        # the game thread (P1-3) — this method must not touch self.get_cvar()/
        # self.game. `generation` guards the queue delete below against a worker
        # that finishes after a stuck-post reset already reclaimed its slot
        # (P1-1): without it, a late-finishing worker could del the WRONG batch
        # off the front of a queue a newer worker has already advanced.
        #
        # No self-retrigger on the way out (unlike the original pickup_telemetry
        # pattern): retriggering here would call _flush_items_async(), which now
        # builds the payload snapshot and would do so from this background
        # thread. _drive_item_events runs every frame regardless, so a
        # leftover queue is picked up within one frame (~10-25ms) — a
        # negligible latency cost for not touching engine state off-thread.
        state = self._items_state
        body = json.dumps(payload).encode("utf-8")
        last_exc = None
        for attempt in range(self._ITEMS_POST_MAX_RETRIES):
            if attempt:
                backoff = self._ITEMS_POST_RETRY_BACKOFF_SEC[
                    min(attempt - 1, len(self._ITEMS_POST_RETRY_BACKOFF_SEC) - 1)
                ]
                time.sleep(backoff)
            try:
                status, resp_body = self._post_once(
                    ingest_url, token, body, self._ITEMS_POST_TIMEOUT_SEC
                )
                if self._items_relay_accepted(status, resp_body):
                    if state.complete(generation, True):
                        del self._items_queue[:batch_len]
                        self._record_post_result(state, True)
                    return
                last_exc = RuntimeError("relay rejected HTTP {}".format(status))
            except (http.client.HTTPException, OSError, ValueError) as exc:
                last_exc = exc
        if not state.complete(generation, False):
            return
        events = payload.get("events") or []
        entity = events[0] if events else {}
        self.logger.warning(
            "stream_telemetry_unified: item POST failed after %s tries (%s queued, "
            "batch kept) entity_id=%s item=%s url=%s: %s",
            self._ITEMS_POST_MAX_RETRIES,
            len(self._items_queue),
            entity.get("item_entity_id"),
            entity.get("item"),
            ingest_url,
            last_exc,
        )
        self._record_post_result(state, False)

    def _drive_item_events(self, enabled):
        state = self._items_state
        if state.sync_enabled(enabled) == "enabled":
            self._reset_circuit(state)
        if not enabled:
            return
        if state.post_in_flight:
            age = state.check_stuck(time.time())
            if age is not None:
                self.logger.error(
                    "stream_telemetry_unified: item post stuck %.1fs — resetting "
                    "(queue=%s posts_ok=%s posts_fail=%s)",
                    age,
                    len(self._items_queue),
                    state.posts_ok,
                    state.posts_fail,
                )
                self._record_post_result(state, False)
            return
        if not self._items_queue:
            return
        self._flush_items_async()

    # ======================================================================
    # Session/chat/vote/pause events (session_events.py equivalent)
    # ======================================================================

    def _session_events_url(self):
        return derive_ingest_url(self.get_cvar("qlx_statsHubUrl"), "session-events")

    def _game_time_ms(self, *, allow_zero=False):
        game_time = getattr(self.game, "time", None) if self.game else None
        if game_time is None:
            return None
        try:
            ms = int(game_time)
            if ms < 0:
                return None
            if ms == 0 and not allow_zero:
                return None
            return ms
        except (TypeError, ValueError):
            return None

    def _level_time_ms(self):
        return self._game_time_ms(allow_zero=True)

    def _sv_paused_active(self):
        if stats_hub_pause is None:
            return False
        return stats_hub_pause.paused_active(self)

    def _match_elapsed_ms(self):
        """Wall match clock minus accumulated pauses (authoritative for pause markers)."""
        if self._match_start_wall is None:
            gt = self._game_time_ms(allow_zero=True)
            return int(gt) if gt is not None else 0
        wall_ms = int((time.time() - self._match_start_wall) * 1000)
        pause_ms = int(self._pause_accumulated_ms)
        if self._pause_wall_at is not None:
            pause_ms += int((time.time() - self._pause_wall_at) * 1000)
        return max(0, wall_ms - pause_ms)

    def _open_pause_lifecycle(self, reason):
        if self._pause_lifecycle_open:
            return
        self._pause_lifecycle_open = True
        self._pause_wall_at = time.time()
        self._pause_reason = reason or "admin"
        elapsed_ms = self._match_elapsed_ms()
        # game_time_ms must come from the same clock (self.game.time) as
        # positions/death/pickup samples, not the wall-clock-minus-pauses
        # reconstruction above - replay chronology on the client merges every
        # event by this field, and a pause marker on a different clock basis
        # than its neighbouring samples reads as a clock freeze/jump on
        # playback (see ql-stream-tools replay-clock investigation). Same
        # engine-time-first, wall-estimate-fallback precedent already used by
        # _resolve_match_end_game_time_ms(). elapsed_ms stays in meta for
        # pause-duration display, which does want the wall-clock estimate.
        game_time_ms = self._game_time_ms(allow_zero=True)
        if game_time_ms is None:
            game_time_ms = elapsed_ms
        self._post_session_lifecycle_now(
            "pause_start",
            game_time_ms=game_time_ms,
            meta={"reason": self._pause_reason, "elapsed_ms": elapsed_ms},
        )

    def _close_pause_lifecycle(self):
        if not self._pause_lifecycle_open:
            return
        duration_ms = None
        if self._pause_wall_at is not None:
            duration_ms = int((time.time() - self._pause_wall_at) * 1000)
            self._pause_accumulated_ms += max(0, duration_ms)
        elapsed_ms = self._match_elapsed_ms()
        # See _open_pause_lifecycle above for why game_time_ms is sourced from
        # self.game.time (via _game_time_ms) rather than elapsed_ms here.
        game_time_ms = self._game_time_ms(allow_zero=True)
        if game_time_ms is None:
            game_time_ms = elapsed_ms
        meta = {"reason": self._pause_reason or "admin", "elapsed_ms": elapsed_ms}
        if duration_ms is not None:
            meta["duration_ms"] = duration_ms
        self._post_session_lifecycle_now("pause_end", game_time_ms=game_time_ms, meta=meta)
        self._pause_lifecycle_open = False
        self._pause_wall_at = None
        self._pause_reason = None

    def _poll_sv_paused(self):
        if not self._session_match_running:
            return
        current = self._sv_paused_active()
        prev = self._last_sv_paused
        if prev is None:
            self._last_sv_paused = current
            if current and not self._pause_lifecycle_open:
                # Don't null self._pause_reason here: _open_pause_lifecycle() just
                # set it (to the reason we passed, or "admin"), and _close_pause_
                # lifecycle() is what reads/clears it later. Wiping it right after
                # setting it was why pause_end always logged reason="admin".
                reason = self._pause_reason or "admin"
                self._open_pause_lifecycle(reason)
            return
        if not prev and current:
            reason = self._pause_reason or "admin"
            self._open_pause_lifecycle(reason)
        elif prev and not current:
            self._close_pause_lifecycle()
        self._last_sv_paused = current

    def _timelimit_sec(self):
        for name in ("timelimit", "g_timelimit", "duel_timelimit"):
            raw = (self.get_cvar(name) or "").strip()
            if not raw:
                continue
            try:
                val = int(float(raw))
            except (TypeError, ValueError):
                continue
            if val <= 0:
                continue
            if val <= 60:
                return val * 60
            return val
        return None

    def _fraglimit(self):
        for name in ("fraglimit", "g_fraglimit"):
            raw = (self.get_cvar(name) or "").strip()
            if not raw:
                continue
            try:
                val = int(float(raw))
            except (TypeError, ValueError):
                continue
            return val if val > 0 else None
        return None

    def _player_summary(self, player):
        if player is None or self._is_bot(player):
            return None
        steam = self._steam_str(player)
        if not steam:
            return None
        stats = getattr(player, "stats", None)
        score = kills = deaths = 0
        if stats is not None:
            score = int(getattr(stats, "score", 0) or 0)
            kills = int(getattr(stats, "kills", 0) or 0)
            deaths = int(getattr(stats, "deaths", 0) or 0)
        team = getattr(player, "team", None)
        return {
            "steam_id64": steam,
            "nickname": self._display_name(player),
            "team": str(team) if team is not None else None,
            "score": score,
            "kills": kills,
            "deaths": deaths,
        }

    def _collect_player_summaries(self):
        rows = []
        for player in self.players():
            row = self._player_summary(player)
            if row:
                rows.append(row)
        return rows

    def _winner_steam_id64(self, players):
        if not players:
            return None
        best = max(players, key=lambda p: p.get("score", 0))
        if best.get("score", 0) <= 0:
            return None
        return best.get("steam_id64")

    def _enqueue_lifecycle(self, kind, *, game_time_ms=None, meta=None):
        if not self._session_enabled():
            return None
        row = {
            "kind": kind,
            "steam_id64": None,
            "nickname": None,
            "text": None,
            "game_time_ms": game_time_ms,
            "meta": meta or {},
        }
        if len(self._session_queue) >= self._SESSION_MAX_QUEUE:
            self._session_queue.pop(0)
        self._session_queue.append(row)
        return row

    def _resolve_match_end_game_time_ms(self, meta):
        end_ms = self._game_time_ms(allow_zero=True)
        if end_ms is None:
            end_ms = self._last_game_time_ms
        if end_ms is None and meta.get("end_reason") == "ended":
            tl = self._timelimit_sec()
            if tl:
                end_ms = int(tl) * 1000
        return end_ms

    def _post_session_events_now(self, batch):
        if not batch or not self._session_enabled():
            return
        state = self._session_state
        if state.post_in_flight:
            for row in reversed(batch):
                self._session_queue.insert(0, row)
            return
        # url/token snapshotted here on the game thread (P1-3) — the worker must
        # not call self.get_cvar() itself.
        url = self._session_events_url()
        token = (self.get_cvar("qlx_statsHubToken") or "").strip()
        generation = state.begin_post(time.time())
        payload = self._build_session_payload(batch)
        self._post_session_batch(url, token, payload, generation)

    def _post_session_lifecycle_now(self, kind, *, game_time_ms=None, meta=None):
        row = self._enqueue_lifecycle(kind, game_time_ms=game_time_ms, meta=meta)
        if not row:
            return
        if self._session_queue and self._session_queue[-1] is row:
            self._session_queue.pop()
        self._post_session_events_now([row])

    def on_game_countdown(self):
        level_ms = self._level_time_ms()
        self._post_session_lifecycle_now(
            "countdown_start", game_time_ms=level_ms, meta={"level_time_ms": level_ms}
        )
        return minqlx.Return.NONE

    def on_game_start(self):
        self._session_match_running = True
        if stats_hub_pause is not None:
            stats_hub_pause.reset_pause_state()
        self._last_game_time_ms = 0
        self._match_start_wall = time.time()
        self._pause_accumulated_ms = 0
        self._pause_lifecycle_open = False
        self._pause_wall_at = None
        self._pause_reason = None
        self._last_sv_paused = None
        level_ms = self._level_time_ms()
        meta = {
            "level_time_ms": level_ms,
            "timelimit_sec": self._timelimit_sec(),
            "fraglimit": self._fraglimit(),
        }
        self._post_session_lifecycle_now("match_start", game_time_ms=0, meta=meta)
        return minqlx.Return.NONE

    def on_game_end(self, aborted):
        players = self._collect_player_summaries()
        meta = {
            "players": players,
            "timelimit_sec": self._timelimit_sec(),
            "fraglimit": self._fraglimit(),
            "level_time_ms": self._level_time_ms(),
        }
        meta["end_reason"] = "abort" if aborted else "ended"
        winner = self._winner_steam_id64(players)
        if winner:
            meta["winner_steam_id64"] = winner
        end_ms = self._resolve_match_end_game_time_ms(meta)
        if end_ms is not None:
            meta["level_time_ms"] = end_ms
        self._post_session_lifecycle_now("match_end", game_time_ms=end_ms, meta=meta)
        if self._pause_lifecycle_open:
            self._close_pause_lifecycle()
        self._session_match_running = False
        if stats_hub_pause is not None:
            stats_hub_pause.reset_pause_state()
        self._last_game_time_ms = None
        self._match_start_wall = None
        self._pause_accumulated_ms = 0
        self._last_sv_paused = None
        return minqlx.Return.NONE

    def _enqueue_session(self, kind, player=None, text=None, meta=None):
        if not self._session_enabled():
            return
        if player is not None and self._is_bot(player):
            return
        steam = self._steam_str(player) if player is not None else None
        if player is not None and not steam:
            return
        row = {
            "kind": kind,
            "steam_id64": steam or None,
            "nickname": self._display_name(player) if player is not None else None,
            "text": text,
            "game_time_ms": self._game_time_ms(),
            "meta": meta or {},
        }
        if len(self._session_queue) >= self._SESSION_MAX_QUEUE:
            self._session_queue.pop(0)
        self._session_queue.append(row)
        if len(self._session_queue) >= self._SESSION_QUEUE_WARN and not self._session_queue_warned:
            self._session_queue_warned = True
            self.logger.warning(
                "stream_telemetry_unified: session queue backlog %s events", len(self._session_queue)
            )

    def on_player_connect(self, player, is_bot):
        # is_bot is the engine's own flag, authoritative here: player.is_bot reads the
        # SVF_BOT bit, which ClientConnect hasn't set yet at this point in the connect
        # sequence, so it reports every bot as human.
        if is_bot:
            return
        self._invalidate_fov_cache(self._steam_str(player))
        self._enqueue_session("connect", player)

    def on_player_disconnect(self, player, reason):
        self._invalidate_fov_cache(self._steam_str(player))
        self._enqueue_session("disconnect", player, meta={"reason": reason})

    def on_vote_started(self, player, vote, args):
        self._enqueue_session("vote_started", player, text=vote, meta={"args": args})

    def on_vote(self, player, yes):
        self._enqueue_session("vote", player, text="yes" if yes else "no", meta={"yes": bool(yes)})

    def on_player_spawn(self, player):
        if not self._session_enabled() or player is None or self._is_bot(player):
            return minqlx.Return.NONE
        meta = {}
        try:
            pos = player.position
            if pos and len(pos) >= 3:
                meta = {
                    "x": round(float(pos[0]), 1),
                    "y": round(float(pos[1]), 1),
                    "z": round(float(pos[2]), 1),
                }
        except (AttributeError, TypeError, ValueError, minqlx.EngineStateError):
            pass
        self._enqueue_session("spawn", player, meta=meta)
        return minqlx.Return.NONE

    def on_team_switch(self, player, old_team, new_team):
        if not self._session_enabled() or player is None or self._is_bot(player):
            return minqlx.Return.NONE
        self._enqueue_session(
            "team_switch",
            player,
            meta={
                "old": str(old_team) if old_team is not None else None,
                "new": str(new_team) if new_team is not None else None,
            },
        )
        return minqlx.Return.NONE

    def on_round_start(self, *args, **kwargs):
        round_number = args[0] if args and isinstance(args[0], int) else None
        self._enqueue_session("round_start", None, meta={"round": round_number})
        return minqlx.Return.NONE

    def on_round_end(self, *args, **kwargs):
        # v1.0.0 dispatches (round_number, winning_team, time) positionally; older
        # builds sent a single dict/int. Handle both without assuming which fired.
        meta = {}
        data = args[0] if args else None
        if isinstance(data, dict):
            for key in ("ROUND", "TEAM_WON", "TIME"):
                if key in data:
                    meta[key.lower()] = data[key]
        elif isinstance(data, int) and len(args) < 3:
            meta["round"] = data
        elif len(args) >= 3:
            round_number, winning_team, time_ms = args[0], args[1], args[2]
            if round_number is not None:
                meta["round"] = round_number
            if winning_team is not None:
                meta["team_won"] = str(winning_team)
            if time_ms is not None:
                meta["time"] = time_ms
        self._enqueue_session("round_end", None, meta=meta)
        return minqlx.Return.NONE

    @staticmethod
    def _weapon_from_death_mod(mod):
        # mod is minqlxtended.MeansOfDeath (StrEnum) in v1.0.0 - its str value is
        # already the bare name (e.g. "ROCKET_SPLASH"), no MOD_ prefix to strip.
        if not mod:
            return None
        text = str(mod).strip()
        return text.replace("_", " ").upper()[:32] or None

    def on_death(self, victim, killer, mod):
        if not self._session_enabled() or victim is None or self._is_bot(victim):
            return minqlx.Return.NONE
        meta = {}
        if killer is not None and killer is not victim and not self._is_bot(killer):
            killer_steam = self._steam_str(killer)
            if killer_steam:
                meta["killer_steam_id64"] = killer_steam
                meta["killer_name"] = self._display_name(killer)
        weapon = self._weapon_from_death_mod(mod)
        if weapon:
            meta["weapon"] = weapon
        self._enqueue_session("death", victim, meta=meta)
        return minqlx.Return.NONE

    def on_vote_ended(self, votes, vote, args, passed):
        self._enqueue_session(
            "vote_ended",
            None,
            text=vote,
            meta={
                "args": args,
                "passed": bool(passed),
                "yes": votes[0] if votes else None,
                "no": votes[1] if votes and len(votes) > 1 else None,
            },
        )
        if not passed or not self._session_match_running:
            return
        vote_key = str(vote or "").strip().lower()
        if vote_key != "timeout":
            return
        if self._pause_lifecycle_open or self._sv_paused_active():
            return
        self._open_pause_lifecycle("timeout_vote")

    def _build_session_payload(self, batch):
        payload = {
            "session_id": self._match_id(),
            "map_name": self._map_name(),
            "gametype": self._gametype(),
            "game_time_ms": self._game_time_ms(),
            "events": batch,
        }
        server_id = self._server_id()
        if server_id is not None:
            payload["server_id"] = server_id
        tournament_id = self._tournament_id()
        if tournament_id is not None:
            payload["tournament_id"] = tournament_id
        return payload

    @minqlx.thread
    def _post_session_batch(self, url, token, payload, generation):
        # url/token are a snapshot from the game thread (P1-3). `generation`
        # guards against a worker finishing after a stuck-post reset already
        # freed this slot for a newer request (P1-1).
        state = self._session_state
        try:
            parsed = urlparse(url)
            host = parsed.hostname
            if not host:
                raise ValueError("invalid session events url")
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
            path = parsed.path or "/"
            body = json.dumps(payload).encode("utf-8")
            if parsed.scheme == "https":
                conn = http.client.HTTPSConnection(host, port, timeout=self._SESSION_POST_TIMEOUT_SEC)
            else:
                conn = http.client.HTTPConnection(host, port, timeout=self._SESSION_POST_TIMEOUT_SEC)
            conn.request(
                "POST",
                path,
                body=body,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": "Bearer {}".format(token),
                },
            )
            resp = conn.getresponse()
            resp.read()
            conn.close()
            ok = resp.status < 400
            if state.complete(generation, ok):
                self._record_post_result(state, ok)
        except (http.client.HTTPException, OSError, ValueError) as exc:
            if state.complete(generation, False):
                self._record_post_result(state, False)
                self.logger.debug("stream_telemetry_unified: session post failed: %s", exc)

    def _sync_match_running_from_game_state(self):
        """Self-heal _session_match_running if game_start never fired.

        Ported from session_events (082f037). Rapid back-to-back games
        (forfeit -> immediate restart) can skip/coalesce minqlx game_start
        while game.state is already in_progress; without this, pause/game_time
        never tick and match_end falls back to timelimit_sec.
        """
        if self._session_match_running:
            return
        state = getattr(self.game, "state", None) if self.game else None
        if state != "in_progress":
            return
        self._session_match_running = True
        if self._last_game_time_ms is None:
            self._last_game_time_ms = 0
        if self._match_start_wall is None:
            self._match_start_wall = time.time()

    def _drive_session_events(self, enabled):
        state = self._session_state
        if state.sync_enabled(enabled) == "enabled":
            self._reset_circuit(state)
        if not enabled:
            return
        # Audit risk #5 fix: pause/game_time poll now runs on a stride instead of
        # completely unthrottled every frame. Phase-shifted off the positions
        # stride so the two never do their work in the same frame.
        self._sync_match_running_from_game_state()
        if self._session_match_running and on_stride(
            self._frame_tick, self._FRAME_STRIDE_SESSION, self._FRAME_PHASE_SESSION
        ):
            self._poll_sv_paused()
            gt = self._game_time_ms(allow_zero=True)
            if gt is not None:
                self._last_game_time_ms = gt
        if not self._session_queue:
            return
        if state.post_in_flight:
            age = state.check_stuck(time.time())
            if age is not None:
                self.logger.error(
                    "stream_telemetry_unified: session post stuck %.1fs — resetting "
                    "(queue=%s posts_ok=%s posts_fail=%s)",
                    age,
                    len(self._session_queue),
                    state.posts_ok,
                    state.posts_fail,
                )
                self._record_post_result(state, False)
            return
        if not on_stride(self._frame_tick, self._FRAME_STRIDE_SESSION, self._FRAME_PHASE_SESSION):
            return
        batch = self._session_queue[: self._SESSION_BATCH_SIZE]
        del self._session_queue[: len(batch)]
        url = self._session_events_url()
        token = (self.get_cvar("qlx_statsHubToken") or "").strip()
        generation = state.begin_post(time.time())
        payload = self._build_session_payload(batch)
        self._post_session_batch(url, token, payload, generation)
