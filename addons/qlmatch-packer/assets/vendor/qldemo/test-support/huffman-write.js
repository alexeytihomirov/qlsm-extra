// Test support only. Carried from ql-stream-tools@31fd6c0 (demo-editor/lib/huffman-write.js), archived 2026-10-14:
// the encode-side mirror of this parser, used to build wire-format fixtures. Changes: imports point at
// the parser next to it, em and en dashes are hyphens. Not used by pack.mjs or the addon at run time.
import staticTree from "../static-huff-tree.json" with { type: "json" };
import { FLOAT_INT_BITS, FLOAT_INT_BIAS } from "../constants.js";

const INTERNAL_NODE = 257;
const HUFF_ROOT = 2;

let cachedTable = null;

// Walks the same static decode tree vendor/qldemo/huffman.js's
// decodeByte() reads (root at index 2, node.s === 257 marks an internal
// node, node.l/node.r are child indices reached by bit 0/1 respectively -
// matching decodeByte's `idx = getBit() ? node.r : node.l`), recording the
// bit path to each leaf byte value. This is the encode-side mirror of that
// same tree: to encode a byte, write the bits on its recorded path.
export function buildEncodeTable() {
  if (cachedTable) return cachedTable;
  const table = new Array(256);
  function walk(idx, path) {
    const node = staticTree[idx];
    if (!node) return;
    if (node.s !== INTERNAL_NODE) {
      if (node.s >= 0 && node.s < 256) table[node.s] = path;
      return;
    }
    if (node.l != null) walk(node.l, [...path, 0]);
    if (node.r != null) walk(node.r, [...path, 1]);
  }
  walk(HUFF_ROOT, []);
  cachedTable = table;
  return table;
}

export function createMsgWriter(initialCapacity = 1024) {
  return { data: new Uint8Array(initialCapacity), bit: { value: 0 } };
}

function ensureCapacity(writer, neededBytes) {
  if (neededBytes <= writer.data.length) return;
  let newLen = writer.data.length * 2;
  while (newLen < neededBytes) newLen *= 2;
  const next = new Uint8Array(newLen);
  next.set(writer.data);
  writer.data = next;
}

// Mirrors huffman.js's getBit() exactly: LSB-first within each byte,
// sequential bit position tracked the same way (msg.bit.value there,
// writer.bit.value here).
function putBit(writer, bit) {
  const bloc = writer.bit.value;
  const byteIndex = bloc >> 3;
  ensureCapacity(writer, byteIndex + 1);
  if (bit) writer.data[byteIndex] |= 1 << (bloc & 7);
  else writer.data[byteIndex] &= ~(1 << (bloc & 7));
  writer.bit.value = bloc + 1;
}

function encodeByte(writer, table, byteValue) {
  const path = table[byteValue & 0xff];
  for (let i = 0; i < path.length; i++) putBit(writer, path[i]);
}

// Mirrors huffman.js's readBits() exactly: the low (bits & 7) bits are
// written raw (uncompressed), then the remaining bits are written 8 at a
// time via the Huffman tree - same split, same order, just the write
// direction instead of read.
export function writeBits(writer, table, value, bits) {
  if (bits < 0) bits = -bits; // sign only changes how the READER interprets the value on the way back out - the bit pattern written is identical either way (two's complement), matching readBits' own symmetric handling.
  const nbits = bits & 7;
  let shift = 0;
  if (nbits) {
    for (let i = 0; i < nbits; i++) putBit(writer, (value >>> (shift + i)) & 1);
    shift += nbits;
  }
  const remaining = bits - nbits;
  for (let i = 0; i < remaining; i += 8) {
    encodeByte(writer, table, (value >>> shift) & 0xff);
    shift += 8;
  }
}

export function huffmanWriteByte(writer, table, value) {
  writeBits(writer, table, value & 0xff, 8);
}

export function huffmanWriteShort(writer, table, value) {
  writeBits(writer, table, value & 0xffff, 16);
}

export function huffmanWriteLong(writer, table, value) {
  writeBits(writer, table, value | 0, 32);
}

export function writeFloatQ3(writer, table, value) {
  const biased = Math.round(value) + FLOAT_INT_BIAS;
  if (Number.isInteger(value) && biased >= 0 && biased < 1 << FLOAT_INT_BITS) {
    writeBits(writer, table, 0, 1);
    writeBits(writer, table, biased, FLOAT_INT_BITS);
    return;
  }
  writeBits(writer, table, 1, 1);
  const buf = new ArrayBuffer(4);
  new DataView(buf).setFloat32(0, value, true);
  writeBits(writer, table, new DataView(buf).getInt32(0, true), 32);
}

export function writeField(writer, table, value, bits) {
  if (bits === 0) {
    writeFloatQ3(writer, table, value);
    return;
  }
  writeBits(writer, table, value, bits);
}

// Closes a written message and returns its bytes, sized the way the real
// engine sizes one.
//
// msg.c MSG_WriteBits ends with `msg->cursize = (msg->bit >> 3) + 1` - ALWAYS
// one more byte than the last bit touched, so a message whose final bit lands
// exactly on a byte boundary still carries a trailing (all-zero) byte.
//
// Using Math.ceil(bit / 8) instead looks equivalent and is not: when bit is a
// multiple of 8 it produces one byte LESS. The reader then blows up on the
// message's own terminating svc_EOF - MSG_ReadBits sets
// `readcount = (bit >> 3) + 1`, MSG_ReadByte returns -1 whenever
// `readcount > cursize`, so the EOF byte reads back as -1 and the engine dies
// with "Illegible server message -1" (seen in WolfcamQL's CL_PeekSnapshot).
// It hits roughly one message in eight - exactly the ones that land flush on a
// byte boundary - which is why a demo can look fine to a lenient parser and
// still be unplayable.
export function finishMessage(writer) {
  const size = (writer.bit.value >> 3) + 1;
  if (size > writer.data.length) {
    const padded = new Uint8Array(size);
    padded.set(writer.data);
    return padded;
  }
  return writer.data.slice(0, size);
}

export function huffmanWriteString(writer, table, str, maxLen = 1024) {
  const len = Math.min(str.length, maxLen);
  for (let i = 0; i < len; i++) huffmanWriteByte(writer, table, str.charCodeAt(i) & 0xff);
  huffmanWriteByte(writer, table, 0);
}

export function huffmanWriteBigString(writer, table, str, maxLen = 8192) {
  const len = Math.min(str.length, maxLen);
  for (let i = 0; i < len; i++) huffmanWriteByte(writer, table, str.charCodeAt(i) & 0xff);
  huffmanWriteByte(writer, table, 0);
}
