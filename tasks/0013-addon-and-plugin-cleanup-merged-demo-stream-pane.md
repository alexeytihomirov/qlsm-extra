---
id: qlsm-extra-0013
title: Addon and plugin cleanup: merged demo-stream panel, telemetry menu, player-ranks defaults, file-forwarder VPS key setting, short descriptions
status: blocked
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

- [x] Spec согласован оператором
- [x] План (writing-plans)
- [x] Часть 5: удаления плагинов/cvar, file-forwarder 1.2.0 (адрес и ключи VPS в настройках), короткие описания
- [x] Часть 4: player-ranks 0.4.0 без "on by default", миграция
- [x] Часть 1: qlsm upstream PR `upstream-pr/addon-menu-status`
- [x] Часть 2: demo-stream 1.5.0 (одна панель, выключение, один раздел Settings)
- [x] Часть 3: telemetry-relay 1.5.0 (меню, галочка, выключение)
- [x] Прод: проверка server.cfg на старые cvar телеметрии до удаления fallback
- [x] Merge в main, push
- [ ] Деплой (Repositories -> Sync, обновить аддоны), проверка оператором

## Журнал

- 2026-10-15 - created
- 2026-10-15 - решения оператора: выключение стрима делаем; удалить chat_rcon_acl, match_restore_lab, qlx_devAuthOpen, debug/legacy telemetry; resync_hold оставить; host-metrics не трогать; per-host override telemetry оставить; telemetry во вкладке -> меню инстанса; статус в меню через upstream PR; file-forwarder - адрес и ключи VPS в настройках ("плагин может использоваться и другими")
- 2026-10-15 - server_id: уже резервируется у stats-hub автоматически; убираем только поле из попапа. Порт и instance.id qlsm не годятся (не уникальны между хостами / установками)
- 2026-10-15 - прод (qlsm-web-1, configs + presets): каждый server.cfg со старым cvar телеметрии задаёт и новый qlx_statsHubFeed* с тем же значением, fallback можно удалять без правки конфигов
- 2026-10-15 - проверено: валидатор манифеста qlsm игнорирует незнакомые ключи у пункта меню, части 2-3 не ломают старый qlsm
- 2026-10-15 - реализация через субагентов, каждая задача с ревью; журнал решений в .superpowers/sdd/2026-10-15-addons-cleanup/progress.md (не в git)
- 2026-10-15 - прод: ssh-keyscan есть в qlsm-web-1 и qlsm-worker-1; ни у одного инстанса нет match_restore_lab / chat_rcon_acl в qlx_plugins; qlx_devAuthOpen нигде не задан; пресет id_tdm2x2 держит оба в checked_plugins.json
- 2026-10-15 - origin/main получил host-metrics 1.1.x и задачу 0012 за время работы: влит в ветку, host-metrics целиком из origin, эта задача перенумерована 0012 -> 0013
- 2026-10-15 - финальное ревью ветки: Critical нет, Important исправлены (8b5f079); ветка готова, merge/push/PR/деплой ждут OK оператора

- 2026-10-15 - оператор: OK. qlsm-extra addons-cleanup -> origin/main d701810 (ls-remote). qlsm: upstream-pr/addon-menu-status запушена в форк (97d3d741); gh pr create в dngrtech/qlsm отказал (fine-grained токен: Resource not accessible), PR открыть руками; ветка влита в main форка bfdb1d63 (конфликты с page.nav: оставлены обе стороны; test_addon_manifest 147, vitest addons 79 зелёные)
- 2026-10-15 - по просьбе оператора menu status добавлен в PR #251 (upstream-pr/host-onboarding-fixes): cherry-pick 9acdf6fb, f2aadf20 поверх e73c44a7, конфликты с page.nav - обе стороны; test_addon_manifest 147, vitest addons 79; описание PR токен менять не может - пункт 10 отдан оператору
- 2026-10-15 - прод после обновления (sqlite read-only): demo-stream 1.5.0, telemetry-relay 1.5.0, player-ranks 0.4.0, file-forwarder 1.2.0 установлены; player-ranks: глобальные on-by-default удалены, инстансы 3-8 получили qlstats+slipgate явно, инстанс 1 свои сохранённые; reserved server ID скопированы у всех 7 инстансов; vps_host в file-forwarder ещё не сохранён (Apply откажет до сохранения адреса); инстансы 1 и 8 делят server_id 1 - было до этой работы

## Результат

Ветка `addons-cleanup` (worktree `.worktrees/qlsm-extra-addons-cleanup`), ещё не в main:
- удалены `chat_rcon_acl`, `match_restore_lab`, `qlx_devAuthOpen`, `qlx_pickupTelemetryDebug`, `qlx_statsHubMatchId`, fallback на старые cvar телеметрии
- file-forwarder 1.2.0: адрес VPS и ключи хоста (ssh-keyscan + отпечаток) в настройках, в коде нет IP
- player-ranks 0.4.0: источники только на вкладке Ranks инстанса, миграция сохраняет текущий вид
- demo-stream 1.5.0: один пункт Live Demo Stream (стрим + задержка), выключение, сохранение чинит рассинхрон, один раздел Settings
- telemetry-relay 1.5.0: Telemetry в меню инстанса, галочка вместо server_id, выключение с сохранением ID
- короткие описания всех аддонов и плагинов, README с release notes
- qlsm: ветка `upstream-pr/addon-menu-status` (0770960c, 97d3d741) в worktree `pr-addon-menu-status`, не запушена

## Как проверить

После деплоя (qlsm-extra в main, Repositories -> Sync, обновить аддоны):
1. File Forwarder: Settings -> Addons -> File Forwarder, ввести адрес VPS, Save; в статусе отпечаток - сверить с консолью Vultr; затем у хоста File Forwarder -> Apply to host проходит.
2. Меню инстанса: один пункт Live Demo Stream (галочка + Delay); смена задержки применяется без рестарта; снятие галочки выключает стрим (рестарт).
3. Меню инстанса: пункт Telemetry с галочкой "Send telemetry", вкладки Telemetry больше нет; в статусе Server ID прежний.
4. Live Status: колонка Rank показывает те же источники, что до обновления.
5. С qlsm, где смёржен PR статуса меню: в выпадающем меню у Live Demo Stream / Telemetry / Demo Stream Tunnel / Telemetry Relay видна точка и короткий статус.
