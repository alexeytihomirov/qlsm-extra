// Pure reshaping of the `series` / `snapshot` answers into aligned columns for
// the charts (tested with `node --test`, no React, no DOM).
//
// Raw rows (ranges 1h, 6h) and minute rows (24h and up) name some columns
// differently (cpu vs cpu_avg, mem vs mem_max, ...): `pick` takes the first
// key a row has.

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
