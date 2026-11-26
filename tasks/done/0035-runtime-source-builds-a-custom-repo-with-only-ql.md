---
id: qlsm-extra-0035
title: runtime-source builds a custom repo with only qlsm-python-deps.patch
status: done-unverified
created: 2026-11-26
updated: 2026-11-26
verified:
depends_on: []
related: [https://github.com/alexeytihomirov/qlsm-extra/pull/6]
---

# runtime-source builds a custom repo with only qlsm-python-deps.patch

## Цель

Re-run Host Setup на хосте с runtime-source (форк alexeytihomirov/minqlxtended) не падает на qlsm 1.65: аддон передает `minqlxtended_patches: ["qlsm-python-deps.patch"]`.

## Контекст

qlsm upstream 1.65 (`dngrtech/qlsm` 231b1e63) в `ansible/playbooks/tasks/build_minqlxtended.yml` применяет `minqlxtended_patches` через `patch --forward`, по умолчанию `qlsm-python-deps.patch` + `qlsm-demo-capture.patch`. Форк уже содержит demo capture, второй патч падает ("previously applied", exit 1). Dry run на коммитах форка 527e2f0d и 82165a8e: python-deps применяется чисто, demo-capture падает.

## Шаги

- [x] `host.setup` возвращает `minqlxtended_patches` вместе с custom repo (`addons/runtime-source/backend.py`)
- [x] Проверка в upstream 231b1e63: ключ не в `_RESERVED_SETUP_VARS`, extra vars идут JSON `-e`; в 1.50.4 (dfe63a27) переменная нигде не используется
- [x] Тесты (`tests/test_addon_runtime_source.py`), прогон против 231b1e63 и dfe63a27 (Linux, WSL `qlsm`)
- [x] Версия 1.1.0, README, `packages/runtime-source.zip`, `qlsm-repository.json`
- [x] PR #6, merge в main, `git ls-remote`

## Журнал

- 2026-11-26 - created
- 2026-11-26 - 231b1e63: `_RESERVED_SETUP_VARS` = host_timezone, game_udp_ports, rcon_tcp_ports, runtime; `addon_setup_extravar_args` делает `-e json.dumps(...)` на каждый вклад; standalone core_keys не содержат minqlxtended_patches. dfe63a27 (1.50.4): в playbooks нет `minqlxtended_patches`, лишняя extra-var игнорируется.
- 2026-11-26 - upstream 231b1e63 не импортируется на Windows (`fcntl`, `os.O_NOFOLLOW` в `ui/addons/runtime_protection.py`); тесты гонял в WSL distro `qlsm` с venv `--system-site-packages` + pytest: 32 passed на 231b1e63 и на dfe63a27.
- 2026-11-26 - PR #6 открыт; CI в репо нет, зеленый = локальные тесты выше.

## Результат

runtime-source 1.1.0, PR https://github.com/alexeytihomirov/qlsm-extra/pull/6 (commit 67230d0), смержен в main. На прод не ставился.

## Как проверить

На проде после установки runtime-source 1.1.0 и qlsm 1.65: Hosts -> хост с Runtime Source (custom repo) -> Re-run Host Setup. В логе setup задача "Apply local minqlxtended patches" показывает один item `qlsm-python-deps.patch`, setup завершается успешно.
