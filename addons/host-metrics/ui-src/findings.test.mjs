import test from 'node:test';
import assert from 'node:assert/strict';
import { findings, P95_GLOSS } from './findings.js';

const GB = 1073741824;
const MB = 1048576;

function snap(over = {}) {
  return {
    now: 100000,
    data_age_s: 10,
    host: { ts: 99990, mem_total: 4 * GB, mem_avail: 3 * GB, disk_used: 38 * GB, disk_total: 100 * GB },
    mem_total: 4 * GB,
    mem_avail_now: 3 * GB,
    steal_p95: 1.2,
    core_p95_24h: { '-1': 30, 0: 41.2, 1: 12 },
    insts: [{ port: 27960, core: 0, busy_p95: 20, rss_max: 100 * MB, late_24h: 0, frames_24h: 1000 }],
    events_24h: {},
    events_24h_busy: { frames_late: 0, core_saturated: 0 },
    ...over,
  };
}
const by = (list, area) => list.filter((f) => f.area === area);
const hhmm = (ts) => {
  const d = new Date(ts * 1000);
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
};

test('null, empty and garbage input never throw', () => {
  for (const arg of [undefined, {}, { snapshot: null }, { snapshot: {} }, { snapshot: 5 }]) {
    const out = findings(arg);
    assert.ok(Array.isArray(out));
  }
  assert.deepEqual(findings({ snapshot: null }), [
    { level: 'info', area: 'data', text: 'No data collected on this host yet.' },
  ]);
  assert.equal(findings({ snapshot: {} })[0].area, 'data');
});

test('stale host gets only the data finding', () => {
  const out = findings({ snapshot: snap({ data_age_s: 360 }) });
  assert.deepEqual(out, [{
    level: 'problem',
    area: 'data',
    text: 'Collector data is 6m old - the collector or the host is down.',
  }]);
});

test('fresh host has no data finding', () => {
  assert.equal(by(findings({ snapshot: snap() }), 'data').length, 0);
});

test('cpu without a series uses the 24 h snapshot and says so', () => {
  const out = by(findings({ snapshot: snap() }), 'cpu');
  assert.equal(out.length, 2); // real cores only, the all-cores row is left out
  assert.equal(out[0].level, 'ok');
  assert.match(out[0].text, /^Core 0 p95 was 41 % over the last 24 hours \(24 h snapshot\); limit for planning is 70 %\.$/);
  assert.match(out[1].text, /^Core 1 p95 was 12 %/);
});

test('cpu with a series states the stay-below sentence for the chosen range', () => {
  const series = {
    res: 'raw',
    cores: [
      { ts: 1, core: -1, busy: 20, busy_max: 30 },
      { ts: 1, core: 0, busy: 30, busy_max: 41 },
      { ts: 2, core: 0, busy: 35, busy_max: 40 },
    ],
    insts: {},
  };
  const out = by(findings({ snapshot: snap(), series, events: [], range: '6h' }), 'cpu');
  assert.equal(out.length, 1);
  assert.equal(out[0].text, 'Core 0 stayed below 41 % (p95 35 %) over the last 6 hours; limit for planning is 70 %.');
});

test('cpu p95 above the planning limit warns; the limit comes from settings', () => {
  const s = snap({ core_p95_24h: { 0: 75 } });
  const out = by(findings({ snapshot: s }), 'cpu');
  assert.equal(out[0].level, 'warning');
  assert.match(out[0].text, /above the 70 % planning limit/);
  const custom = by(findings({ snapshot: s, settings: { verdict_target_pct: '80' } }), 'cpu');
  assert.equal(custom[0].level, 'ok');
  assert.match(custom[0].text, /limit for planning is 80 %/);
});

