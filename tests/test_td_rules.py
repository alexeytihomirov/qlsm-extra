"""Tower defence rules: tables, waves, money, pads, lives."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

import td_rules  # noqa: E402

pytestmark = pytest.mark.standalone


def test_tables():
    assert len(td_rules.WAVES) == 15
    assert 8 == sum(c for _, c in td_rules.WAVES[0])
    assert 30 <= sum(c for _, c in td_rules.WAVES[14]) <= 40
    for wave in td_rules.WAVES:
        assert all(name in td_rules.CREEPS for name, _ in wave)


def test_boss_comes_last_in_its_waves():
    for number in td_rules.BOSS_HP:
        assert td_rules.WAVES[number - 1][-1] == ("boss", 1)


def test_hp_scale():
    assert [td_rules.hp_scale(n) for n in (1, 2, 3, 8)] == [1.0, 1.0, 1.3, 2.8]


def test_creep_hp():
    assert td_rules.creep_hp("normal", 1, 3) == 195
    assert td_rules.creep_hp("boss", 10, 2) == 5000


def test_wave_bonus():
    assert td_rules.wave_bonus(3) == 160


def test_sell_after_upgrade_refunds_70_percent_and_frees_pad():
    g = td_rules.Game(2)
    g.money = 1000
    g.build(0, "pg")
    g.upgrade(0)
    g.sell(0)
    assert g.money == 1000 - 200 + 140
    assert 0 not in g.pads
    g.build(0, "rl")
    assert g.pads[0].kind == "rl"


def test_leak_to_zero_is_loss():
    g = td_rules.Game(1)
    g.start(0.0)
    g.lives = 2
    g.leaked("heavy")
    assert g.phase == "over" and g.result == "loss"


def test_vanished_creep_gives_nothing_and_wave_can_end():
    g = td_rules.Game(1)
    g.start(0.0)
    assert g.tick(25.0, 0) == ["normal"]
    for t in range(26, 33):
        g.tick(float(t), 1)
    money, lives = g.money, g.lives
    for _ in range(8):
        g.vanished()
    assert (g.money, g.lives) == (money, lives)
    g.tick(40.0, 0)
    assert g.phase == "pause" and g.wave == 1


def test_last_spawn_does_not_end_the_wave_in_the_same_tick():
    g = td_rules.Game(1)
    g.start(0.0)
    g.tick(25.0, 0)
    g._to_spawn = ["normal"]
    assert g.tick(26.0, 0) == ["normal"]
    assert g.phase == "wave"


def test_win_after_wave_15():
    g = td_rules.Game(1)
    g.start(0.0)
    g.wave = 15
    g.phase = "wave"
    g._to_spawn = []
    g.tick(1.0, 0)
    assert g.phase == "over" and g.result == "win"


def test_over_returns_to_idle_after_the_wait():
    g = td_rules.Game(1)
    g.start(0.0)
    g.lives = 1
    g.leaked("normal")
    g.tick(100.0, 0)
    g.tick(114.0, 0)
    assert g.phase == "over"
    g.tick(115.0, 0)
    assert g.phase == "idle" and g.result is None and g.lives == td_rules.START_LIVES


def test_spawn_cap_holds_queue():
    g = td_rules.Game(1)
    g.start(0.0)
    assert g.tick(25.0, td_rules.MAX_CREEPS) == []
    assert g.tick(25.0, td_rules.MAX_CREEPS - 1) == ["normal"]


def test_spawn_interval():
    g = td_rules.Game(1)
    g.start(0.0)
    assert g.tick(25.0, 0) == ["normal"]
    assert g.tick(25.5, 1) == []
    assert g.tick(26.0, 1) == ["normal"]


def test_build_errors():
    g = td_rules.Game(2)
    g.money = 150
    for pad, kind in ((5, "pg"), (0, "rl"), (0, "bfg")):
        assert g.build(pad, kind)
        assert g.money == 150 and not g.pads
    g.build(0, "pg")
    money = g.money
    assert g.build(0, "pg")
    assert g.money == money and g.pads[0].level == 0


def test_upgrade_top_level_refused():
    g = td_rules.Game(1)
    g.money = 1000
    g.build(0, "pg")
    g.upgrade(0)
    g.upgrade(0)
    assert g.pads[0].level == 2 and g.pads[0].spent == 400
    money = g.money
    assert "top" in g.upgrade(0)
    assert g.money == money


def test_upgrade_and_sell_on_empty_pad():
    g = td_rules.Game(1)
    assert g.upgrade(0) and g.sell(0)
    assert g.money == td_rules.START_MONEY


def test_wave_bonus_paid_on_clear():
    g = td_rules.Game(1)
    g.start(0.0)
    g.tick(25.0, 0)
    g._to_spawn = []
    money = g.money
    g.tick(26.0, 0)
    assert g.money == money + td_rules.wave_bonus(1)


def test_killed_pays_the_type_reward():
    g = td_rules.Game(1)
    g.killed("boss")
    assert g.money == td_rules.START_MONEY + 50


def test_reset_restores_start():
    g = td_rules.Game(1)
    g.start(0.0)
    g.build(0, "pg")
    g.lives = 3
    g.reset()
    assert (g.phase, g.wave, g.lives, g.money, g.pads, g.result) == (
        "idle", 0, td_rules.START_LIVES, td_rules.START_MONEY, {}, None)


def test_jump_starts_the_wave_next_tick():
    g = td_rules.Game(1)
    g.start(0.0)
    g.jump(15, 3.0)
    assert g.tick(3.0, 0) == ["normal"]
    assert g.wave == 15 and g.phase == "wave"
