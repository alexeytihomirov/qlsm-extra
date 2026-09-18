/** Wall / game clock from demo configstrings (level_start_time = fight start). */

export function parseLevelStartTimeMs(parser) {
  const raw =
    parser.gamestate.config?.level_start_time ?? parser.gamestate.configstrings?.[13];
  if (raw == null) return null;
  const n = Number(String(raw).replace(/"/g, "").trim());
  return Number.isFinite(n) && n > 0 ? n : null;
}

export function parseMatchClock(parser) {
  const recordingStartMs = parser.snapshots.length ? parser.snapshots[0].serverTime : 0;
  const fightStartMs = parseLevelStartTimeMs(parser) ?? recordingStartMs;
  const countdownLeadMs = Math.max(0, fightStartMs - recordingStartMs);
  const durationMs =
    parser.snapshots.length > 0
      ? parser.snapshots[parser.snapshots.length - 1].serverTime - recordingStartMs
      : 0;
  return { recordingStartMs, fightStartMs, countdownLeadMs, durationMs };
}