test('saturation events give minutes and "during matches" only with players in the window', () => {
  const events = [{ kind: 'core_saturated', scope: 'core', ts: 1000, closed_ts: 1000 + 7 * 60, state: 'closed', message: 'core 1 busy 99% (limit 95%)' }];
  const series = {
    cores: [{ ts: 1000, core: 1, busy: 99, busy_max: 100 }],
    insts: { 27960: [{ ts: 1100, players: 6 }] },
    now: 5000,
  };
  const withMatch = by(findings({ snapshot: snap(), series, events, range: '1h' }), 'cpu');
  assert.deepEqual(withMatch[0], {
    level: 'problem', area: 'cpu', text: 'Core 1 was above 95 % for 7 minutes, during matches.',
  });
  const noPlayers = { ...series, insts: { 27960: [{ ts: 1100, players: 0 }] } };
  const out = by(findings({ snapshot: snap(), series: noPlayers, events, range: '1h' }), 'cpu');
  assert.equal(out[0].text, 'Core 1 was above 95 % for 7 minutes.');
});

test('an open saturation event counts up to now', () => {
  const events = [{ kind: 'core_saturated', ts: 1000, closed_ts: null, state: 'open', message: 'core 0 busy 97% (limit 95%)' }];
  const series = { cores: [{ ts: 1, core: 0, busy: 97 }], insts: {}, now: 1000 + 180 };
  const out = by(findings({ snapshot: snap(), series, events, range: '1h' }), 'cpu');
  assert.match(out[0].text, /for 3 minutes\.$/);
});

test('snapshot without per-core numbers falls back to the event count', () => {
  const s = snap({ core_p95_24h: undefined, events_24h: { core_saturated: 2 } });
  const out = by(findings({ snapshot: s }), 'cpu');
  assert.equal(out.length, 1);
  assert.match(out[0].text, /^2 core saturation events in the last 24 hours/);
  assert.deepEqual(by(findings({ snapshot: snap({ core_p95_24h: undefined }) }), 'cpu'), []);
});

