// POV identity / live-window helpers shared by demo-editor (match-set.js
// re-exports these) and match-to-replay.js. Canonical home is lib/qldemo so
// live-overlay never has to depend on demo-editor - see zip-read.js for the
// same pattern.

export const SERVER_TIME_RESET_MS = 1000;

export function snapTime(snap) {
  const t = snap?.t ?? snap?.serverTime;
  return Number.isFinite(t) ? t : null;
}

// Live occupant of this POV file. Leftover prefix snaps keep the previous
// occupant's playerState.clientNum (it is almost never re-delta'd). After a
// mid-file serverTime drop the last gamestate.clientNum is the connection
// identity, even when cloned leftover PS still says otherwise.
export function liveClientNumFromParser(parser) {
  const snaps = parser?.snapshots || [];
  const gs = parser?.gamestate?.clientNum;
  let firstCn = null;
  let lastCn = null;
  let prevT = null;
  let sawReset = false;
  for (const snap of snaps) {
    const t = snapTime(snap);
    const cn = snap.playerState?.clientNum;
    if (Number.isInteger(cn) && cn >= 0) {
      if (firstCn == null) firstCn = cn;
      lastCn = cn;
    }
    if (prevT != null && t != null && prevT - t > SERVER_TIME_RESET_MS) {
      sawReset = true;
    }
    if (t != null) prevT = t;
  }
  if (sawReset) {
    if (Number.isInteger(gs) && gs >= 0 && firstCn != null && gs !== firstCn) return gs;
    if (lastCn != null && firstCn != null && lastCn !== firstCn) return lastCn;
    if (Number.isInteger(gs) && gs >= 0) return gs;
    if (lastCn != null) return lastCn;
  }
  if (lastCn != null) return lastCn;
  return Number.isInteger(gs) && gs >= 0 ? gs : 0;
}

export function liveSnapRange(index, parser) {
  const snaps = index?.snapshots?.length ? index.snapshots : parser?.snapshots || [];
  if (!snaps.length) return { first: null, last: null, count: 0, sawReset: false };
  let dropAt = 0;
  let prev = snapTime(snaps[0]);
  for (let i = 1; i < snaps.length; i++) {
    const cur = snapTime(snaps[i]);
    if (prev != null && cur != null && prev - cur > SERVER_TIME_RESET_MS) dropAt = i;
    if (cur != null) prev = cur;
  }
  const live = snaps.slice(dropAt);
  return {
    first: snapTime(live[0]),
    last: snapTime(live[live.length - 1]),
    count: live.length,
    sawReset: dropAt > 0,
  };
}
