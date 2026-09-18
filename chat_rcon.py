"""Chat !rcon — tiered ACL console passthrough (core always-on).

See docs/superpowers/specs/2026-08-05-chat-rcon-design.md

ACL helpers are inlined (not a sibling import): minqlx loads plugins as
package submodules and flat imports of chat_rcon_acl fail at runtime.
Unit tests still cover the same logic via chat_rcon_acl.py.
"""

import minqlxtended as minqlx

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

RESULT_OK = "ok"
RESULT_DENY = "deny"
RESULT_DISABLED = "disabled"
RESULT_USAGE = "usage"


def parse_csv(raw, defaults):
    if raw is None:
        return set(t.lower() for t in defaults)
    text = str(raw).strip()
    if not text:
        return set(t.lower() for t in defaults)
    parts = []
    for chunk in text.replace(";", ",").split(","):
        for token in chunk.split():
            t = token.strip().lower()
            if t:
                parts.append(t)
    if not parts:
        return set(t.lower() for t in defaults)
    return set(parts)


def normalize_command_line(raw):
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
    return full, first.lower(), second.lower()


def _denied_by_admin_list(first_cf, second_cf, deny):
    if first_cf in deny:
        return True
    if first_cf in ("set", "seta") and second_cf in deny:
        return True
    if first_cf in ("set", "seta") and second_cf == "rconpassword":
        return True
    return False


def evaluate_acl(
    enabled,
    perm_level,
    cmd_line,
    ref_perm=3,
    admin_perm=5,
    ref_commands=None,
    admin_deny=None,
    player_is_none=False,
):
    if not enabled:
        return RESULT_DISABLED, "chat-rcon disabled", ""

    full, first_cf, second_cf = normalize_command_line(cmd_line)
    if not first_cf:
        return RESULT_USAGE, "usage: !rcon <command> [args...]", ""

    if ref_commands is not None:
        ref_set = set(t.lower() for t in ref_commands)
    else:
        ref_set = set(t.lower() for t in DEFAULT_REF_COMMANDS)
    if admin_deny is not None:
        deny_set = set(t.lower() for t in admin_deny)
    else:
        deny_set = set(t.lower() for t in DEFAULT_ADMIN_DENY)
    deny_set = set(deny_set)
    deny_set.add("rconpassword")

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

    if first_cf not in ref_set:
        return RESULT_DENY, "command not allowed for referee", full
    return RESULT_OK, "ok", full


class chat_rcon(minqlx.Plugin):
    def __init__(self):
        self.set_cvar_once("qlx_chatRconEnabled", "1")
        self.set_cvar_once("qlx_chatRconRefPerm", "3")
        self.set_cvar_once("qlx_chatRconAdminPerm", "5")
        self.set_cvar_once(
            "qlx_chatRconRefCommands",
            ",".join(DEFAULT_REF_COMMANDS),
        )
        self.set_cvar_once(
            "qlx_chatRconAdminDeny",
            ",".join(DEFAULT_ADMIN_DENY),
        )
        # perm 0: handler enforces ref/admin tiers. Stock essentials also registers
        # !rcon at perm 5; keep both, but Priority.HIGHEST makes the winner
        # deterministic instead of depending on qlx_plugins load order.
        # CommandInvoker checks priority buckets before per-bucket (load-order)
        # position, and this handler always returns STOP_ALL, so it always runs
        # first and essentials' !rcon never fires while this plugin is enabled —
        # including for perm-5 admins, so the deny-list (exec/vstr/quit/
        # rconpassword/...) always applies.
        self.add_command(
            "rcon", self.cmd_rcon, 0,
            priority=minqlx.Priority.HIGHEST,
            usage="<command> [args...]",
        )

    def _enabled(self):
        return self.get_cvar("qlx_chatRconEnabled", bool) is not False

    def _ref_perm(self):
        try:
            return int(self.get_cvar("qlx_chatRconRefPerm") or 3)
        except (TypeError, ValueError):
            return 3

    def _admin_perm(self):
        try:
            return int(self.get_cvar("qlx_chatRconAdminPerm") or 5)
        except (TypeError, ValueError):
            return 5

    def _ref_commands(self):
        return parse_csv(
            self.get_cvar("qlx_chatRconRefCommands"),
            DEFAULT_REF_COMMANDS,
        )

    def _admin_deny(self):
        return parse_csv(
            self.get_cvar("qlx_chatRconAdminDeny"),
            DEFAULT_ADMIN_DENY,
        )

    def _actor_perm(self, player):
        if player is None:
            return None
        try:
            for level in (5, 4, 3, 2, 1):
                if self.db.has_permission(player, level):
                    return level
        except Exception:
            return 0
        return 0

    def _actor_label(self, player):
        if player is None:
            return "console(none)"
        name = getattr(player, "name", None) or "?"
        steam = getattr(player, "steam_id", None) or "?"
        return "{}({})".format(name, steam)

    def _reply(self, player, channel, msg):
        if player is not None:
            try:
                player.tell(msg)
                return
            except Exception:
                pass
        if channel is not None:
            try:
                channel.reply(msg)
            except Exception:
                pass

    def _log(self, player, result, line):
        minqlx.console_print(
            "chat-rcon: {} {} {}".format(self._actor_label(player), result, line or "-")
        )

    def cmd_rcon(self, player, msg, channel):
        raw_line = " ".join(msg[1:]) if msg and len(msg) > 1 else ""
        result, reason, full = evaluate_acl(
            enabled=self._enabled(),
            perm_level=self._actor_perm(player),
            cmd_line=raw_line,
            ref_perm=self._ref_perm(),
            admin_perm=self._admin_perm(),
            ref_commands=self._ref_commands(),
            admin_deny=self._admin_deny(),
            player_is_none=(player is None),
        )

        if result == RESULT_USAGE:
            self._reply(player, channel, reason)
            self._log(player, result, raw_line)
            return minqlx.Return.STOP_ALL

        if result == RESULT_DISABLED:
            self._reply(player, channel, "chat-rcon: disabled")
            self._log(player, result, full or raw_line)
            return minqlx.Return.STOP_ALL

        if result != RESULT_OK:
            self._reply(player, channel, "chat-rcon: {}".format(reason))
            self._log(player, result, full or raw_line)
            return minqlx.Return.STOP_ALL

        minqlx.console_command(full)
        self._reply(player, channel, "chat-rcon: ok: {}".format(full))
        self._log(player, RESULT_OK, full)
        return minqlx.Return.STOP_ALL
