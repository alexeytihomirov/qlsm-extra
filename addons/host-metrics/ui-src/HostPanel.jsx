import React, { ui } from './runtime';
import { ChartCard } from './charts';
import {
  column, coreIds, coreRows, lastValue, mergeTimes, pick, sortedPorts,
} from './data';
import { fmtBytes, fmtDuration, fmtPct, fmtTime } from './format';
import './panel.css';

const { Modal } = ui;
const { useCallback, useEffect, useMemo, useRef, useState } = React;

const RANGES = ['1h', '6h', '24h', '7d', '30d'];
const RANGE_SECONDS = { '1h': 3600, '6h': 21600, '24h': 86400, '7d': 604800, '30d': 2592000 };
const MAX_EVENT_ROWS = 100;

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

const pct0 = (v) => `${Math.round(v)}%`;
const int = (v) => String(Math.round(v));
const ms = (v) => `${v < 10 ? v.toFixed(1) : Math.round(v)} ms`;
const rate = (v) => `${fmtBytes(v)}/s`;

function errorText(e, fallback) {
  return e?.response?.data?.error?.message || e?.message || fallback;
}

function slotOf(index) {
  return index < 8 ? index + 1 : 0;
}

function SeverityIcon({ severity }) {
  const props = {
    viewBox: '0 0 16 16', fill: 'none', stroke: 'currentColor', strokeWidth: 1.8,
    strokeLinecap: 'round', strokeLinejoin: 'round', 'aria-hidden': true,
  };
  if (severity === 'crit') {
    return <svg {...props}><circle cx="8" cy="8" r="6.5" /><path d="M5.5 5.5l5 5M10.5 5.5l-5 5" /></svg>;
  }
  if (severity === 'warn') {
    return <svg {...props}><path d="M8 2l6.5 11.5h-13z" /><path d="M8 6.5v3M8 11.6v.1" /></svg>;
  }
  return <svg {...props}><circle cx="8" cy="8" r="6.5" /><path d="M8 7.2v4M8 4.9v.1" /></svg>;
}

const SEVERITY_TEXT = { crit: 'Critical', warn: 'Warning', info: 'Info' };
const SEVERITY_TONE = { crit: 'hm-tone-critical', warn: 'hm-tone-warning', info: 'hm-tone-neutral' };

function scopeText(ev) {
  if (ev.scope === 'instance') return `Port ${ev.port}`;
  if (ev.scope === 'core') return 'Core';
  return 'Host';
}

