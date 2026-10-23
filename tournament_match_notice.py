"""tournament_match_notice - says in game that the players on the server have a tournament match.

When both players of a ready or live tournament match are on the server, the plugin prints one chat line
and a centre print to everyone: once when the second of them arrives, and again on every game countdown.
The tournament site (ql-tournament) answers which match that is: GET <url>/api/integrations/game-match
with the steam ids of the players, a service token with the scope game:read (spec
docs/superpowers/specs/2026-10-23-tournament-match-notice-design.md in the monorepo).

Nothing runs on the hot path: the hooks only set flags; one background worker wakes every POLL_S
seconds and asks the site only when the roster changed or a countdown began (timeout TIMEOUT_S, answers
cached CACHE_S per set of players, one request at a time). Only the output goes into the game frame.
A failed request is logged at most once a minute and the notice is skipped.

CVARs:
  qlx_matchNoticeEnabled "0"  - master switch
  qlx_matchNoticeUrl ""       - site base URL, e.g. https://frontiersgaming.com
  qlx_matchNoticeToken ""     - service token of the site (scope game:read)
"""

import http.client
import json
import re
import threading
import time
from urllib.parse import urlencode, urlparse

try:
    import minqlxtended as minqlx
except ImportError:
    import minqlx

POLL_S = 2.0
CACHE_S = 60.0
TIMEOUT_S = 3.0
ERROR_LOG_S = 60.0
IDS_MAX = 64
BODY_MAX = 65536
LOOKUP_PATH = "/api/integrations/game-match"
_STEAM_ID = re.compile(r"7656119[0-9]{10}\Z")


def human_ids(steam_ids):
    """Sorted, unique steam ids of real players (bots and odd ids skipped), at most IDS_MAX."""
    return sorted({str(s) for s in steam_ids if _STEAM_ID.match(str(s))})[:IDS_MAX]


def _names(match):
    players = match.get("players") or []
    names = [str((p or {}).get("nickname") or "?") for p in players[:2]]
    return names + ["?"] * (2 - len(names))


def chat_text(match):
    """'Tournament match: Cup - Groups Round 3 - Group A - Bo1 - a vs b. !call = referee'."""
    stage = " ".join(p for p in (match.get("stage"), match.get("label")) if p)
    best_of = match.get("best_of")
    parts = [match.get("tournament"), stage, "Bo{}".format(best_of) if best_of else None]
    a, b = _names(match)
    head = " - ".join(str(p) for p in parts if p)
    return "^3Tournament match:^7 {} - {} ^7vs^7 {}. ^3!call^7 = referee".format(head, a, b)


def center_text(match):
    a, b = _names(match)
    return "^3TOURNAMENT MATCH\n\n^7{} ^7vs^7 {}\n^7{}".format(a, b, match.get("tournament") or "")


class NoticeState:
    """Which match was announced on arrival on this map. A countdown is always announced."""

    def __init__(self):
        self._arrived = set()

    def reset(self):
        self._arrived.clear()

    def due(self, match, countdown):
        if countdown:
            self._arrived.add(match.get("key"))
            return True
        if match.get("key") in self._arrived:
            return False
        self._arrived.add(match.get("key"))
        return True


class LookupCache:
    """Answers (a match or None) per set of players for ttl seconds."""
    MISS = object()

    def __init__(self, ttl):
        self.ttl = ttl
        self._rows = {}

    def get(self, ids, now):
        row = self._rows.get(tuple(ids))
        if row is None or now - row[0] >= self.ttl:
            return self.MISS
        return row[1]

    def put(self, ids, match, now):
        self._rows = {k: v for k, v in self._rows.items() if now - v[0] < self.ttl}
        self._rows[tuple(ids)] = (now, match)


class LookupError_(Exception):
    pass


