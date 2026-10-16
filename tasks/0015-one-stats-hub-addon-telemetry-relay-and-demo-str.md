---
id: qlsm-extra-0015
title: One Stats Hub addon: telemetry relay and demo stream in one settings section, host panel and instance panel with the delay
status: todo
created: 2026-10-16
updated: 2026-10-16
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

- [ ] Спека (brainstorming), согласование с оператором
- [ ] План
- [ ] Реализация, миграция, выкат

## Журнал

- 2026-10-16 - created (отложено оператором до окончания аналитики)

## Результат

## Как проверить
