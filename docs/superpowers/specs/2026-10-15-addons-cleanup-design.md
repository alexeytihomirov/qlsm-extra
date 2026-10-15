# Addon and plugin cleanup - design

Date: 2026-10-15. Task: `qlsm-extra-0012`. Operator decisions taken in chat
on 2026-10-15; this file records them.

## Goal

Every addon and plugin in qlsm-extra does one clear thing, says so in one or
two sentences, and has the fewest popups and fields that still cover it. Test
and debug leftovers are gone. Nothing install-specific (our VPS address, its
host keys) is baked into the code: the addons are used by other installs too.

## Parts and order

| # | Where | What | Depends on |
|---|-------|------|------------|
| 1 | qlsm, upstream PR `upstream-pr/addon-menu-status` | A status next to an addon menu entry | - |
| 2 | qlsm-extra `demo-stream` 1.5.0 | One instance panel (stream + delay), real disable, one settings section | 1 for the menu status only |
| 3 | qlsm-extra `telemetry-relay` 1.5.0 | Telemetry moves to the instance menu, switch instead of server_id field, disable | 1 for the menu status only |
| 4 | qlsm-extra `player-ranks` 0.4.0 | No "on by default" | - |
| 5 | qlsm-extra plugins, `file-forwarder` 1.2.0, all descriptions | Removals, VPS key as a setting, short descriptions | - |

4 and 5 go first and in parallel with 1. 2 and 3 work without 1: qlsm's
manifest validator (`ui/addons/manifest.py`, the mount-point loop) ignores
keys it does not know on a menu entry, so an older qlsm simply shows no
status.

## Part 1 - menu entry status (qlsm core)

- A `host_menu` / `instance_menu` entry may declare
  `"status": "GET <route>"`, same route rules as a panel route, same response
  as a panel's status badge: `{"data": {"ok": bool, "label": str}}`.
- `AddonMenuSection.jsx`: when the menu opens, fetch every declared status for
  that entity in parallel, render after the label a dot (green `ok`, grey not
  ok) and the label in muted small text, truncated with the full text in
  `title`. A failed or slow fetch shows nothing (no spinner, no error); the
  entry stays clickable. No polling while open; a re-open fetches again.
- An entry without `status` renders exactly as today.
- Manifest validator accepts and validates the key. `addons/README.md` gets a
  short paragraph. Tests: vitest for the menu (with status, without, failed
  fetch), pytest for the validator.

## Part 2 - demo-stream 1.5.0

Instance menu: one entry **Live Demo Stream** (`status` route = today's
`instances/{id}/status`, extended with the delay: `Streaming, delay 5 s` /
`Streaming, delay 3 s (hub default)` / the existing not-ready labels).

Panel fields:
- `enabled` bool "Stream this instance".
- `delay_sec` string "Delay (seconds)", blank = hub default, 0-300.

`GET instances/{id}` returns both (delay blank when not streaming or the hub
cannot be asked). `PUT instances/{id}` compares with the stored state:

| Change | Action |
|--------|--------|
| delay only, instance streaming | the existing hub delay call, no restart, 200 |
| off -> on | existing enable task; the task sets the delay on the hub as its last step when the body carried one; 202 |
| on -> off | new disable task: `sv_demoStream 0` in server.cfg, apply + restart, `enabled` false; token and hub route kept (a stale route is harmless, re-enable reuses them); 202 |
| nothing | 200, "No changes" |
| delay while not streaming and staying off | 409 with the existing "not streaming" text |

The old routes `instances/{id}/delay*` and `POST instances/{id}/enable` stay
for one release for anything that calls them; the manifest no longer points
at them. The second menu entry `demo-stream-delay` is removed.

Settings: one section **Live Demo Stream** with relay host, relay port,
stats-hub URL, ingest token (one form, `GET/PUT settings` merging today's
`relay` and `stats-hub` routes). Host menu entry **Demo Stream Tunnel** gets
`status` = today's `hosts/{id}/status`.

## Part 3 - telemetry-relay 1.5.0

