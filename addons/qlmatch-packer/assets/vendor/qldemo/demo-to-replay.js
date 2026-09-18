import {
  ET_ITEM,
  ET_MISSILE,
  ET_PLAYER,
  MAX_CLIENTS,
  QL91_ITEM_CLASSNAMES,
  STAT_ARMOR,
  STAT_HEALTH,
  STAT_HOLDABLE_ITEM,
  STAT_WEAPONS,
  TEAM_SPECTATOR,
} from "./constants.js";
import {
  EF_DEAD,
  EF_FIRING,
  EF_NODRAW,
  TR_GRAVITY,
  TR_STATIONARY,
  entityOriginAt,
  entityVelocity,
  isSaneWorldOrigin,
  playerStateToEntityState,
} from "./entity-state.js?v=20260712b";
import {
  ET_EVENTS,
  ET_GENERAL,
  EV_GLOBAL_ITEM_PICKUP,
  EV_ITEM_PICKUP,
  EV_OBITUARY,
  EV_RAIL_TRAIL,
  PROJECTILE_WEAPONS,
  WP_GRENADE,
  WP_PLASMA,
  WP_ROCKET,
  WP_SHAFT,
  eventId,
  entityEventId,
  isBulletImpactEvent,
  isMissileImpactEvent,
  meanOfDeathWeaponSlug,
} from "./entity-events.js?v=20260830b";
import { parseMatchClock } from "./demo-match-clock.js?v=20260712b";
import {
  itemFamilyKey,
  loadMapPickupTable,
  normalizeMapKey,
  resolvePickupRowAt,
} from "./map-item-resolve.js?v=20260901a";
import { powerupNamesFromEntityMask } from "./powerups.js?v=20260712b";
import { weaponSlug } from "./weapons.js?v=20260712b";

/** Emit positions at most every N ms (demo has ~25 ms snapshots). */
const POSITION_EMIT_MS = 50;

// Item pickups arrive as EV_ITEM_PICKUP / EV_GLOBAL_ITEM_PICKUP
// (entity_event_t, wolfcamql bg_public.h) via three independent, all
// server-authoritative wire paths - unlike the item-left-PVS disappearance
// heuristic below, none of them guesses the picker by proximity:
// 1. The picker's own playerState - a 2-slot ring (ps.events/ps.eventParms)
//    advanced by ps.eventSequence, consumed exactly like cgame's
//    CG_CheckPlayerstateEvents does. Only ever present in the picker's OWN
//    POV demo (chase-cam/other-POV entities never carry playerState).
// 2. The picker's own playerState again, via ps.externalEvent/
//    ps.externalEventParm - a single-value field, NOT part of the ring
//    above, that the real client checks first and separately (same
//    cg_playerstate.c: `if (ps->externalEvent != ops->externalEvent)`
//    runs before the ring loop). Confirmed empirically on real production
//    demos that at least mega health and yellow armor pickups can land
//    ONLY here with nothing in the ring at all - this is why the actual
//    game client always shows every pickup correctly scrubbing a demo, and
//    why relying on the ring alone silently drops some real pickups.
// 3. The picker's ET_PLAYER entityState (.event/.eventParm) - the same
//    G_AddEvent() call that seeds path 1/2 above also stamps the picker's
//    own networked entity, so every OTHER POV that has the picker in PVS at
//    pickup time observes it too (see the entity loop below). This is what
//    lets a pickup by a player with no POV demo of their own still resolve
//    exactly instead of falling back to the disappearance heuristic.
// All three resolve to the same bg_itemlist item index in the parm.
const PS_EVENT_BITS = 0x300;
const MAX_PS_EVENTS = 2;
// The pickup event fires the same server frame the player touches the item,
// so ps.origin is within touch range of the item spawn; the radius allows
// for one snapshot of fast movement and the item's droptofloor z offset.
const PS_PICKUP_MATCH_RADIUS = 128;

const ITEM_RESPAWN_SEC = {
  item_health_mega: 35,
  weapon_: 5,
  item_armor: 25,
  item_health: 35,
};

function respawnSec(classname) {
  const cn = String(classname || "");
  if (cn === "item_health_mega") return 35;
  if (cn.startsWith("weapon_")) return 5;
  // Ammo boxes (ammo_rockets, ammo_pack, ...) respawn on their own, much
  // slower timer, not the parent weapon's 5s - see AMMO_RESPAWN_SEC_DEFAULT
  // in map-spawns.js (the live map widget's own, already-correct value).
  if (cn.startsWith("ammo_")) return 40;
  if (cn.startsWith("item_armor")) return 25;
  if (cn.startsWith("item_powerup")) return 35;
  if (cn.startsWith("item_")) return 35;
  return 35;
}

function itemKey(classname, x, y, z) {
  return classname + "@" + Math.round(x) + "," + Math.round(y) + "," + Math.round(z);
}

function round1(v) {
  return Math.round(Number(v || 0) * 10) / 10;
}

/** Q3 playerState / entity apos: viewangles[1] and apos.trBase[1] are yaw degrees. */
function yawFromViewangles(viewangles) {
  const y = Number(viewangles?.[1]);
  if (!Number.isFinite(y)) return null;
  return round1(y);
}

function yawFromEntity(ent) {
  const y = Number(ent?.apos?.trBase?.[1]);
  if (!Number.isFinite(y)) return null;
  return round1(y);
}

// LG has no dedicated network beam (unlike rail's EV_RAIL_TRAIL) and the
// bullet-hit temp entities that could mark its wall impact carry no usable
// weapon/shooter field in this protocol (verified empirically: always 0,
// matching the same `es.weapon` field the real UDT viewer keys shaft-impact
// matching off - so it's a wire-format gap, not a parser bug on our side).
// Draw the beam along the shooter's aim direction like UDT's own fallback
// does, but clip it to whichever live player it geometrically passes closest
// to (lgBeamHitDistance) instead of always drawing the full LG_BEAM_LENGTH -
// a beam that visibly stops on the opponent it's hitting matches what you'd
// actually see watching the demo, a straight line through them doesn't.
const LG_BEAM_LENGTH = 768;
const LG_HIT_RADIUS = 32;

function lgAimDir(pitchDeg, yawDeg) {
  const yawRad = (Number(yawDeg) || 0) * (Math.PI / 180);
  const pitchRad = (Number(pitchDeg) || 0) * (Math.PI / 180);
  const cp = Math.cos(pitchRad);
  return [cp * Math.cos(yawRad), cp * Math.sin(yawRad), -Math.sin(pitchRad)];
}

/** Closest along-ray distance (0..LG_BEAM_LENGTH) to a live player within LG_HIT_RADIUS of the aim ray, or null. */
function lgBeamHitDistance(x, y, z, fx, fy, fz, playersByCn, shooterClientNum) {
  let best = null;
  for (const [cn, p] of playersByCn) {
    if (cn === shooterClientNum || p.alive === false) continue;
    const dx = p.x - x;
    const dy = p.y - y;
    const dz = p.z - z;
    const t = dx * fx + dy * fy + dz * fz;
    if (t < 0 || t > LG_BEAM_LENGTH || (best != null && t > best)) continue;
    const perp = Math.hypot(dx - fx * t, dy - fy * t, dz - fz * t);
    if (perp <= LG_HIT_RADIUS) best = t;
  }
  return best;
}

