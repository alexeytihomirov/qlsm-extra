# file-forwarder

Ships demo files from every game host to the site VPS over SFTP (rclone), and
removes delivered raw demos from the host once the VPS confirms it has them.
Design: `docs/superpowers/specs/2026-10-11-file-forwarder-addon-design.md` in
the QL monorepo.

## Parts

| File | Role |
|------|------|
| `assets/forwarder.sh` | Runs on the host as `ql` from a systemd timer; ledger, cleanup, purge. Its header documents `forwarder.conf`. |
| `assets/known_hosts_vps` | Pinned host keys of the VPS (copied from `ql-tournament/deploy/known_hosts`). |
| `config_render.py` | Settings -> `forwarder.conf` text and the sync playbook vars; validates every value. |
| `keypair.py` | The install-wide ed25519 SFTP key (generated with `cryptography`). |
| `backend.py` | Routes, the `apply_task` / `sync_task` tasks, the `host.payload_sync` handler. |
| `playbooks/` | `sync_file_forwarder.yml`, `run_forwarder.yml`, `status_file_forwarder.yml`. |

## Settings

Global (Settings -> Addons -> File Forwarder): VPS address, raw demo retention
(days, 14), raw upload limit per run (MB, 2048), interval (minutes, 10) and
the pattern table. Pattern rows are `glob remote_dir keep|expire`, separated by
`;` (a newline also works through the API); the default is
`*.qlmatch qlmatch keep; *.replay.json.gz qlmatch keep; *.dm_91 raw expire`.
A glob uses only letters, digits and `_ . * ? [ ] -`; a remote dir only
`A-Za-z0-9_.-`, with no leading `.` or `-` and no `..`.

Host (host menu -> File Forwarder): `enabled`, on by default, so a new host
gets the forwarder at its first setup with no operator step.

Pinned in the addon, not settings: SFTP user `qldemos-in`, rclone remote name
`qldemos`, source directories `/home/ql/qlds-*/demos`, state directory
`/home/ql/.forwarder-state/`, the VPS host keys. Moving to another VPS address
needs a release with that host's keys in `assets/known_hosts_vps`.

## The SFTP key

One ed25519 key per qlsm install, generated on first use (opening the
"File Forwarder SFTP key" section, or the first apply). The private half is the
addon's secret setting `sftp_private_key`; it reaches a host only through the
sync playbook, as a 0600 temp file (`ff_private_key_file`) that is deleted
after the run. It is never an extravar, because qlsm's ansible runner logs the
whole extravars JSON. The public half is shown in that settings section; add it
once to `/etc/ssh/authorized_keys.d/qldemos-in` on the VPS.

Note that qlsm core's own `GET /api/addons/file-forwarder/state` returns every
setting of an addon, the secret one included, to any logged-in user; this
addon's UI never calls it.

Rotating: clear `sftp_private_key` (PUT `/api/addons/file-forwarder/state`
with `{"settings": {"sftp_private_key": ""}}`), open the key section to
generate a new pair, replace the line on the VPS, then Apply to host on every
host.

## Host actions (host menu -> File Forwarder Sync)

- **Apply to host**: runs the sync playbook (install / update script, units,
  key, config).
- **Sync now**: one forwarder run now.
- **Sync now and delete delivered**: purge mode; deletes from the host every
  ledgered file the VPS confirms, whatever its age.

The status row shows the installed version (stale when it differs from the
addon's), the timer state and the last run line.
