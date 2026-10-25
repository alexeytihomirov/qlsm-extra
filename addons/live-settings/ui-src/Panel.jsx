import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  CVAR_NAME_RE, baselineValue, currentValue, entryState, formatDateTime, formatTime, isChanged,
  isSecretName, pendingChanges, persistLine, rowState, stripColors,
} from './rows.js';
import './panel.css';

/**
 * Tier-2 entry point: the Live Settings tab of Edit Configuration, mounted by
 * QLSM with a single `ctx` prop (see qlsm's addons/README.md). `ctx.scope.id`
 * is the instance; every request goes through `ctx.api`, pinned to this
 * addon's own prefix.
 */

const RefreshIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
    <path d="M21 12a9 9 0 1 1-2.64-6.36M21 3v6h-6" />
  </svg>
);
const RevertIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
    <path d="M3 12a9 9 0 1 0 3-6.7L3 8" /><path d="M3 3v5h5" />
  </svg>
);
const UnpinIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
    <path d="M18 6 6 18M6 6l12 12" />
  </svg>
);
const ZapIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
    <path d="M13 2 3 14h9l-1 8 10-12h-9l1-8z" />
  </svg>
);
const SpinIcon = () => (
  <svg className="ls-spin" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
    <path d="M21 12a9 9 0 1 1-6.22-8.56" />
  </svg>
);

function Chip({ kind, children }) {
  return <span className={`ls-chip ls-chip-${kind}`}>{children}</span>;
}

function Value({ value, placeholder, secret, revealed, onReveal }) {
  if (value === null || value === undefined) return <span className="ls-empty">{placeholder}</span>;
  if (value === '') return <span className="ls-empty">(empty)</span>;
  if (secret && !revealed) {
    return (
      <button type="button" className="ls-reveal" title="Show the value" onClick={onReveal}>
        {'\u2022'.repeat(8)}
      </button>
    );
  }
  return <span title={secret ? undefined : value}>{stripColors(value)}</span>;
}

function maskDiffLine(line) {
  // `+set qlx_matchNoticeToken "abc"` -> the value hidden, the cvar name kept.
  const m = line.match(/^([+-]\s*seta?\s+)([A-Za-z0-9_]+)(\s+)(".*"|\S+)(.*)$/);
  if (m && isSecretName(m[2])) return `${m[1]}${m[2]}${m[3]}"${'\u2022'.repeat(8)}"${m[5]}`;
  return line;
}

function Editor({ row, value, onChange, revealed }) {
  const label = row.label ? `${row.name}: ${row.label}` : row.name;
  if (row.type === 'bool') {
    const on = value === '1' || value.toLowerCase() === 'true';
    return (
      <button
        type="button" role="switch" aria-checked={on} aria-label={label}
        className={`ls-track${on ? ' ls-on' : ''}`}
        onClick={() => onChange(on ? '0' : '1')}
      />
    );
  }
  if (row.type === 'number') {
    return (
      <input
        className="ls-input ls-input-num" type="number" inputMode="decimal" aria-label={label}
        min={row.min} max={row.max} value={value}
        onChange={(e) => onChange(e.target.value)}
      />
    );
  }
  const secret = isSecretName(row.name) && !revealed;
  return (
    <input
      className="ls-input" type={secret ? 'password' : 'text'} autoComplete="off" aria-label={label} value={value}
      onChange={(e) => onChange(e.target.value)}
    />
  );
}

function DiffBlock({ diff }) {
  if (!diff) return null;
  const lines = diff.replace(/\n$/, '').split('\n').map(maskDiffLine);
  return (
    <details className="ls-diff" open>
      <summary>server.cfg diff</summary>
      <pre>{lines.map((line, i) => {
        let cls = '';
        if (line.startsWith('+') && !line.startsWith('+++')) cls = 'ls-add-line';
        else if (line.startsWith('-') && !line.startsWith('---')) cls = 'ls-del-line';
        else if (line.startsWith('@@')) cls = 'ls-hunk';
        return <span key={i} className={cls}>{line}{'\n'}</span>;
      })}</pre>
    </details>
  );
}

