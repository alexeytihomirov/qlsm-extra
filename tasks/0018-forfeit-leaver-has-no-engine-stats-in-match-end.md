---
id: qlsm-extra-0018
title: Forfeit leaver has no engine stats in match_end
status: in-progress
created: 2026-10-20
updated: 2026-10-21
verified:
depends_on: []
related: [docs/superpowers/specs/2026-10-15-tournament-player-stats-design.md]
---

# Forfeit leaver has no engine stats in match_end

## Цель

При технической победе (игрок ушел в спектаторы, игра прервана) у ушедшего игрока на `/games` видны полная статистика (урон, броня, оружие), а не только убийства и смерти.

## Контекст

Сообщение оператора 2026-10-20 со скриншотом игры `f7tortured` Redragon | AGENT 11 : 7 daz: у daz только убийства и смерти, остальное "-".

Проверено на проде (`https://frontiersgaming.com/api/public/games?player=daz`): игры 107, 109, 111, 114 (все `end_reason: abort`, результат forfeit) - у проигравшего `stats: null`, при этом `kills/deaths` есть. В обычных играх (112, 113) stats есть у обоих.

Причина: `stream_telemetry_unified.py` в `_player_summary` читает `expanded_stats` только у не-спектаторов. Ушедший в спектаторы игрок остается в списке игроков (score/kills/deaths у него читаются из того же `client->expandedStats`, `_build/minqlxtended-fork/src/python/python_embed.c:1308`), но stats ему не пишутся. Сайт (`ql-tournament/app/services/public_games.py`, `_players`) в forfeit уже показывает спектатора со строкой счета, фронт (`ql-tournament/frontend/src/components/public/GameStats.jsx`) рисует "-" для `stats: null`.

## Шаги

- [x] Тест: спектатор со счетом получает stats, спектатор без игры - нет
- [x] Фикс в `_player_summary`
- [x] Манифест, merge в main, push
- [x] Снимок строки и stats в момент ухода (`team_switch_attempt`, `player_disconnect`), подстановка в match_end
- [ ] Обновить плагин на серверах (qlsm, Plugins) - вне идущих матчей
- [ ] Проверить на новой тех. победе

## Журнал

- 2026-10-20 - created; причина найдена по данным прода
- 2026-10-20 - фикс `96b737b` в `origin/main` (тесты `tests/test_telemetry_player_stats.py`, `tests/test_telemetry_winner.py`: 14 passed); на серверы не выкатывал - ждет оператора

- 2026-10-21 - оператор: статистика ушедшего все еще неполная. Проверено: исправленный плагин (`96b737b`) лежит на всех хостах с 2026-10-20 16:31 UTC, но в match_end всех технических побед 2026-10-20 у ушедшего строка 0/0/0 (`spectator`). Предположение выше неверно: к game_end движок уже обнулил и счет, и expandedStats ушедшего (у daz 7/11 на сайте были из ленты фрагов хаба, не из match_end). NN QLDS работал со старым плагином до рестарта 2026-10-20 21:16 UTC, но и новый не помог бы
- 2026-10-21 - фикс: плагин снимает строку и stats игрока до смены команды (`team_switch_attempt` из SetTeam, до перемещения) и при отключении (`player_disconnect`, до SV_DropClient), только пока идет матч; в match_end ушедший - зритель со снятыми строкой и stats, отключившийся добавляется зрителем. Тесты `tests/test_telemetry_player_stats.py` и соседние: 59 passed

## Результат

`_player_summary` читает `expanded_stats` и у спектатора, если у него есть счет, убийства или смерти. Старые игры (107, 109, 111, 114) не исправить: stats тогда не отправлялись.

## Как проверить

1. В qlsm обновить `stream_telemetry_unified.py` из репозитория qlsm-extra на игровых инстансах.
2. Сыграть дуэль, один игрок уходит в спектаторы (`team s`) после пары фрагов.
3. `https://frontiersgaming.com/games` - открыть статистику этой игры: у ушедшего есть урон, броня и строки оружия, а не "-".
