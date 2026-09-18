# qlmatch-packer

Builds one `.qlmatch` package (zip, STORE) per finished match from the
per-player POV `.dm_91` files + `index/*.snaps.json` that minqlxtended's
native demo capture (`demo_match.c`, vendored in
`ql-assets/patches/minqlxtended/`) leaves in an instance's demo directory,
then optionally delivers it to any number of rclone targets.

Contract: `ql-demo-recorder/docs/superpowers/prompts/2026-08-17-sv-demorecord-multi-pov-AGENT-PROMPT.md`,
section "Post-process (off the game thread) -> `.qlmatch`".

## How it runs in production

- Deployed to every game host at `/home/ql/qlmatch-packer/` by this addon's
  own `host.payload_sync` hook (`playbooks/sync_qlmatch_packer.yml`, run
  after host setup and after the "Update Plugins" host action). Requires
  Node.js >= 22 (installed by the same playbook from NodeSource;
  `vendor/qldemo` uses `import ... with { type: "json" }`).
- Launched by `demo_native_autorecord.py` (plugin pool) as a **separate
  process** on `demo_match_finalized` — never on the QLDS game thread and
  never inside the QLDS process. Output goes to
  `<demo_dir>/<match_id>.packer.log`; if the packer (or node) is missing on
  the host, no `.qlmatch` is built for that match — only the raw `.dm_91`
  files remain (there is no in-process fallback build anymore).
- Configured per instance via plugin cvars (editable from the QLSM Plugins
  tab, delivered through server.cfg like every other setting):
  - `qlx_qlmatchNameTemplate` — output filename template (no extension)
  - `qlx_qlmatchRcloneTargets` — comma-separated rclone destinations
    (e.g. `gdrive:ql-demos/frontier,/home/ql/qlmatch-archive`)
- rclone itself must be installed and its remotes configured on the game
  host by the operator (`rclone config`); the packer only calls
  `rclone copy <pack> <target>` per target.

## CLI

```
node pack.mjs --dir <demo_dir> --match-id <stamp> [--map <map>]
              [--name-template <tpl>] [--rclone-targets a,b]
              [--min-window-ms 5000] [--out-dir <dir>]
```

Exit codes: 0 ok; 2 window validation failed (empty/short POV overlap — no
zip written, raw files left in place); 3 no POV files for the match; 4 pack
written but >= 1 rclone delivery failed; 5 usage/IO error.

## Replay sidecar

After writing a pack, `pack.mjs` spawns `qlmatch-to-replay.mjs` (child
process) to merge the N POV demos into one deduplicated replay-v2 JSON and
write it as `{match_id}_{map}.replay.json.gz` **next to** the pack — never
inside the zip (the `.qlmatch` contract forbids decoded dumps in the
package). Consumers: `!restore match` (`restore/qlmatch.py`
`sidecar_path_for()` — the filename is `{match_id}_{map}`, not the pack's
templated name) and the dashboard `#/demo` view. A sidecar failure is
logged to `<match_id>.packer.log` but never fails the pack; regenerate any
sidecar by hand (idempotent — byte-identical output for the same pack):

```
node qlmatch-to-replay.mjs <pack.qlmatch> [-o out.replay.json.gz]
```

Without `-o` the sidecar lands next to the pack named after the pack's own
basename; pass `-o` with `{match_id}_{map}.replay.json.gz` when the pack
filename template differs, or `!restore match` will not find it.
`meta.generator_version` in the JSON tracks the merge algorithm
(`MATCH_REPLAY_GENERATOR_VERSION` in `vendor/qldemo/match-to-replay.js`) so
stale sidecars can be detected and regenerated after upgrades.

## Filename template placeholders

Every substitution is stripped of QL color codes and sanitized to
`[A-Za-z0-9._-]`. Default template: `{match_id}_{map}`.

| Placeholder | Meaning |
|---|---|
| `{match_id}` | UTC match stamp, e.g. `20260816T161443Z` |
| `{date}` / `{time}` | `20260816` / `161443` from the stamp |
| `{map}` | map name |
| `{gametype}` | short gametype (`ffa`, `duel`, `tdm`, `ca`, `ctf`, ...) |
| `{players}` | all non-spectator players, `-`-joined |
| `{pov_players}` | players that actually have a POV demo in this pack |
| `{total_players}` | player count |
| `{red_count}` / `{blue_count}` | per-team player counts |
| `{red_players}` / `{blue_players}` | per-team name lists |
| `{teams}` | `red1-red2_vs_blue1-blue2` (or `{players}` in non-team modes) |

If the rendered name lacks the match stamp and a file with that name already
exists, `_{match_id}` is appended instead of overwriting the previous match.

## vendor/qldemo

Originally vendored from the **production** demo parser
`ql-stream-tools/live-overlay/lib/qldemo/` (not the stale
`_tmp/overkilldemos/qldemo-nquery` snapshot the first prototype used), but
qlsm has since carried its own fixes on top of it without merging them back
upstream. **It is now an independent fork, not a mirror** — do not run
anything that copies `ql-stream-tools/live-overlay/lib/qldemo/` over this
directory (or vice versa); that would silently discard whichever side's
fixes the other is missing.

`maps/entities/` is different: it's a plain data vendor (per-map pickup
tables) from `ql-stream-tools/live-overlay/maps/entities/` with no qlsm-side
edits, so it's still safe to refresh for real — the sidecar merge needs
these tables to resolve item classnames on the game host
(`map-item-resolve.node.js` resolves them relative to this directory).

Run `bash sync-vendor.sh` (from a monorepo workspace, or
`bash sync-vendor.sh /path/to/ql-stream-tools` from anywhere, e.g. a qlsm
git worktree) to diff `vendor/qldemo` against upstream (report only, no
files touched) and refresh `maps/entities/` for real — see
`vendor/VENDOR-INFO.txt`.
