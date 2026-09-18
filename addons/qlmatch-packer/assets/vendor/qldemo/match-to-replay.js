// Merges N per-POV .dm_91 demos from one .qlmatch pack into a single
// deduplicated replay-v2 feed ({ meta, events }), the same schema
// demoToReplay() produces for a single demo. Consumed identically downstream
// by replayForOverlay()/archiveFromDemoReplay() - see
// docs/superpowers/specs/2026-08-29-qlmatch-unified-replay-feed-research.md
// for why this merges at the replay-event level (reusing demoToReplay's own
// per-POV vitals/item-tracker/LG-beam logic, which already can't be shared
// meaningfully across POVs) instead of UDT-merging the raw .dm_91 files
// (rejected: no cross-POV vitals, "corpses win" over live players, item
// pickups never merged - see the research doc section 6).

import { QLDemoParser } from "./demo-parser.js?v=20260901d";
import { demoToReplay } from "./demo-to-replay.js?v=20260917a";
import { liveClientNumFromParser, liveSnapRange } from "./identity.js?v=20260829a";
import { itemFamilyKey, loadMapPickupTable, normalizeMapKey } from "./map-item-resolve.js?v=20260901d";
import { unpackQlMatch } from "./qlmatch-pack.js?v=20260829a";

/** Bump when the merge algorithm changes so a stale sidecar can be detected and regenerated. */
export const MATCH_REPLAY_GENERATOR_VERSION = 11;

// All POVs of one match sit on the same 25 ms server snapshot grid (sv_fps
// 40) - see research doc section 4.
const GAME_TICK_MS = 25;
// A player's own-POV position row is carried forward across small recording
// gaps (segment boundary, brief packet loss) but dropped once stale, so a POV
// that stops recording (disconnect, outlier POV trimmed early) doesn't leave
// a zombie player frozen on the map for the rest of the merged replay.
const POSITION_STALE_MS = 500;
const DEATH_WINDOW_MS = 50;
const PICKUP_WINDOW_MS = 2000;
// Radius for "same physical pickup spot" across POVs/sources (entity origin
// vs map-spawn origin vs picker position differ by droptofloor/touch range).
const PICKUP_MATCH_DIST = 128;
const IMPACT_WINDOW_MS = 60;
// Impact/beam positions differ slightly per POV (aim-synthesized LG beam,
// extrapolated entity position) - round to a coarse grid before keying so
// near-identical observations of the same event still dedup.
const IMPACT_POS_GRID = 48;
const PROJECTILE_STALE_MS = 200;

function roundToGrid(ms, grid = GAME_TICK_MS) {
  return Math.round(ms / grid) * grid;
}

function median(nums) {
  const s = nums.filter((n) => Number.isFinite(n)).sort((a, b) => a - b);
  if (!s.length) return null;
  return s[Math.floor(s.length / 2)];
}

function itemKey(classname, x, y, z) {
  return classname + "@" + Math.round(x) + "," + Math.round(y) + "," + Math.round(z);
}

function posGridKey(x, y, z, grid = IMPACT_POS_GRID) {
  return Math.round(x / grid) + "," + Math.round(y / grid) + "," + Math.round(z / grid);
}

/** Parse every POV .dm_91 in a .qlmatch buffer with the canonical parser. */
export async function parsePovsFromQlMatch(bytesLike) {
  const pack = await unpackQlMatch(bytesLike);
  const povs = pack.demos.map((d) => {
    const parser = new QLDemoParser(d.bytes);
    parser.parseAll();
    // Filename pov_index/client_num and the file's own (possibly leftover)
    // gamestate.clientNum are not reliable player identity - same reasoning
    // as demo-editor/lib/match-set.js's povFromParser().
    const clientNum = liveClientNumFromParser(parser);
    // The pack's .dm_91 bytes can still carry a leftover-occupant prefix even
    // when the manifest/index metadata itself was already trimmed (seen on
    // the real 8-POV OVERKILL sample: 5 of 8 POVs have a raw first snapshot
    // *after* their raw last snapshot - a previous recorder-slot occupant).
    // parser.snapshots[0].serverTime is not safe to use as this POV's
    // recording start; liveSnapRange's reset-aware first live snapshot is.
    const liveRange = liveSnapRange(d.index, parser);
    return {
      fileName: d.fileName,
      name: d.name,
      povIndex: d.povIndex,
      clientNum,
      liveFirstServerTime: liveRange.first,
      parser,
    };
  });
  return { pack, povs };
}

