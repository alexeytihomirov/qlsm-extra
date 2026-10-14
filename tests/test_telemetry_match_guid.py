"""stream_telemetry_unified: match_guid (configstring 712) in countdown/start/end lifecycle events."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _minqlx_stub import bare_instance, import_plugin  # noqa: E402

pytestmark = pytest.mark.standalone

GUID = "0F8FAD5B-D9CB-469F-A165-70867728950E"
GUID2 = "1B4E28BA-2FA1-11D2-883F-0016D3CCA427"

st = import_plugin("stream_telemetry_unified")


class _Log:
    def __init__(self):
        self.records = []

    def __getattr__(self, level):
        return lambda msg, *args: self.records.append((level, msg % args if args else msg))


def _plugin(monkeypatch, configstring, last_end_guid=None):
    """Bare plugin whose lifecycle posts are captured as (kind, meta).

    configstring is the value 712 holds, or a one-element list whose item can be
    swapped between events.
    """
    posted = []
    calls = []
    box = configstring if isinstance(configstring, list) else [configstring]

    def get_configstring(index):
        calls.append(index)
        if isinstance(box[0], Exception):
            raise box[0]
        return box[0]

    monkeypatch.setattr(st.minqlx, "get_configstring", get_configstring, raising=False)
    p = bare_instance(
        st.stream_telemetry_unified,
        _collect_player_summaries=lambda: [],
        _level_time_ms=lambda: 1000,
        _timelimit_sec=lambda: 600,
        _fraglimit=lambda: 0,
        _resolve_match_end_game_time_ms=lambda meta: None,
        _pause_lifecycle_open=False,
        _post_session_lifecycle_now=lambda kind, *, game_time_ms=None, meta=None: posted.append((kind, meta)),
        _last_end_guid=last_end_guid,
        logger=_Log(),
    )
    return p, posted, calls


def _fire(p, kind):
    if kind == "countdown_start":
        p.on_game_countdown()
    elif kind == "match_start":
        p.on_game_start()
    else:
        p.on_game_end(False)


def test_normal_match_guid():
    assert st.normal_match_guid(GUID) == GUID.lower()
    assert st.normal_match_guid("  " + GUID + " ") == GUID.lower()
    for bad in ("", None, "0", "not-a-guid", GUID[:-1], GUID + "0", 712):
        assert st.normal_match_guid(bad) is None


@pytest.mark.parametrize("kind", ["countdown_start", "match_start", "match_end"])
def test_lifecycle_carries_match_guid(monkeypatch, kind):
    p, posted, calls = _plugin(monkeypatch, GUID)
    _fire(p, kind)
    got_kind, meta = posted[-1]
    assert got_kind == kind and meta["match_guid"] == GUID.lower()
    assert calls == [712]


@pytest.mark.parametrize("kind", ["countdown_start", "match_start", "match_end"])
@pytest.mark.parametrize("raw", ["", "garbage", RuntimeError("boom")])
def test_lifecycle_without_guid_has_no_key(monkeypatch, kind, raw):
    p, posted, _ = _plugin(monkeypatch, raw)
    _fire(p, kind)
    assert posted[-1][0] == kind
    assert "match_guid" not in posted[-1][1]


@pytest.mark.parametrize("kind", ["countdown_start", "match_start", "match_end"])
def test_guid_equal_to_previous_end_is_omitted(monkeypatch, kind):
    p, posted, _ = _plugin(monkeypatch, GUID, last_end_guid=GUID.lower())
    _fire(p, kind)
    assert posted[-1][0] == kind
    assert "match_guid" not in posted[-1][1]
    assert ("warning", "match_guid %s equals the previous game's; omitted" % GUID.lower()) in p.logger.records


@pytest.mark.parametrize("kind", ["countdown_start", "match_start", "match_end"])
def test_guid_different_from_previous_end_is_sent(monkeypatch, kind):
    p, posted, _ = _plugin(monkeypatch, GUID2, last_end_guid=GUID.lower())
    _fire(p, kind)
    assert posted[-1][1]["match_guid"] == GUID2.lower()
    assert not [r for r in p.logger.records if r[0] == "warning"]


def test_match_end_remembers_the_guid_it_sent(monkeypatch):
    cs = [GUID]
    p, posted, _ = _plugin(monkeypatch, cs)
    p.on_game_end(False)
    assert posted[-1][1]["match_guid"] == GUID.lower()
    # The next game's countdown still sees the old value in 712: omitted.
    p.on_game_countdown()
    assert "match_guid" not in posted[-1][1]
    # 712 moves on: the new guid is sent and, at its end, becomes the previous one.
    cs[0] = GUID2
    p.on_game_start()
    assert posted[-1][1]["match_guid"] == GUID2.lower()
    p.on_game_end(False)
    assert posted[-1][1]["match_guid"] == GUID2.lower()
    assert p._last_end_guid == GUID2.lower()


def test_guid_read_failure_is_a_warning_once(monkeypatch):
    p, posted, _ = _plugin(monkeypatch, RuntimeError("boom"))
    p.on_game_countdown()
    p.on_game_start()
    assert "match_guid" not in posted[-1][1]
    warnings = [r for r in p.logger.records if r[0] == "warning" and "boom" in r[1]]
    assert len(warnings) == 1


def test_minqlxtended_configstring_api_is_used(monkeypatch):
    """minqlxtended has no get_configstring; it reads configstrings with configstring(index, cached=...)."""
    calls = []

    def configstring(index, cached=True):
        calls.append((index, cached))
        return GUID

    monkeypatch.delattr(st.minqlx, "get_configstring", raising=False)
    monkeypatch.setattr(st.minqlx, "configstring", configstring, raising=False)
    assert st.read_configstring(712) == GUID
    assert calls == [(712, False)]


def test_upstream_minqlx_get_configstring_still_works(monkeypatch):
    monkeypatch.delattr(st.minqlx, "configstring", raising=False)
    monkeypatch.setattr(st.minqlx, "get_configstring", lambda index: GUID if index == 712 else "", raising=False)
    assert st.read_configstring(712) == GUID


def _loaded_plugin(monkeypatch, cs, state, running=False):
    """Bare plugin on which the load-time seeding runs, in the given game state."""
    p, posted, _ = _plugin(monkeypatch, cs)
    p._session_match_running = running
    p.game = type("G", (), {"state": state})() if state else None
    p._seed_last_end_guid()
    return p, posted


def test_reload_in_warmup_seeds_the_previous_guid(monkeypatch):
    p, _ = _loaded_plugin(monkeypatch, GUID, "warmup")
    assert p._last_end_guid == GUID.lower()


@pytest.mark.parametrize("state", ["in_progress", "countdown", None])
def test_reload_during_a_game_does_not_seed(monkeypatch, state):
    p, _ = _loaded_plugin(monkeypatch, GUID, state)
    assert p._last_end_guid is None


def test_reload_with_match_running_does_not_seed(monkeypatch):
    p, _ = _loaded_plugin(monkeypatch, GUID, "warmup", running=True)
    assert p._last_end_guid is None


def test_reload_seed_survives_a_bad_configstring(monkeypatch):
    p, _ = _loaded_plugin(monkeypatch, RuntimeError("boom"), "warmup")
    assert p._last_end_guid is None


def test_countdown_after_warmup_reload_with_stale_712_omits_the_guid(monkeypatch):
    p, posted = _loaded_plugin(monkeypatch, GUID, "warmup")
    p.on_game_countdown()
    assert "match_guid" not in posted[-1][1]
    assert ("warning", "match_guid %s equals the previous game's; omitted" % GUID.lower()) in p.logger.records


def test_countdown_after_warmup_reload_with_new_guid_is_sent(monkeypatch):
    cs = [GUID]
    p, posted = _loaded_plugin(monkeypatch, cs, "warmup")
    cs[0] = GUID2
    p.on_game_countdown()
    assert posted[-1][1]["match_guid"] == GUID2.lower()
