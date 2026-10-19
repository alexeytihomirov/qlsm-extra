---
id: qlsm-extra-0016
title: Addon cvars as launch args, not in server.cfg (presets must not carry or wipe them)
status: in-progress
created: 2026-10-19
updated: 2026-10-19
verified:
depends_on: []
related: [qlsm-extra-0015]
---

# Addon cvars as launch args, not in server.cfg (presets must not carry or wipe them)

## Цель

Ключи, которые пишут аддоны telemetry-relay и demo-stream (`qlx_statsHubUnifiedEnabled`, `qlx_statsHubServerId`, `sv_demoStream*` с токеном), не должны попадать в пресет при Save preset и не должны теряться при Load preset на сервер.

## Контекст

- Первая идея оператора: отдельный `qlsmextra.cfg` с `exec` в конце `server.cfg`. Не решает задачу: редактор qlsm показывает и сохраняет все `*.cfg` инстанса (`qlsm/ui/routes/instance_routes.py:1359`), Save preset уносит файл в пресет, Load preset удаляет его (`qlsm/ui/routes/instance_routes.py:202-207`). Скрыть файл можно только правкой qlsm (`RESERVED_CONFIG_FOLDER_NAMES`, `qlsm/ui/config_path_utils.py:11`); оператор попросил вариант без обновления qlsm.
- Выбрано: хук `instance.launch_args` (`qlsm/ui/addons/hooks.py:43`), командная строка пересобирается при каждом apply (`qlsm/ui/task_logic/ansible_instance_mgmt.py:640`). Хук приходит только когда аддон включён на global, host и instance (`qlsm/ui/addons/settings.py:140-159`); в остальных случаях аддон пишет `server.cfg` как раньше.
- `server.cfg` выполняется после `+set` и перебивает его (`skills/ql-live/reference/config-load-order.md:35`), поэтому аддон вычищает свои строки, а оставшиеся показывает как drift; Save в панели чистит и перезапускает.

## Шаги

- [x] telemetry-relay 1.7.0: launch args, чистка server.cfg, sync не сбрасывает маршрут при server.cfg без cvars, drift.
- [x] demo-stream 1.7.0: launch args, чистка server.cfg, drift.
- [x] Тесты: `tests/test_addon_telemetry_relay_launch_args.py`, `tests/test_addon_demo_stream_launch_args.py`.
- [ ] Merge в main, push.
- [ ] Обновить аддоны в qlsm на проде.
- [ ] На живом инстансе: Save в Telemetry и Live Demo Stream, проверить командную строку и что после Load preset + Save стрим и телеметрия на месте.

## Журнал

- 2026-10-19: реализовано в ветке `feat/addon-launch-args`, тесты затронутых аддонов зелёные.
