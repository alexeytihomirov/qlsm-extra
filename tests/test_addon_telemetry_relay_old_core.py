"""telemetry-relay 1.10.1: the addon loads on a qlsm core whose ansible_runner
has no run_host_ansible_adhoc (the deployed fork build of 2026-10-28).

A module-level import of it broke the whole addon there: the Stats Hub panel
failed to load and the instance.launch_args hook failed, so restarted
instances lost their stats-hub cvars. Only the relay health check needs it,
so it is imported there, and that check reports an error instead of raising.
"""
import importlib
import sys

import pytest

from ui import db
from ui.models import QLInstance
import ui.task_logic.ansible_runner as ansible_runner
from test_addon_telemetry_relay_panel import _make_instance, addon_id  # noqa: F401

PKG = 'qlsm_addon_telemetry_relay'


@pytest.fixture
def old_core(app, monkeypatch):
    """ansible_runner without run_host_ansible_adhoc, and the addon's ops
    modules dropped from sys.modules so the next import runs them again."""
    monkeypatch.delattr(ansible_runner, 'run_host_ansible_adhoc', raising=False)
    for name in ('relay_ops', 'instance_ops'):
        monkeypatch.delitem(sys.modules, f'{PKG}.{name}', raising=False)


def test_ops_modules_import_without_run_host_ansible_adhoc(old_core):
    relay_ops = importlib.import_module(f'{PKG}.relay_ops')
    instance_ops = importlib.import_module(f'{PKG}.instance_ops')
    assert relay_ops.push_relay_config_logic
    assert instance_ops.enable_instance_telemetry_logic


def test_relay_health_check_reports_the_missing_core_function(app, old_core):
    iid = _make_instance(app, relay=True)
    relay_ops = importlib.import_module(f'{PKG}.relay_ops')
    with app.app_context():
        host_id = db.session.get(QLInstance, iid).host_id
        result = relay_ops.get_relay_status_logic(host_id)
    assert result['enabled'] is True
    assert result['reachable'] is False
    assert 'run_host_ansible_adhoc' in result['error']
