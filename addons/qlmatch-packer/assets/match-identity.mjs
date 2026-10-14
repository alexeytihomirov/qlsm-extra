// Match identity for the .qlmatch manifest and {match_id}.meta.json: the
// engine's match GUID (configstring 712) and each player's steam id.
//
// Sources: the C-written POV index files carry optional "match_guid" and
// "steam_id64" keys; the demo's own gamestate carries configstring 712 as a
// fallback for the GUID (only for indexes from before the fork wrote steam_id64). Values that do not look right are treated as absent,
// never written.

const GUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const STEAM_ID_RE = /^\d{17}$/;

// Lower-case canonical UUID, or null.
export function normalizeGuid(value) {
  if (typeof value !== "string") return null;
  const g = value.trim().toLowerCase();
  return GUID_RE.test(g) ? g : null;
}

// 17-digit steam id string, or null.
export function normalizeSteamId(value) {
  if (typeof value === "number") return null; // a double cannot hold 17 digits
  if (typeof value !== "string") return null;
  const s = value.trim();
  return STEAM_ID_RE.test(s) ? s : null;
}

// entries: [{clientNum, index, guidFromGamestate}]
// roster: Map<clientNum, {name, team}>
// -> {match_guid, players: [{steam_id64, name, team, client_num}], warnings}
export function matchIdentity(entries, roster) {
  const warnings = [];

  const indexGuids = new Set();
  for (const e of entries) {
    const g = normalizeGuid(e.index?.match_guid);
    if (g) indexGuids.add(g);
  }
  let matchGuid = null;
  if (indexGuids.size === 1) {
    matchGuid = [...indexGuids][0];
  } else if (indexGuids.size > 1) {
    warnings.push(`POV indexes disagree on match_guid (${[...indexGuids].join(", ")}) - not writing one`);
  } else if (entries.some((e) => e.index && Object.hasOwn(e.index, "steam_id64"))) {
    // New fork: a missing index guid means the engine refused a stale one, and
    // the gamestate (recording start) holds exactly that value.
    warnings.push("no match_guid in the POV indexes; gamestate fallback skipped (new fork indexes)");
  } else {
    for (const e of entries) {
      const g = normalizeGuid(e.guidFromGamestate);
      if (g) { matchGuid = g; break; }
    }
  }

  // A player's steam id comes only from their own POV index.
  const steamByClient = new Map();
  for (const e of entries) {
    const s = normalizeSteamId(e.index?.steam_id64);
    if (s && !steamByClient.has(e.clientNum)) steamByClient.set(e.clientNum, s);
  }

  const players = [...roster.entries()]
    .sort((a, b) => a[0] - b[0])
    .map(([clientNum, row]) => ({
      steam_id64: steamByClient.get(clientNum) ?? null,
      name: row.name,
      team: row.team,
      client_num: clientNum,
    }));

  return { match_guid: matchGuid, players, warnings };
}
