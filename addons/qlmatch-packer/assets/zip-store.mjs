// Minimal zip writer, STORE only (no compression) — the .qlmatch contract
// (ql-demo-recorder/docs/superpowers/prompts/
// 2026-08-17-sv-demorecord-multi-pov-AGENT-PROMPT.md) explicitly allows
// STORE, and .dm_91 payloads are dense binary that barely compresses.
// Descended from the _tmp/overkilldemos/zip-store.mjs prototype with one
// real fix: that prototype wrote 0 into every CRC-32 field, which
// demo-editor's own zip-read.js never checks but Python's zipfile / unzip
// do — a pack delivered to any other consumer via rclone would fail CRC
// validation there. This writer computes real CRC-32s.

const CRC_TABLE = (() => {
  const table = new Uint32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    table[n] = c;
  }
  return table;
})();

export function crc32(buf) {
  let c = 0xffffffff;
  for (let i = 0; i < buf.length; i++) c = CRC_TABLE[(c ^ buf[i]) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

function u16(n) {
  const b = Buffer.alloc(2);
  b.writeUInt16LE(n);
  return b;
}
function u32(n) {
  const b = Buffer.alloc(4);
  b.writeUInt32LE(n >>> 0);
  return b;
}

export function zipSync(files) {
  const locals = [];
  const centrals = [];
  let offset = 0;
  for (const { name, data } of files) {
    const nameBytes = Buffer.from(name, "utf8");
    const body = Buffer.isBuffer(data) ? data : Buffer.from(data);
    const crc = crc32(body);
    const local = Buffer.concat([
      u32(0x04034b50),
      u16(20), // version needed
      u16(0), // flags
      u16(0), // method: STORE
      u16(0), // mod time
      u16(0), // mod date
      u32(crc),
      u32(body.length),
      u32(body.length),
      u16(nameBytes.length),
      u16(0),
      nameBytes,
      body,
    ]);
    const central = Buffer.concat([
      u32(0x02014b50),
      u16(20), // version made by
      u16(20), // version needed
      u16(0), // flags
      u16(0), // method: STORE
      u16(0), // mod time
      u16(0), // mod date
      u32(crc),
      u32(body.length),
      u32(body.length),
      u16(nameBytes.length),
      u16(0), // extra len
      u16(0), // comment len
      u16(0), // disk number
      u16(0), // internal attrs
      u32(0), // external attrs
      u32(offset),
      nameBytes,
    ]);
    locals.push(local);
    centrals.push(central);
    offset += local.length;
  }
  const localBlob = Buffer.concat(locals);
  const centralBlob = Buffer.concat(centrals);
  const eocd = Buffer.concat([
    u32(0x06054b50),
    u16(0),
    u16(0),
    u16(files.length),
    u16(files.length),
    u32(centralBlob.length),
    u32(localBlob.length),
    u16(0),
  ]);
  return Buffer.concat([localBlob, centralBlob, eocd]);
}