function lgBeamEndpoint(x, y, z, fx, fy, fz, length) {
  return [round1(x + fx * length), round1(y + fy * length), round1(z + fz * length)];
}

function saneVital(value) {
  const n = Number(value);
  if (!Number.isFinite(n) || n < 0 || n >= 500) return null;
  return Math.round(n);
}

function withCarriedVitals(row, clientNum, lastVitals, ps) {
  const prev = lastVitals.get(clientNum) || { alive: true };
  const h = ps ? saneVital(ps.stats?.[STAT_HEALTH]) : null;
  const a = ps ? saneVital(ps.stats?.[STAT_ARMOR]) : null;

  if (h != null && h > 0) {
    prev.health = h;
    prev.alive = true;
    if (a != null) prev.armor = a;
  } else if (h === 0 && prev.alive) {
    prev.health = 0;
    prev.alive = false;
  } else if (h === 0 && !prev.alive) {
    row.health = null;
    row.armor = null;
    row.alive = false;
    lastVitals.set(clientNum, prev);
    return row;
  }

  row.alive = prev.alive !== false;
  row.health = row.alive ? (prev.health ?? null) : null;
  row.armor = row.alive ? (prev.armor ?? null) : null;
  lastVitals.set(clientNum, {
    health: prev.health ?? null,
    armor: prev.armor ?? null,
    alive: prev.alive !== false,
  });
  return row;
}





function applyPovDeathFreeze(row, clientNum, ps, poseState) {
  const prev = poseState.get(clientNum) || { alive: true };
  const h = ps ? saneVital(ps.stats?.[STAT_HEALTH]) : null;
  const dead = h === 0;

  if (dead) {
    if (prev.x != null) {
      row.x = prev.x;
      row.y = prev.y;
      row.z = prev.z;
      row.yaw = prev.yaw ?? row.yaw;
    }
    row.alive = false;
    poseState.set(clientNum, { ...prev, alive: false });
    return row;
  }

  prev.x = row.x;
  prev.y = row.y;
  prev.z = row.z;
  prev.yaw = row.yaw;
  prev.alive = true;
  row.alive = true;
  poseState.set(clientNum, prev);
  return row;
}

/** UDT static item registry: pickup when item leaves POV visibility after being seen. */
class StaticItemTracker {
  constructor() {
    this.registry = new Map();
    this.state = new Map();
    this.seenPickups = new Set();
  }

  register(classname, x, y, z) {
    const key = itemKey(classname, x, y, z);
    if (!this.registry.has(key)) {
      this.registry.set(key, { key, classname, x, y, z });
      this.state.set(key, { wasVisible: false, missStreak: 0 });
    }
    return key;
  }

  markVisible(key) {
    const st = this.state.get(key) || { wasVisible: false, missStreak: 0 };
    st.wasVisible = true;
    st.missStreak = 0;
    this.state.set(key, st);
  }

  /**
   * Nearest registered item of the same naming family (itemFamilyKey) within
   * PS_PICKUP_MATCH_RADIUS of (x, y, z), or null. Used to snap a ps pickup
   * event onto the registry spot the PVS heuristic tracks, so both paths
   * name and place the same physical pickup identically.
   */
  nearestFamilyMatch(classname, x, y, z) {
    const family = itemFamilyKey(classname);
    let best = null;
    let bestD = PS_PICKUP_MATCH_RADIUS;
    for (const item of this.registry.values()) {
      if (itemFamilyKey(item.classname) !== family) continue;
      // An item awaiting respawn can't be the one just picked - lets a run
      // through a shard group resolve each of its 3 ps events to a
      // different shard instead of the same nearest one three times.
      if (this.seenPickups.has(item.key)) continue;
      const d = Math.hypot(item.x - x, item.y - y, item.z - z);
      if (d <= bestD) {
        bestD = d;
        best = item;
      }
    }
    return best;
  }

  /**
   * hasNearbyPlayer(x, y): item leaving PVS only means "picked up" if a tracked
   * player was actually close enough to touch it — otherwise it just scrolled
   * out of the POV's view (true for most of the map most of the time) and must
   * stay registered so a real pickup later isn't lost.
   *
   * Returns both pickups (item entity just disappeared from the snapshot next
   * to a player) and respawns (item entity just reappeared after a pickup was
   * recorded for it) — UDT's own viewer has no separate respawn-timer guess at
   * all, it just draws whatever's in the current snapshot; `respawns` lets the
   * overlay un-hide the marker on the exact frame the item actually comes back
   * instead of after a guessed `respawn_sec`.
   */
  collectPickups(visibleKeys, gameTimeMs, wallT, hasNearbyPlayer) {
    const pickups = [];
    const respawns = [];
    for (const [key, item] of this.registry) {
      if (visibleKeys.has(key)) {
        const st = this.state.get(key);
        if (!st?.wasVisible && this.seenPickups.has(key)) {
          this.seenPickups.delete(key);
          respawns.push({ item, gameTimeMs, wallT });
        }
        this.markVisible(key);
        continue;
      }
      const st = this.state.get(key);
      if (!st?.wasVisible) continue;
      if (!hasNearbyPlayer(item.x, item.y)) {
        st.wasVisible = false;
        st.missStreak = 0;
        this.state.set(key, st);
        continue;
      }
      if (this.seenPickups.has(key)) {
        st.wasVisible = false;
        this.state.set(key, st);
        continue;
      }
      this.seenPickups.add(key);
      st.wasVisible = false;
      st.missStreak = 0;
      this.state.set(key, st);
      pickups.push({ item, gameTimeMs, wallT });
    }
    return { pickups, respawns };
  }
}

// ---- death drops -----------------------------------------------------------
//
// When a player dies the engine tosses the weapon they were holding (plus any
// powerup) onto the floor as its own entity - LaunchItem() in baseq3
// g_items.c, which QL kept - and frees it again DROP_LIFETIME_MS later. It is
// a real part of the match state: the opponent can walk over the corpse and
// take the rail. It is NOT a map spawn, so it has no slot in the item table
// and none of the pickup/respawn machinery above can express it.
//
// On the wire a drop is an ET_ITEM whose modelindex2 is 1 - LaunchItem sets
// exactly that, and nothing that places a map item does. That flag, not a
// position or trajectory guess, is what separates the two here.
const DROP_LIFETIME_MS = 30000;
// Drops are tracked by where they came to rest, because the entity number is
// a recycled slot: the same number is a different drop ten seconds later, and
// one drop can leave and re-enter PVS under a number that was reused in
// between. This grid is coarse enough to absorb snapshot rounding and fine
// enough to keep two drops in the same room apart.
const DROP_SPOT_GRID = 16;

