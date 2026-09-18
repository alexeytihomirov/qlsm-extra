"""Deploys/configures ql-telemetry-relay on a host via Ansible.

Wires install_telemetry_relay.yml into the qlsm task queue (previously a
manual-only playbook, see its own header + qlsm-becomes-platform-plugin-sot
in project memory) and keeps its config's routes/token in sync with this
host's effective stats-hub target and whichever instances on the host have
a reserved stats-hub server_id.
"""
import json

from flask import current_app
import os

from ui import db
from ui.models import Host, HostStatus, QLInstance
from ui.task_logic.ansible_runner import _run_host_ansible_playbook, run_host_ansible_adhoc
# The playbook and its template now live next to this module, inside the
# addon, so the path is resolved here rather than assumed to be under
# ansible/playbooks/ (see _run_host_ansible_playbook -- it takes an absolute
# path as-is).
PLAYBOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        'playbooks', 'install_telemetry_relay.yml')

from .settings import (
    get_effective_stats_hub_ingest_token,
    get_effective_stats_hub_url,
    get_instance_server_id,
    is_relay_enabled,
    set_relay_enabled,
)

# Fixed local address the relay sidecar always listens on (see
# ansible/templates/ql-telemetry-relay.service.j2's QL_TELEMETRY_RELAY_HOST/
# _PORT). The stream_telemetry_unified plugin hardcodes this same value as
# its qlx_statsHubUrl default - it is a fixed program constant, not
# per-instance data, so it no longer needs to be written into any
# instance's server.cfg (see telemetry_relay_instance.py).
RELAY_LOCAL_URL = 'http://127.0.0.1:8190/api/ingest/telemetry'
_RELAY_HEALTH_URL = 'http://127.0.0.1:8190/health'
_RELAY_HEALTH_TIMEOUT_SEC = 3


def build_relay_routes_for_host(host_id):
    """{"<server_id>": {"telemetry": "<stats-hub>/api/ingest/telemetry", "server_name": ...}}
    for every instance on this host that already has a reserved server_id,
    targeting this host's effective (override or global) stats-hub URL."""
    stats_hub_url = get_effective_stats_hub_url(host_id)
    if not stats_hub_url:
        return {}
    routes = {}
    for instance in QLInstance.query.filter_by(host_id=host_id).all():
        server_id = get_instance_server_id(instance.id)
        if not server_id:
            continue
        routes[str(server_id)] = {
            'telemetry': f'{stats_hub_url}/api/ingest/telemetry',
            'server_name': instance.name,
        }
    return routes


def push_relay_config_logic(host_id):
    """Re-render + push telemetry-relay.json for a host whose relay is
    already enabled (e.g. after a new instance reserved a server_id, or
    after a stats-hub URL/token override changed). No-op if the relay isn't
    enabled on this host."""
    host = db.session.get(Host, host_id)
    if not host:
        current_app.logger.error(f"Host {host_id} not found for telemetry-relay config push.")
        return False
    if not is_relay_enabled(host_id):
        return True

    extra_vars = {
        'telemetry_relay_enabled': True,
        'telemetry_relay_token': get_effective_stats_hub_ingest_token(host_id) or '',
        'telemetry_relay_routes': build_relay_routes_for_host(host_id),
    }
    success, _stdout, _stderr = _run_host_ansible_playbook(
        host=host,
        playbook_name=PLAYBOOK,
        extravars=extra_vars,
    )
    if not success:
        current_app.logger.error(f"Failed to push telemetry-relay config for host {host.name}.")
    return success


def configure_host_telemetry_relay_logic(host_id, enabled):
    """Enables/disables the ql-telemetry-relay sidecar on a host.

    Disabling stops routing new instances through it but deliberately does
    NOT touch already-applied instance cvars (an instance pointed at
    127.0.0.1:8190 with the relay stopped just stops sending, same failure
    mode as any other misconfiguration - avoids this action silently
    rewriting instance config it doesn't own).
    """
    host = db.session.get(Host, host_id)
    if not host:
        current_app.logger.error(f"Host {host_id} not found for telemetry-relay configuration.")
        return False

    current_app.logger.info(
        f"Configuring telemetry relay for host: {host.name} (enabled={enabled})"
    )

    extra_vars = {
        'telemetry_relay_enabled': bool(enabled),
        'telemetry_relay_token': (get_effective_stats_hub_ingest_token(host_id) or '') if enabled else '',
        'telemetry_relay_routes': build_relay_routes_for_host(host_id) if enabled else {},
    }

    success, stdout_str, stderr_str = _run_host_ansible_playbook(
        host=host,
        playbook_name=PLAYBOOK,
        extravars=extra_vars,
    )

    if success:
        current_app.logger.info(f"Successfully configured telemetry relay for host {host.name}.")
        set_relay_enabled(host_id, enabled)
        host.status = HostStatus.ACTIVE
        host.logs = f"Telemetry relay {'enabled' if enabled else 'disabled'}.\n{host.logs or ''}"
    else:
        current_app.logger.error(f"Failed to configure telemetry relay for host {host.name}.")
        host.status = HostStatus.ERROR
        host.logs = f"Telemetry relay configuration failed.\n{host.logs or ''}"

    db.session.commit()
    return success


def get_relay_status_logic(host_id):
    """Sidecar health/reachability (live probe over SSH, since the relay only
    listens on 127.0.0.1) plus the instances currently routed through it.
    Returns a dict; never raises - probe failures show up as reachable=False.
    """
    host = db.session.get(Host, host_id)
    if not host:
        return None

    enabled = is_relay_enabled(host_id)
    routed_instances = [
        {'id': instance.id, 'name': instance.name, 'server_id': get_instance_server_id(instance.id)}
        for instance in QLInstance.query.filter_by(host_id=host_id).all()
        if get_instance_server_id(instance.id)
    ]

    result = {
        'enabled': enabled,
        'reachable': False,
        'health': None,
        'error': None,
        'routed_instances': routed_instances,
    }

    if not enabled:
        return result

    success, stdout, stderr = run_host_ansible_adhoc(
        host,
        module_args=f"curl -sS -m {_RELAY_HEALTH_TIMEOUT_SEC} {_RELAY_HEALTH_URL}",
    )
    if not success:
        result['error'] = (stderr or 'Could not reach relay health endpoint').strip()[:500]
        return result

    try:
        health = json.loads(stdout)
    except (TypeError, ValueError):
        result['error'] = 'Relay health endpoint returned non-JSON output.'
        return result

    result['reachable'] = bool(health.get('ok'))
    result['health'] = health
    return result
