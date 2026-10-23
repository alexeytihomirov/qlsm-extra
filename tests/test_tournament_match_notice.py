"""tournament_match_notice: who is asked about, what is said, when, and the site request itself."""
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _minqlx_stub import bare_instance, import_plugin  # noqa: E402

tmn = import_plugin("tournament_match_notice")

pytestmark = pytest.mark.standalone

A = "76561198074185301"
B = "76561190000000008"
MATCH = {"tournament": "Check Cup 2026-10", "stage": "Groups", "label": "Round 3 - Group A", "key": "A-R3-1",
         "best_of": 1, "status": "ready",
         "players": [{"steam_id64": A, "nickname": "Cyber"}, {"steam_id64": B, "nickname": "CheckTest08"}]}


def test_human_ids_skip_bots_and_junk_and_sort():
    assert tmn.human_ids([B, "90071996842377216", "0", A, A, "7656119x", B + "\n"]) == sorted([A, B])
    assert len(tmn.human_ids("7656119{:010d}".format(i) for i in range(100))) == tmn.IDS_MAX


def test_texts():
    assert tmn.chat_text(MATCH) == ("^3Tournament match:^7 Check Cup 2026-10 - Groups Round 3 - Group A - Bo1"
                                    " - Cyber ^7vs^7 CheckTest08. ^3!call^7 = referee")
    bare = {"tournament": "Cup", "stage": "Final", "label": "", "best_of": None, "players": []}
    assert tmn.chat_text(bare) == "^3Tournament match:^7 Cup - Final - ? ^7vs^7 ?. ^3!call^7 = referee"
    assert "Cyber ^7vs^7 CheckTest08" in tmn.center_text(MATCH)


def test_state_once_per_map_unless_forgotten():
    s = tmn.NoticeState()
    assert s.due(MATCH) is True
    assert s.due(MATCH) is False
    s.forget(MATCH["key"])
    assert s.due(MATCH) is True
    s.reset()
    assert s.due(MATCH) is True


def test_cache_expires():
    c = tmn.LookupCache(60)
    assert c.get([A, B], 0) is tmn.LookupCache.MISS
    c.put([A, B], None, 0)
    assert c.get([A, B], 59) is None
    assert c.get([A, B], 60) is tmn.LookupCache.MISS


class _Site(BaseHTTPRequestHandler):
    answer = (200, {"data": {"match": MATCH}})
    seen = []

    def do_GET(self):
        _Site.seen.append((self.path, self.headers.get("Authorization")))
        status, body = _Site.answer
        raw = json.dumps(body).encode() if not isinstance(body, bytes) else body
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *args):
        pass


@pytest.fixture
def site():
    server = HTTPServer(("127.0.0.1", 0), _Site)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    _Site.seen = []
    yield "http://127.0.0.1:{}/".format(server.server_port)
    server.shutdown()
    server.server_close()


def test_fetch_sends_ids_and_token_and_reads_the_match(site):
    assert tmn.fetch_match(site, "qlt_x", [A, B]) == MATCH
    path, auth = _Site.seen[0]
    parsed = urlparse(path)
    assert parsed.path == "/api/integrations/game-match"
    assert parse_qs(parsed.query)["steam_id"] == [A, B]
    assert auth == "Bearer qlt_x"


@pytest.mark.parametrize("answer", [(401, {"error": {}}), (200, b"not json"), (200, {"data": {"match": 5}})])
def test_fetch_failures_raise(site, answer):
    _Site.answer = answer
    try:
        with pytest.raises(tmn.LookupError_):
            tmn.fetch_match(site, "t", [A, B])
    finally:
        _Site.answer = (200, {"data": {"match": MATCH}})


def test_fetch_unreachable_or_bad_url_raise():
    with pytest.raises(tmn.LookupError_):
        tmn.fetch_match("http://127.0.0.1:9/", "t", [A, B], timeout=1)
    with pytest.raises(tmn.LookupError_):
        tmn.fetch_match("ftp://x", "t", [A, B])


def _plugin(players, fetch, enabled=True):
    cvars = {"qlx_matchNoticeEnabled": enabled, "qlx_matchNoticeUrl": "https://site", "qlx_matchNoticeToken": "t"}
    said = []
    p = bare_instance(
        tmn.tournament_match_notice,
        _lock=threading.Lock(), _roster_changed=True, _state=tmn.NoticeState(),
        _cache=tmn.LookupCache(tmn.CACHE_S), _last_error_log=None, _fetch=fetch,
        get_cvar=lambda name, kind=str: cvars[name],
        players=lambda: [SimpleNamespace(steam_id=s) for s in players],
        logger=SimpleNamespace(warning=lambda *a: said.append(("warn",) + a)),
    )
    p._announce = lambda key, chat, center: said.append(("say", chat))
    return p, said


def test_tick_announces_once_per_map():
    calls = []
    p, said = _plugin([A, B, "90071996842377216"], lambda url, token, ids: calls.append(ids) or MATCH)
    p._tick(0)
    p._tick(1)  # nothing flagged: no request, no output
    p._flag_roster()
    p._tick(2)  # roster changed again: cached answer, already announced
    p.handle_new_game()
    p._tick(3)
    assert calls == [sorted([A, B])]
    assert [s[0] for s in said] == ["say"]
    p.handle_map("campgrounds", "duel")
    p.handle_new_game()
    p._tick(4)
    assert [s[0] for s in said] == ["say", "say"]


@pytest.mark.parametrize("state", ["countdown", "in_progress"])
def test_announce_outside_warmup_says_nothing_and_waits_for_the_next_game(state):
    said = []
    game = SimpleNamespace(state=state)
    p = bare_instance(
        tmn.tournament_match_notice, _lock=threading.Lock(), _state=tmn.NoticeState(), game=game,
        msg=lambda text: said.append(("say", text)), center_print=lambda text: said.append(("center", text)))
    assert p._state.due(MATCH)
    p._announce(MATCH["key"], "chat", "center")
    assert said == []
    assert p._state.due(MATCH) is True  # forgotten, so due again once back in warmup
    game.state = "warmup"
    p._announce(MATCH["key"], "chat", "center")
    assert said == [("say", "chat"), ("center", "center")]


def test_tick_quiet_without_match_settings_or_pair():
    p, said = _plugin([A, B], lambda *a: None)
    p._tick(0)
    p, said2 = _plugin([A], lambda *a: MATCH)
    p._tick(0)
    p, said3 = _plugin([A, B], lambda *a: MATCH, enabled=False)
    p._tick(0)
    assert said == said2 == said3 == []


def test_tick_logs_a_failure_once_a_minute_and_retries_on_the_next_change():
    def fail(*a):
        raise tmn.LookupError_("down")
    p, said = _plugin([A, B], fail)
    p._tick(0)
    p._flag_roster()
    p._tick(1)
    assert [s[0] for s in said] == ["warn"]
    p._fetch = lambda *a: MATCH
    p._flag_roster()
    p._tick(2)
    assert [s[0] for s in said] == ["warn", "say"]
