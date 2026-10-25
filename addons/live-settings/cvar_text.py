"""Read and rewrite `set <cvar> "<value>"` lines in a server.cfg text.

Python port of qlsm's frontend helper (frontend-react/src/utils/serverCfgCvars.js),
kept behaviour-compatible on purpose: the Plugins tab's cvar form and this
addon write the same file, and the two must agree on which line counts.

- Quake Live applies the LAST `set` for a cvar, so reading and writing both
  target the final occurrence; rewriting the first would leave a later line
  still overriding it.
- `set x "v"` and `seta x v` are both recognised; a hand-written config often
  leaves the quotes off, and treating such a line as absent used to make the
  writer append a second, conflicting `set`.
- Quake Live has no quote escaping, so a value can hold neither a quote nor a
  newline: both are dropped, since either would end the `set` line early and
  let the rest be read as further config lines.
"""
import difflib
import re

CVAR_NAME_RE = re.compile(r'^[A-Za-z0-9_]+$')


def _cvar_re(cvar):
    # Unquoted values end at whitespace or a quote only: `/` is ordinary in a
    # plugin cvar value (an URL, a path) and must stay part of it.
    return re.compile(
        r'^([ \t]*seta?[ \t]+' + re.escape(cvar) + r'[ \t]+)("([^"]*)"|[^\s"]+)',
        re.IGNORECASE | re.MULTILINE,
    )


def _last_match(text, cvar):
    found = None
    for match in _cvar_re(cvar).finditer(text or ''):
        found = match
    return found


def read_cvar(text, cvar):
    """The value the engine would end up with for `cvar`, or None."""
    if not cvar or not CVAR_NAME_RE.match(cvar):
        return None
    match = _last_match(text, cvar)
    if not match:
        return None
    return match.group(3) if match.group(3) is not None else match.group(2)


def sanitize_value(value):
    return re.sub(r'["\r\n]', '', '' if value is None else str(value))


def upsert_cvar(text, cvar, raw_value):
    """Rewrite the last `set`/`seta` of `cvar`, or append one. The rewritten
    line keeps its keyword, indentation and trailing comment; only the value
    changes, always quoted."""
    value = sanitize_value(raw_value)
    text = text or ''
    match = _last_match(text, cvar)
    if match:
        return text[:match.start()] + match.group(1) + '"' + value + '"' + text[match.end():]
    line = f'set {cvar} "{value}"\n'
    if not text:
        return line
    return text + ('' if text.endswith('\n') else '\n') + line


def unified_diff(before, after, filename):
    """Operator-facing diff of the rewrite, empty when nothing changed."""
    if before == after:
        return ''
    lines = difflib.unified_diff(
        before.splitlines(keepends=True), after.splitlines(keepends=True),
        fromfile=filename, tofile=filename, n=2,
    )
    out = []
    for line in lines:
        out.append(line if line.endswith('\n') else line + '\n')
    return ''.join(out)
