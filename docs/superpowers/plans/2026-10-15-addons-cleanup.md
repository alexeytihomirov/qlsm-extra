# Addon and plugin cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Short descriptions, fewer popups and no test leftovers across qlsm-extra's addons and plugins; one Live Demo Stream panel; telemetry in the instance menu; a status next to addon menu entries in qlsm.

**Architecture:** Changes stay inside each addon's own directory and each plugin's own files. qlsm core gets one generic feature (menu entry `status`) through an upstream PR; the addons declare it and work without it on an older qlsm.

**Tech Stack:** Python 3 / Flask addon backends, Ansible playbooks, minqlxtended plugins, React (qlsm frontend, vitest), pytest.

**Spec:** `qlsm-extra/docs/superpowers/specs/2026-10-15-addons-cleanup-design.md`

## Global Constraints

- qlsm-extra worktree: `D:/QuakeLiveData/QL Server/.worktrees/qlsm-extra-addons-cleanup`, branch `addons-cleanup`. Never touch the main checkout `D:/QuakeLiveData/QL Server/qlsm-extra`.
- qlsm worktree (Task 6 only): a new worktree on branch `upstream-pr/addon-menu-status` from `upstream/main`; no fork-only files, no `VERSION` bump.
- Run only the tests of the touched modules: `QLSM_REPO=C:/Users/hellp/orca/workspaces/qlsm/QLSM rtk proxy python -m pytest tests/<file> -q -p no:cacheprovider`. Never the whole suite.
- Every commit that changes a packaged file: `python generate_manifest.py` first and commit `qlsm-repository.json` + `packages/*.zip` with it (the pre-commit hook `hooks/` blocks stale hashes; never `--no-verify`).
- All UI text, descriptions, code, commit messages in English. Hyphens only, no em/en dashes. Descriptions: one or two sentences, what it does and what it needs.
- Commits authored as the user; no `Co-Authored-By`, no "Generated with".
- Addon versions: demo-stream 1.5.0, telemetry-relay 1.5.0, player-ranks 0.4.0, file-forwarder 1.2.0. Other addons whose text changes: patch bump.
- Menu entry status key (shared by Tasks 6, 7, 8): `"status": "GET <route>"` on a `host_menu` / `instance_menu` entry; response `{"data": {"ok": bool, "label": str}}`.

## Review Focus

1. demo-stream PUT with both `enabled` off->on and a delay: the delay must reach the hub after the enable task has registered the route, not be lost or rejected with 409. Test in Task 7.
2. demo-stream / telemetry PUT while the instance is busy (CONFIGURING, RESTARTING ...): 409 with the existing busy text for disable too, not a second task. Tests in Tasks 7 and 8.
3. file-forwarder `ssh-keyscan` failing (host down, timeout, empty output): settings are not saved with empty keys; the error says the VPS could not be reached. Test in Task 4.
4. player-ranks migration run twice (every GET after the update): idempotent, a saved instance is never overwritten. Test in Task 5.
5. Menu status fetch failing or returning non-JSON in qlsm: the entry still renders and opens. Test in Task 6.

---

### Task 1: Remove test and debug leftovers from plugins

**Files:**
- Delete: `chat_rcon_acl.py`, `chat_rcon_acl.ql-plugin.json`, `match_restore_lab.py`, `match_restore_lab.ql-plugin.json`
- Modify: `tests/test_chat_rcon_acl.py` (test `chat_rcon.py` itself), `tournament_access.py` + `.ql-plugin.json` (drop `qlx_devAuthOpen`), `stream_telemetry_unified.py` + `.ql-plugin.json` (drop `qlx_pickupTelemetryDebug`, `qlx_statsHubMatchId`), `match_restore.ql-plugin.json` (`qlx_matchRestoreLabEnabled` description without the lab), `generate_manifest.py` (`DEFAULT_PLUGINS`), `qlsm-repository.json` (entries gone), `README.md` (rows gone)
- Test: `tests/test_chat_rcon_acl.py`, `tests/test_tournament_access.py`, `tests/test_telemetry_*.py`

