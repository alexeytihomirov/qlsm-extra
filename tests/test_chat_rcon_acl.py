import pytest

from _minqlx_stub import import_plugin


@pytest.fixture(params=["chat_rcon_acl", "chat_rcon"])
def acl(request):
    return import_plugin(request.param)


DENIED = ("multi", "denied: one command per line", "")


def test_semicolon_is_rejected_for_admins(acl):
    assert acl.evaluate_acl(enabled=True, perm_level=5, cmd_line="pause; exec x.cfg") == DENIED


def test_semicolon_is_rejected_for_referees(acl):
    assert acl.evaluate_acl(enabled=True, perm_level=3, cmd_line="pause;exec x.cfg") == DENIED


def test_semicolon_is_rejected_from_the_console(acl):
    assert acl.evaluate_acl(enabled=True, perm_level=None, cmd_line="map campgrounds; quit", player_is_none=True) == DENIED


def test_line_breaks_are_rejected(acl):
    for line in ("pause\nquit", "pause\rquit"):
        assert acl.evaluate_acl(enabled=True, perm_level=5, cmd_line=line) == DENIED


def test_single_commands_still_run(acl):
    assert acl.evaluate_acl(enabled=True, perm_level=3, cmd_line="pause") == ("ok", "ok", "pause")
    assert acl.evaluate_acl(enabled=True, perm_level=5, cmd_line="map bloodrun duel") == ("ok", "ok", "map bloodrun duel")


def test_disabled_wins_over_the_separator_check(acl):
    assert acl.evaluate_acl(enabled=False, perm_level=5, cmd_line="pause; quit") == ("disabled", "chat-rcon disabled", "")


def test_both_copies_fold_case_and_show_the_same_usage(acl):
    assert acl.parse_csv("Pause,MAP", ()) == {"pause", "map"}
    assert acl.normalize_command_line("/MAP Bloodrun") == ("MAP Bloodrun", "map", "bloodrun")
    assert acl.evaluate_acl(enabled=True, perm_level=5, cmd_line="") == ("usage", "usage: !rcon <command> [args...]", "")
    assert acl.RESULT_MULTI_COMMAND == "multi"
