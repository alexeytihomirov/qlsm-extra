"""item_presets - edit item spawns in game and save layouts per map.

Admins add, remove, replace and move items from inside the game (in warmup),
save the result as a named preset of the map and switch presets on and off to
test item balance. A preset is a diff against the vanilla map: map items it
removes (classname + origin) and items it adds. The map file is never touched:
with no active preset a restart gives the map's own layout.

Added items are spawned with spawn_entity(), i.e. the way the map's own items
are (G_SpawnItem: normal respawn, keys like wait apply). spawn_item() is not
used: it launches a dropped-style item. Map items are freed with
remove_entity(); a hidden item would come back on its first respawn.

Presets live in the host's Redis (shared by every instance on the host), the
active preset per instance (net_port). Redis is only touched in worker threads.

Spec: docs/superpowers/specs/2026-11-04-item-presets-design.md
"""
import json
import math
import re

try:
    import minqlxtended as minqlx
except ImportError:
    import minqlx

ET_ITEM = getattr(minqlx, "ET_ITEM", 2)
MATCH_TOLERANCE = 8.0   # units between a stored origin and a live map item
RESCAN_S = 0.5          # a restart respawns map items a few frames after new_game
KEY_PRESETS = "minqlx:item_presets:{}"          # hash per map: name -> JSON
KEY_ACTIVE = "minqlx:item_presets:active:{}"    # per net_port: {"map", "name"}
NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,32}$")
COPIED_KEYS = ("wait", "spawnflags")            # map keys kept when a map item is moved

CVAR_DEFAULTS = (
    ("qlx_itemPresetsEnabled", "0"),
    ("qlx_itemEditPerm", "3"),
    ("qlx_itemEditRadius", "64"),
)

# Short names (skills/ql-items/SKILL.md). A tuple lists aliases, the first one
# the engine knows wins.
ALIASES = {
    "g": "weapon_gauntlet", "mg": "weapon_machinegun", "sg": "weapon_shotgun",
    "gl": "weapon_grenadelauncher", "rl": "weapon_rocketlauncher", "lg": "weapon_lightning",
    "rg": "weapon_railgun", "pg": "weapon_plasmagun", "bfg": "weapon_bfg",
    "gh": "weapon_grapplinghook", "ng": "weapon_nailgun", "pl": "weapon_prox_launcher",
    "cg": "weapon_chaingun", "hmg": "weapon_hmg",
    "shard": "item_armor_shard", "ga": "item_armor_jacket", "ya": "item_armor_combat",
    "ra": "item_armor_body",
    "5hp": "item_health_small", "5": "item_health_small",
    "25hp": "item_health", "25": "item_health",
    "50hp": "item_health_large", "50": "item_health_large",
    "mh": "item_health_mega", "mega": "item_health_mega",
    "quad": "item_quad", "bs": "item_enviro", "haste": "item_haste",
    "invis": ("item_invis", "item_invisibility"), "regen": "item_regen",
    "bullets": "ammo_bullets", "shells": "ammo_shells", "grenades": "ammo_grenades",
    "rockets": "ammo_rockets", "lightning": "ammo_lightning", "slugs": "ammo_slugs",
    "cells": "ammo_cells", "bfgammo": "ammo_bfg", "nails": "ammo_nails",
    "mines": "ammo_mines", "belt": "ammo_belt",
}
SHORT_NAMES = ("rl lg rg pg sg gl mg cg ng pl hmg bfg | ra ya ga shard | mh 50hp 25hp 5hp | quad bs haste invis regen"
               " | bullets shells grenades rockets lightning slugs cells bfgammo nails mines belt")


# --- pure helpers ---

def resolve_type(text, known):
    """Short name or classname -> classname the engine knows, else None."""
    key = str(text or "").strip().lower()
    candidates = ALIASES.get(key, key)
    if isinstance(candidates, str):
        candidates = (candidates,)
    for name in candidates:
        if name in known:
            return name
    return None