function EventsTable({ events, dim }) {
  if (!events.length) return <div className={`hm-muted${dim ? ' hm-dim' : ''}`}>No events in this range.</div>;
  const shown = events.slice(0, MAX_EVENT_ROWS);
  return (
    <div className={dim ? 'hm-dim' : undefined}>
      <div className="overflow-x-auto">
        <table className="hm-events">
          <thead>
            <tr>
              <th>Time</th><th>Severity</th><th>Event</th><th>Scope</th><th>Duration</th><th>Detail</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((ev) => (
              <tr key={ev.id}>
                <td className="hm-num" style={{ whiteSpace: 'nowrap' }}>{fmtTime(ev.ts, true)}</td>
                <td>
                  <span className={`hm-sev ${SEVERITY_TONE[ev.severity] || 'hm-tone-neutral'}`}>
                    <SeverityIcon severity={ev.severity} />
                    {SEVERITY_TEXT[ev.severity] || ev.severity}
                  </span>
                </td>
                <td>{KIND_LABELS[ev.kind] || ev.kind}</td>
                <td>{scopeText(ev)}</td>
                <td className="hm-num">
                  {ev.state === 'open' ? 'ongoing' : fmtDuration((ev.closed_ts || ev.ts) - ev.ts)}
                </td>
                <td className="hm-ink-2">{ev.message}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {events.length > shown.length ? (
        <div className="hm-muted" style={{ marginTop: 4 }}>
          Showing the newest {shown.length} of {events.length}.
        </div>
      ) : null}
    </div>
  );
}

/** Chart data of one `series` answer, ready for ChartCard props. */
function buildCharts(series, res) {
  const raw = res === 'raw';
  const hostRows = series?.host || [];
  const hostXs = mergeTimes(hostRows);
  const hostCol = (fn) => column(hostRows, hostXs, fn);

  const cores = coreIds(series?.cores).map((core) => {
    const rows = coreRows(series.cores, core);
    const xs = mergeTimes(rows);
    return {
      core,
      xs,
      columns: ['user', 'system', 'steal'].map((k) => column(rows, xs, (r) => pick(r, k))),
    };
  });

  const insts = series?.insts || {};
  const ports = sortedPorts(insts);
  const instXs = mergeTimes(...ports.map((p) => insts[String(p)]));
  const perPort = (...keys) => ports.map((p) => column(insts[String(p)], instXs, (r) => pick(r, ...keys)));
  const portSeries = (step) => ports.map((p, i) => ({ label: `Port ${p}`, slot: slotOf(i), step }));

  const memTotal = lastValue(hostCol((r) => pick(r, 'mem_total')));
  return {
    cores,
    hostXs,
    instXs,
    ports,
    portSeries,
    cpu: perPort('cpu', 'cpu_avg'),
    players: perPort('players', 'players_max'),
    maxGap: perPort('max_ms'),
    late: perPort('late'),
    instMem: perPort('mem', 'mem_max'),
    memTotal,
    memUsed: hostCol((r) => {
      const total = pick(r, 'mem_total');
      const avail = pick(r, 'mem_avail');
      return total === null || avail === null ? null : Math.max(total - avail, 0);
    }),
    swap: hostCol((r) => pick(r, 'swap_used')),
    rx: hostCol((r) => pick(r, 'rx_bps')),
    tx: hostCol((r) => pick(r, 'tx_bps')),
    disk: hostCol((r) => {
      const used = pick(r, 'disk_used');
      const total = pick(r, 'disk_total');
      return used === null || !total ? null : (used / total) * 100;
    }),
    lateUnit: raw ? 'per 10 s sample' : 'per minute',
  };
}

function Footer({ ctx, host, isOpen }) {
  const ctxRef = useRef(ctx);
  ctxRef.current = ctx; // core rebuilds ctx on every render; effects must not re-run for it
  const [status, setStatus] = useState(null);
  const [statusBusy, setStatusBusy] = useState(false);
  const [enabled, setEnabled] = useState(null);
  const [note, setNote] = useState(null);
  const [applyBusy, setApplyBusy] = useState(false);
  const token = useRef(0);

  const loadStatus = useCallback(async () => {
    if (!host?.id) return;
    const mine = ++token.current;
    setStatusBusy(true);
    try {
      const data = await ctxRef.current.api('GET', `hosts/${host.id}/status`);
      if (token.current === mine) setStatus(data);
    } catch (e) {
      if (token.current === mine) setStatus({ error: errorText(e, 'Could not read the status.') });
    } finally {
      if (token.current === mine) setStatusBusy(false);
    }
  }, [host?.id]);

  useEffect(() => {
    if (!isOpen || !host?.id) return;
    setStatus(null);
    setNote(null);
    setEnabled(null);
    loadStatus();
    ctxRef.current.api('GET', `hosts/${host.id}`).then((d) => setEnabled(Boolean(d?.enabled))).catch(() => {});
  }, [isOpen, host?.id, loadStatus]);

  const toggle = async (value) => {
    setEnabled(value);
    try {
      await ctxRef.current.api('PUT', `hosts/${host.id}`, { data: { enabled: value } });
      setNote(value ? 'Collection enabled. Use Apply to host to install or start it.'
        : 'Collection disabled. Use Apply to host to stop it on the host.');
    } catch (e) {
      setEnabled(!value);
      setNote(errorText(e, 'Could not save the switch.'));
    }
  };

  const apply = async () => {
    setApplyBusy(true);
    setNote(null);
    try {
      const data = await ctxRef.current.api('POST', `hosts/${host.id}/apply`);
      setNote(data?.message || 'Apply queued.');
    } catch (e) {
      setNote(errorText(e, 'Apply failed.'));
    } finally {
      setApplyBusy(false);
    }
  };

  let statusText;
  if (statusBusy && !status) statusText = 'Checking the collector...';
  else if (status?.error) statusText = status.error;
  else if (status) {
    const version = status.version || 'not installed';
    const outdated = status.version && status.expected_version && status.version !== status.expected_version;
    statusText = `Collector ${version}${outdated ? ` (current ${status.expected_version})` : ''}`
      + ` | service ${status.service || 'unknown'}`
      + (status.db_bytes !== null && status.db_bytes !== undefined ? ` | database ${fmtBytes(status.db_bytes)}` : '');
  } else statusText = '';

  return (
    <div className="hm-footer">
      <span>{statusText}</span>
      <button type="button" className="hm-btn" onClick={loadStatus} disabled={statusBusy}>Check</button>
      <label>
        <input
          type="checkbox"
          checked={Boolean(enabled)}
          disabled={enabled === null}
          onChange={(e) => toggle(e.target.checked)}
        />
        Collect metrics on this host
      </label>
      <span className="hm-footer-spacer" />
      {note ? <span className="hm-note">{note}</span> : null}
      <button type="button" className="hm-btn hm-btn-primary" onClick={apply} disabled={applyBusy}>
        Apply to host
      </button>
    </div>
  );
}

/**
 * The whole host dialog. `host` is `{ id, name }` (the host-menu entity, or a row of the
 * Host Metrics page).
 */
export function HostModal({ ctx, host, isOpen, onClose }) {
  const ctxRef = useRef(ctx);
  ctxRef.current = ctx;
  const [range, setRange] = useState('24h');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [series, setSeries] = useState(null);
  const [events, setEvents] = useState([]);
  const [fetchedAt, setFetchedAt] = useState(null);
  const token = useRef(0);

  const load = useCallback(async () => {
    if (!host?.id) return;
    const mine = ++token.current;
    setLoading(true);
    setError(null);
    try {
      const params = { range };
      const [s, e] = await Promise.all([
        ctxRef.current.api('GET', `hosts/${host.id}/series`, { params }),
        ctxRef.current.api('GET', `hosts/${host.id}/events`, { params }),
      ]);
      if (token.current !== mine) return;
      setSeries(s);
      setEvents(e?.events || []);
      setFetchedAt(Date.now());
    } catch (err) {
      if (token.current === mine) setError(errorText(err, 'Could not load the metrics.'));
    } finally {
      if (token.current === mine) setLoading(false);
    }
  }, [host?.id, range]);

  useEffect(() => {
    if (isOpen) load();
  }, [isOpen, load]);

  // Another host: drop the previous host's picture instead of dimming it.
  useEffect(() => {
    setSeries(null);
    setEvents([]);
    setError(null);
  }, [host?.id]);

  const charts = useMemo(() => (series ? buildCharts(series, series.res) : null), [series]);
  const now = series?.now || Math.floor(Date.now() / 1000);
  const xRange = useMemo(() => [now - RANGE_SECONDS[series?.range || range], now], [now, series?.range, range]);
  const seconds = series?.res === 'raw';
  const dim = loading && Boolean(series);
  const common = { xRange, seconds, dim };

  const noInstances = charts && charts.ports.length === 0;

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      size="2xl"
      height="85vh"
      title={(
        <>
          Host Metrics
          <span className="mt-0.5 block font-mono text-xs font-normal normal-case tracking-normal text-theme-secondary">
            {host?.name}
            {fetchedAt ? ` | loaded ${fmtTime(fetchedAt / 1000, true)}` : ''}
          </span>
        </>
      )}
      headerActions={(
        <>
          <button type="button" className="hm-btn" onClick={load} disabled={loading}>
            {loading ? 'Loading...' : 'Refresh'}
          </button>
          <button type="button" className="hm-btn" onClick={onClose} aria-label="Close">Close</button>
        </>
      )}
      footer={<Footer ctx={ctx} host={host} isOpen={isOpen} />}
    >
      <div className="hm-root hm-modal-body">
        <div className="hm-controls">
          <div className="hm-range" role="group" aria-label="Time range">
            {RANGES.map((r) => (
              <button key={r} type="button" aria-pressed={r === range} onClick={() => setRange(r)}>{r}</button>
            ))}
          </div>
          {series ? (
            <span className="hm-muted">
              {series.res === 'raw' ? '10 s samples' : '1 minute averages'}
            </span>
          ) : null}
        </div>

        {error ? <div className="hm-error">{error}</div> : null}
        {!series && loading ? <div className="hm-muted">Loading...</div> : null}

        {charts ? (
          <>
            <section>
              <div className="hm-section-title">CPU per core</div>
              {charts.cores.length === 0 ? (
                <div className="hm-muted">No core data in this range.</div>
              ) : (
                <div className="hm-grid-2">
                  {charts.cores.map((c) => (
                    <ChartCard
                      key={c.core}
                      title={c.core < 0 ? 'All cores' : `Core ${c.core}`}
                      subtitle="% of the core, stacked"
                      series={[
                        { label: 'User', slot: 1 }, { label: 'System', slot: 2 }, { label: 'Steal', slot: 3 },
                      ]}
                      xs={c.xs}
                      columns={c.columns}
                      stacked
                      height={120}
                      yFmt={fmtPct}
                      axisFmt={pct0}
                      yRange={() => [0, 100]}
                      {...common}
                    />
                  ))}
                </div>
              )}
            </section>

            <section>
              <div className="hm-section-title">CPU per instance</div>
              {noInstances ? <div className="hm-muted">No instance data in this range.</div> : (
                <div className="flex flex-col gap-3">
                  <ChartCard
                    title="CPU"
                    subtitle="% of one core"
                    series={charts.portSeries(false)}
                    xs={charts.instXs}
                    columns={charts.cpu}
                    height={150}
                    yFmt={fmtPct}
                    axisFmt={pct0}
                    yRange={(max) => [0, Math.max(10, max * 1.1)]}
                    {...common}
                  />
                  <ChartCard
                    title="Players"
                    subtitle="same time axis as CPU"
                    series={charts.portSeries(true)}
                    xs={charts.instXs}
                    columns={charts.players}
                    height={90}
                    yFmt={int}
                    yRange={(max) => [0, Math.max(4, Math.ceil(max))]}
                    {...common}
                  />
                </div>
              )}
            </section>

            <section>
              <div className="hm-section-title">Frame timing per instance</div>
              {noInstances ? <div className="hm-muted">No instance data in this range.</div> : (
                <div className="hm-grid-2">
                  <ChartCard
                    title="Max frame gap"
                    series={charts.portSeries(false)}
                    xs={charts.instXs}
                    columns={charts.maxGap}
                    height={130}
                    yFmt={ms}
                    yRange={(max) => [0, Math.max(10, max * 1.1)]}
                    {...common}
                  />
                  <ChartCard
                    title="Late frames"
                    subtitle={charts.lateUnit}
                    series={charts.portSeries(true)}
                    xs={charts.instXs}
                    columns={charts.late}
                    height={130}
                    yFmt={int}
                    yRange={(max) => [0, Math.max(4, Math.ceil(max * 1.1))]}
                    {...common}
                  />
                </div>
              )}
            </section>

            <section>
              <div className="hm-section-title">Memory</div>
              <div className="hm-grid-2">
                <ChartCard
                  title="Host memory"
                  subtitle={charts.memTotal ? `of ${fmtBytes(charts.memTotal)}` : undefined}
                  series={[{ label: 'Used', slot: 1 }, { label: 'Swap', slot: 2 }]}
                  xs={charts.hostXs}
                  columns={[charts.memUsed, charts.swap]}
                  height={130}
                  yFmt={fmtBytes}
                  yRange={(max) => [0, charts.memTotal || Math.max(1, max * 1.1)]}
                  {...common}
                />
                {noInstances ? null : (
                  <ChartCard
                    title="Memory per instance"
                    series={charts.portSeries(false)}
                    xs={charts.instXs}
                    columns={charts.instMem}
                    height={130}
                    yFmt={fmtBytes}
                    yRange={(max) => [0, Math.max(1, max * 1.1)]}
                    {...common}
                  />
                )}
              </div>
            </section>

            <section>
              <div className="hm-section-title">Network and disk</div>
              <div className="hm-grid-2">
                <ChartCard
                  title="Network"
                  subtitle="bytes per second"
                  series={[{ label: 'Received', slot: 1 }, { label: 'Sent', slot: 2 }]}
                  xs={charts.hostXs}
                  columns={[charts.rx, charts.tx]}
                  height={130}
                  yFmt={rate}
                  yRange={(max) => [0, Math.max(1024, max * 1.1)]}
                  {...common}
                />
                <ChartCard
                  title="Disk"
                  subtitle="root filesystem used"
                  series={[{ label: 'Used', slot: 1 }]}
                  xs={charts.hostXs}
                  columns={[charts.disk]}
                  height={130}
                  yFmt={fmtPct}
                  axisFmt={pct0}
                  yRange={() => [0, 100]}
                  {...common}
                />
              </div>
            </section>
          </>
        ) : null}

        <section>
          <div className="hm-section-title">Events</div>
          <EventsTable events={events} dim={dim} />
        </section>
      </div>
    </Modal>
  );
}

/**
 * Tier-2 entry for the host menu (`renders: "modal"`): the whole dialog is ours, `ctx.modal`
 * carries the open state and the host the menu entry was opened from.
 */
function HostPanel({ ctx }) {
  const modal = ctx?.modal || {};
  return (
    <HostModal ctx={ctx} host={modal.entity} isOpen={Boolean(modal.isOpen)} onClose={modal.onClose} />
  );
}

export default HostPanel;
