# restore/codec.py — checkpoint helpers for draft/cfg restore.
# No binary blob / paste / fetch transport.

import re
import zlib

CHECKPOINT_VERSION = 2

AMMO_KEYS = ("rl", "lg", "rg", "pg", "gl", "sg", "mg", "cg")

# Items a player drops on death (the weapon they were holding, powerups) are
# separate entities from the map spawns the sparse `items` rows address: the
# engine's LaunchItem() spawns them with FL_DROPPED_ITEM and frees them again
# DROP_LIFETIME_MS later (baseq3 g_items.c, unchanged in QL). They live in
# their own `drops` list — a map spawn slot is identified by its spawn point,
# a drop only by where it happens to be lying.
DROP_LIFETIME_MS = 30000
# A drop with less left than this is not worth recreating: it would blink out
# again before the match is even unpaused.
DROP_MIN_TTL_MS = 250

# bg_itemlist index -> classname, 1-based (0 is the null item). Same table the
# demo side uses as QL91_ITEM_CLASSNAMES (qlmatch-packer constants.js), and
# the same number spawn_item()/drop_item() take and entityState.modelindex
# carries for an ET_ITEM - which is why a drop can travel from a demo to a
# live server as a bare integer.
BG_ITEM_CLASSNAMES = {
    1: "item_armor_shard",
    2: "item_armor_combat",
    3: "item_armor_body",
    4: "item_armor_jacket",
    5: "item_health_small",
    6: "item_health",
    7: "item_health_large",
    8: "item_health_mega",
    9: "weapon_gauntlet",
    10: "weapon_shotgun",
    11: "weapon_machinegun",
    12: "weapon_grenadelauncher",
    13: "weapon_rocketlauncher",
    14: "weapon_lightning",
    15: "weapon_railgun",
    16: "weapon_plasmagun",
    17: "weapon_bfg",
    18: "weapon_grapplinghook",
    19: "ammo_shells",
    20: "ammo_bullets",
    21: "ammo_grenades",
    22: "ammo_cells",
    23: "ammo_lightning",
    24: "ammo_rockets",
    25: "ammo_slugs",
    26: "ammo_bfg",
    27: "holdable_teleporter",
    28: "holdable_medkit",
    29: "item_quad",
    30: "item_enviro",
    31: "item_haste",
    32: "item_invis",
    33: "item_regen",
    34: "item_flight",
    35: "team_CTF_redflag",
    36: "team_CTF_blueflag",
    37: "holdable_kamikaze",
    38: "holdable_portal",
    39: "holdable_invulnerability",
    40: "ammo_nails",
    41: "ammo_mines",
    42: "ammo_belt",
    43: "item_scout",
    44: "item_guard",
    45: "item_doubler",
    46: "item_armorregen",
    47: "team_CTF_neutralflag",
    48: "item_redcube",
    49: "item_bluecube",
    50: "weapon_nailgun",
    51: "weapon_prox_launcher",
    52: "weapon_chaingun",
    53: "item_spawnarmor",
    54: "weapon_hmg",
    55: "ammo_hmg",
    56: "ammo_pack",
    57: "item_key_silver",
    58: "item_key_gold",
    59: "item_key_master",
}

# Player-held powerup remaining time (seconds). Keys are cfg aliases.
POWERUP_KEYS = ("quad", "regen", "bs", "haste", "invis", "invuln")
POWERUP_ALIAS = {
    "quad": "quad",
    "regen": "regen",
    "regeneration": "regen",
    "bs": "bs",
    "battlesuit": "bs",
    "battle": "bs",
    "enviro": "bs",
    "haste": "haste",
    "invis": "invis",
    "invisibility": "invis",
    "invuln": "invuln",
    "invulnerability": "invuln",
}
# minqlxtended Player.powerups property field names (v1.0.0: read/write property, not a method)
POWERUP_MINQLX = {
    "quad": "quad",
    "regen": "regeneration",
    "bs": "battlesuit",
    "haste": "haste",
    "invis": "invisibility",
    "invuln": "invulnerability",
}

WEAPON_ORDER = (
    "g", "mg", "sg", "gl", "rl", "lg", "rg", "pg",
    "bfg", "gh", "ng", "pl", "cg", "hmg", "hands",
)

COORD_DECIMALS = 1


def normalize_map_key(name):
    text = str(name or "").strip().lower()
    if text.startswith("map-"):
        text = text[4:]
    return re.sub(r"[^a-z0-9]", "", text)


