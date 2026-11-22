# rl_rules.py - roguelike rules: markers, runs, rooms, occupancy, teleporter offers, lives. No engine calls.
#
# roguelike.py feeds World the clock, each player's position and the live mob count of their room,
# and acts on the events it returns. One player per room; a run is the rooms in the order the player picks.
import math
import random
import re
from collections import namedtuple

Room = namedtuple("Room", "id type start doors finish pit_z turrets mobs")
Layout = namedtuple("Layout", "hub_start rooms skipped")
MobType = namedtuple("MobType", "name hp speed attack parts frames fps hull")
MobAttack = namedtuple("MobAttack", "damage splash radius interval range muzzle")
Turret = namedtuple("Turret", "weapon attack parts")

START_LIVES = 3
MOVE_LIMIT_S = 45
DODGE_SURVIVE_S = 30
PAD_RANGE = 32
HINT_RANGE = 56
FINISH_RANGE = 48
PIT_MARGIN = 32
MAX_MOBS = 15
MAX_MISSILES = 10
MOB_SPAWN_S = 0.7
OFFER_RETRY_S = 1.0

TYPES = ("move", "dodge", "arena")


def _md3(*names):
    return tuple("models/td/{}.md3".format(n) for n in names)


# hull: (half width, top above the hull origin), as in td_rules.CREEPS
MOBS = {
    "chaser": MobType("chaser", 100, 260, "bite", _md3("normal", "normal_gun"), (1, 29), 20, (20, 26)),
    "shooter": MobType("shooter", 150, 120, "pg", _md3("shooter", "shooter_head"), (5, 25), 20, (40, 130)),
}

# muzzle: above the hull origin
ATTACKS = {
    "bite": MobAttack(15, 0, 0, 1.0, 56, 20),
    "pg": MobAttack(12, 0, 0, 0.8, 1200, 20),
}

TURRET = Turret("rl", MobAttack(50, 40, 100, 1.5, 2000, 34), _md3("turret_base", "turret_rl"))

ARENA_WAVES = [[("chaser", 4)], [("chaser", 4), ("shooter", 2)]]

KITS = {"move": "g", "dodge": "g", "arena": "g mg sg"}

_MARKER = re.compile(r"^rl_([a-z]+)(\d+)_(start|finish|pit|door_(\d+)|turret_(\d+)|mob_(\d+))$")


def parse_markers(named):
    """named: (targetname, origin). None without rl_hub_start or without one complete room."""
    hub = None
    parts = {}
    for name, origin in named:
        origin = tuple(origin)
        if name == "rl_hub_start":
            hub = origin
            continue
        m = _MARKER.match(name)
        if not m:
            continue
        room_id = m.group(1) + m.group(2)
        p = parts.setdefault(room_id, {"type": m.group(1), "doors": {}, "turrets": {}, "mobs": {}})
        kind = m.group(3)
        if m.group(4) is not None:
            p["doors"][int(m.group(4))] = origin
        elif m.group(5) is not None:
            p["turrets"][int(m.group(5))] = origin
        elif m.group(6) is not None:
            p["mobs"][int(m.group(6))] = origin
        else:
            p[kind] = origin
    rooms, skipped = {}, []
    for room_id, p in sorted(parts.items()):
        kind = p["type"]
        ok = kind in TYPES and "start" in p and p["doors"]
        if kind == "move":
            ok = ok and "finish" in p and "pit" in p
        elif kind == "dodge":
            ok = ok and bool(p["turrets"])
        elif kind == "arena":
            ok = ok and bool(p["mobs"])
        if not ok:
            skipped.append(room_id)
            continue
        ordered = lambda d: [d[k] for k in sorted(d)]  # noqa: E731
        rooms[room_id] = Room(room_id, kind, p["start"], ordered(p["doors"]), p.get("finish"),
                              p["pit"][2] if "pit" in p else None, ordered(p["turrets"]), ordered(p["mobs"]))
    if hub is None or not rooms:
        return None
    return Layout(hub, rooms, skipped)


