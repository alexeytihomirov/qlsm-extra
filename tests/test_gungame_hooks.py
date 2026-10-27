"""gungame: hook wiring against fake engine objects."""
import inspect
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
    commands = []
    active = set()  # client ids still loading: the engine refuses to send to them

    def send_server_command(cid, cmd):
        if cid in active:
            return False
        commands.append((cid, cmd))
        return True

    return SimpleNamespace(
        CS_SYSTEMINFO=1,
        configstring=lambda index, cached=True: "\\sv_pure\\1",
        send_server_command=send_server_command,
        commands=commands,
        loading=active,
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
    def __init__(self, sid=1, name="A", pid=None):
        self.steam_id = sid
        self.id = sid if pid is None else pid
        self.name = name
        self.team = "free"
        self.weapons = tuple(f in ("g", "mg") for f in W)
        self.weapon = W.index("mg") + 1
        self.score = 0
        self.armor = 0
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
    delays = []
    hooks = []
    players = []
    broadcast = {"msg": [], "center": []}
    plugin = bare_instance(
        gg.gungame,
        _states={}, _ladder=gg.parse_ladder(gg.DEFAULT_LADDER), _ladder_raw=gg.DEFAULT_LADDER,
        _leader=None, _saved_fraglimit=None, _won=False, _item_hooked=True,
        _hud_sent={}, _hud_dirty=set(), _hud_pending=False, _ended=False,
        _hud_flush_soon=lambda: None,  # tests flush by hand
        add_hook=lambda event, handler, priority=0: hooks.append(("add", event)),
        remove_hook=lambda event, handler, priority=0: hooks.append(("remove", event)),
        players=lambda: list(players),
        get_cvar=get_cvar, set_cvar=set_cvar,
        msg=broadcast["msg"].append, center_print=broadcast["center"].append,
        game=SimpleNamespace(state=state),
        delay=lambda seconds, func, *args: delays.append((seconds, func, args)),
        logger=SimpleNamespace(warning=lambda *a, **k: warnings.append(a), info=lambda *a, **k: None),
    )
    plugin.settings = settings
    plugin.warnings = warnings
    plugin.delays = delays
    plugin.broadcast = broadcast
    plugin.hooks = hooks
    plugin.player_list = players
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
    plugin.handle_new_game()
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
    plugin.handle_new_game()
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


def test_game_start_zeroes_fraglimit_and_game_end_restores(monkeypatch):
    plugin = make_plugin(monkeypatch)
    plugin._states["1"] = (3, 0)
    plugin.handle_game_start()
    assert plugin.settings["fraglimit"] == "0"
    assert plugin._states == {}
    plugin.handle_new_game()  # a restart right around the start must not undo it
    assert plugin.settings["fraglimit"] == "0"
    plugin.handle_game_end(False)
    assert plugin.settings["fraglimit"] == "50"
    assert plugin._saved_fraglimit is None


def test_map_change_restores_fraglimit(monkeypatch):
    plugin = make_plugin(monkeypatch)
    plugin.handle_game_start()
    plugin.handle_map("campgrounds", "ffa")
    assert plugin.settings["fraglimit"] == "50"


def test_new_game_hides_items_again_after_a_restart(monkeypatch):
    rl = make_entity(10, "weapon_rocketlauncher")
    engine = make_engine([rl])
    plugin = make_plugin(monkeypatch, engine)
    plugin.handle_new_game()
    assert rl.r.contents == 0 and engine.linked == [10]


# --- notifications --------------------------------------------------------

def run_delays(plugin):
    pending, plugin.delays[:] = list(plugin.delays), []
    for _, func, args in pending:
        func(*args)


def test_notify_channels(monkeypatch):
    plugin = make_plugin(monkeypatch, cvars={"qlx_gunGameStepNotify": "print,center"})
    player = FakePlayer()
    plugin._notify(player, "hi", "qlx_gunGameStepNotify")
    run_delays(plugin)
    assert player.tells == ["hi"] and player.centers == ["hi"]
    plugin.settings["qlx_gunGameStepNotify"] = "off"
    plugin._notify(player, "again", "qlx_gunGameStepNotify")
    assert player.tells == ["hi"]
    plugin._notify(None, "all", "qlx_gunGameLeaderNotify")
    assert plugin.broadcast["msg"] == ["all"] and plugin.broadcast["center"] == []


# --- kills and deaths -----------------------------------------------------

L3 = {"qlx_gunGameLadder": "rl:2 lg:1 g:1"}


def ladder3(monkeypatch, **cvars):
    plugin = make_plugin(monkeypatch, cvars={**L3, **cvars})
    plugin._reload_ladder()
    return plugin


def test_kill_counts_then_steps_up_with_loadout_and_notify(monkeypatch):
    plugin = ladder3(monkeypatch)
    a, b = FakePlayer(1, "A"), FakePlayer(2, "B")
    plugin.handle_kill(b, a, "ROCKET")
    assert plugin._states["1"] == (0, 1) and a.score == 1 and a.tells == []
    plugin.handle_kill(b, a, "ROCKET")
    assert plugin._states["1"] == (1, 0)
    assert held(a) == ["g", "lg"] and a.score == 2
    assert a.tells == ["Step 2/3: ^3LG^7 (0/1)"]


def test_gauntlet_kill_demotes_victim(monkeypatch):
    plugin = ladder3(monkeypatch)
    a, b = FakePlayer(1, "A"), FakePlayer(2, "B")
    plugin._states["2"] = (2, 0)
    plugin.handle_kill(b, a, "GAUNTLET")
    assert plugin._states["2"] == (1, 0)
    assert b.tells == ["Down to step 2/3: ^3LG^7"] and b.score == 2


def test_gauntlet_demote_switch_off(monkeypatch):
    plugin = ladder3(monkeypatch, qlx_gunGameGauntletDemote="0")
    a, b = FakePlayer(1, "A"), FakePlayer(2, "B")
    plugin._states["2"] = (2, 0)
    plugin.handle_kill(b, a, "GAUNTLET")
    assert plugin._states["2"] == (2, 0)


def test_suicide_and_world_death_cost_one_frag(monkeypatch):
    plugin = ladder3(monkeypatch)
    a = FakePlayer(1, "A")
    plugin._states["1"] = (1, 0)
    plugin.handle_death(a, None, "LAVA")
    assert plugin._states["1"] == (0, 1)
    assert a.tells == ["Down to step 1/3: ^3RL^7"] and a.score == 1
    plugin.handle_death(a, a, "ROCKET_SPLASH")
    assert plugin._states["1"] == (0, 0)
    assert a.tells[-1] == "Step 1/3: ^3RL^7 (0/2)"


def test_suicide_demote_switch_off(monkeypatch):
    plugin = ladder3(monkeypatch, qlx_gunGameSuicideDemote="0")
    a = FakePlayer(1, "A")
    plugin._states["1"] = (2, 0)
    plugin.handle_death(a, None, "LAVA")
    assert plugin._states["1"] == (2, 0)


def test_death_by_other_player_is_left_to_kill(monkeypatch):
    plugin = ladder3(monkeypatch)
    a, b = FakePlayer(1, "A"), FakePlayer(2, "B")
    plugin._states["2"] = (2, 0)
    plugin.handle_death(b, a, "ROCKET")
    assert plugin._states["2"] == (2, 0)


def test_switch_teams_death_does_not_demote(monkeypatch):
    plugin = ladder3(monkeypatch)
    a = FakePlayer(1, "A")
    plugin._states["1"] = (2, 0)
    plugin.handle_death(a, a, "SWITCH_TEAMS")
    plugin.handle_death(a, None, "SWITCH_TEAMS")
    assert plugin._states["1"] == (2, 0)


def test_warmup_kill_does_not_count(monkeypatch):
    plugin = make_plugin(monkeypatch, state="warmup")
    a, b = FakePlayer(1, "A"), FakePlayer(2, "B")
    plugin.handle_kill(b, a, "GAUNTLET")
    plugin.handle_death(a, None, "LAVA")
    assert plugin._states == {}


def test_leader_announced_once_on_change(monkeypatch):
    plugin = ladder3(monkeypatch, qlx_gunGameLadder="rl:1 lg:2 pg:1 g:1")
    plugin._reload_ladder()
    a, b = FakePlayer(1, "A"), FakePlayer(2, "B")
    plugin.handle_kill(b, a, "ROCKET")
    assert plugin.broadcast["msg"] == ["^3A^7 leads: step 2/4"]
    plugin.handle_kill(b, a, "LIGHTNING")
    assert plugin.broadcast["msg"] == ["^3A^7 leads: step 2/4"]


def test_last_step_announced(monkeypatch):
    plugin = ladder3(monkeypatch)
    a, b = FakePlayer(1, "A"), FakePlayer(2, "B")
    plugin._states["1"] = (1, 0)
    plugin._leader = "1"
    plugin.handle_kill(b, a, "LIGHTNING")
    assert plugin.broadcast["msg"] == ["^3A^7: last step!"]


def test_win_sets_score_and_fraglimit_above_ladder(monkeypatch):
    plugin = ladder3(monkeypatch)
    a, b = FakePlayer(1, "A"), FakePlayer(2, "B")
    plugin._states.update({"1": (2, 0), "2": (2, 0)})
    plugin.handle_kill(b, a, "GAUNTLET")
    assert a.score == 4
    assert plugin.settings["fraglimit"] == "4"
    assert plugin.broadcast["msg"][-1] == "^3A^7 wins Gun Game!"


class GonePlayer(FakePlayer):
    """Disconnected by the next frame: every engine write raises."""
    gone = False

    def __init__(self, *args):
        super().__init__(*args)
        self.gone = True

    @property
    def weapons(self):
        return self.__dict__.get("_weapons", ())

    @weapons.setter
    def weapons(self, value):
        if self.gone:
            raise gg.minqlx.NonexistentPlayerError("gone")
        self.__dict__["_weapons"] = value


def test_kill_by_disconnected_killer_does_not_raise(monkeypatch):
    plugin = ladder3(monkeypatch)
    a, b = GonePlayer(1, "A"), FakePlayer(2, "B")
    plugin._states["1"] = (0, 1)
    plugin.handle_kill(b, a, "ROCKET")
    assert plugin._states["1"] == (1, 0)


def test_mid_match_joiner_starts_at_step_one(monkeypatch):
    plugin = make_plugin(monkeypatch)
    player = FakePlayer(7, "New")
    plugin.handle_player_spawn(player)
    assert plugin._states["7"] == (0, 0)
    assert held(player) == ["g", "rl"] and player.score == 1


# --- review fixes ---------------------------------------------------------

# Arguments each fork dispatcher passes (_events.py); add_hook binds the
# handler to this many arguments and refuses to load the plugin otherwise.
DISPATCH_ARITY = {
    "handle_map": 2, "handle_new_game": 0, "handle_game_start": 0, "handle_game_end": 1,
    "handle_player_spawn": 1, "handle_kill": 3, "handle_death": 3, "handle_item_touch": 2,
    "handle_unload": 1, "handle_team_switch": 3, "handle_player_disconnect": 2,
    "handle_player_loaded": 1,
}


@pytest.mark.parametrize("name,arity", sorted(DISPATCH_ARITY.items()))
def test_handlers_match_fork_dispatch_arity(monkeypatch, name, arity):
    plugin = make_plugin(monkeypatch)
    inspect.signature(getattr(plugin, name)).bind(*[None] * arity)


def test_bots_have_separate_states(monkeypatch):
    plugin = ladder3(monkeypatch)
    bot1, bot2, bot3 = FakePlayer(0, "Bot1", pid=3), FakePlayer(0, "Bot2", pid=4), FakePlayer(0, "Bot3", pid=5)
    plugin.handle_kill(bot2, bot1, "ROCKET")
    plugin.handle_kill(bot2, bot1, "ROCKET")
    assert bot1.score == 2
    plugin.handle_player_spawn(bot3)
    assert held(bot3) == ["g", "rl"] and bot3.score == 1


def test_bot_killing_bot_is_not_a_suicide(monkeypatch):
    plugin = ladder3(monkeypatch)
    bot1, bot2 = FakePlayer(0, "Bot1", pid=3), FakePlayer(0, "Bot2", pid=4)
    plugin.handle_player_spawn(bot2)
    plugin.handle_kill(bot2, bot1, "LIGHTNING")
    plugin.handle_kill(bot2, bot1, "LIGHTNING")
    plugin.handle_death(bot2, bot1, "LIGHTNING")
    assert bot2.tells == [] and bot2.score == 1


def test_win_saves_fraglimit_when_enabled_mid_match(monkeypatch):
    plugin = ladder3(monkeypatch)
    a, b = FakePlayer(1, "A"), FakePlayer(2, "B")
    plugin._states["1"] = (2, 0)
    plugin.handle_kill(b, a, "GAUNTLET")
    assert plugin.settings["fraglimit"] == "4"
    plugin.handle_game_end(False)
    assert plugin.settings["fraglimit"] == "50"


def test_nothing_counts_after_a_win(monkeypatch):
    plugin = ladder3(monkeypatch)
    a, b = FakePlayer(1, "A"), FakePlayer(2, "B")
    plugin._states.update({"1": (2, 0), "2": (2, 0)})
    plugin.handle_kill(b, a, "GAUNTLET")
    plugin.handle_kill(a, b, "GAUNTLET")
    plugin.handle_death(a, None, "LAVA")
    assert b.score == 0 and a.score == 4
    assert plugin.broadcast["msg"].count("^3B^7 wins Gun Game!") == 0
    plugin.handle_game_start()
    plugin.handle_kill(b, a, "ROCKET")
    assert plugin._states["1"] == (0, 1)


def test_map_items_are_removed_when_the_engine_can(monkeypatch):
    rl, mega = make_entity(10, "weapon_rocketlauncher"), make_entity(12, "item_health_mega")
    engine = make_engine([rl, mega])
    removed = []
    engine.remove_entity = removed.append
    plugin = make_plugin(monkeypatch, engine)
    plugin.handle_new_game()
    assert removed == [10]
    assert engine.linked == []


# --- operator feedback round 1 -------------------------------------------

def test_spawn_gives_armor(monkeypatch):
    plugin = make_plugin(monkeypatch)
    player = FakePlayer()
    plugin.handle_player_spawn(player)
    assert player.armor == 100


def test_spawn_armor_off(monkeypatch):
    plugin = make_plugin(monkeypatch, cvars={"qlx_gunGameSpawnArmor": "0"})
    player = FakePlayer()
    plugin.handle_player_spawn(player)
    assert player.armor == 0


def test_gauntlet_kill_skips_the_rest_of_the_step(monkeypatch):
    plugin = ladder3(monkeypatch)
    a, b = FakePlayer(1, "A"), FakePlayer(2, "B")
    plugin.handle_kill(b, a, "GAUNTLET")
    assert plugin._states["1"] == (1, 0)
    assert held(a) == ["g", "lg"]


def test_gauntlet_skip_off_counts_one_frag(monkeypatch):
    plugin = ladder3(monkeypatch, qlx_gunGameGauntletSkip="0")
    a, b = FakePlayer(1, "A"), FakePlayer(2, "B")
    plugin.handle_kill(b, a, "GAUNTLET")
    assert plugin._states["1"] == (0, 1)


def test_weapon_delay_gives_the_new_weapon_later(monkeypatch):
    plugin = ladder3(monkeypatch, qlx_gunGameWeaponDelay="500")
    a, b = FakePlayer(1, "A"), FakePlayer(2, "B")
    plugin._states["1"] = (0, 1)
    plugin.handle_kill(b, a, "ROCKET")
    assert held(a) == ["g"]        # the old weapon is gone, the new one not here yet
    assert a.score == 2            # the score does not wait
    seconds, func, args = plugin.delays[-1]
    assert seconds == 0.5
    func(*args)
    assert held(a) == ["g", "lg"]


def test_weapon_delay_zero_is_immediate(monkeypatch):
    plugin = ladder3(monkeypatch, qlx_gunGameWeaponDelay="0")
    a, b = FakePlayer(1, "A"), FakePlayer(2, "B")
    plugin._states["1"] = (0, 1)
    plugin.handle_kill(b, a, "ROCKET")
    assert held(a) == ["g", "lg"] and plugin.delays == []


def test_new_game_scans_items_again_after_they_spawn(monkeypatch):
    rl = make_entity(10, "weapon_rocketlauncher")
    engine = make_engine([])
    later = []
    engine.entities = lambda inuse=True, etype=None: list(later)
    removed = []
    engine.remove_entity = removed.append
    plugin = make_plugin(monkeypatch, engine)
    plugin.handle_new_game()
    assert removed == []           # restart: items not spawned yet on the next frame
    later.append(rl)
    seconds, func, args = plugin.delays[-1]
    assert 0 < seconds <= 1
    func(*args)
    assert removed == [10]


def test_weapon_delay_takes_the_old_weapon_at_once(monkeypatch):
    plugin = ladder3(monkeypatch, qlx_gunGameWeaponDelay="500")
    a, b = FakePlayer(1, "A"), FakePlayer(2, "B")
    a.weapons = gg.loadout_weapons("rl")
    plugin._states["1"] = (0, 1)
    plugin.handle_kill(b, a, "ROCKET")
    assert held(a) == ["g"] and a.weapon == W.index("g") + 1
    seconds, func, args = plugin.delays[-1]
    func(*args)
    assert held(a) == ["g", "lg"] and a.weapon == W.index("lg") + 1


# --- live round 3 ---------------------------------------------------------

def test_center_notify_waits_for_the_clients_own_frag_message(monkeypatch):
    plugin = make_plugin(monkeypatch, cvars={"qlx_gunGameStepNotify": "center", "qlx_gunGameLeaderNotify": "center"})
    player = FakePlayer()
    plugin._notify(player, "step", "qlx_gunGameStepNotify")
    plugin._notify(None, "lead", "qlx_gunGameLeaderNotify")
    assert player.centers == [] and plugin.broadcast["center"] == []
    assert [d[0] for d in plugin.delays] == [gg.CENTER_DELAY_S] * 2
    run_delays(plugin)
    assert player.centers == ["step"] and plugin.broadcast["center"] == ["lead"]


def test_center_notify_to_a_player_who_left_is_dropped(monkeypatch):
    plugin = make_plugin(monkeypatch, cvars={"qlx_gunGameStepNotify": "center"})
    player = FakePlayer()

    def gone(msg):
        raise plugin.engine.NonexistentPlayerError()
    player.center_print = gone
    plugin._notify(player, "step", "qlx_gunGameStepNotify")
    run_delays(plugin)


L4 = "rl:1 lg:1 pg:1 g:1"


def test_leader_passes_on_when_the_leader_is_demoted(monkeypatch):
    plugin = ladder3(monkeypatch, qlx_gunGameLadder=L4)
    a, b, c = FakePlayer(1, "A"), FakePlayer(2, "B"), FakePlayer(3, "C")
    plugin.player_list.extend([a, b, c])
    plugin._states.update({"1": (2, 0), "2": (2, 0)})
    plugin._leader = "1"
    plugin.handle_kill(a, c, "GAUNTLET")
    assert plugin._states["1"] == (1, 0)
    assert plugin._leader == "2"
    assert plugin.broadcast["msg"] == ["^3B^7 leads: step 3/4"]


def test_leader_cleared_when_a_suicide_drops_everyone_below_step_two(monkeypatch):
    plugin = ladder3(monkeypatch, qlx_gunGameLadder=L4)
    a = FakePlayer(1, "A")
    plugin.player_list.append(a)
    plugin._states["1"] = (1, 0)
    plugin._leader = "1"
    plugin.handle_death(a, None, "LAVA")
    assert plugin._states["1"] == (0, 0)
    assert plugin._leader is None and plugin.broadcast["msg"] == []


def test_item_touch_hook_only_while_active(monkeypatch):
    plugin = make_plugin(monkeypatch, cvars={"qlx_gunGameEnabled": "0"})
    plugin._sync_item_hook()
    plugin._sync_item_hook()
    assert plugin.hooks == [("remove", "item_touch")] and plugin._item_hooked is False
    plugin.settings["qlx_gunGameEnabled"] = "1"
    plugin.handle_new_game()
    assert plugin.hooks[-1] == ("add", "item_touch") and plugin._item_hooked is True
    plugin.settings["g_gametype"] = "4"
    plugin.handle_new_game()
    assert plugin.hooks[-1] == ("remove", "item_touch")


# --- HUD panel --------------------------------------------------------------

LAD = gg.parse_ladder(L3["qlx_gunGameLadder"])


def panel(state, keys=None):
    """The cs command the panel gets for *state* (all fields, or only *keys*)."""
    f = gg.hud_fields(LAD, state)
    return gg.modhud_util.command(1, "\\sv_pure\\1", {k: f[k] for k in (keys or gg.modhud_util.FIELDS)})


def centre(state):
    f = gg.hud_fields(LAD, state)
    return 'cp "%s"' % gg.modhud_util.plain("\n".join([f["mod_hud_l1"], f["mod_hud_l2"]]))


@pytest.fixture(autouse=True)
def clean_hud_clients():
    gg.modhud_util.CLIENT.clear()
    gg.modhud_util.PENDING.clear()
    gg.modhud_util.HAS_PANEL.clear()
    gg.modhud_util.INGAME.clear()
    gg.modhud_util.CENTRE.clear()
    yield
    gg.modhud_util.CLIENT.clear()
    gg.modhud_util.PENDING.clear()
    gg.modhud_util.HAS_PANEL.clear()
    gg.modhud_util.INGAME.clear()
    gg.modhud_util.CENTRE.clear()


def test_player_without_the_panel_gets_the_line_in_the_centre(monkeypatch):
    a, b = FakePlayer(1, "A"), FakePlayer(2, "B")
    plugin = hud_players(monkeypatch, a, b, hello=False)
    plugin.handle_player_loaded(a)
    plugin.handle_player_loaded(b)
    assert plugin.handle_client_command(b, "modhud 1") == STOP_EVENT  # B has our files
    assert plugin.handle_client_command(b, "say hi") is None
    plugin.handle_player_spawn(a)
    plugin.handle_player_spawn(b)
    plugin._hud_flush()
    printed = [cmd for c, cmd in plugin.engine.commands if cmd.startswith("cp ")]
    assert printed == [centre((0, 0))]
    assert [c for c, cmd in plugin.engine.commands if cmd.startswith("cp ")] == [1]


def test_panel_goes_again_after_join_match(monkeypatch):
    # Live (#26): Join Match opens after player_loaded and hides the panel sent on load.
    a = FakePlayer(1, "A")
    plugin = hud_players(monkeypatch, a)
    plugin.handle_player_loaded(a)
    plugin._hud_flush()
    plugin.handle_player_spawn(a)
    plugin._hud_flush()
    plugin.handle_player_spawn(a)
    plugin._hud_flush()
    full = panel((0, 0))[5:]
    assert len(hud_cmds(plugin, 1)) == 2 and all(c.endswith(full) for c in hud_cmds(plugin, 1))


def test_map_change_resends_the_panel(monkeypatch):
    # Join Match hides the panel on every map load (warmup map vote: no game_end, same fields).
    a, b = FakePlayer(1, "A"), FakePlayer(2, "B")
    plugin = hud_players(monkeypatch, a, b)
    plugin.game.state = "warmup"
    plugin.handle_player_spawn(a)
    plugin._hud_flush()
    plugin.handle_map("campgrounds", "ffa")
    plugin.handle_new_game()
    plugin._hud_flush()
    plugin.handle_player_loaded(a)
    plugin._hud_flush()
    full = panel((0, 0))[5:]
    # Spawn, new_game after the map reset, player_loaded (client unknown again): all full.
    assert len(hud_cmds(plugin, 1)) == 3 and all(c.endswith(full) for c in hud_cmds(plugin, 1))


def test_disconnect_forgets_the_client(monkeypatch):
    a = FakePlayer(1, "A")
    plugin = hud_players(monkeypatch, a)
    plugin.handle_player_spawn(a)
    plugin._hud_flush()
    plugin.handle_player_disconnect(a, "left")
    assert 1 not in gg.modhud_util.CLIENT


def hud_cmds(plugin, cid=None):
    return [cmd for c, cmd in plugin.engine.commands
            if (cid is None or c == cid) and cmd.startswith("cs ")]


def hud_players(monkeypatch, *players, hello=True, **cvars):
    """Players with our files (they said hello) unless hello=False."""
    plugin = ladder3(monkeypatch, **cvars)
    plugin.player_list.extend(players)
    if hello:
        for player in players:
            gg.modhud_util.client_command(int(player.id), "modhud 1")
    return plugin


def test_kill_sends_one_command_per_player_with_changed_fields(monkeypatch):
    a, b = FakePlayer(1, "A"), FakePlayer(2, "B")
    plugin = hud_players(monkeypatch, a, b)
    plugin.handle_kill(b, a, "ROCKET")
    plugin._hud_flush()
    assert len(hud_cmds(plugin)) == 2
    # First show carries every field: lines left by another server or plugin go.
    assert hud_cmds(plugin, 1)[0] == panel((0, 1))
    assert hud_cmds(plugin, 2)[0] == panel((0, 0))
    plugin._hud_flush()
    plugin.handle_kill(b, a, "ROCKET")  # A steps up
    plugin._hud_flush()
    assert hud_cmds(plugin, 1)[1] == panel((1, 0), ("mod_hud_l1", "mod_hud_l2"))
    assert len(hud_cmds(plugin, 2)) == 1  # nothing changed for B


def test_flush_without_events_sends_nothing(monkeypatch):
    a, b = FakePlayer(1, "A"), FakePlayer(2, "B")
    plugin = hud_players(monkeypatch, a, b)
    plugin.handle_kill(b, a, "ROCKET")
    plugin._hud_flush()
    plugin._hud_flush()
    assert len(hud_cmds(plugin)) == 2


def test_bots_get_no_panel(monkeypatch):
    bot, b = FakePlayer(0, "Bot", pid=5), FakePlayer(0, "Bot2", pid=6)
    plugin = hud_players(monkeypatch, bot, b)
    plugin.handle_kill(b, bot, "ROCKET")
    plugin._hud_flush()
    assert hud_cmds(plugin) == []


def test_other_players_steps_send_nothing_to_a_bystander(monkeypatch):
    a, b, c = FakePlayer(1, "A"), FakePlayer(2, "B"), FakePlayer(3, "C")
    plugin = hud_players(monkeypatch, a, b, c)
    plugin.handle_player_spawn(c)
    plugin._hud_flush()
    plugin._states["1"] = (0, 1)
    plugin.handle_kill(b, a, "ROCKET")  # A steps up and takes the lead
    plugin._hud_flush()
    assert len(hud_cmds(plugin, 3)) == 1


def test_spectator_and_game_end_clear(monkeypatch):
    a, b = FakePlayer(1, "A"), FakePlayer(2, "B")
    plugin = hud_players(monkeypatch, a, b)
    plugin.handle_kill(b, a, "ROCKET")
    plugin._hud_flush()
    a.team = "spectator"
    plugin.handle_team_switch(a, "free", "spectator")
    plugin._hud_flush()
    assert "mod_hud_on\\0" in hud_cmds(plugin, 1)[-1] and 1 not in plugin._hud_sent
    plugin.handle_game_end(False)
    plugin._hud_flush()
    assert "mod_hud_on\\0" in hud_cmds(plugin, 2)[-1] and plugin._hud_sent == {}
    assert len(hud_cmds(plugin, 1)) == 2  # A was already clear


def test_spectator_back_to_free_gets_full_panel(monkeypatch):
    a = FakePlayer(1, "A")
    plugin = hud_players(monkeypatch, a)
    plugin.handle_player_spawn(a)
    plugin._hud_flush()
    a.team = "spectator"
    plugin.handle_team_switch(a, "free", "spectator")
    plugin._hud_flush()
    a.team = "free"
    plugin.handle_player_spawn(a)
    plugin._hud_flush()
    # The blank emptied the lines, so turning the panel back on needs only the flag and line 1.
    assert hud_cmds(plugin, 1)[-1] == panel((0, 0), ("mod_hud_on", "mod_hud_l1", "mod_hud_l2"))


def test_never_shown_player_gets_no_clear(monkeypatch):
    a = FakePlayer(1, "A")
    plugin = hud_players(monkeypatch, a, qlx_gunGameEnabled="0")
    plugin.handle_player_spawn(a)
    plugin.handle_new_game()
    plugin._hud_flush()
    assert hud_cmds(plugin) == []


def test_hud_off_mid_match_clears_on_next_event(monkeypatch):
    a, b = FakePlayer(1, "A"), FakePlayer(2, "B")
    plugin = hud_players(monkeypatch, a, b)
    plugin.handle_kill(b, a, "ROCKET")
    plugin._hud_flush()
    plugin.settings["qlx_gunGameHud"] = "0"
    plugin.handle_player_spawn(a)
    plugin._hud_flush()
    assert "mod_hud_on\\0" in hud_cmds(plugin, 1)[-1]


def test_hud_off_keeps_centre_step_print(monkeypatch):
    a, b = FakePlayer(1, "A"), FakePlayer(2, "B")
    plugin = hud_players(monkeypatch, a, b, qlx_gunGameHud="0", qlx_gunGameStepNotify="center",
                         qlx_gunGameLeaderNotify="off")
    plugin._states["1"] = (0, 1)
    plugin.handle_kill(b, a, "ROCKET")
    plugin._hud_flush()
    run_delays(plugin)
    assert a.centers == ["Step 2/3: ^3LG^7 (0/1)"] and hud_cmds(plugin) == []
    plugin.settings["qlx_gunGameHud"] = "1"
    plugin.handle_kill(b, a, "LIGHTNING")  # last step: the leader channel is off
    run_delays(plugin)
    assert a.centers == ["Step 2/3: ^3LG^7 (0/1)"]


def test_disconnect_clears_at_once(monkeypatch):
    a, b = FakePlayer(1, "A"), FakePlayer(2, "B")
    plugin = hud_players(monkeypatch, a, b)
    plugin.handle_kill(b, a, "ROCKET")
    plugin._hud_flush()
    plugin.handle_player_disconnect(a, "left")
    assert "mod_hud_on\\0" in hud_cmds(plugin, 1)[-1] and 1 not in plugin._hud_sent


def test_send_to_a_loading_client_is_retried_in_full_when_loaded(monkeypatch):
    a, b = FakePlayer(1, "A"), FakePlayer(2, "B")
    plugin = hud_players(monkeypatch, a, b)
    plugin.handle_kill(b, a, "ROCKET")
    plugin._hud_flush()
    plugin.engine.loading.add(1)  # map change: A is loading when new_game flushes
    plugin.handle_new_game()
    plugin._hud_flush()
    assert len(hud_cmds(plugin, 1)) == 1
    plugin.engine.loading.discard(1)
    plugin.handle_player_loaded(a)
    plugin._hud_flush()
    assert hud_cmds(plugin, 1)[-1].endswith(
        panel((0, 0))[5:])


def test_blank_to_a_loading_client_is_retried(monkeypatch):
    a = FakePlayer(1, "A")
    plugin = hud_players(monkeypatch, a)
    plugin.handle_player_spawn(a)
    plugin._hud_flush()
    plugin.engine.loading.add(1)
    plugin.settings["qlx_gunGameEnabled"] = "0"
    plugin.handle_new_game()
    plugin._hud_flush()
    plugin.engine.loading.discard(1)
    plugin.handle_player_loaded(a)
    plugin._hud_flush()
    assert "mod_hud_on\\0" in hud_cmds(plugin, 1)[-1] and plugin._hud_sent == {}
