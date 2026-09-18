import assert from "node:assert/strict";
import { test } from "node:test";
import { ET_ITEM, ET_PLAYER, MAX_CLIENTS } from "./constants.js";
import { createPlayerState } from "./delta.js";
import { createEntityState, TR_INTERPOLATE, TR_STATIONARY } from "./entity-state.js";
import { demoToReplay } from "./demo-to-replay.js";

// EV_ITEM_PICKUP=15 with one toggle-bit (bit 8) set, matching how the real
// wire delta looks (see entity-events.js's ES_EVENT_BITS=0x300 comment).
const EV_ITEM_PICKUP_RAW = 15 | 0x100;
const ITEM_ARMOR_BODY_INDEX = 3; // QL91_ITEM_CLASSNAMES[3] (constants.js)
const ITEM_HEALTH_MEGA_INDEX = 8; // QL91_ITEM_CLASSNAMES[8] (constants.js)
const WEAPON_ROCKETLAUNCHER_INDEX = 13; // QL91_ITEM_CLASSNAMES[13] (constants.js)
const AMMO_ROCKETS_INDEX = 24; // QL91_ITEM_CLASSNAMES[24] (constants.js) - distinct bg_itemlist entry from weapon_rocketlauncher (13)

function ownPlayerState({ x, y, z, externalEvent = 0, externalEventParm = 0 }) {
  const ps = createPlayerState();
  ps.clientNum = 0;
  ps.origin = [x, y, z];
  ps.externalEvent = externalEvent;
  ps.externalEventParm = externalEventParm;
  return ps;
}

function otherPlayerEntity({ clientNum, x, y, z, event = 0, eventParm = 0 }) {
  const ent = createEntityState();
  ent.number = MAX_CLIENTS + clientNum;
  ent.eType = ET_PLAYER;
  ent.pos.trType = TR_STATIONARY;
  ent.pos.trBase = [x, y, z];
  ent.health = 100;
  ent.event = event;
  ent.eventParm = eventParm;
  return ent;
}

// modelindex on the wire is a bg_itemlist index (QL91_ITEM_CLASSNAMES),
// same table EV_ITEM_PICKUP's eventParm resolves through - NOT a
// gamestate.models[] model index.
function itemEntity({ x, y, z, trType = TR_STATIONARY, modelindex = ITEM_ARMOR_BODY_INDEX }) {
  const ent = createEntityState();
  ent.eType = ET_ITEM;
  ent.pos.trType = trType;
  ent.pos.trBase = [x, y, z];
  ent.modelindex = modelindex;
  return ent;
}

/** Minimal fake QLDemoParser: only the surface demoToReplay() actually reads. */
function fakeParser(snapshots) {
  return {
    mapName: () => "bloodrun",
    gametype: () => "duel",
    gamestate: {
      clientNum: 0,
      players: { 0: { n: "A" }, 1: { n: "B" } },
      spectators: {},
    },
    playerRows: () => [{ clientNum: 0 }, { clientNum: 1 }],
    serverCommands: [],
    snapshots,
  };
}

test("entity-observed EV_ITEM_PICKUP on another player's entity emits an exact pickup, not the PVS heuristic", () => {
  const parser = fakeParser([
    // First sighting of clientNum 1's entity: baseline, event=0 - no pickup.
    { serverTime: 1000, entities: [otherPlayerEntity({ clientNum: 1, x: 100, y: 200, z: 300 })] },
    // Fresh EV_ITEM_PICKUP fires on the same entity.
    {
      serverTime: 1025,
      entities: [
        otherPlayerEntity({
          clientNum: 1,
          x: 100,
          y: 200,
          z: 300,
          event: EV_ITEM_PICKUP_RAW,
          eventParm: ITEM_ARMOR_BODY_INDEX,
        }),
      ],
    },
    // Same raw event value carried forward (delta didn't touch it) - must not re-trigger.
    {
      serverTime: 1050,
      entities: [
        otherPlayerEntity({
          clientNum: 1,
          x: 100,
          y: 200,
          z: 300,
          event: EV_ITEM_PICKUP_RAW,
          eventParm: ITEM_ARMOR_BODY_INDEX,
        }),
      ],
    },
  ]);

  const replay = demoToReplay(parser, { povClientNum: 0, mapTable: [], includePickups: true });
  const pickups = replay.events.filter((e) => e.event === "pickup");

  assert.equal(pickups.length, 1, "exactly one pickup event, not zero and not a duplicate");
  const [pickup] = pickups;
  assert.equal(pickup.item, "item_armor_body");
  assert.equal(pickup.clientNum, 1);
  assert.equal(pickup.action, "pickup");
  assert.equal(pickup.source, "entity");
  assert.equal(pickup.game_time_ms, 25);
});