def origin_of(ent):
    o = ent.s.origin
    return [float(o[0]), float(o[1]), float(o[2])]


def compact(origin):
    return [round(float(v), 1) for v in origin]


def distance(a, b):
    return math.sqrt(sum((float(x) - float(y)) ** 2 for x, y in zip(a, b)))


def nearest(entities, pos, radius):
    best, best_d = None, None
    for ent in entities:
        try:
            d = distance(origin_of(ent), pos)
        except Exception:
            continue
        if d <= radius and (best_d is None or d < best_d):
            best, best_d = ent, d
    return best


def match_map_item(entities, entry, exclude):
    """Live map item for a `removed` entry: same classname, within tolerance."""
    for ent in entities:
        if int(ent.s.number) in exclude or str(ent.classname or "") != entry["cn"]:
            continue
        if distance(origin_of(ent), entry["o"]) <= MATCH_TOLERANCE:
            return ent
    return None


def empty_draft():
    return {"removed": [], "added": []}


def parse_preset(raw):
    """Stored JSON -> draft dict; raises ValueError on a broken record."""
    data = json.loads(raw)
    draft = empty_draft()
    for section in ("removed", "added"):
        for row in data.get(section) or []:
            entry = {"cn": str(row["cn"]), "o": [float(v) for v in row["o"]][:3]}
            if len(entry["o"]) != 3:
                raise ValueError("origin needs 3 numbers")
            if section == "added" and row.get("k"):
                entry["k"] = {str(k): v for k, v in dict(row["k"]).items()}
            draft[section].append(entry)
    return draft


def dump_preset(mapname, name, draft):
    return json.dumps({"map": mapname, "name": name,
                       "removed": draft["removed"], "added": draft["added"]},
                      separators=(",", ":"))


def copied_keys(ent):
    keys = {}
    for key in COPIED_KEYS:
        try:
            value = getattr(ent, key)
        except Exception:
            continue
        if value:
            keys[key] = int(value) if float(value).is_integer() else float(value)
    return keys


