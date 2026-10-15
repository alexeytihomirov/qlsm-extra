# Host metrics addon: resource dashboard and capacity verdict per game host - design

Date: 2026-10-15. Task: `qlsm-extra-0009`. Related: `root-0020` (six donated VPS to place instances on).

## Goal

1. For every game host and every QLDS instance on it, the operator sees CPU, RAM, disk, network, player count and server frame timing, now and over the last 30 days.
2. A journal of events that matter for capacity: a saturated core, high steal, low memory, OOM kills, a full disk, late server frames.
3. A verdict per host the operator can act on: "OK, room for N more instances", "tight", "overloaded", with the reason shown next to it.
4. No change to qlsm core, and the pull-only network model stays (`docs/policies/ops.md`): a host never connects home.

## Out of scope (v1)

- Per-instance network traffic. The cgroup does not count it, and systemd `IPAccounting=` would need a drop-in on `qlds@.service` plus a restart of every instance. Host-level network is in v1.
- Alerts that reach the operator (Discord, push). v1 only records events; the operator looks at the page.
- Hosts that are not qlsm game hosts (home-docker, the site VPS).
- Pure frame compute time. v1 measures the interval between server frames, see "Frame timing plugin".

## Verified facts this design rests on

Checked live on 2026-10-15 over SSH, read-only:

| Fact | germany 91.99.3.72 | sweden 70.34.223.51 |
|------|--------------------|---------------------|
| OS, kernel, systemd | Ubuntu 24.04, 6.8, systemd 255 | systemd 259 (from `skills/qlsm-dev/reference/deploy-and-hosts.md`) |
| cores | 2 | 2 |
| cgroup | v2 (`cgroup2fs`) | v2 |
| `DefaultCPUAccounting` / `DefaultMemoryAccounting` | yes / yes | readings present |
| `systemctl show qlds@27960 -p CPUUsageNSec,MemoryCurrent` | numbers (RSS ~91 MB) | numbers (RSS ~80 MB) |
| `CPUAffinity` of the running instance | 0 | 0 |
| steal in `/proc/stat` since boot | 0 | ~0.45 % |
| `/proc/pressure/cpu` (PSI) | present | present |
| Redis | local, unix socket `/var/run/redis/redis.sock`, minqlx uses db 1 | same |
| serverchecker key | `minqlx:server_status:<port>`, JSON (`players`, `maxplayers`, `state`, `map`, `factory`, `updated`), TTL ~10 s | same |
| python3 sqlite3 | 3.45.1 | not checked |
| `ql-watchdog` | not installed | not installed |
| `sv_fps` | 40 (`server.cfg`); the `sv_fps` plugin can raise it via `qlx_svfps` | same |

From the code:

- qlsm pins each instance to the least used core (`qlsm/ui/task_logic/cpu_affinity.py:95`, `choose_least_used_cpu`). So capacity is counted **per core**: QLDS is single-threaded, and two instances on one core share it even when the other core is idle.
- One unit per instance: `qlds@<port>.service`, cgroup `/sys/fs/cgroup/system.slice/system-qlds.slice/qlds@<port>.service/` (`qlsm/ansible/templates/qlds@.service.j2`).
- The addon core has no scheduler for addons and no addon tables (only `AddonState`). This is why history lives on the host.
- `qlsm-extra/addons/file-forwarder/` is the model for installing a host service from an addon (`host.payload_sync` hook, "Apply to host" task, per-host `enabled` setting). `qlsm-extra/addons/demo-management/instance_demo_transport.py:59` is the model for direct SSH via paramiko.

## Architecture

```
game host                                           qlsm (home)
---------                                           -----------
qzeroded --frame hook--> frame_timing plugin
                           |  every 10 s
                           v
                     redis db1  minqlx:frame_stats:<port>
                     redis db1  minqlx:server_status:<port>  (serverchecker)
                           |
/proc, /sys/fs/cgroup ---> hm-collect (systemd service, every 10 s)
                           |
                           v
                     /var/lib/host-metrics/metrics.db (SQLite)
                           ^
                           |  ssh exec: hm-query <cmd> --json      addon backend (paramiko)
                           +------------------------------------- <---- page / host modal
```

Four parts, all in `qlsm-extra`:

1. `addons/host-metrics/assets/hm_collect.py` - collector on the host.
2. `addons/host-metrics/assets/hm_query.py` - read side on the host, prints JSON.
3. `frame_timing.py` at the qlsm-extra root - minqlx plugin in the plugin pool.
4. `addons/host-metrics/` - addon: install playbook, backend routes, tier-2 UI.

## 1. Collector on the host (`hm_collect.py`)

