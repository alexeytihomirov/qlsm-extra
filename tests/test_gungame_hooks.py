"""gungame: hook wiring against fake engine objects."""
from types import SimpleNamespace

import pytest

from tests._minqlx_stub import bare_instance, import_plugin

pytestmark = pytest.mark.standalone

gg = import_plugin("gungame")
W = gg.WEAPON_FIELDS
STOP_EVENT = "stop_event"


def held(player):
    return [f for f, h in zip(W, player.weapons) if h]


def make_entity(eid, classname):
    return SimpleNamespace(
        classname=classname,
        s=SimpleNamespace(number=eid, e_flags=0),
        r=SimpleNamespace(sv_flags=0, contents=1),
    )


def make_engine(entities=()):
    linked = []
    return SimpleNamespace(
        Weapons=tuple,
        Return=SimpleNamespace(STOP_EVENT=STOP_EVENT),
        Priority=SimpleNamespace(HIGH=1),
        EVENT_DISPATCHERS={"item_touch": object()},
        NonexistentPlayerError=type("NonexistentPlayerError", (Exception,), {}),
        entities=lambda inuse=True, etype=None: list(entities),
        link_entity=linked.append,
        linked=linked,
    )


class FakePlayer:
    def __init__(self, sid=1, name="A"):
        self.steam_id = sid
        self.name = name
        self.weapons = tuple(f in ("g", "mg") for f in W)
        self.weapon = W.index("mg") + 1
        self.score = 0
        self.tells = []
        self.centers = []

    def tell(self, msg):
        self.tells.append(msg)

    def center_print(self, msg):
        self.centers.append(msg)


def make_plugin(monkeypatch, engine=None, cvars=None, state="in_progress"):
    engine = engine or make_engine()
    monkeypatch.setattr(gg, "minqlx", engine)
    settings = {name: value for name, value in gg.CVAR_DEFAULTS}
    settings.update({"qlx_gunGameEnabled": "1", "g_gametype": "0", "fraglimit": "50"})
    settings.update(cvars or {})

    def get_cvar(name, return_type=str, default=None):
        value = settings.get(name, default)
        if return_type is bool:
            return value not in (None, "0", "", "false")
        return value

    def set_cvar(name, value, flags=0):
        settings[name] = str(value)

    warnings = []
    broadcast = {"msg": [], "center": []}
    plugin = bare_instance(
        gg.gungame,
        _states={}, _ladder=gg.parse_ladder(gg.DEFAULT_LADDER), _ladder_raw=gg.DEFAULT_LADDER,
        _leader=None, _saved_fraglimit=None,
        get_cvar=get_cvar, set_cvar=set_cvar,
        msg=broadcast["msg"].append, center_print=broadcast["center"].append,
        game=SimpleNamespace(state=state),
        logger=SimpleNamespace(warning=lambda *a, **k: warnings.append(a), info=lambda *a, **k: None),
    )
    plugin.settings = settings
    plugin.warnings = warnings
    plugin.broadcast = broadcast
    plugin.engine = engine
    return plugin


# --- spawn loadout --------------------------------------------------------

def test_spawn_in_warmup_gives_gauntlet_and_first_weapon(monkeypatch):
    plugin = make_plugin(monkeypatch, state="warmup")
    player = FakePlayer()
    plugin.handle_player_spawn(player)
    assert held(player) == ["g", "rl"]
    assert player.weapon == W.index("rl") + 1
    assert player.score == 0


def test_spawn_in_match_gives_step_weapon_and_score(monkeypatch):
    plugin = make_plugin(monkeypatch)
    player = FakePlayer()
    plugin._states["1"] = (2, 1)
    plugin.handle_player_spawn(player)
    assert held(player) == ["g", "lg"]
    assert player.score == 3


# --- map items ------------------------------------------------------------

def test_item_touch_blocks_weapons_and_powerups_only(monkeypatch):
    plugin = make_plugin(monkeypatch)
    player = FakePlayer()
    assert plugin.handle_item_touch(player, make_entity(5, "weapon_railgun")) == STOP_EVENT
    assert plugin.handle_item_touch(player, make_entity(6, "item_quad")) == STOP_EVENT
    assert plugin.handle_item_touch(player, make_entity(7, "item_armor_body")) is None


def test_map_hides_weapons_and_powerups(monkeypatch):
    rl, quad, mega = make_entity(10, "weapon_rocketlauncher"), make_entity(11, "item_quad"), make_entity(12, "item_health_mega")
    engine = make_engine([rl, quad, mega])
    plugin = make_plugin(monkeypatch, engine)
    plugin.handle_map("campgrounds", "ffa")
    for ent in (rl, quad):
        assert ent.s.e_flags & gg.EF_NODRAW
        assert ent.r.sv_flags & gg.SVF_NOCLIENT
        assert ent.r.contents == 0
    assert mega.s.e_flags == 0 and mega.r.contents == 1
    assert engine.linked == [10, 11]


@pytest.mark.parametrize("cvars", [{"qlx_gunGameEnabled": "0"}, {"g_gametype": "4"}])
def test_disabled_or_not_ffa_is_inert(monkeypatch, cvars):
    rl = make_entity(10, "weapon_rocketlauncher")
    engine = make_engine([rl])
    plugin = make_plugin(monkeypatch, engine, cvars=cvars)
    player = FakePlayer()
    plugin.handle_player_spawn(player)
    assert held(player) == ["g", "mg"]
    assert plugin.handle_item_touch(player, rl) is None
    plugin.handle_map("campgrounds", "ffa")
    assert rl.r.contents == 1 and engine.linked == []


# --- ladder / match lifecycle --------------------------------------------

def test_invalid_ladder_keeps_previous(monkeypatch):
    plugin = make_plugin(monkeypatch, cvars={"qlx_gunGameLadder": "rl:1 lg:1"})
    plugin._reload_ladder()
    assert plugin._ladder == [("rl", 1), ("lg", 1)]
    plugin.settings["qlx_gunGameLadder"] = "rl:0"
    plugin._reload_ladder()
    assert plugin._ladder == [("rl", 1), ("lg", 1)]
    assert len(plugin.warnings) == 1


def test_game_start_zeroes_fraglimit_and_new_game_restores(monkeypatch):
    plugin = make_plugin(monkeypatch)
    plugin._states["1"] = (3, 0)
    plugin.handle_game_start({})
    assert plugin.settings["fraglimit"] == "0"
    assert plugin._states == {}
    plugin.handle_new_game()
    assert plugin.settings["fraglimit"] == "50"
    assert plugin._saved_fraglimit is None


# --- notifications --------------------------------------------------------

def test_notify_channels(monkeypatch):
    plugin = make_plugin(monkeypatch, cvars={"qlx_gunGameStepNotify": "print,center"})
    player = FakePlayer()
    plugin._notify(player, "hi", "qlx_gunGameStepNotify")
    assert player.tells == ["hi"] and player.centers == ["hi"]
    plugin.settings["qlx_gunGameStepNotify"] = "off"
    plugin._notify(player, "again", "qlx_gunGameStepNotify")
    assert player.tells == ["hi"]
    plugin._notify(None, "all", "qlx_gunGameLeaderNotify")
    assert plugin.broadcast["msg"] == ["all"] and plugin.broadcast["center"] == []
