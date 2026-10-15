// Pure reshaping of the `series` / `snapshot` answers into aligned columns for
// the charts (tested with `node --test`, no React, no DOM).
//
// Raw rows (ranges 1h, 6h) and minute rows (24h and up) name some columns
// differently (cpu vs cpu_avg, mem vs mem_max, ...): `pick` takes the first
// key a row has.

import { kindLabel } from './format.js';

const isNum = (v) => typeof v === 'number' && Number.isFinite(v);

/** First finite number among `keys` of `row`, else null. */
export function pick(row, ...keys) {
  if (!row) return null;
  for (const key of keys) {
    if (isNum(row[key])) return row[key];
  }
  return null;
}

/** Sorted unique timestamps over several row lists. */
export function mergeTimes(...lists) {
  const seen = new Set();
  for (const rows of lists) {
    for (const r of rows || []) {
      if (isNum(r.ts)) seen.add(r.ts);
    }
  }
  return [...seen].sort((a, b) => a - b);
}

/** One column over `xs`: value of `fn(row)` at each timestamp, null where the list has no row. */
export function column(rows, xs, fn) {
  const byTs = new Map();
  for (const r of rows || []) byTs.set(r.ts, r);
  return xs.map((t) => {
    const r = byTs.get(t);
    return r ? fn(r) : null;
  });
}

/** Ports of `insts` (keys are strings in the JSON) as ascending numbers. */
export function sortedPorts(insts) {
  return Object.keys(insts || {})
    .map((k) => Number(k))
    .filter((n) => Number.isInteger(n))
    .sort((a, b) => a - b);
}

/** Rows of one core (-1 = all cores) from the flat `cores` list. */
export function coreRows(cores, core) {
  return (cores || []).filter((r) => r.core === core);
}

/** Core numbers present in the flat `cores` list: -1 first when present, then ascending. */
export function coreIds(cores) {
  return [...new Set((cores || []).map((r) => r.core).filter(Number.isInteger))].sort((a, b) => a - b);
}

/**
 * Cumulative columns for a stacked area. `columns` run bottom to top; the result keeps the
 * order, each value being the running total (null counts as 0, a point where every layer is
 * null stays null).
 */
export function stackColumns(columns) {
  const n = columns.length ? columns[0].length : 0;
  const out = columns.map(() => new Array(n).fill(null));
  for (let i = 0; i < n; i += 1) {
    let total = 0;
    let any = false;
    columns.forEach((col, k) => {
      if (isNum(col[i])) {
        total += col[i];
        any = true;
      }
      out[k][i] = any ? total : null;
    });
  }
  return out;
}

/** Last non-null value of a column, null when there is none. */
export function lastValue(col) {
  for (let i = (col || []).length - 1; i >= 0; i -= 1) {
    if (isNum(col[i])) return col[i];
  }
  return null;
}

/** Sum of the `events_24h` map of a snapshot. */
export function eventsTotal(snapshot) {
  const map = snapshot?.events_24h || {};
  return Object.values(map).reduce((a, v) => a + (isNum(v) ? v : 0), 0);
}

/** Players now: sum over the latest instance rows; null when no instance reports players. */
export function playersNow(snapshot) {
  const rows = snapshot?.insts_last || [];
  const vals = rows.map((r) => r.players).filter(isNum);
  return vals.length ? vals.reduce((a, v) => a + v, 0) : null;
}

/** Share of disk used, 0-100, or null. */
export function diskUsedPct(host) {
  if (!host || !isNum(host.disk_used) || !isNum(host.disk_total) || host.disk_total <= 0) return null;
  return (host.disk_used / host.disk_total) * 100;
}

/**
 * Per-core 24 h p95 of busy %: `{ peak, cores: [{ core, p95 }] }` over real cores (the all-cores
 * row, key -1, is left out); null when the collector sent no `core_p95_24h` (older collector).
 * JSON keys are strings.
 */
export function corePeaks(snapshot) {
  const map = snapshot?.core_p95_24h;
  if (!map || typeof map !== 'object') return null;
  const cores = Object.keys(map)
    .map((k) => ({ core: Number(k), p95: map[k] }))
    .filter((c) => Number.isInteger(c.core) && c.core >= 0 && isNum(c.p95))
    .sort((a, b) => a.core - b.core);
  if (!cores.length) return null;
  return { peak: Math.max(...cores.map((c) => c.p95)), cores };
}

