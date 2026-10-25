# item_roulette.py - every pickup is a coin flip: the item gives what it always
# gives, or it takes instead.
#
# The engine's pickup is never blocked. On item_touch the plugin remembers the
# player's state and flips the coin; on the item_pickup that follows (same C
# call stack, only after a successful pickup) it rewrites the result:
#   armor / health / ammo  "take": old value minus the configured amount
#   weapon                 "take": the weapon is removed again (if the player
#                          had it) or simply not given; ammo stays as before
#   powerup                "take": the powerup is not given and the player is
#                          cursed for its duration instead: quad deals weaker
#                          damage, battle suit takes more, invisibility draws
#                          a talk balloon over the head, regeneration drains
#                          health, haste is just denied
# A "give" with a configured amount equal to the stock one (or "*") leaves the
# engine's result alone.
#
# CVARs:
#   qlx_itemRouletteEnabled "0"        master switch, read on every touch
#   qlx_itemRouletteTakeChance "50"    percent of pickups that take
#   qlx_itemRouletteAnnounce "1"       centre-screen message to the player
#   qlx_itemRouletteArmor    "shard=*/2 ga=*/33 ya=*/50 ra=*/66"
#   qlx_itemRouletteHealth   "5=*/5 25=*/15 50=*/33 mega=*/66"
#   qlx_itemRouletteWeapons  "default=*"              ammo given; take = lose the weapon
#   qlx_itemRouletteAmmo     "default=*/6 lg=*/66"
#   qlx_itemRoulettePowerups "quad=0.5 bs=1.5 regen=1"
# Rule syntax: key=give/take, "*" = what the engine gives, "default" = any
# key without its own entry. Weapon and ammo keys are g mg sg gl rl lg rg pg
# bfg gh ng pl cg hmg.
#
# Damage cannot be scaled before the engine applies it (the damage event is
# raised afterwards), so the quad and battle suit curses correct health and
# armor after each hit: a hit that killed is final, and the battle suit curse
# never finishes a player (health floor 1).

import random

try:
    import minqlxtended as minqlx
except ImportError:
    import minqlx

# Field order of minqlxtended.Weapons, weapon_t minus WP_NONE.
WEAPON_FIELDS = ("g", "mg", "sg", "gl", "rl", "lg", "rg", "pg", "bfg", "gh", "ng", "pl", "cg", "hmg", "hands")
# Which weapon to hold when the current one is taken away, best first.
WEAPON_PREFERENCE = ("rl", "lg", "rg", "pg", "sg", "gl", "hmg", "cg", "mg", "ng", "pl", "bfg", "gh", "g", "hands")

# itemType_t (quake_common.h).
IT_WEAPON = 1
IT_AMMO = 2
IT_ARMOR = 3
IT_HEALTH = 4
IT_POWERUP = 5

EF_TALK = 0x00001000  # entityState_t.eFlags: draw a talk balloon

ARMOR_MAX = 200
AMMO_MAX = 200

ARMOR_KEYS = {
    "item_armor_shard": "shard",
    "item_armor_jacket": "ga",
    "item_armor_combat": "ya",
    "item_armor_body": "ra",
}
HEALTH_KEYS = {
    "item_health_small": "5",
    "item_health": "25",
    "item_health_large": "50",
    "item_health_mega": "mega",
}
CURSE_KINDS = {
    "item_quad": "quad",
    "item_enviro": "battlesuit",
    "item_invis": "invisibility",
    "item_invisibility": "invisibility",
    "item_regen": "regeneration",
    "item_haste": "haste",
}
CURSE_FACTOR_KEY = {"quad": "quad", "battlesuit": "bs", "regeneration": "regen"}
CURSE_FACTOR_DEFAULT = {"quad": 0.5, "bs": 1.5, "regen": 1.0}

