"""Pure ACL helpers for chat_rcon (no minqlx import)."""

from __future__ import annotations

from typing import Iterable, Sequence, Set, Tuple

DEFAULT_REF_COMMANDS = (
    "pause",
    "unpause",
    "abort",
    "map",
    "teamsize",
    "timelimit",
    "fraglimit",
    "g_password",
    "lock",
    "unlock",
    "allready",
    "forceteam",
    "putteam",
)

DEFAULT_ADMIN_DENY = (
    "quit",
    "rconpassword",
    "exec",
    "vstr",
    "alias",
    "bind",
    "system",
    "devmap",
)

# Results from evaluate_acl
RESULT_OK = "ok"
RESULT_DENY = "deny"
RESULT_DISABLED = "disabled"
RESULT_USAGE = "usage"


def parse_csv(raw: str | None, defaults: Sequence[str]) -> Set[str]:
    """Parse comma/whitespace-separated tokens; empty/None → defaults."""
    if raw is None:
        return {t.casefold() for t in defaults}
    text = str(raw).strip()
    if not text:
        return {t.casefold() for t in defaults}
    parts = []
    for chunk in text.replace(";", ",").split(","):
        for token in chunk.split():
            t = token.strip().casefold()
            if t:
                parts.append(t)
    if not parts:
        return {t.casefold() for t in defaults}
    return set(parts)


def normalize_command_line(raw: str | None) -> Tuple[str, str, str]:
    """Return (full_line, first_token_cf, second_token_cf).

    Strips one leading slash on the first token. Empty → ("", "", "").
    """
    text = str(raw or "").strip()
    if not text:
        return "", "", ""
    parts = text.split(None, 1)
    first = parts[0]
    if first.startswith("/"):
        first = first[1:]
    rest = parts[1] if len(parts) > 1 else ""
    full = first if not rest else "{} {}".format(first, rest)
    second = ""
    if rest:
        second = rest.split(None, 1)[0]
    return full, first.casefold(), second.casefold()


def _denied_by_admin_list(first_cf: str, second_cf: str, deny: Set[str]) -> bool:
    if first_cf in deny:
        return True
    if first_cf in ("set", "seta") and second_cf in deny:
        return True
    if first_cf in ("set", "seta") and second_cf == "rconpassword":
        return True
    return False


def evaluate_acl(
    *,
    enabled: bool,
    perm_level: int | None,
    cmd_line: str | None,
    ref_perm: int = 3,
    admin_perm: int = 5,
    ref_commands: Iterable[str] | None = None,
    admin_deny: Iterable[str] | None = None,
    player_is_none: bool = False,
) -> Tuple[str, str, str]:
    """Decide whether to run a chat-rcon line.

    Returns (result, reason, normalized_full_line).
    result ∈ {ok, deny, disabled, usage}.

    player_is_none: console/RCON invoke — skip whitelist; still apply admin deny.
    perm_level ignored when player_is_none (treated as admin path).
    """
    if not enabled:
        return RESULT_DISABLED, "chat-rcon disabled", ""

    full, first_cf, second_cf = normalize_command_line(cmd_line)
    if not first_cf:
        return RESULT_USAGE, "usage: !rcon <command> [args…]", ""

    ref_set = (
        {t.casefold() for t in ref_commands}
        if ref_commands is not None
        else {t.casefold() for t in DEFAULT_REF_COMMANDS}
    )
    deny_set = (
        {t.casefold() for t in admin_deny}
        if admin_deny is not None
        else {t.casefold() for t in DEFAULT_ADMIN_DENY}
    )
    # Always treat bare rconpassword as denied even if removed from CSV
    deny_set = set(deny_set) | {"rconpassword"}

    if player_is_none:
        if _denied_by_admin_list(first_cf, second_cf, deny_set):
            return RESULT_DENY, "command denied", full
        return RESULT_OK, "ok", full

    level = int(perm_level if perm_level is not None else -1)
    if level < int(ref_perm):
        return RESULT_DENY, "permission denied", full

    if level >= int(admin_perm):
        if _denied_by_admin_list(first_cf, second_cf, deny_set):
            return RESULT_DENY, "command denied", full
        return RESULT_OK, "ok", full

    # referee band: ref_perm <= level < admin_perm
    if first_cf not in ref_set:
        return RESULT_DENY, "command not allowed for referee", full
    return RESULT_OK, "ok", full
