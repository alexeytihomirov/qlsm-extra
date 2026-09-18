import {
  CS_MODELS,
  CS_SOUNDS,
  CS_PLAYERS,
  CS_SERVERINFO,
  CS_STRING_MAP,
  ENTITYNUM_NONE,
  SVC_BASELINE,
  SVC_CONFIGSTRING,
  SVC_EOF,
  SVC_GAMESTATE,
  SVC_SERVERCOMMAND,
  SVC_SNAPSHOT,
  TEAM_SPECTATOR,
  GENTITYNUM_BITS,
  MAX_CLIENTS,
  MAX_GENTITIES,
  PACKET_MASK,
} from "./constants.js";
import {
  cloneEntityState,
  readDeltaEntity,
  readDeltaPlayerState,
} from "./delta.js?v=20260712b";
import { isNewEntityEvent } from "./entity-events.js?v=20260830b";
import {
  createDemoMsgHuffman,
  createMsgReader,
  huffmanReadByte,
  huffmanReadLong,
  huffmanReadShort,
  huffmanReadString,
  huffmanReadBigString,
  readBits,
} from "./huffman.js";

function parseConfigKv(text) {
  const out = {};
  if (!text) return out;
  const parts = text.split("\\");
  const start = parts[0] === "" ? 1 : 0;
  for (let i = start; i + 1 < parts.length; i += 2) out[parts[i]] = parts[i + 1];
  return out;
}

function parseServerinfoKv(text) {
  const out = {};
  if (!text || text[0] !== "\\") return out;
  const parts = text.split("\\");
  for (let i = 1; i + 1 < parts.length; i += 2) out[parts[i]] = parts[i + 1];
  return out;
}

export class QLDemoParser {
  constructor(buffer) {
    this.buffer = buffer instanceof Uint8Array ? buffer : new Uint8Array(buffer);
    this.offset = 0;
    this.huffman = createDemoMsgHuffman();
    this.gamestate = {
      clientNum: 0,
      config: {},
      configstrings: {},
      players: {},
      spectators: {},
      models: {},
    };
    this.snapshots = [];
    this.snapRing = new Array(32).fill(null);
    this.baselines = [];
    this.serverCommands = [];
    this.lastServerTime = 0;
    this.snapshotsParsed = 0;
    this.gamestateCount = 0;
    // Last reliableSequenceAcknowledge long seen at the start of any packet
    // (see parseOnePacket()) — UDT's WriteGameState() writes the parser's
    // live sequence counters into a synthesized gamestate rather than a
    // constant, and demo-editor/lib/cutter.js needs this real value to do
    // the same when it builds a mid-demo synthesized gamestate.
    this.lastReliableSequenceAcknowledge = 0;
    this.errors = [];
    this.entityEventTimes = new Int32Array(MAX_GENTITIES);
    this.leftoverPlayerNames = {};
    this.livePlayerNames = {};
  }

  readRawLong() {
    if (this.offset + 4 > this.buffer.length) return -1;
    const view = new DataView(this.buffer.buffer, this.buffer.byteOffset + this.offset, 4);
    const v = view.getInt32(0, true);
    this.offset += 4;
    return v;
  }

  readPacketBytes(length) {
    if (length < 0 || this.offset + length > this.buffer.length) return null;
    const slice = this.buffer.subarray(this.offset, this.offset + length);
    this.offset += length;
    return slice;
  }

  storeConfigString(index, text) {
    this.gamestate.configstrings[index] = text;
    const field = CS_STRING_MAP[index];
    if (field) {
      if (text.startsWith("\\")) this.gamestate.config[field] = parseServerinfoKv(text);
      else this.gamestate.config[field] = text.replace(/^"|"$/g, "");
      return;
    }
    if (index === CS_SERVERINFO) {
      this.gamestate.config.serverinfo = parseServerinfoKv(text);
      return;
    }
    if (index >= CS_PLAYERS && index < CS_PLAYERS + MAX_CLIENTS) {
      const clientNum = index - CS_PLAYERS;
      delete this.gamestate.players[clientNum];
      delete this.gamestate.spectators[clientNum];
      if (!text) return;
      const row = parseConfigKv(text);
      const dest = row.t === TEAM_SPECTATOR ? this.gamestate.spectators : this.gamestate.players;
      dest[clientNum] = row;
      if (dest === this.gamestate.players && row.n && this.livePlayerNames) {
        this.livePlayerNames[clientNum] = row.n;
        this.livePlayerNames[String(clientNum)] = row.n;
      }
      return;
    }
    if (index >= CS_MODELS && index < CS_SOUNDS) {
      this.gamestate.models[index - CS_MODELS] = text;
    }
  }

