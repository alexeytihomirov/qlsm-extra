import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { filterPickupEntities, normalizeMapKey } from "./map-item-resolve.js";

/** Node CLI only — reads live-overlay/maps/entities/{map}.json from disk. */
export function loadMapPickupTableFromDisk(mapName, gametype) {
  try {
    const root = dirname(dirname(dirname(fileURLToPath(import.meta.url))));
    const path = join(root, "maps", "entities", `${normalizeMapKey(mapName)}.json`);
    const data = JSON.parse(readFileSync(path, "utf8"));
    return filterPickupEntities(data.entities, gametype);
  } catch {
    return [];
  }
}
