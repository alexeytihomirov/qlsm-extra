"""Sets up the host-local TLS tunnel (stunnel client) for the demo stream.

The engine speaks plain TCP to sv_demoStreamHost/Port, but ql-stats-hub now
requires TLS on that ingest. Each game host therefore runs a stunnel client
listening on 127.0.0.1:<port> that forwards to the hub's TLS port, pinning
the hub certificate fetched from GET <hub>/api/demo-stream/tls-cert.
install_demo_stream_tunnel.yml does the host side; this module fetches the
certificate, builds the playbook extravars and records the result.
"""
import os

import requests
from flask import current_app

from ui import db
from ui.models import Host, HostStatus
from ui.task_logic.ansible_runner import _run_host_ansible_playbook

PLAYBOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        'playbooks', 'install_demo_stream_tunnel.yml')

from .settings import (
    get_effective_stats_hub_url,
    get_relay_host,
    get_relay_port,
    set_host_tunnel_enabled,
)

_CERT_PATH = '/api/demo-stream/tls-cert'
_CERT_TIMEOUT_SEC = 10


class TunnelCertError(Exception):
    """str(exc) is the operator-facing message."""


def fetch_hub_tls_cert(host_id):
    """The stats-hub TLS certificate as PEM text, for pinning in stunnel."""
    url = get_effective_stats_hub_url(host_id)
    if not url:
        raise TunnelCertError("Set the demo-stream stats-hub URL in Settings first.")
    try:
        response = requests.get(f"{url}{_CERT_PATH}", timeout=_CERT_TIMEOUT_SEC)
    except requests.RequestException as exc:
        raise TunnelCertError(f"Could not fetch the stats-hub TLS certificate: {exc}")
    if response.status_code == 404:
        raise TunnelCertError(
            "stats-hub has no TLS configured (GET /api/demo-stream/tls-cert "
            "returned 404); the tunnel was not set up."
        )
    if not 200 <= response.status_code < 300:
        raise TunnelCertError(
            f"Could not fetch the stats-hub TLS certificate: HTTP {response.status_code}"
        )
    pem = response.text or ''
    if '-----BEGIN CERTIFICATE-----' not in pem or '-----END CERTIFICATE-----' not in pem:
        raise TunnelCertError("stats-hub returned something that is not a PEM certificate.")
    return pem


def build_tunnel_extravars(enabled, port, cert_pem):
    return {
        'demo_stream_tunnel_enabled': bool(enabled),
        'demo_stream_tunnel_port': port,
        'demo_stream_relay_host': get_relay_host() or '',
        'demo_stream_relay_port': get_relay_port() or '',
        'demo_stream_hub_cert_pem': cert_pem if enabled else '',
    }


def configure_host_demo_stream_tunnel_logic(host_id, enabled, port, cert_pem):
    """Enables/disables the stunnel client on a host. Does not touch any
    instance's cvars."""
    host = db.session.get(Host, host_id)
    if not host:
        current_app.logger.error(f"Host {host_id} not found for demo-stream tunnel configuration.")
        return False

    current_app.logger.info(
        f"Configuring demo-stream tunnel for host: {host.name} (enabled={enabled})"
    )
    success, _stdout, _stderr = _run_host_ansible_playbook(
        host=host,
        playbook_name=PLAYBOOK,
        extravars=build_tunnel_extravars(enabled, port, cert_pem),
    )

    if success:
        set_host_tunnel_enabled(host_id, enabled)
        host.status = HostStatus.ACTIVE
        line = (f"Demo stream tunnel enabled on port {port}." if enabled
                else "Demo stream tunnel disabled.")
        host.logs = f"{line}\n{host.logs or ''}"
    else:
        current_app.logger.error(f"Failed to configure demo-stream tunnel for host {host.name}.")
        host.status = HostStatus.ERROR
        host.logs = f"Demo stream tunnel configuration failed.\n{host.logs or ''}"

    db.session.commit()
    return success
