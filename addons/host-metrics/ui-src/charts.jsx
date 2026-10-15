import React from './runtime';
import uPlot from 'uplot';
import 'uplot/dist/uPlot.min.css';
import { fmtTime } from './format';
import { lastValue, stackColumns } from './data';
import { peakOf } from './chartinfo';
import { chartColors, themeKey, watchTheme } from './theme';

// One chart card that explains itself: title, a "how to read" line, a direction chip (lower
// is better / for context), the finding about this chart, a legend whose items show the value
// now (or under the crosshair) and the peak with the series meaning as tooltip, dashed and
// labelled threshold lines, units on the y axis, and an empty state that says why.
//
// Rules taken from the dataviz skill: one y axis per chart (two measures of different
// scale are two charts sharing the time axis and the crosshair), categorical colors in
// fixed slot order (CSS variables --hm-s1..8, light and dark steps in panel.css), thin 2px
// lines, 1.5px surface gap between stacked fills, recessive grid, text in ink tokens
// (never the series color), a legend on every chart with the value under the crosshair.
//
// Theme: uPlot paints a canvas, so colours are read from the computed QLSM tokens when the
// plot is built (theme.js) and the plot is rebuilt when the `.dark` class of <html> changes.

const { useEffect, useRef, useState, useMemo } = React;

const SYNC_KEY = 'hm-time';
const FONT = 'system-ui, -apple-system, "Segoe UI", sans-serif';

/** 'light' | 'dark', following the `.dark` class QLSM puts on <html>. */
export function useThemeKey() {
  const [key, setKey] = useState(() => themeKey());
  useEffect(() => watchTheme(setKey), []);
  return key;
}

/** CSS variable name of a categorical slot (1-8); 0 or anything else is the muted gray. */
export function slotVar(slot) {
  return slot >= 1 && slot <= 8 ? `var(--hm-s${slot})` : 'var(--hm-s0)';
}

const TONE_VAR = {
  warning: 'var(--accent-warning)',
  critical: 'var(--accent-danger)',
  neutral: 'var(--text-muted)',
};

function seriesColor(colors, slot) {
  return colors.slots[slot >= 1 && slot <= 8 ? slot : 0];
}

/** Dashed, labelled threshold lines over the plot area (uPlot draw hook, canvas pixels). */
function drawThresholds(u, lines, colors) {
  if (!lines || !lines.length) return;
  const pr = uPlot.pxRatio || 1;
  const c = u.ctx;
  const { left, top, width, height } = u.bbox;
  c.save();
  c.font = `${Math.round(11 * pr)}px ${FONT}`;
  c.textAlign = 'right';
  const placed = []; // labels drawn so far: { y, left } (canvas px)
  for (const l of lines) {
    const y = Math.round(u.valToPos(l.value, 'y', true)) + 0.5;
    if (!Number.isFinite(y) || y < top || y > top + height) continue;
    c.strokeStyle = colors.tone[l.tone] || colors.muted;
    c.lineWidth = 1.5 * pr;
    c.setLineDash([5 * pr, 4 * pr]);
    c.beginPath();
    c.moveTo(left, y);
    c.lineTo(left + width, y);
    c.stroke();
    // label at the right end, above the line, or below it when there is no room above
    c.setLineDash([]);
    const above = y - top > 16 * pr;
    c.textBaseline = above ? 'bottom' : 'top';
    const ty = above ? y - 3 * pr : y + 3 * pr;
    const tw = c.measureText(l.label).width;
    const boxTop = above ? ty - 13 * pr : ty - 1 * pr;
    // two lines close together: put this label left of the one it would cover
    let right = left + width - 4 * pr;
    for (const p of placed) {
      if (Math.abs(p.top - boxTop) < 14 * pr) right = Math.min(right, p.left - 10 * pr);
    }
    c.fillStyle = colors.surface;
    c.fillRect(right - tw - 4 * pr, boxTop, tw + 6 * pr, 14 * pr);
    c.fillStyle = colors.ink2;
    c.fillText(l.label, right, ty);
    placed.push({ top: boxTop, left: right - tw - 4 * pr });
  }
  c.restore();
}

