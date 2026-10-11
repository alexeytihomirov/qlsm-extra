"""match_restore item export: a taken item exports its real pickup time, so a
checkpoint carries the pending respawn timer instead of marking it available."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from restore.items import export_item_row, note_item_pickup
from _minqlx_stub import import_plugin, bare_instance

pytestmark = pytest.mark.standalone

mr = import_plugin("match_restore")

MEGA = {"classname": "item_health_mega", "entity_id": 7}


def test_taken_item_exports_its_remaining_respawn_time():
    row = export_item_row("mega", MEGA, 20_000, wall_now=0.0, bundled_pickup={"pickup_ms": 10_000})
    assert row == {"k": "mega", "s": 2, "in": 25.0, "at_ms": 45_000}


def test_item_already_respawned_exports_as_available():
    assert export_item_row("mega", MEGA, 50_000, wall_now=0.0, bundled_pickup={"pickup_ms": 10_000}) == {"k": "mega", "s": 1}


def test_note_item_pickup_keeps_the_latest_pickup_per_slot():
    pickups = {}
    note_item_pickup(pickups, 7, 10_000)
    note_item_pickup(pickups, 7, 30_000)
    note_item_pickup(pickups, 9, 12_000)
    assert pickups == {7: {"pickup_ms": 30_000}, 9: {"pickup_ms": 12_000}}


def test_pickup_at_match_time_zero_is_forgotten():
    pickups = {7: {"pickup_ms": 30_000}}
    note_item_pickup(pickups, 7, 0)
    assert pickups == {}


def _plugin(**attrs):
    base = dict(
        _item_pickups={}, _itemlab_engine_runtime_ids=set(), _runtime_entity_by_alias={},
        _restore_apply_active=False, _restore_session_active=False,
        _enabled=lambda: True, _track_slot_runtime_id=lambda table_id, eid: None,
        _spawn_meta_for_entity=lambda eid, cn, x, y, z: ("mega", dict(MEGA)),
        _export_match_time_ms=lambda: 10_000, _map_key=lambda: "bloodrun",
    )
    base.update(attrs)
    return bare_instance(mr.match_restore, **base)


def test_on_item_event_records_the_match_clock_of_a_pickup():
    p = _plugin()
    p.on_item_event("pickup", 312, object(), "item_health_mega")
    assert p._item_pickups == {7: {"pickup_ms": 10_000}}


def test_on_item_event_ignores_pickups_during_a_restore_session():
    p = _plugin(_restore_session_active=True)
    p.on_item_event("pickup", 312, object(), "item_health_mega")
    assert p._item_pickups == {}


def test_export_item_row_uses_the_tracked_pickup():
    p = _plugin(_item_pickups={7: {"pickup_ms": 10_000}})
    assert p._export_item_row("mega", dict(MEGA), 20_000) == {"k": "mega", "s": 2, "in": 25.0, "at_ms": 45_000}


def test_reset_restore_runtime_cache_forgets_pickups():
    p = _plugin(_item_pickups={7: {"pickup_ms": 10_000}}, _slot_runtime_ids={})
    p._reset_restore_runtime_cache()
    assert p._item_pickups == {}
