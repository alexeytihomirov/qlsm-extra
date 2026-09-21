import React from 'react';

/**
 * The nine lucide icons this screen uses, inlined.
 *
 * Core exposes only a fixed allow-list of icons through `ctx.ui.Icon`
 * (activity, archive, film, download, ... -- see qlsm's addonIcons.js), and
 * it does not include the chevrons, the search glass, the spinner or the
 * close X this table needs. Rather than bundle lucide-react for nine glyphs
 * -- or widen core's allow-list, which is a compatibility promise to every
 * already-built addon -- the paths are inlined here, straight from lucide
 * (ISC). Same geometry, so nothing shifts visually against the rest of QLSM.
 *
 * Attributes mirror lucide's own defaults (24x24 box, currentColor stroke),
 * so `className="h-4 w-4"` sizes them exactly as it did before.
 */
function icon(displayName, children) {
  const Icon = ({ className, strokeWidth = 2, ...rest }) => (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width="24"
      height="24"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true"
      {...rest}
    >
      {children}
    </svg>
  );
  Icon.displayName = displayName;
  return Icon;
}

export const X = icon('X', (
  <>
    <path d="M18 6 6 18" />
    <path d="m6 6 12 12" />
  </>
));

export const RefreshCw = icon('RefreshCw', (
  <>
    <path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8" />
    <path d="M21 3v5h-5" />
    <path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16" />
    <path d="M8 16H3v5" />
  </>
));

export const Film = icon('Film', (
  <>
    <rect width="20" height="20" x="2" y="2" rx="2.18" ry="2.18" />
    <line x1="7" x2="7" y1="2" y2="22" />
    <line x1="17" x2="17" y1="2" y2="22" />
    <line x1="2" x2="22" y1="12" y2="12" />
    <line x1="2" x2="7" y1="7" y2="7" />
    <line x1="2" x2="7" y1="17" y2="17" />
    <line x1="17" x2="22" y1="17" y2="17" />
    <line x1="17" x2="22" y1="7" y2="7" />
  </>
));

export const AlertCircle = icon('AlertCircle', (
  <>
    <circle cx="12" cy="12" r="10" />
    <line x1="12" x2="12" y1="8" y2="12" />
    <line x1="12" x2="12.01" y1="16" y2="16" />
  </>
));

export const FolderOpen = icon('FolderOpen', (
  <path d="m6 14 1.5-2.9A2 2 0 0 1 9.24 10H20a2 2 0 0 1 1.94 2.5l-1.54 6a2 2 0 0 1-1.95 1.5H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h3.9a2 2 0 0 1 1.69.9l.81 1.2a2 2 0 0 0 1.67.9H18a2 2 0 0 1 2 2v2" />
));

export const Download = icon('Download', (
  <>
    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
    <polyline points="7 10 12 15 17 10" />
    <line x1="12" x2="12" y1="15" y2="3" />
  </>
));

export const Search = icon('Search', (
  <>
    <circle cx="11" cy="11" r="8" />
    <path d="m21 21-4.3-4.3" />
  </>
));

export const ChevronRight = icon('ChevronRight', <path d="m9 18 6-6-6-6" />);

export const ChevronDown = icon('ChevronDown', <path d="m6 9 6 6 6-6" />);