/** Late frames over 24 h summed across instances: `{ late, frames, pct }`; null without frames. */
export function lateFrames24h(snapshot) {
  const insts = snapshot?.insts;
  if (!Array.isArray(insts)) return null;
  let late = 0;
  let frames = 0;
  for (const i of insts) {
    if (isNum(i.late_24h)) late += i.late_24h;
    if (isNum(i.frames_24h)) frames += i.frames_24h;
  }
  if (frames <= 0) return null;
  return { late, frames, pct: (late / frames) * 100 };
}

/** Stale host (collector stopped writing): `{ ageS, text }`, null for a host that is not stale. */
export function staleInfo(host) {
  if (host?.state !== 'stale') return null;
  const age = host?.snapshot?.data_age_s;
  const ageS = isNum(age) ? age : null;
  return { ageS, text: host?.verdict?.reason || 'collector data is old' };
}

/** "fleet reference" when the slot count uses the fleet median load, else null. */
export function refNote(verdict) {
  return verdict?.ref_source === 'fleet' ? 'fleet reference' : null;
}

// ---- health board ------------------------------------------------------------------

/** Event kinds that say nothing about health (a server started or stopped). */
const QUIET_KINDS = new Set(['instance_new', 'instance_gone']);
/** Area of the findings that says the same as an open event of that kind. */
const KIND_AREA = {
  core_saturated: 'cpu', steal_high: 'steal', mem_low: 'memory', oom_kill: 'memory',
  disk_low: 'disk', frames_late: 'frames',
};
const HEALTH_LABEL = { problem: 'Problem', watch: 'Watch', nodata: 'No data', ok: 'OK' };
const HEALTH_RANK = { problem: 0, watch: 1, nodata: 2, ok: 3 };

/** Open events of a snapshot, oldest first; null for an older collector without the field. */
export function openEvents(snapshot) {
  const list = snapshot?.events_open;
  if (!Array.isArray(list)) return null;
  return list
    .filter((e) => e && e.state === 'open' && isNum(e.ts))
    .sort((a, b) => a.ts - b.ts || (a.id || 0) - (b.id || 0));
}

const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;

/** The verdict's busy-event reason ("frames_late 2 with players ...") in plain words, else null. */
function overloadText(verdict) {
  const reason = String(verdict?.reason || '');
  let m = /^frames_late (\d+) with players/.exec(reason);
  if (m) return `${plural(Number(m[1]), 'late-frame event', 'late-frame events')} with players in the last 24 hours.`;
  m = /^core_saturated (\d+) with players/.exec(reason);
  if (m) return `${plural(Number(m[1]), 'core saturation event', 'core saturation events')} with players in the last 24 hours.`;
  return null;
}

/** "2 events in the last 24 hours (Memory low 2)." from `events_24h`, null when there were none. */
function recentEventsText(snapshot) {
  const map = snapshot?.events_24h || {};
  const kinds = Object.keys(map).filter((k) => !QUIET_KINDS.has(k) && isNum(map[k]) && map[k] > 0).sort();
  if (!kinds.length) return null;
  const n = kinds.reduce((a, k) => a + map[k], 0);
  return `${plural(n, 'event', 'events')} in the last 24 hours (${kinds.map((k) => `${kindLabel(k)} ${map[k]}`).join(', ')}).`;
}

function health(status, reason, items) {
  return { status, label: HEALTH_LABEL[status], reason, items };
}

/**
 * Board status of one `GET hosts` row with its `findings(...)` list:
 *   problem - unreachable / no sudo, verdict overloaded, an open critical event, a problem finding;
 *   watch   - stale data, verdict tight, an open warning event, a warning finding (noisy
 *             neighbour, CPU above the planning limit, ...), warnings in the last 24 h, an
 *             outdated collector;
 *   nodata  - not installed, no data yet, no data under load (verdict unknown);
 *   ok      - everything else.
 * Returns `{ status, label, reason, items }`: `reason` is one sentence for the card, `items`
 * the things to look at (`{ level: problem|watch, what, since }`, problems first, `since` a
 * unix time or null). Never throws on partial input.
 */
