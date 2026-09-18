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
instead (see `addons/README.md`'s "tier 2" section in the qlsm repo): a
small Vite project under this addon that bundles `TelemetryRelayModal.jsx`
as a library (`react`/`react-dom`/`@qlsm/ui` marked external), shipping the
built output under `ui/Panel.js` (+ `.css` if needed). Nobody has done this
yet -- this file exists so the gap is visible instead of silently forgotten.