test("a stale non-zero event on an entity's first sighting is not mistaken for a fresh pickup", () => {
  const parser = fakeParser([
    // Entity enters this POV's view already mid-toggle (e.g. re-entering PVS) - no prior raw value to diff against.
    {
      serverTime: 1000,
      entities: [
        otherPlayerEntity({
          clientNum: 1,
          x: 100,
          y: 200,
          z: 300,
          event: EV_ITEM_PICKUP_RAW,
          eventParm: ITEM_ARMOR_BODY_INDEX,
        }),
      ],
    },
    { serverTime: 1025, entities: [otherPlayerEntity({ clientNum: 1, x: 100, y: 200, z: 300 })] },
  ]);

  const replay = demoToReplay(parser, { povClientNum: 0, mapTable: [], includePickups: true });
  const pickups = replay.events.filter((e) => e.event === "pickup");
  assert.equal(pickups.length, 0);
});

const ARMOR_SPAWN_MAP_TABLE = [{ classname: "item_armor_body", x: 0, y: 0, z: 0 }];

test("PVS heuristic still tracks a real stationary item spawn (regression check for the trType filter below)", () => {
  const parser = fakeParser([
    {
      serverTime: 1000,
      entities: [
        itemEntity({ x: 30, y: 0, z: 0, trType: TR_STATIONARY }),
        otherPlayerEntity({ clientNum: 1, x: 10, y: 0, z: 0 }),
      ],
    },
    // Item entity gone from the snapshot - still a live player nearby.
    { serverTime: 1025, entities: [otherPlayerEntity({ clientNum: 1, x: 10, y: 0, z: 0 })] },
  ]);

  const replay = demoToReplay(parser, {
    povClientNum: 0,
    mapTable: ARMOR_SPAWN_MAP_TABLE,
    includePickups: true,
  });
  const pickups = replay.events.filter((e) => e.event === "pickup");
  assert.equal(pickups.length, 1);
  assert.equal(pickups[0].item, "item_armor_body");
  assert.equal(pickups[0].source, undefined, "heuristic pickups carry no source tag");
});

test("a dropped (non-stationary) item near a real spawn is never registered by the PVS heuristic, even within the position-match radius", () => {
  const parser = fakeParser([
    {
      serverTime: 1000,
      entities: [
        // 30 units from the item_armor_body spawn at (0,0,0) - well inside
        // resolvePickupAt()'s 64-unit tolerance, so without the trType guard
        // this would get misnamed "item_armor_body" by pure proximity (the
        // real bug: gamestate.models is empty for every real .dm_91 capture
        // seen so far, so modelPathToClassname always falls through to that
        // position-only lookup).
        itemEntity({ x: 30, y: 0, z: 0, trType: TR_INTERPOLATE }),
        otherPlayerEntity({ clientNum: 1, x: 10, y: 0, z: 0 }),
      ],
    },
    { serverTime: 1025, entities: [otherPlayerEntity({ clientNum: 1, x: 10, y: 0, z: 0 })] },
  ]);

  const replay = demoToReplay(parser, {
    povClientNum: 0,
    mapTable: ARMOR_SPAWN_MAP_TABLE,
    includePickups: true,
  });
  const pickups = replay.events.filter((e) => e.event === "pickup");
  assert.equal(pickups.length, 0, "a moving/dropped item must never produce a false pickup of a nearby spawn");
});

test("own-POV pickup via ps.externalEvent is caught even with nothing in the events[] ring - real bug: mega/yellow armor pickups on bloodrun landed only here", () => {
  const parser = fakeParser([
    // events[]/eventParms[] ring stays all-zero for both snapshots - this
    // path must not depend on it at all.
    { serverTime: 1000, playerState: ownPlayerState({ x: 10, y: 20, z: 30 }) },
    {
      serverTime: 1025,
      playerState: ownPlayerState({ x: 10, y: 20, z: 30, externalEvent: EV_ITEM_PICKUP_RAW, externalEventParm: ITEM_HEALTH_MEGA_INDEX }),
    },
  ]);

  const replay = demoToReplay(parser, { povClientNum: 0, mapTable: [], includePickups: true });
  const pickups = replay.events.filter((e) => e.event === "pickup");

  assert.equal(pickups.length, 1);
  const [pickup] = pickups;
  assert.equal(pickup.item, "item_health_mega");
  assert.equal(pickup.clientNum, 0);
  assert.equal(pickup.source, "ps");
  assert.equal(pickup.game_time_ms, 25);
});

