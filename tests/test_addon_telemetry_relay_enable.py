"""The telemetry-relay addon's instance enable flow resets the instance status
when the background task fails a step.

The endpoint sets the instance to CONFIGURING and queues the task; a step
that returns (False, msg) instead of raising never reaches the task runner's
on_failure handler, so the logic itself has to put the status back. It puts
back the status the endpoint saw before going CONFIGURING, the same way core
passes previous_status to apply_instance_config.
"""
import importlib

import pytest
import requests

from ui import db
from ui.models import Host, HostStatus, InstanceStatus, QLInstance
from conftest import auth_headers, make_user


@pytest.fixture
def addon_id():
    return 'telemetry-relay'


def _instance(app, status):
    with app.app_context():
        host = Host(name='germany', ip_address='10.0.0.1', provider='vultr', status=HostStatus.ACTIVE)
        db.session.add(host)
        db.session.flush()
        inst = QLInstance(name='duel srv', port=27960, hostname='duel', host_id=host.id, status=status)
        db.session.add(inst)
        db.session.commit()
        return inst.id


def _status(app, instance_id):
    with app.app_context():
        return db.session.get(QLInstance, instance_id).status


@pytest.mark.parametrize('previous, expected', [
    ('running', InstanceStatus.RUNNING),
    ('stopped', InstanceStatus.STOPPED),
    (None, InstanceStatus.ERROR),
])
def test_failed_enable_restores_the_previous_status(app, previous, expected):
    ops = importlib.import_module('qlsm_addon_telemetry_relay.instance_ops')
    iid = _instance(app, InstanceStatus.CONFIGURING)
    with app.app_context():
        ok, message = ops.enable_instance_telemetry_logic(iid, previous_status=previous)
    assert ok is False and message.startswith('Configure the stats-hub URL')
    assert _status(app, iid) == expected


def test_unreachable_stats_hub_restores_the_previous_status(app, monkeypatch):
    ops = importlib.import_module('qlsm_addon_telemetry_relay.instance_ops')
    monkeypatch.setattr(ops, 'is_stats_hub_configured_for_host', lambda host_id: True)
    monkeypatch.setattr(ops, 'is_relay_enabled', lambda host_id: True)
    monkeypatch.setattr(ops, 'get_instance_server_id', lambda instance_id: None)

    def down(*a, **k):
        raise requests.ConnectionError('hub down')
    monkeypatch.setattr(ops, 'reserve_server_id', down)
    iid = _instance(app, InstanceStatus.CONFIGURING)
    with app.app_context():
        assert ops.enable_instance_telemetry_logic(iid, previous_status='running') == (
            False, 'Could not reserve a server_id from stats-hub: hub down')
    assert _status(app, iid) == InstanceStatus.RUNNING


def test_enable_endpoint_passes_the_previous_status(app, client, monkeypatch):
    settings = importlib.import_module('qlsm_addon_telemetry_relay.settings')
    monkeypatch.setattr(settings, 'is_relay_enabled', lambda host_id: True)
    monkeypatch.setattr(settings, 'is_stats_hub_configured_for_host', lambda host_id: True)
    import ui.task_lock
    import ui.tasks
    monkeypatch.setattr(ui.task_lock, 'acquire_lock', lambda *a, **k: True)
    calls = []
    monkeypatch.setattr(ui.tasks, 'enqueue_task', lambda task, *args, **kwargs: calls.append((args, kwargs)))
    make_user(app, 'op', 'pw')
    iid = _instance(app, InstanceStatus.RUNNING)
    resp = client.post(f'/api/addons/telemetry-relay/instances/{iid}/enable', json={}, headers=auth_headers(app, 'op'))
    assert resp.status_code == 202
    assert calls[0][0] == (iid,) and calls[0][1]['previous_status'] == 'running'
    assert _status(app, iid) == InstanceStatus.CONFIGURING


def test_sync_warns_when_another_instance_already_uses_the_server_id(app, tmp_path, monkeypatch):
    """Two instances on one stats-hub id mix their matches under one server-<id>;
    the config sync keeps working but tells the operator in the instance log."""
    ops = importlib.import_module('qlsm_addon_telemetry_relay.instance_ops')
    settings = importlib.import_module('qlsm_addon_telemetry_relay.settings')
    pushes = []
    monkeypatch.setattr(ops, 'push_relay_config_logic', lambda host_id: pushes.append(host_id))
    monkeypatch.chdir(tmp_path)

    with app.app_context():
        host = Host(name='dup-host', ip_address='10.0.0.9', provider='vultr', status=HostStatus.ACTIVE)
        db.session.add(host)
        db.session.flush()
        first = QLInstance(name='first', port=27960, hostname='a', host_id=host.id, status=InstanceStatus.RUNNING)
        second = QLInstance(name='second', port=27961, hostname='b', host_id=host.id, status=InstanceStatus.RUNNING)
        db.session.add_all([first, second])
        db.session.commit()
        settings.set_instance_server_id(first.id, 40)
        db.session.commit()

        cfg_dir = tmp_path / 'configs' / 'dup-host' / str(second.id)
        cfg_dir.mkdir(parents=True)
        (cfg_dir / 'server.cfg').write_text(
            'set qlx_statsHubUnifiedEnabled "1"\nset qlx_statsHubServerId "40"\n')

        ops.sync_instance_server_id_from_config(second)

        db.session.refresh(second)
        assert settings.get_instance_server_id(second.id) == 40
        assert f'also used by instance(s) {first.id}' in second.logs
        assert pushes == [host.id]
        assert settings.instance_ids_sharing_server_id(40, exclude_instance_id=second.id) == [first.id]
        assert settings.instance_ids_sharing_server_id(41) == []


def test_sync_does_not_warn_for_a_unique_server_id(app, tmp_path, monkeypatch):
    ops = importlib.import_module('qlsm_addon_telemetry_relay.instance_ops')
    monkeypatch.setattr(ops, 'push_relay_config_logic', lambda host_id: None)
    monkeypatch.chdir(tmp_path)

    with app.app_context():
        host = Host(name='uniq-host', ip_address='10.0.0.8', provider='vultr', status=HostStatus.ACTIVE)
        db.session.add(host)
        db.session.flush()
        inst = QLInstance(name='only', port=27960, hostname='a', host_id=host.id, status=InstanceStatus.RUNNING)
        db.session.add(inst)
        db.session.commit()
        cfg_dir = tmp_path / 'configs' / 'uniq-host' / str(inst.id)
        cfg_dir.mkdir(parents=True)
        (cfg_dir / 'server.cfg').write_text(
            'set qlx_statsHubUnifiedEnabled "1"\nset qlx_statsHubServerId "55"\n')

        ops.sync_instance_server_id_from_config(inst)

        db.session.refresh(inst)
        assert 'also used by' not in (inst.logs or '')
