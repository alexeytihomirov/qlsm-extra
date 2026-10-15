---
id: qlsm-extra-0012
title: host-metrics: auto-refresh in the host modal
status: in-progress
created: 2026-10-15
updated: 2026-10-15
verified:
depends_on: []
related: [qlsm-extra-0011]
---

# host-metrics: auto-refresh in the host modal

## Цель

Окно хоста с графиками обновляется само, без кнопки: 1h/6h раз в 10 с, 24h/7d/30d раз в 60 с, с переключателем Auto-refresh (по умолчанию включён).

## Контекст

Запрос оператора 2026-10-15 после выпуска 1.1.1 (`qlsm-extra-0011`). Сборщик пишет точку раз в 10 с; минутные таблицы для 24h+ меняются раз в минуту, чаще ходить по SSH незачем. Плейбук статуса (ansible) в цикл не входит.

## Шаги

- [ ] Автообновление в `addons/host-metrics/ui-src/HostPanel.jsx` (пауза при скрытой вкладке / закрытом окне, без наложения запросов, без мигания, "Updated N s ago")
- [ ] Ревью
- [ ] Выпуск 1.1.2: push, установка в прод, Apply на хостах

## Журнал

- 2026-10-15 - created
- 2026-10-15 - auto-refresh implemented in the host modal (ui-src/refresh.js + HostPanel.jsx), version 1.1.2, built, manifest regenerated, tests green; committed on host-metrics-autorefresh, not merged/pushed

## Результат

## Как проверить
