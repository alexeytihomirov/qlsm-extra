# qlsm-extra

Optional **plugins** and **addons** for [qlsm](https://github.com/alexeytihomirov/qlsm)
that do **not** ship in the standard qlsm image / plugin pools.

| Kind | What |
|------|------|
| Plugins | QLMatch tournament gameplay (`tournament_access`, `chat_rcon`, `lobby`, `match_restore` family) |
| Addons | `telemetry-relay`, `demo-stream`, `qlmatch-packer` |

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

## Plugins

| File | Loadable alone? |
|------|-----------------|
| `tournament_access.py` | Yes |
| `chat_rcon.py` + `chat_rcon_acl.py` | Yes, both together |
| `lobby.py` | Yes |
| `match_restore_util.py` | No — helper for `match_restore.py` |
| `match_restore_lab.py` | Optional add-on to `match_restore.py` |
| `match_restore.py` + `restore/` | Yes together — **not** in the repository manifest |

`match_restore.py` needs the `restore/` package beside it. qlsm's repository
download is one bare filename per click, so that pair is left out of
`qlsm-repository.json`. Copy `match_restore.py`, `match_restore.ql-plugin.json`,
and the whole `restore/` directory into the host's `minqlx` plugin pool by hand
(same as before).

These plugins assume qlsm's `minqlxtended-patched` runtime
([alexeytihomirov/minqlxtended](https://github.com/alexeytihomirov/minqlxtended)).

## Addons

Source lives under `addons/<id>/`. Published packages are `packages/<id>.zip`
(contents of the addon directory, `qlsm-addon.json` at the zip root).

| Addon | Role |
|-------|------|
| `telemetry-relay` | Per-host relay → ql-stats-hub telemetry |
| `demo-stream` | Live POV demo stream screen + cvars |
| `qlmatch-packer` | Host-side `.qlmatch` packer + Demos grouping hooks |

Framework docs: qlsm's `addons/README.md`, `addons/TRUST.md`, `addons/UI-GUIDE.md`.
Addons run in-process with qlsm's full authority — only install what you trust.

## Layout

```
qlsm-extra/
  qlsm-repository.json   # plugins + addons index for qlsm Repositories
  generate_manifest.py   # refresh hashes + rebuild packages/*.zip
  *.py / *.ql-plugin.json / restore/   # plugins (root = download URLs)
  addons/<id>/           # addon sources
  packages/<id>.zip      # installable addon packages
```
