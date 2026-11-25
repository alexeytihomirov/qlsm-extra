---
id: qlsm-extra-0034
title: Multi-POV published names match the .qlmatch base; forwarder 1.3.1 resends raw-ledgered pack demos to qlmatch/
status: in-progress
created: 2026-11-25
updated: 2026-11-25
verified:
depends_on: []
related: [qlsm-extra-0033, ql-tournament-0217]
---

# Multi-POV published names match the .qlmatch base; forwarder 1.3.1 resends raw-ledgered pack demos to qlmatch/

## Цель

Опубликованный multi-POV матч называется ровно как был бы назван его `.qlmatch`:
`<name>.dm_91` + `<name>.meta.json`, `<name>` - шаблон `qlx_qlmatchNameTemplate`
(на germany `{match_id}_{gametype}_{map}_{players}`), без суффикса `_multipov`.
Сайдкар остаётся `{match_id}_{map}.replay.json.gz`. Каждая такая пара на хосте
доезжает до `qlmatch/` на VPS, в том числе `.dm_91`, которые до file-forwarder
1.3.0 уже ушли в `raw/`.

## Контекст

Оператор 2026-11-25: имена multi-POV демо отличаются от имён `.qlmatch`.
Правило имени согласовано с ql-tournament-0217 (миграция на сайте) и ботом:
ровно база `.qlmatch`, без `_multipov`.

Проверка кода: `addons/qlmatch-packer/assets/pack.mjs` с 1.4.0 (qlsm-extra-0033)
именует и `.qlmatch`, и опубликованный `.dm_91` одним `renderName(template, ctx)`;
`{players}` для multi-POV берётся из самой записи, на реальной записи с germany
(`E:/claude-test/multipov/live2/`) - те же игроки, что и в gamestate. На VPS
(91.99.3.72, данные ql-tournament-0217) 41 файл 1.4.0 от 23.11 уже назван по
правилу. Отличаются только сырые файлы движка `{match_id}_{map}_multipov_*.dm_91`,
их packer не публикует. `{match_id}.meta.json` - v1 для экрана Demos, не
пересылается.

Реальная проблема - file-forwarder 1.3.0: ключ ledger (name, size, mtime) не
знает каталога. `.dm_91`, отправленный 1.2.0 в `raw/` до Apply 1.3.0, 1.3.0
считал доставленным и слал в `qlmatch/` только meta (на VPS 41 meta без демо).
Новые пары 1.3.0 маршрутизирует верно.

## Шаги

- [x] сравнить имена `.qlmatch` и опубликованного `.dm_91` в pack.mjs - совпадают, код не менять
- [x] тест на совпадение имён (`tests/test_packer_multipov.py`)
- [x] forwarder.sh: 5-я колонка ledger `PACK_DIR` у pack-файлов, доставкой в `qlmatch/` считается только она
- [x] тесты forwarder (`tests/test_forwarder_sh.py`), версия 1.3.1, пакет, README
- [ ] PR, проверки зелёные
- [ ] оператор: обновить file-forwarder 1.3.1 в qlsm, Apply to host на germany

## Журнал

- 2026-11-25 - created
- 2026-11-25 - pack.mjs: имя multi-POV = база .qlmatch уже с 1.4.0; подтверждено ql-tournament-0217 на VPS (41 файл)
- 2026-11-25 - найдено: forwarder 1.3.0 пропускает .dm_91, ledgered 1.2.0 как raw; исправлено в 1.3.1 (5-я колонка ledger)

## Результат

Ветка `alexeytihomirov/houndshark`, PR в main (не смержен). qlmatch-packer без
изменений (1.4.0). file-forwarder 1.3.1: `addons/file-forwarder/assets/forwarder.sh`.

## Как проверить

1. qlsm: Settings -> Addons -> обновить file-forwarder до 1.3.1 из репозитория
   qlsm-extra, затем File Forwarder -> Apply to host на germany.
2. После следующего запуска таймера (каждые несколько минут) на VPS в
   `qlmatch/` рядом с каждым из 41 `<name>.meta.json` от 23.11 лежит
   `<name>.dm_91`, например `20261123T203710Z_duel_monsoon_a3-Steemorol.Frontier.dm_91`.
3. На germany в `/home/ql/.forwarder-state/delivered.tsv` у этих `.dm_91` есть
   строка с 5-й колонкой `qlmatch`.