/** povs: [{ clientNum, parser, fileName? }] already-parsed QLDemoParser instances. */
export function matchPovsToReplay(povs, options = {}) {
  if (!povs || !povs.length) throw new Error("matchPovsToReplay: no POVs");
  const map = normalizeMapKey(options.mapOverride || povs[0].parser.mapName());
  const mapTable = options.mapTable ?? loadMapPickupTable(map);
  const povReplays = povs.map((p) => ({
    clientNum: p.clientNum,
    fileName: p.fileName,
    liveFirstServerTime: p.liveFirstServerTime,
    replay: demoToReplay(p.parser, { mapTable, povClientNum: p.clientNum, includePickups: true }),
  }));
  return mergeReplays(povReplays);
}

export async function matchBufferToReplay(bytesLike, options = {}) {
  const { povs } = await parsePovsFromQlMatch(bytesLike);
  return matchPovsToReplay(povs, options);
}

/**
 * Memory-lean variant of matchBufferToReplay for Node CLIs: POVs are parsed
 * and folded into per-POV replays ONE AT A TIME, each parser's decoded
 * snapshot list released before the next demo is opened. parseAll() of a
 * full match holds every decoded snapshot (hundreds of MB per POV), so
 * parsing all N POVs of an 8-player pack at once - what
 * parsePovsFromQlMatch does - blows Node's default ~4 GB heap; per-POV
 * replays are tiny by comparison. Output is identical to
 * matchPovsToReplay on the same pack (same per-POV inputs to
 * mergeReplays, in the same order).
 * options.loadMapTable(mapKey, gametype) lets a Node caller supply the
 * pickup table lazily once the first POV reveals the map name and gametype
 * (see map-item-resolve.node.js's loadMapPickupTableFromDisk) - gametype
 * matters because some map spawns are gametype-conditional (e.g. bloodrun
 * has a duel-only quad and TDM/FFA-only ammo packs at the same spots).
 */
export async function matchBufferToReplaySequential(bytesLike, options = {}) {
  const pack = await unpackQlMatch(bytesLike);
  let mapTable = options.mapTable;
  const povReplays = [];
  for (const d of pack.demos) {
    let parser = new QLDemoParser(d.bytes);
    parser.parseAll();
    if (mapTable == null) {
      const map = normalizeMapKey(options.mapOverride || parser.mapName());
      const gametype = parser.gametype();
      mapTable = options.loadMapTable ? options.loadMapTable(map, gametype) : loadMapPickupTable(map);
    }
    const clientNum = liveClientNumFromParser(parser);
    const liveRange = liveSnapRange(d.index, parser);
    povReplays.push({
      clientNum,
      fileName: d.fileName,
      liveFirstServerTime: liveRange.first,
      replay: demoToReplay(parser, { mapTable, povClientNum: clientNum, includePickups: true }),
    });
    parser = null;
    d.bytes = null;
  }
  return mergeReplays(povReplays);
}

// ---------------------------------------------------------------------------
// Core merge: povReplays = [{ clientNum, replay: <demoToReplay() output> }]
// ---------------------------------------------------------------------------

