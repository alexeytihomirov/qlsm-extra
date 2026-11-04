---
id: qlsm-extra-0031
title: Item presets plugin: edit item spawns in game and save layouts per map
status: in-progress
created: 2026-11-04
updated: 2026-11-04
verified:
depends_on: []
related: [qlsm-extra/docs/superpowers/specs/2026-11-04-item-presets-design.md, qlsm-extra-0027]
---

# Item presets plugin: edit item spawns in game and save layouts per map

## Цель

Админ в разминке добавляет, убирает, заменяет и двигает айтемы карты прямо в игре, сохраняет раскладку как пресет карты и включает/выключает пресеты для тестов баланса. Ванильная карта не меняется.

## Контекст

Запрос оператора 2026-11-04. Дизайн согласован в чате, спека `qlsm-extra/docs/superpowers/specs/2026-11-04-item-presets-design.md`. Тестовый сервер: germany `sD test server` (qlsm host 1, instance 1, 91.99.3.72:27960).

## Шаги

- [x] Дизайн согласован, спека
- [x] `item_presets.py` + sidecar + тесты (31)
- [x] Запись в `qlsm-repository.json`, строка в README
- [x] Merge в main, push
- [x] Установка на germany через qlsm (repo sync, download, файл инстанса, cvar, рестарт)
- [ ] Живая проверка: add/remove/replace/move, save/off/load, рестарт; айтем на полу; респаун после подбора

## Журнал

- 2026-11-04 - created
- 2026-11-04 - решения оператора: редактор в игре; пресет = правки к ванили; активный пресет переживает рестарт; Redis хоста; права 3, только разминка; v1: add/remove/replace/move
- 2026-11-04 - spawn_item() в форке = LaunchItem с think=0 (выброшенный айтем), поэтому добавленные айтемы через spawn_entity() (G_SpawnItem, как айтемы карты); spawn_entity есть в .so на germany:27960
- 2026-11-04 - map items freed with remove_entity (hidden powerups come back on respawn, gungame); apply on new_game next frame + 0.5 s
- 2026-11-04 - tests/test_item_presets.py 31 passed; tests/test_descriptions.py: item_presets passes, 7 pre-existing failures of other manifests on origin/main
- 2026-11-04 - pushed to origin/main 70d1497 (ls-remote checked)
- 2026-11-04 - installed on germany instance 1 (sD test server :27960) via qlsm in qlsm-web-1 (script in session scratchpad `ip_deploy.py`): repo sync, download_plugin to the pool (sha d6894bef = manifest), file + sidecar into configs/GermanyHetzner/1/scripts, `set qlx_itemPresetsEnabled "1"` appended to server.cfg, `item_presets` appended to instance.qlx_plugins, apply_instance_config with restart (job f1b579f8). qlds@27960 active since 02:04:31 CET, `Loading plugin 'item_presets'` without errors, host file sha d6894bef, rcon: qlx_itemPresetsEnabled 1, qlx_itemEditPerm 3, map f7tortured. Server was empty (warmup, 0 players). Waiting for the operator's live round

## Результат

- qlsm-extra `70d1497` item_presets: plugin, sidecar, 31 tests, repository entry, README row, spec.
- germany instance 1 (91.99.3.72:27960): installed and enabled.

## Как проверить

На `91.99.3.72:27960` в разминке, с правами minqlx 3+:
1. Встать у MH -> `!item remove`; встать в пустом месте -> `!item add ra`; у YA -> `!item replace ra`; у RL -> `!item move`, перейти, `!item move`. `!item list` показывает правки.
2. `!preset save test1` -> `!preset off` (рестарт, ваниль) -> `!preset load test1` (рестарт, правки вернулись) -> `callvote map_restart` или `!preset load test1` ещё раз -> правки на месте.
3. Добавленная RA лежит на полу, после подбора респаунится (засечь время).
