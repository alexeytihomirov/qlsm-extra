#!/usr/bin/env node
// qlmatch packer — builds one {name}.qlmatch (zip, STORE) per finished match
// out of the trimmed per-player POV .dm_91 files + index/*.snaps.json that
// minqlxtended's native demo capture (demo_match.c, vendored in
// ql-assets/patches/minqlxtended/) leaves in the instance demo directory,
// then generates the {match_id}_{map}.replay.json.gz merged-replay sidecar
// next to the pack (qlmatch-to-replay.mjs child process).
//
// Contract: ql-demo-recorder/docs/superpowers/prompts/
// 2026-08-17-sv-demorecord-multi-pov-AGENT-PROMPT.md, section
// "Post-process (off the game thread) -> .qlmatch". This process is that
// packer. Nothing launches it automatically any more (demo_native_autorecord.py
// was retired): it runs by hand on the host or from the qlmatch-packer addon's
// rebuild actions over SSH, never on the QLDS game thread or inside the QLDS
// process.
//
// Demo protocol parsing (player identity, teams, gametype) reuses the
// parser originally vendored from ql-stream-tools/live-overlay/lib/qldemo
// (archived 2026-10-14) into vendor/qldemo, NOT the stale
// _tmp/overkilldemos/qldemo-nquery snapshot the old prototype used.
// vendor/qldemo is now this addon's own copy and the canonical one: it has
// diverged from ql-stream-tools, which is frozen, and nothing syncs it.
//
// Multi-POV capture (engine sv_demoMultiPov 1): when the match's capture is a
// single file recorded by the server's own connection (gamestate clientNum
// >= sv_maxclients, engine name "{match_id}_{map}_multipov_*"), no .qlmatch
// is built. That file IS the match: it is renamed to "<name>.dm_91" (<name> =
// the rendered name template), described by "<name>.meta.json" (format
// qlsm-demo-meta, version 2) and gets the same replay sidecar. See
// publishMultiPov().
//
// Exit codes:
//   0 pack written (or the multi-POV match published)
//   2 window validation failed (empty/short POV overlap) — no zip written
//   3 no POV files found for the match — nothing to do
//   5 usage / IO error

import {
  readFileSync, readdirSync, writeFileSync, renameSync, existsSync, statSync, copyFileSync, unlinkSync, mkdirSync,
} from "node:fs";
import { join, basename, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";
import { QLDemoParser } from "./vendor/qldemo/demo-parser.js";
import { zipSync } from "./zip-store.mjs";
import { matchIdentity } from "./match-identity.mjs";

const DM91 = ".dm_91";
// Mirrors demo_match.c DEMO_MIN_WINDOW_MS: a shared window shorter than this
// is meaningless and the contract says fail the pack rather than ship it.
const DEFAULT_MIN_WINDOW_MS = 5000;
const SIDECAR_TIMEOUT_MS = 10 * 60 * 1000;
// The engine writes the match GUID into this configstring of every gamestate.
const CS_MATCH_GUID = 712;

function log(...args) {
  console.log("packer:", ...args);
}
function fail(code, ...args) {
  console.error("packer: FAIL:", ...args);
  process.exit(code);
}

function parseArgs(argv) {
  const args = { minWindowMs: DEFAULT_MIN_WINDOW_MS, nameTemplate: "", outDir: "" };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    const next = () => {
      i++;
      if (i >= argv.length) fail(5, "missing value for", a);
      return argv[i];
    };
    if (a === "--dir") args.dir = next();
    else if (a === "--match-id") args.matchId = next();
    else if (a === "--map") args.map = next();
    else if (a === "--name-template") args.nameTemplate = next();
    // Old launchers still pass --rclone-targets: accept and ignore it (delivery
    // moved to the file-forwarder addon) so packing never breaks on it.
    else if (a === "--rclone-targets") { next(); args.rcloneIgnored = true; }
    else if (a === "--min-window-ms") args.minWindowMs = parseInt(next(), 10);
    else if (a === "--out-dir") args.outDir = next();
    else fail(5, "unknown argument", a);
  }
  if (!args.dir || !args.matchId) {
    fail(5, "usage: pack.mjs --dir <demo_dir> --match-id <stamp> [--map <map>] " +
      "[--name-template <tpl>] [--min-window-ms N] [--out-dir <dir>]");
  }
  return args;
}

