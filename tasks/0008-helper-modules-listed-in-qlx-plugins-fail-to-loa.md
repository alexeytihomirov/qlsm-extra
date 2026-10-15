---
id: qlsm-extra-0008
title: Helper modules listed in qlx_plugins fail to load on every server start
status: in-progress
created: 2026-10-15
updated: 2026-10-15
verified:
depends_on: []
related: [root-0014]
---

# Helper modules listed in qlx_plugins fail to load on every server start

## Цель

На игровых серверах в `qlx_plugins` только настоящие плагины; при старте нет ни одного `PluginLoadError`, и помощника нельзя случайно включить снова.

## Контекст

Найдено 2026-10-15 при живой проверке `root-0014` (journald `qlds@27960` на germany, 91.99.3.72). При каждом старте сервера пять модулей падают с `PluginLoadError: The plugin needs to have a class with the exact name as the file, minus the .py.`:

- `chat_rcon_acl`, `match_restore_util`, `qlmatch_packer_cmd`, `stats_hub_pause`, `telemetry_unified_sched`.

Это не плагины, а вспомогательные модули других плагинов (`*.ql-plugin.json` у них: "Helper module for ..., downloaded with it. It is not a plugin: do not add it to qlx_plugins"). Но они стоят в `qlx_plugins` инстанса id 1 `sD test server` (`/home/ql/qlds-27960/baseq3/server.cfg`):

`qlx_plugins "serverchecker, balance, ban, branding, chat_rcon, chat_rcon_acl, clan, essentials, ips, log, match_restore, motd, names, permission, plugin_manager, silence, stream_telemetry_unified, sv_fps, tournament_access, workshop, qlmatch_packer, referee_call, demo_stream_resync_hold, qlmatch_packer_cmd, telemetry_unified_sched, stats_hub_pause, match_restore_util"`

Вред сейчас: шум в логе на каждом старте; сами плагины (`qlmatch_packer`, `stream_telemetry_unified`, ...) грузятся и работают (пакер отработал, `qlmatch-packer finished`). Помощники подтягиваются через `depends_on` своих плагинов.

Не проверено: как они попали в список - вручную в qlsm (галочки в списке плагинов инстанса) или их добавляет сам qlsm при выборе плагина с `depends_on`. Не проверен второй хост (sweden).

## Шаги

- [x] Выяснить, кто добавляет помощники в `qlx_plugins`: оператор вручную или qlsm по `depends_on` (`qlsm` - код выбора плагинов инстанса)
- [ ] Убрать пять помощников из `qlx_plugins` инстанса germany (через qlsm) и проверить sweden
- [ ] Чтобы не повторилось: либо qlsm не предлагает модуль без класса-плагина в списке (метка "do not enable" сейчас только в описании), либо помощники переименовать (например `_chat_rcon_acl.py`) и обновить импорты плагинов - выбрать с оператором (qlsm - форк upstream, правка в нём идёт PR)
- [ ] Проверка: перезапуск инстанса, в journald нет `PluginLoadError`

## Журнал

- 2026-10-15 - created (найдено в `root-0014`, журнал germany)
- 2026-10-15 - причина (по коду qlsm, `frontend-react/src/components/fileManager/pluginSelection.js`): `applyPluginDependencies` кладёт `depends_on`-модули в checked-набор, `toQlxPluginNames` пишет их в `qlx_plugins`. Так попали `match_restore_util`, `qlmatch_packer_cmd`, `telemetry_unified_sched`, `stats_hub_pause`. `chat_rcon_acl` не зависимость ничего - добавлен вручную. Переименование `_name.py` не помогло бы: зависимость всё равно попадает в список
- 2026-10-15 - выбор оператора: PR в upstream qlsm. Ветка `upstream-pr/helper-module-not-enabled` (worktree `C:/Users/hellp/orca/workspaces/qlsm/pr-helper-module`), коммит c5514609: `toQlxPluginNames(checked, tree)` не пишет dependency-only файлы в список. vitest: pluginSelection + EditInstanceConfigModal (85) и addInstance (101) зелёные. PR ещё не открыт

## Результат

## Как проверить

На germany: `journalctl -u qlds@27960 --since "<время перезапуска>" | grep PluginLoadError` - пусто; `!plugins` или лог старта показывает загруженные плагины без помощников.
