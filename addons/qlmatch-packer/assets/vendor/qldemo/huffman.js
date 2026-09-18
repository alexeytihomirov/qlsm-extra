/**
 * Q3/QL demo MSG bitstream reader — static Huffman tree (QLDT / mwvdev q3demo).
 */
import staticTree from "./static-huff-tree.json" with { type: "json" };

const INTERNAL_NODE = 257;

function getBit(buffer, blocRef) {
  const bloc = blocRef.value;
  if ((bloc >> 3) >= buffer.length) return 0;
  const t = (buffer[bloc >> 3] >> (bloc & 7)) & 1;
  blocRef.value = bloc + 1;
  return t;
}

function decodeByte(buffer, blocRef) {
  let idx = 2;
  while (idx != null) {
    const node = staticTree[idx];
    if (!node || node.s !== INTERNAL_NODE) return node?.s ?? 0;
    idx = getBit(buffer, blocRef) ? node.r : node.l;
  }
  return 0;
}

export function createDemoMsgHuffman() {
  return { static: true };
}

export function readBits(msg, _huffman, bits) {
  let value = 0;
  let nbits = 0;
  let sign = false;
  if (bits < 0) {
    bits = -bits;
    sign = true;
  }
  if (bits & 7) {
    nbits = bits & 7;
    for (let i = 0; i < nbits; i++) value |= getBit(msg.data, msg.bit) << i;
    bits -= nbits;
  }
  if (bits) {
    for (let i = 0; i < bits; i += 8) {
      const ch = decodeByte(msg.data, msg.bit);
      value |= ch << (i + nbits);
    }
  }
  msg.readcount = (msg.bit.value >> 3) + 1;
  if (sign && bits + nbits < 32 && value & (1 << (bits + nbits - 1))) {
    value |= -1 ^ ((1 << (bits + nbits)) - 1);
  }
  return value;
}

export function huffmanReadByte(msg, huffman) {
  return readBits(msg, huffman, 8) & 0xff;
}

export function huffmanReadShort(msg, huffman) {
  return readBits(msg, huffman, 16);
}

export function huffmanReadLong(msg, huffman) {
  return readBits(msg, huffman, 32) | 0;
}

export function huffmanReadFloat(msg, huffman) {
  const bytes = new Uint8Array(4);
  for (let i = 0; i < 4; i++) bytes[i] = huffmanReadByte(msg, huffman) & 0xff;
  return new DataView(bytes.buffer).getFloat32(0, true);
}

export function huffmanReadString(msg, huffman, maxLen = 1024) {
  // Keep UTF-8 bytes (QL chat/nicks). Only '%' → '.' (fmt-spec safety).
  // Same policy as live-overlay qldemo + wolfcamql patch 0032: do not clamp
  // bytes >127 to '.' (old ioq3 habit). BigString stays latin-1-per-byte so
  // pack.mjs decodeQlString can re-decode configstring names safely.
  const bytes = [];
  for (let i = 0; i < maxLen; i++) {
    const c = huffmanReadByte(msg, huffman);
    if (c === -1 || c === 0) break;
    bytes.push(c === 37 ? 46 : c);
  }
  return new TextDecoder("utf-8", { fatal: false }).decode(Uint8Array.from(bytes));
}

export function huffmanReadBigString(msg, huffman, maxLen = 8192) {
  let out = "";
  for (let i = 0; i < maxLen; i++) {
    const c = huffmanReadByte(msg, huffman);
    if (c === -1 || c === 0) break;
    out += String.fromCharCode(c === 37 ? 46 : c);
  }
  return out;
}

export function createMsgReader(data, huffman) {
  return { data, bit: { value: 0 }, cursize: data.length, readcount: 0, huffman };
}
