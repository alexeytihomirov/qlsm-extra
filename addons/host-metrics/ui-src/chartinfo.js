// What the charts need besides the data: threshold lines from the addon settings, the server
// tick, scale headroom and the finding shown above a chart (pure, tested with `node --test`).

const isNum = (v) => typeof v === 'number' && Number.isFinite(v);

// QLDS default sv_fps is 40 (skills/ql-live/reference/cvar-metadata.md): one frame every 25 ms.
const DEFAULT_TICK_MS = 25;
// A frame is late when its gap is above 1.5 ticks (37.5 ms at 40 fps).
const LATE_FACTOR = 1.5;

const DEFAULTS = {
  verdict_target_pct: 70,
  core_saturated_pct: 95,
  steal_tight_pct: 5,
  disk_low_pct: 90,
  mem_reserve_pct: 20,
};

/** Setting as a finite number (settings arrive as strings or numbers), else the default. */
function setting(settings, key) {
  const raw = settings?.[key];
  if (raw === null || raw === undefined || (typeof raw === 'string' && !raw.trim())) return DEFAULTS[key];
  const n = Number(raw);
  return Number.isFinite(n) ? n : DEFAULTS[key];
}

const num = (v) => String(Math.round(v * 10) / 10);

/**
 * Threshold lines per chart, `[{ value, label, tone: 'warning'|'critical'|'neutral', hint }]`.
 * `tickMs` is the measured server frame time (null when unknown: the QLDS default is used and
 * `tickKnown` is false so the chart can say so).
 */
export function chartLimits(settings, tickMs) {
  const target = setting(settings, 'verdict_target_pct');
  const sat = setting(settings, 'core_saturated_pct');
  const steal = setting(settings, 'steal_tight_pct');
  const disk = setting(settings, 'disk_low_pct');
  const reserve = setting(settings, 'mem_reserve_pct');
  const tickKnown = isNum(tickMs) && tickMs > 0;
  const tick = tickKnown ? tickMs : DEFAULT_TICK_MS;
  const late = tick * LATE_FACTOR;
  return {
    cpu: [
      {
        value: target, tone: 'warning', label: `${num(target)} % planning limit`,
        hint: `Capacity planning keeps every core below ${num(target)} %; sustained load above it means no room for another server.`,
      },
      {
        value: sat, tone: 'critical', label: `${num(sat)} % saturated`,
        hint: `Above ${num(sat)} % the core is saturated: server frames come late and players see lag.`,
      },
    ],
    steal: [{
      value: steal, tone: 'warning', label: `${num(steal)} % noisy neighbour`,
      hint: `Steal above ${num(steal)} % means other customers of the provider take CPU time from this host.`,
    }],
    disk: [{
      value: disk, tone: 'warning', label: `${num(disk)} % disk low`,
      hint: `Above ${num(disk)} % used the collector opens a disk low event.`,
    }],
    frameGap: [
      {
        value: tick, tone: 'neutral', label: `${num(tick)} ms tick${tickKnown ? '' : ' (default)'}`,
        hint: tickKnown
          ? `The server runs a frame every ${num(tick)} ms; a gap near this line is normal.`
          : `No tick measured yet: the QLDS default of 40 frames per second (${num(tick)} ms) is shown.`,
      },
      {
        value: late, tone: 'warning', label: `${num(late)} ms late`,
        hint: `A gap above ${num(late)} ms (1.5 ticks) is a late frame: players see a hitch.`,
      },
    ],
    tickMs: tick,
    tickKnown,
    lateMs: late,
    memReservePct: reserve,
    /** Used-RAM line where the reserve starts, for a host with `total` bytes of RAM. */
    memReserve(total) {
      if (!isNum(total) || total <= 0) return [];
      return [{
        value: total * (1 - reserve / 100), tone: 'warning', label: `${num(reserve)} % reserve`,
        hint: `Capacity planning keeps ${num(reserve)} % of RAM free; used memory above this line eats into it.`,
      }];
    },
  };
}

/** Newest positive `tick_ms` of the series instance rows, else of the snapshot's last rows, else null. */
export function tickMsOf(series, snapshot) {
  let best = null;
  for (const rows of Object.values(series?.insts || {})) {
    for (const r of Array.isArray(rows) ? rows : []) {
      if (isNum(r?.tick_ms) && r.tick_ms > 0 && isNum(r.ts) && (!best || r.ts > best.ts)) best = r;
    }
  }
  if (best) return best.tick_ms;
  for (const r of Array.isArray(snapshot?.insts_last) ? snapshot.insts_last : []) {
    if (isNum(r?.tick_ms) && r.tick_ms > 0) return r.tick_ms;
  }
  return null;
}

/** Top of a y scale: 10 % above the data, never below `floor`, and every line inside it. */
export function yMaxWith(dataMax, floor, lines) {
  let top = Math.max(floor, isNum(dataMax) ? dataMax * 1.1 : 0);
  for (const l of lines || []) {
    if (isNum(l?.value)) top = Math.max(top, l.value * 1.15);
  }
  return top;
}

/** Largest number of a column, or null. */
export function peakOf(col) {
  let peak = null;
  for (const v of col || []) {
    if (isNum(v) && (peak === null || v > peak)) peak = v;
  }
  return peak;
}

const RANK = { problem: 3, warning: 2, info: 1, ok: 0 };

/**
 * The finding shown above a chart: the most severe of `area`. For `cpu`, `core` picks the
 * statement about that core (findings.js starts each with "Core N ").
 */
export function findingFor(list, area, { core } = {}) {
  let best = null;
  for (const f of Array.isArray(list) ? list : []) {
    if (f?.area !== area) continue;
    if (area === 'cpu' && core !== undefined && !String(f.text).startsWith(`Core ${core} `)) continue;
    if (!best || (RANK[f.level] ?? 0) > (RANK[best.level] ?? 0)) best = f;
  }
  return best;
}
