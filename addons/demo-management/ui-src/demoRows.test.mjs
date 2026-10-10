// Plain-node checks for demoRows.js (no browser, no QLSM runtime):
//   node --test ui-src/demoRows.test.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import {
    buildRows, filterRows, sortRows, facets, dateRange, playersLabel, packingInUse,
    formatDuration, formatAgo,
} from './demoRows.js';

const local = (y, m, d, h = 0, mi = 0) => new Date(y, m - 1, d, h, mi).getTime() / 1000;
const NOW = local(2026, 10, 3, 15, 0);

const OLD_MATCH = '20260920T180000Z';
const NEW_MATCH = '20261003T100000Z';
const demos = [
    // Week-old match whose pack was rebuilt a minute ago: newest mtime of all.
    { name: 'old_pack.qlmatch', size: 900, mtime: NOW - 60, kind: 'pack', match_id: OLD_MATCH },
    { name: `${OLD_MATCH}_bloodrun_p0_a_1_1.dm_91`, size: 100, mtime: local(2026, 9, 20, 21), kind: 'pov', match_id: OLD_MATCH },
    { name: `${NEW_MATCH}_aerowalk_p0_b_1_1.dm_91`, size: 50, mtime: local(2026, 10, 3, 13), kind: 'pov', match_id: NEW_MATCH },
    { name: `${NEW_MATCH}_aerowalk_p1_c_1_1.dm_91`, size: 60, mtime: local(2026, 10, 3, 13), kind: 'pov', match_id: NEW_MATCH },
    { name: '20261002-120000_slot00_x.dm_91', size: 10, mtime: local(2026, 10, 2, 12), kind: 'pov' },
];
const matches = [
    {
        group_id: OLD_MATCH, label: 'bloodrun', member_names: [demos[0].name, demos[1].name],
        info: { match_id: OLD_MATCH, started_at: '2026-09-20T18:00:00Z', map: 'bloodrun', gametype: 'duel',
            players: [{ name: 'a', team: '0' }, { name: 'zorro', team: '0' }] },
    },
    {
        group_id: NEW_MATCH, label: 'aerowalk', member_names: [demos[2].name, demos[3].name],
        info: { match_id: NEW_MATCH, started_at: '2026-10-03T10:00:00Z', map: 'aerowalk', gametype: 'ca',
            players: [{ name: 'b', team: '1' }, { name: 'c', team: '2' }, { name: 'spec', team: '3' }] },
    },
];
const rows = buildRows(demos, matches);
const ids = (list) => list.map((r) => r.key);
const base = { text: '', datePreset: 'all', dateFrom: '', dateTo: '', map: '', gametype: '', kind: 'all' };

test('a rebuilt pack does not make an old match the newest row', () => {
    assert.deepEqual(ids(sortRows(rows, 'newest')), [
        `group-${NEW_MATCH}`, '20261002-120000_slot00_x.dm_91', `group-${OLD_MATCH}`,
    ]);
});

test('date presets filter on the match start, in local days', () => {
    assert.deepEqual(ids(filterRows(rows, { ...base, datePreset: 'today' }, NOW)), [`group-${NEW_MATCH}`]);
    assert.deepEqual(ids(filterRows(rows, { ...base, datePreset: 'yesterday' }, NOW)), ['20261002-120000_slot00_x.dm_91']);
    assert.equal(filterRows(rows, { ...base, datePreset: '7d' }, NOW).length, 2);
    assert.equal(filterRows(rows, { ...base, datePreset: '30d' }, NOW).length, 3);
    // The custom end date includes its whole day.
    const custom = { ...base, datePreset: 'custom', dateFrom: '2026-09-20', dateTo: '2026-09-20' };
    assert.deepEqual(ids(filterRows(rows, custom, NOW)), [`group-${OLD_MATCH}`]);
});

test('custom range with an open end', () => {
    const [from, to] = dateRange('custom', NOW, '2026-10-01', '');
    assert.equal(from, local(2026, 10, 1));
    assert.equal(to, null);
});

test('map, mode, kind and text filters', () => {
    assert.deepEqual(ids(filterRows(rows, { ...base, map: 'bloodrun' }, NOW)), [`group-${OLD_MATCH}`]);
    assert.deepEqual(ids(filterRows(rows, { ...base, gametype: 'ca' }, NOW)), [`group-${NEW_MATCH}`]);
    assert.deepEqual(ids(filterRows(rows, { ...base, kind: 'packed' }, NOW)), [`group-${OLD_MATCH}`]);
    assert.deepEqual(ids(filterRows(rows, { ...base, kind: 'unpacked' }, NOW)), [`group-${NEW_MATCH}`]);
    assert.deepEqual(ids(filterRows(rows, { ...base, kind: 'loose' }, NOW)), ['20261002-120000_slot00_x.dm_91']);
    // Players are searchable, not only file names.
    assert.deepEqual(ids(filterRows(rows, { ...base, text: 'ZORR' }, NOW)), [`group-${OLD_MATCH}`]);
    assert.deepEqual(ids(filterRows(rows, { ...base, text: 'aero c' }, NOW)), [`group-${NEW_MATCH}`]);
});

test('facets and labels', () => {
    assert.deepEqual(facets(rows).maps.map((m) => m.value).sort(), ['aerowalk', 'bloodrun']);
    assert.equal(playersLabel(matches[0].info), 'a vs zorro');
    assert.equal(playersLabel(matches[1].info), 'b vs c');
    assert.equal(packingInUse(rows), true);
    assert.equal(formatDuration(612000), '10:12');
    assert.equal(formatDuration(3723000), '1:02:03');
    assert.equal(formatAgo(NOW - 125, NOW), '2 min ago');
});
