# tower_defence.py - cooperative tower defence: 15 waves of entity creeps on one road, turrets
# on pads bought with team money, 20 base lives. Map markers turn it on: td_path_N, td_pad_N,
# td_creepspawn, td_base. Without them every hook returns at once.
#
#   !build rl|pg, !upgrade, !sell   standing on a pad
#   !td                             wave, lives, money
#   !tdwave <n>                     jump to wave n, permission 5
#
# The match has to run with blue empty: g_teamSizeMin 0, and the plugin calls allready itself.
# A match start wipes every entity, so new_game drops the state and the game starts once the
# match is in progress. An empty team ends the match, so the map pool must hold only this map.
import math
import re
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
    import td_rules
except ImportError:
    from . import td_rules

TICK_S = 0.05
SLOW_S = 0.25
READY_RETRY_S = 15.0
ERROR_LOG_S = 10.0
PAD_RANGE = 96.0
MARKER_TO_HULL = 2.0  # markers stand 24 u above the floor, a hull origin 26 u
TURRET_MUZZLE = 34.0  # above the hull-level origin: inside the turret head
AIM_ABOVE = 22.0  # at a creep's body, floor + 48
MAX_MISSILES = td_rules.MAX_MISSILES
PAD_MODEL = ("models/mapobjects/flagbase/ntrl_base.md3",)
BASE_MODEL = ("models/powerups/obelisk/obelisk.md3",)

_PATH_RE = re.compile(r"^td_path_(\d+)$")
_PAD_RE = re.compile(r"^td_pad_(\d+)$")


def parse_markers(entities):
    """MapEntity list -> dict(path, pads, spawn, base), the base closing the path. None if incomplete."""
    path, pads, found = {}, {}, {}
    for e in entities:
        name = e.keys.get("targetname", "")
        if e.origin is None or not name.startswith("td_"):
            continue
        origin = tuple(float(c) for c in e.origin)
        m = _PATH_RE.match(name)
        p = _PAD_RE.match(name)
        if m:
            path[int(m.group(1))] = origin
        elif p:
            pads[int(p.group(1))] = origin
        elif name in ("td_creepspawn", "td_base"):
            found[name] = origin
    if not path or not pads or len(found) < 2:
        return None
    return dict(path=[path[k] for k in sorted(path)] + [found["td_base"]],
                pads=[pads[k] for k in sorted(pads)],
                spawn=found["td_creepspawn"], base=found["td_base"])


def _hull_level(marker):
    return (marker[0], marker[1], marker[2] + MARKER_TO_HULL)