function dropSpotKey(itemId, x, y, z) {
  return [
    itemId,
    Math.round(x / DROP_SPOT_GRID),
    Math.round(y / DROP_SPOT_GRID),
    Math.round(z / DROP_SPOT_GRID),
  ].join("|");
}

class DroppedItemTracker {
  constructor() {
    this.live = new Map();
  }

  /**
   * Record a settled drop seen this snapshot. Returns the record when this is
   * the first sighting of a *new* drop (caller emits an event), else null.
   */
  see(itemId, x, y, z, gameTimeMs) {
    const key = dropSpotKey(itemId, x, y, z);
    const rec = this.live.get(key);
    // Nothing that has been gone longer than a drop can possibly live is the
    // same drop - it's a fresh one that happened to land on the same spot.
    if (rec && gameTimeMs - rec.lastSeen <= DROP_LIFETIME_MS) {
      rec.lastSeen = gameTimeMs;
      return null;
    }
    const fresh = { key, itemId, x, y, z, dropMs: gameTimeMs, lastSeen: gameTimeMs };
    this.live.set(key, fresh);
    return fresh;
  }

  /**
   * Drops that vanished this snapshot with a player standing on them, i.e.
   * taken rather than merely out of view. Same discipline as
   * StaticItemTracker.collectPickups: without the nearby-player test every
   * drop would "disappear" the moment the POV turned around. A drop that
   * simply timed out needs no event at all - its dropMs plus the fixed
   * lifetime already says when it went away.
   */
  collectTaken(visibleKeys, gameTimeMs, hasNearbyPlayer) {
    const taken = [];
    for (const [key, rec] of this.live) {
      if (visibleKeys.has(key)) continue;
      if (gameTimeMs - rec.lastSeen >= DROP_LIFETIME_MS) {
        this.live.delete(key);
        continue;
      }
      if (gameTimeMs <= rec.lastSeen) continue;
      if (!hasNearbyPlayer(rec.x, rec.y)) continue;
      this.live.delete(key);
      taken.push({ rec, gameTimeMs });
    }
    return taken;
  }
}

function dropEvent(action, rec, gameTimeMs, wallT) {
  return {
    t: wallT,
    event: "item_drop",
    action,
    item_id: rec.itemId,
    item: QL91_ITEM_CLASSNAMES[rec.itemId] || null,
    x: round1(rec.x),
    y: round1(rec.y),
    z: round1(rec.z),
    game_time_ms: gameTimeMs,
    drop_game_time_ms: rec.dropMs,
  };
}

/**
 * Resolve an exact (non-heuristic) pickup event's item classname/position:
 * snap to the PVS-heuristic's own registry spot when a same-family item is
 * within PS_PICKUP_MATCH_RADIUS, so both paths name and place the same
 * physical pickup identically (the merge's exact-key dedup then applies, and
 * the heuristic itself skips it via seenPickups - see StaticItemTracker
 * above); otherwise fall back to the map's own spawn table, then to the raw
 * event position. Shared by both the playerState-ring and entity-event
 * pickup paths below.
 */
function resolveExactPickupItem(canonical, x, y, z, staticItems, mapTable) {
  // canonical is always the event's own bg_itemlist name - server-authoritative
  // and precise (distinguishes e.g. ammo_rockets from weapon_rocketlauncher,
  // item_armor_combat from item_armor_jacket). match/spawn below are used
  // ONLY to snap the reported position onto a known spot (registry entry or
  // map-spawn row) - never to rename the pickup. nearestFamilyMatch()
  // deliberately collapses these distinctions (item_armor_jacket/_combat,
  // weapon_X/ammo_X, ...) to find "the same physical spot" across naming
  // conventions - using the MATCHED spot's own (collapsed) classname here
  // used to silently rename an exact pickup to that family's name. Real bug,
  // confirmed on bloodrun: an ammo_rockets touch got reported (and rendered)
  // as weapon_rocketlauncher, implying a fresh weapon spawn that never
  // happened. See also PICKUP_LABELS in overlay.js, which already expects
  // the raw canonical names (item_armor_jacket "GA", item_armor_combat "YA")
  // - not map-item-resolve.js's own CLASS_MAP output, which invented
  // "item_armor_yellow" as if jacket/combat were the same item; they aren't.
  const match = staticItems.nearestFamilyMatch(canonical, x, y, z);
  if (match) {
    staticItems.seenPickups.add(match.key);
    return { item: { classname: canonical, x: match.x, y: match.y, z: match.z }, approxPos: false };
  }
  const spawn = resolvePickupRowAt(mapTable, x, y, z, PS_PICKUP_MATCH_RADIUS);
  const item = spawn ? { classname: canonical, x: spawn.x, y: spawn.y, z: spawn.z } : { classname: canonical, x, y, z };
  return { item, approxPos: true };
}

function buildExactPickupEvent(wallT, gameTimeMs, item, clientNum, nickname, source, approxPos) {
  const ev = {
    t: wallT,
    event: "pickup",
    item: item.classname,
    x: round1(item.x),
    y: round1(item.y),
    z: round1(item.z),
    action: "pickup",
    game_time_ms: gameTimeMs,
    clientNum,
    nickname,
    respawn_sec: respawnSec(item.classname),
    source,
  };
  if (approxPos) ev.approx_pos = true;
  return ev;
}

function collectDuelScoreUpdates(parser, clock, povClientNum, rosterClients) {
  const updates = [];
  let lastKey = "";
  for (const cmd of parser.serverCommands) {
    if (cmd.cmd !== "scores_duel") continue;
    const parts = cmd.text.trim().split(/\s+/);
    const s0 = parseInt(parts[0], 10);
    const s1 = parseInt(parts[1], 10);
    if (!Number.isFinite(s0) || !Number.isFinite(s1)) continue;
    const key = s0 + "-" + s1;
    if (key === lastKey) continue;
    lastKey = key;
    const serverTime = cmd.serverTime ?? clock.recordingStartMs;
    updates.push({
      wallT: serverTime - clock.recordingStartMs,
      gameTimeMs: serverTime - clock.fightStartMs,
      povScore: s0,
      oppScore: s1,
      byClient: Object.fromEntries(
        rosterClients.map((cn) => [cn, cn === povClientNum ? s0 : s1]),
      ),
    });
  }
  return updates;
}

function playersPoseKey(players) {
  return players
    .slice()
    .sort((a, b) => a.clientNum - b.clientNum)
    .map(
      (p) =>
        `${p.clientNum}:${Math.round(p.x)},${Math.round(p.y)},${Math.round(p.z)}:${Math.round(p.yaw ?? 0)}`,
    )
    .join("|");
}

