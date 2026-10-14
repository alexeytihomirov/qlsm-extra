// Test fixture writer for tests/test_packer_identity.py: synthesizes gamestate-only
// POV .dm_91 files plus index/*.snaps.json that pack.mjs accepts.
// usage: node packer_fixture.mjs <out_dir> <match_id> <spec.json>
// spec: {map, guid, povs: [{client_num, roster: {cn: {n, t}}, index: {...extra index keys}}]}
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

const [outDir, matchId, specPath] = process.argv.slice(2);
const vendor = pathToFileURL(process.argv[1]).href.replace(/tests\/packer_fixture\.mjs$/, "addons/qlmatch-packer/assets/vendor/qldemo/");
const { buildGamestateMessage } = await import(vendor + "test-support/gamestate-writer.js");
const { CS_PLAYERS } = await import(vendor + "constants.js");
const { readFileSync } = await import("node:fs");
const spec = JSON.parse(readFileSync(specPath, "utf8"));

function frame(body) {
  const out = new Uint8Array(8 + body.length + 8);
  const dv = new DataView(out.buffer);
  dv.setInt32(0, 0, true);
  dv.setInt32(4, body.length, true);
  out.set(body, 8);
  dv.setInt32(8 + body.length, -1, true);
  dv.setInt32(12 + body.length, -1, true);
  return out;
}

mkdirSync(join(outDir, "index"), { recursive: true });
for (const pov of spec.povs) {
  const configstrings = { 0: `\\mapname\\${spec.map}\\g_gametype\\1` };
  if (spec.guid) configstrings[712] = spec.guid;
  for (const [cn, row] of Object.entries(pov.roster)) {
    configstrings[CS_PLAYERS + Number(cn)] = `\\n\\${row.n}\\t\\${row.t}`;
  }
  const body = buildGamestateMessage({ configstrings, baselines: [], clientNum: pov.client_num, checksumFeed: 0 });
  const stem = `${matchId}_${spec.map}_p${pov.client_num}_pov${pov.client_num}_1000_1`;
  writeFileSync(join(outDir, stem + ".dm_91"), frame(body));
  const index = {
    client_num: pov.client_num,
    ...pov.index,
    first_server_time: 1000,
    last_server_time: 61000,
    game_start_server_time: 2000,
    snapshots: [],
  };
  writeFileSync(join(outDir, "index", stem + ".snaps.json"), JSON.stringify(index));
}
