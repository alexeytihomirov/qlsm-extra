# gungame.py - Gun Game for FFA: every frag moves the killer one weapon down a
# configurable ladder; a frag on the last step wins the match.
#
# Map weapons and powerups are taken off the map on every map load and restart
# and cannot be picked up (weapons dropped by dying players included); armor and
# health stay. Every player always holds the gauntlet plus the weapon of their
# step and spawns with armor. Ammo is the
# instance's business: run it with g_infiniteAmmo 1.
#   frag                     counts on the killer's step; enough frags = next step
#   gauntlet frag            the killer skips the rest of the step (switchable)
#   death by gauntlet        the victim goes one step down
#   suicide / world death    one frag back (into the previous step when the step has none)
# The scoreboard shows the step (score = step number). The win sets fraglimit
# so the engine ends the match through its own exit rules.
#
# CVARs:
#   qlx_gunGameEnabled "0"                       master switch (FFA only)
#   qlx_gunGameLadder "rl:2 rg:2 lg:2 pg:2 sg:2 gl:2 mg:2 g:1"
#                                                weapon:frags per step, read at match start;
#                                                weapons g mg sg gl rl lg rg pg bfg gh ng pl cg hmg
#   qlx_gunGameGauntletDemote "1"                a gauntlet death costs the victim a step
#   qlx_gunGameSuicideDemote "1"                 suicides and world deaths cost a frag
#   qlx_gunGameGauntletSkip "1"                  a gauntlet frag moves the killer a whole step up
#   qlx_gunGameWeaponDelay "0"                   ms between losing the old weapon and getting the new one
#   qlx_gunGameSpawnArmor "100"                  armor on every spawn (0 = leave the engine's)
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
# A restart respawns map items a couple of frames after new_game; scan again then.
ITEM_RESCAN_S = 0.5
# A frag's obituary shows the client's own "You fragged X" in the centre, replacing a centre
# print sent in the same frame; ours goes out after it.
CENTER_DELAY_S = 0.2