// Mirrors demo_match.c demo_index_path(): "{dir}/index/{basename minus
// '.dm_91'}.snaps.json" — the index name is derived from the demo's own
// basename (per-segment unique), not "p{slot}".
function indexPathFor(dm91Path) {
  const base = basename(dm91Path);
  const stem = base.endsWith(DM91) ? base.slice(0, -DM91.length) : base;
  return join(dirname(dm91Path), "index", stem + ".snaps.json");
}

function discoverPovFiles(dir, matchId) {
  const prefix = matchId + "_";
  return readdirSync(dir)
    .filter((n) => n.startsWith(prefix) && n.toLowerCase().endsWith(DM91) && !n.toLowerCase().endsWith("_merged" + DM91))
    .sort()
    .map((n) => join(dir, n));
}

function loadIndex(dm91Path) {
  const p = indexPathFor(dm91Path);
  if (!existsSync(p)) return null;
  try {
    const data = JSON.parse(readFileSync(p, "utf8"));
    if (!data || !Array.isArray(data.snapshots)) return null;
    return data;
  } catch (err) {
    log("warning: unreadable index", p, "-", err.message || err);
    return null;
  }
}

// Fallback (slot, name) recovery from the C-owned filename convention
// "{match_id}_{map}_p{slot}_{name}_{seg_time}_{seg_id}.dm_91" — same
// heuristic as demo_native_manifest.py:parse_name_from_basename, except up
// to two trailing numeric tokens are stripped one at a time so the older
// eBPF-writer convention (single trailing number) parses too. Underscores
// come back as spaces: demo_sanitise() turned spaces into '_' when naming
// the file.
function nameFromBasename(base, matchId, mapName) {
  const stem = base.endsWith(DM91) ? base.slice(0, -DM91.length) : base;
  const prefix = `${matchId}_${mapName}_`;
  if (!stem.startsWith(prefix)) return "";
  const parts = stem.slice(prefix.length).split("_");
  if (!parts.length || !/^p\d+$/.test(parts[0])) return "";
  const middle = parts.slice(1);
  let dropped = 0;
  while (middle.length > 1 && dropped < 2 && /^\d+$/.test(middle[middle.length - 1])) {
    middle.pop();
    dropped++;
  }
  return middle.join(" ").trim();
}

// Parses one POV for its identity: recorder clientNum, roster (names +
// teams) and serverinfo. A demos.c stage-2 cut file has exactly one
// gamestate and a monotonic clock (demo_write_index refuses to index
// anything else), so its roster is live within a few snapshots — the walk
// stops early. A file WITH a mid-file clock reset (leftover
// previous-occupant prefix, e.g. an un-cut copy-through or a legacy raw
// capture) is parsed to the end instead, because only the post-reset
// roster/configstring updates identify the real occupant — the same
// leftover problem parseUntilLiveIdentity / match-set.js solve in
// demo-editor, which the old qldemo-nquery prototype lacked. Driven through
// parseOnePacket directly so the decoded snapshot list can be dropped as we
// go: identity only needs gamestate state, and holding every snapshot of N
// full-match POVs would cost hundreds of MB.
function parseIdentity(bytes, index) {
  const parser = new QLDemoParser(bytes);
  const RESET_MS = 1000;
  const CLEAN_SNAPS_ENOUGH = 64;
  let prevT = null;
  let firstT = null;
  let sawReset = false;
  try {
    while (true) {
      const r = parser.parseOnePacket();
      if (r.done) break;
      parser.snapshots.length = 0;
      const t = r.snapshot?.serverTime;
      if (t != null && firstT == null) firstT = t;
      if (prevT != null && t != null && prevT - t > RESET_MS) sawReset = true;
      // Early stop only for a provably clean file: its C-written index says
      // the demo starts exactly where its first snapshot actually starts
      // (demo_write_index only ever indexes single-gamestate, no-clock-reset
      // files, so index.first == first snap == live roster within a few
      // snapshots). Anything else — no index, or an index whose range
      // doesn't start at the file's own first snapshot (legacy raw capture
      // with a leftover prefix) — is parsed to the end.
      if (
        !sawReset &&
        parser.gamestateCount === 1 &&
        parser.snapshotsParsed >= CLEAN_SNAPS_ENOUGH &&
        index &&
        firstT === index.first_server_time
      ) {
        break;
      }
      if (t != null) prevT = t;
    }
  } catch (err) {
    parser.errors.push(String(err.message || err));
  }
  parser.sawClockReset = sawReset;
  return parser;
}

