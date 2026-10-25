// Pure helpers behind the Live Settings table: what a row's starting value
// is, whether the operator changed it, and which state chip it shows. Kept
// free of React so `node --test` covers them without a DOM.

export const CVAR_NAME_RE = /^[A-Za-z0-9_]+$/;

/** The value the operator edits against: the engine's when it answered,
 *  else qlsm's server.cfg copy, else the plugin's declared default. */
export function baselineValue(row) {
  if (row.reported && row.live !== null && row.live !== undefined) return row.live;
  if (row.cfg !== null && row.cfg !== undefined) return row.cfg;
  return row.default ?? '';
}

export function currentValue(row, edits) {
  return Object.prototype.hasOwnProperty.call(edits, row.name) ? edits[row.name] : baselineValue(row);
}

export function isChanged(row, edits) {
  return currentValue(row, edits) !== baselineValue(row);
}

/** The engine's `^N` colour codes, for display only; the value itself is
 *  sent back untouched. */
export function stripColors(text) {
  return String(text ?? '').replace(/\^[0-9a-zA-Z]/g, '');
}

/**
 * {kind, text}: kind is one of ok / changed / warn / info / muted.
 * `rconOk` says whether the live column is trustworthy at all.
 */
export function rowState(row, edits, rconOk) {
  if (isChanged(row, edits)) return { kind: 'changed', text: 'changed' };
  if (row.latched !== null && row.latched !== undefined) {
    return { kind: 'info', text: `latched ${row.latched} · on next map` };
  }
  if (!rconOk) return { kind: 'muted', text: 'no live value' };
  if (!row.reported) return { kind: 'muted', text: 'unknown to server' };
  const hasCfg = row.cfg !== null && row.cfg !== undefined;
  if (!hasCfg) {
    const def = row.live_default ?? row.default;
    if (def !== null && def !== undefined && def === row.live) return { kind: 'muted', text: 'default' };
    return { kind: 'warn', text: 'live only · lost on restart' };
  }
  if (row.cfg !== row.live) return { kind: 'warn', text: `drift · cfg ${row.cfg}` };
  return { kind: 'ok', text: 'in sync' };
}

/** Rows whose edited value differs from the baseline, as the apply payload. */
export function pendingChanges(groups, edits) {
  const out = [];
  for (const group of groups || []) {
    for (const row of group.cvars || []) {
      if (isChanged(row, edits)) out.push({ name: row.name, value: currentValue(row, edits) });
    }
  }
  return out;
}

export function entryState(entry) {
  switch (entry.state) {
    case 'live': return { kind: 'ok', text: 'live' };
    case 'latched': return { kind: 'warn', text: 'applies on next map' };
    case 'mismatch': return { kind: 'warn', text: `server has ${stripColors(entry.live)}` };
    default: return { kind: 'warn', text: 'no reply from server' };
  }
}

export function persistLine(apply) {
  if (!apply.persist) return { kind: 'warn', text: 'not written to server.cfg · live only' };
  const result = apply.persist_result;
  if (!result) return { kind: 'warn', text: 'server.cfg not written' };
  if (result.ok && result.unchanged) return { kind: 'muted', text: 'server.cfg already had these values' };
  if (result.ok) return { kind: 'ok', text: 'server.cfg updated · sync to host queued, no restart' };
  return { kind: 'warn', text: result.skipped || 'server.cfg not written' };
}

export function formatTime(seconds) {
  if (!seconds) return '';
  const d = new Date(seconds * 1000);
  const pad = (n) => String(n).padStart(2, '0');
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

export function formatDateTime(seconds) {
  if (!seconds) return '';
  const d = new Date(seconds * 1000);
  const pad = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${formatTime(seconds)}`;
}