DEFAULT_LADDER = "rl:2 rg:2 lg:2 pg:2 sg:2 gl:2 mg:2 g:1"
CVAR_DEFAULTS = (
    ("qlx_gunGameEnabled", "0"),
    ("qlx_gunGameLadder", DEFAULT_LADDER),
    ("qlx_gunGameGauntletDemote", "1"),
    ("qlx_gunGameSuicideDemote", "1"),
    ("qlx_gunGameGauntletSkip", "1"),
    ("qlx_gunGameWeaponDelay", "0"),
    ("qlx_gunGameSpawnArmor", "100"),
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


def parse_ms(text):
    try:
        return max(0, int(str(text).strip()))
    except (TypeError, ValueError):
        return 0


def parse_channels(text):
    words = {w.strip() for w in (text or "").split(",")}
    return frozenset(w for w in words if w in CHANNELS)


def advance(state, ladder, event):
    """(step, frags_on_step) after a "frag", "skip" (the whole step at once),
    "back" (one frag) or "demote" (one step) -> (state, outcome)."""
    step, frags = state
    if event == "back":
        if frags:
            return (step, frags - 1), "back"
        if step == 0:
            return (0, 0), "none"
        return (step - 1, ladder[step - 1][1] - 1), "down"
    if event == "skip":
        if step == len(ladder) - 1:
            return (step, frags + 1), "win"
        return (step + 1, 0), "up"
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


def last_step_text(name):
    # Short: a centre print doesn't wrap, and long nicknames are common.
    return "^3{}^7: last step!".format(name)


def win_text(name):
    return "^3{}^7 wins Gun Game!".format(name)


# --- HUD panel (client cvars read by our ui/intro.menu) ----------------------

HUD_FIELDS = ("mod_gg_on", "mod_gg_w", "mod_gg_next", "mod_gg_step", "mod_gg_lead")


def hud_fields(ladder, state, lead):
    step, frags = state
    key, need = ladder[step]
    return {
        "mod_gg_on": "1",
        "mod_gg_w": key,
        "mod_gg_next": ladder[step + 1][0] if step + 1 < len(ladder) else "",
        "mod_gg_step": "Step {}/{}   {}/{}".format(step + 1, len(ladder), frags, need),
        "mod_gg_lead": lead,
    }


def lead_text(own_key, leader_key, leader_name, leader_step, total):
    if leader_key is None:
        return ""
    if leader_key == own_key:
        return "You lead"
    return "Leader: ^3{}^7 {}/{}".format(leader_name, leader_step, total)


def hud_blank():
    return dict.fromkeys(HUD_FIELDS, "")


def hud_diff(sent, fields):
    return {k: v for k, v in fields.items() if sent.get(k, "") != v}


def hud_clean(value):
    return str(value).replace("\\", "").replace('"', "").replace(";", "")


def hud_command(cs_index, systeminfo, fields):
    """One cs command that sets *fields* as client cvars on top of the current systeminfo."""
    pairs = "".join("\\{}\\{}".format(k, hud_clean(fields[k])) for k in HUD_FIELDS if k in fields)
    return 'cs {} "{}{}"'.format(cs_index, systeminfo, pairs)


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
        self._won = False        # the match is decided; nothing counts until the next one
        self._item_hooked = False

        for name, value in CVAR_DEFAULTS:
            self.set_cvar_once(name, value)
        self._reload_ladder()

        if "item_touch" in minqlx.EVENT_DISPATCHERS:
            self._sync_item_hook()
        else:
            self.logger.warning("gungame: no item_touch event in this runtime, map weapons stay pickable")
        self.add_hook("map", self.handle_map)
        self.add_hook("new_game", self.handle_new_game)
        self.add_hook("game_start", self.handle_game_start)
        self.add_hook("game_end", self.handle_game_end)
        self.add_hook("player_spawn", self.handle_player_spawn)
        self.add_hook("kill", self.handle_kill)
        self.add_hook("death", self.handle_death)
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

    @staticmethod
    def _key(player):
        """steam_id, or the client slot for bots (their steam_id is 0)."""
        sid = int(player.steam_id)
        return str(sid) if sid else "bot{}".format(int(player.id))

    def _state(self, player):
        return self._states.setdefault(self._key(player), (0, 0))

    def _sync_item_hook(self):
        """The engine only calls into Python for item_touch while it is hooked, so hook it
        only while Gun Game is active. Checked on load and on every new_game."""
        active = self._active()
        if active == self._item_hooked or "item_touch" not in minqlx.EVENT_DISPATCHERS:
            return
        if active:
            self.add_hook("item_touch", self.handle_item_touch, priority=minqlx.Priority.HIGH)
        else:
            self.remove_hook("item_touch", self.handle_item_touch, priority=minqlx.Priority.HIGH)
        self._item_hooked = active

    def _notify(self, target, text, cvar):
        channels = parse_channels(self.get_cvar(cvar))
        try:
            if target is None:
                if "print" in channels:
                    self.msg(text)
            elif "print" in channels:
                target.tell(text)
        except Exception:
            pass
        if "center" in channels:
            self.delay(CENTER_DELAY_S, self._center_print, target, text)

    def _center_print(self, target, text):
        try:
            if target is None:
                self.center_print(text)
            else:
                target.center_print(text)
        except Exception:
            pass  # the player left

    def _apply_loadout(self, player, armor=False):
        step = self._state(player)[0] if self._in_progress() else 0
        key = loadout(self._ladder, min(step, len(self._ladder) - 1))
        try:
            player.weapons = minqlx.Weapons(loadout_weapons(key))
            player.weapon = WEAPON_FIELDS.index(key) + 1
            if self._in_progress():
                player.score = step + 1
            if armor:
                spawn_armor = parse_ms(self.get_cvar("qlx_gunGameSpawnArmor"))
                if spawn_armor:
                    player.armor = spawn_armor
        except Exception:
            # Gone or dead by now.
            return

    _give_loadout = minqlx.next_frame(_apply_loadout)

    def _step_up_loadout(self, player):
        """The new step's weapon, after qlx_gunGameWeaponDelay ms (the score does not wait)."""
        ms = parse_ms(self.get_cvar("qlx_gunGameWeaponDelay"))
        if not ms:
            self._give_loadout(player)
            return
        self._write_score(player)
        self._disarm(player)
        self.delay(ms / 1000.0, self._apply_loadout, player)

    @minqlx.next_frame
    def _disarm(self, player):
        """Gauntlet only while the new weapon is on its way."""
        try:
            player.weapons = minqlx.Weapons(loadout_weapons("g"))
            player.weapon = WEAPON_FIELDS.index("g") + 1
        except Exception:
            return

    @minqlx.next_frame
    def _write_score(self, player):
        try:
            player.score = self._state(player)[0] + 1
        except Exception:
            return

    # --- map items ---

    def handle_map(self, mapname, factory):
        self._restore_fraglimit()

    def _scan_items(self):
        """Free the items where the engine can (a hidden powerup would come back
        visible on its first respawn); else match_restore's stock hide: no draw,
        no client, no touch. A restart spawns them again and new_game repeats this."""
        remove = getattr(minqlx, "remove_entity", None)
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
                if remove is not None:
                    remove(int(ent.s.number))
                    hidden += 1
                    continue
                ent.s.e_flags = int(ent.s.e_flags) | EF_NODRAW
                ent.r.sv_flags = int(ent.r.sv_flags) | SVF_NOCLIENT
                ent.r.contents = 0
                minqlx.link_entity(int(ent.s.number))
                hidden += 1
            except Exception:
                continue
        if hidden:
            self.logger.info("gungame: took %d weapons and powerups off the map", hidden)

    _hide_map_items = minqlx.next_frame(_scan_items)

    def handle_item_touch(self, player, entity):
        if not self._active():
            return
        try:
            classname = str(entity.classname or "")
        except Exception:
            return
        if is_blocked_item(classname):
            return minqlx.Return.STOP_EVENT

    # --- frags ---

    def _counts(self):
        return not self._won and self._active() and self._in_progress()

    def handle_kill(self, victim, killer, mod):
        if killer is None or not self._counts():
            return
        gauntlet = str(mod) == "GAUNTLET"
        event = "skip" if gauntlet and self.get_cvar("qlx_gunGameGauntletSkip", bool) else "frag"
        state, outcome = advance(self._state(killer), self._ladder, event)
        self._states[self._key(killer)] = state
        if outcome == "win":
            self._won = True
            self._finish(killer)
            return
        if outcome == "up":
            self._step_up_loadout(killer)
            self._notify(killer, step_text(self._ladder, state), "qlx_gunGameStepNotify")
        else:
            self._write_score(killer)

        if gauntlet and self.get_cvar("qlx_gunGameGauntletDemote", bool):
            self._demote(victim)

        if outcome == "up":
            self._announce_leader(killer, state)

    def handle_death(self, victim, killer, mod):
        if killer is not None and int(killer.id) != int(victim.id):
            return  # a frag: handle_kill has it
        if str(mod) == "SWITCH_TEAMS" or not self._counts():
            return
        if self.get_cvar("qlx_gunGameSuicideDemote", bool):
            self._demote(victim, "back")

    def _demote(self, player, event="demote"):
        state, outcome = advance(self._state(player), self._ladder, event)
        self._states[self._key(player)] = state
        if outcome == "down":
            self._notify(player, demote_text(self._ladder, state), "qlx_gunGameStepNotify")
            self._update_leader(player)
        elif outcome == "back":
            self._notify(player, step_text(self._ladder, state), "qlx_gunGameStepNotify")
        self._write_score(player)

    def _update_leader(self, player):
        """Re-pick the leader after *player*'s step changed; announce a new one."""
        leader = pick_leader(self._states, self._leader)
        if leader == self._leader:
            return
        self._leader = leader
        if leader is None:
            return
        if leader != self._key(player):
            player = next((p for p in self.players() if self._key(p) == leader), None)
            if player is None:
                return
        text = leader_text(player.name, self._states[leader][0] + 1, len(self._ladder))
        self._notify(None, text, "qlx_gunGameLeaderNotify")

    def _announce_leader(self, player, state):
        total = len(self._ladder)
        self._update_leader(player)
        if state[0] == total - 1:
            self._notify(None, last_step_text(player.name), "qlx_gunGameLeaderNotify")

    @minqlx.next_frame
    def _finish(self, winner):
        limit = len(self._ladder) + 1
        if self._saved_fraglimit is None:  # enabled mid-match: game_start saved nothing
            self._saved_fraglimit = self.get_cvar("fraglimit") or "0"
        try:
            winner.score = limit
            name = winner.name
        except Exception:
            name = "?"
        self.set_cvar("fraglimit", str(limit))
        self._notify(None, win_text(name), "qlx_gunGameLeaderNotify")

    # --- match lifecycle ---

    def handle_player_spawn(self, player):
        if self._active():
            self._give_loadout(player, armor=True)

    def _reset(self):
        self._states = {}
        self._leader = None
        self._won = False
        self._reload_ladder()

    def _restore_fraglimit(self):
        if self._saved_fraglimit is not None:
            self.set_cvar("fraglimit", self._saved_fraglimit)
            self._saved_fraglimit = None

    def handle_new_game(self):
        # Every map load and every restart (match start included) respawns the
        # map items; the map event fires on a fresh load only.
        self._reset()
        self._sync_item_hook()
        if self._active():
            self._hide_map_items()
            self.delay(ITEM_RESCAN_S, self._scan_items)

    def handle_game_start(self):
        self._reset()
        if not self._active():
            return
        if self._saved_fraglimit is None:
            self._saved_fraglimit = self.get_cvar("fraglimit") or "0"
        self.set_cvar("fraglimit", "0")

    def handle_game_end(self, aborted):
        self._restore_fraglimit()

    def handle_unload(self, plugin):
        if plugin == self.__class__.__name__:
            self._restore_fraglimit()
