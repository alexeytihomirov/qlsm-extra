"""stream_telemetry_unified: match_guid (configstring 712) in countdown/start/end lifecycle events."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _minqlx_stub import bare_instance, import_plugin  # noqa: E402

pytestmark = pytest.mark.standalone

GUID = "0F8FAD5B-D9CB-469F-A165-70867728950E"

st = import_plugin("stream_telemetry_unified")


def _plugin(monkeypatch, configstring):
    """Bare plugin whose lifecycle posts are captured as (kind, meta)."""
    posted = []
    calls = []

    def get_configstring(index):
        calls.append(index)
        if isinstance(configstring, Exception):
            raise configstring
        return configstring

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
