import {
  GENTITYNUM_BITS,
  MAX_PERSISTANT,
  MAX_POWERUPS,
  MAX_STATS,
  MAX_WEAPONS,
} from "./constants.js";
import {
  ENTITY_BITS_91,
  applyEntityField91,
  cloneEntityState,
  createEntityState,
} from "./entity-state.js?v=20260712b";
import {
  createMsgReader,
  huffmanReadByte,
  huffmanReadLong,
  huffmanReadShort,
  readBits,
} from "./huffman.js?v=20260712b";
import { readField } from "./read-field.js?v=20260712b";

/** dm_91 playerstate net fields (UDT PlayerStateFields91). */
export const PLAYER_BITS_91 = [
  32, 0, 0, 8, 0, 0, 0, 0, -16, 0, 0, 8, -16, 16, 8, 4, 8, 8, 8, 24, GENTITYNUM_BITS, 4, 16, 10, 16, 16, 16, 8, -8,
  8, 8, 8, 8, 8, 8, 16, 16, 12, 8, 8, 8, 5, 8, 0, 0, 0, 0, 10, 16, 32, 1, 32, 32, 8, 8, 8, 8, 8,
];

export function createPlayerState() {
  return {
    commandTime: 0,
    origin: [0, 0, 0],
    bobCycle: 0,
    velocity: [0, 0, 0],
    viewangles: [0, 0, 0],
    weaponTime: 0,
    legsTimer: 0,
    pm_time: 0,
    eventSequence: 0,
    torsoAnim: 0,
    movementDir: 0,
    events: [0, 0],
    legsAnim: 0,
    pm_flags: 0,
    groundEntityNum: 0,
    weaponstate: 0,
    eFlags: 0,
    externalEvent: 0,
    gravity: 0,
    speed: 0,
    delta_angles: [0, 0, 0],
    externalEventParm: 0,
    viewheight: 0,
    damageEvent: 0,
    damageYaw: 0,
    damagePitch: 0,
    damageCount: 0,
    generic1: 0,
    pm_type: 0,
    torsoTimer: 0,
    eventParms: [0, 0],
    clientNum: 0,
    weapon: 0,
    weaponPrimary: 0,
    grapplePoint: [0, 0, 0],
    jumppad_ent: 0,
    loopSound: 0,
    jumpTime: 0,
    doubleJumped: 0,
    crouchTime: 0,
    crouchSlideTime: 0,
    location: 0,
    fov: 0,
    forwardmove: 0,
    rightmove: 0,
    upmove: 0,
    stats: new Array(MAX_STATS).fill(0),
    persistant: new Array(MAX_PERSISTANT).fill(0),
    ammo: new Array(MAX_WEAPONS).fill(0),
    powerups: new Array(MAX_POWERUPS).fill(0),
  };
}

