"""stream_telemetry_unified: winner_steam_id64 in match_end, including a forfeit (end_reason abort)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _minqlx_stub import bare_instance, import_plugin  # noqa: E402

pytestmark = pytest.mark.standalone

st = import_plugin("stream_telemetry_unified")

A = "76561198000000001"
B = "76561198000000002"


def _row(steam, team, score=0):
    return {"steam_id64": steam, "nickname": steam[-1], "team": team, "score": score, "kills": score, "deaths": 0}


def _winner(players, aborted):
    p = bare_instance(st.stream_telemetry_unified)
    return p._winner_steam_id64(players, aborted)


def test_finished_game_winner_is_the_top_score():
    assert _winner([_row(A, "free", 3), _row(B, "free", 7)], aborted=False) == B


def test_finished_game_without_frags_has_no_winner():
    assert _winner([_row(A, "free"), _row(B, "free")], aborted=False) is None


def test_forfeit_to_spectator_gives_the_game_to_the_one_who_stayed():
    # Seen live 2026-10-15: the leaver is listed as spectator in match_end, the stayer as free.
    assert _winner([_row(A, "spectator"), _row(B, "free")], aborted=True) == B


def test_forfeit_by_disconnect_gives_the_game_to_the_one_who_stayed():
    assert _winner([_row(B, "free", 0)], aborted=True) == B


def test_forfeit_ignores_the_score():
    assert _winner([_row(A, "spectator", 9), _row(B, "free", 2)], aborted=True) == B


def test_abort_with_both_still_playing_has_no_winner():
    # e.g. the game was stopped by a vote: nobody forfeited.
    assert _winner([_row(A, "free", 5), _row(B, "free", 1)], aborted=True) is None


def test_abort_with_nobody_playing_has_no_winner():
    assert _winner([_row(A, "spectator"), _row(B, "spectator")], aborted=True) is None
