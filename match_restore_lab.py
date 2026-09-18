# match_restore_lab.py — optional lab/debug commands for match_restore.
#
# Split out of match_restore.py: !spawnsec, !itemlab, !matchtime, !restoreplayer.
# None of these run during a real tournament restore (that is !restore, which
# stays in match_restore.py) — they are perm-5 tools used while building or
# testing a checkpoint (forcing item state, nudging the match clock, poking a
# single player's state).
#
# Requires match_restore to be loaded: reaches into it via
# self.plugins["match_restore"] for the shared item-runtime cache
# (_runtime_entity_by_alias / _slot_runtime_ids / _itemlab_engine_runtime_ids —
# the same cache on_item_event populates from real pickups) and the
# clock/player-apply engine (_apply_match_time, _apply_player_snapshot, ...).
#
# Gated by qlx_matchRestoreLabEnabled — the same cvar match_restore.py's own
# _enabled() reads, so disabling it also disables restore (unchanged
# pre-split behavior); this plugin only stops reacting to its own commands.
#
# Commands (perm 5):
#   !spawnsec <alias> <seconds> [entity_id]
#       Hide runtime entity (hide_map_item), show after N seconds (show_map_item).
#   !spawnsec list|scan|reset
#   !itemlab touch <entity_id> [client_id]  — vanilla Touch_Item (real pickup)
#   !itemlab respawn <entity_id> <delay_sec> — hide + show same runtime entity
#   !itemlab touchat <entity_id> <delay_sec> [client_id] — wall-clock Touch_Item
#   !itemlab stat <entity_id>
#   !matchtime show|<sec|mm:ss|ms N>  — set/show match elapsed clock (lab test)
#       mm:ss = elapsed time (9:00 = 9th minute). HUD countdown = timelimit - elapsed.
#   !restoreplayer <id|me> <payload>  — single player debug (JSON or base64 JSON)

import base64
import json
import time

try:
    import minqlxtended as minqlx
except ImportError:
    import minqlx


