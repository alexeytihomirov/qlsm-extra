# qlsm-extra

Optional **plugins** and **addons** for [qlsm](https://github.com/alexeytihomirov/qlsm)
that do **not** ship in the standard qlsm image / plugin pools.

| Kind | What |
|------|------|
| Plugins | QLMatch tournament gameplay (`tournament_access`, `chat_rcon`, `lobby`, `match_restore` family), live telemetry for the `minqlxtended` runtime |
| Addons | `telemetry-relay`, `demo-management`, `demo-stream`, `qlmatch-packer`, `player-ranks` |

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
| `chat_rcon.py` + `chat_rcon_acl.py` | Yes, both together |
| `lobby.py` | Yes |
| `match_restore_util.py` | No — helper for `match_restore.py` |
| `match_restore_lab.py` | Optional add-on to `match_restore.py` |
| `match_restore.py` + `restore/` | Yes together — downloads as one entry |

`match_restore.py` needs the `restore/` package beside it. Its manifest entry
declares `package_files` for every file under `restore/`, so downloading
`match_restore.py` from the Repositories page fetches the whole folder with
it. `generate_manifest.py` regenerates that list from `PACKAGE_FOLDERS`.

These plugins assume qlsm's `minqlxtended-patched` runtime
([alexeytihomirov/minqlxtended](https://github.com/alexeytihomirov/minqlxtended)).

### Live telemetry (minqlxtended runtime)

| File | Loadable alone? |
|------|-----------------|
| `telemetry_unified_sched.py` | No — helper for `stream_telemetry_unified.py` |
| `stats_hub_pause.py` | No — helper for `stream_telemetry_unified.py` |
| `stream_telemetry_unified.py` | Yes — live match/player/pickup telemetry to `ql-telemetry-relay` |

These three only need the generic `minqlxtended` runtime, not the
`alexeytihomirov/minqlxtended` fork specifically — nothing here touches the
fork's native demo capture.

Native per-match demo capture (`sv_demoRecord`/`sv_demoCut`) is the engine's
own feature on that fork; this repo no longer ships a plugin to launch the
`.qlmatch` packer automatically when a match finishes. Building a `.qlmatch`
for a finished match is manual for now — use the qlmatch-packer addon's
rebuild action from the Demos screen. A compat shim resolving a bare
`import minqlx` to `minqlxtended` (for plugins like `ips.py` that don't know
about the fork) was also dropped, since nothing in this repo needs it — add
one back if a plugin like that is added here later.

## Addons

Source lives under `addons/<id>/`. Published packages are `packages/<id>.zip`
(contents of the addon directory, `qlsm-addon.json` at the zip root).

| Addon | Role |
|-------|------|
| `telemetry-relay` | Per-host relay → ql-stats-hub telemetry |
| `demo-management` | The **Demos** screen: lists and downloads what an instance recorded |
| `demo-stream` | Live POV demo stream screen + cvars |
| `qlmatch-packer` | Host-side `.qlmatch` packer + Demos grouping hooks |
| `player-ranks` | Adds external rating columns to Live Status. qlstats/Slipgate are one installation-wide switch each; Thunderdome elo-service/server-status are per instance. Needs qlsm `ui_api` 4 or newer. |

qlsm's image ships **no** addon — install every one of these from this
repository. `qlmatch-packer` extends `demo-management`'s screen, so it is only
useful with it installed too.

### player-ranks

Four rating sources, each its own column in Live Status (a generic
`live_status_columns` mount point qlsm's core provides, so this addon owns
everything about what a rating means and where it comes from):

- **qlstats** and **Slipgate** are installation-wide switches -- turn one on
  from Settings -> Addons -> Player Ranks and it applies to every instance
  identically, no per-server setup. There is nothing instance-specific about
  either (same public service, same rating system for everyone).
- **Thunderdome elo-service** and **the server's own status data** are
  configured per instance, on that instance's own "Ranks" tab -- a different
  elo-service host/pool per server is the normal case.

A source that's off, or needs a key that isn't set, simply shows no extra
column -- this is normal, not a broken state. Per-source specifics (what a
key changes, rated game types, caching) are in the field descriptions on the
relevant panel and in `qlsm-addon.json`. A third-party addon can add a
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
