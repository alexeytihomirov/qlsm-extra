const PICKUP_PREFIXES = ["item_", "ammo_", "weapon_"];

const CLASS_MAP = {
  ammo_bullets: "weapon_machinegun",
  ammo_shells: "weapon_shotgun",
  ammo_rockets: "weapon_rocketlauncher",
  ammo_lightning: "weapon_lightning",
  ammo_railgun: "weapon_railgun",
  ammo_cells: "weapon_plasmagun",
  item_health_mega: "item_health_mega",
  item_health_large: "item_health_large",
  item_health: "item_health",
  item_health_small: "item_health_small",
  item_armor_shard: "item_armor_shard",
  item_armor_combat: "item_armor_combat",
  item_armor_body: "item_armor_body",
  item_armor_jacket: "item_armor_yellow",
};

const tableCache = new Map();

export function normalizeMapKey(name) {
  return String(name || "")
    .trim()
    .toLowerCase()
    .replace(/^map-/, "")
    .replace(/[^a-z0-9]/g, "");
}

// Gametype-conditional item spawns (bloodrun has duel-only ammo packs and a
// duel-only quad on the flip side of a not_gametype:"duel" pair at the same
// spot) - ported from live-overlay/map-spawns.js's entityMatchesGametype()
// (the live map widget already filters these correctly; the qlmatch replay
// pipeline didn't, showing e.g. TDM-only items as pickable on a duel replay).
// Duplicated rather than imported: map-spawns.js is a browser-global script
// with page/DOM assumptions, this module also runs under Node (the packer
// CLI).
// parser.gametype() (demo-parser.js) returns the raw g_gametype serverinfo
// cvar - a QL gametype *number* as a string ("1"), not a slug. Same table as
// qlmatch-packer/pack.mjs's GAMETYPE_NAMES (independent copy - pack.mjs
// isn't part of the vendored lib/qldemo, only needs this for its own
// filename template).
const GAMETYPE_CVAR_NAMES = {
  0: "ffa", 1: "duel", 2: "race", 3: "tdm", 4: "ca", 5: "ctf",
  6: "1f", 8: "har", 9: "ft", 10: "dom", 11: "ad", 12: "rr",
};

function normalizeGametype(gt) {
  let raw = gt;
  if (typeof raw === "number" || /^\d+$/.test(String(raw || ""))) {
    raw = GAMETYPE_CVAR_NAMES[Number(raw)] ?? raw;
  }
  const g = String(raw || "").trim().toLowerCase().replace(/[\s-]+/g, "_");
  if (!g) return "";
  if (["1v1", "1on1", "oneonone", "one_on_one", "duel", "duels", "tourney", "tournament"].includes(g)) {
    return "duel";
  }
  if (["ffa", "freeforall", "free_for_all", "deathmatch", "dm"].includes(g)) return "dm";
  if (["tdm", "team_deathmatch", "teamdeathmatch", "team_dm"].includes(g)) return "tdm";
  return g;
}

function gametypeTokens(value) {
  const raw = String(value || "").trim().toLowerCase();
  if (!raw) return [];
  const out = [];
  for (const part of raw.split(/[\s,]+/)) {
    const token = normalizeGametype(part);
    if (token && !out.includes(token)) out.push(token);
  }
  return out;
}

function gametypeListMatches(value, gt) {
  const tokens = gametypeTokens(value);
  if (!tokens.length) return false;
  const normalized = normalizeGametype(gt);
  return !!normalized && tokens.includes(normalized);
}

function truthyMapAttr(value) {
  return value === "1" || value === 1 || value === true;
}

function legacySpawnFlagsBlockGametype(attrs, gt) {
  if (!attrs || !gt) return false;
  const g = normalizeGametype(gt);
  if (!g) return false;
  if (truthyMapAttr(attrs.notsingle) && g === "duel") return true;
  if (truthyMapAttr(attrs.notfree) && (g === "dm" || g === "duel")) return true;
  if (truthyMapAttr(attrs.notteam) && (g === "tdm" || g === "ctf" || g === "ca" || g === "dom")) return true;
  return false;
}

