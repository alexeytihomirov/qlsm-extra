import React, { ui } from './runtime';
import {
    X, RefreshCw, Film, AlertCircle, FolderOpen, Download, Search, ChevronRight, ChevronDown,
} from './icons';
import { fillPath, parseRoute } from './panelRoute';
import {
    DATE_PRESETS, KIND_FILTERS, SORTS,
    buildRows, filterRows, sortRows, facets, packingInUse, playersLabel, dayKey,
    formatBytes, formatDuration, formatTime, formatFull, formatDayLabel, formatAgo,
} from './demoRows';

// Modal chrome is core's, read off the runtime kit rather than imported:
// this file is built into a standalone bundle that ships with the addon and
// cannot reach into QLSM's own build (see qlsm's addons/README.md, "tier 2").
const { Modal } = ui;

// Lives inside the addon that owns it: QLSM core no longer has demo
// endpoints to default to, so `api` comes from the addon's mount wrapper and
// is required.

/**
 * Modal for viewing server-side demo files (.dm_91, plus .qlmatch - the
 * native-demo addon's zipped multi-POV match package - and its
 * .replay.json.gz merged-replay sidecar) recorded by minqlxtended on the
 * remote QLDS instance. Ground truth is the demos/ directory on disk
 * (fs_homepath/sv_demoDir) fetched directly over SFTP, so the result
 * reflects what the engine actually wrote, not what a plugin or cvar
 * claims. Each match comes back as one row labelled from its
 * "{match_id}.meta.json" (map, mode, players, length) or, failing that,
 * from the engine's own filenames.
 */

function triggerBlobDownload(blob, filename) {
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    window.URL.revokeObjectURL(url);
}

const PAGE_SIZE = 50;

// The last listing per instance, kept for this page's lifetime: reopening
// the screen shows it at once and refreshes behind it, instead of a spinner
// for however long the remote listing takes.
const listingCache = new Map();

// Filters survive closing the screen (per browser, not per instance - "only
// this week's duels" is how an operator looks at every server).
const FILTERS_KEY = 'qlsm.demo-management.filters.v1';
const DEFAULT_FILTERS = {
    text: '', datePreset: 'all', dateFrom: '', dateTo: '', map: '', gametype: '', kind: 'all', sort: 'newest',
};

function loadFilters() {
    try {
        const saved = JSON.parse(window.localStorage.getItem(FILTERS_KEY) || '{}');
        return { ...DEFAULT_FILTERS, ...saved, text: '' };
    } catch {
        return { ...DEFAULT_FILTERS };
    }
}

function saveFilters(filters) {
    try {
        const { text, ...rest } = filters;
        window.localStorage.setItem(FILTERS_KEY, JSON.stringify(rest));
    } catch {
        // Private window / blocked storage: filters just don't persist.
    }
}

const nowSeconds = () => Date.now() / 1000;

const inputClass = 'py-1.5 px-2 text-sm font-mono rounded-md bg-theme-base border border-theme-strong '
    + 'text-theme-primary focus:outline-none focus:ring-1 focus:ring-[var(--accent-primary)]';
const iconButtonClass = 'p-1.5 rounded-md text-theme-muted hover:text-theme-primary hover:bg-black/[0.04] '
    + 'dark:hover:bg-white/[0.06] disabled:opacity-40 disabled:cursor-not-allowed';

function Badge({ children, tone = 'muted', title }) {
    return <span className={`demos-addon-badge demos-addon-badge-${tone}`} title={title}>{children}</span>;
}

function KindBadges({ kinds, packing }) {
    return (
        <>
            {kinds.pov > 0 && <Badge title="Per-player .dm_91 demos">{kinds.pov} POV</Badge>}
            {kinds.pack > 0 && <Badge tone="primary" title=".qlmatch pack">pack</Badge>}
            {kinds.replay > 0 && <Badge tone="info" title="Merged .replay.json.gz">replay</Badge>}
            {packing && kinds.pov > 0 && kinds.pack === 0 && (
                <Badge tone="warning" title="Raw POVs without a .qlmatch pack - packing may have failed">not packed</Badge>
            )}
        </>
    );
}

