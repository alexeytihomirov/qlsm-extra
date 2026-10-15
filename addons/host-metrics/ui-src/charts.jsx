import React from './runtime';
import uPlot from 'uplot';
import 'uplot/dist/uPlot.min.css';
import { fmtTime } from './format';
import { lastValue, stackColumns } from './data';

// One chart card: title, legend with live values, a uPlot canvas and a hover tooltip.
//
// Rules taken from the dataviz skill: one y axis per chart (two measures of different
// scale are two charts sharing the time axis and the crosshair), categorical colors in
// fixed slot order (CSS variables --hm-s1..8, light and dark steps in panel.css), thin 2px
// lines, 1.5px surface gap between stacked fills, recessive grid, text in ink tokens
// (never the series color), a legend on every chart with the value under the crosshair.

const { useEffect, useRef, useState, useMemo } = React;

const SYNC_KEY = 'hm-time';

/** 'light' | 'dark', following the `.dark` class QLSM puts on <html>. */
export function useThemeKey() {
  const read = () => (typeof document !== 'undefined'
    && document.documentElement.classList.contains('dark') ? 'dark' : 'light');
  const [key, setKey] = useState(read);
  useEffect(() => {
    const observer = new MutationObserver(() => setKey(read()));
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] });
    return () => observer.disconnect();
  }, []);
  return key;
}

/** CSS variable name of a categorical slot (1-8); 0 or anything else is the muted gray. */
export function slotVar(slot) {
  return slot >= 1 && slot <= 8 ? `var(--hm-s${slot})` : 'var(--hm-s0)';
}

function readColors(el) {
  const cs = getComputedStyle(el);
  const v = (name, fallback) => cs.getPropertyValue(name).trim() || fallback;
  const slots = [];
  for (let i = 0; i <= 8; i += 1) slots.push(v(`--hm-s${i}`, '#888888'));
  return {
    surface: v('--hm-surface', '#ffffff'),
    muted: v('--hm-muted', '#898781'),
    grid: v('--hm-grid', '#e1e0d9'),
    axis: v('--hm-axis', '#c3c2b7'),
    slots,
  };
}

function seriesColor(colors, slot) {
  return colors.slots[slot >= 1 && slot <= 8 ? slot : 0];
}

/**
 * props
 *   title, subtitle
 *   series   [{ label, slot, step? }]  stacked: bottom to top
 *   xs       timestamps (seconds), ascending
 *   columns  one array per series, same length as xs (null = no data)
 *   xRange   [from, to] seconds, shared by every chart of the dialog
 *   yFmt     value -> text (legend, tooltip)
 *   axisFmt  value -> shorter text for the axis ticks (default yFmt)
 *   yRange   dataMax -> [min, max]
 *   stacked  cumulative filled layers
 *   height   plot height in px
 *   seconds  show seconds in the tooltip time (raw resolution)
 *   dim      reduce opacity while the data reloads
 */
