// Plain-English findings about a host (pure, tested with `node --test`, no React, no DOM).
//
//   findings({ snapshot, series, events, settings, range, verdict })
//     -> [{ level: 'ok'|'info'|'warning'|'problem', area, text }]
//
// `area` is cpu | room | frames | steal | memory | disk | data. The board passes the snapshot
// (and the verdict of the host row); the modal also passes the `series` and `events` of the
// chosen `range`. Without a series the CPU, steal and frame statements use the snapshot fields
// (24 h per-core p95, 7 d steal p95, 24 h late frames) and say so. Every number in a sentence
// comes from the data or the settings; a missing value drops the clause, never becomes 0.
import { diskUsedPct, sortedPorts } from './data.js';
import { fmtDuration } from './format.js';

const isNum = (v) => typeof v === 'number' && Number.isFinite(v);
const STALE_S = 120; // same as the backend: the collector ticks every 10 s

const RANGE_TEXT = {
  '1h': 'the last hour',
  '6h': 'the last 6 hours',
  '24h': 'the last 24 hours',
  '7d': 'the last 7 days',
  '30d': 'the last 30 days',
};

/** Setting as a finite number (settings arrive as strings or numbers), else the default. */
function setting(settings, key, fallback) {
  const raw = settings?.[key];
  if (raw === null || raw === undefined || (typeof raw === 'string' && !raw.trim())) return fallback;
  const n = Number(raw);
  return Number.isFinite(n) ? n : fallback;
}

const pct0 = (v) => `${Math.round(v)}`;
const gb1 = (bytes) => (bytes / 1073741824).toFixed(1);

function p95(values) {
  const v = values.filter(isNum).sort((a, b) => a - b);
  if (!v.length) return null;
  return v[Math.max(Math.ceil(0.95 * v.length) - 1, 0)];
}

const hhmm = (ts) => {
  const d = new Date(ts * 1000);
  const p = (n) => String(n).padStart(2, '0');
  return `${p(d.getHours())}:${p(d.getMinutes())}`;
};

const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;

function dataFinding(snapshot) {
  const age = snapshot?.data_age_s;
  if (!isNum(age)) {
    return { level: 'info', area: 'data', text: 'No data collected on this host yet.' };
  }
  if (age > STALE_S) {
    return {
      level: 'problem',
      area: 'data',
      text: `Collector data is ${fmtDuration(age)} old - the collector or the host is down.`,
    };
  }
  return null;
}

/** [{ core, p95, max }] from the series rows of one range; null without core rows. */
function coresFromSeries(series) {
  const rows = Array.isArray(series?.cores) ? series.cores : null;
  if (!rows) return null;
  const by = new Map();
  for (const r of rows) {
    if (!Number.isInteger(r?.core) || r.core < 0) continue;
    if (!by.has(r.core)) by.set(r.core, []);
    by.get(r.core).push(r);
  }
  if (!by.size) return null;
  return [...by.keys()].sort((a, b) => a - b).map((core) => {
    const list = by.get(core);
    const busy = list.map((r) => r.busy);
    const maxes = list.map((r) => (isNum(r.busy_max) ? r.busy_max : r.busy)).filter(isNum);
    return { core, p95: p95(busy), max: maxes.length ? Math.max(...maxes) : null };
  }).filter((c) => c.p95 !== null);
}

/** [{ core, p95 }] from the snapshot's 24 h per-core p95 (JSON keys are strings). */
function coresFromSnapshot(snapshot) {
  const map = snapshot?.core_p95_24h;
  if (!map || typeof map !== 'object') return null;
  const list = Object.keys(map)
    .map((k) => ({ core: Number(k), p95: map[k], max: null }))
    .filter((c) => Number.isInteger(c.core) && c.core >= 0 && isNum(c.p95))
    .sort((a, b) => a.core - b.core);
  return list.length ? list : null;
}

