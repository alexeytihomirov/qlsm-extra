"""stats_hub_pause: a pause the engine reports ends when the engine says so."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import stats_hub_pause as pause  # noqa: E402

pytestmark = pytest.mark.standalone


class _Db:
    def has_permission(self, player, level):
        return True


class _Plugin:
    def __init__(self):
        self.cvars = {}
        self.game = None
        self.db = _Db()

    def get_cvar(self, name):
        return self.cvars.get(name)


@pytest.fixture
def plugin():
    pause.reset_pause_state()
    yield _Plugin()
    pause.reset_pause_state()


def test_an_engine_pause_ends_shortly_after_the_engine_stops_reporting_it(plugin):
    plugin.cvars["sv_paused"] = "1"  # a player's timeout
    assert pause.paused_active(plugin, now=100.0)
    plugin.cvars["sv_paused"] = "0"  # timein
    assert pause.paused_active(plugin, now=101.0)  # inside the release window
    assert not pause.paused_active(plugin, now=102.5)
    assert not pause.pause_latch_active()


def test_a_command_pause_stays_until_unpause(plugin):
    pause.note_client_command("!pause", player=object(), plugin=plugin)
    assert pause.paused_active(plugin, now=100.0) and pause.paused_active(plugin, now=500.0)
    pause.note_client_command("!unpause", player=object(), plugin=plugin)
    assert not pause.paused_active(plugin, now=501.0)


def test_reset_clears_everything(plugin):
    plugin.cvars["sv_paused"] = "1"
    pause.note_client_command("!pause", player=object(), plugin=plugin)
    assert pause.paused_active(plugin, now=100.0)
    plugin.cvars["sv_paused"] = "0"
    pause.reset_pause_state()
    assert not pause.paused_active(plugin, now=100.1)
