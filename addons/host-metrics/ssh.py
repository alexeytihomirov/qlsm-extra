"""SSH exec helper of the host-metrics addon: runs hm_query.py on a game host.

Worker threads use this, so nothing here touches the Flask app context or
SQLAlchemy: the request thread turns a Host row into plain data with
connection() first and passes that on.
"""
import json
import os
import shlex
from types import SimpleNamespace

import paramiko

CONNECT_TIMEOUT_SECONDS = 5
STDERR_TAIL = 500
QUERY_SCRIPT = '/home/ql/host-metrics/hm_query.py'
# rc 127 = the script is not there (python3 itself would exit 2 for a missing
# script, which collides with argparse's exit 2 for bad arguments).
MISSING_RC = 127


def connection(host):
    """Plain, thread-safe copy of what open_ssh needs. Call in the request thread."""
    from ui.rcon_transport import rcon_target_for_host

    return SimpleNamespace(
        id=host.id,
        name=host.name,
        target=rcon_target_for_host(host),
        ssh_port=host.ssh_port,
        ssh_user=host.ssh_user,
        ssh_key_path=host.ssh_key_path,
    )


def open_ssh(conn):
    """Open a key-authenticated SSH client to a managed host.

    No-persisted-host-key trust model, same as the other direct-SSH
    management paths in this codebase (service_runtime.py's runtime probe,
    rcon_transport.py's live rcon) - a QLSM-internal channel to hosts QLSM
    itself provisioned, not a user-facing endpoint. Caller is responsible for
    closing the returned client.
    """
    if not conn.target or not conn.ssh_user or not conn.ssh_key_path:
        raise OSError("Could not resolve an SSH target for this host.")

    client = paramiko.SSHClient()
    client.load_system_host_keys()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(
            hostname=conn.target,
            port=conn.ssh_port,
            username=conn.ssh_user,
            key_filename=os.path.abspath(conn.ssh_key_path),
            timeout=CONNECT_TIMEOUT_SECONDS,
            banner_timeout=CONNECT_TIMEOUT_SECONDS,
            auth_timeout=CONNECT_TIMEOUT_SECONDS,
            allow_agent=False,
            look_for_keys=False,
        )
    except Exception:
        client.close()
        raise
    return client


def remote_command(argv):
    """The one command line that is ever sent. argv is built by the backend from
    allow-listed values; shlex still quotes every word. nice 19: the query must not
    compete with QLDS for CPU on the game host."""
    return ('test -f %s || exit %d; nice -n 19 python3 %s %s'
            % (QUERY_SCRIPT, MISSING_RC, QUERY_SCRIPT, shlex.join(argv)))


def exec_json(conn, argv, timeout=5.0):
    """Run hm_query.py with argv on the host.

    Returns (rc, parsed stdout JSON or None, stderr tail). Raises OSError /
    paramiko exceptions / TimeoutError when the host cannot be reached or does
    not answer in time.
    """
    client = open_ssh(conn)
    try:
        _stdin, stdout, stderr = client.exec_command(remote_command(argv), timeout=timeout)
        stdout.channel.settimeout(timeout)
        out = stdout.read().decode('utf-8', errors='replace')
        err = stderr.read().decode('utf-8', errors='replace')
        rc = stdout.channel.recv_exit_status()
    finally:
        client.close()
    try:
        parsed = json.loads(out)
    except ValueError:
        parsed = None
    if not isinstance(parsed, dict):
        parsed = None
    return rc, parsed, err[-STDERR_TAIL:]