export function mergeReplays(povReplays) {
  const valid = (povReplays || []).filter((p) => p?.replay?.meta && p.replay.events);
  if (!valid.length) throw new Error("mergeReplays: no usable POV replays");

  const mergedFightStartMs = median(valid.map((p) => p.replay.meta.match_start_server_time)) ?? 0;
  // Prefer each POV's reset-aware live-window start (liveFirstServerTime, set
  // by parsePovsFromQlMatch via identity.js's liveSnapRange) over
  // demoToReplay's own recording_start_server_time, which is just
  // parser.snapshots[0].serverTime and can still be a leftover-occupant
  // prefix's timestamp (see parsePovsFromQlMatch's liveRange comment) - a
  // single contaminated POV would otherwise be able to drag the merged
  // countdown_lead_ms/duration_wall_ms/t clock to a nonsense value via Math.min.
  const recordingStarts = valid
    .map((p) => (Number.isFinite(p.liveFirstServerTime) ? p.liveFirstServerTime : p.replay.meta.recording_start_server_time))
    .filter(Number.isFinite);
  const mergedRecordingStartMs = recordingStarts.length ? Math.min(...recordingStarts) : mergedFightStartMs;
  const mergedCountdownLeadMs = Math.max(0, mergedFightStartMs - mergedRecordingStartMs);

  // Normalize every POV's own game_time_ms (relative to that POV's own
  // fightStartMs) onto the shared axis. In practice offsetMs is 0 for every
  // POV of a real match (research doc section 4) - this just makes the merge
  // robust to a POV whose fight-start detection landed one snapshot off.
  for (const p of valid) {
    const povFightStart = p.replay.meta.match_start_server_time;
    p.offsetMs = Number.isFinite(povFightStart) ? povFightStart - mergedFightStartMs : 0;
  }

  const map = valid[0].replay.meta.map_name;
  const gametype = valid[0].replay.meta.gametype;
  const roster = mergeRoster(valid);

  const events = [];
  events.push(...mergeLifecycleEvents(mergedCountdownLeadMs, map, gametype));
  events.push(...mergePositions(valid, map, gametype));
  const deaths = mergeDeaths(valid);
  events.push(...deaths.events);
  events.push(...mergePickups(valid));
  events.push(...mergeDrops(valid));
  const projectiles = mergeProjectiles(valid);
  events.push(...projectiles.events);
  const impacts = mergeImpacts(valid);
  events.push(...impacts.events);
  const beams = mergeBeams(valid);
  events.push(...beams.events);

  // t is the merged-feed "wall clock": 0 at the earliest POV's recording
  // start, same relationship demoToReplay() uses per-POV (t = game_time_ms +
  // countdownLeadMs), just anchored to the merged clock instead of one file's.
  for (const ev of events) ev.t = ev.game_time_ms + mergedCountdownLeadMs;
  events.sort((a, b) => a.game_time_ms - b.game_time_ms || eventTypeRank(a.event) - eventTypeRank(b.event));

  const maxGameTimeMs = events.length ? Math.max(...events.map((e) => e.game_time_ms)) : 0;
  const errors = valid.flatMap((p) =>
    (p.replay.meta.errors || []).map((e) => "[pov " + p.clientNum + "] " + e),
  );

  return {
    meta: {
      map_name: map,
      gametype,
      source: "qlmatch",
      format: "json",
      schema: "replay-v2",
      generator_version: MATCH_REPLAY_GENERATOR_VERSION,
      pov_client_num: null,
      pov_count: valid.length,
      povs: valid.map((p) => ({ clientNum: p.clientNum, fileName: p.fileName || null })),
      roster,
      snapshot_count: valid.reduce((n, p) => n + (p.replay.meta.snapshot_count || 0), 0),
      match_start_server_time: mergedFightStartMs,
      recording_start_server_time: mergedRecordingStartMs,
      countdown_lead_ms: mergedCountdownLeadMs,
      duration_wall_ms: maxGameTimeMs + mergedCountdownLeadMs,
      score_updates: deriveScoreUpdatesFromDeaths(deaths.events, roster),
      player_count: roster.length,
      projectile_frames: projectiles.frames,
      impact_frames: impacts.frames,
      beam_frames: beams.frames,
      death_events: deaths.events.length,
      errors,
      seen_items: mergeSeenItems(valid),
    },
    events,
  };
}

const EVENT_TYPE_RANK = {
  countdown_start: 0,
  match_start: 1,
  positions: 2,
  death: 3,
  pickup: 4,
  item_drop: 5,
  projectiles: 6,
  impacts: 7,
  beams: 8,
};

