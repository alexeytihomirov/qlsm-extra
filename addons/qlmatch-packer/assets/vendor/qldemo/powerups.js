/** Q3/QL player powerup slot indices (ps.powerups[i] = expiry server time). */
const PW_SLOT_NAMES = [
  "",
  "quad",
  "battle",
  "haste",
  "invis",
  "regen",
  "flight",
];

/** World item / entity powerup bitmask (entityState.powerups). */
const PW_ENTITY_BITS = [
  { bit: 1 << 0, name: "quad" },
  { bit: 1 << 1, name: "battle" },
  { bit: 1 << 2, name: "haste" },
  { bit: 1 << 3, name: "invis" },
  { bit: 1 << 4, name: "regen" },
  { bit: 1 << 5, name: "flight" },
];

export function powerupNamesFromPlayerState(ps, serverTime = 0) {
  const slots = ps?.powerups;
  if (!slots?.length) return [];
  const out = [];
  for (let i = 1; i < PW_SLOT_NAMES.length; i++) {
    const until = slots[i] || 0;
    if (until > serverTime) out.push(PW_SLOT_NAMES[i]);
  }
  return out;
}

export function powerupNamesFromEntityMask(mask) {
  const out = [];
  for (const row of PW_ENTITY_BITS) {
    if (mask & row.bit) out.push(row.name);
  }
  return out;
}

/** @deprecated use powerupNamesFromPlayerState */
export function powerupNamesFromStats(stats) {
  return powerupNamesFromPlayerState({ powerups: stats });
}
