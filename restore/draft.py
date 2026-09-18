# restore/draft.py — accumulate checkpoint from qlx restore subcommands.

from __future__ import annotations

import re

try:
    from restore.codec import AMMO_KEYS, canonicalize
except ImportError:
    from .codec import AMMO_KEYS, canonicalize

_COLOR_RE = re.compile(r"\^[0-9a-zA-Z]")

DRAFT_SUBCOMMANDS = frozenset(
    {
        "quiet",
        "loud",
        "clear",
        "time",
        "map",
        "player",
        "item",
        "apply",
        "verify",
        "show",
        "players",
    }
)


def empty_draft():
    return {"v": 2, "t_ms": 0, "map": "", "players": {}, "items": []}


def ensure_player_row(draft, slot):
    slot = int(slot)
    players = draft.setdefault("players", {})
    row = players.get(slot)
    if not isinstance(row, dict):
        row = {"cid": slot}
        players[slot] = row
    else:
        row["cid"] = slot
    return row


def draft_to_checkpoint(draft):
    players_raw = draft.get("players") or {}
    if isinstance(players_raw, dict):
        ordered = [players_raw[k] for k in sorted(players_raw.keys(), key=lambda x: int(x))]
    else:
        ordered = list(players_raw)
    doc = {
        "v": 2,
        "t_ms": int(draft.get("t_ms") or 0),
        "map": str(draft.get("map") or ""),
        "players": ordered,
        "items": list(draft.get("items") or []),
    }
    return canonicalize(doc)


def parse_slot_remap_tokens(tokens):
    """Parse 0:3 1:2 → {0: 3, 1: 2}."""
    out = {}
    for raw in tokens or []:
        text = str(raw).strip()
        if not text:
            continue
        if ":" not in text:
            raise ValueError("slot remap must be slot:client_id (e.g. 0:3)")
        left, right = text.split(":", 1)
        if not left.isdigit() or not right.isdigit():
            raise ValueError("slot remap must be digits: {}".format(text))
        out[int(left)] = int(right)
    return out


def format_slot_remap(remap):
    if not remap:
        return "(none)"
    parts = ["{}:{}".format(k, remap[k]) for k in sorted(remap.keys())]
    return " ".join(parts)


def strip_name(text):
    return _COLOR_RE.sub("", str(text or "")).strip()


def names_match(want, have):
    a = strip_name(want).lower()
    b = strip_name(have).lower()
    return bool(a) and a == b


def append_item(draft, item):
    items = draft.setdefault("items", [])
    eid = item.get("eid")
    if eid is not None:
        items[:] = [row for row in items if int(row.get("eid", -1)) != int(eid)]
    else:
        cn = str(item.get("cn") or "").strip().lower()
        pos = (
            round(float(item["x"]), 1),
            round(float(item["y"]), 1),
            round(float(item["z"]), 1),
        ) if all(item.get(axis) is not None for axis in ("x", "y", "z")) else None
        if cn and pos is not None:
            items[:] = [
                row
                for row in items
                if not (
                    str(row.get("cn") or "").strip().lower() == cn
                    and all(row.get(axis) is not None for axis in ("x", "y", "z"))
                    and (
                        round(float(row["x"]), 1),
                        round(float(row["y"]), 1),
                        round(float(row["z"]), 1),
                    )
                    == pos
                )
            ]
        else:
            key = str(item.get("k") or "").strip().lower()
            if key:
                items[:] = [row for row in items if str(row.get("k") or "").lower() != key]
    items.append(item)


