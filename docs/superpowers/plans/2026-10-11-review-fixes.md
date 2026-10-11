# Review Fixes 2026-10-11 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Operator-readable English descriptions for every plugin and addon, plus fixes (each with a test) for the eight bugs the 2026-10-11 review ranked.

**Architecture:** Each fix stays inside the file that owns the behaviour; where a handler is hard to test, the decision moves into a small pure function next to it (restore/items.py, telemetry_unified_sched.py, tournament_access.py). Plugin tests import the plugin against one shared minqlxtended stand-in (`tests/_minqlx_stub.py`); addon tests use the existing qlsm `app` fixture from `tests/conftest.py`.

**Tech Stack:** Python 3.12, pytest, minqlxtended plugin API (stubbed), qlsm addon framework (Flask, RQ, SQLAlchemy) from the QLSM checkout.

**Spec:** No separate spec document. The controller's brief for task `tasks/0003-review-fixes-descriptions-in-english-and-the-sev.md` is the spec; where the code differs from the brief, see "Plan notes" at the end.

Repository: `C:/Users/hellp/orca/workspaces/qlsm/qlsm-extra-review` (worktree, branch `fix/review-2026-10-11`, base origin/main f74474b). QLSM checkout for the addon framework: `C:/Users/hellp/orca/workspaces/qlsm/QLSM`.

## Global Constraints

- Commits authored as the user only; no AI attribution lines (no `Co-Authored-By`, no "Generated with"). Commit messages in English, imperative, one topic each.
- The repo pre-commit hook (`core.hooksPath` -> `hooks/pre-commit`, runs `check_manifest_hashes.py`) blocks a commit when any listed `.py`, `restore/*` file or `addons/<id>/` zip is out of sync with `qlsm-repository.json`. Therefore every task that touches a listed plugin file or anything under `addons/` must run `python generate_manifest.py` before `git add` and include `qlsm-repository.json` and the changed `packages/*.zip` in the commit. Tasks touching only `tests/`, `docs/`, `tasks/` or README do not need it.
- In this worktree `core.hooksPath` is the absolute path `D:\QuakeLiveData\QL Server\qlsm-extra\hooks`, so the hook checks the main checkout, not this worktree. Every commit step therefore runs `python check_manifest_hashes.py` here first; expected output: `qlsm-repository.json: all sha256 hashes match on-disk files.`
- Tests: `QLSM_REPO=C:/Users/hellp/orca/workspaces/qlsm/QLSM python -m pytest tests/ -q -p no:cacheprovider` must stay green (256 passed at base). If pytest output looks swallowed, prefix with `rtk proxy `. Single tests below use the same prefix: `QLSM_REPO=C:/Users/hellp/orca/workspaces/qlsm/QLSM python -m pytest <path>::<name> -q -p no:cacheprovider`.
- Minimal diff, match existing patterns, no refactors beyond the fix. Do not bump addon `version` fields except where a task says so (Tasks 8 and 9 do, see Plan notes 6).
- No new runtime dependencies.
- All user-facing text (descriptions, messages) in English. Hyphens only, never em or en dashes, in any text we write.

## Review Focus

1. Relay unreachable long enough for the session queue to hit its 512-row cap while a batch is in flight: the oldest rows are dropped and the in-flight batch's ack must still remove exactly the rows it delivered. Pinned by `test_ack_after_the_cap_dropped_the_oldest_row` (Task 4).
2. `!rcon` typed in team chat or quoted by the client (`say_team !rcon ...`, `say "!rcon ..."`): must not reach the hub either. Pinned by `test_rcon_chat_lines_are_not_forwarded` and `test_team_chat_rcon_is_not_queued` (Task 5).
3. An item picked up during warmup (match clock 0) or while a restore session is active must not leave a pending respawn timer in the next export. Pinned by `test_pickup_at_match_time_zero_is_forgotten` and `test_on_item_event_ignores_pickups_during_a_restore_session` (Task 2).
4. A tournament server whose roster is not enforced (hub flag off) must still keep a `StreamSpec` account in spectator, while an enforced roster kicks an unlisted one. Pinned by the `decide_loaded` table (Task 7).
5. Enabling telemetry or the demo stream on a STOPPED instance that then fails: the instance must go back to STOPPED, not RUNNING or CONFIGURING. Pinned by `test_failed_enable_restores_the_previous_status` (Task 9, both addons).

---

## File Structure

| File | Change |
|------|--------|
| `README.md`, `*.ql-plugin.json`, `qlsm-repository.json`, `addons/*/qlsm-addon.json`, `addons/qlmatch-packer/assets/README.md`, `addons/qlmatch-packer/assets/pack.mjs`, `addons/qlmatch-packer/playbooks/sync_qlmatch_packer.yml`, `match_restore_lab.py` | Task 1: copy only |
| `tests/_minqlx_stub.py` (new) | Task 2: shared minqlxtended stand-in for plugin tests |
| `restore/items.py`, `match_restore.py` | Task 2 (pickup tracking), Task 3 (velocity flush) |
| `telemetry_unified_sched.py`, `stream_telemetry_unified.py` | Task 4 (session ack), Task 5 (`!rcon` filter) |
| `chat_rcon.py`, `chat_rcon_acl.py` | Task 6 |
| `tournament_access.py`, `tournament_access.ql-plugin.json` | Task 7 |
| `addons/qlmatch-packer/rebuild_tasks.py` | Task 8 |
| `addons/telemetry-relay/{instance_ops,backend}.py`, `addons/demo-stream/{instance_ops,backend}.py` | Task 9 |
| `tasks/0003-review-fixes-descriptions-in-english-and-the-sev.md` | Task 10 |

---

### Task 1: Descriptions in English

**Files:**
- Modify: `README.md:9`, `README.md:58-97`, `README.md:104-111`
- Modify: `chat_rcon.ql-plugin.json`, `chat_rcon_acl.ql-plugin.json`, `lobby.ql-plugin.json`, `match_restore.ql-plugin.json`, `match_restore_lab.ql-plugin.json`, `match_restore_util.ql-plugin.json`, `referee_call.ql-plugin.json`, `stats_hub_pause.ql-plugin.json`, `stream_telemetry_unified.ql-plugin.json`, `telemetry_unified_sched.ql-plugin.json`, `tournament_access.ql-plugin.json`
- Modify: `match_restore_lab.py:69` (in-game usage string only)
- Modify: `addons/demo-management/qlsm-addon.json:5`, `addons/demo-stream/qlsm-addon.json:4-5`, `addons/qlmatch-packer/qlsm-addon.json:5`, `addons/runtime-source/qlsm-addon.json:5`, `addons/telemetry-relay/qlsm-addon.json:5,42,46` (`addons/player-ranks/qlsm-addon.json` is already accurate: unchanged)
- Modify: `addons/qlmatch-packer/assets/README.md:3-7,19-31`, `addons/qlmatch-packer/assets/pack.mjs:11-14`, `addons/qlmatch-packer/playbooks/sync_qlmatch_packer.yml:3-6`
- Regenerate: `qlsm-repository.json`, `packages/*.zip`

**Interfaces:**
- Consumes: nothing.
- Produces: `chat_rcon.py` no longer `depends_on` `chat_rcon_acl.py` (sidecar and manifest); every plugin entry in `qlsm-repository.json` has `"runtime": "minqlxtended"`. Task 7 appends one sentence to the `tournament_access.ql-plugin.json` description written here.

Why the manifest needs a reset first (verified, `generate_manifest.py:133-147`): for plugins the existing manifest entry's `label`/`description`/`runtime` win over the sidecar, and `depends_on` falls back to the old manifest value when the sidecar has none. Editing sidecars alone changes nothing in `qlsm-repository.json`.

- [ ] **Step 1: Rewrite the plugin sidecars**

Replace only the listed strings; every other field stays as is. `<blank>` labels mean "unchanged".

`chat_rcon.ql-plugin.json`
- `description`: `Lets referees and admins run server console commands from chat with !rcon <command>. Referees (permission level Referee Permission Level and up) may run only the Referee-Allowed Commands; admins (Admin Permission Level and up) may run anything except the Admin-Denied Commands. Takes over the stock !rcon while enabled, and every use is written to the server log.`
- command `rcon` `description`: `Runs a console command from chat if your permission level allows it.`
- delete the `"depends_on": ["chat_rcon_acl.py"]` line (and the trailing comma before it).

`chat_rcon_acl.ql-plugin.json`
- `label`: `⚠️ chat_rcon test copy - not a plugin, do not enable`
- `description`: `A copy of chat_rcon's permission rules that this repository's tests import. chat_rcon.py has the same rules built in and does not need this file on a server.`

`lobby.ql-plugin.json`
- `description`: `For a lobby server: tells each player which game server to join and shows its /connect address on screen after a short countdown. Quake Live does not let a server move a player, so players type the command themselves. A player's destination comes from a personal route set by a referee, a tournament assignment the hub writes into the server's Redis, or the default destination.`
- commands:
  - `lobby`: `Lists the destination servers and your own route.`
  - `go`: `Shows the /connect address of a destination: the slug you give, else your route, else the default.`
  - `lobbyset`: `Saves a personal route for a player (client id or name).`
  - `lobbyclear`: `Removes a player's personal route; without an id, removes your own.`
  - `lobbysend`: `Shows a player the /connect address of a destination now: the slug you give, else their route.`
  - `lobbynotify`: `Re-checks tournament assignments from the hub for everyone on the server and shows any new ones.`
  - `servers`, `join`, `play`, `hubnotify`: unchanged.