function DirectionChip({ direction }) {
  if (direction === 'lower') {
    return (
      <span className="hm-chip" title="Smaller values are better on this chart.">
        <svg viewBox="0 0 12 12" aria-hidden="true"><path d="M6 2v8M3 7l3 3 3-3" /></svg>
        Lower is better
      </span>
    );
  }
  if (direction === 'higher') {
    return (
      <span className="hm-chip" title="Larger values are better on this chart.">
        <svg viewBox="0 0 12 12" aria-hidden="true"><path d="M6 10V2M3 5l3-3 3 3" /></svg>
        Higher is better
      </span>
    );
  }
  if (direction === 'context') {
    return (
      <span className="hm-chip" title="No good or bad value: read it next to the other charts.">For context</span>
    );
  }
  return null;
}

const FINDING_TONE = { problem: 'critical', warning: 'warning', info: 'neutral', ok: 'good' };

/** One finding (findings.js) as an icon plus text; the icon carries the level, never colour alone. */
export function FindingLine({ finding }) {
  if (!finding) return null;
  const tone = FINDING_TONE[finding.level] || 'neutral';
  const props = {
    viewBox: '0 0 16 16', fill: 'none', stroke: 'currentColor', strokeWidth: 1.8,
    strokeLinecap: 'round', strokeLinejoin: 'round', 'aria-hidden': true,
  };
  let icon;
  if (tone === 'good') icon = <svg {...props}><circle cx="8" cy="8" r="6.5" /><path d="M5 8.2l2.2 2.2L11 6" /></svg>;
  else if (tone === 'warning') icon = <svg {...props}><path d="M8 2l6.5 11.5h-13z" /><path d="M8 6.5v3M8 11.6v.1" /></svg>;
  else if (tone === 'critical') icon = <svg {...props}><circle cx="8" cy="8" r="6.5" /><path d="M5.5 5.5l5 5M10.5 5.5l-5 5" /></svg>;
  else icon = <svg {...props}><circle cx="8" cy="8" r="6.5" /><path d="M8 7.2v4M8 4.9v.1" /></svg>;
  const label = { good: 'OK', warning: 'Warning', critical: 'Problem', neutral: 'Note' }[tone];
  return (
    <div className={`hm-finding hm-finding-${tone}`}>
      <span className="hm-finding-icon" title={label}>{icon}</span>
      <span>{finding.text}</span>
    </div>
  );
}

/**
 * props
 *   title, subtitle
 *   howTo      one line: what the chart shows and how to read it
 *   direction  'lower' | 'higher' | 'context' (chip next to the title)
 *   finding    { level, area, text } from findings.js, shown above the plot
 *   series     [{ label, slot, step?, hint? }]  stacked: bottom to top; hint = legend tooltip
 *   thresholds [{ value, label, tone, hint? }]  dashed lines (chartinfo.js)
 *   xs         timestamps (seconds), ascending
 *   columns    one array per series, same length as xs (null = no data)
 *   xRange     [from, to] seconds, shared by every chart of the dialog
 *   yFmt       value -> text (legend, tooltip)
 *   axisFmt    value -> shorter text for the axis ticks (default yFmt)
 *   yLabel     unit written along the y axis (for counts without a unit in the ticks)
 *   yRange     dataMax -> [min, max]; the top is raised so every threshold line is visible
 *   stacked    cumulative filled layers
 *   height     plot height in px
 *   seconds    show seconds in the tooltip time (raw resolution)
 *   dim        reduce opacity while the data reloads
 *   emptyText  why the chart is empty
 */