function playersAt(series, from, to) {
  for (const rows of Object.values(series?.insts || {})) {
    for (const r of rows || []) {
      const p = isNum(r.players) ? r.players : r.players_max;
      if (isNum(r.ts) && r.ts >= from && r.ts <= to && isNum(p) && p >= 2) return true;
    }
  }
  return false;
}

/** Minutes above the saturation limit per core, from core_saturated events; Map core -> {minutes, matches}. */
function saturation(events, series, now) {
  const out = new Map();
  for (const e of Array.isArray(events) ? events : []) {
    if (e?.kind !== 'core_saturated' || !isNum(e.ts)) continue;
    const m = /^core (\d+)/.exec(e.message || '');
    if (!m) continue;
    const core = Number(m[1]);
    const end = isNum(e.closed_ts) ? e.closed_ts : (isNum(now) ? now : null);
    const cur = out.get(core) || { seconds: null, matches: false };
    if (end !== null) {
      cur.seconds = (cur.seconds || 0) + Math.max(end - e.ts, 0);
      if (series && playersAt(series, e.ts, end)) cur.matches = true;
    }
    out.set(core, cur);
  }
  return out;
}

function cpuFindings({ snapshot, series, events, settings, range }) {
  const target = setting(settings, 'verdict_target_pct', 70);
  const sat = setting(settings, 'core_saturated_pct', 95);
  const fromSeries = coresFromSeries(series);
  const cores = fromSeries || coresFromSnapshot(snapshot);
  const span = fromSeries ? (RANGE_TEXT[range] || 'the selected range') : 'the last 24 hours';
  const note = fromSeries ? '' : ' (24 h snapshot)';
  const out = [];
  const satMap = saturation(events, series, series?.now ?? snapshot?.now);
  const byCore = new Map((cores || []).map((c) => [c.core, c]));
  const ids = [...new Set([...byCore.keys(), ...satMap.keys()])].sort((a, b) => a - b);
  for (const id of ids) {
    const c = byCore.get(id);
    const s = satMap.get(id);
    if (s) {
      // saturation events stand on their own: a core without a p95 row is still reported
      let dur = '';
      if (s.seconds !== null) {
        dur = s.seconds < 60
          ? ' for less than a minute'
          : ` for ${plural(Math.round(s.seconds / 60), 'minute', 'minutes')}`;
      }
      out.push({
        level: 'problem',
        area: 'cpu',
        text: `Core ${id} was above ${pct0(sat)} %${dur}${s.matches ? ', during matches' : ''}.`,
      });
    } else if (c.p95 > target) {
      out.push({
        level: 'warning',
        area: 'cpu',
        text: `Core ${c.core} p95 was ${pct0(c.p95)} % over ${span}${note}, above the ${pct0(target)} % planning limit.`,
      });
    } else if (fromSeries && isNum(c.max)) {
      out.push({
        level: 'ok',
        area: 'cpu',
        text: `Core ${c.core} stayed below ${pct0(c.max)} % (p95 ${pct0(c.p95)} %) over ${span}; limit for planning is ${pct0(target)} %.`,
      });
    } else {
      out.push({
        level: 'ok',
        area: 'cpu',
        text: `Core ${c.core} p95 was ${pct0(c.p95)} % over ${span}${note}; limit for planning is ${pct0(target)} %.`,
      });
    }
  }
  if (!cores) {
    // no per-core numbers (older collector or no data yet): only the event counts are left
    const n = snapshot?.events_24h?.core_saturated;
    if (isNum(n) && n > 0 && !satMap.size) {
      out.push({
        level: 'warning',
        area: 'cpu',
        text: `${plural(n, 'core saturation event', 'core saturation events')} in the last 24 hours (24 h snapshot).`,
      });
    }
  }
  return out;
}

