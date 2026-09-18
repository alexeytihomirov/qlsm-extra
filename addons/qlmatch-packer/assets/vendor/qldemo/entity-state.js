import { GENTITYNUM_BITS } from "./constants.js";

/** dm_91 entityState net fields (UDT EntityStateFields91). */
export const ENTITY_BITS_91 = [
  32, 0, 0, 0, 0, 0, 0, 0, 0, 32, 10, 0, 8, 8, 8, 8, GENTITYNUM_BITS, 8, 19, GENTITYNUM_BITS, 8, 8, 0, 32, 8, 0, 0, 0,
  24, 16, 8, GENTITYNUM_BITS, 8, 8, 0, 0, 0, 8, 0, 32, 32, 32, 0, 0, 0, 0, 32, 32, 0, 0, 0, 32, 16, 32, 1, 16, 16, 8,
];

export const TR_STATIONARY = 0;
export const TR_LINEAR = 1;
export const TR_LINEAR_STOP = 2;
export const TR_SINE = 3;
export const TR_GRAVITY = 4;
export const TR_INTERPOLATE = 5;

/** dm_91 entity flags (UDT look_up_tables EntityFlag). */
export const EF_DEAD = 1;
export const EF_NODRAW = 1 << 7;
export const EF_FIRING = 1 << 8;

export const MAX_WORLD_COORD = 8192;

export function createTrajectory() {
  return {
    trType: 0,
    trTime: 0,
    trDuration: 0,
    trBase: [0, 0, 0],
    trDelta: [0, 0, 0],
    gravity: 0,
  };
}

export function createEntityState() {
  return {
    number: 0,
    eType: 0,
    eFlags: 0,
    origin: [0, 0, 0],
    origin2: [0, 0, 0],
    angles: [0, 0, 0],
    angles2: [0, 0, 0],
    pos: createTrajectory(),
    apos: createTrajectory(),
    pos_gravity: 0,
    apos_gravity: 0,
    modelindex: 0,
    modelindex2: 0,
    clientNum: 0,
    weapon: 0,
    event: 0,
    eventParm: 0,
    solid: 0,
    powerups: 0,
    groundEntityNum: 0,
    otherEntityNum: 0,
    otherEntityNum2: 0,
    torsoAnim: 0,
    legsAnim: 0,
    loopSound: 0,
    generic1: 0,
    time: 0,
    time2: 0,
    constantLight: 0,
    frame: 0,
    jumpTime: 0,
    doubleJumped: 0,
    health: 0,
    armor: 0,
    location: 0,
  };
}

export function applyEntityField91(ent, index, value) {
  switch (index) {
    case 0:
      ent.pos.trTime = value;
      return;
    case 1:
      ent.pos.trBase[0] = value;
      return;
    case 2:
      ent.pos.trBase[1] = value;
      return;
    case 3:
      ent.pos.trDelta[0] = value;
      return;
    case 4:
      ent.pos.trDelta[1] = value;
      return;
    case 5:
      ent.pos.trBase[2] = value;
      return;
    case 6:
      ent.apos.trBase[1] = value;
      return;
    case 7:
      ent.pos.trDelta[2] = value;
      return;
    case 8:
      ent.apos.trBase[0] = value;
      return;
    case 9:
      ent.pos_gravity = value;
      return;
    case 10:
      ent.event = value;
      return;
    case 11:
      ent.angles2[1] = value;
      return;
    case 12:
      ent.eType = value;
      return;
    case 13:
      ent.torsoAnim = value;
      return;
    case 14:
      ent.eventParm = value;
      return;
    case 15:
      ent.legsAnim = value;
      return;
    case 16:
      ent.groundEntityNum = value;
      return;
    case 17:
      ent.pos.trType = value;
      return;
    case 18:
      ent.eFlags = value;
      return;
    case 19:
      ent.otherEntityNum = value;
      return;
    case 20:
      ent.weapon = value;
      return;
    case 21:
      ent.clientNum = value;
      return;
    case 22:
      ent.angles[1] = value;
      return;
    case 23:
      ent.pos.trDuration = value;
      return;
    case 24:
      ent.apos.trType = value;
      return;
    case 25:
      ent.origin[0] = value;
      return;
    case 26:
      ent.origin[1] = value;
      return;
    case 27:
      ent.origin[2] = value;
      return;
    case 28:
      ent.solid = value;
      return;
    case 29:
      ent.powerups = value;
      return;
    case 30:
      ent.modelindex = value;
      return;
    case 31:
      ent.otherEntityNum2 = value;
      return;
    case 32:
      ent.loopSound = value;
      return;
    case 33:
      ent.generic1 = value;
      return;
    case 34:
      ent.origin2[2] = value;
      return;
    case 35:
      ent.origin2[0] = value;
      return;
    case 36:
      ent.origin2[1] = value;
      return;
    case 37:
      ent.modelindex2 = value;
      return;
    case 38:
      ent.angles[0] = value;
      return;
    case 39:
      ent.time = value;
      return;
    case 40:
      ent.apos.trTime = value;
      return;
    case 41:
      ent.apos.trDuration = value;
      return;
    case 42:
      ent.apos.trBase[2] = value;
      return;
    case 43:
      ent.apos.trDelta[0] = value;
      return;
    case 44:
      ent.apos.trDelta[1] = value;
      return;
    case 45:
      ent.apos.trDelta[2] = value;
      return;
    case 46:
      ent.apos_gravity = value;
      return;
    case 47:
      ent.time2 = value;
      return;
    case 48:
      ent.angles[2] = value;
      return;
    case 49:
      ent.angles2[0] = value;
      return;
    case 50:
      ent.angles2[2] = value;
      return;
    case 51:
      ent.constantLight = value;
      return;
    case 52:
      ent.frame = value;
      return;
    case 53:
      ent.jumpTime = value;
      return;
    case 54:
      ent.doubleJumped = value;
      return;
    case 55:
      ent.health = value;
      return;
    case 56:
      ent.armor = value;
      return;
    case 57:
      ent.location = value;
      return;
    default:
      return;
  }
}

