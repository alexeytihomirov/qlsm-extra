// Death drops across the two stages that produce them: demoToReplay's
// per-POV tracker (fed synthetic snapshots) and mergeReplays' cross-POV
// union. A drop is an ET_ITEM with modelindex2 === 1 - LaunchItem()'s own
// "this was tossed, not map-placed" marker.
import assert from "node:assert/strict";
import { test } from "node:test";
import { demoToReplay } from "./demo-to-replay.js";
import { mergeReplays } from "./match-to-replay.js";

const TR_STATIONARY = 0;
const TR_GRAVITY = 5;
const ET_ITEM = 2;
const ET_PLAYER = 1;

function itemEnt(number, modelindex, x, y, z, { dropped = true, trType = TR_STATIONARY } = {}) {
  return {
    number,
    eType: ET_ITEM,
    eFlags: 0,
    modelindex,
    modelindex2: dropped ? 1 : 0,
    pos: { trType, trTime: 0, trDuration: 0, trBase: [x, y, z], trDelta: [0, 0, 0] },
    apos: { trType: 0, trTime: 0, trDuration: 0, trBase: [0, 0, 0], trDelta: [0, 0, 0] },
  };
}

function playerEnt(number, x, y, z) {
  return {
    number,
    eType: ET_PLAYER,
    eFlags: 0,
    clientNum: number,
    modelindex: 0,
    modelindex2: 0,
    weapon: 0,
    powerups: 0,
    pos: { trType: TR_STATIONARY, trTime: 0, trDuration: 0, trBase: [x, y, z], trDelta: [0, 0, 0] },
    apos: { trType: 0, trTime: 0, trDuration: 0, trBase: [0, 0, 0], trDelta: [0, 0, 0] },
  };
}

/** Minimal stand-in for QLDemoParser: only what demoToReplay actually reads. */
function fakeParser(snapshots) {
  return {
    snapshots,
    gamestate: { clientNum: 0, players: { 0: { n: "A" }, 1: { n: "B" } }, models: {} },
    serverCommands: [],
    errors: [],
    mapName: () => "bloodrun",
    gametype: () => "duel",
    playerRows: () => [
      { clientNum: 0, n: "A", st: null },
      { clientNum: 1, n: "B", st: null },
    ],
  };
}

function snap(serverTime, entities) {
  return { serverTime, entities, changedEntities: [], playerState: null };
}

function dropEventsOf(replay) {
  return replay.events.filter((e) => e.event === "item_drop");
}

// Every fake snapshot sits past the fight start so game_time_ms >= 0 without
// needing a real match clock in the stream.
const T0 = 100000;

test("a settled dropped item becomes one item_drop event, named from its bg_itemlist index", () => {
  const replay = demoToReplay(
    fakeParser([
      snap(T0, [itemEnt(300, 13, 373, -1119, 272)]),
      snap(T0 + 25, [itemEnt(300, 13, 373, -1119, 272)]),
      snap(T0 + 50, [itemEnt(300, 13, 373, -1119, 272)]),
    ]),
    { mapTable: null },
  );
  const drops = dropEventsOf(replay);
  assert.equal(drops.length, 1);
  assert.equal(drops[0].action, "drop");
  assert.equal(drops[0].item_id, 13);
  assert.equal(drops[0].item, "weapon_rocketlauncher");
  assert.deepEqual([drops[0].x, drops[0].y, drops[0].z], [373, -1119, 272]);
  assert.equal(replay.meta.drop_events, 1);
});

test("an in-flight drop is ignored until it lands", () => {
  const replay = demoToReplay(
    fakeParser([
      snap(T0, [itemEnt(300, 15, 100, 100, 400, { trType: TR_GRAVITY })]),
      snap(T0 + 25, [itemEnt(300, 15, 100, 100, 300, { trType: TR_GRAVITY })]),
      snap(T0 + 50, [itemEnt(300, 15, 100, 100, 16)]),
    ]),
    { mapTable: null },
  );
  const drops = dropEventsOf(replay);
  assert.equal(drops.length, 1);
  assert.equal(drops[0].z, 16);
});