class match_restore_lab(minqlx.Plugin):
    def __init__(self):
        self._itemlab_pending_respawns = {}
        self._itemlab_pending_touches = {}
        self.set_cvar_once("qlx_matchRestoreLabEnabled", "1")
        self.add_command(
            ("spawnsec", "spawnitem"),
            self.cmd_spawnsec,
            5,
            usage="<alias|list|scan|reset> <seconds> [entity_id]",
            client_cmd_pass=False,
        )
        self.add_command(
            ("restoreplayer", "restorepl"),
            self.cmd_restoreplayer,
            5,
            usage="<client_id|me> <json_or_base64>",
            client_cmd_pass=False,
        )
        self.add_command(
            ("matchtime", "setmatchtime"),
            self.cmd_matchtime,
            5,
            usage="show | <seconds> | <mm:ss> | ms <milliseconds>",
            client_cmd_pass=False,
        )
        self.add_command(
            ("itemlab", "itemslot"),
            self.cmd_itemlab,
            5,
            usage="touch <eid> [cid] | respawn <eid> <sec> | stat <eid>",
            client_cmd_pass=False,
        )
        self.add_hook("map", self._on_map)
        self.add_hook("game_start", self._on_game_start)
        self.add_hook("frame", self._frame_poll_itemlab, priority=minqlx.Priority.LOWEST)

    def _enabled(self):
        return self.get_cvar("qlx_matchRestoreLabEnabled", bool) is not False

    def _core(self):
        return self.plugins.get("match_restore")

    def _reply(self, player, channel, msg):
        """Same contract as match_restore._reply: RCON/console passes player=None."""
        try:
            caller = player
            if caller is not None:
                caller.tell(msg)
            else:
                channel.reply(msg)
        except Exception:
            self.logger.exception("match_restore_lab: reply failed (msg=%s)", msg)

    def _on_map(self, mapname, factory):
        self._itemlab_pending_respawns.clear()
        self._itemlab_pending_touches.clear()
        return minqlx.Return.NONE

    def _on_game_start(self, *_args, **_kwargs):
        self._itemlab_pending_respawns.clear()
        self._itemlab_pending_touches.clear()
        return minqlx.Return.NONE

    def _frame_poll_itemlab(self, *_args, **_kwargs):
        if not self._enabled():
            return minqlx.Return.NONE
        self._poll_itemlab_engine_respawns()
        self._poll_itemlab_pending_touches()
        return minqlx.Return.NONE

    # -- itemlab ----------------------------------------------------------

    def _resolve_itemlab_eid(self, token):
        text = str(token or "").strip()
        if text.startswith("e") and text[1:].isdigit():
            return int(text[1:])
        if text.isdigit():
            return int(text)
        return None

    def _itemlab_arm_engine_entity(self, runtime_eid):
        core = self._core()
        if core is None:
            return
        try:
            rid = int(runtime_eid)
        except (TypeError, ValueError):
            return
        if rid > 0:
            core._itemlab_engine_runtime_ids.add(rid)

    def _poll_itemlab_engine_respawns(self):
        if not self._itemlab_pending_respawns:
            return
        if not hasattr(minqlx, "show_map_item"):
            return
        now_wall = time.time()
        done = []
        for eid, job in list(self._itemlab_pending_respawns.items()):
            due_at = float(job.get("due_at_wall", 0) or 0)
            if now_wall < due_at:
                continue
            try:
                ok = minqlx.show_map_item(int(eid))
            except (AttributeError, TypeError, ValueError) as exc:
                self.logger.warning("itemlab show e%s failed: %s", eid, exc)
                continue
            if ok is False:
                self.logger.warning("itemlab show e%s returned false", eid)
                continue
            self.logger.info(
                "match_restore_lab: itemlab show e%s due=%.3f now=%.3f",
                eid,
                due_at,
                now_wall,
            )
            done.append(int(eid))
        for eid in done:
            self._itemlab_pending_respawns.pop(int(eid), None)

    def _poll_itemlab_pending_touches(self):
        if not self._itemlab_pending_touches:
            return
        if not hasattr(minqlx, "touch_map_item"):
            return
        core = self._core()
        now_wall = time.time()
        done = []
        for eid, job in list(self._itemlab_pending_touches.items()):
            due_at = float(job.get("due_at_wall", 0) or 0)
            if now_wall < due_at:
                continue
            cid = int(job.get("client_id", 0) or 0)
            if core is None or not core._engine_item_pickable(int(eid)):
                self.logger.warning(
                    "match_restore_lab: itemlab touchat e%s skipped (not pickable)",
                    eid,
                )
                done.append(int(eid))
                continue
            try:
                ok = minqlx.touch_map_item(int(eid), cid)
            except (AttributeError, TypeError, ValueError) as exc:
                self.logger.warning("itemlab touchat e%s failed: %s", eid, exc)
                continue
            if ok is False:
                self.logger.warning("itemlab touchat e%s returned false", eid)
                continue
            self._itemlab_arm_engine_entity(eid)
            self.logger.info(
                "match_restore_lab: itemlab touchat e%s cid=%s due=%.3f now=%.3f",
                eid,
                cid,
                due_at,
                now_wall,
            )
            done.append(int(eid))
        for eid in done:
            self._itemlab_pending_touches.pop(int(eid), None)

    def cmd_itemlab(self, player, msg, channel):
        if not self._enabled():
            self._reply(player, channel, "^1match_restore disabled.^7")
            return minqlx.Return.STOP
        if len(msg) < 2:
            return minqlx.Return.USAGE
        sub = str(msg[1]).strip().lower()
        if sub in ("help", "?"):
            self._reply(player, channel,
                "^2itemlab^7: ^3touch^7 <eid> [cid] — vanilla Touch_Item; "
                "^3touchat^7 <eid> <sec> [cid] — wall-clock touch; "
                "^3respawn^7 <eid> <sec> — hide + show same runtime entity; "
                "^3stat^7 <eid> — use runtime id from ^3!spawnsec scan^7"
            )
            return minqlx.Return.STOP
        if sub == "stat":
            if len(msg) < 3:
                return minqlx.Return.USAGE
            eid = self._resolve_itemlab_eid(msg[2])
            if eid is None:
                self._reply(player, channel, "^1bad entity^7 — runtime id only (see ^3!spawnsec scan^7)")
                return minqlx.Return.STOP
            core = self._core()
            row = core._get_item_state(int(eid)) if core is not None else None
            if row is None:
                self._reply(player, channel, "^1stat failed^7 (no state for e{})".format(eid))
                return minqlx.Return.STOP
            inuse, etype, eflags, contents, nextthink, has_think, level_time, classname = row
            nodraw = bool(int(eflags) & 0x80)
            self._reply(player, channel,
                "^2itemlab stat^7 e{} inuse={} type={} cn={} nodraw={} contents={} nextthink={} think={} level.time={}".format(
                    eid,
                    inuse,
                    etype,
                    classname,
                    int(nodraw),
                    contents,
                    nextthink,
                    has_think,
                    level_time,
                )
            )
            return minqlx.Return.STOP
        if sub == "touch":
            if len(msg) < 3:
                return minqlx.Return.USAGE
            eid = self._resolve_itemlab_eid(msg[2])
            if eid is None:
                self._reply(player, channel, "^1bad entity^7 — runtime id only (see ^3!spawnsec scan^7)")
                return minqlx.Return.STOP
            cid = getattr(player, "id", 0)
            if len(msg) >= 4 and str(msg[3]).strip().isdigit():
                cid = int(msg[3])
            if not hasattr(minqlx, "touch_map_item"):
                self._reply(player, channel, "^1touch_map_item missing^7 — patched-runtime native (not on stock minqlxtended)")
                return minqlx.Return.STOP
            try:
                ok = minqlx.touch_map_item(int(eid), int(cid))
            except (AttributeError, TypeError, ValueError) as exc:
                self._reply(player, channel, "^1touch failed^7: {}".format(exc))
                return minqlx.Return.STOP
            if ok is False:
                self._reply(player, channel, "^1touch_map_item returned false^7")
                return minqlx.Return.STOP
            self._itemlab_arm_engine_entity(eid)
            self._reply(player, channel,
                "^2itemlab touch^7 e{} by cid {} — watch vanilla respawn / ^3!itemlab stat^7".format(
                    eid, cid
                )
            )
            return minqlx.Return.STOP
        if sub == "touchat":
            if len(msg) < 4:
                return minqlx.Return.USAGE
            eid = self._resolve_itemlab_eid(msg[2])
            if eid is None:
                self._reply(player, channel, "^1bad entity^7 — runtime id only (see ^3!spawnsec scan^7)")
                return minqlx.Return.STOP
            try:
                delay_sec = float(msg[3])
            except (TypeError, ValueError):
                self._reply(player, channel, "^1bad delay^7")
                return minqlx.Return.STOP
            if delay_sec < 0:
                self._reply(player, channel, "^1bad delay^7")
                return minqlx.Return.STOP
            cid = getattr(player, "id", 0)
            if len(msg) >= 5 and str(msg[4]).strip().isdigit():
                cid = int(msg[4])
            if not hasattr(minqlx, "touch_map_item"):
                self._reply(player, channel, "^1touch_map_item missing^7 — patched-runtime native (not on stock minqlxtended)")
                return minqlx.Return.STOP
            rescheduled = int(eid) in self._itemlab_pending_touches
            self._itemlab_pending_touches[int(eid)] = {
                "due_at_wall": time.time() + float(delay_sec),
                "client_id": int(cid),
            }
            self._itemlab_arm_engine_entity(eid)
            note = " (rescheduled)" if rescheduled else ""
            self._reply(player, channel,
                "^2itemlab touchat^7 e{} in ^6{}^7s by cid {}{} — pickable required at fire".format(
                    eid, delay_sec, cid, note
                )
            )
            return minqlx.Return.STOP
        if sub == "respawn":
            if len(msg) < 4:
                return minqlx.Return.USAGE
            eid = self._resolve_itemlab_eid(msg[2])
            if eid is None:
                self._reply(player, channel, "^1bad entity^7 — runtime id only (see ^3!spawnsec scan^7)")
                return minqlx.Return.STOP
            try:
                delay_sec = float(msg[3])
            except (TypeError, ValueError):
                self._reply(player, channel, "^1bad delay^7")
                return minqlx.Return.STOP
            if delay_sec < 0:
                self._reply(player, channel, "^1bad delay^7")
                return minqlx.Return.STOP
            if not hasattr(minqlx, "hide_map_item"):
                # Stock minqlxtended: hide via writable fields and hand the
                # timer to the engine's own RespawnItem — no wall-clock poll.
                core = self._core()
                if core is None or not hasattr(minqlx, "respawn_item"):
                    self._reply(player, channel, "^1no stock respawn path^7 (match_restore not loaded?)")
                    return minqlx.Return.STOP
                if not core._stock_hide_item(int(eid)):
                    self._reply(player, channel, "^1stock hide failed^7 e{}".format(eid))
                    return minqlx.Return.STOP
                try:
                    ok = minqlx.respawn_item(int(eid), int(delay_sec * 1000))
                except (AttributeError, TypeError, ValueError) as exc:
                    self._reply(player, channel, "^1respawn_item failed^7: {}".format(exc))
                    return minqlx.Return.STOP
                self._itemlab_arm_engine_entity(eid)
                self._reply(player, channel,
                    "^2itemlab respawn(stock)^7 e{} in ^6{}^7s ok={} — ^3!itemlab stat {}^7".format(
                        eid, delay_sec, ok, eid
                    )
                )
                return minqlx.Return.STOP
            rescheduled = int(eid) in self._itemlab_pending_respawns
            try:
                ok = minqlx.hide_map_item(int(eid))
            except (AttributeError, TypeError, ValueError) as exc:
                self._reply(player, channel, "^1respawn failed^7: {}".format(exc))
                return minqlx.Return.STOP
            if ok is False:
                self._reply(player, channel, "^1hide_map_item returned false^7")
                return minqlx.Return.STOP
            self._itemlab_pending_respawns[int(eid)] = {
                "due_at_wall": time.time() + float(delay_sec),
            }
            self._itemlab_arm_engine_entity(eid)
            note = " (rescheduled)" if rescheduled else ""
            self._reply(player, channel,
                "^2itemlab respawn^7 e{} in ^6{}^7s{} — ^3!itemlab stat {}^7".format(
                    eid, delay_sec, note, eid
                )
            )
            return minqlx.Return.STOP
        return minqlx.Return.USAGE

    # -- spawnsec -----------------------------------------------------------

    def cmd_spawnsec(self, player, msg, channel):
        if not self._enabled():
            self._reply(player, channel, "^1match_restore disabled.^7")
            return minqlx.Return.STOP
        core = self._core()
        if core is None:
            self._reply(player, channel, "^1match_restore core plugin not loaded.^7")
            return minqlx.Return.STOP

        if len(msg) < 2:
            return minqlx.Return.USAGE

        sub = str(msg[1]).strip().lower()
        if sub in ("list", "ls", "help"):
            return self._cmd_spawnsec_list(core, player, channel)
        if sub == "scan":
            return self._cmd_spawnsec_scan(player, channel)
        if sub in ("reset", "restore"):
            core._runtime_entity_by_alias.clear()
            core._slot_runtime_ids.clear()
            core._itemlab_engine_runtime_ids.clear()
            self._itemlab_pending_respawns.clear()
            self._itemlab_pending_touches.clear()
            core._restore_apply_active = False
            self._reply(player, channel,
                "^2spawnsec^7 lab state cleared. Run ^3map_restart^7 to restore map pickups."
            )
            return minqlx.Return.STOP

        if len(msg) < 3:
            return minqlx.Return.USAGE

        classname, alias = core._resolve_alias(sub)
        if not classname:
            self._reply(player, channel, "^1Unknown item alias^7: ^3{}^7".format(sub))
            return minqlx.Return.STOP

        try:
            delay_sec = float(msg[2])
        except (TypeError, ValueError):
            self._reply(player, channel, "^1Invalid seconds^7.")
            return minqlx.Return.STOP
        if delay_sec < 0:
            self._reply(player, channel, "^1Seconds must be >= 0^7.")
            return minqlx.Return.STOP

        entity_id = None
        spawn_meta = core._lookup_spawn_meta(alias)
        if len(msg) >= 4:
            try:
                entity_id = int(msg[3])
            except (TypeError, ValueError):
                self._reply(player, channel, "^1Invalid entity_id^7.")
                return minqlx.Return.STOP
        elif spawn_meta:
            entity_id = spawn_meta.get("entity_id")

        if entity_id is None:
            self._reply(player, channel,
                "^1No entity_id for ^3{}^7 on map ^3{}^7. "
                "Use ^2!spawnsec {} {} <entity_id>^7.".format(
                    alias, core._map_key() or "?", alias, int(delay_sec) if delay_sec.is_integer() else delay_sec
                )
            )
            return minqlx.Return.STOP

        if spawn_meta is None:
            spawn_meta = {"entity_id": entity_id}

        self._hide_item(core, player, channel, entity_id, alias, classname, delay_sec, spawn_meta)
        return minqlx.Return.STOP

    def _cmd_spawnsec_list(self, core, player, channel):
        map_key = core._map_key() or "?"
        rows = core._map_spawns_table()
        if not rows:
            self._reply(player, channel, "^3spawnsec^7: no bundled spawns for map ^3{}^7.".format(map_key))
            return minqlx.Return.STOP
        parts = []
        seen = set()
        for alias, row in sorted(rows.items()):
            eid = row.get("entity_id")
            if eid in seen:
                continue
            seen.add(eid)
            parts.append(
                "^3{}^7=#{} @({},{},{})".format(
                    alias,
                    eid,
                    row.get("x"),
                    row.get("y"),
                    row.get("z"),
                )
            )
        self._reply(player, channel, "^2spawnsec^7 map ^3{}^7: {}".format(map_key, ", ".join(parts)))
        return minqlx.Return.STOP

    def _cmd_spawnsec_scan(self, player, channel):
        if not hasattr(minqlx, "dev_print_items"):
            self._reply(player, channel, "^1dev_print_items missing in minqlx build.^7")
            return minqlx.Return.STOP
        try:
            minqlx.dev_print_items()
        except (AttributeError, TypeError, ValueError) as exc:
            self._reply(player, channel, "^1scan failed^7: {}".format(exc))
            return minqlx.Return.STOP
        self._reply(player, channel,
            "^2Item entity list printed^7 (console + server log). "
            "Use ^3!spawnsec mega 12 <id>^7 while pickup is ^6on map^7."
        )
        return minqlx.Return.STOP

    def _hide_item(self, core, player, channel, entity_id, alias, classname, delay_sec, spawn_meta):
        table_id = int(entity_id)
        if not hasattr(minqlx, "hide_map_item"):
            self._reply(player, channel, "^1hide_map_item missing^7 — patched-runtime native (not on stock minqlxtended).")
            return
        runtime_eid = core._resolve_runtime_eid(
            alias, spawn_meta, classname, force_scan=True
        )
        if runtime_eid <= 0:
            self._reply(player, channel,
                "^1{}^7: no runtime entity — ^3!spawnsec scan^7 while pickup is on map.".format(
                    alias
                )
            )
            return
        if not core._hide_engine_item(runtime_eid, alias, classname, spawn_meta):
            self._reply(player, channel,
                "^1{}^7 hide failed (e{}). Try ^3!spawnsec scan^7.".format(alias, runtime_eid)
            )
            return
        self._itemlab_arm_engine_entity(runtime_eid)
        core._runtime_entity_by_alias[str(alias)] = int(runtime_eid)
        core._runtime_entity_by_alias["e{}".format(table_id)] = int(runtime_eid)
        core._track_slot_runtime_id(table_id, int(runtime_eid))
        if delay_sec <= 0:
            self._reply(player, channel, "^2{}^7 hidden (e{}), no respawn scheduled.".format(alias, runtime_eid))
            return
        if not hasattr(minqlx, "show_map_item"):
            self._reply(player, channel, "^1show_map_item missing^7 — rebuild minqlx.")
            return
        self._itemlab_pending_respawns[int(runtime_eid)] = {
            "due_at_wall": time.time() + float(delay_sec),
        }
        self._reply(player, channel,
            "^2{}^7 hidden e{}; show in ^6{}^7s (^3{}^7). Vanilla respawn after pickup.".format(
                alias, runtime_eid, delay_sec, classname
            )
        )
        self.logger.info(
            "match_restore_lab: spawnsec alias=%s table=%s runtime=%s delay=%ss by=%s",
            alias,
            table_id,
            runtime_eid,
            delay_sec,
            getattr(player, "steam_id", "?"),
        )

    # -- matchtime ------------------------------------------------------------

    def cmd_matchtime(self, player, msg, channel):
        if not self._enabled():
            self._reply(player, channel, "^1match_restore disabled.^7")
            return minqlx.Return.STOP_ALL
        core = self._core()
        if core is None:
            self._reply(player, channel, "^1match_restore core plugin not loaded.^7")
            return minqlx.Return.STOP_ALL
        try:
            if len(msg) < 2 or str(msg[1]).strip().lower() in ("show", "?", "get"):
                ms = core._read_level_time_ms()
                elapsed_sec = ms / 1000.0
                tl_sec = core._timelimit_sec()
                src = core._clock_source or "?"
                live_state = core._game_state_label()
                eff_state = core._effective_match_state()
                map_t = core._native_map_time_ms()
                paused = core._sv_paused_active()
                self.logger.info(
                    "matchtime show: elapsed=%sms src=%s live=%s eff=%s latched=%s "
                    "paused=%s frozen_ms=%s map_t=%s start_t=%s",
                    ms,
                    src,
                    live_state,
                    eff_state,
                    core._last_game_state,
                    paused,
                    core._pause_frozen_ms,
                    map_t,
                    core._match_start_map_time,
                )
                if paused:
                    self._reply(player, channel, "^3paused^7 — frozen at ^6{:.1f}^7s (^6{}^7 ms)".format(elapsed_sec, ms))
                if not core._match_clock_live():
                    self._reply(player, channel,
                        "^3match time^7: ^6{:.1f}^7s (^6{}^7 ms, ^3{}^7) — warmup".format(
                            elapsed_sec, ms, src
                        )
                    )
                    return minqlx.Return.STOP_ALL
                if tl_sec > 0:
                    remain = max(0, tl_sec * 60 - int(ms // 1000))
                    self._reply(player, channel,
                        "^2match time^7: elapsed ^6{:.1f}^7s, remaining ^6{}^7s".format(
                            elapsed_sec, remain
                        )
                    )
                    self._reply(player, channel, "^7{} ms, timelimit {} min, src={}".format(ms, tl_sec, src))
                else:
                    self._reply(player, channel,
                        "^2match time^7: ^6{:.1f}^7 s (^6{}^7 ms, src={})".format(
                            elapsed_sec, ms, src
                        )
                    )
                return minqlx.Return.STOP_ALL
            try:
                ms = core._parse_match_time_arg(msg[1:])
            except (TypeError, ValueError) as exc:
                self._reply(player, channel,
                    "^1matchtime^7: {} — use ^3show^7, ^312000^7 (ms), ^312s^7, ^32:25^7".format(exc)
                )
                return minqlx.Return.STOP_ALL
            ok, detail = core._apply_match_time(ms, force_hud=True, restore_apply=True)
            if ok:
                core._level_time_ms = max(0, int(ms))
                es = max(0, int(ms) // 1000)
                self._reply(player, channel,
                    "^2matchtime^7 set ^6{}:{:02d}^7 ({})".format(
                        es // 60, es % 60, detail or "ok"
                    )
                )
            else:
                self._reply(player, channel, "^1matchtime failed^7: {}".format(detail))
        except Exception as exc:
            self.logger.exception("match_restore_lab matchtime")
            self._reply(player, channel, "^1matchtime error^7: {}".format(exc))
        return minqlx.Return.STOP_ALL

    # -- restoreplayer --------------------------------------------------------

    def cmd_restoreplayer(self, player, msg, channel):
        if not self._enabled():
            self._reply(player, channel, "^1match_restore disabled.^7")
            return minqlx.Return.STOP
        core = self._core()
        if core is None:
            self._reply(player, channel, "^1match_restore core plugin not loaded.^7")
            return minqlx.Return.STOP
        if len(msg) < 3:
            return minqlx.Return.USAGE

        target = self._resolve_target(player, msg[1])
        if target is None:
            self._reply(player, channel, "^1Invalid target^7.")
            return minqlx.Return.STOP

        payload = self._parse_payload(" ".join(msg[2:]))
        if payload is None:
            self._reply(player, channel, "^1Invalid payload^7 (JSON or base64url JSON).")
            return minqlx.Return.STOP

        ok, detail = core._apply_player_snapshot(target, payload)
        if ok:
            self._reply(player, channel, "^2restoreplayer^7 queued for ^3{}^7: {}".format(target.name, detail))
        else:
            self._reply(player, channel, "^1restoreplayer failed^7: {}".format(detail))
        return minqlx.Return.STOP

    def _resolve_target(self, caller, token):
        text = str(token or "").strip().lower()
        if text in ("me", "self", "."):
            return caller
        try:
            client_id = int(text)
        except (TypeError, ValueError):
            return None
        try:
            return self.player(client_id)
        except (AttributeError, TypeError, ValueError, minqlx.NonexistentPlayerError):
            return None

    @staticmethod
    def _parse_payload(raw):
        text = str(raw or "").strip()
        if not text:
            return None
        if text.startswith("#") and text.endswith("#") and len(text) > 2:
            text = text[1:-1]
        if text.startswith("{") or text.startswith("["):
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return None
        pad = "=" * ((4 - len(text) % 4) % 4)
        for decoder in (
            lambda s: base64.urlsafe_b64decode(s + pad),
            lambda s: base64.b64decode(s + pad),
        ):
            try:
                decoded = decoder(text).decode("utf-8")
                return json.loads(decoded)
            except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
                continue
        return None