  parseGamestate(msg) {
    // A full SVC_GAMESTATE replaces the connection's CS_PLAYERS roster.
    // Leftover names from a previous occupant of this recorder slot must
    // not linger when the next match's gamestate omits an unchanged slot.
    this.gamestate.players = {};
    this.gamestate.spectators = {};
    this.gamestateCount++;
    // serverCommandSequence, immediately after the SVC_GAMESTATE byte the
    // caller (parseOnePacket) already consumed. Stored (not just read) so
    // demo-editor/lib/cutter.js can carry the real value forward into a
    // synthesized gamestate instead of hardcoding 0.
    this.gamestate.serverCommandSequence = huffmanReadLong(msg, this.huffman);
    while (true) {
      const cmd = huffmanReadByte(msg, this.huffman);
      if (cmd === SVC_EOF) break;
      if (cmd === SVC_CONFIGSTRING) {
        const idx = huffmanReadShort(msg, this.huffman);
        const text = huffmanReadBigString(msg, this.huffman);
        this.storeConfigString(idx, text);
      } else if (cmd === SVC_BASELINE) {
        const newnum = readBits(msg, this.huffman, GENTITYNUM_BITS);
        const { entity } = readDeltaEntity(msg, this.huffman, null, newnum);
        if (entity) this.baselines[newnum] = entity;
      }
    }
    this.gamestate.clientNum = huffmanReadLong(msg, this.huffman);
    this.gamestate.checksumFeed = huffmanReadLong(msg, this.huffman);
    const names = {};
    for (const [k, row] of Object.entries(this.gamestate.players || {})) {
      if (row && row.n) names[k] = row.n;
    }
    if (this.gamestateCount === 1) this.leftoverPlayerNames = { ...names };
    this.livePlayerNames = names;
    return this.gamestate;
  }

  parseServerCommand(msg) {
    const seq = huffmanReadLong(msg, this.huffman);
    const text = huffmanReadString(msg, this.huffman);
    const parts = text.split(/\s+/);
    const cmd = parts[0] || "";
    const rest = parts.slice(1).join(" ");
    if (cmd === "cs" || cmd === "bcs") {
      // Real QL servers send this as `cs <index> "<value>" ` — with a
      // trailing space AFTER the closing quote (confirmed against real
      // captured .dm_91 mid-match "cs 0" updates). The naive
      // `rest.split(" ")` + `replace(/^"|"$/g, "")` approach used to both
      // (a) tokenize on every space INSIDE the quoted value (breaking
      // values like sv_hostname's "Test Frontier Server #1") and (b) fail
      // to strip the closing quote whenever it wasn't the literal last
      // character of the reassembled string — the trailing wire-space
      // defeats the `"$` anchor, leaving `value" ` stored verbatim. Parse
      // directly against the un-tokenized text instead: index, then
      // everything between the first quote after it and the LAST quote in
      // the command, ignoring any trailing whitespace.
      const afterCmd = text.slice(cmd.length);
      const match = /^\s*(\d+)\s+"([\s\S]*)"\s*$/.exec(afterCmd);
      if (match) {
        const csNum = parseInt(match[1], 10);
        if (!isNaN(csNum)) this.storeConfigString(csNum, match[2]);
      }
    }
    const row = { seq, cmd, text: rest, serverTime: this.lastServerTime };
    this.serverCommands.push(row);
    return row;
  }

