import React, { ui } from './runtime';
import {
    X, RefreshCw, Film, AlertCircle, FolderOpen, Download, Search, ChevronRight, ChevronDown,
} from './icons';
import { fillPath, parseRoute } from './panelRoute';

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
 * claims.
 */

function formatBytes(bytes) {
    if (!Number.isFinite(bytes)) return '—';
    if (bytes < 1024) return `${bytes} B`;
    const units = ['KB', 'MB', 'GB'];
    let value = bytes / 1024;
    let unitIndex = 0;
    while (value >= 1024 && unitIndex < units.length - 1) {
        value /= 1024;
        unitIndex += 1;
    }
    return `${value.toFixed(1)} ${units[unitIndex]}`;
}

function formatMtime(mtime) {
    if (!Number.isFinite(mtime)) return '—';
    return new Date(mtime * 1000).toLocaleString();
}

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

function ViewDemosModal({ isOpen, onClose, instance, api }) {
    const [demos, setDemos] = React.useState([]);
    // Match groups (e.g. a .qlmatch pack + its replay sidecar) contributed
    // by another addon via the demo_management.match_groups
    // hook -- see ui/addons/hooks.py. Empty when no such addon is enabled;
    // this component never assumes it exists.
    const [matches, setMatches] = React.useState([]);
    const [isLoading, setIsLoading] = React.useState(false);
    const [error, setError] = React.useState(null);
    // Space-separated terms, ANDed together -- lets "dm17 alex" match a
    // filename that encodes both a map and a match/player name without a
    // second dedicated field (demo entries carry no separate `map` field).
    const [filterText, setFilterText] = React.useState('');
    const [dateFrom, setDateFrom] = React.useState('');
    const [dateTo, setDateTo] = React.useState('');
    const [page, setPage] = React.useState(1);
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

    const fetchDemos = React.useCallback(async () => {
        if (!instance?.id) return;

        setIsLoading(true);
        setError(null);

        try {
            const data = await api.list(instance.id);
            setDemos(data.demos || []);
            setMatches(Array.isArray(data.matches) ? data.matches : []);
        } catch (err) {
            console.error('Error listing demos:', err);
            setError(err?.message || err?.error?.message || 'Failed to list demos from the remote server.');
            setDemos([]);
            setMatches([]);
        } finally {
            setIsLoading(false);
        }
    }, [instance?.id]);

    React.useEffect(() => {
        if (isOpen && instance?.id) {
            fetchDemos();
        } else {
            setDemos([]);
            setMatches([]);
            setError(null);
            setFilterText('');
            setDateFrom('');
            setDateTo('');
            setPage(1);
            setSelected(new Set());
            setDownloadingNames(new Set());
            setDownloadError(null);
            setSelectedGroupIds(new Set());
            setExpandedGroupIds(new Set());
            setGroupActionError(null);
        }
    }, [isOpen, instance?.id, fetchDemos]);

    const filterTerms = React.useMemo(
        () => filterText.trim().toLowerCase().split(/\s+/).filter(Boolean),
        [filterText],
    );
    const matchesTerms = React.useCallback(
        (name) => {
            const lower = name.toLowerCase();
            return filterTerms.every((term) => lower.includes(term));
        },
        [filterTerms],
    );

    // dateTo is inclusive of the whole day it names, so a demo recorded at
    // 23:59 on the end date still matches.
    const dateFromTs = dateFrom ? new Date(`${dateFrom}T00:00:00`).getTime() / 1000 : null;
    const dateToTs = dateTo ? new Date(`${dateTo}T00:00:00`).getTime() / 1000 + 86400 : null;
    const matchesDateRange = React.useCallback(
        (mtime) => (dateFromTs === null || mtime >= dateFromTs) && (dateToTs === null || mtime < dateToTs),
        [dateFromTs, dateToTs],
    );

    const filteredDemos = React.useMemo(
        () => demos.filter((d) => matchesTerms(d.name) && matchesDateRange(d.mtime || 0)),
        [demos, matchesTerms, matchesDateRange],
    );

    // Drop any selected filenames that no longer exist after a refresh/filter
    // change, so "Download selected (N)" never counts a stale name.
    React.useEffect(() => {
        const visible = new Set(filteredDemos.map((d) => d.name));
        setSelected((prev) => {
            const next = new Set([...prev].filter((name) => visible.has(name)));
            return next.size === prev.size ? prev : next;
        });
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [demos]);

    const allFilteredSelected = filteredDemos.length > 0
        && filteredDemos.every((d) => selected.has(d.name));

    const toggleSelectAll = () => {
        setSelected((prev) => {
            if (allFilteredSelected) {
                const next = new Set(prev);
                filteredDemos.forEach((d) => next.delete(d.name));
                return next;
            }
            const next = new Set(prev);
            filteredDemos.forEach((d) => next.add(d.name));
            return next;
        });
    };

    const toggleSelectOne = (name) => {
        setSelected((prev) => {
            const next = new Set(prev);
            if (next.has(name)) next.delete(name);
            else next.add(name);
            return next;
        });
    };

    // Rows to render: a group's own files clustered under one header (with
    // whatever the contributing addon offered as actions), everything else
    // as a plain standalone row -- same shape the flat list always had.
    // Grouping and filtering both key off `demos`, not `filteredDemos`: a
    // group is shown if ANY of its member filenames matches the filter, so
    // typing part of a match id does not split its pack from its sidecar.
    //
    // Groups and standalone files are then sorted together, newest first, by
    // the newest file each row holds. Listing every group ahead of every loose
    // file (which is what building the two lists back to back used to do) put
    // last week's packed match above this evening's recording.
    const displayRows = React.useMemo(() => {
        const demoByName = new Map(demos.map((d) => [d.name, d]));
        const grouped = new Set();
        matches.forEach((m) => (m.member_names || []).forEach((n) => grouped.add(n)));

        const rows = [];
        matches.forEach((group) => {
            const members = (group.member_names || [])
                .map((name) => demoByName.get(name))
                .filter(Boolean);
            if (!members.length) return;
            if (!members.some((d) => matchesTerms(d.name) && matchesDateRange(d.mtime || 0))) return;
            members.sort((a, b) => (b.mtime || 0) - (a.mtime || 0));
            rows.push({ type: 'group', group, members, mtime: members[0].mtime || 0 });
        });
        demos.forEach((demo) => {
            if (grouped.has(demo.name)) return;
            if (!matchesTerms(demo.name) || !matchesDateRange(demo.mtime || 0)) return;
            rows.push({ type: 'demo', demo, mtime: demo.mtime || 0 });
        });
        rows.sort((a, b) => b.mtime - a.mtime);
        return rows;
    }, [demos, matches, matchesTerms, matchesDateRange]);

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
    }, [filterTerms, dateFromTs, dateToTs]);

    const visibleGroupIds = React.useMemo(
        () => new Set(displayRows.filter((r) => r.type === 'group').map((r) => r.group.group_id)),
        [displayRows],
    );

    // Drop any selected group id no longer visible after a refresh/filter
    // change, mirroring the equivalent effect for file selection above.
    React.useEffect(() => {
        setSelectedGroupIds((prev) => {
            const next = new Set([...prev].filter((id) => visibleGroupIds.has(id)));
            return next.size === prev.size ? prev : next;
        });
    }, [visibleGroupIds]);

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
                    </span>
                </>
            )}
            headerActions={(
                <>
                    <button
                        onClick={fetchDemos}
                        disabled={isLoading}
                        className="demos-addon-btn"
                    >
                        <RefreshCw className={`h-4 w-4 ${isLoading ? 'animate-spin' : ''}`} strokeWidth={2} />
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
                {!isLoading && !error && demos.length > 0 && (
                    <div className="flex flex-shrink-0 items-center gap-3 border-b border-theme pb-3 mb-3">
                        <div className="relative flex-1 max-w-xs">
                            <Search className="demo-search-icon absolute top-1/2 -translate-y-1/2 text-theme-muted" />
                            <input
                                type="text"
                                value={filterText}
                                onChange={(e) => setFilterText(e.target.value)}
                                placeholder="Filter by filename (space-separated terms)..."
                                className="w-full pl-8 pr-3 py-1.5 text-sm font-mono rounded-md bg-theme-base border border-theme-strong text-theme-primary placeholder:text-theme-muted focus:outline-none focus:ring-1 focus:ring-[var(--accent-primary)]"
                            />
                        </div>
                        <div className="flex items-center gap-1.5">
                            <input
                                type="date"
                                value={dateFrom}
                                onChange={(e) => setDateFrom(e.target.value)}
                                max={dateTo || undefined}
                                aria-label="Recorded from date"
                                className="py-1.5 px-2 text-sm font-mono rounded-md bg-theme-base border border-theme-strong text-theme-primary focus:outline-none focus:ring-1 focus:ring-[var(--accent-primary)]"
                            />
                            <span className="text-theme-muted text-xs">to</span>
                            <input
                                type="date"
                                value={dateTo}
                                onChange={(e) => setDateTo(e.target.value)}
                                min={dateFrom || undefined}
                                aria-label="Recorded to date"
                                className="py-1.5 px-2 text-sm font-mono rounded-md bg-theme-base border border-theme-strong text-theme-primary focus:outline-none focus:ring-1 focus:ring-[var(--accent-primary)]"
                            />
                        </div>
                        <span className="text-xs font-mono text-theme-muted whitespace-nowrap">
                            {filteredDemos.length} of {demos.length}
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
                    ) : error ? (
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
                    ) : demos.length === 0 ? (
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
                            <p className="text-sm text-theme-secondary">No demos match "{filterText}".</p>
                        </div>
                    ) : (
                        <table className="w-full text-sm">
                            <thead>
                                <tr className="text-left text-theme-muted uppercase text-xs tracking-wide border-b border-theme">
                                    <th className="py-2 pr-2 w-8">
                                        <input
                                            type="checkbox"
                                            checked={allFilteredSelected}
                                            onChange={toggleSelectAll}
                                            aria-label="Select all demos"
                                        />
                                    </th>
                                    <th className="py-2 pr-4 font-medium">File</th>
                                    <th className="py-2 pr-4 font-medium">Size</th>
                                    <th className="py-2 pr-4 font-medium">Recorded</th>
                                    <th className="py-2 pr-2 w-10" />
                                </tr>
                            </thead>
                            <tbody>
                                {pagedRows.map((row) => {
                                    if (row.type === 'demo') {
                                        return (
                                            <tr key={row.demo.name} className="border-b border-theme/50 hover:bg-black/[0.02] dark:hover:bg-white/[0.02]">
                                                <td className="py-2 pr-2">
                                                    <input
                                                        type="checkbox"
                                                        checked={selected.has(row.demo.name)}
                                                        onChange={() => toggleSelectOne(row.demo.name)}
                                                        aria-label={`Select ${row.demo.name}`}
                                                    />
                                                </td>
                                                <td className="py-2 pr-4 font-mono text-theme-primary break-all">{row.demo.name}</td>
                                                <td className="py-2 pr-4 font-mono text-theme-secondary whitespace-nowrap">{formatBytes(row.demo.size)}</td>
                                                <td className="py-2 pr-4 font-mono text-theme-secondary whitespace-nowrap">{formatMtime(row.demo.mtime)}</td>
                                                <td className="py-2 pr-2">
                                                    <button
                                                        onClick={() => downloadOne(row.demo.name)}
                                                        disabled={downloadingNames.has(row.demo.name)}
                                                        title={`Download ${row.demo.name}`}
                                                        aria-label={`Download ${row.demo.name}`}
                                                        className="p-1.5 rounded-md text-theme-muted hover:text-theme-primary hover:bg-black/[0.04] dark:hover:bg-white/[0.06] disabled:opacity-40 disabled:cursor-not-allowed"
                                                    >
                                                        <Download className={`h-4 w-4 ${downloadingNames.has(row.demo.name) ? 'animate-pulse' : ''}`} strokeWidth={2} />
                                                    </button>
                                                </td>
                                            </tr>
                                        );
                                    }

                                    const { group, members } = row;
                                    const isExpanded = expandedGroupIds.has(group.group_id);
                                    const newest = members[0];
                                    const totalSize = members.reduce((sum, d) => sum + (d.size || 0), 0);
                                    return (
                                        <React.Fragment key={`group-${group.group_id}`}>
                                            <tr className="border-b border-theme/50 bg-black/[0.02] dark:bg-white/[0.03]">
                                                <td className="py-2 pr-2">
                                                    <input
                                                        type="checkbox"
                                                        checked={selectedGroupIds.has(group.group_id)}
                                                        onChange={() => toggleSelectGroup(row)}
                                                        aria-label={`Select match ${group.label}`}
                                                    />
                                                </td>
                                                <td className="py-2 pr-4 font-mono text-theme-primary break-all">
                                                    <button
                                                        onClick={() => toggleExpandGroup(group.group_id)}
                                                        aria-expanded={isExpanded}
                                                        title={isExpanded ? 'Hide the files in this match' : 'Show the files in this match'}
                                                        className="flex items-center gap-1.5 text-left hover:text-[var(--accent-primary)]"
                                                    >
                                                        {isExpanded
                                                            ? <ChevronDown className="h-4 w-4 flex-shrink-0" strokeWidth={2} />
                                                            : <ChevronRight className="h-4 w-4 flex-shrink-0" strokeWidth={2} />}
                                                        <span>{group.label}</span>
                                                        <span className="text-theme-muted">({members.length} file{members.length === 1 ? '' : 's'})</span>
                                                    </button>
                                                </td>
                                                <td className="py-2 pr-4 font-mono text-theme-secondary whitespace-nowrap">{formatBytes(totalSize)}</td>
                                                <td className="py-2 pr-4 font-mono text-theme-secondary whitespace-nowrap">{formatMtime(newest.mtime)}</td>
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
                                                                    className="p-1.5 rounded-md text-theme-muted hover:text-theme-primary hover:bg-black/[0.04] dark:hover:bg-white/[0.06] disabled:opacity-40 disabled:cursor-not-allowed"
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
                                            {isExpanded && members.map((demo) => (
                                                <tr key={demo.name} className="border-b border-theme/50 hover:bg-black/[0.02] dark:hover:bg-white/[0.02]">
                                                    <td className="py-2 pr-2">
                                                        <input
                                                            type="checkbox"
                                                            checked={selected.has(demo.name)}
                                                            onChange={() => toggleSelectOne(demo.name)}
                                                            aria-label={`Select ${demo.name}`}
                                                        />
                                                    </td>
                                                    <td className="py-2 pr-4 pl-6 font-mono text-theme-secondary break-all text-xs">{demo.name}</td>
                                                    <td className="py-2 pr-4 font-mono text-theme-secondary whitespace-nowrap">{formatBytes(demo.size)}</td>
                                                    <td className="py-2 pr-4 font-mono text-theme-secondary whitespace-nowrap">{formatMtime(demo.mtime)}</td>
                                                    <td className="py-2 pr-2">
                                                        <button
                                                            onClick={() => downloadOne(demo.name)}
                                                            disabled={downloadingNames.has(demo.name)}
                                                            title={`Download ${demo.name}`}
                                                            aria-label={`Download ${demo.name}`}
                                                            className="p-1.5 rounded-md text-theme-muted hover:text-theme-primary hover:bg-black/[0.04] dark:hover:bg-white/[0.06] disabled:opacity-40 disabled:cursor-not-allowed"
                                                        >
                                                            <Download className={`h-4 w-4 ${downloadingNames.has(demo.name) ? 'animate-pulse' : ''}`} strokeWidth={2} />
                                                        </button>
                                                    </td>
                                                </tr>
                                            ))}
                                        </React.Fragment>
                                    );
                                })}
                            </tbody>
                        </table>
                    )}
                </div>

                {!isLoading && !error && displayRows.length > 0 && totalPages > 1 && (
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