function eventTypeRank(event) {
  return EVENT_TYPE_RANK[event] ?? 9;
}

function mergeRoster(povs) {
  const byClient = new Map();
  for (const p of povs) {
    for (const row of p.replay.meta.roster || []) {
      if (row.clientNum == null) continue;
      const prev = byClient.get(row.clientNum);
      if (!prev || (!prev.name && row.name)) byClient.set(row.clientNum, row);
    }
  }
  return [...byClient.values()].sort((a, b) => a.clientNum - b.clientNum);
}

function mergeSeenItems(povs) {
  const seen = new Map();
  for (const p of povs) {
    for (const it of p.replay.meta.seen_items || []) {
      const key = itemKey(it.classname, it.x, it.y, it.z);
      if (!seen.has(key)) seen.set(key, it);
    }
  }
  return [...seen.values()];
}

function mergeLifecycleEvents(countdownLeadMs, map, gametype) {
  const events = [];
  if (countdownLeadMs > 0) {
    events.push({ event: "countdown_start", game_time_ms: -countdownLeadMs });
  }
  events.push({ event: "match_start", game_time_ms: 0, map_name: map, gametype });
  return events;
}

/**
 * Running per-client frag count derived from the already-merged, deduplicated
 * "death" events, instead of parsing the raw `scores_duel` server command
 * (demoToReplay's collectDuelScoreUpdates - still used for a single-POV
 * replay, a separate consumer this merge path doesn't touch). Confirmed by
 * direct demo inspection that `scores_duel`'s first two tokens - what that
 * function reads as "my score"/"opponent score" - are NOT a running score at
 * all: on a real bloodrun duel with several kills for both players, those
 * two tokens stayed at a constant "2 0" for the entire match. The real score
 * lives in the CS_SCORES1/CS_SCORES2 configstrings, but those are rank-based
 * (1st place / 2nd place), not tied to a fixed clientNum, so reading them
 * still needs a way to know who currently holds which rank - which the
 * merge already has for free, and more reliably, via its own death events.
 * A kill increments the killer's tally; a self-kill (killer===victim, or no
 * killer_clientNum on an environment death) decrements the victim's own
 * tally by 1, matching Quake's suicide penalty (confirmed against the same
 * demo: a player's real score dropped by exactly 1 after a self-rocket).
 */
function deriveScoreUpdatesFromDeaths(deathEvents, roster) {
  const clientNums = (roster || []).map((r) => r.clientNum).filter((cn) => cn != null);
  if (!clientNums.length) return [];
  const score = Object.fromEntries(clientNums.map((cn) => [cn, 0]));
  const sorted = [...(deathEvents || [])].sort((a, b) => a.game_time_ms - b.game_time_ms);
  const updates = [];
  for (const ev of sorted) {
    const victim = ev.victim_clientNum;
    const killer = ev.killer_clientNum;
    if (killer != null && killer !== victim && killer in score) {
      score[killer] += 1;
    } else if (victim != null && victim in score) {
      score[victim] -= 1;
    } else {
      continue;
    }
    updates.push({ gameTimeMs: ev.game_time_ms, wallT: ev.t, byClient: { ...score } });
  }
  return updates;
}

// ---- positions: own-POV row wins per clientNum, other POVs fill gaps ----

function playerRowKey(p) {
  // Position-only used to dedup "nothing moved" - but health/armor/weapon
  // can change with position completely frozen (a paused player still
  // decays overheal, or gets restored/hurt), and a tick whose key matches
  // the previous one is dropped entirely (see mergePositions below). A
  // pause that holds position for many seconds while health keeps ticking
  // down was silently losing every one of those ticks except the first,
  // which then read back as a hole in positions - not a real gap in the
  // recording, just this key being too narrow to notice anything else
  // changed. Real bug found investigating a checkpoint that appeared to
  // have no data mid-pause when the raw per-POV streams had it throughout.
  return (
    p.clientNum + ":" + Math.round(p.x) + "," + Math.round(p.y) + "," + Math.round(p.z) + ":" +
    Math.round(p.yaw ?? 0) + ":" + (p.health ?? "") + "," + (p.armor ?? "") + ":" + (p.weapon ?? "")
  );
}

