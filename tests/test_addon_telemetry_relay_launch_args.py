"""telemetry-relay: with the addon on for an instance, qlx_statsHub* travel as
`+set` launch args from the addon's own state instead of living in server.cfg,
so a preset saved from the instance does not carry them and loading one does
not wipe them.
"""
import pytest

from ui import db
from ui.models import InstanceStatus, QLInstance
from test_addon_telemetry_relay_panel import (  # noqa: F401
    ON_CFG, URL, _cfg_text, _make_instance, _ops, _settings, addon_id, auth, in_tmp, queued,
)


def _switch_on(app, iid):
    """The addon on at every scope for the instance, so core dispatches its
    instance.launch_args."""
    with app.app_context():
        from ui.addons import get_addon
        settings = get_addon('telemetry-relay').ctx.settings
        host_id = db.session.get(QLInstance, iid).host_id
        settings.set_enabled('global', 0, True)
        settings.set_enabled('host', host_id, True)
        settings.set_enabled('instance', iid, True)


def _launch_args(app, iid):
    with app.app_context():
        from ui.addons import dispatch
        return dispatch('instance.launch_args', iid, iid)


def test_launch_args_carry_the_stored_server_id(app):
    on = _make_instance(app, server_id=12)
    off = _make_instance(app)
    _switch_on(app, on)
    _switch_on(app, off)
    assert _launch_args(app, on) == [
        '+set qlx_statsHubUnifiedEnabled "1"', '+set qlx_statsHubServerId "12"']
    assert _launch_args(app, off) == ['+set qlx_statsHubUnifiedEnabled "0"']


def test_no_launch_args_while_the_addon_is_off_for_the_instance(app):
    iid = _make_instance(app, ON_CFG, server_id=12)
    assert _launch_args(app, iid) == []


def test_enable_and_disable_strip_server_cfg(app, queued, monkeypatch):
    ops = _ops()
    monkeypatch.setattr(ops, 'push_relay_config_logic', lambda host_id: True)
    iid = _make_instance(app, ON_CFG + 'set qlx_statsHubUrl "http://old"\n', server_id=12,
                         status=InstanceStatus.CONFIGURING)
    _switch_on(app, iid)

    with app.app_context():
        ok, message = ops.enable_instance_telemetry_logic(iid, previous_status='running')
        assert ok, message
    assert _cfg_text(app, iid) == 'set sv_hostname "duel"\n'
    assert _launch_args(app, iid)[0] == '+set qlx_statsHubUnifiedEnabled "1"'

    with app.app_context():
        ok, message = ops.disable_instance_telemetry_logic(iid, previous_status='running')
        assert ok, message
        # the config_applied sync finds nothing in server.cfg and leaves the
        # stored state alone
        ops.sync_instance_server_id_from_config(db.session.get(QLInstance, iid))
        assert _settings().get_instance_server_id(iid) is None
        assert _settings().get_reserved_server_id(iid) == 12
    assert _cfg_text(app, iid) == 'set sv_hostname "duel"\n'
    assert _launch_args(app, iid) == ['+set qlx_statsHubUnifiedEnabled "0"']


def test_sync_keeps_the_route_when_server_cfg_has_no_cvars(app, monkeypatch):
    """A preset loaded over the instance brings a server.cfg without the
    cvars; the apply's sync must not read that as "switched off"."""
    ops = _ops()
    pushes = []
    monkeypatch.setattr(ops, 'push_relay_config_logic', lambda host_id: pushes.append(host_id) or True)
    iid = _make_instance(app, 'set sv_hostname "preset"\n', server_id=12)
    _switch_on(app, iid)
    with app.app_context():
        ops.sync_instance_server_id_from_config(db.session.get(QLInstance, iid))
        assert _settings().get_instance_server_id(iid) == 12
    assert pushes == []


def test_switch_reads_the_launch_state(app, client, auth):
    iid = _make_instance(app, 'set sv_hostname "duel"\n', server_id=12)
    _switch_on(app, iid)
    resp = client.get(f'{URL}/instances/{iid}', headers=auth)
    assert resp.get_json()['data']['enabled'] is True


@pytest.mark.parametrize('cfg, queues', [(ON_CFG, True), ('set sv_hostname "duel"\n', False)])
def test_save_moves_leftover_cvars_out_of_server_cfg(app, client, auth, queued, cfg, queues):
    iid = _make_instance(app, cfg, server_id=12)
    _switch_on(app, iid)
    resp = client.put(f'{URL}/instances/{iid}', json={'enabled': True}, headers=auth)
    if queues:
        assert resp.status_code == 202, resp.get_json()
        assert len(queued) == 1
    else:
        assert resp.get_json()['message'] == 'No changes.'
        assert queued == []