CVAR_DEFAULTS = (
    ("qlx_itemRouletteEnabled", "0"),
    ("qlx_itemRouletteTakeChance", "50"),
    ("qlx_itemRouletteAnnounce", "1"),
    ("qlx_itemRouletteArmor", "shard=*/2 ga=*/33 ya=*/50 ra=*/66"),
    ("qlx_itemRouletteHealth", "5=*/5 25=*/15 50=*/33 mega=*/66"),
    ("qlx_itemRouletteWeapons", "default=*"),
    ("qlx_itemRouletteAmmo", "default=*/6 lg=*/66"),
    ("qlx_itemRoulettePowerups", "quad=0.5 bs=1.5 regen=1"),
)


# --- pure decisions ----------------------------------------------------------

def _amount(text):
    """"*" or "" -> None (stock / nothing), digits -> int, anything else -> error."""
    text = text.strip()
    if text in ("", "*"):
        return None
    if not text.isdigit():
        raise ValueError(text)
    return int(text)


def parse_rules(text):
    """"ra=100/66 ga=*/33 sg=10" -> {"ra": (100, 66), "ga": (None, 33), "sg": (10, None)}.
    Tokens that do not parse are dropped."""
    rules = {}
    for token in (text or "").split():
        key, sep, value = token.partition("=")
        if not sep or not key or not value:
            continue
        give_text, _, take_text = value.partition("/")
        if not give_text.strip() and not take_text.strip():
            continue
        try:
            rules[key.strip().lower()] = (_amount(give_text), _amount(take_text))
        except ValueError:
            continue
    return rules


def rule_for(rules, key):
    return rules.get(key, rules.get("default", (None, None)))


def parse_factors(text):
    """"quad=0.5 bs=1.5" -> {"quad": 0.5, "bs": 1.5}; bad tokens dropped."""
    factors = {}
    for token in (text or "").split():
        key, sep, value = token.partition("=")
        if not sep or not key:
            continue
        try:
            factors[key.strip().lower()] = float(value)
        except ValueError:
            continue
    return factors


def roll_take(chance_percent, rnd):
    """rnd is a float in [0, 1)."""
    return rnd * 100.0 < chance_percent


def plan_amount(pre, stock, give, take, outcome, cap, floor=0):
    """New value for a counter the pickup changed, or None to keep the engine's result."""
    if outcome == "give":
        if give is None or give == stock:
            return None
        return min(pre + give, cap)
    if take is None:
        return pre
    return max(pre - take, floor)


def health_cap(classname):
    """Health bubbles and mega stack up to 200, 25 and 50 only to 100 (bg_misc)."""
    return 200 if classname in ("item_health_small", "item_health_mega") else 100


def plan_ammo(pre_ammo, idx, give, take, outcome):
    new = plan_amount(pre_ammo[idx], None, give, take, outcome, cap=AMMO_MAX)
    if new is None:
        return None
    out = list(pre_ammo)
    out[idx] = new
    return tuple(out)


def plan_weapon(pre_weapons, pre_ammo, idx, give, outcome):
    """(weapons or None, ammo or None, had_it). None keeps the engine's result."""
    had = bool(pre_weapons[idx])
    if outcome == "give":
        if give is None:
            return None, None, had
        out = list(pre_ammo)
        out[idx] = min(pre_ammo[idx] + give, AMMO_MAX)
        return None, tuple(out), had
    weapons = list(pre_weapons)
    weapons[idx] = False
    return tuple(weapons), tuple(pre_ammo), had


def best_weapon(weapons, ammo, exclude):
    """Index of the best held weapon with ammo, the gauntlet as the last resort."""
    for short in WEAPON_PREFERENCE:
        idx = WEAPON_FIELDS.index(short)
        if idx == exclude or not weapons[idx]:
            continue
        if ammo[idx] > 0 or short in ("g", "hands"):
            return idx
    return WEAPON_FIELDS.index("g")


def curse_kind(classname):
    return CURSE_KINDS.get(classname)


