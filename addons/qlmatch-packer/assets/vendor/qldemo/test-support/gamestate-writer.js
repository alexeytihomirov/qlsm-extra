// Test support only. Carried from ql-stream-tools@31fd6c0 (demo-editor/lib/gamestate-writer.js), archived 2026-10-14:
// the encode-side mirror of this parser, used to build wire-format fixtures. Changes: imports point at
// the parser next to it, em and en dashes are hyphens. Not used by pack.mjs or the addon at run time.
import { GENTITYNUM_BITS } from "../constants.js";
import { ENTITY_BITS_91 } from "../entity-state.js";
import {
  buildEncodeTable,
  createMsgWriter,
  writeBits,
  huffmanWriteByte,
  huffmanWriteLong,
  huffmanWriteShort,
  huffmanWriteBigString,
  writeField,
  finishMessage,
} from "./huffman-write.js";

const SVC_GAMESTATE = 2;
const SVC_CONFIGSTRING = 3;
const SVC_BASELINE = 4;
const SVC_EOF = 8;

// Exact inverse of vendor/qldemo/entity-state.js's
// applyEntityField91() switch statement - same 58 cases, same field
// order, just extracting a value instead of assigning one. Must stay in
// lockstep with that function; if it ever gains/changes a case, this must
// change identically.
function extractEntityField91(ent, index) {
  switch (index) {
    case 0: return ent.pos.trTime;
    case 1: return ent.pos.trBase[0];
    case 2: return ent.pos.trBase[1];
    case 3: return ent.pos.trDelta[0];
    case 4: return ent.pos.trDelta[1];
    case 5: return ent.pos.trBase[2];
    case 6: return ent.apos.trBase[1];
    case 7: return ent.pos.trDelta[2];
    case 8: return ent.apos.trBase[0];
    case 9: return ent.pos_gravity;
    case 10: return ent.event;
    case 11: return ent.angles2[1];
    case 12: return ent.eType;
    case 13: return ent.torsoAnim;
    case 14: return ent.eventParm;
    case 15: return ent.legsAnim;
    case 16: return ent.groundEntityNum;
    case 17: return ent.pos.trType;
    case 18: return ent.eFlags;
    case 19: return ent.otherEntityNum;
    case 20: return ent.weapon;
    case 21: return ent.clientNum;
    case 22: return ent.angles[1];
    case 23: return ent.pos.trDuration;
    case 24: return ent.apos.trType;
    case 25: return ent.origin[0];
    case 26: return ent.origin[1];
    case 27: return ent.origin[2];
    case 28: return ent.solid;
    case 29: return ent.powerups;
    case 30: return ent.modelindex;
    case 31: return ent.otherEntityNum2;
    case 32: return ent.loopSound;
    case 33: return ent.generic1;
    case 34: return ent.origin2[2];
    case 35: return ent.origin2[0];
    case 36: return ent.origin2[1];
    case 37: return ent.modelindex2;
    case 38: return ent.angles[0];
    case 39: return ent.time;
    case 40: return ent.apos.trTime;
    case 41: return ent.apos.trDuration;
    case 42: return ent.apos.trBase[2];
    case 43: return ent.apos.trDelta[0];
    case 44: return ent.apos.trDelta[1];
    case 45: return ent.apos.trDelta[2];
    case 46: return ent.apos_gravity;
    case 47: return ent.time2;
    case 48: return ent.angles[2];
    case 49: return ent.angles2[0];
    case 50: return ent.angles2[2];
    case 51: return ent.constantLight;
    case 52: return ent.frame;
    case 53: return ent.jumpTime;
    case 54: return ent.doubleJumped;
    case 55: return ent.health;
    case 56: return ent.armor;
    case 57: return ent.location;
    default: return 0;
  }
}

export function extractAllEntityFields91(ent) {
  const values = new Array(ENTITY_BITS_91.length);
  for (let i = 0; i < ENTITY_BITS_91.length; i++) values[i] = extractEntityField91(ent, i) || 0;
  return values;
}

const ZERO_ENTITY_FIELDS = new Array(ENTITY_BITS_91.length).fill(0);

