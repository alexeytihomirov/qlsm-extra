import test from 'node:test';
import assert from 'node:assert/strict';
import {
  pick, mergeTimes, column, sortedPorts, coreIds, stackColumns, lastValue,
  eventsTotal, playersNow, diskUsedPct,
} from './data.js';

test('pick takes the first finite key', () => {
  assert.equal(pick({ cpu_avg: 12 }, 'cpu', 'cpu_avg'), 12);
  assert.equal(pick({ cpu: null, cpu_avg: 3 }, 'cpu', 'cpu_avg'), 3);
  assert.equal(pick({}, 'cpu'), null);
  assert.equal(pick(null, 'cpu'), null);
});

test('mergeTimes + column align lists with different timestamps', () => {
  const a = [{ ts: 10, v: 1 }, { ts: 30, v: 3 }];
  const b = [{ ts: 20, v: 2 }, { ts: 30, v: 4 }];
  const xs = mergeTimes(a, b);
  assert.deepEqual(xs, [10, 20, 30]);
  assert.deepEqual(column(a, xs, (r) => r.v), [1, null, 3]);
  assert.deepEqual(column(b, xs, (r) => r.v), [null, 2, 4]);
});

test('ports are numeric and ascending, keys come as strings', () => {
  assert.deepEqual(sortedPorts({ 27961: [], 27960: [], 100: [] }), [100, 27960, 27961]);
  assert.deepEqual(sortedPorts(null), []);
});

test('coreIds lists -1 first', () => {
  assert.deepEqual(coreIds([{ core: 1 }, { core: -1 }, { core: 0 }, { core: 1 }]), [-1, 0, 1]);
});

test('stackColumns is cumulative bottom to top and keeps gaps', () => {
  const out = stackColumns([[1, null, 2], [1, 1, null], [0.5, null, null]]);
  assert.deepEqual(out, [[1, null, 2], [2, 1, 2], [2.5, 1, 2]]);
});

test('lastValue skips trailing nulls', () => {
  assert.equal(lastValue([1, 2, null]), 2);
  assert.equal(lastValue([null]), null);
});

test('snapshot helpers', () => {
  assert.equal(eventsTotal({ events_24h: { a: 2, b: 3 } }), 5);
  assert.equal(eventsTotal(null), 0);
  assert.equal(playersNow({ insts_last: [{ players: 3 }, { players: null }, { players: 2 }] }), 5);
  assert.equal(playersNow({ insts_last: [{ players: null }] }), null);
  assert.equal(diskUsedPct({ disk_used: 50, disk_total: 200 }), 25);
  assert.equal(diskUsedPct({ disk_used: 50, disk_total: null }), null);
});