test("a stale non-zero ps.externalEvent on the first snapshot is not mistaken for a fresh pickup", () => {
  const parser = fakeParser([
    {
      serverTime: 1000,
      playerState: ownPlayerState({ x: 10, y: 20, z: 30, externalEvent: EV_ITEM_PICKUP_RAW, externalEventParm: ITEM_HEALTH_MEGA_INDEX }),
    },
    { serverTime: 1025, playerState: ownPlayerState({ x: 10, y: 20, z: 30 }) },
  ]);

  const replay = demoToReplay(parser, { povClientNum: 0, mapTable: [], includePickups: true });
  const pickups = replay.events.filter((e) => e.event === "pickup");
  assert.equal(pickups.length, 0);
});

test("an ammo_rockets pickup near a registered weapon_rocketlauncher spot keeps its own name - real bug: reported as a fresh weapon pickup instead of ammo", () => {
  const rlMapTable = [{ classname: "weapon_rocketlauncher", x: 100, y: 100, z: 50 }];
  const parser = fakeParser([
    // The RL weapon entity sits in view the whole time (registers it as
    // "weapon_rocketlauncher" in the PVS heuristic's own registry).
    {
      serverTime: 1000,
      entities: [itemEntity({ x: 100, y: 100, z: 50, modelindex: WEAPON_ROCKETLAUNCHER_INDEX })],
      playerState: ownPlayerState({ x: 150, y: 100, z: 50 }),
    },
    // Player touches the SEPARATE ammo box 50 units away (well inside the
    // 128-unit family-match radius) - the event's own canonical name is
    // ammo_rockets, a distinct bg_itemlist entry from weapon_rocketlauncher.
    {
      serverTime: 1025,
      entities: [itemEntity({ x: 100, y: 100, z: 50, modelindex: WEAPON_ROCKETLAUNCHER_INDEX })],
      playerState: ownPlayerState({
        x: 150,
        y: 100,
        z: 50,
        externalEvent: EV_ITEM_PICKUP_RAW,
        externalEventParm: AMMO_ROCKETS_INDEX,
      }),
    },
  ]);

  const replay = demoToReplay(parser, { povClientNum: 0, mapTable: rlMapTable, includePickups: true });
  const pickups = replay.events.filter((e) => e.event === "pickup" && e.action === "pickup");

  assert.equal(pickups.length, 1);
  assert.equal(pickups[0].item, "ammo_rockets", "must not be renamed to the nearby weapon's classname");
  assert.equal(pickups[0].respawn_sec, 40);
});

test("PVS heuristic (no exact event at all) also reports an ammo box's own name, not its family-collapsed weapon name - root-cause fix, not just the exact-event path", () => {
  const ammoMapTable = [{ classname: "ammo_rockets", x: 0, y: 0, z: 0 }];
  const parser = fakeParser([
    {
      serverTime: 1000,
      entities: [
        itemEntity({ x: 30, y: 0, z: 0, trType: TR_STATIONARY, modelindex: AMMO_ROCKETS_INDEX }),
        otherPlayerEntity({ clientNum: 1, x: 10, y: 0, z: 0 }),
      ],
    },
    // Item entity gone, no ps/entity pickup event fired anywhere - only the
    // disappearance heuristic can attribute this one.
    { serverTime: 1025, entities: [otherPlayerEntity({ clientNum: 1, x: 10, y: 0, z: 0 })] },
  ]);

  const replay = demoToReplay(parser, {
    povClientNum: 0,
    mapTable: ammoMapTable,
    includePickups: true,
  });
  const pickups = replay.events.filter((e) => e.event === "pickup");
  assert.equal(pickups.length, 1);
  assert.equal(pickups[0].item, "ammo_rockets", "the registry itself must store the map's true classname, not weapon_rocketlauncher");
});