def parse_item_pending_tail(item, tail, t_ms, parse_time_arg=None):
    state = str(tail[0]).strip().lower()
    if state in ("hidden", "hide", "0"):
        item["s"] = 0
        return item
    if state not in ("pending", "2", "respawn"):
        raise ValueError("state must be pending or hidden")
    item["s"] = 2
    if len(tail) >= 2 and str(tail[1]).strip().lower() == "at":
        if len(tail) < 3:
            raise ValueError("pending at needs ms")
        item["at_ms"] = int(tail[2])
    elif len(tail) >= 2 and str(tail[1]).strip().lower() == "in":
        if len(tail) < 3:
            raise ValueError("pending in needs seconds")
        sec = float(tail[2])
        item["in"] = sec
        item["at_ms"] = int(t_ms + sec * 1000)
    elif len(tail) >= 2:
        if parse_time_arg is None:
            raise ValueError("pending needs at_ms or in sec")
        item["at_ms"] = int(parse_time_arg(tail[1:]))
    else:
        raise ValueError("pending needs at_ms or in sec")
    return item


def parse_item_draft_line(tokens, t_ms, resolve_alias=None, find_spawn=None, parse_time_arg=None):
    """Parse restore item tail: classname [pos x y z] pending at_ms | hidden."""
    tokens = [str(t) for t in (tokens or [])]
    if len(tokens) < 2:
        raise ValueError("item line too short")
    idx = 0
    item = {}
    head_lc = tokens[idx].strip().lower()
    if head_lc.startswith("item_") or head_lc.startswith("weapon_"):
        item["cn"] = head_lc
        idx += 1
        if idx < len(tokens) and tokens[idx].lower() == "pos":
            if idx + 3 >= len(tokens):
                raise ValueError("item pos needs x y z")
            item["x"] = round(float(tokens[idx + 1]), 1)
            item["y"] = round(float(tokens[idx + 2]), 1)
            item["z"] = round(float(tokens[idx + 3]), 1)
            idx += 4
        if (
            find_spawn
            and item.get("cn")
            and None not in (item.get("x"), item.get("y"), item.get("z"))
        ):
            found_alias, found_meta = find_spawn(
                item["cn"], item["x"], item["y"], item["z"]
            )
            if found_meta:
                if found_alias:
                    item["k"] = found_alias
                try:
                    item["eid"] = int(found_meta.get("entity_id"))
                except (TypeError, ValueError):
                    pass
    else:
        if resolve_alias is None:
            raise ValueError("unknown item token {}".format(tokens[idx]))
        eid, alias = resolve_alias(tokens[idx])
        item["eid"] = int(eid)
        item["k"] = alias
        idx = 1
    if idx >= len(tokens):
        raise ValueError("item state missing")
    return parse_item_pending_tail(item, tokens[idx:], int(t_ms), parse_time_arg=parse_time_arg)


