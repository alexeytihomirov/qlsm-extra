---
id: qlsm-extra-0001
title: referee_call plugin - !call answers the caller
status: in-progress
created: 2026-10-07
updated: 2026-10-07
verified:
depends_on: []
related: [root-0008, docs/superpowers/specs/2026-10-07-tickets-and-referee-calls-design.md]
---

# referee_call plugin - !call answers the caller

## Цель
Игрок (в том числе зритель) пишет `!call` в чате и получает ответ только себе: "Referees have been notified." или "Please wait N s before calling again." (один вызов в 60 секунд на steam id). Сам вызов уходит как обычная строка чата через `stream_telemetry_unified`, плагин не делает сетевого ввода-вывода и не работает с Redis.

## Контекст
Часть плана тикетов и вызовов судьи, см. `root-0008` и спецификацию `docs/superpowers/specs/2026-10-07-tickets-and-referee-calls-design.md` (Task 8 плана). Строка `say` видна хуку `client_command` в `stream_telemetry_unified.py` (приоритет LOWEST), команда `!call` выполняется позже, в событии `chat`, и ничего не останавливает.

## Шаги
- [x] Тесты на чистую функцию `decide`
- [x] Плагин `referee_call.py` и `referee_call.ql-plugin.json`
- [x] Запись в `qlsm-repository.json`, README
- [ ] Установка и проверка на живом сервере (делает родительская сессия после деплоя)

## Журнал
- 2026-10-07 - created, plugin implemented in worktree `feature/referee-call`, not merged, not deployed

## Результат
Ветка `feature/referee-call` (не влита, не запушена).

## Как проверить
Включить `referee_call` и `stream_telemetry_unified` на сервере, написать `!call` в чате (и зрителем): ответ приходит только вызвавшему; повтор в течение 60 секунд даёт "Please wait N s before calling again."; строка `!call` видна в потоке чата телеметрии.
