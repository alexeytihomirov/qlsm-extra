# host_menu panel: tier-1 form, not the old rich modal

This addon used to ship bundled with QLSM and mounted a hand-built React
component (`ui/TelemetryRelayModal.jsx`, kept here for reference) via the
`bundled:` component tier documented in qlsm's `addons/UI-GUIDE.md` /
`addons/README.md`. That tier is refused for anything that isn't shipped
inside QLSM's own image (`addon.source !== 'bundled'`), so once this addon
moved out to its own repo, the host-level panel had to fall back to a
generic declarative `form` panel (`host_relay` in `qlsm-addon.json`).

What was lost: the live sidecar-status badge and the routed-instances list
(`GET hosts/{host_id}/status`) that `TelemetryRelayModal.jsx` rendered.
The declarative form only covers the plain enable/url-override/token-override
fields (`GET`/`PUT hosts/{host_id}`); the status endpoint is still there in
`backend.py` and untouched, just not wired into any UI right now.

To get the richer UI back, build this as a proper tier-2 addon component
instead (see `addons/README.md`'s "tier 2" section in the qlsm repo).

**There is a worked example now:** `addons/demo-management/` went through
exactly this migration and kept its whole screen. Copy its `ui-src/` +
`vite.config.js` + `package.json` shape:

* `ui-src/runtime.js` -- reads qlsm's React and UI kit off `window.__qlsm`,
  and the Vite config aliases `react` to it. Not a rollup "external": an
  external leaves a bare `import ... from "react"` the browser cannot
  resolve, since qlsm loads the file with a plain dynamic `import()`.
* `ui-src/panel.css` -- Tailwind scoped to the addon's own sources, plus
  copies (renamed, so they cannot restyle core) of the plain classes the
  component used to borrow from qlsm's `index.css`.
* `ui-src/icons.jsx` -- the lucide glyphs core's `ctx.ui.Icon` allow-list
  does not carry, inlined instead of bundling lucide-react.
* Manifest: `"component": "ui/Panel.js"`, `"renders": "modal"`, `ui_api: 3`.
  `renders: "modal"` means the component *is* the whole dialog, which is how
  a rich screen survives the move; `ctx.modal` carries open/close + the
  entity.

The status endpoint this panel lost (`GET hosts/{host_id}/status`) is still
in `backend.py`, untouched, waiting for that component to exist.
