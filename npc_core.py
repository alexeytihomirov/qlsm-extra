# npc_core.py - server entities as creeps and turrets: no bots, no engine change. No game rules.
#
# A creep is a pair. The hull is an invisible ET_ITEM: it takes hits with the hit sound, and
# G_RunItem moves it along TR_LINEAR with a trace. The visual is an ET_GENERAL with any md3,
# copying the hull's trajectory; s.frame is the animation. A part stays on frame 0 unless it
# is the first one, because heads and guns have few frames.
#
# Hull health starts at BASE_HP and the caller removes the pair at its limit, so the engine's
# die callback (NULL on an info_notnull) is never reached.
#
# Turret missiles clip walls only, so they can never touch a player: a mask that hits a hull
# also hits players. tick_missiles finds the hull hit, explodes the missile by event and
# applies the damage here. Creep missiles mask CLIP_HITS_PLAYERS: the engine flies them past
# hulls, into players.
import math

try:
    import minqlxtended as minqlx
except ImportError:
    import minqlx

BASE_HP = 100000
STUCK_S = 3.0
REACH_U = 16.0
HULL_CONTENTS = 0x4000000  # CONTENTS_CORPSE: players walk through, their shots hit
CLIP_HITS_CREEPS = 0x1  # CONTENTS_SOLID: the plugin does the hit test
CLIP_HITS_PLAYERS = 0x2000001  # SOLID + BODY: passes hulls
ENTITYNUM_NONE = 1023
SVF_NOCLIENT = 0x1
SVF_USE_CURRENT_ORIGIN = 0x80
EV_FIRE_WEAPON = 0x14
MISSILE_PRESTEP_MS = 50
FLOOR_TO_HULL = 26.0  # hull origin above the floor: mins -24 and 2 u clear; md3 origin is at the feet
HULL_MIN_Z = -24.0
HIT_RADIUS = 64.0
EXPLOSION_S = 0.5
CS_ITEM_BITS = (13, 16)  # bg_itemlist index of RL and PG: cgame loads a weapon's effects only with its bit
MAX_MODELS = 256

_WEAPONS = {"rl": ("ROCKET_LAUNCHER", 900.0, "ROCKET", "ROCKET_SPLASH"),
            "pg": ("PLASMAGUN", 2000.0, "PLASMA", "PLASMA_SPLASH")}

_model_slots = {}
_flying = {}  # missile number -> dict(damage, radius, last, gone); damage None for an engine-run one


class Npc:
    def __init__(self, hull, visuals, hp_limit, origin, now, frames=None, fps=0):
        self.hull = hull
        self.visuals = visuals
        self.hp_limit = hp_limit
        self.path = []
        self.idx = 0
        self.speed = 0.0
        self.vel = (0.0, 0.0, 0.0)
        self.frames = frames
        self.fps = fps
        self.frame = None
        self.born = now
        self.pos = origin
        self.last_pos = origin
        self.last_move = now
        self.last_shot = 0.0


# pure


def steer(pos, waypoint, speed):
    dx, dy = waypoint[0] - pos[0], waypoint[1] - pos[1]
    dist = math.hypot(dx, dy) or 1.0
    return (dx / dist * speed, dy / dist * speed, 0.0)


def reached(pos, waypoint):
    return math.hypot(waypoint[0] - pos[0], waypoint[1] - pos[1]) <= REACH_U


def next_frame(first, last, elapsed_s, fps):
    return first + int(elapsed_s * fps) % (last - first + 1)


def nearest(pos, candidates, max_range):
    """candidates: (position, value) pairs. The value of the closest one in range, or None."""
    best, best_d = None, max_range * max_range
    for where, value in candidates:
        d = (where[0] - pos[0]) ** 2 + (where[1] - pos[1]) ** 2 + (where[2] - pos[2]) ** 2
        if d <= best_d:
            best, best_d = value, d
    return best


