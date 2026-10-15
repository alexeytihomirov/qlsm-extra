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
  unknown: { text: 'No data yet', tone: 'neutral' },
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

const KIND_LABELS = {
  core_saturated: 'Core saturated',
  steal_high: 'Steal high',
  mem_low: 'Memory low',
  disk_low: 'Disk low',
  frames_late: 'Late frames',
  oom_kill: 'OOM kill',
  instance_new: 'Instance appeared',
  instance_gone: 'Instance gone',
};

/** Collector event kind in words; an unknown kind as it is. */
export function kindLabel(kind) {
  return KIND_LABELS[kind] || String(kind);
}

const text = (v) => (typeof v === 'string' && v.trim() ? v.trim().replace(/\s+/g, ' ') : null);

function cpuCount(hw) {
  if (!isNum(hw.vcpus)) return null;
  return hw.hypervisor === false ? `${hw.vcpus} CPU threads` : `${hw.vcpus} vCPU`;
}

function diskText(hw) {
  if (!isNum(hw.disk_total)) return null;
  let kind = 'disk';
  if (hw.disk_rotational === true) kind = 'HDD';
  else if (hw.disk_rotational === false) kind = 'SSD';
  return `${fmtBytes(hw.disk_total)} ${kind}`;
}

/** Product name when it says more than the provider (EC2 instance type, "vServer"). */
function productOf(hw) {
  const product = text(hw.product_name);
  if (!product || product === text(hw.provider) || product === text(hw.sys_vendor)) return null;
  return product;
}

/**
 * One line about the host's hardware (`snapshot.hardware`), e.g. "AMD EPYC-Rome Processor,
 * 2 vCPU, 3.8 GB RAM, 38 GB SSD, Hetzner (vServer)". Unknown parts are left out; null when
 * nothing is known (no hardware read yet, or an older collector).
 */
export function hardwareLine(hw) {
  if (!hw || typeof hw !== 'object') return null;
  const provider = text(hw.provider);
  const product = productOf(hw);
  const parts = [
    text(hw.cpu_model),
    cpuCount(hw),
    isNum(hw.mem_total) ? `${fmtBytes(hw.mem_total)} RAM` : null,
    diskText(hw),
    provider ? `${provider}${product ? ` (${product})` : ''}` : null,
  ].filter(Boolean);
  return parts.length ? parts.join(', ') : null;
}

/** The full hardware block of the host modal: [[label, value]], only rows with a known value. */
export function hardwareDetails(hw) {
  if (!hw || typeof hw !== 'object') return [];
  const out = [];
  const add = (label, value) => { if (value) out.push([label, value]); };
  add('CPU', text(hw.cpu_model));

  let cores = cpuCount(hw);
  if (cores) {
    const topo = [];
    if (isNum(hw.threads_per_core)) topo.push(`${hw.threads_per_core} ${hw.threads_per_core === 1 ? 'thread' : 'threads'} per core`);
    if (isNum(hw.sockets)) topo.push(`${hw.sockets} ${hw.sockets === 1 ? 'socket' : 'sockets'}`);
    if (topo.length) cores += ` (${topo.join(', ')})`;
  }
  const clock = [cores, isNum(hw.mhz) ? `${Math.round(hw.mhz)} MHz` : null, text(hw.cache) ? `cache ${text(hw.cache)}` : null]
    .filter(Boolean);
  add('Cores', clock.length ? clock.join(', ') : null);

  const mem = [];
  if (isNum(hw.mem_total)) mem.push(`${fmtBytes(hw.mem_total)} RAM`);
  if (isNum(hw.swap_total)) mem.push(hw.swap_total > 0 ? `${fmtBytes(hw.swap_total)} swap` : 'no swap');
  add('Memory', mem.length ? mem.join(', ') : null);
  add('Disk', diskText(hw));

  let virt = null;
  if (hw.hypervisor === true) virt = 'virtual machine';
  else if (hw.hypervisor === false) virt = 'no hypervisor detected';
  const provider = text(hw.provider);
  const extras = [productOf(hw), virt].filter(Boolean);
  if (provider) add('Provider', `${provider}${extras.length ? ` (${extras.join(', ')})` : ''}`);
  else if (virt) add('Provider', virt.charAt(0).toUpperCase() + virt.slice(1));

  const sys = [text(hw.os), text(hw.kernel) ? `kernel ${text(hw.kernel)}` : null].filter(Boolean);
  add('System', sys.length ? sys.join(', ') : null);
  add('Booted', isNum(hw.boot_time) ? fmtTime(hw.boot_time) : null);
  return out;
}
