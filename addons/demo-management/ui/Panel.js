const runtime = typeof window !== "undefined" ? window.__qlsm : void 0;
if (!runtime || !runtime.react || !runtime.ui) {
  throw new Error(
    "demo-management: window.__qlsm.react is not published. This bundle only runs inside QLSM, which publishes its React and UI kit before mounting an addon component."
  );
}
const React = runtime.react;
const {
  Fragment,
  createElement,
  useCallback,
  useEffect,
  useMemo,
  useState
} = React;
const ui = runtime.ui;
function icon(displayName, children) {
  const Icon = ({ className, strokeWidth = 2, ...rest }) => /* @__PURE__ */ React.createElement(
    "svg",
    {
      xmlns: "http://www.w3.org/2000/svg",
      width: "24",
      height: "24",
      viewBox: "0 0 24 24",
      fill: "none",
      stroke: "currentColor",
      strokeWidth,
      strokeLinecap: "round",
      strokeLinejoin: "round",
      className,
      "aria-hidden": "true",
      ...rest
    },
    children
  );
  Icon.displayName = displayName;
  return Icon;
}
const X = icon("X", /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("path", { d: "M18 6 6 18" }), /* @__PURE__ */ React.createElement("path", { d: "m6 6 12 12" })));
const RefreshCw = icon("RefreshCw", /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("path", { d: "M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8" }), /* @__PURE__ */ React.createElement("path", { d: "M21 3v5h-5" }), /* @__PURE__ */ React.createElement("path", { d: "M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16" }), /* @__PURE__ */ React.createElement("path", { d: "M8 16H3v5" })));
const Film = icon("Film", /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("rect", { width: "20", height: "20", x: "2", y: "2", rx: "2.18", ry: "2.18" }), /* @__PURE__ */ React.createElement("line", { x1: "7", x2: "7", y1: "2", y2: "22" }), /* @__PURE__ */ React.createElement("line", { x1: "17", x2: "17", y1: "2", y2: "22" }), /* @__PURE__ */ React.createElement("line", { x1: "2", x2: "22", y1: "12", y2: "12" }), /* @__PURE__ */ React.createElement("line", { x1: "2", x2: "7", y1: "7", y2: "7" }), /* @__PURE__ */ React.createElement("line", { x1: "2", x2: "7", y1: "17", y2: "17" }), /* @__PURE__ */ React.createElement("line", { x1: "17", x2: "22", y1: "17", y2: "17" }), /* @__PURE__ */ React.createElement("line", { x1: "17", x2: "22", y1: "7", y2: "7" })));
const AlertCircle = icon("AlertCircle", /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("circle", { cx: "12", cy: "12", r: "10" }), /* @__PURE__ */ React.createElement("line", { x1: "12", x2: "12", y1: "8", y2: "12" }), /* @__PURE__ */ React.createElement("line", { x1: "12", x2: "12.01", y1: "16", y2: "16" })));
const FolderOpen = icon("FolderOpen", /* @__PURE__ */ React.createElement("path", { d: "m6 14 1.5-2.9A2 2 0 0 1 9.24 10H20a2 2 0 0 1 1.94 2.5l-1.54 6a2 2 0 0 1-1.95 1.5H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h3.9a2 2 0 0 1 1.69.9l.81 1.2a2 2 0 0 0 1.67.9H18a2 2 0 0 1 2 2v2" }));
const Download = icon("Download", /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("path", { d: "M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" }), /* @__PURE__ */ React.createElement("polyline", { points: "7 10 12 15 17 10" }), /* @__PURE__ */ React.createElement("line", { x1: "12", x2: "12", y1: "15", y2: "3" })));
const Search = icon("Search", /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("circle", { cx: "11", cy: "11", r: "8" }), /* @__PURE__ */ React.createElement("path", { d: "m21 21-4.3-4.3" })));
const ChevronRight = icon("ChevronRight", /* @__PURE__ */ React.createElement("path", { d: "m9 18 6-6-6-6" }));
const ChevronDown = icon("ChevronDown", /* @__PURE__ */ React.createElement("path", { d: "m6 9 6 6 6-6" }));
function parseRoute(route) {
  if (typeof route !== "string" || !route.trim()) return null;
  const trimmed = route.trim();
  const match = trimmed.match(/^(GET|POST|PUT|PATCH|DELETE)\s+(.*)$/i);
  if (match) return { method: match[1].toUpperCase(), path: match[2].trim() };
  return { method: "GET", path: trimmed };
}
function fillPath(path, { scope, scopeId } = {}) {
  if (typeof path !== "string") return "";
  const values = {
    scope_id: scopeId,
    host_id: scope === "host" ? scopeId : void 0,
    instance_id: scope === "instance" ? scopeId : void 0
  };
  return path.replace(/\{(\w+)\}/g, (whole, key) => {
    const value = values[key];
    return value === void 0 || value === null ? whole : String(value);
  });
}
const { Modal } = ui;
function formatBytes(bytes) {
  if (!Number.isFinite(bytes)) return "—";
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB"];
  let value = bytes / 1024;
  let unitIndex = 0;
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }
  return `${value.toFixed(1)} ${units[unitIndex]}`;
}
function formatMtime(mtime) {
  if (!Number.isFinite(mtime)) return "—";
  return new Date(mtime * 1e3).toLocaleString();
}
function triggerBlobDownload(blob, filename) {
  const url = window.URL.createObjectURL(blob);
  const a = document.createElement("a");
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
  const [matches, setMatches] = React.useState([]);
  const [isLoading, setIsLoading] = React.useState(false);
  const [error, setError] = React.useState(null);
  const [filterText, setFilterText] = React.useState("");
  const [dateFrom, setDateFrom] = React.useState("");
  const [dateTo, setDateTo] = React.useState("");
  const [page, setPage] = React.useState(1);
  const [selected, setSelected] = React.useState(() => /* @__PURE__ */ new Set());
  const [downloadingNames, setDownloadingNames] = React.useState(() => /* @__PURE__ */ new Set());
  const [isBatchDownloading, setIsBatchDownloading] = React.useState(false);
  const [downloadError, setDownloadError] = React.useState(null);
  const [selectedGroupIds, setSelectedGroupIds] = React.useState(() => /* @__PURE__ */ new Set());
  const [expandedGroupIds, setExpandedGroupIds] = React.useState(() => /* @__PURE__ */ new Set());
  const [busyGroupActionKey, setBusyGroupActionKey] = React.useState(null);
  const [groupActionError, setGroupActionError] = React.useState(null);
  const fetchDemos = React.useCallback(async () => {
    var _a;
    if (!(instance == null ? void 0 : instance.id)) return;
    setIsLoading(true);
    setError(null);
    try {
      const data = await api.list(instance.id);
      setDemos(data.demos || []);
      setMatches(Array.isArray(data.matches) ? data.matches : []);
    } catch (err) {
      console.error("Error listing demos:", err);
      setError((err == null ? void 0 : err.message) || ((_a = err == null ? void 0 : err.error) == null ? void 0 : _a.message) || "Failed to list demos from the remote server.");
      setDemos([]);
      setMatches([]);
    } finally {
      setIsLoading(false);
    }
  }, [instance == null ? void 0 : instance.id]);
  React.useEffect(() => {
    if (isOpen && (instance == null ? void 0 : instance.id)) {
      fetchDemos();
    } else {
      setDemos([]);
      setMatches([]);
      setError(null);
      setFilterText("");
      setDateFrom("");
      setDateTo("");
      setPage(1);
      setSelected(/* @__PURE__ */ new Set());
      setDownloadingNames(/* @__PURE__ */ new Set());
      setDownloadError(null);
      setSelectedGroupIds(/* @__PURE__ */ new Set());
      setExpandedGroupIds(/* @__PURE__ */ new Set());
      setGroupActionError(null);
    }
  }, [isOpen, instance == null ? void 0 : instance.id, fetchDemos]);
  const filterTerms = React.useMemo(
    () => filterText.trim().toLowerCase().split(/\s+/).filter(Boolean),
    [filterText]
  );
  const matchesTerms = React.useCallback(
    (name) => {
      const lower = name.toLowerCase();
      return filterTerms.every((term) => lower.includes(term));
    },
    [filterTerms]
  );
  const dateFromTs = dateFrom ? (/* @__PURE__ */ new Date(`${dateFrom}T00:00:00`)).getTime() / 1e3 : null;
  const dateToTs = dateTo ? (/* @__PURE__ */ new Date(`${dateTo}T00:00:00`)).getTime() / 1e3 + 86400 : null;
  const matchesDateRange = React.useCallback(
    (mtime) => (dateFromTs === null || mtime >= dateFromTs) && (dateToTs === null || mtime < dateToTs),
    [dateFromTs, dateToTs]
  );
  const filteredDemos = React.useMemo(
    () => demos.filter((d) => matchesTerms(d.name) && matchesDateRange(d.mtime || 0)),
    [demos, matchesTerms, matchesDateRange]
  );
  React.useEffect(() => {
    const visible = new Set(filteredDemos.map((d) => d.name));
    setSelected((prev) => {
      const next = new Set([...prev].filter((name) => visible.has(name)));
      return next.size === prev.size ? prev : next;
    });
  }, [demos]);
  const allFilteredSelected = filteredDemos.length > 0 && filteredDemos.every((d) => selected.has(d.name));
  const toggleSelectAll = () => {
    setSelected((prev) => {
      if (allFilteredSelected) {
        const next2 = new Set(prev);
        filteredDemos.forEach((d) => next2.delete(d.name));
        return next2;
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
  const displayRows = React.useMemo(() => {
    const demoByName = new Map(demos.map((d) => [d.name, d]));
    const grouped = /* @__PURE__ */ new Set();
    matches.forEach((m) => (m.member_names || []).forEach((n) => grouped.add(n)));
    const rows = [];
    matches.forEach((group) => {
      const members = (group.member_names || []).map((name) => demoByName.get(name)).filter(Boolean);
      if (!members.length) return;
      if (!members.some((d) => matchesTerms(d.name) && matchesDateRange(d.mtime || 0))) return;
      members.sort((a, b) => (b.mtime || 0) - (a.mtime || 0));
      rows.push({ type: "group", group, members, mtime: members[0].mtime || 0 });
    });
    demos.forEach((demo) => {
      if (grouped.has(demo.name)) return;
      if (!matchesTerms(demo.name) || !matchesDateRange(demo.mtime || 0)) return;
      rows.push({ type: "demo", demo, mtime: demo.mtime || 0 });
    });
    rows.sort((a, b) => b.mtime - a.mtime);
    return rows;
  }, [demos, matches, matchesTerms, matchesDateRange]);
  const totalPages = Math.max(1, Math.ceil(displayRows.length / PAGE_SIZE));
  const pagedRows = React.useMemo(
    () => displayRows.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE),
    [displayRows, page]
  );
  React.useEffect(() => {
    setPage((prev) => Math.min(prev, totalPages));
  }, [totalPages]);
  React.useEffect(() => {
    setPage(1);
  }, [filterTerms, dateFromTs, dateToTs]);
  const visibleGroupIds = React.useMemo(
    () => new Set(displayRows.filter((r) => r.type === "group").map((r) => r.group.group_id)),
    [displayRows]
  );
  React.useEffect(() => {
    setSelectedGroupIds((prev) => {
      const next = new Set([...prev].filter((id) => visibleGroupIds.has(id)));
      return next.size === prev.size ? prev : next;
    });
  }, [visibleGroupIds]);
  const bulkGroupActions = React.useMemo(() => {
    const selectedGroups = matches.filter((m) => selectedGroupIds.has(m.group_id));
    if (selectedGroups.length === 0) return [];
    const byId = /* @__PURE__ */ new Map();
    selectedGroups.forEach((group) => {
      (group.actions || []).forEach((action) => {
        if (!action.bulk) return;
        if (!byId.has(action.id)) {
          byId.set(action.id, { action, addonId: group.addon_id, qlmatchNames: [] });
        }
        byId.get(action.id).qlmatchNames.push(group.qlmatch_name);
      });
    });
    return [...byId.values()].filter((entry) => entry.qlmatchNames.length === selectedGroups.length);
  }, [matches, selectedGroupIds]);
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
      row.members.forEach((d) => selecting ? next.add(d.name) : next.delete(d.name));
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
    var _a;
    const spec = action.action;
    if (spec.confirm && !window.confirm(spec.confirm)) return;
    const key = `${action.id}:${group.group_id}`;
    setBusyGroupActionKey(key);
    setGroupActionError(null);
    try {
      const resolved = parseRoute(`${spec.method} ${spec.route}`);
      const path = fillPath(resolved.path, { scope: "instance", scopeId: instance.id });
      await api.runAction(group.addon_id, resolved.method, path);
    } catch (err) {
      console.error("Error running match action:", err);
      setGroupActionError(
        (err == null ? void 0 : err.message) || ((_a = err == null ? void 0 : err.error) == null ? void 0 : _a.message) || `Failed to run "${action.label}" for ${group.label}.`
      );
    } finally {
      setBusyGroupActionKey(null);
    }
  };
  const runBulkGroupAction = async (entry) => {
    var _a, _b;
    const confirmText = (_a = entry.action.action) == null ? void 0 : _a.confirm;
    if (confirmText && !window.confirm(confirmText)) return;
    const key = `bulk:${entry.action.id}`;
    setBusyGroupActionKey(key);
    setGroupActionError(null);
    try {
      const resolved = parseRoute(`${entry.action.bulk.method} ${entry.action.bulk.route}`);
      const path = fillPath(resolved.path, { scope: "instance", scopeId: instance.id });
      const selectionKey = entry.action.bulk.selection_key || "selected";
      await api.runAction(entry.addonId, resolved.method, path, { [selectionKey]: entry.qlmatchNames });
      setSelectedGroupIds(/* @__PURE__ */ new Set());
    } catch (err) {
      console.error("Error running bulk match action:", err);
      setGroupActionError((err == null ? void 0 : err.message) || ((_b = err == null ? void 0 : err.error) == null ? void 0 : _b.message) || `Failed to run "${entry.action.label}".`);
    } finally {
      setBusyGroupActionKey(null);
    }
  };
  const downloadOne = async (name) => {
    var _a;
    setDownloadError(null);
    setDownloadingNames((prev) => new Set(prev).add(name));
    try {
      const blob = await api.downloadOne(instance.id, name);
      triggerBlobDownload(blob, name);
    } catch (err) {
      console.error("Error downloading demo:", err);
      setDownloadError((err == null ? void 0 : err.message) || ((_a = err == null ? void 0 : err.error) == null ? void 0 : _a.message) || `Failed to download ${name}.`);
    } finally {
      setDownloadingNames((prev) => {
        const next = new Set(prev);
        next.delete(name);
        return next;
      });
    }
  };
  const downloadSelected = async () => {
    var _a;
    if (selected.size === 0) return;
    setDownloadError(null);
    setIsBatchDownloading(true);
    try {
      const names = [...selected];
      const blob = await api.downloadBatch(instance.id, names);
      const safeName = ((instance == null ? void 0 : instance.name) || "instance").replace(/[^A-Za-z0-9._-]+/g, "-");
      triggerBlobDownload(blob, `${safeName}-demos.zip`);
    } catch (err) {
      console.error("Error batch-downloading demos:", err);
      setDownloadError((err == null ? void 0 : err.message) || ((_a = err == null ? void 0 : err.error) == null ? void 0 : _a.message) || "Failed to download selected demos.");
    } finally {
      setIsBatchDownloading(false);
    }
  };
  return /* @__PURE__ */ React.createElement(
    Modal,
    {
      isOpen,
      onClose,
      size: "2xl",
      height: "75vh",
      icon: /* @__PURE__ */ React.createElement("div", { className: "demos-addon-icon-wrapper" }, /* @__PURE__ */ React.createElement("div", { className: "demos-addon-icon-glow" }), /* @__PURE__ */ React.createElement(Film, { className: "demos-addon-icon", strokeWidth: 2.5 })),
      title: /* @__PURE__ */ React.createElement(React.Fragment, null, "Demos", /* @__PURE__ */ React.createElement("span", { className: "mt-0.5 block font-mono text-xs font-normal normal-case tracking-normal text-theme-secondary" }, instance == null ? void 0 : instance.name, " ", /* @__PURE__ */ React.createElement("span", { className: "text-theme-muted" }, "•"), " Port ", instance == null ? void 0 : instance.port, " ", /* @__PURE__ */ React.createElement("span", { className: "text-theme-muted" }, "•"), " demos/ on disk")),
      headerActions: /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement(
        "button",
        {
          onClick: fetchDemos,
          disabled: isLoading,
          className: "demos-addon-btn"
        },
        /* @__PURE__ */ React.createElement(RefreshCw, { className: `h-4 w-4 ${isLoading ? "animate-spin" : ""}`, strokeWidth: 2 }),
        /* @__PURE__ */ React.createElement("span", null, "Refresh")
      ), /* @__PURE__ */ React.createElement(
        "button",
        {
          onClick: onClose,
          className: "demos-addon-close-btn"
        },
        /* @__PURE__ */ React.createElement(X, { className: "h-5 w-5", strokeWidth: 2 })
      ))
    },
    /* @__PURE__ */ React.createElement("div", { className: "flex h-full flex-col" }, !isLoading && !error && demos.length > 0 && /* @__PURE__ */ React.createElement("div", { className: "flex flex-shrink-0 items-center gap-3 border-b border-theme pb-3 mb-3" }, /* @__PURE__ */ React.createElement("div", { className: "relative flex-1 max-w-xs" }, /* @__PURE__ */ React.createElement(Search, { className: "demo-search-icon absolute top-1/2 -translate-y-1/2 text-theme-muted" }), /* @__PURE__ */ React.createElement(
      "input",
      {
        type: "text",
        value: filterText,
        onChange: (e) => setFilterText(e.target.value),
        placeholder: "Filter by filename (space-separated terms)...",
        className: "w-full pl-8 pr-3 py-1.5 text-sm font-mono rounded-md bg-theme-base border border-theme-strong text-theme-primary placeholder:text-theme-muted focus:outline-none focus:ring-1 focus:ring-[var(--accent-primary)]"
      }
    )), /* @__PURE__ */ React.createElement("div", { className: "flex items-center gap-1.5" }, /* @__PURE__ */ React.createElement(
      "input",
      {
        type: "date",
        value: dateFrom,
        onChange: (e) => setDateFrom(e.target.value),
        max: dateTo || void 0,
        "aria-label": "Recorded from date",
        className: "py-1.5 px-2 text-sm font-mono rounded-md bg-theme-base border border-theme-strong text-theme-primary focus:outline-none focus:ring-1 focus:ring-[var(--accent-primary)]"
      }
    ), /* @__PURE__ */ React.createElement("span", { className: "text-theme-muted text-xs" }, "to"), /* @__PURE__ */ React.createElement(
      "input",
      {
        type: "date",
        value: dateTo,
        onChange: (e) => setDateTo(e.target.value),
        min: dateFrom || void 0,
        "aria-label": "Recorded to date",
        className: "py-1.5 px-2 text-sm font-mono rounded-md bg-theme-base border border-theme-strong text-theme-primary focus:outline-none focus:ring-1 focus:ring-[var(--accent-primary)]"
      }
    )), /* @__PURE__ */ React.createElement("span", { className: "text-xs font-mono text-theme-muted whitespace-nowrap" }, filteredDemos.length, " of ", demos.length), /* @__PURE__ */ React.createElement("div", { className: "flex-1" }), bulkGroupActions.map((entry) => /* @__PURE__ */ React.createElement(
      "button",
      {
        key: entry.action.id,
        onClick: () => runBulkGroupAction(entry),
        disabled: busyGroupActionKey !== null,
        className: "demos-addon-btn disabled:opacity-40 disabled:cursor-not-allowed"
      },
      /* @__PURE__ */ React.createElement(
        RefreshCw,
        {
          className: `h-4 w-4 ${busyGroupActionKey === `bulk:${entry.action.id}` ? "animate-spin" : ""}`,
          strokeWidth: 2
        }
      ),
      /* @__PURE__ */ React.createElement("span", null, entry.action.label, " (", entry.qlmatchNames.length, ")")
    )), /* @__PURE__ */ React.createElement(
      "button",
      {
        onClick: downloadSelected,
        disabled: selected.size === 0 || isBatchDownloading,
        className: "demos-addon-btn disabled:opacity-40 disabled:cursor-not-allowed"
      },
      /* @__PURE__ */ React.createElement(Download, { className: `h-4 w-4 ${isBatchDownloading ? "animate-pulse" : ""}`, strokeWidth: 2 }),
      /* @__PURE__ */ React.createElement("span", null, "Download selected ", selected.size > 0 ? `(${selected.size})` : "")
    )), downloadError && /* @__PURE__ */ React.createElement("div", { className: "flex-shrink-0 pb-2 text-sm text-center", style: { color: "var(--accent-danger)" } }, downloadError), groupActionError && /* @__PURE__ */ React.createElement("div", { className: "flex-shrink-0 pb-2 text-sm text-center", style: { color: "var(--accent-danger)" } }, groupActionError), /* @__PURE__ */ React.createElement("div", { className: "flex-1 overflow-auto" }, isLoading ? /* @__PURE__ */ React.createElement("div", { className: "demos-addon-empty-state" }, /* @__PURE__ */ React.createElement("div", { className: "demos-addon-spinner-wrapper" }, /* @__PURE__ */ React.createElement(RefreshCw, { className: "demos-addon-spinner", strokeWidth: 2 })), /* @__PURE__ */ React.createElement("p", { className: "font-mono text-sm text-theme-secondary uppercase tracking-wide" }, "Listing demos on remote server...")) : error ? /* @__PURE__ */ React.createElement("div", { className: "demos-addon-error-state" }, /* @__PURE__ */ React.createElement(AlertCircle, { className: "h-10 w-10 mb-4", style: { color: "var(--accent-danger)" }, strokeWidth: 2 }), /* @__PURE__ */ React.createElement("p", { className: "font-display text-lg font-bold uppercase tracking-wide", style: { color: "var(--accent-danger)" } }, "Error Listing Demos"), /* @__PURE__ */ React.createElement("p", { className: "text-sm text-theme-secondary mt-2 max-w-md text-center" }, error), /* @__PURE__ */ React.createElement(
      "button",
      {
        onClick: fetchDemos,
        className: "demos-addon-retry-btn"
      },
      "Try Again"
    )) : demos.length === 0 ? /* @__PURE__ */ React.createElement("div", { className: "demos-addon-empty-state" }, /* @__PURE__ */ React.createElement(FolderOpen, { className: "h-10 w-10 mb-4 text-theme-muted", strokeWidth: 2 }), /* @__PURE__ */ React.createElement("p", { className: "font-display text-base font-bold uppercase tracking-wide text-theme-primary" }, "No demos found"), /* @__PURE__ */ React.createElement("p", { className: "text-sm text-theme-secondary mt-2 max-w-md text-center" }, `No .dm_91, .qlmatch or .replay.json.gz files in this instance's demos/ directory. Recording needs sv_demoRecord 1 (add sv_demoCut 1 for match-cut demos and .qlmatch packing) — check View MinQLX Logs / View Server Logs for "demo:" lines after a manual test.`)) : displayRows.length === 0 ? /* @__PURE__ */ React.createElement("div", { className: "demos-addon-empty-state" }, /* @__PURE__ */ React.createElement(Search, { className: "h-10 w-10 mb-4 text-theme-muted", strokeWidth: 2 }), /* @__PURE__ */ React.createElement("p", { className: "text-sm text-theme-secondary" }, 'No demos match "', filterText, '".')) : /* @__PURE__ */ React.createElement("table", { className: "w-full text-sm" }, /* @__PURE__ */ React.createElement("thead", null, /* @__PURE__ */ React.createElement("tr", { className: "text-left text-theme-muted uppercase text-xs tracking-wide border-b border-theme" }, /* @__PURE__ */ React.createElement("th", { className: "py-2 pr-2 w-8" }, /* @__PURE__ */ React.createElement(
      "input",
      {
        type: "checkbox",
        checked: allFilteredSelected,
        onChange: toggleSelectAll,
        "aria-label": "Select all demos"
      }
    )), /* @__PURE__ */ React.createElement("th", { className: "py-2 pr-4 font-medium" }, "File"), /* @__PURE__ */ React.createElement("th", { className: "py-2 pr-4 font-medium" }, "Size"), /* @__PURE__ */ React.createElement("th", { className: "py-2 pr-4 font-medium" }, "Recorded"), /* @__PURE__ */ React.createElement("th", { className: "py-2 pr-2 w-10" }))), /* @__PURE__ */ React.createElement("tbody", null, pagedRows.map((row) => {
      if (row.type === "demo") {
        return /* @__PURE__ */ React.createElement("tr", { key: row.demo.name, className: "border-b border-theme/50 hover:bg-black/[0.02] dark:hover:bg-white/[0.02]" }, /* @__PURE__ */ React.createElement("td", { className: "py-2 pr-2" }, /* @__PURE__ */ React.createElement(
          "input",
          {
            type: "checkbox",
            checked: selected.has(row.demo.name),
            onChange: () => toggleSelectOne(row.demo.name),
            "aria-label": `Select ${row.demo.name}`
          }
        )), /* @__PURE__ */ React.createElement("td", { className: "py-2 pr-4 font-mono text-theme-primary break-all" }, row.demo.name), /* @__PURE__ */ React.createElement("td", { className: "py-2 pr-4 font-mono text-theme-secondary whitespace-nowrap" }, formatBytes(row.demo.size)), /* @__PURE__ */ React.createElement("td", { className: "py-2 pr-4 font-mono text-theme-secondary whitespace-nowrap" }, formatMtime(row.demo.mtime)), /* @__PURE__ */ React.createElement("td", { className: "py-2 pr-2" }, /* @__PURE__ */ React.createElement(
          "button",
          {
            onClick: () => downloadOne(row.demo.name),
            disabled: downloadingNames.has(row.demo.name),
            title: `Download ${row.demo.name}`,
            "aria-label": `Download ${row.demo.name}`,
            className: "p-1.5 rounded-md text-theme-muted hover:text-theme-primary hover:bg-black/[0.04] dark:hover:bg-white/[0.06] disabled:opacity-40 disabled:cursor-not-allowed"
          },
          /* @__PURE__ */ React.createElement(Download, { className: `h-4 w-4 ${downloadingNames.has(row.demo.name) ? "animate-pulse" : ""}`, strokeWidth: 2 })
        )));
      }
      const { group, members } = row;
      const isExpanded = expandedGroupIds.has(group.group_id);
      const newest = members[0];
      const totalSize = members.reduce((sum, d) => sum + (d.size || 0), 0);
      return /* @__PURE__ */ React.createElement(React.Fragment, { key: `group-${group.group_id}` }, /* @__PURE__ */ React.createElement("tr", { className: "border-b border-theme/50 bg-black/[0.02] dark:bg-white/[0.03]" }, /* @__PURE__ */ React.createElement("td", { className: "py-2 pr-2" }, /* @__PURE__ */ React.createElement(
        "input",
        {
          type: "checkbox",
          checked: selectedGroupIds.has(group.group_id),
          onChange: () => toggleSelectGroup(row),
          "aria-label": `Select match ${group.label}`
        }
      )), /* @__PURE__ */ React.createElement("td", { className: "py-2 pr-4 font-mono text-theme-primary break-all" }, /* @__PURE__ */ React.createElement(
        "button",
        {
          onClick: () => toggleExpandGroup(group.group_id),
          "aria-expanded": isExpanded,
          title: isExpanded ? "Hide the files in this match" : "Show the files in this match",
          className: "flex items-center gap-1.5 text-left hover:text-[var(--accent-primary)]"
        },
        isExpanded ? /* @__PURE__ */ React.createElement(ChevronDown, { className: "h-4 w-4 flex-shrink-0", strokeWidth: 2 }) : /* @__PURE__ */ React.createElement(ChevronRight, { className: "h-4 w-4 flex-shrink-0", strokeWidth: 2 }),
        /* @__PURE__ */ React.createElement("span", null, group.label),
        /* @__PURE__ */ React.createElement("span", { className: "text-theme-muted" }, "(", members.length, " file", members.length === 1 ? "" : "s", ")")
      )), /* @__PURE__ */ React.createElement("td", { className: "py-2 pr-4 font-mono text-theme-secondary whitespace-nowrap" }, formatBytes(totalSize)), /* @__PURE__ */ React.createElement("td", { className: "py-2 pr-4 font-mono text-theme-secondary whitespace-nowrap" }, formatMtime(newest.mtime)), /* @__PURE__ */ React.createElement("td", { className: "py-2 pr-2" }, /* @__PURE__ */ React.createElement("div", { className: "flex items-center gap-1" }, (group.actions || []).map((action) => {
        const busyKey = `${action.id}:${group.group_id}`;
        return /* @__PURE__ */ React.createElement(
          "button",
          {
            key: action.id,
            onClick: () => runGroupAction(group, action),
            disabled: busyGroupActionKey !== null,
            title: action.label,
            "aria-label": `${action.label} for ${group.label}`,
            className: "p-1.5 rounded-md text-theme-muted hover:text-theme-primary hover:bg-black/[0.04] dark:hover:bg-white/[0.06] disabled:opacity-40 disabled:cursor-not-allowed",
            style: action.danger ? { color: "var(--accent-danger)" } : void 0
          },
          /* @__PURE__ */ React.createElement(
            RefreshCw,
            {
              className: `h-4 w-4 ${busyGroupActionKey === busyKey ? "animate-spin" : ""}`,
              strokeWidth: 2
            }
          )
        );
      })))), isExpanded && members.map((demo) => /* @__PURE__ */ React.createElement("tr", { key: demo.name, className: "border-b border-theme/50 hover:bg-black/[0.02] dark:hover:bg-white/[0.02]" }, /* @__PURE__ */ React.createElement("td", { className: "py-2 pr-2" }, /* @__PURE__ */ React.createElement(
        "input",
        {
          type: "checkbox",
          checked: selected.has(demo.name),
          onChange: () => toggleSelectOne(demo.name),
          "aria-label": `Select ${demo.name}`
        }
      )), /* @__PURE__ */ React.createElement("td", { className: "py-2 pr-4 pl-6 font-mono text-theme-secondary break-all text-xs" }, demo.name), /* @__PURE__ */ React.createElement("td", { className: "py-2 pr-4 font-mono text-theme-secondary whitespace-nowrap" }, formatBytes(demo.size)), /* @__PURE__ */ React.createElement("td", { className: "py-2 pr-4 font-mono text-theme-secondary whitespace-nowrap" }, formatMtime(demo.mtime)), /* @__PURE__ */ React.createElement("td", { className: "py-2 pr-2" }, /* @__PURE__ */ React.createElement(
        "button",
        {
          onClick: () => downloadOne(demo.name),
          disabled: downloadingNames.has(demo.name),
          title: `Download ${demo.name}`,
          "aria-label": `Download ${demo.name}`,
          className: "p-1.5 rounded-md text-theme-muted hover:text-theme-primary hover:bg-black/[0.04] dark:hover:bg-white/[0.06] disabled:opacity-40 disabled:cursor-not-allowed"
        },
        /* @__PURE__ */ React.createElement(Download, { className: `h-4 w-4 ${downloadingNames.has(demo.name) ? "animate-pulse" : ""}`, strokeWidth: 2 })
      )))));
    })))), !isLoading && !error && displayRows.length > 0 && totalPages > 1 && /* @__PURE__ */ React.createElement("div", { className: "flex flex-shrink-0 items-center justify-center gap-3 border-t border-theme pt-3 mt-3" }, /* @__PURE__ */ React.createElement(
      "button",
      {
        onClick: () => setPage((p) => Math.max(1, p - 1)),
        disabled: page <= 1,
        className: "demos-addon-btn disabled:opacity-40 disabled:cursor-not-allowed"
      },
      "Prev"
    ), /* @__PURE__ */ React.createElement("span", { className: "text-xs font-mono text-theme-muted whitespace-nowrap" }, "Page ", page, " of ", totalPages), /* @__PURE__ */ React.createElement(
      "button",
      {
        onClick: () => setPage((p) => Math.min(totalPages, p + 1)),
        disabled: page >= totalPages,
        className: "demos-addon-btn disabled:opacity-40 disabled:cursor-not-allowed"
      },
      "Next"
    )))
  );
}
function Panel({ ctx }) {
  const modal = (ctx == null ? void 0 : ctx.modal) || {};
  const api = React.useMemo(() => ({
    list: (instanceId) => ctx.api("GET", `instances/${instanceId}/demos`),
    downloadOne: async (instanceId, name) => {
      const { blob } = await ctx.download(
        "GET",
        `instances/${instanceId}/demos/download?filename=${encodeURIComponent(name)}`,
        { fallbackName: name }
      );
      return blob;
    },
    downloadBatch: async (instanceId, names) => {
      const { blob } = await ctx.download(
        "POST",
        `instances/${instanceId}/demos/download-batch`,
        { data: { filenames: names }, fallbackName: "demos.zip" }
      );
      return blob;
    },
    // Match-group actions (e.g. qlmatch-packer's Rebuild buttons) are
    // contributed by another addon via the demo_management.match_groups
    // hook and carry their own `addon_id` + relative route -- this addon
    // has no idea what the action does, only how to call it.
    runAction: (addonId, method, path, data) => ctx.apiFor(addonId)(method, path, { data })
  }), [ctx]);
  return /* @__PURE__ */ React.createElement(
    ViewDemosModal,
    {
      isOpen: Boolean(modal.isOpen),
      onClose: modal.onClose,
      instance: modal.entity,
      api
    }
  );
}
export {
  Panel as default
};
