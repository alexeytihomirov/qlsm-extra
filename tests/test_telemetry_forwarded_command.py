"""stream_telemetry_unified.forwarded_command(): which console commands reach the stats hub."""
import sys
import types
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# The plugin imports minqlxtended/minqlx at module level; only the pure helper is tested here.
_stub = mock.MagicMock(name="minqlxtended")
_stub.Plugin = object
_stub.EngineStateError = RuntimeError
# Another test may have left a thinner stub in place: use ours for this import only.
_previous = sys.modules.get("minqlxtended")
sys.modules["minqlxtended"] = _stub
try:
    from stream_telemetry_unified import forwarded_command, should_forward_say  # noqa: E402
finally:
    if _previous is not None:
        sys.modules["minqlxtended"] = _previous

pytestmark = pytest.mark.standalone


def test_referee_and_pause_commands_are_forwarded_as_typed():
    assert forwarded_command("!call cyber loh") == "!call cyber loh"
    assert forwarded_command("  !CALL  ") == "!CALL"
    assert forwarded_command("!pause") == "!pause"
    assert forwarded_command("!timeout") == "!timeout"


def test_everything_else_stays_on_the_server():
    for cmd in ("!rcon map bloodrun duel", "!callvote map x", "!calls", "say !call x", "team a", "", None):
        assert forwarded_command(cmd) is None, cmd


def test_rcon_chat_lines_are_not_forwarded():
    for text in ("!rcon g_password secret", "!RCON map bloodrun", '"!rcon g_password secret"', "/!rcon quit", "  !rcon", "!rcon"):
        assert should_forward_say(text) is False, text


def test_other_chat_lines_are_forwarded():
    for text in ("gg", "!call ref please", "!rconx", "about !rcon", "", None):
        assert should_forward_say(text) is True, text


def test_team_chat_rcon_is_not_queued():
    from _minqlx_stub import import_plugin, bare_instance
    st = import_plugin("stream_telemetry_unified")
    queued = []
    p = bare_instance(st.stream_telemetry_unified, _session_enabled=lambda: True,
                      _enqueue_session=lambda kind, player, text=None, meta=None: queued.append((kind, text)))
    p.on_client_command_chat(object(), "say_team !rcon g_password secret")
    p.on_client_command_chat(object(), 'say "!rcon g_password secret"')
    p.on_client_command_chat(object(), "say gg")
    assert queued == [("say", "gg")]