test("a map-placed item is never mistaken for a drop", () => {
  const replay = demoToReplay(
    fakeParser([snap(T0, [itemEnt(80, 8, 784, -224, 81, { dropped: false })])]),
    { mapTable: null },
  );
  assert.equal(dropEventsOf(replay).length, 0);
});

test("a drop that vanishes next to a player is reported gone; one that merely leaves view is not", () => {
  const spot = [200, 200, 16];
  const withPlayer = demoToReplay(
    fakeParser([
      snap(T0, [itemEnt(300, 14, ...spot), playerEnt(1, 210, 200, 16)]),
      snap(T0 + 25, [playerEnt(1, 210, 200, 16)]),
    ]),
    { mapTable: null },
  );
  const taken = dropEventsOf(withPlayer);
  assert.deepEqual(taken.map((e) => e.action), ["drop", "gone"]);

  const noPlayer = demoToReplay(
    fakeParser([
      snap(T0, [itemEnt(300, 14, ...spot), playerEnt(1, 3000, 3000, 16)]),
      snap(T0 + 25, [playerEnt(1, 3000, 3000, 16)]),
    ]),
    { mapTable: null },
  );
  assert.deepEqual(dropEventsOf(noPlayer).map((e) => e.action), ["drop"]);
});

test("a drop that leaves and re-enters PVS stays one drop, not two", () => {
  const spot = [400, -400, 16];
  const replay = demoToReplay(
    fakeParser([
      snap(T0, [itemEnt(300, 16, ...spot), playerEnt(1, 3000, 3000, 16)]),
      snap(T0 + 25, [playerEnt(1, 3000, 3000, 16)]),
      snap(T0 + 5000, [itemEnt(311, 16, ...spot), playerEnt(1, 3000, 3000, 16)]),
    ]),
    { mapTable: null },
  );
  assert.equal(dropEventsOf(replay).length, 1);
});

// ---- cross-POV merge -------------------------------------------------------

function baseMeta() {
  return {
    map_name: "bloodrun",
    gametype: "duel",
    match_start_server_time: 1000,
    recording_start_server_time: 1000,
    roster: [{ clientNum: 0, name: "A" }, { clientNum: 1, name: "B" }],
  };
}

function ev(action, t, dropT) {
  return {
    event: "item_drop",
    action,
    item_id: 13,
    item: "weapon_rocketlauncher",
    x: 373,
    y: -1119,
    z: 272,
    game_time_ms: t,
    drop_game_time_ms: dropT ?? t,
  };
}

test("the same drop seen by two POVs merges into one lifetime, starting at the earliest sighting", () => {
  const merged = mergeReplays([
    { clientNum: 0, replay: { meta: baseMeta(), events: [ev("drop", 21500)] } },
    { clientNum: 1, replay: { meta: baseMeta(), events: [ev("drop", 24000)] } },
  ]);
  const drops = merged.events.filter((e) => e.event === "item_drop");
  assert.equal(drops.length, 1);
  assert.equal(drops[0].game_time_ms, 21500);
});

test("one POV's 'gone' is overruled by another POV that still saw the item there", () => {
  const merged = mergeReplays([
    // POV 0 loses it at 23000 (really just PVS), POV 1 still sees it at 26000.
    { clientNum: 0, replay: { meta: baseMeta(), events: [ev("drop", 21500), ev("gone", 23000, 21500)] } },
    { clientNum: 1, replay: { meta: baseMeta(), events: [ev("drop", 26000, 21500)] } },
  ]);
  const drops = merged.events.filter((e) => e.event === "item_drop");
  assert.deepEqual(drops.map((d) => d.action), ["drop"]);
});

test("a 'gone' after every sighting survives the merge", () => {
  const merged = mergeReplays([
    { clientNum: 0, replay: { meta: baseMeta(), events: [ev("drop", 21500)] } },
    { clientNum: 1, replay: { meta: baseMeta(), events: [ev("drop", 22000, 21500), ev("gone", 23650, 21500)] } },
  ]);
  const drops = merged.events.filter((e) => e.event === "item_drop");
  assert.deepEqual(drops.map((d) => [d.action, d.game_time_ms]), [
    ["drop", 21500],
    ["gone", 23650],
  ]);
});
