"""player-ranks' private copy of the server.cfg cvar-reading helper.

Same regex as qlmatch-packer's and telemetry-relay's own copies (all three
descend from ui/stats_hub.py's original cvar text helpers) -- duplicated, not
imported, since there is no addon-to-addon dependency mechanism to rely on
(see addons/README.md, "Two addons needing the same mechanism"). Only the
read side is needed here: player-ranks never writes to an instance's
server.cfg, only suggests values read from it.
"""
import re


def read_cvars_from_text(text, cvar_names):
    """Returns {name: value} for whichever of `cvar_names` appear as
    `set <name> "value"` lines. Last occurrence wins, matching how the
    engine execs a cfg top to bottom."""
    names = set(cvar_names)
    found = {}
    for line in text.splitlines():
        m = re.match(r'^\s*set\s+([A-Za-z0-9_]+)\s+"(.*)"\s*$', line)
        if m and m.group(1) in names:
            found[m.group(1)] = m.group(2)
    return found
