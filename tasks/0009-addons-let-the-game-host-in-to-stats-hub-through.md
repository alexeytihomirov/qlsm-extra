---
id: qlsm-extra-0009
title: Addons let the game host in to stats-hub through the hub firewall API
status: blocked
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
- [x] `generate_manifest.py`, пакеты
- [x] Merge, push
- [ ] Установка в prod qlsm (оператор: Settings -> Repositories -> Update, перезапуск qlsm)
- [ ] Проверка на одном хосте

## Журнал

- 2026-10-15 - created
- 2026-10-15 - telemetry-relay и demo-stream реализованы, тесты `tests/test_addon_telemetry_relay_access.py`, `tests/test_addon_demo_stream_access.py`
- 2026-10-15 - ревью: allow перенесён после взятия host lock (отказ хаба освобождает lock), статус ходит с таймаутом 10 с; включение tunnel теперь требует и URL, и ingest token хаба
- 2026-10-15 - `generate_manifest.py` пересобрал и `packages/qlmatch-packer.zip` без изменений кода (другие байты на Windows) - откачено, в коммите только demo-stream и telemetry-relay
- 2026-10-15 - merged `feat/hub-firewall-access` -> `origin/main` (af04f52, ls-remote подтвердил). Хаб с API уже задеплоен (`ql-stats-hub-0014`). Ждём установки оператором
- 2026-10-15 - оператор поставил 1.4.0: у Telemetry Relay нет бейджа. Причина: панель `host_relay` в манифесте никогда не объявляла `status` (эндпоинт `GET hosts/{host_id}/status` был и раньше, UI его не вызывал), не проверил это до релиза. Исправлено: `status` в манифесте + тест, версия 1.4.2 (1.4.1 параллельно выпустила другая сессия - предупреждение о двух инстансах с одним server id; перебазировано поверх, `origin/main` 1e70838)

## Результат

`origin/main` af04f52: demo-stream 1.4.0, telemetry-relay 1.4.0, пакеты и `qlsm-repository.json` обновлены.

## Как проверить

1. qlsm: Settings -> Repositories -> у Live Demo Stream и Telemetry Relay есть Update до 1.4.0 -> Update обоих -> перезапуск qlsm.
2. Хост nn1 -> меню хоста -> Telemetry Relay: бейдж статуса заканчивается на `Firewall ok; telemetry N s ago`.
3. Хост nn1 -> Demo Stream Tunnel: бейдж `Firewall ok; demo stream connected|not connected`.
4. (Меняет хост) на хосте с обоими включёнными: выключить Telemetry Relay -> на VPS хаба `hub-allow list` всё ещё содержит адрес; выключить и Tunnel -> адрес исчез; включить обратно -> адрес вернулся.
