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
const DATE_PRESETS = [
  { id: "all", label: "All" },
  { id: "today", label: "Today" },
  { id: "yesterday", label: "Yesterday" },
  { id: "7d", label: "7 days" },
  { id: "30d", label: "30 days" },
  { id: "custom", label: "Range" }
];
const KIND_FILTERS = [
  { id: "all", label: "All rows" },
  { id: "matches", label: "Matches" },
  { id: "packed", label: "Packed" },
  { id: "unpacked", label: "Not packed" },
  { id: "loose", label: "Loose files" }
];
const SORTS = [
  { id: "newest", label: "Newest first" },
  { id: "oldest", label: "Oldest first" },
  { id: "largest", label: "Largest first" },
  { id: "map", label: "Map A–Z" }
];
const DAY = 86400;
function isoToSeconds(iso) {
  if (!iso) return null;
  const ms = Date.parse(iso);
  return Number.isFinite(ms) ? ms / 1e3 : null;
}
function kindOf(demo) {
  if (demo.kind) return demo.kind;
  const name = (demo.name || "").toLowerCase();
  if (name.endsWith(".replay.json.gz")) return "replay";
  if (name.endsWith(".qlmatch")) return "pack";
  if (name.endsWith(".dm_91")) return "pov";
  return "other";
}
function countKinds(files) {
  const kinds = { pov: 0, pack: 0, replay: 0, other: 0 };
  files.forEach((d) => {
    const kind = kindOf(d);
    kinds[kind in kinds ? kind : "other"] += 1;
  });
  return kinds;
}
function playingPlayers(info) {
  return ((info == null ? void 0 : info.players) || []).filter((p) => p && p.name && p.team !== "3");
}
function playersLabel(info, max = 4) {
  const players = playingPlayers(info);
  if (!players.length) return "";
  const red = players.filter((p) => p.team === "1").map((p) => p.name);
  const blue = players.filter((p) => p.team === "2").map((p) => p.name);
  const short = (names2) => names2.length > max ? `${names2.slice(0, max).join(", ")} +${names2.length - max}` : names2.join(", ");
  if (red.length && blue.length) return `${short(red)} vs ${short(blue)}`;
  const names = players.map((p) => p.name);
  if (names.length === 2) return `${names[0]} vs ${names[1]}`;
  return short(names);
}
function buildRows(demos, matches) {
  const demoByName = new Map(demos.map((d) => [d.name, d]));
  const grouped = /* @__PURE__ */ new Set();
  const rows = [];
  matches.forEach((group) => {
    const members = (group.member_names || []).map((name) => demoByName.get(name)).filter(Boolean);
    if (!members.length) return;
    members.forEach((d) => grouped.add(d.name));
    members.sort((a, b) => (b.mtime || 0) - (a.mtime || 0));
    const info = group.info || {};
    const newest = members[0].mtime || 0;
    rows.push({
      type: "group",
      key: `group-${group.group_id}`,
      group,
      members,
      info,
      when: isoToSeconds(info.started_at) ?? newest,
      size: members.reduce((sum, d) => sum + (d.size || 0), 0),
      kinds: countKinds(members),
      haystack: [
        ...members.map((d) => d.name),
        info.map,
        info.gametype,
        info.match_id,
        group.label,
        ...playingPlayers(info).map((p) => p.name)
      ].filter(Boolean).join(" ").toLowerCase()
    });
  });
  demos.forEach((demo) => {
    var _a, _b;
    if (grouped.has(demo.name)) return;
    const info = {
      match_id: demo.match_id,
      map: demo.map,
      started_at: demo.started_at,
      players: ((_a = demo.pov) == null ? void 0 : _a.player) ? [{ name: demo.pov.player, team: "" }] : []
    };
    rows.push({
      type: "demo",
      key: demo.name,
      demo,
      members: [demo],
      info,
      when: isoToSeconds(demo.started_at) ?? (demo.mtime || 0),
      size: demo.size || 0,
      kinds: countKinds([demo]),
      haystack: [demo.name, demo.map, (_b = demo.pov) == null ? void 0 : _b.player].filter(Boolean).join(" ").toLowerCase()
    });
  });
  return rows;
}
function startOfLocalDay(seconds) {
  const d = new Date(seconds * 1e3);
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime() / 1e3;
}
function localDateToSeconds(value) {
  if (!value) return null;
  const [y, m, d] = value.split("-").map(Number);
  if (!y || !m || !d) return null;
  return new Date(y, m - 1, d).getTime() / 1e3;
}
function dateRange(preset, nowSeconds2, customFrom, customTo) {
  const today = startOfLocalDay(nowSeconds2);
  switch (preset) {
    case "today":
      return [today, null];
    case "yesterday":
      return [startOfLocalDay(today - DAY / 2), today];
    case "7d":
      return [startOfLocalDay(today - 6 * DAY + DAY / 2), null];
    case "30d":
      return [startOfLocalDay(today - 29 * DAY + DAY / 2), null];
    case "custom": {
      const from = localDateToSeconds(customFrom);
      const to = localDateToSeconds(customTo);
      return [from, to === null ? null : startOfLocalDay(to + DAY + DAY / 2)];
    }
    default:
      return [null, null];
  }
}
function packingInUse(rows) {
  return rows.some((r) => r.kinds.pack > 0);
}
function filterRows(rows, filters, nowSeconds2) {
  const terms = (filters.text || "").trim().toLowerCase().split(/\s+/).filter(Boolean);
  const [from, to] = dateRange(filters.datePreset, nowSeconds2, filters.dateFrom, filters.dateTo);
  return rows.filter((row) => {
    if (from !== null && row.when < from) return false;
    if (to !== null && row.when >= to) return false;
    if (filters.map && (row.info.map || "") !== filters.map) return false;
    if (filters.gametype && (row.info.gametype || "") !== filters.gametype) return false;
    switch (filters.kind) {
      case "matches":
        if (row.type !== "group") return false;
        break;
      case "packed":
        if (!row.kinds.pack) return false;
        break;
      case "unpacked":
        if (row.kinds.pack || !row.kinds.pov || !row.info.match_id) return false;
        break;
      case "loose":
        if (row.type !== "demo") return false;
        break;
    }
    return terms.every((term) => row.haystack.includes(term));
  });
}
function sortRows(rows, sort) {
  const sorted = [...rows];
  const byWhen = (a, b) => b.when - a.when;
  switch (sort) {
    case "oldest":
      sorted.sort((a, b) => a.when - b.when);
      break;
    case "largest":
      sorted.sort((a, b) => b.size - a.size || byWhen(a, b));
      break;
    case "map":
      sorted.sort((a, b) => (a.info.map || "￿").localeCompare(b.info.map || "￿") || byWhen(a, b));
      break;
    default:
      sorted.sort(byWhen);
  }
  return sorted;
}
function facets(rows) {
  const count = (key) => {
    const seen = /* @__PURE__ */ new Map();
    rows.forEach((r) => {
      const value = r.info[key];
      if (value) seen.set(value, (seen.get(value) || 0) + 1);
    });
    return [...seen.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).map(([value, n]) => ({ value, count: n }));
  };
  return { maps: count("map"), gametypes: count("gametype") };
}
function dayKey(seconds) {
  return startOfLocalDay(seconds);
}
function formatBytes(bytes) {
  if (!Number.isFinite(bytes)) return "—";
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let value = bytes / 1024;
  let unitIndex = 0;
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }
  return `${value.toFixed(1)} ${units[unitIndex]}`;
}
function formatDuration(ms) {
  if (!Number.isFinite(ms) || ms <= 0) return "";
  const total = Math.round(ms / 1e3);
  const h = Math.floor(total / 3600);
  const m = Math.floor(total % 3600 / 60);
  const s = String(total % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${s}` : `${m}:${s}`;
}
function formatTime(seconds) {
  if (!Number.isFinite(seconds) || seconds <= 0) return "—";
  return new Date(seconds * 1e3).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}
function formatFull(seconds) {
  if (!Number.isFinite(seconds) || seconds <= 0) return "";
  const d = new Date(seconds * 1e3);
  return `${d.toLocaleString()} (${d.toISOString().replace(".000", "")})`;
}
function formatDayLabel(seconds, nowSeconds2) {
  const day = startOfLocalDay(seconds);
  const today = startOfLocalDay(nowSeconds2);
  if (day === today) return "Today";
  if (day === startOfLocalDay(today - DAY / 2)) return "Yesterday";
  const d = new Date(seconds * 1e3);
  const sameYear = d.getFullYear() === new Date(nowSeconds2 * 1e3).getFullYear();
  return d.toLocaleDateString([], {
    weekday: "short",
    day: "numeric",
    month: "long",
    year: sameYear ? void 0 : "numeric"
  });
}
function formatAgo(seconds, nowSeconds2) {
  const diff = Math.max(0, Math.round(nowSeconds2 - seconds));
  if (diff < 10) return "just now";
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)} min ago`;
  if (diff < DAY) return `${Math.floor(diff / 3600)} h ago`;
  return `${Math.floor(diff / DAY)} d ago`;
}
const { Modal } = ui;
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
const listingCache = /* @__PURE__ */ new Map();
const FILTERS_KEY = "qlsm.demo-management.filters.v1";
const DEFAULT_FILTERS = {
  text: "",
  datePreset: "all",
  dateFrom: "",
  dateTo: "",
  map: "",
  gametype: "",
  kind: "all",
  sort: "newest"
};
function loadFilters() {
  try {
    const saved = JSON.parse(window.localStorage.getItem(FILTERS_KEY) || "{}");
    return { ...DEFAULT_FILTERS, ...saved, text: "" };
  } catch {
    return { ...DEFAULT_FILTERS };
  }
}
function saveFilters(filters) {
  try {
    const { text, ...rest } = filters;
    window.localStorage.setItem(FILTERS_KEY, JSON.stringify(rest));
  } catch {
  }
}
const nowSeconds = () => Date.now() / 1e3;
const inputClass = "py-1.5 px-2 text-sm font-mono rounded-md bg-theme-base border border-theme-strong text-theme-primary focus:outline-none focus:ring-1 focus:ring-[var(--accent-primary)]";
const iconButtonClass = "p-1.5 rounded-md text-theme-muted hover:text-theme-primary hover:bg-black/[0.04] dark:hover:bg-white/[0.06] disabled:opacity-40 disabled:cursor-not-allowed";
function Badge({ children, tone = "muted", title }) {
  return /* @__PURE__ */ React.createElement("span", { className: `demos-addon-badge demos-addon-badge-${tone}`, title }, children);
}
function KindBadges({ kinds, packing }) {
  return /* @__PURE__ */ React.createElement(React.Fragment, null, kinds.pov > 0 && /* @__PURE__ */ React.createElement(Badge, { title: "Per-player .dm_91 demos" }, kinds.pov, " POV"), kinds.pack > 0 && /* @__PURE__ */ React.createElement(Badge, { tone: "primary", title: ".qlmatch pack" }, "pack"), kinds.replay > 0 && /* @__PURE__ */ React.createElement(Badge, { tone: "info", title: "Merged .replay.json.gz" }, "replay"), packing && kinds.pov > 0 && kinds.pack === 0 && /* @__PURE__ */ React.createElement(Badge, { tone: "warning", title: "Raw POVs without a .qlmatch pack - packing may have failed" }, "not packed"));
}
function ViewDemosModal({ isOpen, onClose, instance, api }) {
  const [demos, setDemos] = React.useState([]);
  const [matches, setMatches] = React.useState([]);
  const [fetchedAt, setFetchedAt] = React.useState(null);
  const [timing, setTiming] = React.useState(null);
  const [isLoading, setIsLoading] = React.useState(false);
  const [isRefreshing, setIsRefreshing] = React.useState(false);
  const [error, setError] = React.useState(null);
  const [filters, setFilters] = React.useState(loadFilters);
  const [page, setPage] = React.useState(1);
  const [now, setNow] = React.useState(nowSeconds);
  const [selected, setSelected] = React.useState(() => /* @__PURE__ */ new Set());
  const [downloadingNames, setDownloadingNames] = React.useState(() => /* @__PURE__ */ new Set());
  const [isBatchDownloading, setIsBatchDownloading] = React.useState(false);
  const [downloadError, setDownloadError] = React.useState(null);
  const [selectedGroupIds, setSelectedGroupIds] = React.useState(() => /* @__PURE__ */ new Set());
  const [expandedGroupIds, setExpandedGroupIds] = React.useState(() => /* @__PURE__ */ new Set());
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
    var _a;
    if (!(instance == null ? void 0 : instance.id)) return;
    const cached = listingCache.get(instance.id);
    if (cached) setIsRefreshing(true);
    else setIsLoading(true);
    setError(null);
    try {
      const data = await api.list(instance.id);
      listingCache.set(instance.id, data);
      applyListing(data);
    } catch (err) {
      console.error("Error listing demos:", err);
      setError((err == null ? void 0 : err.message) || ((_a = err == null ? void 0 : err.error) == null ? void 0 : _a.message) || "Failed to list demos from the remote server.");
      if (!cached) {
        setDemos([]);
        setMatches([]);
      }
    } finally {
      setIsLoading(false);
      setIsRefreshing(false);
      setNow(nowSeconds());
    }
  }, [instance == null ? void 0 : instance.id]);
  React.useEffect(() => {
    if (isOpen && (instance == null ? void 0 : instance.id)) {
      const cached = listingCache.get(instance.id);
      if (cached) applyListing(cached);
      fetchDemos();
    } else {
      setDemos([]);
      setMatches([]);
      setFetchedAt(null);
      setTiming(null);
      setError(null);
      setFilters((prev) => ({ ...prev, text: "" }));
      setPage(1);
      setSelected(/* @__PURE__ */ new Set());
      setDownloadingNames(/* @__PURE__ */ new Set());
      setDownloadError(null);
      setSelectedGroupIds(/* @__PURE__ */ new Set());
      setExpandedGroupIds(/* @__PURE__ */ new Set());
      setGroupActionError(null);
    }
  }, [isOpen, instance == null ? void 0 : instance.id, fetchDemos]);
  React.useEffect(() => {
    if (!isOpen) return void 0;
    const timer = window.setInterval(() => setNow(nowSeconds()), 3e4);
    return () => window.clearInterval(timer);
  }, [isOpen]);
  const allRows = React.useMemo(() => buildRows(demos, matches), [demos, matches]);
  const facetValues = React.useMemo(() => facets(allRows), [allRows]);
  const packing = React.useMemo(() => packingInUse(allRows), [allRows]);
  const displayRows = React.useMemo(
    () => sortRows(filterRows(allRows, filters, now), filters.sort),
    [allRows, filters, now]
  );
  const totals = React.useMemo(() => {
    const sum = (rows) => ({
      matches: rows.filter((r) => r.type === "group").length,
      files: rows.reduce((n, r) => n + r.members.length, 0),
      size: rows.reduce((n, r) => n + r.size, 0)
    });
    return { all: sum(allRows), shown: sum(displayRows) };
  }, [allRows, displayRows]);
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
  }, [filters]);
  const visibleNames = React.useMemo(
    () => new Set(displayRows.flatMap((r) => r.members.map((d) => d.name))),
    [displayRows]
  );
  const visibleGroupIds = React.useMemo(
    () => new Set(displayRows.filter((r) => r.type === "group").map((r) => r.group.group_id)),
    [displayRows]
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
      setSelected(/* @__PURE__ */ new Set());
      setSelectedGroupIds(/* @__PURE__ */ new Set());
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
  const filtersActive = filters.text || filters.datePreset !== "all" || filters.map || filters.gametype || filters.kind !== "all";
  const resetFilters = () => setFilters((prev) => ({ ...DEFAULT_FILTERS, sort: prev.sort }));
  const showDayHeaders = filters.sort === "newest" || filters.sort === "oldest";
  const hasData = demos.length > 0;
  const listingSeconds = timing && Number.isFinite(timing.total_ms) ? ((timing.total_ms + (timing.hooks_ms || 0)) / 1e3).toFixed(1) : null;
  const downloadButton = (name) => /* @__PURE__ */ React.createElement(
    "button",
    {
      onClick: () => downloadOne(name),
      disabled: downloadingNames.has(name),
      title: `Download ${name}`,
      "aria-label": `Download ${name}`,
      className: iconButtonClass
    },
    /* @__PURE__ */ React.createElement(Download, { className: `h-4 w-4 ${downloadingNames.has(name) ? "animate-pulse" : ""}`, strokeWidth: 2 })
  );
  const renderWhen = (row) => /* @__PURE__ */ React.createElement("td", { className: "py-2 pr-4 font-mono text-theme-secondary whitespace-nowrap", title: formatFull(row.when) }, showDayHeaders ? formatTime(row.when) : `${formatDayLabel(row.when, now)}, ${formatTime(row.when)}`);
  const renderFileRow = (demo, nested) => {
    var _a;
    return /* @__PURE__ */ React.createElement("tr", { key: demo.name, className: "border-b border-theme/50 hover:bg-black/[0.02] dark:hover:bg-white/[0.02]" }, /* @__PURE__ */ React.createElement("td", { className: "py-2 pr-2" }, /* @__PURE__ */ React.createElement(
      "input",
      {
        type: "checkbox",
        checked: selected.has(demo.name),
        onChange: () => toggleSelectOne(demo.name),
        "aria-label": `Select ${demo.name}`
      }
    )), /* @__PURE__ */ React.createElement("td", { className: `py-2 pr-4 font-mono break-all ${"pl-6 text-xs text-theme-secondary"}` }, /* @__PURE__ */ React.createElement("div", null, demo.name), ((_a = demo.pov) == null ? void 0 : _a.player) && /* @__PURE__ */ React.createElement("div", { className: "text-theme-muted" }, demo.pov.slot !== null && demo.pov.slot !== void 0 ? `slot ${demo.pov.slot} · ` : "", demo.pov.player)), /* @__PURE__ */ React.createElement("td", { className: "py-2 pr-4" }), /* @__PURE__ */ React.createElement("td", { className: "py-2 pr-4 font-mono text-theme-secondary whitespace-nowrap" }, formatBytes(demo.size)), /* @__PURE__ */ React.createElement("td", { className: "py-2 pr-4 font-mono text-theme-secondary whitespace-nowrap", title: formatFull(demo.mtime) }, formatTime(demo.mtime)), /* @__PURE__ */ React.createElement("td", { className: "py-2 pr-2" }, downloadButton(demo.name)));
  };
  const renderLooseRow = (row) => {
    var _a, _b;
    const { demo, info } = row;
    return /* @__PURE__ */ React.createElement("tr", { key: row.key, className: "border-b border-theme/50 hover:bg-black/[0.02] dark:hover:bg-white/[0.02]" }, /* @__PURE__ */ React.createElement("td", { className: "py-2 pr-2" }, /* @__PURE__ */ React.createElement(
      "input",
      {
        type: "checkbox",
        checked: selected.has(demo.name),
        onChange: () => toggleSelectOne(demo.name),
        "aria-label": `Select ${demo.name}`
      }
    )), /* @__PURE__ */ React.createElement("td", { className: "py-2 pr-4" }, /* @__PURE__ */ React.createElement("div", { className: "font-mono text-theme-primary break-all" }, demo.name), (info.map || ((_a = demo.pov) == null ? void 0 : _a.player)) && /* @__PURE__ */ React.createElement("div", { className: "mt-0.5 flex flex-wrap items-center gap-1.5 text-xs text-theme-muted" }, info.map && /* @__PURE__ */ React.createElement("span", { className: "text-theme-secondary" }, info.map), ((_b = demo.pov) == null ? void 0 : _b.player) && /* @__PURE__ */ React.createElement("span", null, "· ", demo.pov.player), /* @__PURE__ */ React.createElement(KindBadges, { kinds: row.kinds, packing: false }))), /* @__PURE__ */ React.createElement("td", { className: "py-2 pr-4" }), /* @__PURE__ */ React.createElement("td", { className: "py-2 pr-4 font-mono text-theme-secondary whitespace-nowrap" }, formatBytes(demo.size)), renderWhen(row), /* @__PURE__ */ React.createElement("td", { className: "py-2 pr-2" }, downloadButton(demo.name)));
  };
  const renderGroupRow = (row) => {
    const { group, members, info } = row;
    const isExpanded = expandedGroupIds.has(group.group_id);
    const players = playersLabel(info);
    return /* @__PURE__ */ React.createElement(React.Fragment, { key: row.key }, /* @__PURE__ */ React.createElement("tr", { className: "border-b border-theme/50 bg-black/[0.02] dark:bg-white/[0.03]" }, /* @__PURE__ */ React.createElement("td", { className: "py-2 pr-2 align-top" }, /* @__PURE__ */ React.createElement(
      "input",
      {
        type: "checkbox",
        checked: selectedGroupIds.has(group.group_id),
        onChange: () => toggleSelectGroup(row),
        "aria-label": `Select match ${group.label}`
      }
    )), /* @__PURE__ */ React.createElement("td", { className: "py-2 pr-4" }, /* @__PURE__ */ React.createElement(
      "button",
      {
        onClick: () => toggleExpandGroup(group.group_id),
        "aria-expanded": isExpanded,
        title: isExpanded ? "Hide the files in this match" : "Show the files in this match",
        className: "flex items-start gap-1.5 text-left hover:text-[var(--accent-primary)]"
      },
      isExpanded ? /* @__PURE__ */ React.createElement(ChevronDown, { className: "mt-0.5 h-4 w-4 flex-shrink-0", strokeWidth: 2 }) : /* @__PURE__ */ React.createElement(ChevronRight, { className: "mt-0.5 h-4 w-4 flex-shrink-0", strokeWidth: 2 }),
      /* @__PURE__ */ React.createElement("span", { className: "min-w-0" }, /* @__PURE__ */ React.createElement("span", { className: "flex flex-wrap items-center gap-x-2 gap-y-0.5" }, /* @__PURE__ */ React.createElement("span", { className: "font-display text-base font-bold text-theme-primary" }, info.map || group.label), info.gametype && /* @__PURE__ */ React.createElement(Badge, { tone: "primary" }, info.gametype), players && /* @__PURE__ */ React.createElement("span", { className: "text-sm text-theme-secondary" }, players)), /* @__PURE__ */ React.createElement("span", { className: "mt-0.5 flex flex-wrap items-center gap-1.5 text-xs text-theme-muted" }, /* @__PURE__ */ React.createElement("span", { className: "font-mono" }, info.match_id || group.group_id), /* @__PURE__ */ React.createElement("span", null, "·"), /* @__PURE__ */ React.createElement("span", null, members.length, " file", members.length === 1 ? "" : "s"), /* @__PURE__ */ React.createElement(KindBadges, { kinds: row.kinds, packing })))
    )), /* @__PURE__ */ React.createElement("td", { className: "py-2 pr-4 font-mono text-theme-secondary whitespace-nowrap" }, formatDuration(info.duration_ms)), /* @__PURE__ */ React.createElement("td", { className: "py-2 pr-4 font-mono text-theme-secondary whitespace-nowrap" }, formatBytes(row.size)), renderWhen(row), /* @__PURE__ */ React.createElement("td", { className: "py-2 pr-2" }, /* @__PURE__ */ React.createElement("div", { className: "flex items-center gap-1" }, (group.actions || []).map((action) => {
      const busyKey = `${action.id}:${group.group_id}`;
      return /* @__PURE__ */ React.createElement(
        "button",
        {
          key: action.id,
          onClick: () => runGroupAction(group, action),
          disabled: busyGroupActionKey !== null,
          title: action.label,
          "aria-label": `${action.label} for ${group.label}`,
          className: iconButtonClass,
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
    })))), isExpanded && members.map((demo) => renderFileRow(demo)));
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
          const dayMatches = sameDay.filter((r) => r.type === "group").length;
          const dayLoose = sameDay.length - dayMatches;
          const daySummary = [
            dayMatches > 0 ? `${dayMatches} match${dayMatches === 1 ? "" : "es"}` : null,
            dayLoose > 0 ? `${dayLoose} file${dayLoose === 1 ? "" : "s"}` : null
          ].filter(Boolean).join(" · ");
          out.push(
            /* @__PURE__ */ React.createElement("tr", { key: `day-${day}`, className: "demos-addon-day-row" }, /* @__PURE__ */ React.createElement("td", { colSpan: 6, className: "pt-4 pb-1.5" }, /* @__PURE__ */ React.createElement("span", { className: "font-display text-sm font-bold uppercase tracking-wide text-theme-primary" }, formatDayLabel(row.when, now)), /* @__PURE__ */ React.createElement("span", { className: "ml-2 text-xs font-mono text-theme-muted" }, daySummary)))
          );
        }
      }
      out.push(row.type === "group" ? renderGroupRow(row) : renderLooseRow(row));
    });
    return out;
  };
  return /* @__PURE__ */ React.createElement(
    Modal,
    {
      isOpen,
      onClose,
      size: "2xl",
      height: "75vh",
      icon: /* @__PURE__ */ React.createElement("div", { className: "demos-addon-icon-wrapper" }, /* @__PURE__ */ React.createElement("div", { className: "demos-addon-icon-glow" }), /* @__PURE__ */ React.createElement(Film, { className: "demos-addon-icon", strokeWidth: 2.5 })),
      title: /* @__PURE__ */ React.createElement(React.Fragment, null, "Demos", /* @__PURE__ */ React.createElement("span", { className: "mt-0.5 block font-mono text-xs font-normal normal-case tracking-normal text-theme-secondary" }, instance == null ? void 0 : instance.name, " ", /* @__PURE__ */ React.createElement("span", { className: "text-theme-muted" }, "•"), " Port ", instance == null ? void 0 : instance.port, " ", /* @__PURE__ */ React.createElement("span", { className: "text-theme-muted" }, "•"), " demos/ on disk", fetchedAt && /* @__PURE__ */ React.createElement(React.Fragment, null, " ", /* @__PURE__ */ React.createElement("span", { className: "text-theme-muted" }, "•"), " ", /* @__PURE__ */ React.createElement("span", { title: timing ? `Listing timings (ms): ${JSON.stringify(timing)}` : void 0 }, isRefreshing ? "refreshing…" : `updated ${formatAgo(fetchedAt, now)}`, listingSeconds && !isRefreshing ? ` in ${listingSeconds}s` : "")))),
      headerActions: /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement(
        "button",
        {
          onClick: fetchDemos,
          disabled: isLoading || isRefreshing,
          className: "demos-addon-btn"
        },
        /* @__PURE__ */ React.createElement(RefreshCw, { className: `h-4 w-4 ${isLoading || isRefreshing ? "animate-spin" : ""}`, strokeWidth: 2 }),
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
    /* @__PURE__ */ React.createElement("div", { className: "flex h-full flex-col" }, !isLoading && hasData && /* @__PURE__ */ React.createElement("div", { className: "flex flex-shrink-0 flex-col gap-2 border-b border-theme pb-3 mb-3" }, /* @__PURE__ */ React.createElement("div", { className: "flex flex-wrap items-center gap-2" }, /* @__PURE__ */ React.createElement("div", { className: "relative min-w-[12rem] flex-1 max-w-xs" }, /* @__PURE__ */ React.createElement(Search, { className: "demo-search-icon absolute top-1/2 -translate-y-1/2 text-theme-muted" }), /* @__PURE__ */ React.createElement(
      "input",
      {
        type: "text",
        value: filters.text,
        onChange: (e) => setFilter("text", e.target.value),
        placeholder: "Map, player, file name...",
        "aria-label": "Filter demos",
        className: `w-full pl-8 pr-3 ${inputClass} placeholder:text-theme-muted`
      }
    )), /* @__PURE__ */ React.createElement("div", { className: "demos-addon-segmented", role: "group", "aria-label": "Recorded" }, DATE_PRESETS.map((preset) => /* @__PURE__ */ React.createElement(
      "button",
      {
        key: preset.id,
        onClick: () => setFilter("datePreset", preset.id),
        "aria-pressed": filters.datePreset === preset.id,
        className: filters.datePreset === preset.id ? "is-active" : ""
      },
      preset.label
    ))), filters.datePreset === "custom" && /* @__PURE__ */ React.createElement("div", { className: "flex items-center gap-1.5" }, /* @__PURE__ */ React.createElement(
      "input",
      {
        type: "date",
        value: filters.dateFrom,
        onChange: (e) => setFilter("dateFrom", e.target.value),
        max: filters.dateTo || void 0,
        "aria-label": "Recorded from date",
        className: inputClass
      }
    ), /* @__PURE__ */ React.createElement("span", { className: "text-theme-muted text-xs" }, "to"), /* @__PURE__ */ React.createElement(
      "input",
      {
        type: "date",
        value: filters.dateTo,
        onChange: (e) => setFilter("dateTo", e.target.value),
        min: filters.dateFrom || void 0,
        "aria-label": "Recorded to date",
        className: inputClass
      }
    ))), /* @__PURE__ */ React.createElement("div", { className: "flex flex-wrap items-center gap-2" }, facetValues.maps.length > 0 && /* @__PURE__ */ React.createElement(
      "select",
      {
        value: filters.map,
        onChange: (e) => setFilter("map", e.target.value),
        "aria-label": "Map",
        className: inputClass
      },
      /* @__PURE__ */ React.createElement("option", { value: "" }, "All maps"),
      facetValues.maps.map(({ value, count }) => /* @__PURE__ */ React.createElement("option", { key: value, value }, value, " (", count, ")"))
    ), facetValues.gametypes.length > 0 && /* @__PURE__ */ React.createElement(
      "select",
      {
        value: filters.gametype,
        onChange: (e) => setFilter("gametype", e.target.value),
        "aria-label": "Game type",
        className: inputClass
      },
      /* @__PURE__ */ React.createElement("option", { value: "" }, "All modes"),
      facetValues.gametypes.map(({ value, count }) => /* @__PURE__ */ React.createElement("option", { key: value, value }, value, " (", count, ")"))
    ), /* @__PURE__ */ React.createElement(
      "select",
      {
        value: filters.kind,
        onChange: (e) => setFilter("kind", e.target.value),
        "aria-label": "Show",
        className: inputClass
      },
      KIND_FILTERS.map((k) => /* @__PURE__ */ React.createElement("option", { key: k.id, value: k.id }, k.label))
    ), /* @__PURE__ */ React.createElement(
      "select",
      {
        value: filters.sort,
        onChange: (e) => setFilter("sort", e.target.value),
        "aria-label": "Sort",
        className: inputClass
      },
      SORTS.map((s) => /* @__PURE__ */ React.createElement("option", { key: s.id, value: s.id }, s.label))
    ), filtersActive && /* @__PURE__ */ React.createElement("button", { onClick: resetFilters, className: "text-xs font-mono text-theme-muted underline hover:text-theme-primary" }, "reset"), /* @__PURE__ */ React.createElement("span", { className: "text-xs font-mono text-theme-muted whitespace-nowrap", title: `${totals.all.files} files, ${formatBytes(totals.all.size)} on disk` }, filtersActive ? `${totals.shown.matches} of ${totals.all.matches} matches · ${totals.shown.files} of ${totals.all.files} files` : `${totals.all.matches} matches · ${totals.all.files} files`, ` · ${formatBytes(filtersActive ? totals.shown.size : totals.all.size)}`), /* @__PURE__ */ React.createElement("div", { className: "flex-1" }), bulkGroupActions.map((entry) => /* @__PURE__ */ React.createElement(
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
    ))), error && hasData && /* @__PURE__ */ React.createElement("div", { className: "flex-shrink-0 pb-2 text-sm text-center", style: { color: "var(--accent-danger)" } }, "Refresh failed: ", error, " Showing the previous listing."), downloadError && /* @__PURE__ */ React.createElement("div", { className: "flex-shrink-0 pb-2 text-sm text-center", style: { color: "var(--accent-danger)" } }, downloadError), groupActionError && /* @__PURE__ */ React.createElement("div", { className: "flex-shrink-0 pb-2 text-sm text-center", style: { color: "var(--accent-danger)" } }, groupActionError), /* @__PURE__ */ React.createElement("div", { className: "flex-1 overflow-auto" }, isLoading ? /* @__PURE__ */ React.createElement("div", { className: "demos-addon-empty-state" }, /* @__PURE__ */ React.createElement("div", { className: "demos-addon-spinner-wrapper" }, /* @__PURE__ */ React.createElement(RefreshCw, { className: "demos-addon-spinner", strokeWidth: 2 })), /* @__PURE__ */ React.createElement("p", { className: "font-mono text-sm text-theme-secondary uppercase tracking-wide" }, "Listing demos on remote server...")) : error && !hasData ? /* @__PURE__ */ React.createElement("div", { className: "demos-addon-error-state" }, /* @__PURE__ */ React.createElement(AlertCircle, { className: "h-10 w-10 mb-4", style: { color: "var(--accent-danger)" }, strokeWidth: 2 }), /* @__PURE__ */ React.createElement("p", { className: "font-display text-lg font-bold uppercase tracking-wide", style: { color: "var(--accent-danger)" } }, "Error Listing Demos"), /* @__PURE__ */ React.createElement("p", { className: "text-sm text-theme-secondary mt-2 max-w-md text-center" }, error), /* @__PURE__ */ React.createElement(
      "button",
      {
        onClick: fetchDemos,
        className: "demos-addon-retry-btn"
      },
      "Try Again"
    )) : !hasData ? /* @__PURE__ */ React.createElement("div", { className: "demos-addon-empty-state" }, /* @__PURE__ */ React.createElement(FolderOpen, { className: "h-10 w-10 mb-4 text-theme-muted", strokeWidth: 2 }), /* @__PURE__ */ React.createElement("p", { className: "font-display text-base font-bold uppercase tracking-wide text-theme-primary" }, "No demos found"), /* @__PURE__ */ React.createElement("p", { className: "text-sm text-theme-secondary mt-2 max-w-md text-center" }, `No .dm_91, .qlmatch or .replay.json.gz files in this instance's demos/ directory. Recording needs sv_demoRecord 1 (add sv_demoCut 1 for match-cut demos and .qlmatch packing) — check View MinQLX Logs / View Server Logs for "demo:" lines after a manual test.`)) : displayRows.length === 0 ? /* @__PURE__ */ React.createElement("div", { className: "demos-addon-empty-state" }, /* @__PURE__ */ React.createElement(Search, { className: "h-10 w-10 mb-4 text-theme-muted", strokeWidth: 2 }), /* @__PURE__ */ React.createElement("p", { className: "text-sm text-theme-secondary" }, "No demos match these filters."), /* @__PURE__ */ React.createElement("button", { onClick: resetFilters, className: "demos-addon-btn" }, "Reset filters")) : /* @__PURE__ */ React.createElement("table", { className: "w-full text-sm" }, /* @__PURE__ */ React.createElement("thead", { className: "demos-addon-thead" }, /* @__PURE__ */ React.createElement("tr", { className: "text-left text-theme-muted uppercase text-xs tracking-wide border-b border-theme" }, /* @__PURE__ */ React.createElement("th", { className: "py-2 pr-2 w-8" }, /* @__PURE__ */ React.createElement(
      "input",
      {
        type: "checkbox",
        checked: allVisibleSelected,
        onChange: toggleSelectAll,
        "aria-label": "Select all shown demos"
      }
    )), /* @__PURE__ */ React.createElement("th", { className: "py-2 pr-4 font-medium" }, "Match / file"), /* @__PURE__ */ React.createElement("th", { className: "py-2 pr-4 font-medium w-20" }, "Length"), /* @__PURE__ */ React.createElement("th", { className: "py-2 pr-4 font-medium w-24" }, "Size"), /* @__PURE__ */ React.createElement("th", { className: "py-2 pr-4 font-medium w-40" }, "Started"), /* @__PURE__ */ React.createElement("th", { className: "py-2 pr-2 w-20" }))), /* @__PURE__ */ React.createElement("tbody", null, renderRows()))), !isLoading && displayRows.length > 0 && totalPages > 1 && /* @__PURE__ */ React.createElement("div", { className: "flex flex-shrink-0 items-center justify-center gap-3 border-t border-theme pt-3 mt-3" }, /* @__PURE__ */ React.createElement(
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