export function cloneTrajectory(tr) {
  return {
    trType: tr.trType,
    trTime: tr.trTime,
    trDuration: tr.trDuration,
    trBase: tr.trBase.slice(),
    trDelta: tr.trDelta.slice(),
    gravity: tr.gravity,
  };
}

export function cloneEntityState(ent) {
  return {
    ...ent,
    origin: ent.origin.slice(),
    origin2: ent.origin2.slice(),
    angles: ent.angles.slice(),
    angles2: ent.angles2.slice(),
    pos: cloneTrajectory(ent.pos),
    apos: cloneTrajectory(ent.apos),
  };
}

/** World origin at server time (UDT viewer trajectory). */
export function entityOriginAt(ent, serverTimeMs) {
  const tr = ent.pos;
  if (tr.trType !== TR_STATIONARY && tr.trType !== TR_INTERPOLATE) {
    const out = [0, 0, 0];
    const dtSec = (serverTimeMs - tr.trTime) / 1000;
    switch (tr.trType) {
      case TR_LINEAR:
        out[0] = tr.trBase[0] + tr.trDelta[0] * dtSec;
        out[1] = tr.trBase[1] + tr.trDelta[1] * dtSec;
        out[2] = tr.trBase[2] + tr.trDelta[2] * dtSec;
        return out;
      case TR_LINEAR_STOP: {
        let t = serverTimeMs;
        if (tr.trDuration > 0 && t > tr.trTime + tr.trDuration) t = tr.trTime + tr.trDuration;
        const d = Math.max(0, (t - tr.trTime) * 0.001);
        return [tr.trBase[0] + tr.trDelta[0] * d, tr.trBase[1] + tr.trDelta[1] * d, tr.trBase[2] + tr.trDelta[2] * d];
      }
      case TR_GRAVITY: {
        const d = (serverTimeMs - tr.trTime) * 0.001;
        const g = tr.gravity || ent.pos_gravity || 800;
        return [
          tr.trBase[0] + tr.trDelta[0] * d,
          tr.trBase[1] + tr.trDelta[1] * d,
          tr.trBase[2] + tr.trDelta[2] * d - 0.5 * g * d * d,
        ];
      }
      case TR_SINE: {
        const phase = Math.sin(((serverTimeMs - tr.trTime) / (tr.trDuration || 1)) * Math.PI * 2);
        return [
          tr.trBase[0] + tr.trDelta[0] * phase,
          tr.trBase[1] + tr.trDelta[1] * phase,
          tr.trBase[2] + tr.trDelta[2] * phase,
        ];
      }
      default:
        break;
    }
  }
  return [tr.trBase[0], tr.trBase[1], tr.trBase[2]];
}

export function entityVelocity(ent) {
  if (ent.pos.trType === TR_LINEAR || ent.pos.trType === TR_GRAVITY || ent.pos.trType === TR_LINEAR_STOP) {
    return [ent.pos.trDelta[0], ent.pos.trDelta[1], ent.pos.trDelta[2]];
  }
  return [0, 0, 0];
}

export function isSaneWorldOrigin(x, y, z) {
  return (
    Math.abs(Number(x)) <= MAX_WORLD_COORD &&
    Math.abs(Number(y)) <= MAX_WORLD_COORD &&
    Math.abs(Number(z)) <= MAX_WORLD_COORD
  );
}

/** UDT utils.cpp PlayerStateToEntityState (extrapolate=false for demo viewer). */
export function playerStateToEntityState(ps, clientNum, serverTimeMs, extrapolate = false) {
  const es = createEntityState();
  if (!ps) return es;

  const health = ps.stats?.[0] ?? 100;
  es.eType = 1; // ET_PLAYER
  es.number = clientNum != null ? clientNum : ps.clientNum;
  es.clientNum = clientNum != null ? clientNum : ps.clientNum;

  es.pos.trBase[0] = ps.origin[0];
  es.pos.trBase[1] = ps.origin[1];
  es.pos.trBase[2] = ps.origin[2];
  es.pos.trDelta[0] = ps.velocity?.[0] ?? 0;
  es.pos.trDelta[1] = ps.velocity?.[1] ?? 0;
  es.pos.trDelta[2] = ps.velocity?.[2] ?? 0;
  if (extrapolate) {
    es.pos.trType = TR_LINEAR_STOP;
    es.pos.trTime = serverTimeMs;
    es.pos.trDuration = 50;
  } else {
    es.pos.trType = TR_INTERPOLATE;
  }

  es.apos.trType = TR_INTERPOLATE;
  es.apos.trBase[0] = ps.viewangles?.[0] ?? 0;
  es.apos.trBase[1] = ps.viewangles?.[1] ?? 0;
  es.apos.trBase[2] = ps.viewangles?.[2] ?? 0;
  es.weapon = ps.weapon || 0;
  es.health = health >= 0 && health < 500 ? health : 0;
  const armor = ps.stats?.[4];
  es.armor = armor >= 0 && armor < 500 ? armor : 0;
  if (health <= 0) es.eFlags |= EF_DEAD;

  let powerups = 0;
  for (let i = 0; i < (ps.powerups?.length || 0); i++) {
    if (ps.powerups[i]) powerups |= 1 << i;
  }
  es.powerups = powerups;
  return es;
}
