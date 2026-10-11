---
id: qlsm-extra-0002
title: Review fixes: descriptions in English and the seven ranked bugs
status: in-progress
created: 2026-10-11
updated: 2026-10-11
verified:
depends_on: []
related: [qlsm-extra-0001, qlsm-extra/docs/superpowers/plans/2026-10-11-review-fixes.md]
---

# Review fixes: descriptions in English and the seven ranked bugs

## Цель
Описания всех плагинов и аддонов (README, `*.ql-plugin.json`, `qlsm-repository.json`, `qlsm-addon.json`) на английском, точные и понятные оператору без разработческого контекста. Исправлены семь ошибок из ревью 2026-10-11, у каждой есть тест.

## Контекст
Ревью `origin/main` (f74474b) четырьмя субагентами 2026-10-11. Семь ошибок, взятых в работу:
1. match_restore export никогда не пишет таймеры предметов (`match_restore.py:2392`, `bundled_pickup=None`).
2. Session feed телеметрии теряет батч при ошибке POST (`stream_telemetry_unified.py:2165`).
3. chat_rcon проверяет только первое слово, строка целиком уходит в консоль (`chat_rcon.py:62-75`).
4. tournament_access пускает ник на `StreamSpec` раньше ростера (`tournament_access.py:209`).
5. Телеметрия пересылает `say !rcon ...` в чат-архив хаба (`stream_telemetry_unified.py:615-618`).
6. match_restore не очищает скорости из точки после применения (`match_restore.py:3867`).
7. qlmatch-packer rebuild ловит только `RebuildError` (`addons/qlmatch-packer/rebuild_tasks.py`).
8. telemetry-relay и demo-stream оставляют сервер в CONFIGURING при `(False, msg)` (`addons/telemetry-relay/backend.py:249`, `addons/demo-stream/backend.py:168`).
Остальные находки ревью (улучшения, оптимизация, фичи) не в этой задаче.

## Шаги
- [x] План в `docs/superpowers/plans/2026-10-11-review-fixes.md`
- [x] Описания на английском обновлены
- [x] Ошибки 1-8 исправлены с тестами
- [x] `generate_manifest.py`, полный прогон тестов
- [ ] Слито в `main`, запушено, проверено `git ls-remote`

## Журнал
- 2026-10-11 - created; worktree `fix/review-2026-10-11` from origin/main f74474b; работа ведётся субагентами (subagent-driven-development)
- 2026-10-11 - задача 1 (185e75c): описания плагинов и аддонов переписаны на английский, runtime всех записей `minqlxtended`
- 2026-10-11 - задача 2 (6d5128b): `match_restore` экспортирует реальное время подбора предметов
- 2026-10-11 - задача 3 (7697441): zip аддонов собираются детерминированно
- 2026-10-11 - задача 4 (c7f6983): `match_restore` применяет скорости из точки один раз
- 2026-10-11 - задача 5 (6f96d72, 52ec808): session feed хранит события до ack, постоянно отклонённые (4xx) отбрасываются
- 2026-10-11 - задача 6 (2267270): `stream_telemetry_unified` не пересылает строки `!rcon` в хаб
- 2026-10-11 - задача 7 (1975460): `chat_rcon` отклоняет строки с разделителями команд
- 2026-10-11 - задача 8 (76dbd67, 8d967df): `tournament_access` проверяет ростер раньше правила specbot; `generate_manifest` берёт label и description из sidecar
- 2026-10-11 - задача 9 (4217301, d9525b9): `qlmatch-packer` логирует SSH и непредвиденные сбои rebuild
- 2026-10-11 - задача 10 (f0166a8): `telemetry-relay` и `demo-stream` возвращают статус инстанса при ошибке включения
- 2026-10-11 - доп.: 9b71de9 `generate_manifest` фиксирует поле host OS в zip (create_system = 3), d388195 строка `runtime-source` в README совпадает с описанием аддона
- 2026-10-11 - итоговый прогон: 340 passed, 903 warnings; `check_manifest_hashes.py` и `task.py check` чисто

## Результат

Ветка `fix/review-2026-10-11`, в `main` пока не слита, не запушена.

- d388195 docs: align the runtime-source row with the addon description
- 9b71de9 generate_manifest: pin the zip host OS field
- f0166a8 telemetry-relay, demo-stream: reset instance status when enabling fails
- d9525b9 Test that qlmatch-packer rebuild failures are logged with kind and traceback
- 4217301 qlmatch-packer: report SSH and unexpected failures from rebuild tasks
- 8d967df generate_manifest: take plugin label and description from the sidecar
- 76dbd67 tournament_access: check the roster before the specbot rule
- 1975460 chat_rcon: reject lines with command separators
- 2267270 stream_telemetry_unified: never forward !rcon chat lines to the hub
- 52ec808 stream_telemetry_unified: resend nothing twice, drop permanently rejected session batches
- 6f96d72 stream_telemetry_unified: keep session events until the relay acknowledges them
- c7f6983 match_restore: apply checkpoint velocities once
- 7697441 chore: build addon zips deterministically
- 6d5128b match_restore: export the real pickup time of taken items
- 185e75c docs: rewrite plugin and addon descriptions for operators

- runtime плагинов во всех записях теперь `minqlxtended`; операторам нужно заново скачать плагины, взятые раньше (см. заметку 4 плана)
- версии аддонов: qlmatch-packer 1.1.2, telemetry-relay 1.3.1, demo-stream 1.1.2

## Как проверить

1. Страница Repositories показывает новые описания и chat_rcon без helper.
2. На тестовом сервере: `!rcon pause; exec x.cfg` от рефери отвечает `chat-rcon: denied: one command per line`; `say !rcon g_password x` не попадает в чат-архив хаба; взять mega, `!restore export` показывает `1 pending`, в JSON есть строка mega с `s:2`; restore, дважды pause и unpause - на втором unpause игроков не толкает; имя `StreamSpec` не из ростера кикается на закрытом сервере.
3. Остановить relay, вызвать `!call`, запустить relay: вызов доходит.
4. Включить телеметрию на инстансе без настроенного stats-hub: статус возвращается к прежнему значению.
