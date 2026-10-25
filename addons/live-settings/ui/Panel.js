const runtime = typeof window !== "undefined" ? window.__qlsm : void 0;
if (!runtime || !runtime.react || !runtime.ui) {
  throw new Error(
    "live-settings: window.__qlsm.react is not published. This bundle only runs inside QLSM, which publishes its React and UI kit before mounting an addon component."
  );
}
const React = runtime.react;
const {
  Fragment,
  createElement,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState
} = React;
runtime.ui;
const CVAR_NAME_RE = /^[A-Za-z0-9_]+$/;
function baselineValue(row) {
  if (row.reported && row.live !== null && row.live !== void 0) return row.live;
  if (row.cfg !== null && row.cfg !== void 0) return row.cfg;
  return row.default ?? "";
}
function currentValue(row, edits) {
  return Object.prototype.hasOwnProperty.call(edits, row.name) ? edits[row.name] : baselineValue(row);
}
function isChanged(row, edits) {
  return currentValue(row, edits) !== baselineValue(row);
}
function stripColors(text) {
  return String(text ?? "").replace(/\^[0-9a-zA-Z]/g, "");
}
function rowState(row, edits, rconOk) {
  if (isChanged(row, edits)) return { kind: "changed", text: "changed" };
  if (row.latched !== null && row.latched !== void 0) {
    return { kind: "info", text: `latched ${row.latched} · on next map` };
  }
  if (!rconOk) return { kind: "muted", text: "no live value" };
  if (!row.reported) return { kind: "muted", text: "unknown to server" };
  const hasCfg = row.cfg !== null && row.cfg !== void 0;
  if (!hasCfg) {
    const def = row.live_default ?? row.default;
    if (def !== null && def !== void 0 && def === row.live) return { kind: "muted", text: "default" };
    return { kind: "warn", text: "live only · lost on restart" };
  }
  if (row.cfg !== row.live) return { kind: "warn", text: `drift · cfg ${row.cfg}` };
  return { kind: "ok", text: "in sync" };
}
function pendingChanges(groups, edits) {
  const out = [];
  for (const group of groups || []) {
    for (const row of group.cvars || []) {
      if (isChanged(row, edits)) out.push({ name: row.name, value: currentValue(row, edits) });
    }
  }
  return out;
}
function entryState(entry) {
  switch (entry.state) {
    case "live":
      return { kind: "ok", text: "live" };
    case "latched":
      return { kind: "warn", text: "applies on next map" };
    case "mismatch":
      return { kind: "warn", text: `server has ${stripColors(entry.live)}` };
    default:
      return { kind: "warn", text: "no reply from server" };
  }
}
function persistLine(apply) {
  if (!apply.persist) return { kind: "warn", text: "not written to server.cfg · live only" };
  const result = apply.persist_result;
  if (!result) return { kind: "warn", text: "server.cfg not written" };
  if (result.ok && result.unchanged) return { kind: "muted", text: "server.cfg already had these values" };
  if (result.ok) return { kind: "ok", text: "server.cfg updated · sync to host queued, no restart" };
  return { kind: "warn", text: result.skipped || "server.cfg not written" };
}
function formatTime(seconds) {
  if (!seconds) return "";
  const d = new Date(seconds * 1e3);
  const pad = (n) => String(n).padStart(2, "0");
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}
function formatDateTime(seconds) {
  if (!seconds) return "";
  const d = new Date(seconds * 1e3);
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${formatTime(seconds)}`;
}
const RefreshIcon = () => /* @__PURE__ */ React.createElement("svg", { viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: "2", "aria-hidden": "true" }, /* @__PURE__ */ React.createElement("path", { d: "M21 12a9 9 0 1 1-2.64-6.36M21 3v6h-6" }));
const RevertIcon = () => /* @__PURE__ */ React.createElement("svg", { viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: "2", "aria-hidden": "true" }, /* @__PURE__ */ React.createElement("path", { d: "M3 12a9 9 0 1 0 3-6.7L3 8" }), /* @__PURE__ */ React.createElement("path", { d: "M3 3v5h5" }));
const UnpinIcon = () => /* @__PURE__ */ React.createElement("svg", { viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: "2", "aria-hidden": "true" }, /* @__PURE__ */ React.createElement("path", { d: "M18 6 6 18M6 6l12 12" }));
const ZapIcon = () => /* @__PURE__ */ React.createElement("svg", { viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: "2", "aria-hidden": "true" }, /* @__PURE__ */ React.createElement("path", { d: "M13 2 3 14h9l-1 8 10-12h-9l1-8z" }));
const SpinIcon = () => /* @__PURE__ */ React.createElement("svg", { className: "ls-spin", width: "15", height: "15", viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: "2", "aria-hidden": "true" }, /* @__PURE__ */ React.createElement("path", { d: "M21 12a9 9 0 1 1-6.22-8.56" }));
function Chip({ kind, children }) {
  return /* @__PURE__ */ React.createElement("span", { className: `ls-chip ls-chip-${kind}` }, children);
}
function Value({ value, placeholder }) {
  if (value === null || value === void 0) return /* @__PURE__ */ React.createElement("span", { className: "ls-empty" }, placeholder);
  if (value === "") return /* @__PURE__ */ React.createElement("span", { className: "ls-empty" }, "(empty)");
  return /* @__PURE__ */ React.createElement("span", { title: value }, stripColors(value));
}
function Editor({ row, value, onChange }) {
  const label = row.label ? `${row.name}: ${row.label}` : row.name;
  if (row.type === "bool") {
    const on = value === "1" || value.toLowerCase() === "true";
    return /* @__PURE__ */ React.createElement(
      "button",
      {
        type: "button",
        role: "switch",
        "aria-checked": on,
        "aria-label": label,
        className: `ls-track${on ? " ls-on" : ""}`,
        onClick: () => onChange(on ? "0" : "1")
      }
    );
  }
  if (row.type === "number") {
    return /* @__PURE__ */ React.createElement(
      "input",
      {
        className: "ls-input ls-input-num",
        type: "number",
        inputMode: "decimal",
        "aria-label": label,
        min: row.min,
        max: row.max,
        value,
        onChange: (e) => onChange(e.target.value)
      }
    );
  }
  return /* @__PURE__ */ React.createElement(
    "input",
    {
      className: "ls-input",
      type: "text",
      "aria-label": label,
      value,
      onChange: (e) => onChange(e.target.value)
    }
  );
}
function DiffBlock({ diff }) {
  if (!diff) return null;
  const lines = diff.replace(/\n$/, "").split("\n");
  return /* @__PURE__ */ React.createElement("details", { className: "ls-diff", open: true }, /* @__PURE__ */ React.createElement("summary", null, "server.cfg diff"), /* @__PURE__ */ React.createElement("pre", null, lines.map((line, i) => {
    let cls = "";
    if (line.startsWith("+") && !line.startsWith("+++")) cls = "ls-add-line";
    else if (line.startsWith("-") && !line.startsWith("---")) cls = "ls-del-line";
    else if (line.startsWith("@@")) cls = "ls-hunk";
    return /* @__PURE__ */ React.createElement("span", { key: i, className: cls }, line, "\n");
  })));
}
function ApplyLog({ apply }) {
  var _a;
  const time = formatTime(apply.at);
  const persist = persistLine(apply);
  return /* @__PURE__ */ React.createElement("div", { className: "ls-log" }, /* @__PURE__ */ React.createElement("div", { className: "ls-log-head" }, "Apply ", formatDateTime(apply.at), /* @__PURE__ */ React.createElement("span", { className: "ls-chip ls-chip-muted", style: { marginLeft: "auto" } }, "rcon · set, then read back")), /* @__PURE__ */ React.createElement("pre", null, (apply.entries || []).map((entry) => {
    const state = entryState(entry);
    return /* @__PURE__ */ React.createElement(React.Fragment, { key: entry.name }, /* @__PURE__ */ React.createElement("span", { className: "ls-time" }, time), " ", /* @__PURE__ */ React.createElement("span", { className: "ls-cmd" }, entry.command), "\n", "         ", entry.reply ? stripColors(entry.reply) : "(no reply)", "   ", /* @__PURE__ */ React.createElement("span", { className: `ls-${state.kind === "ok" ? "ok" : "warn"}` }, state.text), "\n");
  }), "         ", /* @__PURE__ */ React.createElement("span", { className: `ls-${persist.kind === "ok" ? "ok" : persist.kind === "muted" ? "muted" : "warn"}` }, persist.text), "\n"), /* @__PURE__ */ React.createElement(DiffBlock, { diff: (_a = apply.persist_result) == null ? void 0 : _a.diff }));
}
function Panel({ ctx }) {
  var _a, _b;
  const instanceId = (_a = ctx == null ? void 0 : ctx.scope) == null ? void 0 : _a.id;
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [edits, setEdits] = useState({});
  const [persist, setPersist] = useState(true);
  const [applying, setApplying] = useState(false);
  const [applyError, setApplyError] = useState(null);
  const [addName, setAddName] = useState("");
  const [pinBusy, setPinBusy] = useState(false);
  const retryTimer = useRef(null);
  const alive = useRef(true);
  const load = useCallback(async ({ quiet = false } = {}) => {
    var _a2, _b2, _c;
    if (!instanceId) return null;
    if (!quiet) setLoading(true);
    setError(null);
    try {
      const result = await ctx.api("GET", `instances/${instanceId}/cvars`);
      if (!alive.current) return null;
      setData(result);
      return result;
    } catch (err) {
      if (alive.current) setError(((_c = (_b2 = (_a2 = err == null ? void 0 : err.response) == null ? void 0 : _a2.data) == null ? void 0 : _b2.error) == null ? void 0 : _c.message) || (err == null ? void 0 : err.message) || "Failed to load");
      return null;
    } finally {
      if (alive.current && !quiet) setLoading(false);
    }
  }, [ctx, instanceId]);
  useEffect(() => {
    alive.current = true;
    load();
    return () => {
      alive.current = false;
      if (retryTimer.current) clearTimeout(retryTimer.current);
    };
  }, [load]);
  useEffect(() => {
    var _a2;
    const err = ((_a2 = data == null ? void 0 : data.rcon) == null ? void 0 : _a2.error) || "";
    if (/configuring/i.test(err) && !retryTimer.current) {
      retryTimer.current = setTimeout(() => {
        retryTimer.current = null;
        load({ quiet: true });
      }, 5e3);
    }
  }, [data, load]);
  const groups = (data == null ? void 0 : data.groups) || [];
  const rconOk = Boolean((_b = data == null ? void 0 : data.rcon) == null ? void 0 : _b.ok);
  const pending = useMemo(() => pendingChanges(groups, edits), [groups, edits]);
  const pinnedNames = useMemo(
    () => {
      var _a2;
      return (((_a2 = groups.find((g) => g.id === "pinned")) == null ? void 0 : _a2.cvars) || []).map((c) => c.name);
    },
    [groups]
  );
  const knownNames = useMemo(() => {
    const names = /* @__PURE__ */ new Set();
    groups.forEach((g) => g.cvars.forEach((c) => names.add(c.name.toLowerCase())));
    return names;
  }, [groups]);
  const setEdit = (name, value) => setEdits((prev) => ({ ...prev, [name]: value }));
  const revert = (name) => setEdits((prev) => {
    const next = { ...prev };
    delete next[name];
    return next;
  });
  const apply = async () => {
    var _a2, _b2, _c;
    if (!pending.length || applying) return;
    setApplying(true);
    setApplyError(null);
    try {
      await ctx.api("POST", `instances/${instanceId}/cvars/apply`, {
        data: { changes: pending, persist }
      });
      setEdits({});
      await load({ quiet: true });
    } catch (err) {
      setApplyError(((_c = (_b2 = (_a2 = err == null ? void 0 : err.response) == null ? void 0 : _a2.data) == null ? void 0 : _b2.error) == null ? void 0 : _c.message) || (err == null ? void 0 : err.message) || "Apply failed");
    } finally {
      if (alive.current) setApplying(false);
    }
  };
  const savePinned = async (names) => {
    var _a2, _b2, _c;
    setPinBusy(true);
    setApplyError(null);
    try {
      await ctx.api("PUT", `instances/${instanceId}/pinned`, { data: { cvars: names } });
      await load({ quiet: true });
    } catch (err) {
      setApplyError(((_c = (_b2 = (_a2 = err == null ? void 0 : err.response) == null ? void 0 : _a2.data) == null ? void 0 : _b2.error) == null ? void 0 : _c.message) || (err == null ? void 0 : err.message) || "Could not save the pinned list");
    } finally {
      if (alive.current) setPinBusy(false);
    }
  };
  const addPinned = async () => {
    const name = addName.trim();
    if (!CVAR_NAME_RE.test(name)) {
      setApplyError(`"${name}" is not a cvar name (letters, digits and _ only).`);
      return;
    }
    setAddName("");
    if (knownNames.has(name.toLowerCase())) return;
    await savePinned([...pinnedNames, name]);
  };
  const unpin = async (name) => {
    revert(name);
    await savePinned(pinnedNames.filter((n2) => n2 !== name));
  };
  if (loading && !data) {
    return /* @__PURE__ */ React.createElement("div", { className: "ls-root" }, /* @__PURE__ */ React.createElement("div", { className: "ls-loading" }, /* @__PURE__ */ React.createElement(SpinIcon, null), " Reading values from the server..."));
  }
  if (error && !data) {
    return /* @__PURE__ */ React.createElement("div", { className: "ls-root" }, /* @__PURE__ */ React.createElement("p", { className: "ls-error" }, error), /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("button", { type: "button", className: "ls-btn ls-btn-secondary", onClick: () => load() }, /* @__PURE__ */ React.createElement(RefreshIcon, null), "Retry")));
  }
  const rcon = (data == null ? void 0 : data.rcon) || {};
  const history = (data == null ? void 0 : data.history) || [];
  const n = pending.length;
  const hasRows = groups.some((g) => g.cvars.length);
  return /* @__PURE__ */ React.createElement("div", { className: "ls-root" }, /* @__PURE__ */ React.createElement("div", { className: "ls-toolbar" }, rconOk ? /* @__PURE__ */ React.createElement(Chip, { kind: "ok" }, /* @__PURE__ */ React.createElement("span", { className: "ls-dot" }), "RCON connected", rcon.port ? ` · :${rcon.port}` : "") : /* @__PURE__ */ React.createElement(Chip, { kind: "danger", title: rcon.error }, "no live values", rcon.error ? ` · ${rcon.error}` : ""), rcon.read_at ? /* @__PURE__ */ React.createElement(Chip, { kind: "muted" }, "values read ", formatTime(rcon.read_at)) : null, n ? /* @__PURE__ */ React.createElement(Chip, { kind: "changed" }, n, " change", n > 1 ? "s" : "", " pending") : null, /* @__PURE__ */ React.createElement("span", { className: "ls-spacer" }), /* @__PURE__ */ React.createElement(
    "form",
    {
      className: "ls-add",
      onSubmit: (e) => {
        e.preventDefault();
        addPinned();
      }
    },
    /* @__PURE__ */ React.createElement(
      "input",
      {
        className: "ls-input",
        list: "ls-cvar-suggestions",
        value: addName,
        placeholder: "pin a server cvar, e.g. g_password",
        "aria-label": "Pin a server cvar to this instance",
        onChange: (e) => setAddName(e.target.value),
        disabled: pinBusy
      }
    ),
    /* @__PURE__ */ React.createElement("datalist", { id: "ls-cvar-suggestions" }, ((data == null ? void 0 : data.suggestions) || []).map((name) => /* @__PURE__ */ React.createElement("option", { key: name, value: name }))),
    /* @__PURE__ */ React.createElement("button", { type: "submit", className: "ls-btn ls-btn-secondary", disabled: pinBusy || !addName.trim() }, "Pin")
  ), /* @__PURE__ */ React.createElement("button", { type: "button", className: "ls-btn ls-btn-secondary", onClick: () => load(), disabled: loading }, loading ? /* @__PURE__ */ React.createElement(SpinIcon, null) : /* @__PURE__ */ React.createElement(RefreshIcon, null), "Refresh")), error ? /* @__PURE__ */ React.createElement("p", { className: "ls-error" }, error) : null, /* @__PURE__ */ React.createElement("div", { className: "ls-tablewrap" }, /* @__PURE__ */ React.createElement("table", { className: "ls-table" }, /* @__PURE__ */ React.createElement("thead", null, /* @__PURE__ */ React.createElement("tr", null, /* @__PURE__ */ React.createElement("th", { style: { width: "30%" } }, "Cvar"), /* @__PURE__ */ React.createElement("th", null, "Live"), /* @__PURE__ */ React.createElement("th", null, "server.cfg"), /* @__PURE__ */ React.createElement("th", { style: { width: "22%" } }, "New value"), /* @__PURE__ */ React.createElement("th", null, "State"), /* @__PURE__ */ React.createElement("th", null))), /* @__PURE__ */ React.createElement("tbody", null, !hasRows ? /* @__PURE__ */ React.createElement("tr", { className: "ls-empty-row" }, /* @__PURE__ */ React.createElement("td", { colSpan: 6 }, "No cvars yet: none of this instance's plugins declares cvars in its .ql-plugin.json, and nothing is pinned. Pin a server cvar above to start.")) : null, groups.map((group) => group.cvars.length ? /* @__PURE__ */ React.createElement(React.Fragment, { key: group.id }, /* @__PURE__ */ React.createElement("tr", { className: "ls-group" }, /* @__PURE__ */ React.createElement("td", { colSpan: 6 }, group.label, " ", /* @__PURE__ */ React.createElement("span", null, group.subtitle))), group.cvars.map((row) => {
    const value = currentValue(row, edits);
    const changed = isChanged(row, edits);
    const state = rowState(row, edits, rconOk);
    const cfgPlaceholder = row.default !== null && row.default !== void 0 ? `not set (default ${row.default})` : "not set";
    return /* @__PURE__ */ React.createElement("tr", { key: row.name, className: changed ? "ls-row-changed" : void 0 }, /* @__PURE__ */ React.createElement("td", { className: "ls-name" }, row.name, row.label || row.description ? /* @__PURE__ */ React.createElement("small", null, row.label, row.label && row.description ? " · " : "", row.description) : null), /* @__PURE__ */ React.createElement("td", { className: "ls-val" }, /* @__PURE__ */ React.createElement(Value, { value: row.reported ? row.live : null, placeholder: rconOk ? "no reply" : "-" })), /* @__PURE__ */ React.createElement("td", { className: "ls-val" }, /* @__PURE__ */ React.createElement(Value, { value: row.cfg, placeholder: cfgPlaceholder })), /* @__PURE__ */ React.createElement("td", { className: "ls-edit" }, /* @__PURE__ */ React.createElement(Editor, { row, value, onChange: (v) => setEdit(row.name, v) })), /* @__PURE__ */ React.createElement("td", { className: "ls-state" }, /* @__PURE__ */ React.createElement(Chip, { kind: state.kind }, state.text)), /* @__PURE__ */ React.createElement("td", { className: "ls-act" }, /* @__PURE__ */ React.createElement(
      "button",
      {
        type: "button",
        className: "ls-mini",
        title: "Revert to the current value",
        "aria-label": `Revert ${row.name}`,
        onClick: () => revert(row.name),
        disabled: !changed
      },
      /* @__PURE__ */ React.createElement(RevertIcon, null)
    ), group.id === "pinned" ? /* @__PURE__ */ React.createElement(
      "button",
      {
        type: "button",
        className: "ls-mini",
        title: "Unpin from this list",
        "aria-label": `Unpin ${row.name}`,
        onClick: () => unpin(row.name),
        disabled: pinBusy
      },
      /* @__PURE__ */ React.createElement(UnpinIcon, null)
    ) : null));
  })) : null)))), /* @__PURE__ */ React.createElement("div", { className: "ls-footer" }, /* @__PURE__ */ React.createElement("label", { className: "ls-check" }, /* @__PURE__ */ React.createElement("input", { type: "checkbox", checked: persist, onChange: (e) => setPersist(e.target.checked) }), "Also write to server.cfg ", /* @__PURE__ */ React.createElement("small", null, "(kept after a restart; synced to the host without restarting, the instance shows UPDATED until its next restart)")), /* @__PURE__ */ React.createElement("span", { className: "ls-spacer" }), applyError ? /* @__PURE__ */ React.createElement("span", { className: "ls-error" }, applyError) : null, /* @__PURE__ */ React.createElement("button", { type: "button", className: "ls-btn ls-btn-secondary", onClick: () => setEdits({}), disabled: !n || applying }, "Discard"), /* @__PURE__ */ React.createElement("button", { type: "button", className: "ls-btn ls-btn-primary", onClick: apply, disabled: !n || applying || !rconOk }, applying ? /* @__PURE__ */ React.createElement(SpinIcon, null) : /* @__PURE__ */ React.createElement(ZapIcon, null), applying ? "Applying..." : n ? `Apply ${n} change${n > 1 ? "s" : ""} live` : "Nothing to apply")), history.length ? /* @__PURE__ */ React.createElement("div", { className: "ls-history" }, /* @__PURE__ */ React.createElement(ApplyLog, { apply: history[0] }), history.length > 1 ? /* @__PURE__ */ React.createElement("details", null, /* @__PURE__ */ React.createElement("summary", null, history.length - 1, " earlier appl", history.length - 1 > 1 ? "ies" : "y"), /* @__PURE__ */ React.createElement("div", { className: "ls-history", style: { marginTop: 8 } }, history.slice(1).map((apply2, i) => /* @__PURE__ */ React.createElement(ApplyLog, { key: apply2.at || i, apply: apply2 })))) : null) : null, /* @__PURE__ */ React.createElement("p", { className: "ls-hint" }, "Live values come from the running server over RCON and are shown as the server reports them. A latched cvar applies on the next map or restart; a plugin cvar read once at load (", /* @__PURE__ */ React.createElement("code", null, "set_cvar_once"), ") applies after ", /* @__PURE__ */ React.createElement("code", null, "!reload"), ' or a restart. Anything applied without "write to server.cfg" is gone after a restart and shows as "live only".'));
}
export {
  Panel as default
};
