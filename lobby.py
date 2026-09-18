# lobby.py — minqlx lobby: redirect players to game servers.
# Released AS IS. Works with minqlx / minqlxtended (import minqlxtended as minqlx).

"""
Lobby server plugin. Players connect here; the plugin points them to a target
Quake Live instance. QL blocks server-pushed ``connect`` (anti fake-redirect);
players must join via ``/connect IP:port`` in the client console (QL blocks server-pushed connect/open).

CVARs (set in server.cfg or server-lobby.cfg):

  qlx_lobbyEnabled "1"
      Master switch. If 0, only manual !go / !lobbysend work.

  qlx_lobbyPublicHost ""
      Hostname or IP clients must use (public IP). If empty, uses net_ip when
      set, otherwise 127.0.0.1. Destinations may use HOST as alias for this.

  qlx_lobbyDestinations ""
      Semicolon-separated list of targets. Each target:
        slug|host|port|label|password|tags
      password and tags are optional. Example:
        c1|HOST|27961|Championship 1|secret|duel,EU;c2|HOST|27962|Championship 2|secret|duel,EU

  qlx_lobbyDefaultDest ""
      Slug used when no per-player route is set (e.g. c1).

  qlx_lobbyAutoRedirect "1"
      After load: countdown then show /connect hint (not a silent redirect).

  qlx_lobbyRedirectDelay "5"
      Seconds before connect (centerprint countdown).

  qlx_lobbyForceSpec "1"
      Move joining players to spectator (lobby is not for playing).

  qlx_lobbyStayPerm "3"
      Permission level that stays on lobby (no auto-redirect). Owner always stays.

  qlx_lobbyConnectMessage ""
      Extra centerprint line before redirect.

  qlx_hubNotifyDelay "60"
      Hub tournament assignment countdown (seconds) when payload has no connect_delay_seconds.

  qlx_hubNotifyCountdown "1"
      If 1, hub notify with connect shows countdown before /connect hint. !lobby / !go never use this.

Commands:
  !lobby              — list destinations and your assigned route
  !go [slug]          — connect to destination (default: your route or default dest)
  !lobbyset <id> <slug>  — (perm 3) assign persistent route for a player
  !lobbyclear [id]    — (perm 3) clear route
  !lobbysend <id> [slug] — (perm 3) redirect a player now
"""

import json
import time

try:
    import minqlxtended as minqlx
except ImportError:
    import minqlx

ROUTE_KEY = "minqlx:lobby:route:{}"
HUB_NOTIFY_KEY = "minqlx:hub:notify:{}"
HUB_NOTIFY_REV_KEY = "minqlx:hub:notify:rev:{}"


