import { e as ensurePanelCss, R as React, f as fmtTime, H as HostModal, p as playersNow, a as eventsTotal, s as slotsText, b as fmtPct, d as diskUsedPct, c as stateLabel, g as statusLabel, h as fmtBytes } from "./hm-shared.js";
ensurePanelCss();
const { useCallback, useEffect, useRef, useState } = React;
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
    return /* @__PURE__ */ React.createElement("svg", { ...props, style: { color: "var(--hm-good)" } }, /* @__PURE__ */ React.createElement("circle", { cx: "8", cy: "8", r: "6.5" }), /* @__PURE__ */ React.createElement("path", { d: "M5 8.2l2.2 2.2L11 6" }));
  }
  if (tone === "warning") {
    return /* @__PURE__ */ React.createElement("svg", { ...props }, /* @__PURE__ */ React.createElement("path", { d: "M8 2l6.5 11.5h-13z" }), /* @__PURE__ */ React.createElement("path", { d: "M8 6.5v3M8 11.6v.1" }));
  }
  if (tone === "critical") {
    return /* @__PURE__ */ React.createElement("svg", { ...props }, /* @__PURE__ */ React.createElement("circle", { cx: "8", cy: "8", r: "6.5" }), /* @__PURE__ */ React.createElement("path", { d: "M5.5 5.5l5 5M10.5 5.5l-5 5" }));
  }
  return /* @__PURE__ */ React.createElement("svg", { ...props }, /* @__PURE__ */ React.createElement("circle", { cx: "8", cy: "8", r: "6.5" }), /* @__PURE__ */ React.createElement("path", { d: "M5 8h6" }));
}
function Badge({ text, tone }) {
  return /* @__PURE__ */ React.createElement("span", { className: `hm-badge hm-tone-${tone}` }, /* @__PURE__ */ React.createElement(ToneIcon, { tone }), text);
}
function StatusCell({ host }) {
  var _a, _b;
  const problem = stateLabel(host.state);
  if (host.state !== "ok" && !host.snapshot) {
    const tone = host.state === "unreachable" ? "critical" : "neutral";
    return /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement(Badge, { text: problem || host.state, tone }), host.error ? /* @__PURE__ */ React.createElement("div", { className: "hm-reason" }, host.error) : null);
  }
  const label = statusLabel((_a = host.verdict) == null ? void 0 : _a.status);
  const reason = (_b = host.verdict) == null ? void 0 : _b.reason;
  return /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("span", { title: reason || void 0 }, /* @__PURE__ */ React.createElement(Badge, { text: label.text, tone: label.tone })), reason ? /* @__PURE__ */ React.createElement("div", { className: "hm-reason" }, reason) : null, problem ? /* @__PURE__ */ React.createElement("div", { className: "hm-reason" }, problem, host.version ? ` (${host.version})` : "", ": use Apply to host.") : null);
}
function CoresCell({ snapshot }) {
  const cores = ((snapshot == null ? void 0 : snapshot.cores_last) || []).filter((c) => c.core >= 0);
  if (!cores.length) return /* @__PURE__ */ React.createElement("span", { className: "hm-muted" }, "-");
  return /* @__PURE__ */ React.createElement("div", { className: "hm-cores hm-num" }, cores.map((c) => /* @__PURE__ */ React.createElement("span", { key: c.core, className: c.busy >= 95 ? "hm-core-hot" : void 0, title: `Core ${c.core} busy now` }, c.core, ": ", fmtPct(c.busy))));
}
function memText(snapshot) {
  const avail = snapshot == null ? void 0 : snapshot.mem_avail_now;
  const total = snapshot == null ? void 0 : snapshot.mem_total;
  if (avail === null || avail === void 0) return "-";
  return total ? `${fmtBytes(avail)} of ${fmtBytes(total)}` : fmtBytes(avail);
}
function HostRow({ host, onOpen }) {
  var _a;
  const s = host.snapshot;
  const instances = s ? (s.insts_last || []).length : null;
  const players = s ? playersNow(s) : null;
  const late = s ? ((_a = s.events_24h) == null ? void 0 : _a.frames_late) || 0 : null;
  const events = s ? eventsTotal(s) : null;
  const dash = /* @__PURE__ */ React.createElement("span", { className: "hm-muted" }, "-");
  return /* @__PURE__ */ React.createElement("tr", null, /* @__PURE__ */ React.createElement("td", null, /* @__PURE__ */ React.createElement("button", { type: "button", className: "hm-host-link", onClick: () => onOpen(host) }, host.name)), /* @__PURE__ */ React.createElement("td", null, /* @__PURE__ */ React.createElement(StatusCell, { host })), /* @__PURE__ */ React.createElement("td", { className: "hm-num" }, host.verdict ? slotsText(host.verdict) : "-"), /* @__PURE__ */ React.createElement("td", null, s ? /* @__PURE__ */ React.createElement(CoresCell, { snapshot: s }) : dash), /* @__PURE__ */ React.createElement("td", { className: "hm-num" }, s ? fmtPct(s.steal_p95) : dash), /* @__PURE__ */ React.createElement("td", { className: "hm-num" }, s ? memText(s) : dash), /* @__PURE__ */ React.createElement("td", { className: "hm-num" }, s ? fmtPct(diskUsedPct(s.host)) : dash), /* @__PURE__ */ React.createElement("td", { className: "hm-num" }, instances === null ? dash : instances), /* @__PURE__ */ React.createElement("td", { className: "hm-num" }, players === null ? dash : players), /* @__PURE__ */ React.createElement("td", { className: "hm-num" }, late === null ? dash : late), /* @__PURE__ */ React.createElement("td", { className: "hm-num" }, events === null ? dash : events));
}
function Page({ ctx }) {
  const [hosts, setHosts] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [loadedAt, setLoadedAt] = useState(null);
  const [open, setOpen] = useState(null);
  const token = useRef(0);
  const load = useCallback(async (refresh) => {
    const mine = ++token.current;
    setLoading(true);
    setError(null);
    try {
      const data = await ctx.api("GET", "hosts", refresh ? { params: { refresh: 1 } } : void 0);
      if (token.current !== mine) return;
      setHosts((data == null ? void 0 : data.hosts) || []);
      setLoadedAt(Date.now() / 1e3);
    } catch (e) {
      if (token.current === mine) setError(errorText(e, "Could not load the hosts."));
    } finally {
      if (token.current === mine) setLoading(false);
    }
  }, [ctx]);
  useEffect(() => {
    load(false);
  }, [load]);
  return /* @__PURE__ */ React.createElement("div", { className: "hm-root hm-page" }, /* @__PURE__ */ React.createElement("div", { className: "hm-toolbar" }, /* @__PURE__ */ React.createElement("button", { type: "button", className: "hm-btn", onClick: () => load(true), disabled: loading }, loading ? "Loading..." : "Refresh"), /* @__PURE__ */ React.createElement("span", { className: "hm-muted" }, loadedAt ? `Updated ${fmtTime(loadedAt, true)}. ` : "", "Core figures are the latest sample; steal is the 7-day p95; late frames and events are the last 24 hours.")), error ? /* @__PURE__ */ React.createElement("div", { className: "hm-error" }, error) : null, hosts === null && loading ? /* @__PURE__ */ React.createElement("div", { className: "hm-muted" }, "Loading hosts (one SSH query per host)...") : null, hosts && hosts.length === 0 ? /* @__PURE__ */ React.createElement("div", { className: "hm-muted" }, "No hosts.") : null, hosts && hosts.length > 0 ? /* @__PURE__ */ React.createElement("div", { className: `hm-table-wrap${loading ? " hm-dim" : ""}` }, /* @__PURE__ */ React.createElement("table", { className: "hm-table" }, /* @__PURE__ */ React.createElement("thead", null, /* @__PURE__ */ React.createElement("tr", null, /* @__PURE__ */ React.createElement("th", null, "Host"), /* @__PURE__ */ React.createElement("th", null, "Status"), /* @__PURE__ */ React.createElement("th", null, "Capacity"), /* @__PURE__ */ React.createElement("th", null, "Core busy now"), /* @__PURE__ */ React.createElement("th", null, "Steal p95"), /* @__PURE__ */ React.createElement("th", null, "RAM available"), /* @__PURE__ */ React.createElement("th", null, "Disk used"), /* @__PURE__ */ React.createElement("th", null, "Instances"), /* @__PURE__ */ React.createElement("th", null, "Players now"), /* @__PURE__ */ React.createElement("th", null, "Late-frame events 24 h"), /* @__PURE__ */ React.createElement("th", null, "Events 24 h"))), /* @__PURE__ */ React.createElement("tbody", null, hosts.map((h) => /* @__PURE__ */ React.createElement(HostRow, { key: h.id, host: h, onOpen: setOpen }))))) : null, open ? /* @__PURE__ */ React.createElement(HostModal, { ctx, host: open, isOpen: true, onClose: () => setOpen(null) }) : null);
}
export {
  Page as default
};