// Field index -> struct member, per the real vendored engine's authoritative
// wire order (wasm-build/vendor/wolfcamql/code/qcommon/msg.c's
// playerStateFieldsQldm91[]) — NOT just the handful this project's overlay
// rendering happens to read. demo-editor/lib/snapshot-writer.js needs every
// field round-tripped losslessly to synthesize a byte-correct full snapshot
// at an arbitrary cut point; silently dropping unmapped fields (the previous
// state of this switch, which only covered 14 of 59) would zero out real
// values like groundEntityNum/pm_flags/pm_type in an exported clip's first
// frame — the real player-position corruption this was written to fix.
function applyPlayerField91(ps, index, value) {
  switch (index) {
    case 0:
      ps.commandTime = value;
      return;
    case 1:
      ps.origin[0] = value;
      return;
    case 2:
      ps.origin[1] = value;
      return;
    case 3:
      ps.bobCycle = value;
      return;
    case 4:
      ps.velocity[0] = value;
      return;
    case 5:
      ps.velocity[1] = value;
      return;
    case 6:
      ps.viewangles[1] = value;
      return;
    case 7:
      ps.viewangles[0] = value;
      return;
    case 8:
      ps.weaponTime = value;
      return;
    case 9:
      ps.origin[2] = value;
      return;
    case 10:
      ps.velocity[2] = value;
      return;
    case 11:
      ps.legsTimer = value;
      return;
    case 12:
      ps.pm_time = value;
      return;
    case 13:
      ps.eventSequence = value;
      return;
    case 14:
      ps.torsoAnim = value;
      return;
    case 15:
      ps.movementDir = value;
      return;
    case 16:
      ps.events[0] = value;
      return;
    case 17:
      ps.legsAnim = value;
      return;
    case 18:
      ps.events[1] = value;
      return;
    case 19:
      ps.pm_flags = value;
      return;
    case 20:
      ps.groundEntityNum = value;
      return;
    case 21:
      ps.weaponstate = value;
      return;
    case 22:
      ps.eFlags = value;
      return;
    case 23:
      ps.externalEvent = value;
      return;
    case 24:
      ps.gravity = value;
      return;
    case 25:
      ps.speed = value;
      return;
    case 26:
      ps.delta_angles[1] = value;
      return;
    case 27:
      ps.externalEventParm = value;
      return;
    case 28:
      ps.viewheight = value;
      return;
    case 29:
      ps.damageEvent = value;
      return;
    case 30:
      ps.damageYaw = value;
      return;
    case 31:
      ps.damagePitch = value;
      return;
    case 32:
      ps.damageCount = value;
      return;
    case 33:
      ps.generic1 = value;
      return;
    case 34:
      ps.pm_type = value;
      return;
    case 35:
      ps.delta_angles[0] = value;
      return;
    case 36:
      ps.delta_angles[2] = value;
      return;
    case 37:
      ps.torsoTimer = value;
      return;
    case 38:
      ps.eventParms[0] = value;
      return;
    case 39:
      ps.eventParms[1] = value;
      return;
    case 40:
      ps.clientNum = value;
      return;
    case 41:
      ps.weapon = value;
      return;
    case 42:
      ps.weaponPrimary = value;
      return;
    case 43:
      ps.viewangles[2] = value;
      return;
    case 44:
      ps.grapplePoint[0] = value;
      return;
    case 45:
      ps.grapplePoint[1] = value;
      return;
    case 46:
      ps.grapplePoint[2] = value;
      return;
    case 47:
      ps.jumppad_ent = value;
      return;
    case 48:
      ps.loopSound = value;
      return;
    case 49:
      ps.jumpTime = value;
      return;
    case 50:
      ps.doubleJumped = value;
      return;
    case 51:
      ps.crouchTime = value;
      return;
    case 52:
      ps.crouchSlideTime = value;
      return;
    case 53:
      ps.location = value;
      return;
    case 54:
      ps.fov = value;
      return;
    case 55:
      ps.forwardmove = value;
      return;
    case 56:
      ps.rightmove = value;
      return;
    case 57:
      ps.upmove = value;
      return;
    default:
      return;
  }
}

// Inverse of applyPlayerField91 — demo-editor/lib/snapshot-writer.js needs
// this to extract the current absolute value of every wire field when
// synthesizing a full (non-delta) playerstate at an arbitrary cut point.
function extractPlayerField91(ps, index) {
  switch (index) {
    case 0: return ps.commandTime;
    case 1: return ps.origin[0];
    case 2: return ps.origin[1];
    case 3: return ps.bobCycle;
    case 4: return ps.velocity[0];
    case 5: return ps.velocity[1];
    case 6: return ps.viewangles[1];
    case 7: return ps.viewangles[0];
    case 8: return ps.weaponTime;
    case 9: return ps.origin[2];
    case 10: return ps.velocity[2];
    case 11: return ps.legsTimer;
    case 12: return ps.pm_time;
    case 13: return ps.eventSequence;
    case 14: return ps.torsoAnim;
    case 15: return ps.movementDir;
    case 16: return ps.events[0];
    case 17: return ps.legsAnim;
    case 18: return ps.events[1];
    case 19: return ps.pm_flags;
    case 20: return ps.groundEntityNum;
    case 21: return ps.weaponstate;
    case 22: return ps.eFlags;
    case 23: return ps.externalEvent;
    case 24: return ps.gravity;
    case 25: return ps.speed;
    case 26: return ps.delta_angles[1];
    case 27: return ps.externalEventParm;
    case 28: return ps.viewheight;
    case 29: return ps.damageEvent;
    case 30: return ps.damageYaw;
    case 31: return ps.damagePitch;
    case 32: return ps.damageCount;
    case 33: return ps.generic1;
    case 34: return ps.pm_type;
    case 35: return ps.delta_angles[0];
    case 36: return ps.delta_angles[2];
    case 37: return ps.torsoTimer;
    case 38: return ps.eventParms[0];
    case 39: return ps.eventParms[1];
    case 40: return ps.clientNum;
    case 41: return ps.weapon;
    case 42: return ps.weaponPrimary;
    case 43: return ps.viewangles[2];
    case 44: return ps.grapplePoint[0];
    case 45: return ps.grapplePoint[1];
    case 46: return ps.grapplePoint[2];
    case 47: return ps.jumppad_ent;
    case 48: return ps.loopSound;
    case 49: return ps.jumpTime;
    case 50: return ps.doubleJumped;
    case 51: return ps.crouchTime;
    case 52: return ps.crouchSlideTime;
    case 53: return ps.location;
    case 54: return ps.fov;
    case 55: return ps.forwardmove;
    case 56: return ps.rightmove;
    case 57: return ps.upmove;
    default: return 0;
  }
}