class lobby(minqlx.Plugin):
    def __init__(self):
        self._pending = set()
        self._hub_countdown_pending = set()
        self._hub_frame_tick = 0
        self._hub_delivered_rev = {}

        self.set_cvar_once("qlx_lobbyEnabled", "1")
        self.set_cvar_once("qlx_lobbyPublicHost", "")
        self.set_cvar_once("qlx_lobbyDestinations", "")
        self.set_cvar_once("qlx_lobbyDefaultDest", "")
        self.set_cvar_once("qlx_lobbyAutoRedirect", "1")
        self.set_cvar_once("qlx_lobbyRedirectDelay", "5")
        self.set_cvar_once("qlx_lobbyForceSpec", "1")
        self.set_cvar_once("qlx_lobbyStayPerm", "3")
        self.set_cvar_once("qlx_lobbyConnectMessage", "")
        self.set_cvar_once("qlx_lobbyTrySteamOpen", "0")
        self.set_cvar_once("qlx_lobbyInstancesJson", "")
        self.set_cvar_once("qlx_hubNotifyDelay", "60")
        self.set_cvar_once("qlx_hubNotifyCountdown", "1")

        self.add_hook("player_loaded", self.handle_player_loaded, priority=minqlx.Priority.LOW)
        self.add_hook("team_switch_attempt", self.handle_team_switch_attempt, priority=minqlx.Priority.HIGH)
        self.add_hook("frame", self.handle_hub_notify_frame)

        self.add_command(("lobby", "servers"), self.cmd_lobby, client_cmd_perm=0)
        self.add_command(("go", "join", "play"), self.cmd_go, usage="[slug]", client_cmd_perm=0)
        self.add_command("lobbyset", self.cmd_lobbyset, 3, usage="<id> <slug>")
        self.add_command("lobbyclear", self.cmd_lobbyclear, 3, usage="[id]")
        self.add_command("lobbysend", self.cmd_lobbysend, 3, usage="<id> [slug]")
        self.add_command(("lobbynotify", "hubnotify"), self.cmd_lobbynotify, 0)

        self.plugin_version = "1.3"

    @staticmethod
    def _find_player_by_steam(players, steam_id64):
        want = str(steam_id64).strip()
        try:
            want_int = int(want)
        except ValueError:
            want_int = None
        for p in players:
            sid = getattr(p, "steam_id", "")
            if str(sid).strip() == want:
                return p
            if want_int is not None:
                try:
                    if int(sid) == want_int:
                        return p
                except (TypeError, ValueError):
                    pass
        return None

    @staticmethod
    def _show_hub_assignment(player, data):
        name = data.get("server_name") or "server"
        connect = data.get("connect") or ""
        lines = data.get("lines") or []
        if not lines and connect:
            lines = [
                "Турнир: {}".format(data.get("tournament_name", "")),
                "Сервер: {}".format(name),
                "/connect {}".format(connect),
            ]
        player.center_print("^2Турнир\n\n^7Ваш сервер:\n^6{}\n\n^7/connect ^6{}".format(name, connect))
        player.tell("^3Hub:^7 назначение для вас:")
        for line in lines[:8]:
            player.tell("^7{}".format(line))

    def _hub_connect_delay_seconds(self, data):
        if data.get("connect_delay_seconds") is not None:
            try:
                return max(0, int(data["connect_delay_seconds"]))
            except (TypeError, ValueError):
                pass
        try:
            return max(0, int(self.get_cvar("qlx_hubNotifyDelay") or "60"))
        except (TypeError, ValueError):
            return 60

    def _deliver_hub_assignment(self, player, data):
        connect = (data.get("connect") or "").strip()
        if connect and self.get_cvar("qlx_hubNotifyCountdown", bool):
            self._countdown_connect_assignment(player, data)
        else:
            self._show_hub_assignment(player, data)

    @minqlx.thread
    def _countdown_connect_assignment(self, player, data):
        connect = (data.get("connect") or "").strip()
        if not connect:
            return
        sid = str(player.steam_id)
        if sid in self._hub_countdown_pending:
            return
        self._hub_countdown_pending.add(sid)
        try:
            name = data.get("server_name") or "server"
            tournament = (data.get("tournament_name") or "").strip()
            delay = self._hub_connect_delay_seconds(data)
            title = "^2Турнир"
            if tournament:
                title = "^2{}".format(tournament)
            for remaining in range(delay, 0, -1):
                if sid not in [str(p.steam_id) for p in self.players()]:
                    return
                player.center_print(
                    "{}\n\n^7Сервер: ^6{}\n\n^7Подключитесь через ^1{}^7...".format(
                        title, name, remaining))
                time.sleep(1)
            self._show_hub_assignment(player, data)
        finally:
            self._hub_countdown_pending.discard(sid)

    def handle_hub_notify_frame(self, *args, **kwargs):
        self._hub_frame_tick += 1
        if self._hub_frame_tick % 10 != 0:
            return
        for player in self.players():
            self._check_hub_notify_player(player)

    def _check_hub_notify_player(self, player):
        sid = str(player.steam_id)
        key = HUB_NOTIFY_KEY.format(sid)
        raw = self.db.get(key)
        if not raw:
            return
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")
        try:
            data = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            self.logger.warning("lobby: bad hub notify json for %s", sid)
            return

        rev = str(data.get("assignment_rev", data.get("connect", "0")))
        if self._hub_delivered_rev.get(sid) == rev:
            return

        self._deliver_hub_assignment(player, data)
        self._hub_delivered_rev[sid] = rev
        self.db.set(HUB_NOTIFY_REV_KEY.format(sid), rev)
        self.logger.info("hub notify (redis) -> %s (%s)", player.name, sid)

    def _deliver_hub_notify(self, data):
        steam = str(data.get("steam_id64", "")).strip()
        if not steam:
            return False
        target = self._find_player_by_steam(self.players(), steam)
        if not target:
            return False
        self._deliver_hub_assignment(target, data)
        rev = str(data.get("assignment_rev", data.get("connect", "0")))
        self._hub_delivered_rev[steam] = rev
        self.db.set(HUB_NOTIFY_REV_KEY.format(steam), rev)
        self.logger.info("hub notify delivered to %s (%s)", target.name, steam)
        return True

    # ------------------------------------------------------------------
    # Destinations
    # ------------------------------------------------------------------

    def public_host(self):
        host = (self.get_cvar("qlx_lobbyPublicHost") or "").strip()
        if host:
            return host
        host = (minqlx.get_cvar("net_ip") or "").strip()
        if host and host != "0.0.0.0":
            return host
        return "127.0.0.1"

    def parse_destinations(self):
        """Return dict slug -> {host, port, label, password, tags}."""
        dests = {}
        raw = (self.get_cvar("qlx_lobbyDestinations") or "").strip()
        if raw:
            for chunk in raw.split(";"):
                chunk = chunk.strip()
                if not chunk:
                    continue
                parts = [p.strip() for p in chunk.split("|")]
                if len(parts) < 4:
                    self.logger.warning("lobby: skip invalid dest chunk: %r", chunk)
                    continue
                slug, host, port_s, label = parts[0], parts[1], parts[2], parts[3]
                password = parts[4] if len(parts) > 4 else ""
                tags = parts[5] if len(parts) > 5 else ""
                if host.upper() == "HOST":
                    host = self.public_host()
                try:
                    port = int(port_s)
                except ValueError:
                    self.logger.warning("lobby: bad port in %r", chunk)
                    continue
                dests[slug.lower()] = {
                    "slug": slug,
                    "host": host,
                    "port": port,
                    "label": label,
                    "password": password,
                    "tags": [t.strip().lower() for t in tags.split(",") if t.strip()],
                }

        json_path = (self.get_cvar("qlx_lobbyInstancesJson") or "").strip()
        if json_path:
            try:
                with open(json_path, encoding="utf-8") as f:
                    data = json.load(f)
                base_host = self.public_host()
                for inst in data.get("instances", []):
                    if not inst.get("enabled", True):
                        continue
                    if inst.get("lobby"):
                        continue
                    iid = inst.get("id")
                    if iid is None:
                        continue
                    slug = (inst.get("slug") or "instance-{}".format(iid)).lower()
                    if slug in dests:
                        continue
                    port = 27960 + int(iid)
                    dests[slug] = {
                        "slug": inst.get("slug", slug),
                        "host": base_host,
                        "port": port,
                        "label": inst.get("name", slug),
                        "password": (inst.get("password") or "").strip(),
                        "tags": [t.strip().lower() for t in (inst.get("tags") or "").split(",") if t.strip()],
                    }
            except OSError as e:
                self.logger.error("lobby: cannot read %s: %s", json_path, e)
            except json.JSONDecodeError as e:
                self.logger.error("lobby: invalid JSON %s: %s", json_path, e)

        return dests

    def resolve_dest(self, slug, dests=None):
        if dests is None:
            dests = self.parse_destinations()
        if not slug:
            return None
        return dests.get(str(slug).lower())

    def route_for_player(self, player, dests=None):
        if dests is None:
            dests = self.parse_destinations()
        key = ROUTE_KEY.format(player.steam_id)
        if key in self.db:
            slug = self.db[key]
            if isinstance(slug, bytes):
                slug = slug.decode("utf-8", errors="replace")
            d = self.resolve_dest(slug, dests)
            if d:
                return d
        default = (self.get_cvar("qlx_lobbyDefaultDest") or "").strip().lower()
        if default:
            return self.resolve_dest(default, dests)
        if len(dests) == 1:
            return next(iter(dests.values()))
        return None

    def should_stay_on_lobby(self, player):
        if str(player.steam_id) == str(minqlx.owner()):
            return True
        stay = int(self.get_cvar("qlx_lobbyStayPerm") or "3")
        return self.db.get_permission(player) >= stay

    # ------------------------------------------------------------------
    # Redirect
    # ------------------------------------------------------------------

    @minqlx.next_frame
    def _force_spec(self, player):
        try:
            player.put("spectator")
        except Exception:
            pass

    @staticmethod
    def _connect_addr(host, port):
        return "{}:{}".format(host, port)

    def _steam_connect_uri(self, host, port, password=""):
        addr = self._connect_addr(host, port)
        if password:
            return "steam://connect/{}/{}".format(addr, password)
        return "steam://connect/{}".format(addr)

    def _manual_connect_hint(self, player, host, port, label="", password=""):
        """QL blocks server-pushed connect/open — only the player's console works."""
        addr = self._connect_addr(host, port)
        title = label or "Game server"
        steam_uri = self._steam_connect_uri(host, port, password)

        player.center_print(
            "^2{}\n\n^7Open console (~) and type:\n^6/connect {}".format(title, addr))
        player.tell("^2Lobby:^7 ^6/connect {}^7".format(addr))
        if password:
            player.tell("^3Lobby:^7 password: ^6{}^7 (after connect or in URI)".format(password))
        player.tell("^3Lobby:^7 copy link: {}".format(steam_uri))
        return addr

    @minqlx.next_frame
    def _client_connect(self, player, host, port, password=""):
        self._manual_connect_hint(player, host, port, password=password)

    def redirect_player(self, player, dest, notify=True):
        if not dest:
            player.tell("^1Lobby:^7 no destination configured.")
            return False
        host, port = dest["host"], dest["port"]
        label = dest.get("label", dest.get("slug", ""))
        password = dest.get("password") or ""

        if notify:
            player.tell("^2Lobby:^7 target ^6{}^7 (^2{}:{}^7)".format(label, host, port))
            extra = (self.get_cvar("qlx_lobbyConnectMessage") or "").strip()
            if extra:
                player.center_print(extra)

        self._manual_connect_hint(player, host, port, label=label, password=password)
        return True

    @minqlx.thread
    def _auto_redirect(self, player):
        sid = player.steam_id
        if sid in self._pending:
            return
        self._pending.add(sid)
        try:
            delay = max(0, int(self.get_cvar("qlx_lobbyRedirectDelay") or "5"))
            dest = self.route_for_player(player)
            if not dest:
                player.tell("^3Lobby:^7 no route assigned. Use ^6!lobby^7 and ^6!go <slug>^7.")
                return

            label = dest.get("label", dest["slug"])
            for remaining in range(delay, 0, -1):
                if player.steam_id not in [p.steam_id for p in self.players()]:
                    return
                player.center_print(
                    "^2Lobby\n\n^7Connecting to\n^6{}\n\n^1{}^7".format(label, remaining))
                time.sleep(1)

            self.redirect_player(player, dest, notify=False)
        finally:
            self._pending.discard(sid)

    # ------------------------------------------------------------------
    # Hooks
    # ------------------------------------------------------------------

    def handle_player_loaded(self, player):
        if self.get_cvar("qlx_lobbyForceSpec", bool):
            self._force_spec(player)

        if not self.get_cvar("qlx_lobbyEnabled", bool):
            return
        if self.should_stay_on_lobby(player):
            dests = self.parse_destinations()
            route = self.route_for_player(player, dests)
            if route:
                player.tell("^3Lobby admin:^7 your route is ^6{}^7 (^2{}:{}^7).".format(
                    route["label"], route["host"], route["port"]))
            return
        if self.get_cvar("qlx_lobbyAutoRedirect", bool):
            self._auto_redirect(player)
        self._check_hub_notify_player(player)

    def handle_team_switch_attempt(self, player, old_team, new_team, target):
        if not self.get_cvar("qlx_lobbyEnabled", bool):
            return
        if self.should_stay_on_lobby(player):
            return
        if new_team in ("free", "red", "blue"):
            player.tell("^3Lobby:^7 pick a server: ^6!lobby^7 / ^6!go <slug>^7")
            return minqlx.Return.STOP_ALL

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    def cmd_lobby(self, player, msg, channel):
        dests = self.parse_destinations()
        if not dests:
            channel.reply("^1Lobby:^7 qlx_lobbyDestinations is empty.")
            return minqlx.Return.STOP_ALL

        route = self.route_for_player(player, dests)
        if route:
            channel.reply("^2Your route:^7 ^6{}^7 → ^6/connect {}:{}^7".format(
                route["label"], route["host"], route["port"]))
        else:
            channel.reply("^3No personal route.^7 Use ^6!go <slug>^7")

        channel.reply("^3Destinations:^7")
        for slug in sorted(dests.keys()):
            d = dests[slug]
            channel.reply("  ^6{}^7 — {}  ^6/connect {}:{}^7".format(
                d["slug"], d["label"], d["host"], d["port"]))
        return minqlx.Return.STOP_ALL

    def cmd_go(self, player, msg, channel):
        dests = self.parse_destinations()
        if len(msg) >= 2:
            dest = self.resolve_dest(" ".join(msg[1:]), dests)
        else:
            dest = self.route_for_player(player, dests)
        if not dest:
            channel.reply("^1Lobby:^7 unknown destination. ^6!lobby^7 for list.")
            return minqlx.Return.STOP_ALL
        self.redirect_player(player, dest)
        return minqlx.Return.STOP_ALL

    def _player_from_arg(self, arg):
        try:
            return self.player(int(arg))
        except ValueError:
            matches = self.find_player(arg)
            if not matches:
                return None
            return matches[0]
        except minqlx.NonexistentPlayerError:
            return None

    def cmd_lobbyset(self, player, msg, channel):
        if len(msg) < 3:
            return minqlx.Return.USAGE
        target = self._player_from_arg(msg[1])
        if not target:
            channel.reply("^1No matching player.")
            return minqlx.Return.STOP_ALL
        slug = msg[2].lower()
        dests = self.parse_destinations()
        if slug not in dests:
            channel.reply("^1Unknown slug. ^6!lobby^7 for list.")
            return minqlx.Return.STOP_ALL
        self.db[ROUTE_KEY.format(target.steam_id)] = slug
        d = dests[slug]
        channel.reply("^2Set route for {} → {} ({}:{})".format(
            target.name, d["label"], d["host"], d["port"]))
        return minqlx.Return.STOP_ALL

    def cmd_lobbyclear(self, player, msg, channel):
        if len(msg) >= 2:
            target = self._player_from_arg(msg[1])
            if not target:
                channel.reply("^1No matching player.")
                return minqlx.Return.STOP_ALL
            key = ROUTE_KEY.format(target.steam_id)
        else:
            key = ROUTE_KEY.format(player.steam_id)
            target = player
        if key in self.db:
            del self.db[key]
        channel.reply("^2Cleared lobby route for {}.".format(target.name))
        return minqlx.Return.STOP_ALL

    def cmd_lobbysend(self, player, msg, channel):
        if len(msg) < 2:
            return minqlx.Return.USAGE
        target = self._player_from_arg(msg[1])
        if not target:
            channel.reply("^1No matching player.")
            return minqlx.Return.STOP_ALL
        dests = self.parse_destinations()
        if len(msg) >= 3:
            dest = self.resolve_dest(msg[2], dests)
        else:
            dest = self.route_for_player(target, dests)
        if not dest:
            channel.reply("^1Unknown destination.")
            return minqlx.Return.STOP_ALL
        self.redirect_player(target, dest)
        channel.reply("^2Sent {} to {}.".format(target.name, dest["label"]))
        return minqlx.Return.STOP_ALL

    def cmd_lobbynotify(self, player, msg, channel):
        """Debug: re-check redis notify for all players on server."""
        delivered = 0
        for p in self.players():
            before = self._hub_delivered_rev.get(str(p.steam_id))
            self._check_hub_notify_player(p)
            if self._hub_delivered_rev.get(str(p.steam_id)) != before:
                delivered += 1
        if channel:
            channel.reply("^2lobbynotify:^7 delivered to {} player(s).".format(delivered))
        return minqlx.Return.STOP_ALL