export function ChartCard({
  title, subtitle, howTo, direction, finding, series, thresholds = [], xs, columns, xRange, yFmt,
  axisFmt, yLabel, yRange, stacked = false, height = 150, seconds = false, dim = false,
  emptyText = 'No data in this range.',
}) {
  const theme = useThemeKey();
  const wrapRef = useRef(null);
  const plotRef = useRef(null);
  const uRef = useRef(null);
  const live = useRef({});
  const [hover, setHover] = useState(null);
  const [width, setWidth] = useState(0);

  const hasData = xs.length > 0 && columns.some((c) => c.some((v) => v !== null && v !== undefined));
  const lineSig = thresholds.map((t) => `${t.value}:${t.tone}:${t.label}`).join('|');
  const sig = `${series.map((s) => `${s.label}:${s.slot}:${s.step ? 1 : 0}`).join('|')}|${stacked}|${height}|${theme}|${hasData}|${lineSig}|${yLabel || ''}`;

  // Display columns: cumulative and top layer first when stacked, so each fill is drawn
  // over the taller one behind it and no band logic is needed.
  const display = useMemo(() => {
    if (!stacked) return { cols: columns, order: series.map((_, i) => i) };
    const cum = stackColumns(columns);
    const order = series.map((_, i) => series.length - 1 - i);
    return { cols: order.map((i) => cum[i]), order };
  }, [columns, series, stacked]);

  const peaks = useMemo(() => columns.map((c) => peakOf(c)), [columns]);

  live.current = {
    xs, display, xRange, yRange, thresholds,
  };

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return undefined;
    const measure = () => setWidth(Math.floor(el.clientWidth));
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  // (Re)create the canvas when anything that shapes it changes, the theme included. Data-only
  // updates go through setData below.
  useEffect(() => {
    const host = plotRef.current;
    if (!host || !hasData || width < 40) return undefined;
    const colors = chartColors(getComputedStyle(host));
    const font = `11px ${FONT}`;
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
        y: {
          range: (u, min, max) => {
            const [lo, hi] = live.current.yRange(max);
            let top = hi;
            for (const t of live.current.thresholds || []) {
              if (Number.isFinite(t.value) && t.value * 1.05 > top) top = t.value * 1.15;
            }
            return [lo, top];
          },
        },
      },
      axes: [
        { ...axisBase, size: 28 },
        {
          ...axisBase,
          size: 58,
          values: (u, vals) => vals.map((v) => (axisFmt || yFmt)(v)),
          ...(yLabel ? { label: yLabel, labelSize: 16, labelFont: font } : {}),
        },
      ],
      series: uSeries,
      hooks: {
        draw: [(u) => drawThresholds(u, live.current.thresholds, colors)],
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

  // The legend never changes on hover (latest value and peak), so the card
  // keeps its layout; the value under the crosshair lives in the tooltip.
  const fmtValue = (v) => (v === null || v === undefined ? 'no data' : yFmt(v));
  const latestAt = (col) => fmtValue(lastValue(col));
  const hoveredAt = (col) => fmtValue(hover ? col[hover.idx] : lastValue(col));
  const flipLeft = hover && width && hover.left > width * 0.6;

  return (
    <div className={`hm-card${dim ? ' hm-dim' : ''}`}>
      <div className="hm-card-head">
        <div>
          <span className="hm-card-title">{title}</span>
          {subtitle ? <span className="hm-card-sub">{subtitle}</span> : null}
        </div>
        <DirectionChip direction={direction} />
      </div>
      {howTo ? <div className="hm-howto">{howTo}</div> : null}
      <FindingLine finding={finding} />
      <div className="hm-legend">
        {series.map((s, i) => (
          <span className="hm-legend-item" key={s.label} title={s.hint || undefined}>
            <span
              className={stacked ? 'hm-swatch-box' : 'hm-swatch-line'}
              style={{ background: slotVar(s.slot) }}
            />
            <span>{s.label}</span>
            <span className="hm-legend-value">{latestAt(columns[i] || [])}</span>
            {peaks[i] !== null ? (
              <span className="hm-muted">peak {yFmt(peaks[i])}</span>
            ) : null}
          </span>
        ))}
        {thresholds.map((t) => (
          <span className="hm-legend-item" key={`t-${t.label}`} title={t.hint || undefined}>
            <span className="hm-swatch-dash" style={{ borderColor: TONE_VAR[t.tone] || TONE_VAR.neutral }} />
            <span>{t.label}</span>
          </span>
        ))}
        <span className="hm-muted">latest values; peak over the range</span>
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
                    <span className="hm-tip-val">{hoveredAt(columns[i] || [])}</span>
                  </div>
                ))}
              </div>
            ) : null}
          </>
        ) : (
          <div className="hm-chart-empty" style={{ height }}>{emptyText}</div>
        )}
      </div>
    </div>
  );
}
