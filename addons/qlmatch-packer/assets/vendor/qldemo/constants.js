export const GENTITYNUM_BITS = 10;
export const MAX_GENTITIES = 1 << GENTITYNUM_BITS;
export const ENTITYNUM_NONE = MAX_GENTITIES - 1;
export const FLOAT_INT_BITS = 13;
export const FLOAT_INT_BIAS = 1 << (FLOAT_INT_BITS - 1);

export const SVC_BAD = 0;
export const SVC_NOP = 1;
export const SVC_GAMESTATE = 2;
export const SVC_CONFIGSTRING = 3;
export const SVC_BASELINE = 4;
export const SVC_SERVERCOMMAND = 5;
export const SVC_DOWNLOAD = 6;
export const SVC_SNAPSHOT = 7;
export const SVC_EOF = 8;

export const ET_GENERAL = 0;
export const ET_PLAYER = 1;
export const ET_ITEM = 2;
export const ET_MISSILE = 3;
export const ET_EVENTS = 13;

export const TEAM_SPECTATOR = "3";

export const MAX_CLIENTS = 64;
export const MAX_MODELS = 256;
export const MAX_SOUNDS = 256;
export const MAX_STATS = 16;
export const MAX_PERSISTANT = 16;
export const MAX_POWERUPS = 16;
export const MAX_WEAPONS = 16;
export const MAX_MAP_AREA_BYTES = 32;
export const PACKET_BACKUP = 32;
export const PACKET_MASK = PACKET_BACKUP - 1;

export const CS_SERVERINFO = 0;
export const CS_SYSTEMINFO = 1;
export const CS_MODELS = 17;
export const CS_SOUNDS = CS_MODELS + MAX_MODELS;
export const CS_PLAYERS = CS_SOUNDS + MAX_SOUNDS;

export const CS_STRING_MAP = {
  0: "serverinfo",
  1: "systeminfo",
  5: "warmup",
  6: "scores1",
  7: "scores2",
  13: "level_start_time",
  686: "1stplayer",
  687: "2ndplayer",
};

export const STAT_HEALTH = 0;
/** QL statIndex_t (quake_common.h): STAT_HOLDABLE_ITEM=1, STAT_WEAPONS=3, STAT_ARMOR=4. */
export const STAT_HOLDABLE_ITEM = 1;
export const STAT_WEAPONS = 3;
export const STAT_ARMOR = 4;
export const STAT_WEAPON = 2;

/**
 * QL dm_91 bg_itemlist index -> classname, 1-based (index 0 is the NULL
 * item). Source: wolfcamql bg_misc.c `bg_itemlistQldm91` (the protocol-91
 * table its cgame uses to play back these very demos). The eventParm of an
 * EV_ITEM_PICKUP / EV_GLOBAL_ITEM_PICKUP playerState event indexes this
 * list.
 */
export const QL91_ITEM_CLASSNAMES = [
  null,
  "item_armor_shard",
  "item_armor_combat",
  "item_armor_body",
  "item_armor_jacket",
  "item_health_small",
  "item_health",
  "item_health_large",
  "item_health_mega",
  "weapon_gauntlet",
  "weapon_shotgun",
  "weapon_machinegun",
  "weapon_grenadelauncher",
  "weapon_rocketlauncher",
  "weapon_lightning",
  "weapon_railgun",
  "weapon_plasmagun",
  "weapon_bfg",
  "weapon_grapplinghook",
  "ammo_shells",
  "ammo_bullets",
  "ammo_grenades",
  "ammo_cells",
  "ammo_lightning",
  "ammo_rockets",
  "ammo_slugs",
  "ammo_bfg",
  "holdable_teleporter",
  "holdable_medkit",
  "item_quad",
  "item_enviro",
  "item_haste",
  "item_invis",
  "item_regen",
  "item_flight",
  "team_CTF_redflag",
  "team_CTF_blueflag",
  "holdable_kamikaze",
  "holdable_portal",
  "holdable_invulnerability",
  "ammo_nails",
  "ammo_mines",
  "ammo_belt",
  "item_scout",
  "item_guard",
  "item_doubler",
  "item_armorregen",
  "team_CTF_neutralflag",
  "item_redcube",
  "item_bluecube",
  "weapon_nailgun",
  "weapon_prox_launcher",
  "weapon_chaingun",
  "item_spawnarmor",
  "weapon_hmg",
  "ammo_hmg",
  "ammo_pack",
  "item_key_silver",
  "item_key_gold",
  "item_key_master",
];