export function extractAllPlayerFields91(ps) {
  const values = new Array(PLAYER_BITS_91.length);
  for (let i = 0; i < PLAYER_BITS_91.length; i++) values[i] = extractPlayerField91(ps, i) || 0;
  return values;
}

/** dm_91 entity delta (UDT RealReadDeltaEntity). Returns { entity, changed } or { entity: null, changed: true }. */
export function readDeltaEntity(msg, huffman, from, number) {
  const base = from ? cloneEntityState(from) : createEntityState();

  if (readBits(msg, huffman, 1) === 1) return { entity: null, changed: true };

  if (readBits(msg, huffman, 1) === 0) {
    const ent = cloneEntityState(base);
    ent.number = number;
    return { entity: ent, changed: false };
  }

  const ent = cloneEntityState(base);
  ent.number = number;
  const lc = huffmanReadByte(msg, huffman);
  if (lc < 0 || lc > ENTITY_BITS_91.length) {
    throw new Error(`entity lc=${lc} max=${ENTITY_BITS_91.length}`);
  }

  for (let i = 0; i < lc; i++) {
    if (readBits(msg, huffman, 1) === 0) continue;
    if (readBits(msg, huffman, 1) === 0) {
      applyEntityField91(ent, i, 0);
      continue;
    }
    applyEntityField91(ent, i, readField(msg, huffman, ENTITY_BITS_91[i]));
  }

  return { entity: ent, changed: true };
}

/**
 * dm_91 playerstate delta (UDT RealReadDeltaPlayer).
 *
 * `from` is legitimately null for the first snapshot(s) after `record` starts
 * mid-connection: the server's delta reference predates what the demo file
 * captured. clientNum almost never gets explicitly redelta'd afterwards
 * (a connected client's own slot doesn't change), so seeding it from a blank
 * `createPlayerState()` (clientNum 0) would leave a wrong clientNum "stuck"
 * for the rest of the demo via clone-forward — fixed by seeding the blank
 * baseline with the connection's real identity instead of 0.
 */
export function readDeltaPlayerState(msg, huffman, from, fallbackClientNum) {
  const ps = from ? clonePlayerState(from) : createPlayerState();
  if (!from && fallbackClientNum != null && fallbackClientNum >= 0) {
    ps.clientNum = fallbackClientNum;
  }
  const lc = huffmanReadByte(msg, huffman);
  if (lc < 0 || lc > PLAYER_BITS_91.length) {
    throw new Error(`playerstate lc=${lc} max=${PLAYER_BITS_91.length}`);
  }

  for (let i = 0; i < lc; i++) {
    if (readBits(msg, huffman, 1) === 0) continue;
    applyPlayerField91(ps, i, readField(msg, huffman, PLAYER_BITS_91[i]));
  }

  if (readBits(msg, huffman, 1)) {
    if (readBits(msg, huffman, 1)) {
      const mask = readBits(msg, huffman, MAX_STATS);
      for (let i = 0; i < MAX_STATS; i++) {
        if (mask & (1 << i)) ps.stats[i] = readBits(msg, huffman, -16);
      }
    }
    if (readBits(msg, huffman, 1)) {
      const mask = readBits(msg, huffman, MAX_PERSISTANT);
      for (let i = 0; i < MAX_PERSISTANT; i++) {
        if (mask & (1 << i)) ps.persistant[i] = huffmanReadShort(msg, huffman);
      }
    }
    if (readBits(msg, huffman, 1)) {
      const mask = readBits(msg, huffman, 16);
      for (let i = 0; i < MAX_WEAPONS; i++) {
        if (mask & (1 << i)) ps.ammo[i] = huffmanReadShort(msg, huffman);
      }
    }
    if (readBits(msg, huffman, 1)) {
      const mask = readBits(msg, huffman, MAX_POWERUPS);
      for (let i = 0; i < MAX_POWERUPS; i++) {
        if (mask & (1 << i)) ps.powerups[i] = huffmanReadLong(msg, huffman);
      }
    }
  }
  return ps;
}

export function clonePlayerState(ps) {
  return {
    ...ps,
    origin: ps.origin.slice(),
    velocity: (ps.velocity || [0, 0, 0]).slice(),
    viewangles: ps.viewangles.slice(),
    events: (ps.events || [0, 0]).slice(),
    delta_angles: (ps.delta_angles || [0, 0, 0]).slice(),
    eventParms: (ps.eventParms || [0, 0]).slice(),
    grapplePoint: (ps.grapplePoint || [0, 0, 0]).slice(),
    stats: ps.stats.slice(),
    persistant: ps.persistant.slice(),
    ammo: ps.ammo.slice(),
    powerups: ps.powerups.slice(),
  };
}

export { cloneEntityState, createEntityState } from "./entity-state.js";
export { createMsgReader };
