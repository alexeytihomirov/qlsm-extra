# moba_npc_probe.py - THROWAWAY spike 2 probe (root-0034). Never merged to main.
# Question: can a plain server entity (not a bot) be a tower/creep: visible, shootable with
# accumulated HP, moving smoothly? Pure plugin, no engine change.
#
# Owner console only (rcon: qlx !npc ...):
#   spawn <x> <y> <z>        info_notnull made solid, shootable, drawn as an item model
#   walk <n> <vx> <vy>       TR_LINEAR from where it is now, speed in u/s
#   stop <n>                 TR_STATIONARY where it is now
#   status                   health lost, position
#   clear                    remove every probe entity
#
# Health starts at BASE_HP; the probe counts it "dead" after LIFE_HP damage and removes it
# itself, so the engine's die callback (NULL on an info_notnull) is never reached.

import time

try:
    import minqlxtended as minqlx
except ImportError:
    import minqlx

BASE_HP = 100000
LIFE_HP = 1000
CONTENTS_BODY = 0x2000000
TICK_S = 0.05


class moba_npc_probe(minqlx.Plugin):
    def __init__(self):
        self._npcs = {}  # entity number -> dict(last_hp, walking)
        self._last_tick = 0.0
        self.add_hook("frame", self.handle_frame)
        self.add_hook("map", self.handle_map)
        self.add_command("npc", self.cmd_npc, 5, usage="<spawn|walk|stop|status|clear> ...")

    def handle_map(self, mapname, factory):
        self._npcs.clear()

    @staticmethod
    def _item_model():
        for e in minqlx.entities(etype=minqlx.EntityType.ITEM):
            if e.s.modelindex:
                return e.s.modelindex, e.classname
        return 1, None

    @staticmethod
    def _now_pos(e):
        s = e.s
        if s.e_type == minqlx.EntityType.ITEM:
            return tuple(e.r.current_origin)  # G_RunItem moves it, with a trace
        if s.pos_type == minqlx.TrajectoryType.LINEAR:
            dt = (minqlx.level.time - s.pos_time) / 1000.0
            return tuple(s.pos_base[i] + s.pos_delta[i] * dt for i in range(3))
        return tuple(s.pos_base)

    def _spawn(self, origin, model=None):
        # ET_ITEM gets G_RunItem's physics, which drops a TR_LINEAR item to TR_STATIONARY:
        # ET_GENERAL with a CS_MODELS index instead, drawn by cgame as a plain model.
        e = minqlx.spawn_entity("info_notnull", {"origin": origin})
        if e is None:
            return None, "spawn_entity returned None"
        if model is None:
            model, cls = self._item_model()
            e.s.e_type = minqlx.EntityType.ITEM
        else:
            cls = minqlx.configstring(minqlx.CS_MODELS + model, cached=False)
            e.s.e_type = minqlx.EntityType.GENERAL
        e.s.modelindex = model
        e.s.pos_type = minqlx.TrajectoryType.STATIONARY
        e.s.pos_base = origin
        e.s.origin = origin
        e.r.current_origin = origin
        e.r.mins = (-16.0, -16.0, -24.0)
        e.r.maxs = (16.0, 16.0, 32.0)
        e.r.contents = CONTENTS_BODY
        e.clipmask = 1  # CONTENTS_SOLID: G_RunItem's trace stops on walls, not on players
        e.r.owner_num = 1023  # ENTITYNUM_NONE
        e.takedamage = True
        e.health = BASE_HP
        minqlx.link_entity(e.s.number)
        self._npcs[e.s.number] = dict(last_hp=BASE_HP, hits=0)
        return e.s.number, "model {} ({})".format(model, cls)

    def _fire(self, num, cid, weapon):
        """A real missile entity from NPC num at player cid; the engine runs, hits, explodes it."""
        src = self._now_pos(minqlx.Entity(num))
        start = (src[0], src[1], src[2] + 16)
        target = tuple(self.player(cid).position)
        aim = (target[0] - start[0], target[1] - start[1], target[2] - start[2])
        dist = max(sum(c * c for c in aim) ** 0.5, 1.0)
        if weapon == "pg":
            wp, speed, dmg, splash, radius = minqlx.Weapon.PLASMAGUN, 2000, 20, 15, 20
            mod, smod = minqlx.Mod.PLASMA, minqlx.Mod.PLASMA_SPLASH
        else:
            wp, speed, dmg, splash, radius = minqlx.Weapon.ROCKET_LAUNCHER, 900, 100, 100, 120
            mod, smod = minqlx.Mod.ROCKET, minqlx.Mod.ROCKET_SPLASH
        m = minqlx.spawn_entity("info_notnull", {"origin": start})
        if m is None:
            return "spawn_entity returned None"
        m.s.e_type = minqlx.EntityType.MISSILE
        m.s.weapon = wp
        m.s.pos_type = minqlx.TrajectoryType.LINEAR
        m.s.pos_time = minqlx.level.time - 50  # MISSILE_PRESTEP_TIME
        m.s.pos_base = start
        m.s.pos_delta = tuple(c / dist * speed for c in aim)
        m.r.current_origin = start
        m.r.owner_num = num
        m.r.sv_flags = 0x80  # SVF_USE_CURRENT_ORIGIN
        m.parent = minqlx.Entity(num)
        m.clipmask = 0x1 | 0x2000000 | 0x4000000  # MASK_SHOT
        m.damage = dmg
        m.splash_damage = splash
        m.splash_radius = radius
        m.method_of_death = mod
        m.splash_method_of_death = smod
        m.nextthink = 0  # no think: a NULL think with a nextthink is G_Error
        minqlx.link_entity(m.s.number)
        return "missile {} weapon {} from {} to {}".format(
            m.s.number, int(wp), tuple(int(c) for c in start), tuple(int(c) for c in target))

    def handle_frame(self):
        now = time.monotonic()
        if not self._npcs or now - self._last_tick < TICK_S:
            return
        self._last_tick = now
        for num, st in list(self._npcs.items()):
            try:
                e = minqlx.Entity(num)
                if not e.inuse:
                    self._npcs.pop(num)
                    continue
                patrol = st.get("patrol")
                moving = e.s.pos_type == minqlx.TrajectoryType.LINEAR and e.s.pos_delta[0] != 0.0
                if patrol or moving:
                    # collision and hit traces read r.current_origin, clients read s.pos
                    pos = self._now_pos(e)
                    if patrol and (not moving or not patrol[0] <= pos[0] <= patrol[1]):
                        # out of bounds, or G_RunItem stopped it on a wall/floor: head inward
                        if not moving:
                            st["stops"] = st.get("stops", 0) + 1
                            st["dir"] = -st.get("dir", 1)
                        x = min(max(pos[0], patrol[0]), patrol[1])
                        pos = (x, pos[1], pos[2])
                        if pos[0] >= patrol[1]:
                            st["dir"] = -1
                        elif pos[0] <= patrol[0]:
                            st["dir"] = 1
                        e.s.pos_base = pos
                        e.s.pos_time = minqlx.level.time
                        e.s.pos_delta = (st["speed"] * st.get("dir", 1), 0.0, 0.0)
                        e.s.pos_type = minqlx.TrajectoryType.LINEAR
                    if e.s.e_type != minqlx.EntityType.ITEM:
                        e.r.current_origin = pos
                        minqlx.link_entity(num)
                turret = st.get("turret")
                if turret and now - st.get("last_shot", 0.0) >= turret[1]:
                    src = self._now_pos(e)
                    near = [p for p in self.players() if p.team in ("red", "blue") and p.is_alive
                            and sum((a - b) ** 2 for a, b in zip(p.position, src)) <= 1200 ** 2]
                    if near:
                        target = min(near, key=lambda p: sum((a - b) ** 2 for a, b in zip(p.position, src)))
                        self._fire(num, target.id, turret[0])
                        st["last_shot"] = now
                hp = e.health
                if hp != st["last_hp"]:
                    st["hits"] += 1
                    self.logger.info("npc %s: health %s -> %s", num, st["last_hp"], hp)
                    st["last_hp"] = hp
                if BASE_HP - hp >= LIFE_HP:
                    minqlx.remove_entity(num)
                    self._npcs.pop(num)
                    self.msg("npc {} destroyed after {} damage".format(num, BASE_HP - hp))
            except Exception as ex:
                self.logger.warning("npc %s: tick failed: %s", num, ex)
                self._npcs.pop(num, None)

    def cmd_npc(self, player, msg, channel):
        args = msg[1:]
        if not args:
            return minqlx.Return.USAGE
        sub = args[0].lower()
        try:
            if sub == "spawn" and len(args) in (4, 5):
                model = int(args[4]) if len(args) == 5 else None
                num, info = self._spawn(tuple(float(a) for a in args[1:4]), model)
                channel.reply("npc spawn: {} {}".format(num, info))
            elif sub == "patrol" and len(args) == 5:
                num, x0, x1, speed = int(args[1]), float(args[2]), float(args[3]), float(args[4])
                e = minqlx.Entity(num)
                pos = self._now_pos(e)
                self._npcs[num]["patrol"] = (x0, x1)
                self._npcs[num]["speed"] = abs(speed)
                self._npcs[num]["dir"] = 1 if speed > 0 else -1
                e.s.pos_base = pos
                e.s.pos_time = minqlx.level.time
                e.s.pos_delta = (speed, 0.0, 0.0)
                e.s.pos_type = minqlx.TrajectoryType.LINEAR
                channel.reply("npc {}: patrol {}..{} at {}".format(num, x0, x1, speed))
            elif sub == "hit" and len(args) == 3:
                # direct damage: health only (armor ignored), death through G_Damage
                p = self.player(int(args[1]))
                dmg = int(args[2])
                if p.health > dmg:
                    p.health = p.health - dmg
                    minqlx.add_event(p.id, minqlx.EntityEvent.PAIN, p.health)
                else:
                    minqlx.slay_with_mod(p.id, minqlx.Mod.MACHINEGUN)
                channel.reply("npc: hit {} for {}, health {}".format(p.name, dmg, p.health))
            elif sub == "fire" and len(args) in (3, 4):
                num, cid = int(args[1]), int(args[2])
                weapon = args[3] if len(args) == 4 else "rl"
                channel.reply("npc fire: {}".format(self._fire(num, cid, weapon)))
            elif sub == "turret" and len(args) == 4:
                num = int(args[1])
                self._npcs[num]["turret"] = (args[2], float(args[3]))
                channel.reply("npc {}: turret {} every {} s, range 1200".format(num, args[2], args[3]))
            elif sub == "arm" and len(args) == 2:
                p = self.player(int(args[1]))
                p.weapons = minqlx.Weapons([True] * 15)
                p.ammo = minqlx.Weapons([200] * 15)
                channel.reply("npc: armed {}".format(p.name))
            elif sub == "setmodel" and len(args) == 3:
                minqlx.set_configstring(minqlx.CS_MODELS + int(args[1]), args[2])
                channel.reply("model {} := {}".format(args[1], args[2]))
            elif sub == "models":
                for i in range(1, 64):
                    name = minqlx.configstring(minqlx.CS_MODELS + i, cached=False)
                    if name:
                        channel.reply("model {}: {}".format(i, name))
            elif sub in ("walk", "stop") and len(args) >= 2:
                num = int(args[1])
                e = minqlx.Entity(num)
                pos = self._now_pos(e)
                e.s.pos_base = pos
                e.s.pos_time = minqlx.level.time
                if sub == "walk":
                    e.s.pos_delta = (float(args[2]), float(args[3]), 0.0)
                    e.s.pos_type = minqlx.TrajectoryType.LINEAR
                else:
                    e.s.pos_delta = (0.0, 0.0, 0.0)
                    e.s.pos_type = minqlx.TrajectoryType.STATIONARY
                e.r.current_origin = pos
                minqlx.link_entity(num)
                channel.reply("npc {}: {} from {}".format(num, sub, tuple(int(c) for c in pos)))
            elif sub == "status":
                for num, st in sorted(self._npcs.items()):
                    e = minqlx.Entity(num)
                    channel.reply("npc {}: stops {} lost {} hits {} pos {} cur {} type {} contents {} takedamage {}".format(
                        num, st.get("stops", 0), BASE_HP - e.health, st["hits"], tuple(int(c) for c in self._now_pos(e)),
                        tuple(int(c) for c in e.r.current_origin), e.s.e_type, e.r.contents, e.takedamage))
                channel.reply("npc: {} alive".format(len(self._npcs)))
            elif sub == "clear":
                for num in list(self._npcs):
                    minqlx.remove_entity(num)
                self._npcs.clear()
                channel.reply("npc: cleared")
            else:
                return minqlx.Return.USAGE
        except Exception as ex:
            channel.reply("npc {}: {}: {}".format(sub, type(ex).__name__, ex))
