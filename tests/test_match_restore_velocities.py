"""match_restore applies checkpoint velocities once: the pending map is consumed
by the flush and forgotten on abort."""
import logging
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _minqlx_stub import import_plugin, bare_instance

pytestmark = pytest.mark.standalone

mr = import_plugin("match_restore")


def _plugin(pending):
    writes = []
    p = bare_instance(
        mr.match_restore,
        _restore_pending_velocities=pending,
        player=lambda cid: SimpleNamespace(id=cid),
        _write_player_velocity=lambda target, vx, vy, vz: writes.append((target.id, vx, vy, vz)),
        _queue_player_velocity=lambda cid, vx, vy, vz, frames=5: None,
        logger=logging.getLogger("test"),
    )
    return p, writes


def test_flush_applies_pending_velocities_once():
    p, writes = _plugin({3: (100.0, 0.0, 270.0)})
    p._flush_restore_velocities()
    p._flush_restore_velocities()
    assert writes == [(3, 100.0, 0.0, 270.0)]
    assert p._restore_pending_velocities == {}


def test_abort_forgets_pending_velocities():
    p, _ = _plugin({3: (100.0, 0.0, 270.0)})
    p._restore_hold_until_unpause = True
    p._awaiting_unfreeze_after_unpause = True
    p._unfreeze_thaw_token = 0
    p._unfreeze_thaw_at_wall = 1.0
    p._end_restore_session = lambda: None
    p._abort_restore_session("test")
    assert p._restore_pending_velocities == {}