def lead(muzzle, target, vel, speed):
    """Where to aim so a missile at speed meets a target moving at vel."""
    t = math.dist(muzzle, target) / speed
    return tuple(target[i] + vel[i] * t for i in range(3))


def speed_of(weapon):
    return _WEAPONS[weapon][1]


def closest_on_segment(a, b, point):
    ab = tuple(b[i] - a[i] for i in range(3))
    length = sum(c * c for c in ab)
    if not length:
        return a
    t = max(0.0, min(1.0, sum((point[i] - a[i]) * ab[i] for i in range(3)) / length))
    return tuple(a[i] + ab[i] * t for i in range(3))


def _passed(pos, waypoint, vel):
    return (waypoint[0] - pos[0]) * vel[0] + (waypoint[1] - pos[1]) * vel[1] < 0


# configstrings


def reset_cache():
    _model_slots.clear()
    _flying.clear()


def model_index(path):
    slot = _model_slots.get(path)
    if slot is not None:
        return slot
    for i in range(1, MAX_MODELS):
        name = minqlx.configstring(minqlx.CS_MODELS + i, cached=False)
        if name in ("", path):
            if not name:
                minqlx.set_configstring(minqlx.CS_MODELS + i, path)
            _model_slots[path] = i
            return i
    raise RuntimeError("no free CS_MODELS slot for " + path)


def preload_weapons():
    bits = list(minqlx.configstring(minqlx.CS_ITEMS, cached=False))
    for index in CS_ITEM_BITS:
        bits += ["0"] * (index + 1 - len(bits))
        bits[index] = "1"
    minqlx.set_configstring(minqlx.CS_ITEMS, "".join(bits))


# pairs


def _visual(origin, path):
    e = minqlx.spawn_entity("info_notnull", {"origin": origin})
    if e is None:
        raise RuntimeError("spawn_entity returned None")
    e.s.e_type = minqlx.EntityType.GENERAL
    e.s.modelindex = model_index(path)
    e.s.pos_type = minqlx.TrajectoryType.STATIONARY
    e.s.pos_base = origin
    e.r.current_origin = origin
    minqlx.link_entity(e.s.number)
    return e.s.number


def _visual_origin(origin):
    return (origin[0], origin[1], origin[2] - FLOOR_TO_HULL)


def spawn_pair(origin, parts, hp_limit, now, solid=True, hull_size=(16, 32), frames=None, fps=0):
    """origin: the hull origin, FLOOR_TO_HULL above the floor. solid=False: no hull, a thing to look at."""
    hull_num = None
    visuals = []
    try:
        if solid:
            e = minqlx.spawn_entity("info_notnull", {"origin": origin})
            if e is None:
                raise RuntimeError("spawn_entity returned None")
            hull_num = e.s.number
            e.s.e_type = minqlx.EntityType.ITEM
            e.s.modelindex = 1
            e.s.pos_type = minqlx.TrajectoryType.STATIONARY
            e.s.pos_base = origin
            e.s.origin = origin
            e.r.current_origin = origin
            half, top = hull_size
            e.r.mins = (-float(half), -float(half), HULL_MIN_Z)
            e.r.maxs = (float(half), float(half), float(top))
            e.r.contents = HULL_CONTENTS
            e.r.sv_flags = e.r.sv_flags | SVF_NOCLIENT
            e.clipmask = CLIP_HITS_CREEPS
            e.r.owner_num = ENTITYNUM_NONE
            e.takedamage = True
            e.health = BASE_HP
            minqlx.link_entity(hull_num)
        for path in parts:
            visuals.append(_visual(_visual_origin(origin), path))
    except Exception:
        for num in visuals + ([hull_num] if hull_num is not None else []):
            minqlx.remove_entity(num)
        raise
    return Npc(hull_num, visuals, hp_limit, origin, now, frames, fps)


def remove(npc):
    for num in npc.visuals + ([npc.hull] if npc.hull is not None else []):
        minqlx.remove_entity(num)


