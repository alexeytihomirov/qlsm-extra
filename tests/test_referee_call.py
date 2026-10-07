"""referee_call.decide(): the reply-or-wait rule, without minqlx."""
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# The plugin imports minqlxtended/minqlx at module level; only decide() is tested here.
_stub = types.ModuleType("minqlxtended")
_stub.Plugin = object
sys.modules.setdefault("minqlxtended", _stub)

from referee_call import decide  # noqa: E402

pytestmark = pytest.mark.standalone


def test_first_call_is_notified_and_time_stored():
    assert decide(None, 100.0) == ("Referees have been notified.", 100.0)


def test_call_10s_later_waits_and_keeps_stored_time():
    assert decide(100.0, 110.0) == ("Please wait 50 s before calling again.", 100.0)


def test_call_61s_later_is_notified_again():
    assert decide(100.0, 161.0) == ("Referees have been notified.", 161.0)


def test_call_at_exactly_60s_is_notified():
    assert decide(100.0, 160.0) == ("Referees have been notified.", 160.0)


def test_fractional_remaining_rounds_up():
    assert decide(100.0, 159.5)[0] == "Please wait 1 s before calling again."
