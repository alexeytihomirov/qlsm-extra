// Everything this bundle takes from QLSM at runtime instead of bundling.
//
// The build aliases `react` to this module, so Panel.jsx can keep a plain
// `import React from 'react'` and still use *core's* React instance: two React
// copies on one page break hooks, which is why core publishes its own on
// window.__qlsm (see qlsm's addons/README.md, "tier 2").
const runtime = typeof window !== 'undefined' ? window.__qlsm : undefined;

if (!runtime || !runtime.react || !runtime.ui) {
  throw new Error(
    'live-settings: window.__qlsm.react is not published. This bundle only '
    + 'runs inside QLSM, which publishes its React and UI kit before mounting '
    + 'an addon component.',
  );
}

const React = runtime.react;

export default React;
export const {
  Fragment, createElement, useCallback, useEffect, useMemo, useRef, useState,
} = React;

/** The shared component kit (Modal, Button, Icon, ...). */
export const ui = runtime.ui;
