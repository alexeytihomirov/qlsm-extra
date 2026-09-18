import assert from "node:assert/strict";
import { test } from "node:test";
import { mergeReplays } from "./match-to-replay.js";

function baseMeta(overrides = {}) {
  return {
    map_name: "bloodrun",
    gametype: "duel",
    match_start_server_time: 1000,
    recording_start_server_time: 1000,
    roster: [
      { clientNum: 0, name: "A" },
      { clientNum: 1, name: "B" },
    ],
    ...overrides,
  };
}

test("score_updates is derived from death events, not the scores_duel command's constant/unrelated fields", () => {
  // Same shape as a real bloodrun duel: clientNum 1 kills clientNum 0 twice,
  // then kills itself (suicide - decrements its own tally by 1), then
  // clientNum 0 kills clientNum 1 once. Real values confirmed by direct demo
  // inspection (2026-09-17): the old scores_duel-parsing approach read a
  // constant "2 0" for the whole match regardless of these kills - completely
  // disconnected from who actually scored.
  const deaths = [
    { event: "death", game_time_ms: 100, victim_clientNum: 0, killer_clientNum: 1, weapon: "rocketlauncher" },
    { event: "death", game_time_ms: 200, victim_clientNum: 0, killer_clientNum: 1, weapon: "rocketlauncher" },
    { event: "death", game_time_ms: 200, victim_clientNum: 1, killer_clientNum: 1, weapon: "rocketlauncher" },
    { event: "death", game_time_ms: 300, victim_clientNum: 1, killer_clientNum: 0, weapon: "lightninggun" },
  ];
  const povReplays = [
    { clientNum: 0, replay: { meta: baseMeta(), events: deaths } },
    { clientNum: 1, replay: { meta: baseMeta(), events: [] } },
  ];

  const merged = mergeReplays(povReplays);
  const updates = merged.meta.score_updates;
  assert.equal(updates.length, 4);
  assert.deepEqual(updates[0].byClient, { 0: 0, 1: 1 });
  assert.deepEqual(updates[1].byClient, { 0: 0, 1: 2 });
  assert.deepEqual(updates[2].byClient, { 0: 0, 1: 1 });
  assert.deepEqual(updates[3].byClient, { 0: 1, 1: 1 });
});

test("mergePickups prefers an exact entity-sourced pickup over an unsourced PVS-heuristic duplicate of the same spot", () => {
  const povReplays = [
    {
      clientNum: 0,
      replay: {
        meta: baseMeta(),
        events: [
          // POV 0 never had player 1 in view close enough to confirm the pickup
          // itself - only the PVS heuristic's own "item vanished near someone"
          // guess (no `source` field, exactly what StaticItemTracker emits).
          {
            event: "pickup",
            game_time_ms: 100,
            item: "item_armor_body",
            x: 100,
            y: 200,
            z: 300,
            action: "pickup",
            clientNum: 1,
          },
        ],
      },
    },
    {
      clientNum: 1,
      replay: {
        meta: baseMeta(),
        events: [
          // POV 1 is the picker's own demo: exact entity/ps-sourced pickup.
          {
            event: "pickup",
            game_time_ms: 100,
            item: "item_armor_body",
            x: 100,
            y: 200,
            z: 300,
            action: "pickup",
            clientNum: 1,
            source: "ps",
          },
        ],
      },
    },
  ];

  const merged = mergeReplays(povReplays);
  const pickups = merged.events.filter((e) => e.event === "pickup");
  assert.equal(pickups.length, 1, "the two observations of one physical pickup collapse into one event");
  assert.equal(pickups[0].source, "ps");
});

test("mergeProjectiles clears an eid immediately once its own source POV reports it gone, without waiting for cross-POV staleness", () => {
  const povReplays = [
    {
      clientNum: 0,
      replay: {
        meta: baseMeta(),
        events: [
          {
            event: "projectiles",
            game_time_ms: 100,
            projectiles: [{ eid: 1, weapon: 5, weapon_slug: "rocketlauncher", clientNum: 0, x: 0, y: 0, z: 0, vx: 900, vy: 0, vz: 0 }],
          },
          // This POV's own trailing-empty-frame, 25ms later (well under
          // PROJECTILE_STALE_MS=200) - real bug: without honoring this as
          // an explicit "gone" signal, the eid stays in byEid (not yet
          // stale by the timer) and, if neither stream produces another
          // tick for a long time (nothing else airborne), it never gets
          // re-evaluated - the last frame keeps reporting a frozen ghost.
          { event: "projectiles", game_time_ms: 125, projectiles: [] },
        ],
      },
    },
    { clientNum: 1, replay: { meta: baseMeta(), events: [] } },
  ];

  const merged = mergeReplays(povReplays);
  const frames = merged.events.filter((e) => e.event === "projectiles");
  const last = frames[frames.length - 1];
  assert.equal(last.game_time_ms, 125);
  assert.equal(last.projectiles.length, 0, "the source POV's own empty frame must clear the eid immediately");
});

test("mergePositions carries map_name/gametype on every frame, not just the one-time match_start event", () => {
  const povReplays = [
    {
      clientNum: 0,
      replay: {
        meta: baseMeta(),
        events: [
          { event: "positions", game_time_ms: 100, players: [{ clientNum: 0, x: 1, y: 2, z: 3, yaw: 0 }] },
          { event: "positions", game_time_ms: 125, players: [{ clientNum: 0, x: 4, y: 5, z: 6, yaw: 0 }] },
        ],
      },
    },
    { clientNum: 1, replay: { meta: baseMeta(), events: [] } },
  ];

  const merged = mergeReplays(povReplays);
  const frames = merged.events.filter((e) => e.event === "positions");
  assert.ok(frames.length >= 2);
  for (const f of frames) {
    assert.equal(f.map_name, "bloodrun");
    assert.equal(f.gametype, "duel");
  }
});
