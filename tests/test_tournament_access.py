"""tournament_access: the roster decides access before the specbot name rule."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _minqlx_stub import import_plugin  # noqa: E402

ta = import_plugin("tournament_access")

pytestmark = pytest.mark.standalone


@pytest.mark.parametrize("role, active, specbot, lobby, expected", [
    (None, True, True, False, "kick"),       # unlisted StreamSpec on a closed server
    ("player", True, True, False, "spec"),
    ("caster", True, False, False, "spec"),
    ("player", True, False, True, "spec"),
    ("player", True, False, False, "allow"),
    (None, True, False, False, "kick"),
    (None, False, True, False, "spec"),      # roster not enforced: specbot still spectates
    (None, False, False, True, "allow"),     # roster not enforced: lobby does not force spec (as today)
    (None, False, False, False, "allow"),
])
def test_decide_loaded(role, active, specbot, lobby, expected):
    assert ta.decide_loaded(role, active, specbot, lobby) == expected


@pytest.mark.parametrize("role, active, specbot, lobby, team, expected", [
    (None, True, True, False, "red", "deny_roster"),
    ("player", True, True, False, "red", "deny_specbot"),
    ("player", True, True, False, "spectator", "allow"),
    (None, False, True, False, "blue", "deny_specbot"),
    (None, True, False, False, "spectator", "deny_roster"),
    ("player", True, False, True, "free", "deny_lobby"),
    ("caster", True, False, False, "red", "deny_caster"),
    ("player", True, False, False, "red", "allow"),
    (None, False, False, False, "red", "allow"),
])
def test_decide_team_switch(role, active, specbot, lobby, team, expected):
    assert ta.decide_team_switch(role, active, specbot, lobby, team) == expected


def test_plugin_does_not_read_the_dev_auth_open_cvar():
    source = (Path(__file__).resolve().parent.parent / "tournament_access.py").read_text(encoding="utf-8")
    assert "qlx_devAuthOpen" not in source
