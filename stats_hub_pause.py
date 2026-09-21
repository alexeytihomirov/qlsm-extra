# Shared pause detection for stats-hub telemetry / session_events.
#
# QL console `pause` / chat `!rcon pause` may not expose sv_paused to get_cvar().
# We combine cvar probes, minqlx game flags (when present), and explicit rcon
# pause/unpause commands observed via client_command.

_PAUSE_LATCH = False


def set_pause_latch(active):
    global _PAUSE_LATCH
    _PAUSE_LATCH = bool(active)


def pause_latch_active():
    return bool(_PAUSE_LATCH)


def _cvar_truthy(plugin, name):
    try:
        raw = plugin.get_cvar(name)
    except Exception:
        return False
    if raw is None:
        return False
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, (int, float)):
        return int(raw) != 0
    text = str(raw).strip().lower()
    return text not in ("0", "", "false", "off", "no")


def _game_paused(plugin):
    game = getattr(plugin, "game", None)
    if game is None:
        return False
    for attr in ("paused", "is_paused"):
        try:
            val = getattr(game, attr, None)
        except Exception:
            val = None
        if val is not None and bool(val):
            return True
    return False


def raw_paused(plugin):
    """Real engine/cvar signal only — bypasses the operator-intent latch.

    Useful as a positive signal when cvars flip. On Quake Live, console/
    ``!pause`` often leaves ``sv_paused`` at 0 even when freeze works — do
    **not** treat a False result alone as proof that pause failed. See
    ``accept_console_pause``."""
    return bool(
        any(_cvar_truthy(plugin, name) for name in ("sv_paused", "cl_paused", "g_paused"))
        or _game_paused(plugin)
    )


def accept_console_pause(raw_ok, match_state):
    """Whether console ``pause`` should be treated as successful after issue.

    ``raw_ok`` True → always accept. Warmup → reject (pause often a no-op for
    match freeze). Otherwise accept and latch intent: QL commonly keeps pause
    cvars at 0 while the match is actually frozen.
    """
    if raw_ok:
        return True
    if match_state == "warmup":
        return False
    return True


def paused_active(plugin):
    """Return True when the match should be treated as paused for stats-hub."""
    global _PAUSE_LATCH
    if any(
        _cvar_truthy(plugin, name) for name in ("sv_paused", "cl_paused", "g_paused")
    ) or _game_paused(plugin):
        _PAUSE_LATCH = True
        return True
    # QL minqlx !pause often leaves sv_paused at 0 — keep explicit latch until !unpause.
    if _PAUSE_LATCH:
        return True
    return False


PAUSE_TEXT_CMD_PERM = 5


def _actor_allowed(plugin, player):
    """Console/RCON (player None) is trusted; players need perm>=5.

    Without this any client could flip the latch by typing "pause"/"unpause"
    in chat or as a raw client command the engine itself rejects."""
    if player is None:
        return True
    if plugin is None:
        return False
    try:
        return bool(plugin.db.has_permission(player, PAUSE_TEXT_CMD_PERM))
    except Exception:
        return False


def note_client_command(cmd, player=None, plugin=None):
    """Track explicit pause/unpause from chat !rcon or direct console lines.

    Pass the acting player and the calling plugin from client_command/chat
    hooks so unprivileged clients cannot spoof the latch (player=None means
    console/RCON and is trusted)."""
    text = str(cmd or "").strip()
    if not text:
        return
    lower = text.lower()
    if lower.startswith("say ") or lower.startswith("say_team "):
        parts = text.split(None, 1)
        if len(parts) < 2:
            return
        text = parts[1].strip().strip('"')
        lower = text.lower()
    if lower.startswith("!rcon "):
        text = text[6:].strip()
        lower = text.lower()
    if lower.startswith("!"):
        lower = lower[1:].lstrip()
    is_pause = lower == "pause" or lower.startswith("pause ")
    is_unpause = lower == "unpause" or lower.startswith("unpause ")
    if not (is_pause or is_unpause):
        return
    if not _actor_allowed(plugin, player):
        return
    set_pause_latch(bool(is_pause))


def reset_pause_state():
    set_pause_latch(False)
