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
    from stream_telemetry_unified import forwarded_command  # noqa: E402
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
