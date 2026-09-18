# tournament_access.py — tournament whitelist from Hub Redis (lobby + game).
#
# Redis key (Hub sync-access): minqlx:tournament:access:{tournament_id}
# JSON: {"rev", "players": [steam_id64, ...], "casters": [...], "enforced": true}
#
# CVARs:
#   qlx_tournamentAccessEnabled "0"   — master switch
#   qlx_tournamentId "0"              — Hub tournament id (must match sync-access key)
#   qlx_tournamentAccessBypassPerm "3" — minqlx permission level that skips checks
#
# Lobby: qlx_lobbyEnabled "1" on server-lobby.cfg — casters/players stay spec; non-list → kick.
# Game: registered players may join teams; casters spec-only.

import json

try:
    import minqlxtended as minqlx
except ImportError:
    import minqlx

ACCESS_KEY = "minqlx:tournament:access:{tournament_id}"
PLAYING_TEAMS = frozenset(("free", "red", "blue"))


class tournament_access(minqlx.Plugin):
    def __init__(self):
        self._cache = None
        self._cache_rev = -1
        self._frame_tick = 0

        self.set_cvar_once("qlx_tournamentAccessEnabled", "0")
        self.set_cvar_once("qlx_tournamentId", "0")
        self.set_cvar_once("qlx_tournamentAccessBypassPerm", "3")
        self.set_cvar_once("qlx_devAuthOpen", "0")

        self.add_hook("player_loaded", self.handle_player_loaded, priority=minqlx.Priority.HIGH)
        self.add_hook("team_switch_attempt", self.handle_team_switch_attempt, priority=minqlx.Priority.HIGH)
        self.add_hook("frame", self.handle_frame)

        self.plugin_version = "1.0"

    def _tournament_id(self):
        try:
            tid = int(self.get_cvar("qlx_tournamentId") or "0")
        except ValueError:
            return 0
        return tid if tid > 0 else 0

    def _master_enabled(self):
        if self.get_cvar("qlx_tournamentAccessEnabled", bool) is False:
            return False
        return self._tournament_id() > 0

    def _dev_auth_open(self):
        raw = self.get_cvar("qlx_devAuthOpen")
        if raw is None:
            return False
        if isinstance(raw, bool):
            return raw
        return str(raw).strip().lower() not in ("0", "false", "")

    def _access_key(self):
        return ACCESS_KEY.format(tournament_id=self._tournament_id())

    @staticmethod
    def _steam_id64(player):
        return str(getattr(player, "steam_id", "")).strip()

    @staticmethod
    def _is_bot(player):
        steam = str(getattr(player, "steam_id", "")).strip()
        return not steam or steam[0] == "9"

    def _bypass(self, player):
        if str(player.steam_id) == str(minqlx.owner()):
            return True
        try:
            need = int(self.get_cvar("qlx_tournamentAccessBypassPerm") or "3")
        except ValueError:
            need = 3
        return self.db.get_permission(player) >= need

    def _is_lobby_server(self):
        raw = self.get_cvar("qlx_lobbyEnabled")
        if raw is None:
            return False
        return bool(raw) if not isinstance(raw, str) else raw.strip().lower() not in ("0", "false", "")

    def _load_access_raw(self):
        raw = self.db.get(self._access_key())
        if not raw:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")
        try:
            return json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            self.logger.warning("tournament_access: bad json for %s", self._access_key())
            return None

    def _refresh_access(self, force=False):
        if not self._master_enabled():
            self._cache = None
            self._cache_rev = -1
            return None

        data = self._load_access_raw()
        if not data:
            if force:
                self._cache = None
                self._cache_rev = -1
            return self._cache

        try:
            rev = int(data.get("rev", 0))
        except (TypeError, ValueError):
            rev = 0

        if not force and self._cache is not None and rev == self._cache_rev:
            return self._cache

        players = {str(p).strip() for p in (data.get("players") or []) if str(p).strip()}
        casters = {str(c).strip() for c in (data.get("casters") or []) if str(c).strip()}
        enforced = bool(data.get("enforced"))

        self._cache = {
            "rev": rev,
            "players": players,
            "casters": casters,
            "enforced": enforced,
        }
        self._cache_rev = rev
        return self._cache

    def _access_active(self):
        access = self._refresh_access()
        if not access or not access.get("enforced"):
            return None
        return access

    def _role(self, player, access):
        sid = self._steam_id64(player)
        if sid in access["players"]:
            return "player"
        if sid in access["casters"]:
            return "caster"
        return None

    def _is_whitelisted(self, player, access):
        return self._role(player, access) is not None

    @staticmethod
    def _steam_id_in_set(steam, allowed):
        if not steam or not allowed:
            return False
        if steam in allowed:
            return True
        try:
            steam_int = int(steam)
        except ValueError:
            return False
        for sid in allowed:
            if steam == sid:
                return True
            try:
                sid_int = int(sid)
            except ValueError:
                continue
            if steam_int == sid_int:
                return True
        return False

    def _is_specbot(self, player):
        prefix = (self.get_cvar("qlx_specbot_name_prefix") or "StreamSpec").strip()
        name = getattr(player, "clean_name", "") or ""
        return bool(prefix) and name.startswith(prefix)

    @minqlx.next_frame
    def _force_spec(self, player, reason=""):
        team = (getattr(player, "team", None) or "").strip().lower()
        if team in ("spectator", "spec"):
            return
        try:
            player.put("spectator")
        except Exception:
            minqlx.console_command("put {} spec".format(player.id))

    @minqlx.next_frame
    def _kick_not_whitelisted(self, player):
        try:
            player.kick("Tournament access: you are not on the whitelist for this server.")
        except Exception as exc:
            self.logger.warning("tournament_access: kick failed for %s: %s", player.name, exc)

    def handle_frame(self, *args, **kwargs):
        if not self._master_enabled():
            return
        self._frame_tick += 1
        if self._frame_tick % 15 != 0:
            return
        self._refresh_access()

    def handle_player_loaded(self, player):
        if self._dev_auth_open():
            return
        if self._is_bot(player) or self._bypass(player):
            return

        if self._is_specbot(player):
            self._force_spec(player, "specbot")
            return

        access = self._access_active()
        if not access:
            return

        role = self._role(player, access)
        if role is None:
            self.logger.info(
                "tournament_access: kick %s (%s) — not on whitelist rev=%s",
                player.name,
                self._steam_id64(player),
                access.get("rev"),
            )
            self._kick_not_whitelisted(player)
            return

        if role == "caster" or self._is_lobby_server():
            self._force_spec(player)

    def handle_team_switch_attempt(self, player, old_team, new_team, target=None):
        if self._dev_auth_open():
            return
        if self._is_bot(player) or self._bypass(player):
            return

        if self._is_specbot(player):
            if new_team in PLAYING_TEAMS:
                player.tell("^3Tournament:^7 spec bots may only spectate.")
                self._force_spec(player, "specbot_team_block")
                return minqlx.Return.STOP_ALL
            return

        access = self._access_active()
        if not access:
            return

        if not self._is_whitelisted(player, access):
            player.tell("^1Tournament:^7 you are not on the whitelist.")
            return minqlx.Return.STOP_ALL

        if new_team not in PLAYING_TEAMS:
            return

        if self._is_lobby_server():
            player.tell("^3Tournament:^7 lobby is spec-only — use ^6!go^7 to join a game server.")
            return minqlx.Return.STOP_ALL

        if self._role(player, access) == "caster":
            player.tell("^3Tournament:^7 casters may only spectate on game servers.")
            return minqlx.Return.STOP_ALL
