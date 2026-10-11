"""The demo-stream addon's instance enable flow resets the instance status
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
    return 'demo-stream'


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
    ops = importlib.import_module('qlsm_addon_demo_stream.instance_ops')
    iid = _instance(app, InstanceStatus.CONFIGURING)
    with app.app_context():
        ok, message = ops.enable_instance_demo_stream_logic(iid, previous_status=previous)
    assert ok is False and message.startswith('Configure the demo-stream relay host/port')
    assert _status(app, iid) == expected


def test_unreachable_stats_hub_restores_the_previous_status(app, monkeypatch):
    ops = importlib.import_module('qlsm_addon_demo_stream.instance_ops')
    monkeypatch.setattr(ops, 'is_relay_configured', lambda: True)
    monkeypatch.setattr(ops, 'is_stats_hub_configured_for_host', lambda host_id: True)
    monkeypatch.setattr(ops, 'is_host_tunnel_enabled', lambda host_id: True)
    monkeypatch.setattr(ops, '_resolve_server_id', lambda instance, host_id: 7)
    monkeypatch.setattr(ops, 'get_instance_demo_stream_token', lambda instance_id: 'tok')

    def down(*a, **k):
        raise requests.ConnectionError('hub down')
    monkeypatch.setattr(ops, '_register_route', down)
    iid = _instance(app, InstanceStatus.CONFIGURING)
    with app.app_context():
        assert ops.enable_instance_demo_stream_logic(iid, previous_status='running') == (
            False, 'Could not register the demo-stream route with stats-hub: hub down')
    assert _status(app, iid) == InstanceStatus.RUNNING


def test_enable_endpoint_passes_the_previous_status(app, client, monkeypatch):
    settings = importlib.import_module('qlsm_addon_demo_stream.settings')
    monkeypatch.setattr(settings, 'is_relay_configured', lambda: True)
    monkeypatch.setattr(settings, 'is_host_tunnel_enabled', lambda host_id: True)
    import ui.task_lock
    import ui.tasks
    monkeypatch.setattr(ui.task_lock, 'acquire_lock', lambda *a, **k: True)
    calls = []
    monkeypatch.setattr(ui.tasks, 'enqueue_task', lambda task, *args, **kwargs: calls.append((args, kwargs)))
    make_user(app, 'op', 'pw')
    iid = _instance(app, InstanceStatus.RUNNING)
    resp = client.post(f'/api/addons/demo-stream/instances/{iid}/enable', json={'enabled': True}, headers=auth_headers(app, 'op'))
    assert resp.status_code == 202
    assert calls[0][0] == (iid,) and calls[0][1]['previous_status'] == 'running'
    assert _status(app, iid) == InstanceStatus.CONFIGURING