function ApplyLog({ apply }) {
  const time = formatTime(apply.at);
  const persist = persistLine(apply);
  return (
    <div className="ls-log">
      <div className="ls-log-head">
        Apply {formatDateTime(apply.at)}
        <span className="ls-chip ls-chip-muted" style={{ marginLeft: 'auto' }}>rcon · set, then read back</span>
      </div>
      <pre>{(apply.entries || []).map((entry) => {
        const state = entryState(entry);
        const secret = isSecretName(entry.name);
        const command = secret ? `set ${entry.name} "${'\u2022'.repeat(8)}"` : entry.command;
        const reply = secret ? `"${entry.name}" is:"${'\u2022'.repeat(8)}"` : stripColors(entry.reply);
        return (
          <React.Fragment key={entry.name}>
            <span className="ls-time">{time}</span> <span className="ls-cmd">{command}</span>{'\n'}
            {'         '}{entry.reply ? reply : '(no reply)'}
            {'   '}<span className={`ls-${state.kind === 'ok' ? 'ok' : 'warn'}`}>{state.text}</span>{'\n'}
          </React.Fragment>
        );
      })}
        {'         '}<span className={`ls-${persist.kind === 'ok' ? 'ok' : persist.kind === 'muted' ? 'muted' : 'warn'}`}>{persist.text}</span>{'\n'}
      </pre>
      <DiffBlock diff={apply.persist_result?.diff} />
    </div>
  );
}

