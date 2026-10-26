# qlmatch-packer

Builds one `.qlmatch` package (zip, STORE) per finished match from the
per-player POV `.dm_91` files and `index/*.snaps.json` that the native demo
capture of the minqlxtended fork (alexeytihomirov/minqlxtended, built on a
host with the runtime-source addon) leaves in an instance's demo directory,
Delivery off the host is not done here: the file-forwarder addon forwards
the finished files.

Contract: `ql-demo-recorder/docs/superpowers/prompts/2026-08-17-sv-demorecord-multi-pov-AGENT-PROMPT.md`,
section "Post-process (off the game thread) -> `.qlmatch`".

## How it runs in production

- Deployed to every game host at `/home/ql/qlmatch-packer/` by this addon's
  own `host.payload_sync` hook (`playbooks/sync_qlmatch_packer.yml`, run
  after host setup and after the "Update Plugins" host action). Requires
  Node.js >= 22 (installed by the same playbook from NodeSource;
  `vendor/qldemo` uses `import ... with { type: "json" }`).
- No automatic trigger: nothing launches the packer when a match ends (the
  plugin that did was retired). A first pack is built by running pack.mjs on
  the host by hand (see CLI below). The Demos screen's rebuild actions
  (`rebuild_ops.py`) run the same scripts over SSH, but only for a match that
  already has a `.qlmatch`. Output goes to `<demo_dir>/<match_id>.packer.log`;
  if the packer (or node) is missing on the host, no `.qlmatch` is built and
  only the raw `.dm_91` files remain.
- Configured per instance by a cvar set by hand in the instance's
  server.cfg (QLSM has no editor for it); a rebuild reads it from there:
  - `qlx_qlmatchNameTemplate` — output filename template (no extension)
- Delivery moved to the file-forwarder addon. A launcher that still passes
  `--rclone-targets <value>` is tolerated: the flag is accepted, ignored,
  and one line is printed to stderr.

## CLI

```
node pack.mjs --dir <demo_dir> --match-id <stamp> [--map <map>]
              [--name-template <tpl>]
              [--min-window-ms 5000] [--out-dir <dir>]
```

Exit codes: 0 ok; 2 window validation failed (empty/short POV overlap — no
zip written, raw files left in place); 3 no POV files for the match; 5 usage/IO error.

## Manifest v2 and match identity

`manifest.json` is `version: 2` (since addon 1.3.0). Added, all optional for readers:

- `match_guid` - the engine match GUID (configstring 712), lower-case UUID. Taken from the
  POV index files (`"match_guid"`) when they agree; if they disagree it is omitted and a
  warning goes to the packer log; if no index has one, from the demo gamestate - but only
  when no index is from the new fork (none has a `steam_id64` key). New-fork indexes without
  a guid mean the engine refused a stale one, so the manifest gets no `match_guid` and the
  log gets a warning (addon 1.3.1). Omitted when nothing valid is found.
- `players[]` - `{steam_id64, name, team, client_num}` for every roster player.
  `steam_id64` (17-digit string) comes from the player's own POV index only, else `null`.

`{match_id}.meta.json` stays `version: 1` and gains optional `match_guid` and
`players[].steam_id64`.

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

View direction in the sidecar (generator version 13, addon 1.3.4): every
`positions` player row has `yaw` and `pitch` in degrees (one decimal, pitch
positive looks down; the recording player's own row from the playerState, the
others from the entity's `apos`). `!restore match` turns the player to them.
A sidecar made before version 13 has no `pitch`; restore then looks level
until the pack is rebuilt.

Effects in the sidecar (generator version 12, addon 1.3.3):

- `impacts` with `kind: "explosion"` (RL, GL): one per explosion. The exploded
  missile stays in the demo's snapshots for 300 ms; only its first sighting is
  written, and the merge folds the POVs' copies within 325 ms.
- `impacts` with `kind: "shaft"`: the server's own LG hits, on a wall or on a
  player, each with its shooter's `clientNum`. The demo does not name the
  shooter (the temp entity's `clientNum` is always 0); it is the player firing
  the LG that snapshot whose aim ray the hit lies on (within 64 units).
- `beams` with `weapon_slug: "lightninggun"` are synthesized from the shooter's
  aim and end at the shooter's hit nearest in time (within 50 ms) on that ray;
  only a beam with no such hit keeps the nearest player along it or the full
  768-unit range.


## Match meta

After the pack, `pack.mjs` also writes `{match_id}.meta.json` into the demo
dir (always the demo dir, even with `--out-dir`): map, gametype, length,
roster with teams, which `.dm_91` files are this match's POVs and which
`.qlmatch` is its pack. demo-management's Demos screen reads it to label the
match and to tie a pack to its match when `qlx_qlmatchNameTemplate` gave it a
name without the match id in front. It is named after the match id, never
the template, and written to `.{match_id}.meta.json.part` then renamed, so a
reader never sees half a file and a full rebuild simply replaces it.

It only labels files - the directory listing still decides what exists, so
deleting a match's files (`rm <demo_dir>/<match_id>*`) takes the meta with
it, and a leftover meta whose files are gone is ignored. A failure to write
it is logged and never fails the pack; packs from before this file existed
are labelled from their `manifest.json` (read once, then cached in Redis).
Format: demo-management's `demo_meta.py`.
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
qlsm has since carried its own fixes on top of it without merging them back.
**It is an independent fork, not a mirror.** The `ql-stream-tools` repository
was archived on 2026-10-14, so this directory is now the canonical copy and
there is nothing to sync from; change it here.

`maps/entities/` (per-map pickup tables, originally from
`ql-stream-tools/live-overlay/maps/entities/`, no qlsm-side edits) is likewise
canonical here: the sidecar merge needs these tables to resolve item
classnames on the game host (`map-item-resolve.node.js` resolves them relative
to this directory). See `vendor/VENDOR-INFO.txt` for the origin.

`vendor/qldemo/test-support/` holds the two encode-side modules
(`gamestate-writer.js`, `huffman-write.js`) that `demo-parser.test.mjs` uses to
build wire-format fixtures. They were carried from `ql-stream-tools@31fd6c0`
(`demo-editor/lib/`) so the tests run without a checkout of that repository.
Run the vendored tests with `node --test vendor/qldemo/*.test.mjs` from this
directory.