function computeWindow(entries, minWindowMs) {
  const indexed = entries.filter((e) => e.index);
  if (!indexed.length) return { error: "no indexed POV files — cannot establish a shared window" };

  // The stage-2 cut in demo_match.c gives every clock-aligned POV a
  // byte-identical (first,last) pair; a POV published un-cut (outlier,
  // copy-through) keeps its own different range. So a (first,last) pair
  // shared by >= 2 files IS the aligned cohort — same reasoning as
  // demo_native_manifest.py:compute_window.
  const counts = new Map();
  for (const e of indexed) {
    const key = `${e.index.first_server_time}|${e.index.last_server_time}`;
    counts.set(key, (counts.get(key) || 0) + 1);
  }
  let best = null;
  for (const [key, n] of counts) {
    if (n >= 2 && (!best || n > best.n)) best = { key, n };
  }

  let start, end, group;
  if (best) {
    const [f, l] = best.key.split("|").map(Number);
    start = f;
    end = l;
    group = indexed.filter((e) => e.index.first_server_time === f && e.index.last_server_time === l);
  } else {
    // No pre-aligned cohort (e.g. files that never went through the shared
    // stage-2 cut): the shared window is the raw intersection of all ranges.
    start = Math.max(...indexed.map((e) => e.index.first_server_time));
    end = Math.min(...indexed.map((e) => e.index.last_server_time));
    group = indexed;
  }

  if (indexed.length >= 2 && !(end - start >= minWindowMs)) {
    return {
      error:
        `shared window [${start},${end}] is ${end - start} ms across ${indexed.length} indexed POVs ` +
        `(< ${minWindowMs} ms) — refusing to pack a desynced .qlmatch`,
    };
  }
  if (!(end >= start)) return { error: `invalid window [${start},${end}]` };

  const gstVotes = new Map();
  for (const e of group) {
    const g = e.index.game_start_server_time;
    if (g != null && g !== -1) gstVotes.set(g, (gstVotes.get(g) || 0) + 1);
  }
  let gameStart = -1;
  for (const [g, n] of gstVotes) {
    if (gameStart === -1 || n > gstVotes.get(gameStart)) gameStart = g;
  }
  return {
    window: { start_server_time: start, end_server_time: end, game_start_server_time: gameStart },
  };
}

function mapNameOf(parser) {
  return parser.gamestate.config.serverinfo?.mapname || "";
}

// Configstring bytes reach us latin-1-decoded: the vendored parser's
// huffmanReadBigString maps every raw byte to one JS code point. Player
// names from modern clients are UTF-8 on the wire, so a multibyte name
// (e.g. Chinese) arrives as mojibake ("ä¸æµ·..."). Re-decode: code points
// back to bytes, then strict UTF-8. A byte string that is NOT valid UTF-8
// (a genuinely latin-1-era name) is left exactly as delivered.
const UTF8_STRICT = new TextDecoder("utf-8", { fatal: true });
function decodeQlString(s) {
  s = String(s || "");
  let hasHigh = false;
  for (let i = 0; i < s.length; i++) {
    const c = s.charCodeAt(i);
    if (c > 255) return s; // already real decoded text, not a byte string
    if (c > 127) hasHigh = true;
  }
  if (!hasHigh) return s;
  try {
    return UTF8_STRICT.decode(Uint8Array.from(s, (ch) => ch.charCodeAt(0)));
  } catch {
    return s;
  }
}

