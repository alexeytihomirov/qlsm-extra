"""!call - a player asks the referees for help.

The plugin only answers the caller. The call itself travels as the ordinary
chat line `say "!call ..."`: stream_telemetry_unified's client_command hook
(PRI_LOWEST) already forwards every `say` to the stats hub, which turns a
`!call` line into a referee ticket. So this plugin does no network or Redis
I/O and keeps no hook of its own on the hot path.
"""

import math
import time

try:
    import minqlxtended as minqlx
except ImportError:
    import minqlx

CALL_COOLDOWN_S = 60
NOTIFIED_TEXT = "Referees have been notified."


def decide(last_call_at, now):
    """Pure decision: returns (reply text, new stored time of the last call).

    last_call_at is None for a first call. Within the cooldown the stored time
    is returned unchanged, so waiting does not extend the wait.
    """
    if last_call_at is not None:
        remaining = CALL_COOLDOWN_S - (now - last_call_at)
        if remaining > 0:
            return "Please wait {} s before calling again.".format(int(math.ceil(remaining))), last_call_at
    return NOTIFIED_TEXT, now


class referee_call(minqlx.Plugin):
    def __init__(self):
        self._last_call = {}
        # permission=0: anyone may use it from chat, including spectators (the
        # chat channel is not team-bound). The handler returns None, so the chat
        # line is neither stopped nor hidden from other hooks.
        self.add_command("call", self.cmd_call, 0, usage="[reason]")
        self.plugin_version = "1.0"

    def cmd_call(self, player, msg, channel):
        now = time.monotonic()
        # Forget expired entries so the dict does not grow for the whole uptime.
        for sid in [s for s, t in self._last_call.items() if now - t >= CALL_COOLDOWN_S]:
            del self._last_call[sid]
        text, stored = decide(self._last_call.get(player.steam_id), now)
        self._last_call[player.steam_id] = stored
        # tell() reaches the caller only; channel.reply() would answer the whole chat.
        player.tell("^3Referee:^7 " + text)
