import test from 'node:test';
import assert from 'node:assert/strict';
import {
  hostHealth, sortByHealth, healthCounts, openEvents, hostIdFromSearch,
} from './data.js';
import { hardwareLine, hardwareDetails, kindLabel } from './format.js';

const NOW = 1_800_000_000;
const OK_VERDICT = { status: 'ok', slots: 2, reason: 'room for 2 more, core 0: ...', ref_load: 20, ref_source: 'host' };
const ROOM_OK = { level: 'ok', area: 'room', text: 'Room for 2 more instances (reference: one instance uses 20 % of a core in a match).' };
const CPU_OK = { level: 'ok', area: 'cpu', text: 'Core 0 p95 was 41 % over the last 24 hours (24 h snapshot); limit for planning is 70 %.' };

function row(over = {}) {
  return {
    id: 1,
    name: 'Germany',
    state: 'ok',
    version: '1.1.0',
    error: null,
    snapshot: { now: NOW, data_age_s: 5, events_24h: {}, events_open: [] },
    verdict: OK_VERDICT,
    ...over,
  };
}

test('hostHealth: a healthy host is OK and says why with the room finding', () => {
  const h = hostHealth(row(), [CPU_OK, ROOM_OK]);
  assert.equal(h.status, 'ok');
  assert.equal(h.label, 'OK');
  assert.equal(h.reason, ROOM_OK.text);
  assert.deepEqual(h.items, []);
});

test('hostHealth: OK without a room finding falls back to the first finding', () => {
  const h = hostHealth(row(), [CPU_OK]);
  assert.equal(h.status, 'ok');
  assert.equal(h.reason, CPU_OK.text);
});

test('hostHealth: unreachable and no sudo are problems with the error as the reason', () => {
  const u = hostHealth(row({ state: 'unreachable', snapshot: null, verdict: null }), []);
  assert.equal(u.status, 'problem');
  assert.equal(u.label, 'Problem');
  assert.equal(u.reason, 'The host did not answer the SSH query.');
  assert.deepEqual(u.items, [{ level: 'problem', what: 'The host did not answer the SSH query.', since: null }]);
  const n = hostHealth(row({ state: 'no_sudo', snapshot: null, verdict: null, error: 'SSH user ubuntu has no passwordless sudo' }), []);
  assert.equal(n.status, 'problem');
  assert.equal(n.reason, 'SSH user ubuntu has no passwordless sudo');
});

test('hostHealth: not installed and no data yet are No data', () => {
  const a = hostHealth(row({ state: 'not_installed', snapshot: null, verdict: null }), []);
  assert.equal(a.status, 'nodata');
  assert.equal(a.label, 'No data');
  assert.match(a.reason, /not installed/);
  assert.match(a.reason, /Apply to host/);
  const b = hostHealth(row({ state: 'no_data', snapshot: null, verdict: null }), []);
  assert.equal(b.status, 'nodata');
  assert.match(b.reason, /not written any data yet/);
});

test('hostHealth: no data under load (verdict unknown) is No data', () => {
  const h = hostHealth(row({ verdict: { status: 'unknown', slots: null, reason: 'no data under load', ref_load: null, ref_source: null } }), [CPU_OK]);
  assert.equal(h.status, 'nodata');
  assert.match(h.reason, /No data under load yet/);
});

test('hostHealth: stale data under 5 min is Watch, since the last sample, with the data finding as reason', () => {
  const text = 'Collector data is 3m old - the collector or the host is down.';
  const h = hostHealth(row({
    state: 'stale',
    snapshot: { now: NOW, data_age_s: 200, events_open: [{ id: 1, ts: NOW - 9999, kind: 'disk_low', severity: 'crit', state: 'open', message: 'old' }] },
    verdict: { status: 'unknown', slots: null, reason: 'collector data is 3 min old' },
  }), [{ level: 'problem', area: 'data', text }]);
  assert.equal(h.status, 'watch');
  assert.equal(h.reason, text);
  // the open events of a stale host describe the past: not reported
  assert.deepEqual(h.items, [{ level: 'watch', what: text, since: NOW - 200 }]);
});