const GAMETYPE_NAMES = {
  0: "ffa", 1: "duel", 2: "race", 3: "tdm", 4: "ca", 5: "ctf",
  6: "1f", 8: "har", 9: "ft", 10: "dom", 11: "ad", 12: "rr",
};

function stripColors(s) {
  return String(s || "").replace(/\^./g, "");
}

// One template substitution -> a filename-safe token.
function sanitizeToken(s) {
  return stripColors(s)
    .replace(/[^A-Za-z0-9._-]+/g, "_")
    .replace(/_+/g, "_")
    .replace(/^_+|_+$/g, "");
}

function renderName(template, ctx) {
  const rendered = template.replace(/\{([a-z_]+)\}/g, (m, key) =>
    Object.prototype.hasOwnProperty.call(ctx, key) ? sanitizeToken(String(ctx[key])) : m,
  );
  const safe = rendered.replace(/[^A-Za-z0-9._{}-]+/g, "_").replace(/_+/g, "_").replace(/^[_.]+|_+$/g, "");
  return safe.slice(0, 180) || ctx.match_id;
}

// "{match_id}.meta.json" next to the demos: what demo-management's Demos
// listing reads to label this match (map, gametype, players, which files are
// its POVs and its pack) without opening the zip, and the only thing that
// ties a pack to its match once qlx_qlmatchNameTemplate has named it
// something without the match id in front. Format and its rules live in
// demo-management's demo_meta.py. One file per match, named after the match
// id (never the template), written to a hidden temp name and renamed into
// place: a reader sees the old meta or the new one, never half of either,
// and a full rebuild simply replaces it. A failure only costs the labels -
// the listing falls back to parsing the engine's own filenames - so it is
// logged, never fatal to the pack.
function writeMatchMeta(args, { mapName, gametype, window, roster, entries, packName, identity }) {
  const steamByClient = new Map(identity.players.map((p) => [p.client_num, p.steam_id64]));
  writeMetaV1(args, {
    map: mapName,
    gametype,
    window,
    matchGuid: identity.match_guid,
    players: [...roster.entries()].map(([cn, p]) => ({
      name: stripColors(p.name),
      team: String(p.team ?? ""),
      steam_id64: steamByClient.get(cn) ?? null,
    })),
    povs: entries.map((e) => ({ file: e.base, client_num: e.clientNum, name: stripColors(e.name) })),
    packName,
  });
}

function writeMetaV1(args, { map, gametype, window, matchGuid, players, povs, packName }) {
  const meta = {
    format: "qlsm-demo-meta",
    version: 1,
    match_id: args.matchId,
    map,
    gametype,
    duration_ms: durationMs(window),
    ...(matchGuid ? { match_guid: matchGuid } : {}),
    players,
    povs,
    pack: packName,
    written_at: new Date().toISOString(),
  };
  if (!writeJsonAtomic(args.dir, `${args.matchId}.meta.json`, meta)) {
    console.error("packer: the match meta is lost, the pack is intact");
  }
}

// Match length from the game start (else the window start) to the window end.
function durationMs(window) {
  const startedFrom = Number.isFinite(window?.game_start_server_time) && window.game_start_server_time > 0
    ? window.game_start_server_time
    : window?.start_server_time;
  const duration = Number.isFinite(window?.end_server_time) && Number.isFinite(startedFrom)
    ? window.end_server_time - startedFrom
    : null;
  return duration > 0 ? duration : null;
}