function ViewDemosModal({ isOpen, onClose, instance, api }) {
    const [demos, setDemos] = React.useState([]);
    // Match groups: demo-management's own (clustered by match id) plus any
    // another addon contributed via the demo_management.match_groups hook
    // (e.g. qlmatch-packer, with its rebuild actions) -- see
    // ui/addons/hooks.py. Each carries an `info` the backend assembled.
    const [matches, setMatches] = React.useState([]);
    const [fetchedAt, setFetchedAt] = React.useState(null);
    const [timing, setTiming] = React.useState(null);
    const [isLoading, setIsLoading] = React.useState(false);
    const [isRefreshing, setIsRefreshing] = React.useState(false);
    const [error, setError] = React.useState(null);
    const [filters, setFilters] = React.useState(loadFilters);
    const [page, setPage] = React.useState(1);
    const [now, setNow] = React.useState(nowSeconds);
    const [selected, setSelected] = React.useState(() => new Set());
    const [downloadingNames, setDownloadingNames] = React.useState(() => new Set());
    const [isBatchDownloading, setIsBatchDownloading] = React.useState(false);
    const [downloadError, setDownloadError] = React.useState(null);
    const [selectedGroupIds, setSelectedGroupIds] = React.useState(() => new Set());
    // Collapsed by default: a match is meant to read as ONE line in this list.
    // Its files are a detail you open, not four rows you scroll past.
    const [expandedGroupIds, setExpandedGroupIds] = React.useState(() => new Set());
    const [busyGroupActionKey, setBusyGroupActionKey] = React.useState(null);
    const [groupActionError, setGroupActionError] = React.useState(null);

    const setFilter = (key, value) => setFilters((prev) => ({ ...prev, [key]: value }));
    React.useEffect(() => saveFilters(filters), [filters]);

    const applyListing = (data) => {
        setDemos(data.demos || []);
        setMatches(Array.isArray(data.matches) ? data.matches : []);
        setFetchedAt(data.fetched_at || nowSeconds());
        setTiming(data.timing_ms || null);
    };

    const fetchDemos = React.useCallback(async () => {
        if (!instance?.id) return;
        const cached = listingCache.get(instance.id);

        // With something already on screen, refresh behind it rather than
        // blanking the table for the length of a remote listing.
        if (cached) setIsRefreshing(true);
        else setIsLoading(true);
        setError(null);

        try {
            const data = await api.list(instance.id);
            listingCache.set(instance.id, data);
            applyListing(data);
        } catch (err) {
            console.error('Error listing demos:', err);
            setError(err?.message || err?.error?.message || 'Failed to list demos from the remote server.');
            if (!cached) {
                setDemos([]);
                setMatches([]);
            }
        } finally {
            setIsLoading(false);
            setIsRefreshing(false);
            setNow(nowSeconds());
        }
    }, [instance?.id]);

    React.useEffect(() => {
        if (isOpen && instance?.id) {
            const cached = listingCache.get(instance.id);
            if (cached) applyListing(cached);
            fetchDemos();
        } else {
            setDemos([]);
            setMatches([]);
            setFetchedAt(null);
            setTiming(null);
            setError(null);
            setFilters((prev) => ({ ...prev, text: '' }));
            setPage(1);
            setSelected(new Set());
            setDownloadingNames(new Set());
            setDownloadError(null);
            setSelectedGroupIds(new Set());
            setExpandedGroupIds(new Set());
            setGroupActionError(null);
        }
    }, [isOpen, instance?.id, fetchDemos]);

    // Keeps "updated 3 min ago" and the Today/Yesterday headers honest while
    // the screen stays open.
    React.useEffect(() => {
        if (!isOpen) return undefined;
        const timer = window.setInterval(() => setNow(nowSeconds()), 30000);
        return () => window.clearInterval(timer);
    }, [isOpen]);

    const allRows = React.useMemo(() => buildRows(demos, matches), [demos, matches]);
    const facetValues = React.useMemo(() => facets(allRows), [allRows]);
    const packing = React.useMemo(() => packingInUse(allRows), [allRows]);
    const displayRows = React.useMemo(
        () => sortRows(filterRows(allRows, filters, now), filters.sort),
        [allRows, filters, now],
    );

    const totals = React.useMemo(() => {
        const sum = (rows) => ({
            matches: rows.filter((r) => r.type === 'group').length,
            files: rows.reduce((n, r) => n + r.members.length, 0),
            size: rows.reduce((n, r) => n + r.size, 0),
        });
        return { all: sum(allRows), shown: sum(displayRows) };
    }, [allRows, displayRows]);

    const totalPages = Math.max(1, Math.ceil(displayRows.length / PAGE_SIZE));
    const pagedRows = React.useMemo(
        () => displayRows.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE),
        [displayRows, page],
    );

    // Any filter/data change can shrink the result set below the current
    // page -- snap back to a valid page instead of rendering an empty one.
    React.useEffect(() => {
        setPage((prev) => Math.min(prev, totalPages));
    }, [totalPages]);
    React.useEffect(() => {
        setPage(1);
    }, [filters]);

    // Selection follows what is visible: drop files and groups a refresh or
    // a filter change hid, so "Download selected (N)" never counts a stale
    // name.
    const visibleNames = React.useMemo(
        () => new Set(displayRows.flatMap((r) => r.members.map((d) => d.name))),
        [displayRows],
    );
    const visibleGroupIds = React.useMemo(
        () => new Set(displayRows.filter((r) => r.type === 'group').map((r) => r.group.group_id)),
        [displayRows],
    );
    React.useEffect(() => {
        setSelected((prev) => {
            const next = new Set([...prev].filter((name) => visibleNames.has(name)));
            return next.size === prev.size ? prev : next;
        });
        setSelectedGroupIds((prev) => {
            const next = new Set([...prev].filter((id) => visibleGroupIds.has(id)));
            return next.size === prev.size ? prev : next;
        });
    }, [visibleNames, visibleGroupIds]);

    const allVisibleSelected = visibleNames.size > 0 && [...visibleNames].every((n) => selected.has(n));

    const toggleSelectAll = () => {
        if (allVisibleSelected) {
            setSelected(new Set());
            setSelectedGroupIds(new Set());
        } else {
            setSelected(new Set(visibleNames));
            setSelectedGroupIds(new Set(visibleGroupIds));
        }
    };

    const toggleSelectOne = (name) => {
        setSelected((prev) => {
            const next = new Set(prev);
            if (next.has(name)) next.delete(name);
            else next.add(name);
            return next;
        });
    };

    // Bulk buttons: one per action `id` shared by every currently-selected
    // group that offers a `bulk` route for it (e.g. "Rebuild sidecar" on 3
    // selected matches becomes one "Rebuild sidecar (3)" button).
    const bulkGroupActions = React.useMemo(() => {
        const selectedGroups = matches.filter((m) => selectedGroupIds.has(m.group_id));
        if (selectedGroups.length === 0) return [];
        const byId = new Map();
        selectedGroups.forEach((group) => {
            (group.actions || []).forEach((action) => {
                if (!action.bulk) return;
                if (!byId.has(action.id)) {
                    byId.set(action.id, { action, addonId: group.addon_id, qlmatchNames: [] });
                }
                byId.get(action.id).qlmatchNames.push(group.qlmatch_name);
            });
        });
        // Only offer a bulk action every selected group actually has --
        // otherwise "Rebuild sidecar (3)" could silently skip one of them.
        return [...byId.values()].filter((entry) => entry.qlmatchNames.length === selectedGroups.length);
    }, [matches, selectedGroupIds]);

    // One checkbox, one meaning: "this whole match is selected". That drives
    // both the addon's bulk actions (which key off group ids) and the file
    // selection "Download selected" posts, so ticking a match downloads all of
    // its files without having to expand it first.
    const toggleSelectGroup = (row) => {
        const groupId = row.group.group_id;
        const selecting = !selectedGroupIds.has(groupId);
        setSelectedGroupIds((prev) => {
            const next = new Set(prev);
            if (selecting) next.add(groupId);
            else next.delete(groupId);
            return next;
        });
        setSelected((prev) => {
            const next = new Set(prev);
            row.members.forEach((d) => (selecting ? next.add(d.name) : next.delete(d.name)));
            return next;
        });
    };

    const toggleExpandGroup = (groupId) => {
        setExpandedGroupIds((prev) => {
            const next = new Set(prev);
            if (next.has(groupId)) next.delete(groupId);
            else next.add(groupId);
            return next;
        });
    };

    const runGroupAction = async (group, action) => {
        const spec = action.action;
        if (spec.confirm && !window.confirm(spec.confirm)) return;
        const key = `${action.id}:${group.group_id}`;
        setBusyGroupActionKey(key);
        setGroupActionError(null);
        try {
            const resolved = parseRoute(`${spec.method} ${spec.route}`);
            const path = fillPath(resolved.path, { scope: 'instance', scopeId: instance.id });
            await api.runAction(group.addon_id, resolved.method, path);
        } catch (err) {
            console.error('Error running match action:', err);
            setGroupActionError(
                err?.message || err?.error?.message || `Failed to run "${action.label}" for ${group.label}.`,
            );
        } finally {
            setBusyGroupActionKey(null);
        }
    };

    const runBulkGroupAction = async (entry) => {
        const confirmText = entry.action.action?.confirm;
        if (confirmText && !window.confirm(confirmText)) return;
        const key = `bulk:${entry.action.id}`;
        setBusyGroupActionKey(key);
        setGroupActionError(null);
        try {
            const resolved = parseRoute(`${entry.action.bulk.method} ${entry.action.bulk.route}`);
            const path = fillPath(resolved.path, { scope: 'instance', scopeId: instance.id });
            const selectionKey = entry.action.bulk.selection_key || 'selected';
            await api.runAction(entry.addonId, resolved.method, path, { [selectionKey]: entry.qlmatchNames });
            setSelectedGroupIds(new Set());
        } catch (err) {
            console.error('Error running bulk match action:', err);
            setGroupActionError(err?.message || err?.error?.message || `Failed to run "${entry.action.label}".`);
        } finally {
            setBusyGroupActionKey(null);
        }
    };

    const downloadOne = async (name) => {
        setDownloadError(null);
        setDownloadingNames((prev) => new Set(prev).add(name));
        try {
            const blob = await api.downloadOne(instance.id, name);
            triggerBlobDownload(blob, name);
        } catch (err) {
            console.error('Error downloading demo:', err);
            setDownloadError(err?.message || err?.error?.message || `Failed to download ${name}.`);
        } finally {
            setDownloadingNames((prev) => {
                const next = new Set(prev);
                next.delete(name);
                return next;
            });
        }
    };

    const downloadSelected = async () => {
        if (selected.size === 0) return;
        setDownloadError(null);
        setIsBatchDownloading(true);
        try {
            const names = [...selected];
            const blob = await api.downloadBatch(instance.id, names);
            const safeName = (instance?.name || 'instance').replace(/[^A-Za-z0-9._-]+/g, '-');
            triggerBlobDownload(blob, `${safeName}-demos.zip`);
        } catch (err) {
            console.error('Error batch-downloading demos:', err);
            setDownloadError(err?.message || err?.error?.message || 'Failed to download selected demos.');
        } finally {
            setIsBatchDownloading(false);
        }
    };

    const filtersActive = filters.text || filters.datePreset !== 'all' || filters.map
        || filters.gametype || filters.kind !== 'all';
    const resetFilters = () => setFilters((prev) => ({ ...DEFAULT_FILTERS, sort: prev.sort }));
    const showDayHeaders = filters.sort === 'newest' || filters.sort === 'oldest';
    const hasData = demos.length > 0;
    const listingSeconds = timing && Number.isFinite(timing.total_ms)
        ? ((timing.total_ms + (timing.hooks_ms || 0)) / 1000).toFixed(1)
        : null;

    const downloadButton = (name) => (
        <button
            onClick={() => downloadOne(name)}
            disabled={downloadingNames.has(name)}
            title={`Download ${name}`}
            aria-label={`Download ${name}`}
            className={iconButtonClass}
        >
            <Download className={`h-4 w-4 ${downloadingNames.has(name) ? 'animate-pulse' : ''}`} strokeWidth={2} />
        </button>
    );

    const renderWhen = (row) => (
        <td className="py-2 pr-4 font-mono text-theme-secondary whitespace-nowrap" title={formatFull(row.when)}>
            {showDayHeaders ? formatTime(row.when) : `${formatDayLabel(row.when, now)}, ${formatTime(row.when)}`}
        </td>
    );

    const renderFileRow = (demo, nested) => (
        <tr key={demo.name} className="border-b border-theme/50 hover:bg-black/[0.02] dark:hover:bg-white/[0.02]">
            <td className="py-2 pr-2">
                <input
                    type="checkbox"
                    checked={selected.has(demo.name)}
                    onChange={() => toggleSelectOne(demo.name)}
                    aria-label={`Select ${demo.name}`}
                />
            </td>
            <td className={`py-2 pr-4 font-mono break-all ${nested ? 'pl-6 text-xs text-theme-secondary' : 'text-theme-primary'}`}>
                <div>{demo.name}</div>
                {nested && demo.pov?.player && (
                    <div className="text-theme-muted">
                        {demo.pov.slot !== null && demo.pov.slot !== undefined ? `slot ${demo.pov.slot} · ` : ''}
                        {demo.pov.player}
                    </div>
                )}
            </td>
            <td className="py-2 pr-4" />
            <td className="py-2 pr-4 font-mono text-theme-secondary whitespace-nowrap">{formatBytes(demo.size)}</td>
            <td className="py-2 pr-4 font-mono text-theme-secondary whitespace-nowrap" title={formatFull(demo.mtime)}>
                {nested ? formatTime(demo.mtime) : ''}
            </td>
            <td className="py-2 pr-2">{downloadButton(demo.name)}</td>
        </tr>
    );

    const renderLooseRow = (row) => {
        const { demo, info } = row;
        return (
            <tr key={row.key} className="border-b border-theme/50 hover:bg-black/[0.02] dark:hover:bg-white/[0.02]">
                <td className="py-2 pr-2">
                    <input
                        type="checkbox"
                        checked={selected.has(demo.name)}
                        onChange={() => toggleSelectOne(demo.name)}
                        aria-label={`Select ${demo.name}`}
                    />
                </td>
                <td className="py-2 pr-4">
                    <div className="font-mono text-theme-primary break-all">{demo.name}</div>
                    {(info.map || demo.pov?.player) && (
                        <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-xs text-theme-muted">
                            {info.map && <span className="text-theme-secondary">{info.map}</span>}
                            {demo.pov?.player && <span>· {demo.pov.player}</span>}
                            <KindBadges kinds={row.kinds} packing={false} />
                        </div>
                    )}
                </td>
                <td className="py-2 pr-4" />
                <td className="py-2 pr-4 font-mono text-theme-secondary whitespace-nowrap">{formatBytes(demo.size)}</td>
                {renderWhen(row)}
                <td className="py-2 pr-2">{downloadButton(demo.name)}</td>
            </tr>
        );
    };

    const renderGroupRow = (row) => {
        const { group, members, info } = row;
        const isExpanded = expandedGroupIds.has(group.group_id);
        const players = playersLabel(info);
        return (
            <React.Fragment key={row.key}>
                <tr className="border-b border-theme/50 bg-black/[0.02] dark:bg-white/[0.03]">
                    <td className="py-2 pr-2 align-top">
                        <input
                            type="checkbox"
                            checked={selectedGroupIds.has(group.group_id)}
                            onChange={() => toggleSelectGroup(row)}
                            aria-label={`Select match ${group.label}`}
                        />
                    </td>
                    <td className="py-2 pr-4">
                        <button
                            onClick={() => toggleExpandGroup(group.group_id)}
                            aria-expanded={isExpanded}
                            title={isExpanded ? 'Hide the files in this match' : 'Show the files in this match'}
                            className="flex items-start gap-1.5 text-left hover:text-[var(--accent-primary)]"
                        >
                            {isExpanded
                                ? <ChevronDown className="mt-0.5 h-4 w-4 flex-shrink-0" strokeWidth={2} />
                                : <ChevronRight className="mt-0.5 h-4 w-4 flex-shrink-0" strokeWidth={2} />}
                            <span className="min-w-0">
                                <span className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
                                    <span className="font-display text-base font-bold text-theme-primary">
                                        {info.map || group.label}
                                    </span>
                                    {info.gametype && <Badge tone="primary">{info.gametype}</Badge>}
                                    {players && <span className="text-sm text-theme-secondary">{players}</span>}
                                </span>
                                <span className="mt-0.5 flex flex-wrap items-center gap-1.5 text-xs text-theme-muted">
                                    <span className="font-mono">{info.match_id || group.group_id}</span>
                                    <span>·</span>
                                    <span>{members.length} file{members.length === 1 ? '' : 's'}</span>
                                    <KindBadges kinds={row.kinds} packing={packing} />
                                </span>
                            </span>
                        </button>
                    </td>
                    <td className="py-2 pr-4 font-mono text-theme-secondary whitespace-nowrap">
                        {formatDuration(info.duration_ms)}
                    </td>
                    <td className="py-2 pr-4 font-mono text-theme-secondary whitespace-nowrap">{formatBytes(row.size)}</td>
                    {renderWhen(row)}
                    <td className="py-2 pr-2">
                        <div className="flex items-center gap-1">
                            {(group.actions || []).map((action) => {
                                const busyKey = `${action.id}:${group.group_id}`;
                                return (
                                    <button
                                        key={action.id}
                                        onClick={() => runGroupAction(group, action)}
                                        disabled={busyGroupActionKey !== null}
                                        title={action.label}
                                        aria-label={`${action.label} for ${group.label}`}
                                        className={iconButtonClass}
                                        style={action.danger ? { color: 'var(--accent-danger)' } : undefined}
                                    >
                                        <RefreshCw
                                            className={`h-4 w-4 ${busyGroupActionKey === busyKey ? 'animate-spin' : ''}`}
                                            strokeWidth={2}
                                        />
                                    </button>
                                );
                            })}
                        </div>
                    </td>
                </tr>
                {isExpanded && members.map((demo) => renderFileRow(demo, true))}
            </React.Fragment>
        );
    };

    const renderRows = () => {
        const out = [];
        let lastDay = null;
        pagedRows.forEach((row) => {
            if (showDayHeaders) {
                const day = dayKey(row.when);
                if (day !== lastDay) {
                    lastDay = day;
                    const sameDay = displayRows.filter((r) => dayKey(r.when) === day);
                    const dayMatches = sameDay.filter((r) => r.type === 'group').length;
                    const dayLoose = sameDay.length - dayMatches;
                    const daySummary = [
                        dayMatches > 0 ? `${dayMatches} match${dayMatches === 1 ? '' : 'es'}` : null,
                        dayLoose > 0 ? `${dayLoose} file${dayLoose === 1 ? '' : 's'}` : null,
                    ].filter(Boolean).join(' · ');
                    out.push(
                        <tr key={`day-${day}`} className="demos-addon-day-row">
                            <td colSpan={6} className="pt-4 pb-1.5">
                                <span className="font-display text-sm font-bold uppercase tracking-wide text-theme-primary">
                                    {formatDayLabel(row.when, now)}
                                </span>
                                <span className="ml-2 text-xs font-mono text-theme-muted">{daySummary}</span>
                            </td>
                        </tr>,
                    );
                }
            }
            out.push(row.type === 'group' ? renderGroupRow(row) : renderLooseRow(row));
        });
        return out;
    };

    return (
        <Modal
            isOpen={isOpen}
            onClose={onClose}
            size="2xl"
            height="75vh"
            icon={(
                <div className="demos-addon-icon-wrapper">
                    <div className="demos-addon-icon-glow" />
                    <Film className="demos-addon-icon" strokeWidth={2.5} />
                </div>
            )}
            title={(
                <>
                    Demos
                    <span className="mt-0.5 block font-mono text-xs font-normal normal-case tracking-normal text-theme-secondary">
                        {instance?.name} <span className="text-theme-muted">•</span> Port {instance?.port} <span className="text-theme-muted">•</span> demos/ on disk
                        {fetchedAt && (
                            <>
                                {' '}<span className="text-theme-muted">•</span>{' '}
                                <span title={timing ? `Listing timings (ms): ${JSON.stringify(timing)}` : undefined}>
                                    {isRefreshing ? 'refreshing…' : `updated ${formatAgo(fetchedAt, now)}`}
                                    {listingSeconds && !isRefreshing ? ` in ${listingSeconds}s` : ''}
                                </span>
                            </>
                        )}
                    </span>
                </>
            )}
            headerActions={(
                <>
                    <button
                        onClick={fetchDemos}
                        disabled={isLoading || isRefreshing}
                        className="demos-addon-btn"
                    >
                        <RefreshCw className={`h-4 w-4 ${isLoading || isRefreshing ? 'animate-spin' : ''}`} strokeWidth={2} />
                        <span>Refresh</span>
                    </button>
                    <button
                        onClick={onClose}
                        className="demos-addon-close-btn"
                    >
                        <X className="h-5 w-5" strokeWidth={2} />
                    </button>
                </>
            )}
        >
            <div className="flex h-full flex-col">
                {!isLoading && hasData && (
                    <div className="flex flex-shrink-0 flex-col gap-2 border-b border-theme pb-3 mb-3">
                        <div className="flex flex-wrap items-center gap-2">
                            <div className="relative min-w-[12rem] flex-1 max-w-xs">
                                <Search className="demo-search-icon absolute top-1/2 -translate-y-1/2 text-theme-muted" />
                                <input
                                    type="text"
                                    value={filters.text}
                                    onChange={(e) => setFilter('text', e.target.value)}
                                    placeholder="Map, player, file name..."
                                    aria-label="Filter demos"
                                    className={`w-full pl-8 pr-3 ${inputClass} placeholder:text-theme-muted`}
                                />
                            </div>
                            <div className="demos-addon-segmented" role="group" aria-label="Recorded">
                                {DATE_PRESETS.map((preset) => (
                                    <button
                                        key={preset.id}
                                        onClick={() => setFilter('datePreset', preset.id)}
                                        aria-pressed={filters.datePreset === preset.id}
                                        className={filters.datePreset === preset.id ? 'is-active' : ''}
                                    >
                                        {preset.label}
                                    </button>
                                ))}
                            </div>
                            {filters.datePreset === 'custom' && (
                                <div className="flex items-center gap-1.5">
                                    <input
                                        type="date"
                                        value={filters.dateFrom}
                                        onChange={(e) => setFilter('dateFrom', e.target.value)}
                                        max={filters.dateTo || undefined}
                                        aria-label="Recorded from date"
                                        className={inputClass}
                                    />
                                    <span className="text-theme-muted text-xs">to</span>
                                    <input
                                        type="date"
                                        value={filters.dateTo}
                                        onChange={(e) => setFilter('dateTo', e.target.value)}
                                        min={filters.dateFrom || undefined}
                                        aria-label="Recorded to date"
                                        className={inputClass}
                                    />
                                </div>
                            )}
                        </div>
                        <div className="flex flex-wrap items-center gap-2">
                            {facetValues.maps.length > 0 && (
                                <select
                                    value={filters.map}
                                    onChange={(e) => setFilter('map', e.target.value)}
                                    aria-label="Map"
                                    className={inputClass}
                                >
                                    <option value="">All maps</option>
                                    {facetValues.maps.map(({ value, count }) => (
                                        <option key={value} value={value}>{value} ({count})</option>
                                    ))}
                                </select>
                            )}
                            {facetValues.gametypes.length > 0 && (
                                <select
                                    value={filters.gametype}
                                    onChange={(e) => setFilter('gametype', e.target.value)}
                                    aria-label="Game type"
                                    className={inputClass}
                                >
                                    <option value="">All modes</option>
                                    {facetValues.gametypes.map(({ value, count }) => (
                                        <option key={value} value={value}>{value} ({count})</option>
                                    ))}
                                </select>
                            )}
                            <select
                                value={filters.kind}
                                onChange={(e) => setFilter('kind', e.target.value)}
                                aria-label="Show"
                                className={inputClass}
                            >
                                {KIND_FILTERS.map((k) => <option key={k.id} value={k.id}>{k.label}</option>)}
                            </select>
                            <select
                                value={filters.sort}
                                onChange={(e) => setFilter('sort', e.target.value)}
                                aria-label="Sort"
                                className={inputClass}
                            >
                                {SORTS.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
                            </select>
                            {filtersActive && (
                                <button onClick={resetFilters} className="text-xs font-mono text-theme-muted underline hover:text-theme-primary">
                                    reset
                                </button>
                            )}
                            <span className="text-xs font-mono text-theme-muted whitespace-nowrap" title={`${totals.all.files} files, ${formatBytes(totals.all.size)} on disk`}>
                                {filtersActive
                                    ? `${totals.shown.matches} of ${totals.all.matches} matches · ${totals.shown.files} of ${totals.all.files} files`
                                    : `${totals.all.matches} matches · ${totals.all.files} files`}
                                {` · ${formatBytes(filtersActive ? totals.shown.size : totals.all.size)}`}
                            </span>
                            <div className="flex-1" />
                            {bulkGroupActions.map((entry) => (
                                <button
                                    key={entry.action.id}
                                    onClick={() => runBulkGroupAction(entry)}
                                    disabled={busyGroupActionKey !== null}
                                    className="demos-addon-btn disabled:opacity-40 disabled:cursor-not-allowed"
                                >
                                    <RefreshCw
                                        className={`h-4 w-4 ${busyGroupActionKey === `bulk:${entry.action.id}` ? 'animate-spin' : ''}`}
                                        strokeWidth={2}
                                    />
                                    <span>{entry.action.label} ({entry.qlmatchNames.length})</span>
                                </button>
                            ))}
                            <button
                                onClick={downloadSelected}
                                disabled={selected.size === 0 || isBatchDownloading}
                                className="demos-addon-btn disabled:opacity-40 disabled:cursor-not-allowed"
                            >
                                <Download className={`h-4 w-4 ${isBatchDownloading ? 'animate-pulse' : ''}`} strokeWidth={2} />
                                <span>Download selected {selected.size > 0 ? `(${selected.size})` : ''}</span>
                            </button>
                        </div>
                    </div>
                )}

                {error && hasData && (
                    <div className="flex-shrink-0 pb-2 text-sm text-center" style={{ color: 'var(--accent-danger)' }}>
                        Refresh failed: {error} Showing the previous listing.
                    </div>
                )}

                {downloadError && (
                    <div className="flex-shrink-0 pb-2 text-sm text-center" style={{ color: 'var(--accent-danger)' }}>
                        {downloadError}
                    </div>
                )}

                {groupActionError && (
                    <div className="flex-shrink-0 pb-2 text-sm text-center" style={{ color: 'var(--accent-danger)' }}>
                        {groupActionError}
                    </div>
                )}

                <div className="flex-1 overflow-auto">
                    {isLoading ? (
                        <div className="demos-addon-empty-state">
                            <div className="demos-addon-spinner-wrapper">
                                <RefreshCw className="demos-addon-spinner" strokeWidth={2} />
                            </div>
                            <p className="font-mono text-sm text-theme-secondary uppercase tracking-wide">Listing demos on remote server...</p>
                        </div>
                    ) : error && !hasData ? (
                        <div className="demos-addon-error-state">
                            <AlertCircle className="h-10 w-10 mb-4" style={{ color: 'var(--accent-danger)' }} strokeWidth={2} />
                            <p className="font-display text-lg font-bold uppercase tracking-wide" style={{ color: 'var(--accent-danger)' }}>Error Listing Demos</p>
                            <p className="text-sm text-theme-secondary mt-2 max-w-md text-center">{error}</p>
                            <button
                                onClick={fetchDemos}
                                className="demos-addon-retry-btn"
                            >
                                Try Again
                            </button>
                        </div>
                    ) : !hasData ? (
                        <div className="demos-addon-empty-state">
                            <FolderOpen className="h-10 w-10 mb-4 text-theme-muted" strokeWidth={2} />
                            <p className="font-display text-base font-bold uppercase tracking-wide text-theme-primary">No demos found</p>
                            <p className="text-sm text-theme-secondary mt-2 max-w-md text-center">
                                No .dm_91, .qlmatch or .replay.json.gz files in this instance's demos/
                                directory. Recording needs sv_demoRecord 1 (add sv_demoCut 1 for match-cut demos
                                and .qlmatch packing) — check View MinQLX Logs / View Server Logs for "demo:"
                                lines after a manual test.
                            </p>
                        </div>
                    ) : displayRows.length === 0 ? (
                        <div className="demos-addon-empty-state">
                            <Search className="h-10 w-10 mb-4 text-theme-muted" strokeWidth={2} />
                            <p className="text-sm text-theme-secondary">No demos match these filters.</p>
                            <button onClick={resetFilters} className="demos-addon-btn">Reset filters</button>
                        </div>
                    ) : (
                        <table className="w-full text-sm">
                            <thead className="demos-addon-thead">
                                <tr className="text-left text-theme-muted uppercase text-xs tracking-wide border-b border-theme">
                                    <th className="py-2 pr-2 w-8">
                                        <input
                                            type="checkbox"
                                            checked={allVisibleSelected}
                                            onChange={toggleSelectAll}
                                            aria-label="Select all shown demos"
                                        />
                                    </th>
                                    <th className="py-2 pr-4 font-medium">Match / file</th>
                                    <th className="py-2 pr-4 font-medium w-20">Length</th>
                                    <th className="py-2 pr-4 font-medium w-24">Size</th>
                                    <th className="py-2 pr-4 font-medium w-40">Started</th>
                                    <th className="py-2 pr-2 w-20" />
                                </tr>
                            </thead>
                            <tbody>{renderRows()}</tbody>
                        </table>
                    )}
                </div>

                {!isLoading && displayRows.length > 0 && totalPages > 1 && (
                    <div className="flex flex-shrink-0 items-center justify-center gap-3 border-t border-theme pt-3 mt-3">
                        <button
                            onClick={() => setPage((p) => Math.max(1, p - 1))}
                            disabled={page <= 1}
                            className="demos-addon-btn disabled:opacity-40 disabled:cursor-not-allowed"
                        >
                            Prev
                        </button>
                        <span className="text-xs font-mono text-theme-muted whitespace-nowrap">
                            Page {page} of {totalPages}
                        </span>
                        <button
                            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                            disabled={page >= totalPages}
                            className="demos-addon-btn disabled:opacity-40 disabled:cursor-not-allowed"
                        >
                            Next
                        </button>
                    </div>
                )}
            </div>
        </Modal>
    );
}

export default ViewDemosModal;
