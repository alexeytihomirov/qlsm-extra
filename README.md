# qlsm-extra

Optional **plugins** and **addons** for [qlsm](https://github.com/alexeytihomirov/qlsm)
that do **not** ship in the standard qlsm image / plugin pools.

| Kind | What |
|------|------|
| Plugins | QLMatch tournament gameplay (`tournament_access`, `chat_rcon`, `lobby`, `referee_call`, `match_restore`), demo packing and live stream repair (`qlmatch_packer`, `demo_stream_resync_hold`), server frame timing (`frame_timing`), live telemetry for the `minqlxtended` runtime |
| Addons | `telemetry-relay`, `demo-management`, `demo-stream`, `qlmatch-packer`, `file-forwarder`, `runtime-source`, `player-ranks`, `host-metrics`, `server-ping` |

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

The zips are reproducible: entries are sorted, carry a fixed date, mode and
host OS, and text files (no NUL byte) are packed with LF line endings
whatever the checkout has (`core.autocrlf`, a file type `.gitattributes` does
not list). So a rebuild changes only the packages whose files changed, on
Windows and Linux alike.

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
| `tournament_access.py` | Yes - the roster comes from the tournament hub through the server's Redis and is checked only once the hub marks it enforced (`qlx_tournamentAccessEnabled` and a `qlx_tournamentId` needed too). On a lobby server everyone stays in spectator. A stream spectator account (name starting with `StreamSpec`, or `qlx_specbot_name_prefix`) must be on the roster or have the bypass level like anyone else; on the roster it is kept in spectator |
| `chat_rcon.py` | Yes |
| `lobby.py` | Yes |
| `frame_timing.py` | Yes - every 10 s writes the last 10 s of server frame stats (frames, late frames, max, p50 and p99 gap) to the Redis key `minqlx:frame_stats:<port>` with a 30 s TTL, for the `host-metrics` addon. A frame is late when it takes longer than 1.5 x 1000 / `sv_fps` ms; the gap across a map change is not counted. The frame hook only reads the clock; the Redis write runs in a worker thread |
| `referee_call.py` | Yes - `!call` for players; the call travels as chat through `stream_telemetry_unified` (Session Events on) |
| `tournament_match_notice.py` | Yes - when both players of a `ready` or `live` match of the tournament site are on the server, says so in chat and in the centre of the screen: once on arrival (per map), again on every game countdown. Needs `qlx_matchNoticeEnabled 1`, `qlx_matchNoticeUrl` (site base URL) and `qlx_matchNoticeToken` (site service token, scope `game:read`; it asks `GET /api/integrations/game-match`). The hooks only set flags; a worker thread asks the site every 2 s at most and only after the players changed (3 s timeout, 60 s cache); only the two output calls run in the game frame. A failed request is logged once a minute and skips the notice |
| `match_restore_util.py` | No - helper for `match_restore.py`, downloaded with it |
| `match_restore.py` + `restore/` | Yes - downloads as one entry |
| `qlmatch_packer.py` | Yes - launches the `qlmatch-packer` addon's `pack.mjs` when the engine finishes a match's demos; **required** for automatic `.qlmatch` (without it only raw `.dm_91` remain). Downloads with its helper `qlmatch_packer_cmd.py` (not a plugin) |
| `demo_stream_resync_hold.py` | Yes - after the engine forces a full snapshot for a live-streamed player (relay reconnect, lost blocks, keyframe), keeps forcing one per server frame until the client acknowledges it (at most `qlx_demoStreamResyncHoldMaxFrames`, default 8; at most `qlx_demoStreamResyncHoldPerFrame` holds at once, default 2). **Off by default** (`qlx_demoStreamResyncHold 0`): measured on a duel server only, not yet on a populated server or in team modes; set it to 1 to enable. With `sv_demoStreamKeyframeSec 0` there are no keyframe holds, but a relay reconnect and lost blocks are still repaired, the first player after a reconnect included. `qlx !resynchold` prints the counters, `qlx !resynchold log` the last holds. Needs the fork's live demo stream |

`demo_stream_resync_hold.py` in more detail: without it the snapshots right
behind a single full one are deltas from messages the relay never received,
and the relay's picture can stop until the next keyframe. Cost: one to three
extra full snapshots (about 250 bytes each in a duel) per resync and per
keyframe interval for each streamed player, none while the relay is behind.
For a periodic keyframe the plugin cannot see which player the engine meant
and works it out from its own record of each player's last full snapshot. A
hold that has waited more than 60 server frames for its turn is dropped,
unless it repairs a real loss. It does nothing while `sv_demoStream` is off.

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

Every session event and item pickup carries `sample_wall_ms` (int ms of the game
host's `time.time()` in the hook), the same clock as the positions' `sample_wall_ms`,
so the hub can place it on the positions' time line instead of stamping it on arrival.
The relay forwards it unchanged; a hub that does not know it ignores it.

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
| `telemetry-relay` | Per-host relay that forwards `stream_telemetry_unified` data to ql-stats-hub, and the owner of the **Stats Hub** entries for telemetry and the live demo stream together: host menu **Stats Hub** (relay and demo stream tunnel), instance menu **Stats Hub** (**Send telemetry**, **Live demo stream**, the stream delay, one Save with at most one restart), Settings -> **Stats Hub** (hub URL, ingest token, **Switch on new instances**, demo stream relay). The server ID is reserved automatically and shared by both. **Switch on new instances** (or the **Stats Hub** tab of the Add Instance form) sets up telemetry and the live demo stream before the first deploy |
| `demo-management` | The **Demos** screen: lists and downloads what an instance recorded |
| `demo-stream` | Live POV demo stream through a central relay; per-host stunnel TLS tunnel to stats-hub. No menu entries of its own since 1.9.0: it is switched on and configured in the **Stats Hub** entries of `telemetry-relay` (1.9.0 or newer); its API routes, tasks and launch args are unchanged. A delay change applies on stats-hub without a restart |
| `qlmatch-packer` | Installs the `.qlmatch` packer on hosts; shows and rebuilds packs on the Demos screen. The `qlmatch_packer.py` plugin runs it when the engine finishes a match's demos |
| `file-forwarder` | Ships demo files (.qlmatch packs, replay sidecars, raw demos) from game hosts to the VPS over SFTP with rclone, keeps a delivery ledger, cleans up delivered raw demos, and offers manual sync from the host menu. The VPS address is a setting; saving it scans the VPS host keys and shows their fingerprints. The host menu entry **File Forwarder** has the host switch, the status and **Apply to host**, **Sync now** and **Sync now and delete delivered** |
| `runtime-source` | Builds a host's minqlxtended from a repository you choose (a fork) instead of the commit qlsm pins. Per host: enter repository + commit in **Runtime Source**, then **Re-run Host Setup**. Needs a QLSM whose host setup supports a custom minqlxtended repository on every provider (`host.setup` hook). |
| `player-ranks` | Shows external ratings (qlstats, Slipgate, x76) stacked in one Rank column in Live Status. Sources are chosen per instance on its Ranks tab; qlstats/Slipgate connection details are set once for the installation. Needs qlsm `ui_api` 4 or newer. |
| `host-metrics` | Per-host and per-instance resource metrics: a low-priority collector on every game host keeps 30 days of CPU (incl. steal), memory, disk, players and frame timing in SQLite; the Host Metrics page is a health board (status, findings in plain English, hardware, charts) with a capacity verdict per host. Collector changes reach a host with **Apply to host** |
| `server-ping` | Browser ping to game hosts: deploys `ql-ping-echo` (a static Go WebRTC UDP echo, `Nice=19`, `CPUWeight=1`, user `ql-ping`) to each enabled host and opens its UDP port (default 28111) in its own firewall chain `QLPING-INPUT`, never touching qlsm's `QLSM-INPUT`. One DTLS key + certificate for all hosts: generate it once on the **Server Ping** page and put the fingerprint shown there into the ql-tournament env (`PING_DTLS_FINGERPRINT`). Per host: switch, Status, **Apply**; a host setup re-applies it; Apply refuses while the addon is switched off globally. While enabled, the `QLPING-INPUT` chain and hook also end up in `/etc/iptables/rules.v4`, because qlsm runs `iptables-save > /etc/iptables/rules.v4` on every instance add/start; switching a host off + Apply re-saves that file when it still holds the chain, so the port stays closed after a reboot. Rebuild the binary with `addons/server-ping/build.sh` |

qlsm's image ships **no** addon - install every one of these from this
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

**demo-stream 1.5.0:** the Demo Stream Delay instance menu entry is merged
into **Live Demo Stream**, which now has the stream switch and the delay, and
its status shows whether the instance streams and with what delay. Switching
the stream off now works (`sv_demoStream 0`, applied with a restart; the token
and hub route are kept for re-enabling). The Demo Stream Relay and Demo Stream
Stats Hub settings sections are one **Live Demo Stream** section. After
upgrading nothing needs re-entering: set the delay in **Live Demo Stream**
instead of the old entry.

**telemetry-relay 1.5.0:** Telemetry moved from an instance tab to an
instance menu entry **Telemetry** with a **Send telemetry** switch; the
server ID field is gone. The ID is reserved from stats-hub automatically,
kept when telemetry is switched off, and shown in the entry's status.
Switching off now works (`qlx_statsHubUnifiedEnabled 0`, applied with a
restart). After upgrading, use the menu entry instead of the tab; instances
already sending keep their server ID.

**telemetry-relay 1.5.1:** the Telemetry entry has a **Reserve a new server
ID** switch for two servers that share one: saving with it on (and Send
telemetry on) reserves a fresh ID from stats-hub and restarts once; untick it
afterwards (another new ID is refused for 10 minutes). Setting a cvar in
`server.cfg` now leaves exactly one `set` line for it, removing duplicates.

**demo-stream 1.5.1:** when the stream runs under another server ID than the
instance's telemetry, the Live Demo Stream status says so and a save moves the
stream to telemetry's ID (one restart).

**demo-stream 1.6.0:** the host's **Demo Stream Tunnel** entry has **Relay
host for this host** and **Relay port for this host**: where that host's
stunnel connects instead of the relay in Settings (both or neither; blank uses
Settings). For a host that cannot reach the hub's TLS port directly, e.g. one
whose provider path cuts TLS on non-standard ports: point it at a plain TCP
relay on port 443 elsewhere that forwards to the hub's ingest port. The TLS
and the pinned hub certificate go through the relay untouched; stats-hub sees
the relay's address, so that address must be in the hub firewall, and the
entry's status then says "demo stream through relay <host:port>" instead of
counting links. Saving re-renders the host's `stunnel.conf`. Nothing to do
after upgrading: hosts without the fields keep the relay in Settings.

**telemetry-relay 1.6.0:** the host's **Telemetry Relay** entry has **Forward
through** (`http://host:port`, no path): the sidecar on that host sends its
POSTs there instead of the stats-hub URL, for a host whose own HTTP path to
the hub is cut (a plain TCP relay on port 80 that forwards to the hub's 8090).
qlsm's own calls to stats-hub (server IDs, firewall) keep the stats-hub URL.
stats-hub sees the relay's address, so it must be in the hub firewall, and the
"telemetry N s ago" in the entry's status refers to this host's own address
(it reads "no telemetry seen" while everything goes through the relay); the
status adds "sends through <url>". Blank sends straight to stats-hub as
before.

**telemetry-relay 1.7.0, demo-stream 1.7.0:** on an instance where the addon
is switched on (Addons, at global, host and instance level), its cvars
(`qlx_statsHubUnifiedEnabled`, `qlx_statsHubServerId`; `sv_demoStream`,
`sv_demoStreamHost`, `sv_demoStreamPort`, `sv_demoStreamToken`) are passed as
`+set` launch arguments from the addon's own state and no longer live in
`server.cfg`. A preset saved from the instance does not carry them (the
stream token included), and loading a preset onto it does not wipe them. A
`server.cfg` line for one of them still wins (it is exec'd after the command
line), so the panel reports it as drift and **Save** in the Telemetry / Live
Demo Stream entry removes the lines and restarts once: do that once per
instance after upgrading. Where the addon is not switched on for the
instance, nothing changes: the cvars are written into `server.cfg` as before.

**telemetry-relay 1.7.1, demo-stream 1.7.1:** qlsm's UI only has the global
addon switch, so under 1.7.0 the host and instance layers stayed off and the
cvars stayed in `server.cfg`. The enable and disable now switch the addon on
for the instance's host and the instance themselves, and a **Save** in the
Telemetry / Live Demo Stream entry runs them when those layers are off or
`server.cfg` still has the cvars, also for an instance that is switched off.
The stream remembers the tunnel port it was wired to, so a changed host
tunnel port still shows as drift until a save.

**telemetry-relay 1.8.0, demo-stream 1.8.0:** Settings -> **Telemetry Stats
Hub** has **Switch on new instances**. With it on, a new instance gets
telemetry and the live demo stream before its first deploy: one server ID is
reserved once (telemetry-relay reserves it, demo-stream takes the same one
whenever both use the same stats-hub), the addon layers are switched on and
the `+set` launch args are in the very first start, so there is no extra
apply or restart. The Add Instance form has a **Stats Hub** tab (from
telemetry-relay) with both switches, prefilled from that setting, and an
optional **Server ID** to use instead of reserving one. What a host cannot do
yet (Telemetry Relay off, no Demo Stream Tunnel, Live Demo Stream addon
switched off, hub unreachable) is skipped with a "Stats Hub: ..." line in the
instance log; switch that on and save the instance's panel as before. Needs a
qlsm with the `instance.created` hook and the `add_instance_tabs` mount point
(upstream PR `upstream-pr/add-instance-addon-hook`); on an older qlsm the
setting is shown but nothing happens on create and the tab does not appear,
everything else works as in 1.7.1. Update both addons together: the stream
part runs demo-stream 1.8.0's set-up, an older demo-stream is reported in the
log instead.

**telemetry-relay 1.9.0, demo-stream 1.9.0:** one **Stats Hub** entry each in
the host menu, the instance menu and Settings, all from telemetry-relay;
demo-stream's own **Demo Stream Tunnel**, **Live Demo Stream** entries and
settings section are gone (its API routes stay). Both addons keep their own
stored settings, nothing is migrated:
- Instance entry: **Send telemetry**, **Reserve a new server ID**, **Live demo
  stream**, **Stream delay**. One Save runs whatever changed for both in one
  task with one apply and restart; a delay change alone is one hub call and no
  restart. A new server ID now moves a streaming instance's stream to it in the
  same restart. It always restarts, like the old entries: the cvars are launch
  args, which a deferred restart (Settings -> Defer restarts) would not pick up.
- Host entry: the relay fields and the tunnel fields; what has to run on the
  host (relay and/or tunnel playbook) runs in one host job. The stats-hub URL
  and token override are stored for both addons.
- Settings: hub URL, ingest token, **Switch on new instances**, demo stream
  relay host and port. Saving writes the URL and token to both addons, so they
  point at the same hub (a stream that used a different hub moves to this one
  with its next enable); the status line says when they still differ.
- Ingest tokens are never sent back to the browser any more: blank keeps the
  stored one; clearing a host's URL override clears its token override too.
- Menu statuses are just **On** / **Off**, from local state only (no SSH or hub
  call when the menu opens). Instance: On when telemetry or the stream is
  switched on. Host: On when the relay is on, and the tunnel too once any
  instance on the host streams. The details are in the entry's own status line.
- Without a usable demo-stream (not installed, switched off, older than 1.9.0)
  the entries show and save telemetry only; switching the stream or the tunnel
  on is refused with the reason, and the status line says why.
Update both addons together; after the update use the Stats Hub entries.

**player-ranks 0.4.0:** the installation-wide "on by default" switches for
qlstats and Slipgate are gone; each instance picks its sources on its own
Ranks tab, and a new instance starts with every source off. On the first load
after the update an instance that never saved its Ranks tab gets the sources
it showed before, so nothing visible changes and there is nothing to do.

**file-forwarder 1.2.0:** no VPS address or host key is built in any more.
The VPS address is a setting; saving a new one scans its SSH host keys from
qlsm, stores them and shows their SHA256 fingerprints, and **Re-scan host
keys** reads them again after a VPS reinstall. Forwarders already on the
hosts keep running untouched, but **Apply to host** refuses until the
settings are saved once. After upgrading: open Settings -> Addons -> File
Forwarder, enter the VPS address if the field is empty, save once, compare
the fingerprints in the status line with the VPS provider console, then use
**Apply to host** on each host.

**host-metrics 1.1.0:** the Host Metrics page becomes a health board (one card
per host with a status, open problems and plain-English findings), the host
dialog shows hardware (CPU model, memory, disk, provider) and charts with their
limits marked, all in the QLSM light and dark theme. On a QLSM core with
notifications (`poller.tick`, `ctx.notify`) and `page.nav` it also:

- puts host problems under the navbar bell: late frames or a saturated core
  while players are on, high steal, low memory (warning); an OOM kill, a full
  disk, a host unreachable or a collector silent for more than 5 minutes
  (critical). Checked once a minute against what is open on the host now: one
  notification per problem, resolved after it stayed clear for two checks (a
  flapping condition does not flood the bell), an OOM kill stays for 24 hours,
  a host switched off has its notifications resolved. Switch and minimum
  severity: Settings -> Addons -> Host Metrics (`notify_enabled`,
  `notify_min_severity`);
- adds a **Hosts health** entry to the navbar.

On an older core the addon loads and works as before, without the bell
notifications and without the navbar entry (the page stays at
`/addons/host-metrics`). Hosts need **Apply to host** after the update to 1.1.0
(the collector gains hardware info and the list of open events; the bell
notifications are state-based and read that list, so a host that was not
re-applied only gets the "unreachable" and "collector silent" notifications).

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
Addons run in-process with qlsm's full authority - only install what you trust.

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
