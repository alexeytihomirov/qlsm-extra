#!/usr/bin/env node
// CLI: qlmatch-to-replay.mjs <file.qlmatch> [-o out.replay.json.gz]
//
// Game-host twin of ql-stream-tools/scripts/qlmatch-to-replay.mjs, importing
// the vendored parser (vendor/qldemo) instead of the live-overlay checkout.
// (Re)generates the replay-v2 sidecar for a .qlmatch pack - the gzipped
// {match_id}_{map}.replay.json.gz file next to the pack that
// restore/qlmatch.py (!restore match) and the dashboard's #/demo view
// consume instead of parsing all N POV .dm_91 themselves. Idempotent:
// re-running on the same pack produces byte-identical output (see
// match-to-replay.js's MATCH_REPLAY_GENERATOR_VERSION for detecting a stale
// sidecar produced by an older algorithm). Called by pack.mjs after it
// finishes writing a pack; safe to run by hand for older packs.
import { gzipSync } from "node:zlib";
import { readFileSync, writeFileSync, renameSync } from "node:fs";
import { basename, dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const LIB = join(__dirname, "vendor", "qldemo");

function libImport(name) {
  return import(pathToFileURL(join(LIB, name)).href);
}

const { matchBufferToReplaySequential } = await libImport("match-to-replay.js");
const { loadMapPickupTableFromDisk } = await libImport("map-item-resolve.node.js");

function parseArgs(argv) {
  let input = null;
  let output = null;
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (arg === "-o" || arg === "--output") {
      output = argv[++i];
    } else if (!input) {
      input = arg;
    }
  }
  return { input, output };
}

function defaultOutputPath(inputPath) {
  const dir = dirname(inputPath);
  const base = basename(inputPath).replace(/\.qlmatch$/i, "");
  return join(dir, base + ".replay.json.gz");
}

async function main() {
  const { input, output } = parseArgs(process.argv.slice(2));
  if (!input) {
    console.error("usage: qlmatch-to-replay.mjs <file.qlmatch> [-o out.replay.json.gz]");
    process.exit(1);
  }

  const bytes = readFileSync(input);
  // Sequential (one POV parsed at a time): an 8-POV pack parsed all at once
  // exceeds Node's default heap - see matchBufferToReplaySequential. The
  // pickup table is loaded lazily once the first POV reveals the map name;
  // map-item-resolve.node.js resolves it against ../maps/entities/ relative
  // to vendor/qldemo, i.e. the tables sync-vendor.sh vendors alongside.
  const replay = await matchBufferToReplaySequential(bytes, {
    loadMapTable: loadMapPickupTableFromDisk,
  });

  // .part + rename so a crash mid-write never leaves a truncated gzip where
  // restore/qlmatch.py expects a valid sidecar.
  const outPath = output || defaultOutputPath(input);
  const partPath = outPath + ".part";
  writeFileSync(partPath, gzipSync(Buffer.from(JSON.stringify(replay))));
  renameSync(partPath, outPath);

  const positionEvents = replay.events.filter((e) => e.event === "positions").length;
  console.log("wrote", outPath);
  console.log(
    "povs", replay.meta.povs.length,
    "map", replay.meta.map_name,
    "generator_version", replay.meta.generator_version,
    "duration_ms", replay.meta.duration_wall_ms,
    "positions", positionEvents,
    "deaths", replay.meta.death_events,
    "pickups", replay.events.filter((e) => e.event === "pickup").length,
    "errors", replay.meta.errors.length,
  );
}

main().catch((err) => {
  console.error(err.stack || String(err));
  process.exit(1);
});
