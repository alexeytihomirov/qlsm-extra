import React, { Button } from './runtime';
import { HostModal } from './HostPanel';
import { findings } from './findings';
import {
  corePeaks, diskUsedPct, eventsTotal, healthCounts, hostHealth, hostIdFromSearch, lateFrames24h,
  openEvents, playersNow, refNote, sortByHealth,
} from './data';
import {
  fmtBytes, fmtDuration, fmtPct, fmtTime, hardwareLine, slotsText,
} from './format';
import './panel.css';

const { useCallback, useEffect, useMemo, useRef, useState } = React;

const STATUS_TONE = { problem: 'critical', watch: 'warning', nodata: 'neutral', ok: 'good' };
const STATUS_ORDER = ['problem', 'watch', 'nodata', 'ok'];
const STATUS_LABEL = { problem: 'Problem', watch: 'Watch', nodata: 'No data', ok: 'OK' };
const STATUS_HINT = {
  problem: 'Overloaded, an open critical event, or the host does not answer.',
  watch: 'Tight capacity, noisy neighbour, stale data, or warnings in the last 24 hours.',
  nodata: 'Not installed, or no data under load yet.',
  ok: 'Room for more and nothing to look at.',
};

function errorText(e, fallback) {
  return e?.response?.data?.error?.message || e?.message || fallback;
}

function ToneIcon({ tone }) {
  const props = {
    viewBox: '0 0 16 16', fill: 'none', stroke: 'currentColor', strokeWidth: 1.8,
    strokeLinecap: 'round', strokeLinejoin: 'round', 'aria-hidden': true,
  };
  if (tone === 'good') {
    return <svg {...props}><circle cx="8" cy="8" r="6.5" /><path d="M5 8.2l2.2 2.2L11 6" /></svg>;
  }
  if (tone === 'warning') {
    return <svg {...props}><path d="M8 2l6.5 11.5h-13z" /><path d="M8 6.5v3M8 11.6v.1" /></svg>;
  }
  if (tone === 'critical') {
    return <svg {...props}><circle cx="8" cy="8" r="6.5" /><path d="M5.5 5.5l5 5M10.5 5.5l-5 5" /></svg>;
  }
  return <svg {...props}><circle cx="8" cy="8" r="6.5" /><path d="M5 8h6" /></svg>;
}

/** Status light and word (icon shape + word, never colour alone). */
function StatusBadge({ health }) {
  const tone = STATUS_TONE[health.status] || 'neutral';
  return (
    <span className={`hm-badge hm-tone-${tone}`} title={STATUS_HINT[health.status]}>
      <ToneIcon tone={tone} />
      {health.label}
    </span>
  );
}

function sinceText(since, now) {
  if (!Number.isFinite(since)) return '';
  const ago = Number.isFinite(now) ? ` (${fmtDuration(now - since)} ago)` : '';
  return `since ${fmtTime(since)}${ago}`;
}