function roomFindings({ snapshot, verdict }) {
  if (!verdict) return [];
  const slots = verdict.slots;
  const ref = verdict.ref_load;
  if (verdict.ref_source === null || verdict.ref_source === undefined || !isNum(ref)) {
    const anyBusy = (snapshot?.insts || []).some((i) => isNum(i?.busy_p95));
    if (anyBusy) return [];
    return [{
      level: 'info',
      area: 'room',
      text: 'No match played on this host yet and no other host has data, so room cannot be estimated.',
    }];
  }
  const refText = `reference: one instance uses ${pct0(ref)} % of a core in a match`;
  const prefix = verdict.ref_source === 'fleet'
    ? 'No match played on this host yet, so room is estimated from other hosts. '
    : '';
  if (!isNum(slots)) return [];
  if (slots > 0) {
    return [{
      level: 'ok',
      area: 'room',
      text: `${prefix}Room for ${slots} more ${slots === 1 ? 'instance' : 'instances'} (${refText}).`,
    }];
  }
  // the verdict takes the smaller of the CPU and RAM slot counts: name the one that limits
  const reason = String(verdict.reason || '');
  let why = '';
  if (/^0 slots, memory:/.test(reason)) why = ': RAM is the limit';
  else if (/^0 slots, core \d+:/.test(reason)) why = ` (CPU is the limit; ${refText})`;
  return [{
    level: verdict.status === 'overloaded' ? 'problem' : 'warning',
    area: 'room',
    text: `${prefix}No room for more instances${why}.`,
  }];
}

/** Per-port { late, frames, worst: {ms, ts, players} } from the series, or from the snapshot. */
function frameStats(snapshot, series) {
  const rowsByPort = series?.insts && typeof series.insts === 'object' ? series.insts : null;
  const fromSeries = !!rowsByPort && sortedPorts(rowsByPort).length > 0;
  const out = [];
  if (fromSeries) {
    for (const port of sortedPorts(rowsByPort)) {
      let late = 0;
      let frames = 0;
      let worst = null;
      for (const r of rowsByPort[String(port)] || []) {
        if (isNum(r.late)) late += r.late;
        if (isNum(r.frames)) frames += r.frames;
        if (isNum(r.max_ms) && isNum(r.ts) && (!worst || r.max_ms > worst.ms)) {
          const p = isNum(r.players) ? r.players : r.players_max;
          worst = { ms: r.max_ms, ts: r.ts, players: isNum(p) ? p : null };
        }
      }
      out.push({ port, late, frames, worst });
    }
    return { fromSeries, list: out };
  }
  for (const i of Array.isArray(snapshot?.insts) ? snapshot.insts : []) {
    if (!Number.isInteger(i?.port)) continue;
    out.push({
      port: i.port,
      late: isNum(i.late_24h) ? i.late_24h : 0,
      frames: isNum(i.frames_24h) ? i.frames_24h : 0,
      worst: null,
    });
  }
  return { fromSeries, list: out };
}

function frameFindings({ snapshot, series, events, range }) {
  const { fromSeries, list } = frameStats(snapshot, series);
  const withFrames = list.filter((s) => s.frames > 0);
  if (!withFrames.length) {
    return [{ level: 'info', area: 'frames', text: 'No frame statistics yet (no instance is running or reporting).' }];
  }
  const span = fromSeries ? (RANGE_TEXT[range] || 'the selected range') : 'the last 24 hours';
  const note = fromSeries ? '' : ' (24 h snapshot)';
  const openLate = new Set(
    (Array.isArray(events) ? events : [])
      .filter((e) => e?.kind === 'frames_late' && e.state === 'open' && Number.isInteger(e.port))
      .map((e) => e.port),
  );
  const out = [];
  for (const s of withFrames) {
    if (s.late <= 0) continue;
    let text = `${plural(s.late, 'late frame', 'late frames')} on :${s.port}`;
    if (s.worst) {
      text += `, worst gap ${Math.round(s.worst.ms)} ms at ${hhmm(s.worst.ts)}`;
      if (s.worst.players !== null) text += ` (players: ${s.worst.players})`;
    } else {
      text += ` in ${span}${note}`;
    }
    text += '. A late frame means players see a hitch.';
    out.push({ level: openLate.has(s.port) ? 'problem' : 'warning', area: 'frames', text });
  }
  if (!out.length) {
    out.push({ level: 'ok', area: 'frames', text: `No late server frames in ${span}${note}.` });
  }
  return out;
}

