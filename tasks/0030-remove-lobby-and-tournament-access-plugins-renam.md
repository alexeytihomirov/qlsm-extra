---
id: qlsm-extra-0030
title: Remove lobby and tournament_access plugins, rename Telemetry (Unified) to Live Telemetry
status: done-unverified
created: 2026-10-27
updated: 2026-10-27
verified:
depends_on: []
related: []
---

# Remove lobby and tournament_access plugins, rename Telemetry (Unified) to Live Telemetry

## Цель

`lobby` and `tournament_access` are gone from the repository and the manifest; the telemetry plugin shows as "Live Telemetry".

## Контекст

Operator request: the two plugins are not needed, "unified" is no longer a thing. Other plugins (chat_rcon, referee_call, demo_stream_resync_hold, item_roulette) were offered for removal and the operator kept them.

## Шаги

- [x] delete lobby, tournament_access (py, sidecar, test)
- [x] drop them from `DEFAULT_PLUGINS`, `qlsm-repository.json`, README
- [x] label "Telemetry (Unified)" -> "Live Telemetry" in the sidecar
- [x] manifest hashes check

## Журнал

- 2026-10-27 - created
- 2026-10-27 - only the label is renamed: file `stream_telemetry_unified.py` and cvars `qlx_statsHubUnified*` stay, so hosts' `qlx_plugins` keep working
- 2026-10-27 - `generate_manifest.py` keeps stale entries of deleted files; removed them from `qlsm-repository.json` by hand
- 2026-10-27 - tests/test_descriptions.py has 6 failures (description length) that also fail on main

## Результат

Branch `chore/drop-lobby-access-live-telemetry`, merged into `main`. A host that still has `lobby` or `tournament_access` in `qlx_plugins` keeps its copy of the file until it is removed by hand.

## Как проверить

Settings -> Repositories -> Sync in qlsm: the plugin list has no Lobby and no Tournament Access, and the telemetry plugin is "Live Telemetry".
