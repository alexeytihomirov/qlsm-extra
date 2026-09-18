# match_restore_util.py — pause latch + map spawn table loader for match_restore.

# Shared pause detection for match restore (console pause latch).
#
# QL console `pause` / chat `!rcon pause` may not expose sv_paused to get_cvar().
# We combine cvar probes, minqlx game flags (when present), and explicit rcon
# pause/unpause commands observed via client_command.

_PAUSE_LATCH = False


def set_pause_latch(active):
    global _PAUSE_LATCH
    _PAUSE_LATCH = bool(active)


def pause_latch_active():
    return bool(_PAUSE_LATCH)


def _cvar_truthy(plugin, name):
    try:
        raw = plugin.get_cvar(name)
    except Exception:
        return False
    if raw is None:
        return False
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, (int, float)):
        return int(raw) != 0
    text = str(raw).strip().lower()
    return text not in ("0", "", "false", "off", "no")


def _game_paused(plugin):
    game = getattr(plugin, "game", None)
    if game is None:
        return False
    for attr in ("paused", "is_paused"):
        try:
            val = getattr(game, attr, None)
        except Exception:
            val = None
        if val is not None and bool(val):
            return True
    return False


def raw_paused(plugin):
    """Real engine/cvar signal only — bypasses the operator-intent latch.

    Useful as a positive signal when cvars flip. On Quake Live, console/
    ``!pause`` often leaves ``sv_paused`` at 0 even when freeze works — do
    **not** treat a False result alone as proof that pause failed. See
    ``accept_console_pause``."""
    return bool(
        any(_cvar_truthy(plugin, name) for name in ("sv_paused", "cl_paused", "g_paused"))
        or _game_paused(plugin)
    )


def accept_console_pause(raw_ok, match_state):
    """Whether console ``pause`` should be treated as successful after issue.

    ``raw_ok`` True → always accept. Warmup → reject (pause often a no-op for
    match freeze). Otherwise accept and latch intent: QL commonly keeps pause
    cvars at 0 while the match is actually frozen.
    """
    if raw_ok:
        return True
    if match_state == "warmup":
        return False
    return True


def paused_active(plugin):
    """Return True when the match should be treated as paused for restore."""
    global _PAUSE_LATCH
    if any(
        _cvar_truthy(plugin, name) for name in ("sv_paused", "cl_paused", "g_paused")
    ) or _game_paused(plugin):
        _PAUSE_LATCH = True
        return True
    # QL minqlx !pause often leaves sv_paused at 0 — keep explicit latch until !unpause.
    if _PAUSE_LATCH:
        return True
    return False


PAUSE_TEXT_CMD_PERM = 5


def _actor_allowed(plugin, player):
    """Console/RCON (player None) is trusted; players need perm>=5.

    Without this any client could flip the latch by typing "pause"/"unpause"
    in chat or as a raw client command the engine itself rejects."""
    if player is None:
        return True
    if plugin is None:
        return False
    try:
        return bool(plugin.db.has_permission(player, PAUSE_TEXT_CMD_PERM))
    except Exception:
        return False


def note_client_command(cmd, player=None, plugin=None):
    """Track explicit pause/unpause from chat !rcon or direct console lines.

    Pass the acting player and the calling plugin from client_command/chat
    hooks so unprivileged clients cannot spoof the latch (player=None means
    console/RCON and is trusted)."""
    text = str(cmd or "").strip()
    if not text:
        return
    lower = text.lower()
    if lower.startswith("say ") or lower.startswith("say_team "):
        parts = text.split(None, 1)
        if len(parts) < 2:
            return
        text = parts[1].strip().strip('"')
        lower = text.lower()
    if lower.startswith("!rcon "):
        text = text[6:].strip()
        lower = text.lower()
    if lower.startswith("!"):
        lower = lower[1:].lstrip()
    is_pause = lower == "pause" or lower.startswith("pause ")
    is_unpause = lower == "unpause" or lower.startswith("unpause ")
    if not (is_pause or is_unpause):
        return
    if not _actor_allowed(plugin, player):
        return
    set_pause_latch(bool(is_pause))


def reset_pause_state():
    set_pause_latch(False)


# ---------------------------------------------------------------------------
# Map spawn table (was map_spawns_loader.py)
# ---------------------------------------------------------------------------


import json
import os
import re

try:
    import minqlxtended as minqlx
except ImportError:
    try:
        import minqlx
    except ImportError:
        minqlx = None