function mergePositions(povs, map, gametype) {
  const streams = povs.map((p) => ({
    povClientNum: p.clientNum,
    events: p.replay.events
      .filter((e) => e.event === "positions")
      .map((e) => ({ ...e, game_time_ms: e.game_time_ms + p.offsetMs }))
      .sort((a, b) => a.game_time_ms - b.game_time_ms),
  }));

  const tickSet = new Set();
  for (const s of streams) for (const e of s.events) tickSet.add(roundToGrid(e.game_time_ms));
  const ticks = [...tickSet].sort((a, b) => a - b);

  const idx = streams.map(() => 0);
  // Per source POV: clientNum -> last row observed + the tick it was seen at.
  const lastRowByStream = streams.map(() => new Map());

  const events = [];
  let lastKey = "";
  for (const tick of ticks) {
    streams.forEach((s, si) => {
      while (idx[si] < s.events.length && roundToGrid(s.events[idx[si]].game_time_ms) <= tick) {
        const ev = s.events[idx[si]];
        for (const row of ev.players || []) lastRowByStream[si].set(row.clientNum, { row, lastSeenTick: tick });
        idx[si]++;
      }
    });

    const byClient = new Map();
    for (let si = 0; si < streams.length; si++) {
      const povCn = streams[si].povClientNum;
      for (const [cn, rec] of lastRowByStream[si]) {
        if (tick - rec.lastSeenTick > POSITION_STALE_MS) continue;
        const isOwn = cn === povCn;
        const existing = byClient.get(cn);
        // Own-POV row (accurate health/armor/yaw from playerState) always
        // wins over an entity-derived row from someone else's POV - see
        // withCarriedVitals()/playerRowFromEntity() in demo-to-replay.js.
        if (!existing || (isOwn && !existing.own)) byClient.set(cn, { row: rec.row, own: isOwn });
      }
    }
    if (!byClient.size) continue;

    const players = [...byClient.values()].map((v) => v.row).sort((a, b) => a.clientNum - b.clientNum);
    const key = players.map(playerRowKey).join("|");
    if (key === lastKey) continue;
    lastKey = key;
    // map_name/gametype on every frame, not just the one-time match_start
    // event, matching demoToReplay()'s own per-frame shape - the map
    // widget (map-spawns.js's MapSpawns.onMapPayload) only updates its
    // remembered gametype when a payload actually carries one, and a
    // replay seek can dispatch a "positions" frame as the first payload
    // for a match without match_start ever having been replayed first.
    // Real bug this fixes: a duel replay's gametype-conditional map items
    // (e.g. bloodrun's TDM-only ammo packs) stayed visible because the
    // widget's own gametype was never initialized in that dispatch order.
    events.push({ event: "positions", game_time_ms: tick, map_name: map, gametype, players });
  }
  return events;
}

// ---- death: dedup broadcast EV_OBITUARY seen by every POV ----

function mergeDeaths(povs) {
  const all = [];
  for (const p of povs) {
    for (const ev of p.replay.events) {
      if (ev.event !== "death") continue;
      all.push({ ...ev, game_time_ms: ev.game_time_ms + p.offsetMs, _povClientNum: p.clientNum });
    }
  }
  all.sort((a, b) => a.game_time_ms - b.game_time_ms);

  const used = new Array(all.length).fill(false);
  const events = [];
  for (let i = 0; i < all.length; i++) {
    if (used[i]) continue;
    const base = all[i];
    used[i] = true;
    const cluster = [base];
    for (let j = i + 1; j < all.length; j++) {
      if (used[j]) continue;
      const cand = all[j];
      if (cand.game_time_ms - base.game_time_ms > DEATH_WINDOW_MS) break;
      if (cand.victim_clientNum !== base.victim_clientNum) continue;
      if (cand.killer_clientNum !== base.killer_clientNum) continue;
      if (cand.weapon !== base.weapon) continue;
      cluster.push(cand);
      used[j] = true;
    }
    // Prefer the victim's own POV recording - most accurate position of the
    // victim at the moment of death (own playerState, not extrapolated entity).
    const winner = cluster.find((c) => c._povClientNum === c.victim_clientNum) || cluster[0];
    const { _povClientNum, ...clean } = winner;
    events.push(clean);
  }
  return { events };
}

