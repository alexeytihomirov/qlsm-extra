# match_restore.py — checkpoint restore (cfg draft).
#
# In default qlx_plugins (baseq3/server1.cfg) as of 2026-07-17.
#
# Checkpoint delivery is cfg-style only (client exec: !restore …; RCON: qlx restore …).
# Cfg draft lines only (no binary blob / paste / fetch transport).
#
# Commands (perm 5):
#   !restore clear|time|map|player|item|apply|verify|show — cfg-style draft
#   !restore players [0:3 1:2|clear] — slot→client_id remap (survives clear)
#   !restore export — current state as checkpoint JSON (summary tell, JSON to log)
#   !restore test [bloodrun_lab_35s|bloodrun_lab_21s] — bundled lab checkpoint (JSON)
#   Items: touch + vanilla nextthink (game clock). touch_map_item resets entity;
#       set_item_respawn_delay only bumps nextthink (no hide/show). Legacy wall-clock
#       show if set_item_respawn_delay missing.
#
# Lab/debug commands (!spawnsec, !itemlab, !matchtime, !restoreplayer) live in the
# optional match_restore_lab.py plugin (gated by qlx_matchRestoreLabEnabled), which
# reaches back into this plugin via self.plugins["match_restore"] for the shared
# item-runtime cache (_runtime_entity_by_alias/_slot_runtime_ids/_itemlab_engine_runtime_ids)
# and player-apply engine (_apply_player_snapshot, clock helpers, etc).
#
# pause/unpause text commands drive the match clock only when issued by perm>=5
# (or console/RCON); real sv_paused transitions are tracked via the frame poll.
# View angles not required for cfg restore.

import json
import os
import re
import time

try:
    from restore import draft as restore_draft
    from restore.codec import (
        AMMO_KEYS,
        BG_ITEM_CLASSNAMES,
        DROP_LIFETIME_MS,
        DROP_MIN_TTL_MS,
        POWERUP_ALIAS,
        POWERUP_KEYS,
        POWERUP_MINQLX,
        canonicalize,
        map_crc32,
        normalize_map_key,
        mask_to_loadout,
        loadout_to_mask,
        normalize_loadout_mask,
        normalize_powerups,
        weapon_key_bit,
    )
    from restore import items as match_restore_items
    from restore import qlmatch as restore_qlmatch
except ImportError:
    from .restore import draft as restore_draft
    from .restore.codec import (
        AMMO_KEYS,
        BG_ITEM_CLASSNAMES,
        DROP_LIFETIME_MS,
        DROP_MIN_TTL_MS,
        POWERUP_ALIAS,
        POWERUP_KEYS,
        POWERUP_MINQLX,
        canonicalize,
        map_crc32,
        normalize_map_key,
        mask_to_loadout,
        loadout_to_mask,
        normalize_loadout_mask,
        normalize_powerups,
        weapon_key_bit,
    )
    from .restore import items as match_restore_items
    from .restore import qlmatch as restore_qlmatch

try:
    import minqlxtended as minqlx
except ImportError:
    import minqlx

try:
    import match_restore_util as restore_util
except ImportError:
    try:
        from . import match_restore_util as restore_util
    except ImportError:
        restore_util = None
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
    "quad": "item_quad",
    "regen": "item_regen",
    "haste": "item_haste",
    "bs": "item_enviro",
    "invis": "item_invis",
}

# bg_itemlist index (skills/ql-live/reference/items.md — NOT entity_id on map).
CLASSNAME_BG_INDEX = {
    "item_armor_shard": 1,
    "item_armor_combat": 2,
    "item_armor_body": 3,
    "item_armor_jacket": 4,
    "item_health_small": 5,
    "item_health": 6,
    "item_health_large": 7,
    "item_health_mega": 8,
    "weapon_gauntlet": 9,
    "weapon_shotgun": 10,
    "weapon_machinegun": 11,
    "weapon_grenadelauncher": 12,
    "weapon_rocketlauncher": 13,
    "weapon_lightning": 14,
    "weapon_railgun": 15,
    "weapon_plasmagun": 16,
    "weapon_bfg": 17,
    "weapon_grapplinghook": 18,
    "weapon_nailgun": 50,
    "weapon_prox_launcher": 51,
    "weapon_chaingun": 52,
    "weapon_hmg": 54,
    "item_quad": 29,
    "item_enviro": 30,
    "item_haste": 31,
    "item_invisibility": 32,
    "item_invis": 32,
    "item_regen": 33,
}

# Bundled map spawns (data/map_entities/*.json).
MAP_ITEM_SPAWNS = {
    "bloodrun": {
        "mega": {"entity_id": 42, "x": 784, "y": -224, "z": 88},
        "mh": {"entity_id": 42, "x": 784, "y": -224, "z": 88},
        "ya": {"entity_id": 25, "x": 224, "y": 240, "z": 528},
        "ra": {"entity_id": 49, "x": -160, "y": 16, "z": 528},
        "rl": {"entity_id": 35, "x": 672, "y": -1368, "z": 272},
        "lg": {"entity_id": 41, "x": 672, "y": 384, "z": 88},
    },
}

PICKUP_MATCH_RADIUS = 96.0
SPAWN_TABLE_MATCH_MAX_SQ = 32.0 * 32.0
ITEM_RUNTIME_SCAN_RADIUS = 64.0
_RESTORE_PHASES = frozenset({"all", "time", "players", "items"})
PAUSE_TEXT_CMD_PERM = 5
RESTORE_POS_FRAMES = 3
RESTORE_POS_FRAMES_BOT = 10
RESTORE_VEL_FRAMES = 5
# Server frames to leave unpaused after set_position so other clients
# receive a snapshot with EF_TELEPORT_BIT before we freeze the match.
RESTORE_SNAPSHOT_FRAMES = 2
COORD_DECIMALS = 1

WEAPON_KEYS = (
    "g", "mg", "sg", "gl", "rl", "lg", "rg", "pg", "bfg", "gh", "ng", "pl", "cg", "hmg", "hands",
)

WEAPON_ALIAS = {
    "g": "g",
    "gauntlet": "g",
    "mg": "mg",
    "sg": "sg",
    "gl": "gl",
    "rl": "rl",
    "lg": "lg",
    "rg": "rg",
    "pg": "pg",
    "bfg": "bfg",
    "gh": "gh",
    "ng": "ng",
    "pl": "pl",
    "cg": "cg",
    "hmg": "hmg",
    "hands": "hands",
}

# --- stock minqlxtended compatibility -----------------------------------------
# On the patched runtime the item natives (hide_map_item/show_map_item/
# get_map_item_state/find_map_item_entity/set_item_respawn_delay/set_pickup_lock)
# and the item_event dispatcher come from qlhub_item_events.c/qlhub_item_respawn.c.
# On a stock minqlxtended (>= v1.1.0 + our fork) the same ground is covered by
# writable entity fields, respawn_item() and the gated item_touch event; every
# item helper below prefers the native and falls back to the stock path, and
# __init__ pairs item_touch + item_pickup when there is no item_event.
_EF_NODRAW = getattr(minqlx, "EF_NODRAW", 0x80)
_SVF_NOCLIENT = getattr(minqlx, "SVF_NOCLIENT", 0x01)
_CONTENTS_TRIGGER = 0x40000000  # q_shared.h; not exported by minqlxtended
_ET_ITEM = getattr(minqlx, "ET_ITEM", 2)
# g_local.h; set by LaunchItem() on everything it spawns, which is every death
# drop and every /drop* command - and nothing the map itself placed.
_FL_DROPPED_ITEM = getattr(minqlx, "FL_DROPPED_ITEM", 0x00001000)
_TR_STATIONARY = getattr(minqlx, "TR_STATIONARY", 0)
# Raised by stock natives/views when the vm is not ready or the slot is empty.
_ENGINE_ERR = getattr(minqlx, "EngineStateError", RuntimeError)


def _stock_item_entity(runtime_eid):
    """Entity behind a runtime id, or None (bad id / vm not ready / freed slot)."""
    try:
        ent = minqlx.Entity(int(runtime_eid))
        if not ent.inuse:
            return None
        return ent
    except (TypeError, ValueError, _ENGINE_ERR):
        return None


