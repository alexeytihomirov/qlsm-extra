---
id: qlsm-extra-0024
title: item_roulette plugin: pickups randomly give or take
status: in-progress
created: 2026-10-25
updated: 2026-10-25
verified:
depends_on: []
related: []
---

# item_roulette plugin: pickups randomly give or take

## Цель

minqlxtended-плагин: при подборе предмета случайно либо даёт обычный эффект, либо отнимает (RA +100 / -66, оружие: патроны / потеря оружия, патроны: +N / -6, шафт -66). Включается и выключается cvar-ом, что даёт и что отнимает каждый предмет настраивается.

## Контекст

Запрос оператора 2026-10-25 (чат). Факты движка (fork `_build/minqlxtended-fork`, ветка `demo-match-capture`): `item_touch` (гейтед, до подбора, `STOP_EVENT` отменяет касание) и `item_pickup` (после успешного подбора, тот же C-стек, `classname`); `Player.health/armor/weapons/ammo/powerups` читаются и пишутся; `Item(modelindex).quantity/gi_type/gi_tag`. Та же пара хуков уже в `stream_telemetry_unified.py` и `match_restore.py`.

## Шаги

- [x] Дизайн согласован с оператором (формат настроек, охват предметов, пауэрапы-проклятия)
- [x] `item_roulette.py` + `item_roulette.ql-plugin.json`
- [x] Тесты `tests/test_item_roulette.py` (чистые функции) и `tests/test_item_roulette_hooks.py` (touch -> pickup на фейковых объектах движка)
- [x] `generate_manifest.py` (DEFAULT_PLUGINS), `qlsm-repository.json`, README
- [x] merge в main, push, `git ls-remote` (c7ebf83)
- [x] Поставить на `sD test server` (germany, инстанс 1, :27960) - просьба оператора
- [ ] Проверка на живом сервере (в т.ч. рисуется ли EF_TALK-пузырь у проклятой невидимости)

## Журнал

- 2026-10-25 - created; worktree `D:/QuakeLiveData/QL Server/.worktrees/qlsm-extra-item-roulette`, ветка `feat/item-roulette` от main fc8e747
- 2026-10-25 - дизайн: подбор не блокируем, item_touch снимает состояние и бросает монету, item_pickup переписывает результат; пауэрапы при "take" не выдаются, вместо них проклятие на их длительность (квад: возврат части урона жертве 2/3 броня 1/3 хп; батлсьют: доп. урон броня -> хп, пол 1; невидимость: EF_TALK над головой каждый кадр; регена: -1 хп/с; хаста: просто не выдаётся). Урон менять до применения нельзя (хук damage после G_Damage, `hooks.c:634`), убийство необратимо, `slay_with_mod` = суицид - поэтому добивать батлсьют не может
- 2026-10-25 - 34 теста зелёные (`tests/test_item_roulette*.py`); `tests/test_descriptions.py` падает на 4 описаниях demo-stream/telemetry-relay и на чистом main - не наше. Новая запись в `qlsm-repository.json` добавляется руками (generate_manifest берёт список из существующего манифеста, DEFAULT_PLUGINS только для пустого)

- 2026-10-25 00:40-00:45 UTC - `c7ebf83` в `origin/main` (ls-remote). Выкатка на sD test server по рецепту `qlsm-extra-0022`: скрипт `/tmp/qlsm_rollout_roulette.py` на home-docker, запуск в qlsm-web-1 с `PYTHONPATH=/app` (без него `No module named 'ui'`); инстанс был в статусе UPDATED, не RUNNING - скрипт пускает оба; sync репозитория, `download_plugin` в operator pool (`/app/data/shared-plugins/minqlxtended/item_roulette.py`, sha `7acce6a7...`), файл в `configs/GermanyHetzner/1/scripts`, `set qlx_itemRouletteEnabled "1"` в конец `server.cfg`, `item_roulette` в `qlx_plugins`, `apply_instance_config` с рестартом (job `1c9fa81f`). На germany: unit active с 02:43:44 CEST, файл с ожидаемым sha, `item_roulette` в `+set qlx_plugins`, в логе `Loading plugin 'item_roulette'` без ошибок (только штатный шум PluginLoadError хелперов). Хук `item_touch` гейтед - до первого касания предмета игроком плагин ничего не делает; живая проверка за оператором

## Результат

`c7ebf83` feat(item_roulette) в qlsm-extra `main`: `item_roulette.py`, `item_roulette.ql-plugin.json`, тесты, README, `qlsm-repository.json`. Стоит и включён (`qlx_itemRouletteEnabled 1`, остальное по умолчанию: шанс 50 %, RA -66, YA -50, GA -33, шард -2, хп 5/15/33/66, патроны -6 (LG -66), оружие отнимается, пауэрапы - проклятия quad 0.5 / bs 1.5 / regen 1) на sD test server (germany :27960) с 2026-10-25 02:43 CEST.

## Как проверить

На sD test server (germany, :27960, `qlx_itemRouletteEnabled 1`):
1. Зайти, взять RA несколько раз (респаун 25 с): примерно в половине случаев в центре экрана `-66 ARMOR` и броня = прежняя - 66 (не ниже 0); в остальных - штатные +100 без сообщения.
2. Взять RL с RL в руках: при "take" - `LOST ROCKET LAUNCHER`, оружие пропадает, в руках следующее лучшее; без RL - `NO ROCKET LAUNCHER FOR YOU`.
3. Патроны: `-6 ROCKETS` (LG: `-66 ...`), не ниже 0.
4. Квад/батлсьют/невидимость/регена при "take": пауэрап не выдан, сообщение `CURSED ...30s`; у невидимости у второго игрока над головой проклятого виден чат-пузырь (это единственное, что не проверено кодом - если пузыря нет, доложить). Квад-проклятие: урон проклятого по второму игроку в половину; батлсьют: проклятый получает x1.5, но не умирает от добавки.
5. Выключить на лету: rcon `set qlx_itemRouletteEnabled 0` - подборы снова штатные без рестарта.