// ---- pickup: union across POVs (PVS coverage grows with more POVs) ----

function mergePickups(povs) {
  const all = [];
  for (const p of povs) {
    for (const ev of p.replay.events) {
      if (ev.event !== "pickup") continue;
      all.push({ ...ev, game_time_ms: ev.game_time_ms + p.offsetMs, _povClientNum: p.clientNum });
    }
  }
  all.sort((a, b) => a.game_time_ms - b.game_time_ms);

  const used = new Array(all.length).fill(false);
  const events = [];
  for (let i = 0; i < all.length; i++) {
    if (used[i]) continue;
    const base = all[i];
    used[i] = true;
    // Same physical pickup: normally the exact classname@x,y,z key (all
    // registry/entity-derived observations of one spot share server
    // coords, and e.g. the 3 shards of an armor-shard group are distinct
    // spots only a few dozen units apart - a radius alone would wrongly
    // fuse them). A ps-event pickup that missed the item registry
    // (approx_pos) carries the picker's position and bg_itemlist canon
    // naming instead, so only THOSE fall back to family + radius matching
    // (see itemFamilyKey).
    const key = itemKey(base.item, base.x, base.y, base.z);
    const family = itemFamilyKey(base.item);
    const cluster = [base];
    for (let j = i + 1; j < all.length; j++) {
      if (used[j]) continue;
      const cand = all[j];
      if (cand.game_time_ms - base.game_time_ms > PICKUP_WINDOW_MS) break;
      if (cand.action !== base.action) continue;
      const exact = itemKey(cand.item, cand.x, cand.y, cand.z) === key;
      const fuzzy =
        (cand.approx_pos || base.approx_pos) &&
        itemFamilyKey(cand.item) === family &&
        Math.hypot(cand.x - base.x, cand.y - base.y, cand.z - base.z) <= PICKUP_MATCH_DIST;
      if (!exact && !fuzzy) continue;
      cluster.push(cand);
      used[j] = true;
    }
    let winner = cluster[0];
    if (base.action === "pickup") {
      // Prefer an exact, non-heuristic pickup (source "ps" - the picker's
      // own playerState ring - or "entity" - the same broadcast event seen
      // on the picker's entity by another POV in PVS, see EV_ITEM_PICKUP
      // comment in demo-to-replay.js; "ps" wins between the two when both
      // exist since it carries the picker's own exact ps.origin rather than
      // an extrapolated entity position), then the picker's own POV
      // (nickname/clientNum resolved from its own roster view, not guessed
      // from "nearest visible player"), then whoever saw it first.
      winner =
        cluster.find((c) => c.source === "ps") ||
        cluster.find((c) => c.source === "entity") ||
        cluster.find((c) => c._povClientNum === c.clientNum) ||
        cluster[0];
    }
    const { _povClientNum, ...clean } = winner;
    events.push(clean);
  }
  return events;
}

// ---- death drops: union across POVs, one lifetime per physical drop ----
//
// Each POV only sees a drop while it is in that POV's PVS, so the same weapon
// lying on the floor shows up as a "drop" in one file and, seconds later, as
// a "drop" again in the other - or as a "gone" in only one of them. Merging
// on the resting spot collapses those into one lifetime: earliest sighting
// wins as the drop time (closest to when the player actually died), and a
// "gone" is only believed if no POV saw the item still there afterwards.
const DROP_SPOT_GRID = 16;
// Two drops of the same weapon on the same spot inside this window are the
// same physical drop seen by different POVs, not two deaths in a row.
const DROP_MERGE_WINDOW_MS = 30000;

