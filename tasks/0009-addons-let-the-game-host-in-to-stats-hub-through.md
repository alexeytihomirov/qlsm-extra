---
id: qlsm-extra-0009
title: Addons let the game host in to stats-hub through the hub firewall API
status: in-progress
created: 2026-10-15
updated: 2026-10-15
verified:
depends_on: [ql-stats-hub-0014]
related: [root-0020, ql-stats-hub/docs/superpowers/specs/2026-10-15-hub-firewall-api-design.md]
---

# Addons let the game host in to stats-hub through the hub firewall API

## Цель

Telemetry Relay и Demo Stream Tunnel при включении на хосте сами пускают его IP через firewall stats-hub, при выключении обоих - убирают; панели хоста показывают состояние firewall и приход данных.

## Контекст

Хабовая часть и дизайн: `ql-stats-hub-0014` (спека `ql-stats-hub/docs/superpowers/specs/2026-10-15-hub-firewall-api-design.md`, план `ql-stats-hub/docs/superpowers/plans/2026-10-15-hub-firewall-api.md`, Tasks 6-7). Нужен хаб с эндпоинтами `/api/admin/firewall/hosts`.

## Шаги

- [x] telemetry-relay: allow при включении (и при пересохранении включённого), release после выключения, если tunnel выключен; статус панели
- [x] demo-stream: allow при включении, release после выключения, если relay выключен; новый status хоста
- [ ] `generate_manifest.py`, пакеты
- [ ] Merge, push, установка в prod qlsm
- [ ] Проверка на одном хосте

## Журнал

- 2026-10-15 - created
- 2026-10-15 - telemetry-relay и demo-stream реализованы, тесты `tests/test_addon_telemetry_relay_access.py`, `tests/test_addon_demo_stream_access.py`

## Результат

## Как проверить