class tower_defence(minqlx.Plugin):
    def __init__(self):
        self._init_state()
        self.add_hook("map", self.handle_map)
        self.add_hook("new_game", self.handle_new_game)
        self.add_hook("frame", self.handle_frame)
        self.add_hook("player_loaded", self.handle_player_loaded)
        self.add_hook("player_disconnect", self.handle_player_disconnect)
        self.add_hook("team_switch_attempt", self.handle_team_switch_attempt)
        self.add_hook("unload", self.handle_unload)
        self.add_command("build", self.cmd_build, usage="rl|pg")
        self.add_command("upgrade", self.cmd_upgrade)
        self.add_command("sell", self.cmd_sell)
        self.add_command("td", self.cmd_td)
        self.add_command("tdwave", self.cmd_tdwave, 5, usage="<1-{}>".format(len(td_rules.WAVES)))
        self._load_markers(self.get_cvar("mapname"))

    def _init_state(self):
        self._markers = None
        self._game = None
        self._creeps = []
        self._turrets = {}
        self._scene = []
        self._red_count = 0
        self._targets = []
        self._last_tick = 0.0
        self._last_slow = 0.0
        self._last_ready = -READY_RETRY_S
        self._last_error = -ERROR_LOG_S
        self._seen = ("idle", 0)

    # markers

    @minqlx.thread
    def _load_markers(self, mapname):
        entities = minqlx.map_entities(mapname)  # reads the BSP: worker thread only
        minqlx.next_frame(self._apply_markers)(mapname, entities)

    def _apply_markers(self, mapname, entities):
        self._markers = parse_markers(entities)
        if self._markers is None:
            self.logger.info("tower_defence: no td_* markers on %s, off", mapname)
            return
        self._game = td_rules.Game(len(self._markers["pads"]))
        self._preload()

    @staticmethod
    def _preload():
        """Into the gamestate early, so nobody loads a model in the middle of a wave."""
        npc_core.preload_weapons()
        for kind in list(td_rules.CREEPS.values()) + list(td_rules.TURRETS.values()):
            for path in kind.parts:
                npc_core.model_index(path)
        for path in PAD_MODEL + BASE_MODEL:
            npc_core.model_index(path)

    # lifecycle

    def handle_map(self, mapname, factory):
        self._forget()
        self._markers = None
        self._game = None
        self._load_markers(mapname)

    def handle_new_game(self):
        self._forget()
        if self._markers is not None:
            self._game = td_rules.Game(len(self._markers["pads"]))

    def _forget(self):
        """The engine freed every entity: nothing to remove, and their numbers mean others now."""
        npc_core.reset_cache()
        self._creeps = []
        self._turrets = {}
        self._scene = []
        self._seen = ("idle", 0)

    def handle_unload(self, plugin):
        if plugin != self.__class__.__name__ or self._game is None:
            return
        self._clear_fight()
        self._remove_turrets()
        for npc in self._scene:
            npc_core.remove(npc)
        self._scene = []
        self._game = None
        self._markers = None

    def _clear_fight(self):
        for npc in self._creeps:
            npc_core.remove(npc)
        self._creeps = []
        npc_core.clear_missiles()

    def _remove_turrets(self):
        for npc in self._turrets.values():
            npc_core.remove(npc)
        self._turrets = {}

    def _stop(self):
        self._clear_fight()
        self._remove_turrets()
        self._game.reset()
        self._seen = ("idle", 0)

    def _game_state(self):
        try:
            return minqlx.Game().state
        except minqlx.NonexistentGameError:
            return None

    def _begin(self, now):
        self._preload()
        if not self._scene:
            for marker in self._markers["pads"]:
                self._scene.append(npc_core.spawn_pair(_hull_level(marker), PAD_MODEL, 0, now, solid=False))
            self._scene.append(npc_core.spawn_pair(_hull_level(self._markers["base"]), BASE_MODEL, 0, now, solid=False))
        self._game.start(now)
        self.center_print("Tower defence: wave 1 in {} s. Build on a pad: !build rl or !build pg".format(td_rules.PAUSE_S))

    # players

    def handle_player_loaded(self, player):
        if self._game is not None and player.team == "spectator":
            player.put("red")

    def handle_player_disconnect(self, player, reason):
        if self._game is None or self._game.phase == "idle":
            return
        if not any(p.team == "red" and p.id != player.id for p in self.players()):
            self._stop()

    def handle_team_switch_attempt(self, player, old_team, new_team, target):
        if self._game is None:
            return None
        if new_team == "any":  # SetTeam would pick the smaller team, blue
            player.put("red")
            return minqlx.Return.STOP_ALL
        if new_team == "blue":
            return minqlx.Return.STOP_ALL
        return None

    # frame

    def handle_frame(self):
        if self._game is None:
            return
        now = time.monotonic()
        if now - self._last_tick < TICK_S:
            return
        self._last_tick = now
        try:
            self._tick(now)
        except Exception as ex:
            if now - self._last_error >= ERROR_LOG_S:
                self._last_error = now
                self.logger.warning("tower_defence: tick failed: %s", ex)

    def _tick(self, now):
        if now - self._last_slow >= SLOW_S:
            self._last_slow = now
            self._slow(now)
        game = self._game
        if game.phase == "idle":
            return
        self._tick_creeps(now)
        for name in game.tick(now, len(self._creeps)):
            self._spawn_creep(name, now)
        self._announce()
        if game.phase in ("pause", "wave"):
            self._fire_turrets(now)
            self._fire_creeps(now)
        npc_core.tick_missiles(self._creeps, now)

    def _slow_players(self):
        reds = [p for p in self.players() if p.team == "red"]
        self._red_count = len(reds)
        # plain tuples: a Player object goes stale when its client leaves
        self._targets = [tuple(p.position) for p in reds if p.is_alive]

    def _slow(self, now):
        self._slow_players()
        if self._game.phase != "idle":
            if not self._red_count:
                self._stop()
            return
        if not self._red_count:
            return
        state = self._game_state()
        if state == "in_progress":
            self._begin(now)
        elif state == "warmup" and now - self._last_ready >= READY_RETRY_S:
            self._last_ready = now
            minqlx.console_command("allready")

    def _announce(self):
        game = self._game
        seen = (game.phase, game.wave)
        if seen == self._seen:
            return
        was_phase = self._seen[0]
        self._seen = seen
        if game.phase == "wave":
            self.center_print("Wave {} of {}".format(game.wave, len(td_rules.WAVES)))
        elif game.phase == "pause" and was_phase == "wave":
            self.msg("Wave {} cleared. Money {}, lives {}".format(game.wave, game.money, game.lives))
        elif game.phase == "over":
            self._clear_fight()
            text = "You won!" if game.result == "win" else "The base is lost, wave {}".format(game.wave)
            self.center_print(text)
            self.msg("{} New game in {} s".format(text, td_rules.OVER_S))
        elif game.phase == "idle":
            self._remove_turrets()

    def _spawn_creep(self, name, now):
        kind = td_rules.CREEPS[name]
        hp = td_rules.creep_hp(name, self._game.wave, max(1, self._red_count))
        npc = npc_core.spawn_pair(_hull_level(self._markers["spawn"]), kind.parts, hp, now,
                                  hull_size=kind.hull, frames=kind.frames, fps=kind.fps)
        npc.creep = name
        npc_core.start_path(npc, [_hull_level(p) for p in self._markers["path"]], kind.speed, now)
        self._creeps.append(npc)

    def _tick_creeps(self, now):
        game = self._game
        alive = []
        for npc in self._creeps:
            try:
                result = npc_core.tick(npc, now)
            except Exception as ex:
                self.logger.warning("tower_defence: creep %s dropped: %s", npc.creep, ex)
                result = "failed"
            if result == "alive":
                alive.append(npc)
                continue
            try:
                npc_core.remove(npc)
            except Exception as ex:
                self.logger.warning("tower_defence: creep %s not removed: %s", npc.creep, ex)
            if result == "dead":
                game.killed(npc.creep)
            elif result == "arrived":
                game.leaked(npc.creep)
            else:
                if result == "stuck":
                    self.logger.warning("tower_defence: creep %s stuck at %s", npc.creep, npc.pos)
                game.vanished()
        self._creeps = alive

    def _fire_turrets(self, now):
        if not self._creeps or not self._turrets:
            return
        candidates = [(c.pos, c) for c in self._creeps]
        for pad, npc in self._turrets.items():
            built = self._game.pads[pad]
            kind = td_rules.TURRETS[built.kind]
            if now - npc.last_shot < kind.interval:
                continue
            if npc_core.missiles_in_flight() >= MAX_MISSILES:
                return
            creep = npc_core.nearest(npc.pos, candidates, kind.range)
            if creep is None:
                continue
            npc.last_shot = now
            muzzle = (npc.pos[0], npc.pos[1], npc.pos[2] + TURRET_MUZZLE)
            body = (creep.pos[0], creep.pos[1], creep.pos[2] + AIM_ABOVE)
            aim = npc_core.lead(muzzle, body, creep.vel, npc_core.speed_of(built.kind))
            npc_core.aim_visual(npc, 1, aim)
            radius = td_rules.ROCKET_RADIUS if built.kind == "rl" else 0
            npc_core.fire_at_creeps(muzzle, aim, built.kind, kind.damage[built.level], radius,
                                    npc.visuals[0], visual=npc.visuals[1])

    def _fire_creeps(self, now):
        if not self._targets:
            return
        candidates = [(t, t) for t in self._targets]
        for npc in self._creeps:
            weapon = td_rules.CREEPS[npc.creep].attack
            if weapon is None:
                continue
            attack = td_rules.CREEP_ATTACKS[weapon]
            if now - npc.last_shot < attack.interval:
                continue
            if npc_core.missiles_in_flight() >= MAX_MISSILES:
                return
            target = npc_core.nearest(npc.pos, candidates, attack.range)
            if target is None:
                continue
            npc.last_shot = now
            muzzle = (npc.pos[0], npc.pos[1], npc.pos[2] + attack.muzzle)
            npc_core.fire(muzzle, target, weapon, attack.damage, attack.splash, attack.radius,
                          npc.hull, npc_core.CLIP_HITS_PLAYERS, visual=npc.visuals[-1])

    # commands

    def _pad_of(self, player):
        """The pad the player stands on, or None after telling them why not."""
        if self._game is None:
            player.tell("Tower defence is off on this map")
            return None
        if self._game.phase not in ("pause", "wave"):
            player.tell("No game is running")
            return None
        if player.team != "red" or not player.is_alive:
            player.tell("Only a live player can do that")
            return None
        where = player.position
        for pad, marker in enumerate(self._markers["pads"]):
            if math.hypot(marker[0] - where[0], marker[1] - where[1]) <= PAD_RANGE:
                return pad
        player.tell("Stand on a pad first")
        return None

    def cmd_build(self, player, msg, channel):
        pad = self._pad_of(player)
        if pad is None:
            return None
        kind = msg[1].lower() if len(msg) > 1 else ""
        reply = self._game.build(pad, kind)
        built = self._game.pads.get(pad)
        if pad not in self._turrets and built is not None:
            self._turrets[pad] = npc_core.spawn_pair(_hull_level(self._markers["pads"][pad]),
                                                     td_rules.TURRETS[built.kind].parts, 0,
                                                     time.monotonic(), solid=False)
            self.msg(reply)
        else:
            player.tell(reply)
        return None

    def cmd_upgrade(self, player, msg, channel):
        pad = self._pad_of(player)
        if pad is None:
            return None
        before = self._game.pads.get(pad)
        reply = self._game.upgrade(pad)
        if self._game.pads.get(pad) != before:
            self.msg(reply)
        else:
            player.tell(reply)
        return None

    def cmd_sell(self, player, msg, channel):
        pad = self._pad_of(player)
        if pad is None:
            return None
        reply = self._game.sell(pad)
        turret = self._turrets.pop(pad, None)
        if turret is not None:
            npc_core.remove(turret)
            self.msg(reply)
        else:
            player.tell(reply)
        return None

    def cmd_td(self, player, msg, channel):
        if self._game is None:
            channel.reply("Tower defence is off on this map")
            return
        game = self._game
        channel.reply("Wave {}/{}, lives {}, money {}".format(game.wave, len(td_rules.WAVES), game.lives, game.money))

    def cmd_tdwave(self, player, msg, channel):
        if self._game is None:
            channel.reply("Tower defence is off on this map")
            return None
        try:
            wave = int(msg[1])
        except (IndexError, ValueError):
            return minqlx.Return.USAGE
        if not 1 <= wave <= len(td_rules.WAVES):
            return minqlx.Return.USAGE
        self._clear_fight()
        self._game.jump(wave, time.monotonic())
        return None
