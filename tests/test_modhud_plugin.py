"""modhud: !hud / !hudicons and the resend on player_loaded."""
from types import SimpleNamespace

import pytest

from tests._minqlx_stub import bare_instance, import_plugin

pytestmark = pytest.mark.standalone

mh = import_plugin("modhud")
mu = import_plugin("modhud_util")
USAGE = "usage"


@pytest.fixture(autouse=True)
def clean_clients():
    mh.modhud_util.CLIENT.clear()
    yield
    mh.modhud_util.CLIENT.clear()


class FakePlayer:
    def __init__(self, sid, pid):
        self.steam_id = sid
        self.id = pid
        self.tells = []

    def tell(self, msg):
        self.tells.append(msg)


def make_plugin(monkeypatch, *players):
    commands = []
    engine = SimpleNamespace(
        CS_SYSTEMINFO=1,
        configstring=lambda index, cached=True: "\\sv_pure\\1",
        send_server_command=lambda cid, cmd: commands.append((cid, cmd)) or True,
        Return=SimpleNamespace(USAGE=USAGE),
    )
    monkeypatch.setattr(mh, "minqlx", engine)
    plugin = bare_instance(mh.modhud, _lines=["", "", ""], _sent={}, players=lambda: list(players))
    plugin.commands = commands
    return plugin


def cmds(plugin, cid=None):
    return [cmd for c, cmd in plugin.commands if cid is None or c == cid]


def test_hud_line_goes_to_every_human(monkeypatch):
    a, b, bot = FakePlayer(11, 1), FakePlayer(12, 2), FakePlayer(0, 3)
    plugin = make_plugin(monkeypatch, a, b, bot)
    assert plugin.cmd_hud(a, ["!hud", "2", "hello", "{rl}"], None) is None
    assert len(cmds(plugin)) == 2 and cmds(plugin, 3) == []
    assert cmds(plugin, 1)[0] == ('cs 1 "\\sv_pure\\1\\mod_hud_on\\1\\mod_hud_l1\\'
                                  '\\mod_hud_l2\\hello \\mod_hud_l3\\"')
    plugin.cmd_hud(a, ["!hud", "1", "top"], None)
    assert cmds(plugin, 1)[-1] == 'cs 1 "\\sv_pure\\1\\mod_hud_l1\\top"'


def test_hud_clear(monkeypatch):
    a, b = FakePlayer(11, 1), FakePlayer(12, 2)
    plugin = make_plugin(monkeypatch, a, b)
    plugin.cmd_hud(a, ["!hud", "1", "x"], None)
    plugin.cmd_hud(a, ["!hud", "clear"], None)
    assert cmds(plugin, 1)[-1] == 'cs 1 "\\sv_pure\\1\\mod_hud_on\\0\\mod_hud_l1\\"'
    assert plugin._lines == ["", "", ""] and plugin._sent == {}


@pytest.mark.parametrize("msg", [["!hud"], ["!hud", "4", "x"], ["!hud", "1"], ["!hud", "a", "x"]])
def test_hud_bad_args(monkeypatch, msg):
    a = FakePlayer(11, 1)
    plugin = make_plugin(monkeypatch, a)
    assert plugin.cmd_hud(a, msg, None) == USAGE
    assert cmds(plugin) == []


def test_player_loaded_gets_the_lines(monkeypatch):
    a, b = FakePlayer(11, 1), FakePlayer(12, 2)
    plugin = make_plugin(monkeypatch, a)
    plugin.cmd_hud(a, ["!hud", "3", "z"], None)
    plugin.handle_player_loaded(b)
    assert cmds(plugin, 2) == ['cs 1 "\\sv_pure\\1\\mod_hud_on\\1\\mod_hud_l1\\\\mod_hud_l2\\\\mod_hud_l3\\z"']


def test_map_change_resends_to_everyone(monkeypatch):
    a = FakePlayer(11, 1)
    plugin = make_plugin(monkeypatch, a)
    plugin.cmd_hud(a, ["!hud", "1", "x"], None)
    plugin.handle_map("campgrounds", "ffa")
    assert len(cmds(plugin, 1)) == 2 and cmds(plugin, 1)[1] == cmds(plugin, 1)[0]


def test_map_change_without_lines_sends_nothing(monkeypatch):
    a = FakePlayer(11, 1)
    plugin = make_plugin(monkeypatch, a)
    plugin.handle_map("campgrounds", "ffa")
    assert cmds(plugin) == []


def test_player_loaded_without_lines_sends_nothing(monkeypatch):
    a = FakePlayer(11, 1)
    plugin = make_plugin(monkeypatch, a)
    plugin.handle_player_loaded(a)
    assert cmds(plugin) == []


def test_disconnect_forgets(monkeypatch):
    a = FakePlayer(11, 1)
    plugin = make_plugin(monkeypatch, a)
    plugin.cmd_hud(a, ["!hud", "1", "x"], None)
    plugin.handle_player_disconnect(a, "left")
    assert plugin._sent == {} and 1 not in mh.modhud_util.CLIENT


def test_hudicons_lists_every_token(monkeypatch):
    a = FakePlayer(11, 1)
    plugin = make_plugin(monkeypatch, a)
    plugin.cmd_hudicons(a, ["!hudicons"], None)
    text = " ".join(a.tells)
    for token, char in mu.TOKENS.items():
        assert "{%s}" % token in text and char in text
    assert all(len(t) < 150 for t in a.tells)
    assert cmds(plugin) == []
