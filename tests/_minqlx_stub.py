"""One stand-in for minqlxtended so plugin modules import without a server."""
import importlib
import sys
import types
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parent.parent


def _identity(fn):
    return fn


def _noop(*_args, **_kwargs):
    return None


def minqlx_stub() -> types.ModuleType:
    stub = types.ModuleType("minqlxtended")
    stub.Plugin = object
    stub.Priority = SimpleNamespace(HIGHEST=0, HIGH=1, NORMAL=2, LOW=3, LOWEST=4)
    stub.Return = SimpleNamespace(NONE=0, STOP=1, STOP_EVENT=2, STOP_ALL=3, USAGE=4)
    stub.thread = _identity
    stub.next_frame = _identity

    def delay(seconds):
        return _identity

    stub.delay = delay
    stub.EngineStateError = type("EngineStateError", (RuntimeError,), {})
    stub.NonexistentPlayerError = type("NonexistentPlayerError", (Exception,), {})
    stub.console_print = _noop
    stub.console_command = _noop
    stub.owner = lambda: "0"
    stub.EVENT_DISPATCHERS = {}
    return stub


def import_plugin(name: str) -> types.ModuleType:
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    previous = sys.modules.get("minqlxtended")
    sys.modules["minqlxtended"] = minqlx_stub()
    try:
        sys.modules.pop(name, None)
        module = importlib.import_module(name)
    finally:
        if previous is not None:
            sys.modules["minqlxtended"] = previous
        else:
            sys.modules.pop("minqlxtended", None)
    return module


def bare_instance(cls: type, **attrs) -> object:
    obj = object.__new__(cls)
    for key, value in attrs.items():
        setattr(obj, key, value)
    return obj