// Writes one entity's [removed=0][hasDelta=1][lc][fields...] body - the part
// of a delta-encoded entity that comes AFTER its entity number (written
// separately by callers: SVC_BASELINE embeds it via writeDeltaEntityFull
// below; demo-editor/lib/snapshot-writer.js's packetEntities writer embeds
// it after its own GENTITYNUM_BITS newNum, exactly mirroring how
// vendor/qldemo/demo-parser.js's parsePacketEntities() reads
// newNum itself before calling readDeltaEntity()).
//
// `baseFieldValues` is the reference state each field is deltaed against -
// all-zero for a gamestate baseline (see writeDeltaEntityFull), but the
// entity's REAL baseline for a synthesized mid-demo full snapshot (an
// entity's baseline origin is rarely all-zero, so diffing against zero
// there would make every field "changed" and, worse, mark fields the real
// baseline already covers as needing values they don't have here). Mirrors
// vendor/qldemo/delta.js's readDeltaEntity() bit-for-bit: bit 1 =
// changed from base (0 = keep base's cloned value, matching the reader's
// `continue` that leaves `ent` as clone(base)); if changed, bit 2 = "new
// value is exactly 0" (0 = apply zero, no further bits; 1 = full field
// value follows).
export function writeDeltaEntityFields(writer, table, fieldValues, baseFieldValues) {
  let lc = 0;
  for (let i = 0; i < fieldValues.length; i++) {
    if (fieldValues[i] !== baseFieldValues[i]) lc = i + 1;
  }
  writeBits(writer, table, 0, 1); // not removed
  writeBits(writer, table, 1, 1); // has delta
  huffmanWriteByte(writer, table, lc);
  for (let i = 0; i < lc; i++) {
    const value = fieldValues[i];
    if (value === baseFieldValues[i]) {
      writeBits(writer, table, 0, 1); // unchanged from base
      continue;
    }
    writeBits(writer, table, 1, 1); // changed
    if (value === 0) {
      writeBits(writer, table, 0, 1); // new value is exactly 0
    } else {
      writeBits(writer, table, 1, 1); // new value follows
      writeField(writer, table, value, ENTITY_BITS_91[i]);
    }
  }
}

// Writes one entity as a "full" baseline delta - matches UDT's
// WriteDeltaEntity(&nullState, &newState, force=true) (see this project's
// implementation-plan protocol background section for the source trace).
// Every field defaults to "unchanged from the null/all-zero base" unless
// it's genuinely non-zero. Used for SVC_BASELINE, whose real reference is
// always the implicit all-zero nullstate (matches
// vendor/qldemo/demo-parser.js's parseGamestate(), which passes
// `from: null` into readDeltaEntity for every SVC_BASELINE).
export function writeDeltaEntityFull(writer, table, entityNumber, fieldValues) {
  writeBits(writer, table, entityNumber, GENTITYNUM_BITS);
  writeDeltaEntityFields(writer, table, fieldValues, ZERO_ENTITY_FIELDS);
}

export function buildGamestateMessage({
  configstrings,
  baselines,
  clientNum,
  checksumFeed,
  reliableSequenceAcknowledge = 0,
  serverCommandSequence = 0,
}) {
  const table = buildEncodeTable();
  const writer = createMsgWriter();

  huffmanWriteLong(writer, table, reliableSequenceAcknowledge);

  huffmanWriteByte(writer, table, SVC_GAMESTATE);
  huffmanWriteLong(writer, table, serverCommandSequence);

  for (const [indexStr, text] of Object.entries(configstrings)) {
    if (!text) continue;
    huffmanWriteByte(writer, table, SVC_CONFIGSTRING);
    huffmanWriteShort(writer, table, Number(indexStr));
    huffmanWriteBigString(writer, table, text);
  }

  for (let num = 0; num < baselines.length; num++) {
    const entity = baselines[num];
    if (!entity) continue;
    const fieldValues = extractAllEntityFields91(entity);
    if (fieldValues.every((v) => v === 0)) continue; // matches UDT's memcmp-against-null-state skip
    huffmanWriteByte(writer, table, SVC_BASELINE);
    writeDeltaEntityFull(writer, table, num, fieldValues);
  }

  huffmanWriteByte(writer, table, SVC_EOF);
  huffmanWriteLong(writer, table, clientNum);
  huffmanWriteLong(writer, table, checksumFeed);
  huffmanWriteByte(writer, table, SVC_EOF);

  return finishMessage(writer);
}
