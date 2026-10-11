---
id: qlsm-extra-0004
title: demo-stream 1.3.0: per-instance stream delay through the stats-hub API
status: in-progress
created: 2026-10-11
updated: 2026-10-11
verified:
depends_on: []
related: [qlsm-extra-0002]
---

# demo-stream 1.3.0: per-instance stream delay through the stats-hub API

## Цель

У каждого стримящего инстанса в qlsm есть настройка задержки live-стрима (0-300 с, пусто = значение хаба по умолчанию). Аддон `demo-stream` читает и пишет её через API ql-stats-hub. Сохранение - один HTTP-вызов в хаб: `server.cfg` не меняется, инстанс не блокируется и не перезапускается.

## Контекст

Хаб задерживает стрим (по умолчанию 30 с). В хабе параллельно делается API смены задержки на сервер во время работы; контракт зафиксирован заказчиком задачи:

- `GET <stats-hub url>/api/demo-stream/servers/{server_id}/delay`, `Authorization: Bearer <ingest token>` -> 200 `{"ok": true, "server_id": 1, "delay_sec": 30.0, "default_delay_sec": 30.0, "override": false}`; 404 `{"detail": "unknown server_id"}` - у хаба нет маршрута для этого server_id; 401 - неверный токен.
- `PUT` туда же, тело `{"delay_sec": <0..300> | null}` (`null` = вернуть значение хаба по умолчанию) -> тот же 200; 400/422 - значение вне диапазона.
- Хаб без этого API отвечает 404/405.

На стороне qlsm задержка нигде не хранится: источник истины - хаб. `server_id` - тот, что аддон хранит для инстанса (`demo_stream_stats_hub_server_id:<instance_id>`), URL и токен - действующие для хоста инстанса.

UI: декларативная форма (`kind: form`) имеет один submit на панель (`frontend-react/src/components/addons/AddonFormPanel.jsx` в qlsm), поэтому задержка - отдельный пункт меню инстанса "Demo Stream Delay" со своей панелью `instance_delay` и своим бейджем (`status.load`). Поле - `string`, а не `number`: числовое поле в qlsm не может быть пустым (валидатор формы отвечает "Required", пустое значение сериализуется в 0), а пустое значение здесь означает "по умолчанию".

## Шаги

- [x] Тесты (`tests/test_addon_demo_stream_delay.py`): GET по умолчанию и с override, PUT числа, PUT пустого -> `null`, локальная проверка диапазона, не стримит, 404/405 хаба, 401, сетевая ошибка, отсутствие блокировки/смены статуса/задач на PUT
- [x] Эндпоинты `GET/PUT instances/<id>/delay` и `GET instances/<id>/delay/status`
- [x] Манифест: пункт меню инстанса и панель `instance_delay`, версия 1.3.0, описание аддона, README
- [x] `generate_manifest.py`, `check_manifest_hashes.py`, полный прогон тестов
- [ ] Проверка на живом qlsm против хаба с новым API (см. Как проверить)
- [ ] Слито в `main`, запушено, проверено `git ls-remote`

## Журнал

- 2026-10-11 - created; worktree `qlsm-extra-delay`, ветка `feat/demo-stream-delay` от origin/main 5654eb0
- 2026-10-11 - решение: отдельная панель, а не поле в "Live Demo Stream" - у формы один submit, а submit той панели перезапускает инстанс
- 2026-10-11 - решение: поле `string` - тип `number` в форме qlsm не допускает пустого значения
- 2026-10-11 - решение: 404 хаба с `detail: "unknown server_id"` -> 409 "нет маршрута, сохраните Live Demo Stream ещё раз"; любой другой 404/405 -> 502 с обеими причинами (старый хаб либо нет маршрута)
- 2026-10-11 - эндпоинты, манифест 1.3.0, README, пакет пересобран; `tests/`: 457 passed; `check_manifest_hashes.py` чисто. Против живого хаба не проверялось: API хаба ещё в работе

## Результат

Ветка `feat/demo-stream-delay` (не слита, не запушена).

- `addons/demo-stream/stats_hub.py`: `get_server_delay`, `set_server_delay`, `HubDelayError` (таймаут 5 с; токен не попадает ни в сообщения, ни в лог)
- `addons/demo-stream/backend.py`: `GET/PUT instances/<id>/delay`, `GET instances/<id>/delay/status`
- `addons/demo-stream/qlsm-addon.json`: 1.3.0, пункт меню "Demo Stream Delay", панель `instance_delay`
- `README.md`, `qlsm-repository.json`, `packages/demo-stream.zip`
- `tests/test_addon_demo_stream_delay.py`

## Как проверить

Нужны: хаб с API `/api/demo-stream/servers/{id}/delay`, qlsm с установленным `demo-stream` 1.3.0, один инстанс, который уже стримит, и один, который не стримит.

1. Settings -> Repositories -> Sync, обновить `demo-stream` до 1.3.0. В меню инстанса появился пункт "Demo Stream Delay".
2. Стримящий инстанс, открыть "Demo Stream Delay": поле пустое, бейдж "Delay 30 s (hub default)" (число - значение хаба по умолчанию).
3. Ввести `10`, Save: "Saved", бейдж "Delay 10 s (hub default 30 s)". Статус инстанса не менялся (не CONFIGURING), инстанс не перезапускался, в `server.cfg` нет новых строк. На хабе: `GET /api/demo-stream/servers/<id>/delay` отдаёт `delay_sec: 10.0, override: true`.
4. Открытый зритель стрима: при уменьшении задержки (например 30 -> 10) его переподключает, отставание от игры становится около 10 с.
5. Очистить поле, Save: бейдж снова "Delay 30 s (hub default)", на хабе `override: false`.
6. Ввести `301`, затем `abc`: под кнопкой ошибка "delay_sec must be a number of seconds from 0 to 300, or blank for the hub default.", на хаб запрос не уходит.
7. Инстанс, который не стримит: панель открывается, поле пустое, бейдж "Not streaming"; Save с числом -> ошибка "This instance is not streaming yet. Enable it from its Live Demo Stream menu entry first...".
8. По возможности: qlsm против хаба без этого API - панель показывает ошибку "stats-hub answered HTTP 404 ... older than the per-server delay API ... or it has no demo-stream route ..." с кнопкой Retry, стрим при этом работает как раньше.
9. По возможности: неверный Ingest token в Settings -> Demo Stream Stats Hub - ошибка называет настройку Ingest token; самого токена нет ни в ошибке, ни в логе qlsm.