function dropSpotKey(ev) {
  return [
    ev.item_id,
    Math.round(Number(ev.x) / DROP_SPOT_GRID),
    Math.round(Number(ev.y) / DROP_SPOT_GRID),
    Math.round(Number(ev.z) / DROP_SPOT_GRID),
  ].join("|");
}

function mergeDrops(povs) {
  const all = [];
  for (const p of povs) {
    for (const ev of p.replay.events) {
      if (ev.event !== "item_drop") continue;
      all.push({
        ...ev,
        game_time_ms: ev.game_time_ms + p.offsetMs,
        drop_game_time_ms: (ev.drop_game_time_ms ?? ev.game_time_ms) + p.offsetMs,
      });
    }
  }
  all.sort((a, b) => a.game_time_ms - b.game_time_ms);

  // spot key -> list of {dropMs, lastSeenMs, goneMs, sample}
  const lifetimes = new Map();
  for (const ev of all) {
    const key = dropSpotKey(ev);
    const list = lifetimes.get(key) || [];
    let cur = list.length ? list[list.length - 1] : null;
    if (cur && ev.drop_game_time_ms - cur.dropMs > DROP_MERGE_WINDOW_MS) cur = null;
    if (!cur) {
      cur = { dropMs: ev.drop_game_time_ms, lastSeenMs: ev.game_time_ms, goneMs: null, sample: ev };
      list.push(cur);
      lifetimes.set(key, list);
    }
    cur.dropMs = Math.min(cur.dropMs, ev.drop_game_time_ms);
    if (ev.action === "gone") {
      // Only the last POV to still see it decides when it went away.
      cur.goneMs = cur.goneMs == null ? ev.game_time_ms : Math.max(cur.goneMs, ev.game_time_ms);
    } else {
      cur.lastSeenMs = Math.max(cur.lastSeenMs, ev.game_time_ms);
    }
  }

  const events = [];
  for (const list of lifetimes.values()) {
    for (const cur of list) {
      const sample = cur.sample;
      events.push({ ...sample, action: "drop", game_time_ms: cur.dropMs, drop_game_time_ms: cur.dropMs });
      // A POV that saw the item still lying there after another POV lost it
      // means it was never taken then - that "gone" was just PVS loss.
      if (cur.goneMs != null && cur.goneMs >= cur.lastSeenMs) {
        events.push({ ...sample, action: "gone", game_time_ms: cur.goneMs, drop_game_time_ms: cur.dropMs });
      }
    }
  }
  return events;
}

// ---- projectiles: dedup by server-authoritative entity id (eid) ----

function mergeProjectiles(povs) {
  const streams = povs.map((p) => ({
    events: p.replay.events
      .filter((e) => e.event === "projectiles")
      .map((e) => ({ ...e, game_time_ms: e.game_time_ms + p.offsetMs }))
      .sort((a, b) => a.game_time_ms - b.game_time_ms),
  }));

  const tickSet = new Set();
  for (const s of streams) for (const e of s.events) tickSet.add(roundToGrid(e.game_time_ms));
  const ticks = [...tickSet].sort((a, b) => a - b);

  const idx = streams.map(() => 0);
  const byEid = new Map();
  const events = [];
  let frames = 0;
  let hadAny = false;

  for (const tick of ticks) {
    streams.forEach((s, si) => {
      while (idx[si] < s.events.length && roundToGrid(s.events[idx[si]].game_time_ms) <= tick) {
        const seenThisFrame = new Set();
        for (const proj of s.events[idx[si]].projectiles || []) {
          byEid.set(proj.eid, { data: proj, lastSeenTick: tick, streamIdx: si });
          seenThisFrame.add(proj.eid);
        }
        // A stream's own frame (even an empty one) is authoritative for any
        // eid IT was the current source of: that POV's own demoToReplay()
        // already decided, via its own trailing-empty-frame logic, that the
        // projectile is gone (missile entity's eType/trajectory stopped
        // looking like a live projectile - see collectFxFromEntity). Acting
        // on that immediately, instead of only via the PROJECTILE_STALE_MS
        // timeout below, matters because the timeout can never fire if NO
        // stream produces any more ticks for a while (nothing else airborne
        // on the map) - real bug, confirmed on real production data: a
        // rocket froze on the map for 35 real seconds because the next tick
        // in either stream didn't arrive until then, so the stale eid just
        // sat in byEid, never re-evaluated, and got included in every
        // (nonexistent) frame in between as "still there".
        for (const [eid, rec] of byEid) {
          if (rec.streamIdx === si && !seenThisFrame.has(eid)) byEid.delete(eid);
        }
        idx[si]++;
      }
    });
    for (const [eid, rec] of byEid) {
      if (tick - rec.lastSeenTick > PROJECTILE_STALE_MS) byEid.delete(eid);
    }
    const projectiles = [...byEid.values()].map((r) => r.data);
    // Emit one empty frame right after the last projectile disappears, same
    // as demoToReplay(), so the overlay's tracked eid actually gets pruned.
    if (projectiles.length || hadAny) {
      frames++;
      events.push({ event: "projectiles", game_time_ms: tick, projectiles });
    }
    hadAny = projectiles.length > 0;
  }
  return { events, frames };
}