class match_restore(minqlx.Plugin):
    def __init__(self):
        self._position_apply_queue = []
        self._velocity_apply_queue = []
        self._restore_pending_velocities = {}
        self._was_paused = False
        self._pause_frozen_ms = None
        self._restore_hold_until_unpause = False
        self._awaiting_unfreeze_after_unpause = False
        self._unfreeze_hold_ms = None
        self._unfreeze_thaw_token = 0
        self._unfreeze_thaw_at_wall = None
        self._engine_clock_synced = False
        self._restore_clock_latch_ms = None
        self._frame_poll_error_count = 0
        self._level_time_ms = 0
        self._match_start_map_time = None
        self._last_game_state = None
        self._clock_source = "none"
        self._runtime_entity_by_alias = {}
        self._slot_runtime_ids = {}
        self._itemlab_engine_runtime_ids = set()
        self._restore_apply_active = False
        self._restore_session_active = False
        self._restore_apply_used_runtime_eids = set()
        self._restore_skip_pause_hooks = False
        self._map_spawns = dict(MAP_ITEM_SPAWNS)
        self._map_spawns_loaded = set()
        self._restore_slot_remap = {}
        self._restore_draft = restore_draft.empty_draft()
        self._restore_draft_quiet = False
        self._qlmatch_list_cache = []
        self.set_cvar_once("qlx_matchRestoreLabEnabled", "1")
        self.set_cvar_once("qlx_matchRestoreNativeClock", "0")
        self.set_cvar_once("qlx_matchRestoreUnfreezeDelaySec", "4")
        self.add_command(
            ("restore", "restorecheckpoint"),
            self.cmd_restore,
            5,
            usage="export | test [name] | quiet | loud | clear | time | map | player | item | apply | verify | show "
                  "| players [slot:cid...] | match list [filter] [page] | match <N> <mm:ss>",
            client_cmd_pass=False,
        )
        self.add_hook("map", self._on_map)
        self.add_hook("game_start", self._on_game_start)
        self.add_hook("game_end", self._on_game_end)
        self.add_hook("game_countdown", self._on_game_countdown)
        self._last_item_touch = {}
        if "item_event" in minqlx.EVENT_DISPATCHERS:
            self.add_hook("item_event", self.on_item_event, priority=minqlx.Priority.LOW)
        else:
            # Stock minqlxtended: pair the gated item_touch with item_pickup and
            # synthesize the same item_event payload. The touch hook also
            # enforces the Python-side pickup lock that set_pickup_lock did in C.
            self.add_hook("item_touch", self._on_item_touch_stock, priority=minqlx.Priority.LOW)
            self.add_hook("item_pickup", self._on_item_pickup_stock, priority=minqlx.Priority.LOW)
        self.add_hook("client_command", self._on_client_command, priority=minqlx.Priority.HIGHEST)
        self.add_hook("chat", self._on_chat, priority=minqlx.Priority.HIGHEST)
        self.add_hook("frame", self._frame_apply_positions, priority=minqlx.Priority.LOWEST)
        self.add_hook("frame", self._frame_poll_pause, priority=minqlx.Priority.LOWEST)

    def _enabled(self):
        return self.get_cvar("qlx_matchRestoreLabEnabled", bool) is not False

    def _on_map(self, mapname, factory):
        self._last_item_touch.clear()
        self._position_apply_queue.clear()
        self._velocity_apply_queue.clear()
        self._restore_pending_velocities.clear()
        self._was_paused = False
        self._pause_frozen_ms = None
        self._restore_hold_until_unpause = False
        self._awaiting_unfreeze_after_unpause = False
        self._unfreeze_hold_ms = None
        self._unfreeze_thaw_token = 0
        self._unfreeze_thaw_at_wall = None
        self._engine_clock_synced = False
        self._restore_clock_latch_ms = None
        self._level_time_ms = 0
        self._match_start_map_time = None
        self._last_game_state = None
        self._clock_source = "none"
        self._reset_restore_runtime_cache()
        self._itemlab_engine_runtime_ids.clear()
        self._restore_apply_active = False
        self._end_restore_session()
        self._map_spawns = dict(MAP_ITEM_SPAWNS)
        self._map_spawns_loaded = set()
        self._restore_draft = restore_draft.empty_draft()
        self._restore_draft_quiet = False
        if restore_util is not None:
            restore_util.reset_pause_state()
        self._ensure_map_spawns_loaded()
        return minqlx.Return.NONE

    def _ensure_map_spawns_loaded(self):
        map_key = self._map_key()
        if not map_key or map_key in self._map_spawns_loaded:
            return
        existing = self._map_spawns.get(map_key)
        loaded = {}
        if restore_util is not None:
            loaded = restore_util.load_map_spawns(map_key, self._raw_map_name()) or {}
        if loaded:
            merged = dict(existing or {})
            merged.update(loaded)
            self._prune_ambiguous_spawn_aliases(merged)
            self._map_spawns[map_key] = merged
        self._map_spawns_loaded.add(map_key)

    @staticmethod
    def _prune_ambiguous_spawn_aliases(table):
        """Drop short class aliases (ya, ra, …) when map has multiple of that classname.

        Keep location aliases (ya_fog_bounce) and e{id} keys.
        """
        if not isinstance(table, dict):
            return
        short = frozenset(ITEM_ALIASES) | frozenset({"mh", "mega"})
        by_class = {}
        for alias, meta in table.items():
            if not isinstance(meta, dict):
                continue
            cn = str(meta.get("classname") or "").strip()
            if not cn:
                continue
            by_class.setdefault(cn, []).append(str(alias))
        for cn, aliases in by_class.items():
            if len(aliases) < 2:
                continue
            for alias in aliases:
                if alias in short:
                    table.pop(alias, None)

    def _map_spawns_table(self):
        self._ensure_map_spawns_loaded()
        map_key = self._map_key()
        return self._map_spawns.get(map_key) or {}

    def _restore_engine_timer_active(self):
        # Patched runtime schedules through set_item_respawn_delay; stock
        # minqlxtended (>= v1.1.0) through respawn_item (see
        # _prime_stock_respawn). Either one makes engine-timer restore work.
        return hasattr(minqlx, "set_item_respawn_delay") or hasattr(minqlx, "respawn_item")

    def _ensure_lab_sparring_bot(self, cp=None):
        """Spawn duel bot only for restore test — never on map load (steals pickups)."""
        if self.get_cvar("bot_enable", bool) is not True:
            return False, "bot_enable 0 — set before map load"
        rows = (cp or {}).get("players") or []
        if not any(row.get("bot") for row in rows):
            return True, None
        for player in self.players():
            if self._is_bot_player(player):
                return True, None
        name = "anarki"
        try:
            minqlx.console_command('addbot {} 5 a 0 "{}"'.format(name, name))
            self.logger.info("match_restore: lab sparring bot %s", name)
            return True, None
        except (AttributeError, TypeError, ValueError) as exc:
            return False, "addbot failed: {}".format(exc)

    def _touch_engine_item(self, runtime_eid, client_id=0, alias=None):
        eid = int(runtime_eid)
        cid = int(client_id)
        if eid <= 0:
            return False
        if not hasattr(minqlx, "touch_map_item"):
            return False
        try:
            ok = minqlx.touch_map_item(eid, cid)
            ok = ok is not False
        except (AttributeError, TypeError, ValueError) as exc:
            self.logger.warning(
                "match_restore: touch_map_item e%s alias=%s: %s",
                eid,
                alias,
                exc,
            )
            return False
        if alias is not None:
            self.logger.info(
                "match_restore: touch e%s alias=%s cid=%s ok=%s",
                eid,
                alias,
                cid,
                ok,
            )
        return ok

    def _restore_touch_client_id(self, cp=None):
        """Human slot for touch_map_item during restore (not bot cid 0)."""
        if cp:
            for row in cp.get("players") or []:
                if row.get("bot"):
                    continue
                try:
                    cid = int(row.get("cid", -1))
                except (TypeError, ValueError):
                    continue
                try:
                    target = self.player(int(cid))
                    if target:
                        return int(getattr(target, "id", cid))
                except (IndexError, TypeError, AttributeError, ValueError, minqlx.NonexistentPlayerError):
                    pass
        for player in self.players():
            if player is None:
                continue
            try:
                if getattr(player, "steam_id", "") and str(player.steam_id).startswith("9"):
                    continue
            except (AttributeError, TypeError):
                pass
            return int(getattr(player, "id", 0))
        return 0

    def _validate_runtime_item_entity(self, runtime_eid, classname=None):
        row = self._get_item_state(runtime_eid)
        if row is None:
            return False
        if not int(row[0]):
            return False
        if int(row[1]) == 1:
            return False
        if classname:
            cn = str(row[-1] or "").strip()
            want = str(classname or "").strip()
            if cn and want and cn != want:
                return False
        return True

    def _recover_checkpoint_runtime_eid(self, alias, spawn_meta, classname, table_id):
        alias_key = str(alias or "").strip().lower()
        want_cn = str(classname or "").strip()
        candidates = []
        for rid in self._slot_runtime_ids.get(self._slot_key(table_id), set()) or set():
            try:
                candidates.append(int(rid))
            except (TypeError, ValueError):
                continue
        for key in (alias_key, "e{}".format(table_id), str(table_id)):
            rid = self._runtime_entity_by_alias.get(key)
            if rid is not None:
                try:
                    candidates.append(int(rid))
                except (TypeError, ValueError):
                    pass
        seen = set()
        for rid in sorted(set(candidates), reverse=True):
            if rid in seen:
                continue
            seen.add(rid)
            if self._validate_runtime_item_entity(rid, want_cn or None):
                return rid
        return self._scan_runtime_eid_at_spawn(alias_key, spawn_meta, want_cn, table_id)

    @staticmethod
    def _checkpoint_item_slot_key(spawn_meta, classname):
        if not spawn_meta:
            return None
        try:
            return (
                str(classname or "").strip(),
                round(float(spawn_meta.get("x")), COORD_DECIMALS),
                round(float(spawn_meta.get("y")), COORD_DECIMALS),
                round(float(spawn_meta.get("z")), COORD_DECIMALS),
            )
        except (TypeError, ValueError):
            return None

    def _restore_prep_checkpoint_slots(self, cp):
        """Invalidate stale jobs; recover map runtime entities (incl. hidden)."""
        seen = set()
        recovered = 0
        for item in (cp or {}).get("items") or []:
            alias, spawn_meta, classname = self._spawn_meta_from_checkpoint_item(item)
            if not spawn_meta:
                continue
            slot_key = self._checkpoint_item_slot_key(spawn_meta, classname)
            if slot_key is None:
                continue
            if slot_key in seen:
                continue
            seen.add(slot_key)
            try:
                table_id = int(spawn_meta.get("entity_id"))
            except (TypeError, ValueError):
                continue
            runtime_eid = self._scan_runtime_eid_at_spawn(
                alias,
                spawn_meta,
                classname,
                table_id,
                exclude=set(),
                cache_writes=False,
            )
            if runtime_eid <= 0:
                self.logger.warning(
                    "match_restore: prep missing runtime alias=%s table=%s",
                    alias,
                    table_id,
                )
                continue
            recovered += 1
        self.logger.info(
            "match_restore: restore prep recovered %s/%s checkpoint slot(s)",
            recovered,
            len(seen),
        )
        return recovered

    def _get_item_state(self, runtime_eid):
        """(inuse, etype, eflags, contents, nextthink, has_think, level_time,
        classname) — the get_map_item_state tuple, from the native when the
        patched runtime provides it, else rebuilt from Entity fields. None on
        any failure."""
        if hasattr(minqlx, "get_map_item_state"):
            try:
                return minqlx.get_map_item_state(int(runtime_eid))
            except (AttributeError, TypeError, ValueError):
                return None
        ent = _stock_item_entity(runtime_eid)
        if ent is None:
            return None
        try:
            level_time = int(minqlx.level.time)
        except (AttributeError, TypeError, ValueError, _ENGINE_ERR):
            level_time = 0
        try:
            return (
                1 if ent.inuse else 0,
                int(ent.s.e_type),
                int(ent.s.e_flags),
                int(ent.r.contents),
                int(ent.nextthink),
                1 if ent.think is not None else 0,
                level_time,
                str(ent.classname or ""),
            )
        except (AttributeError, TypeError, ValueError, _ENGINE_ERR):
            return None

    def _engine_item_has_think(self, runtime_eid):
        row = self._get_item_state(runtime_eid)
        if row is None:
            return False
        return bool(int(row[0]) and int(row[5]))

    def _prime_vanilla_respawn_chain(
        self, runtime_eid, delay_ms, alias=None, client_id=0, classname=None, spawn_meta=None
    ):
        """Schedule engine respawn without Python-side entity spawn."""
        eid = int(runtime_eid)
        cid = int(client_id)
        delay_ms = max(0, int(delay_ms))
        if eid <= 0:
            return False
        if not self._restore_engine_timer_active():
            return False

        if delay_ms == 0 and self._engine_item_pickable(eid):
            if alias is not None:
                self.logger.info(
                    "match_restore: vanilla keep e%s alias=%s (already on map)",
                    eid,
                    alias,
                )
            return True

        if not hasattr(minqlx, "set_item_respawn_delay") and hasattr(minqlx, "respawn_item"):
            return self._prime_stock_respawn(eid, delay_ms, alias=alias, classname=classname)

        hide_for_pending = delay_ms > 0 and hasattr(minqlx, "hide_map_item")

        if self._engine_item_has_think(eid) and not self._engine_item_pickable(eid):
            pass
        elif self._engine_item_pickable(eid):
            if hide_for_pending:
                if not self._hide_engine_item(eid, alias, classname, spawn_meta):
                    return False
            elif not self._touch_engine_item(eid, client_id=cid, alias=alias):
                return False
        else:
            if self._show_engine_item(eid, alias=alias, classname=classname):
                if delay_ms == 0 and self._engine_item_pickable(eid):
                    if alias is not None:
                        self.logger.info(
                            "match_restore: vanilla keep e%s alias=%s (shown on map)",
                            eid,
                            alias,
                        )
                    return True
                if self._engine_item_pickable(eid):
                    if hide_for_pending:
                        if not self._hide_engine_item(eid, alias, classname, spawn_meta):
                            return False
                    elif not self._touch_engine_item(eid, client_id=cid, alias=alias):
                        return False
            elif not self._engine_item_has_think(eid):
                self.logger.warning(
                    "match_restore: vanilla prime failed e%s alias=%s (no think)",
                    eid,
                    alias,
                )
                return False

        try:
            ok = minqlx.set_item_respawn_delay(eid, delay_ms)
            ok = ok is not False
        except (AttributeError, TypeError, ValueError) as exc:
            self.logger.warning(
                "match_restore: set_item_respawn_delay e%s alias=%s: %s",
                eid,
                alias,
                exc,
            )
            return False
        if alias is not None:
            self.logger.info(
                "match_restore: vanilla schedule e%s alias=%s delay_ms=%s",
                eid,
                alias,
                delay_ms,
            )
        return ok

    def _prime_stock_respawn(self, eid, delay_ms, alias=None, classname=None):
        """Stock minqlxtended: hide via writable fields, then respawn_item() arms
        the engine's own RespawnItem think - no touch/priming dance needed."""
        if delay_ms == 0:
            # Not pickable (the pickable case returned "keep" above): show it
            # through the engine's own respawn on the next think.
            delay_ms = 1
        elif self._engine_item_pickable(eid):
            if not self._hide_engine_item(eid, alias, classname, None):
                return False
        try:
            ok = minqlx.respawn_item(int(eid), int(delay_ms)) is not False
        except (AttributeError, TypeError, ValueError, _ENGINE_ERR) as exc:
            self.logger.warning(
                "match_restore: respawn_item e%s alias=%s: %s",
                eid,
                alias,
                exc,
            )
            return False
        if alias is not None:
            self.logger.info(
                "match_restore: stock schedule e%s alias=%s delay_ms=%s ok=%s",
                eid,
                alias,
                delay_ms,
                ok,
            )
        return ok

    def _schedule_vanilla_respawn(
        self, runtime_eid, delay_ms, alias=None, client_id=0, classname=None, spawn_meta=None
    ):
        return self._prime_vanilla_respawn_chain(
            runtime_eid,
            delay_ms,
            alias=alias,
            client_id=client_id,
            classname=classname,
            spawn_meta=spawn_meta,
        )

    def _on_game_start(self, *_args, **_kwargs):
        self._last_game_state = "in_progress"
        if self._awaiting_post_unpause_unfreeze():
            self._finish_unpause_clock_thaw()
            return minqlx.Return.NONE
        self._latch_match_start_from_map_time("zmq")
        self._reset_restore_runtime_cache()
        self._itemlab_engine_runtime_ids.clear()
        self._restore_apply_active = False
        return minqlx.Return.NONE

    def _on_game_countdown(self, *_args, **_kwargs):
        self._last_game_state = "countdown"
        return minqlx.Return.NONE

    def _on_game_end(self, *_args, **_kwargs):
        self._reset_match_clock()
        return minqlx.Return.NONE

    def _reset_match_clock(self):
        self._match_start_map_time = None
        self._level_time_ms = 0
        self._last_game_state = None
        self._clock_source = "none"
        self._restore_clock_latch_ms = None
        self._pause_frozen_ms = None
        self._awaiting_unfreeze_after_unpause = False
        self._unfreeze_hold_ms = None
        self._unfreeze_thaw_token = 0
        self._unfreeze_thaw_at_wall = None
        self._engine_clock_synced = False

    def _unfreeze_delay_sec(self):
        try:
            sec = float(self.get_cvar("qlx_matchRestoreUnfreezeDelaySec") or 4)
        except (TypeError, ValueError):
            sec = 4.0
        return max(0.0, sec)

    def _awaiting_post_unpause_unfreeze(self):
        return bool(self._awaiting_unfreeze_after_unpause)

    def _begin_unpause_clock_hold(self):
        """Hold match elapsed until duel unfreezes (after 3-2-1), not at !unpause."""
        if self._awaiting_unfreeze_after_unpause:
            return
        frozen = self._restore_clock_latch_ms
        if frozen is None:
            frozen = self._pause_frozen_ms
        if frozen is None:
            frozen = self._level_time_ms
        self._unfreeze_hold_ms = max(0, int(frozen or 0))
        self._awaiting_unfreeze_after_unpause = True
        self._level_time_ms = self._unfreeze_hold_ms
        self._clock_source = "unfreeze_hold"
        self.logger.info(
            "match_restore: unpause hold ms=%s (wait unfreeze ~%.1fs)",
            self._unfreeze_hold_ms,
            self._unfreeze_delay_sec(),
        )

    def _schedule_unfreeze_thaw(self):
        """Arm the wall-clock deadline; _frame_poll_pause fires the thaw on the
        main thread (no timer thread: engine calls are not thread-safe)."""
        delay = self._unfreeze_delay_sec()
        self._unfreeze_thaw_token += 1
        self._unfreeze_thaw_at_wall = time.time() + delay

    def _note_unpause_command(self):
        if getattr(self, "_restore_skip_pause_hooks", False):
            return
        if self._awaiting_unfreeze_after_unpause:
            self._restore_hold_until_unpause = False
            return
        self._restore_hold_until_unpause = False
        if getattr(self, "_pickup_lock_py", False):
            self._end_restore_session()
        self._begin_unpause_clock_hold()
        self._schedule_unfreeze_thaw()

    def _note_pause_command(self):
        if self._awaiting_unfreeze_after_unpause:
            return
        self._unfreeze_thaw_token += 1
        self._awaiting_unfreeze_after_unpause = False
        self._unfreeze_hold_ms = None
        self._refresh_pause_frozen_ms()

    def _finish_unpause_clock_thaw(self):
        if not self._awaiting_unfreeze_after_unpause:
            return
        self._unfreeze_thaw_token += 1
        frozen = self._unfreeze_hold_ms
        if frozen is None:
            frozen = self._pause_frozen_ms
        if frozen is None:
            frozen = self._level_time_ms
        self._restore_clock_latch_ms = max(0, int(frozen or 0))
        self._resync_match_clock_after_unpause()
        self._awaiting_unfreeze_after_unpause = False
        self._unfreeze_hold_ms = None
        self._unfreeze_thaw_at_wall = None
        self.logger.info(
            "match_restore: unpause unfreeze thaw ms=%s src=%s",
            self._level_time_ms,
            self._clock_source,
        )
        self._flush_restore_velocities()
        self._end_restore_session()

    def _set_pickup_lock(self, active):
        want = bool(active)
        self._pickup_lock_py = want
        if hasattr(minqlx, "set_pickup_lock"):
            try:
                minqlx.set_pickup_lock(1 if want else 0)
            except (AttributeError, TypeError, ValueError) as exc:
                self.logger.warning("match_restore: set_pickup_lock failed: %s", exc)

    def _reset_restore_runtime_cache(self):
        self._runtime_entity_by_alias.clear()
        self._slot_runtime_ids.clear()

    def _abort_restore_session(self, reason=None):
        """No item rollback by design: engine nextthink respawns anything still hidden."""
        self._restore_hold_until_unpause = False
        self._awaiting_unfreeze_after_unpause = False
        self._unfreeze_thaw_token += 1
        self._unfreeze_thaw_at_wall = None
        self._end_restore_session()
        if reason:
            self.logger.warning("match_restore: restore aborted: %s", reason)

    def _restore_ensure_live_for_hud(self):
        """Brief unpause so timer / HP / inventory HUD refresh before final pause."""
        if not self._sv_paused_active():
            return False
        self._restore_skip_pause_hooks = True
        try:
            minqlx.console_command("unpause")
        except (AttributeError, TypeError, ValueError):
            pass
        if restore_util is not None:
            restore_util.set_pause_latch(False)
        self._was_paused = False
        self.logger.info("match_restore: live HUD window (unpause before restore apply)")
        return True

    def _restore_cancel_live_hud_hooks(self):
        self._restore_skip_pause_hooks = False

    def _schedule_after_frames(self, frames, fn):
        """Run fn after `frames` server frames (0 = now)."""
        try:
            left = int(frames)
        except (TypeError, ValueError):
            left = 0
        if left <= 0:
            fn()
            return

        @minqlx.next_frame
        def _step():
            self._schedule_after_frames(left - 1, fn)

        _step()

    def _begin_restore_session(self):
        self._restore_session_active = True
        self._reset_restore_runtime_cache()
        self._restore_apply_used_runtime_eids = set()
        self._restore_pending_velocities.clear()
        self._velocity_apply_queue.clear()
        self._set_pickup_lock(True)
        self.logger.info("match_restore: restore session start (pickup lock ON)")

    def _end_restore_session(self):
        if not self._restore_session_active and not getattr(self, "_pickup_lock_py", False):
            self._set_pickup_lock(False)
            return
        self._restore_session_active = False
        self._set_pickup_lock(False)
        self.logger.info("match_restore: restore session end (pickup lock OFF)")

    def _maybe_end_restore_session(self):
        if not self._restore_session_active:
            return
        if self._awaiting_post_unpause_unfreeze():
            return
        if self._restore_hold_until_unpause:
            return
        self._end_restore_session()

    def _compute_live_elapsed_ms(self):
        """Match elapsed ignoring pause freeze — snap at pause/export edge."""
        if self._restore_clock_latch_ms is not None:
            return max(0, int(self._restore_clock_latch_ms))
        if self._sv_paused_active() and self._pause_frozen_ms is not None:
            return max(0, int(self._pause_frozen_ms))
        effective = self._effective_match_state()
        if effective not in ("countdown", "in_progress"):
            return max(0, int(self._level_time_ms or 0))
        candidates = []
        native = self._native_elapsed_ms()
        if native is not None:
            candidates.append(native)
        mt = self._native_map_time_ms()
        if mt is not None and self._match_start_map_time is not None:
            candidates.append(max(0, mt - int(self._match_start_map_time)))
        try:
            if self.game is not None:
                gt = int(getattr(self.game, "time", 0) or 0)
                if gt > 0:
                    if self._match_start_map_time is not None:
                        candidates.append(max(0, gt - int(self._match_start_map_time)))
                    else:
                        candidates.append(max(0, gt))
        except (AttributeError, TypeError, ValueError):
            pass
        if candidates:
            return max(candidates)
        return max(0, int(self._level_time_ms or 0))

    def _refresh_pause_frozen_ms(self):
        """Freeze match clock now (do not wait for next frame poll)."""
        if not self._sv_paused_active():
            return None
        if self._restore_clock_latch_ms is not None:
            ms = max(0, int(self._restore_clock_latch_ms))
        elif self._pause_frozen_ms is not None:
            ms = max(0, int(self._pause_frozen_ms))
        else:
            ms = max(0, int(self._compute_live_elapsed_ms()))
        self._pause_frozen_ms = ms
        self._level_time_ms = ms
        self._clock_source = "pause_snap"
        self.logger.info("match_restore: pause snap frozen_ms=%s", ms)
        return ms

    @staticmethod
    def _pause_command_kind(cmd):
        text = str(cmd or "").strip()
        if not text:
            return None
        lower = text.lower()
        if lower.startswith("say ") or lower.startswith("say_team "):
            parts = text.split(None, 1)
            if len(parts) < 2:
                return None
            lower = parts[1].strip().strip('"').lower()
        if lower.startswith("!rcon "):
            lower = lower[6:].strip()
        if lower.startswith("!"):
            lower = lower[1:].lstrip()
        if lower == "pause" or lower.startswith("pause "):
            return "pause"
        if lower == "unpause" or lower.startswith("unpause "):
            return "unpause"
        return None

    def _pause_text_cmd_allowed(self, player):
        """Only console/RCON and perm>=5 players may drive the pause/clock state
        machine via pause/unpause text. Real sv_paused transitions are still
        tracked by _frame_poll_pause, so unprivileged (engine-honored) pauses
        are not lost — this only blocks chat/command spoofing."""
        if player is None:
            return True
        try:
            return bool(self.db.has_permission(player, PAUSE_TEXT_CMD_PERM))
        except Exception:
            return False

    def _note_pause_text(self, player, text):
        kind = self._pause_command_kind(text)
        if kind is None:
            return
        if not self._pause_text_cmd_allowed(player):
            self.logger.info(
                "match_restore: ignore %s text from unprivileged %s",
                kind,
                getattr(player, "steam_id", "?"),
            )
            return
        if restore_util is not None:
            restore_util.note_client_command(
                str(text or ""), player=player, plugin=self
            )
        if kind == "pause":
            self._note_pause_command()
        else:
            self._note_unpause_command()

    def _on_client_command(self, player, cmd):
        if self._enabled():
            self._note_pause_text(player, cmd)
        return minqlx.Return.NONE

    def _on_chat(self, player, msg, channel, recipient=None):
        if self._enabled():
            self._note_pause_text(player, msg)
        return minqlx.Return.NONE

    def _sv_paused_active(self):
        if restore_util is not None:
            return restore_util.paused_active(self)
        raw = (self.get_cvar("sv_paused") or "0").strip().lower()
        return raw not in ("0", "", "false", "off")

    def _frame_poll_pause(self, *_args, **_kwargs):
        if not self._enabled():
            return minqlx.Return.NONE
        try:
            if self._awaiting_unfreeze_after_unpause:
                thaw_at = getattr(self, "_unfreeze_thaw_at_wall", None)
                if thaw_at is not None and time.time() >= float(thaw_at):
                    self._finish_unpause_clock_thaw()
            paused = self._sv_paused_active()
            if paused and not self._was_paused:
                if not self._awaiting_unfreeze_after_unpause:
                    self._note_pause_command()
            elif self._was_paused and not paused:
                if not getattr(self, "_restore_skip_pause_hooks", False):
                    self._note_unpause_command()
            elif self._restore_hold_until_unpause and not paused:
                if not getattr(self, "_restore_skip_pause_hooks", False):
                    self._note_unpause_command()
            if (
                not paused
                and getattr(self, "_pickup_lock_py", False)
                and not self._restore_apply_active
            ):
                self._end_restore_session()
            if not self._sv_paused_active():
                self._track_match_clock()
            self._was_paused = paused
        except Exception:
            # Never break the frame loop, but do not hide failures either.
            self._frame_poll_error_count += 1
            if self._frame_poll_error_count <= 3 or self._frame_poll_error_count % 1000 == 0:
                self.logger.exception(
                    "match_restore: frame poll error #%s",
                    self._frame_poll_error_count,
                )
        return minqlx.Return.NONE

    def _game_state_label(self):
        try:
            game = self.game
            if game is None:
                return None
            return str(getattr(game, "state", "") or "") or None
        except Exception:
            return None

    def _effective_match_state(self):
        """Phase for match clock: combine game.state with ZMQ hooks.

        game.state can lag or read None while ZMQ already fired game_start;
        never downgrade an in_progress latch back to warmup/None on read.
        """
        live = self._game_state_label()
        latched = self._last_game_state
        if live in ("countdown", "in_progress"):
            return live
        if latched in ("countdown", "in_progress"):
            return latched
        return live or latched

    def _native_map_time_ms(self):
        # get_map_time() was a custom C function pre-port; v1.0.0 exposes the
        # same value natively as the always-present minqlxtended.level.time
        # singleton attribute (level_locals_t.time). hasattr guard kept
        # defensively in case a future minqlxtended build ever drops it.
        if not hasattr(minqlx, "level"):
            return None
        try:
            ms = int(minqlx.level.time)
            return ms if ms >= 0 else None
        except (AttributeError, TypeError, ValueError, minqlx.EngineStateError):
            return None

    def _native_clock_enabled(self):
        return self.get_cvar("qlx_matchRestoreNativeClock", bool) is True

    def _engine_level_time_api(self):
        # set_level_time/get_level_time were custom C functions pre-port;
        # v1.0.0 exposes both level.time (read) and level.start_time
        # (read/write) as one native attribute object, so a single hasattr
        # check now covers what used to need two - but only guards against
        # the attribute never existing at all (a future minqlxtended build
        # dropping it), not against the level pointer being transiently
        # unavailable (mid-match VM reload): that raises
        # minqlx.EngineStateError, caught separately at each call site below.
        return hasattr(minqlx, "level")

    def _sync_engine_level_time(self, ms):
        """Align engine level.start_time so timelimit uses restored elapsed, not HUD-only.

        Same arithmetic the old custom set_level_time() C function did
        (level->startTime = level->time - time_ms), now done in Python from
        two native attribute reads/writes instead of one custom call.
        """
        if not self._engine_level_time_api():
            return False, None
        try:
            ms = int(ms)
            if ms < 0:
                return False, "set_level_time failed: time_ms must be non-negative."
            lvl = minqlx.level
            lvl.start_time = int(lvl.time) - ms
        except (AttributeError, TypeError, ValueError, minqlx.EngineStateError) as exc:
            return False, "set_level_time failed: {}".format(exc)
        self._engine_clock_synced = True
        return True, "engine_elapsed={}ms".format(ms)

    def _native_elapsed_ms(self):
        if not (self._native_clock_enabled() or self._engine_clock_synced):
            return None
        if not hasattr(minqlx, "level"):
            return None
        try:
            lvl = minqlx.level
            ms = int(lvl.time) - int(lvl.start_time)
            return max(0, ms)
        except (AttributeError, TypeError, ValueError, minqlx.EngineStateError):
            return None

    def _latch_match_start_from_map_time(self, reason="state"):
        mt = self._native_map_time_ms()
        if mt is None:
            return False
        self._match_start_map_time = mt
        self._level_time_ms = 0
        self._clock_source = "latched_{}".format(reason)
        return True

    def _track_match_clock(self):
        state = self._game_state_label()
        prev = self._last_game_state
        if state is not None and state != prev:
            if state == "in_progress" and prev in (None, "warmup", "countdown"):
                self._latch_match_start_from_map_time("in_progress")
            elif state == "warmup" and prev in ("in_progress", "countdown"):
                self._reset_match_clock()
            self._last_game_state = state
        if self._sv_paused_active():
            if self._pause_frozen_ms is not None:
                self._level_time_ms = self._pause_frozen_ms
            else:
                self._level_time_ms = self._compute_live_elapsed_ms()
                self._pause_frozen_ms = max(0, int(self._level_time_ms))
            return
        if self._awaiting_post_unpause_unfreeze():
            self._level_time_ms = max(0, int(self._unfreeze_hold_ms or 0))
            self._clock_source = "unfreeze_hold"
            return
        effective = self._effective_match_state()
        self._level_time_ms = self._match_elapsed_ms(effective)

    def _match_elapsed_ms(self, state=None):
        if state is None:
            state = self._game_state_label()
        if state not in ("countdown", "in_progress"):
            self._clock_source = "warmup"
            return 0
        native = self._native_elapsed_ms()
        if native is not None:
            self._clock_source = "native"
            return native
        if self._match_start_map_time is not None:
            mt = self._native_map_time_ms()
            if mt is not None:
                self._clock_source = "map_delta"
                return max(0, mt - int(self._match_start_map_time))
        self._clock_source = "cache"
        return max(0, int(self._level_time_ms or 0))

    def _resync_match_clock_after_unpause(self):
        """Map time keeps ticking during QL pause; re-anchor so elapsed resumes at freeze."""
        frozen = self._restore_clock_latch_ms
        if frozen is None:
            frozen = self._pause_frozen_ms
        self._pause_frozen_ms = None
        if frozen is None:
            self._restore_clock_latch_ms = None
            return
        self._level_time_ms = max(0, int(frozen))
        if not self._match_clock_live():
            self._restore_clock_latch_ms = None
            return
        mt = self._native_map_time_ms()
        if mt is not None:
            self._match_start_map_time = mt - int(frozen)
            self._clock_source = "pause_thaw"
        ok_eng, eng_detail = self._sync_engine_level_time(int(frozen))
        self._restore_clock_latch_ms = None
        self.logger.info(
            "match_restore: unpause clock thaw frozen_ms=%s map_t=%s start_t=%s eng=%s",
            frozen,
            mt,
            self._match_start_map_time,
            eng_detail or ok_eng,
        )

    def _frame_apply_positions(self, *_args, **_kwargs):
        if not self._enabled():
            return minqlx.Return.NONE
        if self._position_apply_queue:
            pos_remaining = []
            for job in self._position_apply_queue:
                try:
                    target = self.player(job["client_id"])
                    self._apply_player_position(
                        target,
                        job["x"],
                        job["y"],
                        job["z"],
                        teleport=False,
                    )
                except (AttributeError, TypeError, ValueError, minqlx.NonexistentPlayerError):
                    pass
                job["frames"] -= 1
                if job["frames"] > 0:
                    pos_remaining.append(job)
            self._position_apply_queue = pos_remaining
        if self._velocity_apply_queue:
            vel_remaining = []
            for job in self._velocity_apply_queue:
                try:
                    target = self.player(job["client_id"])
                    self._write_player_velocity(target, job["vx"], job["vy"], job["vz"])
                except (AttributeError, TypeError, ValueError, minqlx.NonexistentPlayerError):
                    pass
                job["frames"] -= 1
                if job["frames"] > 0:
                    vel_remaining.append(job)
            self._velocity_apply_queue = vel_remaining
        return minqlx.Return.NONE

    @staticmethod
    def _bg_index_for(classname):
        return CLASSNAME_BG_INDEX.get(str(classname or "").strip())

    def _vanilla_respawn_sec(self, classname):
        name = str(classname or "")
        if name.startswith("weapon_"):
            try:
                sec = self.get_cvar("g_weaponrespawn", int)
            except (AttributeError, TypeError, ValueError):
                sec = None
            return float(sec if sec is not None else 5)
        if name == "item_health_mega":
            return 35.0
        if name.startswith("item_armor"):
            return 25.0
        if name.startswith("ammo_"):
            try:
                sec = self.get_cvar("g_ammorespawn", int)
            except (AttributeError, TypeError, ValueError):
                sec = None
            return float(sec if sec is not None else 40)
        if name.startswith("item_"):
            try:
                sec = self.get_cvar("g_poweruprespawn", int)
            except (AttributeError, TypeError, ValueError):
                sec = None
            return float(sec if sec is not None else 120)
        return 35.0

    def _find_bundled_spawn(self, classname, x, y, z):
        rows = self._map_spawns_table()
        best_alias = None
        best_meta = None
        best_dist = PICKUP_MATCH_RADIUS * PICKUP_MATCH_RADIUS
        want_cn = str(classname or "").strip()
        for alias, meta in rows.items():
            if alias in ("mh",):
                continue
            cn = str(meta.get("classname") or ITEM_ALIASES.get(alias, alias) or "").strip()
            if cn != want_cn:
                continue
            dx = float(x) - float(meta.get("x", 0))
            dy = float(y) - float(meta.get("y", 0))
            dz = float(z) - float(meta.get("z", 0))
            dist = dx * dx + dy * dy + dz * dz
            if dist <= best_dist:
                best_alias = alias
                best_meta = meta
                best_dist = dist
        if best_meta is None or best_dist > SPAWN_TABLE_MATCH_MAX_SQ:
            return None, None
        return best_alias, best_meta

    def _spawn_meta_for_entity(self, item_entity_id, classname, x, y, z):
        alias, meta = self._find_bundled_spawn(classname, x, y, z)
        if meta:
            return alias, meta
        try:
            eid = int(item_entity_id)
        except (TypeError, ValueError):
            eid = 0
        if eid > 0:
            for alias, meta in self._map_spawns_table().items():
                if alias in ("mh",):
                    continue
                try:
                    if int(meta.get("entity_id", -1)) == eid:
                        return alias, meta
                except (TypeError, ValueError):
                    continue
        return None, None

    def _slot_key(self, table_entity_id):
        return (self._map_key(), int(table_entity_id))

    def _track_slot_runtime_id(self, table_id, runtime_eid):
        try:
            rid = int(runtime_eid)
        except (TypeError, ValueError):
            return
        if rid <= 0:
            return
        key = self._slot_key(table_id)
        self._slot_runtime_ids.setdefault(key, set()).add(rid)

    def _on_item_touch_stock(self, player, entity):
        """Stock runtime: enforce the pickup lock and stash the touched entity so
        _on_item_pickup_stock can rebuild the item_event payload."""
        if getattr(self, "_pickup_lock_py", False):
            return minqlx.Return.STOP_EVENT
        try:
            origin = entity.r.current_origin
            self._last_item_touch[int(player.id)] = (
                int(entity.number),
                str(entity.classname or ""),
                int(entity.s.modelindex),
                float(origin.x),
                float(origin.y),
                float(origin.z),
            )
        except (AttributeError, TypeError, ValueError, _ENGINE_ERR):
            pass
        return minqlx.Return.NONE

    def _on_item_pickup_stock(self, player, item):
        """Stock runtime: the pickup that follows a touch, same call stack C-side."""
        info = self._last_item_touch.pop(int(player.id), None)
        if not info:
            return minqlx.Return.NONE
        eid, classname, bg_index, x, y, z = info
        gi_type = gi_tag = gi_quantity = 0
        try:
            bg_item = minqlx.Item(int(bg_index))
            gi_type = int(bg_item.gi_type)
            gi_tag = int(bg_item.gi_tag)
            gi_quantity = int(bg_item.quantity)
        except (AttributeError, TypeError, ValueError, _ENGINE_ERR):
            pass
        try:
            game_time = int(minqlx.level.time)
        except (AttributeError, TypeError, ValueError, _ENGINE_ERR):
            game_time = 0
        return self.on_item_event(
            "pickup", eid, player, classname or str(item or ""),
            gi_type, gi_tag, gi_quantity, x, y, z, game_time,
        )

    def on_item_event(
        self,
        action,
        item_entity_id,
        player,
        classname,
        gi_type=0,
        gi_tag=0,
        gi_quantity=0,
        x=0.0,
        y=0.0,
        z=0.0,
        game_time=0,
    ):
        """Track runtime entity ids only — vanilla engine handles respawn."""
        if not self._enabled():
            return minqlx.Return.NONE
        if str(action or "").strip().lower() != "pickup":
            return minqlx.Return.NONE
        alias, spawn_meta = self._spawn_meta_for_entity(
            item_entity_id, classname, x, y, z
        )
        if not spawn_meta or not alias:
            return minqlx.Return.NONE
        table_id = int(spawn_meta.get("entity_id"))
        try:
            runtime_eid = int(item_entity_id)
        except (TypeError, ValueError):
            runtime_eid = 0
        if runtime_eid <= 0:
            return minqlx.Return.NONE
        if runtime_eid in self._itemlab_engine_runtime_ids:
            return minqlx.Return.NONE
        self._runtime_entity_by_alias[str(alias)] = runtime_eid
        self._runtime_entity_by_alias["e{}".format(table_id)] = runtime_eid
        self._track_slot_runtime_id(table_id, runtime_eid)
        return minqlx.Return.NONE

    @staticmethod
    def _map_key():
        game = minqlx.Game()
        name = ""
        for attr in ("map", "map_name"):
            val = getattr(game, attr, None)
            if val:
                name = str(val)
                break
        return normalize_map_key(name or getattr(game, "map_title", None))

    @staticmethod
    def _raw_map_name():
        """Unnormalized map name (matches the .bsp/.pk3 filename) for map_entities()."""
        game = minqlx.Game()
        for attr in ("map", "map_name"):
            val = getattr(game, attr, None)
            if val:
                return str(val)
        return None

    def _resolve_alias(self, alias):
        key = str(alias or "").strip().lower()
        row = self._lookup_spawn_meta(key)
        if row and row.get("classname"):
            return str(row["classname"]), key
        return ITEM_ALIASES.get(key), key

    def _lookup_spawn_meta(self, alias):
        table = self._map_spawns_table()
        key = str(alias).strip().lower()
        row = table.get(key)
        if row and isinstance(row, dict):
            return dict(row)
        if key.startswith("e") and key[1:].isdigit():
            want_id = int(key[1:])
            for meta in table.values():
                if not isinstance(meta, dict):
                    continue
                try:
                    if int(meta.get("entity_id", -1)) == want_id:
                        return dict(meta)
                except (TypeError, ValueError):
                    continue
        return None

    def _reply(self, player, channel, msg):
        """Reply to the command caller. RCON/console invocation (`qlx restore ...`,
        e.g. hub-delivered cfg lines) passes player=None where tell would raise
        AttributeError and swallow the real result. channel.reply() works for both
        console and in-game channels."""
        try:
            caller = player
            if caller is not None:
                caller.tell(msg)
            else:
                channel.reply(msg)
        except Exception:
            self.logger.exception("match_restore: reply failed (msg=%s)", msg)

    def cmd_restore(self, player, msg, channel):
        try:
            return self._cmd_restore_impl(player, msg, channel)
        except Exception as exc:
            self.logger.exception("restore failed")
            self._reply(player, channel, "^1restore error^7: {}".format(exc))
            return minqlx.Return.STOP_ALL

    def _cmd_restore_impl(self, player, msg, channel):
        if not self._enabled():
            self._reply(player, channel, "^1match_restore disabled.^7")
            return minqlx.Return.STOP_ALL
        if len(msg) < 2:
            return minqlx.Return.USAGE
        sub = str(msg[1]).strip().lower()
        if sub == "export":
            return self._cmd_restore_export(player, channel)
        if sub == "test":
            return self._cmd_restore_test(player, channel, msg[2:])
        if sub == "match":
            return self._cmd_restore_qlmatch(player, channel, msg[2:])
        if sub in restore_draft.DRAFT_SUBCOMMANDS:
            return self._cmd_restore_draft(player, channel, sub, msg[2:])
        return minqlx.Return.USAGE

    LAB_CHECKPOINT_MAX_BYTES = 256 * 1024

    def _load_checkpoint_json(self, path):
        """Bundled lab fixtures only (data/checkpoints/*.json), size-capped."""
        with open(path, "rb") as handle:
            data = handle.read(self.LAB_CHECKPOINT_MAX_BYTES + 1)
        if len(data) > self.LAB_CHECKPOINT_MAX_BYTES:
            raise ValueError("checkpoint file too large (> {} bytes)".format(
                self.LAB_CHECKPOINT_MAX_BYTES
            ))
        return canonicalize(json.loads(data.decode("utf-8")))

    def _lab_checkpoint_dir(self):
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "checkpoints")

    def _list_lab_checkpoints(self):
        base = self._lab_checkpoint_dir()
        if not os.path.isdir(base):
            return []
        return sorted(
            name[:-5] for name in os.listdir(base) if name.endswith(".json")
        )

    def _lab_checkpoint_path(self, name):
        base = self._lab_checkpoint_dir()
        stem = os.path.basename(str(name or "").strip()) or "bloodrun_lab_35s"
        if not stem.endswith(".json"):
            stem += ".json"
        path = os.path.join(base, stem)
        return path if os.path.isfile(path) else None

    def _cmd_restore_test(self, player, channel, msg_tail):
        name = str(msg_tail[0]).strip() if msg_tail else "bloodrun_lab_35s"
        path = self._lab_checkpoint_path(name)
        if not path:
            have = ", ".join(self._list_lab_checkpoints()) or "(none)"
            self._reply(
                player,
                channel,
                "^1restore test^7: unknown ^3{}^7. Bundled: ^3{}^7".format(name, have),
            )
            return minqlx.Return.STOP_ALL
        try:
            cp = self._load_checkpoint_json(path)
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            self._reply(player, channel, "^1restore test^7: {}".format(exc))
            return minqlx.Return.STOP_ALL
        map_key = self._map_key()
        cp_map = str(cp.get("map") or "")
        if cp_map and map_key and cp_map != map_key:
            self._reply(
                player,
                channel,
                "^1restore test^7: need map ^3{}^7 (server ^3{}^7). ^2map bloodrun^7 first.".format(
                    cp_map, map_key
                ),
            )
            return minqlx.Return.STOP_ALL
        t_ms = int(cp.get("t_ms") or 0)
        n_pending = sum(1 for it in cp.get("items") or [] if int(it.get("s", 1)) == 2)
        self._reply(
            player,
            channel,
            "^2restore test^7: ^3{}^7 — t={}ms ({:.1f}s), {} pending".format(
                os.path.basename(path), t_ms, t_ms / 1000.0, n_pending
            ),
        )
        bot_ok, bot_detail = self._ensure_lab_sparring_bot(cp)
        if not bot_ok:
            self._reply(player, channel, "^1restore test^7: {}".format(bot_detail))
            return minqlx.Return.STOP_ALL
        ok, detail = self._apply_checkpoint(player, cp)
        if ok:
            self._reply(player, channel, "^2restore test OK^7: {}".format(detail))
            if name.startswith("bloodrun_lab_35") or t_ms >= 30000:
                self._reply(
                    player,
                    channel,
                    "^7Expect: HUD ~0:35, mega ~+7s after unfreeze, bot ^650hp^7, YA e25+e32 now.",
                )
            else:
                self._reply(
                    player,
                    channel,
                    "^7Expect: HUD ~0:21, mega ~+16s after ^3!unpause^7.",
                )
        else:
            self._reply(player, channel, "^1restore test failed^7: {}".format(detail))
        return minqlx.Return.STOP_ALL

    def _qlmatch_demo_dir(self):
        """Same directory the .qlmatch packer and native demo capture write
        to: fs_homepath/sv_demoDir (kept as a private copy — plugins don't
        share instance state, and this is the one cvar pair minqlxtended's
        own demo_match.c uses for its final_path construction, not a
        guess)."""
        homepath = (self.get_cvar("fs_homepath") or "").strip()
        subdir = (self.get_cvar("sv_demoDir") or "").strip() or "demos"
        if not homepath:
            return None
        return os.path.join(homepath, subdir)

    def _cmd_restore_qlmatch(self, player, channel, tail):
        if not tail:
            self._reply(
                player, channel,
                "^1restore match^7: usage ^3match list [filter] [page]^7 | ^3match <N> <mm:ss[.mmm]>^7",
            )
            return minqlx.Return.STOP_ALL
        head = str(tail[0]).strip().lower()
        if head == "list":
            return self._cmd_restore_qlmatch_list(player, channel, tail[1:])
        return self._cmd_restore_qlmatch_apply(player, channel, tail)

    _QLMATCH_LIST_PAGE_SIZE = 10

    def _cmd_restore_qlmatch_list(self, player, channel, tail):
        demo_dir = self._qlmatch_demo_dir()
        if not demo_dir:
            self._reply(
                player, channel,
                "^1restore match list^7: fs_homepath cvar empty, cannot locate demo dir",
            )
            return minqlx.Return.STOP_ALL
        tokens = [str(t).strip() for t in tail if str(t).strip()]
        page = 1
        if tokens and tokens[-1].isdigit():
            page = max(1, int(tokens[-1]))
            tokens = tokens[:-1]
        filter_substr = " ".join(tokens).strip() or None
        rows = restore_qlmatch.list_packs(demo_dir, filter_substr)
        # Cached so `match <N> <mm:ss>` resolves N against THIS listing,
        # not a directory rescan — numbering is only stable within one
        # list -> act pair (a new match finishing between the two calls
        # shifts everyone's index since packs are sorted newest-first).
        self._qlmatch_list_cache = rows
        suffix = " matching '{}'".format(filter_substr) if filter_substr else ""
        if not rows:
            self._reply(
                player, channel,
                "^3restore match list^7: no .qlmatch packs found in {}{}".format(demo_dir, suffix),
            )
            return minqlx.Return.STOP_ALL
        page_size = self._QLMATCH_LIST_PAGE_SIZE
        pages = max(1, (len(rows) + page_size - 1) // page_size)
        page = min(page, pages)
        window = rows[(page - 1) * page_size:page * page_size]
        # Sidecar-derived durations only for the rows actually shown — the
        # full-directory fallback is what used to hitch the server.
        restore_qlmatch.fill_sidecar_durations(window, demo_dir)
        self._reply(
            player, channel,
            "^2restore match list^7: {} pack(s){} — page ^3{}^7/^3{}^7".format(
                len(rows), suffix, page, pages
            ),
        )
        for row in window:
            self._reply(
                player, channel,
                "  ^3{}^7. {} map={} time={} players={}".format(
                    row["index"], row["match_id"], row["map"] or "?",
                    restore_qlmatch.format_clock(row.get("duration_ms")),
                    ",".join(row["players"][:8]) or "?",
                ),
            )
        if page < pages:
            self._reply(
                player, channel,
                "  ^7... ^3!restore match list {}{}^7 for the next page".format(
                    (filter_substr + " ") if filter_substr else "", page + 1
                ),
            )
        return minqlx.Return.STOP_ALL

    def _cmd_restore_qlmatch_apply(self, player, channel, tail):
        if len(tail) < 2:
            self._reply(
                player, channel,
                "^1restore match^7: usage ^3<N> <mm:ss[.mmm]>^7 (run ^3restore match list^7 first)",
            )
            return minqlx.Return.STOP_ALL
        pack = restore_qlmatch.resolve_pack_by_index(self._qlmatch_list_cache, tail[0])
        if pack is None:
            self._reply(
                player, channel,
                "^1restore match^7: no pack #{} in the last list — run ^3restore match list^7 again".format(
                    tail[0]
                ),
            )
            return minqlx.Return.STOP_ALL
        try:
            target_ms = restore_qlmatch.parse_clock_to_ms(tail[1])
        except ValueError as exc:
            self._reply(player, channel, "^1restore match^7: {}".format(exc))
            return minqlx.Return.STOP_ALL

        map_key = self._map_key()
        pack_map_key = normalize_map_key(pack["map"])
        if map_key and pack_map_key and pack_map_key != map_key:
            self._reply(
                player, channel,
                "^1restore match^7: need map ^3{}^7 (server ^3{}^7). ^2map {}^7 first.".format(
                    pack["map"], map_key, pack["map"]
                ),
            )
            return minqlx.Return.STOP_ALL

        demo_dir = self._qlmatch_demo_dir()
        if not demo_dir:
            self._reply(player, channel, "^1restore match^7: fs_homepath cvar empty, cannot locate demo dir")
            return minqlx.Return.STOP_ALL
        sidecar_path = restore_qlmatch.sidecar_path_for(demo_dir, pack["match_id"], pack["map"])
        if not os.path.isfile(sidecar_path):
            self._reply(
                player, channel,
                "^1restore match^7: no replay sidecar for {} ({}) — {} does not exist yet "
                "(the .qlmatch replay/merge step has not produced it for this pack)".format(
                    pack["match_id"], pack["map"], os.path.basename(sidecar_path)
                ),
            )
            return minqlx.Return.STOP_ALL
        try:
            sidecar = restore_qlmatch.load_sidecar(sidecar_path)
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            self._reply(player, channel, "^1restore match^7: could not read sidecar: {}".format(exc))
            return minqlx.Return.STOP_ALL

        try:
            doc, warning, snap_t = restore_qlmatch.build_checkpoint_doc(
                sidecar, target_ms, self._map_spawns_table(), map_key or pack_map_key, time.time(),
                window=pack.get("window"),
            )
            cp = canonicalize(doc)
        except (ValueError, KeyError, TypeError) as exc:
            self._reply(player, channel, "^1restore match^7: {}".format(exc))
            return minqlx.Return.STOP_ALL

        gen_version = (sidecar.get("meta") or {}).get("generator_version")
        self._reply(
            player, channel,
            "^2restore match^7: {} map={} t={}ms (snapshot t={}ms) gen={} — {} players, {} items".format(
                pack["match_id"], pack["map"], target_ms, snap_t, gen_version or "?",
                len(cp.get("players") or []), len(cp.get("items") or []),
            ),
        )
        if warning:
            self._reply(player, channel, warning)

        ok, detail = self._apply_checkpoint(
            player, cp, slot_remap=dict(self._restore_slot_remap)
        )
        if ok:
            self._reply(player, channel, "^2restore match OK^7: {}".format(detail))
        else:
            self._reply(player, channel, "^1restore match failed^7: {}".format(detail))
        return minqlx.Return.STOP_ALL

    def _reset_restore_draft(self):
        self._restore_draft = restore_draft.empty_draft()

    @staticmethod
    def _player_display_name(player):
        name = getattr(player, "clean_name", None) or getattr(player, "name", None) or ""
        return restore_draft.strip_name(name)[:64] or None

    def _draft_resolve_item_eid(self, token):
        text = str(token or "").strip().lower()
        if not text:
            raise ValueError("item id empty")
        if text.startswith("e") and text[1:].isdigit():
            return int(text[1:]), "e{}".format(int(text[1:]))
        self._ensure_map_spawns_loaded()
        map_key = self._map_key()
        table = (self._map_spawns.get(map_key) or {}).get(text)
        if not table:
            raise ValueError("unknown item alias {} on map {}".format(text, map_key or "?"))
        return int(table.get("entity_id")), text

    def _draft_tell(self, player, channel, msg, *, loud=False):
        """Draft step feedback. quiet mode → log only (apply/verify/errors use loud=True)."""
        if loud or not self._restore_draft_quiet:
            self._reply(player, channel, msg)
        else:
            self.logger.debug(
                "restore draft: %s",
                re.sub(r"\^[0-9a-zA-Z]", "", str(msg or "")),
            )

    def _cmd_restore_draft(self, player, channel, sub, tail):
        sub = str(sub or "").strip().lower()
        if sub == "quiet":
            self._restore_draft_quiet = True
            return minqlx.Return.STOP_ALL
        if sub == "loud":
            self._restore_draft_quiet = False
            return minqlx.Return.STOP_ALL
        if sub == "clear":
            self._reset_restore_draft()
            self._draft_tell(
                player,
                channel,
                "^2restore clear^7 — draft reset (slot remap kept: {})".format(
                    restore_draft.format_slot_remap(self._restore_slot_remap)
                ),
            )
            return minqlx.Return.STOP_ALL
        if sub == "players":
            if tail and str(tail[0]).strip().lower() in ("clear", "reset", "none"):
                self._restore_slot_remap = {}
                self._draft_tell(player, channel, "^2restore players clear^7")
                return minqlx.Return.STOP_ALL
            if not tail:
                self._draft_tell(
                    player,
                    channel,
                    "^3restore players^7: {} — use ^30:3 1:2^7 or ^3clear^7".format(
                        restore_draft.format_slot_remap(self._restore_slot_remap)
                    ),
                )
                return minqlx.Return.STOP_ALL
            try:
                self._restore_slot_remap = restore_draft.parse_slot_remap_tokens(tail)
            except ValueError as exc:
                self._draft_tell(player, channel, "^1restore players^7: {}".format(exc), loud=True)
                return minqlx.Return.STOP_ALL
            self._draft_tell(
                player,
                channel,
                "^2restore players^7: {}".format(
                    restore_draft.format_slot_remap(self._restore_slot_remap)
                ),
            )
            return minqlx.Return.STOP_ALL
        if sub == "show":
            cp = restore_draft.draft_to_checkpoint(self._restore_draft)
            self._draft_tell(
                player,
                channel,
                "^3restore draft^7: t={}ms map={} players={} items={} remap={}".format(
                    cp.get("t_ms"),
                    cp.get("map") or "?",
                    len(cp.get("players") or []),
                    len(cp.get("items") or []),
                    restore_draft.format_slot_remap(self._restore_slot_remap),
                ),
            )
            return minqlx.Return.STOP_ALL
        if sub == "time":
            if not tail:
                self._draft_tell(player, channel, "^1restore time^7: need ms or mm:ss", loud=True)
                return minqlx.Return.STOP_ALL
            try:
                ms = self._parse_match_time_arg(tail)
            except (TypeError, ValueError) as exc:
                self._draft_tell(player, channel, "^1restore time^7: {}".format(exc), loud=True)
                return minqlx.Return.STOP_ALL
            self._restore_draft["t_ms"] = int(ms)
            self._draft_tell(
                player,
                channel,
                "^2restore time^7: {} ms ({:.1f}s)".format(ms, ms / 1000.0),
            )
            return minqlx.Return.STOP_ALL
        if sub == "map":
            if not tail:
                self._draft_tell(player, channel, "^1restore map^7: need map name", loud=True)
                return minqlx.Return.STOP_ALL
            self._restore_draft["map"] = normalize_map_key(tail[0])
            self._draft_tell(player, channel, "^2restore map^7: {}".format(self._restore_draft["map"]))
            return minqlx.Return.STOP_ALL
        if sub == "player":
            return self._cmd_restore_draft_player(player, channel, tail)
        if sub == "item":
            return self._cmd_restore_draft_item(player, channel, tail)
        if sub == "apply":
            try:
                cp = restore_draft.draft_to_checkpoint(self._restore_draft)
            except (TypeError, ValueError) as exc:
                self._draft_tell(player, channel, "^1restore apply^7: {}".format(exc), loud=True)
                return minqlx.Return.STOP_ALL
            if not cp.get("players"):
                self._draft_tell(player, channel, "^1restore apply^7: no players in draft", loud=True)
                return minqlx.Return.STOP_ALL
            ok, detail = self._apply_checkpoint(
                player,
                cp,
                slot_remap=dict(self._restore_slot_remap),
            )
            if ok:
                self._draft_tell(player, channel, "^2restore apply OK^7: {}".format(detail), loud=True)
            else:
                self._draft_tell(player, channel, "^1restore apply failed^7: {}".format(detail), loud=True)
            return minqlx.Return.STOP_ALL
        if sub == "verify":
            try:
                expected = restore_draft.draft_to_checkpoint(self._restore_draft)
            except (TypeError, ValueError) as exc:
                self._draft_tell(player, channel, "^1restore verify^7: {}".format(exc), loud=True)
                return minqlx.Return.STOP_ALL
            try:
                live, pair_errors = self._live_checkpoint_for_verify(
                    expected, self._restore_slot_remap
                )
            except (AttributeError, TypeError, ValueError) as exc:
                self._draft_tell(player, channel, "^1restore verify^7: export failed: {}".format(exc), loud=True)
                return minqlx.Return.STOP_ALL
            diffs = list(pair_errors)
            diffs.extend(restore_draft.compare_checkpoints(expected, live))
            if not diffs:
                self._draft_tell(player, channel, "^2restore verify OK^7", loud=True)
                return minqlx.Return.STOP_ALL
            self._draft_tell(
                player,
                channel,
                "^1restore verify FAIL^7 ({} diffs)".format(len(diffs)),
                loud=True,
            )
            if not self._restore_draft_quiet:
                for line in diffs[:8]:
                    self._reply(player, channel, "^7{}".format(line))
                if len(diffs) > 8:
                    self._reply(
                        player, channel, "^7… +{} more (see log)".format(len(diffs) - 8)
                    )
            self.logger.warning("restore verify diffs: %s", "; ".join(diffs))
            return minqlx.Return.STOP_ALL
        self._draft_tell(player, channel, "^1restore^7: unknown draft subcommand", loud=True)
        return minqlx.Return.STOP_ALL

    def _cmd_restore_draft_player(self, player, channel, tail):
        if len(tail) < 2:
            self._draft_tell(
                player,
                channel,
                "^1restore player^7: slot + field — bot | sid | nick | pos | vel | "
                "hp | armor | score | active weapon | weapon | ammo | powerup | dead",
                loud=True,
            )
            return minqlx.Return.STOP_ALL
        try:
            slot = int(str(tail[0]).strip())
        except (TypeError, ValueError):
            self._draft_tell(player, channel, "^1restore player^7: bad slot", loud=True)
            return minqlx.Return.STOP_ALL
        field = str(tail[1]).strip().lower()
        args = tail[2:]
        try:
            row = restore_draft.ensure_player_row(self._restore_draft, slot)
            if field == "bot":
                row["bot"] = 1
                self._draft_tell(player, channel, "^2restore player^7: slot {} bot".format(slot))
                return minqlx.Return.STOP_ALL
            if field == "sid":
                if not args:
                    raise ValueError("sid requires steam_id64")
                row["sid"] = str(args[0]).strip()
                self._draft_tell(
                    player, channel, "^2restore player^7: slot {} sid {}".format(slot, row["sid"])
                )
                return minqlx.Return.STOP_ALL
            if field == "nick":
                if not args:
                    raise ValueError("nick requires name")
                row["nick"] = " ".join(str(a) for a in args).strip()
                self._draft_tell(
                    player, channel, "^2restore player^7: slot {} nick {}".format(slot, row["nick"])
                )
                return minqlx.Return.STOP_ALL
            if field == "pos":
                if len(args) < 3:
                    raise ValueError("pos needs x y z")
                row["x"] = float(args[0])
                row["y"] = float(args[1])
                row["z"] = float(args[2])
                self._draft_tell(
                    player,
                    channel,
                    "^2restore player^7: slot {} pos {:.1f} {:.1f} {:.1f}".format(
                        slot, row["x"], row["y"], row["z"]
                    ),
                )
                return minqlx.Return.STOP_ALL
            if field == "vel":
                if len(args) < 3:
                    raise ValueError("vel needs vx vy vz")
                row["vx"] = int(float(args[0]))
                row["vy"] = int(float(args[1]))
                row["vz"] = int(float(args[2]))
                self._draft_tell(player, channel, "^2restore player^7: slot {} vel".format(slot))
                return minqlx.Return.STOP_ALL
            if field == "hp":
                if not args:
                    raise ValueError("hp needs value")
                row["h"] = int(args[0])
                self._draft_tell(
                    player, channel, "^2restore player^7: slot {} hp {}".format(slot, row["h"])
                )
                return minqlx.Return.STOP_ALL
            if field == "armor":
                if not args:
                    raise ValueError("armor needs value")
                row["a"] = int(args[0])
                self._draft_tell(
                    player, channel, "^2restore player^7: slot {} armor {}".format(slot, row["a"])
                )
                return minqlx.Return.STOP_ALL
            if field == "score":
                if not args:
                    raise ValueError("score needs value")
                row["sc"] = int(args[0])
                self._draft_tell(
                    player, channel, "^2restore player^7: slot {} score {}".format(slot, row["sc"])
                )
                return minqlx.Return.STOP_ALL
            if field == "active":
                # active weapon gl
                tokens = list(args)
                if tokens and str(tokens[0]).strip().lower() == "weapon":
                    tokens = tokens[1:]
                if not tokens:
                    raise ValueError("active weapon needs key (e.g. gl)")
                raw = str(tokens[0]).strip().lower()
                if raw.isdigit():
                    raise ValueError("use weapon key, not index (e.g. active weapon gl)")
                wkey = WEAPON_ALIAS.get(raw)
                if wkey not in WEAPON_KEYS or wkey == "hands":
                    raise ValueError(
                        "active weapon must be one of {}".format(",".join(WEAPON_KEYS[:-1]))
                    )
                row["w"] = WEAPON_KEYS.index(wkey) + 1
                self._draft_tell(
                    player,
                    channel,
                    "^2restore player^7: slot {} active weapon {}".format(slot, wkey),
                )
                return minqlx.Return.STOP_ALL
            if field == "weapon":
                if not args:
                    raise ValueError("weapon needs key [0|1]")
                key = WEAPON_ALIAS.get(str(args[0]).strip().lower())
                if key not in WEAPON_KEYS or key == "hands":
                    raise ValueError("weapon key must be one of {}".format(",".join(WEAPON_KEYS[:-1])))
                on = True
                if len(args) >= 2:
                    on = str(args[1]).strip().lower() not in ("0", "false", "no", "off")
                bit = weapon_key_bit(key)
                if bit is None:
                    raise ValueError("weapon key invalid")
                lo = int(row.get("lo") or 0)
                row["lo"] = (lo | bit) if on else (lo & ~bit) & 0xFFFF
                self._draft_tell(
                    player,
                    channel,
                    "^2restore player^7: slot {} weapon {}={}".format(slot, key, 1 if on else 0),
                )
                return minqlx.Return.STOP_ALL
            if field == "dead":
                row["dead"] = 0 if args and str(args[0]).strip() in ("0", "false", "no") else 1
                self._draft_tell(
                    player, channel, "^2restore player^7: slot {} dead {}".format(slot, row["dead"])
                )
                return minqlx.Return.STOP_ALL
            if field == "ammo":
                if len(args) < 2:
                    raise ValueError("ammo needs key count")
                key = str(args[0]).strip().lower()
                if key not in AMMO_KEYS:
                    raise ValueError("ammo key must be one of {}".format(",".join(AMMO_KEYS)))
                am = row.get("am")
                if not isinstance(am, dict):
                    am = {}
                    row["am"] = am
                am[key] = int(args[1])
                self._draft_tell(
                    player,
                    channel,
                    "^2restore player^7: slot {} ammo {}={}".format(slot, key, am[key]),
                )
                return minqlx.Return.STOP_ALL
            if field == "powerup":
                if len(args) < 2:
                    raise ValueError("powerup needs key seconds (quad|regen|bs|haste|invis|invuln)")
                alias = POWERUP_ALIAS.get(str(args[0]).strip().lower())
                if not alias:
                    raise ValueError("powerup key must be one of {}".format(",".join(POWERUP_KEYS)))
                sec = int(args[1])
                pw = row.get("pw")
                if not isinstance(pw, dict):
                    pw = {}
                    row["pw"] = pw
                if sec <= 0:
                    pw.pop(alias, None)
                else:
                    pw[alias] = sec
                self._draft_tell(
                    player,
                    channel,
                    "^2restore player^7: slot {} powerup {}={}".format(slot, alias, sec),
                )
                return minqlx.Return.STOP_ALL
            self._draft_tell(player, channel, "^1restore player^7: unknown field {}".format(field), loud=True)
        except ValueError as exc:
            self._draft_tell(player, channel, "^1restore player^7: {}".format(exc), loud=True)
        return minqlx.Return.STOP_ALL

    def _parse_item_draft_from_tail(self, tail):
        return restore_draft.parse_item_draft_line(
            tail,
            int(self._restore_draft.get("t_ms") or 0),
            resolve_alias=self._draft_resolve_item_eid,
            find_spawn=self._find_bundled_spawn,
            parse_time_arg=self._parse_match_time_arg,
        )

    def _cmd_restore_draft_item(self, player, channel, tail):
        if len(tail) < 2:
            self._draft_tell(
                player,
                channel,
                "^1restore item^7: <classname> [pos x y z] pending <at_ms|in sec> | hidden",
                loud=True,
            )
            return minqlx.Return.STOP_ALL
        try:
            item = self._parse_item_draft_from_tail(tail)
            restore_draft.append_item(self._restore_draft, item)
            label = item.get("cn") or item.get("k") or item.get("eid")
            self._draft_tell(
                player,
                channel,
                "^2restore item^7: {} s={} at_ms={}".format(
                    label, item.get("s"), item.get("at_ms", "-")
                ),
            )
        except ValueError as exc:
            self._draft_tell(player, channel, "^1restore item^7: {}".format(exc), loud=True)
        return minqlx.Return.STOP_ALL

    def _cmd_restore_export(self, player, channel):
        try:
            cp = self._build_checkpoint_export()
        except (AttributeError, TypeError, ValueError) as exc:
            self.logger.exception("restore export failed")
            self._reply(player, channel, "^1export failed^7: {}".format(exc))
            return minqlx.Return.STOP_ALL
        n_players = len(cp.get("players") or [])
        n_items = len(cp.get("items") or [])
        n_pending = sum(1 for it in (cp.get("items") or []) if int(it.get("s", 1)) == 2)
        t_ms = cp.get("t_ms", 0)
        t_sec = int(t_ms) / 1000.0
        self._reply(
            player,
            channel,
            "^2restore export^7: {} players, {} items ({} pending), t={}ms ({:.1f}s). "
            "JSON in server log.".format(n_players, n_items, n_pending, t_ms, t_sec),
        )
        self.logger.info(
            "match_restore export players=%s items=%s t_ms=%s",
            n_players,
            n_items,
            t_ms,
        )
        self.logger.info(
            "match_restore export json=%s",
            json.dumps(cp, separators=(",", ":"), sort_keys=True),
        )
        return minqlx.Return.STOP_ALL

    @staticmethod
    def _read_weapon_idx(player):
        try:
            w = player.weapon
            if w is not None:
                return int(w)
        except (AttributeError, TypeError, ValueError):
            pass
        try:
            state = getattr(player, "state", None)
            if state is not None:
                return int(getattr(state, "weapon", 0) or 0)
        except (AttributeError, TypeError, ValueError):
            pass
        return 0

    def _player_respawn_remaining_ms(self, player):
        """Ms left on a dead player's gclient_t.respawnTime - the real respawn
        gate the game module checks against level.time (GameClient(n).respawn_time,
        offset +1252 on gclient_t per engine_fields.h GAMECLIENT_FIELDS; read-write).
        Not the same field as GameClient(n).ps.respawn_time (playerState_t +512,
        confirmed live 2026-09-22 to just be a HUD-facing mirror that reads back
        0 during a real death - writing there has no effect on when the engine
        actually lets the player respawn). None when unreadable (vm not ready,
        freed slot)."""
        level_ms = self._native_map_time_ms()
        if level_ms is None:
            return None
        try:
            client = minqlx.Entity(int(player.id)).client
            if client is None:
                return None
            respawn_at = int(client.respawn_time)
        except (AttributeError, TypeError, ValueError, minqlx.EngineStateError):
            return None
        return max(0, respawn_at - int(level_ms))

    def _compute_respawn_at_ms(self, respawn_in_ms):
        """Absolute level.time deadline for `respawn_in_ms` from right now, or
        None. Callers compute this ONCE per restore-apply and thread the
        absolute value through to any delayed reassert - recomputing
        `level.time + respawn_in_ms` again later (using a later "now") would
        silently push the deadline further out by however long the reassert
        waited, defeating the whole point of restoring the remaining time."""
        if respawn_in_ms is None:
            return None
        level_ms = self._native_map_time_ms()
        if level_ms is None:
            return None
        return int(level_ms) + max(0, int(respawn_in_ms))

    def _set_player_respawn_at_ms(self, target, respawn_at_ms):
        """Overwrite gclient_t.respawnTime (see _player_respawn_remaining_ms)
        with an absolute level.time deadline, so a restored dead player becomes
        eligible to respawn after the time already elapsed in the recorded
        match, not a fresh full g_respawn_delay_min/max window starting at the
        restore moment (target.is_alive=False slays for real via
        slay_with_mod(), and the engine sets its own fresh deadline as part of
        that death)."""
        try:
            client = minqlx.Entity(int(target.id)).client
            if client is None:
                return False
            client.respawn_time = int(respawn_at_ms)
        except (AttributeError, TypeError, ValueError, minqlx.EngineStateError) as exc:
            self.logger.warning(
                "match_restore: set respawn_time cid=%s failed: %s",
                getattr(target, "id", "?"),
                exc,
            )
            return False
        return True

    def _export_player_checkpoint_row(self, player, slot_cid=None):
        if not self._player_exportable(player):
            return None
        pos = self._export_player_position(player)
        if not pos or len(pos) < 3:
            return None
        row = {
            "cid": int(slot_cid if slot_cid is not None else player.id),
            "x": round(float(pos[0]), COORD_DECIMALS),
            "y": round(float(pos[1]), COORD_DECIMALS),
            "z": round(float(pos[2]), COORD_DECIMALS),
            "h": int(getattr(player, "health", 0) or 0),
            "a": int(getattr(player, "armor", 0) or 0),
            "w": self._read_weapon_idx(player),
            "lo": self._export_loadout_mask(player),
        }
        if not getattr(player, "is_alive", True):
            row["dead"] = 1
            ri = self._player_respawn_remaining_ms(player)
            if ri is not None:
                row["ri"] = ri
        steam = getattr(player, "steam_id", None)
        if steam:
            row["sid"] = str(steam)
        vel = self._export_velocity(player)
        if vel:
            row.update(vel)
        ammo = self._export_ammo(player)
        if ammo:
            row["am"] = ammo
        sc = self._export_player_score(player)
        if sc is not None:
            row["sc"] = sc
        pw = self._export_powerups(player)
        if pw:
            row["pw"] = pw
        return row

    def _live_checkpoint_for_verify(self, expected, slot_remap=None):
        """Align live export player rows to draft slots (same pairing as apply)."""
        live = self._build_checkpoint_export()
        pair_errors = []
        try:
            pairs = self._pair_players_for_restore(
                expected.get("players") or [],
                slot_remap=dict(slot_remap or {}),
            )
        except ValueError as exc:
            pair_errors.append(str(exc))
            return live, pair_errors
        aligned = []
        for slot_row, target in pairs:
            row = self._export_player_checkpoint_row(
                target, slot_cid=int(slot_row.get("cid", 0) or 0)
            )
            if row:
                aligned.append(row)
        if aligned:
            live = dict(live)
            live["players"] = aligned
        return live, pair_errors

    def _build_checkpoint_export(self):
        if self._sv_paused_active():
            self._refresh_pause_frozen_ms()
        else:
            self._track_match_clock()
        players = []
        for p in self.players():
            row = self._export_player_checkpoint_row(p)
            if row:
                players.append(row)
        map_key = self._map_key()
        items = self._export_items_checkpoint()
        return canonicalize(
            {
                "v": 2,
                "t_ms": self._export_match_time_ms(),
                "map": map_key,
                "players": players,
                "items": items,
                "drops": self._export_drops_checkpoint(),
            }
        )

    def _export_drops_checkpoint(self):
        """`drops` rows for every item lying on the floor after a death.

        The engine marks those FL_DROPPED_ITEM and frees them again on their
        own think, so they are neither in the map spawn table nor addressable
        by a spawn point - position plus remaining think is all there is.
        """
        if not hasattr(minqlx, "entities"):
            return []
        level_ms = self._native_map_time_ms()
        if level_ms is None:
            return []
        rows = []
        for ent in self._iter_dropped_item_entities():
            row = self._export_drop_row(ent, level_ms)
            if row is not None:
                rows.append(row)
        return rows

    def _iter_dropped_item_entities(self):
        """Live FL_DROPPED_ITEM item entities (death drops, thrown holdables)."""
        try:
            ents = list(minqlx.entities(inuse=True, etype=_ET_ITEM))
        except (AttributeError, TypeError, ValueError, _ENGINE_ERR) as exc:
            self.logger.warning("match_restore: drop scan failed: %s", exc)
            return []
        out = []
        for ent in ents:
            try:
                if int(ent.flags) & _FL_DROPPED_ITEM:
                    out.append(ent)
            except (AttributeError, TypeError, ValueError, _ENGINE_ERR):
                continue
        return out

    def _export_drop_row(self, ent, level_ms):
        try:
            idx = int(ent.s.modelindex)
            pos = ent.r.current_origin
            x, y, z = float(pos[0]), float(pos[1]), float(pos[2])
            nextthink = int(ent.nextthink)
        except (AttributeError, IndexError, TypeError, ValueError, _ENGINE_ERR):
            return None
        if idx <= 0:
            return None
        # nextthink is G_FreeEntity's deadline on level.time's clock, so the
        # remaining life is exact - no guessing from when the drop happened.
        ttl = nextthink - int(level_ms) if nextthink > 0 else DROP_LIFETIME_MS
        row = {"i": idx, "x": x, "y": y, "z": z, "ttl": ttl}
        cn = BG_ITEM_CLASSNAMES.get(idx)
        if cn:
            row["cn"] = cn
        return row

    def _export_items_checkpoint(self):
        rows = self._map_spawns_table()
        now_ms = self._export_match_time_ms()
        items = []
        seen = set()
        for alias, meta in rows.items():
            if alias in ("mh",) or meta.get("entity_id") in seen:
                continue
            seen.add(meta.get("entity_id"))
            row = self._export_item_row(alias, meta, now_ms)
            if int(row.get("s", 1)) == 1:
                continue
            try:
                row["eid"] = int(meta.get("entity_id"))
            except (TypeError, ValueError):
                pass
            items.append(row)
        return items

    def _export_item_row(self, alias, meta, now_ms):
        if match_restore_items is not None:
            return match_restore_items.export_item_row(
                alias,
                meta,
                int(now_ms),
                wall_now=time.time(),
                bundled_pickup=None,
                map_key=self._map_key() or "",
            )
        return {"k": alias, "s": 1}

    @staticmethod
    def _export_player_score(player):
        try:
            sc = getattr(player, "score", None)
            if sc is not None:
                return int(sc)
        except (TypeError, ValueError, AttributeError):
            pass
        stats = getattr(player, "stats", None)
        if stats is not None:
            try:
                return int(getattr(stats, "score", 0) or 0)
            except (TypeError, ValueError, AttributeError):
                pass
        return None

    @staticmethod
    def _player_exportable(player):
        try:
            if getattr(player, "team", None) == "spectator":
                return False
        except (AttributeError, TypeError):
            pass
        return True

    def _export_player_position(self, player):
        try:
            pos = player.position
            if pos and len(pos) >= 3:
                return pos
        except (AttributeError, TypeError, ValueError):
            pass
        state = getattr(player, "state", None)
        if state is None:
            return None
        for attr in ("origin", "pos"):
            raw = getattr(state, attr, None)
            if raw is not None and len(raw) >= 3:
                try:
                    return (float(raw[0]), float(raw[1]), float(raw[2]))
                except (TypeError, ValueError, IndexError):
                    continue
        return None

    def _export_loadout_mask(self, player):
        try:
            state = getattr(player, "state", None)
            weapons = getattr(state, "weapons", None) if state else None
            if weapons is None:
                return 0
            weapon_order = (
                "g", "mg", "sg", "gl", "rl", "lg", "rg", "pg",
                "bfg", "gh", "ng", "pl", "cg", "hmg", "hands",
            )
            kwargs = {}
            for idx, key in enumerate(weapon_order):
                try:
                    kwargs[key] = bool(weapons[idx])
                except (TypeError, IndexError):
                    kwargs[key] = False
            return loadout_to_mask(kwargs)
        except (AttributeError, TypeError, ValueError):
            return 0

    @staticmethod
    def _export_velocity(player):
        try:
            state = getattr(player, "state", None)
            vel = getattr(state, "velocity", None) if state else None
            if vel is None or len(vel) < 3:
                return None
            return {
                "vx": int(round(float(vel[0]))),
                "vy": int(round(float(vel[1]))),
                "vz": int(round(float(vel[2]))),
            }
        except (AttributeError, TypeError, ValueError):
            return None

    @staticmethod
    def _export_ammo(player):
        try:
            state = getattr(player, "state", None)
            ammo = getattr(state, "ammo", None) if state else None
            if ammo is None:
                return None
            out = {}
            for key in AMMO_KEYS:
                try:
                    val = getattr(ammo, key, None)
                    if val is not None:
                        out[key] = int(val)
                except (TypeError, ValueError, AttributeError):
                    continue
            return out or None
        except (AttributeError, TypeError, ValueError):
            return None

    @staticmethod
    def _export_powerups(player):
        """Remaining powerup SECONDS for the checkpoint `pw` field.

        `Player.powerups` (v1.0.0 property) reads milliseconds, but `pw` is a seconds
        field everywhere else: codec.py's `normalize_powerups` treats it as seconds,
        and the operator `!restore <player> <slot> powerup quad 30` draft path writes
        seconds directly. Convert ms -> sec here so both producers of `pw` agree; see
        `_apply_powerups` which converts back to ms (`sec * 1000`) on the way in.
        """
        try:
            pu = player.powerups
        except (AttributeError, TypeError, ValueError):
            return None
        mapping = (
            ("quad", "quad"),
            ("regeneration", "regen"),
            ("battlesuit", "bs"),
            ("haste", "haste"),
            ("invisibility", "invis"),
            ("invulnerability", "invuln"),
        )
        out = {}
        for attr, alias in mapping:
            try:
                remaining_ms = int(getattr(pu, attr, 0) or 0)
            except (TypeError, ValueError, AttributeError):
                remaining_ms = 0
            remaining_sec = remaining_ms // 1000
            if remaining_sec > 0:
                out[alias] = remaining_sec
        return out or None

    def _resolve_player_from_row(self, row, allow_cid_live=True):
        sid = row.get("sid")
        if sid:
            want = str(sid).strip()
            for p in self.players():
                if str(getattr(p, "steam_id", "") or "") == want:
                    return p
        nick = row.get("nick") or row.get("nickname")
        if nick:
            for p in self.players():
                live = self._player_display_name(p)
                if live and restore_draft.names_match(nick, live):
                    return p
        if allow_cid_live:
            cid = row.get("cid")
            if cid is not None:
                try:
                    return self.player(int(cid))
                except (AttributeError, TypeError, ValueError, minqlx.NonexistentPlayerError):
                    pass
        return None

    @staticmethod
    def _is_bot_player(player):
        sid = str(getattr(player, "steam_id", "") or "")
        return sid.startswith("9")

    def _pair_players_for_restore(self, player_rows, slot_remap=None):
        rows = sorted(
            player_rows,
            key=lambda row: int(row.get("cid", row.get("client_id", 0)) or 0),
        )
        slot_remap = dict(slot_remap or {})
        if slot_remap:
            pairs = []
            for row in rows:
                slot = int(row.get("cid", 0) or 0)
                if slot in slot_remap:
                    try:
                        target = self.player(int(slot_remap[slot]))
                    except (AttributeError, TypeError, ValueError, minqlx.NonexistentPlayerError):
                        target = None
                    if target is None:
                        raise ValueError(
                            "slot remap {} -> client {} not found".format(slot, slot_remap[slot])
                        )
                else:
                    target = self._resolve_player_from_row(row, allow_cid_live=False)
                    if target is None:
                        raise ValueError(
                            "player slot={} sid={} nick={} not matched (use restore players slot:cid)".format(
                                slot, row.get("sid"), row.get("nick")
                            )
                        )
                pairs.append((row, target))
            return pairs

        live = [p for p in self.players() if self._player_exportable(p)]
        bots = [p for p in live if self._is_bot_player(p)]
        humans = [p for p in live if not self._is_bot_player(p)]
        if len(rows) == 2 and len(bots) == 1 and len(humans) == 1:
            flagged = [r for r in rows if r.get("bot")]
            if len(flagged) == 1:
                bot_row = flagged[0]
                human_row = next(r for r in rows if r is not bot_row)
            else:
                # Neither row is flagged "bot" (a real qlmatch pack never sets
                # it - both recorded players were human) - the connected live
                # human matches exactly one of the two recorded rows by
                # sid/nick; the other row is the one the sparring bot stands
                # in for. Used to sort by "sc" (score) instead and assume
                # higher score = human - harmless while every row's score was
                # always unset/0 (stable sort, arbitrary but consistent), but
                # a real regression once checkpoint rows carry real scores
                # (see score_at()): whichever recorded player was winning
                # became "the human" regardless of actual identity.
                matched = [
                    row for row in rows
                    if self._resolve_player_from_row(row, allow_cid_live=False) is humans[0]
                ]
                if len(matched) != 1:
                    raise ValueError(
                        "cannot tell which recorded slot is the connected human "
                        "(sid/nick match ambiguous or none) - use restore players slot:cid"
                    )
                human_row = matched[0]
                bot_row = next(r for r in rows if r is not human_row)
            return [(human_row, humans[0]), (bot_row, bots[0])]

        pairs = []
        for row in rows:
            target = self._resolve_player_from_row(row, allow_cid_live=True)
            if target is None:
                raise ValueError(
                    "player cid={} sid={} not found".format(row.get("cid"), row.get("sid"))
                )
            pairs.append((row, target))
        return pairs

    def _ensure_restore_paused(self, caller):
        if self._sv_paused_active():
            return True, None
        try:
            minqlx.console_command("pause")
        except (AttributeError, TypeError):
            pass
        if restore_util is not None:
            really_paused = restore_util.raw_paused(self)
            state = self._effective_match_state()
            if not restore_util.accept_console_pause(really_paused, state):
                return False, (
                    "pause command had no effect (match in warmup/practice? "
                    "^3!pause^7 manually first, then retry restore)"
                )
            if not really_paused:
                self.logger.info(
                    "match_restore: console pause; cvars still 0 "
                    "(state=%s) — latching pause intent",
                    state,
                )
            restore_util.set_pause_latch(True)
        else:
            really_paused = self._sv_paused_active()
            if not really_paused:
                return False, (
                    "pause command had no effect (match in warmup/practice? "
                    "^3!pause^7 manually first, then retry restore)"
                )
        if caller is not None:
            caller.tell("^2restore^7: paused for checkpoint apply.")
        return True, None

    @staticmethod
    def _item_checkpoint_alias(item):
        key = str((item or {}).get("k") or "").strip().lower()
        if key:
            return key
        try:
            eid = int((item or {}).get("eid"))
        except (TypeError, ValueError):
            return ""
        return "e{}".format(eid)

    def _spawn_meta_from_checkpoint_item(self, item):
        """Merge checkpoint item row with bundled spawn table; prefer draft cn/coords."""
        item = item or {}
        alias = self._item_checkpoint_alias(item)
        spawn_meta = self._lookup_spawn_meta(alias)
        if not spawn_meta:
            try:
                table_id = int(item.get("eid"))
                spawn_meta = self._lookup_spawn_meta("e{}".format(table_id))
                if spawn_meta:
                    alias = "e{}".format(table_id)
            except (TypeError, ValueError):
                spawn_meta = None
        cn = str(item.get("cn") or "").strip()
        x = self._num(item.get("x"))
        y = self._num(item.get("y"))
        z = self._num(item.get("z"))
        if cn and x is not None and y is not None and z is not None:
            found_alias, found_meta = self._find_bundled_spawn(cn, x, y, z)
            if found_meta:
                spawn_meta = found_meta
                alias = found_alias or alias
        elif spawn_meta is None and cn and x is not None and y is not None and z is not None:
            found_alias, found_meta = self._find_bundled_spawn(cn, x, y, z)
            if found_meta:
                spawn_meta = found_meta
                alias = found_alias or alias
        if not spawn_meta:
            return alias, None, cn
        meta = dict(spawn_meta)
        if cn:
            meta["classname"] = cn
        if x is not None:
            meta["x"] = float(x)
        if y is not None:
            meta["y"] = float(y)
        if z is not None:
            meta["z"] = float(z)
        classname = str(
            meta.get("classname") or cn or ITEM_ALIASES.get(str(alias).lower(), alias) or ""
        ).strip()
        return alias, meta, classname

    def _apply_checkpoint(self, caller, cp, slot_remap=None, phase="all"):
        map_key = self._map_key()
        cp_map = str(cp.get("map") or "")
        if cp_map and map_key and cp_map != map_key:
            return False, "map mismatch checkpoint={} server={}".format(cp_map, map_key)
        crc = cp.get("map_crc32")
        if crc is not None and map_key:
            try:
                if int(crc) != int(map_crc32(map_key)):
                    return False, "map crc mismatch (checkpoint crc={} server={})".format(
                        int(crc), map_crc32(map_key)
                    )
            except (TypeError, ValueError):
                pass
        self._begin_restore_session()
        self._restore_hold_until_unpause = True
        self._restore_apply_active = True
        self._restore_pause_pending = False
        try:
            ok, detail = self._apply_checkpoint_body(
                caller, cp, slot_remap=slot_remap, phase=phase
            )
            if not ok and not self._restore_pause_pending:
                self._abort_restore_session(detail)
            return ok, detail
        except Exception:
            self._abort_restore_session("exception")
            raise
        finally:
            self._restore_apply_active = False

    def _apply_checkpoint_body(self, caller, cp, slot_remap=None, phase="all"):
        phase = str(phase or "all").strip().lower()
        if phase not in _RESTORE_PHASES:
            return False, "unknown phase {}".format(phase)
        checkpoint_t_ms = int(cp.get("t_ms") or 0)
        parts = ["phase={}".format(phase)]
        time_ok = True
        time_detail = None
        live_hud = False
        items_failure_detail = None

        if phase in ("all", "time", "players", "items"):
            live_hud = self._restore_ensure_live_for_hud()

        try:
            if phase in ("all", "time"):
                time_ok, time_detail = self._restore_phase_time(checkpoint_t_ms)
                if time_detail:
                    parts.append(time_detail)
                if time_ok is False:
                    return False, time_detail or "time phase failed"

            n_players = 0
            if phase in ("all", "players"):
                n_players, player_detail = self._restore_phase_player_state(
                    cp, slot_remap=slot_remap
                )
                if player_detail:
                    parts.append(player_detail)
                if n_players < 0:
                    return False, player_detail

            n_items = 0
            pending = 0
            n_drops = 0
            if phase in ("all", "items"):
                if self._restore_engine_timer_active():
                    self._restore_prep_checkpoint_slots(cp)
                n_items, pending, item_detail = self._restore_phase_items(cp, checkpoint_t_ms)
                if item_detail:
                    parts.append(item_detail)
                # Drops are their own entities, never a map slot, so they run
                # after the slot work and can't be starved by an item that
                # failed to resolve its runtime entity.
                n_drops, drop_detail = self._restore_phase_drops(cp)
                if drop_detail:
                    parts.append(drop_detail)
                if n_items < 0:
                    # Don't abort before the pause below: an item lookup
                    # failure must not also cost the operator the match
                    # pause. Record it and let HUD/pause/kinematics still
                    # run; the overall restore is still reported as failed.
                    items_failure_detail = item_detail

            # HUD must refresh while unpaused (before final pause).
            if phase in ("all", "items", "players"):
                self._refresh_match_timer_hud(checkpoint_t_ms)

            if phase in ("all", "items", "players"):
                # Same-tick unpause+write+pause never lets SV_Frame send the
                # teleport snapshot; other clients only saw the opponent
                # after a later unpause. Hold live for a couple of frames.
                hud_flag = live_hud
                live_hud = False
                self._restore_pause_pending = True
                self._schedule_after_frames(
                    RESTORE_SNAPSHOT_FRAMES,
                    lambda: self._finish_restore_pause_kinematics(
                        caller, cp, slot_remap, phase, hud_flag,
                        items_failure_detail,
                    ),
                )

            if items_failure_detail is not None:
                return False, items_failure_detail
        finally:
            if live_hud:
                # live_hud is only still truthy here when we exited (return,
                # or an uncaught exception) before the "hand off to the
                # deferred _finish_restore_pause_kinematics re-pause" step
                # above, which is the only thing that otherwise re-pauses.
                # _restore_ensure_live_for_hud() had briefly unpaused an
                # ALREADY-paused match (e.g. the operator is dialing in the
                # right moment across several restore attempts) so the HUD
                # would refresh - real bug, confirmed 2026-09-22: an attempt
                # that failed validation (bad time, a player pairing miss)
                # left the match live with no re-pause at all, so "one more
                # restore to adjust the moment" silently unpaused the match.
                self._restore_cancel_live_hud_hooks()
                repause_ok, repause_detail = self._ensure_restore_paused(None)
                if not repause_ok:
                    self.logger.warning(
                        "match_restore: re-pause after a failed restore attempt failed: %s",
                        repause_detail,
                    )

        summary_bits = []
        if phase in ("all", "time"):
            summary_bits.append("t={}ms".format(checkpoint_t_ms))
        if phase in ("all", "players"):
            summary_bits.append("{} players".format(n_players))
        if phase in ("all", "items"):
            item_summary = "{} items".format(n_items)
            if pending:
                item_summary += ", {} pending".format(pending)
            if n_drops:
                item_summary += ", {} drops".format(n_drops)
            summary_bits.append(item_summary)
        summary = ", ".join(summary_bits) if summary_bits else phase
        self.logger.info(
            "match_restore restore phase=%s summary=%s detail=%s",
            phase,
            summary,
            "; ".join(parts),
        )
        return True, summary

    def _finish_restore_pause_kinematics(
        self, caller, cp, slot_remap, phase, live_hud, items_failure_detail
    ):
        """Pause + kinematics after teleport snapshots have gone out."""
        self._restore_pause_pending = False
        try:
            if phase in ("all", "items", "players"):
                ok_pause, pause_detail = self._ensure_restore_paused(caller)
                if not ok_pause:
                    if caller is not None:
                        try:
                            caller.tell("^1restore^7: {}".format(pause_detail))
                        except (AttributeError, TypeError, ValueError):
                            pass
                    self.logger.warning(
                        "match_restore: deferred pause failed: %s", pause_detail
                    )
                    return
            if phase in ("all", "players"):
                n_kin, kin_detail = self._restore_phase_player_kinematics(
                    cp, slot_remap=slot_remap
                )
                if kin_detail:
                    self.logger.info(
                        "match_restore restore phase=player_kinematics deferred %s",
                        kin_detail,
                    )
                if n_kin < 0:
                    if caller is not None:
                        try:
                            caller.tell(
                                "^1restore^7: kinematics failed: {}".format(kin_detail)
                            )
                        except (AttributeError, TypeError, ValueError):
                            pass
                    return
            if phase in ("all", "items", "players"):
                self._end_restore_session()
        except Exception:
            self.logger.exception("match_restore: deferred pause/kinematics failed")
        finally:
            if live_hud:
                self._restore_cancel_live_hud_hooks()

    def _refresh_match_timer_hud(self, t_ms):
        """Push setmatchtime to clients (must run unpaused for visible HUD)."""
        try:
            elapsed_sec = max(0, int(t_ms) // 1000)
        except (TypeError, ValueError):
            return False
        try:
            cmd_arg = str(int(elapsed_sec))
            if hasattr(minqlx.Game, "setmatchtime"):
                minqlx.Game.setmatchtime(cmd_arg)
            else:
                minqlx.console_command("setmatchtime {}".format(cmd_arg))
            self.logger.info(
                "match_restore: hud setmatchtime %ss (t_ms=%s paused=%s)",
                elapsed_sec,
                int(t_ms),
                self._sv_paused_active(),
            )
            return True
        except (AttributeError, TypeError, ValueError) as exc:
            self.logger.warning("match_restore: setmatchtime hud failed: %s", exc)
            return False

    def _restore_phase_time(self, checkpoint_t_ms):
        ms = max(0, int(checkpoint_t_ms))
        self._restore_clock_latch_ms = ms
        self._pause_frozen_ms = ms
        ok, detail = self._apply_match_time(
            ms, force_hud=True, restore_apply=True
        )
        if ok:
            self._refresh_match_timer_hud(ms)
        self.logger.info(
            "match_restore restore phase=time t_ms=%s ok=%s latch=%s %s",
            ms,
            ok,
            self._restore_clock_latch_ms,
            detail,
        )
        return ok, detail

    def _restore_phase_player_state(self, cp, slot_remap=None):
        """Position + vitals + inventory while unpaused (HUD visible before pause)."""
        n_players = 0
        parts = []
        try:
            pairs = self._pair_players_for_restore(
                cp.get("players") or [],
                slot_remap=slot_remap,
            )
        except ValueError as exc:
            return -1, str(exc)
        for row, target in pairs:
            payload = self._strip_dead_player_inventory(dict(row))
            payload["loadout"] = mask_to_loadout(
                normalize_loadout_mask(payload.get("lo", 0), payload.get("w"))
            )
            if isinstance(payload.get("am"), dict):
                payload["ammo"] = payload["am"]
            ok, detail = self._apply_player_snapshot(
                target, payload, state_only=True
            )
            if not ok:
                return -1, "player {} state: {}".format(row.get("cid"), detail)
            n_players += 1
            parts.append("p{}".format(getattr(target, "id", row.get("cid"))))
        detail = "{} state ({})".format(n_players, ",".join(parts)) if parts else "0 state"
        self.logger.info("match_restore restore phase=player_state %s", detail)
        return n_players, detail

    def _restore_phase_player_kinematics(self, cp, slot_remap=None):
        n_players = 0
        parts = []
        try:
            pairs = self._pair_players_for_restore(
                cp.get("players") or [],
                slot_remap=slot_remap,
            )
        except ValueError as exc:
            return -1, str(exc)
        restore_cids = set()
        for row, target in pairs:
            restore_cids.add(int(target.id))
        if restore_cids:
            self._position_apply_queue = [
                job
                for job in self._position_apply_queue
                if int(job.get("client_id", -1)) not in restore_cids
            ]
        for row, target in pairs:
            payload = dict(row)
            ok, detail = self._apply_player_snapshot(
                target, payload, kinematics_only=True, velocity_only=True
            )
            if not ok:
                return -1, "player {} kinematics: {}".format(row.get("cid"), detail)
            n_players += 1
            parts.append("p{}".format(getattr(target, "id", row.get("cid"))))
        detail = "{} kinematics ({})".format(n_players, ",".join(parts)) if parts else "0 kinematics"
        self.logger.info("match_restore restore phase=player_kinematics %s", detail)
        return n_players, detail

    @staticmethod
    def _checkpoint_loadout_includes_weapon(cp, weapon_alias):
        alias = str(weapon_alias or "").strip().lower()
        if alias not in WEAPON_KEYS or alias == "hands":
            return False
        for row in (cp or {}).get("players") or []:
            try:
                lo = int(row.get("lo", 0) or 0)
            except (TypeError, ValueError):
                continue
            if alias in mask_to_loadout(lo):
                return True
        return False

    def _restore_phase_items(self, cp, checkpoint_t_ms):
        # One item failing to resolve a runtime entity (moved/despawned,
        # stale spawn table, ...) must not cost every OTHER item in the
        # list its restore - previously this bailed out on the first
        # failure, so anything later in cp["items"] (e.g. mega) silently
        # kept its default "available" state instead of being touched at
        # all. Apply every item regardless, then report failure/detail.
        touch_cid = self._restore_touch_client_id(cp)
        n_items = 0
        pending = 0
        aliases = []
        failed_aliases = []
        for item in cp.get("items") or []:
            ok, alias = self._apply_item_checkpoint(
                item, checkpoint_t_ms, cp=cp, touch_cid=touch_cid,
            )
            if not ok:
                failed_aliases.append(
                    self._item_checkpoint_alias(item) or item.get("eid")
                )
                continue
            n_items += 1
            aliases.append(alias)
            if int(item.get("s", 1)) == 2:
                pending += 1
        detail = "{} items".format(n_items)
        if pending:
            detail += ", {} engine pending".format(pending)
        if failed_aliases:
            detail += ", {} failed ({})".format(
                len(failed_aliases), ",".join(str(a) for a in failed_aliases[:12])
            )
        self.logger.info(
            "match_restore restore phase=items t_ms=%s mode=touch_vanilla %s aliases=%s",
            checkpoint_t_ms,
            detail,
            ",".join(aliases[:12]),
        )
        if failed_aliases:
            return -1, pending, detail
        return n_items, pending, detail

    def _restore_phase_drops(self, cp):
        """Death drops: wipe the floor, then relaunch the checkpoint's own.

        Nothing here goes through the map spawn table - a drop is a plain
        FL_DROPPED_ITEM entity the engine created at whatever spot the item
        happened to land, so there is no slot to hide/show, only entities to
        free and entities to make.
        """
        rows = cp.get("drops")
        if rows is None:
            # Checkpoint written before drops were part of the format: it has
            # no opinion about what is lying on the floor, so don't sweep it.
            return 0, None
        if not hasattr(minqlx, "drop_item"):
            return 0, "drops skipped (runtime has no drop_item)"
        cleared = self._clear_dropped_items()
        if not rows:
            return 0, "drops cleared={}".format(cleared)
        level_ms = self._native_map_time_ms()
        touch_cid = self._restore_touch_client_id(cp)
        made = 0
        failed = 0
        for row in rows:
            if self._spawn_checkpoint_drop(row, level_ms, touch_cid):
                made += 1
            else:
                failed += 1
        detail = "{} drops (cleared {})".format(made, cleared)
        if failed:
            detail += ", {} failed".format(failed)
        self.logger.info(
            "match_restore restore phase=drops %s cid=%s", detail, touch_cid
        )
        return made, detail

    def _clear_dropped_items(self):
        """Free every live drop; count of what was there."""
        ents = self._iter_dropped_item_entities()
        if not ents:
            return 0
        if hasattr(minqlx, "remove_dropped_items"):
            try:
                minqlx.remove_dropped_items()
                return len(ents)
            except (AttributeError, TypeError, ValueError, _ENGINE_ERR) as exc:
                self.logger.warning("match_restore: remove_dropped_items: %s", exc)
        removed = 0
        for ent in ents:
            try:
                if minqlx.remove_entity(int(ent.number)) is not False:
                    removed += 1
            except (AttributeError, TypeError, ValueError, _ENGINE_ERR):
                continue
        return removed

    def _spawn_checkpoint_drop(self, row, level_ms, client_id):
        try:
            idx = int(row.get("i") or 0)
            x = float(row["x"])
            y = float(row["y"])
            z = float(row["z"])
        except (KeyError, TypeError, ValueError):
            return False
        if idx <= 0:
            return False
        try:
            ttl = int(row.get("ttl", DROP_LIFETIME_MS))
        except (TypeError, ValueError):
            ttl = DROP_LIFETIME_MS
        ttl = max(DROP_MIN_TTL_MS, min(DROP_LIFETIME_MS, ttl))
        # Drop_Item is the only way to a *real* drop: it is what sets
        # FL_DROPPED_ITEM and the G_FreeEntity think that makes the item
        # expire instead of respawning forever. spawn_item() deliberately
        # clears both, so it would leave a permanent ghost item behind.
        try:
            eid = minqlx.drop_item(int(client_id), idx, 0.0)
        except (AttributeError, TypeError, ValueError, _ENGINE_ERR) as exc:
            self.logger.warning("match_restore: drop_item item=%s: %s", idx, exc)
            return False
        if eid is None:
            return False
        return self._place_dropped_item(int(eid), x, y, z, ttl, level_ms)

    def _place_dropped_item(self, eid, x, y, z, ttl_ms, level_ms):
        """Move a just-launched drop onto its checkpoint spot and stop it there.

        Drop_Item throws the item away from the player on a TR_GRAVITY arc; the
        checkpoint already knows where it came to rest, so pin it stationary
        rather than letting it re-simulate into a different spot.
        """
        ent = _stock_item_entity(eid)
        if ent is None:
            return False
        pos = (x, y, z)
        try:
            ent.s.pos_type = _TR_STATIONARY
            ent.s.pos_time = 0
            ent.s.pos_duration = 0
            ent.s.pos_base = pos
            ent.s.pos_delta = (0.0, 0.0, 0.0)
            ent.s.origin = pos
            # A settled item stands on the world (entity 0). G_RunItem turns
            # anything with groundEntityNum -1 back into a falling
            # TR_GRAVITY entity, which would undo the pinning above.
            ent.s.ground_entity_num = 0
            ent.r.current_origin = pos
            if level_ms is not None:
                ent.nextthink = int(level_ms) + int(ttl_ms)
            minqlx.link_entity(eid)
        except (AttributeError, TypeError, ValueError, _ENGINE_ERR) as exc:
            self.logger.warning("match_restore: place drop e%s: %s", eid, exc)
            return False
        return True

    def _read_level_time_ms(self):
        if self._awaiting_post_unpause_unfreeze():
            return max(0, int(self._unfreeze_hold_ms or 0))
        if self._sv_paused_active():
            if self._restore_clock_latch_ms is not None:
                return max(0, int(self._restore_clock_latch_ms))
            if self._pause_frozen_ms is not None:
                return self._pause_frozen_ms
            self._track_match_clock()
            self._pause_frozen_ms = max(0, int(self._level_time_ms or 0))
            return self._pause_frozen_ms
        self._track_match_clock()
        return max(0, int(self._level_time_ms or 0))

    def _export_match_time_ms(self):
        return self._read_level_time_ms()

    def _match_clock_live(self):
        return self._effective_match_state() in ("countdown", "in_progress")

    def _apply_match_time(self, t_ms, force_hud=False, restore_apply=False):
        if t_ms is None:
            return True, None
        try:
            ms = int(t_ms)
        except (TypeError, ValueError):
            return False, "invalid t_ms"
        if ms < 0:
            return False, "invalid t_ms"
        paused = self._sv_paused_active()
        details = []
        if self._match_clock_live():
            if restore_apply:
                ok_eng, eng_detail = self._sync_engine_level_time(ms)
                if eng_detail:
                    details.append(eng_detail)
                if not ok_eng and self._engine_level_time_api():
                    return False, eng_detail or "set_level_time failed"
            elif not paused and self._native_clock_enabled():
                ok_eng, eng_detail = self._sync_engine_level_time(ms)
                if not ok_eng:
                    return False, eng_detail or "set_level_time failed"
                if eng_detail:
                    details.append(eng_detail)
            if not paused and not restore_apply and not self._native_clock_enabled():
                mt = self._native_map_time_ms()
                if mt is not None:
                    self._match_start_map_time = mt - ms
                    details.append("elapsed={}ms (map_delta)".format(ms))
                else:
                    details.append("cached={}ms".format(ms))
            else:
                if paused:
                    details.append("elapsed={}ms (paused)".format(ms))
                if restore_apply or force_hud or (not paused and self._native_clock_enabled()):
                    mt = self._native_map_time_ms()
                    if mt is not None:
                        self._match_start_map_time = mt - ms
                        details.append("anchor={} (explicit)".format(self._match_start_map_time))
        elif ms > 0:
            details.append("cached={}ms (warmup)".format(ms))
        self._level_time_ms = ms
        if paused:
            self._pause_frozen_ms = ms
        elapsed_sec = max(0, ms // 1000)
        if force_hud:
            try:
                cmd_arg = str(int(elapsed_sec))
                if hasattr(minqlx.Game, "setmatchtime"):
                    minqlx.Game.setmatchtime(cmd_arg)
                else:
                    minqlx.console_command("setmatchtime {}".format(cmd_arg))
                if restore_apply and self._engine_clock_synced:
                    details.append("hud_elapsed={}s (+engine)".format(elapsed_sec))
                else:
                    details.append("hud_elapsed={}s".format(elapsed_sec))
            except (AttributeError, TypeError, ValueError) as exc:
                if not details:
                    return False, "setmatchtime failed: {}".format(exc)
        return True, ", ".join(details) if details else "t={}ms".format(ms)

    def _timelimit_sec(self):
        for name in ("timelimit", "g_timelimit"):
            try:
                raw = self.get_cvar(name)
            except Exception:
                raw = None
            if raw is None:
                continue
            text = str(raw).strip()
            if not text:
                continue
            try:
                val = int(float(text))
            except (TypeError, ValueError):
                continue
            if val > 0:
                return val
        return 0

    @staticmethod
    def _parse_match_time_arg(parts):
        text = " ".join(str(p) for p in parts).strip().lower()
        if not text:
            raise ValueError("missing value")
        if text.startswith("ms "):
            return max(0, int(float(text[3:].strip())))
        if text.endswith("ms"):
            return max(0, int(float(text[:-2].strip())))
        if text.startswith("sec ") or text.startswith("s "):
            return max(0, int(float(text.split(None, 1)[1]) * 1000))
        if len(text) > 1 and text.endswith("s") and text[:-1].replace(".", "", 1).isdigit():
            return max(0, int(float(text[:-1]) * 1000))
        if ":" in text:
            bits = text.split(":")
            if len(bits) != 2:
                raise ValueError("bad mm:ss")
            mins = int(bits[0])
            sec = int(bits[1])
            return max(0, (mins * 60 + sec) * 1000)
        if not text.replace(".", "", 1).isdigit():
            raise ValueError("bad number")
        val = float(text)
        if val >= 1000:
            return max(0, int(val))
        return max(0, int(val * 1000))

    def _resolve_runtime_eid(
        self, alias, spawn_meta, classname, force_scan=False, exclude=None, restore_apply=False
    ):
        """Table spawn slot -> live ET_ITEM entity."""
        table_id = int(spawn_meta.get("entity_id"))
        alias_key = str(alias or "").strip().lower()
        exclude = set(exclude or ())

        if restore_apply:
            rid = self._scan_runtime_eid_at_spawn(
                alias_key,
                spawn_meta,
                classname,
                table_id,
                exclude=exclude,
                cache_writes=False,
            )
            if rid <= 0:
                self.logger.error(
                    "match_restore: runtime scan failed alias=%s table=%s cn=%s",
                    alias_key,
                    table_id,
                    classname,
                )
            return rid

        if force_scan:
            rid = self._scan_runtime_eid_at_spawn(
                alias_key, spawn_meta, classname, table_id, exclude=exclude
            )
            if rid > 0:
                return rid

        for key in (alias_key, "e{}".format(table_id), str(table_id)):
            rid = self._runtime_entity_by_alias.get(key)
            if rid and int(rid) not in exclude:
                return int(rid)
        slot = self._slot_runtime_ids.get(self._slot_key(table_id))
        if slot:
            for rid in sorted(slot, reverse=True):
                if int(rid) not in exclude:
                    return int(rid)
        rid = self._scan_runtime_eid_at_spawn(
            alias_key, spawn_meta, classname, table_id, exclude=exclude
        )
        if rid > 0:
            return rid
        self.logger.error(
            "match_restore: runtime resolve failed alias=%s table=%s cn=%s",
            alias_key,
            table_id,
            classname,
        )
        return 0

    def _stock_find_item_entity(self, x, y, z, radius, want_item_id=0, exclude_entity_id=-1):
        """Stock runtime: nearest live ET_ITEM entity within radius, optionally
        matched on bg item index (s.modelindex), same contract as the native."""
        best_eid = 0
        best_d2 = float(radius) * float(radius)
        try:
            item_entities = minqlx.entities(etype=_ET_ITEM)
        except (AttributeError, TypeError, ValueError, _ENGINE_ERR):
            return 0
        for ent in item_entities:
            try:
                eid = int(ent.number)
                if eid == int(exclude_entity_id):
                    continue
                if want_item_id and int(ent.s.modelindex) != int(want_item_id):
                    continue
                origin = ent.r.current_origin
                dx = float(origin.x) - float(x)
                dy = float(origin.y) - float(y)
                dz = float(origin.z) - float(z)
                d2 = dx * dx + dy * dy + dz * dz
            except (AttributeError, TypeError, ValueError, _ENGINE_ERR):
                continue
            if d2 <= best_d2:
                best_d2 = d2
                best_eid = eid
        return best_eid

    def _call_find_map_item_entity(self, x, y, z, radius, bg_index=None, exclude_entity_id=-1):
        want_item_id = int(bg_index) if bg_index is not None else 0
        if not hasattr(minqlx, "find_map_item_entity"):
            try:
                return int(self._stock_find_item_entity(
                    float(x), float(y), float(z), float(radius),
                    want_item_id=want_item_id,
                    exclude_entity_id=int(exclude_entity_id),
                ))
            except (TypeError, ValueError):
                return 0
        attempts = (
            (float(x), float(y), float(z), float(radius), want_item_id, int(exclude_entity_id)),
            (float(x), float(y), float(z), float(radius), want_item_id),
            (float(x), float(y), float(z), float(radius)),
        )
        for args in attempts:
            try:
                return int(minqlx.find_map_item_entity(*args))
            except TypeError:
                continue
            except (AttributeError, ValueError):
                return 0
        return 0

    def _scan_runtime_eid_at_spawn(
        self, alias_key, spawn_meta, classname, table_id, exclude=None, cache_writes=True
    ):
        exclude = set(exclude or ())
        try:
            x = float(spawn_meta.get("x"))
            y = float(spawn_meta.get("y"))
            z = float(spawn_meta.get("z"))
        except (TypeError, ValueError):
            return 0
        bg = self._bg_index_for(classname)
        scan_radius = ITEM_RUNTIME_SCAN_RADIUS
        last_bad = -1
        rid = 0
        for _ in range(32):
            rid = self._call_find_map_item_entity(
                x, y, z, scan_radius, bg_index=bg, exclude_entity_id=last_bad
            )
            if rid <= 0:
                return 0
            if int(rid) not in exclude:
                break
            last_bad = int(rid)
        else:
            return 0
        rid = int(rid)
        if cache_writes:
            self._runtime_entity_by_alias[str(alias_key)] = rid
            self._runtime_entity_by_alias["e{}".format(table_id)] = rid
            self._track_slot_runtime_id(table_id, rid)
        self.logger.info(
            "match_restore: runtime resolve alias=%s table=%s -> e%s at=(%.1f,%.1f,%.1f)",
            alias_key,
            table_id,
            rid,
            x,
            y,
            z,
        )
        return rid

    def _engine_item_pickable(self, runtime_eid):
        row = self._get_item_state(runtime_eid)
        if row is None:
            return False
        inuse, etype, eflags, contents = row[0], row[1], row[2], row[3]
        if not int(inuse):
            return False
        if int(etype) == 1:
            return False
        if int(eflags) & 0x80:
            return False
        return int(contents) != 0

    def _item_bg_index(self, classname):
        bg = self._bg_index_for(classname)
        if bg is None:
            return 0
        try:
            return int(bg)
        except (TypeError, ValueError):
            return 0

    def _stock_hide_item(self, runtime_eid, item_id=0):
        """Stock runtime hide: writable fields + link, the way Touch_Item hides a
        taken item. contents 0 blocks pickup; think is left alone (respawn_item
        re-arms it)."""
        ent = _stock_item_entity(runtime_eid)
        if ent is None:
            return False
        try:
            if int(item_id) > 0:
                ent.s.modelindex = int(item_id)
            ent.s.e_flags = int(ent.s.e_flags) | _EF_NODRAW
            ent.r.sv_flags = int(ent.r.sv_flags) | _SVF_NOCLIENT
            ent.r.contents = 0
            minqlx.link_entity(int(runtime_eid))
        except (AttributeError, TypeError, ValueError, _ENGINE_ERR):
            return False
        return True

    def _hide_engine_item(self, runtime_eid, alias, classname, spawn_meta):
        eid = int(runtime_eid)
        if eid <= 0:
            return False
        if not hasattr(minqlx, "hide_map_item"):
            ok = self._stock_hide_item(eid, self._item_bg_index(classname))
            if not ok:
                self.logger.warning(
                    "match_restore: stock hide failed alias=%s e%s",
                    alias,
                    eid,
                )
            return ok
        item_id = self._item_bg_index(classname)
        try:
            ok = (
                minqlx.hide_map_item(eid, item_id)
                if item_id > 0
                else minqlx.hide_map_item(eid)
            )
        except (AttributeError, TypeError, ValueError) as exc:
            self.logger.warning(
                "match_restore: hide_map_item alias=%s e%s item=%s: %s",
                alias,
                eid,
                item_id or "-",
                exc,
            )
            return False
        if ok is False:
            self.logger.warning(
                "match_restore: hide_map_item false alias=%s e%s",
                alias,
                eid,
            )
            return False
        return True

    def _show_engine_item(self, runtime_eid, alias=None, classname=None):
        eid = int(runtime_eid)
        if eid <= 0:
            return False
        if not hasattr(minqlx, "show_map_item"):
            # Stock runtime: hand the show to the engine's own RespawnItem via
            # respawn_item(); it restores contents/EF_NODRAW/CS_ITEMS itself on
            # the next think, so the item is visible a frame later, not
            # synchronously like the patched native.
            if not hasattr(minqlx, "respawn_item"):
                return False
            item_id = self._item_bg_index(classname) if classname else 0
            ent = _stock_item_entity(eid)
            if ent is None:
                return False
            try:
                if item_id > 0:
                    ent.s.modelindex = item_id
                ok = minqlx.respawn_item(eid, 1) is not False
            except (AttributeError, TypeError, ValueError, _ENGINE_ERR):
                return False
            if alias is not None:
                self.logger.info(
                    "match_restore: stock show via respawn_item e%s alias=%s ok=%s",
                    eid,
                    alias,
                    ok,
                )
            return ok
        item_id = self._item_bg_index(classname) if classname else 0
        try:
            ok = (
                minqlx.show_map_item(eid, item_id)
                if item_id > 0
                else minqlx.show_map_item(eid)
            )
            ok = ok is not False
        except (AttributeError, TypeError, ValueError):
            return False
        if alias is not None:
            self.logger.info(
                "match_restore: engine show e%s alias=%s item=%s ok=%s pickable=%s",
                eid,
                alias,
                item_id or "-",
                ok,
                self._engine_item_pickable(eid) if ok else False,
            )
        return ok

    def _apply_item_checkpoint_engine(
        self,
        item,
        alias,
        state,
        runtime_eid,
        classname,
        spawn_meta,
        now_ms,
        touch_cid=0,
    ):
        """Touch-reset + vanilla nextthink (game clock). No hide/show respawn path."""
        eid = int(runtime_eid)
        cid = int(touch_cid)
        if state == 0:
            self._hide_engine_item(eid, alias, classname, spawn_meta)
            self.logger.info(
                "match_restore: restore hide alias=%s runtime=%s (s:0)",
                alias,
                eid,
            )
            return True, alias

        visible_at_ms = None
        if match_restore_items is not None:
            visible_at_ms = match_restore_items.plan_item_visible_at_ms(item, now_ms)
        elif state == 1:
            visible_at_ms = now_ms

        if visible_at_ms is None:
            self.logger.warning(
                "match_restore: restore item alias=%s s=%s no visible_at_ms",
                alias,
                state,
            )
            return True, alias

        delay_ms = max(0, int(visible_at_ms) - int(now_ms))
        if not self._schedule_vanilla_respawn(
            eid,
            delay_ms,
            alias=alias,
            client_id=cid,
            classname=classname,
            spawn_meta=spawn_meta,
        ):
            return False, alias

        self.logger.info(
            "match_restore: restore item alias=%s s=%s runtime=%s visible_at_ms=%s delay_ms=%s",
            alias,
            state,
            eid,
            visible_at_ms,
            delay_ms,
        )
        return True, alias

    def _apply_item_checkpoint(
        self, item, checkpoint_t_ms=0, cp=None, touch_cid=0
    ):
        alias, spawn_meta, classname = self._spawn_meta_from_checkpoint_item(item)
        state = int(item.get("s", 1))
        if not spawn_meta:
            return False, alias
        table_id = int(spawn_meta.get("entity_id"))
        now_ms = max(0, int(checkpoint_t_ms))
        held_by_player = bool(
            cp and self._checkpoint_loadout_includes_weapon(cp, alias)
        )
        runtime_eid = self._resolve_runtime_eid(
            alias,
            spawn_meta,
            classname,
            force_scan=True,
            exclude=self._restore_apply_used_runtime_eids,
            restore_apply=True,
        )
        if runtime_eid <= 0:
            if state == 1 and held_by_player:
                self.logger.info(
                    "match_restore: restore skip alias=%s (checkpoint loadout holds weapon)",
                    alias,
                )
                return True, alias
            self.logger.error(
                "match_restore: restore skip alias=%s table=%s (no runtime entity)",
                alias,
                table_id,
            )
            return False, alias

        self._restore_apply_used_runtime_eids.add(int(runtime_eid))
        return self._apply_item_checkpoint_engine(
            item,
            alias,
            state,
            runtime_eid,
            classname,
            spawn_meta,
            now_ms,
            touch_cid=int(touch_cid),
        )

    @staticmethod
    def _num(value):
        if value is None or value == "":
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _int(value):
        num = match_restore._num(value)
        if num is None:
            return None
        return int(num)

    def _sync_health_hud_stat(self, target, hp):
        # v1.0.0's Player.health setter writes only the native Entity.health
        # field; stats[STAT_HEALTH] (the HUD/read-back copy) is documented as
        # "rewritten from this one every frame" by the engine, but that
        # refresh needs a live frame to actually run. Restore always
        # re-pauses right after applying vitals (_ensure_restore_paused,
        # called from the same command handler with no frame boundary in
        # between) so that refresh may never happen before the freeze -
        # write the stat directly too, the same way the native armor setter
        # already does (gclient.ps.stats[StatIndex.ARMOR]), instead of
        # depending on frame timing around pause.
        try:
            target.gclient.ps.stats[minqlx.StatIndex.HEALTH] = int(hp)
        except (AttributeError, TypeError, ValueError, minqlx.EngineStateError):
            pass

    def _apply_player_health_hud(self, target, health):
        if health is None:
            return True
        hp = int(health)
        if hp < 1:
            hp = 1
        if not hasattr(target, "health"):
            return False
        try:
            target.health = hp
        except (AttributeError, TypeError, ValueError, minqlx.EngineStateError) as exc:
            self.logger.warning(
                "match_restore: set_health cid=%s failed: %s",
                getattr(target, "id", "?"),
                exc,
            )
            return False
        self._sync_health_hud_stat(target, hp)
        self._schedule_health_reassert(target, hp)
        return True

    def _schedule_health_reassert(self, target, hp, delay_sec=0.15):
        # Live-tested 2026-08-25 on a real match: the immediate write above
        # alone left the HUD-visible health showing the pre-restore value
        # through the whole paused window, only snapping to the restored hp
        # once the match actually unpaused/unfroze. Mirror the same delayed
        # reassert _schedule_dead_state_reassert already uses for the
        # dead-player path - re-applying health+stat once more a beat later
        # made it stick immediately, confirmed live.
        @minqlx.delay(float(delay_sec))
        def _reassert():
            @minqlx.next_frame
            def _reassert_main():
                try:
                    if target is not None:
                        target.health = hp
                        self._sync_health_hud_stat(target, hp)
                except (AttributeError, TypeError, ValueError, minqlx.EngineStateError) as exc:
                    self.logger.warning(
                        "match_restore: health reassert cid=%s failed: %s",
                        getattr(target, "id", "?"),
                        exc,
                    )

            _reassert_main()

        _reassert()

    @staticmethod
    def _strip_dead_player_inventory(payload):
        if payload.get("dead") not in (1, True, "1"):
            return payload
        row = dict(payload)
        row.pop("loadout", None)
        row.pop("lo", None)
        row.pop("am", None)
        row.pop("ammo", None)
        row["w"] = 0
        return row

    @staticmethod
    def _infer_want_dead(payload):
        if payload.get("dead") in (1, True, "1"):
            return True
        hp = match_restore._int(payload.get("h", payload.get("health")))
        return hp is not None and hp <= 0

    def _apply_player_dead_state(self, target, respawn_at_ms=None):
        try:
            target.is_alive = False
        except (AttributeError, TypeError, ValueError, minqlx.EngineStateError):
            pass
        try:
            target.health = 0
        except (AttributeError, TypeError, ValueError, minqlx.EngineStateError) as exc:
            self.logger.warning(
                "match_restore: dead set_health cid=%s failed: %s",
                getattr(target, "id", "?"),
                exc,
            )
        else:
            self._sync_health_hud_stat(target, 0)
        self._apply_dead_player_inventory(target)
        if respawn_at_ms is not None:
            # Immediate best-effort write, same as the health reassert below:
            # is_alive=False's real slay_with_mod() may set its own fresh
            # respawnTime a frame after this call returns, stomping an
            # immediate write - _schedule_respawn_time_reassert is the safety
            # net that makes it stick. Both writes use the SAME absolute
            # deadline computed once by the caller - recomputing "level.time +
            # remaining" again inside the reassert would use a later "now" and
            # silently push the deadline out by however long the reassert
            # waited.
            self._set_player_respawn_at_ms(target, respawn_at_ms)
            self._schedule_respawn_time_reassert(target, respawn_at_ms)

    def _schedule_respawn_time_reassert(self, target, respawn_at_ms, delay_sec=0.15):
        # Mirrors _schedule_health_reassert: live-tested pattern for this same
        # dead-player path, where the engine's own catch-up a frame later can
        # stomp values set immediately after target.is_alive = False.
        @minqlx.delay(float(delay_sec))
        def _reassert():
            @minqlx.next_frame
            def _reassert_main():
                try:
                    if target is not None:
                        self._set_player_respawn_at_ms(target, respawn_at_ms)
                except (AttributeError, TypeError, ValueError) as exc:
                    self.logger.warning(
                        "match_restore: respawn_time reassert cid=%s failed: %s",
                        getattr(target, "id", "?"),
                        exc,
                    )

            _reassert_main()

        _reassert()

    def _schedule_dead_state_reassert(self, target, respawn_at_ms=None, delay_sec=0.12):
        # delay runs on a timer thread; hop back to the main thread for engine calls.
        @minqlx.delay(float(delay_sec))
        def _reassert():
            @minqlx.next_frame
            def _reassert_main():
                try:
                    if target is not None:
                        self._apply_player_dead_state(target, respawn_at_ms=respawn_at_ms)
                except (AttributeError, TypeError, ValueError) as exc:
                    self.logger.warning(
                        "match_restore: dead reassert cid=%s failed: %s",
                        getattr(target, "id", "?"),
                        exc,
                    )

            _reassert_main()

        _reassert()

    def _apply_dead_player_inventory(self, target):
        try:
            self._write_player_weapons(target, minqlx.NO_WEAPONS._replace(g=True))
        except (AttributeError, TypeError, ValueError):
            pass
        try:
            self._write_player_weapon(target, 1)
        except (AttributeError, TypeError, ValueError):
            pass
        try:
            self._apply_ammo(target, {key: 0 for key in AMMO_KEYS})
        except (AttributeError, TypeError, ValueError):
            pass

    def _remember_restore_velocity(self, client_id, vx, vy, vz, frames=RESTORE_VEL_FRAMES):
        cid = int(client_id)
        vel = (float(vx), float(vy), float(vz))
        self._restore_pending_velocities[cid] = vel
        self._queue_player_velocity(cid, vel[0], vel[1], vel[2], frames=frames)

    def _flush_restore_velocities(self, frames=RESTORE_VEL_FRAMES):
        pending = dict(self._restore_pending_velocities or {})
        if not pending:
            return
        for cid, vel in pending.items():
            try:
                target = self.player(cid)
                self._write_player_velocity(target, vel[0], vel[1], vel[2])
                self._queue_player_velocity(cid, vel[0], vel[1], vel[2], frames=frames)
            except (AttributeError, TypeError, ValueError, minqlx.NonexistentPlayerError):
                pass
        self.logger.info(
            "match_restore: restore velocity flush count=%s",
            len(pending),
        )

    def _apply_player_vitals(self, target, payload):
        """Apply hp/armor/loadout/ammo/weapon/score (run before kinematics pause)."""
        want_dead = self._infer_want_dead(payload)
        respawn_at_ms = self._compute_respawn_at_ms(self._int(payload.get("ri")))
        health = self._int(payload.get("h", payload.get("health")))
        armor = self._int(payload.get("a", payload.get("armor")))
        weapon = payload.get("w", payload.get("weapon", payload.get("active_weapon")))
        weapon_idx = None
        if weapon is not None:
            if isinstance(weapon, str):
                wkey = WEAPON_ALIAS.get(weapon.lower())
                if wkey in WEAPON_KEYS:
                    weapon_idx = WEAPON_KEYS.index(wkey) + 1
            else:
                weapon_idx = self._int(weapon)
        score = self._int(payload.get("sc", payload.get("score")))
        loadout = payload.get("loadout")
        if loadout is None and payload.get("lo") is not None:
            lo_norm = normalize_loadout_mask(payload.get("lo"), weapon_idx)
            loadout = mask_to_loadout(lo_norm)
        ammo = payload.get("ammo", payload.get("am"))
        try:
            if want_dead:
                self._apply_player_dead_state(target, respawn_at_ms=respawn_at_ms)
            elif not target.is_alive:
                target.is_alive = True
            if health is not None and not want_dead:
                if not self._apply_player_health_hud(target, health):
                    return False
            if armor is not None and not want_dead:
                target.armor = armor
            if not want_dead:
                if isinstance(loadout, dict) and loadout:
                    kwargs = {}
                    for key, val in loadout.items():
                        wkey = WEAPON_ALIAS.get(str(key).lower(), str(key).lower())
                        if wkey in WEAPON_KEYS:
                            kwargs[wkey] = bool(val)
                    if kwargs:
                        self._write_player_weapons(
                            target, minqlx.NO_WEAPONS._replace(**kwargs)
                        )
                if isinstance(ammo, dict) and ammo:
                    self._apply_ammo(target, ammo)
                # weapon_idx 0 means "no active weapon recorded" -- _read_weapon_idx
                # falls back to 0 on export. minqlx.Weapon is an IntEnum starting at
                # WP_GAUNTLET = 1, so Weapon(0) would raise ValueError and abort the
                # whole vitals restore for this player; skip the write instead, the
                # same way the empty loadout/ammo dicts above are skipped.
                if weapon_idx:
                    self._write_player_weapon(target, int(weapon_idx))
                self._apply_powerups(target, payload.get("pw", payload.get("powerups")))
            if score is not None:
                self._apply_player_score(target, score)
        except (AttributeError, TypeError, ValueError) as exc:
            self.logger.warning(
                "match_restore: vitals apply failed cid=%s: %s",
                getattr(target, "id", "?"),
                exc,
            )
            return False
        return True

    def _apply_player_snapshot(
        self, target, payload, vitals_only=False, kinematics_only=False, state_only=False, velocity_only=False
    ):
        if not isinstance(payload, dict):
            return False, "payload must be object"

        x = self._num(payload.get("x"))
        y = self._num(payload.get("y"))
        z = self._num(payload.get("z"))
        want_dead = self._infer_want_dead(payload)
        respawn_at_ms = self._compute_respawn_at_ms(self._int(payload.get("ri")))
        vx = self._num(payload.get("vx"))
        vy = self._num(payload.get("vy"))
        vz = self._num(payload.get("vz"))
        health = self._int(payload.get("h", payload.get("health")))
        armor = self._int(payload.get("a", payload.get("armor")))
        weapon = payload.get("w", payload.get("weapon", payload.get("active_weapon")))
        weapon_idx = None
        if weapon is not None:
            if isinstance(weapon, str):
                wkey = WEAPON_ALIAS.get(weapon.lower())
                if wkey in WEAPON_KEYS:
                    weapon_idx = WEAPON_KEYS.index(wkey) + 1
            else:
                weapon_idx = self._int(weapon)
        score = self._int(payload.get("sc", payload.get("score")))
        loadout = payload.get("loadout")
        if loadout is None and payload.get("lo") is not None:
            lo_norm = normalize_loadout_mask(payload.get("lo"), weapon_idx)
            loadout = mask_to_loadout(lo_norm)
        ammo = payload.get("ammo", payload.get("am"))

        planned = []
        if x is not None and y is not None and z is not None:
            planned.append("pos")
        if vx is not None and vy is not None and vz is not None:
            planned.append("vel")
        elif payload.get("vel_reset"):
            planned.append("vel_reset")
        if health is not None:
            planned.append("hp")
        if armor is not None:
            planned.append("ar")
        if isinstance(loadout, dict) and loadout:
            planned.append("loadout")
        if isinstance(ammo, dict) and ammo:
            planned.append("ammo")
        if weapon_idx is not None:
            planned.append("w={}".format(weapon_idx))
        if normalize_powerups(payload.get("pw", payload.get("powerups"))):
            planned.append("powerups")
        if score is not None:
            planned.append("sc={}".format(score))
        if not planned:
            return False, "no fields to apply"

        if vitals_only:
            if not self._apply_player_vitals(target, payload):
                return False, "vitals failed"
            return True, ", ".join(planned)

        if state_only:
            planned = [
                p
                for p in planned
                if p in ("pos", "hp", "ar", "loadout", "ammo") or p.startswith(("w=", "sc="))
            ]
            if not planned:
                return False, "no state fields"
            if not self._apply_player_vitals(target, payload):
                return False, "vitals failed"
            client_id = int(target.id)
            if x is not None and y is not None and z is not None:
                pos_frames = (
                    RESTORE_POS_FRAMES_BOT
                    if self._is_bot_player(target)
                    else RESTORE_POS_FRAMES
                )
                self._teleport_player(target, x, y, z, frames=pos_frames)
            if want_dead:
                self._schedule_dead_state_reassert(target, respawn_at_ms=respawn_at_ms)
            return True, ", ".join(planned)

        if kinematics_only:
            if velocity_only:
                planned = [p for p in planned if p in ("vel", "vel_reset")]
            else:
                planned = [p for p in planned if p in ("pos", "vel", "vel_reset")]
            if not planned:
                return True, "kinematics skip"
            client_id = int(target.id)
            if not velocity_only and x is not None and y is not None and z is not None:
                pos_frames = (
                    RESTORE_POS_FRAMES_BOT
                    if self._is_bot_player(target)
                    else RESTORE_POS_FRAMES
                )
                self._teleport_player(target, x, y, z, frames=pos_frames)
            if vx is not None and vy is not None and vz is not None:
                self._write_player_velocity(target, vx, vy, vz)
                self._remember_restore_velocity(client_id, vx, vy, vz)
            elif payload.get("vel_reset"):
                # minqlx.Vector3 is a PyStructSequence: its ctor takes exactly ONE
                # sequence argument, hence the double parens. NOTE (operator-approved
                # behavior change): this is a REAL zero-velocity write. The pre-v1.0.0
                # `velocity(reset=True)` call this replaced returned the zero vector
                # without ever writing it (`if not kwargs: return vel`), so on production
                # it was a silent no-op. Zeroing here is deliberate, not accidental.
                self._write_player_velocity(target, 0, 0, 0)
                self._restore_pending_velocities.pop(int(client_id), None)
            return True, ", ".join(planned)

        client_id = int(target.id)
        pos_frames = (
            RESTORE_POS_FRAMES_BOT
            if self._is_bot_player(target)
            else RESTORE_POS_FRAMES
        )

        if not kinematics_only:
            self._apply_player_vitals(target, payload)

        @minqlx.next_frame
        def _apply():
            try:
                if target is None:
                    return
                if x is not None and y is not None and z is not None:
                    self._teleport_player(target, x, y, z, frames=pos_frames)
                if vx is not None and vy is not None and vz is not None:
                    self._write_player_velocity(target, vx, vy, vz)
                elif payload.get("vel_reset"):
                    # REAL zero-velocity write (was a silent no-op pre-v1.0.0) --
                    # operator-approved; see the Vector3 note in _apply_player_snapshot's
                    # kinematics_only branch above.
                    self._write_player_velocity(target, 0, 0, 0)
                elif not want_dead and x is not None and y is not None and z is not None:
                    # Same: REAL zero-velocity write, operator-approved (see note above).
                    self._write_player_velocity(target, 0, 0, 0)
                if (
                    not want_dead
                    and not target.is_alive
                    and x is not None
                    and y is not None
                    and z is not None
                ):
                    target.is_alive = True
            except (AttributeError, TypeError, ValueError) as exc:
                self.logger.exception("match_restore restoreplayer: %s", exc)

        _apply()
        if x is not None and y is not None and z is not None and self._is_bot_player(target):
            # Native set_position xors EF_TELEPORT_BIT each call; do not
            # re-teleport the bot. Fallback queue holds origin without xor.

            @minqlx.delay(0.15)
            def _bot_reposition():
                if callable(getattr(minqlx, "set_position", None)):
                    return
                self._queue_player_position(
                    client_id, x, y, z, frames=RESTORE_POS_FRAMES_BOT
                )

            _bot_reposition()
        return True, ", ".join(planned)

    def _queue_player_position(self, client_id, x, y, z, frames=RESTORE_POS_FRAMES):
        self._position_apply_queue.append(
            {
                "client_id": int(client_id),
                "x": float(x),
                "y": float(y),
                "z": float(z),
                "frames": int(frames),
            }
        )

    def _queue_player_velocity(self, client_id, vx, vy, vz, frames=RESTORE_VEL_FRAMES):
        self._velocity_apply_queue = [
            job
            for job in self._velocity_apply_queue
            if int(job.get("client_id", -1)) != int(client_id)
        ]
        self._velocity_apply_queue.append(
            {
                "client_id": int(client_id),
                "vx": float(vx),
                "vy": float(vy),
                "vz": float(vz),
                "frames": int(frames),
            }
        )

    @staticmethod
    def _write_player_velocity(target, vx, vy, vz):
        vel = minqlx.Vector3((float(vx), float(vy), float(vz)))
        setter = getattr(minqlx, "set_velocity", None)
        if callable(setter):
            try:
                if setter(int(target.id), vel):
                    return
            except (AttributeError, TypeError, ValueError):
                pass
        target.velocity = target.velocity._replace(x=float(vx), y=float(vy), z=float(vz))

    def _teleport_player(self, target, x, y, z, frames=RESTORE_POS_FRAMES):
        """One native teleport (xor EF_TELEPORT_BIT once). Queue only on fallback.

        minqlx.set_position xors the teleport bit every call. Re-applying it
        for RESTORE_POS_FRAMES cancelled the snap on even counts, so other
        clients interpolated from the old origin until a later unpause.
        """
        if self._apply_player_position(target, x, y, z, teleport=True):
            return True
        self._queue_player_position(int(target.id), x, y, z, frames=frames)
        return False

    @staticmethod
    def _write_player_weapons(target, weapons_obj):
        setter = getattr(minqlx, "set_weapons", None)
        if callable(setter):
            try:
                if setter(int(target.id), weapons_obj):
                    return
            except (AttributeError, TypeError, ValueError):
                pass
        target.weapons = weapons_obj

    @staticmethod
    def _write_player_weapon(target, weapon_idx):
        idx = int(weapon_idx)
        setter = getattr(minqlx, "set_weapon", None)
        if callable(setter):
            try:
                if setter(int(target.id), idx):
                    return
            except (AttributeError, TypeError, ValueError):
                pass
        target.weapon = minqlx.Weapon(idx)

    @staticmethod
    def _apply_player_position(target, x, y, z, teleport=True):
        pos = minqlx.Vector3((float(x), float(y), float(z)))
        if teleport:
            setter = getattr(minqlx, "set_position", None)
            if callable(setter):
                try:
                    if setter(int(target.id), pos):
                        return True
                except (AttributeError, TypeError, ValueError, _ENGINE_ERR):
                    # Fork set_position raises EngineStateError for an empty
                    # slot (the patched native returned False); same fallback.
                    pass
        try:
            # REAL zero-velocity write (was a silent no-op pre-v1.0.0) --
            # operator-approved; see the Vector3 note in _apply_player_snapshot.
            target.velocity = minqlx.Vector3((0, 0, 0))
        except (AttributeError, TypeError, ValueError):
            pass
        target.position = target.position._replace(x=float(x), y=float(y), z=float(z))
        return False

    @staticmethod
    def _apply_player_score(target, score):
        want = int(score)
        current = int(getattr(target, "score", 0) or 0)
        delta = want - current
        if delta != 0:
            minqlx.console_command("addscore {} {}".format(int(target.id), delta))

    @staticmethod
    def _apply_ammo(target, ammo_dict):
        kwargs = {}
        for key in AMMO_KEYS:
            if key in ammo_dict:
                kwargs[key] = int(ammo_dict[key])
        if not kwargs:
            return
        try:
            ammo_obj = target.ammo._replace(**kwargs)
        except (AttributeError, TypeError, ValueError) as exc:
            raise ValueError("ammo apply failed: {}".format(exc)) from exc
        setter = getattr(minqlx, "set_ammo", None)
        if callable(setter):
            try:
                if setter(int(target.id), ammo_obj):
                    return
            except (AttributeError, TypeError, ValueError):
                pass
        try:
            target.ammo = ammo_obj
        except (AttributeError, TypeError, ValueError) as exc:
            raise ValueError("ammo apply failed: {}".format(exc)) from exc

    @staticmethod
    def _apply_powerups(target, pw_raw):
        """Set player powerup remaining times (seconds in, ms on the wire). Always clears first.

        `Player.powerups` (v1.0.0 property) reads/writes milliseconds directly with no
        internal conversion -- the old `powerups(**kwargs)` method took seconds and did
        `round(kwargs[x] * 1000)` itself, so that *1000 has to happen here now instead.
        """
        clear_kwargs = {name: 0 for name in POWERUP_MINQLX.values()}
        try:
            target.powerups = target.powerups._replace(**clear_kwargs)
        except (AttributeError, TypeError, ValueError):
            pass
        pw = normalize_powerups(pw_raw)
        if not pw:
            return
        kwargs = {}
        for alias, sec in pw.items():
            mk = POWERUP_MINQLX.get(alias)
            if mk and sec > 0:
                kwargs[mk] = int(sec) * 1000
        if not kwargs:
            return
        try:
            target.powerups = target.powerups._replace(**kwargs)
        except (AttributeError, TypeError, ValueError) as exc:
            raise ValueError("powerup apply failed: {}".format(exc)) from exc
