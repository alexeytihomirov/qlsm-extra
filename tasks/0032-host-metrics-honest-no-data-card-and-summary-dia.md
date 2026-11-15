---
id: qlsm-extra-0032
title: host-metrics: honest No data card and Summary diagnostics for missing serverchecker/frame_timing data
status: in-progress
created: 2026-11-15
updated: 2026-11-15
verified:
depends_on: []
related: []
---

# host-metrics: honest No data card and Summary diagnostics for missing serverchecker/frame_timing data

## Цель

Карточка хоста с работающим коллектором, но неизвестной ёмкостью (verdict unknown) не пишет "No data yet", а говорит "Collecting" и почему. Summary в модалке прямо называет, чего не хватает: ключа serverchecker в Redis или данных frame_timing, по портам.

## Контекст

Админы чужой qlsm (qlsm.x76.gg, хосты na-east, na-west, x76-asia-node) решили, что плагин не получает данные: карточки "No data / No data yet", хотя коллектор 1.1.3 активен и графики есть. На деле verdict unknown: нет busy_p95 (ни одной минуты с state=in_progress и 2+ игроками) и нет среднего по флоту; frame statistics пустые. Источники: `minqlx:server_status:<port>` (serverchecker, системный плагин qlsm) и `minqlx:frame_stats:<port>` (наш frame_timing.py).

Только UI: данные берутся из уже существующих полей snapshot (`insts_last` - последняя сырая строка на порт, `insts[].frames_24h`), коллектор не меняется.

## Шаги

- [x] `feedGaps(snapshot)` в `ui-src/data.js`: running / noStatus / noFrames / states по портам
- [x] hostHealth: verdict unknown -> label Collecting, причина по feedGaps
- [x] findings: строка `feeds` про отсутствие serverchecker-статуса; room с текущим состоянием портов; frames называет frame_timing и порты
- [x] тесты findings/health/data, сборка UI, версия 1.1.4, пакет и манифест
- [ ] merge в main, push
- [ ] оператор обновил аддон и посмотрел карточки

## Журнал

- 2026-11-15 - created
- 2026-11-15 - решено не трогать коллектор: insts_last уже несёт players/state/frames последнего тика, frames_24h есть в insts; бамп сборщика заставил бы всех делать Apply ради одних текстов (бамп версии аддона всё равно помечает коллектор outdated, как и в прошлых UI-фиксах)
- 2026-11-15 - уровень новых строк info, а не warning: одна пустая строка при рестарте инстанса не должна переводить хост в Watch
- 2026-11-15 - node --test findings/health/data: 64 pass; tests/test_addon_host_metrics.py: 78 skipped (нет qlsm checkout рядом), backend не менялся; check_manifest_hashes ok. Tailwind в сборке 4.3.3 -> 4.3.5 (npm install), в CSS две строки дрейфа

## Результат

## Как проверить

В qlsm (Settings -> Addons) обновить Host Metrics до 1.1.4. На странице Host Metrics:
- хост с работающим коллектором без матчей: бейдж "Collecting", причина "Collecting - no match with 2+ players seen yet, room unknown." (или "no live status from serverchecker in Redis" / "no instance running");
- Details -> Summary: строка "No match with 2+ players seen ... Now: :<port> warmup, N players", при отсутствии frame_timing - "frame_timing is not reporting on :<port>", при отсутствии статуса - "No live status in Redis for :<port> ...".