test('hostHealth: stale up to 5 minutes is Watch, older is a Problem in the open problems', () => {
  const stale = (age) => row({
    state: 'stale',
    snapshot: { now: NOW, data_age_s: age, events_open: [] },
    verdict: { status: 'unknown', slots: null, reason: 'collector data is old' },
  });
  const w = hostHealth(stale(200), [{ level: 'problem', area: 'data', text: 'Collector data is 3m old - the collector or the host is down.' }]);
  assert.equal(w.status, 'watch');
  assert.deepEqual(w.items.map((i) => i.level), ['watch']);
  const p = hostHealth(stale(400), [{ level: 'problem', area: 'data', text: 'Collector data is 6m old - the collector or the host is down.' }]);
  assert.equal(p.status, 'problem');
  assert.equal(p.reason, 'Collector data is 6 min old - the collector or the host is down.');
  assert.deepEqual(p.items, [{ level: 'problem', what: p.reason, since: NOW - 400 }]);
  // without data_age_s the age is unknown: Watch
  assert.equal(hostHealth(row({ state: 'stale', snapshot: { now: NOW } }), []).status, 'watch');
});

test('hostHealth: an open frames_late (warn event) is a Problem, listed once with its start time', () => {
  const h = hostHealth(row({
    snapshot: {
      now: NOW,
      data_age_s: 5,
      events_24h: { frames_late: 1 },
      events_open: [{ id: 5, ts: NOW - 120, kind: 'frames_late', scope: 'instance', port: 27960, severity: 'warn', state: 'open', message: 'port 27960: 4% late' }],
    },
  }), [ROOM_OK, { level: 'problem', area: 'frames', text: '12 late frames on :27960 in the last 24 hours (24 h snapshot). A late frame means players see a hitch.' }]);
  assert.equal(h.status, 'problem');
  assert.deepEqual(h.items, [{ level: 'problem', what: 'Late frames: port 27960: 4% late', since: NOW - 120 }]);
});

test('hostHealth: an open critical event is a problem with its start time', () => {
  const h = hostHealth(row({
    snapshot: {
      now: NOW,
      data_age_s: 5,
      events_24h: { disk_low: 1 },
      events_open: [{ id: 7, ts: NOW - 600, kind: 'disk_low', scope: 'host', port: null, severity: 'crit', state: 'open', message: 'disk 93% used' }],
    },
  }), [ROOM_OK, { level: 'problem', area: 'disk', text: 'Disk / is 93 % full.' }]);
  assert.equal(h.status, 'problem');
  assert.equal(h.reason, 'Disk low: disk 93% used');
  // the disk finding says the same as the open event: listed once
  assert.deepEqual(h.items.filter((i) => i.level === 'problem'), [
    { level: 'problem', what: 'Disk low: disk 93% used', since: NOW - 600 },
  ]);
});

test('hostHealth: an open warning event makes Watch, instance events are ignored', () => {
  const h = hostHealth(row({
    snapshot: {
      now: NOW,
      data_age_s: 5,
      events_24h: { steal_high: 1, instance_new: 3 },
      events_open: [
        { id: 3, ts: NOW - 60, kind: 'instance_new', severity: 'info', state: 'open', message: 'port 27961' },
        { id: 4, ts: NOW - 300, kind: 'steal_high', severity: 'warn', state: 'open', message: 'steal 12%' },
      ],
    },
  }), [ROOM_OK]);
  assert.equal(h.status, 'watch');
  assert.equal(h.reason, 'Steal high: steal 12%');
  assert.equal(h.items[0].since, NOW - 300);
});

test('hostHealth: verdict overloaded by busy events is a problem in plain words', () => {
  const h = hostHealth(row({
    verdict: { status: 'overloaded', slots: 1, reason: 'frames_late 2 with players in the last 24 h', ref_load: 20, ref_source: 'host' },
  }), [ROOM_OK]);
  assert.equal(h.status, 'problem');
  assert.equal(h.reason, '2 late-frame events with players in the last 24 hours.');
  const s = hostHealth(row({
    verdict: { status: 'overloaded', slots: 1, reason: 'core_saturated 1 with players in the last 24 h', ref_load: 20, ref_source: 'host' },
  }), []);
  assert.equal(s.reason, '1 core saturation event with players in the last 24 hours.');
});

