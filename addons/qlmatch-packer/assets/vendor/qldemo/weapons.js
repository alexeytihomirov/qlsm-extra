/** QL dm_91 weapon index → slug (UDT Weapons_73p, protocol 91). */
export const WEAPON_SLUG = {
  1: "gauntlet",
  2: "machinegun",
  3: "shotgun",
  4: "grenadelauncher",
  5: "rocketlauncher",
  6: "lightninggun",
  7: "railgun",
  8: "plasmagun",
  9: "bfg",
  10: "grapple",
  11: "nailgun",
  12: "proxlauncher",
  13: "chaingun",
  14: "hmg",
};

export function weaponSlug(id) {
  return WEAPON_SLUG[id] || "";
}