function entityMatchesGametype(ent, gametype) {
  const gt = normalizeGametype(gametype);
  if (!gt) return true;
  const attrs = ent.attrs || {};
  if (attrs.gametype && !gametypeListMatches(attrs.gametype, gt)) return false;
  if (attrs.not_gametype && gametypeListMatches(attrs.not_gametype, gt)) return false;
  if (legacySpawnFlagsBlockGametype(attrs, gt)) return false;
  return true;
}

/** gametype: the match's own gametype (parser.gametype()) - omit to skip gametype filtering entirely. */
export function filterPickupEntities(entities, gametype) {
  return (entities || []).filter(
    (row) =>
      PICKUP_PREFIXES.some((p) => String(row.classname || "").startsWith(p)) &&
      entityMatchesGametype(row, gametype),
  );
}

export function registerMapPickupTable(mapName, rows) {
  tableCache.set(normalizeMapKey(mapName), rows || []);
}

/** In-browser: populate via registerMapPickupTable or pass options.mapTable to demoToReplay. */
export function loadMapPickupTable(mapName) {
  return tableCache.get(normalizeMapKey(mapName)) || [];
}

export function toRestoreClassname(mapClassname) {
  const cn = String(mapClassname || "");
  if (CLASS_MAP[cn]) return CLASS_MAP[cn];
  if (cn.startsWith("item_") || cn.startsWith("weapon_")) return cn;
  return "";
}

// The pipeline ends up naming the same pickup spot up to three ways:
// CLASS_MAP restore names above, raw BSP classnames passed through
// toRestoreClassname, and bg_itemlist canon from both ps pickup events and
// demo-to-replay's map-item registration (item_armor_combat, item_quad,
// ammo_rockets - see QL91_ITEM_CLASSNAMES). itemFamilyKey collapses all of
// them to one comparison key so a ps-event pickup can be matched against a
// registry item or another POV's pickup regardless of which convention
// named it. Position (not the name) disambiguates which physical spot it
// was, so conflating e.g. every ammo box of a weapon with that weapon is
// fine - two spots of the same family are never within match radius.
const ITEM_FAMILY_ALIASES = {
  item_armor_jacket: "item_armor_yellow",
  item_armor_combat: "item_armor_yellow",
  item_quad: "item_powerup_quad",
  item_regen: "item_powerup_regen",
  item_haste: "item_powerup_haste",
  item_invis: "item_powerup_invis",
  item_enviro: "item_powerup_battlesuit",
  item_flight: "item_powerup_flight",
  holdable_medkit: "item_holdable_medkit",
  holdable_teleporter: "item_holdable_teleporter",
  holdable_kamikaze: "item_holdable_kamikaze",
  holdable_portal: "item_holdable_portal",
  holdable_invulnerability: "item_holdable_invulnerability",
  ammo_bullets: "weapon_machinegun",
  ammo_shells: "weapon_shotgun",
  ammo_rockets: "weapon_rocketlauncher",
  ammo_lightning: "weapon_lightning",
  ammo_railgun: "weapon_railgun",
  ammo_slugs: "weapon_railgun",
  ammo_cells: "weapon_plasmagun",
  ammo_grenades: "weapon_grenadelauncher",
  ammo_bfg: "weapon_bfg",
  ammo_nails: "weapon_nailgun",
  ammo_mines: "weapon_prox_launcher",
  ammo_belt: "weapon_chaingun",
  ammo_hmg: "weapon_hmg",
};

export function itemFamilyKey(classname) {
  const cn = String(classname || "");
  return ITEM_FAMILY_ALIASES[cn] || cn;
}

/** Nearest map-spawn row within tolerance of (x, y, z), or null. */
export function resolvePickupRowAt(table, x, y, z, tolerance = 64) {
  let best = null;
  let bestD = tolerance * tolerance;
  for (const row of table || []) {
    const dx = row.x - x;
    const dy = row.y - y;
    const dz = row.z - z;
    const d = dx * dx + dy * dy + dz * dz;
    if (d < bestD) {
      bestD = d;
      best = row;
    }
  }
  return best;
}

export function resolvePickupAt(table, x, y, z, tolerance = 64) {
  const best = resolvePickupRowAt(table, x, y, z, tolerance);
  return best ? toRestoreClassname(best.classname) : "";
}