def damage_taken(npc):
    return BASE_HP - minqlx.Entity(npc.hull).health


def damage(npc, amount):
    hull = minqlx.Entity(npc.hull)
    hull.health = hull.health - int(amount)


def _write_trajectory(num, pos, vel, level_time, moving):
    e = minqlx.Entity(num)
    e.s.pos_base = pos
    e.s.pos_time = level_time
    e.s.pos_delta = vel
    e.s.pos_type = minqlx.TrajectoryType.LINEAR if moving else minqlx.TrajectoryType.STATIONARY
    e.r.current_origin = pos
    return e


def _resteer(npc, pos):
    npc.vel = steer(pos, npc.path[npc.idx], npc.speed)
    level_time = minqlx.level.time
    _write_trajectory(npc.hull, pos, npc.vel, level_time, True)
    minqlx.link_entity(npc.hull)
    low = _visual_origin(pos)
    yaw = math.degrees(math.atan2(npc.vel[1], npc.vel[0]))
    for num in npc.visuals:
        e = _write_trajectory(num, low, npc.vel, level_time, True)
        e.s.apos_base = (0.0, yaw, 0.0)
        minqlx.link_entity(num)


def start_path(npc, path, speed, now):
    npc.path = list(path)
    npc.idx = 0
    npc.speed = float(speed)
    npc.last_move = now
    npc.last_pos = npc.pos
    if reached(npc.pos, npc.path[0]) and len(npc.path) > 1:
        npc.idx = 1
    _resteer(npc, npc.pos)


def tick(npc, now):
    hull = minqlx.Entity(npc.hull)
    if not hull.inuse:
        return "stuck"
    if BASE_HP - hull.health >= npc.hp_limit:
        return "dead"
    pos = tuple(hull.r.current_origin)
    npc.pos = pos
    if reached(pos, npc.path[npc.idx]) or _passed(pos, npc.path[npc.idx], npc.vel):
        npc.idx += 1
        if npc.idx >= len(npc.path):
            return "arrived"
        _resteer(npc, pos)
    if abs(pos[0] - npc.last_pos[0]) > 1.0 or abs(pos[1] - npc.last_pos[1]) > 1.0:
        npc.last_pos = pos
        npc.last_move = now
    elif now - npc.last_move >= STUCK_S:
        return "stuck"
    elif hull.s.pos_type != minqlx.TrajectoryType.LINEAR:
        _resteer(npc, pos)  # G_RunItem stopped it short of the waypoint
    if npc.frames:
        frame = next_frame(npc.frames[0], npc.frames[1], now - npc.born, npc.fps)
        if frame != npc.frame:
            npc.frame = frame
            minqlx.Entity(npc.visuals[0]).s.frame = frame
    return "alive"


def aim_visual(npc, part, target):
    num = npc.visuals[part]
    e = minqlx.Entity(num)
    origin = e.s.pos_base
    dx, dy, dz = target[0] - origin[0], target[1] - origin[1], target[2] - origin[2]
    e.s.apos_base = (-math.degrees(math.atan2(dz, math.hypot(dx, dy))), math.degrees(math.atan2(dy, dx)), 0.0)


# missiles


