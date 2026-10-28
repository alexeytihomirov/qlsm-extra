# moba_spike.py - THROWAWAY phase 0 probe for the MOBA-lite mode (root-0034). Not for
# production, never merged to main. Answers live on a test instance:
#   (a) does botclip + a velocity nudge keep creep bots on a lane,
#   (b) does a pinned bot (speed 0 + position reset) work as a tower,
#   (c) how many bots the host takes.
# Needs a map with moba_* markers (ql-map-generator/qls/moba_spike.qls.json).
#
# Owner console only (rcon: qlx !moba_spike ...):
#   tower <red|blue>          one pinned bot at moba_tower_<team>_top_1, HP, RG, never respawns
#   creeps <red|blue> <n>     n bots at moba_creepspawn_<team>_top walking moba_path_top_*
#   load <n>                  n idle bots (load test)
#   clear                     kick every bot this plugin added
#   status                    roles, positions, nudges/s, our frame time
#
# CVARs:
#   qlx_mobaSpikeBotName "sarge"   bot character for addbot
#   qlx_mobaSpikeSkill "1"         bot skill for addbot
#   qlx_mobaSpikeTowerHealth "1000"

import collections
import math
import re
import time

try:
    import minqlxtended as minqlx
except ImportError:
    import minqlx

WEAPON_FIELDS = ("g", "mg", "sg", "gl", "rl", "lg", "rg", "pg", "bfg", "gh", "ng", "pl", "cg", "hmg", "hands")
TICK_S = 0.5
NUDGE_SPEED = 320.0
REACHED = 64.0
ENEMY_RANGE = 600.0
TOWER_DRIFT = 32.0
CVAR_DEFAULTS = (
    ("qlx_mobaSpikeBotName", "sarge"),
    ("qlx_mobaSpikeSkill", "1"),
    ("qlx_mobaSpikeTowerHealth", "1000"),
)
_PATH_RE = re.compile(r"^moba_path_(\w+?)_(\d+)$")


# --- pure helpers ------------------------------------------------------------

def parse_markers(entities):
    """MapEntity list -> {targetname: [origin, ...]} for moba_* targetnames with an origin."""
    markers = {}
    for e in entities:
        name = e.keys.get("targetname", "")
        if not name.startswith("moba_") or e.origin is None:
            continue
        markers.setdefault(name, []).append(tuple(float(c) for c in e.origin))
    return markers


def lane_path(markers, lane):
    """Ordered points moba_path_<lane>_<k>, k as an int."""
    points = []
    for name, origins in markers.items():
        m = _PATH_RE.match(name)
        if m and m.group(1) == lane:
            points.append((int(m.group(2)), origins[0]))
    return [p for _k, p in sorted(points)]


def nudge(pos, path, idx, speed=NUDGE_SPEED):
    """(next idx, horizontal velocity toward path[idx]); idx advances within REACHED units."""
    while idx < len(path) and math.hypot(path[idx][0] - pos[0], path[idx][1] - pos[1]) <= REACHED:
        idx += 1
    if idx >= len(path):
        return idx, (0.0, 0.0, 0.0)
    dx, dy = path[idx][0] - pos[0], path[idx][1] - pos[1]
    d = math.hypot(dx, dy)
    return idx, (dx / d * speed, dy / d * speed, 0.0)


def safe_bot_name(raw):
    """Only [A-Za-z0-9_]: the name goes into a console command."""
    return re.sub(r"[^A-Za-z0-9_]", "", raw or "") or "sarge"


def weapons_only(key):
    return tuple(f == key for f in WEAPON_FIELDS)


