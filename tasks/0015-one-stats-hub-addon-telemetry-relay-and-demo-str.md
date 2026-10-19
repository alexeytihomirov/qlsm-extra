---
id: qlsm-extra-0015
title: One Stats Hub addon: telemetry relay and demo stream in one settings section, host panel and instance panel with the delay
status: in-progress
created: 2026-10-16
updated: 2026-10-19
verified:
depends_on: []
related: [ql-tournament-0060, ql-stats-hub-0017, ql-tournament/docs/superpowers/specs/2026-10-16-public-match-analytics-design.md]
---

# One Stats Hub addon: telemetry relay and demo stream in one settings section, host panel and instance panel with the delay

## Цель

Вместо двух аддонов (`telemetry-relay`, `demo-stream`) один аддон «Stats Hub»: одни настройки хаба (URL, ingest-токен), одна панель хоста (relay и туннель, один переключатель файрвола), одна панель инстанса (телеметрия, demo stream, задержка). Задержку можно задать серверу и без demo stream: она действует и на трансляцию, и на публичную аналитику.

## Контекст

Решение оператора 2026-10-16 (при работе над `ql-tournament-0060`): сначала аналитика, потом объединение отдельной задачей. Раздел "Separate task: one addon for the hub" в спеке `ql-tournament/docs/superpowers/specs/2026-10-16-public-match-analytics-design.md`.

Сейчас (проверено 2026-10-16):
- обе копии хранят URL хаба и ingest-токен (`addons/telemetry-relay/stats_hub.py`, `addons/demo-stream/stats_hub.py`), `server_id` общий только при одинаковом URL (`addons/demo-stream/instance_ops.py:102`);
- каждый аддон сам открывает хост в файрволе хаба;
- поле «Delay» есть только в панели Live Demo Stream; хаб с `ql-stats-hub-0017` (d989bc3) принимает задержку для любого сервера реестра (`PUT /api/demo-stream/servers/{id}/delay`), но UI для сервера без стрима нет.

Нужна своя спека: миграция сохранённых настроек обоих аддонов на проде (ключи `stats_hub_server_id:`, `demo_stream_stats_hub_server_id:` и др.), плейбуки и сайдкары, порядок выката без потери телеметрии.

## Шаги

Вариант A (выбран оператором 2026-10-19): один UI «Stats Hub», два пакета под ним, без миграции данных.

- [x] Вариант A согласован с оператором (вместо отдельной спеки на слияние пакетов)
- [x] Instance menu: одна запись «Stats Hub» (telemetry-relay) - телеметрия, новый server ID, стрим, задержка; один Save, не больше одного apply/restart
- [x] Host menu: одна запись «Stats Hub» - relay и туннель, одна host-задача
- [x] Settings: одна секция «Stats Hub» - URL, токен, автовключение, relay стрима; URL/токен пишутся в оба аддона
- [x] Статус в меню: On/Off; детали в статусе панели
- [x] demo-stream без своих menu/settings, API/задачи/плейбуки/hooks на месте; деградация без demo-stream
- [x] Версии 1.9.0, README, манифесты, тесты
- [ ] Деплой (родительская сессия) и проверка оператором в UI
- [ ] Вариант B (позже, отдельно): один пакет, миграция ключей, задержка для сервера без стрима

## Журнал

- 2026-10-16 - created (отложено оператором до окончания аналитики)
- 2026-10-19 - оператор выбрал вариант A на сейчас: один UI Stats Hub поверх двух пакетов, без миграции данных. Объём: одна запись в instance menu (телеметрия + стрим + задержка, один Save, не больше одного рестарта), одна в host menu (relay + туннель), одна секция Settings (URL/токен пишутся в оба аддона), статус меню On/Off, у demo-stream убраны свои menu/settings (API, задачи, плейбуки, hooks остаются), деградация без demo-stream. Ветка `feat/stats-hub-one-ui`.
- 2026-10-19 - реализовано: telemetry-relay 1.9.0 (`addons/telemetry-relay/hub_ui.py`, маршруты `hub/...` в `addons/telemetry-relay/backend.py`, задачи `apply_stats_hub_instance` и `configure_stats_hub_host`), demo-stream 1.9.0 (`STATS_HUB_UI_API` и `stats_hub_ui_*` в `addons/demo-stream/backend.py`, `queue_apply=False` в enable/disable). Defer restarts ядра не учитывается: cvars идут launch args, без рестарта не применятся - как и раньше, всегда рестарт. Новые тесты `tests/test_addon_telemetry_relay_stats_hub.py` (36) зелёные.
- 2026-10-19 - вариант A выложен: main d48de1e, на проде telemetry-relay 1.9.0 и demo-stream 1.9.0 из репозитория, qlsm перезапущен, оба загружены без ошибок; URL и токен хаба у обоих аддонов совпадали до выката (сверено по хешу). Ждёт проверки оператором; вариант Б (один пакет, миграция) остаётся в этой задаче

## Результат

## Как проверить