// JSON to "<dir>/<fileName>" through a hidden ".<fileName>.part" and a rename,
// so a reader sees the old file or the new one, never half of either.
// Returns false (and logs why) when it could not be written.
function writeJsonAtomic(dir, fileName, value) {
  const finalPath = join(dir, fileName);
  const tmpPath = join(dir, `.${fileName}.part`);
  try {
    writeFileSync(tmpPath, JSON.stringify(value, null, 2) + "\n");
    renameSync(tmpPath, finalPath);
    log(`wrote ${finalPath}`);
    return true;
  } catch (err) {
    console.error(`packer: writing ${finalPath} FAILED (${err.message || err})`);
    return false;
  }
}

// ---- multi-POV capture (engine sv_demoMultiPov 1) ---------------------------

// A real Steam account id (individual accounts, 7656119...). Bots carry
// another number or nothing in the "st" key of their CS_PLAYERS row.
const STEAM_ID64_RE = /^7656119\d{10}$/;

function steamOf(row) {
  const s = String(row?.st ?? "").trim();
  return STEAM_ID64_RE.test(s) ? s : null;
}

// The capture is one multi-POV recording: exactly one file, recorded by the
// server's own connection, whose clientNum is sv_maxclients (no player can
// have it). The engine name "_multipov_" is the fallback for a gamestate
// without sv_maxclients; a re-run on an already published "<name>.dm_91" is
// still recognised by its clientNum.
function multiPovEntry(entries) {
  if (entries.length !== 1) return null;
  const e = entries[0];
  const maxClients = parseInt(e.parser.gamestate.config.serverinfo?.sv_maxclients ?? "", 10);
  if (Number.isInteger(maxClients) && maxClients > 0 && e.clientNum >= maxClients) return e;
  return /_multipov_/i.test(e.base) ? e : null;
}

// Everyone who played in the recording: every CS_PLAYERS row seen in a
// playing team at any point of the file, not only at its start, so a player
// who left before the end is still listed. Key is (client_num, steam id): a
// slot reused by another account during the match gives two rows with the
// same client_num; a row without a steam id (bot) keeps its slot's last name.
// Values are the player's last playing row, in order of first appearance.
// steam_id64 is the "st" key QL puts in every player configstring.
function multiPovPlayers(bytes) {
  const parser = new QLDemoParser(bytes);
  const seen = new Map();
  const take = () => {
    for (const [k, row] of Object.entries(parser.gamestate.players || {})) {
      if (!row || !row.n) continue;
      const clientNum = parseInt(k, 10);
      const steam = steamOf(row);
      seen.set(`${clientNum}|${steam ?? ""}`, {
        client_num: clientNum,
        name: stripColors(decodeQlString(row.n)),
        team: String(row.t ?? ""),
        steam_id64: steam,
      });
    }
  };
  try {
    while (true) {
      const r = parser.parseOnePacket();
      if (r.done) break;
      parser.snapshots.length = 0;
      take();
    }
  } catch (err) {
    log("warning: multi-POV roster scan stopped early:", String(err.message || err));
  }
  take();
  return [...seen.values()];
}

