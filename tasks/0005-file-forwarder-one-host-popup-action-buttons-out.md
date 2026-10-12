---
id: qlsm-extra-0005
title: File forwarder: one host popup, action buttons outside the status table
status: in-progress
created: 2026-10-12
updated: 2026-10-12
verified:
depends_on: []
related: [root-0012, docs/superpowers/specs/2026-10-11-file-forwarder-addon-design.md]
---

# File forwarder: one host popup, action buttons outside the status table

## Цель

В меню хоста один пункт File Forwarder, который открывает один попап: переключатель хоста, статус форвардера и кнопки действий. Действия - кнопки вне таблицы, горизонтальной прокрутки в попапе нет.

## Контекст

Запрос оператора 2026-10-12. В 1.0.0 у хоста два пункта меню: `File Forwarder` (форма с переключателем) и `File Forwarder Sync` (таблица статуса). Таблицу рисует ядро qlsm (`frontend-react/src/components/addons/AddonTablePanel.jsx`): `row_actions` выводятся текстовыми ссылками в последней ячейке с `whitespace-nowrap`, поэтому три действия (самое длинное - "Sync now and delete delivered") распирают таблицу и появляется горизонтальная прокрутка. Декларативная панель (tier 1) не умеет ни форму вместе с таблицей, ни кнопки вне таблицы, поэтому нужен собственный компонент аддона (tier 2, `renders: "modal"`, `ui_api` 3).

## Шаги

- [x] Дизайн согласован с оператором (2026-10-12: статус таблицей, страницу настроек тоже поправить)
- [x] `ui/HostPanel.js`: попап хоста (переключатель, таблица статуса, кнопки)
- [x] `ui/PublicKey.js`: секция SFTP-ключа без таблицы
- [x] Манифест: один пункт `host_menu`, `ui_api` 3, версия 1.1.0, описание
- [x] Тесты манифеста и пакета обновлены, pytest зелёный
- [x] `generate_manifest.py`, README аддона
- [x] Влито в main, запушено
- [ ] Обновлён в боевом qlsm, попап и настройки проверены вживую

## Журнал

- 2026-10-12 - created; worktree D:/QuakeLiveData/QL Server/.worktrees/qlsm-extra-ff-host-popup, branch file-forwarder-host-popup from origin/main 3b8b228
- 2026-10-12 - design sent to the operator (tier-2 hand-written component without a build step)
- 2026-10-12 - operator: design ok, status stays a table, the addon settings page scrolls sideways too. Cause there: the public key table (one unbreakable ~100 char cell); replaced by a tier-2 section component
- 2026-10-12 - implemented; queued message of apply/sync/purge is now also inside `data` (ctx.api returns only that key; the `raw` option is newer core and was avoided); full qlsm-extra suite 635 passed before that change, file-forwarder tests 126 passed after; both components rendered in jsdom with real React and a stub UI kit (11 checks: one table, 4 cells, no buttons in it, actions, switch, refresh). Not verified: the look inside a real qlsm (no local qlsm stand)
- 2026-10-12 - a host shows "outdated, addon is 1.1.0" after the addon update until Apply to host (the host script itself did not change)

## Результат

Аддон `file-forwarder` 1.1.0 в origin/main `qlsm-extra`. В меню хоста один пункт File Forwarder: попап с переключателем, таблицей статуса фиксированной ширины (длинная строка Last run переносится) и кнопками Apply to host, Sync now, Sync now and delete delivered, Refresh под таблицей. В настройках аддона секция SFTP-ключа показывает ключ переносимым блоком с кнопкой Copy. В боевой qlsm не установлен.

## Как проверить

- qlsm: Settings -> Repositories -> Sync, у File Forwarder нажать Update (1.1.0), перезапустить qlsm.
- Меню хоста Germany: один пункт File Forwarder; в попапе нет горизонтальной прокрутки, кнопки под таблицей; Sync now показывает "Sync queued for ...", после Refresh меняется Last run.
- Addons -> шестерёнка File Forwarder: нет горизонтальной прокрутки, ключ читается целиком, Copy копирует строку.
- State будет "outdated, addon is 1.1.0", пока не нажать Apply to host.
