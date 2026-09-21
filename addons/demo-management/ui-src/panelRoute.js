// Copied from qlsm's frontend-react/src/components/addons/panelRoute.js.
//
// Only the two helpers this component needs, and only because a contributed
// match action arrives as a "POST matches/{name}/rebuild" string that has to
// be split and filled the same way core's declarative panels do it. Copied
// rather than imported: an addon bundle cannot reach into core's build, and
// the kit deliberately exposes components, not route helpers.
//
// If core's own copy ever changes shape, this one does not follow
// automatically -- the route grammar is part of the hook contract documented
// in qlsm's addons/README.md, so a change there is a contract change anyway.

/** Split "GET hosts/{host_id}" into { method, path }. */
export function parseRoute(route) {
  if (typeof route !== 'string' || !route.trim()) return null;
  const trimmed = route.trim();
  const match = trimmed.match(/^(GET|POST|PUT|PATCH|DELETE)\s+(.*)$/i);
  if (match) return { method: match[1].toUpperCase(), path: match[2].trim() };
  return { method: 'GET', path: trimmed };
}

/**
 * Substitute {instance_id} / {scope_id} / {host_id} in a path. An unknown
 * placeholder is left as-is rather than replaced with "undefined": a URL with
 * a literal {foo} fails loudly at the backend, whereas ".../undefined" looks
 * like a real request and can hit the wrong row.
 */
export function fillPath(path, { scope, scopeId } = {}) {
  if (typeof path !== 'string') return '';
  const values = {
    scope_id: scopeId,
    host_id: scope === 'host' ? scopeId : undefined,
    instance_id: scope === 'instance' ? scopeId : undefined,
  };
  return path.replace(/\{(\w+)\}/g, (whole, key) => {
    const value = values[key];
    return value === undefined || value === null ? whole : String(value);
  });
}
