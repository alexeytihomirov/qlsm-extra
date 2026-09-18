import assert from "node:assert/strict";
import { test } from "node:test";
import { QLDemoParser } from "./demo-parser.js";
import { SVC_SNAPSHOT, SVC_SERVERCOMMAND, SVC_EOF } from "./constants.js";
// Cross-directory test-only imports: demo-editor/lib/*-write.js are the
// encode-side mirrors of this parser, already used the same way by
// demo-editor/lib/gamestate-writer.test.mjs (which imports QLDemoParser
// from here) — just the reverse direction, purely to build wire-format test
// fixtures.
import { buildGamestateMessage } from "../../../demo-editor/lib/gamestate-writer.js";
import {
  buildEncodeTable,
  createMsgWriter,
  writeBits,
  huffmanWriteByte,
  huffmanWriteLong,
  huffmanWriteString,
} from "../../../demo-editor/lib/huffman-write.js";

function frameAsDemoFile(body) {
  const header = new ArrayBuffer(8);
  new DataView(header).setInt32(0, 0, true);
  new DataView(header).setInt32(4, body.length, true);
  const trailerBuf = new ArrayBuffer(8);
  new DataView(trailerBuf).setInt32(0, -1, true);
  new DataView(trailerBuf).setInt32(4, -1, true);
  const out = new Uint8Array(8 + body.length + 8);
  out.set(new Uint8Array(header), 0);
  out.set(body, 8);
  out.set(new Uint8Array(trailerBuf), 8 + body.length);
  return out;
}

function trailerOnlyBuffer() {
  const buf = new ArrayBuffer(8);
  const view = new DataView(buf);
  view.setInt32(0, -1, true);
  view.setInt32(4, -1, true);
  return new Uint8Array(buf);
}

test("parseAll() on a trailer-only buffer finishes immediately with no errors", () => {
  const parser = new QLDemoParser(trailerOnlyBuffer());
  const result = parser.parseAll();
  assert.equal(result, parser);
  assert.deepEqual(parser.errors, []);
  assert.equal(parser.snapshots.length, 0);
});

test("parseOnePacket() on a trailer-only buffer reports done immediately", () => {
  const parser = new QLDemoParser(trailerOnlyBuffer());
  const result = parser.parseOnePacket();
  assert.deepEqual(result, { done: true });
});

test("parseOnePacket() reports done on a malformed packet header without throwing", () => {
  const buf = new ArrayBuffer(8);
  const view = new DataView(buf);
  view.setInt32(0, 5, true); // seq
  view.setInt32(4, -999, true); // invalid length
  const parser = new QLDemoParser(new Uint8Array(buf));
  const result = parser.parseOnePacket();
  assert.deepEqual(result, { done: true });
  assert.equal(parser.errors.length, 1);
});

// Finding 5: parseGamestate used to read serverCommandSequence via
// huffmanReadLong right after the SVC_GAMESTATE byte, but discarded it
// instead of storing it — demo-editor/lib/cutter.js needs the real value to
// build a format-correct synthesized gamestate instead of hardcoding 0.
test("parseGamestate captures serverCommandSequence onto gamestate.serverCommandSequence", () => {
  const body = buildGamestateMessage({
    configstrings: {},
    baselines: [],
    clientNum: 0,
    checksumFeed: 0,
    serverCommandSequence: 4242,
  });
  const parser = new QLDemoParser(frameAsDemoFile(body));
  parser.parseAll();
  assert.deepEqual(parser.errors, []);
  assert.equal(parser.gamestate.serverCommandSequence, 4242);
});

