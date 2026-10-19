"""demo-stream: with the addon on for an instance, sv_demoStream* (the token
included) travel as `+set` launch args from the addon's own state instead of
living in server.cfg, so a preset saved from the instance does not carry them
and loading one does not wipe them.
"""
import importlib
from unittest.mock import Mock, patch

import pytest

from ui import db
from ui.models import InstanceStatus, QLInstance
from test_addon_demo_stream_panel import (  # noqa: F401
    GET, PUT, URL, WIRED, _cfg, _hub, addon_id, auth, off, queued, streaming,
)


def _switch_on(app, iid):
    with app.app_context():
        from ui.addons import get_addon
        settings = get_addon('demo-stream').ctx.settings
        host_id = db.session.get(QLInstance, iid).host_id
        settings.set_enabled('global', 0, True)
        settings.set_enabled('host', host_id, True)
        settings.set_enabled('instance', iid, True)


def _launch_args(app, iid):
    with app.app_context():
        from ui.addons import dispatch
        return dispatch('instance.launch_args', iid, iid)


def test_launch_args_carry_the_stored_wiring(app, streaming, off):
    _switch_on(app, streaming)
    _switch_on(app, off)
    assert _launch_args(app, streaming) == [
        '+set sv_demoStream "1"', '+set sv_demoStreamHost "127.0.0.1"',
        '+set sv_demoStreamPort "27999"', '+set sv_demoStreamToken "stream-token"']
    assert _launch_args(app, off) == ['+set sv_demoStream "0"']


def test_no_launch_args_while_the_addon_is_off_for_the_instance(app, streaming):
    assert _launch_args(app, streaming) == []


def test_disable_strips_server_cfg(app, streaming, monkeypatch):
    ops = importlib.import_module('qlsm_addon_demo_stream.instance_ops')
    _switch_on(app, streaming)
    with app.app_context():
        db.session.get(QLInstance, streaming).status = InstanceStatus.CONFIGURING
        db.session.commit()
    import ui.tasks
    monkeypatch.setattr(ui.tasks, 'enqueue_task', lambda *a, **k: Mock(id='job-9'))
    with app.app_context():
        ok, message = ops.disable_instance_demo_stream_logic(streaming, previous_status='running')
    assert ok, message
    assert _cfg(app, streaming).read_text(encoding='utf-8') == 'set sv_hostname "duel"\n'
    assert _launch_args(app, streaming) == ['+set sv_demoStream "0"']


@pytest.mark.parametrize('cfg, queues', [(WIRED, True), ('set sv_hostname "duel"\n', False)])
def test_save_moves_leftover_cvars_out_of_server_cfg(app, client, auth, streaming, queued, cfg, queues):
    _switch_on(app, streaming)
    _cfg(app, streaming).write_text(cfg, encoding='utf-8')
    with patch(GET, return_value=_hub()), patch(PUT):
        resp = client.put(f'{URL}/instances/{streaming}',
                          json={'enabled': True, 'delay_sec': ''}, headers=auth)
    if queues:
        assert resp.status_code == 202, resp.get_json()
        assert len(queued) == 1
    else:
        assert resp.status_code == 200, resp.get_json()
        assert queued == []