- [ ] Step 1: Rewrite `tests/test_chat_rcon_acl.py` to import the permission rules from `chat_rcon.py` (load it with `tests/_minqlx_stub.py` as other plugin tests do), same cases as today. Run it: PASS against `chat_rcon.py` (if `chat_rcon.py` has no importable function for the rule, extract a module-level pure function in `chat_rcon.py` with the same behaviour and test that).
- [ ] Step 2: Delete the four files; remove their manifest entries and README rows; remove `chat_rcon_acl.py` from `DEFAULT_PLUGINS`; grep the repo for `match_restore_lab` and `chat_rcon_acl` and fix every remaining reference (keep `qlx_matchRestoreLabEnabled` as a cvar name).
- [ ] Step 3: Remove `qlx_devAuthOpen` from `tournament_access.py` (the roster check no longer has a bypass besides the permission level and the owner) and its sidecar; add a test in `tests/test_tournament_access.py` that the plugin no longer reads `qlx_devAuthOpen` (`"qlx_devAuthOpen" not in source`).
- [ ] Step 4: Remove `qlx_pickupTelemetryDebug` and `qlx_statsHubMatchId` from `stream_telemetry_unified.py` and sidecar; the match id is always `server-<Server ID>` (as with an empty override today). Keep the legacy cvar fallback (Task 2 decides). Run `tests/test_telemetry_*.py`: PASS.
- [ ] Step 5: `python generate_manifest.py`, run the touched tests, commit `chore: drop chat_rcon_acl, match_restore_lab and debug cvars`.

### Task 2: Legacy telemetry cvar fallback (gated on prod)

**Files:** `stream_telemetry_unified.py`, its sidecar, `tests/test_telemetry_*.py`

- [ ] Step 1 (controller, not a subagent): read every prod instance's `server.cfg` for `qlx_streamTelemetryEnabled`, `qlx_pickupTelemetryEnabled`, `qlx_sessionEventsEnabled` (read-only; hosts in `skills/qlsm-dev/reference/deploy-and-hosts.md`). Record the result in the task journal.
- [ ] Step 2: If none sets an old cvar without the new one: remove the fallback from the plugin and the "Falls back to ..." sentences from the sidecar; test that each feed reads only its `qlx_statsHubFeed*` cvar. If some do: write the new cvar into those configs first (operator OK required), then remove.
- [ ] Step 3: `generate_manifest.py`, tests, commit `chore(telemetry): drop the legacy feed cvar fallback`.

### Task 4: file-forwarder 1.2.0 - VPS address and host keys as settings

**Files:**
- Create: `addons/file-forwarder/hostkeys.py`
- Delete: `addons/file-forwarder/assets/known_hosts_vps`
- Modify: `addons/file-forwarder/config_render.py` (no `vps_host` default, `KNOWN_HOSTS_FILE` gone, `playbook_vars` takes keys from settings), `backend.py` (`put_settings`, `get_settings`, settings status, `apply_host` refusal), `qlsm-addon.json` (no default, new global setting `vps_known_hosts` type `string` label `internal: pinned VPS host keys`, field `rescan_keys` bool "Re-scan host keys" with description, panel `status: GET settings/status`), `README.md` of the addon
- Test: `tests/test_addon_file_forwarder.py`, `tests/test_file_forwarder_playbooks.py`, `tests/test_file_forwarder_package.py`

**Interfaces:**
- Produces: `hostkeys.scan(host: str, timeout: int = 10) -> str` (known_hosts lines, `ssh-keyscan -T <timeout> -t ed25519,ecdsa,rsa <host>`, comments stripped; raises `HostKeyScanError(message)` on non-zero exit, timeout or no key lines); `hostkeys.fingerprints(known_hosts: str) -> list[str]` (`"ED25519 SHA256:<base64 no padding>"`, computed in Python from the key blob, no ssh-keygen); `HostKeyScanError(Exception)`.

- [ ] Step 1: Tests in `tests/test_addon_file_forwarder.py` (mock `subprocess.run`):
  - `test_scan_returns_key_lines_without_comments`
  - `test_scan_failure_raises` (rc 1, empty stdout, `TimeoutExpired`)
  - `test_fingerprint_matches_ssh_keygen` (fixed ed25519 line -> its known `SHA256:` string computed once with ssh-keygen and pasted in)
  - `test_put_settings_new_address_scans_and_stores_keys` (response `data.fingerprints` non-empty, `vps_known_hosts` stored)
  - `test_put_settings_same_address_does_not_rescan`
  - `test_put_settings_rescan_keys_rescans`
  - `test_put_settings_scan_failure_saves_nothing` (409, message contains "could not reach", stored settings unchanged)
  - `test_apply_refuses_without_keys` (409, message names Settings -> File Forwarder)
  - `test_playbook_vars_use_stored_keys`
  - `test_no_ip_in_addon` (no `70.34.223.191` anywhere under `addons/file-forwarder`)
