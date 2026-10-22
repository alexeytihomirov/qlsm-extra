---
id: qlsm-extra-0021
title: Session and item events carry the plugin clock sample_wall_ms
status: done-unverified
created: 2026-10-22
updated: 2026-10-22
verified:
depends_on: []
related: [root-0030]
---

# Session and item events carry the plugin clock sample_wall_ms

## Цель

Session-события (lifecycle, death, chat, ...) и подборы предметов от `stream_telemetry_unified.py` несут `sample_wall_ms` - время `time.time()` игрового хоста в момент хука (int, мс), те же часы, что у позиций. Хаб ставит их на шкалу позиций вместо времени приема (убирает разброс ±50-100 мс). Вариант D из `root-0030`.

## Контекст

- Позиции уже несут `sample_wall_ms` на верхнем уровне payload (`stream_telemetry_unified.py`, `_send_positions`).
- Теперь ключ лежит на верхнем уровне каждого события в `events[]`: рядом с `game_time_ms` у session-событий (`_enqueue_session`, `_enqueue_lifecycle`) и рядом с `game_time` у item-событий (`_on_item_event_inner`). Время берется один раз на событие (один хук - одна строка).
- Relay (`addons/telemetry-relay/assets/relay.py`, `_enrich_forward_body`) пересылает тело как есть, добавляя только поля верхнего уровня (`server_id`, `match_id`, `server_name`, `server_address`); `events[]` не трогает. Код relay не менялся, версия 1.10.0 остается.
- Хаб: pydantic-модели `SessionEventIn` и `ItemEventIn` (`ql-stats-hub/stats_hub/models.py`) молча отбрасывают неизвестные ключи, так что без правки хаба поле просто игнорируется. Хабу надо добавить `sample_wall_ms: int | None = None` в обе модели (делает другой агент в `root-0030`).
- Плагины в этом репозитории без версии: обновление определяется по sha256 в `qlsm-repository.json`.

## Шаги

- [x] `sample_wall_ms` в строках session- и item-событий
- [x] Тесты `tests/test_telemetry_event_sample_wall.py` (плагин + сквозной relay)
- [x] Манифест, merge в main, push
- [x] Выкатка плагина на хосты (родительская сессия `root-0030`)

## Журнал

- 2026-10-22 - created
- 2026-10-22 - сделано: поле в трех местах плагина, README, манифест (zip-пакеты не изменились). Тесты: `tests/test_telemetry_event_sample_wall.py` и соседние тесты плагина и relay - 87 passed (с `QLSM_REPO`)
- 2026-10-22 14:44-15:07 UTC - выкатка через qlsm: sync репозитория qlsm-extra, `download_plugin` (sha256 `290663b8571c...`) в operator pool и `download_addon` qlmatch-packer 1.3.3 (задача `0020`), рестарт qlsm web/worker-1..5/poller; затем `apply_plugin_updates_task` по хостам 1, 3, 4, 5, 6, 7, 8, 9 (общий пул + файл в `configs/<host>/<inst>/scripts` + рестарт только пустых инстансов), пакер - только плейбук аддона `sync_qlmatch_packer.yml` по каждому хосту (`apply_plugin_updates_task` не вызывает `host.payload_sync`). Moscow #2 шла игра - выкачен в 15:05 после ее конца. Рестарты NN #1/#2 и Frankfurt #1/#2 упали по 120 с таймауту плейбука (инстанс ERROR), повторены по одному через `restart_instance`. Итог: все 15 инстансов RUNNING, в каждом `minqlxtended-plugins` новый файл, в логе `Loading plugin 'stream_telemetry_unified'` и `active match_id=server-N` после рестарта, на всех 8 хостах пакер с `MATCH_REPLAY_GENERATOR_VERSION = 12`, телеметрия всех 14 server_id идет в хаб (`/api/health` 15:07 UTC)

## Результат

Каждое session-событие и каждый подбор несут int `sample_wall_ms`. Relay пропускает поле без изменений.

## Как проверить

1. Выкатить `stream_telemetry_unified.py` из репозитория qlsm-extra на инстанс (см. выкатку в `tasks/done/0018-forfeit-leaver-has-no-engine-stats-in-match-end.md`).
2. Сыграть короткий матч.
3. В записи хаба (после правки хаба) у `match_start`, `death`, `pickup` время `t` выровнено по часам позиций; до правки хаба - в логах ingest или дампе запроса видно `sample_wall_ms` в `events[]`.