ITEM_ALIASES = {
    "mega": "item_health_mega",
    "mh": "item_health_mega",
    "50": "item_health_large",
    "25": "item_health",
    "5": "item_health_small",
    "ya": "item_armor_combat",
    "ra": "item_armor_body",
    "ga": "item_armor_jacket",
    "shard": "item_armor_shard",
    "quad": "item_quad",
    "regen": "item_regen",
    "haste": "item_haste",
    "bs": "item_enviro",
    "invis": "item_invis",
    "invuln": "item_invulnerability",
    "rl": "weapon_rocketlauncher",
    "lg": "weapon_lightning",
    "rg": "weapon_railgun",
    "pg": "weapon_plasmagun",
    "gl": "weapon_grenadelauncher",
    "sg": "weapon_shotgun",
    "mg": "weapon_machinegun",
    "cg": "weapon_chaingun",
    "ng": "weapon_nailgun",
    "hmg": "weapon_hmg",
}

POWERUP_CLASSNAMES = frozenset(
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

_ALIAS_SKIP = frozenset({"mh"})


def normalize_map_key(name):
    text = str(name or "").strip().lower()
    if text.startswith("map-"):
        text = text[4:]
    return re.sub(r"[^a-z0-9]", "", text)


def _data_dir():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "map_entities")


def _is_restorable(classname):
    """Map pickups restorable via spawn table (weapons/armor/health/ammo/powerups)."""
    cn = str(classname or "").strip()
    if not cn:
        return False
    if cn == "ammo_pack":
        return False
    if cn in POWERUP_CLASSNAMES:
        return True
    if cn.startswith("item_") or cn.startswith("weapon_") or cn.startswith("ammo_"):
        return True
    return False


def _alias_for_classname(classname):
    for alias, cn in ITEM_ALIASES.items():
        if alias in _ALIAS_SKIP:
            continue
        if cn == classname:
            return alias
    return None


def _native_map_entities(map_name):
    """Live entity lump via minqlxtended.map_entities(); None if unavailable/failed.

    Native entities carry no persistent id (BSP has none) — the enumerate index
    below is only a stable per-load slot key, not a re-derivation of the old
    bundled JSON's "id" field.
    """
    if minqlx is None or not hasattr(minqlx, "map_entities"):
        return None
    name = str(map_name or "").strip()
    if not name:
        return None
    try:
        raw_entities = minqlx.map_entities(name)
    except Exception:
        return None
    if not isinstance(raw_entities, list):
        return None
    rows = []
    for idx, ent in enumerate(raw_entities):
        classname = getattr(ent, "classname", None)
        origin = getattr(ent, "origin", None)
        if not classname or not origin:
            continue
        try:
            x, y, z = origin
        except (TypeError, ValueError):
            continue
        rows.append({"id": idx, "classname": classname, "x": x, "y": y, "z": z})
    return rows


def load_map_spawns(map_key, raw_map_name=None):
    """Return {alias: {entity_id, x, y, z, classname}} for restorable spawns.

    Reads live from minqlxtended.map_entities() (BSP entity lump) when the
    native build exposes it; falls back to the bundled
    data/map_entities/<map>.json snapshot otherwise.
    """
    key = normalize_map_key(map_key)
    if not key:
        return {}
    entities = _native_map_entities(raw_map_name if raw_map_name else map_key)
    if entities is None:
        path = os.path.join(_data_dir(), key + ".json")
        if not os.path.isfile(path):
            return {}
        try:
            with open(path, encoding="utf-8") as handle:
                raw = json.load(handle)
        except (OSError, json.JSONDecodeError):
            return {}
        entities = raw.get("entities") if isinstance(raw, dict) else raw
        if not isinstance(entities, list):
            return {}
    restorable = []
    by_class = {}
    for row in entities:
        if not isinstance(row, dict):
            continue
        cn = str(row.get("classname") or "").strip()
        if not _is_restorable(cn):
            continue
        try:
            ent_id = int(row.get("id"))
        except (TypeError, ValueError):
            continue
        restorable.append((ent_id, cn, row))
        by_class.setdefault(cn, []).append(ent_id)
    table = {}
    for ent_id, cn, row in restorable:
        # Spawn table for restore uses short ITEM_ALIASES when classname is unique,
        # else e{id}. Ignore map-entity auto aliases (target_location) here — those
        # are for annotated maps / editor, not cfg restore tokens.
        if len(by_class.get(cn) or []) == 1:
            alias = _alias_for_classname(cn) or "e{}".format(ent_id)
        else:
            alias = "e{}".format(ent_id)
        if alias in table:
            alias = "e{}".format(ent_id)
        table[alias] = {
            "entity_id": ent_id,
            "x": float(row.get("x", 0)),
            "y": float(row.get("y", 0)),
            "z": float(row.get("z", 0)),
            "classname": cn,
        }
    return table