def quad_refund(damage, factor, armor_after):
    """What to give back to the victim of a cursed-quad hit: (armor, health).
    Split 2/3 armor, 1/3 health like G_Damage while the victim still has armor."""
    if factor >= 1.0 or damage <= 0:
        return 0, 0
    refund = int(round(damage * (1.0 - factor)))
    if armor_after > 0:
        armor = refund * 2 // 3
        return armor, refund - armor
    return 0, refund


def battlesuit_extra(damage, factor, armor, health):
    """Armor and health of a cursed-battle-suit victim after the extra damage.
    Armor goes first; health never drops below 1."""
    if factor <= 1.0 or damage <= 0:
        return armor, health
    extra = int(round(damage * (factor - 1.0)))
    from_armor = min(armor, extra)
    rest = extra - from_armor
    return armor - from_armor, max(1, health - rest)


# --- the plugin ----------------------------------------------------------------

class item_roulette(minqlx.Plugin):
    def __init__(self):
        self._touch = {}        # player id -> snapshot taken on item_touch
        self._curses = {}       # player id -> {"kind", "until", "factor"}
        self._rule_cache = {}   # cvar name -> (raw text, parsed)
        self._damage_hooked = False
        self._next_drain = 0

        for name, value in CVAR_DEFAULTS:
            self.set_cvar_once(name, value)

        if "item_touch" in minqlx.EVENT_DISPATCHERS and "item_pickup" in minqlx.EVENT_DISPATCHERS:
            self.add_hook("item_touch", self.handle_item_touch, priority=minqlx.Priority.LOW)
            self.add_hook("item_pickup", self.handle_item_pickup, priority=minqlx.Priority.LOW)
        else:
            self.logger.warning("item_roulette: no item_touch/item_pickup events in this runtime, plugin idle")
        self.add_hook("frame", self.handle_frame)
        self.add_hook("player_spawn", self.handle_player_spawn)
        self.add_hook("death", self.handle_death)
        self.add_hook("player_disconnect", self.handle_player_disconnect)
        self.add_hook("new_game", self.handle_new_game)

        self.plugin_version = "1.0"

    # --- settings ---

    def _enabled(self):
        return bool(self.get_cvar("qlx_itemRouletteEnabled", bool))

    def _chance(self):
        try:
            return int(self.get_cvar("qlx_itemRouletteTakeChance") or "0")
        except ValueError:
            return 0

    def _rules(self, cvar, parser=parse_rules):
        raw = self.get_cvar(cvar) or ""
        cached = self._rule_cache.get(cvar)
        if cached is None or cached[0] != raw:
            cached = (raw, parser(raw))
            self._rule_cache[cvar] = cached
        return cached[1]

    def _factor(self, kind):
        key = CURSE_FACTOR_KEY.get(kind)
        if key is None:
            return None
        factors = self._rules("qlx_itemRoulettePowerups", parse_factors)
        return factors.get(key, CURSE_FACTOR_DEFAULT[key])

    def _announce(self, player, msg):
        if not self.get_cvar("qlx_itemRouletteAnnounce", bool):
            return
        try:
            player.center_print(msg)
        except Exception:
            pass

    @staticmethod
    def _signed(delta, what):
        color = "^1" if delta < 0 else "^2"
        return "{}{}{} {}".format(color, "+" if delta >= 0 else "-", abs(delta), what)

    # --- pickups ---

    def handle_item_touch(self, player, entity):
        if not self._enabled():
            return
        try:
            classname = str(entity.classname or "")
            if not classname:
                return
            snap = {
                "classname": classname,
                "modelindex": int(entity.s.modelindex),
                "take": roll_take(self._chance(), random.random()),
                "health": int(player.health),
                "armor": int(player.armor),
            }
            if classname.startswith(("weapon_", "ammo_")):
                snap["weapons"] = tuple(player.weapons)
                snap["ammo"] = tuple(player.ammo)
            elif classname in CURSE_KINDS:
                snap["powerups"] = tuple(player.powerups)
            self._touch[int(player.id)] = snap
        except Exception:
            # A touch by a client without a game client, or an entity gone mid-frame.
            return

    def handle_item_pickup(self, player, item_name):
        snap = self._touch.pop(int(player.id), None)
        if not snap or not self._enabled():
            return
        try:
            item = minqlx.Item(snap["modelindex"])
            gi_type = int(item.gi_type)
            gi_tag = int(item.gi_tag)
            stock = int(item.quantity)
            name = str(item.pickup_name or snap["classname"])
        except Exception:
            self.logger.warning("item_roulette: cannot read item %s", snap.get("classname"))
            return
        outcome = "take" if snap["take"] else "give"
        try:
            if gi_type == IT_ARMOR:
                self._apply_armor(player, snap, stock, outcome)
            elif gi_type == IT_HEALTH:
                self._apply_health(player, snap, stock, outcome)
            elif gi_type == IT_WEAPON and "weapons" in snap:
                self._apply_weapon(player, snap, gi_tag, name, outcome)
            elif gi_type == IT_AMMO and "ammo" in snap:
                self._apply_ammo(player, snap, gi_tag, name, outcome)
            elif gi_type == IT_POWERUP and "powerups" in snap:
                self._apply_powerup(player, snap, stock, name, outcome)
        except Exception as exc:
            self.logger.warning("item_roulette: %s on %s failed: %s", outcome, snap["classname"], exc)

    def _apply_armor(self, player, snap, stock, outcome):
        give, take = rule_for(self._rules("qlx_itemRouletteArmor"), ARMOR_KEYS.get(snap["classname"], ""))
        new = plan_amount(snap["armor"], stock, give, take, outcome, cap=ARMOR_MAX)
        if new is None:
            return
        player.armor = new
        self._announce(player, self._signed(new - snap["armor"], "ARMOR"))

    def _apply_health(self, player, snap, stock, outcome):
        classname = snap["classname"]
        give, take = rule_for(self._rules("qlx_itemRouletteHealth"), HEALTH_KEYS.get(classname, ""))
        new = plan_amount(snap["health"], stock, give, take, outcome, cap=health_cap(classname), floor=1)
        if new is None:
            return
        player.health = new
        self._announce(player, self._signed(new - snap["health"], "HEALTH"))

    @staticmethod
    def _weapon_index(gi_tag):
        idx = gi_tag - 1
        if 0 <= idx < len(WEAPON_FIELDS):
            return idx
        return None

    def _apply_weapon(self, player, snap, gi_tag, name, outcome):
        idx = self._weapon_index(gi_tag)
        if idx is None:
            return
        give, _ = rule_for(self._rules("qlx_itemRouletteWeapons"), WEAPON_FIELDS[idx])
        new_weapons, new_ammo, had = plan_weapon(snap["weapons"], snap["ammo"], idx, give, outcome)
        if new_ammo is not None:
            player.ammo = minqlx.Weapons(new_ammo)
        if new_weapons is not None:
            player.weapons = minqlx.Weapons(new_weapons)
            if int(player.weapon) == gi_tag:
                player.weapon = best_weapon(new_weapons, new_ammo, exclude=idx) + 1
        if outcome == "take":
            self._announce(player, "^1LOST {}".format(name.upper()) if had else "^1NO {} FOR YOU".format(name.upper()))
        elif new_ammo is not None:
            self._announce(player, self._signed(new_ammo[idx] - snap["ammo"][idx], "{} AMMO".format(name.upper())))

    def _apply_ammo(self, player, snap, gi_tag, name, outcome):
        idx = self._weapon_index(gi_tag)
        if idx is None:
            return
        give, take = rule_for(self._rules("qlx_itemRouletteAmmo"), WEAPON_FIELDS[idx])
        new_ammo = plan_ammo(snap["ammo"], idx, give, take, outcome)
        if new_ammo is None:
            return
        player.ammo = minqlx.Weapons(new_ammo)
        self._announce(player, self._signed(new_ammo[idx] - snap["ammo"][idx], name.upper()))

    def _apply_powerup(self, player, snap, stock, name, outcome):
        if outcome == "give":
            return
        kind = curse_kind(snap["classname"])
        player.powerups = minqlx.Powerups(snap["powerups"])
        if kind is None or kind == "haste":
            self._announce(player, "^1{} DENIED".format(name.upper()))
            return
        duration_ms = max(1, stock) * 1000
        self._curses[int(player.id)] = {
            "kind": kind,
            "until": int(minqlx.level.time) + duration_ms,
            "factor": self._factor(kind),
        }
        if kind in ("quad", "battlesuit"):
            self._hook_damage()
        text = {
            "quad": "CURSED QUAD: WEAK DAMAGE",
            "battlesuit": "CURSED BATTLE SUIT: MORE DAMAGE TAKEN",
            "invisibility": "CURSED INVISIBILITY: EVERYONE SEES YOU",
            "regeneration": "CURSED REGENERATION: HEALTH DRAINS",
        }[kind]
        self._announce(player, "^1{} {}s".format(text, duration_ms // 1000))

    # --- curses ---

    def _hook_damage(self):
        if not self._damage_hooked and "damage" in minqlx.EVENT_DISPATCHERS:
            self.add_hook("damage", self.handle_damage)
            self._damage_hooked = True

    def _unhook_damage(self):
        if self._damage_hooked:
            self.remove_hook("damage", self.handle_damage)
            self._damage_hooked = False

    def _drop_curse(self, player_id):
        self._curses.pop(int(player_id), None)

    def _active_curse(self, player_id, kind, now):
        curse = self._curses.get(int(player_id))
        if curse and curse["kind"] == kind and now < curse["until"]:
            return curse
        return None

    def handle_damage(self, target, attacker, damage, dflags, mod):
        if not self._curses or target is None:
            return
        now = int(minqlx.level.time)
        try:
            if int(target.health) <= 0:
                return
            if attacker is not None and int(attacker.id) != int(target.id):
                curse = self._active_curse(attacker.id, "quad", now)
                if curse:
                    armor = int(target.armor)
                    add_armor, add_health = quad_refund(int(damage), curse["factor"], armor)
                    if add_armor:
                        target.armor = min(armor + add_armor, ARMOR_MAX)
                    if add_health:
                        target.health = min(int(target.health) + add_health, 200)
            curse = self._active_curse(target.id, "battlesuit", now)
            if curse:
                new_armor, new_health = battlesuit_extra(int(damage), curse["factor"], int(target.armor), int(target.health))
                target.armor = new_armor
                target.health = new_health
        except Exception:
            return

    def handle_frame(self):
        if not self._curses:
            if self._damage_hooked:
                self._unhook_damage()
            return
        if not self._enabled():
            self._curses.clear()
            self._unhook_damage()
            return
        now = int(minqlx.level.time)
        drain = now >= self._next_drain
        if drain:
            self._next_drain = now + 1000
        need_damage = False
        for pid, curse in list(self._curses.items()):
            if now >= curse["until"]:
                self._drop_curse(pid)
                continue
            kind = curse["kind"]
            try:
                if kind == "invisibility":
                    ps = minqlx.GameClient(pid).ps
                    ps.e_flags = int(ps.e_flags) | EF_TALK
                elif kind == "regeneration" and drain:
                    player = minqlx.Player(pid)
                    health = int(player.health)
                    if health > 1:
                        player.health = max(1, health - int(round(curse["factor"] or 0)))
                elif kind in ("quad", "battlesuit"):
                    need_damage = True
            except Exception:
                self._drop_curse(pid)
        if not need_damage:
            self._unhook_damage()

    def handle_player_spawn(self, player):
        self._drop_curse(player.id)
        self._touch.pop(int(player.id), None)

    def handle_death(self, victim, killer, mod):
        if victim is not None:
            self._drop_curse(victim.id)

    def handle_player_disconnect(self, player, reason):
        self._drop_curse(player.id)
        self._touch.pop(int(player.id), None)

    def handle_new_game(self):
        self._touch.clear()
        self._curses.clear()
        self._unhook_damage()
