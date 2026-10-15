import test from 'node:test';
import assert from 'node:assert/strict';
import {
  chartLimits, findingFor, peakOf, tickMsOf, yMaxWith,
} from './chartinfo.js';

const GB = 1073741824;

test('chartLimits uses the defaults without settings', () => {
  const l = chartLimits({}, null);
  assert.deepEqual(l.cpu.map((t) => [t.value, t.tone]), [[70, 'warning'], [95, 'critical']]);
  assert.match(l.cpu[0].label, /70 %/);
  assert.match(l.cpu[1].label, /95 %/);
  assert.deepEqual(l.steal.map((t) => t.value), [5]);
  assert.deepEqual(l.disk.map((t) => t.value), [90]);
  assert.equal(l.tickMs, 25);
  assert.equal(l.tickKnown, false);
  assert.deepEqual(l.frameGap.map((t) => t.value), [25, 37.5]);
  assert.equal(l.lateMs, 37.5);
  assert.equal(l.memReservePct, 20);
});

test('chartLimits follows the settings (strings or numbers) and the measured tick', () => {
  const l = chartLimits({
    verdict_target_pct: '60', core_saturated_pct: 90, steal_tight_pct: '3', disk_low_pct: '85', mem_reserve_pct: '25',
  }, 16.7);
  assert.deepEqual(l.cpu.map((t) => t.value), [60, 90]);
  assert.deepEqual(l.steal.map((t) => t.value), [3]);
  assert.deepEqual(l.disk.map((t) => t.value), [85]);
  assert.equal(l.tickKnown, true);
  assert.equal(l.tickMs, 16.7);
  assert.ok(Math.abs(l.lateMs - 25.05) < 1e-9);
  assert.equal(l.memReservePct, 25);
});

test('chartLimits ignores garbage settings and a non-positive tick', () => {
  const l = chartLimits({ verdict_target_pct: 'abc', disk_low_pct: '' }, 0);
  assert.equal(l.cpu[0].value, 70);
  assert.equal(l.disk[0].value, 90);
  assert.equal(l.tickMs, 25);
  assert.equal(l.tickKnown, false);
});

test('memReserve gives the used-RAM line where the reserve starts, or nothing without a total', () => {
  const l = chartLimits({ mem_reserve_pct: '20' }, null);
  const lines = l.memReserve(10 * GB);
  assert.equal(lines.length, 1);
  assert.equal(lines[0].value, 8 * GB);
  assert.match(lines[0].label, /20 % reserve/);
  assert.deepEqual(l.memReserve(null), []);
  assert.deepEqual(l.memReserve(0), []);
});

test('tickMsOf takes the newest tick_ms of the series, else of the snapshot, else null', () => {
  const series = { insts: { 27960: [{ ts: 1, tick_ms: 25 }, { ts: 3, tick_ms: null }], 27961: [{ ts: 2, tick_ms: 16.7 }] } };
  assert.equal(tickMsOf(series, null), 16.7);
  const snapshot = { insts_last: [{ port: 27960, tick_ms: 25 }] };
  assert.equal(tickMsOf({ insts: {} }, snapshot), 25);
  assert.equal(tickMsOf(null, { insts_last: [{ tick_ms: 0 }] }), null);
  assert.equal(tickMsOf(undefined, undefined), null);
});

test('yMaxWith keeps the data and every threshold line inside the scale', () => {
  assert.equal(yMaxWith(10, 4, []), 11);
  assert.equal(yMaxWith(1, 4, []), 4);
  assert.equal(yMaxWith(20, 10, [{ value: 37.5 }]), 37.5 * 1.15);
  assert.equal(yMaxWith(null, 4, [{ value: 5 }]), 5 * 1.15);
});

test('peakOf returns the largest number of a column, null for a column without numbers', () => {
  assert.equal(peakOf([null, 3, 7, undefined, 2]), 7);
  assert.equal(peakOf([null, undefined]), null);
  assert.equal(peakOf([]), null);
});

test('findingFor picks the most severe finding of an area, and the one of a core for cpu', () => {
  const list = [
    { level: 'ok', area: 'cpu', text: 'Core 0 stayed below 40 % (p95 30 %) over the last hour; limit for planning is 70 %.' },
    { level: 'problem', area: 'cpu', text: 'Core 1 was above 95 % for 3 minutes.' },
    { level: 'ok', area: 'cpu', text: 'Core 10 p95 was 5 % over the last hour; limit for planning is 70 %.' },
    { level: 'ok', area: 'frames', text: 'No late server frames in the last hour.' },
    { level: 'warning', area: 'frames', text: '3 late frames on :27960.' },
    { level: 'problem', area: 'frames', text: '9 late frames on :27961.' },
  ];
  assert.equal(findingFor(list, 'cpu', { core: 1 }).level, 'problem');
  assert.match(findingFor(list, 'cpu', { core: 0 }).text, /^Core 0 /);
  assert.match(findingFor(list, 'cpu', { core: 10 }).text, /^Core 10 /);
  assert.equal(findingFor(list, 'cpu', { core: 2 }), null);
  assert.match(findingFor(list, 'frames').text, /27961/);
  assert.equal(findingFor(list, 'disk'), null);
  assert.equal(findingFor(null, 'disk'), null);
});
