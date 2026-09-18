/** dm_91 entity events (UDT EntityEvents_73p, protocol 91). */
export const ET_EVENTS = 13;
export const ET_GENERAL = 0;
export const EVENT_VALID_MSEC = 300;
export const ES_EVENT_BITS = 0x300;

export const EV_BULLET_HIT_FLESH = 45;
export const EV_BULLET_HIT_WALL = 46;
export const EV_MISSILE_HIT = 47;
export const EV_MISSILE_MISS = 48;
export const EV_MISSILE_MISS_METAL = 49;
export const EV_RAIL_TRAIL = 50;
export const EV_OBITUARY = 58;
// Shared entity_event_t ids (bg_public.h): the same EV_ITEM_PICKUP /
// EV_GLOBAL_ITEM_PICKUP fire both on the picker's own playerState ring
// (ps.events/ps.eventParms, consumed by demo-to-replay.js's own-POV path)
// AND, independently, on the picker's ET_PLAYER entityState (.event /
// .eventParm) - the latter is what every OTHER POV that has the picker in
// PVS actually observes.
export const EV_ITEM_PICKUP = 15;
export const EV_GLOBAL_ITEM_PICKUP = 16;

/** Raw dm_91/protocol-73p meansOfDeath (UDT MeansOfDeath_73p) -> weapon slug. */
const MOD_WEAPON_SLUG = {
  1: "shotgun",
  2: "gauntlet",
  3: "machinegun",
  4: "grenadelauncher",
  5: "grenadelauncher",
  6: "rocketlauncher",
  7: "rocketlauncher",
  8: "plasmagun",
  9: "plasmagun",
  10: "railgun",
  11: "lightninggun",
  12: "bfg",
  13: "bfg",
  23: "nailgun",
  24: "chaingun",
  25: "proxlauncher",
  28: "grapple",
  32: "hmg",
};

export function meanOfDeathWeaponSlug(mod) {
  return MOD_WEAPON_SLUG[mod] || "";
}

export const WP_GRENADE = 4;
export const WP_ROCKET = 5;
export const WP_SHAFT = 6;
export const WP_PLASMA = 8;

export const PROJECTILE_WEAPONS = new Set([WP_GRENADE, WP_ROCKET, WP_PLASMA]);

export function eventId(raw) {
  return Number(raw || 0) & ~ES_EVENT_BITS;
}

export function isBulletImpactEvent(ev) {
  return ev === EV_BULLET_HIT_FLESH || ev === EV_BULLET_HIT_WALL;
}

export function isMissileImpactEvent(ev) {
  return ev === EV_MISSILE_HIT || ev === EV_MISSILE_MISS || ev === EV_MISSILE_MISS_METAL;
}

export function entityEventId(ent) {
  if (!ent) return 0;
  if (ent.eType > ET_EVENTS) return (ent.eType - ET_EVENTS) & ~ES_EVENT_BITS;
  return eventId(ent.event);
}

export function isEventEntity(ent) {
  return ent != null && ent.eType >= ET_EVENTS;
}

export function isNewEntityEvent(ent, serverTimeMs, lastEventTimeMs) {
  if (!isEventEntity(ent)) return false;
  return serverTimeMs > (lastEventTimeMs || 0) + EVENT_VALID_MSEC;
}