test('room: slots, no room, fleet reference, nothing at all', () => {
  const ok = findings({ snapshot: snap(), verdict: { status: 'ok', slots: 2, ref_load: 20.4, ref_source: 'host' } });
  assert.deepEqual(by(ok, 'room')[0], {
    level: 'ok', area: 'room',
    text: 'Room for 2 more instances (reference: one instance uses 20 % of a core in a match).',
  });
  const one = findings({ snapshot: snap(), verdict: { status: 'ok', slots: 1, ref_load: 20, ref_source: 'host' } });
  assert.match(by(one, 'room')[0].text, /^Room for 1 more instance \(/);
  const none = findings({ snapshot: snap(), verdict: { status: 'tight', slots: 0, ref_load: 50, ref_source: 'host' } });
  assert.equal(by(none, 'room')[0].level, 'warning');
  assert.equal(by(none, 'room')[0].text, 'No room for more instances.'); // reason unknown: no resource is blamed
  const cpu = findings({ snapshot: snap(), verdict: { status: 'tight', slots: 0, ref_load: 50, ref_source: 'host', reason: '0 slots, core 0: 1 x 50% + 30% other of 70%' } });
  assert.equal(by(cpu, 'room')[0].text, 'No room for more instances (CPU is the limit; reference: one instance uses 50 % of a core in a match).');
  const ram = findings({ snapshot: snap(), verdict: { status: 'tight', slots: 0, ref_load: 50, ref_source: 'host', reason: '0 slots, memory: 500 MB available - 20% reserve, largest instance 100 MB' } });
  assert.equal(by(ram, 'room')[0].text, 'No room for more instances: RAM is the limit.');
  assert.doesNotMatch(by(ram, 'room')[0].text, /core/);
  const over = findings({ snapshot: snap(), verdict: { status: 'overloaded', slots: 0, ref_load: 50, ref_source: 'host' } });
  assert.equal(by(over, 'room')[0].level, 'problem');

  const fleet = findings({ snapshot: snap({ insts: [] }), verdict: { status: 'ok', slots: 3, ref_load: 25, ref_source: 'fleet' } });
  assert.equal(by(fleet, 'room')[0].text,
    'No match played on this host yet, so room is estimated from other hosts. Room for 3 more instances (reference: one instance uses 25 % of a core in a match).');
  assert.equal(by(fleet, 'room')[0].level, 'ok');
});

test('a host with no match yet and no fleet data says room cannot be estimated', () => {
  const s = snap({ insts: [{ port: 27960, core: 0, busy_p95: null, late_24h: 0, frames_24h: 100 }] });
  const out = findings({ snapshot: s, verdict: { status: 'unknown', slots: null, ref_load: null, ref_source: null } });
  assert.equal(by(out, 'room')[0].level, 'info');
  assert.match(by(out, 'room')[0].text, /No match played on this host yet/);
  assert.deepEqual(by(findings({ snapshot: s }), 'room'), []); // no verdict, no statement
});

test('frames: none late', () => {
  const out = by(findings({ snapshot: snap() }), 'frames');
  assert.deepEqual(out, [{ level: 'ok', area: 'frames', text: 'No late server frames in the last 24 hours (24 h snapshot).' }]);
  const series = { cores: [], insts: { 27960: [{ ts: 1, frames: 500, late: 0, max_ms: 60 }] } };
  const s = by(findings({ snapshot: snap(), series, range: '7d' }), 'frames');
  assert.equal(s[0].text, 'No late server frames in the last 7 days.');
});

test('frames: late with worst gap, time and players; keys are strings', () => {
  const ts = 1700000000;
  const series = {
    cores: [],
    insts: {
      27961: [
        { ts: ts - 60, frames: 500, late: 2, max_ms: 80, players: 4 },
        { ts, frames: 500, late: 1, max_ms: 142.6, players: 8 },
      ],
      27962: [{ ts, frames: 500, late: 0, max_ms: 40, players: 0 }],
    },
  };
  const out = by(findings({ snapshot: snap(), series, range: '1h' }), 'frames');
  assert.equal(out.length, 1);
  assert.equal(out[0].level, 'warning');
  assert.equal(out[0].text,
    `3 late frames on :27961, worst gap 143 ms at ${hhmm(ts)} (players: 8). A late frame means players see a hitch.`);
});

test('frames: players clause is dropped when the row has none; open event escalates', () => {
  const series = { cores: [], insts: { 27960: [{ ts: 1700000000, frames: 100, late: 1, max_ms: 120 }] } };
  const events = [{ kind: 'frames_late', port: 27960, state: 'open' }];
  const out = by(findings({ snapshot: snap(), series, events, range: '1h' }), 'frames');
  assert.equal(out[0].level, 'problem');
  assert.doesNotMatch(out[0].text, /players:/);
  assert.match(out[0].text, /^1 late frame on :27960, worst gap 120 ms at \d\d:\d\d\./);
});

test('frames: snapshot only gives the 24 h count without gap details', () => {
  const s = snap({ insts: [{ port: 27960, late_24h: 50, frames_24h: 1000 }] }); // 5 %, above 1 %
  const out = by(findings({ snapshot: s }), 'frames');
  assert.equal(out[0].level, 'warning');
  assert.equal(out[0].text, '50 late frames on :27960 in the last 24 hours (24 h snapshot). A late frame means players see a hitch.');
});

test('frames: a few late frames among millions are an info line, not a warning', () => {
  const s = snap({ insts: [{ port: 27960, late_24h: 3, frames_24h: 3_400_000 }] });
  const out = by(findings({ snapshot: s }), 'frames');
  assert.deepEqual(out, [{
    level: 'info',
    area: 'frames',
    text: '3 late frames out of 3.4 million on :27960 in the last 24 hours (24 h snapshot) - normal.',
  }]);
});

test('frames: the frames_late_pct setting moves the line; an open event or a big gap still warns', () => {
  const s = snap({ insts: [{ port: 27960, late_24h: 20, frames_24h: 1000 }] }); // 2 %
  assert.equal(by(findings({ snapshot: s }), 'frames')[0].level, 'warning');
  assert.equal(by(findings({ snapshot: s, settings: { frames_late_pct: '5' } }), 'frames')[0].level, 'info');
  const events = [{ kind: 'frames_late', port: 27960, state: 'open' }];
  assert.equal(by(findings({ snapshot: s, events, settings: { frames_late_pct: '5' } }), 'frames')[0].level, 'problem');
  const series = { cores: [], insts: { 27960: [{ ts: 1700000000, frames: 100000, late: 1, max_ms: 180 }] } };
  const big = by(findings({ snapshot: snap(), series, range: '1h' }), 'frames')[0];
  assert.equal(big.level, 'warning'); // 0.001 % but the worst gap is above frame_gap_ms (100)
  const small = by(findings({ snapshot: snap(), series: { cores: [], insts: { 27960: [{ ts: 1, frames: 100000, late: 1, max_ms: 60 }] } }, range: '1h' }), 'frames')[0];
  assert.equal(small.level, 'info');
  assert.match(small.text, /^1 late frame out of 100 thousand on :27960 in the last hour - normal\.$/);
  assert.equal(by(findings({ snapshot: snap(), series, settings: { frame_gap_ms: '200' }, range: '1h' }), 'frames')[0].level, 'info');
});

test('steal sentence has no nested parentheses; p95 gloss is exported', () => {
  const t = by(findings({ snapshot: snap() }), 'steal')[0].text;
  assert.doesNotMatch(t, /\([^)]*\(/);
  assert.equal(t, 'The provider took 1.2 % of CPU time (steal), p95 over the last 7 days; above 5 % means a noisy neighbour.');
  assert.match(P95_GLOSS, /95 %/);
});

test('frames: no instance or no frames is "no statistics", not "no late frames"', () => {
  for (const insts of [[], [{ port: 27960, late_24h: 0, frames_24h: 0 }], undefined]) {
    const out = by(findings({ snapshot: snap({ insts }) }), 'frames');
    assert.equal(out.length, 1);
    assert.equal(out[0].level, 'info');
    assert.match(out[0].text, /^No frame statistics yet/);
  }
});

test('steal: snapshot 7 d value, series value, levels', () => {
  const a = by(findings({ snapshot: snap({ steal_p95: 1.234 }) }), 'steal')[0];
  assert.equal(a.level, 'ok');
  assert.equal(a.text, 'The provider took 1.2 % of CPU time (steal), p95 over the last 7 days; above 5 % means a noisy neighbour.');
  assert.equal(by(findings({ snapshot: snap({ steal_p95: 7 }) }), 'steal')[0].level, 'warning');
  assert.equal(by(findings({ snapshot: snap({ steal_p95: 20 }) }), 'steal')[0].level, 'problem');
  const series = { cores: [{ ts: 1, core: -1, steal: 12 }, { ts: 2, core: -1, steal: 14 }], insts: {} };
  const s = by(findings({ snapshot: snap({ steal_p95: 1 }), series, range: '1h' }), 'steal')[0];
  assert.match(s.text, /took 14 % of CPU time \(steal\), p95 over the last hour/);
  assert.equal(s.level, 'warning');
  const custom = by(findings({ snapshot: snap({ steal_p95: 7 }), settings: { steal_tight_pct: '8' } }), 'steal')[0];
  assert.equal(custom.level, 'ok');
  assert.match(custom.text, /above 8 %/);
  assert.deepEqual(by(findings({ snapshot: snap({ steal_p95: null }) }), 'steal'), []);
});

test('memory: free, spare instances, below reserve, open event, no data', () => {
  const ok = by(findings({ snapshot: snap() }), 'memory')[0];
  assert.equal(ok.text, 'RAM: 3.0 GB free of 4.0 GB, enough for about 22 more instances.'); // floor((3 - 0.8) GB / 100 MB) = 22
  const noRss = by(findings({ snapshot: snap({ insts: [] }) }), 'memory')[0];
  assert.equal(noRss.text, 'RAM: 3.0 GB free of 4.0 GB.');
  const low = by(findings({ snapshot: snap({ mem_avail_now: 0.5 * GB }) }), 'memory')[0];
  assert.equal(low.level, 'warning');
  assert.equal(low.text, 'RAM: 0.5 GB free of 4.0 GB, below the 20 % reserve.');
  const ev = by(findings({ snapshot: snap(), events: [{ kind: 'mem_low', state: 'open' }] }), 'memory')[0];
  assert.equal(ev.level, 'problem');
  assert.deepEqual(by(findings({ snapshot: snap({ mem_total: null }) }), 'memory'), []);
});

test('disk: percent and free space, over the limit, open event, no data', () => {
  const ok = by(findings({ snapshot: snap() }), 'disk')[0];
  assert.deepEqual(ok, { level: 'ok', area: 'disk', text: 'Disk / is 38 % full (62.0 GB free).' });
  const full = snap({ host: { disk_used: 92 * GB, disk_total: 100 * GB } });
  assert.deepEqual(by(findings({ snapshot: full }), 'disk')[0], { level: 'problem', area: 'disk', text: 'Disk / is 92 % full.' });
  const custom = by(findings({ snapshot: full, settings: { disk_low_pct: '95' } }), 'disk')[0];
  assert.equal(custom.level, 'ok');
  assert.equal(by(findings({ snapshot: snap(), events: [{ kind: 'disk_low', state: 'open' }] }), 'disk')[0].level, 'problem');
  assert.deepEqual(by(findings({ snapshot: snap({ host: null }) }), 'disk'), []);
});

test('output order follows the areas and every entry is well formed', () => {
  const out = findings({
    snapshot: snap(),
    verdict: { status: 'ok', slots: 2, ref_load: 20, ref_source: 'host' },
  });
  const areas = out.map((f) => f.area);
  assert.deepEqual(areas, ['cpu', 'cpu', 'room', 'frames', 'steal', 'memory', 'disk']);
  for (const f of out) {
    assert.ok(['ok', 'info', 'warning', 'problem'].includes(f.level));
    assert.equal(typeof f.text, 'string');
    assert.doesNotMatch(f.text, /NaN|undefined|null|Infinity/);
  }
});

test('a snapshot with almost nothing in it yields no invented numbers', () => {
  const out = findings({ snapshot: { data_age_s: 5 } });
  for (const f of out) assert.doesNotMatch(f.text, /NaN|undefined|null|Infinity/);
  assert.deepEqual(out.map((f) => f.area), ['frames']);
});

test('a saturation event on a core without a p95 row is still reported, in core order', () => {
  const events = [{ kind: 'core_saturated', ts: 1000, closed_ts: 1000 + 300, state: 'closed', message: 'core 5 busy 99% (limit 95%)' }];
  const out = by(findings({ snapshot: snap(), events }), 'cpu'); // snapshot has p95 rows for cores 0 and 1 only
  assert.deepEqual(out.map((f) => f.text.slice(0, 6)), ['Core 0', 'Core 1', 'Core 5']);
  assert.deepEqual(out[2], { level: 'problem', area: 'cpu', text: 'Core 5 was above 95 % for 5 minutes.' });
  // no per-core data at all: the event is still there
  const bare = by(findings({ snapshot: snap({ core_p95_24h: undefined }), events }), 'cpu');
  assert.equal(bare.length, 1);
  assert.match(bare[0].text, /^Core 5 was above/);
});

test('saturation duration: under a minute and unknown are never rounded up to 1 minute', () => {
  const ev = (over) => [{ kind: 'core_saturated', ts: 1000, state: 'closed', message: 'core 0 busy 99% (limit 95%)', ...over }];
  const short = by(findings({ snapshot: snap(), events: ev({ closed_ts: 1020 }) }), 'cpu')[0];
  assert.equal(short.text, 'Core 0 was above 95 % for less than a minute.');
  const open = by(findings({ snapshot: { ...snap(), now: undefined }, events: ev({ closed_ts: null, state: 'open' }) }), 'cpu')[0];
  assert.equal(open.text, 'Core 0 was above 95 %.');
  assert.doesNotMatch(open.text + short.text, /1 minute/);
});