// Finding 6: huffman.js's getBit() returns 0 forever (without ever
// advancing its cursor) once past the buffer's end, so a truncated
// snapshot's entity list previously never saw its ENTITYNUM_NONE
// terminator and grew `entities` without bound — a hang, not a crash. This
// JS parser now runs on the main thread against user-supplied demo bytes
// (demo-editor/lib/cutter.js), so that's reachable from an untrusted file
// pick. This fixture deliberately omits the entity-list terminator to
// reproduce exactly that truncation. Kept intentionally minimal: if the
// MAX_GENTITIES guard in parsePacketEntities() regresses, this loop no
// longer throws and instead spins forever — node:test's default timeout is
// Infinity (it will NOT fail this test on its own), so the explicit
// `timeout` below is what actually turns a regression into a fast,
// reported failure instead of a suite-wide hang.
test("a truncated snapshot (entity list cut off mid-stream) fails fast instead of hanging", { timeout: 5000 }, () => {
  const table = buildEncodeTable();
  const writer = createMsgWriter();
  huffmanWriteLong(writer, table, 0); // reliableSequenceAcknowledge
  huffmanWriteByte(writer, table, SVC_SNAPSHOT);
  huffmanWriteLong(writer, table, 1000); // serverTime
  huffmanWriteByte(writer, table, 0); // deltaByte = 0 (no delta)
  huffmanWriteByte(writer, table, 0); // snapFlags (discarded)
  huffmanWriteByte(writer, table, 0); // areamaskLen = 0
  huffmanWriteByte(writer, table, 0); // playerstate lc = 0
  writeBits(writer, table, 0, 1); // extended playerstate block off
  // Deliberately no ENTITYNUM_NONE terminator here — the packet just ends,
  // simulating a truncated/malformed demo mid-entity-list.
  const body = writer.data.slice(0, Math.ceil(writer.bit.value / 8));

  const parser = new QLDemoParser(frameAsDemoFile(body));
  const result = parser.parseOnePacket();
  // parseSnapshot's own try/catch converts the guard's thrown error into a
  // recorded parser.errors entry rather than an uncaught throw — the
  // packet is still reported as parsed (done: false), just with the
  // corrupt-entities error recorded, matching the existing
  // "bad packet header" error-handling style in this file.
  assert.equal(result.done, false);
  assert.equal(parser.errors.length, 1);
  assert.match(parser.errors[0], /MAX_GENTITIES/);
});

// Real QL servers re-broadcast CS_SERVERINFO mid-match (e.g. on the
// PRE_GAME -> IN_PROGRESS transition) as a "cs" server command whose raw
// wire text has a trailing space AFTER the closing quote — confirmed by
// decoding a real captured .dm_91 (demo-editor/demos/), where the initial
// gamestate's configstring 0 is clean but every later "cs 0 ..." command's
// text ends in `..."` followed by a space. parseServerCommand used to
// build `rest` via `text.split(/\s+/).join(" ")` — which also tokenizes on
// spaces INSIDE the quoted value (e.g. "Test Frontier Server #1") — then
// re-split rest on " " and strip only a quote anchored at the very start
// and end of the reassembled string via `replace(/^"|"$/g, "")`. The
// trailing wire-space becomes the reassembled string's actual last
// character, so the `"$` anchor never matches and the closing quote is
// left attached to the value. demo-editor/lib/cutter.js later captures
// whatever configstrings[0] currently holds as the synthesized gamestate
// for an exported clip cut after this point — the corrupted
// `mapname\phrantic" ` value is what real playback of that exported clip
// then fails to load a map for (CM_LoadMap "maps/phrantic\".bsp" not
// found), even though the source demo's OWN initial gamestate was clean
// and full playback of the source demo never re-reads mapname after
// CG_Init, so the corruption was invisible there.
test("parseServerCommand: a 'cs' update with spaces inside the quoted value and a trailing space after the closing quote is stored without corruption", () => {
  const table = buildEncodeTable();
  const writer = createMsgWriter();
  huffmanWriteLong(writer, table, 0); // reliableSequenceAcknowledge
  huffmanWriteByte(writer, table, SVC_SERVERCOMMAND);
  huffmanWriteLong(writer, table, 1); // command seq
  huffmanWriteString(writer, table, 'cs 0 "\\sv_hostname\\Test Frontier Server #1\\mapname\\phrantic" ');
  huffmanWriteByte(writer, table, SVC_EOF);
  const body = writer.data.slice(0, Math.ceil(writer.bit.value / 8));

  const parser = new QLDemoParser(frameAsDemoFile(body));
  parser.parseAll();
  assert.deepEqual(parser.errors, []);
  assert.equal(parser.gamestate.configstrings[0], "\\sv_hostname\\Test Frontier Server #1\\mapname\\phrantic");
});
