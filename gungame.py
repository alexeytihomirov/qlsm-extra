# gungame.py - Gun Game for FFA: every frag moves the killer one weapon down a
# configurable ladder; a frag on the last step wins the match.
#
# Map weapons and powerups are hidden at map load and cannot be picked up
# (weapons dropped by dying players included); armor and health stay. Every
# player always holds the gauntlet plus the weapon of their step. Ammo is the
# instance's business: run it with g_infiniteAmmo 1.
#   frag                     counts on the killer's step; enough frags = next step
#   death by gauntlet        the victim goes one step down
#   suicide / world death    one step down
# The scoreboard shows the step (score = step number). The win sets fraglimit
# so the engine ends the match through its own exit rules.
#
# CVARs:
#   qlx_gunGameEnabled "0"                       master switch (FFA only)
#   qlx_gunGameLadder "rl:2 rg:2 lg:2 pg:2 sg:2 gl:2 mg:2 g:1"
#                                                weapon:frags per step, read at match start;
#                                                weapons g mg sg gl rl lg rg pg bfg gh ng pl cg hmg
#   qlx_gunGameGauntletDemote "1"                a gauntlet death costs the victim a step
#   qlx_gunGameSuicideDemote "1"                 suicides and world deaths cost a step
#   qlx_gunGameStepNotify "print"                own step news: print, center, print,center, off
#   qlx_gunGameLeaderNotify "print"              leader news to everyone, same values

try:
    import minqlxtended as minqlx
except ImportError:
    import minqlx

# Field order of minqlxtended.Weapons, weapon_t minus WP_NONE.
WEAPON_FIELDS = ("g", "mg", "sg", "gl", "rl", "lg", "rg", "pg", "bfg", "gh", "ng", "pl", "cg", "hmg", "hands")
LADDER_KEYS = frozenset(WEAPON_FIELDS) - {"hands"}
WEAPON_LABELS = {
    "g": "GAUNTLET", "mg": "MG", "sg": "SG", "gl": "GL", "rl": "RL", "lg": "LG", "rg": "RG",
    "pg": "PG", "bfg": "BFG", "gh": "GH", "ng": "NG", "pl": "PL", "cg": "CG", "hmg": "HMG",
}
POWERUP_CLASSNAMES = frozenset({"item_quad", "item_enviro", "item_haste", "item_invis", "item_regen", "item_flight"})
CHANNELS = ("print", "center")

DEFAULT_LADDER = "rl:2 rg:2 lg:2 pg:2 sg:2 gl:2 mg:2 g:1"
CVAR_DEFAULTS = (
    ("qlx_gunGameEnabled", "0"),
    ("qlx_gunGameLadder", DEFAULT_LADDER),
    ("qlx_gunGameGauntletDemote", "1"),
    ("qlx_gunGameSuicideDemote", "1"),
    ("qlx_gunGameStepNotify", "print"),
    ("qlx_gunGameLeaderNotify", "print"),
)


# --- pure decisions ----------------------------------------------------------

def parse_ladder(text):
    """'rl:2 lg:1' -> [("rl", 2), ("lg", 1)]; ValueError names the bad token."""
    ladder = []
    for token in (text or "").split():
        key, sep, frags = token.partition(":")
        if not sep or key not in LADDER_KEYS:
            raise ValueError("bad ladder step {!r}: want weapon:frags".format(token))
        try:
            count = int(frags)
        except ValueError:
            raise ValueError("bad frag count in {!r}".format(token)) from None
        if count < 1:
            raise ValueError("frag count below 1 in {!r}".format(token))
        ladder.append((key, count))
    if not ladder:
        raise ValueError("empty ladder")
    return ladder


def parse_channels(text):
    words = {w.strip() for w in (text or "").split(",")}
    return frozenset(w for w in words if w in CHANNELS)


def advance(state, ladder, event):
    """(step, frags_on_step) after a "frag" or "demote" -> (state, outcome)."""
    step, frags = state
    if event == "frag":
        frags += 1
        if frags < ladder[step][1]:
            return (step, frags), "none"
        if step == len(ladder) - 1:
            return (step, frags), "win"
        return (step + 1, 0), "up"
    if step == 0:
        return (0, 0), "down" if frags else "none"
    return (step - 1, 0), "down"


def loadout(ladder, step):
    return ladder[step][0]


def loadout_weapons(key):
    return tuple(f in ("g", key) for f in WEAPON_FIELDS)


def is_blocked_item(classname):
    return classname.startswith("weapon_") or classname in POWERUP_CLASSNAMES


def pick_leader(states, current):
    """Key with the highest step (the current leader keeps a tie); None below step 1."""
    if not states:
        return None
    top = max(step for step, _ in states.values())
    if top < 1:
        return None
    if current in states and states[current][0] == top:
        return current
    return next(key for key, (step, _) in states.items() if step == top)


def step_text(ladder, state):
    step, frags = state
    key, need = ladder[step]
    return "Step {}/{}: ^3{}^7 ({}/{})".format(step + 1, len(ladder), WEAPON_LABELS[key], frags, need)


def demote_text(ladder, state):
    step = state[0]
    return "Down to step {}/{}: ^3{}^7".format(step + 1, len(ladder), WEAPON_LABELS[ladder[step][0]])


def leader_text(name, step, total):
    return "^3{}^7 leads: step {}/{}".format(name, step, total)