/** Q3 player entity numbers are MAX_CLIENTS + clientNum; dm_91 entity.clientNum field is often stale in POV demos. */
function resolveEntityClientNum(ent) {
  if (!ent || ent.eType !== ET_PLAYER) return -1;
  // Entity 0 is a real, valid player slot in this protocol (the first
  // connected client can legitimately own it) — it's NOT reserved for
  // "world"/invalid like in vanilla Q3. Blanket-excluding it here used to
  // hide that player's entire early-match presence. The other tell for a
  // truly blank/reused slot (exact (0,0,0) origin) is filtered separately in
  // shouldProcessPlayerEntity.
  if (ent.number >= MAX_CLIENTS && ent.number < MAX_CLIENTS * 2) {
    return ent.number - MAX_CLIENTS;
  }
  if (ent.number < MAX_CLIENTS && ent.clientNum >= 0 && ent.clientNum < MAX_CLIENTS) {
    return ent.clientNum;
  }
  return -1;
}

function isSpectatorClient(rosterByClient, clientNum) {
  const row = rosterByClient[clientNum] || rosterByClient[String(clientNum)];
  return String(row?.t || "") === TEAM_SPECTATOR;
}

/**
 * A missing/blank baseline (no explicit SVC_BASELINE for that entity number,
 * or a delta that never touched trTime) can leave pos.trTime at 0 while
 * trBase is still the real, correctly-decoded last position. Extrapolating
 * TR_LINEAR/TR_GRAVITY/etc. with a multi-thousand-second dt (serverTime minus
 * a trTime stuck at 0) then produces astronomically wrong coordinates, and
 * the entity gets hidden entirely instead of shown at its real spot. Fall
 * back to the raw base position when the extrapolated one is insane.
 */
function safePlayerEntityOrigin(ent, serverTime) {
  const extrapolated = entityOriginAt(ent, serverTime);
  if (isSaneWorldOrigin(extrapolated[0], extrapolated[1], extrapolated[2])) return extrapolated;
  const base = ent.pos.trBase;
  if (isSaneWorldOrigin(base[0], base[1], base[2])) return [base[0], base[1], base[2]];
  return extrapolated;
}

/** UDT Demo::ProcessPlayer filters. */
function shouldProcessPlayerEntity(ent, serverTime, rosterByClient, clientNum) {
  if (clientNum < 0 || clientNum >= MAX_CLIENTS) return false;
  if (isSpectatorClient(rosterByClient, clientNum)) return false;
  if (ent.eFlags & EF_NODRAW) return false;
  if ((ent.eFlags & EF_DEAD) && ent.pos.trType === TR_GRAVITY) return false;
  const [x, y, z] = safePlayerEntityOrigin(ent, serverTime);
  if (!isSaneWorldOrigin(x, y, z)) return false;
  // A blank/freed entity slot (createEntityState() defaults, never actually
  // updated) sits at exactly world origin — real players essentially never
  // land on (0,0,0) on all three axes at once. Seen in practice on entity 0
  // once it stops being reused as a real player's slot later in the demo.
  if (x === 0 && y === 0 && z === 0) return false;
  return true;
}

function entityPreferredForClient(ent, prevEntNum, clientNum) {
  const ideal = MAX_CLIENTS + clientNum;
  if (ent.number === ideal) return true;
  if (prevEntNum === ideal) return false;
  return ent.number > (prevEntNum ?? -1);
}

function playerNearItem(playersByCn, x, y, radius = 128) {
  for (const p of playersByCn.values()) {
    const dx = p.x - x;
    const dy = p.y - y;
    if (dx * dx + dy * dy <= radius * radius) return p;
  }
  return null;
}

function impactKind(ev, weapon) {
  if (weapon === WP_SHAFT && isBulletImpactEvent(ev)) return "shaft";
  if (isBulletImpactEvent(ev)) return "bullet";
  if (weapon === WP_PLASMA) return "plasma";
  if (weapon === WP_ROCKET || weapon === WP_GRENADE) return "explosion";
  if (isMissileImpactEvent(ev)) return "missile";
  return "impact";
}

function collectFxFromEntity(ent, snap, impacts, projectiles) {
  if (ent.eType === ET_MISSILE && PROJECTILE_WEAPONS.has(ent.weapon)) {
    const [x, y, z] = entityOriginAt(ent, snap.serverTime);
    const [vx, vy, vz] = entityVelocity(ent);
    projectiles.push({
      eid: ent.number,
      weapon: ent.weapon,
      weapon_slug: weaponSlug(ent.weapon),
      clientNum: ent.clientNum,
      x: round1(x),
      y: round1(y),
      z: round1(z),
      vx: round1(vx),
      vy: round1(vy),
      vz: round1(vz),
    });
    return;
  }

  if (ent.eType === ET_GENERAL) {
    const ev = eventId(ent.event);
    if (!isMissileImpactEvent(ev)) return;
    const [x, y, z] = entityOriginAt(ent, snap.serverTime);
    impacts.push({
      kind: impactKind(ev, ent.weapon),
      weapon: ent.weapon,
      weapon_slug: weaponSlug(ent.weapon),
      clientNum: ent.clientNum >= 0 ? ent.clientNum : undefined,
      x: round1(x),
      y: round1(y),
      z: round1(z),
    });
  }
}

function collectFxFromChangedEntity(ent, snap, impacts, beams, deaths, rosterByClient) {
  if (ent.eType < ET_EVENTS || !ent.newEvent) return;
  const ev = entityEventId(ent);
  const [x, y, z] = entityOriginAt(ent, snap.serverTime);

  if (ev === EV_OBITUARY) {
    const victimCn = ent.otherEntityNum;
    if (victimCn < 0 || victimCn >= MAX_CLIENTS) return;
    const attackerCn = ent.otherEntityNum2 >= 0 && ent.otherEntityNum2 < MAX_CLIENTS ? ent.otherEntityNum2 : null;
    const victim = rosterByClient[victimCn] || {};
    const attacker = attackerCn != null ? rosterByClient[attackerCn] || {} : null;
    deaths.push({
      victim_clientNum: victimCn,
      victim_name: victim.n || victim.name || "player" + victimCn,
      victim_steam_id64: victim.st || null,
      killer_clientNum: attackerCn,
      killer_name: attacker ? attacker.n || attacker.name || "player" + attackerCn : null,
      killer_steam_id64: attacker ? attacker.st || null : null,
      weapon_slug: meanOfDeathWeaponSlug(ent.eventParm),
      x: round1(x),
      y: round1(y),
      z: round1(z),
    });
    return;
  }

  if (ev === EV_RAIL_TRAIL && ent.clientNum >= 0) {
    beams.push({
      clientNum: ent.clientNum,
      x0: round1(ent.origin2[0]),
      y0: round1(ent.origin2[1]),
      z0: round1(ent.origin2[2]),
      x1: round1(ent.pos.trBase[0]),
      y1: round1(ent.pos.trBase[1]),
      z1: round1(ent.pos.trBase[2]),
      weapon: 7,
      weapon_slug: "railgun",
    });
    return;
  }

  if (isBulletImpactEvent(ev) || isMissileImpactEvent(ev)) {
    // Bullet/missile impact temp entities are anonymous in this protocol
    // (weapon/clientNum/otherEntityNum all read back as 0 - verified against
    // the real UDT viewer source: it keys shaft-beam matching off `es.weapon`
    // on this exact same entity, which means it's subject to the same gap).
    // The LG beam is synthesized separately from the shooter's own aim
    // direction instead of impact-matching (see collectLightningBeams).
    impacts.push({
      kind: impactKind(ev, ent.weapon),
      weapon: ent.weapon,
      weapon_slug: weaponSlug(ent.weapon),
      clientNum: ent.clientNum >= 0 ? ent.clientNum : undefined,
      x,
      y,
      z,
    });
  }
}

