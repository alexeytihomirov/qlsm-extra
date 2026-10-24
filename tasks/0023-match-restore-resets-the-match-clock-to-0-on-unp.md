---
id: qlsm-extra-0023
title: match_restore resets the match clock to 0 on unpause
status: in-progress
created: 2026-10-24
updated: 2026-10-24
verified:
depends_on: []
related: []
---

# match_restore resets the match clock to 0 on unpause

## Цель

Обычные `pause` / `unpause` (в том числе `!pause` / `!unpause` из essentials) не меняют время матча: таймер после паузы продолжается с того же места, timelimit не начинается заново.

## Контекст

2026-10-24, Frankfurt #2 (`18.195.127.110:27961`), Frontier One Map Cup #1, Playoffs Round 2, k1llsen vs Radist, вторая игра (match_guid `2c5723a2-7ac6-4299-8751-165ebd88bb4c`). `!pause` на 3:15, затем `unpause`; время матча стало 0:00, radist сдался.

Из `/home/ql/qlds-27961/minqlxtended.log` (время хоста, UTC+2):

```
(15:16:33) match_restore: pause snap frozen_ms=0
(15:17:11) match_restore: unpause clock thaw frozen_ms=0 map_t=84665825 start_t=84665825 eng=engine_elapsed=0ms
(15:17:16) match_restore: unpause clock thaw frozen_ms=0 map_t=84670375 start_t=84670375 eng=engine_elapsed=0ms
```

Механизм: `_resync_match_clock_after_unpause` на каждом unpause писал в движок `level.start_time = level.time - frozen`. Время паузы плагин брал из своей привязки к времени карты (`_match_start_map_time`), а не из движка, и в этой игре получил 0 (вторая пауза: 4225 мс вместо ~93 с). Почему привязка была пустой, по логам не установлено; тест с пустой привязкой воспроизводит ровно `frozen_ms=0`.

QL сам сдвигает `level.start_time` на паузах (`skills/ql-live/reference/demos.md`, cs 13), поэтому для обычной паузы запись в движок не нужна.

## Шаги

- [x] Найти матч и причину по логам stats-hub и сервера
- [x] Тесты, воспроизводящие инцидент (`tests/test_match_restore_pause_clock.py`)
- [x] Фикс: движок пишется на unpause только после restore; время матча при live-матче читается из движка (`level.time - level.start_time`)
- [x] Merge в `main`, push
- [ ] Обновить плагин на серверах через qlsm
- [ ] Проверка на живом сервере: пауза в идущем матче, unpause, таймер продолжается

## Журнал

- 2026-10-24 - created
- 2026-10-24 - причина найдена по `minqlxtended.log` на Frankfurt; запись `level.start_time` при `frozen_ms=0` в `_resync_match_clock_after_unpause`
- 2026-10-24 - фикс + 4 теста; `tests/test_match_restore_*.py` зелёные (14 passed); манифест пересобран
- 2026-10-24 - `b8da09b` в `origin/main` (rebase на свежий main, тесты и манифест перепроверены). Выкатка на инстансы ждёт OK оператора: на серверах есть игроки

## Результат

`b8da09b` fix(match_restore): leave the engine match clock alone on a plain unpause (qlsm-extra `main`). На серверы ещё не выкачено.

## Как проверить

На сервере с обновлённым `match_restore`: запустить duel, на ~1:00 `!pause`, через 20 с `!unpause`. Таймер продолжается с ~1:00, в `minqlxtended.log` строка `unpause clock thaw frozen_ms=<около 60000> ... eng=engine untouched`.