  parsePacketEntities(msg, oldSnap, serverTime) {
    const entities = [];
    const changedEntities = [];
    const tagChanged = (ent) => {
      if (!ent) return;
      const newEvent = isNewEntityEvent(ent, serverTime, this.entityEventTimes[ent.number]);
      ent.newEvent = newEvent;
      if (newEvent) this.entityEventTimes[ent.number] = serverTime;
      changedEntities.push(ent);
    };

    let oldIndex = 0;
    let oldNum = 99999;
    let oldState = null;
    if (oldSnap?.entities?.length) {
      oldState = oldSnap.entities[0];
      oldNum = oldState.number;
    }

    // Bounded-iteration guard: on a truncated/malformed buffer,
    // huffman.js's getBit() returns 0 forever once past the buffer's end
    // without ever advancing its cursor (a pre-existing latent bug), so
    // readBits() here can keep returning the same non-ENTITYNUM_NONE value
    // indefinitely — this loop would otherwise never see its terminator and
    // grow `entities` without bound. This JS parser now runs on the main
    // thread against user-supplied demo bytes (demo-editor/lib/cutter.js),
    // so a malformed file reaching this loop must fail loudly instead of
    // hanging the tab. MAX_GENTITIES is already a generous ceiling: a real
    // snapshot can name at most MAX_GENTITIES distinct entity numbers before
    // it must have hit ENTITYNUM_NONE.
    let iterations = 0;
    while (true) {
      if (++iterations > MAX_GENTITIES) {
        throw new Error(
          "parsePacketEntities: exceeded MAX_GENTITIES iterations without finding ENTITYNUM_NONE — malformed or truncated demo",
        );
      }
      const newNum = readBits(msg, this.huffman, GENTITYNUM_BITS);
      if (newNum === ENTITYNUM_NONE) break;

      while (oldNum < newNum) {
        if (oldState) entities.push(cloneEntityState(oldState));
        oldIndex++;
        if (oldSnap && oldIndex < oldSnap.entities.length) {
          oldState = oldSnap.entities[oldIndex];
          oldNum = oldState.number;
        } else {
          oldNum = 99999;
          oldState = null;
        }
      }

      if (oldNum === newNum) {
        const { entity, changed } = readDeltaEntity(msg, this.huffman, oldState, newNum);
        if (entity) {
          entities.push(entity);
          if (changed) tagChanged(entity);
        }
        oldIndex++;
        if (oldSnap && oldIndex < oldSnap.entities.length) {
          oldState = oldSnap.entities[oldIndex];
          oldNum = oldState.number;
        } else {
          oldNum = 99999;
          oldState = null;
        }
        continue;
      }

      if (oldNum > newNum) {
        const baseline = this.baselines[newNum] || null;
        const { entity, changed } = readDeltaEntity(msg, this.huffman, baseline, newNum);
        if (entity) {
          entities.push(entity);
          if (changed) tagChanged(entity);
        }
        continue;
      }
    }

    while (oldNum !== 99999) {
      if (oldState) entities.push(cloneEntityState(oldState));
      oldIndex++;
      if (oldSnap && oldIndex < oldSnap.entities.length) {
        oldState = oldSnap.entities[oldIndex];
        oldNum = oldState.number;
      } else {
        oldNum = 99999;
        oldState = null;
      }
    }

    return { entities, changedEntities };
  }

  parseSnapshot(msg, packetLen, messageNum) {
    const serverTime = huffmanReadLong(msg, this.huffman);
    const deltaByte = huffmanReadByte(msg, this.huffman);
    huffmanReadByte(msg, this.huffman);
    const areamaskLen = huffmanReadByte(msg, this.huffman);
    for (let i = 0; i < areamaskLen; i++) huffmanReadByte(msg, this.huffman);
    let oldSnap = null;
    if (deltaByte > 0) {
      const deltaNum = messageNum - deltaByte;
      const candidate = this.snapRing[deltaNum & PACKET_MASK];
      if (candidate?.messageNum === deltaNum) oldSnap = candidate;
    }
    const ps = readDeltaPlayerState(msg, this.huffman, oldSnap?.playerState || null, this.gamestate.clientNum);
    let entities = [];
    let changedEntities = [];
    try {
      const parsed = this.parsePacketEntities(msg, oldSnap, serverTime);
      entities = parsed.entities;
      changedEntities = parsed.changedEntities;
    } catch (err) {
      this.errors.push(`entities @${messageNum}: ${err.message || err}`);
      if (packetLen > 0) msg.bit.value = packetLen * 8;
    }
    this.lastServerTime = serverTime;
    const snap = { messageNum, serverTime, delta: deltaByte, playerState: ps, entities, changedEntities };
    this.snapRing[messageNum & PACKET_MASK] = snap;
    this.snapshots.push(snap);
    this.snapshotsParsed++;
    return snap;
  }

