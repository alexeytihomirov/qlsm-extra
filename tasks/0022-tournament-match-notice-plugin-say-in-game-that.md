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
- [x] merge, push (37ad70d)
- [x] Только в разминке (оператор): проверка `game.state` в `_announce` (игровой кадр), отсчет больше не объявляется, ожидающее объявление повторяется по `new_game`
- [x] qlsm: синхронизировать репозиторий, скачать плагин, включить с тремя cvar, применить (13 пустых инстансов; Tallin #2 (14) и Moscow #1 (9) - автоматически, когда опустеют)
- [ ] Проверка на живом сервере с двумя игроками матча

## Журнал

- 2026-10-23 - created
- 2026-10-23 - 12 тестов зеленые; `tests/test_descriptions.py` падает на 4 описаниях аддонов (demo-stream, telemetry-relay) и на чистом `origin/main`, к задаче не относится
- 2026-10-23 - оператор: показывать только в разминке; версия 1.1, 14 тестов зеленые
- 2026-10-23 13:44-13:50 UTC - выкатка через qlsm (скрипт в контейнере qlsm-web-1, без штатного маршрута, чтобы не рассылать пул по хостам): sync репозитория qlsm-extra, `download_plugin` в operator pool (sha256 `9e89955e...`), для каждого пустого инстанса - файл в `configs/<host>/<id>/scripts`, три cvar в конец `server.cfg`, `tournament_match_notice` в `qlx_plugins`, `apply_instance_config` с рестартом под instance lock. Пустоту проверял по статусу поллера (свежий, 0 игроков), для Stockholm/Helsinki поллер отставал на ~200 с - перепроверил A2S. Инстансы 1, 11, 12, 15, 16, 22, 13, 10, 21, 19, 20, 17, 18 - RUNNING, задачи успешны. Germany (1): файл с ожидаемым sha, cvar на месте, в логе `Loading plugin 'tournament_match_notice'`, ошибок нет. Tallin #2 (14, hoOp/sano) и Moscow #1 (9, daz/chr) были заняты: на home-docker фоновый `/tmp/wait_empty.sh` (лог `/tmp/wait_empty.log`, до 4 ч) выкатит на них, когда A2S дважды подряд покажет 0 игроков

## Результат

## Как проверить
