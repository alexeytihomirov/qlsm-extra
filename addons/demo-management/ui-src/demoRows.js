// Pure row/filter/format logic for the Demos screen, kept out of the
// component so it can be exercised with plain `node` (`npm test`, see
// demoRows.test.mjs) without QLSM's runtime on the page.
//
// A "row" is what the table shows as one line: a match (a group of files the
// backend clustered, with its `info`) or a loose file. Every row carries a
// `when` - the match's start time from its match id when known, else the
// newest file's mtime. Sorting and date filtering key off `when`, never off
// a pack's mtime alone: a rebuild rewrites the pack, and a week-old match
// must not jump to the top of the list (or out of a date filter) because of
// it.

export const DATE_PRESETS = [
    { id: 'all', label: 'All' },
    { id: 'today', label: 'Today' },
    { id: 'yesterday', label: 'Yesterday' },
    { id: '7d', label: '7 days' },
    { id: '30d', label: '30 days' },
    { id: 'custom', label: 'Range' },
];

export const KIND_FILTERS = [
    { id: 'all', label: 'All rows' },
    { id: 'matches', label: 'Matches' },
    { id: 'packed', label: 'Packed' },
    { id: 'unpacked', label: 'Not packed' },
    { id: 'loose', label: 'Loose files' },
];

export const SORTS = [
    { id: 'newest', label: 'Newest first' },
    { id: 'oldest', label: 'Oldest first' },
    { id: 'largest', label: 'Largest first' },
    { id: 'map', label: 'Map A–Z' },
];

const DAY = 86400;

function isoToSeconds(iso) {
    if (!iso) return null;
    const ms = Date.parse(iso);
    return Number.isFinite(ms) ? ms / 1000 : null;
}

function kindOf(demo) {
    if (demo.kind) return demo.kind;
    const name = (demo.name || '').toLowerCase();
    if (name.endsWith('.replay.json.gz')) return 'replay';
    if (name.endsWith('.qlmatch')) return 'pack';
    if (name.endsWith('.dm_91')) return 'pov';
    return 'other';
}

function countKinds(files) {
    const kinds = { pov: 0, pack: 0, replay: 0, other: 0 };
    files.forEach((d) => {
        const kind = kindOf(d);
        kinds[kind in kinds ? kind : 'other'] += 1;
    });
    return kinds;
}

// Spectators (team "3") watched the match, they did not play it.
export function playingPlayers(info) {
    return (info?.players || []).filter((p) => p && p.name && p.team !== '3');
}

export function playersLabel(info, max = 4) {
    const players = playingPlayers(info);
    if (!players.length) return '';
    const red = players.filter((p) => p.team === '1').map((p) => p.name);
    const blue = players.filter((p) => p.team === '2').map((p) => p.name);
    const short = (names) => (names.length > max
        ? `${names.slice(0, max).join(', ')} +${names.length - max}`
        : names.join(', '));
    if (red.length && blue.length) return `${short(red)} vs ${short(blue)}`;
    const names = players.map((p) => p.name);
    if (names.length === 2) return `${names[0]} vs ${names[1]}`;
    return short(names);
}

/** Matches (groups) + loose files -> rows, unsorted, unfiltered. */
export function buildRows(demos, matches) {
    const demoByName = new Map(demos.map((d) => [d.name, d]));
    const grouped = new Set();
    const rows = [];

    matches.forEach((group) => {
        const members = (group.member_names || [])
            .map((name) => demoByName.get(name))
            .filter(Boolean);
        if (!members.length) return;
        members.forEach((d) => grouped.add(d.name));
        members.sort((a, b) => (b.mtime || 0) - (a.mtime || 0));
        const info = group.info || {};
        const newest = members[0].mtime || 0;
        rows.push({
            type: 'group',
            key: `group-${group.group_id}`,
            group,
            members,
            info,
            when: isoToSeconds(info.started_at) ?? newest,
            size: members.reduce((sum, d) => sum + (d.size || 0), 0),
            kinds: countKinds(members),
            haystack: [
                ...members.map((d) => d.name), info.map, info.gametype, info.match_id, group.label,
                ...playingPlayers(info).map((p) => p.name),
            ].filter(Boolean).join(' ').toLowerCase(),
        });
    });

    demos.forEach((demo) => {
        if (grouped.has(demo.name)) return;
        const info = {
            match_id: demo.match_id, map: demo.map, started_at: demo.started_at,
            players: demo.pov?.player ? [{ name: demo.pov.player, team: '' }] : [],
        };
        rows.push({
            type: 'demo',
            key: demo.name,
            demo,
            members: [demo],
            info,
            when: isoToSeconds(demo.started_at) ?? (demo.mtime || 0),
            size: demo.size || 0,
            kinds: countKinds([demo]),
            haystack: [demo.name, demo.map, demo.pov?.player].filter(Boolean).join(' ').toLowerCase(),
        });
    });
    return rows;
}

function startOfLocalDay(seconds) {
    const d = new Date(seconds * 1000);
    return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime() / 1000;
}

function localDateToSeconds(value) {
    // "YYYY-MM-DD" from <input type="date">, read as local midnight.
    if (!value) return null;
    const [y, m, d] = value.split('-').map(Number);
    if (!y || !m || !d) return null;
    return new Date(y, m - 1, d).getTime() / 1000;
}

