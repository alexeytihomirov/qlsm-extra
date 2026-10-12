"""qlmatch_packer: argv builder, cvar defaults and the launch path, without a server."""
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _minqlx_stub import bare_instance, import_plugin  # noqa: E402

pytestmark = pytest.mark.standalone


@pytest.fixture(scope="module")
def mod():
    return import_plugin("qlmatch_packer")


@pytest.fixture(scope="module")
def cmd():
    return import_plugin("qlmatch_packer_cmd")


def test_packer_command_minimal(cmd):
    assert cmd.packer_command("node", "/p/pack.mjs", "/d", "m1") == [
        "node", "/p/pack.mjs", "--dir", "/d", "--match-id", "m1"]


def test_packer_command_optional_values_only_when_set(cmd):
    out = cmd.packer_command("node", "/p/pack.mjs", "/d", "m1", map_name="campgrounds", name_template="{map}")
    assert out[-4:] == ["--map", "campgrounds", "--name-template", "{map}"]


def test_packer_command_has_no_delivery_argument(cmd):
    out = cmd.packer_command("node", "/p/pack.mjs", "/d", "m1", name_template="x")
    assert not any("rclone" in a for a in out)


def test_plugin_class_matches_module_name(mod):
    assert hasattr(mod, "qlmatch_packer")


class _Logger:
    def __init__(self):
        self.lines = []

    def warning(self, *a):
        self.lines.append(("warning", a))

    def info(self, *a):
        self.lines.append(("info", a))


def _plugin(mod, cvars):
    return bare_instance(mod.qlmatch_packer, logger=_Logger(), get_cvar=lambda k: cvars.get(k, ""))


def test_missing_packer_returns_false(mod, tmp_path):
    p = _plugin(mod, {"qlx_qlmatchPackerPath": str(tmp_path / "nope.mjs")})
    assert p._run_external_packer(str(tmp_path), "m1") is False


def test_packer_run_logs_into_match_log_and_reports_success(mod, tmp_path, monkeypatch):
    packer = tmp_path / "pack.mjs"
    packer.write_text("")
    seen = {}

    def fake_run(cmd, stdout, stderr, timeout):
        seen["cmd"] = cmd
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(mod.shutil, "which", lambda n: "/usr/bin/node")
    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    p = _plugin(mod, {"qlx_qlmatchPackerPath": str(packer), "qlx_qlmatchNameTemplate": " {map} "})
    assert p._run_external_packer(str(tmp_path), "m1") is True
    assert seen["cmd"] == ["/usr/bin/node", str(packer), "--dir", str(tmp_path), "--match-id", "m1",
                           "--name-template", "{map}"]
    assert os.path.exists(tmp_path / "m1.packer.log")


def test_exit_5_means_packer_never_ran(mod, tmp_path, monkeypatch):
    packer = tmp_path / "pack.mjs"
    packer.write_text("")
    monkeypatch.setattr(mod.shutil, "which", lambda n: "/usr/bin/node")
    monkeypatch.setattr(mod.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=5))
    p = _plugin(mod, {"qlx_qlmatchPackerPath": str(packer)})
    assert p._run_external_packer(str(tmp_path), "m1") is False