test('hostHealth: verdict overloaded by steal uses the steal finding, not a second line', () => {
  const steal = { level: 'problem', area: 'steal', text: 'The provider took 18 % of CPU time (steal, p95 over the last 7 days (snapshot)); above 5 % means a noisy neighbour.' };
  const h = hostHealth(row({
    verdict: { status: 'overloaded', slots: 1, reason: 'steal p95 18% > 15%', ref_load: 20, ref_source: 'host' },
  }), [steal]);
  assert.equal(h.status, 'problem');
  assert.deepEqual(h.items, [{ level: 'problem', what: steal.text, since: null }]);
});

test('hostHealth: tight verdict and warning findings are Watch', () => {
  const room = { level: 'warning', area: 'room', text: 'No room for more instances: RAM is the limit.' };
  const h = hostHealth(row({
    verdict: { status: 'tight', slots: 0, reason: '0 slots, memory: ...', ref_load: 20, ref_source: 'host' },
  }), [CPU_OK, room]);
  assert.equal(h.status, 'watch');
  assert.equal(h.label, 'Watch');
  assert.equal(h.reason, room.text);
  // a tight verdict without a matching finding still shows, in its own words
  const t = hostHealth(row({ verdict: { status: 'tight', slots: 0, reason: '0 slots, core 0: x' } }), []);
  assert.equal(t.status, 'watch');
  assert.equal(t.reason, 'Capacity is tight: 0 slots, core 0: x.');
});

test('hostHealth: warnings in the last 24 h are Watch even when nothing is open', () => {
  const h = hostHealth(row({
    snapshot: { now: NOW, data_age_s: 5, events_24h: { mem_low: 2, instance_gone: 1 }, events_open: [] },
  }), [ROOM_OK]);
  assert.equal(h.status, 'watch');
  assert.equal(h.reason, '2 events in the last 24 hours (Memory low 2).');
});

test('hostHealth: an outdated collector with good data is Watch and says Apply to host', () => {
  const h = hostHealth(row({ state: 'outdated', version: '1.0.1' }), [ROOM_OK]);
  assert.equal(h.status, 'watch');
  assert.equal(h.reason, 'Collector 1.0.1 is outdated: use Apply to host.');
});

test('hostHealth: a problem finding wins over a warning; items list problems first', () => {
  const h = hostHealth(row(), [
    { level: 'warning', area: 'cpu', text: 'Core 1 p95 was 80 %.' },
    { level: 'problem', area: 'frames', text: '3 late frames on :27960.' },
  ]);
  assert.equal(h.status, 'problem');
  assert.equal(h.reason, '3 late frames on :27960.');
  assert.deepEqual(h.items.map((i) => i.level), ['problem', 'watch']);
});

test('hostHealth: an older collector without events_open does not throw', () => {
  const r = row();
  delete r.snapshot.events_open;
  assert.equal(hostHealth(r, [ROOM_OK]).status, 'ok');
  assert.equal(openEvents(r.snapshot), null);
  assert.equal(hostHealth(null, []).status, 'nodata');
});

test('openEvents: open rows only, sorted oldest first, null without the field', () => {
  const s = { events_open: [{ id: 2, ts: 20, state: 'open' }, { id: 1, ts: 10, state: 'open' }, { id: 3, ts: 5, state: 'closed' }] };
  assert.deepEqual(openEvents(s).map((e) => e.id), [1, 2]);
  assert.equal(openEvents({}), null);
  assert.equal(openEvents(null), null);
});

test('sortByHealth: problems first, then watch, no data, ok; by name inside', () => {
  const list = [
    { row: { name: 'b' }, health: { status: 'ok' } },
    { row: { name: 'z' }, health: { status: 'problem' } },
    { row: { name: 'a' }, health: { status: 'ok' } },
    { row: { name: 'm' }, health: { status: 'nodata' } },
    { row: { name: 'C' }, health: { status: 'watch' } },
    { row: { name: 'b2' }, health: { status: 'problem' } },
  ];
  assert.deepEqual(sortByHealth(list).map((e) => e.row.name), ['b2', 'z', 'C', 'm', 'a', 'b']);
  assert.equal(list[0].row.name, 'b'); // input untouched
});

