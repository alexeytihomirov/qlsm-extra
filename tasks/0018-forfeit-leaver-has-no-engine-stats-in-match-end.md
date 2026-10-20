---
id: qlsm-extra-0018
title: Forfeit leaver has no engine stats in match_end
status: in-progress
created: 2026-10-20
updated: 2026-10-20
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

- [ ] Тест: спектатор со счетом получает stats, спектатор без игры - нет
- [ ] Фикс в `_player_summary`
- [ ] Манифест, merge в main, push
- [ ] Обновить плагин на серверах (qlsm, Plugins), проверить на новой тех. победе

## Журнал

- 2026-10-20 - created; причина найдена по данным прода

## Результат

## Как проверить