export function ChartCard({
  title, subtitle, series, xs, columns, xRange, yFmt, axisFmt, yRange, stacked = false,
  height = 150, seconds = false, dim = false,
}) {
  const theme = useThemeKey();
  const wrapRef = useRef(null);
  const plotRef = useRef(null);
  const uRef = useRef(null);
  const live = useRef({});
  const [hover, setHover] = useState(null);
  const [width, setWidth] = useState(0);

  const hasData = xs.length > 0 && columns.some((c) => c.some((v) => v !== null && v !== undefined));
  const sig = `${series.map((s) => `${s.label}:${s.slot}:${s.step ? 1 : 0}`).join('|')}|${stacked}|${height}|${theme}|${hasData}`;

  // Display columns: cumulative and top layer first when stacked, so each fill is drawn
  // over the taller one behind it and no band logic is needed.
  const display = useMemo(() => {
    if (!stacked) return { cols: columns, order: series.map((_, i) => i) };
    const cum = stackColumns(columns);
    const order = series.map((_, i) => series.length - 1 - i);
    return { cols: order.map((i) => cum[i]), order };
  }, [columns, series, stacked]);

  live.current = { xs, display, xRange, yRange };

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return undefined;
    const measure = () => setWidth(Math.floor(el.clientWidth));
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  // (Re)create the canvas when anything that shapes it changes. Data-only updates go
  // through setData below.
  useEffect(() => {
    const host = plotRef.current;
    if (!host || !hasData || width < 40) return undefined;
    const colors = readColors(host);
    const font = '11px system-ui, -apple-system, "Segoe UI", sans-serif';
    const axisBase = {
      font,
      stroke: colors.muted,
      grid: { stroke: colors.grid, width: 1 },
      ticks: { show: false },
      border: { stroke: colors.axis, width: 1 },
    };
    const uSeries = [{}].concat(display.order.map((origIdx) => {
      const s = series[origIdx];
      const color = seriesColor(colors, s.slot);
      if (stacked) {
        return {
          label: s.label, stroke: colors.surface, width: 1.5, fill: color,
          points: { show: false }, spanGaps: false,
        };
      }
      return {
        label: s.label, stroke: color, width: 2, points: { show: false }, spanGaps: false,
        ...(s.step ? { paths: uPlot.paths.stepped({ align: 1 }) } : {}),
      };
    }));
    const dotColors = [null].concat(display.order.map((origIdx) => seriesColor(colors, series[origIdx].slot)));
    const opts = {
      width,
      height,
      legend: { show: false },
      padding: [8, 8, 0, 0],
      cursor: {
        sync: { key: SYNC_KEY, setSeries: false },
        drag: { x: false, y: false, setScale: false },
        points: {
          size: 8, width: 2,
          stroke: () => colors.surface,
          fill: (u, si) => dotColors[si] || colors.muted,
        },
      },
      scales: {
        x: { time: true, range: () => live.current.xRange },
        y: { range: (u, min, max) => live.current.yRange(max) },
      },
      axes: [
        { ...axisBase, size: 28 },
        {
          ...axisBase,
          size: 58,
          values: (u, vals) => vals.map((v) => (axisFmt || yFmt)(v)),
        },
      ],
      series: uSeries,
      hooks: {
        setCursor: [(u) => {
          const idx = u.cursor.idx;
          if (idx === null || idx === undefined || u.cursor.left < 0) {
            setHover((h) => (h === null ? h : null));
            return;
          }
          const left = u.over.offsetLeft + u.cursor.left;
          setHover((h) => (h && h.idx === idx && h.left === left ? h : { idx, left }));
        }],
      },
    };
    const u = new uPlot(opts, [live.current.xs, ...live.current.display.cols], host);
    uRef.current = u;
    return () => {
      u.destroy();
      uRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sig, width > 40]);

  useEffect(() => {
    if (uRef.current) uRef.current.setData([xs, ...display.cols], true);
  }, [xs, display, xRange]);

  useEffect(() => {
    if (uRef.current && width > 40) uRef.current.setSize({ width, height });
  }, [width, height]);

  const idx = hover ? hover.idx : null;
  const valueAt = (col) => {
    const v = idx !== null ? col[idx] : lastValue(col);
    return v === null || v === undefined ? 'no data' : yFmt(v);
  };
  const flipLeft = hover && width && hover.left > width * 0.6;

  return (
    <div className={`hm-card${dim ? ' hm-dim' : ''}`}>
      <div>
        <span className="hm-card-title">{title}</span>
        {subtitle ? <span className="hm-card-sub">{subtitle}</span> : null}
      </div>
      <div className="hm-legend">
        {series.map((s, i) => (
          <span className="hm-legend-item" key={s.label}>
            <span
              className={stacked ? 'hm-swatch-box' : 'hm-swatch-line'}
              style={{ background: slotVar(s.slot) }}
            />
            <span>{s.label}</span>
            <span className="hm-legend-value">{valueAt(columns[i] || [])}</span>
          </span>
        ))}
        <span className="hm-muted">{idx !== null ? fmtTime(xs[idx], seconds) : 'latest'}</span>
      </div>
      <div className="hm-chart" ref={wrapRef}>
        {hasData ? (
          <>
            <div ref={plotRef} />
            {hover ? (
              <div
                className="hm-tip"
                style={flipLeft
                  ? { left: hover.left - 12, transform: 'translateX(-100%)' }
                  : { left: hover.left + 12 }}
              >
                <div className="hm-tip-time">{fmtTime(xs[hover.idx], seconds)}</div>
                {series.map((s, i) => (
                  <div className="hm-tip-row" key={s.label}>
                    <span className="hm-swatch-line" style={{ background: slotVar(s.slot) }} />
                    <span className="hm-tip-name">{s.label}</span>
                    <span className="hm-tip-val">{valueAt(columns[i] || [])}</span>
                  </div>
                ))}
              </div>
            ) : null}
          </>
        ) : (
          <div className="hm-chart-empty" style={{ height }}>No data in this range</div>
        )}
      </div>
    </div>
  );
}