test('healthCounts: one count per status', () => {
  const c = healthCounts([{ status: 'ok' }, { status: 'ok' }, { status: 'problem' }, { status: 'nodata' }]);
  assert.deepEqual(c, { problem: 1, watch: 0, nodata: 1, ok: 2 });
});

test('hostIdFromSearch: positive integer host id from ?host=, else null', () => {
  assert.equal(hostIdFromSearch('?host=3'), 3);
  assert.equal(hostIdFromSearch('?x=1&host=12'), 12);
  assert.equal(hostIdFromSearch('?host=abc'), null);
  assert.equal(hostIdFromSearch('?host=-1'), null);
  assert.equal(hostIdFromSearch('?host=1.5'), null);
  assert.equal(hostIdFromSearch(''), null);
  assert.equal(hostIdFromSearch(undefined), null);
});

const GIB = 1073741824;
const HETZNER = {
  cpu_model: 'AMD EPYC-Rome Processor',
  vcpus: 2,
  threads_per_core: 1,
  sockets: 1,
  mhz: 2445.406,
  cache: '512 KB',
  hypervisor: true,
  sys_vendor: 'Hetzner',
  product_name: 'vServer',
  provider: 'Hetzner',
  mem_total: 3.8 * GIB,
  swap_total: 0,
  disk_total: 38 * GIB,
  disk_rotational: false,
  kernel: '6.8.0-45-generic',
  os: 'Ubuntu 24.04.1 LTS',
  boot_time: NOW - 86400,
};

test('hardwareLine: model, vCPU, RAM, disk type, provider and product', () => {
  assert.equal(hardwareLine(HETZNER), 'AMD EPYC-Rome Processor, 2 vCPU, 3.8 GB RAM, 38 GB SSD, Hetzner (vServer)');
});

test('hardwareLine: bare metal says CPU threads, HDD, missing parts are left out', () => {
  assert.equal(
    hardwareLine({ cpu_model: '  Intel(R)  Xeon(R) E-2276G ', vcpus: 12, hypervisor: false, disk_total: 512 * GIB, disk_rotational: true }),
    'Intel(R) Xeon(R) E-2276G, 12 CPU threads, 512 GB HDD',
  );
  assert.equal(hardwareLine({ vcpus: 1, provider: 'Amazon EC2', product_name: 'Amazon EC2' }), '1 vCPU, Amazon EC2');
  assert.equal(hardwareLine({ disk_total: 10 * GIB }), '10 GB disk');
  assert.equal(hardwareLine({}), null);
  assert.equal(hardwareLine(null), null);
});

test('hardwareDetails: label/value pairs, only known values', () => {
  const d = hardwareDetails(HETZNER);
  const map = Object.fromEntries(d);
  assert.equal(map.CPU, 'AMD EPYC-Rome Processor');
  assert.equal(map.Cores, '2 vCPU (1 thread per core, 1 socket), 2445 MHz, cache 512 KB');
  assert.equal(map.Memory, '3.8 GB RAM, no swap');
  assert.equal(map.Disk, '38 GB SSD');
  assert.equal(map.Provider, 'Hetzner (vServer, virtual machine)');
  assert.equal(map.System, 'Ubuntu 24.04.1 LTS, kernel 6.8.0-45-generic');
  assert.ok(map.Booted.length > 0);
  assert.deepEqual(hardwareDetails({ vcpus: 4, threads_per_core: 2 }), [['Cores', '4 vCPU (2 threads per core)']]);
  assert.deepEqual(hardwareDetails(null), []);
});

test('kindLabel: known kinds in words, unknown kinds as they are', () => {
  assert.equal(kindLabel('disk_low'), 'Disk low');
  assert.equal(kindLabel('oom_kill'), 'OOM kill');
  assert.equal(kindLabel('new_kind'), 'new_kind');
});
