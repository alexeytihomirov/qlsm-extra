import React from './runtime';
import { HostModal } from './HostPanel';
import { ensurePanelCss } from './css';
import { diskUsedPct, eventsTotal, playersNow } from './data';
import {
  fmtBytes, fmtPct, fmtTime, slotsText, stateLabel, statusLabel,
} from './format';
import './panel.css';

ensurePanelCss();

const { useCallback, useEffect, useRef, useState } = React;

function errorText(e, fallback) {
  return e?.response?.data?.error?.message || e?.message || fallback;
}

function ToneIcon({ tone }) {
  const props = {
    viewBox: '0 0 16 16', fill: 'none', stroke: 'currentColor', strokeWidth: 1.8,
    strokeLinecap: 'round', strokeLinejoin: 'round', 'aria-hidden': true,
  };
  if (tone === 'good') {
    return <svg {...props} style={{ color: 'var(--hm-good)' }}><circle cx="8" cy="8" r="6.5" /><path d="M5 8.2l2.2 2.2L11 6" /></svg>;
  }
  if (tone === 'warning') {
    return <svg {...props}><path d="M8 2l6.5 11.5h-13z" /><path d="M8 6.5v3M8 11.6v.1" /></svg>;
  }
  if (tone === 'critical') {
    return <svg {...props}><circle cx="8" cy="8" r="6.5" /><path d="M5.5 5.5l5 5M10.5 5.5l-5 5" /></svg>;
  }
  return <svg {...props}><circle cx="8" cy="8" r="6.5" /><path d="M5 8h6" /></svg>;
}

function Badge({ text, tone }) {
  return (
    <span className={`hm-badge hm-tone-${tone}`}>
      <ToneIcon tone={tone} />
      {text}
    </span>
  );
}

/** Status cell: verdict badge with the reason as tooltip and second line, or the host state. */
function StatusCell({ host }) {
  const problem = stateLabel(host.state);
  if (host.state !== 'ok' && !host.snapshot) {
    const tone = host.state === 'unreachable' ? 'critical' : 'neutral';
    return (
      <>
        <Badge text={problem || host.state} tone={tone} />
        {host.error ? <div className="hm-reason">{host.error}</div> : null}
      </>
    );
  }
  const label = statusLabel(host.verdict?.status);
  const reason = host.verdict?.reason;
  return (
    <>
      <span title={reason || undefined}><Badge text={label.text} tone={label.tone} /></span>
      {reason ? <div className="hm-reason">{reason}</div> : null}
      {problem ? (
        <div className="hm-reason">
          {problem}{host.version ? ` (${host.version})` : ''}: use Apply to host.
        </div>
      ) : null}
    </>
  );
}

function CoresCell({ snapshot }) {
  const cores = (snapshot?.cores_last || []).filter((c) => c.core >= 0);
  if (!cores.length) return <span className="hm-muted">-</span>;
  return (
    <div className="hm-cores hm-num">
      {cores.map((c) => (
        <span key={c.core} className={c.busy >= 95 ? 'hm-core-hot' : undefined} title={`Core ${c.core} busy now`}>
          {c.core}: {fmtPct(c.busy)}
        </span>
      ))}
    </div>
  );
}

function memText(snapshot) {
  const avail = snapshot?.mem_avail_now;
  const total = snapshot?.mem_total;
  if (avail === null || avail === undefined) return '-';
  return total ? `${fmtBytes(avail)} of ${fmtBytes(total)}` : fmtBytes(avail);
}

function HostRow({ host, onOpen }) {
  const s = host.snapshot;
  const instances = s ? (s.insts_last || []).length : null;
  const players = s ? playersNow(s) : null;
  const late = s ? (s.events_24h?.frames_late || 0) : null;
  const events = s ? eventsTotal(s) : null;
  const dash = <span className="hm-muted">-</span>;
  return (
    <tr>
      <td><button type="button" className="hm-host-link" onClick={() => onOpen(host)}>{host.name}</button></td>
      <td><StatusCell host={host} /></td>
      <td className="hm-num">{host.verdict ? slotsText(host.verdict) : '-'}</td>
      <td>{s ? <CoresCell snapshot={s} /> : dash}</td>
      <td className="hm-num">{s ? fmtPct(s.steal_p95) : dash}</td>
      <td className="hm-num">{s ? memText(s) : dash}</td>
      <td className="hm-num">{s ? fmtPct(diskUsedPct(s.host)) : dash}</td>
      <td className="hm-num">{instances === null ? dash : instances}</td>
      <td className="hm-num">{players === null ? dash : players}</td>
      <td className="hm-num">{late === null ? dash : late}</td>
      <td className="hm-num">{events === null ? dash : events}</td>
    </tr>
  );
}

/**
 * Tier-2 `page`: one row per host. The host name opens the same dialog as the host menu.
 */
function Page({ ctx }) {
  const [hosts, setHosts] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [loadedAt, setLoadedAt] = useState(null);
  const [open, setOpen] = useState(null);
  const token = useRef(0);

  const load = useCallback(async (refresh) => {
    const mine = ++token.current;
    setLoading(true);
    setError(null);
    try {
      const data = await ctx.api('GET', 'hosts', refresh ? { params: { refresh: 1 } } : undefined);
      if (token.current !== mine) return;
      setHosts(data?.hosts || []);
      setLoadedAt(Date.now() / 1000);
    } catch (e) {
      if (token.current === mine) setError(errorText(e, 'Could not load the hosts.'));
    } finally {
      if (token.current === mine) setLoading(false);
    }
  }, [ctx]);

  useEffect(() => { load(false); }, [load]);

  return (
    <div className="hm-root hm-page">
      <div className="hm-toolbar">
        <button type="button" className="hm-btn" onClick={() => load(true)} disabled={loading}>
          {loading ? 'Loading...' : 'Refresh'}
        </button>
        <span className="hm-muted">
          {loadedAt ? `Updated ${fmtTime(loadedAt, true)}. ` : ''}
          Core figures are the latest sample; steal is the 7-day p95; late frames and events are the last 24 hours.
        </span>
      </div>
      {error ? <div className="hm-error">{error}</div> : null}
      {hosts === null && loading ? <div className="hm-muted">Loading hosts (one SSH query per host)...</div> : null}
      {hosts && hosts.length === 0 ? <div className="hm-muted">No hosts.</div> : null}
      {hosts && hosts.length > 0 ? (
        <div className={`hm-table-wrap${loading ? ' hm-dim' : ''}`}>
          <table className="hm-table">
            <thead>
              <tr>
                <th>Host</th>
                <th>Status</th>
                <th>Capacity</th>
                <th>Core busy now</th>
                <th>Steal p95</th>
                <th>RAM available</th>
                <th>Disk used</th>
                <th>Instances</th>
                <th>Players now</th>
                <th>Late-frame events 24 h</th>
                <th>Events 24 h</th>
              </tr>
            </thead>
            <tbody>
              {hosts.map((h) => <HostRow key={h.id} host={h} onOpen={setOpen} />)}
            </tbody>
          </table>
        </div>
      ) : null}
      {open ? (
        <HostModal ctx={ctx} host={open} isOpen onClose={() => setOpen(null)} />
      ) : null}
    </div>
  );
}

export default Page;
