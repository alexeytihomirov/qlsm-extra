import { R as React, h as hostIdFromSearch, s as sortByHealth, f as findings, o as openEvents, a as hostHealth, B as Button, b as fmtTime, P as P95_GLOSS, H as HostModal, c as healthCounts, d as hardwareLine, p as playersNow, e as eventsTotal, g as slotsText, r as refNote, i as corePeaks, l as lateFrames24h, j as fmtPct, k as diskUsedPct, m as fmtDuration, n as fmtBytes } from "./hm-shared.js";
const { useCallback, useEffect, useMemo, useRef, useState } = React;
const STATUS_TONE = { problem: "critical", watch: "warning", nodata: "neutral", ok: "good" };
const STATUS_ORDER = ["problem", "watch", "nodata", "ok"];
const STATUS_LABEL = { problem: "Problem", watch: "Watch", nodata: "No data", ok: "OK" };
const STATUS_HINT = {
  problem: "Overloaded, an open critical event, or the host does not answer.",
  watch: "Tight capacity, noisy neighbour, stale data, or warnings in the last 24 hours.",
  nodata: "Not installed, or no data yet.",
  ok: "Room for more and nothing to look at."
};
function errorText(e, fallback) {
  var _a, _b, _c;
  return ((_c = (_b = (_a = e == null ? void 0 : e.response) == null ? void 0 : _a.data) == null ? void 0 : _b.error) == null ? void 0 : _c.message) || (e == null ? void 0 : e.message) || fallback;
}
function ToneIcon({ tone }) {
  const props = {
    viewBox: "0 0 16 16",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.8,
    strokeLinecap: "round",
    strokeLinejoin: "round",
    "aria-hidden": true
  };
  if (tone === "good") {
    return /* @__PURE__ */ React.createElement("svg", { ...props }, /* @__PURE__ */ React.createElement("circle", { cx: "8", cy: "8", r: "6.5" }), /* @__PURE__ */ React.createElement("path", { d: "M5 8.2l2.2 2.2L11 6" }));
  }
  if (tone === "warning") {
    return /* @__PURE__ */ React.createElement("svg", { ...props }, /* @__PURE__ */ React.createElement("path", { d: "M8 2l6.5 11.5h-13z" }), /* @__PURE__ */ React.createElement("path", { d: "M8 6.5v3M8 11.6v.1" }));
  }
  if (tone === "critical") {
    return /* @__PURE__ */ React.createElement("svg", { ...props }, /* @__PURE__ */ React.createElement("circle", { cx: "8", cy: "8", r: "6.5" }), /* @__PURE__ */ React.createElement("path", { d: "M5.5 5.5l5 5M10.5 5.5l-5 5" }));
  }
  return /* @__PURE__ */ React.createElement("svg", { ...props }, /* @__PURE__ */ React.createElement("circle", { cx: "8", cy: "8", r: "6.5" }), /* @__PURE__ */ React.createElement("path", { d: "M5 8h6" }));
}
function StatusBadge({ health }) {
  const tone = STATUS_TONE[health.status] || "neutral";
  return /* @__PURE__ */ React.createElement("span", { className: `hm-badge hm-tone-${tone}`, title: STATUS_HINT[health.status] }, /* @__PURE__ */ React.createElement(ToneIcon, { tone }), health.label);
}
function sinceText(since, now) {
  if (!Number.isFinite(since)) return "";
  const ago = Number.isFinite(now) ? ` (${fmtDuration(now - since)} ago)` : "";
  return `since ${fmtTime(since)}${ago}`;
}
function Summary({ entries, onOpen, now }) {
  const counts = healthCounts(entries.map((e) => e.health));
  const problems = [];
  for (const e of entries) {
    for (const item of e.health.items) {
      if (item.level === "problem") problems.push({ row: e.row, item });
    }
  }
  return /* @__PURE__ */ React.createElement("div", { className: "hm-board-summary" }, /* @__PURE__ */ React.createElement("div", { className: "hm-tiles" }, STATUS_ORDER.map((s) => /* @__PURE__ */ React.createElement("div", { key: s, className: `hm-tile hm-health-${s}`, title: STATUS_HINT[s] }, /* @__PURE__ */ React.createElement("span", { className: "hm-tile-value hm-num" }, counts[s]), /* @__PURE__ */ React.createElement(StatusBadge, { health: { status: s, label: STATUS_LABEL[s] } })))), /* @__PURE__ */ React.createElement("div", { className: "hm-problems" }, /* @__PURE__ */ React.createElement("div", { className: "hm-section-title" }, "Open problems"), problems.length === 0 ? /* @__PURE__ */ React.createElement("div", { className: "hm-muted" }, "No open problems.") : /* @__PURE__ */ React.createElement("ul", null, problems.map(({ row, item }, i) => {
    var _a;
    return /* @__PURE__ */ React.createElement("li", { key: `${row.id}-${i}` }, /* @__PURE__ */ React.createElement("button", { type: "button", className: "hm-host-link", onClick: () => onOpen(row) }, row.name), /* @__PURE__ */ React.createElement("span", { className: "hm-problem-what" }, item.what), item.since !== null ? /* @__PURE__ */ React.createElement("span", { className: "hm-muted hm-num" }, sinceText(item.since, ((_a = row.snapshot) == null ? void 0 : _a.now) ?? now)) : null);
  }))));
}
function memText(snapshot) {
  const avail = snapshot == null ? void 0 : snapshot.mem_avail_now;
  const total = snapshot == null ? void 0 : snapshot.mem_total;
  if (avail === null || avail === void 0) return null;
  return total ? `${fmtBytes(avail)} free of ${fmtBytes(total)}` : `${fmtBytes(avail)} free`;
}
function metricsText(s) {
  if (!s) return null;
  const peaks = corePeaks(s);
  const late = lateFrames24h(s);
  const parts = [
    peaks ? `busiest core p95 ${fmtPct(peaks.peak)} (24 h)` : null,
    Number.isFinite(s.steal_p95) ? `steal p95 ${fmtPct(s.steal_p95)} (7 d)` : null,
    memText(s) ? `RAM ${memText(s)}` : null,
    diskUsedPct(s.host) !== null ? `disk ${fmtPct(diskUsedPct(s.host))} used` : null,
    late ? `${late.late} late frames (24 h)` : null
  ].filter(Boolean);
  return parts.length ? parts.join(" | ") : null;
}
function Fact({ label, value, title }) {
  return /* @__PURE__ */ React.createElement("span", { className: "hm-fact", title }, /* @__PURE__ */ React.createElement("span", { className: "hm-muted" }, label), " ", /* @__PURE__ */ React.createElement("span", { className: "hm-num" }, value));
}
function HostCard({ row, health, onOpen }) {
  const s = row.snapshot;
  const hw = hardwareLine(s == null ? void 0 : s.hardware);
  const instances = s ? (s.insts_last || []).length : null;
  const players = s ? playersNow(s) : null;
  const open = s ? openEvents(s) : null;
  const metrics = metricsText(s);
  const live = row.state !== "stale";
  return /* @__PURE__ */ React.createElement("article", { className: `hm-hcard hm-health-${health.status}` }, /* @__PURE__ */ React.createElement("div", { className: "hm-hcard-head" }, /* @__PURE__ */ React.createElement(StatusBadge, { health }), /* @__PURE__ */ React.createElement("span", { className: "hm-hcard-name" }, row.name), /* @__PURE__ */ React.createElement("span", { className: "hm-footer-spacer" }), /* @__PURE__ */ React.createElement(Button, { onClick: () => onOpen(row) }, "Details")), /* @__PURE__ */ React.createElement("div", { className: "hm-hcard-reason" }, health.reason), s ? /* @__PURE__ */ React.createElement("div", { className: `hm-hcard-hw${hw ? "" : " hm-muted"}`, title: "CPU, cores, RAM, root disk, provider (read by the collector every hour)" }, hw || "Hardware not read yet (collector before 1.1, or its first read is pending).") : null, s && live ? /* @__PURE__ */ React.createElement("div", { className: "hm-facts" }, /* @__PURE__ */ React.createElement(Fact, { label: "Instances", value: instances }), /* @__PURE__ */ React.createElement(Fact, { label: "Players now", value: players === null ? "-" : players }), open ? /* @__PURE__ */ React.createElement(Fact, { label: "Open events", value: open.filter((e) => e.kind !== "instance_new" && e.kind !== "instance_gone").length }) : /* @__PURE__ */ React.createElement(Fact, { label: "Events 24 h", value: eventsTotal(s), title: "This collector does not report open events yet." }), row.verdict && Number.isFinite(row.verdict.slots) ? /* @__PURE__ */ React.createElement(
    Fact,
    {
      label: "Capacity",
      value: `${slotsText(row.verdict)}${refNote(row.verdict) ? " (fleet reference)" : ""}`,
      title: row.verdict.reason || void 0
    }
  ) : null) : null, metrics && live ? /* @__PURE__ */ React.createElement("div", { className: "hm-hcard-metrics hm-muted", title: P95_GLOSS }, metrics) : null);
}
function Page({ ctx }) {
  var _a;
  const [hosts, setHosts] = useState(null);
  const [settings, setSettings] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [loadedAt, setLoadedAt] = useState(null);
  const [open, setOpen] = useState(null);
  const token = useRef(0);
  const ctxRef = useRef(ctx);
  ctxRef.current = ctx;
  const [, bumpUrl] = useState(0);
  const linkedNow = hostIdFromSearch(typeof window !== "undefined" ? (_a = window.location) == null ? void 0 : _a.search : "");
  const linkHandled = useRef(null);
  useEffect(() => {
    const onPop = () => bumpUrl((n) => n + 1);
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);
  const load = useCallback(async (refresh) => {
    const mine = ++token.current;
    setLoading(true);
    setError(null);
    try {
      const data = await ctxRef.current.api("GET", "hosts", refresh ? { params: { refresh: 1 } } : void 0);
      if (token.current !== mine) return;
      const list = (data == null ? void 0 : data.hosts) || [];
      setHosts(list);
      setLoadedAt(Date.now() / 1e3);
    } catch (e) {
      if (token.current === mine) setError(errorText(e, "Could not load the hosts."));
    } finally {
      if (token.current === mine) setLoading(false);
    }
  }, []);
  useEffect(() => {
    load(false);
  }, [load]);
  useEffect(() => {
    if (linkedNow === null) {
      linkHandled.current = null;
      return;
    }
    if (!hosts || linkHandled.current === linkedNow) return;
    linkHandled.current = linkedNow;
    const row = hosts.find((h) => h.id === linkedNow);
    if (row) setOpen(row);
    else setError(`Host ${linkedNow} from the link is not in the host list.`);
  }, [linkedNow, hosts]);
  const closeOpen = useCallback(() => {
    try {
      const url = new URL(window.location.href);
      if (url.searchParams.has("host")) {
        url.searchParams.delete("host");
        window.history.replaceState(window.history.state, "", `${url.pathname}${url.search}${url.hash}`);
      }
    } catch (e) {
    }
    linkHandled.current = null;
    setOpen(null);
  }, []);
  useEffect(() => {
    let alive = true;
    ctxRef.current.api("GET", "settings").then((d) => {
      if (alive) setSettings(d || null);
    }).catch(() => {
    });
    return () => {
      alive = false;
    };
  }, []);
  const entries = useMemo(() => sortByHealth((hosts || []).map((row) => {
    const list = row.snapshot ? findings({
      snapshot: row.snapshot,
      events: openEvents(row.snapshot) || void 0,
      settings,
      verdict: row.verdict || null
    }) : [];
    return { row, health: hostHealth(row, list) };
  })), [hosts, settings]);
  return /* @__PURE__ */ React.createElement("div", { className: "hm-root hm-page" }, /* @__PURE__ */ React.createElement("div", { className: "hm-toolbar" }, /* @__PURE__ */ React.createElement(Button, { onClick: () => load(true), disabled: loading }, loading ? "Loading..." : "Refresh"), /* @__PURE__ */ React.createElement("span", { className: "hm-muted" }, loadedAt ? `Updated ${fmtTime(loadedAt, true)}. ` : "", "One card per host, problems first. Details opens the charts and events of the host. ", P95_GLOSS)), error ? /* @__PURE__ */ React.createElement("div", { className: "hm-error" }, error) : null, hosts === null && loading ? /* @__PURE__ */ React.createElement("div", { className: "hm-muted" }, "Loading hosts (one SSH query per host)...") : null, hosts && hosts.length === 0 ? /* @__PURE__ */ React.createElement("div", { className: "hm-muted" }, "No hosts.") : null, hosts && hosts.length > 0 ? /* @__PURE__ */ React.createElement("div", { className: loading ? "hm-dim" : void 0 }, /* @__PURE__ */ React.createElement(Summary, { entries, onOpen: setOpen, now: loadedAt }), /* @__PURE__ */ React.createElement("div", { className: "hm-board" }, entries.map(({ row, health }) => /* @__PURE__ */ React.createElement(HostCard, { key: row.id, row, health, onOpen: setOpen })))) : null, open ? /* @__PURE__ */ React.createElement(HostModal, { ctx, host: open, isOpen: true, onClose: closeOpen }) : null);
}
export {
  Page as default
};