def dist2d(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


# --- plugin ------------------------------------------------------------------

class moba_spike(minqlx.Plugin):
    def __init__(self):
        self._markers = {}
        self._roles = {}                      # client id -> dict(role, team, anchor, idx, dead)
        self._pending = collections.deque()   # roles waiting for the next unclaimed bot
        self._item_hooked = False
        self._last_tick = 0.0
        self._nudges = 0
        self._nudge_window = (time.monotonic(), 0)
        self._frame_cost = collections.deque(maxlen=200)
        self._damage_seen = 0
        for name, value in CVAR_DEFAULTS:
            self.set_cvar_once(name, value)
        self.add_hook("map", self.handle_map)
        self.add_hook("player_spawn", self.handle_player_spawn)
        self.add_hook("player_disconnect", self.handle_player_disconnect)
        self.add_hook("death", self.handle_death)
        self.add_hook("damage", self.handle_damage)
        self.add_hook("frame", self.handle_frame)
        self.add_hook("unload", self.handle_unload)
        self.add_command("moba_spike", self.cmd_moba_spike, 5,
                         usage="<tower|creeps|load|clear|status> [team] [n]")
        self._load_markers(self.get_cvar("mapname"))

    # markers

    @minqlx.thread
    def _load_markers(self, mapname):
        entities = minqlx.map_entities(mapname)  # reads the BSP: worker thread only
        minqlx.next_frame(self._apply_markers)(mapname, entities)

    def _apply_markers(self, mapname, entities):
        self._markers = parse_markers(entities)
        if not self._markers:
            self.logger.warning("moba_spike: no moba_* markers on %s, idle", mapname)
        else:
            self.logger.info("moba_spike: %d markers on %s", len(self._markers), mapname)

    def handle_map(self, mapname, factory):
        self._roles.clear()
        self._pending.clear()
        self._sync_item_hook()
        self._load_markers(mapname)

    def _marker(self, name):
        origins = self._markers.get(name)
        return origins[0] if origins else None

    # bots

    def _addbot(self, team, role):
        name = safe_bot_name(self.get_cvar("qlx_mobaSpikeBotName"))
        skill = int(self.get_cvar("qlx_mobaSpikeSkill") or "1")
        self._pending.append(role)
        minqlx.console_command("addbot {} {} {}".format(name, skill, team))

    def _claim(self, player):
        """First spawn of an unclaimed bot takes the oldest pending role of its own team."""
        # Not steam_id == 0: a QL bot reports 90071996842377216 (seen live on #26).
        if player.id in self._roles or not getattr(player, "is_bot", False) or not self._pending:
            return self._roles.get(player.id)
        role = next((r for r in self._pending if r.get("team") == player.team), None)
        if role is None:
            return None
        self._pending.remove(role)
        self._roles[player.id] = role
        self._sync_item_hook()
        return role

    def handle_player_spawn(self, player):
        role = self._claim(player)
        if role is not None:
            minqlx.next_frame(self._setup_bot)(player.id)

    def _setup_bot(self, cid):
        player = self.player(cid)
        role = self._roles.get(cid)
        if player is None or role is None:
            return
        try:
            if role["role"] == "tower":
                if role["dead"]:
                    minqlx.console_command("clientkick {}".format(cid))
                    return
                player.position = role["anchor"]
                player.velocity = (0, 0, 0)
                player.health = int(self.get_cvar("qlx_mobaSpikeTowerHealth") or "1000")
                player.weapons = minqlx.Weapons(weapons_only("rg"))
                player.weapon = WEAPON_FIELDS.index("rg") + 1
                player.speed = 0
            elif role["role"] == "creep":
                player.position = role["anchor"]
                player.health = 100
                player.weapons = minqlx.Weapons(weapons_only("mg"))
                player.weapon = WEAPON_FIELDS.index("mg") + 1
                role["idx"] = 0
        except Exception as e:
            self.logger.warning("moba_spike: setup of %s failed: %s", cid, e)

    def handle_death(self, victim, killer, data):
        role = self._roles.get(victim.id)
        if role is not None and role["role"] == "tower":
            role["dead"] = True
            self.msg("moba_spike: tower {} destroyed".format(role["team"]))

    def handle_damage(self, target, attacker, damage, dflags, mod):
        if target is not None and getattr(target, "id", None) in self._roles:
            self._damage_seen += 1
            if self._damage_seen <= 5:
                self.logger.info("moba_spike: damage %s -> bot %s (%s)", damage, target.id, mod)

    def handle_player_disconnect(self, player, reason):
        self._roles.pop(player.id, None)
        self._sync_item_hook()

    # items: bots of this plugin never pick anything up

    def _sync_item_hook(self):
        active = bool(self._roles) or bool(self._pending)
        if active == self._item_hooked or "item_touch" not in minqlx.EVENT_DISPATCHERS:
            return
        if active:
            self.add_hook("item_touch", self.handle_item_touch, priority=minqlx.Priority.HIGH)
        else:
            self.remove_hook("item_touch", self.handle_item_touch, priority=minqlx.Priority.HIGH)
        self._item_hooked = active

    def handle_item_touch(self, player, entity):
        if player is not None and player.id in self._roles:
            return minqlx.Return.STOP_EVENT

    # per tick

    def handle_frame(self):
        now = time.monotonic()
        if now - self._last_tick < TICK_S or not self._roles:
            return
        self._last_tick = now
        t0 = time.perf_counter()
        path = lane_path(self._markers, "top")
        humans_and_bots = {p.id: p for p in self.players()}
        for cid, role in list(self._roles.items()):
            player = humans_and_bots.get(cid)
            if player is None or not player.is_alive:
                continue
            try:
                pos = tuple(player.position)
                if role["role"] == "tower":
                    if dist2d(pos, role["anchor"]) > TOWER_DRIFT:
                        player.position = role["anchor"]
                        player.velocity = (0, 0, 0)
                elif role["role"] == "creep" and path:
                    if self._enemy_near(player, pos, humans_and_bots.values()):
                        continue
                    lane = path if role["team"] == "red" else list(reversed(path))
                    role["idx"], vel = nudge(pos, lane, role["idx"])
                    player.velocity = (vel[0], vel[1], tuple(player.velocity)[2])
                    self._nudges += 1
            except Exception:
                continue  # left or died between the snapshot and the setter
        self._frame_cost.append(time.perf_counter() - t0)

    @staticmethod
    def _enemy_near(player, pos, players):
        for other in players:
            if other.team in ("red", "blue") and other.team != player.team and other.is_alive:
                if dist2d(pos, tuple(other.position)) <= ENEMY_RANGE:
                    return True
        return False

    # command

    def cmd_moba_spike(self, player, msg, channel):
        args = msg[1:]
        if not args:
            return minqlx.Return.USAGE
        sub = args[0].lower()
        if sub in ("tower", "creeps") and (len(args) < 2 or args[1] not in ("red", "blue")):
            return minqlx.Return.USAGE
        if sub in ("tower", "creeps", "load") and not self._markers:
            channel.reply("moba_spike: no moba_* markers on this map")
            return
        if sub == "tower":
            team = args[1]
            name = "moba_tower_{}_top_1".format(team)
            anchor = self._marker(name)
            if anchor is None:
                channel.reply("moba_spike: no marker {}".format(name))
                return
            self._addbot(team, dict(role="tower", team=team, anchor=anchor, idx=0, dead=False))
        elif sub == "creeps":
            team, n = args[1], int(args[2]) if len(args) > 2 else 3
            name = "moba_creepspawn_{}_top".format(team)
            anchor = self._marker(name)
            if anchor is None:
                channel.reply("moba_spike: no marker {}".format(name))
                return
            for i in range(n):
                # bots placed on one point stick inside each other: spread them across the lane
                spot = (anchor[0], anchor[1] + 40 * (i - (n - 1) / 2), anchor[2])
                self._addbot(team, dict(role="creep", team=team, anchor=spot, idx=0, dead=False))
        elif sub == "load":
            n = int(args[1]) if len(args) > 1 else 10
            for i in range(n):
                team = "red" if i % 2 == 0 else "blue"
                self._addbot(team, dict(role="idle", team=team, anchor=None, idx=0, dead=False))
        elif sub == "clear":
            for cid in list(self._roles):
                minqlx.console_command("clientkick {}".format(cid))
            self._pending.clear()
        elif sub == "status":
            self._status(channel)
        else:
            return minqlx.Return.USAGE

    def _status(self, channel):
        counts = collections.Counter(r["role"] for r in self._roles.values())
        t_start, n_start = self._nudge_window
        now = time.monotonic()
        rate = (self._nudges - n_start) / max(now - t_start, 1e-6)
        self._nudge_window = (now, self._nudges)
        cost = (sum(self._frame_cost) / len(self._frame_cost) * 1000) if self._frame_cost else 0.0
        channel.reply("moba_spike: markers {} roles {} pending {} nudges/s {:.1f} tick {:.2f} ms damage {}".format(
            len(self._markers), dict(counts), len(self._pending), rate, cost, self._damage_seen))
        for cid, role in sorted(self._roles.items()):
            p = self.player(cid)
            pos = tuple(int(c) for c in p.position) if p is not None else None
            channel.reply("  {} {} {} idx {} dead {} pos {}".format(
                cid, role["role"], role["team"], role["idx"], role["dead"], pos))

    def handle_unload(self, plugin):
        if plugin == self.__class__.__name__ and self._item_hooked:
            self.remove_hook("item_touch", self.handle_item_touch, priority=minqlx.Priority.HIGH)
            self._item_hooked = False
