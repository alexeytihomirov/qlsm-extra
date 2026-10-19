"""The "Stats Hub" entries (1.9.0): one instance entry, one host entry and
one settings section for telemetry and the live demo stream together.

Two packages stay underneath, each with its own stored settings; nothing is
migrated. A tier-1 panel only reaches its own addon's routes, so this
addon's `hub/...` routes (backend.py) serve the whole form and call the
demo-stream addon's backend in-process: its module publishes
`STATS_HUB_UI_API` and `stats_hub_ui_*` functions from 1.9.0 on, found
through its addon context the same way new_instance.py finds its
`prepare_new_instance`. Without a usable demo-stream (not installed,
switched off, older than 1.9.0) the entries show and save telemetry only,
and say why the stream part is missing.

One save, at most one apply + restart: what the instance save changes for
both features runs in one instance task here, each feature's enable or
disable without its own apply (`queue_apply=False`), then one apply with a
restart for both. A delay-only change is one hub call, no restart, as before.
The host save runs the relay and the tunnel playbooks in one host task, so
they do not fight over the host lock.
"""
import sys

from flask import current_app

from ui import db
from ui.models import Host, HostStatus, QLInstance

DEMO_STREAM_ADDON_ID = 'demo-stream'
DEMO_STREAM_UI_API = 1


def demo_stream_api():
    """(module, None) when demo-stream can be driven from here, else
    (None, a short note saying why)."""
    from ui.addons import get_addon

    addon = get_addon(DEMO_STREAM_ADDON_ID)
    if not (addon and addon.loaded and addon.ctx):
        return None, 'the Live Demo Stream addon (demo-stream) is not installed'
    if not addon.globally_enabled:
        return None, 'the Live Demo Stream addon is switched off on the Addons page'
    module = sys.modules.get(addon.ctx.module_name or '')
    if getattr(module, 'STATS_HUB_UI_API', 0) < DEMO_STREAM_UI_API:
        return None, 'the installed Live Demo Stream addon is older than 1.9.0; update it'
    return module, None


def _log(instance, message):
    instance.logs = f"{message}\n{instance.logs or ''}"


def apply_instance_logic(instance_id, previous_status=None, telemetry=None,
                         new_server_id=False, stream=None, delay_sec=None):
    """The instance task of a Stats Hub save. `telemetry` and `stream` are
    'enable', 'disable' or None. Telemetry goes first, so a stream enable
    in the same save takes telemetry's (new) server ID. Returns (ok, message)."""
    from ui.models import InstanceStatus
    from ui.tasks import apply_instance_config, enqueue_task
    from ui.task_logic.job_failure_handlers import instance_job_failure_handler

    from .instance_ops import (
        _status_after_failure, disable_instance_telemetry_logic, enable_instance_telemetry_logic,
    )

    instance = db.session.get(QLInstance, instance_id)
    if not instance or not instance.host:
        return False, "Instance or associated host not found."

    changed = []
    if telemetry == 'enable':
        ok, _ = enable_instance_telemetry_logic(instance_id, previous_status=previous_status,
                                                new_server_id=new_server_id, queue_apply=False)
        changed.append(ok)
    elif telemetry == 'disable':
        ok, _ = disable_instance_telemetry_logic(instance_id, previous_status=previous_status,
                                                 queue_apply=False)
        changed.append(ok)

    if stream in ('enable', 'disable'):
        api, why = demo_stream_api()
        if api is None:
            instance = db.session.get(QLInstance, instance_id)
            _log(instance, f"Live demo stream left unchanged: {why}.")
            db.session.commit()
        elif stream == 'enable':
            ok, _ = api.stats_hub_ui_enable(instance_id, previous_status=previous_status,
                                            delay_sec=delay_sec)
            changed.append(ok)
        else:
            ok, _ = api.stats_hub_ui_disable(instance_id, previous_status=previous_status)
            changed.append(ok)

    instance = db.session.get(QLInstance, instance_id)
    if not any(changed):
        # Every part failed (each logged why) or there was nothing to do: no
        # apply, and the instance leaves CONFIGURING.
        if instance.status == InstanceStatus.CONFIGURING:
            instance.status = _status_after_failure(previous_status)
        db.session.commit()
        return False, "Stats Hub: nothing was changed."

    job = enqueue_task(apply_instance_config, instance.id, restart=True,
                       on_failure=instance_job_failure_handler)
    if not job:
        _log(instance, "Stats Hub: queuing the config apply/restart failed.")
        if instance.status == InstanceStatus.CONFIGURING:
            instance.status = _status_after_failure(previous_status)
        db.session.commit()
        return False, "Stats Hub: queuing the config apply/restart failed."
    message = f"Stats Hub: applying config and restarting once (job {job.id})."
    _log(instance, message)
    db.session.commit()
    return all(changed), message


def configure_host_logic(host_id, relay=None, tunnel=None):
    """The host task of a Stats Hub save: the relay playbook (`relay` True
    or False) and the tunnel playbook (`tunnel` = (wanted, port, cert_pem)),
    in that order, under one host lock. Each records its own result; the
    host ends in ERROR when either failed. Returns ok."""
    from .relay_ops import configure_host_telemetry_relay_logic

    results = []
    if relay is not None:
        results.append(configure_host_telemetry_relay_logic(host_id, relay))
    if tunnel is not None:
        api, why = demo_stream_api()
        if api is None:
            host = db.session.get(Host, host_id)
            if host is not None:
                host.logs = f"Demo stream tunnel left unchanged: {why}.\n{host.logs or ''}"
                db.session.commit()
            results.append(False)
        else:
            wanted, port, cert_pem = tunnel
            results.append(api.stats_hub_ui_configure_host(host_id, wanted, port, cert_pem))

    host = db.session.get(Host, host_id)
    if host is not None and not all(results):
        host.status = HostStatus.ERROR
        db.session.commit()
    if not all(results):
        current_app.logger.error(f"telemetry-relay: Stats Hub host task for host {host_id} failed.")
    return all(results)
