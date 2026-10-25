import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  baselineValue, entryState, isChanged, pendingChanges, persistLine, rowState, stripColors,
} from './rows.js';

const row = (over) => ({
  name: 'qlx_x', type: 'string', default: '50', cfg: '25', live: '25', live_default: '50',
  latched: null, reported: true, ...over,
});

test('baseline prefers live, then cfg, then the declared default', () => {
  assert.equal(baselineValue(row()), '25');
  assert.equal(baselineValue(row({ reported: false, live: null })), '25');
  assert.equal(baselineValue(row({ reported: false, live: null, cfg: null })), '50');
  assert.equal(baselineValue(row({ reported: false, live: null, cfg: null, default: null })), '');
});

test('changed only when the edit differs from the baseline', () => {
  assert.equal(isChanged(row(), {}), false);
  assert.equal(isChanged(row(), { qlx_x: '25' }), false);
  assert.equal(isChanged(row(), { qlx_x: '30' }), true);
});

test('state chips', () => {
  assert.deepEqual(rowState(row(), {}, true), { kind: 'ok', text: 'in sync' });
  assert.deepEqual(rowState(row(), { qlx_x: '30' }, true), { kind: 'changed', text: 'changed' });
  assert.deepEqual(rowState(row({ latched: '24' }), {}, true), { kind: 'info', text: 'latched 24 · on next map' });
  assert.deepEqual(rowState(row({ cfg: '30' }), {}, true), { kind: 'warn', text: 'drift · cfg 30' });
  assert.deepEqual(rowState(row({ cfg: null, live: '50' }), {}, true), { kind: 'muted', text: 'default' });
  assert.deepEqual(rowState(row({ cfg: null }), {}, true), { kind: 'warn', text: 'live only · lost on restart' });
  assert.deepEqual(rowState(row({ reported: false, live: null }), {}, true), { kind: 'muted', text: 'unknown to server' });
  assert.deepEqual(rowState(row(), {}, false), { kind: 'muted', text: 'no live value' });
});

test('pending changes carry the edited value per name', () => {
  const groups = [{ cvars: [row(), row({ name: 'timelimit', cfg: '15', live: '15' })] }];
  assert.deepEqual(pendingChanges(groups, { timelimit: '20', qlx_x: '25' }), [{ name: 'timelimit', value: '20' }]);
});

test('apply log lines', () => {
  assert.deepEqual(entryState({ state: 'live' }), { kind: 'ok', text: 'live' });
  assert.deepEqual(entryState({ state: 'latched' }), { kind: 'warn', text: 'applies on next map' });
  assert.deepEqual(entryState({ state: 'mismatch', live: '^1x' }), { kind: 'warn', text: 'server has x' });
  assert.deepEqual(persistLine({ persist: false }), { kind: 'warn', text: 'not written to server.cfg · live only' });
  assert.equal(persistLine({ persist: true, persist_result: { ok: true, diff: 'x' } }).kind, 'ok');
  assert.equal(persistLine({ persist: true, persist_result: { ok: false, skipped: 'busy' } }).text, 'busy');
  assert.equal(stripColors('^1sD ^7test'), 'sD test');
});