// Publishes a multi-POV match: "<name>.dm_91" + "<name>.meta.json" (v2) +
// the replay sidecar, no .qlmatch. Order matters to the file-forwarder, which
// sends "<name>.dm_91" to qlmatch/ only while "<name>.meta.json" names it:
// the meta is written first, then the index and the demo are renamed (a
// rename keeps the capture's mtime, so the forwarder may pick the file up at
// once). With --out-dir the demo is copied there instead and the original
// stays. {match_id}.meta.json (v1, the Demos screen's label file) is still
// written, unless <name> is the match id itself (the two would share a name).
function publishMultiPov(args, entry, window) {
  const gs = entry.parser.gamestate;
  const mapName = args.map || gs.config.serverinfo?.mapname || "";
  const players = multiPovPlayers(entry.bytes);
  const identity = matchIdentity([entry], new Map());
  for (const w of identity.warnings) log("warning:", w);
  log(`multi-POV capture ${entry.base}: client_num ${entry.clientNum}, ${players.length} player(s), ` +
    `${players.filter((p) => p.steam_id64).length} with a steam id`);

  const ctx = nameContext(args, mapName, gs.config.serverinfo?.g_gametype || "", players, players.map((p) => p.name));
  const template = args.nameTemplate || "{match_id}_{map}";
  const outDir = args.outDir || args.dir;
  const inPlace = outDir === args.dir;
  let stem = renderName(template, ctx);
  const taken = (s) => existsSync(join(outDir, s + DM91)) && !(inPlace && s + DM91 === entry.base);
  if (taken(stem) && !stem.includes(args.matchId)) stem = `${stem}_${args.matchId}`;
  if (taken(stem)) fail(5, `match ${args.matchId}: ${join(outDir, stem + DM91)} already exists, not overwriting it`);
  const pubName = stem + DM91;
  const pubPath = join(outDir, pubName);
  const metaName = `${stem}.meta.json`;

  const meta = {
    format: "qlsm-demo-meta",
    version: 2,
    match_id: args.matchId,
    map: mapName,
    gametype: ctx.gametype,
    match_guid: identity.match_guid,
    duration_ms: durationMs(window),
    window,
    players,
    pack: pubName,
    written_at: new Date().toISOString(),
  };
  if (!writeJsonAtomic(outDir, metaName, meta)) fail(5, `match ${args.matchId}: cannot write ${metaName}`);

  const srcIndex = indexPathFor(entry.path);
  const pubIndex = indexPathFor(pubPath);
  try {
    if (inPlace) {
      if (srcIndex !== pubIndex && existsSync(srcIndex)) renameSync(srcIndex, pubIndex);
      if (entry.path !== pubPath) renameSync(entry.path, pubPath);
    } else {
      if (existsSync(srcIndex)) {
        mkdirSync(dirname(pubIndex), { recursive: true });
        copyFileSync(srcIndex, pubIndex);
      }
      copyFileSync(entry.path, pubPath);
    }
  } catch (err) {
    // Undo, so a re-run finds the capture where the engine left it.
    try { unlinkSync(join(outDir, metaName)); } catch { /* already gone */ }
    if (inPlace && srcIndex !== pubIndex && !existsSync(srcIndex) && existsSync(pubIndex)) {
      try { renameSync(pubIndex, srcIndex); } catch { /* left as is */ }
    }
    fail(5, `match ${args.matchId}: publishing ${pubPath} failed (${err.message || err})`);
  }
  log(`published ${pubPath} (multi-POV, ${statSync(pubPath).size} bytes, gametype ${ctx.gametype}), no .qlmatch`);

  if (stem !== args.matchId) {
    const pov = { file: inPlace ? pubName : entry.base, client_num: entry.clientNum, name: stripColors(entry.name) };
    writeMetaV1(args, {
      map: mapName,
      gametype: ctx.gametype,
      window,
      matchGuid: identity.match_guid,
      players: players.map((p) => ({ name: p.name, team: p.team, steam_id64: p.steam_id64 })),
      povs: [pov],
      packName: inPlace ? pubName : null,
    });
  }

  writeSidecar(pubPath, join(outDir, `${args.matchId}_${mapName}.replay.json.gz`));
}

// Filename template context. players: [{name, team}]; povNames: the players
// that have their own POV in the pack.
function nameContext(args, mapName, gametype, players, povNames) {
  const red = players.filter((p) => p.team === "1");
  const blue = players.filter((p) => p.team === "2");
  const names = (list) => list.map((p) => sanitizeToken(p.name)).filter(Boolean).join("-");
  const m = /^(\d{4})(\d{2})(\d{2})T(\d{6})Z$/.exec(args.matchId) || [];
  return {
    match_id: args.matchId,
    date: m.length ? `${m[1]}${m[2]}${m[3]}` : args.matchId,
    time: m.length ? m[4] : "",
    map: mapName,
    gametype: GAMETYPE_NAMES[parseInt(gametype, 10)] || (gametype ? `gt${gametype}` : "unknown"),
    players: names(players),
    pov_players: povNames.map((n) => sanitizeToken(n)).filter(Boolean).join("-"),
    total_players: players.length,
    red_count: red.length,
    blue_count: blue.length,
    red_players: names(red),
    blue_players: names(blue),
    teams: red.length || blue.length ? `${names(red) || "red"}_vs_${names(blue) || "blue"}` : names(players),
  };
}

