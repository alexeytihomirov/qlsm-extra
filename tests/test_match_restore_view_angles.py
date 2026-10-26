"""match_restore exports and restores the player's view angles (pa/ya) through
GameClient.ps.delta_angles: view = usercmd angles + delta_angles. Rows without
angles, and stock minqlx without GameClient, restore exactly as before."""
import logging
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _minqlx_stub import import_plugin, bare_instance

pytestmark = pytest.mark.standalone

mr = import_plugin("match_restore")


def _short(angle):
    return int(angle * 65536 / 360) & 65535


class FakeGameClient:
    instances = {}

    def __init__(self, cid):
        self.pers = SimpleNamespace(cmd_angles=[65776, 65600, 0])
        self.ps = SimpleNamespace(viewangles=(12.5, -90.25, 0.0), delta_angles=[0, 0, 0])
        FakeGameClient.instances[cid] = self


@pytest.fixture
def gc(monkeypatch):
    FakeGameClient.instances = {}
    monkeypatch.setattr(mr.minqlx, "GameClient", FakeGameClient, raising=False)
    return FakeGameClient


@pytest.fixture
def no_gc(monkeypatch):
    monkeypatch.delattr(mr.minqlx, "GameClient", raising=False)


def _plugin(**attrs):
    state = dict(
        _view_apply_queue=[],
        _restore_pending_views={},
        player=lambda cid: SimpleNamespace(id=cid),
        logger=logging.getLogger("test"),
    )
    state.update(attrs)
    return bare_instance(mr.match_restore, **state)


def test_export_reads_viewangles(gc):
    assert mr.match_restore._export_view_angles(SimpleNamespace(id=4)) == {"pa": 12.5, "ya": -90.25}


def test_export_without_gameclient_is_none(no_gc):
    assert mr.match_restore._export_view_angles(SimpleNamespace(id=4)) is None


def test_export_engine_error_is_none(monkeypatch):
    def boom(cid):
        raise mr._ENGINE_ERR("vm not ready")

    monkeypatch.setattr(mr.minqlx, "GameClient", boom, raising=False)
    assert mr.match_restore._export_view_angles(SimpleNamespace(id=4)) is None


def test_write_sets_delta_angles_from_cmd_angles(gc):
    assert mr.match_restore._write_player_view(SimpleNamespace(id=2), 30.0, 270.0)
    delta = gc.instances[2].ps.delta_angles
    assert delta == [_short(30.0) - 65776, _short(270.0) - 65600, 0]
    # view = cmd + delta, masked to 16 bits, lands on the wanted angle
    assert (65776 + delta[0]) & 65535 == _short(30.0)
    assert (65600 + delta[1]) & 65535 == _short(270.0)


def test_write_without_gameclient_is_noop(no_gc):
    assert mr.match_restore._write_player_view(SimpleNamespace(id=2), 30.0, 270.0) is False


def test_kinematics_row_with_angles_remembers_and_writes(gc):
    p = _plugin(
        _write_player_velocity=lambda *a: None,
        _remember_restore_velocity=lambda *a: None,
    )
    target = SimpleNamespace(id=2)
    ok, detail = p._apply_player_snapshot(
        target, {"cid": 2, "pa": 30.0, "ya": 270.0}, kinematics_only=True, velocity_only=True
    )
    assert ok and "view" in detail
    assert p._restore_pending_views == {2: (30.0, 270.0)}
    assert [j["client_id"] for j in p._view_apply_queue] == [2]
    assert gc.instances[2].ps.delta_angles[1] == _short(270.0) - 65600


def test_kinematics_row_without_angles_is_unchanged(gc):
    p = _plugin(
        _write_player_velocity=lambda *a: None,
        _remember_restore_velocity=lambda *a: None,
    )
    ok, detail = p._apply_player_snapshot(
        SimpleNamespace(id=2),
        {"cid": 2, "vx": 1, "vy": 2, "vz": 3},
        kinematics_only=True,
        velocity_only=True,
    )
    assert ok and detail == "vel"
    assert p._restore_pending_views == {} and p._view_apply_queue == []
    assert gc.instances == {}


