import test from 'node:test';
import assert from 'node:assert/strict';
import {
  refreshIntervalMs, shouldRefresh, ageSeconds, updatedText, SNAPSHOT_INTERVAL_MS,
} from './refresh.js';

const base = {
  enabled: true, isOpen: true, visible: true, inFlight: false, lastAttemptAt: 0, now: 10000, intervalMs: 10000,
};

test('refreshIntervalMs: 10 s for 1h/6h, 60 s for the minute ranges', () => {
  assert.equal(refreshIntervalMs('1h'), 10000);
  assert.equal(refreshIntervalMs('6h'), 10000);
  for (const r of ['24h', '7d', '30d']) assert.equal(refreshIntervalMs(r), 60000);
  assert.equal(SNAPSHOT_INTERVAL_MS, 60000);
});

test('shouldRefresh: due exactly at the interval, not before', () => {
  assert.equal(shouldRefresh({ ...base, now: 9999 }), false);
  assert.equal(shouldRefresh(base), true);
  assert.equal(shouldRefresh({ ...base, now: 600000 }), true); // overdue after a hidden tab
});

test('shouldRefresh: off, closed, hidden or in flight never refreshes', () => {
  assert.equal(shouldRefresh({ ...base, enabled: false }), false);
  assert.equal(shouldRefresh({ ...base, isOpen: false }), false);
  assert.equal(shouldRefresh({ ...base, visible: false }), false);
  assert.equal(shouldRefresh({ ...base, inFlight: true }), false);
});

test('shouldRefresh: nothing loaded yet is not a background refresh', () => {
  assert.equal(shouldRefresh({ ...base, lastAttemptAt: null }), false);
  assert.equal(shouldRefresh({ ...base, lastAttemptAt: undefined }), false);
});

test('a range change resets the timer: a fresh attempt makes it not due', () => {
  assert.equal(shouldRefresh({ ...base, lastAttemptAt: 9000, now: 10000 }), false);
});

test('ageSeconds and updatedText', () => {
  assert.equal(ageSeconds(null, 5), null);
  assert.equal(ageSeconds(1000, 4999), 3);
  assert.equal(ageSeconds(5000, 1000), 0);
  assert.equal(updatedText(null, 1), '');
  assert.equal(updatedText(0, 0), 'Updated 0 s ago');
  assert.equal(updatedText(0, 59999), 'Updated 59 s ago');
  assert.equal(updatedText(0, 125000), 'Updated 2 min ago');
});
