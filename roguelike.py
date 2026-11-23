# roguelike.py - solo runs through sealed rooms (root-0042, stage 1 probe). Map markers turn it on:
# rl_hub_start, rl_<type><n>_start/_door_K/..., see rl_rules.parse_markers. Without them every hook
# returns at once.
#
#   step on the hub pad        starts a run in a random free room
#   !rl                        room, lives, run time
#   !rlroom <room id>          start or move your run into that room, permission 5
#
# rl_rules.World owns runs, rooms and offers; this file turns its events into engine calls. One
# player per room. The game runs in warmup, everyone on red, as in tower_defence.
import math
import random
import time

try:
    import minqlxtended as minqlx
except ImportError:
    import minqlx

try:
    import npc_core
except ImportError:
    from . import npc_core

try:
    import rl_rules
except ImportError:
    from . import rl_rules

TICK_S = 0.05
ERROR_LOG_S = 10.0
FULL_TELL_S = 5.0
PLUM_S = 0.25
MOB_LIFT = 4.0  # hull origin above a floor marker: hull bottom 4 u up, clear of 2 u floor patches
TURRET_LIFT = 2.0  # a turret stands on its block like a tower_defence turret on a pad
PAD_LIFT = 2.0
AIM_ABOVE = 10.0  # a player's chest above the player origin
BITE_FROM = 8.0  # the bite missile starts this far from the chest, on the mob's side
CHASE_TURN = 360.0  # degrees per second
BITE_WEAPON = "pg"  # Task 3: damage is exact either way, plasma has no splash
PAD_MODEL = ("models/mapobjects/flagbase/ntrl_base.md3",)
WEAPON_FIELDS = ("g", "mg", "sg", "gl", "rl", "lg", "rg", "pg", "bfg", "gh", "ng", "pl", "cg", "hmg", "hands")
LABELS = {"move": "Movement", "dodge": "Dodge", "arena": "Arena", "hub": "Back to the hub"}
REASONS = {"done": "all rooms cleared", "dead": "out of lives", "left": "left the room"}

_ENGINE_ERR = getattr(minqlx, "EngineStateError", RuntimeError)


def _plays(player):
    return player.team in ("red", "blue")


def _lift(marker, dz):
    return (marker[0], marker[1], marker[2] + dz)


def _kit(letters):
    keys = set(letters.split()) | {"g"}
    weapons = tuple(f in keys for f in WEAPON_FIELDS)
    held = next((f for f in WEAPON_FIELDS if f in keys and f != "g"), "g")
    return weapons, WEAPON_FIELDS.index(held) + 1


