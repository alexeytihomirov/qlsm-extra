"""match_restore pause/unpause leaves the engine match clock alone: QL shifts
level.start_time over a pause itself, so only a restore may rewrite it. The
pause snapshot reads the engine clock while a match is live.

Regression for 2026-10-24 (Frankfurt #2, k1llsen vs radist): a pause at 3:15
was snapped as frozen_ms=0 and the unpause wrote level.start_time = level.time,
restarting the 10 minute timelimit from 0:00."""
import logging
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _minqlx_stub import import_plugin, bare_instance

pytestmark = pytest.mark.standalone

mr = import_plugin("match_restore")

MATCH_START = 84_431_600


@pytest.fixture
def level(monkeypatch):
    lvl = SimpleNamespace(time=MATCH_START + 195_561, start_time=MATCH_START)
    monkeypatch.setattr(mr.minqlx, "level", lvl, raising=False)
    return lvl


def _plugin(paused=True, **attrs):
    state = dict(
        _restore_clock_latch_ms=None,
        _pause_frozen_ms=None,
        _level_time_ms=0,
        _match_start_map_time=None,
        _last_game_state="in_progress",
        _clock_source="none",
        _engine_clock_synced=False,
        _awaiting_unfreeze_after_unpause=False,
        _unfreeze_hold_ms=None,
        _unfreeze_thaw_token=0,
        _unfreeze_thaw_at_wall=None,
        _unfreeze_from_restore=False,
        _restore_session_active=False,
        _pickup_lock_py=False,
        _sv_paused_active=lambda: paused,
        _game_state_label=lambda: "in_progress",
        get_cvar=lambda name, *a: None,
        _flush_restore_velocities=lambda: None,
        _flush_restore_views=lambda: None,
        _end_restore_session=lambda: None,
        logger=logging.getLogger("test"),
    )
    state.update(attrs)
    return bare_instance(mr.match_restore, **state)


def test_pause_snap_reads_the_engine_clock(level):
    p = _plugin()
    assert p._refresh_pause_frozen_ms() == 195_561


def test_stale_zero_snap_does_not_reset_the_engine_clock_on_unpause(level):
    p = _plugin(_pause_frozen_ms=0)
    p._begin_unpause_clock_hold()
    level.time += 4_000
    p._finish_unpause_clock_thaw()
    assert level.start_time == MATCH_START


def test_unpause_after_restore_still_sets_the_engine_clock(level):
    p = _plugin(_restore_clock_latch_ms=120_000, _pause_frozen_ms=120_000)
    p._begin_unpause_clock_hold()
    p._finish_unpause_clock_thaw()
    assert level.time - level.start_time == 120_000


def test_countdown_does_not_read_the_engine_clock(level):
    p = _plugin(paused=False, _game_state_label=lambda: "countdown", _last_game_state="countdown")
    assert p._native_elapsed_ms() is None