// Replay sidecar: merge the N POVs into one deduplicated replay-v2 JSON
// ({match_id}_{map}.replay.json.gz next to the pack, never inside the zip
// - the .qlmatch contract forbids decoded dumps in the package). This is
// what !restore match (restore/qlmatch.py sidecar_path_for) and the
// dashboard's #/demo view read. Child process, not in-process: parsing
// every POV in full is the memory-heavy part this packer deliberately
// avoids, and a merge failure must not lose an already-written pack. A
// failure is logged (it lands in <match_id>.packer.log) but does not
// change the exit code - the sidecar is re-generatable by hand:
//   node qlmatch-to-replay.mjs <pack.qlmatch | published.dm_91> -o <sidecar>
function writeSidecar(inputPath, sidecarPath) {
  const sidecarScript = fileURLToPath(new URL("./qlmatch-to-replay.mjs", import.meta.url));
  const sc = spawnSync(process.execPath, [sidecarScript, inputPath, "-o", sidecarPath], {
    encoding: "utf8",
    timeout: SIDECAR_TIMEOUT_MS,
  });
  if (sc.error || sc.status !== 0) {
    const why = sc.error ? String(sc.error.message || sc.error) : `exit ${sc.status}: ${(sc.stderr || "").trim().slice(-500)}`;
    console.error(`packer: replay sidecar FAILED (${why}) — pack is intact, regenerate with qlmatch-to-replay.mjs`);
  } else {
    for (const line of (sc.stdout || "").trim().split("\n")) log("sidecar:", line);
  }
}