/** [from, to) in epoch seconds for a preset; either end may be null. */
export function dateRange(preset, nowSeconds, customFrom, customTo) {
    const today = startOfLocalDay(nowSeconds);
    switch (preset) {
        case 'today': return [today, null];
        case 'yesterday': return [startOfLocalDay(today - DAY / 2), today];
        case '7d': return [startOfLocalDay(today - 6 * DAY + DAY / 2), null];
        case '30d': return [startOfLocalDay(today - 29 * DAY + DAY / 2), null];
        case 'custom': {
            const from = localDateToSeconds(customFrom);
            const to = localDateToSeconds(customTo);
            // The end date is inclusive of its whole day.
            return [from, to === null ? null : startOfLocalDay(to + DAY + DAY / 2)];
        }
        default: return [null, null];
    }
}

/** True when a pack exists anywhere in the listing, i.e. packing is in use
 *  on this instance - only then is a match without one worth flagging. */
export function packingInUse(rows) {
    return rows.some((r) => r.kinds.pack > 0);
}

export function filterRows(rows, filters, nowSeconds) {
    const terms = (filters.text || '').trim().toLowerCase().split(/\s+/).filter(Boolean);
    const [from, to] = dateRange(filters.datePreset, nowSeconds, filters.dateFrom, filters.dateTo);
    return rows.filter((row) => {
        if (from !== null && row.when < from) return false;
        if (to !== null && row.when >= to) return false;
        if (filters.map && (row.info.map || '') !== filters.map) return false;
        if (filters.gametype && (row.info.gametype || '') !== filters.gametype) return false;
        switch (filters.kind) {
            case 'matches': if (row.type !== 'group') return false; break;
            case 'packed': if (!row.kinds.pack) return false; break;
            case 'unpacked': if (row.kinds.pack || !row.kinds.pov || !row.info.match_id) return false; break;
            case 'loose': if (row.type !== 'demo') return false; break;
            default: break;
        }
        return terms.every((term) => row.haystack.includes(term));
    });
}

export function sortRows(rows, sort) {
    const sorted = [...rows];
    const byWhen = (a, b) => b.when - a.when;
    switch (sort) {
        case 'oldest': sorted.sort((a, b) => a.when - b.when); break;
        case 'largest': sorted.sort((a, b) => b.size - a.size || byWhen(a, b)); break;
        case 'map':
            sorted.sort((a, b) => (a.info.map || '￿').localeCompare(b.info.map || '￿') || byWhen(a, b));
            break;
        default: sorted.sort(byWhen);
    }
    return sorted;
}

/** Distinct values for the map / gametype dropdowns, most common first. */
export function facets(rows) {
    const count = (key) => {
        const seen = new Map();
        rows.forEach((r) => {
            const value = r.info[key];
            if (value) seen.set(value, (seen.get(value) || 0) + 1);
        });
        return [...seen.entries()]
            .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
            .map(([value, n]) => ({ value, count: n }));
    };
    return { maps: count('map'), gametypes: count('gametype') };
}

export function dayKey(seconds) {
    return startOfLocalDay(seconds);
}

// ---- formatting --------------------------------------------------------

export function formatBytes(bytes) {
    if (!Number.isFinite(bytes)) return '—';
    if (bytes < 1024) return `${bytes} B`;
    const units = ['KB', 'MB', 'GB', 'TB'];
    let value = bytes / 1024;
    let unitIndex = 0;
    while (value >= 1024 && unitIndex < units.length - 1) {
        value /= 1024;
        unitIndex += 1;
    }
    return `${value.toFixed(1)} ${units[unitIndex]}`;
}

export function formatDuration(ms) {
    if (!Number.isFinite(ms) || ms <= 0) return '';
    const total = Math.round(ms / 1000);
    const h = Math.floor(total / 3600);
    const m = Math.floor((total % 3600) / 60);
    const s = String(total % 60).padStart(2, '0');
    return h ? `${h}:${String(m).padStart(2, '0')}:${s}` : `${m}:${s}`;
}

export function formatTime(seconds) {
    if (!Number.isFinite(seconds) || seconds <= 0) return '—';
    return new Date(seconds * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

export function formatFull(seconds) {
    if (!Number.isFinite(seconds) || seconds <= 0) return '';
    const d = new Date(seconds * 1000);
    return `${d.toLocaleString()} (${d.toISOString().replace('.000', '')})`;
}

export function formatDayLabel(seconds, nowSeconds) {
    const day = startOfLocalDay(seconds);
    const today = startOfLocalDay(nowSeconds);
    if (day === today) return 'Today';
    if (day === startOfLocalDay(today - DAY / 2)) return 'Yesterday';
    const d = new Date(seconds * 1000);
    const sameYear = d.getFullYear() === new Date(nowSeconds * 1000).getFullYear();
    return d.toLocaleDateString([], {
        weekday: 'short', day: 'numeric', month: 'long', year: sameYear ? undefined : 'numeric',
    });
}

export function formatAgo(seconds, nowSeconds) {
    const diff = Math.max(0, Math.round(nowSeconds - seconds));
    if (diff < 10) return 'just now';
    if (diff < 60) return `${diff}s ago`;
    if (diff < 3600) return `${Math.floor(diff / 60)} min ago`;
    if (diff < DAY) return `${Math.floor(diff / 3600)} h ago`;
    return `${Math.floor(diff / DAY)} d ago`;
}
