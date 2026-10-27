# modhud.py - manual control of the shared mod HUD panel (three lines, see modhud_util.py).
#
#   !hud <1-3> <text>   line n for everyone; icons as tokens: {rl} {mh} {ra} ... ({{ = "{")
#   !hud clear          blank the panel for everyone
#   !hudicons           tell the caller every token with its glyph
#
# Players see the panel with zz_modhud.pk3 installed and pick its place with
# `seta mod_hud_pos` (top, center, bottom, left, topleft, bottomleft, right, topright,
# bottomright, off). Other plugins draw on the panel through modhud_util, not through this one.
try:
    import minqlxtended as minqlx
except ImportError:
    import minqlx

try:
    import modhud_util
except ImportError:
    from . import modhud_util

ICONS_PER_TELL = 6


class modhud(minqlx.Plugin):
    def __init__(self):
        self._lines = ["", "", ""]
        self._sent = {}  # client id -> panel fields last sent
        self.set_cvar_once("qlx_modHudPerm", "3")
        perm = self.get_cvar("qlx_modHudPerm", int)
        self.add_command("hud", self.cmd_hud, perm, usage="<1-3> <text> | clear")
        self.add_command("hudicons", self.cmd_hudicons, perm)
        self.add_hook("map", self.handle_map)
        self.add_hook("player_loaded", self.handle_player_loaded)
        self.add_hook("player_disconnect", self.handle_player_disconnect)

    def _fields(self):
        return modhud_util.fields(self._lines) if any(self._lines) else modhud_util.blank()

    def _send(self, players):
        info = minqlx.configstring(minqlx.CS_SYSTEMINFO, cached=False)
        new = self._fields()
        for player in players:
            if int(player.steam_id) != 0:  # bots have no screen
                modhud_util.send(minqlx, self._sent, int(player.id), new, info)

    def cmd_hud(self, player, msg, channel):
        if len(msg) == 2 and msg[1].lower() == "clear":
            self._lines = ["", "", ""]
        elif len(msg) >= 3 and msg[1] in ("1", "2", "3"):
            self._lines[int(msg[1]) - 1] = " ".join(msg[2:])
        else:
            return minqlx.Return.USAGE
        self._send(self.players())

    def cmd_hudicons(self, player, msg, channel):
        names = list(modhud_util.TOKENS)
        for i in range(0, len(names), ICONS_PER_TELL):
            player.tell("  ".join("{%s} %s" % (name, modhud_util.TOKENS[name])
                                  for name in names[i:i + ICONS_PER_TELL]))

    def handle_map(self, mapname, factory):
        # Join Match hid every panel; loading clients refuse now and get it on player_loaded.
        modhud_util.reset_clients()
        if any(self._lines):
            self._send(self.players())

    def handle_player_loaded(self, player):
        if any(self._lines):
            self._send([player])

    def handle_player_disconnect(self, player, reason):
        self._sent.pop(int(player.id), None)
        modhud_util.forget(int(player.id))