- Python 3 stdlib only (`sqlite3`, `json`, `socket` for Redis over the unix socket with a minimal RESP client: no pip on hosts).
- Long-running `host-metrics.service` (`Type=simple`, `Restart=always`, `Nice=19`, `CPUWeight=1`, `User=ql`, group with access to the redis socket the same way QLDS has it). A loop with a 10 s tick, not a timer: rates (CPU, network) need the previous reading, and Python start-up every 10 s would cost more than the work.
- No CPU pinning: the collector must not land on the core of a game server by design, the low weight makes the scheduler prefer QLDS.
- Every tick it reads:

| Scope | Value | Source |
|-------|-------|--------|
| host, per core | user, system, iowait, steal, idle % | `/proc/stat` deltas |
| host | load1, PSI cpu `some avg10` | `/proc/loadavg`, `/proc/pressure/cpu` |
| host | MemTotal, MemAvailable, swap used | `/proc/meminfo` |
| host | `/` used and total | `os.statvfs` |
| host | rx/tx bytes and packets per s on the default-route interface | `/proc/net/dev`, `/proc/net/route` |
| host | OOM kills (delta) | `/proc/vmstat` `oom_kill` |
| instance | CPU % of one core | cgroup `cpu.stat` `usage_usec` delta |
| instance | throttled time, if any | cgroup `cpu.stat` |
| instance | memory current | cgroup `memory.current` |
| instance | OOM kills (delta) | cgroup `memory.events` `oom_kill` |
| instance | pinned core | `CPUAffinity` from the unit (read once a minute) |
| instance | players, maxplayers, state, map | `minqlx:server_status:<port>` |
| instance | frame stats for the last window | `minqlx:frame_stats:<port>` |

- Instances are found by listing `system-qlds.slice/qlds@*.service` cgroups each minute, so a new instance shows up without reinstalling anything.
- Storage `/var/lib/host-metrics/metrics.db`, WAL mode:
  - `host_raw`, `inst_raw`: one row per 10 s tick, kept 48 h (~17k rows a day per host and per instance).
  - `host_min`, `inst_min`: one row per minute, avg and max of every value (frame stats: max gap and sum of late frames), kept 30 days.
  - `events`: kept 30 days.
  - Roll-up and pruning once a minute in the same loop. Expected size well under 100 MB per host; the plan measures it.
- Config: `/etc/host-metrics/config.json` written by the install playbook (thresholds below, retention). Read at start; the playbook restarts the service.

## 2. Events

