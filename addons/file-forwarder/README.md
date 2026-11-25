# file-forwarder

Ships demo files from every game host to the site VPS over SFTP (rclone), and
removes raw demos from the host after the retention once their delivery is
recorded in the host's ledger and at least 24 hours old. The VPS is not asked:
the NAS pulls `raw/` with a MOVE sync, so a delivered raw demo is normally gone
from the VPS by then. A file is never deleted in the run that delivered it.
Design: `docs/superpowers/specs/2026-10-11-file-forwarder-addon-design.md` in
the QL monorepo.

## Parts

| File | Role |
|------|------|
| `assets/forwarder.sh` | Runs on the host as `ql` from a systemd timer; ledger, cleanup, purge. Its header documents `forwarder.conf`. |
| `config_render.py` | Settings -> `forwarder.conf` text and the sync playbook vars; validates every value. |
| `keypair.py` | The install-wide ed25519 SFTP key (generated with `cryptography`). |
| `hostkeys.py` | `ssh-keyscan` of the VPS from qlsm and the SHA256 fingerprints of the pinned keys. |
| `backend.py` | Routes, the `apply_task` / `sync_task` tasks, the `host.payload_sync` handler. |
| `playbooks/` | `sync_file_forwarder.yml`, `run_forwarder.yml`, `status_file_forwarder.yml`. |
| `ui/HostPanel.js` | The host menu dialog: switch, status table, action buttons. Hand-written, no build step. |
| `ui/PublicKey.js` | The SFTP key settings section: the public line, wrapped, with Copy. |

## Settings

Global (Settings -> Addons -> File Forwarder): VPS address (no default), raw demo retention
(days, 14), raw upload limit per run (MB, 2048), interval (minutes, 10) and
the pattern table. Pattern rows are `glob remote_dir keep|expire`, separated by
`;` (a newline also works through the API); the default is
`*.qlmatch qlmatch keep; *.replay.json.gz qlmatch keep; *.dm_91 raw expire`.
A glob uses only letters, digits and `_ . * ? [ ] -`; a remote dir only
`A-Za-z0-9_.-`, with no leading `.` or `-` and no `..`.

Host (host menu -> File Forwarder): `enabled`, on by default, so a new host
gets the forwarder at its first setup with no operator step. The addon hooks
host setup only (`host.payload_sync`); Update Plugins does not reach it, so use
Apply to host after an addon update or a settings change.

Pinned in the addon, not settings: SFTP user `qldemos-in`, rclone remote name
`qldemos`, source directories `/home/ql/qlds-*/demos`, state directory
`/home/ql/.forwarder-state/`, the delivery grace (24 hours,
`DELIVERED_GRACE_HOURS`) and the remote raw budget (5000 MB,
`MAX_RAW_REMOTE_MB`: a run that finds `raw/` on the VPS that full sends no raw
demo; the `.qlmatch` files still go) and the remote dir of published
multi-POV matches (`PACK_DIR`, `qlmatch`).

## The VPS address and its host keys

Nothing install-specific is in the addon: each install types its VPS address
once. Saving the settings form with a new address runs `ssh-keyscan` in the
qlsm container (`openssh-client`), stores the keys as the internal setting
`vps_known_hosts` and shows their SHA256 fingerprints in the form's status
line; compare them once with the VPS provider console. Saving the same address
again does not re-scan. After a VPS reinstall, tick "Re-scan host keys" and
save. A failed scan saves nothing. `vps_known_hosts` is never accepted from the
form; it only comes from the scan. Apply to host writes it as the host's
`known_hosts_qldemos`.

Apply to host (and host setup) refuses while the address or its keys are not
set. Upgrading from 1.1: a forwarder already installed on a host keeps running
with the `known_hosts` it has; Apply refuses until the settings are saved once.
An install that never saved the address (it relied on the old built-in
default) sees the address field empty and types it once.

## Published multi-POV matches (1.3.0)

With the engine's `sv_demoMultiPov 1` and qlmatch-packer 1.4.0 a match is one
`<name>.dm_91` plus `<name>.meta.json` (`"format": "qlsm-demo-meta"`,
`"version": 2`, `"pack": "<name>.dm_91"`), no `.qlmatch`. A `*.meta.json`
whose `pack` value is its own stem plus `.dm_91` marks that pair; both files
go to `qlmatch/` (pinned `PACK_DIR`, an empty value switches this off) and are
kept like a `keep` row, so such a `.dm_91` never goes to `raw/` and is never
deleted by the retention. The `.dm_91` is sent first; the meta only once the
`.dm_91` is in the ledger, so the VPS never holds a meta without its demo.
"Sync now and delete delivered" deletes the `.dm_91` once the VPS listing
holds it, and the meta only after that. Every other `.dm_91` (per-client
captures, `sv_demoMultiPov 0`) still follows its pattern row (`raw/`). The
`{match_id}.meta.json` the packer also writes for the Demos screen is never
sent (its `pack` is not its own stem). A `.dm_91` whose meta was deleted on the
host is a plain `.dm_91` again and follows the `raw/` row.

1.3.1: a pack file's ledger line carries a 5th column, the remote dir
(`qlmatch`), and only such a line counts as its delivery to `qlmatch/`. A
published `.dm_91` that 1.2.x had already sent to `raw/` (a host where
qlmatch-packer 1.4.0 ran before file-forwarder 1.3.x) is sent to `qlmatch/`
on the next run; 1.3.0 took the old `raw/` line for a delivery and sent only
the meta. Pack files 1.3.0 ledgered are sent once more, harmlessly (same
name, same bytes).

File names are shared flat across hosts: each remote dir on the VPS is one
directory for all hosts, so the same file name from two hosts would overwrite
there (match names make that improbable).

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

## Host dialog (host menu -> File Forwarder)

One dialog holds the `enabled` switch (saved as soon as it is toggled), the
status table and the actions as buttons below it. An action is queued as a
task; press Refresh to read the status again once it has finished.

- **Apply to host**: runs the sync playbook (install / update script, units,
  key, config).
- **Sync now**: one forwarder run now.
- **Sync now and delete delivered**: purge mode; whatever the file age, deletes
  ledgered files of `keep` rows (`.qlmatch`, `.replay.json.gz`) only when the
  VPS listing holds them (name and size), and ledgered files of `expire` rows
  (`.dm_91`) when the VPS listing holds them or their delivery is more than
  24 hours old (the NAS has pulled them). Everything else stays and is counted
  as `kept_unconfirmed`; that does not make the run fail (exit 1 is for failed
  uploads only).

The status table shows the installed version (stale when it differs from the
addon's), the timer state and the last run line.
