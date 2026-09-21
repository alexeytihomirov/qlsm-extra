"""restore/codec.py canonicalize() round-trip for the dead-player respawn-remaining
field ("ri"). Pure stdlib, no minqlx/qlsm dependency - the engine-side apply/export
(_player_respawn_remaining_ms / _set_player_respawn_remaining_ms in match_restore.py)
is covered by live-server verification instead, matching this plugin's existing
convention (see the "live-tested" comments throughout match_restore.py).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from restore.codec import canonicalize


def _doc(player_row):
    return {"v": 2, "t_ms": 1000, "map": "bloodrun", "players": [player_row], "items": []}


def test_dead_player_keeps_respawn_remaining_ms():
    out = canonicalize(_doc({"cid": 0, "x": 1, "y": 2, "z": 3, "dead": 1, "ri": 1400}))
    assert out["players"][0]["dead"] == 1
    assert out["players"][0]["ri"] == 1400


def test_respawn_remaining_ms_clamped_non_negative():
    out = canonicalize(_doc({"cid": 0, "x": 1, "y": 2, "z": 3, "dead": 1, "ri": -50}))
    assert out["players"][0]["ri"] == 0


def test_respawn_remaining_ms_omitted_when_absent():
    out = canonicalize(_doc({"cid": 0, "x": 1, "y": 2, "z": 3, "dead": 1}))
    assert "ri" not in out["players"][0]


def test_respawn_remaining_ms_ignored_for_alive_player():
    out = canonicalize(_doc({"cid": 0, "x": 1, "y": 2, "z": 3, "ri": 1400}))
    assert "dead" not in out["players"][0]
    assert "ri" not in out["players"][0]


def test_respawn_remaining_ms_non_numeric_dropped():
    out = canonicalize(_doc({"cid": 0, "x": 1, "y": 2, "z": 3, "dead": 1, "ri": "soon"}))
    assert "ri" not in out["players"][0]