def map_crc32(map_key):
    key = normalize_map_key(map_key)
    if not key:
        return 0
    return zlib.crc32(key.encode("utf-8")) & 0xFFFFFFFF


def loadout_to_mask(loadout):
    if loadout is None:
        return 0
    if isinstance(loadout, int):
        return int(loadout) & 0xFFFF
    if not isinstance(loadout, dict):
        return 0
    mask = 0
    for idx, key in enumerate(WEAPON_ORDER):
        if loadout.get(key):
            mask |= 1 << (idx + 1)
    return mask & 0xFFFF


def mask_to_loadout(mask):
    out = {}
    m = int(mask) & 0xFFFF
    for idx, key in enumerate(WEAPON_ORDER):
        if m & (1 << (idx + 1)):
            out[key] = 1
    return out


def weapon_key_bit(key):
    """Loadout bit for weapon key (g/mg/…); None if unknown."""
    key = str(key or "").strip().lower()
    if key not in WEAPON_ORDER or key == "hands":
        return None
    return 1 << (WEAPON_ORDER.index(key) + 1)


def mask_weapon_keys(mask):
    """Owned weapon keys from loadout mask (excludes hands)."""
    out = []
    m = int(mask or 0) & 0xFFFF
    for idx, key in enumerate(WEAPON_ORDER):
        if key == "hands":
            continue
        if m & (1 << (idx + 1)):
            out.append(key)
    return out


def normalize_powerups(raw):
    """Return {alias: remaining_seconds} for known powerups; drop zeros.

    `pw` values are always whole seconds, never milliseconds -- match_restore.py's
    `_export_powerups` converts `Player.powerups` (ms) down to seconds before this
    ever sees it, and `_apply_powerups` converts back up (`sec * 1000`) on apply.
    """
    if not isinstance(raw, dict):
        return {}
    out = {}
    for key, val in raw.items():
        alias = POWERUP_ALIAS.get(str(key).strip().lower())
        if not alias:
            continue
        try:
            sec = int(val)
        except (TypeError, ValueError):
            continue
        if sec > 0:
            out[alias] = sec
    return out


def repair_telemetry_loadout_mask(mask):
    """Shift old 1<<idx masks (bit0 set) to 1<<(idx+1)."""
    m = int(mask) & 0xFFFF
    if m & 1:
        return (m << 1) & 0xFFFF
    return m


def ensure_active_weapon_in_loadout(lo, weapon_w):
    if weapon_w is None:
        return int(lo) & 0xFFFF
    try:
        w = int(weapon_w)
    except (TypeError, ValueError):
        return int(lo) & 0xFFFF
    if 1 <= w <= 14:
        return (int(lo) | (1 << w)) & 0xFFFF
    return int(lo) & 0xFFFF


def normalize_loadout_mask(lo, weapon_w=None):
    m = repair_telemetry_loadout_mask(int(lo or 0))
    return ensure_active_weapon_in_loadout(m, weapon_w)


def _coord_val(value):
    return round(float(value), COORD_DECIMALS)


def _item_row_eid(row):
    if row.get("eid") is not None:
        try:
            return int(row["eid"])
        except (TypeError, ValueError):
            pass
    key = str(row.get("k", row.get("key", row.get("alias", "")))).strip().lower()
    if key.startswith("e") and key[1:].isdigit():
        return int(key[1:])
    return None


def canonicalize_drop_row(row):
    """One `drops` row, or None when it can't address a real item.

    `i` is the bg_itemlist index — the same number spawn_item()/drop_item()
    take and the same number the wire carries in entityState.modelindex for an
    ET_ITEM, so it survives the demo path without a classname table. `cn` is
    carried along only so a hand-edited checkpoint stays readable.
    """
    if not isinstance(row, dict):
        return None
    try:
        idx = int(row.get("i", row.get("item_id", 0)) or 0)
    except (TypeError, ValueError):
        return None
    if idx <= 0:
        return None
    try:
        out = {
            "i": idx,
            "x": _coord_val(row["x"]),
            "y": _coord_val(row["y"]),
            "z": _coord_val(row["z"]),
        }
    except (KeyError, TypeError, ValueError):
        return None
    try:
        ttl = int(row.get("ttl", row.get("ttl_ms", DROP_LIFETIME_MS)))
    except (TypeError, ValueError):
        ttl = DROP_LIFETIME_MS
    ttl = max(0, min(DROP_LIFETIME_MS, ttl))
    if ttl < DROP_MIN_TTL_MS:
        return None
    out["ttl"] = ttl
    cn = str(row.get("cn") or "").strip()
    if cn:
        out["cn"] = cn
    return out


