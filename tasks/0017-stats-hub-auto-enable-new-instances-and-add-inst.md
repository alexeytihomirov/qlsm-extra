---
id: qlsm-extra-0017
title: Stats Hub: auto-enable new instances and add-instance tab
status: in-progress
created: 2026-10-19
updated: 2026-10-19
verified:
depends_on: [qlsm-0016]
related: [qlsm-extra-0015, qlsm-extra-0016]
---

# Stats Hub: auto-enable new instances and add-instance tab

## Цель

В настройках аддона есть переключатель "включать новые серверы автоматически": новый инстанс сразу получает один stats-hub id и телеметрию + live demo stream уже в первом деплое, без отдельного захода в панели и без лишних рестартов. В форме добавления инстанса есть вкладка, где это можно выключить/включить и необязательно задать значения вручную (server id).

## Контекст

Запрос оператора 2026-10-19 (пункт 3): неудобно отдельно заходить в панели телеметрии и стрима ради id; сегодня это давало по два id на инстанс (стрим резервировал свой до телеметрии) и 2 лишних рестарта на инстанс. Нужен core-хук и вкладка формы добавления: qlsm-0016. Связано с объединением аддонов qlsm-extra-0015 и launch args из qlsm-extra-0016 (1.7.1: cvars идут через `instance.launch_args`, значит включение до первого деплоя = 0 рестартов).

## Шаги

- [ ] Дизайн поверх qlsm-0016 (`instance.created` + вкладка формы добавления)
- [ ] Глобальная настройка auto-enable
- [ ] На `instance.created`: один id (резерв или ручной), включить слои, телеметрия и стрим под одним id
- [ ] Вкладка формы добавления: вкл/выкл, необязательный server id
- [ ] Тесты, версия, manifest, merge, push, деплой аддона
- [ ] Проверка: добавить инстанс, он сразу в hub под одним id, рестартов 0 после деплоя

## Журнал

- 2026-10-19 - created
- 2026-10-19 - qlsm-0016 pushed as `upstream-pr/add-instance-addon-hook` (0a1d45e5): `instance.created` (ungated, own `addon_options` per addon) + `ui.add_instance_tabs`.
- 2026-10-19 - telemetry-relay 1.8.0 / demo-stream 1.8.0 on `feat/stats-hub-auto-enable`: setting "Switch on new instances" (AppSetting `stats_hub_auto_enable_new_instances`, in the Telemetry Stats Hub settings panel), tab "Stats Hub" (telemetry, demo_stream, optional server_id; prefill `GET add-instance`), handler `new_instance.prepare_new_instance`. One id: telemetry-relay reserves it (or takes the manual one) and stores it as its reserved id, then calls demo-stream's `prepare_new_instance` (published on its backend module), whose `_resolve_server_id` takes telemetry's id on the same hub; demo-stream registers no hook of its own because dispatch order is demo-stream < telemetry-relay. No apply/restart; only the relay's route push is queued (host sidecar config). Missing relay/tunnel/addon/hub -> "Stats Hub: ..." line in the instance log. Hook registered only when the core has it (older core: addon still loads, tab not shown).

## Результат

## Как проверить