- `instance_tabs.telemetry` becomes `instance_menu` entry **Telemetry**,
  with `status`: `Server ID 12, relay on` / `Off` / `Relay off on host`.
- Panel field: `enabled` bool "Send telemetry". The `server_id` input goes;
  the ID stays reserved from stats-hub automatically (unique across the
  cluster, unlike a port or qlsm's own instance id, which is unique only
  within one qlsm) and is shown in the status.
- Off: new disable task sets `qlx_statsHubUnifiedEnabled 0`, apply +
  restart. The reserved server ID is kept, so re-enabling gets the same ID.
- Host menu **Telemetry Relay** gets `status` = today's host status. The
  per-host URL / token overrides stay.

## Part 4 - player-ranks 0.4.0

- Remove global `qlstats_enabled` / `slipgate_enabled` ("on by default") and
  instance `configured` / `sources_saved`.
- Migration on first load after the update (idempotent): an instance whose
  Ranks tab was never saved gets its instance checkboxes set to what it shows
  today (the old global defaults), so nothing visible changes.
- A new instance starts with every source off.

## Part 5 - plugins, file-forwarder, descriptions

Removed:
- `chat_rcon_acl.py` + sidecar + manifest entry; `tests/test_chat_rcon_acl.py`
  tests `chat_rcon.py`'s own rules instead (via `tests/_minqlx_stub.py`).
- `match_restore_lab.py` + sidecar + manifest entry + README rows. The cvar
  `qlx_matchRestoreLabEnabled` keeps its name in `match_restore` (renaming
  would break existing configs); its description no longer mentions the lab.
- `tournament_access`: `qlx_devAuthOpen`.
- `stream_telemetry_unified`: `qlx_pickupTelemetryDebug`,
  `qlx_statsHubMatchId`, and the fallback to `qlx_streamTelemetryEnabled` /
  `qlx_pickupTelemetryEnabled` / `qlx_sessionEventsEnabled`. Before removing
  the fallback, read every prod instance's server.cfg: an instance that sets
  only an old cvar gets the new one written first.

file-forwarder 1.2.0:
- `vps_host` has no default. `assets/known_hosts_vps` is removed.
- Saving the settings with a new address runs `ssh-keyscan` from qlsm,
  stores the keys as a setting (`vps_known_hosts`) and returns their SHA256
  fingerprints; the panel shows them in its status so the operator compares
  them once with the provider console. Same address saved again: keys are not
  re-scanned. A "Re-scan host keys" path for a reinstalled VPS: saving with
  an explicit `rescan_keys` bool.
- Apply to host renders `known_hosts` from the setting. No address or no keys:
  Apply refuses with a clear message instead of installing a forwarder that
  cannot connect.
- Upgrade, no IP in code at all: the forwarder already installed on each
  host keeps running with the `known_hosts` it has, untouched by the update.
  Until the operator saves the settings once (address in, keys scanned,
  fingerprints checked), Apply to host refuses and the host panel says why.
  An install that never saved `vps_host` (relied on the old default) sees the
  address field empty and has to type it once.

Descriptions (every addon manifest, every panel, every plugin sidecar): one or
two sentences: what it does and what it needs. Operational detail moves to
field descriptions and `README.md`. Helper sidecars: `Helper of <plugin>, not
a plugin.`. `demo_stream_resync_hold` stays, description cut to two
sentences. `qlmatch-packer`'s stale "Nothing runs the packer after a match"
is replaced (the `qlmatch_packer.py` plugin runs it).

## Testing

Only the tests of the touched modules (operator rule), each part its own:
`tests/test_addon_demo_stream*.py`, `test_addon_telemetry_relay_*.py`,
`test_addon_player_ranks.py`, `test_addon_file_forwarder.py`,
`test_file_forwarder_playbooks.py`, `test_chat_rcon_acl.py`,
`test_tournament_access.py`, `test_telemetry_*.py`; qlsm: the menu's vitest
and the validator's pytest. `check_manifest_hashes.py` before each commit.
Live check on prod after deploy: the operator opens each changed menu.
