import assert from "node:assert/strict";
import { test } from "node:test";
import { filterPickupEntities } from "./map-item-resolve.js";

// Real bloodrun.json shape: a duel-only quad sits at the same spot as a
// not_gametype:"duel" pair (TDM/FFA-only ammo variants nearby).
const ROWS = [
  { classname: "item_quad", x: 544, y: 800, z: 600, attrs: { not_gametype: "duel" } },
  { classname: "ammo_lightning", x: 592, y: 848, z: 592, attrs: { gametype: "duel" } },
  { classname: "ammo_lightning", x: 416, y: 832, z: 592, attrs: { not_gametype: "duel" } },
  { classname: "item_health", x: 0, y: 0, z: 0, attrs: {} },
  { classname: "target_speaker", x: 1, y: 2, z: 3, attrs: {} },
];

test("filterPickupEntities drops non-pickup classnames regardless of gametype", () => {
  const out = filterPickupEntities(ROWS, "duel");
  assert.ok(!out.some((r) => r.classname === "target_speaker"));
});

test("filterPickupEntities: raw numeric g_gametype '1' resolves to duel and applies duel-only/not-duel filters", () => {
  const out = filterPickupEntities(ROWS, "1").map((r) => r.classname + "@" + r.x);
  assert.deepEqual(out.sort(), ["ammo_lightning@592", "item_health@0"]);
});

test("filterPickupEntities: TDM (numeric '3') keeps the not_gametype:duel rows and drops the duel-only ones", () => {
  const out = filterPickupEntities(ROWS, "3").map((r) => r.classname + "@" + r.x);
  assert.deepEqual(out.sort(), ["ammo_lightning@416", "item_health@0", "item_quad@544"]);
});

test("filterPickupEntities: no gametype argument keeps every pickup row (back-compat, no filtering)", () => {
  const out = filterPickupEntities(ROWS);
  assert.equal(out.length, 4);
});
