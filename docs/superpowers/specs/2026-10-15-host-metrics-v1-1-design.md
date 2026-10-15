# Host metrics 1.1: readable dashboard, hardware, notifications - design

Date: 2026-10-15. Follows `2026-10-15-host-metrics-addon-design.md` (1.0, released on GermanyHetzner the same day). Operator feedback on 1.0, decisions taken with the operator:

| Feedback | Decision |
|----------|----------|
| Text buttons ignore the light/dark theme | Use qlsm's own theme tokens |
| Need one page that says per host whether all is OK | Health board page, reachable from the **navbar** (qlsm PR) |
| Charts are hard to read; say it in words; problems into notifications | Text findings per host and per chart; a **notification bell in qlsm** (qlsm PR) |
| No CPU model, cores, what hardware it is | Hardware block per host |
| Legends with hints, a visible limit, "lower is better" | Chart legend with explanations, threshold lines, direction hints |
| Language | English, like the rest of qlsm |

## Verified facts this design rests on

- Theme: qlsm toggles a `.dark` class (`frontend-react/src/index.css:2`, `@custom-variant dark`) and defines tokens on `:root` and `.dark`: `--surface-base/raised/overlay/elevated/border`, `--accent-primary/danger/warning/info`, text tokens (`index.css:12-80`).
- Notifications: qlsm has transient toasts only (`components/NotificationProvider.jsx`, exposed to addons as `ctx.ui.useNotification`); no stored notifications, no bell (`components/Navbar.jsx` has none).
- Navbar: fixed entries; addons appear only as one "Addons" item (`Navbar.jsx:136-140`); an addon `page` is routed at `/addons/:addonId` (`App.jsx:55`).
- Periodic work: the status poller (`ui/cli.py`, `run-status-poller`, every 15 s, one process) is the only loop that runs once per install; addons have no hook into it (`ui/addons/hooks.py`).
- Production hosts: 8 hosts, ssh users `root` (3), `ubuntu` (4 AWS), `ruweb` (1). Non-root support is task 12 of the 1.0 plan (1.0.1, in progress).

## Part A - qlsm core (three upstream PRs, one topic each)

Each is a branch `upstream-pr/<topic>` from `upstream/main`, merged into our fork's working branch while open (`skills/qlsm-dev/SKILL.md`). Generic: nothing in them knows about host-metrics.

### A1 `upstream-pr/addon-nav-entry` - an addon page in the navbar

- Manifest: `ui.page` gains an optional `nav` object: `{"label": "Hosts health", "icon": "<allowed icon>"}`; validated like other ui fields (label 1-32 chars, icon from the allow-list).
- Navbar: every loaded, globally enabled addon whose `page` has `nav` gets a top-level item linking to `/addons/<id>`, after the core items, ordered by addon id. Disabled or broken addons show nothing.
- Tests: manifest validation; navbar renders the item only for enabled addons.

### A2 `upstream-pr/notifications` - stored notifications and a bell

