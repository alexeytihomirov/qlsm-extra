"""stream_telemetry_unified: engine end-of-game stats per player in match_end."""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _minqlx_stub import bare_instance, import_plugin  # noqa: E402

pytestmark = pytest.mark.standalone

st = import_plugin("stream_telemetry_unified")

A = "76561198000000001"
B = "76561198000000002"
C = "76561198000000003"

NAMES = ("g", "mg", "sg", "gl", "rl", "lg", "rg", "pg", "bfg", "gh", "ng", "pl", "cg", "hmg", "hands")


class _Log:
    def __init__(self):
        self.records = []

    def __getattr__(self, level):
        return lambda msg, *args: self.records.append((level, msg % args if args else msg))


def _weapons(**values):
    return SimpleNamespace(**{n: values.get(n, 0) for n in NAMES})


def _expanded(**over):
    fields = dict(
        play_time=600000, damage_dealt=4210, damage_taken=3380, kills=21, deaths=14, suicides=1,
        max_kill_streak=5, mega_health_pickups=4, red_armor_pickups=5, yellow_armor_pickups=3,
        green_armor_pickups=1, health_pickups=20, ammo_pickups=14,
        weapon_kills=_weapons(rl=9, gh=7), weapon_deaths=_weapons(rl=4),
        shots_fired=_weapons(rl=120, hands=3), shots_hit=_weapons(rl=48),
        weapon_damage_dealt=_weapons(rl=1900), weapon_damage_taken=_weapons(rl=1500),
        weapon_pickups=_weapons(rl=6), weapon_time=_weapons(rl=210000, lg=5),
    )
    fields.update(over)
    return SimpleNamespace(**fields)


def test_player_stats_reads_fields_by_name():
    got = st.player_stats(_expanded())
    assert got["time_ms"] == 600000
    assert (got["dmg_dealt"], got["dmg_taken"]) == (4210, 3380)
    assert (got["kills"], got["deaths"], got["suicides"], got["max_streak"]) == (21, 14, 1, 5)
    assert got["weapons"]["rl"] == {"k": 9, "d": 4, "s": 120, "h": 48, "dd": 1900, "dt": 1500, "p": 6, "t": 210000}
    assert got["weapons"]["lg"] == {"k": 0, "d": 0, "s": 0, "h": 0, "dd": 0, "dt": 0, "p": 0, "t": 5}
    assert got["pickups"] == {"mega": 4, "ra": 5, "ya": 3, "ga": 1, "health": 20, "ammo": 14}


def test_player_stats_none_without_expanded():
    assert st.player_stats(None) is None


def test_zero_weapons_omitted():
    got = st.player_stats(_expanded())
    assert set(got["weapons"]) == {"rl", "lg"}
    assert "gh" not in got["weapons"] and "hands" not in got["weapons"]
    empty = st.player_stats(_expanded(
        weapon_kills=_weapons(), weapon_deaths=_weapons(), shots_fired=_weapons(), shots_hit=_weapons(),
        weapon_damage_dealt=_weapons(), weapon_damage_taken=_weapons(), weapon_pickups=_weapons(),
        weapon_time=_weapons(),
    ))
    assert empty["weapons"] == {}


def _plugin(expanded_by_steam, teams, lines=None):
    posted = []
    lines = lines or {}

    class _P:
        def __init__(self, steam):
            self.steam = steam
            self.team = teams[steam]
            score, kills, deaths = lines.get(steam, (1, 1, 0))
            self.stats = SimpleNamespace(score=score, kills=kills, deaths=deaths)

        @property
        def expanded_stats(self):
            v = expanded_by_steam[self.steam]
            if isinstance(v, Exception):
                raise v
            return v

    players = [_P(s) for s in expanded_by_steam]
    p = bare_instance(
        st.stream_telemetry_unified,
        players=lambda: players,
        _is_bot=lambda pl: False,
        _steam_str=lambda pl: pl.steam,
        _display_name=lambda pl: pl.steam[-1],
        get_cvar=lambda name: "",
        _match_guid=lambda: None,
        _level_time_ms=lambda: 1000,
        _timelimit_sec=lambda: 600,
        _fraglimit=lambda: 0,
        _resolve_match_end_game_time_ms=lambda meta: None,
        _pause_lifecycle_open=False,
        _post_session_lifecycle_now=lambda kind, *, game_time_ms=None, meta=None: posted.append((kind, meta)),
        _last_end_guid=None,
        logger=_Log(),
    )
    return p, posted


def test_spectator_and_failure_have_no_stats():
    p, posted = _plugin(
        {A: _expanded(), B: _expanded(), C: RuntimeError("boom")},
        {A: "free", B: "spectator", C: "free"},
        {B: (0, 0, 0)},
    )
    p.on_game_end(False)
    by = {r["steam_id64"]: r for r in posted[-1][1]["players"]}
    assert "stats" in by[A]
    assert "stats" not in by[B]
    assert "stats" not in by[C]
    p.on_game_end(False)
    warnings = [r for r in p.logger.records if r[0] == "warning" and "boom" in r[1]]
    assert len(warnings) == 1
    assert C in warnings[0][1]  # names the player whose stats could not be read


def test_forfeit_leaver_in_spectators_keeps_stats():
    # A duel player who went to spectators stopped the game; the engine still holds the game's numbers.
    p, posted = _plugin(
        {A: _expanded(), B: _expanded(kills=7)},
        {A: "free", B: "spectator"},
        {A: (11, 11, 7), B: (7, 7, 11)},
    )
    p.on_game_end(True)
    meta = posted[-1][1]
    by = {r["steam_id64"]: r for r in meta["players"]}
    assert by[B]["stats"]["kills"] == 7
    assert meta["winner_steam_id64"] == A


def test_expanded_stats_none_has_no_stats():
    p, posted = _plugin({A: None}, {A: "free"})
    p.on_game_end(False)
    assert "stats" not in posted[-1][1]["players"][0]


def test_match_end_players_carry_stats():
    p, posted = _plugin({A: _expanded(), B: _expanded(kills=3)}, {A: "free", B: "free"})
    p.on_game_end(False)
    kind, meta = posted[-1]
    assert kind == "match_end"
    by = {r["steam_id64"]: r for r in meta["players"]}
    assert by[A]["stats"]["kills"] == 21
    assert by[B]["stats"]["kills"] == 3
    assert by[A]["score"] == 1
