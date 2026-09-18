// Minimal ZIP reader (store + deflate-raw). Enough for ql-demo-pack /
// ql-match archives written by zipfile/Compress-Archive. No zip64.
// Canonical home for zip reading shared by dashboard (live-overlay) and
// demo-editor - demo-editor/lib/zip-read.js re-exports from here so
// live-overlay never has to depend on demo-editor.

const EOCD = 0x06054b50;
const CEN = 0x02014b50;
const LOC = 0x04034b50;

function findEocd(view, length) {
  const min = Math.max(0, length - 22 - 65535);
  for (let i = length - 22; i >= min; i--) {
    if (view.getUint32(i, true) === EOCD) return i;
  }
  return -1;
}

// Pipes through DecompressionStream instead of manually
// getWriter().write()/close() then reading stream.readable afterwards - that
// sequence deadlocks for real in at least one real browser's
// DecompressionStream (confirmed live, 2026-08-29, on a .qlmatch with a
// deflated manifest.json - real .qlmatch packs deflate manifest.json while
// leaving the much larger .dm_91 entries STORE-only, so this branch is
// exercised on every real pack, not just a hypothetical). write() awaiting a
// writer nobody is reading from yet is a known backpressure footgun for
// TransformStream-based APIs; pipeThrough lets the platform drive both sides
// concurrently instead of serializing them.
async function inflateRaw(compressed) {
  if (typeof DecompressionStream !== "function") {
    throw new Error("deflate zip needs DecompressionStream");
  }
  const stream = new Blob([compressed]).stream().pipeThrough(new DecompressionStream("deflate-raw"));
  return new Uint8Array(await new Response(stream).arrayBuffer());
}

function basename(path) {
  const parts = String(path).split(/[/\\]/);
  return parts[parts.length - 1] || "";
}

export async function unzipEntries(buffer) {
  const bytes = buffer instanceof Uint8Array ? buffer : new Uint8Array(buffer);
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const eocd = findEocd(view, bytes.byteLength);
  if (eocd < 0) throw new Error("not a zip file");
  const count = view.getUint16(eocd + 10, true);
  let off = view.getUint32(eocd + 16, true);
  const out = [];
  const decoder = new TextDecoder();
  for (let i = 0; i < count; i++) {
    if (view.getUint32(off, true) !== CEN) throw new Error("bad zip central directory");
    const method = view.getUint16(off + 10, true);
    const compSize = view.getUint32(off + 20, true);
    const nameLen = view.getUint16(off + 28, true);
    const extraLen = view.getUint16(off + 30, true);
    const commentLen = view.getUint16(off + 32, true);
    const localOff = view.getUint32(off + 42, true);
    const name = decoder.decode(bytes.subarray(off + 46, off + 46 + nameLen));
    off += 46 + nameLen + extraLen + commentLen;
    if (!name || name.endsWith("/")) continue;
    if (view.getUint32(localOff, true) !== LOC) throw new Error("bad zip local header");
    const locNameLen = view.getUint16(localOff + 26, true);
    const locExtraLen = view.getUint16(localOff + 28, true);
    const dataStart = localOff + 30 + locNameLen + locExtraLen;
    const compressed = bytes.subarray(dataStart, dataStart + compSize);
    let raw;
    if (method === 0) raw = compressed.slice();
    else if (method === 8) raw = await inflateRaw(compressed);
    else throw new Error("unsupported zip method " + method);
    out.push({ name: basename(name), path: name, bytes: raw });
  }
  return out;
}

export function isPackFileName(name) {
  const lower = String(name || "").toLowerCase();
  return lower.endsWith(".zip") || lower.endsWith(".qlpack") || lower.endsWith(".qlmatch");
}

export function findZipEntry(entries, name) {
  const want = String(name || "").replace(/\\/g, "/");
  if (!want) return null;
  const base = want.split("/").pop();
  return (
    entries.find((e) => (e.path || e.name).replace(/\\/g, "/") === want) ||
    entries.find((e) => e.name === base) ||
    null
  );
}
