---
id: qlsm-extra-0020
title: qlmatch-packer: one impact per explosion, LG wall impacts for every shooter
status: in-progress
created: 2026-10-22
updated: 2026-10-22
verified:
depends_on: []
related: []
---

# qlmatch-packer: one impact per explosion, LG wall impacts for every shooter

## Цель

Сайдкар `{match_id}_{map}.replay.json.gz`, который строит qlmatch-packer
(`addons/qlmatch-packer/assets/vendor/qldemo/`), должен:

1. записывать каждый взрыв (RL, GL) один раз, а не ~5 раз подряд;
2. давать попадания LG (в стену и в игрока) с правильным стрелком для
   каждого игрока и заканчивать синтезированный луч LG в точке попадания,
   а не рисовать его на полные 768 юнитов сквозь стены.

## Контекст

Найдено родителем на реальных данных, игра 249, пак
`20261021T205116Z_duel_f7tortured_k1llsen-PioBe.qlmatch` (VPS сайта,
`/srv/ql-demos/qlmatch/`):

- 864 импакта `kind: "explosion"` при ~176 выстрелах RL+GL, повторы с
  одинаковыми x,y,z через +75/+150/+225/+300 мс (689 точных повторов за 400 мс);
- 814 импактов `kind: "missile", weapon: 6` все с clientNum 0, ни одного для
  clientNum 1 (PioBe), хотя он стрелял из LG;
- комментарий в `demo-to-replay.js` утверждает, что у импактов LG нет поля
  стрелка, а луч LG синтезируется на полную длину, если не задет игрок.

Сайт (`ql-tournament/frontend/public/analytics/js/replay-fx.js`) пока сам
убирает повторы и обрезает луч по импактам `missile`/weapon 6 того же clientNum.

## Шаги

- [x] Найти причину повторов взрывов в коде парсера
- [x] Найти, что на самом деле лежит в демо для попаданий LG (какие события, какие поля)
- [x] Исправить у источника, добавить тесты
- [x] Прогнать конвейер на реальном паке, сравнить до/после
- [x] Версия аддона и манифест по правилам репо
- [ ] Ревью, merge, push, раскатка на хосты (родитель)

## Журнал

- 2026-10-22 - created
- 2026-10-22 - baseline: local run of qlmatch-to-replay.mjs on the real pack gives a sidecar byte-identical to the production one
- 2026-10-22 - cause 1: an exploded missile stays an ET_GENERAL entity carrying EV_MISSILE_MISS/HIT for ~300 ms and collectFxFromEntity emitted it from every snapshot it was in
- 2026-10-22 - cause 2: weapon-6 EV_MISSILE_HIT temp entities are LG hits on a player (otherEntityNum = victim), clientNum is never set (always 0, k1llsen's slot by chance); LG wall hits are EV_MISSILE_MISS temp entities with weapon 0 and no shooter field, 558 of 567 lie within 64 units of a firing LG shooter's aim ray in the same snapshot, both shooters
- 2026-10-22 - fixed in demo-to-replay.js (first sighting per exploded missile; LG hits attributed by aim ray, beams end at the shooter's hit within 50 ms; no synthetic tip marker), merge folds explosions within 325 ms (a POV that sees one late); generator version 12, addon 1.3.3, manifest regenerated; tests pass; real-pack numbers in Результат
- 2026-10-22 - id 0018 был занят (`tasks/done/0018-forfeit-...`), задача перенумерована в 0020; ревью родителя пройдено, merge в main

## Результат

Реальный пак игры 249 (локальный прогон `qlmatch-to-replay.mjs`, до = байт в байт как прод-сайдкар):

| | до (gen 11) | после (gen 12) |
|---|---|---|
| explosion | 864, 689 повторов за 400 мс | 175, 0 повторов (снарядов RL/GL в демо 176, одна граната PioBe без взрыва) |
| попадания LG (`shaft`, сервер) | 0 своих; 319 `missile`/w6 все cn0, 464 `missile`/w0 cn0 | cn0 448, cn1 329; без стрелка остались 8 `missile`/w0 и 2 `missile`/w6 |
| синтетические маркеры на кончике луча | 1571 | 0 |
| лучи LG на полную длину | cn0 328 из 527, cn1 232 из 386 | cn0 30, cn1 33 |

Остальное (позиции, смерти, пикапы, набор лучей по времени и стрелку) не изменилось.

## Как проверить

После раскатки 1.3.3 и пересборки сайдкара игры 249: на сайте луч LG обоих игроков
останавливается на стене, взрыв RL/GL рисуется один раз.
