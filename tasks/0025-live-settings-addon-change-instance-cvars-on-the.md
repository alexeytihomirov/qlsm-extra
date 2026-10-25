---
id: qlsm-extra-0025
title: Live Settings addon: change instance cvars on the fly without a restart
status: in-progress
created: 2026-10-25
updated: 2026-10-25
verified:
depends_on: []
related: [qlsm-extra-0024, qlsm-extra-0016]
---

# Live Settings addon: change instance cvars on the fly without a restart

## Цель

В окне Edit Configuration инстанса есть вкладка Live Settings: список cvar-ов с живым значением (с работающего сервера) и значением из `server.cfg`; изменённые значения уходят на сервер через rcon (`set`) и применяются без рестарта, по желанию дописываются в `server.cfg` и синхронизируются на хост тоже без рестарта.

## Контекст

- Запрос оператора после qlsm-extra-0024: шанс item_roulette меняли через rcon вручную, хочется делать это из qlsm.
- В qlsm уже есть: rcon через Redis и `rcon_service` (zmq DEALER, PLAIN auth, `register`; `qlsm/rcon_service/instance_connection.py`), сохранение конфигов без рестарта (`apply_instance_config(restart=False)` -> статус UPDATED), форма cvar-ов плагина по `.ql-plugin.json` (`qlsm/frontend-react/src/components/fileManager/PluginCvarsModal.jsx`), mount point `instance_tabs` (`qlsm/addons/README.md`), tier-2 компоненты (модель `qlsm-extra/addons/demo-management/`).
- Чего нет: ни одного пути "записать cvar в работающий сервер" из UI настроек; rcon-консоль есть, но это ручной ввод команд.
- Дизайн (согласовывается с оператором, макет: артефакт "Live Settings Mockup"):
  - аддон `live-settings`, scopes global + instance, `ui_api` 3, вкладка `instance_tabs` "Live Settings" (icon `zap`), tier-2 компонент `ui/Panel.js` (таблица с колонками Cvar / Live / server.cfg / New value / State, группы по плагинам, закреплённые серверные cvar-ы, лог последнего apply);
  - backend: `GET instances/{id}/cvars` (cvar-ы плагинов инстанса из sidecar-манифестов пула + закреплённые оператором, значение из `configs/<host>/<id>/server.cfg` по последнему `set`, живое значение одним rcon-запросом), `POST instances/{id}/cvars/apply` (`set name "value"` на каждый, затем чтение обратно; ответ сервера отдаётся как есть, `latched:` помечается), `PUT instances/{id}/pinned`;
  - rcon напрямую из web-процесса через pyzmq (есть в образе), тот же протокол, что в `rcon_service`, своё соединение на запрос, poll ~2 с; `rcon_service` не трогаем;
  - запись в `server.cfg`: upsert последнего `set` в копии qlsm (та же логика, что `serverCfgCvars.js`), затем синк файла на хост без рестарта. Открытый вопрос: через core `apply_instance_config(restart=False)` (статус станет UPDATED, "ждёт рестарта") или собственным playbook аддона (статус не меняется) - решить при реализации.
- Ограничения, которые UI показывает честно: latched cvar-ы (`sv_maxclients` и т.п.) применяются на следующей карте; qlx_-cvar-ы, прочитанные плагином один раз при загрузке, применяются после `!reload` или рестарта; значение без записи в `server.cfg` теряется при рестарте ("live only").

## Шаги

- [x] Согласовать дизайн и макет с оператором.
- [x] Backend: rcon-клиент (pyzmq), чтение cvar-ов, apply, upsert в server.cfg, синк на хост.
- [x] Frontend: tier-2 компонент по макету, сборка `ui/Panel.js` + `Panel.css`.
- [x] Манифест аддона, `generate_manifest.py`, README, тесты (`tests/`).
- [ ] Установить на прод qlsm, проверить на sD test server (item_roulette take chance).
- [ ] Merge в main, push.

## Журнал

- 2026-10-25 - created; изучены rcon-транспорт qlsm, mount point instance_tabs, PluginCvarsModal, apply без рестарта; нарисован макет вкладки.
- 2026-10-25 - оператор принял дизайн и макет; запись в server.cfg через штатный `apply_instance_config(restart=False)` (статус UPDATED), итоговый дифф server.cfg показывается в логе apply и хранится в `data/addons/live-settings/instance-<id>.json` (20 последних).
- 2026-10-25 - реализован аддон `addons/live-settings/`: `rcon_client.py` (своё zmq DEALER/PLAIN соединение на запрос), `cvar_reply.py` (разбор `"name" is:"v^7" default:"d^7" latched:"x"`), `cvar_text.py` (порт serverCfgCvars.js: последний set, seta, без кавычек, unified diff), `catalog.py` (cvar-ы плагинов из sidecar через `ui.plugin_manifest`, pinned из настроек инстанса `pinned_cvars`), `backend.py` (GET cvars, POST cvars/apply, PUT pinned; apply = set + чтение обратно + upsert + enqueue core apply без рестарта), tier-2 `ui-src/Panel.jsx` + `panel.css` (без Tailwind) -> `ui/Panel.js`. Тесты: 16 standalone (cvar_text, cvar_reply), 13 с qlsm (`tests/test_addon_live_settings.py`, rcon замокан), 5 node (`ui-src/rows.test.mjs`) - все зелёные. Открытие: модуль аддона в реестре называется `qlsm_addon_live_settings` и это сам backend.py, патчить нужно `sys.modules[...]`, а не `.backend`.

## Результат

## Как проверить