function playerRowFromEntity(ent, serverTime, rosterByClient, clientNum) {
  const [x, y, z] = safePlayerEntityOrigin(ent, serverTime);
  const [vx, vy, vz] = entityVelocity(ent);
  const row = rosterByClient[clientNum] || {};
  const powerups = powerupNamesFromEntityMask(ent.powerups);
  // A settled (non-falling) corpse still passes shouldProcessPlayerEntity by
  // design (matches UDT's Demo::ProcessPlayer) so its death marker/position
  // stays visible; eFlags is the reliable alive/dead signal. The health/armor
  // entity fields (indices 55/56) are only populated by the server for
  // spectator recordings (recording client has full-entity visibility);
  // regular participant demos read back a constant 0 for opponents. A live
  // player can never actually be at 0 HP (they'd be dead), so alive+0 means
  // "not populated" here - suppress both fields together rather than show a
  // fabricated 0/0.
  const dead = (ent.eFlags & EF_DEAD) !== 0;
  const vitalsPopulated = !dead && Number(ent.health) > 0;
  return {
    clientNum,
    nickname: row.n || row.name || "player" + clientNum,
    x,
    y,
    z,
    vx,
    vy,
    vz,
    yaw: yawFromEntity(ent),
    weapon: ent.weapon || 0,
    health: vitalsPopulated ? saneVital(ent.health) : null,
    armor: vitalsPopulated ? saneVital(ent.armor) : null,
    alive: !dead,
    powerups: powerups.length ? powerups : undefined,
  };
}

/** Only meaningful for spectator-recorded demos — see povIsSpectator above. */
function resolveFollowedClientNum(ps, rosterSet, fallbackClientNum) {
  if (ps && ps.clientNum >= 0 && ps.clientNum < MAX_CLIENTS && rosterSet.has(ps.clientNum)) {
    return ps.clientNum;
  }
  return fallbackClientNum;
}

function playerRowFromPs(ps, rosterByClient, serverTime, clientNum, lastVitals, poseState) {
  const es = playerStateToEntityState(ps, clientNum, serverTime, false);
  let row = playerRowFromEntity(es, serverTime, rosterByClient, clientNum);
  row.yaw = yawFromViewangles(ps.viewangles);
  row = withCarriedVitals(row, clientNum, lastVitals, ps);
  if (poseState) row = applyPovDeathFreeze(row, clientNum, ps, poseState);
  // Only ever available for the recording player's own playerState (chase-cam
  // entities never carry ammo/stats) - future !restore match needs this
  // instead of guessing inventory from pickup history.
  row.ammo = ps.ammo ? ps.ammo.slice() : undefined;
  row.weapons = ps.stats?.[STAT_WEAPONS];
  row.holdable = ps.stats?.[STAT_HOLDABLE_ITEM] || undefined;
  // entityVelocity() returns 0,0,0 for TR_INTERPOLATE (the type
  // playerStateToEntityState uses when extrapolate=false), so own-POV
  // rows were serializing a standing-still vector even while moving.
  // Restore and overlays need the real playerState velocity.
  if (ps.velocity) {
    row.vx = round1(ps.velocity[0] || 0);
    row.vy = round1(ps.velocity[1] || 0);
    row.vz = round1(ps.velocity[2] || 0);
  }
  return row;
}

/**
 * Convert parsed demo to canonical replay ({ meta, events }).
 * Events: match_start, positions, pickup, projectiles (sparse).
 */