- [ ] Step 2: Run: FAIL.
- [ ] Step 3: Implement. `GET settings/status`: `ok` true with `label` `"Host keys pinned: <fingerprint>, ..."` or false `"VPS address or host keys not set"`. `vps_known_hosts` never editable from the form (strip it from PUT input like the SFTP key).
- [ ] Step 4: Run the three test files: PASS. Update the playbook test if it read the asset file.
- [ ] Step 5: Version 1.2.0, `generate_manifest.py`, commit `feat(file-forwarder): VPS address and host keys are settings, nothing pinned in code`.

### Task 5: player-ranks 0.4.0 - no "on by default"

**Files:** `addons/player-ranks/qlsm-addon.json`, `backend.py`, `ranks_service.py`, `tests/test_addon_player_ranks.py`

**Interfaces:**
- Produces: `ranks_service.migrate_instance(global_cfg: dict, stored: dict) -> dict | None` - returns the values to store for an instance never saved (`configured` falsy): `qlstats_enabled` / `slipgate_enabled` = the old effective value (old `source_enabled`), plus `configured` dropped; `None` when nothing to do.

- [ ] Step 1: Tests: `test_migrate_unsaved_instance_takes_old_defaults`, `test_migrate_saved_instance_untouched`, `test_migrate_twice_is_noop`, `test_new_instance_all_sources_off`, `test_suggestion_shown_while_x76_url_blank` (server.cfg suggestion now keyed on blank `elo_service_base_url`, not on `configured`), `test_manifest_has_no_on_by_default` (no `qlstats_enabled`/`slipgate_enabled` under `settings.global`, no `configured`/`sources_saved` under `settings.instance`).
- [ ] Step 2: Run: FAIL.
- [ ] Step 3: Implement: run the migration in `register(ctx)` once over all instances with stored settings, and lazily in `get_instance_config` / the ranks route; `source_enabled` reads the instance value only. Remove the four settings from the manifest and the "on by default" sentences from panel descriptions.
- [ ] Step 4: Run `tests/test_addon_player_ranks.py tests/test_player_ranks_*.py`: PASS.
- [ ] Step 5: Version 0.4.0, `generate_manifest.py`, commit `feat(player-ranks): sources are chosen per instance only`.

### Task 6: qlsm upstream PR - status next to an addon menu entry

**Files (qlsm worktree):** `ui/addons/manifest.py` (mount-point loop: validate `status` like a panel status route, GET only, menu points only), `frontend-react/src/components/addons/AddonMenuSection.jsx`, `addons/README.md` (one paragraph under mount points), tests `tests/test_addon_manifest*.py` (find the existing validator test file), `frontend-react/src/components/addons/__tests__/AddonMenuSection.test.jsx`

**Interfaces:**
- Produces: manifest key `status` on `host_menu` / `instance_menu` entries; rendered dot + label.

- [ ] Step 1: pytest: `test_menu_status_route_accepted`, `test_menu_status_must_be_get`, `test_menu_status_route_escape_rejected` (reuse the panel route checker), `test_status_on_settings_section_rejected`.
- [ ] Step 2: vitest: renders label + dot when status ok; grey dot when `ok:false`; nothing extra when fetch rejects or returns invalid data and the entry still opens its panel on click; no fetch for an entry without `status`; fetches again on re-open.
- [ ] Step 3: Run both: FAIL. Implement: fetch with the existing addon API helper when the menu's items render (the `items(closeMenu)` call happens on open), store per mount key in state; dot `w-1.5 h-1.5 rounded-full`, label `text-xs text-theme-muted truncate max-w-[10rem]` with `title`.
- [ ] Step 4: Run both: PASS. Commit `feat(addons): a menu entry can show a status`. Push the branch to `origin` and open the PR to `dngrtech/qlsm` with `gh pr create` (body without AI attribution). Merge the branch into the local `QLSM` working branch per the qlsm-dev skill.

### Task 7: demo-stream 1.5.0 - one instance panel, disable, one settings section

**Files:** `addons/demo-stream/backend.py`, `instance_ops.py`, `qlsm-addon.json`, tests `tests/test_addon_demo_stream*.py`

**Interfaces:**
- Consumes: menu `status` key (Task 6, optional at runtime).
- Produces: routes `GET/PUT instances/{id}` (body `{enabled: bool, delay_sec: str|number|null}`), `GET instances/{id}/status` (label carries the delay), `GET/PUT settings` (`relay_host`, `relay_port`, `stats_hub_url`, `ingest_token`), task `disable_instance_demo_stream`; `instance_ops.disable_instance_demo_stream_logic(instance_id, previous_status=None) -> (bool, str)`; `enable_instance_demo_stream_logic(instance_id, previous_status=None, delay_sec=None)`.