  // Parses exactly one length-prefixed packet starting at the current
  // this.offset (advancing it past the packet). Extracted out of the old
  // parseAll() so callers other than parseAll() — namely
  // demo-editor/lib/cutter.js, which needs to stop at an arbitrary point in
  // time rather than after N snapshots or end-of-file — can drive the same
  // packet-by-packet dispatch loop directly instead of forking a second
  // copy of it.
  parseOnePacket(maxSnapshots = Infinity) {
    const packetStartOffset = this.offset;
    if (this.offset + 8 > this.buffer.length) return { done: true };
    const seq = this.readRawLong();
    const length = this.readRawLong();
    if (seq === -1 && length === -1) return { done: true };
    // 0x8000 (32768) matches the real engine's MAX_MSGLEN
    // (code/qcommon/qcommon.h: MAX_MSGLEN 16384*2) — the same ceiling
    // demo-editor/lib/concat.js and demo-editor/lib/cutter.js enforce. This
    // used to be an incorrect 0x4000 ceiling here, which would reject a
    // legally-sized 16-32KB packet with a misleading "past the end of the
    // recorded demo" error even though concatDemos() would accept it fine.
    if (seq === -1 || length === -1 || length <= 0 || length > 0x8000) {
      this.errors.push(`bad packet header seq=${seq} len=${length} @${this.offset}`);
      return { done: true };
    }
    const packet = this.readPacketBytes(length);
    if (!packet) return { done: true };
    const msg = createMsgReader(packet, this.huffman);
    // The leading reliableSequenceAcknowledge long, present at the start of
    // every packet. Captured (not just consumed) so a caller building a
    // synthesized gamestate mid-demo (demo-editor/lib/cutter.js) can carry
    // forward the real, live value instead of hardcoding 0 — see
    // this.gamestate.serverCommandSequence above for the matching case.
    this.lastReliableSequenceAcknowledge = huffmanReadLong(msg, this.huffman);
    // A single packet can bundle a snapshot preceded/followed by any number
    // of server commands (UDT ParseServerMessage's inner for(;;) loop) — it
    // is not one message per packet. Keep reading commands from this same
    // packet buffer until it's exhausted or we hit the EOF marker.
    const packetBits = packet.length * 8;
    let stop = false;
    let snapshot = null;
    try {
      while (!stop && msg.bit.value < packetBits) {
        const cmd = huffmanReadByte(msg, this.huffman);
        if (cmd === SVC_EOF) break;
        if (cmd === SVC_GAMESTATE) this.parseGamestate(msg);
        else if (cmd === SVC_SERVERCOMMAND) this.parseServerCommand(msg);
        else if (cmd === SVC_SNAPSHOT) {
          if (this.snapshotsParsed >= maxSnapshots) {
            stop = true;
            break;
          }
          snapshot = this.parseSnapshot(msg, packet.length, seq);
        } else {
          break;
        }
      }
    } catch (err) {
      this.errors.push(String(err.message || err));
      return { done: true };
    }
    if (stop) return { done: true };
    return { done: false, packetStartOffset, seq, snapshot };
  }

  parseAll(options = {}) {
    if (options.untilLiveIdentity) {
      return this.parseUntilLiveIdentity(options);
    }
    const maxSnapshots = options.maxSnapshots ?? Infinity;
    while (true) {
      const result = this.parseOnePacket(maxSnapshots);
      if (result.done) break;
    }
    return this;
  }

  // Walk leftover prefix snaps (high serverTime) until the mid-file reset
  // and the following gamestate, then a few live snaps. Used by demo-editor
  // POV labels: maxSnapshots from file start would freeze leftover CS_PLAYERS.
  parseUntilLiveIdentity(options = {}) {
    const RESET_MS = 1000;
    let prevT = null;
    let sawReset = false;
    let snapsAfterReset = 0;
    while (true) {
      const result = this.parseOnePacket(Infinity);
      if (result.done) break;
      const t = result.snapshot?.serverTime;
      if (prevT != null && t != null && prevT - t > RESET_MS) sawReset = true;
      if (sawReset) {
        if (result.snapshot) snapsAfterReset++;
        if (this.gamestateCount >= 2 && snapsAfterReset >= 8) break;
        if (snapsAfterReset >= 64) break;
      }
      if (!sawReset && this.snapshotsParsed > 20000) break;
      if (t != null) prevT = t;
    }
    return this;
  }

  mapName() {
    return this.gamestate.config.serverinfo?.mapname || "";
  }

  gametype() {
    return this.gamestate.config.serverinfo?.g_gametype || "";
  }

  playerRows() {
    return Object.keys(this.gamestate.players)
      .map((k) => ({ clientNum: parseInt(k, 10), ...this.gamestate.players[k] }))
      .filter((p) => p.n);
  }
}

export function parseDemoBuffer(buffer, options) {
  return new QLDemoParser(buffer).parseAll(options);
}
