# td_rules.py - tower defence rules: tables, waves, money, pads. No engine calls.
#
# tower_defence.py feeds Game the clock and the live creep count and acts on what it returns.
from collections import namedtuple

CreepType = namedtuple("CreepType", "name hp speed reward lives attack parts frames fps hull")
TurretType = namedtuple("TurretType", "kind prices damage interval range parts")
PadTurret = namedtuple("PadTurret", "kind level spent")
CreepAttack = namedtuple("CreepAttack", "damage splash radius interval range muzzle")

START_MONEY = 300
START_LIVES = 20
PAUSE_S = 25
SPAWN_INTERVAL_S = 1.0
MAX_CREEPS = 60
REFUND = 0.7
OVER_S = 15
MAX_MISSILES = 40
ROCKET_RADIUS = 120


def _md3(*names):
    return tuple("models/td/{}.md3".format(n) for n in names)


# hull: (half width, top above the hull origin), near what the model shows, so shots at it hit
CREEPS = {
    "normal": CreepType("normal", 150, 200, 5, 1, None, _md3("normal", "normal_gun"), (1, 29), 15, (20, 26)),
    "fast": CreepType("fast", 80, 400, 5, 1, None, _md3("fast"), (1, 29), 30, (16, 12)),
    "heavy": CreepType("heavy", 600, 120, 20, 2, None, _md3("heavy"), (5, 25), 20, (48, 170)),
    "shooter": CreepType("shooter", 200, 180, 15, 1, "pg", _md3("shooter", "shooter_head"), (5, 25), 20, (40, 130)),
    "boss": CreepType("boss", 3000, 100, 50, 5, "rl", _md3("boss", "boss_head"), (5, 25), 20, (64, 248)),
}

TURRETS = {
    "pg": TurretType("pg", (100, 100, 200), (20, 30, 45), 0.3, 900, _md3("turret_base", "turret_pg")),
    "rl": TurretType("rl", (200, 200, 400), (100, 150, 220), 2.0, 1200, _md3("turret_base", "turret_rl")),
}

# muzzle: above the hull origin. A creep's splash also hurts other creeps, so it stays small.
CREEP_ATTACKS = {
    "pg": CreepAttack(15, 0, 0, 0.6, 800, 20),
    "rl": CreepAttack(60, 40, 100, 2.5, 800, 40),
}

WAVES = [
    [("normal", 8)],
    [("normal", 12)],
    [("normal", 10), ("fast", 6)],
    [("normal", 12), ("heavy", 2)],
    [("normal", 12), ("boss", 1)],
    [("fast", 14), ("normal", 8)],
    [("normal", 14), ("shooter", 4)],
    [("normal", 12), ("heavy", 6)],
    [("fast", 16), ("shooter", 6)],
    [("normal", 16), ("heavy", 4), ("boss", 1)],
    [("normal", 18), ("shooter", 8)],
    [("fast", 20), ("heavy", 8)],
    [("normal", 20), ("shooter", 10)],
    [("fast", 18), ("heavy", 10), ("shooter", 6)],
    [("normal", 20), ("heavy", 8), ("shooter", 8), ("boss", 1)],
]
BOSS_HP = {5: 3000, 10: 5000, 15: 8000}


def hp_scale(players):
    return round(1.0 + 0.3 * max(0, players - 2), 2)


def wave_bonus(wave):
    return 100 + 20 * wave


def creep_hp(name, wave, players):
    base = BOSS_HP.get(wave, CREEPS[name].hp) if name == "boss" else CREEPS[name].hp
    return int(base * hp_scale(players))


class Game:
    def __init__(self, pad_count):
        self.pad_count = pad_count
        self.reset()

    def reset(self):
        self.phase = "idle"
        self.wave = 0
        self.lives = START_LIVES
        self.money = START_MONEY
        self.pads = {}
        self.result = None
        self._to_spawn = []
        self._next_at = 0.0
        self._over_at = None

    def start(self, now):
        self.reset()
        self.phase = "pause"
        self._next_at = now + PAUSE_S

    def jump(self, wave, now):
        """Wave `wave` starts on the next tick; money and pads stay. For tests on the server."""
        self.phase = "pause"
        self.wave = wave - 1
        self.result = None
        self._to_spawn = []
        self._next_at = now
        self._over_at = None

    def tick(self, now, alive_creeps):
        """One step of the clock. Returns creep type names to spawn now."""
        if self.phase == "over":
            if self._over_at is None:
                self._over_at = now
            elif now - self._over_at >= OVER_S:
                self.reset()
            return []
        if self.phase == "pause" and now >= self._next_at:
            self.wave += 1
            self.phase = "wave"
            self._to_spawn = [name for name, count in WAVES[self.wave - 1] for _ in range(count)]
            self._next_at = now
        if self.phase != "wave":
            return []
        if self._to_spawn:
            if now >= self._next_at and alive_creeps < MAX_CREEPS:
                self._next_at = now + SPAWN_INTERVAL_S
                return [self._to_spawn.pop(0)]
            return []
        if alive_creeps == 0:
            self.money += wave_bonus(self.wave)
            if self.wave >= len(WAVES):
                self.phase = "over"
                self.result = "win"
            else:
                self.phase = "pause"
                self._next_at = now + PAUSE_S
        return []

    def killed(self, name):
        self.money += CREEPS[name].reward

    def leaked(self, name):
        self.lives = max(0, self.lives - CREEPS[name].lives)
        if self.lives == 0 and self.phase != "over":
            self.phase = "over"
            self.result = "loss"

    def vanished(self):
        """A creep got stuck and was removed: no reward, no lost life; alive_creeps drops by itself."""

    def build(self, pad, kind):
        if kind not in TURRETS:
            return "Unknown turret, use: !build rl or !build pg"
        if not 0 <= pad < self.pad_count:
            return "No such pad"
        if pad in self.pads:
            return "This pad is taken, try !upgrade or !sell"
        price = TURRETS[kind].prices[0]
        if self.money < price:
            return "Not enough money: {} costs {}, the team has {}".format(kind, price, self.money)
        self.money -= price
        self.pads[pad] = PadTurret(kind, 0, price)
        return "Built {} on pad {}, money left {}".format(kind, pad, self.money)

    def upgrade(self, pad):
        turret = self.pads.get(pad)
        if turret is None:
            return "Nothing to upgrade on this pad"
        prices = TURRETS[turret.kind].prices
        if turret.level + 1 >= len(prices):
            return "This {} is at the top level".format(turret.kind)
        price = prices[turret.level + 1]
        if self.money < price:
            return "Not enough money: the upgrade costs {}, the team has {}".format(price, self.money)
        self.money -= price
        self.pads[pad] = PadTurret(turret.kind, turret.level + 1, turret.spent + price)
        return "Upgraded {} on pad {} to level {}, money left {}".format(
            turret.kind, pad, turret.level + 2, self.money)

    def sell(self, pad):
        turret = self.pads.pop(pad, None)
        if turret is None:
            return "Nothing to sell on this pad"
        refund = int(turret.spent * REFUND)
        self.money += refund
        return "Sold {} on pad {} for {}, money {}".format(turret.kind, pad, refund, self.money)
