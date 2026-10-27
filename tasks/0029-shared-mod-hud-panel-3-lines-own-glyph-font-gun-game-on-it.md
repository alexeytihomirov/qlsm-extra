---
id: qlsm-extra-0029
title: Shared mod HUD panel (3 lines, own glyph font), Gun Game on it
status: in-progress
created: 2026-10-27
updated: 2026-10-27
verified:
depends_on: []
related: [root-0036, qlsm-extra-0027, docs/superpowers/specs/2026-10-27-mod-hud-panel-design.md]
---

# Shared mod HUD panel (3 lines, own glyph font), Gun Game on it

## Цель

Одна плашка на 3 строки в 9 местах экрана, которой пользуется любой наш плагин: текст и иконки-символы присылает сервер, место выбирает игрок. Gun Game показывает свой HUD через неё. Клиентская часть - один pk3 (меню + запасной шрифт с нашими символами).

## Контекст

Возможности и ограничения проверены в `root-0036` (`skills/ql-live/reference/server-driven-hud-and-view.md`): cvar'ы с сервера через `cs`, UTF-8 символы, свой запасной шрифт из pk3 в папке установки, автоочистка через `onOpen` у `joingame_menu`. Дизайн согласован с оператором 2026-10-27: `docs/superpowers/specs/2026-10-27-mod-hud-panel-design.md` (в этом репозитории).

## Шаги

- [x] Дизайн согласован в чате
- [ ] Spec написан и одобрен оператором
- [ ] План реализации
- [ ] Реализация (helper, plugin, builder, Gun Game)
- [ ] Живая проверка на #26
- [ ] Workshop-тест (отдельно, позже)

## Журнал

- 2026-10-27 - created. Branch `feat/modhud` from `origin/main` (b54f55b; local `main` was 42 behind, Gun Game HUD already on origin/main), worktree `D:/QuakeLiveData/QL Server/.worktrees/qlsm-extra-modhud`.

## Результат

## Как проверить