def test_flush_reapplies_once_and_requeues(gc):
    p = _plugin(_restore_pending_views={3: (10.0, 90.0)})
    p._flush_restore_views()
    p._flush_restore_views()
    assert p._restore_pending_views == {}
    assert gc.instances[3].ps.delta_angles[0] == _short(10.0) - 65776
    assert len(p._view_apply_queue) == 1


def test_frame_queue_reapplies_then_expires(gc):
    p = _plugin(
        _enabled=lambda: True,
        _position_apply_queue=[],
        _velocity_apply_queue=[],
    )
    p._queue_player_view(5, 0.0, 180.0, frames=2)
    p._frame_apply_positions()
    assert len(p._view_apply_queue) == 1
    p._frame_apply_positions()
    assert p._view_apply_queue == []
    assert gc.instances[5].ps.delta_angles[1] == _short(180.0) - 65600


def test_codec_keeps_angles_and_old_rows_have_none():
    from restore import codec

    base = {"t_ms": 1000, "map": "campgrounds", "players": [
        {"cid": 0, "x": 1, "y": 2, "z": 3, "pa": 12.345, "ya": -90.0},
        {"cid": 1, "x": 1, "y": 2, "z": 3},
    ]}
    cp = codec.canonicalize(base)
    assert cp["players"][0]["pa"] == 12.35 and cp["players"][0]["ya"] == -90.0
    assert "pa" not in cp["players"][1]


def test_draft_view_field_reaches_the_checkpoint():
    from restore import draft as restore_draft

    tells = []
    p = _plugin(
        _restore_draft={"t_ms": 0, "map": "campgrounds", "players": {}, "items": []},
        _draft_tell=lambda player, channel, text, loud=False: tells.append(text),
    )
    p._cmd_restore_draft_player(None, None, ["0", "pos", "1", "2", "3"])
    p._cmd_restore_draft_player(None, None, ["0", "view", "12.345", "-90"])
    cp = restore_draft.draft_to_checkpoint(p._restore_draft)
    assert cp["players"][0]["pa"] == 12.35 and cp["players"][0]["ya"] == -90.0
    p._cmd_restore_draft_player(None, None, ["0", "view", "5"])
    assert "view needs pitch yaw" in tells[-1]


def test_state_phase_writes_view_when_pause_never_happens(gc):
    p = _plugin(
        _apply_player_vitals=lambda target, payload: True,
        _teleport_player=lambda *a, **k: True,
        _is_bot_player=lambda target: False,
    )
    ok, detail = p._apply_player_snapshot(
        SimpleNamespace(id=2),
        {"cid": 2, "x": 1, "y": 2, "z": 3, "pa": 30.0, "ya": 270.0},
        state_only=True,
    )
    assert ok and "view" in detail
    assert gc.instances[2].ps.delta_angles[1] == _short(270.0) - 65600
    assert p._restore_pending_views == {}
    assert [j["client_id"] for j in p._view_apply_queue] == [2]


def test_qlmatch_rows_carry_yaw_and_level_pitch():
    from restore import codec, qlmatch

    ev = {"players": [
        {"clientNum": 0, "x": 1, "y": 2, "z": 3, "yaw": -88.4},
        {"clientNum": 1, "x": 1, "y": 2, "z": 3, "yaw": 10, "pitch": 5.5},
        {"clientNum": 2, "x": 1, "y": 2, "z": 3},
        {"clientNum": 3, "x": 1, "y": 2, "z": 3, "yaw": "nan"},
    ]}
    rows = qlmatch.build_player_rows(ev)
    assert (rows[0]["ya"], rows[0]["pa"]) == (-88.4, 0.0)
    assert (rows[1]["ya"], rows[1]["pa"]) == (10.0, 5.5)
    assert "ya" not in rows[2] and "pa" not in rows[2]
    assert "ya" not in rows[3]
    cp = codec.canonicalize({"t_ms": 1, "map": "q4sun", "players": rows})
    assert cp["players"][0]["ya"] == -88.4 and cp["players"][0]["pa"] == 0.0