def canonicalize(doc):
    if not isinstance(doc, dict):
        raise ValueError("checkpoint must be object")
    ver = int(doc.get("v", doc.get("version", CHECKPOINT_VERSION)) or CHECKPOINT_VERSION)
    if ver != CHECKPOINT_VERSION:
        raise ValueError("unsupported checkpoint version: {} (need {})".format(ver, CHECKPOINT_VERSION))
    out = {
        "v": CHECKPOINT_VERSION,
        "t_ms": int(doc.get("t_ms", doc.get("game_time_ms", 0)) or 0),
        "map": normalize_map_key(doc.get("map", doc.get("map_name", ""))),
        "players": [],
        "items": [],
    }
    for row in doc.get("players") or []:
        if not isinstance(row, dict):
            continue
        p = {
            "cid": int(row.get("cid", row.get("client_id", 0))),
            "x": _coord_val(row["x"]),
            "y": _coord_val(row["y"]),
            "z": _coord_val(row["z"]),
            "h": int(row.get("h", row.get("health", 0)) or 0),
            "a": int(row.get("a", row.get("armor", 0)) or 0),
            "w": int(row.get("w", row.get("weapon", 0)) or 0),
            "lo": loadout_to_mask(row.get("lo", row.get("loadout"))),
        }
        sid = row.get("sid", row.get("steam_id64"))
        if sid:
            p["sid"] = str(sid).strip()
        nick = row.get("nick", row.get("nickname", row.get("name")))
        if nick:
            p["nick"] = str(nick)
        for axis in ("vx", "vy", "vz"):
            if row.get(axis) is not None:
                p[axis] = int(round(float(row[axis])))
        am = row.get("am", row.get("ammo"))
        if isinstance(am, dict) and am:
            p["am"] = {k: int(am[k]) for k in AMMO_KEYS if k in am}
        sc = row.get("sc", row.get("score"))
        if sc is not None:
            p["sc"] = int(sc)
        pw = normalize_powerups(row.get("pw", row.get("powerups")))
        if pw:
            p["pw"] = pw
        if row.get("dead") in (1, True, "1") or row.get("alive") is False:
            p["dead"] = 1
            # Ms left on playerState_t.respawnTime at export time (engine level.time
            # clock, not the checkpoint's own t_ms) - lets restore re-arm the real
            # respawn deadline instead of the fresh delay is_alive=False's real
            # slay_with_mod() starts counting from the restore moment.
            ri = row.get("ri")
            if ri is not None:
                try:
                    p["ri"] = max(0, int(ri))
                except (TypeError, ValueError):
                    pass
        if row.get("bot"):
            p["bot"] = 1
        out["players"].append(p)
    for row in doc.get("items") or []:
        if not isinstance(row, dict):
            continue
        state = int(row.get("s", row.get("state", 1)) or 0)
        if state == 1:
            continue
        eid = _item_row_eid(row)
        item = {"s": state}
        if eid is not None:
            item["eid"] = int(eid)
        key = str(row.get("k", row.get("key", row.get("alias", "")))).strip().lower()
        if key:
            item["k"] = key
        cn = str(row.get("cn") or "").strip()
        has_pos = all(row.get(axis) is not None for axis in ("x", "y", "z"))
        if not item.get("eid") and not item.get("k"):
            if not (
                cn
                and (cn.startswith("item_") or cn.startswith("weapon_"))
                and has_pos
            ):
                continue
        if item["s"] == 2 and row.get("in") is not None:
            item["in"] = float(row["in"])
        if item["s"] == 2 and row.get("at_ms") is not None:
            try:
                item["at_ms"] = int(row["at_ms"])
            except (TypeError, ValueError):
                pass
        if cn:
            item["cn"] = cn
        for axis in ("x", "y", "z"):
            if row.get(axis) is not None:
                try:
                    item[axis] = round(float(row[axis]), 1)
                except (TypeError, ValueError):
                    pass
        out["items"].append(item)
    # The key is kept only when the source doc had one at all: an empty list
    # means "this checkpoint knows there were no drops" (clear the floor),
    # while no key at all means "written before drops existed" (leave it
    # alone). Every pre-existing checkpoint therefore canonicalizes exactly
    # as it did before.
    raw_drops = doc.get("drops")
    if raw_drops is not None:
        drops = []
        for row in raw_drops:
            drop = canonicalize_drop_row(row)
            if drop is not None:
                drops.append(drop)
        out["drops"] = drops
    return out