def _clock(seconds):
    seconds = max(0, int(seconds))
    return "{}:{:02d}".format(seconds // 60, seconds % 60)


class Room:
    """The entities of one occupied room. cid: its player."""

    def __init__(self, cid):
        self.cid = cid
        self.mobs = []
        self.turrets = []
        self.pads = []
        self.missiles = set()


class roguelike(minqlx.Plugin):
    def __init__(self):
        self._init_state()
        self.add_hook("map", self.handle_map)
        self.add_hook("new_game", self.handle_new_game)
        self.add_hook("frame", self.handle_frame)
        self.add_hook("player_loaded", self.handle_player_loaded)
        self.add_hook("player_spawn", self.handle_player_spawn)
        self.add_hook("death", self.handle_death)
        self.add_hook("player_disconnect", self.handle_player_disconnect)
        self.add_hook("team_switch", self.handle_team_switch)
        self.add_hook("team_switch_attempt", self.handle_team_switch_attempt)
        self.add_hook("unload", self.handle_unload)
        self.add_command("rl", self.cmd_rl)
        self.add_command("rlroom", self.cmd_rlroom, 5, usage="<room id>")
        self._load_markers(self.get_cvar("mapname"))

    def _init_state(self):
        self._world = None
        self._hub_spawns = []
        self._rooms = {}
        self._scene = []
        self._rng = random.Random()
        self._last_tick = 0.0
        self._last_plum = 0.0
        self._last_error = -ERROR_LOG_S
        self._last_full = {}
        self._unloaded = False

    # markers

    @minqlx.thread
    def _load_markers(self, mapname):
        entities = minqlx.map_entities(mapname)  # reads the BSP: worker thread only
        minqlx.next_frame(self._apply_markers)(mapname, entities)

    def _apply_markers(self, mapname, entities):
        if self._unloaded or mapname != self.get_cvar("mapname"):
            return
        named, spawns = [], []
        for e in entities:
            if e.origin is None:
                continue
            origin = tuple(float(c) for c in e.origin)
            if e.keys.get("classname") == "info_player_deathmatch":
                spawns.append(origin)
            name = e.keys.get("targetname", "")
            if name.startswith("rl_"):
                named.append((name, origin))
        layout = rl_rules.parse_markers(named)
        if layout is None:
            self._world = None
            self.logger.info("roguelike: no complete rl_* rooms on %s, off", mapname)
            return
        if layout.skipped:
            self.logger.warning("roguelike: rooms without the markers they need: %s", ", ".join(layout.skipped))
        self._world = rl_rules.World(layout, rng=self._rng)
        self._hub_spawns = spawns or [_lift(layout.hub_start, 0.0)]
        self._preload()

    @staticmethod
    def _preload():
        npc_core.preload_weapons()
        for kind in rl_rules.MOBS.values():
            for path in kind.parts:
                npc_core.model_index(path)
        for path in rl_rules.TURRET.parts + PAD_MODEL:
            npc_core.model_index(path)

    # lifecycle

    def handle_map(self, mapname, factory):
        self._forget()
        self._world = None
        self._load_markers(mapname)

    def handle_new_game(self):
        self._forget()

    def _forget(self):
        """The engine freed every entity: nothing to remove, and their numbers mean others now."""
        npc_core.reset_cache()
        if self._world is not None:
            self._world.drop_all()
        self._rooms = {}
        self._scene = []
        self._last_full = {}

    def handle_unload(self, plugin):
        if plugin != self.__class__.__name__ or self._unloaded:
            return
        self._unloaded = True
        if self._world is not None:
            for cid in self._world.occupied().values():
                self._send_to_hub(self.player(cid))  # the next instance knows no runs
        for room_id in list(self._rooms):
            self._clear_room(room_id)
        self._rooms = {}
        for npc in self._scene:
            npc_core.remove(npc)
        self._scene = []
        self._world = None

    # players

    def handle_player_loaded(self, player):
        if self._world is not None and player.team == "spectator":
            player.put("red")

    def handle_team_switch_attempt(self, player, old_team, new_team, target):
        if self._world is None:
            return None
        if new_team == "any":  # SetTeam would pick the smaller team, blue
            player.put("red")
            return minqlx.Return.STOP_ALL
        if new_team == "blue":
            return minqlx.Return.STOP_ALL
        return None

    def handle_team_switch(self, player, old_team, new_team):
        if self._world is None or new_team in ("red", "blue"):
            return
        self._apply(player.id, self._world.leave(player.id), time.monotonic())

    def handle_player_disconnect(self, player, reason):
        if self._world is None:
            return
        self._last_full.pop(player.id, None)
        self._apply(player.id, self._world.leave(player.id), time.monotonic())

    def handle_death(self, victim, killer, data):
        if self._world is None or victim is None:
            return
        if str(data) == "SWITCH_TEAMS":
            return  # QL kills a player who changes team; team_switch ends the run as "left"
        self._apply(victim.id, self._world.died(victim.id, time.monotonic()), time.monotonic(), dead=True)

    def handle_player_spawn(self, player):
        if self._world is None:
            return
        try:
            where = self._world.where(player.id)
            if where is None:
                self._set_kit(player, "g")
                return
            self._teleport(player, where)  # Task 3: straight from the hook, no frame delay
            self._set_kit(player, rl_rules.KITS[self._room_type(player.id)])
        except Exception as ex:
            self.logger.warning("roguelike: spawn of %s: %s", player.id, ex)

    # engine calls on players

    @staticmethod
    def _teleport(player, xyz):
        x, y, z = (float(c) for c in xyz)
        setter = getattr(minqlx, "set_position", None)
        if callable(setter):
            try:
                if setter(int(player.id), minqlx.Vector3((x, y, z))):
                    player.velocity = minqlx.Vector3((0, 0, 0))
                    return
            except (AttributeError, TypeError, ValueError, _ENGINE_ERR):
                pass
        player.velocity = minqlx.Vector3((0, 0, 0))
        player.position = player.position._replace(x=x, y=y, z=z)

    @staticmethod
    def _set_kit(player, letters):
        weapons, held = _kit(letters)
        player.weapons = minqlx.Weapons(weapons)
        player.weapon = held

    def _room_type(self, cid):
        run = self._world.run(cid)
        return self._world.layout.rooms[run.room].type

    def _hub_spawn(self):
        return self._rng.choice(self._hub_spawns)

    # events

    def _apply(self, cid, events, now, dead=False):
        """Turns World events into engine calls. dead: the player is dead, the spawn hook places them."""
        world = self._world
        player = self.player(cid)
        for event in events:
            kind = event[0]
            if kind in ("enter", "restart"):
                room_id = event[1]
                self._clear_room(room_id)
                self._rooms[room_id] = Room(cid)
                self._build_room(room_id, now)
                if player is not None and not dead:
                    self._teleport(player, world.layout.rooms[room_id].start)
                    self._set_kit(player, rl_rules.KITS[world.layout.rooms[room_id].type])
                    player.health = 100
            elif kind == "spawn_mob":
                self._spawn_mob(cid, event[1], event[2], now)
            elif kind in ("cleared", "offers"):
                self._show_offers(cid, now)
                if kind == "cleared" and player is not None:
                    player.center_print("Room cleared. Pick a teleporter")
            elif kind == "hint" and player is not None:
                run = world.run(cid)
                player.center_print(LABELS.get(run.offers.get(event[1]), ""))
            elif kind == "fall" and player is not None:
                run = world.run(cid)
                self._teleport(player, world.layout.rooms[run.room].start)
            elif kind == "lives" and player is not None:
                player.center_print("Lives left: {}".format(event[1]))
            elif kind == "hub":
                reason, seconds = event[1], event[2]
                if player is not None:
                    if not dead and player.is_alive and _plays(player):
                        self._teleport(player, self._hub_spawn())
                        self._set_kit(player, "g")
                    self.msg("{}: run over, {}, {}".format(player.name, REASONS.get(reason, reason), _clock(seconds)))
            elif kind == "full" and player is not None:
                if now - self._last_full.get(cid, -FULL_TELL_S) >= FULL_TELL_S:
                    self._last_full[cid] = now
                    player.tell("Every free room is taken, wait a moment")
        self._sync_rooms()

    def _sync_rooms(self):
        """A room the World no longer gives to its player loses its entities."""
        occupied = self._world.occupied() if self._world is not None else {}
        for room_id in list(self._rooms):
            if occupied.get(room_id) != self._rooms[room_id].cid:
                self._clear_room(room_id)

    def _clear_room(self, room_id):
        room = self._rooms.pop(room_id, None)
        if room is None:
            return
        for npc in room.mobs + room.turrets + room.pads:
            try:
                npc_core.remove(npc)
            except Exception as ex:
                self.logger.warning("roguelike: %s entity not removed: %s", room_id, ex)
        for num in room.missiles:
            npc_core.remove_missile(num)

    def _clear_fight(self, room):
        for npc in room.mobs + room.turrets:
            npc_core.remove(npc)
        room.mobs, room.turrets = [], []
        for num in room.missiles:
            npc_core.remove_missile(num)
        room.missiles = set()

    def _build_room(self, room_id, now):
        spec = self._world.layout.rooms[room_id]
        room = self._rooms[room_id]
        if spec.type == "dodge":
            for marker in spec.turrets:
                room.turrets.append(npc_core.spawn_pair(_lift(marker, TURRET_LIFT), rl_rules.TURRET.parts, 0, now,
                                                        solid=False))

    def _spawn_mob(self, cid, name, point, now):
        run = self._world.run(cid)
        room = self._rooms.get(run.room) if run else None
        if room is None:
            return
        kind = rl_rules.MOBS[name]
        marker = self._world.layout.rooms[run.room].mobs[point]
        npc = npc_core.spawn_pair(_lift(marker, MOB_LIFT), kind.parts, kind.hp, now,
                                  hull_size=kind.hull, frames=kind.frames, fps=kind.fps)
        npc.mob = name
        npc.shown = 0
        npc.last_shot = now
        room.mobs.append(npc)

    def _show_offers(self, cid, now):
        run = self._world.run(cid)
        room = self._rooms.get(run.room) if run else None
        if room is None:
            return
        self._clear_fight(room)
        for npc in room.pads:
            npc_core.remove(npc)
        doors = self._world.layout.rooms[run.room].doors
        room.pads = [npc_core.spawn_pair(_lift(doors[d], PAD_LIFT), PAD_MODEL, 0, now, solid=False)
                     for d in sorted(run.offers)]

    # frame

    def handle_frame(self):
        if self._world is None:
            return
        now = time.monotonic()
        if now - self._last_tick < TICK_S:
            return
        self._last_tick = now
        try:
            self._tick(now)
        except Exception as ex:
            self._log_error("tick failed: %s", ex, now)

    def _log_error(self, text, ex, now):
        if now - self._last_error >= ERROR_LOG_S:
            self._last_error = now
            self.logger.warning("roguelike: " + text, ex)

    def _tick(self, now):
        world = self._world
        if world is None:
            return
        if not self._scene:
            try:
                self._scene.append(npc_core.spawn_pair(_lift(world.layout.hub_start, PAD_LIFT), PAD_MODEL, 0, now,
                                                       solid=False))
            except Exception as ex:
                self._log_error("hub pad model: %s", ex, now)  # decoration: the runs go on without it
        # plain tuples: a Player object goes stale when its client leaves
        live = {}
        for p in self.players():
            if _plays(p) and p.is_alive:
                live[p.id] = (tuple(p.position), tuple(p.velocity))
        hub = world.layout.hub_start
        for cid, (pos, _vel) in live.items():
            run = world.run(cid)
            try:
                if run is None:
                    if math.hypot(pos[0] - hub[0], pos[1] - hub[1]) <= rl_rules.PAD_RANGE:
                        self._apply(cid, world.begin(cid, now), now)
                    continue
                room = self._rooms.get(run.room)
                self._apply(cid, world.tick(cid, pos, now, len(room.mobs) if room else 0), now)
            except Exception as ex:
                run = world.run(cid)
                if run is not None and run.room in self._rooms:
                    self._fail_room(run.room, self._rooms[run.room], ex, now)
                else:
                    world.leave(cid)
                    self._sync_rooms()
                    self._log_error("player tick failed: %s", ex, now)
        plums = now - self._last_plum >= PLUM_S
        if plums:
            self._last_plum = now
        for room_id in list(self._rooms):
            room = self._rooms.get(room_id)
            if room is None or room.cid not in live:
                continue
            try:
                self._tick_room(room_id, room, live[room.cid], now, plums)
            except Exception as ex:
                self._fail_room(room_id, room, ex, now)

    def _tick_room(self, room_id, room, target, now, plums):
        pos, vel = target
        body = (pos[0], pos[1], pos[2] + AIM_ABOVE)
        alive = []
        for npc in room.mobs:
            kind = rl_rules.MOBS[npc.mob]
            npc_core.chase(npc, (pos[0], pos[1], pos[2] + MOB_LIFT), kind.speed, now, turn=CHASE_TURN)
            result = npc_core.tick_chaser(npc, now)
            if result == "alive":
                alive.append(npc)
                continue
            if result == "stuck":
                self.logger.info("roguelike: %s %s stuck at %s, counted as killed", room_id, npc.mob, npc.pos)
            npc_core.remove(npc)
        room.mobs = alive
        room.missiles = {n for n in room.missiles if not npc_core.missile_gone(n)}
        for npc in room.mobs:
            self._mob_attack(room, npc, body, now)
        for npc in room.turrets:
            self._turret_fire(room, npc, body, vel, now)
        npc_core.tick_missiles(room.mobs, now, only=room.missiles)
        if plums:
            for npc in room.mobs:
                taken = npc_core.damage_taken(npc)
                if taken > npc.shown:
                    npc_core.damage_plum((npc.pos[0], npc.pos[1], npc.pos[2] + AIM_ABOVE * 2), taken - npc.shown,
                                         room.cid, now)
                    npc.shown = taken

    def _mob_attack(self, room, npc, body, now):
        kind = rl_rules.MOBS[npc.mob]
        attack = rl_rules.ATTACKS[kind.attack]
        if now - npc.last_shot < attack.interval or len(room.missiles) >= rl_rules.MAX_MISSILES:
            return
        dx, dy, dz = body[0] - npc.pos[0], body[1] - npc.pos[1], body[2] - npc.pos[2]
        dist = math.sqrt(dx * dx + dy * dy + dz * dz) or 1.0
        if dist > attack.range:
            return
        npc.last_shot = now
        if kind.attack == "bite":
            # contact damage: a missile from next to the chest, on the mob's side (Task 3)
            muzzle = tuple(body[i] - (dx, dy, dz)[i] / dist * BITE_FROM for i in range(3))
            weapon = BITE_WEAPON
        else:
            muzzle = (npc.pos[0], npc.pos[1], npc.pos[2] + attack.muzzle)
            weapon = kind.attack
        room.missiles.add(npc_core.fire(muzzle, body, weapon, attack.damage, attack.splash, attack.radius,
                                        npc.hull, npc_core.CLIP_HITS_PLAYERS, visual=npc.visuals[-1]))

    def _turret_fire(self, room, npc, body, vel, now):
        turret = rl_rules.TURRET
        attack = turret.attack
        if now - npc.last_shot < attack.interval or len(room.missiles) >= rl_rules.MAX_MISSILES:
            return
        muzzle = (npc.pos[0], npc.pos[1], npc.pos[2] + attack.muzzle)
        if math.dist(muzzle, body) > attack.range:
            return
        npc.last_shot = now
        aim = npc_core.lead(muzzle, body, vel, npc_core.speed_of(turret.weapon))
        npc_core.aim_visual(npc, 1, aim)
        room.missiles.add(npc_core.fire(muzzle, aim, turret.weapon, attack.damage, attack.splash, attack.radius,
                                        npc.visuals[0], npc_core.CLIP_HITS_PLAYERS, visual=npc.visuals[1]))

    def _fail_room(self, room_id, room, ex, now):
        """One room's error: that room is reset and its player goes to the hub; other runs go on."""
        self._log_error("room " + room_id + " failed: %s", ex, now)
        cid = room.cid
        self._clear_room(room_id)
        self._world.leave(cid)
        self._sync_rooms()
        player = self.player(cid)
        if self._send_to_hub(player):
            player.tell("The room hit an error and was reset. Back in the hub")

    def _send_to_hub(self, player):
        """A live player out of a room they no longer own: to a hub spawn, gauntlet only."""
        if player is None or not player.is_alive or not _plays(player):
            return False
        try:
            self._teleport(player, self._hub_spawn())
            self._set_kit(player, "g")
            return True
        except Exception as ex:
            self.logger.warning("roguelike: %s not sent to the hub: %s", player.id, ex)
            return False

    # commands

    def cmd_rl(self, player, msg, channel):
        if self._world is None:
            channel.reply("Roguelike is off on this map")
            return
        run = self._world.run(player.id)
        if run is None:
            channel.reply("No run. Step on the pad in the hub to start one")
            return
        channel.reply("Room {} ({}), lives {}, run time {}".format(
            run.room, run.phase, run.lives, _clock(time.monotonic() - run.started)))

    def cmd_rlroom(self, player, msg, channel):
        if self._world is None:
            channel.reply("Roguelike is off on this map")
            return None
        if len(msg) < 2:
            return minqlx.Return.USAGE
        if not _plays(player):
            channel.reply("Join the game first")
            return None
        events = self._world.force(player.id, msg[1], time.monotonic())
        if not events:
            channel.reply("No such room, or someone is in it")
            return None
        self._apply(player.id, events, time.monotonic())
        return None