The collector writes an event when a condition holds for a whole window, and one closing event when it clears, so a flapping value does not flood the journal. Defaults (all in the addon's global settings):

| Event | Condition | Window |
|-------|-----------|--------|
| `core_saturated` | a core > 95 % busy | 60 s |
| `steal_high` | host steal > 10 % | 60 s |
| `mem_low` | MemAvailable < 10 % | 60 s |
| `disk_low` | `/` > 90 % used | at once |
| `oom_kill` | OOM counter grew (host or instance) | at once |
| `frames_late` | instance late frames > 1 % of frames, or a gap > 100 ms outside map load | 60 s |
| `instance_gone` / `instance_new` | cgroup appeared or disappeared | at once |

## 3. Read side (`hm_query.py`)

Called by the backend over SSH, prints JSON to stdout, never writes:

- `hm_query.py snapshot` - the last tick of the host and every instance, plus the verdict inputs over the last 7 days (see "Verdict").
- `hm_query.py series --range 1h|6h|24h|7d|30d [--port N]` - raw rows for 1 h and 6 h, minute rows otherwise, downsampled on the host to at most ~600 points per series so a 30-day answer stays small.
- `hm_query.py events --range ...`.
- Exit code and a `version` field let the backend tell "not installed" and "old version" apart from an error.

## 4. Frame timing plugin (`frame_timing.py`)

Answers "does the server keep its tick", which CPU percentages alone cannot.

- `frame` hook: `t = time.perf_counter()`, gap = t - previous, update a fixed histogram (1 ms buckets up to 100 ms, one overflow bucket), max gap, frame count, late count (gap > 1.5 x the tick, tick = 1000 / `sv_fps` ms). Nothing else on the frame: no Redis, no logging, no allocation beyond integer updates (`skills/ql-live/reference/minqlx-internals.md`, "never block the game thread").
- `sv_fps` is read at plugin load and on `new_game` / `map` hooks, so `qlx_svfps` changes are respected.
- Map load: the gap across `SV_SpawnServer` is huge by nature. The `map` hook marks the next gap as excluded.
- Every 10 s a reload-safe worker thread (stop event on unload, per `skills/minqlx-plugin-review/SKILL.md`) swaps the counters for fresh ones and writes `minqlx:frame_stats:<port>` (JSON: window, frames, late, max_ms, p50/p99 from the histogram, tick_ms) with a 30 s TTL, through the shared minqlx Redis client.
- Ships in the qlsm-extra plugin pool with its `.ql-plugin.json`, enabled per instance like the other plugins. Without it the dashboard still works, the frame columns show "no data".
- Assumption to check in step 1 of the plan: the minqlx `frame` event fires once per game frame (from `G_RunFrame`). If the engine runs catch-up frames back to back after a stall, the data shows one long gap followed by near-zero gaps; max gap and late count capture that, an average would hide it.

## 5. Addon (`addons/host-metrics/`)

Manifest (`ui_api` 3), scopes `global` and `host`:

- Global settings: thresholds from "Events", the verdict target (default 70 % of a core) and the steal limits.
- Host setting: `enabled` (default true).
- Hooks: `host.payload_sync` installs or updates the collector when the host is enabled (as file-forwarder does). No hook for removal on `host.delete`: the host is gone.
- Playbooks:
  - `sync_host_metrics.yml`: copy `hm_collect.py`, `hm_query.py`, a `VERSION` file, `config.json`, the unit; enable and restart the service. With `enabled: false` it stops and disables the service and keeps the data.
  - `status_host_metrics.yml`: version and service state, for the host modal.
- Backend routes (all `@jwt_required`):
  - `GET hosts` - every host with its snapshot and verdict. Runs `hm_query.py snapshot` on all hosts in parallel (paramiko, 5 s timeout each). The result is cached in the qlsm Redis for 30 s, as player-ranks caches (`qlsm-extra/addons/player-ranks/cache.py`), so several open tabs do not multiply SSH sessions. A host that does not answer is shown as such, not dropped.
  - `GET hosts/<id>/series?range=&port=`, `GET hosts/<id>/events?range=` - pass-through to `hm_query.py`.
  - `POST hosts/<id>/apply` - queues the sync playbook under the host lock, like file-forwarder.
- SSH: own copy of the paramiko helper from demo-management (`open_ssh`), not an import from another addon. Every command is fixed text plus validated arguments (`range` from an allow-list, `port` an int); nothing from a request reaches the shell as text.

## 6. UI (tier-2, model `qlsm-extra/addons/demo-management/`)

- **Page** `page` "Host Metrics" (opened from Addons; core gives addons no navbar entry). One row per host:
  - verdict badge and "room for N more instances" with the reason in one line;
  - per core: busiest 5-minute p95 over 24 h, steal p95;
  - RAM available, disk used;
  - instances and players now;
  - late frames over 24 h;
  - number of events over 24 h.
- **Host modal** (`host_menu`), range switch 1h / 6h / 24h / 7d / 30d:
  - per-core CPU stacked (user, system, steal);
  - CPU per instance with the player count on the same time axis (the "cost of a match" view);
  - frame gaps per instance: max and late count;
  - memory, network, disk;
  - events table;
  - service version and state, button "Apply to host".
- Charts: a small charting library bundled into `ui/Panel.js` by the Vite build (uPlot is the candidate, ~50 KB). The plan checks first whether `window.__qlsm` already exposes a chart component; if it does, use that instead.

## Verdict

Shown per host with the numbers behind it, so the operator can disagree with it.

1. **Load of one instance under play.** For each instance: p95 of its CPU % over 7 days, counting only the 10 s samples with 2+ players and state `in_progress`. The host reference `L` is the largest of these. With no such samples on the host, `L` is the median over all hosts, marked "no data under load on this host"; with no samples anywhere, no slot count is shown.
2. **Room per core.** For each core: used = sum of `L` over instances pinned to it + p95 of non-QLDS load on that core. Free slots on that core = floor((target 70 % - used) / `L`), at least 0. Host slots = sum over cores.
3. **Memory cap.** slots_mem = floor((MemAvailable - 20 % of MemTotal) / largest instance RSS). Host slots = min(cpu slots, mem slots).
4. **Status.**
   - **Overloaded**: in the last 24 h, `frames_late` or `core_saturated` with players on, or steal p95 > 15 %.
   - **Tight**: 0 slots, or steal p95 > 5 % ("noisy neighbour, numbers may get worse").
   - **OK**: otherwise, with "room for N more".

The 70 % target leaves room for frag-heavy moments and for the collector and sshd. All limits are settings.

## Testing

- Collector and query: pytest in qlsm-extra `tests/` on fixture copies of `/proc` and cgroup files (taken from germany) and a temp SQLite; roll-up, pruning, event open/close.
- Verdict: pure function, table-driven tests (pinned cores, no busy samples, steal limits, memory cap).
- Plugin: unit test of the histogram, the late count and the map-load exclusion with a fake clock, no minqlx.
- Backend: route tests with a stubbed SSH runner, as the other addons do (`QLSM_REPO=<path> python -m pytest tests/<file> -q`).
- Live: install on germany (test instance), then a real 1v1 on it; check that CPU per instance, players and frame stats line up in time, and that the SQLite size after 24 h matches the estimate.

## Open questions

- Steal and late-frame limits are first guesses. They get tuned after a week of data from germany, sweden and the first donated VPS.
- Whether `IPAccounting` per instance is worth a drop-in in v2. Decide after v1 shows how close any host is to its bandwidth.