def _flat(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


class Run:
    def __init__(self, room, now):
        self.room = room
        self.lives = START_LIVES
        self.phase = "play"
        self.visited = [room]
        self.offers = {}
        self.started = now
        self.seen = now
        self.room_t0 = now
        self.queue = []
        self.wave = 0
        self.next_spawn = now
        self.next_point = 0
        self.offers_built = now
        self.hinted = None
        self.blocked = None


class World:
    def __init__(self, layout, rng=random):
        self.layout = layout
        self.rng = rng
        self._runs = {}

    # queries

    def run(self, cid):
        return self._runs.get(cid)

    def occupied(self):
        return {r.room: cid for cid, r in self._runs.items()}

    def where(self, cid):
        r = self._runs.get(cid)
        return self.layout.rooms[r.room].start if r else None

    # state changes

    def begin(self, cid, now):
        if cid in self._runs:
            return []
        taken = self.occupied()
        free = [rid for rid in sorted(self.layout.rooms) if rid not in taken]
        if not free:
            return [("full",)]
        room = self.rng.choice(free)
        self._runs[cid] = Run(room, now)
        self._start_room(self._runs[cid], now)
        return [("enter", room)]

    def force(self, cid, room_id, now):
        """!rlroom: put cid's run into room_id. [] when the room does not exist or holds another player."""
        if room_id not in self.layout.rooms or self.occupied().get(room_id, cid) != cid:
            return []
        r = self._runs.get(cid)
        if r is None:
            r = self._runs[cid] = Run(room_id, now)
        else:
            r.room = room_id
            if room_id not in r.visited:
                r.visited.append(room_id)
        r.seen = now
        self._start_room(r, now)
        return [("enter", room_id)]

    def leave(self, cid):
        r = self._runs.pop(cid, None)
        if r is None:
            return []
        return [("hub", "left", r.seen - r.started)]

    def drop_all(self):
        self._runs.clear()

    def died(self, cid, now):
        r = self._runs.get(cid)
        if r is None:
            return []
        r.seen = now
        if r.phase != "play":
            return []  # nothing in a cleared room can kill: no life lost, respawn at the room start
        return self._lose_life(cid, r, now)

    def tick(self, cid, pos, now, alive_mobs):
        r = self._runs.get(cid)
        if r is None:
            return []
        r.seen = now
        room = self.layout.rooms[r.room]
        if room.type == "move" and pos[2] < room.pit_z + PIT_MARGIN:
            return [("fall",)]
        if r.phase == "play":
            return self._play(cid, r, room, pos, now, alive_mobs)
        return self._exit(cid, r, room, pos, now)

    # internals

    def _start_room(self, r, now):
        r.phase = "play"
        r.offers = {}
        r.room_t0 = now
        r.wave = 0
        r.queue = self._wave_queue(0)
        r.next_spawn = now
        r.next_point = 0
        r.hinted = None
        r.blocked = None

    @staticmethod
    def _wave_queue(index):
        waves = ARENA_WAVES
        if index >= len(waves):
            return []
        return [name for name, count in waves[index] for _ in range(count)]

    def _lose_life(self, cid, r, now):
        r.lives -= 1
        if r.lives <= 0:
            del self._runs[cid]
            return [("hub", "dead", now - r.started)]
        self._start_room(r, now)
        return [("lives", r.lives), ("restart", r.room)]

    def _play(self, cid, r, room, pos, now, alive_mobs):
        if room.type == "move":
            if _flat(pos, room.finish) <= FINISH_RANGE:
                return self._clear(r, room, now)
            if now - r.room_t0 >= MOVE_LIMIT_S:
                return self._lose_life(cid, r, now)
            return []
        if room.type == "dodge":
            if now - r.room_t0 >= DODGE_SURVIVE_S:
                return self._clear(r, room, now)
            return []
        # arena
        if not r.queue and alive_mobs == 0:
            r.wave += 1
            if r.wave >= len(ARENA_WAVES):
                return self._clear(r, room, now)
            r.queue = self._wave_queue(r.wave)
            r.next_spawn = now
        if r.queue and now >= r.next_spawn and alive_mobs < MAX_MOBS:
            name = r.queue.pop(0)
            point = r.next_point % len(room.mobs)
            r.next_point += 1
            r.next_spawn = now + MOB_SPAWN_S
            return [("spawn_mob", name, point)]
        return []

    def _clear(self, r, room, now):
        r.phase = "cleared"
        r.offers = self._build_offers(r, room)
        r.offers_built = now
        return [("cleared", room.id, r.offers)]

    def _build_offers(self, r, room):
        doors = list(range(len(room.doors)))
        unvisited = [rid for rid in self.layout.rooms if rid not in r.visited]
        if not unvisited:
            return {self.rng.choice(doors): "hub"}
        taken = self.occupied()
        types = sorted({self.layout.rooms[rid].type for rid in unvisited if rid not in taken})
        if len(types) > len(doors):
            types = sorted(self.rng.sample(types, len(doors)))
        picked = self.rng.sample(doors, len(types))
        return dict(zip(picked, types))

    def _exit(self, cid, r, room, pos, now):
        events = []
        if not r.offers and now - r.offers_built >= OFFER_RETRY_S:
            r.offers_built = now
            r.offers = self._build_offers(r, room)
            if r.offers:
                events.append(("offers", r.offers))
        if r.blocked is not None and _flat(pos, room.doors[r.blocked]) > PAD_RANGE:
            r.blocked = None
        best, best_d = None, None
        for door in r.offers:
            d = _flat(pos, room.doors[door])
            if best_d is None or d < best_d:
                best, best_d = door, d
        if best is None or best_d > HINT_RANGE:
            r.hinted = None
            return events
        if best_d <= PAD_RANGE and best != r.blocked:
            return events + self._step(cid, r, room, best, now)
        if best != r.hinted:
            r.hinted = best
            events.append(("hint", best))
        return events

    def _step(self, cid, r, room, door, now):
        kind = r.offers[door]
        if kind == "hub":
            del self._runs[cid]
            return [("hub", "done", now - r.started)]
        taken = self.occupied()
        free = [rid for rid in sorted(self.layout.rooms)
                if self.layout.rooms[rid].type == kind and rid not in taken and rid not in r.visited]
        if not free:
            r.blocked = door
            r.offers = self._build_offers(r, room)
            r.offers_built = now
            return [("full",), ("offers", r.offers)]
        target = self.rng.choice(free)
        r.room = target
        r.visited.append(target)
        self._start_room(r, now)
        return [("enter", target)]
