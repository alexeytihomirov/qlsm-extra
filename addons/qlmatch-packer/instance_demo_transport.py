"""qlmatch-packer's private copy of the SFTP-to-a-managed-host plumbing for
reading an instance's demo dir.

Used to be ui/instance_demo_transport.py in qlsm core, shared with the
demo-management addon (which originally had this code inline in its own
ansible_instance_demos.py before the split). Duplicated instead of kept
shared once it became clear the addon system has no way to declare or
enforce a dependency between addons -- see addons/README.md's "Where the
line falls" in qlsm for the full reasoning, which applies here identically
(telemetry-relay's and demo-stream's private copies of the old
ui/stats_hub.py are the same pattern). This copy and demo-management's are
free to diverge from here on.
"""
import logging
import os
import stat as stat_module

import paramiko

from ui import db
from ui.models import QLInstance
from ui.rcon_transport import rcon_target_for_host

log = logging.getLogger(__name__)

SSH_CONNECT_TIMEOUT_SECONDS = 10
# Covers a whole batch fetch, not just one file - mirrors the old Ansible
# fetch module's FETCH_TIMEOUT_SECONDS budget.
SSH_IO_TIMEOUT_SECONDS = 180


def resolve_instance_and_host(instance_id):
    """Return (instance, host, error_msg)."""
    instance = db.session.get(QLInstance, instance_id)
    if not instance:
        return None, None, f"Instance {instance_id} not found."

    host = instance.host
    if not host:
        return instance, None, "Associated host not found."

    if not isinstance(instance.port, int) or instance.port <= 0:
        return instance, host, "Instance port is invalid."

    if not host.ip_address or not host.ssh_key_path or not host.ssh_user:
        return instance, host, "Host details missing (IP, SSH key, or user)."

    return instance, host, None


def demo_dir_for_instance(instance):
    return f"/home/ql/qlds-{instance.port}/demos"


def open_ssh(host):
    """Open a key-authenticated SSH client to a managed host.

    No-persisted-host-key trust model, same as the other direct-SSH
    management paths in this codebase (service_runtime.py's runtime probe,
    rcon_transport.py's live rcon) - a QLSM-internal channel to hosts QLSM
    itself provisioned, not a user-facing endpoint. Caller is responsible for
    closing the returned client.
    """
    target = rcon_target_for_host(host)
    if not target:
        raise OSError("Could not resolve an SSH target for this host.")

    client = paramiko.SSHClient()
    client.load_system_host_keys()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(
            hostname=target,
            port=host.ssh_port,
            username=host.ssh_user,
            key_filename=os.path.abspath(host.ssh_key_path),
            timeout=SSH_CONNECT_TIMEOUT_SECONDS,
            banner_timeout=SSH_CONNECT_TIMEOUT_SECONDS,
            auth_timeout=SSH_CONNECT_TIMEOUT_SECONDS,
            allow_agent=False,
            look_for_keys=False,
        )
    except Exception:
        client.close()
        raise
    return client


def open_sftp(host):
    """Open a key-authenticated SFTP session to a managed host.

    Caller is responsible for closing the returned client (which also closes
    the sftp session).
    """
    client = open_ssh(host)
    try:
        sftp = client.open_sftp()
        sftp.get_channel().settimeout(SSH_IO_TIMEOUT_SECONDS)
    except Exception:
        client.close()
        raise
    return client, sftp


def run_remote_command(host, command, timeout=SSH_IO_TIMEOUT_SECONDS):
    """Run one command on a managed host over SSH exec, blocking for its exit.

    For a single Node invocation (qlmatch-packer's rebuild), not a general
    remote-shell facility - no streaming, no interactivity. Returns
    (exit_status, stdout_text, stderr_text). Caller owns error handling for
    a non-zero exit_status; this never raises for that, only for a
    connection failure (paramiko/OSError), same as open_sftp's callers do.
    """
    client = open_ssh(host)
    try:
        _stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
        exit_status = stdout.channel.recv_exit_status()
        stdout_text = stdout.read().decode('utf-8', errors='replace')
        stderr_text = stderr.read().decode('utf-8', errors='replace')
        return exit_status, stdout_text, stderr_text
    finally:
        client.close()


def list_dir_entries(sftp, demo_dir, filename_re):
    """Regular files directly under demo_dir whose name matches filename_re.

    Returns a list of {"name", "size", "mtime"} dicts, unsorted - callers
    sort by whatever key fits their listing (newest-first, by suffix, ...).
    """
    try:
        entries = sftp.listdir_attr(demo_dir)
    except FileNotFoundError:
        entries = []
    return [
        {'name': entry.filename, 'size': entry.st_size, 'mtime': entry.st_mtime}
        for entry in entries
        if entry.st_mode is not None and stat_module.S_ISREG(entry.st_mode)
        and filename_re.fullmatch(entry.filename)
    ]


def fetch_files(instance_id, filenames, filename_re, max_batch=200):
    """Fetch one or more named files from an instance's demo dir into memory.

    Returns (success, files: dict[str, bytes], missing: list[str], error_msg).
    `missing` holds requested filenames that no longer existed on the remote
    host by the time the fetch ran - not treated as a failure, since the
    files that WERE found are still worth returning.

    Filenames are validated against filename_re before anything else: this
    value reaches a remote path built by string concatenation.
    """
    if not isinstance(filenames, list) or not filenames:
        return False, {}, [], "filenames must be a non-empty list."
    if len(filenames) > max_batch:
        return False, {}, [], f"Cannot fetch more than {max_batch} files at once."

    deduped = []
    for name in filenames:
        if not isinstance(name, str) or not filename_re.fullmatch(name):
            return False, {}, [], f"Invalid filename: {name!r}"
        if name not in deduped:
            deduped.append(name)
    filenames = deduped

    client = None
    try:
        instance, host, instance_error = resolve_instance_and_host(instance_id)
        if instance_error:
            log.error(f"Cannot fetch files for instance {instance_id}: {instance_error}")
            return False, {}, [], instance_error

        demo_dir = demo_dir_for_instance(instance)
        log.info(f"Fetching {len(filenames)} file(s) for instance {instance_id} on host {host.name}...")

        client, sftp = open_sftp(host)

        files = {}
        missing = []
        for name in filenames:
            try:
                with sftp.open(f"{demo_dir}/{name}", 'rb') as fh:
                    files[name] = fh.read()
            except FileNotFoundError:
                missing.append(name)

        log.info(f"Fetched {len(files)}/{len(filenames)} file(s) for instance {instance_id}")
        return True, files, missing, None

    except (paramiko.AuthenticationException, paramiko.SSHException, OSError) as exc:
        log.error(f"SSH failure fetching files for instance {instance_id}: {exc}")
        return False, {}, [], "Failed to fetch files from remote host."
    except Exception as e:
        log.exception(f"Exception fetching files for instance {instance_id}: {e}")
        return False, {}, [], "Failed to fetch files."
    finally:
        if client is not None:
            client.close()
