// Timing decisions of the host dialog's auto-refresh, kept pure so they can be tested.
//
// The collector writes a raw sample every 10 s (ranges 1h/6h read those); the minute tables
// behind 24h/7d/30d change once a minute, so asking more often only costs SSH round trips.

export const FAST_RANGES = ['1h', '6h'];
export const FAST_INTERVAL_MS = 10000;
export const SLOW_INTERVAL_MS = 60000;
/** The host list (snapshot for the findings) is cached by the backend; never ask faster. */
export const SNAPSHOT_INTERVAL_MS = 60000;

export function refreshIntervalMs(range) {
  return FAST_RANGES.includes(range) ? FAST_INTERVAL_MS : SLOW_INTERVAL_MS;
}

/**
 * Whether a background refresh is due now.
 *   enabled, isOpen, visible  all must be true
 *   inFlight                  a request is still running: skip this tick
 *   lastAttemptAt, now        ms timestamps; lastAttemptAt null = never loaded, so not due
 *                             (the regular load on open/range change does that)
 *   intervalMs                how long after the last attempt
 */
export function shouldRefresh({
  enabled, isOpen, visible, inFlight, lastAttemptAt, now, intervalMs,
}) {
  if (!enabled || !isOpen || !visible || inFlight) return false;
  if (lastAttemptAt === null || lastAttemptAt === undefined) return false;
  return now - lastAttemptAt >= intervalMs;
}

/** Whole seconds since `at` (ms), never negative; null when there is no `at`. */
export function ageSeconds(at, now) {
  if (at === null || at === undefined) return null;
  return Math.max(0, Math.floor((now - at) / 1000));
}

/** "Updated 5 s ago" / "Updated 2 min ago"; '' when nothing was loaded yet. */
export function updatedText(at, now) {
  const s = ageSeconds(at, now);
  if (s === null) return '';
  if (s < 60) return `Updated ${s} s ago`;
  return `Updated ${Math.floor(s / 60)} min ago`;
}
