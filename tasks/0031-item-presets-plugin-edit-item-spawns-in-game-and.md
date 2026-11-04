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
- [ ] Merge в main, push
- [ ] Установка на germany через qlsm (repo sync, download, файл инстанса, cvar, рестарт)
- [ ] Живая проверка: add/remove/replace/move, save/off/load, рестарт; айтем на полу; респаун после подбора

## Журнал

- 2026-11-04 - created
- 2026-11-04 - решения оператора: редактор в игре; пресет = правки к ванили; активный пресет переживает рестарт; Redis хоста; права 3, только разминка; v1: add/remove/replace/move
- 2026-11-04 - spawn_item() в форке = LaunchItem с think=0 (выброшенный айтем), поэтому добавленные айтемы через spawn_entity() (G_SpawnItem, как айтемы карты); spawn_entity есть в .so на germany:27960
- 2026-11-04 - map items freed with remove_entity (hidden powerups come back on respawn, gungame); apply on new_game next frame + 0.5 s
- 2026-11-04 - tests/test_item_presets.py 31 passed; tests/test_descriptions.py: item_presets passes, 7 pre-existing failures of other manifests on origin/main

## Результат

## Как проверить