function Panel({ ctx }) {
  const instanceId = ctx?.scope?.id;
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [edits, setEdits] = useState({});
  const [persist, setPersist] = useState(true);
  const [applying, setApplying] = useState(false);
  const [applyError, setApplyError] = useState(null);
  const [addName, setAddName] = useState('');
  const [pinBusy, setPinBusy] = useState(false);
  const [revealed, setRevealed] = useState({});
  const retryTimer = useRef(null);
  const alive = useRef(true);

  const load = useCallback(async ({ quiet = false } = {}) => {
    if (!instanceId) return null;
    if (!quiet) setLoading(true);
    setError(null);
    try {
      const result = await ctx.api('GET', `instances/${instanceId}/cvars`);
      if (!alive.current) return null;
      setData(result);
      return result;
    } catch (err) {
      if (alive.current) setError(err?.response?.data?.error?.message || err?.message || 'Failed to load');
      return null;
    } finally {
      if (alive.current && !quiet) setLoading(false);
    }
  }, [ctx, instanceId]);

  useEffect(() => {
    alive.current = true;
    load();
    return () => {
      alive.current = false;
      if (retryTimer.current) clearTimeout(retryTimer.current);
    };
  }, [load]);

  // Right after a server.cfg write the instance sits in CONFIGURING for a
  // few seconds while core syncs the file; the engine itself is untouched,
  // so one retry a little later brings the live column back.
  useEffect(() => {
    const err = data?.rcon?.error || '';
    if (/configuring/i.test(err) && !retryTimer.current) {
      retryTimer.current = setTimeout(() => {
        retryTimer.current = null;
        load({ quiet: true });
      }, 5000);
    }
  }, [data, load]);

  const groups = data?.groups || [];
  const rconOk = Boolean(data?.rcon?.ok);
  const pending = useMemo(() => pendingChanges(groups, edits), [groups, edits]);
  const pinnedNames = useMemo(
    () => (groups.find((g) => g.id === 'pinned')?.cvars || []).map((c) => c.name),
    [groups],
  );
  const knownNames = useMemo(() => {
    const names = new Set();
    groups.forEach((g) => g.cvars.forEach((c) => names.add(c.name.toLowerCase())));
    return names;
  }, [groups]);

  const setEdit = (name, value) => setEdits((prev) => ({ ...prev, [name]: value }));
  const revert = (name) => setEdits((prev) => {
    const next = { ...prev };
    delete next[name];
    return next;
  });

  const apply = async () => {
    if (!pending.length || applying) return;
    setApplying(true);
    setApplyError(null);
    try {
      await ctx.api('POST', `instances/${instanceId}/cvars/apply`, {
        data: { changes: pending, persist },
      });
      setEdits({});
      await load({ quiet: true });
    } catch (err) {
      setApplyError(err?.response?.data?.error?.message || err?.message || 'Apply failed');
    } finally {
      if (alive.current) setApplying(false);
    }
  };

  const savePinned = async (names) => {
    setPinBusy(true);
    setApplyError(null);
    try {
      await ctx.api('PUT', `instances/${instanceId}/pinned`, { data: { cvars: names } });
      await load({ quiet: true });
    } catch (err) {
      setApplyError(err?.response?.data?.error?.message || err?.message || 'Could not save the pinned list');
    } finally {
      if (alive.current) setPinBusy(false);
    }
  };

  const addPinned = async () => {
    const name = addName.trim();
    if (!CVAR_NAME_RE.test(name)) {
      setApplyError(`"${name}" is not a cvar name (letters, digits and _ only).`);
      return;
    }
    setAddName('');
    if (knownNames.has(name.toLowerCase())) return;
    await savePinned([...pinnedNames, name]);
  };

  const unpin = async (name) => {
    revert(name);
    await savePinned(pinnedNames.filter((n) => n !== name));
  };

  if (loading && !data) {
    return <div className="ls-root"><div className="ls-loading"><SpinIcon /> Reading values from the server...</div></div>;
  }
  if (error && !data) {
    return (
      <div className="ls-root">
        <p className="ls-error">{error}</p>
        <div><button type="button" className="ls-btn ls-btn-secondary" onClick={() => load()}><RefreshIcon />Retry</button></div>
      </div>
    );
  }

  const rcon = data?.rcon || {};
  const history = data?.history || [];
  const n = pending.length;
  const hasRows = groups.some((g) => g.cvars.length);

  return (
    <div className="ls-root">
      <div className="ls-toolbar">
        {rconOk
          ? <Chip kind="ok"><span className="ls-dot" />RCON connected{rcon.port ? ` · :${rcon.port}` : ''}</Chip>
          : <Chip kind="danger" title={rcon.error}>no live values{rcon.error ? ` · ${rcon.error}` : ''}</Chip>}
        {rcon.read_at ? <Chip kind="muted">values read {formatTime(rcon.read_at)}</Chip> : null}
        {n ? <Chip kind="changed">{n} change{n > 1 ? 's' : ''} pending</Chip> : null}
        <span className="ls-spacer" />
        <form
          className="ls-add"
          onSubmit={(e) => { e.preventDefault(); addPinned(); }}
        >
          <input
            className="ls-input" list="ls-cvar-suggestions" value={addName}
            placeholder="pin a server cvar, e.g. g_password" aria-label="Pin a server cvar to this instance"
            onChange={(e) => setAddName(e.target.value)} disabled={pinBusy}
          />
          <datalist id="ls-cvar-suggestions">
            {(data?.suggestions || []).map((name) => <option key={name} value={name} />)}
          </datalist>
          <button type="submit" className="ls-btn ls-btn-secondary" disabled={pinBusy || !addName.trim()}>Pin</button>
        </form>
        <button type="button" className="ls-btn ls-btn-secondary" onClick={() => load()} disabled={loading}>
          {loading ? <SpinIcon /> : <RefreshIcon />}Refresh
        </button>
      </div>

      {error ? <p className="ls-error">{error}</p> : null}

      <div className="ls-tablewrap">
        <table className="ls-table">
          <thead>
            <tr>
              <th style={{ width: '30%' }}>Cvar</th><th>Live</th><th>server.cfg</th>
              <th style={{ width: '22%' }}>New value</th><th>State</th><th />
            </tr>
          </thead>
          <tbody>
            {!hasRows ? (
              <tr className="ls-empty-row">
                <td colSpan={6}>
                  No cvars yet: none of this instance's plugins declares cvars in its .ql-plugin.json,
                  and nothing is pinned. Pin a server cvar above to start.
                </td>
              </tr>
            ) : null}
            {groups.map((group) => (group.cvars.length ? (
              <React.Fragment key={group.id}>
                <tr className="ls-group"><td colSpan={6}>{group.label} <span>{group.subtitle}</span></td></tr>
                {group.cvars.map((row) => {
                  const value = currentValue(row, edits);
                  const changed = isChanged(row, edits);
                  const state = rowState(row, edits, rconOk);
                  const cfgPlaceholder = row.default !== null && row.default !== undefined
                    ? `not set (default ${row.default})` : 'not set';
                  const secret = isSecretName(row.name);
                  const shown = Boolean(revealed[row.name]);
                  const reveal = () => setRevealed((prev) => ({ ...prev, [row.name]: true }));
                  return (
                    <tr key={row.name} className={changed ? 'ls-row-changed' : undefined}>
                      <td className="ls-name">
                        {row.name}
                        {(row.label || row.description) ? (
                          <small>{row.label}{row.label && row.description ? ' · ' : ''}{row.description}</small>
                        ) : null}
                      </td>
                      <td className="ls-val"><Value value={row.reported ? row.live : null} placeholder={rconOk ? 'no reply' : '-'} secret={secret} revealed={shown} onReveal={reveal} /></td>
                      <td className="ls-val"><Value value={row.cfg} placeholder={cfgPlaceholder} secret={secret} revealed={shown} onReveal={reveal} /></td>
                      <td className="ls-edit"><Editor row={row} value={value} onChange={(v) => setEdit(row.name, v)} revealed={shown} /></td>
                      <td className="ls-state"><Chip kind={state.kind}>{state.text}</Chip></td>
                      <td className="ls-act">
                        <button
                          type="button" className="ls-mini" title="Revert to the current value" aria-label={`Revert ${row.name}`}
                          onClick={() => revert(row.name)} disabled={!changed}
                        ><RevertIcon /></button>
                        {group.id === 'pinned' ? (
                          <button
                            type="button" className="ls-mini" title="Unpin from this list" aria-label={`Unpin ${row.name}`}
                            onClick={() => unpin(row.name)} disabled={pinBusy}
                          ><UnpinIcon /></button>
                        ) : null}
                      </td>
                    </tr>
                  );
                })}
              </React.Fragment>
            ) : null))}
          </tbody>
        </table>
      </div>

      <div className="ls-footer">
        <label className="ls-check">
          <input type="checkbox" checked={persist} onChange={(e) => setPersist(e.target.checked)} />
          Also write to server.cfg <small>(kept after a restart; synced to the host without restarting, the instance shows UPDATED until its next restart)</small>
        </label>
        <span className="ls-spacer" />
        {applyError ? <span className="ls-error">{applyError}</span> : null}
        <button type="button" className="ls-btn ls-btn-secondary" onClick={() => setEdits({})} disabled={!n || applying}>Discard</button>
        <button type="button" className="ls-btn ls-btn-primary" onClick={apply} disabled={!n || applying || !rconOk}>
          {applying ? <SpinIcon /> : <ZapIcon />}
          {applying ? 'Applying...' : n ? `Apply ${n} change${n > 1 ? 's' : ''} live` : 'Nothing to apply'}
        </button>
      </div>

      {history.length ? (
        <div className="ls-history">
          <ApplyLog apply={history[0]} />
          {history.length > 1 ? (
            <details>
              <summary>{history.length - 1} earlier appl{history.length - 1 > 1 ? 'ies' : 'y'}</summary>
              <div className="ls-history" style={{ marginTop: 8 }}>
                {history.slice(1).map((apply, i) => <ApplyLog key={apply.at || i} apply={apply} />)}
              </div>
            </details>
          ) : null}
        </div>
      ) : null}

      <p className="ls-hint">
        Live values come from the running server over RCON and are shown as the server reports them.
        A latched cvar applies on the next map or restart; a plugin cvar read once at load
        (<code>set_cvar_once</code>) applies after <code>!reload</code> or a restart. Anything applied
        without "write to server.cfg" is gone after a restart and shows as "live only".
      </p>
    </div>
  );
}

export default Panel;