def fire(muzzle, target, weapon, damage_amount, splash, radius, owner, clipmask, visual=None, speed=None):
    """Spawns a missile, returns its number. owner: the entity number recorded as its parent."""
    weapon_name, default_speed, mod, splash_mod = _WEAPONS[weapon]
    aim = tuple(target[i] - muzzle[i] for i in range(3))
    dist = math.sqrt(sum(c * c for c in aim)) or 1.0
    velocity = speed or default_speed
    m = minqlx.spawn_entity("info_notnull", {"origin": muzzle})
    if m is None:
        raise RuntimeError("spawn_entity returned None")
    wp = getattr(minqlx.Weapon, weapon_name)
    m.s.e_type = minqlx.EntityType.MISSILE
    m.s.weapon = wp
    m.s.pos_type = minqlx.TrajectoryType.LINEAR
    m.s.pos_time = minqlx.level.time - MISSILE_PRESTEP_MS
    m.s.pos_base = muzzle
    m.s.pos_delta = tuple(c / dist * velocity for c in aim)
    m.r.current_origin = muzzle
    m.r.owner_num = ENTITYNUM_NONE
    m.r.sv_flags = SVF_USE_CURRENT_ORIGIN
    m.parent = minqlx.Entity(owner)
    m.clipmask = clipmask
    m.damage = int(damage_amount)
    m.splash_damage = int(splash)
    m.splash_radius = int(radius)
    m.method_of_death = getattr(minqlx.Mod, mod)
    m.splash_method_of_death = getattr(minqlx.Mod, splash_mod)
    m.nextthink = 0  # no think: a NULL think with a nextthink is G_Error
    minqlx.link_entity(m.s.number)
    if visual is not None:
        minqlx.Entity(visual).s.weapon = wp
        minqlx.add_event(visual, EV_FIRE_WEAPON)
    _flying[m.s.number] = dict(damage=None, radius=0, last=muzzle, gone=None)
    return m.s.number


def fire_at_creeps(muzzle, target, weapon, amount, radius, owner, visual=None):
    """A turret missile: harmless to the engine, tick_missiles applies amount, radius > 0 for an area."""
    num = fire(muzzle, target, weapon, 0, 0, 0, owner, CLIP_HITS_CREEPS, visual)
    _flying[num].update(damage=amount, radius=radius)
    return num


def missiles_in_flight():
    return sum(1 for f in _flying.values() if f["gone"] is None)


def missile_gone(num):
    e = minqlx.Entity(num)
    return not e.inuse or e.s.e_type != minqlx.EntityType.MISSILE


def area_damage(npcs, pos, radius, amount, skip=None):
    for npc in npcs:
        if npc is skip:
            continue
        d = math.dist(npc.pos, pos)
        if d < radius:
            damage(npc, amount * (1.0 - d / radius))


def _explode(num, m, pos, now, flight):
    m.clipmask = 0
    m.s.pos_base = pos
    m.s.pos_type = minqlx.TrajectoryType.STATIONARY
    m.s.e_type = minqlx.EntityType.GENERAL
    m.s.modelindex = 0
    m.r.current_origin = pos
    minqlx.link_entity(num)
    minqlx.add_event(num, minqlx.EntityEvent.MISSILE_MISS, 5)
    flight["gone"] = now + EXPLOSION_S


def tick_missiles(npcs, now):
    """npcs: the creeps, with npc.pos fresh. Drops spent missiles, explodes those that met a hull."""
    level_time = minqlx.level.time
    for num, flight in list(_flying.items()):
        if flight["gone"] is not None:
            if now >= flight["gone"]:
                minqlx.remove_entity(num)
                del _flying[num]
            continue
        m = minqlx.Entity(num)
        if not m.inuse or m.s.e_type != minqlx.EntityType.MISSILE:
            del _flying[num]  # the engine exploded it on a wall or on a player
            continue
        if flight["damage"] is None:
            continue
        dt = (level_time - m.s.pos_time) / 1000.0
        pos = tuple(m.s.pos_base[i] + m.s.pos_delta[i] * dt for i in range(3))
        last = flight["last"]
        flight["last"] = pos
        for npc in npcs:
            where = closest_on_segment(last, pos, npc.pos)
            if math.dist(where, npc.pos) <= HIT_RADIUS:
                _explode(num, m, where, now, flight)
                damage(npc, flight["damage"])
                if flight["radius"]:
                    area_damage(npcs, where, flight["radius"], flight["damage"], skip=npc)
                break


def clear_missiles():
    for num, flight in _flying.items():
        if flight["gone"] is not None or not missile_gone(num):
            minqlx.remove_entity(num)
    _flying.clear()