function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.rcloneIgnored) console.error("packer: --rclone-targets is ignored, delivery moved to the file-forwarder addon");
  if (!existsSync(args.dir) || !statSync(args.dir).isDirectory()) fail(5, "not a directory:", args.dir);

  const files = discoverPovFiles(args.dir, args.matchId);
  if (!files.length) fail(3, "no", `${args.matchId}_*${DM91}`, "files in", args.dir);
  log(`match ${args.matchId}: ${files.length} POV file(s) in ${args.dir}`);

  // Per-POV: bytes + paired C-written index + parsed live identity.
  const entries = [];
  for (const path of files) {
    const bytes = readFileSync(path);
    const index = loadIndex(path);
    const parser = parseIdentity(bytes, index);
    const clientNum = Number.isInteger(index?.client_num) ? index.client_num : parser.gamestate.clientNum;
    // Name: this POV's own roster row for its client_num (players, then
    // spectators — a player who left before game_end only survives there),
    // else the sanitized name demos.c baked into the filename. livePlayerNames
    // is NOT used here: it keeps ghost entries for disconnected clients, and
    // on a slot-reuse capture that ghost belongs to a different player.
    const gs = parser.gamestate;
    const name = decodeQlString(
      gs.players?.[clientNum]?.n ||
      gs.spectators?.[clientNum]?.n ||
      nameFromBasename(basename(path), args.matchId, args.map || mapNameOf(parser) || "") ||
      String(clientNum));
    const guidFromGamestate = String(parser.gamestate.configstrings?.[CS_MATCH_GUID] ?? "");
    entries.push({ path, base: basename(path), bytes, index, parser, clientNum, name, guidFromGamestate });
    log(
      `  ${basename(path)}: client_num ${clientNum} "${stripColors(name)}"` +
        (index
          ? ` window [${index.first_server_time},${index.last_server_time}] ${index.snapshots.length} snaps`
          : " (no index)") +
        (parser.errors.length ? ` parse_errors=${parser.errors.length}` : ""),
    );
  }

  const win = computeWindow(entries, args.minWindowMs);
  if (win.error) fail(2, `match ${args.matchId}:`, win.error, "— raw POV files left in place");
  const window = win.window;
  log(`window [${window.start_server_time},${window.end_server_time}] game_start ${window.game_start_server_time}`);

  const multi = multiPovEntry(entries);
  if (multi) {
    publishMultiPov(args, multi, window);
    process.exit(0);
  }

  // Roster across every POV (a player without their own POV still shows up
  // in the others' gamestates): clientNum -> {name, team}. First POV that
  // knows a client wins; a later POV only fills in a missing team.
  const roster = new Map();
  let gametype = "";
  let mapName = args.map || "";
  for (const e of entries) {
    const gs = e.parser.gamestate;
    if (!gametype) gametype = gs.config.serverinfo?.g_gametype || "";
    if (!mapName) mapName = gs.config.serverinfo?.mapname || "";
    for (const [k, row] of Object.entries(gs.players || {})) {
      const cn = parseInt(k, 10);
      if (!roster.has(cn)) roster.set(cn, { name: decodeQlString(row.n) || String(cn), team: row.t ?? "" });
      else if (!roster.get(cn).team && row.t) roster.get(cn).team = row.t;
    }
  }

  // Manifest per the .qlmatch contract. pov_index is a stable per-file
  // ordinal (sorted by client_num, then first_server_time, then basename),
  // not the capture slot — one slot can yield several segments.
  entries.sort((a, b) =>
    a.clientNum - b.clientNum ||
    (a.index?.first_server_time ?? 2 ** 31) - (b.index?.first_server_time ?? 2 ** 31) ||
    a.base.localeCompare(b.base),
  );
  const demos = entries.map((e, i) => ({
    file: `demos/${e.base}`,
    pov_index: i,
    client_num: e.clientNum,
    name: e.name,
    index: e.index ? `index/${basename(indexPathFor(e.path))}` : null,
  }));
  const identity = matchIdentity(entries, roster);
  for (const w of identity.warnings) log("warning:", w);
  const manifest = {
    format: "ql-match",
    version: 2,
    match_id: args.matchId,
    ...(identity.match_guid ? { match_guid: identity.match_guid } : {}),
    map: mapName,
    gametype: String(gametype),
    index_framing: "with_header",
    window,
    players: identity.players,
    demos,
  };

  // Filename template context.
  const ctx = nameContext(args, mapName, gametype, [...roster.values()], entries.map((e) => e.name));
  const template = args.nameTemplate || "{match_id}_{map}";
  let outName = renderName(template, ctx) + ".qlmatch";
  const outDir = args.outDir || args.dir;
  let outPath = join(outDir, outName);
  if (existsSync(outPath) && !outName.includes(args.matchId)) {
    // A template without a unique stamp must not overwrite the previous match.
    outName = renderName(template, ctx) + "_" + args.matchId + ".qlmatch";
    outPath = join(outDir, outName);
  }

  const members = [{ name: "manifest.json", data: Buffer.from(JSON.stringify(manifest, null, 2) + "\n") }];
  for (const e of entries) {
    members.push({ name: `demos/${e.base}`, data: e.bytes });
    if (e.index) members.push({ name: `index/${basename(indexPathFor(e.path))}`, data: readFileSync(indexPathFor(e.path)) });
  }
  const partPath = outPath + ".part";
  writeFileSync(partPath, zipSync(members));
  renameSync(partPath, outPath);
  const size = statSync(outPath).size;
  log(`wrote ${outPath} (${entries.length} POV(s), ${size} bytes, gametype ${ctx.gametype})`);
  writeMatchMeta(args, { mapName, gametype: ctx.gametype, window, roster, entries, packName: outDir === args.dir ? outName : null, identity });

  writeSidecar(outPath, join(outDir, `${args.matchId}_${mapName}.replay.json.gz`));

  process.exit(0);
}

main();
