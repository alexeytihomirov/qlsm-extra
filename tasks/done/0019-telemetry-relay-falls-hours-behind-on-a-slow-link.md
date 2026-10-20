---
id: qlsm-extra-0019
title: Telemetry relay falls hours behind on a slow link
status: done-unverified
created: 2026-10-20
updated: 2026-10-21
verified:
depends_on: []
related: [qlsm-extra-0018, ql-stats-hub-0018, root-0023]
---

# Telemetry relay falls hours behind on a slow link

## Цель

Relay телеметрии на хосте не отстает от игры: позиции в хабе живые на любом хосте, включая NN, где все идет через socat на germany.

## Контекст

2026-10-20, хост NijniyNovgorod: `/health` relay показал 323 191 принятых пакетов телеметрии и 239 805 пересланных, `queue_depth_max` 83 729. Приток 8,7 пакета/с, отток 5,9/с, отставание росло ~10 тысяч пакетов в час с перезагрузки хоста 2026-10-19 23:36 UTC. Следствие: хаб показывал позиции игры трехчасовой давности, а результаты игр получали чужих игроков (`ql-stats-hub-0018`).

Причина в `addons/telemetry-relay/assets/relay.py`: один поток, новый TCP-коннект на каждый пакет (`Connection: close`), неограниченная очередь. До VPS через germany каждый пакет ~170 мс.

Попутно: шаг "Copy relay.py" в `addons/telemetry-relay/playbooks/install_telemetry_relay.yml` не вызывал перезапуск, новый код relay не начинал работать при обновлении.

## Шаги

- [x] 2026-10-20 21:34 UTC: `ql-telemetry-relay` на NN перезапущен по команде оператора (QLDS не затронуты), позиции стали живыми
- [x] Тесты: схлопывание по серверу, одно соединение, переподключение, длина/возраст очереди в `/health`
- [x] Фикс relay, notify на копировании relay.py, аддон 1.10.0
- [x] Merge, push (`eb827c1`)
- [x] Аддон 1.10.0 поставлен в qlsm из репозитория, relay разослан на все 8 хостов (`push_relay_config_logic`), `/health` проверен

## Журнал

- 2026-10-20 - created; relay на NN перезапущен; фикс и тесты (`tests/test_relay_telemetry_backlog.py`, `tests/test_relay_forward_status.py`, manifest-тесты аддона)
- 2026-10-20 22:01 UTC - telemetry-relay 1.10.0 установлен в prod qlsm из репозитория qlsm-extra (без рестарта qlsm: изменены только relay.py, playbook и версия)
- 2026-10-20 22:03-22:05 UTC - relay разослан на хосты 1, 3-9; у всех в `/health` есть `telemetry_queue_depth`, очереди 0-1; NN: за 30 с 260 принято, 250 отправлено (было 5,9/с, стало ~8,3/с), 9 схлопнуто; QLDS не перезапускались (время старта `qlds@*` раньше рассылки)

## Результат

Relay держит одно соединение с хабом и при отставании заменяет устаревший снимок сервера в очереди новым; в `/health` видны длина и возраст очереди. Обновление relay через playbook теперь перезапускает сервис. Раскатано на все хосты 2026-10-20.

## Как проверить

На хосте NN: `curl -s http://127.0.0.1:8190/health` - `telemetry_queue_depth` 0-2, `telemetry_queue_oldest_sec` меньше секунды; `telemetry_coalesced` растет, только если канал не успевает.
