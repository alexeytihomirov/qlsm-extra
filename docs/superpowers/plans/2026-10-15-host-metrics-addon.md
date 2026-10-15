# Host Metrics Addon Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A qlsm addon that shows CPU, RAM, disk, network, players and frame timing per game host and per QLDS instance over 30 days, an event journal and a capacity verdict.

**Architecture:** A stdlib-only Python collector runs as a systemd service on each game host and writes 10 s samples into a local SQLite; a minqlx plugin publishes frame-interval stats into the host's Redis for it. The addon installs the collector through `host.payload_sync`, reads JSON from a host-side query script over SSH (paramiko) and renders a page plus a host modal (tier-2 React, uPlot charts).

**Tech Stack:** Python 3.10+ stdlib on hosts (`sqlite3`, `socket`), Flask blueprint + paramiko in the addon, Ansible playbooks, React (core's, via `window.__qlsm`) + Vite + Tailwind 4 + uPlot in the UI, pytest.

**Spec:** `qlsm-extra/docs/superpowers/specs/2026-10-15-host-metrics-addon-design.md`. Task: `qlsm-extra-0009`.

## Global Constraints

- Worktree `D:/QuakeLiveData/QL Server/.worktrees/qlsm-extra-host-metrics`, branch `host-metrics`. Never edit `D:/QuakeLiveData/QL Server/qlsm-extra` or `.../qlsm`.
- No change to qlsm core.
- Host-side code (`addons/host-metrics/assets/*.py`): Python stdlib only, must run on 3.10 to 3.14 (hosts have 3.12.3 and 3.14.4). No pip on hosts.
- Paths on the host: code `/home/ql/host-metrics/`, data `/var/lib/host-metrics/metrics.db`, config `/etc/host-metrics/config.json`. Service `host-metrics.service`, `User=ql` (member of group `redis`, verified), `Nice=19`, `CPUWeight=1`, `Restart=always`.
- Redis on hosts: unix socket `/var/run/redis/redis.sock`, minqlx database `1` (read from the instance cmdline `qlx_redisDatabase`, default 1). Keys: `minqlx:server_status:<port>` (serverchecker JSON), `minqlx:frame_stats:<port>` (this plan).
- Cgroups: v2, `/sys/fs/cgroup/system.slice/system-qlds.slice/qlds@<port>.service/` (`cpu.stat` `usage_usec`, `memory.current`, `memory.events` `oom_kill`).
- Tick 10 s. Raw tables kept 48 h, minute tables and events 30 days.
- Event defaults: core > 95 % for 60 s, steal > 10 % for 60 s, MemAvailable < 10 % for 60 s, `/` > 90 % at once, OOM delta at once, late frames > 1 % or gap > 100 ms over 60 s, instance appear/disappear at once.
- Verdict defaults: target 70 % of a core, memory reserve 20 % of MemTotal, steal tight 5 %, steal overload 15 %, busy sample = `state == "in_progress"` and 2+ players, look-back 7 days.
- Late frame = gap > 1.5 x tick, tick = 1000 / `sv_fps` ms.
- Every backend route `@jwt_required()`. Nothing from a request reaches a shell as text: `range` from the allow-list `1h 6h 24h 7d 30d`, `port` an int, argv joined with `shlex.quote`.
- Tests: run only the test files of the task (`rtk proxy python -m pytest tests/<file> -q -p no:cacheprovider`; addon route tests need `QLSM_REPO="D:/QuakeLiveData/QL Server/qlsm"`). Never the whole suite.
- Commits as the operator, no AI attribution. No push, no merge into `main` until Task 11.
- Never kill processes by image name.

## Review Focus

1. A host where the addon was never applied, or with an older collector: the page must show the host as "not installed" / "outdated", not fail the whole list. Test in Task 9 (`test_hosts_lists_unreachable_and_not_installed_hosts`).
2. Counter resets (instance restarted, so `usage_usec` drops; host reboot, so `/proc/stat` drops): no negative or huge CPU %. Test in Task 5 (`test_tick_after_counter_reset_skips_rate`).
3. Missing Redis keys (serverchecker or frame_timing not enabled, server between maps): instance row still written with players / frames as NULL, the UI shows "no data". Test in Task 5 (`test_tick_without_redis_keys_writes_nulls`).
4. A new or removed instance between ticks (`qlds@<port>` cgroup appears or disappears): one `instance_new` / `instance_gone` event, no crash, no rate on the first tick. Test in Task 5 (`test_instance_appears_and_disappears`).
5. A host with no busy samples at all (fresh VPS from `root-0020`): verdict says "no data under load" and does not invent a slot count. Test in Task 6 (`test_no_busy_samples_anywhere_gives_no_slot_count`).

## File Structure

```
qlsm-extra/
  frame_timing.py                      Task 1  minqlx plugin
  frame_timing.ql-plugin.json          Task 1
  addons/host-metrics/
    qlsm-addon.json                    Task 8
    README.md                          Task 11
    backend.py                         Task 8 (install, routes), Task 9 (read routes)
    settings.py                        Task 8  settings -> validated config dict
    ssh.py                             Task 9  paramiko exec helper
    verdict.py                         Task 6  pure verdict
    assets/
      hm_readers.py                    Task 2  /proc, cgroup, redis readers (pure, root-relative)
      hm_store.py                      Task 3  SQLite schema, insert, rollup, prune, series
      hm_events.py                     Task 4  windowed event tracker
      hm_collect.py                    Task 5  service main loop
      hm_query.py                      Task 7  CLI printing JSON
      host-metrics.service             Task 8
    playbooks/
      sync_host_metrics.yml            Task 8
      status_host_metrics.yml          Task 8
    ui-src/ (Page.jsx, HostPanel.jsx, charts.jsx, runtime.js, panel.css)   Task 10
    ui/ (Page.js, HostPanel.js, Panel.css: built, committed)               Task 10
    package.json, vite.config.js       Task 10
  tests/
    fixtures/host-metrics/germany/...  Task 2  copies of /proc + cgroup files
    test_frame_timing.py               Task 1
    test_hm_readers.py                 Task 2
    test_hm_store.py                   Task 3
    test_hm_events.py                  Task 4
    test_hm_collect.py                 Task 5
    test_hm_verdict.py                 Task 6
    test_hm_query.py                   Task 7
    test_host_metrics_playbooks.py     Task 8
    test_addon_host_metrics.py         Task 8, Task 9
```

Host-side modules import each other by plain name (`import hm_readers`); tests add `addons/host-metrics/assets` to `sys.path` and are `pytestmark = pytest.mark.standalone` (no qlsm needed). `verdict.py` is standalone too.

---

### Task 1: frame_timing plugin

**Files:**
- Create: `frame_timing.py`, `frame_timing.ql-plugin.json`
- Test: `tests/test_frame_timing.py`

**Interfaces:**
- Produces: Redis key `minqlx:frame_stats:<port>`, TTL 30 s, JSON `{"seq": int, "window_s": float, "frames": int, "late": int, "max_ms": float, "p50_ms": float, "p99_ms": float, "tick_ms": float, "updated": int}`.
- Pure class `FrameStats(tick_ms: float)` with `add(gap_ms: float) -> None`, `snapshot() -> dict` (the JSON fields above minus `seq`, `window_s`, `updated`), histogram 1 ms buckets 0..99 + one overflow bucket; p50/p99 are the bucket upper bounds; overflow reports `max_ms`.

- [ ] **Step 1: Write the failing tests** (import via `tests/_minqlx_stub.py`, `pytestmark = pytest.mark.standalone`)

```python
def test_late_counts_gaps_over_one_and_a_half_ticks():
    s = FrameStats(tick_ms=25.0)
    for g in (25, 25, 37.4, 37.6, 80):
        s.add(g)
    snap = s.snapshot()
    assert snap["frames"] == 5 and snap["late"] == 2 and snap["max_ms"] == 80

def test_percentiles_from_histogram():
    s = FrameStats(tick_ms=25.0)
    for _ in range(98): s.add(25.2)
    s.add(60.0); s.add(150.0)
    snap = s.snapshot()
    assert snap["p50_ms"] == 26 and snap["p99_ms"] == 61 and snap["max_ms"] == 150

def test_gap_after_map_hook_is_excluded():
    # plugin with a fake clock: frame at 0, map hook, frame at 5.0 s, frame at 5.025 s
    assert published["frames"] == 1 and published["max_ms"] == pytest.approx(25, abs=0.5)

def test_tick_follows_sv_fps():
    # sv_fps cvar "80" at new_game -> tick_ms 12.5, a 20 ms gap is late
```

- [ ] **Step 2:** Run `rtk proxy python -m pytest tests/test_frame_timing.py -q -p no:cacheprovider`. Expected: FAIL (module missing).
- [ ] **Step 3: Implement `frame_timing.py`.** Import as `demo_stream_resync_hold.py:48-51` does (minqlxtended, fallback minqlx). Plugin class `frame_timing`: hooks `frame`, `map`, `new_game`, `unload`. Frame handler: `time.perf_counter()`, skip if `_skip_next`, else `self._stats.add(gap_ms)`; nothing else on the frame. A worker thread started in `__init__` (stop `threading.Event`, set on `unload`) every 10 s swaps `self._stats` for a fresh `FrameStats` (a single attribute assignment) and writes the snapshot with `self.db.set(key, json); self.db.expire(key, 30)` as serverchecker does; errors are logged at most once a minute. Port from cvar `net_port`.
- [ ] **Step 4:** Run the tests again. Expected: PASS.
- [ ] **Step 5:** `frame_timing.ql-plugin.json`: label "Frame Timing", description says what it measures, that it writes `minqlx:frame_stats:<port>` every 10 s, and that the host-metrics addon reads it. Run `python generate_manifest.py`, check the new entry has `"runtime": "minqlxtended"` like the others.
- [ ] **Step 6: Commit** `feat(frame_timing): frame interval stats into redis for host-metrics`.

### Task 2: host readers

**Files:**
- Create: `addons/host-metrics/assets/hm_readers.py`, fixtures under `tests/fixtures/host-metrics/germany/` (copy from germany over SSH, read-only: `proc/stat`, `proc/meminfo`, `proc/loadavg`, `proc/pressure/cpu`, `proc/net/dev`, `proc/net/route`, `proc/vmstat`, and `sys/fs/cgroup/system.slice/system-qlds.slice/qlds@27960.service/{cpu.stat,memory.current,memory.events}`)
- Test: `tests/test_hm_readers.py`

**Interfaces (all take `root: str = "/"` so tests point at the fixture dir):**
- `read_cpu_times(root) -> dict[int, CpuTimes]`, `CpuTimes` namedtuple `user nice system idle iowait irq softirq steal` (ticks), key `-1` = the aggregate `cpu` line.
- `cpu_percent(prev: CpuTimes, cur: CpuTimes) -> dict | None` keys `user system iowait steal idle busy` in %, `None` when any field went down (reset).
- `read_mem(root) -> dict` keys `total available swap_used` (bytes).
- `read_load(root) -> float`, `read_psi_cpu_some10(root) -> float | None`.
- `default_iface(root) -> str | None` (from `proc/net/route`, destination `00000000`), `read_net(root, iface) -> dict` keys `rx_bytes tx_bytes rx_packets tx_packets`.
- `read_oom_kills(root) -> int` (`proc/vmstat` `oom_kill`).
- `read_disk(path="/") -> dict` keys `used total` (`os.statvfs`; not root-relative).
- `list_instances(root) -> list[int]` ports from `qlds@<port>.service` dir names.
- `read_instance(root, port) -> dict` keys `usage_usec mem_bytes oom_kills`.
- `read_affinity(port) -> int | None` (`systemctl show -p CPUAffinity --value`; first cpu if exactly one, else None).
- `class RedisSocket(path, db, timeout=1.0)` with `get(key) -> bytes | None` (minimal RESP: `SELECT`, `GET`), reconnects on error.

- [ ] **Step 1: Write the failing tests** against the fixtures: two cores plus aggregate parsed; `cpu_percent` of two fixture snapshots (make the second by editing numbers) sums to 100 ± 0.1; reset returns `None`; `default_iface == "eth0"`; `list_instances == [27960]`; `read_instance` matches the fixture numbers; `RedisSocket.get` against a `socketserver` unix-socket fake is skipped on Windows (`pytest.mark.skipif(not hasattr(socket, "AF_UNIX"))`) and a RESP parse unit test runs everywhere (`parse_bulk(b"$3\r\nabc\r\n") == b"abc"`, `parse_bulk(b"$-1\r\n") is None`).
- [ ] **Step 2:** Run `tests/test_hm_readers.py`. Expected: FAIL.
- [ ] **Step 3:** Implement `hm_readers.py`.
- [ ] **Step 4:** Run. Expected: PASS.
- [ ] **Step 5: Commit** `feat(host-metrics): host and cgroup readers`.

### Task 3: SQLite store

**Files:** Create `addons/host-metrics/assets/hm_store.py`; Test `tests/test_hm_store.py`.

**Interfaces:**
- `open_db(path) -> sqlite3.Connection` (WAL, creates schema, `PRAGMA user_version = 1`).
- Tables (ts = unix seconds, int):
  - `host_raw(ts, load1, psi10, mem_total, mem_avail, swap_used, disk_used, disk_total, rx_bps, tx_bps, rx_pps, tx_pps)`
  - `core_raw(ts, core, user, system, iowait, steal, busy)` (core -1 = all)
  - `inst_raw(ts, port, cpu, mem, core, players, state, map, frames, late, max_ms, p99_ms, tick_ms)`
  - `host_min`, `core_min`: same columns as avg plus `_max` for `busy steal load1`, and `mem_avail_min`.
  - `inst_min(ts, port, cpu_avg, cpu_max, mem_max, core, players_max, busy_ticks, cpu_busy_avg, frames, late, max_ms, p99_max)`
  - `events(id, ts, kind, scope, port, severity, state, message)`, `state` in `open|closed`.
- `insert_tick(conn, ts, host: dict, cores: list[dict], insts: list[dict]) -> None`.
- `rollup(conn, until_ts) -> int` rolls every complete minute not yet rolled (tracked in a `meta` table), returns minutes rolled. `busy` = `state == "in_progress" and players >= 2`.
- `prune(conn, now, raw_keep_s=172800, min_keep_s=2592000) -> None`.
- `series(conn, now, range_name, port=None, max_points=600) -> dict` with `{"res": "raw"|"min", "host": [...], "cores": [...], "insts": {port: [...]}}`; ranges `1h 6h` from raw, `24h 7d 30d` from minute tables; downsample by averaging into equal buckets when rows > max_points.
- `insert_event`, `close_event`, `events(conn, since) -> list[dict]`.

- [ ] **Step 1: Write the failing tests:** insert 120 ticks at 10 s, `rollup` gives 20 minute rows with correct avg/max; busy averaging counts only busy ticks (`cpu_busy_avg` over 3 busy ticks of 6); `prune` drops raw older than 48 h and keeps minutes; `series("30d")` with 43200 minute rows returns <= 600 points per series; `series("1h", port=27960)` returns only that port.
- [ ] **Step 2:** Run `tests/test_hm_store.py`. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run. Expected: PASS.
- [ ] **Step 5: Commit** `feat(host-metrics): sqlite store with rollup and retention`.

### Task 4: event tracker

**Files:** Create `addons/host-metrics/assets/hm_events.py`; Test `tests/test_hm_events.py`.

**Interfaces:**
- `class EventTracker(store_conn, thresholds: dict)`; `observe(ts, kind, scope_key, active: bool, message: str) -> None`. A condition opens an event once it has been continuously active for `window_s` (0 for "at once" kinds), closes it on the first inactive tick; one open row per `(kind, scope_key)`.
- `evaluate(ts, sample) -> None` applies the Global Constraints rules to one collector sample (shape from Task 5) and calls `observe`.
- Kinds: `core_saturated steal_high mem_low disk_low oom_kill frames_late instance_new instance_gone`.

- [ ] **Step 1: Write the failing tests:** core at 96 % for 50 s -> no event, for 60 s -> one open event, back to 50 % -> closed; flapping 96/50 every tick -> no event; `oom_kill` delta 1 -> open and closed in the same tick (point event); late 2 % for 60 s -> `frames_late` for that port only.
- [ ] **Step 2:** Run `tests/test_hm_events.py`. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run. Expected: PASS.
- [ ] **Step 5: Commit** `feat(host-metrics): windowed event tracker`.

### Task 5: collector loop

**Files:** Create `addons/host-metrics/assets/hm_collect.py`; Test `tests/test_hm_collect.py`.

**Interfaces:**
- `class Collector(config: dict, root="/", redis=None, clock=time.time, affinity=hm_readers.read_affinity)`; `tick() -> dict` (the sample written, for tests); `run_forever()` (sleep to the next 10 s boundary, `tick()`, `rollup` + `prune` once a minute, exceptions logged to stderr and the loop continues).
- Sample: `{"ts", "host": {...}, "cores": [...], "insts": [{"port", "cpu", "mem", "core", "players", "state", "map", "frames", "late", "max_ms", "p99_ms", "tick_ms", "oom_delta"}], "oom_delta"}`.
- Config keys (written by Task 8): `db_path`, `redis_socket`, `redis_db`, `thresholds` (dict of the event defaults), `version`.
- Instance CPU % = Δ`usage_usec` / Δwall / 10 000 (100 % = one full core). Frame stats are taken only when the key's `seq` changed since the last tick, else NULL.
- `main(argv)` reads `/etc/host-metrics/config.json` (`--config` overrides); `--once` runs one tick; `--dry-run` with `--once` reads everything and prints the sample as JSON without opening the DB (the playbook smoke check, Task 8).

- [ ] **Step 1: Write the failing tests** with a temp copy of the germany fixture tree whose counters the test advances between ticks, a fake Redis dict and a fake clock:
  - `test_first_tick_has_no_rates_second_has_rates`
  - `test_instance_cpu_percent_of_one_core` (Δusage 5 s over 10 s -> 50.0)
  - `test_tick_after_counter_reset_skips_rate` (usage drops -> `cpu is None`, no negative)
  - `test_dry_run_prints_sample_without_db`
  - `test_tick_without_redis_keys_writes_nulls`
  - `test_frame_stats_only_when_seq_changes`
  - `test_instance_appears_and_disappears` (one `instance_new`, one `instance_gone`)
- [ ] **Step 2:** Run `tests/test_hm_collect.py`. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run. Expected: PASS.
- [ ] **Step 5: Commit** `feat(host-metrics): collector service loop`.

### Task 6: verdict

**Files:** Create `addons/host-metrics/verdict.py`; Test `tests/test_hm_verdict.py`.

**Interfaces:**
- Input (produced by `hm_query.py snapshot`, Task 7): `{"cores": n, "mem_total", "mem_avail_now", "steal_p95", "core_other_p95": {core: pct}, "insts": [{"port", "core", "busy_p95": float | None, "rss_max"}], "events_24h": {kind: count}, "events_24h_busy": {"frames_late": n, "core_saturated": n}}`.
- `verdict(inp: dict, settings: dict, fleet_busy_median: float | None) -> dict` returns `{"status": "ok"|"tight"|"overloaded"|"unknown", "slots": int | None, "reason": str, "ref_load": float | None, "ref_source": "host"|"fleet"|None}`.
- Algorithm exactly as the spec's "Verdict" section: `L` = max `busy_p95` on the host, else `fleet_busy_median` (`ref_source="fleet"`), else no slot count; per-core free = floor((target - (sum L of pinned + other_p95)) / L), min 0; mem slots = floor((avail - reserve% x total) / max rss); slots = min. Status precedence: overloaded (busy `frames_late`/`core_saturated` in 24 h, or steal_p95 > overload) > tight (slots == 0 or steal_p95 > tight) > ok. `reason` names the deciding number, e.g. `"core 0: 2 x 31% + 6% other of 70%"`.

- [ ] **Step 1: Write the failing tests** (table-driven):
  - 2 cores, one instance on core 0 with busy_p95 30, other 5/5 -> slots 3 (core0: (70-35)/30=1, core1: (70-5)/30=2), status ok.
  - same with steal_p95 7 -> tight, slots still 3.
  - steal_p95 16 -> overloaded.
  - `events_24h_busy.frames_late == 1` -> overloaded.
  - memory cap: avail 500 MB, total 4 GB, rss 90 MB -> mem slots 0 -> tight.
  - `test_no_busy_samples_on_host_uses_fleet_median` -> `ref_source == "fleet"`.
  - `test_no_busy_samples_anywhere_gives_no_slot_count` -> `slots is None`, status `unknown` unless steal/events force otherwise.
- [ ] **Step 2:** Run `tests/test_hm_verdict.py`. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run. Expected: PASS.
- [ ] **Step 5: Commit** `feat(host-metrics): capacity verdict`.

### Task 7: host query CLI

**Files:** Create `addons/host-metrics/assets/hm_query.py`; Test `tests/test_hm_query.py`.

**Interfaces:**
- `python3 hm_query.py [--db PATH] snapshot | series --range R [--port N] | events --range R` prints one JSON object with `"version"` (from `VERSION` next to the script) and exits 0; unknown args exit 2 (argparse); missing DB prints `{"version": ..., "error": "no_data"}` and exits 3.
- `snapshot`: last host/core/inst raw rows, plus the Task 6 input block computed over 7 days from minute tables (`busy_p95` over minutes with `busy_ticks >= 3`; `core_other_p95` = p95 of per-minute `core busy avg - sum of cpu_avg of instances pinned to that core`, floored at 0) and `events_24h` / `events_24h_busy` (busy = an instance on the host had `busy_ticks > 0` in that minute).
- `series` / `events` wrap `hm_store.series` / `hm_store.events`.

- [ ] **Step 1: Write the failing tests:** run `main(argv)` against a store filled by a helper (two days of minute rows, one busy hour on port 27960) and assert the snapshot block values; `series --range 2h` exits 2; missing db exits 3 with `error == "no_data"`.
- [ ] **Step 2:** Run `tests/test_hm_query.py`. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run. Expected: PASS.
- [ ] **Step 5: Commit** `feat(host-metrics): query cli`.

### Task 8: addon skeleton, settings, install playbooks

**Files:**
- Create: `addons/host-metrics/qlsm-addon.json`, `settings.py`, `backend.py` (install part), `assets/host-metrics.service`, `playbooks/sync_host_metrics.yml`, `playbooks/status_host_metrics.yml`
- Test: `tests/test_host_metrics_playbooks.py`, `tests/test_addon_host_metrics.py`

**Interfaces:**
- Manifest: `id "host-metrics"`, `version "1.0.0"`, `scopes ["global","host"]`, `ui_api 3`. Global settings (type `string`, like file-forwarder) with the defaults from Global Constraints: `core_saturated_pct 95`, `steal_event_pct 10`, `mem_low_pct 10`, `disk_low_pct 90`, `frames_late_pct 1`, `frame_gap_ms 100`, `event_window_s 60`, `verdict_target_pct 70`, `mem_reserve_pct 20`, `steal_tight_pct 5`, `steal_overload_pct 15`. Host setting `enabled` bool default true. UI: `page` `{"label": "Host Metrics", "icon": "gauge", "component": "Page.js"}`, `host_menu` `[{"id": "host-metrics", "label": "Host Metrics", "icon": "gauge", "component": "HostPanel.js", "renders": "modal"}]`, `settings_section` form over the global settings (`gauge` is in `qlsm/frontend-react/src/components/addons/addonIcons.js`).
- `settings.py`: `collector_config(values: dict) -> dict` returns the config.json dict (Task 5 keys; `redis_db` 1), raising `ValueError` naming the field on a non-integer or out-of-range value (0-100 for percents, 1-3600 for seconds/ms).
- `backend.py`: same shape as `qlsm-extra/addons/file-forwarder/backend.py`: `CTX`, `_run(host, name, extravars)`, `host_enabled(host_id)`, `apply_host(host_id)`, tasks `apply_task`, `POST hosts/<id>/apply`, `GET hosts/<id>/status`, `GET/PUT settings`, `@ctx.on('host.payload_sync')`.
- `sync_host_metrics.yml` (extravars `hm_enabled`, `hm_version`, `hm_config_json`): create `/home/ql/host-metrics` (owner ql), `/var/lib/host-metrics` (ql, 0750), `/etc/host-metrics`; copy the five `assets/*.py`, write `VERSION` (content `{{ hm_version }}`, the manifest version; no VERSION file in the repo) and `config.json`; install the unit; `daemon-reload`; enabled -> `enable --now` + restart and `sudo -u ql python3 /home/ql/host-metrics/hm_collect.py --once --dry-run` as the smoke check; disabled -> `disable --now`, data kept.
- `status_host_metrics.yml` prints `HM_VERSION=`, `HM_SERVICE=` (is-active), `HM_DB_BYTES=`.

- [ ] **Step 1: Write the failing tests:** playbooks parse and target `all`, every copied asset exists, the unit has `User=ql`, `Nice=19`, `CPUWeight=1`, `Restart=always`; `collector_config` defaults equal the Global Constraints values, `"abc"` and `"101"` raise; route tests (QLSM_REPO) for `PUT settings` validation and `POST hosts/<id>/apply` queuing under the host lock with a stubbed `enqueue_task` (copy the pattern from `tests/test_addon_file_forwarder.py`).
- [ ] **Step 2:** Run the two test files. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run. Expected: PASS. If `ansible-playbook` is on PATH, the syntax-check test runs too.
- [ ] **Step 5: Commit** `feat(host-metrics): addon manifest, settings and install playbooks`.

### Task 9: read routes over SSH

**Files:** Create `addons/host-metrics/ssh.py`; Modify `addons/host-metrics/backend.py`; Test `tests/test_addon_host_metrics.py`.

**Interfaces:**
- `ssh.py`: `exec_json(host, argv: list[str], timeout=5.0) -> tuple[int, dict | None, str]` (rc, parsed stdout, stderr tail). `open_ssh` copied from `qlsm-extra/addons/demo-management/instance_demo_transport.py:59-90` with its comment about the trust model. Command `python3 /home/ql/host-metrics/hm_query.py ` + `shlex.join(argv)`.
- Routes:
  - `GET hosts` -> `{"data": {"hosts": [{"id", "name", "state": "ok"|"not_installed"|"outdated"|"unreachable"|"no_data", "version", "snapshot", "verdict"}]}}`; snapshots fetched with a `ThreadPoolExecutor(max_workers=8)`; fleet median of `busy_p95` over all answering hosts passed to `verdict()`; result cached in `current_app.extensions.get('redis')` key `addon:host-metrics:hosts`, TTL 30 s, no-op without Redis (pattern `qlsm-extra/addons/player-ranks/cache.py`). `?refresh=1` skips the cache.
  - `GET hosts/<id>/series?range=&port=` and `GET hosts/<id>/events?range=` -> pass-through `{"data": <hm_query json>}`; bad `range`/`port` -> 400.
  - State mapping: rc 127 or "No such file" in stderr -> `not_installed`; `version` != manifest version -> `outdated` (data still shown); rc 3 -> `no_data`; SSH exception or timeout -> `unreachable`.

- [ ] **Step 1: Write the failing tests** with `ssh.exec_json` monkeypatched per host:
  - `test_hosts_lists_unreachable_and_not_installed_hosts` (3 hosts: ok, rc 127, raises `TimeoutError`; all three rows present with the right `state`)
  - `test_hosts_uses_cache_within_ttl` (fake redis dict; second call does not call ssh)
  - `test_series_rejects_bad_range_and_port` (`range=2h` -> 400, `port=abc` -> 400, ssh not called)
  - `test_series_argv_is_fixed` (asserts the exact argv `["series", "--range", "24h", "--port", "27960"]`)
  - `test_routes_need_login` (401 without JWT)
- [ ] **Step 2:** Run `tests/test_addon_host_metrics.py`. Expected: new tests FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run. Expected: PASS.
- [ ] **Step 5: Commit** `feat(host-metrics): read routes over ssh with cache`.

### Task 10: UI

**Files:** Create `addons/host-metrics/ui-src/{runtime.js,Page.jsx,HostPanel.jsx,charts.jsx,format.js,format.test.mjs,panel.css}`, `package.json`, `vite.config.js`, built `ui/Page.js`, `ui/HostPanel.js`, `ui/Panel.css`.

**Interfaces:**
- Build: copy `qlsm-extra/addons/demo-management/vite.config.js` with `lib.entry` = `{Page: 'ui-src/Page.jsx', HostPanel: 'ui-src/HostPanel.jsx'}`, `fileName: (_, name) => `${name}.js``, CSS into one `Panel.css` imported by both entries. Dependency `uplot` (pin an exact version at least two weeks old) bundled. CSS classes prefixed `hm-`.
- `format.js` (pure, tested with `node --test`): `fmtPct`, `fmtBytes`, `statusLabel(status) -> {text, tone}` (English like the rest of qlsm: `ok` "OK", `tight` "Tight", `overloaded` "Overloaded", `unknown` "No data under load"), `slotsText(verdict)` ("room for 3 more", "no room", "-").
- `Page.jsx`: `ctx.api('GET', 'hosts')`, table per spec section 6 (status badge with `reason` as tooltip and second line, per-core 24 h p95, steal p95, RAM available, disk used %, instances, players now, late frames 24 h, events 24 h), Refresh button calls `hosts?refresh=1`, host name opens the same modal component as the host menu.
- `HostPanel.jsx`: `renders: "modal"`, uses `ctx.modal.entity` for the host id; range switch `1h 6h 24h 7d 30d`; charts in this order: per-core stacked user/system/steal, CPU per instance with players on a second axis, frame max gap and late count per instance, memory, network, disk; events table; footer with version, service state and "Apply to host" (`POST hosts/<id>/apply`).
- Before writing charts, load the `dataviz` skill and follow its palette and light/dark rules.

- [ ] **Step 1:** Write `format.test.mjs` cases for the four helpers; run `npm test`. Expected: FAIL.
- [ ] **Step 2:** Implement `format.js`; `npm test` passes.
- [ ] **Step 3:** Implement the components; `npm install && npm run build` in a **normal checkout copy** if Tailwind classes vanish (worktree scan issue, `skills/qlsm-dev/reference/addons.md`); check `ui/Page.js` and `ui/HostPanel.js` exist and contain no bare `import ... from "react"`.
- [ ] **Step 4:** `python generate_manifest.py`. Undeclared names (the `modal is not defined` class of bug) are caught by opening both components in the Task 11 live check; qlsm-extra has no eslint setup.
- [ ] **Step 5: Commit** `feat(host-metrics): page and host modal`.

### Task 11: release and live check

**Files:** Modify `addons/host-metrics/README.md` (what it does, data on the host, how to remove), `qlsm-repository.json` (generated), task file `tasks/0009-...md`.

- [ ] **Step 1:** `python generate_manifest.py`, `python check_manifest_hashes.py`. Expected: hashes match.
- [ ] **Step 2:** Run the Task 1-9 test files once more. Expected: PASS.
- [ ] **Step 3:** Merge `host-metrics` into `main` (check `git merge-base` against local `main` first), push, confirm with `git ls-remote origin main`.
- [ ] **Step 4:** Ask the operator before touching production: install the addon in qlsm from the repository, restart, enable it, Apply to host on germany only; enable `frame_timing` on the germany test instance and restart it.
- [ ] **Step 5:** On germany: `systemctl is-active host-metrics`, `sqlite3 /var/lib/host-metrics/metrics.db 'select count(*) from inst_raw'` grows by 6 a minute, `redis-cli -s /var/run/redis/redis.sock -n 1 get minqlx:frame_stats:27960` shows `tick_ms 25`.
- [ ] **Step 6:** Prepare for the operator: a 1v1 on the germany test server; the Host Metrics page and modal show CPU and players moving together, frame stats present. After 24 h record the DB size in the task journal.
- [ ] **Step 7:** Task file: Результат, Как проверить, status `done-unverified`.
