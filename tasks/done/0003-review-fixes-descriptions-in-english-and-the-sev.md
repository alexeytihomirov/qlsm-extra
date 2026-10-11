---
id: qlsm-extra-0003
title: Review fixes: descriptions in English and the eight ranked bugs
status: done-unverified
created: 2026-10-11
updated: 2026-10-11
verified:
depends_on: []
related: [qlsm-extra-0001, qlsm-extra/docs/superpowers/plans/2026-10-11-review-fixes.md]
---

# Review fixes: descriptions in English and the eight ranked bugs

## Цель
Описания всех плагинов и аддонов (README, `*.ql-plugin.json`, `qlsm-repository.json`, `qlsm-addon.json`) на английском, точные и понятные оператору без разработческого контекста. Исправлены восемь ошибок из ревью 2026-10-11, у каждой есть тест.

## Контекст
Ревью `origin/main` (f74474b) четырьмя субагентами 2026-10-11. Восемь ошибок, взятых в работу:
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
- [x] Слито в `main`, запушено, проверено `git ls-remote`

## Журнал
- 2026-10-11 - created; worktree `fix/review-2026-10-11` from origin/main f74474b; работа ведётся субагентами (subagent-driven-development)
- 2026-10-11 - задача 1 (185e75c): описания плагинов и аддонов переписаны на английский, runtime всех записей `minqlxtended`
- 2026-10-11 - задача 2 (6d5128b): `match_restore` экспортирует реальное время подбора предметов
- 2026-10-11 - задача 3 (7697441, c7f6983): zip аддонов собираются детерминированно; `match_restore` применяет скорости из точки один раз
- 2026-10-11 - задача 4 (6f96d72, 52ec808): session feed хранит события до ack, постоянно отклонённые (4xx) отбрасываются
- 2026-10-11 - задача 5 (2267270): `stream_telemetry_unified` не пересылает строки `!rcon` в хаб
- 2026-10-11 - задача 6 (1975460): `chat_rcon` отклоняет строки с разделителями команд
- 2026-10-11 - задача 7 (76dbd67, 8d967df): `tournament_access` проверяет ростер раньше правила specbot; `generate_manifest` берёт label и description из sidecar
- 2026-10-11 - задача 8 (4217301, d9525b9): `qlmatch-packer` логирует SSH и непредвиденные сбои rebuild
- 2026-10-11 - задача 9 (f0166a8): `telemetry-relay` и `demo-stream` возвращают статус инстанса при ошибке включения
- 2026-10-11 - задача 10 (9b71de9, d388195, 01cebd6): `generate_manifest` фиксирует поле host OS в zip (create_system = 3), строка `runtime-source` в README совпадает с описанием аддона; файл задачи и план
- 2026-10-11 - итоговый прогон: 340 passed, 903 warnings; `check_manifest_hashes.py` и `task.py check` чисто
- 2026-10-11 - слит origin/main 7ee029c (demo-stream 1.2.0, stunnel-туннель) в ветку: 96ac658; сброс статуса demo-stream перенесён на 1.2.0 (версия 1.2.1), задача перенумерована в qlsm-extra-0003 (0002 занят задачей туннеля)
- 2026-10-11 - правки итогового ревью: 2893877 relay отдаёт плагину 4xx хаба (кроме 408/429); 6ae786b `*.txt` и `*.j2` с LF в zip; b33c8e6 batch rebuild не глотает таймаут RQ; 94beb8e тексты вкладки Telemetry; c2b45d6 runtime новых записей по умолчанию `minqlxtended`; этот коммит - журнал задачи. Не сделано (follow-up): восстановленные таймеры предметов не отслеживаются после restore
- 2026-10-11 - 904c9af: с demo-stream снята пометка experimental (main в 1.2.0 её уже убрал); scoped re-review фикс-волны и слияния чистый
- 2026-10-11 - слито в main fast-forward и запушено (git ls-remote); не проверено оператором на живом сервере, см. Как проверить

## Результат

Ветка `fix/review-2026-10-11`, слита в `main` fast-forward и запушена 2026-10-11.

- 904c9af docs: demo-stream is no longer marked experimental
- 0774139 tasks: 0003 journal matches the plan
- c2b45d6 generate_manifest: default new plugin entries to minqlxtended
- 94beb8e docs: say what the Telemetry tab does and does not switch on
- b33c8e6 qlmatch-packer: let the job timeout stop a batch rebuild
- 6ae786b chore: normalise txt and j2 line endings in addon packages
- 2893877 telemetry-relay: pass the hub's permanent rejects through to the plugin
- 96ac658 Merge origin/main into fix/review-2026-10-11
- 01cebd6 tasks: 0002 review fixes done
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
- версии аддонов: qlmatch-packer 1.1.2, telemetry-relay 1.3.1, demo-stream 1.2.1 (поверх 1.2.0 из main)

## Как проверить

1. Страница Repositories показывает новые описания и chat_rcon без helper.
2. На тестовом сервере: `!rcon pause; exec x.cfg` от рефери отвечает `chat-rcon: denied: one command per line`; `say !rcon g_password x` не попадает в чат-архив хаба; взять mega, `!restore export` показывает `1 pending`, в JSON есть строка mega с `s:2`; restore, дважды pause и unpause - на втором unpause игроков не толкает; имя `StreamSpec` не из ростера кикается на закрытом сервере.
3. Остановить relay, вызвать `!call`, запустить relay: вызов доходит.
4. Включить телеметрию на инстансе без настроенного stats-hub: статус возвращается к прежнему значению.