export function hostHealth(row, list) {
  const found = Array.isArray(list) ? list : [];
  const state = row?.state;
  const snapshot = row?.snapshot;
  if (state === 'unreachable' || state === 'no_sudo') {
    const what = row?.error || (state === 'no_sudo'
      ? 'The SSH user has no passwordless sudo.'
      : 'The host did not answer the SSH query.');
    return health('problem', what, [{ level: 'problem', what, since: null }]);
  }
  if (state === 'not_installed') {
    return health('nodata', 'Host metrics are not installed on this host: use Apply to host.', []);
  }
  if (!row || state === 'no_data' || !snapshot || typeof snapshot !== 'object') {
    return health('nodata', 'The collector has not written any data yet.', []);
  }
  if (state === 'stale') {
    // its open events and findings describe the past: only the staleness is reported
    const data = found.find((f) => f?.area === 'data');
    const what = data?.text || 'Collector data is old - the collector or the host is down.';
    const since = isNum(snapshot.now) && isNum(snapshot.data_age_s) ? snapshot.now - snapshot.data_age_s : null;
    return health('watch', what, [{ level: 'watch', what, since }]);
  }

  const problems = [];
  const watch = [];
  const covered = new Set();
  for (const e of openEvents(snapshot) || []) {
    if (QUIET_KINDS.has(e.kind)) continue;
    const item = {
      level: e.severity === 'crit' ? 'problem' : 'watch',
      what: `${kindLabel(e.kind)}${e.message ? `: ${e.message}` : ''}`,
      since: e.ts,
    };
    (item.level === 'problem' ? problems : watch).push(item);
    if (KIND_AREA[e.kind]) covered.add(KIND_AREA[e.kind]);
  }
  const verdict = row.verdict;
  const overload = verdict?.status === 'overloaded' ? overloadText(verdict) : null;
  if (overload) problems.push({ level: 'problem', what: overload, since: null });
  for (const f of found) {
    if (!f || covered.has(f.area)) continue;
    if (f.level === 'problem') problems.push({ level: 'problem', what: f.text, since: null });
    else if (f.level === 'warning') watch.push({ level: 'watch', what: f.text, since: null });
  }
  // a verdict the findings did not explain still counts, in its own words
  if (verdict?.status === 'overloaded' && !problems.length) {
    problems.push({ level: 'problem', what: `Overloaded: ${verdict.reason}.`, since: null });
  }
  if (verdict?.status === 'tight' && !problems.length && !watch.length) {
    watch.push({ level: 'watch', what: `Capacity is tight: ${verdict.reason}.`, since: null });
  }
  if (state === 'outdated') {
    watch.push({ level: 'watch', what: `Collector ${row.version || 'version unknown'} is outdated: use Apply to host.`, since: null });
  }
  const recent = recentEventsText(snapshot);
  if (recent && !problems.length && !watch.length) watch.push({ level: 'watch', what: recent, since: null });

  const items = [...problems, ...watch];
  if (problems.length) return health('problem', problems[0].what, items);
  if (watch.length) return health('watch', watch[0].what, items);
  if (!verdict || verdict.status === 'unknown') {
    return health('nodata', 'No data under load yet: no match has been played on this host, so its capacity is unknown.', []);
  }
  const room = found.find((f) => f?.area === 'room');
  return health('ok', room?.text || found[0]?.text || 'All checks passed.', []);
}

/** `[{ row, health }]` sorted problems first, then watch, no data, ok; by host name inside. */
export function sortByHealth(entries) {
  return [...(entries || [])].sort((a, b) => (
    (HEALTH_RANK[a.health?.status] ?? 9) - (HEALTH_RANK[b.health?.status] ?? 9)
    || String(a.row?.name || '').localeCompare(String(b.row?.name || ''), undefined, { sensitivity: 'base' })
  ));
}

/** Number of hosts per board status. */
export function healthCounts(healths) {
  const out = { problem: 0, watch: 0, nodata: 0, ok: 0 };
  for (const h of healths || []) if (h && h.status in out) out[h.status] += 1;
  return out;
}

/** Host id of `?host=<id>` in a location search string, null when absent or not a positive integer. */
export function hostIdFromSearch(search) {
  if (typeof search !== 'string' || !search) return null;
  const raw = new URLSearchParams(search).get('host');
  if (!raw || !/^\d+$/.test(raw)) return null;
  const id = Number(raw);
  return id > 0 ? id : null;
}
