# qlsm-extra

Optional **plugins** and **addons** for [qlsm](https://github.com/alexeytihomirov/qlsm)
that do **not** ship in the standard qlsm image / plugin pools.

| Kind | What |
|------|------|
| Plugins | QLMatch tournament gameplay (`tournament_access`, `chat_rcon`, `lobby`, `match_restore` family), live telemetry for the `minqlxtended` runtime |
| Addons | `telemetry-relay`, `demo-management`, `demo-stream`, `qlmatch-packer`, `file-forwarder`, `runtime-source`, `player-ranks` |

Merged from the former local `minqlxtended-plugins` and `qlsm-addons` trees.

## Install via qlsm Repositories

1. In qlsm: **Settings → Repositories → Add**, URL:

   `https://raw.githubusercontent.com/alexeytihomirov/qlsm-extra/main`

2. Sync, then download plugins / install addons from the list.

The root file `qlsm-repository.json` lists both. Plugin files sit at the repo
root (one bare `.py` per download). Addon packages are the `.zip` files under
`packages/`.

After changing any listed `.py` or anything under `addons/`, run:

```bash
python generate_manifest.py
```

and commit the updated `qlsm-repository.json` + `packages/*.zip`.

### Manifest hash guard (pre-commit)

If you change a packaged file and forget to re-run `generate_manifest.py`,
`qlsm-repository.json` publishes a stale sha256 and Repositories sync/update
fails hash checks on the client. A local pre-commit hook catches that before
the commit lands.

Enable once per clone (hooks are not auto-installed by git):

```bash
git config core.hooksPath hooks
```

The hook runs `check_manifest_hashes.py`: every `sha256` in
`qlsm-repository.json` (plugin `.py`, `package_files`, addon zips) must match
the file on disk. Mismatch → commit blocked; fix with
`python generate_manifest.py` and stage the refreshed manifest (and zips).

Manual check without committing:

```bash
python check_manifest_hashes.py
```


## Plugins

| File | Loadable alone? |
|------|-----------------|
| `tournament_access.py` | Yes |
| `chat_rcon.py` | Yes |
| `lobby.py` | Yes |
| `referee_call.py` | Yes - `!call` for players; the call travels as chat through `stream_telemetry_unified` (Session Events on) |
| `match_restore_util.py` | No - helper for `match_restore.py`, downloaded with it |
| `match_restore.py` + `restore/` | Yes - downloads as one entry |
| `qlmatch_packer.py` | Yes - launches the `qlmatch-packer` addon's `pack.mjs` when the engine finishes a match's demos; **required** for automatic `.qlmatch` (without it only raw `.dm_91` remain). Downloads with its helper `qlmatch_packer_cmd.py` (not a plugin) |
| `demo_stream_resync_hold.py` | Yes - after the engine forces a full snapshot for a live-streamed player (relay reconnect, lost blocks, keyframe), keeps forcing one per server frame until the client acknowledges it (at most `qlx_demoStreamResyncHoldMaxFrames`, default 8; at most `qlx_demoStreamResyncHoldPerFrame` holds at once, default 2). **Off by default** (`qlx_demoStreamResyncHold 0`): measured on a duel server only, not yet on a populated server or in team modes; set it to 1 to enable. With `sv_demoStreamKeyframeSec 0` there are no keyframe holds, but a relay reconnect and lost blocks are still repaired, the first player after a reconnect included. `qlx !resynchold` prints the counters, `qlx !resynchold log` the last holds. Needs the fork's live demo stream |

`match_restore.py` needs the `restore/` package beside it. Its manifest entry
declares `package_files` for every file under `restore/`, so downloading
`match_restore.py` from the Repositories page fetches the whole folder with
it. `generate_manifest.py` regenerates that list from `PACKAGE_FOLDERS`.

All plugins here need the `minqlxtended` runtime (every entry in `qlsm-repository.json` says `"runtime": "minqlxtended"`). Native demo capture needs the [alexeytihomirov/minqlxtended](https://github.com/alexeytihomirov/minqlxtended) fork, which a host gets through the `runtime-source` addon.

### Live telemetry (minqlxtended runtime)

| File | Loadable alone? |
|------|-----------------|
| `telemetry_unified_sched.py` | No - helper for `stream_telemetry_unified.py` |
| `stats_hub_pause.py` | No - helper for `stream_telemetry_unified.py` |
| `stream_telemetry_unified.py` | Yes - live positions, item pickups and match events to the host's telemetry relay |

`stream_telemetry_unified.py` puts the engine match GUID (configstring 712, lower-case
UUID) into `meta.match_guid` of the session lifecycle events `countdown_start`,
`match_start` and `match_end`; it is omitted when the server does not know it yet, and
when it equals the guid sent with the previous `match_end` (712 still holding the last
game's value; logged as a warning). It
is the key that ties a hub result, a `.qlmatch` pack and a tournament game together
(see `addons/qlmatch-packer/assets/README.md` for the manifest side).

`match_end` also carries `players[].stats` for every non-spectator: the engine's own
end-of-game numbers (`Player.expanded_stats`, minqlxtended fork), read once on the game
thread. Shape: `time_ms`, `dmg_dealt`, `dmg_taken`, `kills`, `deaths`, `suicides`,
`max_streak`, `weapons` (keys `g, mg, sg, gl, rl, lg, rg, pg, bfg, ng, pl, cg, hmg`, each
`{k, d, s, h, dd, dt, p, t}` = kills, deaths, shots, hits, damage dealt, damage taken,
pickups, ms held; an all-zero weapon is left out) and `pickups`
(`mega, ra, ya, ga, health, ammo`). A player whose stats cannot be read has no `stats`
(one warning in the log) and the event is still sent. The stats hub keeps them in the
result snapshot and the tournament site shows them (ql-tournament `docs/DEVELOPMENT.md`,
"Tournament player stats").

These three only need the generic `minqlxtended` runtime, not the
`alexeytihomirov/minqlxtended` fork specifically - nothing here touches the
fork's native demo capture.

Native per-match demo capture (`sv_demoRecord`/`sv_demoCut`) is the engine's
own feature on that fork. `qlmatch_packer.py` (formerly `demo_native_autorecord.py`,
which hosts may still carry) only reacts to the engine's `demo_match_finalized`
event and launches `pack.mjs` from the `qlmatch-packer` addon. When migrating a
host, replace `demo_native_autorecord` with `qlmatch_packer` in `qlx_plugins`
(never both: the packer would run twice). Shipping the files off the host is the
`file-forwarder` addon. A compat shim resolving a bare
`import minqlx` to `minqlxtended` (for plugins like `ips.py` that don't know
about the fork) was also dropped, since nothing in this repo needs it - add
one back if a plugin like that is added here later.

## Addons

Source lives under `addons/<id>/`. Published packages are `packages/<id>.zip`
(contents of the addon directory, `qlsm-addon.json` at the zip root).

| Addon | Role |
|-------|------|
| `telemetry-relay` | Per-host relay that forwards `stream_telemetry_unified` data to ql-stats-hub; enable per host, then per instance on its Telemetry tab |
| `demo-management` | The **Demos** screen: lists and downloads what an instance recorded |
| `demo-stream` | Live POV demo stream through a central relay; per-host stunnel TLS tunnel to stats-hub; per-instance stream delay set on stats-hub without a restart |
| `qlmatch-packer` | Installs the `.qlmatch` packer on hosts; shows and rebuilds packs on the Demos screen |
| `file-forwarder` | Ships demo files (.qlmatch packs, replay sidecars, raw demos) from game hosts to the VPS over SFTP, keeps a delivery ledger, cleans up delivered raw demos, and offers manual sync from the host menu |
| `runtime-source` | Builds a host's minqlxtended from a repository you choose (a fork) instead of the commit qlsm pins. Per host: enable, enter repository + commit, then **Re-run Host Setup**. Needs a QLSM whose host setup supports a custom minqlxtended repository on every provider (`host.setup` hook). |
| `player-ranks` | Shows external ratings (qlstats, Slipgate, x76) stacked in one Rank column in Live Status. Sources are chosen per instance on its Ranks tab; qlstats/Slipgate connection details are set once for the installation. Needs qlsm `ui_api` 4 or newer. |

qlsm's image ships **no** addon — install every one of these from this
repository. `qlmatch-packer` extends `demo-management`'s screen, so it is only
useful with it installed too.

**demo-stream 1.2.0:** the stream now goes through a per-host stunnel TLS
tunnel (Hosts -> Demo Stream Tunnel). Instances enabled under 1.1.1 still point
straight at the relay over plain TCP and must be re-enabled (Live Demo Stream
tab) after the host tunnel is on.

**demo-stream 1.3.0:** each streaming instance has a Demo Stream Delay menu
entry: the delay stats-hub puts on its stream, 0 to 300 seconds, blank for the
hub default. Saving is one call to stats-hub, so it applies immediately,
without restarting the instance or changing its `server.cfg`; viewers already
watching are reconnected when the delay goes down. Needs a stats-hub that has
the per-server delay API (`/api/demo-stream/servers/<id>/delay`); with an older
hub the panel says so and nothing else changes.

### player-ranks

Three rating sources, stacked in one Rank column in Live Status (a generic
`live_status_columns` mount point qlsm's core provides, so this addon owns
everything about what a rating means and where it comes from):

- **qlstats** and **Slipgate** keep their connection details (base URL, key,
  rating system) under Settings -> Addons -> Player Ranks, set once for the
  installation.
- **x76** (elo-service) is configured per instance: base URL, API key, pool,
  and whether the column shows the score or the rank label. A rank label is
  shown in its tier's in-game colour (yellow for Gold, cyan for Platinum, ...)
  on a qlsm whose `live_status_columns` cell supports `color`; an older qlsm
  shows the same label uncoloured.
- **Which sources an instance shows** is chosen with checkboxes on that
  instance's own "Ranks" tab. A new instance starts with every source off.

A source that's off, or needs a key that isn't set, simply shows no line in
the Rank column -- this is normal, not a broken state. Per-source specifics
(what a key changes, rated game types, caching) are in the field descriptions
on the relevant panel and in `qlsm-addon.json`. A third-party addon can add a
further source via the `player_ranks.providers` hook without touching this
addon's code (see qlsm's `addons/README.md`, "Cross-addon UI contribution").

Framework docs: qlsm's `addons/README.md`, `addons/TRUST.md`, `addons/UI-GUIDE.md`.
Addons run in-process with qlsm's full authority — only install what you trust.

### Building an addon's UI

`demo-management` ships a **tier-2** component: its own pre-built
`ui/Panel.js` + `ui/Panel.css`, built from `ui-src/` with Vite. qlsm installs
a zip and can never build anything, so the built files are committed; the
sources and toolchain are not part of the package (`generate_manifest.py`
skips them).

```bash
cd addons/demo-management
npm install
npm run build          # writes ui/Panel.js + ui/Panel.css
cd ../.. && python generate_manifest.py
```

Re-run both after any change under `ui-src/`, or the package ships a stale
screen.

## Tests

The addons here import qlsm's own modules (`ui.db`, `ui.models`,
`ui.addons`), so their tests need a qlsm checkout. Keep one next to this repo
or point `QLSM_REPO` at it; without one every test skips.

```bash
QLSM_REPO=/path/to/qlsm python -m pytest tests/ -q
```

Each addon installs into a temporary addon-packages volume for the run, which
is also the only way qlsm can load one now.

## Layout

```
qlsm-extra/
  qlsm-repository.json   # plugins + addons index for qlsm Repositories
  generate_manifest.py   # refresh hashes + rebuild packages/*.zip
  check_manifest_hashes.py  # verify manifest sha256 vs disk (pre-commit)
  hooks/pre-commit       # blocks commit when hashes are stale
  *.py / *.ql-plugin.json / restore/   # plugins (root = download URLs)
  addons/<id>/           # addon sources
  addons/<id>/ui-src/    # tier-2 UI sources (built into ui/, not packaged)
  packages/<id>.zip      # installable addon packages
  tests/                 # pytest suite, needs a qlsm checkout
```
