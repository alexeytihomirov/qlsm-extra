---
id: qlsm-extra-0014
title: Per-host relay for the demo-stream tunnel and the telemetry sidecar
status: done-unverified
created: 2026-10-16
updated: 2026-10-16
verified:
depends_on: []
related: [root-0023, ql-tournament-0063]
---

# Per-host relay for the demo-stream tunnel and the telemetry sidecar

## Цель

Хост, у которого путь до хаба режется (NN), настраивается в qlsm так, чтобы демо-стрим и телеметрия шли через реле, и повторный Save в qlsm это не ломает.

## Контекст

`root-0023`: из NN режутся TLS и HTTP на нестандартных портах до хаба; поток пущен через socat-реле на germany (443 -> hub:27999, 80 -> hub:8090). До этой задачи адрес реле demo-stream был один на все хосты, и правка `stunnel.conf` на NN вручную перетиралась бы при Save.

## Шаги

- [x] demo-stream 1.6.0: поля хоста `relay_host` / `relay_port` (оба или ни одного), в `stunnel.conf` хоста; статус "demo stream through relay"
- [x] telemetry-relay 1.6.0: поле хоста `forward_url` (`http://host:port`), только в маршрутах сайдкара; вызовы qlsm к хабу на прежнем URL
- [x] Тесты: demo-stream 133 pass, telemetry-relay 82 pass
- [x] Merge, push, обновить аддоны в qlsm, выставить NN: relay `91.99.3.72:443`, forward `http://91.99.3.72:80`, Save

## Журнал

- 2026-10-16 - created; реализовано в ветке `feat/per-host-hub-route`
- 2026-10-16 - `generate_manifest.py` пересобрал и чужие zip (file-forwarder, player-ranks, server-ping) с другими хешами без изменений в коде; откатил их и их хеши, чтобы не было ложного обновления
- 2026-10-16 - `79a0950` в `main`, push; в production qlsm: sync репозитория, install-addon demo-stream и telemetry-relay 1.6.0, рестарт контейнеров qlsm; NN (host 3) сохранён с relay `91.99.3.72:443` и forward `http://91.99.3.72:80`; плейбуки отрисовали `stunnel.conf` и `telemetry-relay.json` с этими адресами, статусы в qlsm показывают реле

## Результат

`79a0950` (demo-stream 1.6.0, telemetry-relay 1.6.0), установлено в production qlsm, NN настроен.

## Как проверить

qlsm -> Hosts -> NijniyNovgorod -> Demo Stream Tunnel: поля реле `91.99.3.72` / `443`, статус "demo stream through relay 91.99.3.72:443". Telemetry Relay: Forward through `http://91.99.3.72:80`, статус "sends through ...". На NN `stunnel.conf` -> `connect = 91.99.3.72:443`, `telemetry-relay.json` -> `http://91.99.3.72:80/api/ingest/telemetry`.
