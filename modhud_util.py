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
# SV_SendServerCommand drops a command of 1023 bytes or more without a word (minqlxtended
# fork, src/features/reliable.c), and systeminfo length differs per host.
MAX_COMMAND_BYTES = 1022

# Client id -> fields that client shows (None = unknown), shared by every plugin that draws
# on the panel: the module is imported once per server, plugin reloads keep it.
CLIENT = {}
# Client ids loaded but not yet in the game: their Join Match screen will hide the panel.
PENDING = set()

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


def fitted_command(cs_index, systeminfo, changed):
    """command() cut under the engine's limit (longer server commands are dropped silently):
    the longest line loses the excess until it fits. Returns (command, fields as sent)."""
    changed = dict(changed)
    cmd = command(cs_index, systeminfo, changed)
    while len(cmd.encode("utf-8")) + 1 > MAX_COMMAND_BYTES:  # +1: the engine appends "\n"
        lines = [k for k in FIELDS[1:] if changed.get(k)]
        if not lines:
            break  # systeminfo alone is too long; nothing of ours to cut
        longest = max(lines, key=lambda k: len(changed[k].encode("utf-8")))
        excess = len(cmd.encode("utf-8")) + 1 - MAX_COMMAND_BYTES
        changed[longest] = fit(changed[longest], max(0, len(changed[longest].encode("utf-8")) - excess))
        cmd = command(cs_index, systeminfo, changed)
    return cmd, changed


def reset_clients():
    """Every map load opens Join Match, whose onOpen hides the panel: what each client shows is
    unknown until the next send, which then carries every field. Call from the map hook."""
    for cid in CLIENT:
        CLIENT[cid] = dict.fromkeys(FIELDS)


def loaded(cid):
    """player_loaded: the client starts unknown (also after a /reconnect, which fires no
    disconnect). Join Match opens after this and hides the panel (seen live, #26), so the
    panel goes again in full on joined()."""
    CLIENT[cid] = dict.fromkeys(FIELDS)
    PENDING.add(cid)


def joined(cid):
    """First spawn or team switch after player_loaded: Join Match has hidden the panel, what
    the client shows is unknown again. True once per load; then send the panel again."""
    if cid not in PENDING:
        return False
    PENDING.discard(cid)
    CLIENT[cid] = dict.fromkeys(FIELDS)
    return True


def forget(cid):
    """The client left; the next player in the slot starts unknown."""
    CLIENT.pop(cid, None)
    PENDING.discard(cid)


def _changes(sent, cid, new):
    showing = new.get("mod_hud_on") == "1"
    if not showing and cid not in sent:
        return {}  # never shown by this plugin: someone else's panel is not ours to clear
    known = CLIENT.get(cid)
    if known is None:
        return dict(new) if showing or cid in sent else {}
    return diff(known, new)


def needs_send(sent, cid, new):
    return bool(_changes(sent, cid, new))


def send(engine, sent, cid, new, systeminfo):
    """Make client *cid* show *new*: one cs with the fields that differ from what it has.

    *sent* belongs to the calling plugin (client id -> fields it last asked for); it decides
    whether a blank is ours to send. What the client really shows is CLIENT, shared by every
    plugin, because the panel is one per client: the last write wins."""
    changed = _changes(sent, cid, new)
    if changed:
        cmd, changed = fitted_command(engine.CS_SYSTEMINFO, systeminfo, changed)
        try:
            delivered = engine.send_server_command(cid, cmd)
        except Exception:
            delivered = False  # the player left
        if delivered is False:
            # Still loading (not CS_ACTIVE): what the client shows is unknown, resend it all.
            CLIENT[cid] = dict.fromkeys(FIELDS)
            if new.get("mod_hud_on") == "1":
                sent[cid] = dict(new)
            return
        known = dict(CLIENT.get(cid) or {})
        known.update(changed)
        CLIENT[cid] = known
    if new.get("mod_hud_on") == "1":
        sent[cid] = dict(new)
    else:
        sent.pop(cid, None)
