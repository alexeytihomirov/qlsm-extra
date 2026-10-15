"""stream_telemetry_unified: each feed reads only its qlx_statsHubFeed* cvar; the
legacy qlx_streamTelemetryEnabled / qlx_pickupTelemetryEnabled / qlx_sessionEventsEnabled
names are ignored."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _minqlx_stub import import_plugin, bare_instance

pytestmark = pytest.mark.standalone

st = import_plugin("stream_telemetry_unified")

LEGACY = ("qlx_streamTelemetryEnabled", "qlx_pickupTelemetryEnabled", "qlx_sessionEventsEnabled")
FEEDS = ("qlx_statsHubFeedPositions", "qlx_statsHubFeedItems", "qlx_statsHubFeedSession")


def make(cvars):
    seen = []
    cls = st.stream_telemetry_unified

    def get_cvar(name, typ=str):
        seen.append(name)
        raw = cvars.get(name)
        if raw is None:
            return None
        if typ is bool:
            return str(raw).strip().lower() not in ("0", "false", "")
        return raw

    obj = bare_instance(
        cls,
        get_cvar=get_cvar,
        _base_ready=lambda: True,
        _server_id=lambda: 1,
        _item_events_available=True,
    )
    return obj, seen


def flags(cvars):
    obj, seen = make(cvars)
    result = obj._feature_flags()
    return result, seen


def test_legacy_cvars_alone_enable_nothing():
    (positions, items, session), seen = flags({name: "1" for name in LEGACY})
    assert (positions, items, session) == (False, False, False)
    assert not set(seen) & set(LEGACY)


def test_new_cvars_enable_each_feed():
    assert flags({FEEDS[0]: "1"})[0] == (True, False, False)
    assert flags({FEEDS[1]: "1"})[0] == (False, True, False)
    assert flags({FEEDS[2]: "1"})[0] == (False, False, True)


def test_new_cvar_off_is_not_overridden_by_legacy_on():
    cvars = {name: "0" for name in FEEDS}
    cvars.update({name: "1" for name in LEGACY})
    assert flags(cvars)[0] == (False, False, False)


def test_enabled_helpers_ignore_legacy():
    obj, seen = make({name: "1" for name in LEGACY})
    assert not obj._positions_enabled()
    assert not obj._items_enabled()
    assert not obj._session_enabled()
    assert not set(seen) & set(LEGACY)
