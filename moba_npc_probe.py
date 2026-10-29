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
        e.takedamage = True
        e.health = BASE_HP
        minqlx.link_entity(e.s.number)
        self._npcs[e.s.number] = dict(last_hp=BASE_HP, hits=0)
        return e.s.number, "model {} ({})".format(model, cls)

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
                if e.s.pos_type == minqlx.TrajectoryType.LINEAR:
                    # collision and hit traces read r.current_origin, clients read s.pos
                    pos = self._now_pos(e)
                    patrol = st.get("patrol")
                    if patrol and not patrol[0] <= pos[0] <= patrol[1]:
                        x = min(max(pos[0], patrol[0]), patrol[1])
                        pos = (x, pos[1], pos[2])
                        e.s.pos_base = pos
                        e.s.pos_time = minqlx.level.time
                        dx = e.s.pos_delta[0]
                        e.s.pos_delta = (-dx, 0.0, 0.0)
                    e.r.current_origin = pos
                    minqlx.link_entity(num)
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
                e.s.pos_base = pos
                e.s.pos_time = minqlx.level.time
                e.s.pos_delta = (speed, 0.0, 0.0)
                e.s.pos_type = minqlx.TrajectoryType.LINEAR
                channel.reply("npc {}: patrol {}..{} at {}".format(num, x0, x1, speed))
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
                    channel.reply("npc {}: lost {} hits {} pos {} cur {} type {} contents {} takedamage {}".format(
                        num, BASE_HP - e.health, st["hits"], tuple(int(c) for c in self._now_pos(e)),
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
