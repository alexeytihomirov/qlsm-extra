# Host Metrics 1.1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the host-metrics dashboard readable (theme, health board, text findings, hardware, self-explaining charts) and add qlsm core support for addon navbar entries, stored notifications with a bell, and a periodic `poller.tick` hook that host-metrics uses to notify.

**Architecture:** Three generic qlsm core commits on the open upstream PR branch `upstream-pr/host-onboarding-fixes` (PR dngrtech/qlsm#251, operator's decision). host-metrics 1.1.0 in qlsm-extra uses them when present (capability checks) and still loads on a core without them.

**Tech Stack:** qlsm: Flask, SQLAlchemy + Alembic, RQ, React 19 + Tailwind 4 + vitest. qlsm-extra: stdlib Python on hosts, Flask blueprint, React via `window.__qlsm`, uPlot 1.6.31.

**Spec:** `qlsm-extra/docs/superpowers/specs/2026-10-15-host-metrics-v1-1-design.md` (the 1.0 spec still applies where 1.1 is silent).

## Global Constraints

- qlsm work: worktree `D:/QuakeLiveData/QL Server/.qlsm-worktrees/hm-core`, branch `hm-core` created from `origin/upstream-pr/host-onboarding-fixes` (80c47c34). Never touch `C:/Users/hellp/orca/workspaces/qlsm/pr-onboarding` (another session's worktree of that branch) or the shared `D:/QuakeLiveData/QL Server/qlsm` checkout. Commits are generic qlsm features: no mention of host-metrics, no fork-only files, no VERSION / release-notes bump (`skills/qlsm-dev/SKILL.md`).
- qlsm-extra work: worktree `D:/QuakeLiveData/QL Server/.worktrees/qlsm-extra-host-metrics`, branch `host-metrics`.
- UI text English. Theme: only qlsm tokens (`--surface-*`, `--accent-*`, text tokens from `frontend-react/src/index.css`), `.dark` class; no `prefers-color-scheme`.
- Notification severities `info|warning|critical`; dedupe `key`; retention 30 days.
- `poller.tick` dispatched once per status-poller cycle (15 s), handlers isolated, warn when one takes > 10 s.
- host-metrics notifies every 4th tick (60 s); keys `host-metrics:<host_id>:<kind>:<scope>`; notified kinds and severities exactly as spec B6.
- Thresholds shown on charts: CPU 70 % and 95 %, frame tick `tick_ms` and late `1.5 x tick_ms`, steal 5 %, disk 90 %, RAM reserve from settings.
- host-metrics 1.1.0 must load on a core without the new features: `ctx.on('poller.tick')` only if the core knows the hook, `ctx.notify` only if present, `ui.page.nav` only if the core's manifest validator accepts it (check: a core that rejects unknown `page` keys must not mark the addon broken; if it would, gate by `ui_api` level instead and document).
- Tests: only the test files of what a task touches. qlsm: `rtk proxy python -m pytest tests/<files> -q -p no:cacheprovider` and `npx vitest run <files>` in `frontend-react` (node_modules: junction from `D:/QuakeLiveData/QL Server/qlsm/frontend-react/node_modules`, see the qlsm-dev skill). qlsm-extra as in the 1.0 plan; Linux run via WSL before release.
- Commits as the operator, no AI attribution; no push, no merge until the release task.

## Review Focus

1. Old core / new addon and new core / old addon combinations must not break either side (capability checks; `nav` key on an older validator). Test in C3 and H6.
2. Notification flood: an event that flaps, a host that is unreachable for an hour, a qlsm restart - one open notification per key, resolved once, no replay after restart. Test in C2 and H6.
3. A slow or dead host must not stall the poller: the tick handler uses the 5 s parallel snapshot path and its own time budget. Test in H6.
4. Light and dark theme for every new element incl. canvas charts after a live theme switch. Checked in H4 (unit: colour read from tokens) and the release task (screenshots).
5. Findings must never state a number that is not in the data (null-safe; "no data yet" wording). Test in H3.

## Tasks

### Part C - qlsm core (worktree hm-core)

### Task C1: `poller.tick` hook
**Files:** `ui/addons/hooks.py` (HOOK_SCOPES: `'poller.tick': 'global'` with a comment), `ui/cli.py` (dispatch after `poll_all_hosts()` inside the loop, wrapped, duration warning > 10 s), `addons/README.md` (hook list), tests `tests/test_addon_hooks_are_wired.py` (must see the call site) + new `tests/test_poller_tick.py` (dispatch called once per cycle; a raising handler does not stop the loop; slow handler logs a warning - fake clock).
- [ ] Write failing tests; run; implement; run; commit `Add a poller.tick hook for addons`.

### Task C2: stored notifications and the navbar bell
**Files:**
- Backend: `ui/models.py` (`Notification` per spec A2), Alembic migration in `migrations/versions/` (check the single head first: `flask db heads`), `ui/notifications.py` (`notify(source, severity, title, body='', link=None, key=None) -> Notification`, `resolve(source, key) -> int`, prune > 30 days on insert), `ui/addons/context.py` (`ctx.notify(...)`, `ctx.resolve(key)` binding `source=addon_id`), `ui/routes/notification_routes.py` + registration in `ui/__init__.py` (`/api/notifications`, `/<id>/read`, `/read-all`, all `@jwt_required`), backup export/import (`ui/task_logic/backup_export.py`, `backup_import.py`, `backup_db_import.py`: include the table the same way other tables are listed).
- Frontend: `src/services/notifications.js`, `src/components/NotificationBell.jsx` (badge, dropdown last 20, severity colour from tokens, resolved greyed, link via router, "Mark all read", poll 30 s + on focus), mounted in `src/components/Navbar.jsx`.
- Tests: `tests/test_notifications.py` (dedupe by key while open, new row after resolve, resolve by key scoped to source, prune, routes auth + read/read-all, ctx.notify binds source), backup round-trip test next to the existing backup tests, vitest `src/components/__tests__/NotificationBell.test.jsx`.
- [ ] Failing tests; run; implement; run; commit `Store notifications and show them under a navbar bell`.

### Task C3: addon page in the navbar
**Files:** `ui/addons/manifest.py` (`ui.page.nav = {label 1-32, icon from the allow-list}` validated; error messages like the others), catalog payload carries it (where `AddonsContext` gets the list), `frontend-react/src/components/Navbar.jsx` (top-level items for enabled, loaded addons with `page.nav`, after core items, ordered by id), `addons/README.md` (`page.nav`), tests: manifest validation cases (`tests/test_addon_manifest*.py` - find the existing file), vitest Navbar test (item shown only when enabled and loaded).
- [ ] Failing tests; run; implement; run; commit `Let an addon page add a navbar entry`.

### Part H - host-metrics 1.1.0 (worktree qlsm-extra-host-metrics)

### Task H1: hardware
**Files:** `assets/hm_readers.py` (`read_hardware(root="/") -> dict` keys `cpu_model vcpus threads_per_core sockets mhz cache hypervisor sys_vendor product_name provider mem_total swap_total disk_total disk_rotational kernel os boot_time`, every key may be None), `assets/hm_store.py` (table `hardware`, one row JSON, `set_hardware`, `get_hardware`), `assets/hm_collect.py` (read at start and hourly, failures logged once), `assets/hm_query.py` (`snapshot.hardware`), fixtures from germany and one AWS host (read-only `cat` of `/proc/cpuinfo`, `/sys/class/dmi/id/{sys_vendor,product_name}`, `/etc/os-release`, `/sys/block/*/queue/rotational` of the root disk), tests in `tests/test_hm_readers.py`, `test_hm_store.py`, `test_hm_query.py`. Provider map: `Hetzner` (sys_vendor "Hetzner"), `Amazon EC2` ("Amazon EC2"), `Vultr` ("Vultr"), else sys_vendor.
- [ ] Failing tests; run; implement; run; commit.

### Task H2: events since
**Files:** `assets/hm_query.py` (`events --since <unix ts>` returns events opened or closed after it; mutually exclusive with `--range`), `assets/hm_store.py` (`events_changed_since(conn, ts)`), tests.
- [ ] Failing tests; run; implement; run; commit.

### Task H3: findings
**Files:** `ui-src/findings.js` (`findings({snapshot, series, events, settings, range}) -> [{level, area, text}]`; `area` in `cpu|room|frames|steal|memory|disk|data`), `ui-src/findings.test.mjs`. Wording as spec B3; numbers rounded (percent integer, ms integer, GB one decimal); null-safe.
- [ ] Failing tests; run; implement; run; commit.

### Task H4: theme and self-explaining charts
**Files:** `ui-src/panel.css` (tokens only), `ui-src/charts.jsx` (colours from computed tokens, MutationObserver on `<html class>` -> redraw; per chart: title, how-to-read line, direction chip, legend items with current/peak + tooltip, dashed labelled threshold lines, units, empty-state text), buttons via `ctx.ui.Button` where available, `ui-src/theme.js` (+ test: token read + fallback), rebuild.
- [ ] Failing tests (theme.js, threshold computation helper); run; implement; run; build; Node load check; commit.

### Task H5: health board and modal summary
**Files:** `ui-src/Page.jsx` (cards per spec B2: status OK/Watch/Problem/No data from a pure `hostHealth(row, findings)` in `ui-src/data.js`, problems first; top strip with counts and open problems; hardware line; open `?host=<id>` modal on load), `ui-src/HostPanel.jsx` (summary list from findings at the top, one finding line above each chart, hardware block in the header), tests for `hostHealth` and the hardware line formatter.
- [ ] Failing tests; run; implement; run; build; commit.

### Task H6: notifications and navbar entry (1.1.0)
**Files:** `backend.py` (`register`: if the core knows `poller.tick` (check `ui.addons.hooks.HOOK_SCOPES`) subscribe `on_tick`; every 4th tick, if `hasattr(CTX, 'notify')` and setting `notify_enabled`: parallel snapshot (existing path) + `events --since` per enabled host, last check ts in Redis `addon:host-metrics:notify:<host_id>`; open -> `CTX.notify(severity, title, body, link=f"/addons/host-metrics?host={id}", key=...)`, close -> `CTX.resolve(key)`; stale/unreachable > 5 min -> critical, resolved when back; whole tick budget 8 s), `settings.py` + manifest (`notify_enabled` default true, `notify_min_severity` default warning; `ui.page.nav = {"label": "Hosts health", "icon": "gauge"}`), version `1.1.0` everywhere, `README.md`, tests in `tests/test_addon_host_metrics.py` (tick gating, dedupe, resolve on close, no replay after restart, stale -> critical, old core without notify/poller.tick loads fine).
- [ ] Failing tests; run; implement; run; build; manifest; commit.

### Task R: release (controller, operator already OK'd deploy)
- [ ] qlsm: push `hm-core` to `origin upstream-pr/host-onboarding-fixes` (fast-forward), update PR #251 body (three new commits listed), merge the branch into the fork's working branch / `origin/main` per `skills/qlsm-dev/SKILL.md`, run `ql-local/qlsm-tools/check-unpushed.sh`, deploy via qlsm-ci (Woodpecker repo 4, `skills/qlsm-dev/reference/deploy-and-hosts.md`), check the migration ran and the stack is healthy.
- [ ] qlsm-extra: merge + push, install host-metrics 1.1.0, restart, Apply on all 8 hosts (hardware table), verify: bell appears, navbar "Hosts health", board statuses, findings text, hardware lines, both themes (screenshots for the operator), a test notification by forcing a threshold on GermanyHetzner test instance is NOT done without asking.
- [ ] Task file journal, status done-unverified.
