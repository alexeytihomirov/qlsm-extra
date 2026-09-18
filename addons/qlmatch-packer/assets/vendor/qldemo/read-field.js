import { FLOAT_INT_BITS, FLOAT_INT_BIAS } from "./constants.js";
import { readBits } from "./huffman.js";

export function readFloatQ3(msg, huffman) {
  if (readBits(msg, huffman, 1)) {
    const bits = readBits(msg, huffman, 32);
    const bytes = new ArrayBuffer(4);
    new DataView(bytes).setInt32(0, bits, true);
    return new DataView(bytes).getFloat32(0, true);
  }
  return readBits(msg, huffman, FLOAT_INT_BITS) - FLOAT_INT_BIAS;
}

export function readField(msg, huffman, bits) {
  if (bits === 0) return readFloatQ3(msg, huffman);
  return readBits(msg, huffman, bits);
}