// ---- impacts / beams: dedup transient per-tick effects ----

function preferOwnPov(cluster) {
  return cluster.find((c) => c.item.clientNum != null && c.item.clientNum === c._povClientNum);
}

function mergeFrameItems(povs, eventName, itemsField, keyFn, windowMs) {
  const all = [];
  for (const p of povs) {
    for (const ev of p.replay.events) {
      if (ev.event !== eventName) continue;
      const gtm = ev.game_time_ms + p.offsetMs;
      for (const item of ev[itemsField] || []) all.push({ item, game_time_ms: gtm, _povClientNum: p.clientNum });
    }
  }
  all.sort((a, b) => a.game_time_ms - b.game_time_ms);

  const used = new Array(all.length).fill(false);
  const deduped = [];
  for (let i = 0; i < all.length; i++) {
    if (used[i]) continue;
    const base = all[i];
    used[i] = true;
    const baseKey = keyFn(base.item);
    const cluster = [base];
    for (let j = i + 1; j < all.length; j++) {
      if (used[j]) continue;
      const cand = all[j];
      if (cand.game_time_ms - base.game_time_ms > windowMs) break;
      if (keyFn(cand.item) !== baseKey) continue;
      cluster.push(cand);
      used[j] = true;
    }
    const winner = preferOwnPov(cluster) || cluster[0];
    deduped.push({ game_time_ms: winner.game_time_ms, item: winner.item });
  }
  return deduped;
}

function groupIntoFrames(deduped, eventName, itemsField) {
  const byTick = new Map();
  for (const d of deduped) {
    const tick = roundToGrid(d.game_time_ms);
    if (!byTick.has(tick)) byTick.set(tick, []);
    byTick.get(tick).push(d.item);
  }
  const ticks = [...byTick.keys()].sort((a, b) => a - b);
  return ticks.map((tick) => ({ event: eventName, game_time_ms: tick, [itemsField]: byTick.get(tick) }));
}

function mergeImpacts(povs) {
  const deduped = mergeFrameItems(
    povs,
    "impacts",
    "impacts",
    (it) => it.kind + "|" + (it.clientNum ?? "") + "|" + posGridKey(it.x, it.y, it.z),
    IMPACT_WINDOW_MS,
  );
  const events = groupIntoFrames(deduped, "impacts", "impacts");
  return { events, frames: events.length };
}

function mergeBeams(povs) {
  // Keyed on shooter origin (x0,y0,z0), not the endpoint - LG beam endpoints
  // vary per POV with aim-synthesis/hit-detection precision (see
  // lgBeamHitDistance() in demo-to-replay.js) while the shooter's own
  // position at that tick is effectively identical everywhere it's observed.
  const deduped = mergeFrameItems(
    povs,
    "beams",
    "beams",
    (it) => it.clientNum + "|" + it.weapon_slug + "|" + posGridKey(it.x0, it.y0, it.z0),
    IMPACT_WINDOW_MS,
  );
  const events = groupIntoFrames(deduped, "beams", "beams");
  return { events, frames: events.length };
}
