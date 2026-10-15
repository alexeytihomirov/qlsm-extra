import test from 'node:test';
import assert from 'node:assert/strict';
import { chartColors, readToken, themeKey, watchTheme } from './theme.js';

/** A stand-in for CSSStyleDeclaration: only getPropertyValue is used. */
const style = (vars) => ({ getPropertyValue: (name) => (name in vars ? `  ${vars[name]} ` : '') });

test('readToken trims the value and falls back when the token is missing or blank', () => {
  const s = style({ '--surface-raised': '#111820', '--blank': '' });
  assert.equal(readToken(s, '--surface-raised', 'x'), '#111820');
  assert.equal(readToken(s, '--missing', 'fallback'), 'fallback');
  assert.equal(readToken(s, '--blank', 'fallback'), 'fallback');
  assert.equal(readToken(null, '--surface-raised', 'fallback'), 'fallback');
});

test('chartColors reads chrome from the QLSM tokens and series from the slot tokens', () => {
  const light = style({
    '--surface-raised': '#FAFBFC',
    '--surface-border': '#D0D7E0',
    '--surface-border-strong': '#B0BAC6',
    '--text-primary': '#0F172A',
    '--text-secondary': '#3E4C5E',
    '--text-muted': '#7E8D9F',
    '--accent-warning': '#D97706',
    '--accent-danger': '#DC2626',
    '--hm-s1': '#2a78d6',
    '--hm-s3': '#1baf7a',
    '--hm-s0': '#7E8D9F',
  });
  const c = chartColors(light);
  assert.equal(c.surface, '#FAFBFC');
  assert.equal(c.grid, '#D0D7E0');
  assert.equal(c.axis, '#B0BAC6');
  assert.equal(c.ink, '#0F172A');
  assert.equal(c.ink2, '#3E4C5E');
  assert.equal(c.muted, '#7E8D9F');
  assert.equal(c.tone.warning, '#D97706');
  assert.equal(c.tone.critical, '#DC2626');
  assert.equal(c.tone.neutral, '#7E8D9F');
  assert.equal(c.slots.length, 9);
  assert.equal(c.slots[1], '#2a78d6');
  assert.equal(c.slots[3], '#1baf7a');
  assert.equal(c.slots[0], '#7E8D9F');
});

test('chartColors follows a theme switch: the same call on the dark values gives the dark colours', () => {
  const dark = style({ '--surface-raised': '#111820', '--accent-warning': '#FFB800', '--hm-s1': '#3987e5' });
  const c = chartColors(dark);
  assert.equal(c.surface, '#111820');
  assert.equal(c.tone.warning, '#FFB800');
  assert.equal(c.slots[1], '#3987e5');
});

test('chartColors never returns an empty colour: every missing token has a fallback', () => {
  const c = chartColors(style({}));
  for (const v of [c.surface, c.grid, c.axis, c.ink, c.ink2, c.muted, c.tone.warning, c.tone.critical,
    c.tone.neutral, ...c.slots]) {
    assert.equal(typeof v, 'string');
    assert.ok(v.length > 0);
  }
  // a missing slot falls back to the muted gray slot, not to a made-up hue
  const partial = chartColors(style({ '--hm-s0': '#7E8D9F' }));
  assert.equal(partial.slots[5], '#7E8D9F');
});

test('themeKey reads the .dark class of <html>', () => {
  const doc = (cls) => ({ documentElement: { classList: { contains: (c) => cls.includes(c) } } });
  assert.equal(themeKey(doc(['dark'])), 'dark');
  assert.equal(themeKey(doc([])), 'light');
  assert.equal(themeKey(undefined), 'light');
});

test('watchTheme observes the class attribute of <html> and reports the new key', () => {
  let classes = [];
  const doc = { documentElement: { classList: { contains: (c) => classes.includes(c) } } };
  let observed = null;
  let disconnected = false;
  class FakeObserver {
    constructor(cb) { this.cb = cb; }
    observe(el, opts) { observed = { el, opts, cb: this.cb }; }
    disconnect() { disconnected = true; }
  }
  const seen = [];
  const stop = watchTheme((k) => seen.push(k), doc, FakeObserver);
  assert.equal(observed.el, doc.documentElement);
  assert.deepEqual(observed.opts, { attributes: true, attributeFilter: ['class'] });
  classes = ['dark'];
  observed.cb();
  classes = [];
  observed.cb();
  assert.deepEqual(seen, ['dark', 'light']);
  stop();
  assert.equal(disconnected, true);
});

test('watchTheme without MutationObserver is a no-op that still returns a stop function', () => {
  const stop = watchTheme(() => {}, undefined, undefined);
  assert.equal(typeof stop, 'function');
  stop();
});