class item_presets(minqlx.Plugin):
    def __init__(self):
        for name, value in CVAR_DEFAULTS:
            self.set_cvar_once(name, value)
        self._map = ""
        self._draft = empty_draft()
        self._active = None      # active preset name on this map
        self._ours = {}          # entity number -> added entry (same object as in the draft)
        self._picked = {}        # client id -> entity number picked by !item move
        self._known = None       # classnames the engine knows

        perm = self.get_cvar("qlx_itemEditPerm", int)
        self.add_command("item", self.cmd_item, perm, usage="add <type> | remove | replace <type> | move | list")
        self.add_command("preset", self.cmd_preset, perm, usage="save <name> | load <name> | off | list | delete <name>")
        self.add_hook("map", self.handle_map)
        self.add_hook("new_game", self.handle_new_game)

        try:
            current = self.game.map if self.game is not None else ""
        except Exception:
            current = ""
        if current:
            self.handle_map(current, None)

    # --- state checks ---

    def _enabled(self):
        return bool(self.get_cvar("qlx_itemPresetsEnabled", bool))

    def _warmup(self):
        try:
            return self.game is not None and self.game.state == "warmup"
        except Exception:
            return False

    def _can_edit(self, player):
        if not self._enabled():
            self._tell(player, "item_presets is off (qlx_itemPresetsEnabled 0)")
            return False
        if not self._warmup():
            self._tell(player, "item edits only in warmup")
            return False
        return True

    def _radius(self):
        try:
            return float(self.get_cvar("qlx_itemEditRadius") or 64)
        except (TypeError, ValueError):
            return 64.0

    def _known_items(self):
        if self._known is None:
            try:
                self._known = {str(it.classname) for it in minqlx.items() if it.classname}
            except Exception:
                self._known = set()
            if not self._known:  # runtime without items(): trust the alias table
                for value in ALIASES.values():
                    self._known.update((value,) if isinstance(value, str) else value)
        return self._known

    @staticmethod
    def _tell(player, text):
        try:
            if player is not None:
                player.tell("^7[items] " + text)
        except Exception:
            pass

    @staticmethod
    def _pos(player):
        pos = player.position
        if callable(pos):  # minqlx: method; minqlxtended: property
            pos = pos()
        return compact((pos[0], pos[1], pos[2]))

    def _items(self):
        try:
            return list(minqlx.entities(inuse=True, etype=ET_ITEM))
        except Exception as exc:
            self.logger.warning("item_presets: item scan failed: %s", exc)
            return []

    @staticmethod
    def _entity(number):
        try:
            for ent in minqlx.entities(inuse=True, start=int(number), stop=int(number) + 1):
                if int(ent.s.number) == int(number):
                    return ent
        except Exception:
            pass
        return None

    def _port(self):
        return self.get_cvar("net_port") or "0"

    # --- engine edits ---

    def _spawn(self, entry):
        keys = {"origin": tuple(entry["o"])}
        keys.update(entry.get("k") or {})
        try:
            ent = minqlx.spawn_entity(entry["cn"], keys)
        except Exception as exc:
            self.logger.warning("item_presets: spawn %s at %s: %s", entry["cn"], entry["o"], exc)
            return None
        return ent

    def _remove(self, number):
        try:
            minqlx.remove_entity(int(number))
            return True
        except Exception as exc:
            self.logger.warning("item_presets: remove e%s: %s", number, exc)
            return False

    def _take(self, ent):
        """Take a live item off the map and record it in the draft. Returns the
        keys to carry over when the item is placed again (move)."""
        number = int(ent.s.number)
        entry = self._ours.pop(number, None)
        if entry is not None:
            self._draft["added"] = [e for e in self._draft["added"] if e is not entry]
            keys = dict(entry.get("k") or {})
        else:
            self._draft["removed"].append({"cn": str(ent.classname), "o": compact(origin_of(ent))})
            keys = copied_keys(ent)
        self._remove(number)
        return keys

    def _place(self, classname, origin, keys=None):
        entry = {"cn": classname, "o": compact(origin)}
        if keys:
            entry["k"] = dict(keys)
        ent = self._spawn(entry)
        if ent is None:
            return None
        self._ours[int(ent.s.number)] = entry
        self._draft["added"].append(entry)
        return entry

    def _apply(self):
        """Bring the live map in line with the draft. Safe to call repeatedly."""
        if not self._enabled():
            return
        ents = self._items()
        alive = {}
        for number, entry in self._ours.items():
            # Looked up by number, not among ET_ITEM: a fresh item only becomes
            # ET_ITEM two frames after spawn_entity. A restart frees our entities
            # and the number may come back as another entity.
            ent = self._entity(number)
            if ent is not None and str(ent.classname or "") == entry["cn"] \
                    and distance(origin_of(ent)[:2], entry["o"][:2]) <= MATCH_TOLERANCE:
                alive[number] = entry
        self._ours = alive
        removed = 0
        for entry in self._draft["removed"]:
            ent = match_map_item(ents, entry, set(alive))
            if ent is not None and self._remove(ent.s.number):
                removed += 1
        live_entries = {id(e) for e in alive.values()}
        spawned = 0
        for entry in self._draft["added"]:
            if id(entry) in live_entries:
                continue
            ent = self._spawn(entry)
            if ent is not None:
                self._ours[int(ent.s.number)] = entry
                spawned += 1
        if removed or spawned:
            self.logger.info("item_presets: %s: removed %d, spawned %d", self._map, removed, spawned)

    _apply_soon = minqlx.next_frame(_apply)

    def _restart(self):
        minqlx.console_command("map_restart")

    # --- hooks ---

    def handle_map(self, mapname, factory):
        self._map = str(mapname or "").lower()
        self._draft = empty_draft()
        self._active = None
        self._ours = {}
        self._picked = {}
        self._fetch_active(self._map, self._port())

    def handle_new_game(self):
        self._ours = {}  # a restart freed every entity we spawned
        self._picked = {}
        if self._enabled():
            self._apply_soon()
            self.delay(RESCAN_S, self._apply)

    # --- Redis (worker threads) ---

    @minqlx.thread
    def _fetch_active(self, mapname, port):
        try:
            raw = self.db.get(KEY_ACTIVE.format(port))
            active = json.loads(raw) if raw else None
            if not active or active.get("map") != mapname:
                return
            name = str(active.get("name") or "")
            stored = self.db.hget(KEY_PRESETS.format(mapname), name)
            draft = parse_preset(stored) if stored else None
        except Exception as exc:
            self.logger.warning("item_presets: reading the active preset of %s: %s", mapname, exc)
            return
        if draft is not None:
            self._activate(mapname, name, draft, False)

    @minqlx.next_frame
    def _activate(self, mapname, name, draft, restart):
        if mapname != self._map:
            return
        self._draft = draft
        self._active = name
        self._picked = {}
        if restart:
            self._restart()
        else:
            self._apply()

    @minqlx.next_frame
    def _reply(self, player, text):
        self._tell(player, text)

    @minqlx.thread
    def _db_save(self, player, mapname, name, payload, port):
        try:
            self.db.hset(KEY_PRESETS.format(mapname), name, payload)
            self.db.set(KEY_ACTIVE.format(port), json.dumps({"map": mapname, "name": name}))
        except Exception as exc:
            self._reply(player, "save failed: {}".format(exc))
            return
        self._saved(mapname, name)
        self._reply(player, "saved preset ^3{}^7 for {} (active)".format(name, mapname))

    @minqlx.next_frame
    def _saved(self, mapname, name):
        if mapname == self._map:
            self._active = name

    @minqlx.thread
    def _db_load(self, player, mapname, name, port):
        try:
            stored = self.db.hget(KEY_PRESETS.format(mapname), name)
            if not stored:
                self._reply(player, "no preset ^3{}^7 on {}".format(name, mapname))
                return
            draft = parse_preset(stored)
            self.db.set(KEY_ACTIVE.format(port), json.dumps({"map": mapname, "name": name}))
        except Exception as exc:
            self._reply(player, "load failed: {}".format(exc))
            return
        self._reply(player, "loading preset ^3{}^7, restarting".format(name))
        self._activate(mapname, name, draft, True)

    @minqlx.thread
    def _db_off(self, player, mapname, port):
        try:
            self.db.delete(KEY_ACTIVE.format(port))
        except Exception as exc:
            self._reply(player, "off failed: {}".format(exc))
            return
        self._reply(player, "preset off, vanilla layout, restarting")
        self._activate(mapname, None, empty_draft(), True)

    @minqlx.thread
    def _db_list(self, player, mapname, active):
        try:
            names = sorted(self.db.hkeys(KEY_PRESETS.format(mapname)) or [])
        except Exception as exc:
            self._reply(player, "list failed: {}".format(exc))
            return
        if not names:
            self._reply(player, "no presets for {}".format(mapname))
            return
        shown = ["^3{}^7 (active)".format(n) if n == active else n for n in names]
        self._reply(player, "presets for {}: {}".format(mapname, ", ".join(shown)))

    @minqlx.thread
    def _db_delete(self, player, mapname, name, port):
        try:
            gone = self.db.hdel(KEY_PRESETS.format(mapname), name)
            raw = self.db.get(KEY_ACTIVE.format(port))
            active = json.loads(raw) if raw else None
            if active and active.get("map") == mapname and active.get("name") == name:
                self.db.delete(KEY_ACTIVE.format(port))
        except Exception as exc:
            self._reply(player, "delete failed: {}".format(exc))
            return
        if not gone:
            self._reply(player, "no preset ^3{}^7 on {}".format(name, mapname))
            return
        self._deleted(mapname, name)
        self._reply(player, "deleted preset ^3{}^7 (the items on the map stay until a restart)".format(name))

    @minqlx.next_frame
    def _deleted(self, mapname, name):
        if mapname == self._map and self._active == name:
            self._active = None

    # --- commands ---

    def cmd_item(self, player, msg, channel):
        if len(msg) < 2:
            return minqlx.Return.USAGE
        sub = msg[1].lower()
        if sub == "list":
            self._tell_list(player)
            return
        if sub not in ("add", "remove", "replace", "move"):
            return minqlx.Return.USAGE
        if not self._can_edit(player):
            return
        if sub in ("add", "replace"):
            if len(msg) < 3:
                return minqlx.Return.USAGE
            classname = resolve_type(msg[2], self._known_items())
            if classname is None:
                self._tell(player, "unknown item ^3{}^7. Use: {} or a classname".format(msg[2], SHORT_NAMES))
                return
        pos = self._pos(player)
        if sub == "add":
            entry = self._place(classname, pos)
            self._tell(player, "added {}".format(classname) if entry else "the engine refused {} here".format(classname))
            return
        if sub == "move" and int(player.id) in self._picked:
            self._move_to(player, self._picked.pop(int(player.id)), pos)
            return
        target = nearest(self._items(), pos, self._radius())
        if target is None:
            self._tell(player, "no item within {:g} units".format(self._radius()))
            return
        if sub == "remove":
            self._take(target)
            self._tell(player, "removed {}".format(target.classname))
        elif sub == "replace":
            old, origin = str(target.classname), origin_of(target)
            self._take(target)
            entry = self._place(classname, origin)
            self._tell(player, "{} -> {}".format(old, classname) if entry
                       else "removed {}, the engine refused {} there".format(old, classname))
        else:
            self._picked[int(player.id)] = int(target.s.number)
            self._tell(player, "picked {}, go to the new spot and type ^3!item move^7 again".format(target.classname))

    def _move_to(self, player, number, pos):
        target = None
        for ent in self._items():
            if int(ent.s.number) == number:
                target = ent
                break
        if target is None:
            self._tell(player, "the picked item is gone (restart?), pick it again")
            return
        classname = str(target.classname)
        keys = self._take(target)
        entry = self._place(classname, pos, keys)
        self._tell(player, "moved {}".format(classname) if entry
                   else "removed {}, the engine refused it here".format(classname))

    def _tell_list(self, player):
        head = "preset ^3{}^7".format(self._active) if self._active else "no active preset"
        self._tell(player, "{} on {}: {} removed, {} added".format(
            head, self._map, len(self._draft["removed"]), len(self._draft["added"])))
        for entry in self._draft["removed"]:
            self._tell(player, "  - {} @ {}".format(entry["cn"], " ".join("{:g}".format(v) for v in entry["o"])))
        for entry in self._draft["added"]:
            self._tell(player, "  + {} @ {}".format(entry["cn"], " ".join("{:g}".format(v) for v in entry["o"])))

    def cmd_preset(self, player, msg, channel):
        if len(msg) < 2:
            return minqlx.Return.USAGE
        sub = msg[1].lower()
        if sub == "list":
            self._db_list(player, self._map, self._active)
            return
        if sub not in ("save", "load", "off", "delete"):
            return minqlx.Return.USAGE
        if not self._can_edit(player):
            return
        if sub == "off":
            self._db_off(player, self._map, self._port())
            return
        if len(msg) < 3:
            return minqlx.Return.USAGE
        name = msg[2]
        if not NAME_RE.match(name):
            self._tell(player, "preset name: letters, digits, . _ - (up to 32)")
            return
        if sub == "save":
            self._db_save(player, self._map, name, dump_preset(self._map, name, self._draft), self._port())
        elif sub == "load":
            self._db_load(player, self._map, name, self._port())
        else:
            self._db_delete(player, self._map, name, self._port())