- cvars:
  - `qlx_lobbyEnabled`: `Turns automatic routing on or off. When off, !go and !lobbysend still work and players may join teams.`
  - `qlx_lobbyPublicHost`: `Address players are told to connect to. Empty uses net_ip, else 127.0.0.1. A destination whose host is HOST uses this address.`
  - `qlx_lobbyDestinations`: `Destination servers, separated by semicolons. Each is slug|host|port|label|password|tags; password and tags are optional. Example: c1|HOST|27961|Championship 1`
  - `qlx_lobbyDefaultDest`: `Slug used for players without a personal route. With only one destination configured, that one is used.`
  - `qlx_lobbyAutoRedirect`: `After a player loads, counts down and then shows the /connect address of their destination, without waiting for !go.`
  - `qlx_lobbyRedirectDelay`: `Length of that countdown in seconds.`
  - `qlx_lobbyForceSpec`: `Moves every player to spectator when they load into the lobby.`
  - `qlx_lobbyStayPerm`: `Players with at least this permission level, and the server owner, are not routed and may join teams.`
  - `qlx_lobbyConnectMessage`: `Extra line shown on screen when a player uses !go or is sent with !lobbysend.`
  - delete the `qlx_lobbyTrySteamOpen` entry (`lobby.ql-plugin.json:26`; the code never reads it).
  - `qlx_lobbyInstancesJson`: `Path on the game host to a JSON file with an "instances" list. Each enabled, non-lobby instance becomes a destination on port 27960 plus its id. Destinations above win on a slug clash.`
  - `qlx_hubNotifyDelay`: label `Hub Countdown (s)`, description `Seconds a player counts down before the /connect address of their tournament server appears, when the hub's assignment does not set its own delay.`
  - `qlx_hubNotifyCountdown`: label `Hub Countdown`, description `When on, a tournament assignment from the hub is shown after that countdown; when off, at once. !lobby and !go never count down.`

`match_restore.ql-plugin.json`
- `description`: `Saves the state of a running match and puts it back later. A checkpoint holds player positions, health, armor, weapons, ammo, powerups and score, item respawn timers, dropped items and the match clock. Admins (permission 5) build, check and apply checkpoints with !restore, or restore a moment from a recorded .qlmatch demo pack. Needs the minqlxtended runtime; downloading it also fetches the restore/ folder.`
- both commands `usage`: `export | test [name] | quiet | loud | clear | time | map | player | item | apply | verify | show | players [slot:cid...] | match list [filter] [page] | match <N> <mm:ss>` (identical to `match_restore.py:264-265`).
- command `restore` `description`: `export writes the current state as checkpoint JSON to the server log. clear, time, map, player and item build a checkpoint line by line; show and verify check it; apply restores it. match list and match <N> <mm:ss> restore a moment from a .qlmatch pack on this server. test [name] loads a checkpoint file from a data/checkpoints/ folder next to the plugin; none ship with this repository.`
- cvars:
  - `qlx_matchRestoreLabEnabled`: `Turns match_restore on or off. The match_restore_lab commands share this switch.`
  - `qlx_matchRestoreUnfreezeDelaySec`: `Seconds after an unpause before the match clock runs again, to cover the 3-2-1 unfreeze countdown.`
  - `qlx_matchRestoreNativeClock`: unchanged.

`match_restore_lab.ql-plugin.json`
- `description`: `Extra test and debug commands for match_restore: item respawn timers, item entity tools, setting the match clock by hand and restoring a single player. Not needed for a real restore. Needs match_restore enabled.`
- commands `itemlab` and `itemslot` `usage`: `touch <eid> [cid] | touchat <eid> <sec> [cid] | respawn <eid> <sec> | stat <eid>`
- command `itemlab` `description`: `Item entity tools: pick an item up now or after a delay, respawn it after a delay, or show its state.`
- command `spawnsec` `description`: `Hides an item and shows it again after the given seconds; list, scan and reset manage this map's overrides.`
- cvar `qlx_matchRestoreLabEnabled`: `Shared with match_restore: turning it off disables match_restore as well as these commands.`

`match_restore_util.ql-plugin.json`
- `label`: `⚠️ match_restore helper - do not enable`
- `description`: `Helper module for match_restore.py, downloaded with it. It is not a plugin: do not add it to qlx_plugins.`

`stats_hub_pause.ql-plugin.json` and `telemetry_unified_sched.ql-plugin.json`
- `label`: `⚠️ telemetry helper - do not enable`
- `description`: `Helper module for stream_telemetry_unified.py, downloaded with it. It is not a plugin: do not add it to qlx_plugins.`

`referee_call.ql-plugin.json`
- `description`: `Adds the !call chat command, which any player or spectator can use to ask for a referee. It only answers the caller; the call reaches the referees as a chat line that stream_telemetry_unified forwards to ql-stats-hub, so that plugin must be enabled with Session Events (qlx_statsHubFeedSession) on. One call per player per 60 seconds.`

`stream_telemetry_unified.ql-plugin.json`
- `description`: `Sends live match data from this instance to ql-stats-hub through the host's telemetry relay: player positions and stats, item pickups, and match events such as chat, votes, pauses, kills and !call referee requests. Turn the relay on for the host, then enable this instance on its Telemetry tab (telemetry-relay addon), which reserves its server ID and turns this plugin on. Each feed has its own switch.`
- cvars:
  - `qlx_statsHubUnifiedEnabled`: `Master switch for everything this plugin sends. The instance's Telemetry tab turns it on.`
  - `qlx_statsHubFeedPositions`: `Sends player positions, view angles, weapons and accuracy for the stream overlay. Needs a Server ID. Falls back to the old qlx_streamTelemetryEnabled cvar when unset.`
  - `qlx_statsHubFeedItems`: `Sends item pickup and drop events. Falls back to the old qlx_pickupTelemetryEnabled cvar when unset.`
  - `qlx_pickupTelemetryDebug`: `Writes extra pickup details to the server log, for troubleshooting.`
  - `qlx_statsHubFeedSession`: `Sends match events: chat, connects and disconnects, votes, spawns, team switches, kills, rounds, pauses, match start and end, and !call referee requests. Falls back to the old qlx_sessionEventsEnabled cvar when unset.`
  - `qlx_statsHubIdleInterval`: `Seconds between sends while no player is in play.`
  - `qlx_statsHubMatchId`: `Fixed match ID to tag telemetry with. Empty uses server-<Server ID>.`
  - `qlx_statsHubServerId`: `This instance's ID in ql-stats-hub. The instance's Telemetry tab reserves one and writes it here. With 0 the position feed is off and the host relay has no route for this instance.`
  - `qlx_statsHubTournamentId`: `Tournament ID added to position and session data. 0 leaves it out.`
  - `qlx_statsHubInterval`, `qlx_statsHubAccuracyInterval`: unchanged.

`tournament_access.ql-plugin.json`
- `description`: `Closes a tournament server to everyone not on the tournament roster. The tournament hub writes the roster (players and casters) into the server's Redis; when the hub marks it enforced, players not on it are kicked as they load, casters are kept in spectator, and on a lobby server everyone stays in spectator. The server owner and players at the bypass permission level are never checked.`
- cvars:
  - `qlx_tournamentAccessEnabled`: `Turns the roster check on. It also needs a Tournament ID, and the hub must mark the roster as enforced.`
  - `qlx_tournamentId`: `Hub tournament whose roster this server uses. 0 turns the check off.`
  - `qlx_tournamentAccessBypassPerm`: `Players with at least this minqlx permission level skip the roster check.`
  - `qlx_devAuthOpen`: `Turns the roster check off entirely, for testing. Leave it off on a real tournament.`

- [ ] **Step 2: Fix the lab's in-game usage string**

`match_restore_lab.py:69`: `usage="touch <eid> [cid] | touchat <eid> <sec> [cid] | respawn <eid> <sec> | stat <eid>",`

- [ ] **Step 3: Rewrite the addon manifests' operator text**

