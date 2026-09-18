// Reads a .qlmatch (or legacy ql-demo-pack) archive into raw per-POV bytes.
// Env-agnostic (Node Buffer or browser ArrayBuffer/Uint8Array) so both the
// qlmatch-to-replay CLI and the dashboard's #/demo fallback parser can share
// it - unlike demo-editor/lib/demo-pack.js, this never touches the DOM File
// API, it only deals in bytes.

import { findZipEntry, unzipEntries } from "./zip-read.js?v=20260829a";

const PACK_FORMATS = new Set(["ql-demo-pack", "ql-match"]);

function basename(path) {
  return String(path || "").split(/[/\\]/).pop() || "";
}

function isPlayableDemoName(name) {
  const lower = String(name || "").toLowerCase();
  return lower.endsWith(".dm_91") && !lower.endsWith("_merged.dm_91");
}

/**
 * @returns {Promise<{manifest: object, format: string, demos: Array<{
 *   fileName: string, bytes: Uint8Array, povIndex: number|null,
 *   clientNum: number|null, name: string|null, index: object|null
 * }>}>}
 */
export async function unpackQlMatch(bytesLike) {
  const entries = await unzipEntries(bytesLike);
  const manifestEntry = findZipEntry(entries, "manifest.json");
  if (!manifestEntry) throw new Error("qlmatch pack has no manifest.json");
  const manifest = JSON.parse(new TextDecoder().decode(manifestEntry.bytes));
  if (manifest.format && !PACK_FORMATS.has(manifest.format)) {
    throw new Error("unsupported pack format: " + manifest.format);
  }
  const demoSpecs = Array.isArray(manifest.demos)
    ? manifest.demos
        .map((item) => (typeof item === "string" ? { file: item } : item))
        .filter((item) => item && item.file)
    : [];

  const demos = [];
  for (const spec of demoSpecs) {
    const base = basename(spec.file);
    const entry = findZipEntry(entries, spec.file);
    if (!entry || !isPlayableDemoName(base)) continue;
    let index = null;
    if (spec.index) {
      const indexEntry = findZipEntry(entries, spec.index);
      if (indexEntry) {
        try {
          index = JSON.parse(new TextDecoder().decode(indexEntry.bytes));
        } catch {
          index = null;
        }
      }
    }
    demos.push({
      fileName: base,
      bytes: entry.bytes,
      povIndex: Number.isInteger(spec.pov_index) ? spec.pov_index : null,
      clientNum: Number.isInteger(spec.client_num) ? spec.client_num : null,
      name: spec.name || null,
      index,
    });
  }
  if (!demos.length) throw new Error("qlmatch pack has no playable demos");
  return { manifest, format: manifest.format || "ql-match", demos };
}
