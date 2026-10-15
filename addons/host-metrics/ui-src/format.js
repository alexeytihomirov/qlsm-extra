// Pure display helpers (tested with `node --test`, no React, no DOM).

const isNum = (v) => typeof v === 'number' && Number.isFinite(v);

/** "4.3%" under 10, "63%" above, "-" without a value. */
export function fmtPct(v) {
  if (!isNum(v)) return '-';
  return v < 10 ? `${v.toFixed(1)}%` : `${Math.round(v)}%`;
}

const UNITS = ['B', 'KB', 'MB', 'GB', 'TB'];

/** Binary units; one decimal under 10, none above (bytes are whole). */
export function fmtBytes(b) {
  if (!isNum(b)) return '-';
  let value = b;
  let unit = 0;
  while (value >= 1024 && unit < UNITS.length - 1) {
    value /= 1024;
    unit += 1;
  }
  if (unit === 0) return `${Math.round(value)} B`;
  return `${value < 10 ? value.toFixed(1) : Math.round(value)} ${UNITS[unit]}`;
}

const STATUS = {
  ok: { text: 'OK', tone: 'good' },
  tight: { text: 'Tight', tone: 'warning' },
  overloaded: { text: 'Overloaded', tone: 'critical' },
  unknown: { text: 'No data under load', tone: 'neutral' },
};

/** Verdict status -> badge text and tone (good / warning / critical / neutral). */
export function statusLabel(status) {
  return { ...(STATUS[status] || STATUS.unknown) };
}

/** "room for 3 more", "no room", "-" when the verdict has no slot count. */
export function slotsText(verdict) {
  const slots = verdict?.slots;
  if (!isNum(slots)) return '-';
  return slots > 0 ? `room for ${slots} more` : 'no room';
}

const STATES = {
  not_installed: 'Not installed',
  outdated: 'Outdated collector',
  unreachable: 'Unreachable',
  no_sudo: 'No sudo',
  no_data: 'No data yet',
  stale: 'Stale',
};

/** Label for a host row whose collector is not answering normally; null when it is. */
export function stateLabel(state) {
  return STATES[state] || null;
}

/** 45s, 2m, 3h 2m, 2d 4h. */
export function fmtDuration(seconds) {
  if (!isNum(seconds)) return '-';
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  if (s < 86400) {
    const m = Math.floor((s % 3600) / 60);
    return `${Math.floor(s / 3600)}h${m ? ` ${m}m` : ''}`;
  }
  const h = Math.floor((s % 86400) / 3600);
  return `${Math.floor(s / 86400)}d${h ? ` ${h}h` : ''}`;
}

/** Local "YYYY-MM-DD HH:MM" (":SS" with `seconds`) for a unix timestamp in seconds. */
export function fmtTime(ts, seconds = false) {
  if (!isNum(ts)) return '-';
  const d = new Date(ts * 1000);
  const p = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}${seconds ? `:${p(d.getSeconds())}` : ''}`;
}
