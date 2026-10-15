// Theme for the canvas charts (pure, tested with `node --test`; the DOM is passed in).
//
// QLSM switches theme by toggling `.dark` on <html>; its tokens (`--surface-*`, `--text-*`,
// `--accent-*`, frontend-react/src/index.css) change with it. CSS follows on its own, but uPlot
// paints on a canvas with plain colour strings, so the colours are read from the computed
// tokens when a chart is drawn and the chart is redrawn when the class of <html> changes.
//
// The fallbacks below are used only when a token is missing (a core without it): mid grays
// that stay readable on a light and on a dark surface, never a light-only or dark-only colour.

const FALLBACK = {
  surface: 'transparent',
  line: 'rgba(128, 128, 128, 0.35)',
  lineStrong: 'rgba(128, 128, 128, 0.6)',
  ink: 'rgb(128, 128, 128)',
};

/** Value of a CSS custom property from a computed style, trimmed; `fallback` when unset. */
export function readToken(style, name, fallback) {
  if (!style || typeof style.getPropertyValue !== 'function') return fallback;
  const v = String(style.getPropertyValue(name) || '').trim();
  return v || fallback;
}

/**
 * Every colour a chart paints, from a computed style of an element inside the addon root:
 * chrome from the QLSM tokens, series from the addon's categorical slots `--hm-s0..8`
 * (panel.css; 0 is the muted "other" slot), threshold lines from the accent tokens.
 */
export function chartColors(style) {
  const t = (name, fallback) => readToken(style, name, fallback);
  const muted = t('--text-muted', FALLBACK.ink);
  const s0 = t('--hm-s0', muted);
  const slots = [s0];
  for (let i = 1; i <= 8; i += 1) slots.push(t(`--hm-s${i}`, s0));
  return {
    surface: t('--surface-raised', FALLBACK.surface),
    grid: t('--surface-border', FALLBACK.line),
    axis: t('--surface-border-strong', FALLBACK.lineStrong),
    ink: t('--text-primary', FALLBACK.ink),
    ink2: t('--text-secondary', FALLBACK.ink),
    muted,
    tone: {
      warning: t('--accent-warning', FALLBACK.lineStrong),
      critical: t('--accent-danger', FALLBACK.lineStrong),
      neutral: muted,
    },
    slots,
  };
}

/** 'dark' when <html> carries QLSM's `.dark` class, else 'light'. */
export function themeKey(doc = typeof document !== 'undefined' ? document : undefined) {
  return doc?.documentElement?.classList?.contains('dark') ? 'dark' : 'light';
}

/**
 * Calls `onChange(themeKey)` whenever the class attribute of <html> changes. Returns the
 * function that stops watching. Without a document or MutationObserver it does nothing.
 */
export function watchTheme(
  onChange,
  doc = typeof document !== 'undefined' ? document : undefined,
  Observer = typeof MutationObserver !== 'undefined' ? MutationObserver : undefined,
) {
  if (!doc?.documentElement || !Observer) return () => {};
  const observer = new Observer(() => onChange(themeKey(doc)));
  observer.observe(doc.documentElement, { attributes: true, attributeFilter: ['class'] });
  return () => observer.disconnect();
}
