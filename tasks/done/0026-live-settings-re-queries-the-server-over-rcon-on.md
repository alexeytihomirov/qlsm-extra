---
id: qlsm-extra-0026
title: Live Settings re-queries the server over rcon on every page render
status: done-unverified
created: 2026-10-25
updated: 2026-10-25
verified:
depends_on: []
related: [root-0032, qlsm-extra-0025]
---

# Live Settings re-queries the server over rcon on every page render

## Цель

Вкладка Live Settings опрашивает сервер по rcon только при открытии и по кнопкам Refresh / Apply / Retry, а не на каждый перерендер окна инстанса.

## Контекст

2026-10-25 завис `sD test server` (germany :27960) посреди матча: главный поток движка ждал бесконечно в отправке вывода консоли rcon-клиенту, который уже отключился (разбор в `root-0032`). Клиентом был этот аддон: пока вкладка открыта, он открывал новую rcon-сессию примерно раз в 15 с (около 47 cvar'ов за раз) и закрывал её с `LINGER 0`.

Причина частоты: `load` в `addons/live-settings/ui-src/Panel.jsx` зависел от `ctx`, а qlsm (`frontend-react/src/components/addons/AddonComponentHost.jsx:90`) создаёт `ctx` заново на каждом рендере. Каждый перерендер окна инстанса (его собственный опрос статуса) менял `load`, и `useEffect([load])` запускал новый GET `/cvars`, то есть новую rcon-сессию.

Риск зависания от любого отключающегося rcon-клиента закрывается на стороне движка в `root-0032`; здесь убираем лишние подключения.

## Шаги

- [x] `load` зависит только от `instanceId`, `ctx` читается через ref
- [x] версия 1.0.2, `ui/Panel.js` пересобран, `npm test` зелёный
- [x] merge в `main`, push
- [x] установить 1.0.2 на прод qlsm
- [ ] проверка оператором: при открытой вкладке на germany :27960 нет rcon-подключений, кроме открытия и Refresh

## Журнал

- 2026-10-25 - created
- 2026-10-25 - фикс в `ui-src/Panel.jsx` (ctxRef), 1.0.2, сборка и `rows.test.mjs` зелёные
- 2026-10-25 - 15 с - это `POLL_INTERVAL` в `qlsm/frontend-react/src/hooks/useServerStatus.js:4`; `ctx` в `AddonComponentHost.jsx:90` создаётся на каждом рендере
- 2026-10-25 - `generate_manifest.py` (изменился только `packages/live-settings.zip`), push `c0f56b3` в `main` подтверждён `ls-remote`; установлен на прод скриптом в `qlsm-web-1` (`_sync` + `download_addon`), перезапущены web, worker-1..5, poller; в контейнере `version 1.0.2`, `ctxRef` в `ui/Panel.js`

## Результат

- live-settings 1.0.2 в qlsm-extra `main` (`c0f56b3` и коммит журнала после него), установлен на проде qlsm.

## Как проверить

1. В qlsm открыть Edit Configuration инстанса `sD test server` (germany), вкладку Live Settings, оставить открытой на 1-2 минуты.
2. На germany: `journalctl -u qlds@27960 --since "-3 min" | grep "RCON client connected"` - одно подключение на открытие вкладки (плюс по одному на каждое нажатие Refresh / Apply), а не каждые 15 с.