def fetch_match(base_url, token, ids, timeout=TIMEOUT_S):
    """The site's answer for these players: a match dict or None. Raises LookupError_ on any failure."""
    parsed = urlparse((base_url or "").strip())
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise LookupError_("bad url")
    cls = http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
    path = parsed.path.rstrip("/") + LOOKUP_PATH + "?" + urlencode([("steam_id", s) for s in ids])
    conn = cls(parsed.hostname, parsed.port, timeout=timeout)
    try:
        conn.request("GET", path, headers={"Authorization": "Bearer " + token, "Accept": "application/json"})
        resp = conn.getresponse()
        body = resp.read(BODY_MAX)
        status = resp.status
    except (OSError, http.client.HTTPException) as exc:
        raise LookupError_(str(exc)) from exc
    finally:
        conn.close()
    if status != 200:
        raise LookupError_("HTTP {}".format(status))
    try:
        match = json.loads(body.decode("utf-8"))["data"]["match"]
    except (ValueError, KeyError, TypeError) as exc:
        raise LookupError_("bad answer") from exc
    if match is not None and not isinstance(match, dict):
        raise LookupError_("bad answer")
    return match


class tournament_match_notice(minqlx.Plugin):
    def __init__(self):
        super().__init__()
        self.set_cvar_once("qlx_matchNoticeEnabled", "0")
        self.set_cvar_once("qlx_matchNoticeUrl", "")
        self.set_cvar_once("qlx_matchNoticeToken", "")

        self._lock = threading.Lock()
        self._roster_changed = True
        self._countdown = False
        self._state = NoticeState()
        self._cache = LookupCache(CACHE_S)
        self._last_error_log = None
        self._fetch = fetch_match

        self.add_hook("player_loaded", self.handle_roster)
        self.add_hook("player_disconnect", self.handle_player_disconnect)
        self.add_hook("team_switch", self.handle_team_switch)
        self.add_hook("game_countdown", self.handle_game_countdown)
        self.add_hook("map", self.handle_map)
        self.add_hook("unload", self.handle_unload)

        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        self.plugin_version = "1.0"

    # Hooks: flags only (under the lock the worker reads and clears them with, so none is lost).
    def _flag_roster(self):
        with self._lock:
            self._roster_changed = True

    def handle_roster(self, player):
        self._flag_roster()

    def handle_player_disconnect(self, player, reason):
        self._flag_roster()

    def handle_team_switch(self, player, old_team, new_team):
        self._flag_roster()

    def handle_game_countdown(self):
        with self._lock:
            self._countdown = True

    def handle_map(self, mapname, factory):
        with self._lock:
            self._state.reset()

    def handle_unload(self, plugin):
        if plugin == self.__class__.__name__:
            self._stop_event.set()

    # Worker.
    def _loop(self):
        while not self._stop_event.wait(POLL_S):
            try:
                self._tick(time.monotonic())
            except Exception as exc:  # the worker must outlive any surprise
                self._log_error("tick failed: {}".format(exc))

    def _settings(self):
        if not self.get_cvar("qlx_matchNoticeEnabled", bool):
            return None
        url = (self.get_cvar("qlx_matchNoticeUrl") or "").strip()
        token = (self.get_cvar("qlx_matchNoticeToken") or "").strip()
        return (url, token) if url and token else None

    def _tick(self, now):
        with self._lock:
            changed, countdown = self._roster_changed, self._countdown
            self._roster_changed = self._countdown = False
        if not (changed or countdown):
            return
        settings = self._settings()
        if settings is None:
            return
        ids = human_ids(str(p.steam_id) for p in self.players())
        if len(ids) < 2:
            return
        match = self._cache.get(ids, now)
        if match is LookupCache.MISS:
            try:
                match = self._fetch(settings[0], settings[1], ids)
            except LookupError_ as exc:
                self._log_error("lookup failed: {}".format(exc))
                return
            self._cache.put(ids, match, now)
        if match is None:
            return
        with self._lock:
            due = self._state.due(match, countdown)
        if due:
            self._announce(chat_text(match), center_text(match))

    @minqlx.next_frame
    def _announce(self, chat, center):
        self.msg(chat)
        self.center_print(center)  # Plugin.center_print is the broadcast

    def _log_error(self, text):
        now = time.monotonic()
        if self._last_error_log is None or now - self._last_error_log >= ERROR_LOG_S:
            self._last_error_log = now
            self.logger.warning("tournament_match_notice: %s", text)