- Table `notification`: `id, created_at, updated_at, source` (`core` or addon id), `severity` (`info|warning|critical`), `title` (<=120), `body` (<=1000), `link` (relative path or null), `key` (dedupe, nullable), `resolved_at`, `read_at`. Alembic migration. Rows older than 30 days pruned on insert.
- Backend API for addons: `ctx.notify(severity, title, body='', link=None, key=None)`; with `key`, an open (unresolved) row with that key is updated instead of duplicated; `ctx.resolve(key)` sets `resolved_at`. Core can use the same functions.
- Routes (`@jwt_required`): `GET /api/notifications?unread=1&limit=`, `POST /api/notifications/<id>/read`, `POST /api/notifications/read-all`.
- Navbar bell: unread count badge (polls `GET /api/notifications?unread=1&limit=1` every 30 s and on window focus); dropdown with the last 20, severity colour from theme tokens, "resolved" shown greyed, link opens the page; "Mark all read".
- Included in the DB backup (unlike `AddonState`, known gap DevInbox #552).

### A3 `upstream-pr/addon-poller-tick` - periodic hook for addons

- New core hook `poller.tick` (scope global, gated by the addon's global enable), dispatched by `run-status-poller` once per cycle (15 s), after `poll_all_hosts()`.
- Handlers run in the poller process, sequentially, each wrapped: exceptions logged with the addon id and swallowed; a handler running longer than 10 s logs a warning. Addons do their own interval gating (e.g. every 4th tick).
- Documented in `addons/README.md` next to the other hooks.

## Part B - host-metrics 1.1 (qlsm-extra)

### B1 Theme

- All addon CSS uses qlsm tokens (`var(--surface-raised)`, `var(--accent-danger)`, text tokens); no hard-coded light/dark colours, no `prefers-color-scheme`. Buttons come from `ctx.ui.Button` where it exists, otherwise styled with tokens.
- uPlot draws on canvas, so series/axis/grid colours are read from computed tokens at draw time, and charts redraw when the `class` attribute of `<html>` changes (MutationObserver).
- Check both themes in a real qlsm page (Task 11 style live check with screenshots for the operator).

### B2 Health board (the addon page, navbar item "Hosts health")

- One card per host, problems first, then by name. Card:
  - status light and word: **OK** (green), **Watch** (amber: tight, noisy neighbour, stale data, warnings in 24 h), **Problem** (red: overloaded, open critical event, unreachable/no sudo), **No data** (grey: not installed, no data under load);
  - one sentence why, from B3 (e.g. "Core 0 peaked at 41 % during matches; room for 2 more instances.");
  - hardware line from B4 (e.g. "AMD EPYC 7B13, 2 vCPU, 3.8 GB RAM, 38 GB SSD, Hetzner (KVM)");
  - instances and players now; open events count; link "Details" opens the host modal.
- Top strip: counts per status and the open problems list (host, what, since when).

### B3 Text findings

- Pure function `findings(snapshot, series, events, settings) -> [{level: ok|info|warning|problem, area, text}]` in `ui-src/findings.js`, unit-tested; shown as a bulleted summary at the top of the host modal and one line above each chart.
- Rules (numbers from the data; thresholds from addon settings):
  - CPU per core: "Core N stayed below X % (p95 Y %) over <range>; limit for planning is 70 %." / "Core N was above 95 % for M minutes, during matches."
  - Room: "Room for N more instances (reference: one instance uses X % of a core in a match)." / "No room: ..." / "No match played on this host yet, so room is estimated from other hosts."
  - Frames: "No late server frames in <range>." / "K late frames on :PORT, worst gap Z ms at HH:MM (players: P). A late frame means players see a hitch."
  - Steal: "The provider took S % of CPU time (steal); above 5 % means a noisy neighbour."
  - Memory, disk: "RAM: A GB free of T GB, enough for about N more instances." / "Disk / is 92 % full."
  - Data: "Collector data is 6 min old - the collector or the host is down."

### B4 Hardware

- Collector reads at start and every hour (cheap): `/proc/cpuinfo` model name, vCPU count, threads per core and sockets (`lscpu` if present, else cpuinfo), MHz, cache size; hypervisor vendor (`/proc/cpuinfo` flags `hypervisor` + `/sys/class/dmi/id/sys_vendor`, `product_name`, readable without root on these hosts, else null); provider guess from DMI strings (Hetzner, Amazon EC2, Vultr, else the raw vendor); MemTotal, SwapTotal; root disk size and rotational flag (`/sys/block/<dev>/queue/rotational`); kernel and OS (`/etc/os-release`); boot time.
- Stored in a `hardware` table (one row, replaced); `hm_query snapshot` returns it as `hardware`.

### B5 Charts that explain themselves

- Every chart has a title, a one-line "how to read" (e.g. "% of one CPU core used by each server. Lower is better. Sustained above the dashed 70 % line means no room for more servers."), units on the axis, and a legend whose items show the current/peak value and a tooltip with the series meaning.
- Threshold lines (dashed, labelled): CPU 70 % planning limit and 95 % saturation; frame gap 25 ms tick and late threshold 37.5 ms (from `tick_ms`); steal 5 %; RAM reserve line; disk 90 %.
- Direction hint chip per chart: "lower is better" / "higher is better".
- Empty states say why ("No data yet: the collector started 3 minutes ago").

### B6 Notifications from host-metrics

- Handler on `poller.tick`, every 4th tick (60 s): for each host with the addon enabled, fetch `snapshot` (parallel, 5 s timeout, the existing cache path) and events opened or closed since the last check (`hm_query events --since <ts>`, new argument).
- `ctx.notify(key="host-metrics:<host_id>:<kind>:<scope>")` when an event opens, `ctx.resolve(key)` when it closes. Kinds and severity: `frames_late` and `core_saturated` with players on -> warning; `oom_kill`, `disk_low` -> critical; `steal_high`, `mem_low` -> warning; collector stale or host unreachable for more than 5 min -> critical, resolved when data is back. `instance_new/gone` are not notified.
- Link: `/addons/host-metrics?host=<id>` (the board opens that host's modal).
- Settings: `notify_enabled` (default on), `notify_min_severity` (default warning).
- Last check timestamp per host kept in Redis (`addon:host-metrics:notify:<host_id>`), so a qlsm restart does not replay old events.

## Order and release

1. A3, A2, A1 as three PRs (A3 smallest first); merged into the fork; deployed with qlsm-ci after the operator's OK.
2. B1, B3, B4, B5 do not depend on Part A and can ship as host-metrics 1.1.0 first.
3. B2 navbar entry and B6 ship as 1.2.0 once the fork carries A1-A3 (`ui_api`/core capability check so 1.2 still runs on a core without them: no nav item, no notifications, a note on the board).

## Out of scope

- Discord or other external channels (the bell can feed them later).
- Per-instance network traffic (unchanged from 1.0).