def compare_checkpoints(expected, actual, *, coord_eps=0.15):
    """Return list of human-readable diffs (empty = OK)."""
    diffs = []
    exp_t = int(expected.get("t_ms") or 0)
    act_t = int(actual.get("t_ms") or 0)
    if exp_t != act_t:
        diffs.append("t_ms expected {} got {}".format(exp_t, act_t))

    exp_map = str(expected.get("map") or "")
    act_map = str(actual.get("map") or "")
    if exp_map and act_map and exp_map != act_map:
        diffs.append("map expected {} got {}".format(exp_map, act_map))

    exp_players = sorted(
        expected.get("players") or [],
        key=lambda r: int(r.get("cid", 0)),
    )
    act_players = sorted(
        actual.get("players") or [],
        key=lambda r: int(r.get("cid", 0)),
    )
    if len(exp_players) != len(act_players):
        diffs.append("players count expected {} got {}".format(len(exp_players), len(act_players)))
    for idx, exp_row in enumerate(exp_players):
        if idx >= len(act_players):
            break
        act_row = act_players[idx]
        slot = exp_row.get("cid", idx)
        prefix = "player slot {}".format(slot)
        for axis in ("x", "y", "z"):
            if axis not in exp_row:
                continue
            try:
                ev = float(exp_row[axis])
                av = float(act_row.get(axis, 0))
            except (TypeError, ValueError):
                continue
            if abs(ev - av) > coord_eps:
                diffs.append("{} {} expected {:.1f} got {:.1f}".format(prefix, axis, ev, av))
        for key in ("h", "a", "w", "sc"):
            if key not in exp_row:
                continue
            if int(exp_row.get(key, 0) or 0) != int(act_row.get(key, 0) or 0):
                diffs.append(
                    "{} {} expected {} got {}".format(
                        prefix, key, exp_row.get(key), act_row.get(key)
                    )
                )
        exp_am = exp_row.get("am") if isinstance(exp_row.get("am"), dict) else {}
        act_am = act_row.get("am") if isinstance(act_row.get("am"), dict) else {}
        for ak in AMMO_KEYS:
            if ak not in exp_am:
                continue
            if int(exp_am.get(ak, 0) or 0) != int(act_am.get(ak, 0) or 0):
                diffs.append(
                    "{} ammo.{} expected {} got {}".format(prefix, ak, exp_am.get(ak), act_am.get(ak))
                )
        exp_pw = exp_row.get("pw") if isinstance(exp_row.get("pw"), dict) else {}
        act_pw = act_row.get("pw") if isinstance(act_row.get("pw"), dict) else {}
        for pk in sorted(set(exp_pw) | set(act_pw)):
            if int(exp_pw.get(pk, 0) or 0) != int(act_pw.get(pk, 0) or 0):
                diffs.append(
                    "{} powerup.{} expected {} got {}".format(
                        prefix, pk, exp_pw.get(pk), act_pw.get(pk)
                    )
                )

    exp_items = {
        int(r.get("eid") or 0): r
        for r in (expected.get("items") or [])
        if r.get("eid") is not None
    }
    act_items = {
        int(r.get("eid") or 0): r
        for r in (actual.get("items") or [])
        if r.get("eid") is not None
    }
    for eid, exp_item in exp_items.items():
        act_item = act_items.get(eid)
        if not act_item:
            diffs.append("item e{} missing in live export".format(eid))
            continue
        if int(exp_item.get("s", 1)) != int(act_item.get("s", 1)):
            diffs.append(
                "item e{} state expected {} got {}".format(
                    eid, exp_item.get("s"), act_item.get("s")
                )
            )
        if int(exp_item.get("s", 1)) == 2:
            exp_at = exp_item.get("at_ms")
            act_at = act_item.get("at_ms")
            if exp_at is not None and act_at is not None and int(exp_at) != int(act_at):
                diffs.append(
                    "item e{} at_ms expected {} got {}".format(eid, exp_at, act_at)
                )

    # Drops are anonymous - no eid to pair on, since the restored one is a
    # brand new entity - so they only match on item + where it is lying.
    # Skipped entirely for a checkpoint with no `drops` key at all (a typed
    # draft, or one written before drops existed): it never claimed anything
    # about the floor, so whatever is lying there is not a diff.
    if expected.get("drops") is not None:
        exp_drops = _drop_keys(expected)
        act_drops = _drop_keys(actual)
        for key in sorted(exp_drops - act_drops):
            diffs.append("drop {} missing in live export".format(_drop_label(key)))
        for key in sorted(act_drops - exp_drops):
            diffs.append("drop {} on floor but not in checkpoint".format(_drop_label(key)))
    return diffs


# Drops land where the engine's own bounce math puts them, so a restored drop
# sits within a unit or so of the recorded spot, not exactly on it.
DROP_MATCH_GRID = 8.0


def _drop_keys(doc):
    keys = set()
    for row in (doc.get("drops") or []):
        try:
            keys.add(
                (
                    int(row.get("i") or 0),
                    round(float(row["x"]) / DROP_MATCH_GRID),
                    round(float(row["y"]) / DROP_MATCH_GRID),
                    round(float(row["z"]) / DROP_MATCH_GRID),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return keys


def _drop_label(key):
    idx, gx, gy, gz = key
    return "item {} at {:.0f},{:.0f},{:.0f}".format(
        idx, gx * DROP_MATCH_GRID, gy * DROP_MATCH_GRID, gz * DROP_MATCH_GRID
    )
