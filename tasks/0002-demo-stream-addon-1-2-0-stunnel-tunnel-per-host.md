---
id: qlsm-extra-0002
title: demo-stream addon 1.2.0: stunnel tunnel per host, port 27999, shared server_id with telemetry
status: in-progress
created: 2026-10-11
updated: 2026-10-11
verified:
depends_on: []
related: [root-0011, root-0003, docs/superpowers/specs/2026-10-11-demo-stream-relay-hardening-design.md]
---

# demo-stream addon 1.2.0: stunnel tunnel per host, port 27999, shared server_id with telemetry

## Цель

Аддон demo-stream 1.2.0: туннель stunnel на хосте (панель хоста, playbook), инстанс стримит через 127.0.0.1, server_id общий с телеметрией, порт по умолчанию 27999.

## Контекст

Спека: `docs/superpowers/specs/2026-10-11-demo-stream-relay-hardening-design.md`, раздел 4.3 (монолит). Ветка `feat/demo-stream-tunnel`, worktree `.claude/worktrees/demo-stream-tunnel`. Образец для playbook и панели хоста: аддон `telemetry-relay`.

## Шаги

- [ ]

## Журнал

- 2026-10-11 - created

- 2026-10-11 - ветка `feat/demo-stream-tunnel` влита в `main` `de7055b` (после слияния с чужими коммитами referee_call и runtime-source; 309 тестов зелёные), пуш подтверждён `git ls-remote`. Обновление аддона в qlsm до 1.2.0 и живая проверка туннеля - за оператором

## Результат

## Как проверить
