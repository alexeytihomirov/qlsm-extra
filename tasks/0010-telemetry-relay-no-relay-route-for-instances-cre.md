---
id: qlsm-extra-0010
title: telemetry-relay: no relay route for instances created with a stats-hub server id already in the config
status: todo
created: 2026-10-15
updated: 2026-10-15
verified:
depends_on: []
related: [root-0020, qlsm-0002]
---

# telemetry-relay: no relay route for instances created with a stats-hub server id already in the config

## Цель

An instance that is created with `qlx_statsHubServerId` already set (and the unified feed on) gets a relay route on its host without an extra "Apply" click, and no two instances end up sharing one hub server id by default.

## Контекст

Found 2026-10-15 while onboarding the donated VPS (`root-0020`). On 5 of 6 new hosts the relay answered `routes 0`, `dropped_no_route` 110-367, `telemetry-relay.json` had `"routes": {}`: all telemetry was dropped. The server.cfg values were right (ids 40, 50, 60, 70, 80); the qlsm AppSetting `stats_hub_server_id:<instance_id>` was missing for instances 4-8 (it existed for 1, 2, 3). nn1 (instance 3) worked after an Apply.

Mechanism (verified in code): `build_relay_routes_for_host` (`addons/telemetry-relay/relay_ops.py:43`) builds routes only from that AppSetting. It is filled by `sync_instance_server_id_from_config` (`addons/telemetry-relay/instance_ops.py:43`), which runs on the hook `instance.config_applied` (`addons/telemetry-relay/backend.py:295`). The add-instance path (`add_qlds_instance.yml`, worker log 2026-10-15 15:23-15:29) did not fire that hook, so ids typed before or at creation never reached the AppSetting. Not verified: which core code path creates the instance and whether it can dispatch the hook (qlsm side, may need an upstream hook).

Second cause: every instance created from our presets starts with `qlx_statsHubServerId "1"` (before the operator changed them, instances 1, 2, 3 all had AppSetting 1, i.e. the same hub server `server-1`). Two servers on one id mix their matches under `server-1`. The assisted flow `enable_instance_telemetry_logic` reserves a unique id from the hub (`reserve_server_id`), the preset default bypasses it.

Interim fix used on 2026-10-15: operator applies the config on each instance (fires the hook).

## Шаги

- [ ] Find where an instance is created in core and whether `instance.config_applied` (or a new `instance.created` hook) can be dispatched there
- [ ] Make the addon sync the AppSetting and push the relay config after creation too (idempotent, same as `sync_instance_server_id_from_config`)
- [ ] Decide the default id for new instances: preset default 0 (disabled until reserved) or reserve from the hub on creation; check `qlx_statsHubServerId` in the presets under `qlsm/configs/presets/*` and in `ql-assets`
- [ ] Add a check that warns when two instances share a server id
- [ ] Tests in `tests/` for the hook path and the id default; `check_manifest_hashes.py` and `generate_manifest.py` after rebuilding the addon (see `skills/qlsm-dev/reference/plugins-and-presets.md`)
- [ ] Release the addon version, update installed addons, and verify on a host with a fresh instance: `curl 127.0.0.1:8190/health` shows `routes: 1` and the hub `/api/health` lists the new id

## Журнал

- 2026-10-15 - created from the readiness check of the new hosts

## Результат

## Как проверить

Create a new instance on any host with a unique `qlx_statsHubServerId` in the form, without pressing Apply afterwards: on the host `/home/ql/telemetry-relay.json` has the route, the relay `/health` shows `routes: 1`, and after a match the hub's `last_telemetry_by_server` has that id.
