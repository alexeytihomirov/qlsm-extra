"""Parse what the engine prints over rcon for a bare cvar name.

The engine answers `name` with one line:

    "sv_maxclients" is:"16^7" default:"24^7" latched:"24"

`^7` after the value and the default is the engine resetting the colour, not
part of the value, so it is cut; colour codes *inside* a value (a coloured
sv_hostname) are kept. `, the default` in place of `default:"..."` means the
value is the default. `latched:"x"` appears when the cvar is latched: the
new value is stored and applies on the next map (or restart).

Frames arrive the same way qlsm's own rcon service sees them (see
qlsm/rcon_service/message_parser.py): `print "..."` wrappers, broadcasts, and
line fragments without a trailing newline that belong together.
"""
import re

_PRINT_RE = re.compile(r'^\s*print "(.*)"\s*$', re.S)
_CVAR_RE = re.compile(
    r'^"(?P<name>[A-Za-z0-9_]+)"\s+is:"(?P<value>.*?)\^7"'
    r'(?:(?P<is_default>,\s*the default)|\s+default:"(?P<default>.*?)\^7")?'
    r'(?:\s+latched:\s*"(?P<latched>[^"]*)")?'
)


def frame_to_text(raw):
    """One zmq frame to plain text, without the engine's `print` wrapper."""
    text = raw.decode('utf-8', errors='replace') if isinstance(raw, bytes) else str(raw)
    text = text.replace(chr(25), '').replace(chr(19), '')
    stripped = text.lstrip()
    match = _PRINT_RE.match(stripped)
    if match:
        return match.group(1)
    return text


def frames_to_lines(frames):
    """Join fragments into whole lines; drop the engine's own command echo
    (`zmq RCON command from ...`), which is noise for the operator."""
    lines, buffer = [], []

    def flush():
        line = ''.join(buffer).replace('\r', '').replace('\n', '').strip()
        buffer.clear()
        if line and not line.startswith('zmq RCON command'):
            lines.append(line)

    for raw in frames:
        text = frame_to_text(raw)
        buffer.append(text)
        if text.endswith('\n') or text.endswith('\r'):
            flush()
    if buffer:
        flush()
    return lines


def parse_cvar_line(line):
    match = _CVAR_RE.match(line.strip())
    if not match:
        return None
    value = match.group('value')
    if match.group('is_default'):
        default = value
    else:
        default = match.group('default')
    return {
        'name': match.group('name'),
        'value': value,
        'default': default,
        'latched': match.group('latched'),
        'raw': line,
    }


def parse_cvar_lines(lines):
    """{lower-case name: parsed entry}; the last report for a name wins, the
    way the engine's state is the last thing it printed."""
    found = {}
    for line in lines:
        entry = parse_cvar_line(line)
        if entry:
            found[entry['name'].lower()] = entry
    return found
