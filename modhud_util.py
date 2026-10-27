# modhud_util.py - helper of plugins that draw on the shared mod HUD panel. Not a plugin.
#
# The panel is three text lines in our ui/intro.menu (zz_modhud.pk3, hud/build_modhud.py),
# shown while the client cvar mod_hud_on is "1"; the player picks the place with
# `seta mod_hud_pos`. A plugin sets the cvars on one client with a crafted CS_SYSTEMINFO
# (see skills/ql-live/reference/server-driven-hud-and-view.md in the monorepo):
#
#   sent = {}                                    # client id -> fields last sent, owned by the plugin
#   info = minqlx.configstring(minqlx.CS_SYSTEMINFO, cached=False)
#   modhud_util.send(minqlx, sent, player.id, modhud_util.fields(["{rl} 1/2"]), info)
#   modhud_util.send(minqlx, sent, player.id, modhud_util.blank(), info)
#
# Icons are glyphs of our fallback font, written as tokens: {rl}, {mh}, {ra}, ... ({{ = "{").
# Call send() on the game thread only.

import re

FIELDS = ("mod_hud_on", "mod_hud_l1", "mod_hud_l2", "mod_hud_l3")
MAX_LINE_BYTES = 120

_WEAPONS = ("g", "mg", "sg", "gl", "rl", "lg", "rg", "pg", "bfg", "gh", "ng", "pl", "cg", "hmg")
_ITEMS = ("mh", "ra", "ya", "ga", "shard", "quad", "bs", "regen", "haste", "invis", "flight", "flag")

TOKENS = {name: chr(0xE000 + i) for i, name in enumerate(_WEAPONS)}
TOKENS.update({name: chr(0xE010 + i) for i, name in enumerate(_ITEMS)})
TOKENS.update({"on": "▰", "off": "▱"})

_TOKEN = re.compile(r"\{\{|\{(\w+)\}")


def expand(text):
    """Tokens to glyphs; an unknown token stays as typed."""
    def repl(m):
        if m.group(0) == "{{":
            return "{"
        return TOKENS.get(m.group(1), m.group(0))
    return _TOKEN.sub(repl, str(text))


def fit(text, limit=MAX_LINE_BYTES):
    """Cut *text* to *limit* bytes of UTF-8, never inside a character."""
    data = text.encode("utf-8")
    if len(data) <= limit:
        return text
    return data[:limit].decode("utf-8", errors="ignore")


def clean(value):
    return str(value).replace("\\", "").replace('"', "").replace(";", "")


def fields(lines):
    """The panel showing up to three *lines* (tokens expanded); missing lines are empty."""
    lines = [fit(clean(expand(line))) for line in list(lines)[:3]]
    lines += [""] * (3 - len(lines))
    return dict(zip(FIELDS, ["1"] + lines))


def blank():
    return dict(zip(FIELDS, ["0", "", "", ""]))


def diff(sent, new):
    """Fields of *new* that differ from *sent*; a field never sent counts as blank."""
    empty = blank()
    return {k: v for k, v in new.items() if sent.get(k, empty.get(k)) != v}


def command(cs_index, systeminfo, changed):
    """One cs command that sets *changed* as client cvars on top of the current systeminfo."""
    pairs = "".join("\\{}\\{}".format(k, clean(changed[k])) for k in FIELDS if k in changed)
    return 'cs {} "{}{}"'.format(cs_index, systeminfo, pairs)


def send(engine, sent, cid, new, systeminfo):
    """Send *cid* the fields of *new* that changed since sent[cid] and record the result."""
    changed = diff(sent.get(cid, {}), new)
    if not changed:
        return
    try:
        delivered = engine.send_server_command(cid, command(engine.CS_SYSTEMINFO, systeminfo, changed))
    except Exception:
        delivered = False  # the player left
    if delivered is False:
        # Still loading (not CS_ACTIVE): what the client shows is unknown, resend it all.
        sent[cid] = dict.fromkeys(FIELDS)
    elif new.get("mod_hud_on") == "1":
        sent[cid] = dict(new)
    else:
        sent.pop(cid, None)
