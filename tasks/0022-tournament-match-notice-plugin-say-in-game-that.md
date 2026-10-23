---
id: qlsm-extra-0022
title: tournament_match_notice plugin: say in game that the players have a tournament match
status: in-progress
created: 2026-10-23
updated: 2026-10-23
verified:
depends_on: [ql-tournament-0119]
related: [root-0029, docs/superpowers/specs/2026-10-23-tournament-match-notice-design.md]
---

# tournament_match_notice plugin: say in game that the players have a tournament match

## Цель

На игровом сервере, где оказались оба игрока ready/live турнирного матча, в чате и в центре экрана видно, что это турнирный матч: при входе пары (раз за карту) и на отсчете перед каждой игрой. Без влияния на игровой цикл и на sync.

## Контекст

Оператор 2026-10-23 (`root-0029`): "главное чтобы не было проблем с процессом игры основным; если можно делать в плагине в стороне, не влияя на перфоманс или стопорку синк процесса, то нужно делать". Выбор оператора: при входе + на отсчете; чат + центр экрана. Сайт: `ql-tournament-0119` (`GET /api/integrations/game-match`, скоуп `game:read`), токен `match-notice` создан на проде, секрет в `ql-local/hub.env` (`QLT_MATCH_NOTICE_TOKEN`).

## Шаги

- [x] Плагин `tournament_match_notice.py` + `.ql-plugin.json`
- [x] Тесты `tests/test_tournament_match_notice.py` (чистые функции, HTTP к локальному серверу, `_tick`)
- [x] API сверено с исходником движка (`_build/minqlxtended-fork`, коммит 90e24bd): сигнатуры шести хуков, `Plugin.msg`, `Plugin.center_print` (broadcast), `get_cvar`
- [x] `qlsm-repository.json` (generate_manifest), README
- [ ] merge, push
- [ ] qlsm: синхронизировать репозиторий, скачать плагин, включить на турнирных серверах с тремя cvar, применить
- [ ] Проверка на живом сервере с двумя игроками матча

## Журнал

- 2026-10-23 - created
- 2026-10-23 - 12 тестов зеленые; `tests/test_descriptions.py` падает на 4 описаниях аддонов (demo-stream, telemetry-relay) и на чистом `origin/main`, к задаче не относится

## Результат

## Как проверить
