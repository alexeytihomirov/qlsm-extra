# restore/items.py — pure export/restore item planning (unit-testable).

from __future__ import annotations


_POWERUP_CLASSNAMES = frozenset(
    {
        "item_quad",
        "item_regen",
        "item_haste",
        "item_enviro",
        "item_invis",
        "item_invisibility",
        "item_invulnerability",
        "item_flight",
    }
)


def vanilla_respawn_sec(classname: str, map_key: str = "") -> float:
    name = str(classname or "")
    if name.startswith("weapon_"):
        return 5.0
    if name == "item_health_mega":
        return 120.0 if map_key == "proq3tourney4" else 35.0
    if name.startswith("item_armor"):
        return 25.0
    if name.startswith("ammo_"):
        return 40.0
    if name in _POWERUP_CLASSNAMES:
        return 120.0
    if name.startswith("item_health"):
        return 35.0
    if name.startswith("item_"):
        return 120.0
    return 35.0


def export_item_row(
    alias: str,
    meta: dict,
    now_ms: int,
    *,
    wall_now: float,
    bundled_pickup: dict | None = None,
    map_key: str = "",
) -> dict:
    """Build one items[] checkpoint row. Untouched visible items default to s:1 (never s:0)."""
    classname = meta.get("classname") or alias
    respawn_sec = vanilla_respawn_sec(classname, map_key)

    if bundled_pickup:
        respawn_sec = float(bundled_pickup.get("respawn_sec") or respawn_sec)
        remain_sec = None
        visible_at_ms = None
        pickup_ms = int(bundled_pickup.get("pickup_ms", 0) or 0)
        if pickup_ms > 0:
            visible_at_ms = int(pickup_ms + respawn_sec * 1000)
            if visible_at_ms > now_ms:
                remain_sec = (visible_at_ms - now_ms) / 1000.0
        if remain_sec is None and now_ms > 0 and pickup_ms > 0:
            elapsed_ms = max(0, now_ms - pickup_ms)
            remain_ms = int(respawn_sec * 1000) - elapsed_ms
            if remain_ms > 50:
                remain_sec = remain_ms / 1000.0
                visible_at_ms = int(now_ms + remain_ms)
        if remain_sec is not None and remain_sec > 0.05:
            row = {"k": alias, "s": 2, "in": round(remain_sec, 2)}
            if visible_at_ms is not None:
                row["at_ms"] = int(visible_at_ms)
            return row

    return {"k": alias, "s": 1}


def plan_item_visible_at_ms(item: dict, checkpoint_t_ms: int) -> int | None:
    """Absolute match ms when a restored item should spawn (None = hide only)."""
    state = int(item.get("s", 1))
    now_ms = max(0, int(checkpoint_t_ms or 0))
    if state == 0:
        return None
    if state == 1:
        return now_ms
    if state != 2:
        return None
    in_sec = float(item.get("in", 0) or 0)
    visible_at_ms = None
    if item.get("at_ms") is not None:
        try:
            visible_at_ms = int(item["at_ms"])
        except (TypeError, ValueError):
            visible_at_ms = None
    if visible_at_ms is None and in_sec > 0:
        visible_at_ms = int(now_ms + in_sec * 1000)
    if visible_at_ms is None:
        return None
    if visible_at_ms <= now_ms:
        return now_ms
    return visible_at_ms