/** Top strip: one tile per status, then the open problems of every host. */
function Summary({ entries, onOpen, now }) {
  const counts = healthCounts(entries.map((e) => e.health));
  const problems = [];
  for (const e of entries) {
    for (const item of e.health.items) {
      if (item.level === 'problem') problems.push({ row: e.row, item });
    }
  }
  return (
    <div className="hm-board-summary">
      <div className="hm-tiles">
        {STATUS_ORDER.map((s) => (
          <div key={s} className={`hm-tile hm-health-${s}`} title={STATUS_HINT[s]}>
            <span className="hm-tile-value hm-num">{counts[s]}</span>
            <StatusBadge health={{ status: s, label: STATUS_LABEL[s] }} />
          </div>
        ))}
      </div>
      <div className="hm-problems">
        <div className="hm-section-title">Open problems</div>
        {problems.length === 0 ? (
          <div className="hm-muted">No open problems.</div>
        ) : (
          <ul>
            {problems.map(({ row, item }, i) => (
              <li key={`${row.id}-${i}`}>
                <button type="button" className="hm-host-link" onClick={() => onOpen(row)}>{row.name}</button>
                <span className="hm-problem-what">{item.what}</span>
                {item.since !== null ? (
                  <span className="hm-muted hm-num">{sinceText(item.since, row.snapshot?.now ?? now)}</span>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function memText(snapshot) {
  const avail = snapshot?.mem_avail_now;
  const total = snapshot?.mem_total;
  if (avail === null || avail === undefined) return null;
  return total ? `${fmtBytes(avail)} free of ${fmtBytes(total)}` : `${fmtBytes(avail)} free`;
}

/** The numbers behind the status, in one muted line (only the known ones). */
function metricsText(s) {
  if (!s) return null;
  const peaks = corePeaks(s);
  const late = lateFrames24h(s);
  const parts = [
    peaks ? `busiest core p95 ${fmtPct(peaks.peak)} (24 h)` : null,
    Number.isFinite(s.steal_p95) ? `steal p95 ${fmtPct(s.steal_p95)} (7 d)` : null,
    memText(s) ? `RAM ${memText(s)}` : null,
    diskUsedPct(s.host) !== null ? `disk ${fmtPct(diskUsedPct(s.host))} used` : null,
    late ? `${late.late} late frames (24 h)` : null,
  ].filter(Boolean);
  return parts.length ? parts.join(' | ') : null;
}

function Fact({ label, value, title }) {
  return (
    <span className="hm-fact" title={title}>
      <span className="hm-muted">{label}</span> <span className="hm-num">{value}</span>
    </span>
  );
}

function HostCard({ row, health, onOpen }) {
  const s = row.snapshot;
  const hw = hardwareLine(s?.hardware);
  const instances = s ? (s.insts_last || []).length : null;
  const players = s ? playersNow(s) : null;
  const open = s ? openEvents(s) : null;
  const metrics = metricsText(s);
  const live = row.state !== 'stale';
  return (
    <article className={`hm-hcard hm-health-${health.status}`}>
      <div className="hm-hcard-head">
        <StatusBadge health={health} />
        <span className="hm-hcard-name">{row.name}</span>
        <span className="hm-footer-spacer" />
        <Button onClick={() => onOpen(row)}>Details</Button>
      </div>
      <div className="hm-hcard-reason">{health.reason}</div>
      {s ? (
        <div className={`hm-hcard-hw${hw ? '' : ' hm-muted'}`} title="CPU, cores, RAM, root disk, provider (read by the collector every hour)">
          {hw || 'Hardware not read yet (collector before 1.1, or its first read is pending).'}
        </div>
      ) : null}
      {s && live ? (
        <div className="hm-facts">
          <Fact label="Instances" value={instances} />
          <Fact label="Players now" value={players === null ? '-' : players} />
          {open ? (
            <Fact label="Open events" value={open.filter((e) => e.kind !== 'instance_new' && e.kind !== 'instance_gone').length} />
          ) : (
            <Fact label="Events 24 h" value={eventsTotal(s)} title="This collector does not report open events yet." />
          )}
          {row.verdict && Number.isFinite(row.verdict.slots) ? (
            <Fact
              label="Capacity"
              value={`${slotsText(row.verdict)}${refNote(row.verdict) ? ' (fleet reference)' : ''}`}
              title={row.verdict.reason || undefined}
            />
          ) : null}
        </div>
      ) : null}
      {metrics && live ? <div className="hm-hcard-metrics hm-muted">{metrics}</div> : null}
    </article>
  );
}

/**
 * Tier-2 `page`: the health board, one card per host, problems first. "Details" opens the
 * same dialog as the host menu; `?host=<id>` in the URL opens it on load (notification links).
 */
function Page({ ctx }) {
  const [hosts, setHosts] = useState(null);
  const [settings, setSettings] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [loadedAt, setLoadedAt] = useState(null);
  const [open, setOpen] = useState(null);
  const token = useRef(0);
  const ctxRef = useRef(ctx);
  ctxRef.current = ctx; // core rebuilds ctx on every render
  // ?host=<id> is honoured once, on the first host list
  const linked = useRef(typeof window !== 'undefined' ? hostIdFromSearch(window.location?.search) : null);

  const load = useCallback(async (refresh) => {
    const mine = ++token.current;
    setLoading(true);
    setError(null);
    try {
      const data = await ctxRef.current.api('GET', 'hosts', refresh ? { params: { refresh: 1 } } : undefined);
      if (token.current !== mine) return;
      const list = data?.hosts || [];
      setHosts(list);
      setLoadedAt(Date.now() / 1000);
      if (linked.current !== null) {
        const want = linked.current;
        linked.current = null;
        const row = list.find((h) => h.id === want);
        if (row) setOpen(row);
        else setError(`Host ${want} from the link is not in the host list.`);
      }
    } catch (e) {
      if (token.current === mine) setError(errorText(e, 'Could not load the hosts.'));
    } finally {
      if (token.current === mine) setLoading(false);
    }
  }, []);

  useEffect(() => { load(false); }, [load]);

  // Thresholds for the findings (defaults until they arrive, or when the call fails).
  useEffect(() => {
    let alive = true;
    ctxRef.current.api('GET', 'settings')
      .then((d) => { if (alive) setSettings(d || null); })
      .catch(() => {});
    return () => { alive = false; };
  }, []);

  const entries = useMemo(() => sortByHealth((hosts || []).map((row) => {
    const list = row.snapshot ? findings({
      snapshot: row.snapshot,
      events: openEvents(row.snapshot) || undefined,
      settings,
      verdict: row.verdict || null,
    }) : [];
    return { row, health: hostHealth(row, list) };
  })), [hosts, settings]);

  return (
    <div className="hm-root hm-page">
      <div className="hm-toolbar">
        <Button onClick={() => load(true)} disabled={loading}>
          {loading ? 'Loading...' : 'Refresh'}
        </Button>
        <span className="hm-muted">
          {loadedAt ? `Updated ${fmtTime(loadedAt, true)}. ` : ''}
          One card per host, problems first. Details opens the charts and events of the host.
        </span>
      </div>
      {error ? <div className="hm-error">{error}</div> : null}
      {hosts === null && loading ? <div className="hm-muted">Loading hosts (one SSH query per host)...</div> : null}
      {hosts && hosts.length === 0 ? <div className="hm-muted">No hosts.</div> : null}
      {hosts && hosts.length > 0 ? (
        <div className={loading ? 'hm-dim' : undefined}>
          <Summary entries={entries} onOpen={setOpen} now={loadedAt} />
          <div className="hm-board">
            {entries.map(({ row, health }) => (
              <HostCard key={row.id} row={row} health={health} onOpen={setOpen} />
            ))}
          </div>
        </div>
      ) : null}
      {open ? (
        <HostModal ctx={ctx} host={open} isOpen onClose={() => setOpen(null)} />
      ) : null}
    </div>
  );
}

export default Page;
