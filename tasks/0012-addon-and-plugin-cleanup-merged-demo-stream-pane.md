---
id: qlsm-extra-0012
title: Addon and plugin cleanup: merged demo-stream panel, telemetry menu, player-ranks defaults, file-forwarder VPS key setting, short descriptions
status: in-progress
created: 2026-10-15
updated: 2026-10-15
verified:
depends_on: []
related: [qlsm-extra/docs/superpowers/specs/2026-10-15-addons-cleanup-design.md]
---

# Addon and plugin cleanup: merged demo-stream panel, telemetry menu, player-ranks defaults, file-forwarder VPS key setting, short descriptions

## Цель

Каждый аддон и плагин qlsm-extra делает одну понятную вещь, описан 1-2 фразами, попапы минимальны; тестовое и отладочное удалено; ничего специфичного для нашей установки (IP VPS, его ключи) не зашито в код.

## Контекст

Оператор 2026-10-15: Live Demo Stream и Demo Stream Delay разнесены зря; пройтись по каждому аддону и плагину. Решения по каждому пункту - в spec (`related`). Статус у пункта меню - отдельный upstream PR в qlsm (часть 1 spec).

## Шаги

- [ ] Spec согласован оператором
- [ ] План (writing-plans)
- [ ] Часть 5: удаления плагинов/cvar, file-forwarder 1.2.0 (адрес и ключи VPS в настройках), короткие описания
- [ ] Часть 4: player-ranks 0.4.0 без "on by default", миграция
- [ ] Часть 1: qlsm upstream PR `upstream-pr/addon-menu-status`
- [ ] Часть 2: demo-stream 1.5.0 (одна панель, выключение, один раздел Settings)
- [ ] Часть 3: telemetry-relay 1.5.0 (меню, галочка, выключение)
- [x] Прод: проверка server.cfg на старые cvar телеметрии до удаления fallback
- [ ] Merge в main, push, деплой, проверка оператором

## Журнал

- 2026-10-15 - created
- 2026-10-15 - решения оператора: выключение стрима делаем; удалить chat_rcon_acl, match_restore_lab, qlx_devAuthOpen, debug/legacy telemetry; resync_hold оставить; host-metrics не трогать; per-host override telemetry оставить; telemetry во вкладке -> меню инстанса; статус в меню через upstream PR; file-forwarder - адрес и ключи VPS в настройках ("плагин может использоваться и другими")
- 2026-10-15 - server_id: уже резервируется у stats-hub автоматически; убираем только поле из попапа. Порт и instance.id qlsm не годятся (не уникальны между хостами / установками)
- 2026-10-15 - прод (qlsm-web-1, configs + presets): каждый server.cfg со старым cvar телеметрии задаёт и новый qlx_statsHubFeed* с тем же значением, fallback можно удалять без правки конфигов
- 2026-10-15 - проверено: валидатор манифеста qlsm игнорирует незнакомые ключи у пункта меню, части 2-3 не ломают старый qlsm

## Результат

## Как проверить