function stealFindings({ snapshot, series, settings, range }) {
  const tight = setting(settings, 'steal_tight_pct', 5);
  const over = setting(settings, 'steal_overload_pct', 15);
  let value = null;
  let span;
  const rows = Array.isArray(series?.cores) ? series.cores.filter((r) => r?.core === -1) : [];
  if (rows.length) {
    value = p95(rows.map((r) => r.steal));
    span = RANGE_TEXT[range] || 'the selected range';
  }
  if (value === null && isNum(snapshot?.steal_p95)) {
    value = snapshot.steal_p95;
    span = 'the last 7 days (snapshot)';
  }
  if (value === null) return [];
  const shown = value < 10 ? value.toFixed(1) : pct0(value);
  const level = value > over ? 'problem' : value > tight ? 'warning' : 'ok';
  return [{
    level,
    area: 'steal',
    text: `The provider took ${shown} % of CPU time (steal, p95 over ${span}); above ${pct0(tight)} % means a noisy neighbour.`,
  }];
}

function memoryFindings({ snapshot, events, settings }) {
  const total = snapshot?.mem_total;
  const avail = snapshot?.mem_avail_now;
  if (!isNum(total) || !isNum(avail) || total <= 0) return [];
  const reserve = setting(settings, 'mem_reserve_pct', 20);
  const rss = (snapshot?.insts || []).map((i) => i?.rss_max).filter((v) => isNum(v) && v > 0);
  const lowOpen = (Array.isArray(events) ? events : []).some((e) => e?.kind === 'mem_low' && e.state === 'open');
  let text = `RAM: ${gb1(avail)} GB free of ${gb1(total)} GB`;
  let level = 'ok';
  const spare = avail - (reserve / 100) * total;
  if (spare < 0) {
    level = 'warning';
    text += `, below the ${pct0(reserve)} % reserve.`;
  } else if (rss.length) {
    const n = Math.floor(spare / Math.max(...rss));
    text += `, enough for about ${n} more ${n === 1 ? 'instance' : 'instances'}.`;
  } else {
    text += '.';
  }
  if (lowOpen) level = 'problem';
  return [{ level, area: 'memory', text }];
}

function diskFindings({ snapshot, events, settings }) {
  const pct = diskUsedPct(snapshot?.host);
  if (pct === null) return [];
  const limit = setting(settings, 'disk_low_pct', 90);
  const lowOpen = (Array.isArray(events) ? events : []).some((e) => e?.kind === 'disk_low' && e.state === 'open');
  const over = pct > limit || lowOpen;
  return [{
    level: over ? 'problem' : 'ok',
    area: 'disk',
    text: `Disk / is ${pct0(pct)} % full${over ? '' : ` (${gb1(snapshot.host.disk_total - snapshot.host.disk_used)} GB free)`}.`,
  }];
}

/**
 * Findings of one host, in the order data, cpu, room, frames, steal, memory, disk. A stale
 * host (collector data older than 2 min) gets only the data finding: the rest would describe
 * a past state as if it were current. Never throws on missing or partial input.
 */
export function findings({ snapshot, series, events, settings, range, verdict } = {}) {
  if (!snapshot || typeof snapshot !== 'object') {
    return [{ level: 'info', area: 'data', text: 'No data collected on this host yet.' }];
  }
  const data = dataFinding(snapshot);
  if (data) return [data];
  const ctx = { snapshot, series, events, settings, range, verdict };
  return [
    ...cpuFindings(ctx),
    ...roomFindings(ctx),
    ...frameFindings(ctx),
    ...stealFindings(ctx),
    ...memoryFindings(ctx),
    ...diskFindings(ctx),
  ];
}
