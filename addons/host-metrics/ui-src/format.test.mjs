import test from 'node:test';
import assert from 'node:assert/strict';
import {
  fmtPct, fmtBytes, statusLabel, slotsText, stateLabel, fmtDuration,
} from './format.js';

test('fmtPct: one decimal under 10, none above, dash for no data', () => {
  assert.equal(fmtPct(null), '-');
  assert.equal(fmtPct(undefined), '-');
  assert.equal(fmtPct(NaN), '-');
  assert.equal(fmtPct(0), '0.0%');
  assert.equal(fmtPct(4.26), '4.3%');
  assert.equal(fmtPct(63.4), '63%');
  assert.equal(fmtPct(100), '100%');
});

test('fmtBytes: binary units, dash for no data', () => {
  assert.equal(fmtBytes(null), '-');
  assert.equal(fmtBytes(0), '0 B');
  assert.equal(fmtBytes(512), '512 B');
  assert.equal(fmtBytes(1024), '1.0 KB');
  assert.equal(fmtBytes(1536 * 1024), '1.5 MB');
  assert.equal(fmtBytes(15 * 1024 ** 3), '15 GB');
  assert.equal(fmtBytes(3 * 1024 ** 4), '3.0 TB');
});

test('statusLabel: text and tone per verdict status', () => {
  assert.deepEqual(statusLabel('ok'), { text: 'OK', tone: 'good' });
  assert.deepEqual(statusLabel('tight'), { text: 'Tight', tone: 'warning' });
  assert.deepEqual(statusLabel('overloaded'), { text: 'Overloaded', tone: 'critical' });
  assert.deepEqual(statusLabel('unknown'), { text: 'No data under load', tone: 'neutral' });
  assert.deepEqual(statusLabel(undefined), { text: 'No data under load', tone: 'neutral' });
});

test('slotsText: room for N more, no room, dash without a count', () => {
  assert.equal(slotsText(null), '-');
  assert.equal(slotsText({ status: 'unknown', slots: null }), '-');
  assert.equal(slotsText({ status: 'ok', slots: 3 }), 'room for 3 more');
  assert.equal(slotsText({ status: 'ok', slots: 1 }), 'room for 1 more');
  assert.equal(slotsText({ status: 'tight', slots: 0 }), 'no room');
});

test('stateLabel: host row states other than ok', () => {
  assert.equal(stateLabel('ok'), null);
  assert.equal(stateLabel('not_installed'), 'Not installed');
  assert.equal(stateLabel('outdated'), 'Outdated collector');
  assert.equal(stateLabel('unreachable'), 'Unreachable');
  assert.equal(stateLabel('no_sudo'), 'No sudo');
  assert.equal(stateLabel('no_data'), 'No data yet');
});

test('fmtDuration: compact span', () => {
  assert.equal(fmtDuration(45), '45s');
  assert.equal(fmtDuration(125), '2m');
  assert.equal(fmtDuration(3 * 3600 + 120), '3h 2m');
  assert.equal(fmtDuration(null), '-');
});
