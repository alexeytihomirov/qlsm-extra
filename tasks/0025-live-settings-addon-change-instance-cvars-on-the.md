---
id: qlsm-extra-0025
title: Live Settings addon: change instance cvars on the fly without a restart
status: todo
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

- [ ] Согласовать дизайн и макет с оператором.
- [ ] Backend: rcon-клиент (pyzmq), чтение cvar-ов, apply, upsert в server.cfg, синк на хост.
- [ ] Frontend: tier-2 компонент по макету, сборка `ui/Panel.js` + `Panel.css`.
- [ ] Манифест аддона, `generate_manifest.py`, README, тесты (`tests/`).
- [ ] Установить на прод qlsm, проверить на sD test server (item_roulette take chance).
- [ ] Merge в main, push.

## Журнал

- 2026-10-25 - created; изучены rcon-транспорт qlsm, mount point instance_tabs, PluginCvarsModal, apply без рестарта; нарисован макет вкладки.

## Результат

## Как проверить