- `addons/demo-management/qlsm-addon.json` `description`: `Adds a Demos screen for each instance: lists the demo files the server recorded, newest first, with all files of one match grouped in one row labelled with map, mode, players and length, and downloads them. Filters by date, map, mode and pack state. Install qlmatch-packer as well to see and rebuild .qlmatch packs. Needs QLSM with ui_api 3 or newer.`
- `addons/demo-stream/qlsm-addon.json`: `name` -> `Live Demo Stream (experimental)`; `description`: `Experimental, not yet verified end to end. Lets a spectator watch a player's view live: points an instance's sv_demoStream cvars at the central demo-stream relay and registers the instance with ql-stats-hub. Set the relay address and the stats-hub in Settings, then enable each instance from its Live Demo Stream menu entry, which restarts it. Needs a game server build that supports the sv_demoStream cvars.`
- `addons/qlmatch-packer/qlsm-addon.json` `description`: `Installs the qlmatch packer and Node.js 22 on every game host during host setup and Update Plugins, and shows its .qlmatch packs and replay files on the Demos screen. Nothing runs the packer after a match: a first pack is built by running pack.mjs on the host by hand, and the Demos screen can rebuild an existing pack or its replay file. The output name template and rclone upload targets are the cvars qlx_qlmatchNameTemplate and qlx_qlmatchRcloneTargets, set by hand in the instance's server.cfg. Needs the demo-management addon.`
- `addons/runtime-source/qlsm-addon.json` `description`: `Builds a host's minqlxtended from a repository you choose instead of the commit QLSM pins, for example the alexeytihomirov/minqlxtended fork that native demo capture needs. Enable it for a host, enter the repository and a commit, then run Re-run Host Setup. Needs a QLSM whose host setup supports a custom minqlxtended repository on every provider (host.setup hook).`
- `addons/telemetry-relay/qlsm-addon.json`:
  - `description` (line 5): `Sends live telemetry from game instances (player positions, item pickups, match events) to ql-stats-hub through a relay on each host. Set the stats-hub URL and ingest token in Settings, turn the relay on per host (host menu, Telemetry Relay), then enable each instance on its Telemetry tab. The instances need the stream_telemetry_unified plugin.`
  - `instance_telemetry.description` (line 42): `Reserves this instance's server ID in ql-stats-hub, turns on the stream_telemetry_unified plugin and points it at the host relay, then restarts the instance. Turn the relay on for this instance's host first.`
  - field `server_id` `description` (line 46): `Assigned automatically the first time you save this form, then kept; a number typed here is ignored. 0 means telemetry was never enabled for this instance.` (QLSM's manifest schema `ui/addons/manifest.py:19` and `AddonFormPanel.jsx` have no read-only field, so the field stays.)

- [ ] **Step 4: Fix the qlmatch-packer docs and stale comments**

- `addons/qlmatch-packer/assets/README.md:3-7` becomes:
  `Builds one .qlmatch package (zip, STORE) per finished match from the per-player POV .dm_91 files and index/*.snaps.json that the native demo capture of the minqlxtended fork (alexeytihomirov/minqlxtended, built on a host with the runtime-source addon) leaves in an instance's demo directory, then optionally delivers it to any number of rclone targets.` (keep the backticks around file names as in the original).
- `addons/qlmatch-packer/assets/README.md:19-31` becomes two bullets:
  - `No automatic trigger: nothing launches the packer when a match ends (the plugin that did was retired). A first pack is built by running pack.mjs on the host by hand (see CLI below). The Demos screen's rebuild actions (rebuild_ops.py) run the same scripts over SSH, but only for a match that already has a .qlmatch. Output goes to <demo_dir>/<match_id>.packer.log; if the packer (or node) is missing on the host, no .qlmatch is built and only the raw .dm_91 files remain.`
  - `Configured per instance by two cvars set by hand in the instance's server.cfg (QLSM has no editor for them); a rebuild reads them from there:` followed by the existing two cvar sub-bullets (`README.md:29-31`) unchanged.
- `addons/qlmatch-packer/assets/pack.mjs:11-14` comment becomes: `// packer. Nothing launches it automatically any more (demo_native_autorecord.py` / `// was retired): it runs by hand on the host or from the qlmatch-packer addon's` / `// rebuild actions over SSH, never on the QLDS game thread or inside the QLDS` / `// process.` (each ` / ` is a line break; keep line 10 as is).
- `addons/qlmatch-packer/playbooks/sync_qlmatch_packer.yml:3-6` becomes (each ` / ` is a line break): `# Nothing launches it automatically (the demo_native_autorecord.py plugin` / `# that did was retired): it runs by hand or from this addon's rebuild` / `# actions over SSH, builds the .qlmatch package, renders the operator's` / `# filename template and delivers the result via rclone.`

- [ ] **Step 5: Rewrite the README plugin and addon sections**

- `README.md:9`: `| Addons | \`telemetry-relay\`, \`demo-management\`, \`demo-stream\`, \`qlmatch-packer\`, \`runtime-source\`, \`player-ranks\` |`
- `README.md:60-68` table rows:
  - `| \`tournament_access.py\` | Yes |`
  - `| \`chat_rcon.py\` | Yes |`
  - `| \`chat_rcon_acl.py\` | No - a copy of chat_rcon's permission rules for the tests; not needed on a server |`
  - `| \`lobby.py\` | Yes |`
  - `| \`referee_call.py\` | Yes - \`!call\` for players; the call travels as chat through \`stream_telemetry_unified\` (Session Events on) |`
  - `| \`match_restore_util.py\` | No - helper for \`match_restore.py\`, downloaded with it |`
  - `| \`match_restore_lab.py\` | Optional add-on to \`match_restore.py\` |`
  - `| \`match_restore.py\` + \`restore/\` | Yes - downloads as one entry |`
- `README.md:75-76` becomes: `All plugins here need the \`minqlxtended\` runtime (every entry in \`qlsm-repository.json\` says \`"runtime": "minqlxtended"\`). Native demo capture needs the [alexeytihomirov/minqlxtended](https://github.com/alexeytihomirov/minqlxtended) fork, which a host gets through the \`runtime-source\` addon.`
- `README.md:82-84` rows: `No - helper for \`stream_telemetry_unified.py\``, `No - helper for \`stream_telemetry_unified.py\``, `Yes - live positions, item pickups and match events to the host's telemetry relay`.
- `README.md:86-97` paragraphs: replace each em dash with ` - ` and change `use the qlmatch-packer addon's rebuild action from the Demos screen` to `run \`pack.mjs\` on the host by hand; the Demos screen can only rebuild a match that already has a \`.qlmatch\``. No other wording change.
- `README.md:106-109` rows:
  - `| \`telemetry-relay\` | Per-host relay that forwards \`stream_telemetry_unified\` data to ql-stats-hub; enable per host, then per instance on its Telemetry tab |`
  - `| \`demo-management\` | The **Demos** screen: lists and downloads what an instance recorded |`
  - `| \`demo-stream\` | Experimental: live POV demo stream through a central relay |`
  - `| \`qlmatch-packer\` | Installs the \`.qlmatch\` packer on hosts; shows and rebuilds packs on the Demos screen |`

- [ ] **Step 6: Reset the plugin entries and regenerate the manifest**

```bash
python - <<'EOF'
import json
path = 'qlsm-repository.json'
data = json.load(open(path, encoding='utf-8'))
for entry in data['plugins']:
    for key in ('label', 'description', 'depends_on'):
        entry.pop(key, None)
    entry['runtime'] = 'minqlxtended'
open(path, 'w', encoding='utf-8').write(json.dumps(data, indent=2) + '\n')
EOF
python generate_manifest.py
```
Expected last line: `Updated qlsm-repository.json: 11 plugins, 6 addons.`

- [ ] **Step 7: Verify the copy**

```bash
python - <<'EOF'
import glob, json
m = json.load(open('qlsm-repository.json', encoding='utf-8'))
files = glob.glob('*.ql-plugin.json') + glob.glob('addons/*/qlsm-addon.json') + ['qlsm-repository.json']
def text(f):
    return open(f, encoding='utf-8').read().replace('\\u2014', '\u2014').replace('\\u2013', '\u2013')
bad = [f for f in files if '\u2014' in text(f) or '\u2013' in text(f)]
plugins = {e['filename']: e for e in m['plugins']}
assert 'depends_on' not in plugins['chat_rcon.py'], plugins['chat_rcon.py']
assert {e['runtime'] for e in m['plugins']} == {'minqlxtended'}
assert plugins['lobby.py']['description'].startswith('For a lobby server')
assert not any(c['cvar'] == 'qlx_lobbyTrySteamOpen' for c in json.load(open('lobby.ql-plugin.json', encoding='utf-8'))['cvars'])
print('dashes in:', bad)
EOF
```
Expected: `dashes in: []` (only the JSON files are checked; README text outside the rows rewritten above keeps its old dashes). Then the full suite (addon manifests are loaded by the addon tests): `256 passed`.

- [ ] **Step 8: Commit**

```bash
python check_manifest_hashes.py
git add README.md *.ql-plugin.json match_restore_lab.py qlsm-repository.json addons/*/qlsm-addon.json addons/qlmatch-packer/assets/README.md addons/qlmatch-packer/assets/pack.mjs addons/qlmatch-packer/playbooks/sync_qlmatch_packer.yml packages/
git commit -m "docs: rewrite plugin and addon descriptions for operators"
```

---

### Task 2: match_restore export records real item pickup times

**Files:**
- Create: `tests/_minqlx_stub.py`
- Modify: `restore/items.py` (new function after `export_item_row`, line 73)
- Modify: `match_restore.py:272` (init), `match_restore.py:714-725` (`_reset_match_clock`), `match_restore.py:814-816` (`_reset_restore_runtime_cache`), `match_restore.py:1388-1391` (`on_item_event`), `match_restore.py:2384-2394` (`_export_item_row`)
- Test: `tests/test_match_restore_item_pickups.py`

**Interfaces:**
- Consumes: `restore.items.export_item_row(alias, meta, now_ms, *, wall_now, bundled_pickup=None, map_key="") -> dict` (unchanged).
- Produces:
  - `tests/_minqlx_stub.py`: `minqlx_stub() -> types.ModuleType`; `import_plugin(name: str) -> types.ModuleType`; `bare_instance(cls: type, **attrs) -> object`. Used by Tasks C, D, E, F, G.
  - `restore.items.note_item_pickup(pickups: dict, table_id: int, match_ms: int) -> None`.
  - `match_restore` attribute `self._item_pickups: dict[int, dict]` (spawn-table entity id -> `{"pickup_ms": int}`).

Bug (verified): `match_restore.py:2391` passes `bundled_pickup=None`, so `export_item_row` returns `{"k": alias, "s": 1}` for every item and `_export_items_checkpoint` (`:2375`) drops all of them. Clock: `now_ms` is `_export_match_time_ms()` (match clock, `:3191`), so the pickup must be stored on the same clock, not `level.time`.

- [ ] **Step 1: Write `tests/_minqlx_stub.py`**

Module docstring: one stand-in for `minqlxtended` so plugin modules import without a server. Contents fixed by these rules:
- `REPO_ROOT = Path(__file__).resolve().parent.parent`.
- `minqlx_stub()` returns a fresh `types.ModuleType("minqlxtended")` with: `Plugin = object`; `Priority = SimpleNamespace(HIGHEST=0, HIGH=1, NORMAL=2, LOW=3, LOWEST=4)`; `Return = SimpleNamespace(NONE=0, STOP=1, STOP_EVENT=2, STOP_ALL=3, USAGE=4)`; `thread` and `next_frame` = identity decorators; `delay(seconds)` returns an identity decorator; `EngineStateError` = a `RuntimeError` subclass; `NonexistentPlayerError` = an `Exception` subclass; `console_print` and `console_command` = functions that do nothing; `owner = lambda: "0"`; `EVENT_DISPATCHERS = {}`.
- `import_plugin(name)`: put `str(REPO_ROOT)` at `sys.path[0]` if absent; remember `sys.modules.get("minqlxtended")`; install `minqlx_stub()` there; `sys.modules.pop(name, None)`; `importlib.import_module(name)`; in `finally` restore the previous `minqlxtended` entry (or remove it if there was none); return the module. The pop is deliberate: `tests/test_telemetry_forwarded_command.py` imports `stream_telemetry_unified` under a MagicMock stub whose `@minqlx.thread` turns methods into mocks.
- `bare_instance(cls, **attrs)`: `obj = object.__new__(cls)`, `setattr` each attr, return obj (no `__init__`, so no cvars or hooks).

- [ ] **Step 2: Write the failing tests**

`tests/test_match_restore_item_pickups.py`, `pytestmark = pytest.mark.standalone`, imports `from restore.items import export_item_row, note_item_pickup` and `from _minqlx_stub import import_plugin, bare_instance` (put `REPO_ROOT` on `sys.path` first, as `tests/test_restore_codec_respawn.py` does).

```python
MEGA = {"classname": "item_health_mega", "entity_id": 7}

def test_taken_item_exports_its_remaining_respawn_time():
    row = export_item_row("mega", MEGA, 20_000, wall_now=0.0, bundled_pickup={"pickup_ms": 10_000})
    assert row == {"k": "mega", "s": 2, "in": 25.0, "at_ms": 45_000}

def test_item_already_respawned_exports_as_available():
    assert export_item_row("mega", MEGA, 50_000, wall_now=0.0, bundled_pickup={"pickup_ms": 10_000}) == {"k": "mega", "s": 1}

def test_note_item_pickup_keeps_the_latest_pickup_per_slot():
    pickups = {}
    note_item_pickup(pickups, 7, 10_000)
    note_item_pickup(pickups, 7, 30_000)
    note_item_pickup(pickups, 9, 12_000)
    assert pickups == {7: {"pickup_ms": 30_000}, 9: {"pickup_ms": 12_000}}

def test_pickup_at_match_time_zero_is_forgotten():
    pickups = {7: {"pickup_ms": 30_000}}
    note_item_pickup(pickups, 7, 0)
    assert pickups == {}
```

Plugin wiring tests (module `mr = import_plugin("match_restore")`, class `mr.match_restore`):

```python
def _plugin(**attrs):
    base = dict(
        _item_pickups={}, _itemlab_engine_runtime_ids=set(), _runtime_entity_by_alias={},
        _restore_apply_active=False, _restore_session_active=False,
        _enabled=lambda: True, _track_slot_runtime_id=lambda table_id, eid: None,
        _spawn_meta_for_entity=lambda eid, cn, x, y, z: ("mega", dict(MEGA)),
        _export_match_time_ms=lambda: 10_000, _map_key=lambda: "bloodrun",
    )
    base.update(attrs)
    return bare_instance(mr.match_restore, **base)

def test_on_item_event_records_the_match_clock_of_a_pickup():
    p = _plugin()
    p.on_item_event("pickup", 312, object(), "item_health_mega")
    assert p._item_pickups == {7: {"pickup_ms": 10_000}}

def test_on_item_event_ignores_pickups_during_a_restore_session():
    p = _plugin(_restore_session_active=True)
    p.on_item_event("pickup", 312, object(), "item_health_mega")
    assert p._item_pickups == {}

def test_export_item_row_uses_the_tracked_pickup():
    p = _plugin(_item_pickups={7: {"pickup_ms": 10_000}})
    assert p._export_item_row("mega", dict(MEGA), 20_000) == {"k": "mega", "s": 2, "in": 25.0, "at_ms": 45_000}

def test_reset_restore_runtime_cache_forgets_pickups():
    p = _plugin(_item_pickups={7: {"pickup_ms": 10_000}}, _slot_runtime_ids={})
    p._reset_restore_runtime_cache()
    assert p._item_pickups == {}
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `QLSM_REPO=C:/Users/hellp/orca/workspaces/qlsm/QLSM python -m pytest tests/test_match_restore_item_pickups.py -q -p no:cacheprovider`
Expected: collection error `ImportError: cannot import name 'note_item_pickup'`.

- [ ] **Step 4: Implement**

- `restore/items.py`: `def note_item_pickup(pickups: dict, table_id: int, match_ms: int) -> None` - store `{"pickup_ms": int(match_ms)}` under `int(table_id)`; when `match_ms <= 0` (warmup, clock not running) remove the key instead. Docstring: the match clock of the last pickup per spawn slot, the `bundled_pickup` shape `export_item_row` takes.
- `match_restore.py:272`: next to `self._last_item_touch = {}` add `self._item_pickups = {}` with a one-line comment (spawn-table entity id -> `{"pickup_ms"}` on the match clock, for export).
- `on_item_event` (`:1388-1391`): after `self._track_slot_runtime_id(table_id, runtime_eid)`, when `match_restore_items is not None and not self._restore_apply_active and not self._restore_session_active`, call `match_restore_items.note_item_pickup(self._item_pickups, table_id, self._export_match_time_ms())`. (Restore applies touch items through `touch_map_item`, which fires this same hook with a clock that is being rewritten.)
- `_reset_restore_runtime_cache` (`:814-816`): add `self._item_pickups.clear()`. This covers map change (`:307`), match start (`:701`) and restore session start (`:864`).
- `_reset_match_clock` (`:714-725`): add `self._item_pickups.clear()` (game end and back to warmup).
- `_export_item_row` (`:2384-2394`): look up `bundled = self._item_pickups.get(int(meta.get("entity_id")))` (on `TypeError`/`ValueError` use `None`) and pass `bundled_pickup=bundled`. Signature unchanged.

- [ ] **Step 5: Run the tests to verify they pass**

Run the same command. Expected: `8 passed`. Then the full suite: `264 passed`.

- [ ] **Step 6: Commit**

```bash
python generate_manifest.py
python check_manifest_hashes.py
git add tests/_minqlx_stub.py tests/test_match_restore_item_pickups.py restore/items.py match_restore.py qlsm-repository.json
git commit -m "match_restore: export the real pickup time of taken items"
```

---

### Task 3: match_restore applies checkpoint velocities once

**Files:**
- Modify: `match_restore.py:3875-3889` (`_flush_restore_velocities`), `match_restore.py:818-826` (`_abort_restore_session`)
- Test: `tests/test_match_restore_velocities.py`

**Interfaces:**
- Consumes: `tests/_minqlx_stub.py` (`import_plugin`, `bare_instance`) from Task 2.
- Produces: nothing new.

Bug (verified): `_flush_restore_velocities` copies `_restore_pending_velocities` and never clears it; `_finish_unpause_clock_thaw` (`:802`) calls it on every unpause thaw. It is cleared only on map change (`:293`) and at the next restore session start (`:866`), not on abort.

- [ ] **Step 1: Write the failing tests**

`tests/test_match_restore_velocities.py`, standalone, `mr = import_plugin("match_restore")`.

```python
def _plugin(pending):
    writes = []
    p = bare_instance(
        mr.match_restore,
        _restore_pending_velocities=pending,
        player=lambda cid: SimpleNamespace(id=cid),
        _write_player_velocity=lambda target, vx, vy, vz: writes.append((target.id, vx, vy, vz)),
        _queue_player_velocity=lambda cid, vx, vy, vz, frames=5: None,
        logger=logging.getLogger("test"),
    )
    return p, writes

def test_flush_applies_pending_velocities_once():
    p, writes = _plugin({3: (100.0, 0.0, 270.0)})
    p._flush_restore_velocities()
    p._flush_restore_velocities()
    assert writes == [(3, 100.0, 0.0, 270.0)]
    assert p._restore_pending_velocities == {}

def test_abort_forgets_pending_velocities():
    p, _ = _plugin({3: (100.0, 0.0, 270.0)})
    p._restore_hold_until_unpause = True
    p._awaiting_unfreeze_after_unpause = True
    p._unfreeze_thaw_token = 0
    p._unfreeze_thaw_at_wall = 1.0
    p._end_restore_session = lambda: None
    p._abort_restore_session("test")
    assert p._restore_pending_velocities == {}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `QLSM_REPO=C:/Users/hellp/orca/workspaces/qlsm/QLSM python -m pytest tests/test_match_restore_velocities.py -q -p no:cacheprovider`
Expected: 2 failed (`writes` has two entries; dict not empty).

- [ ] **Step 3: Implement**

- `_flush_restore_velocities`: after taking `pending = dict(...)`, call `self._restore_pending_velocities.clear()` before applying (the copy is what gets applied; the dict is empty afterwards whether or not a player write fails).
- `_abort_restore_session`: add `self._restore_pending_velocities.clear()` next to the other resets.

- [ ] **Step 4: Run the tests to verify they pass**

Same command: `2 passed`. Full suite: `266 passed`.

- [ ] **Step 5: Commit**

```bash
python generate_manifest.py
python check_manifest_hashes.py
git add tests/test_match_restore_velocities.py match_restore.py qlsm-repository.json
git commit -m "match_restore: apply checkpoint velocities once"
```

---

### Task 4: telemetry session feed keeps the batch until acknowledged

**Files:**
- Modify: `telemetry_unified_sched.py` (append after line 180)
- Modify: `stream_telemetry_unified.py:137-149` (sched imports), `:303-304` (init), `:1833-1847` (`_post_session_events_now`), `:1849-1855` (`_post_session_lifecycle_now`), `:2073-2109` (`_post_session_batch`), `:2130-2170` (`_drive_session_events`)
- Test: `tests/test_telemetry_session_queue.py`

**Interfaces:**
- Consumes: `tests/_minqlx_stub.py` from Task 2; `FeedState` (`telemetry_unified_sched.py:90-180`, unchanged).
- Produces:
  - `telemetry_unified_sched.ack_batch(queue: list, batch: list) -> int`
  - `stream_telemetry_unified` attribute `self._session_acks: list[list[dict]]` and method `_apply_session_acks(self) -> None`
  - changed signature `_post_session_batch(self, url, token, payload, generation, batch)`

Bug (verified): `_drive_session_events` slices the batch and `del`s it from `_session_queue` before the POST (`:2165-2166`); `_post_session_lifecycle_now` pops its row out of the queue (`:1853-1854`); `_post_session_batch` (`:2096-2109`) never puts anything back. One failed POST loses `!call`, pauses, `match_end`.

Design decision (thread model): only the game thread mutates `_session_queue` (appends in `_enqueue_session`/`_enqueue_lifecycle`, cap drop `pop(0)` at `_SESSION_MAX_QUEUE = 512`, and now ack removal). The `@minqlx.thread` worker only appends the delivered batch to `self._session_acks` (a single `list.append`), and does that **before** `state.complete(...)`, so by the time the game thread sees `post_in_flight == False` the ack is already visible and is applied before the next batch is taken. Removal is by identity, so rows appended or cap-dropped while the batch was in flight are handled. A failed POST appends nothing: the rows stay at the head of the queue and go with the next batch. A late success after a stuck-reset is still acked (rows were delivered; at-least-once). The items feed is not changed.

- [ ] **Step 1: Write the failing tests**

`tests/test_telemetry_session_queue.py`, standalone.

```python
from telemetry_unified_sched import FeedState, ack_batch

def test_ack_removes_only_the_acknowledged_rows():
    a, b, c, d = ({"kind": k} for k in "abcd")
    queue = [a, b, c]
    batch = queue[:2]
    queue.append(d)
    assert ack_batch(queue, batch) == 2
    assert queue[0] is c and queue[1] is d and len(queue) == 2

def test_ack_after_the_cap_dropped_the_oldest_row():
    a, b, c, d = ({"kind": k} for k in "abcd")
    queue = [a, b, c]
    batch = queue[:2]
    queue.pop(0)
    queue.append(d)
    assert ack_batch(queue, batch) == 1
    assert queue[0] is c and queue[1] is d and len(queue) == 2

def test_equal_but_distinct_rows_are_kept():
    first, second = {"kind": "say", "text": "gg"}, {"kind": "say", "text": "gg"}
    queue = [first, second]
    assert ack_batch(queue, [first]) == 1
    assert queue[0] is second and len(queue) == 1
```

Plugin tests (`st = import_plugin("stream_telemetry_unified")`, class `st.stream_telemetry_unified`):

```python
URL = "http://127.0.0.1:8190/api/ingest/session-events"

class _Conn:
    status = 200
    fail = False
    def __init__(self, host, port, timeout=None): pass
    def request(self, *a, **k):
        if self.fail:
            raise OSError("connection refused")
    def getresponse(self):
        return SimpleNamespace(status=self.status, read=lambda: b"{}")
    def close(self): pass

def _sender():
    return bare_instance(
        st.stream_telemetry_unified,
        _session_state=FeedState("session", 12.0, 10), _session_acks=[],
        _record_post_result=lambda state, ok: None, logger=logging.getLogger("test"),
    )

def test_accepted_post_queues_an_ack(monkeypatch):
    monkeypatch.setattr("http.client.HTTPConnection", _Conn)
    p = _sender()
    batch = [{"kind": "say"}]
    gen = p._session_state.begin_post(0.0)
    p._post_session_batch(URL, "", {"events": batch}, gen, batch)
    assert p._session_acks == [batch] and p._session_state.posts_ok == 1

def test_failed_post_keeps_the_batch_queued(monkeypatch):
    monkeypatch.setattr("http.client.HTTPConnection", type("Down", (_Conn,), {"fail": True}))
    p = _sender()
    batch = [{"kind": "match_end"}]
    gen = p._session_state.begin_post(0.0)
    p._post_session_batch(URL, "", {"events": batch}, gen, batch)
    assert p._session_acks == [] and p._session_state.posts_fail == 1

def test_rejected_post_keeps_the_batch_queued(monkeypatch):
    monkeypatch.setattr("http.client.HTTPConnection", type("Reject", (_Conn,), {"status": 503}))
    p = _sender()
    batch = [{"kind": "say"}]
    gen = p._session_state.begin_post(0.0)
    p._post_session_batch(URL, "", {"events": batch}, gen, batch)
    assert p._session_acks == []

def test_lifecycle_row_stays_queued_until_acked():
    posted = []
    p = bare_instance(
        st.stream_telemetry_unified,
        _session_queue=[], _session_acks=[], _session_state=FeedState("session", 12.0, 10),
        _session_enabled=lambda: True, get_cvar=lambda name, *a: "",
        _session_events_url=lambda: URL, _build_session_payload=lambda batch: {"events": batch},
        _post_session_batch=lambda url, token, payload, gen, batch: posted.append(batch),
    )
    p._post_session_lifecycle_now("match_end", game_time_ms=600_000, meta={})
    assert len(p._session_queue) == 1 and posted[0][0] is p._session_queue[0]
    p._session_acks.append(posted[0])
    p._apply_session_acks()
    assert p._session_queue == [] and p._session_acks == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `QLSM_REPO=C:/Users/hellp/orca/workspaces/qlsm/QLSM python -m pytest tests/test_telemetry_session_queue.py -q -p no:cacheprovider`
Expected: collection error `ImportError: cannot import name 'ack_batch'`.

- [ ] **Step 3: Implement `ack_batch(queue: list, batch: list) -> int` in `telemetry_unified_sched.py`**

Remove from `queue`, in place (`queue[:] = ...`), every row that is (by `id`) in `batch`; return how many were removed. Docstring: rows are matched by identity because equal-looking events (two "gg" lines) are distinct, and the queue may have been appended to or cap-trimmed while the batch was in flight.

- [ ] **Step 4: Implement the plugin side**

- Imports (`:137-149`, both branches): add `ack_batch`.
- `__init__` after `:304`: `self._session_acks = []` with a comment: batches the relay accepted; appended by the POST worker, applied to `_session_queue` on the game thread only.
- `_apply_session_acks(self) -> None`: while `self._session_acks` is non-empty, `ack_batch(self._session_queue, self._session_acks.pop(0))`.
- `_drive_session_events` (`:2130`): call `self._apply_session_acks()` right after the `sync_enabled`/`_reset_circuit` lines, before `if not enabled: return`. Replace `:2165-2166` with `batch = self._session_queue[: self._SESSION_BATCH_SIZE]` (no `del`) and pass `batch` as the new last argument of `_post_session_batch`.
- `_post_session_batch(self, url, token, payload, generation, batch)`: when `ok`, `self._session_acks.append(batch)` before `state.complete(generation, ok)`. Failure paths unchanged (no ack).
- `_post_session_events_now` (`:1833-1847`): when `state.post_in_flight`, just `return` (drop the re-insert loop `:1838-1840`; the rows are already in the queue). Pass `batch` to `_post_session_batch`.
- `_post_session_lifecycle_now` (`:1849-1855`): delete the two lines that pop the row back off the queue (`:1853-1854`); the row stays queued until acked.

- [ ] **Step 5: Run the tests to verify they pass**

Same command: `7 passed`. Also `tests/test_telemetry_forwarded_command.py` still passes. Full suite: `273 passed`.

- [ ] **Step 6: Commit**

```bash
python generate_manifest.py
python check_manifest_hashes.py
git add tests/test_telemetry_session_queue.py telemetry_unified_sched.py stream_telemetry_unified.py qlsm-repository.json
git commit -m "stream_telemetry_unified: keep session events until the relay acknowledges them"
```

---

### Task 5: telemetry does not archive `!rcon` chat lines

**Files:**
- Modify: `stream_telemetry_unified.py:152-162` (next to `forwarded_command`), `:613-619` (`on_client_command_chat`)
- Test: `tests/test_telemetry_forwarded_command.py` (extend)

**Interfaces:**
- Consumes: `tests/_minqlx_stub.py` (`import_plugin`, `bare_instance`) from Task 2.
- Produces: `stream_telemetry_unified.should_forward_say(text: str | None) -> bool` (module level).

Ruling: a `say` or `say_team` line whose first token, after optional surrounding whitespace, an optional leading `"` and one optional leading `/`, is `!rcon` (case-insensitive) is not queued; everything else unchanged. `say_team` is included because minqlx runs chat commands from team chat too, so the same secret leaks there (Plan notes 9). `tell` lines are unchanged (no command runs from them). `forwarded_command` is not reused: it answers a different question (which console commands to forward), only the head-token idea is shared.

- [ ] **Step 1: Write the failing tests**

In `tests/test_telemetry_forwarded_command.py` import `should_forward_say` in the same `try` block as `forwarded_command`, and add:

```python
def test_rcon_chat_lines_are_not_forwarded():
    for text in ("!rcon g_password secret", "!RCON map bloodrun", '"!rcon g_password secret"', "/!rcon quit", "  !rcon", "!rcon"):
        assert should_forward_say(text) is False, text

def test_other_chat_lines_are_forwarded():
    for text in ("gg", "!call ref please", "!rconx", "about !rcon", "", None):
        assert should_forward_say(text) is True, text

def test_team_chat_rcon_is_not_queued():
    from _minqlx_stub import import_plugin, bare_instance
    st = import_plugin("stream_telemetry_unified")
    queued = []
    p = bare_instance(st.stream_telemetry_unified, _session_enabled=lambda: True,
                      _enqueue_session=lambda kind, player, text=None, meta=None: queued.append((kind, text)))
    p.on_client_command_chat(object(), "say_team !rcon g_password secret")
    p.on_client_command_chat(object(), 'say "!rcon g_password secret"')
    p.on_client_command_chat(object(), "say gg")
    assert queued == [("say", "gg")]
```

- [ ] **Step 2: Run to verify failure**

Run: `QLSM_REPO=C:/Users/hellp/orca/workspaces/qlsm/QLSM python -m pytest tests/test_telemetry_forwarded_command.py -q -p no:cacheprovider`
Expected: collection error `ImportError: cannot import name 'should_forward_say'`.

- [ ] **Step 3: Implement**

- `should_forward_say(text: str | None) -> bool` right after `forwarded_command`, with a constant `_UNFORWARDED_CHAT_HEAD = "!rcon"` and a comment: chat_rcon consumes `!rcon` lines, which can carry passwords; they must not reach the hub's chat archive.
- `on_client_command_chat`: for the `say ` and `say_team ` branches compute the text once and call `_enqueue_session` only when `should_forward_say(text)`.

- [ ] **Step 4: Run to verify pass**

Same command: `5 passed`. Full suite: `276 passed`.

- [ ] **Step 5: Commit**

```bash
python generate_manifest.py
python check_manifest_hashes.py
git add tests/test_telemetry_forwarded_command.py stream_telemetry_unified.py qlsm-repository.json
git commit -m "stream_telemetry_unified: never forward !rcon chat lines to the hub"
```

---

### Task 6: chat_rcon rejects multi-command lines

**Files:**
- Modify: `chat_rcon.py:39-42`, `:45-59` (`parse_csv`), `:62-75` (`normalize_command_line`), `:88-114` (`evaluate_acl`)
- Modify: `chat_rcon_acl.py:34-38`, `:89-113` (`evaluate_acl`)
- Test: `tests/test_chat_rcon_acl.py` (new)

**Interfaces:**
- Consumes: `tests/_minqlx_stub.py` (`import_plugin`) from Task 2.
- Produces: in both modules `RESULT_MULTI_COMMAND = "multi"`; `evaluate_acl` returns `(RESULT_MULTI_COMMAND, "denied: one command per line", "")` for such lines.

Verified: `chat_rcon.py` inlines its own copy of the ACL (`:5-7`) and never imports `chat_rcon_acl`; the copies differ in `lower()` vs `casefold()` and in the usage text (`[args...]` vs `[args…]`). Alignment: `chat_rcon.py` switches to `casefold()` (the variables are already named `*_cf`), `chat_rcon_acl.py` switches its usage text to ASCII `[args...]`. `chat_rcon_acl.evaluate_acl` stays keyword-only; tests call both with keywords.

- [ ] **Step 1: Write the failing tests**

`tests/test_chat_rcon_acl.py`, standalone:

```python
@pytest.fixture(params=["chat_rcon_acl", "chat_rcon"])
def acl(request):
    return import_plugin(request.param)

DENIED = ("multi", "denied: one command per line", "")

def test_semicolon_is_rejected_for_admins(acl):
    assert acl.evaluate_acl(enabled=True, perm_level=5, cmd_line="pause; exec x.cfg") == DENIED

def test_semicolon_is_rejected_for_referees(acl):
    assert acl.evaluate_acl(enabled=True, perm_level=3, cmd_line="pause;exec x.cfg") == DENIED

def test_semicolon_is_rejected_from_the_console(acl):
    assert acl.evaluate_acl(enabled=True, perm_level=None, cmd_line="map campgrounds; quit", player_is_none=True) == DENIED

def test_line_breaks_are_rejected(acl):
    for line in ("pause\nquit", "pause\rquit"):
        assert acl.evaluate_acl(enabled=True, perm_level=5, cmd_line=line) == DENIED

def test_single_commands_still_run(acl):
    assert acl.evaluate_acl(enabled=True, perm_level=3, cmd_line="pause") == ("ok", "ok", "pause")
    assert acl.evaluate_acl(enabled=True, perm_level=5, cmd_line="map bloodrun duel") == ("ok", "ok", "map bloodrun duel")

def test_disabled_wins_over_the_separator_check(acl):
    assert acl.evaluate_acl(enabled=False, perm_level=5, cmd_line="pause; quit") == ("disabled", "chat-rcon disabled", "")

def test_both_copies_fold_case_and_show_the_same_usage(acl):
    assert acl.parse_csv("Pause,MAP", ()) == {"pause", "map"}
    assert acl.normalize_command_line("/MAP Bloodrun") == ("MAP Bloodrun", "map", "bloodrun")
    assert acl.evaluate_acl(enabled=True, perm_level=5, cmd_line="") == ("usage", "usage: !rcon <command> [args...]", "")
    assert acl.RESULT_MULTI_COMMAND == "multi"
```

- [ ] **Step 2: Run to verify failure**

Run: `QLSM_REPO=C:/Users/hellp/orca/workspaces/qlsm/QLSM python -m pytest tests/test_chat_rcon_acl.py -q -p no:cacheprovider`
Expected: separator tests fail with `('ok', 'ok', ...)` and the `chat_rcon_acl` usage test fails on `[args…]`.

- [ ] **Step 3: Implement in both modules**

- Add `RESULT_MULTI_COMMAND = "multi"` after `RESULT_USAGE`.
- In `evaluate_acl`, right after the `if not enabled` return and before `normalize_command_line`: if any of `";"`, `"\n"`, `"\r"` is in `str(cmd_line or "")`, return `(RESULT_MULTI_COMMAND, "denied: one command per line", "")`. Comment: idTech3 splits a console line on `;` and newlines, so anything after the first command would bypass both the referee allow-list and the admin deny-list.
- `chat_rcon.py`: every `.lower()` in `parse_csv`, `normalize_command_line` and `evaluate_acl` becomes `.casefold()`.
- `chat_rcon_acl.py`: usage text `"usage: !rcon <command> [args...]"`; docstring line `result ∈ {ok, deny, disabled, usage}` becomes `result is one of ok, deny, disabled, usage, multi.`
- `cmd_rcon` (`chat_rcon.py:225-256`) needs no change: the `result != RESULT_OK` branch replies `chat-rcon: denied: one command per line` and logs the raw line.

- [ ] **Step 4: Run to verify pass**

Same command: `14 passed`. Full suite: `290 passed`.

- [ ] **Step 5: Commit**

```bash
python generate_manifest.py
python check_manifest_hashes.py
git add tests/test_chat_rcon_acl.py chat_rcon.py chat_rcon_acl.py qlsm-repository.json
git commit -m "chat_rcon: reject lines with command separators"
```

---

### Task 7: tournament_access checks the roster before the specbot rule

**Files:**
- Modify: `tournament_access.py:21-22` (module-level functions after the constants), `:203-229` (`handle_player_loaded`), `:231-261` (`handle_team_switch_attempt`)
- Modify: `tournament_access.ql-plugin.json` (`description`, text from Task 1 plus one sentence)
- Test: `tests/test_tournament_access.py` (new)

**Interfaces:**
- Consumes: `tests/_minqlx_stub.py` (`import_plugin`) from Task 2; Task 1's `tournament_access.ql-plugin.json` description.
- Produces: `decide_loaded(role: str | None, access_active: bool, is_specbot: bool, is_lobby: bool) -> str` returning `"allow" | "spec" | "kick"`; `decide_team_switch(role: str | None, access_active: bool, is_specbot: bool, is_lobby: bool, new_team: str) -> str` returning `"allow" | "deny_roster" | "deny_specbot" | "deny_lobby" | "deny_caster"`.

Bug (verified): `handle_player_loaded` (`:209-211`) forces any `StreamSpec*` name to spectator and returns before `_access_active()`, so the name prefix alone gets into a closed server. In `handle_team_switch_attempt` (`:237-242`) the specbot branch also comes before the roster check (it only blocks, so it is not a bypass, but it is reordered to the same rule). Dev-open (`:204`) and bots/bypass (`:206`) stay first and unchanged.

- [ ] **Step 1: Write the failing tests**

`tests/test_tournament_access.py`, standalone, `ta = import_plugin("tournament_access")`:

```python
@pytest.mark.parametrize("role, active, specbot, lobby, expected", [
    (None, True, True, False, "kick"),       # unlisted StreamSpec on a closed server
    ("player", True, True, False, "spec"),
    ("caster", True, False, False, "spec"),
    ("player", True, False, True, "spec"),
    ("player", True, False, False, "allow"),
    (None, True, False, False, "kick"),
    (None, False, True, False, "spec"),      # roster not enforced: specbot still spectates
    (None, False, False, True, "allow"),     # roster not enforced: lobby does not force spec (as today)
    (None, False, False, False, "allow"),
])
def test_decide_loaded(role, active, specbot, lobby, expected):
    assert ta.decide_loaded(role, active, specbot, lobby) == expected

@pytest.mark.parametrize("role, active, specbot, lobby, team, expected", [
    (None, True, True, False, "red", "deny_roster"),
    ("player", True, True, False, "red", "deny_specbot"),
    ("player", True, True, False, "spectator", "allow"),
    (None, False, True, False, "blue", "deny_specbot"),
    (None, True, False, False, "spectator", "deny_roster"),
    ("player", True, False, True, "free", "deny_lobby"),
    ("caster", True, False, False, "red", "deny_caster"),
    ("player", True, False, False, "red", "allow"),
    (None, False, False, False, "red", "allow"),
])
def test_decide_team_switch(role, active, specbot, lobby, team, expected):
    assert ta.decide_team_switch(role, active, specbot, lobby, team) == expected
```

- [ ] **Step 2: Run to verify failure**

Run: `QLSM_REPO=C:/Users/hellp/orca/workspaces/qlsm/QLSM python -m pytest tests/test_tournament_access.py -q -p no:cacheprovider`
Expected: 18 failed, `AttributeError: module 'tournament_access' has no attribute 'decide_loaded'`.

- [ ] **Step 3: Implement**

- Both functions at module level after `PLAYING_TEAMS`. Order in `decide_loaded`: not `access_active` -> spec for a specbot, else allow (today's behaviour); `role is None` -> kick; specbot, caster or lobby -> spec; else allow. Order in `decide_team_switch`: `access_active and role is None` -> deny_roster; specbot -> deny_specbot if `new_team in PLAYING_TEAMS` else allow; not active -> allow; `new_team not in PLAYING_TEAMS` -> allow; lobby -> deny_lobby; caster -> deny_caster; else allow.
- `handle_player_loaded`: keep `:204-207`; then `access = self._access_active()`, `role = self._role(player, access) if access else None`, `specbot = self._is_specbot(player)`, `decision = decide_loaded(role, access is not None, specbot, self._is_lobby_server())`. `"kick"`: the existing log line (`:219-224`) and `_kick_not_whitelisted`; `"spec"`: `self._force_spec(player, "specbot" if specbot else "")`.
- `handle_team_switch_attempt`: keep `:232-235`; same inputs plus `new_team`; `"allow"` returns `None`; otherwise `player.tell(_TEAM_SWITCH_DENIED[decision])`, and for `"deny_specbot"` also `self._force_spec(player, "specbot_team_block")`; return `minqlx.Return.STOP_ALL`. `_TEAM_SWITCH_DENIED` is a module dict with the four existing messages (`:239`, `:249`, `:256`, `:260`); in the lobby message replace the em dash with ` - `: `^3Tournament:^7 lobby is spec-only - use ^6!go^7 to join a game server.`
- `tournament_access.ql-plugin.json` description: append ` A stream spectator account (name starting with StreamSpec, or the qlx_specbot_name_prefix cvar) must be on the roster or have the bypass level like anyone else; on the roster it is kept in spectator.`

- [ ] **Step 4: Run to verify pass**

Same command: `18 passed`. Full suite: `308 passed`.

- [ ] **Step 5: Commit**

```bash
python generate_manifest.py
python check_manifest_hashes.py
git add tests/test_tournament_access.py tournament_access.py tournament_access.ql-plugin.json qlsm-repository.json
git commit -m "tournament_access: check the roster before the specbot rule"
```

---

### Task 8: qlmatch-packer rebuild tasks report unexpected failures

**Files:**
- Modify: `addons/qlmatch-packer/rebuild_tasks.py:19-82`
- Modify: `addons/qlmatch-packer/qlsm-addon.json:3` (`"version": "1.1.2"`)
- Test: `tests/test_qlmatch_rebuild_tasks.py` (new)

**Interfaces:**
- Consumes: `ui.job_events.publish_job_event(source, status, message, **extra)` (QLSM), `rebuild_ops.RebuildError`.
- Produces: `rebuild_tasks._error_text(exc: Exception) -> str`.

Verified: the three task bodies catch only `RebuildError` (`:22`, `:36`, `:68`). `rebuild_ops` calls `run_remote_command` / `open_sftp` (paramiko, `OSError`) uncaught. The lock is not the problem: `ctx.task(lock_scope='instance')` (`QLSM/ui/addons/context.py:113-120`) releases it in `finally`; what is lost is the operator's toast, the task result, and for a batch every later file plus the summary event.

- [ ] **Step 1: Write the failing tests**

`tests/test_qlmatch_rebuild_tasks.py` (needs QLSM, not standalone):

```python
@pytest.fixture
def addon_id():
    return 'qlmatch-packer'

@pytest.fixture
def tasks_mod(app, monkeypatch):
    mod = importlib.import_module('qlsm_addon_qlmatch_packer.rebuild_tasks')
    events = []
    monkeypatch.setattr(mod, 'publish_job_event', lambda source, status, message, **extra: events.append((status, message)))
    mod.events = events
    return mod

def _ssh_lost(instance_id, filename):
    raise OSError('ssh lost')

def test_sidecar_rebuild_reports_an_ssh_failure(tasks_mod, monkeypatch):
    monkeypatch.setattr(tasks_mod, 'rebuild_sidecar_logic', _ssh_lost)
    assert tasks_mod.rebuild_sidecar_task_logic(1, 'a.qlmatch') == {'ok': False, 'error': 'OSError: ssh lost'}
    assert tasks_mod.events == [('error', 'Sidecar rebuild failed for "a.qlmatch": OSError: ssh lost')]

def test_full_rebuild_reports_an_ssh_failure(tasks_mod, monkeypatch):
    monkeypatch.setattr(tasks_mod, 'rebuild_full_logic', _ssh_lost)
    assert tasks_mod.rebuild_full_task_logic(1, 'a.qlmatch') == {'ok': False, 'error': 'OSError: ssh lost'}
    assert tasks_mod.events == [('error', 'Full rebuild failed for "a.qlmatch": OSError: ssh lost')]

def test_rebuild_error_text_is_unchanged(tasks_mod, monkeypatch):
    def refuse(instance_id, filename):
        raise tasks_mod.RebuildError('no raw demos')
    monkeypatch.setattr(tasks_mod, 'rebuild_full_logic', refuse)
    assert tasks_mod.rebuild_full_task_logic(1, 'a.qlmatch') == {'ok': False, 'error': 'no raw demos'}

def test_batch_continues_after_an_ssh_failure(tasks_mod, monkeypatch):
    def logic(instance_id, filename):
        if filename == 'a.qlmatch':
            raise OSError('ssh lost')
        return {'filename': filename}
    monkeypatch.setitem(tasks_mod._KIND_LOGIC, 'full', logic)
    result = tasks_mod.rebuild_batch_task_logic(1, 'full', ['a.qlmatch', 'b.qlmatch'])
    assert result['ok'] is False
    assert result['results']['a.qlmatch'] == {'ok': False, 'error': 'OSError: ssh lost'}
    assert result['results']['b.qlmatch'] == {'ok': True, 'filename': 'b.qlmatch'}
    assert tasks_mod.events[-1] == ('error', 'Batch full rebuild finished: 1/2 succeeded.')

def test_batch_where_every_file_fails_still_sends_the_summary(tasks_mod, monkeypatch):
    monkeypatch.setitem(tasks_mod._KIND_LOGIC, 'sidecar', _ssh_lost)
    result = tasks_mod.rebuild_batch_task_logic(1, 'sidecar', ['a.qlmatch', 'b.qlmatch'])
    assert result['ok'] is False
    assert tasks_mod.events[-1] == ('error', 'Batch sidecar rebuild finished: 0/2 succeeded.')
```

- [ ] **Step 2: Run to verify failure**

Run: `QLSM_REPO=C:/Users/hellp/orca/workspaces/qlsm/QLSM python -m pytest tests/test_qlmatch_rebuild_tasks.py -q -p no:cacheprovider`
Expected: the four OSError tests fail with `OSError: ssh lost`; `test_rebuild_error_text_is_unchanged` passes.

- [ ] **Step 3: Implement**

- `_error_text(exc)`: `str(exc)` for a `RebuildError`, else `f'{type(exc).__name__}: {exc}'`.
- In the three places change `except RebuildError as e:` to `except Exception as e:`; log a `RebuildError` with the existing `log.warning(...)`, anything else with `log.exception(...)` (same message text); use `_error_text(e)` in the event message and in the returned `'error'`. Everything else (event names, summary) unchanged.
- `qlsm-addon.json` version `1.1.1` -> `1.1.2`.

- [ ] **Step 4: Run to verify pass**

Same command: `5 passed`. Full suite: `313 passed`.

- [ ] **Step 5: Commit**

```bash
python generate_manifest.py
python check_manifest_hashes.py
git add tests/test_qlmatch_rebuild_tasks.py addons/qlmatch-packer/rebuild_tasks.py addons/qlmatch-packer/qlsm-addon.json qlsm-repository.json packages/qlmatch-packer.zip
git commit -m "qlmatch-packer: report SSH and unexpected failures from rebuild tasks"
```

---

### Task 9: telemetry-relay and demo-stream reset the instance status on a failed task

**Files:**
- Modify: `addons/telemetry-relay/instance_ops.py:21-22` (import), `:88-158`; `addons/telemetry-relay/backend.py:247-250`, `:283-288`; `addons/telemetry-relay/qlsm-addon.json:3` (`"version": "1.3.1"`)
- Modify: `addons/demo-stream/instance_ops.py:29-30` (import), `:62-145`; `addons/demo-stream/backend.py:166-169`, `:189-196`; `addons/demo-stream/qlsm-addon.json:3` (`"version": "1.1.2"`)
- Test: `tests/test_addon_telemetry_relay_enable.py`, `tests/test_addon_demo_stream_enable.py` (new; one addon per module because `addon_id` is a module fixture)

**Interfaces:**
- Consumes: QLSM `ui.models.InstanceStatus`, `ui.tasks.enqueue_task(task, *args, on_failure=None, **kwargs)` (kwargs reach the task), `ctx.task` wrapper passing `*args, **kwargs` through (`QLSM/ui/addons/context.py:114-116`).
- Produces (both addons): `enable_instance_telemetry_logic(instance_id, previous_status=None)` / `enable_instance_demo_stream_logic(instance_id, previous_status=None)`; `_finish(instance, ok, message, previous_status=None)`; `_status_after_failure(previous_status: str | None) -> InstanceStatus`; task functions `enable_instance_telemetry_task(instance_id, previous_status=None)` / `enable_instance_demo_stream_task(instance_id, previous_status=None)`.

Decision (core pattern): QLSM core passes the status the instance had before it went transitional as `previous_status=<InstanceStatus value>` (`QLSM/ui/routes/instance_routes.py:1330`, consumed by `apply_instance_config_logic`, `QLSM/ui/task_logic/ansible_instance_mgmt.py:604,627-630`). Both addons do the same: the endpoint captures `instance.status.value` before setting CONFIGURING and enqueues with `previous_status=...`; every `(False, msg)` return goes through `_finish`, which, when the instance is still CONFIGURING, sets it back to `InstanceStatus(previous_status)`, or to `InstanceStatus.ERROR` when `previous_status` is missing or invalid (same outcome as core's `instance_job_failure_handler`). Raising instead was rejected: it would turn a refused precondition ("enable the relay first") into an ERROR instance. The success path is unchanged (the queued `apply_instance_config` sets the final status).

- [ ] **Step 1: Write the failing tests**

Shared shape for both files (shown for telemetry-relay; demo-stream differs only where noted). Imports as in `tests/test_addon_demo_management.py` (`db`, `Host`, `HostStatus`, `InstanceStatus`, `QLInstance`, `make_user`, `auth_headers`) plus `importlib` and `requests`:

```python
@pytest.fixture
def addon_id():
    return 'telemetry-relay'          # demo-stream: 'demo-stream'

def _instance(app, status):
    with app.app_context():
        host = Host(name='germany', ip_address='10.0.0.1', provider='vultr', status=HostStatus.ACTIVE)
        db.session.add(host)
        db.session.flush()
        inst = QLInstance(name='duel srv', port=27960, hostname='duel', host_id=host.id, status=status)
        db.session.add(inst)
        db.session.commit()
        return inst.id

def _status(app, instance_id):
    with app.app_context():
        return db.session.get(QLInstance, instance_id).status

@pytest.mark.parametrize('previous, expected', [('running', InstanceStatus.RUNNING), ('stopped', InstanceStatus.STOPPED), (None, InstanceStatus.ERROR)])
def test_failed_enable_restores_the_previous_status(app, previous, expected):
    ops = importlib.import_module('qlsm_addon_telemetry_relay.instance_ops')
    iid = _instance(app, InstanceStatus.CONFIGURING)
    with app.app_context():
        ok, message = ops.enable_instance_telemetry_logic(iid, previous_status=previous)
    assert ok is False and message.startswith('Configure the stats-hub URL')
    assert _status(app, iid) == expected
```
demo-stream: `qlsm_addon_demo_stream.instance_ops.enable_instance_demo_stream_logic`, message starts with `Configure the demo-stream relay host/port`.

```python
def test_unreachable_stats_hub_restores_the_previous_status(app, monkeypatch):
    ops = importlib.import_module('qlsm_addon_telemetry_relay.instance_ops')
    monkeypatch.setattr(ops, 'is_stats_hub_configured_for_host', lambda host_id: True)
    monkeypatch.setattr(ops, 'is_relay_enabled', lambda host_id: True)
    monkeypatch.setattr(ops, 'get_instance_server_id', lambda instance_id: None)
    def down(*a, **k):
        raise requests.ConnectionError('hub down')
    monkeypatch.setattr(ops, 'reserve_server_id', down)
    iid = _instance(app, InstanceStatus.CONFIGURING)
    with app.app_context():
        assert ops.enable_instance_telemetry_logic(iid, previous_status='running') == (False, 'Could not reserve a server_id from stats-hub: hub down')
    assert _status(app, iid) == InstanceStatus.RUNNING
```
demo-stream variant: patch `is_relay_configured -> True`, `is_stats_hub_configured_for_host -> True`, `get_instance_server_id -> 7`, `get_instance_demo_stream_token -> 'tok'`, `_register_route` raising `requests.ConnectionError('hub down')`; expected `(False, 'Could not register the demo-stream route with stats-hub: hub down')`.

```python
def test_enable_endpoint_passes_the_previous_status(app, client, monkeypatch):
    settings = importlib.import_module('qlsm_addon_telemetry_relay.settings')
    monkeypatch.setattr(settings, 'is_relay_enabled', lambda host_id: True)
    monkeypatch.setattr(settings, 'is_stats_hub_configured_for_host', lambda host_id: True)
    import ui.task_lock, ui.tasks
    monkeypatch.setattr(ui.task_lock, 'acquire_lock', lambda *a, **k: True)
    calls = []
    monkeypatch.setattr(ui.tasks, 'enqueue_task', lambda task, *args, **kwargs: calls.append((args, kwargs)))
    make_user(app, 'op', 'pw')
    iid = _instance(app, InstanceStatus.RUNNING)
    resp = client.post(f'/api/addons/telemetry-relay/instances/{iid}/enable', json={}, headers=auth_headers(app, 'op'))
    assert resp.status_code == 202
    assert calls[0][0] == (iid,) and calls[0][1]['previous_status'] == 'running'
    assert _status(app, iid) == InstanceStatus.CONFIGURING
```
demo-stream: patch `qlsm_addon_demo_stream.settings.is_relay_configured -> True`, post to `/api/addons/demo-stream/instances/{iid}/enable` with `json={'enabled': True}`.

Each file: 5 tests (3 parametrized + 2).

- [ ] **Step 2: Run to verify failure**

Run: `QLSM_REPO=C:/Users/hellp/orca/workspaces/qlsm/QLSM python -m pytest tests/test_addon_telemetry_relay_enable.py tests/test_addon_demo_stream_enable.py -q -p no:cacheprovider`
Expected: 10 failed (`TypeError: ... unexpected keyword argument 'previous_status'`, `KeyError: 'previous_status'`).

- [ ] **Step 3: Implement (both addons, same shape)**

- `instance_ops.py`: import `InstanceStatus` with `QLInstance`; add `_status_after_failure(previous_status)` (valid `InstanceStatus` value -> that member, else `InstanceStatus.ERROR`); `_finish(instance, ok, message, previous_status=None)`: when `not ok and instance.status == InstanceStatus.CONFIGURING`, set `instance.status = _status_after_failure(previous_status)` before the existing commit. Logic functions take `previous_status=None` and pass it to every `_finish(...)` call. The "Instance or associated host not found." return goes through `_finish(instance, False, ..., previous_status)` when `instance` exists (host missing); with no instance it stays a bare return.
- `backend.py`: capture `previous_status = instance.status.value` before `update_instance(..., status=InstanceStatus.CONFIGURING)` and add `previous_status=previous_status` to the `enqueue_task(...)` call (telemetry-relay `:248-250`, demo-stream `:167-169`). The task functions (`:284-288`, `:190-196`) take `previous_status=None` and pass it on.
- Versions: telemetry-relay `1.3.0` -> `1.3.1`, demo-stream `1.1.1` -> `1.1.2`.

- [ ] **Step 4: Run to verify pass**

Same command: `10 passed`. Full suite: `323 passed`.

- [ ] **Step 5: Commit**

```bash
python generate_manifest.py
python check_manifest_hashes.py
git add tests/test_addon_telemetry_relay_enable.py tests/test_addon_demo_stream_enable.py addons/telemetry-relay/instance_ops.py addons/telemetry-relay/backend.py addons/telemetry-relay/qlsm-addon.json addons/demo-stream/instance_ops.py addons/demo-stream/backend.py addons/demo-stream/qlsm-addon.json qlsm-repository.json packages/telemetry-relay.zip packages/demo-stream.zip
git commit -m "telemetry-relay, demo-stream: reset instance status when enabling fails"
```

---

### Task 10: Close out

**Files:**
- Modify: `tasks/0003-review-fixes-descriptions-in-english-and-the-sev.md` (currently untracked in this worktree)

**Interfaces:**
- Consumes: the commits of Tasks A-I.
- Produces: nothing.

- [ ] **Step 1: Final checks**

```bash
python generate_manifest.py
python check_manifest_hashes.py
QLSM_REPO=C:/Users/hellp/orca/workspaces/qlsm/QLSM python -m pytest tests/ -q -p no:cacheprovider
python "D:/QuakeLiveData/QL Server/skills/tasks/scripts/task.py" check
git status --short
```
Expected: `Updated qlsm-repository.json: 11 plugins, 6 addons.`; `all sha256 hashes match`; `323 passed`; `... task files, 0 problems`; `git status` shows only the task file (generate_manifest must not have changed anything).

- [ ] **Step 2: Update the task file**

- Tick the first four `## Шаги` boxes (plan, descriptions, bugs 1-8, generate_manifest + tests); leave "Слито в main" for the controller.
- `updated: 2026-10-11`; `related` keeps the plan path.
- `## Журнал`: `- 2026-10-11 - tasks A-I done in fix/review-2026-10-11 (subagent-driven), 323 tests green`.
- `## Результат`: one line per commit, `<short sha> <subject>`, from `git log --oneline origin/main..HEAD`, plus: plugin runtime set to `minqlxtended` for every entry (operators must re-download plugins they took before, see Plan notes 4); addon versions qlmatch-packer 1.1.2, telemetry-relay 1.3.1, demo-stream 1.1.2.
- `## Как проверить`: (1) Repositories page shows the new descriptions and lists chat_rcon without a helper; (2) on a test server: `!rcon pause; exec x.cfg` from a referee answers `chat-rcon: denied: one command per line`; `say !rcon g_password x` does not appear in the hub chat archive; take mega, `!restore export` shows `1 pending` and the JSON has the mega row with `s:2`; restore, pause and unpause twice, players are not pushed on the second unpause; a non-roster `StreamSpec` name is kicked on a closed server; (3) stop the relay, trigger `!call`, start the relay: the call arrives; (4) enable telemetry on an instance with no stats-hub configured: the status returns to its previous value.

- [ ] **Step 3: Commit**

```bash
git add tasks/0003-review-fixes-descriptions-in-english-and-the-sev.md
git commit -m "tasks: 0002 review fixes done"
```

Merging to `main` and pushing is the controller's job, not this task's.

---

## Plan notes

1. `export_item_row` with a known pickup returns `{"k", "s": 2, "in", "at_ms"}`, not an `s:0`/`remain` row as the brief described; the brief's numbers (pickup 10 s, now 20 s, mega 35 s) give `in: 25.0, at_ms: 45000`, which is what Task 2 tests.
2. The session feed does send connects and disconnects (`stream_telemetry_unified.py:1943,1947`); the old "player join/leave" text was incomplete, not false. Task 1 lists all kinds.
3. `generate_manifest.py:138-147` keeps the manifest's own plugin `label`/`description`/`runtime` over the sidecar and falls back to the old `depends_on`, so sidecar edits alone never reach `qlsm-repository.json`. Task 1 strips those keys before regenerating.
4. Runtime: every plugin imports `minqlxtended` first (`chat_rcon.py:10` only that), `match_restore` uses minqlxtended-only APIs, and in QLSM the entry's runtime picks the pool (`QLSM/ui/plugin_pool.py`, `data/shared-plugins/<runtime>/`); a `minqlx` entry is invisible to minqlxtended hosts. All entries become `minqlxtended`. Copies an operator already downloaded sit in the `minqlx` pool and must be downloaded again.
5. qlmatch-packer: rebuild actions exist only for a match that already has a `.qlmatch` (`match_groups.py:84-170`, `rebuild_ops.py:42-52`), and nothing builds a first pack after a match, so there is no UI path to a first pack. Task 1 describes this honestly; it is not fixed here.
6. Addon updates are detected by `version` only (`QLSM/ui/plugin_repositories.py:830-870`), so Tasks 8 and 9 bump patch versions despite the "do not bump" constraint; without that installed copies never receive the fixes. Task 1's description-only addon edits do not bump.
7. `core.hooksPath` is absolute to the main checkout, so the pre-commit hook does not check this worktree; each commit step runs `check_manifest_hashes.py` by hand.
8. QLSM has no read-only addon field (`ui/addons/manifest.py`, `AddonFormPanel.jsx`); telemetry-relay's `server_id` gets a description instead.
9. `say_team !rcon ...` leaks the same way as `say`; Task 5 filters both.
10. Task 4 keeps a lifecycle row in the queue until acked instead of re-inserting it at the head on failure (same effect, no cross-thread insert), and removes acked rows by identity on the game thread. The items feed has a similar latent race (`state.complete()` runs before `del self._items_queue[:batch_len]` on the worker, `:1586-1588`); left alone.
11. Task 2 clears tracked pickups when a restore session starts, so an export taken right after a restore shows the restored pending items as available until they are picked up again.
12. Out of scope, unchanged: `lobby.py` hub assignment texts shown to players are Russian (`:131-136`, `:168-174`); `lobby.py:85` still sets the unused `qlx_lobbyTrySteamOpen`.
13. In `tournament_access` the team-switch specbot branch only blocks; the real hole is at player load. A specbot with the bypass level is still not forced to spectator (unchanged).
