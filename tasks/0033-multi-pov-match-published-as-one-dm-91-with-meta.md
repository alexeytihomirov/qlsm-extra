---
id: qlsm-extra-0033
title: Multi-POV match published as one .dm_91 with meta (no .qlmatch)
status: done-unverified
created: 2026-11-20
updated: 2026-11-20
verified:
depends_on: []
related: [root-0041, qlsm-0026]
---

# Multi-POV match published as one .dm_91 with meta (no .qlmatch)

## Цель

Когда движок (форк minqlxtended, `sv_demoMultiPov 1`) пишет на матч один
multi-POV файл `{match_id}_{map}_multipov_{seed}_{n}.dm_91`, packer публикует
его как `<name>.dm_91` + `<name>.meta.json` (v2) + replay-сайдкар, без
`.qlmatch`. file-forwarder везёт эту пару в `qlmatch/`, а не в `raw/`.
Per-client записи (`sv_demoMultiPov 0`) дают `.qlmatch`, как раньше.

## Контекст

- Программа: root-0041 (`tasks/0041-one-multi-pov-demo-per-server-single-dm-91-repla.md`
  в корне монорепо), движок: qlsm-0026.
- Сейчас packer заворачивает multi-POV файл в 1-POV `.qlmatch`, steam id в
  players пустые (у записи нет своего клиента). Пример лога:
  `E:/claude-test/multipov/live2/20261120T031541Z.packer.log`.
- Контракт каталога `qlmatch/` на VPS: `<name>.dm_91`, `<name>.meta.json`
  (format `qlsm-demo-meta`, version 2), `{match_id}_{map}.replay.json.gz`.
  Сайт переводит другой агент.

## Шаги

- [x] pack.mjs: ветка multi-POV (один файл, clientNum >= sv_maxclients или имя `_multipov_`)
- [x] steam id: из самой записи (ключ `st` в CS_PLAYERS), плагин `qlmatch_packer` не меняется (см. Журнал)
- [x] qlmatch-to-replay.mjs: вход `.dm_91`
- [x] forwarder.sh: пара `<name>.dm_91` + `<name>.meta.json` -> `qlmatch/` (keep)
- [x] restore/qlmatch.py: `!restore match list` видит опубликованный multi-POV матч
- [x] тесты, README, версии (qlmatch-packer 1.4.0, file-forwarder 1.3.0), пакеты
- [x] проверка на реальном multi-POV файле с germany (локально, E:)
- [ ] деплой (оператор): обновить аддоны, Apply to host, Update Plugins
- [ ] живой матч на germany: файлы в `qlmatch/` на VPS

## Журнал

- 2026-11-20 - created
- 2026-11-20 - решение: steam id берутся из записи, а не из плагина. В строке игрока
  (configstring CS_PLAYERS) реальной multi-POV записи с germany есть `st` = steam id64
  (проверено на `20261120T025005Z`: оба игрока). Это работает и для ушедших до конца
  (скан всего файла), и при ручном перезапуске packer, без кода на игровом потоке и без
  деплоя плагина.
- 2026-11-20 - pack.mjs публикует `<name>.dm_91` + `<name>.meta.json` v2 + сайдкар; сайдкар
  из `.dm_91` совпадает с сайдкаром из старого 1-POV `.qlmatch` (events равны, отличается
  только `meta.povs[].fileName`).
- 2026-11-20 - forwarder.sh 1.3.0: пара по meta -> `qlmatch/`, meta только после доставки
  `.dm_91`; restore/qlmatch.py: такие матчи в `!restore match list`.
- 2026-11-20 - тесты: packer 30 passed, forwarder.sh 35 passed, file-forwarder addon
  (с QLSM_REPO) - все, кроме 7 давних test_descriptions по чужим аддонам; restore 35 passed.
- 2026-11-20 - слито в main (`9c7d98b`). Ждёт оператора: в qlsm file-forwarder 1.3.0 + Apply to host, затем qlmatch-packer 1.4.0; проверка на живом матче germany

## Результат

Коммиты в ветке `feat/multipov-pack` (worktree
`D:/QuakeLiveData/QL Server/.worktrees/qlsm-extra-multipov-pack`), не смержено, не задеплоено.

## Как проверить

1. Обновить в qlsm аддоны qlmatch-packer (1.4.0) и file-forwarder (1.3.0) из репозитория
   qlsm-extra, плагин `match_restore` (Update Plugins).
2. germany: Update Plugins (доставляет pack.mjs) и File Forwarder -> Apply to host.
3. Сыграть матч с `sv_demoMultiPov 1`. В `/home/ql/qlds-27960/demos/`: `<name>.dm_91`,
   `<name>.meta.json` (version 2, steam_id64 заполнены), `{match_id}_{map}.replay.json.gz`,
   нет `.qlmatch`; в `<match_id>.packer.log` строка `published ... no .qlmatch`.
4. Через 10-15 минут на VPS в `qlmatch/` эти три файла, в `raw/` - ничего от матча.