export function demoToReplay(parser, options = {}) {
  const map = normalizeMapKey(parser.mapName());
  const rosterByClient = parser.gamestate.players;
  // options.povClientNum wins when the caller already resolved the correct
  // live identity (e.g. match-to-replay.js via identity.js's
  // liveClientNumFromParser) - parser.gamestate.clientNum can still be a
  // leftover previous occupant's slot for a recorder-slot file with a
  // mid-file serverTime reset (see match-set.js).
  const povClientNum = options.povClientNum ?? parser.gamestate.clientNum ?? null;
  const mapTable = options.mapTable ?? loadMapPickupTable(map);
  const includePickups = options.includePickups !== false;
  const rosterSet = new Set(
    parser.playerRows().map((p) => p.clientNum).filter((cn) => cn >= 0 && cn < MAX_CLIENTS),
  );
  // A demo recorded by a spectator (follow-cam bot, e.g. "StreamSpec") has a
  // recording connection that's in gamestate.spectators, not .players — its
  // playerState is legitimately cloned from whichever real player it's
  // currently chase-camming, and ps.clientNum tells us who. A real POV demo's
  // recording connection IS a player, and ps.clientNum should stay pinned to
  // it (see the trTime/corpse investigation earlier — chasing ps.clientNum
  // there was chasing decode noise, not a real follow target).
  const povIsSpectator = !!(parser.gamestate.spectators && parser.gamestate.spectators[povClientNum]);
  const rosterClients = [...rosterSet];
  const clock = parseMatchClock(parser);
  const { recordingStartMs, fightStartMs, countdownLeadMs, durationMs } = clock;
  const scoreUpdates = collectDuelScoreUpdates(parser, clock, povClientNum, rosterClients);
  const events = [];

  if (countdownLeadMs > 0) {
    events.push({
      t: 0,
      event: "countdown_start",
      game_time_ms: -countdownLeadMs,
    });
  }
  events.push({
    t: countdownLeadMs,
    event: "match_start",
    game_time_ms: 0,
    map_name: map,
    gametype: parser.gametype(),
  });

  const staticItems = new StaticItemTracker();
  const droppedItems = new DroppedItemTracker();
  const lastVitals = new Map();
  const povPoseState = new Map();
  // Raw entityState.event byte (id + toggle bits, see EV_ITEM_PICKUP comment
  // above) last observed per OTHER player's clientNum - a change from the
  // stored value is this POV's signal that that entity just fired a new
  // event, mirroring the ring-sequence check the ps.events path below does
  // for the POV's own player. Entity events here don't get demo-parser's
  // isNewEntityEvent()/EVENT_VALID_MSEC treatment - that debounce is scoped
  // to eType>=ET_EVENTS broadcast temp entities (EV_OBITUARY/EV_RAIL_TRAIL/
  // impacts), which recycle entity-number slots and have no stable "previous
  // value" to diff against; a player's own entity number is stable for the
  // whole demo, so a plain raw-value comparison is the correct (and
  // simpler) check here - same technique real cgame uses.
  const lastPlayerEventRaw = new Map();
  let fightItemsReady = false;
  let lastEmitMs = -POSITION_EMIT_MS;
  let lastEmitKey = "";
  let projectileEvents = 0;
  let impactEvents = 0;
  let beamEvents = 0;
  let deathEvents = 0;
  let dropEvents = 0;
  let hadProjectilesLastSnap = false;
  // ps.eventSequence of the previous snapshot; null until the first snapshot
  // seeds it (events already sitting in the ring at recording start predate
  // the demo and must not be replayed - same as cgame's first-snap handling).
  let psPrevEventSeq = null;
  // ps.externalEvent of the previous snapshot - see the ps.externalEvent
  // pickup block below for why this is a second, independent own-POV pickup
  // source alongside the events[] ring.
  let psPrevExternalEvent = undefined;

  for (const snap of parser.snapshots) {
    const wallT = snap.serverTime - recordingStartMs;
    const gameTimeMs = snap.serverTime - fightStartMs;
    const playersByCn = new Map();
    const entNumByCn = new Map();

    if (gameTimeMs >= 0 && !fightItemsReady) {
      staticItems.registry.clear();
      staticItems.state.clear();
      staticItems.seenPickups.clear();
      fightItemsReady = true;
    }

    // UDT order: ET_PLAYER entities first, then followed player from playerState.
    // In spectator mode, fall back to null (not the spectator's own slot) —
    // when the spectator isn't chase-camming a real roster player this tick,
    // we simply have no reliable playerState-derived row to add, rather than
    // leaking the spectator's own free-fly identity in as a fake "player".
    const psClientNum = povIsSpectator
      ? resolveFollowedClientNum(snap.playerState, rosterSet, null)
      : povClientNum;

    // Players actively firing the LG this snapshot (weapon + EF_FIRING), with
    // the aim angles needed to draw their beam - see lgBeamEndpoint() above.
    const firingShaft = new Map();

    for (const ent of snap.entities || []) {
      if (ent.eType !== ET_PLAYER) continue;
      const clientNum = resolveEntityClientNum(ent);
      if (clientNum < 0 || !rosterSet.has(clientNum) || clientNum === psClientNum) continue;
      if (!shouldProcessPlayerEntity(ent, snap.serverTime, rosterByClient, clientNum)) continue;
      const prevEntNum = entNumByCn.get(clientNum);
      if (!entityPreferredForClient(ent, prevEntNum, clientNum)) continue;
      const row = playerRowFromEntity(ent, snap.serverTime, rosterByClient, clientNum);
      playersByCn.set(clientNum, row);
      entNumByCn.set(clientNum, ent.number);
      if (ent.weapon === WP_SHAFT && (ent.eFlags & EF_FIRING)) {
        firingShaft.set(clientNum, {
          x: row.x, y: row.y, z: row.z,
          pitch: ent.apos.trBase[0], yaw: ent.apos.trBase[1],
        });
      }

      // Other players' pickups, observed via their own entity's broadcast
      // event (see EV_ITEM_PICKUP comment near the top of this file) instead
      // of guessed from PVS disappearance. No gameTimeMs>=0 gate here - a
      // pickup before the detected fight-start still has a real, lasting
      // effect (overheal, ammo, held weapon) that a restore at a later
      // match time must see; only "seen a prior raw value first" guards
      // against a stale first-sighting looking like a fresh pickup.
      if (includePickups) {
        const rawEvent = ent.event | 0;
        const prevRaw = lastPlayerEventRaw.get(clientNum);
        lastPlayerEventRaw.set(clientNum, rawEvent);
        if (prevRaw !== undefined && rawEvent !== 0 && rawEvent !== prevRaw) {
          const evId = entityEventId(ent);
          if (evId === EV_ITEM_PICKUP || evId === EV_GLOBAL_ITEM_PICKUP) {
            const canonical = QL91_ITEM_CLASSNAMES[ent.eventParm | 0];
            if (canonical) {
              const { item, approxPos } = resolveExactPickupItem(canonical, row.x, row.y, row.z, staticItems, mapTable);
              events.push(
                buildExactPickupEvent(wallT, gameTimeMs, item, clientNum, row.nickname, "entity", approxPos),
              );
            }
          }
        }
      }
    }

    if (snap.playerState && psClientNum != null) {
      const psRow = playerRowFromPs(
        snap.playerState,
        rosterByClient,
        snap.serverTime,
        psClientNum,
        lastVitals,
        povPoseState,
      );
      if (gameTimeMs >= 0) {
        playersByCn.set(psClientNum, psRow);
      } else {
        const poseOnly = Object.assign({}, psRow, { health: null, armor: null });
        playersByCn.set(psClientNum, poseOnly);
      }
      if (snap.playerState.weapon === WP_SHAFT && (snap.playerState.eFlags & EF_FIRING)) {
        firingShaft.set(psClientNum, {
          x: psRow.x, y: psRow.y, z: psRow.z,
          pitch: snap.playerState.viewangles[0], yaw: snap.playerState.viewangles[1],
        });
      }
    } else if (snap.playerState && povClientNum == null) {
      // Only for a demo with no recording identity at all (distinct from a
      // spectator recording that simply isn't following anyone this tick —
      // psClientNum being null there means "no reliable row", not "guess one").
      const psRow = playerRowFromPs(snap.playerState, rosterByClient, snap.serverTime, null, lastVitals, null);
      playersByCn.set(psRow.clientNum, psRow);
    }

    const snapItems = new Set();
    const snapDrops = new Set();
    const newDrops = [];
    const projectiles = [];
    const impacts = [];
    const beams = [];
    const deaths = [];
    for (const ent of snap.entities || []) {
      if (ent.eType === ET_ITEM) {
        // A real map-spawned pickup is settled onto the floor server-side at
        // level load, before any client ever sees a snapshot of it - every
        // ET_ITEM this parser can observe over the wire is already
        // TR_STATIONARY. A dropped/in-flight item (weapon or ammo dropped on
        // death, a thrown holdable) instead arrives with a moving trajectory
        // (TR_GRAVITY while falling, TR_INTERPOLATE once settling) and its
        // own distinct entity number. Registering it into the static
        // registry at all is the root cause of a real observed bug: with
        // `gamestate.models` empty for every real .dm_91 capture seen so far
        // (models[] configstrings apparently never make it into the demo -
        // separate finding, not fixed here), classname resolution used to
        // fall through to resolvePickupAt()'s pure position lookup, so a
        // drop landing within its 64-unit tolerance of an unrelated spawn
        // (e.g. red armor) got misnamed as that spawn's item and reported as
        // a false pickup of it once the drop later disappeared or was
        // picked up. Skipping non-stationary entities here closes that at
        // the source, independent of whether models[] ever gets populated.
        // modelindex2 === 1 is LaunchItem()'s own "dropped, not map-placed"
        // marker, so a death drop is separated out here by what the engine
        // says it is rather than by the trajectory test below - which only
        // ever caught drops while they were still in the air. A settled drop
        // is TR_STATIONARY like any map item, and used to be registered as
        // one: that is the misnamed-spawn/false-pickup case the comment above
        // describes, now closed for good.
        if ((ent.modelindex2 | 0) === 1) {
          if (ent.pos.trType !== TR_STATIONARY) continue;
          const [dx, dy, dz] = entityOriginAt(ent, snap.serverTime);
          if (!isSaneWorldOrigin(dx, dy, dz)) continue;
          const itemId = ent.modelindex | 0;
          if (!itemId) continue;
          snapDrops.add(dropSpotKey(itemId, dx, dy, dz));
          if (gameTimeMs >= 0) {
            const fresh = droppedItems.see(itemId, dx, dy, dz, gameTimeMs);
            if (fresh) newDrops.push(fresh);
          }
          continue;
        }
        if (ent.pos.trType !== TR_STATIONARY) continue;
        const [x, y, z] = entityOriginAt(ent, snap.serverTime);
        // ent.modelindex on an item entity is a bg_itemlist index (same table
        // EV_ITEM_PICKUP's eventParm resolves through via QL91_ITEM_CLASSNAMES),
        // NOT a gamestate.models[] model index - that table is empty for every
        // real .dm_91 capture seen so far, so indexing into it always produced
        // "" and silently fell through to a 64-unit position-tolerance guess.
        const classname = QL91_ITEM_CLASSNAMES[ent.modelindex | 0] || "";
        if (!classname) continue;
        const key = staticItems.register(classname, x, y, z);
        snapItems.add(key);
      }
      collectFxFromEntity(ent, snap, impacts, projectiles);
    }
    for (const ent of snap.changedEntities || []) {
      collectFxFromChangedEntity(ent, snap, impacts, beams, deaths, rosterByClient);
    }
    // LG has no dedicated network beam (unlike rail's EV_RAIL_TRAIL): draw a
    // beam along the shooter's aim direction for every player actively firing
    // it this snapshot, clipped to whichever live opponent it geometrically
    // hits (see lgBeamHitDistance()/lgBeamEndpoint() comment above).
    for (const [clientNum, shooter] of firingShaft) {
      const [fx, fy, fz] = lgAimDir(shooter.pitch, shooter.yaw);
      const hitDist = lgBeamHitDistance(shooter.x, shooter.y, shooter.z, fx, fy, fz, playersByCn, clientNum);
      const [x1, y1, z1] = lgBeamEndpoint(
        shooter.x,
        shooter.y,
        shooter.z,
        fx,
        fy,
        fz,
        hitDist != null ? hitDist : LG_BEAM_LENGTH,
      );
      beams.push({
        clientNum,
        x0: round1(shooter.x),
        y0: round1(shooter.y),
        z0: round1(shooter.z),
        x1,
        y1,
        z1,
        weapon: WP_SHAFT,
        weapon_slug: "lightninggun",
      });
      // The beam is synthesized (see lgBeamEndpoint() comment above) and never
      // wall-snapped, so it has no matched impact temp-entity like other
      // weapons — push its own end point as a "shaft" impact so the overlay
      // draws a hit marker at the beam tip like UDT does.
      impacts.push({
        kind: "shaft",
        weapon: WP_SHAFT,
        weapon_slug: "lightninggun",
        clientNum,
        x: x1,
        y: y1,
        z: z1,
      });
    }
    for (const death of deaths) {
      deathEvents++;
      events.push({
        t: wallT,
        event: "death",
        game_time_ms: gameTimeMs,
        victim_clientNum: death.victim_clientNum,
        victim_name: death.victim_name,
        victim_steam_id64: death.victim_steam_id64,
        killer_clientNum: death.killer_clientNum,
        killer_name: death.killer_name,
        killer_steam_id64: death.killer_steam_id64,
        weapon: death.weapon_slug,
        x: death.x,
        y: death.y,
        z: death.z,
        time: gameTimeMs,
      });
    }

    // Own-POV pickups from playerState events - processed BEFORE the
    // disappearance heuristic below so a ps-confirmed pickup marks the
    // registry spot (seenPickups) and the heuristic doesn't emit a duplicate
    // when the item entity vanishes from the same or the next snapshot.
    if (includePickups && snap.playerState && psClientNum != null) {
      const ps = snap.playerState;
      const seq = ps.eventSequence | 0;
      if (psPrevEventSeq != null && seq > psPrevEventSeq) {
        for (let i = Math.max(psPrevEventSeq, seq - MAX_PS_EVENTS); i < seq; i++) {
          const slot = i & (MAX_PS_EVENTS - 1);
          const ev = (ps.events?.[slot] | 0) & ~PS_EVENT_BITS;
          if (ev !== EV_ITEM_PICKUP && ev !== EV_GLOBAL_ITEM_PICKUP) continue;
          const canonical = QL91_ITEM_CLASSNAMES[ps.eventParms?.[slot] | 0];
          if (!canonical) continue;
          const [px, py, pz] = ps.origin || [];
          if (!Number.isFinite(px)) continue;
          const { item, approxPos } = resolveExactPickupItem(canonical, px, py, pz, staticItems, mapTable);
          events.push(
            buildExactPickupEvent(
              wallT,
              gameTimeMs,
              item,
              psClientNum,
              playersByCn.get(psClientNum)?.nickname,
              "ps",
              approxPos,
            ),
          );
        }
      }
      psPrevEventSeq = seq;

      // Second, independent own-POV pickup source: ps.externalEvent /
      // ps.externalEventParm. Confirmed empirically against real production
      // demos (bloodrun match 20260829T225720Z): a mega health and a yellow
      // armor pickup were both real (health/armor jumped by exactly the
      // item's value) but produced NO events[]/eventParms[] ring entry at
      // all - the only place the server recorded them was externalEvent/
      // externalEventParm, encoded identically (EV_ITEM_PICKUP id + the same
      // bg_itemlist parm). This matches CG_CheckPlayerstateEvents in the
      // real client (wasm-build/vendor/wolfcamql/code/cgame/cg_playerstate.c):
      // it checks `ps->externalEvent != ops->externalEvent` as a SEPARATE
      // step before the predictable-events ring loop - both mechanisms
      // coexist and the game client relies on both, which is exactly why
      // "just watch the demo" always shows every pickup correctly. Not a
      // ring, so no sequence bookkeeping - just a changed-since-last-tick
      // comparison, same technique as the entity-event path above.
      const extRaw = ps.externalEvent | 0;
      if (
        psPrevExternalEvent !== undefined &&
        extRaw !== 0 &&
        extRaw !== psPrevExternalEvent
      ) {
        const extEv = extRaw & ~PS_EVENT_BITS;
        if (extEv === EV_ITEM_PICKUP || extEv === EV_GLOBAL_ITEM_PICKUP) {
          const canonical = QL91_ITEM_CLASSNAMES[ps.externalEventParm | 0];
          const [px, py, pz] = ps.origin || [];
          if (canonical && Number.isFinite(px)) {
            const { item, approxPos } = resolveExactPickupItem(canonical, px, py, pz, staticItems, mapTable);
            events.push(
              buildExactPickupEvent(
                wallT,
                gameTimeMs,
                item,
                psClientNum,
                playersByCn.get(psClientNum)?.nickname,
                "ps",
                approxPos,
              ),
            );
          }
        }
      }
      psPrevExternalEvent = extRaw;
    }

    if (includePickups && gameTimeMs >= 0) {
      const hasNearbyPlayer = (x, y) => !!playerNearItem(playersByCn, x, y);
      for (const rec of newDrops) {
        dropEvents++;
        events.push(dropEvent("drop", rec, rec.dropMs, wallT));
      }
      for (const { rec, gameTimeMs: takenMs } of droppedItems.collectTaken(
        snapDrops,
        gameTimeMs,
        hasNearbyPlayer,
      )) {
        events.push(dropEvent("gone", rec, takenMs, wallT));
      }
      const { pickups, respawns } = staticItems.collectPickups(snapItems, gameTimeMs, wallT, hasNearbyPlayer);
      for (const pickup of pickups) {
        const picker = playerNearItem(playersByCn, pickup.item.x, pickup.item.y);
        events.push({
          t: pickup.wallT,
          event: "pickup",
          item: pickup.item.classname,
          x: round1(pickup.item.x),
          y: round1(pickup.item.y),
          z: round1(pickup.item.z),
          action: "pickup",
          game_time_ms: pickup.gameTimeMs,
          clientNum: picker?.clientNum ?? povClientNum ?? undefined,
          nickname: picker?.nickname,
          respawn_sec: respawnSec(pickup.item.classname),
        });
      }
      for (const respawn of respawns) {
        events.push({
          t: respawn.wallT,
          event: "pickup",
          item: respawn.item.classname,
          x: round1(respawn.item.x),
          y: round1(respawn.item.y),
          z: round1(respawn.item.z),
          action: "respawn",
          game_time_ms: respawn.gameTimeMs,
        });
      }
    }

    const players = [...playersByCn.values()].sort((a, b) => a.clientNum - b.clientNum);
    const poseKey = playersPoseKey(players);
    const shouldEmitPositions =
      players.length > 0 &&
      (gameTimeMs - lastEmitMs >= POSITION_EMIT_MS || poseKey !== lastEmitKey);
    if (shouldEmitPositions) {
      lastEmitMs = gameTimeMs;
      lastEmitKey = poseKey;
      events.push({
        t: wallT,
        event: "positions",
        game_time_ms: gameTimeMs,
        map_name: map,
        gametype: parser.gametype(),
        players: players.map((p) => ({
          nickname: p.nickname,
          clientNum: p.clientNum,
          x: round1(p.x),
          y: round1(p.y),
          z: round1(p.z),
          yaw: p.yaw,
          health: p.health,
          armor: p.armor,
          weapon: p.weapon,
          vx: p.vx,
          vy: p.vy,
          vz: p.vz,
          powerups: p.powerups,
          alive: p.alive !== false,
          ammo: p.ammo,
          weapons: p.weapons,
          holdable: p.holdable,
        })),
      });
    }

    // Emit even when empty on the one frame right after the last in-flight
    // missile disappears (hit/expired) — otherwise the client never learns
    // that eid is gone and its dot sticks on the map forever (no further
    // "projectiles" event ever arrives to prune it).
    if (projectiles.length || hadProjectilesLastSnap) {
      projectileEvents++;
      events.push({
        t: wallT,
        event: "projectiles",
        game_time_ms: gameTimeMs,
        projectiles,
      });
    }
    hadProjectilesLastSnap = projectiles.length > 0;

    if (impacts.length) {
      impactEvents++;
      events.push({
        t: wallT,
        event: "impacts",
        game_time_ms: gameTimeMs,
        impacts,
      });
    }

    if (beams.length) {
      beamEvents++;
      events.push({
        t: wallT,
        event: "beams",
        game_time_ms: gameTimeMs,
        beams,
      });
    }
  }

  return {
    meta: {
      map_name: map,
      gametype: parser.gametype(),
      source: "demo",
      format: "json",
      schema: "replay-v2",
      pov_client_num: povClientNum,
      roster: parser.playerRows().map((p) => ({
        clientNum: p.clientNum,
        name: p.n,
        steam_id64: p.st || null,
      })),
      snapshot_count: parser.snapshots.length,
      match_start_server_time: fightStartMs,
      recording_start_server_time: recordingStartMs,
      countdown_lead_ms: countdownLeadMs,
      duration_wall_ms: durationMs,
      score_updates: scoreUpdates,
      player_count: parser.playerRows().length,
      projectile_frames: projectileEvents,
      impact_frames: impactEvents,
      beam_frames: beamEvents,
      death_events: deathEvents,
      drop_events: dropEvents,
      errors: parser.errors,
      // Every (classname, x, y, z) the POV ever actually rendered as an
      // ET_ITEM entity anywhere in the recording - lets the map widget
      // permanently hide static-catalog item spawns this demo has zero
      // evidence for (MapSpawns.markNeverSeenInDemo), instead of the
      // default-present-until-picked-up model that's only valid for live
      // (server-authoritative) telemetry.
      seen_items: [...staticItems.registry.values()].map((it) => ({
        classname: it.classname,
        x: it.x,
        y: it.y,
        z: it.z,
      })),
    },
    events,
    respawnSec,
    ITEM_RESPAWN_SEC,
  };
}

export function replaySummary(replay) {
  const positions = replay.events.filter((e) => e.event === "positions");
  const pickups = replay.events.filter((e) => e.event === "pickup");
  const projectiles = replay.events.filter((e) => e.event === "projectiles");
  const impacts = replay.events.filter((e) => e.event === "impacts");
  const beams = replay.events.filter((e) => e.event === "beams");
  const deaths = replay.events.filter((e) => e.event === "death");
  const last = positions[positions.length - 1];
  return {
    map: replay.meta.map_name,
    gametype: replay.meta.gametype,
    snapshots: replay.meta.snapshot_count,
    position_events: positions.length,
    pickups: pickups.length,
    projectile_frames: projectiles.length,
    impact_frames: impacts.length,
    beam_frames: beams.length,
    deaths: deaths.length,
    duration_game_ms: last?.game_time_ms ?? 0,
    players: parserPlayerNames(replay),
    errors: replay.meta.errors,
  };
}

function parserPlayerNames(replay) {
  const names = new Set();
  for (const ev of replay.events) {
    if (ev.event !== "positions") continue;
    for (const p of ev.players || []) if (p.nickname) names.add(p.nickname);
  }
  return [...names];
}
