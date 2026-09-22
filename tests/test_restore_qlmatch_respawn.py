"""restore/qlmatch.py's death/respawn cross-check: a qlmatch replay has no
telemetry field for the engine's real respawnTime countdown (unlike a live
!checkpoint export), so _apply_death_overrides must derive "ri" (ms left
until the real respawn) from the recording's own eventual respawn teleport -
see the docstring on _apply_death_overrides for the real bug this closes
(restored dead players got a full fresh random respawn delay instead of the
remainder, because "ri" was never set for this restore path at all).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from restore.qlmatch import _apply_death_overrides  # noqa: E402


def _death_ev(t, victim_cn):
    return {"event": "death", "game_time_ms": t, "victim_clientNum": victim_cn}


def _pos_ev(t, cn, x, y, z):
    return {"event": "positions", "game_time_ms": t, "players": [{"clientNum": cn, "x": x, "y": y, "z": z}]}


def test_ri_is_the_real_remaining_wait_past_the_restore_target():
    # Death at 19625ms, frozen at the death spot until the real respawn
    # teleport lands at 21725ms - restoring at 20000ms should say 1725ms left.
    events = [
        _death_ev(19625, 1),
        _pos_ev(19600, 1, 633, -177, 88),
        _pos_ev(21725, 1, 633, 200, 88),  # > _RESPAWN_TELEPORT_MIN_DIST away
    ]
    players = [{"cid": 1, "h": 100}]
    _apply_death_overrides(players, events, 20000)
    assert players[0]["dead"] == 1
    assert players[0]["h"] == 0
    assert players[0]["ri"] == 1725


def test_no_ri_when_the_real_respawn_is_never_observed():
    """The recording ends before the player ever respawns - no ground truth
    to restore, so "ri" stays unset rather than a guessed value (same
    behavior as before this fix)."""
    events = [
        _death_ev(19625, 1),
        _pos_ev(19600, 1, 633, -177, 88),
    ]
    players = [{"cid": 1, "h": 100}]
    _apply_death_overrides(players, events, 20000)
    assert players[0]["dead"] == 1
    assert "ri" not in players[0]


def test_no_override_once_the_real_respawn_already_happened_by_target():
    events = [
        _death_ev(19625, 1),
        _pos_ev(19600, 1, 633, -177, 88),
        _pos_ev(20500, 1, 633, 200, 88),
    ]
    players = [{"cid": 1, "h": 100}]
    _apply_death_overrides(players, events, 21000)
    assert "dead" not in players[0]
    assert "ri" not in players[0]


def test_player_never_dead_is_left_untouched():
    players = [{"cid": 0, "h": 80}]
    _apply_death_overrides(players, [], 5000)
    assert players[0] == {"cid": 0, "h": 80}