- [ ] Step 1: Tests, one per spec table row: `test_put_delay_only_calls_hub_no_task`, `test_put_enable_queues_task_with_delay` and `test_enable_task_sets_delay_last`, `test_put_disable_queues_disable_task`, `test_disable_logic_writes_sv_demoStream_0_and_restarts` (token kept), `test_put_no_change_200`, `test_put_delay_while_off_409`, `test_put_disable_while_busy_409`, `test_status_label_with_delay`, `test_settings_get_put_merges_relay_and_stats_hub` (secret token kept when blank), `test_manifest_one_instance_entry_with_status` (`instance_menu` has one entry `demo-stream` with `status`, `settings_section` one entry, `host_menu` entry has `status`). Keep the old `delay` / `enable` / `relay` / `stats-hub` route tests passing.
- [ ] Step 2: Run: FAIL. Implement. The status label: `Streaming, delay 5 s` / `Streaming, delay 3 s (hub default)`; when the hub cannot be asked, `Streaming` alone (status must stay cheap: one hub call, existing timeout).
- [ ] Step 3: Run `tests/test_addon_demo_stream*.py`: PASS. Remove the stale "No disable" paragraph from the `instance_ops.py` docstring.
- [ ] Step 4: Version 1.5.0, `generate_manifest.py`, commit `feat(demo-stream): one Live Demo Stream panel with delay, switch off works`.

### Task 8: telemetry-relay 1.5.0 - instance menu, switch, disable

**Files:** `addons/telemetry-relay/backend.py`, `instance_ops.py`, `qlsm-addon.json`, tests `tests/test_addon_telemetry_relay_*.py`

**Interfaces:**
- Produces: `GET instances/{id}` -> `{enabled: bool}` (from `qlx_statsHubUnifiedEnabled` in server.cfg), `PUT instances/{id}` (`enabled`), `GET instances/{id}/status` (`Server ID 12, relay on` / `Off` / `Relay off on host`), `instance_ops.disable_instance_telemetry_logic(instance_id, previous_status=None) -> (bool, str)` (writes `qlx_statsHubUnifiedEnabled 0`, keeps the server ID, pushes relay config, apply + restart).

- [ ] Step 1: Tests: `test_get_instance_enabled_from_cfg`, `test_put_enable_queues_enable`, `test_put_disable_queues_disable`, `test_disable_keeps_server_id`, `test_put_no_change_200`, `test_put_while_busy_409`, `test_status_labels` (three cases), `test_manifest_telemetry_in_instance_menu` (no `instance_tabs`, `instance_menu` entry `telemetry` with `status`, panel has no `server_id` field, `host_menu` entry has `status`). Old `POST instances/{id}/enable` keeps working.
- [ ] Step 2: Run: FAIL. Implement.
- [ ] Step 3: Run `tests/test_addon_telemetry_relay_*.py`: PASS.
- [ ] Step 4: Version 1.5.0, `generate_manifest.py`, commit `feat(telemetry-relay): Telemetry in the instance menu, a switch instead of the server ID field`.

### Task 9: Short descriptions everywhere

**Files:** every `addons/*/qlsm-addon.json` (`description`, panel `description`s), every `*.ql-plugin.json`, root `README.md`, `addons/qlmatch-packer/qlsm-addon.json` (stale "Nothing runs the packer after a match")

- [ ] Step 1: Rewrite: addon `description` and plugin `description` at most two sentences (what it does, what it needs); panel descriptions at most two sentences; detail that matters moves to a field `description` or the README. Helper sidecars: label `<plugin> helper`, description `Helper of <plugin>.py, downloaded with it. Not a plugin.` `demo_stream_resync_hold` description two sentences; command/cvar descriptions unchanged. host-metrics: description text only.
- [ ] Step 2: Add `tests/test_descriptions.py`: every addon and plugin `description` has at most 2 sentences (split on `. ` followed by a capital) and at most 300 characters; no `—`/`–`.
- [ ] Step 3: Run it: PASS. README: tables updated (removed plugins gone, demo-stream/telemetry rows match the new menus), release notes for 1.5.0 / 0.4.0 / 1.2.0 in the existing style. Patch-bump addons whose only change is text.
- [ ] Step 4: `generate_manifest.py`, `check_manifest_hashes.py`, commit `docs: short descriptions for every addon and plugin`.

### Task 10: Integrate

- [ ] Whole-branch review; merge `addons-cleanup` into `main` (re-check `origin/main` first), push, confirm with `git ls-remote`. Deploy per `skills/qlsm-dev/reference/deploy-and-hosts.md` only with the operator's OK. Task file: Результат + Как проверить.