def last_step_text(name, key):
    return "^3{}^7 is on the last step (^3{}^7)!".format(name, WEAPON_LABELS[key])


def win_text(name):
    return "^3{}^7 wins Gun Game!".format(name)


# --- plugin ------------------------------------------------------------------

EF_NODRAW = getattr(minqlx, "EF_NODRAW", 0x80)
SVF_NOCLIENT = getattr(minqlx, "SVF_NOCLIENT", 0x01)
ET_ITEM = getattr(minqlx, "ET_ITEM", 2)


class gungame(minqlx.Plugin):
    def __init__(self):
        self._states = {}        # steam_id (str) -> (step, frags_on_step), this match
        self._ladder = parse_ladder(DEFAULT_LADDER)
        self._ladder_raw = DEFAULT_LADDER
        self._leader = None      # steam_id (str) of the announced leader
        self._saved_fraglimit = None

        for name, value in CVAR_DEFAULTS:
            self.set_cvar_once(name, value)
        self._reload_ladder()

        if "item_touch" in minqlx.EVENT_DISPATCHERS:
            self.add_hook("item_touch", self.handle_item_touch, priority=minqlx.Priority.HIGH)
        else:
            self.logger.warning("gungame: no item_touch event in this runtime, map weapons stay pickable")
        self.add_hook("map", self.handle_map)
        self.add_hook("new_game", self.handle_new_game)
        self.add_hook("game_start", self.handle_game_start)
        self.add_hook("player_spawn", self.handle_player_spawn)
        self.add_hook("unload", self.handle_unload)

        self.plugin_version = "1.0"

    # --- settings ---

    def _active(self):
        return bool(self.get_cvar("qlx_gunGameEnabled", bool)) and self.get_cvar("g_gametype") == "0"

    def _in_progress(self):
        try:
            return self.game is not None and self.game.state == "in_progress"
        except Exception:
            return False

    def _reload_ladder(self):
        raw = self.get_cvar("qlx_gunGameLadder") or ""
        if raw == self._ladder_raw:
            return
        try:
            self._ladder = parse_ladder(raw)
        except ValueError as exc:
            self.logger.warning("gungame: qlx_gunGameLadder ignored, keeping %s: %s", self._ladder_raw, exc)
        else:
            self._ladder_raw = raw
            return
        self._ladder_raw = raw  # warn once per bad value

    def _state(self, player):
        return self._states.setdefault(str(player.steam_id), (0, 0))

    def _notify(self, target, text, cvar):
        channels = parse_channels(self.get_cvar(cvar))
        try:
            if target is None:
                if "print" in channels:
                    self.msg(text)
                if "center" in channels:
                    self.center_print(text)
            else:
                if "print" in channels:
                    target.tell(text)
                if "center" in channels:
                    target.center_print(text)
        except Exception:
            pass

    @minqlx.next_frame
    def _give_loadout(self, player):
        step = self._state(player)[0] if self._in_progress() else 0
        key = loadout(self._ladder, min(step, len(self._ladder) - 1))
        try:
            player.weapons = minqlx.Weapons(loadout_weapons(key))
            player.weapon = WEAPON_FIELDS.index(key) + 1
            if self._in_progress():
                player.score = step + 1
        except Exception:
            # Gone or dead by the next frame.
            return

    # --- map items ---

    def handle_map(self, mapname, factory):
        if self._active():
            self._hide_map_items()

    @minqlx.next_frame
    def _hide_map_items(self):
        """Same writes as match_restore's stock hide: no draw, no client, no touch."""
        try:
            ents = list(minqlx.entities(inuse=True, etype=ET_ITEM))
        except Exception as exc:
            self.logger.warning("gungame: item scan failed: %s", exc)
            return
        hidden = 0
        for ent in ents:
            try:
                if not is_blocked_item(str(ent.classname or "")):
                    continue
                ent.s.e_flags = int(ent.s.e_flags) | EF_NODRAW
                ent.r.sv_flags = int(ent.r.sv_flags) | SVF_NOCLIENT
                ent.r.contents = 0
                minqlx.link_entity(int(ent.s.number))
                hidden += 1
            except Exception:
                continue
        self.logger.info("gungame: hid %d weapons and powerups", hidden)

    def handle_item_touch(self, player, entity):
        if not self._active():
            return
        try:
            classname = str(entity.classname or "")
        except Exception:
            return
        if is_blocked_item(classname):
            return minqlx.Return.STOP_EVENT

    # --- match lifecycle ---

    def handle_player_spawn(self, player):
        if self._active():
            self._give_loadout(player)

    def _reset(self):
        self._states = {}
        self._leader = None
        self._reload_ladder()

    def _restore_fraglimit(self):
        if self._saved_fraglimit is not None:
            self.set_cvar("fraglimit", self._saved_fraglimit)
            self._saved_fraglimit = None

    def handle_new_game(self):
        self._reset()
        self._restore_fraglimit()

    def handle_game_start(self, data):
        self._reset()
        if not self._active():
            return
        if self._saved_fraglimit is None:
            self._saved_fraglimit = self.get_cvar("fraglimit") or "0"
        self.set_cvar("fraglimit", "0")

    def handle_unload(self, plugin):
        if plugin == self.__class__.__name__:
            self._restore_fraglimit()
