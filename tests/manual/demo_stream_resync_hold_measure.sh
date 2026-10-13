#!/usr/bin/env bash
# One measured recovery of the live demo stream after a stats-hub restart, with the
# demo_stream_resync_hold plugin switched on or off.
#
#   QL_CONFIRM=1 bash tests/manual/demo_stream_resync_hold_measure.sh <on|off> [out dir]
#
# It RESTARTS THE STATS HUB, which every game server shares: all live viewers are cut for a few
# seconds. The addresses come from QL_SSH_KEY, QL_GAME_HOST, QL_HUB_SSH and QL_HUB_HTTP, and nothing
# runs without QL_CONFIRM=1. It refuses to restart anything unless:
#   - no OTHER game server has a POV listed at the hub (their viewers would be cut too);
#   - the measured server streams at least one POV and is in warmup (g_gameState PRE_GAME);
#   - the plugin is loaded, answers, and reports the requested mode after the cvar was set.
# The cvar qlx_demoStreamResyncHold is put back to what it was on every way out.
# Watches EVERY streamed slot for 60 s in parallel. Everything printed is also kept in
# <out dir>/<stamp>-<mode>.log. Needs python with the `websockets` package.
# The rcon port and password are read on the game host from the process and never printed.
# Every rcon call here is a new zmq rcon connection. On 2026-10-13 the game server crashed in its
# own rcon code (a client list walked while clients disconnected) right when this script and
# another rcon poller disconnected together: do not run it next to other rcon tools.
set -euo pipefail

MODE="${1:?on or off}"
OUT="${2:-${TMPDIR:-/tmp}/resync-hold-measure}"
if [ "${QL_CONFIRM:-}" != "1" ]; then
    echo "This restarts the shared stats hub. Set QL_CONFIRM=1 to run it (and set the QL_* addresses)." >&2
    exit 2
fi
KEY="${QL_SSH_KEY:?path to the ssh key}"
GAME="${QL_GAME_HOST:?user@host of the game host}"
PORT="${QL_GAME_PORT:-27960}"
HUB_SSH="${QL_HUB_SSH:?user@host of the stats hub}"
HUB="${QL_HUB_HTTP:?host:port of the stats hub}"
SERVER_ID="${QL_HUB_SERVER_ID:-1}"
WATCH_SECONDS="${QL_WATCH_SECONDS:-60}"
HUB_LOG=/var/log/supervisor/ql-stats-hub.err.log
HERE="$(cd "$(dirname "$0")" && pwd)"

case "$MODE" in on) VALUE=1 ;; off) VALUE=0 ;; *) echo "mode must be on or off" >&2; exit 2 ;; esac
mkdir -p "$OUT"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
exec > >(tee "$OUT/$STAMP-$MODE.log") 2>&1
SSH=(ssh -o BatchMode=yes -o ConnectTimeout=10 -i "$KEY")

rcon() {  # console commands on the game server; addresses and steam ids are masked
    local quoted=""
    for c in "$@"; do quoted="$quoted \"$c\""; done
    "${SSH[@]}" "$GAME" "python3 - $PORT $quoted" < "$HERE/demo_stream_rcon_cmd.py" \
        | grep -v "zmq RCON command" \
        | sed -E 's/[0-9]{1,3}(\.[0-9]{1,3}){3}:[0-9]+/<addr>/g; s/7656[0-9]{13}/<steamid>/g'
}

SERVERS="$(curl -s -m 10 "http://$HUB/api/demo-stream/servers" | python -c "
import json, sys
for server in json.load(sys.stdin).get('servers', []):
    slots = ' '.join(str(s.get('slot')) for s in server.get('slots') or [])
    if slots:
        print('{}|{}|{}'.format(server.get('server_id'), server.get('server_name') or '', slots))
")"
OTHERS="$(echo "$SERVERS" | grep -v "^$SERVER_ID|" | grep . || true)"
if [ -n "$OTHERS" ]; then
    echo "Other game servers are streaming through this hub; a restart would cut their viewers. Nothing was changed."
    echo "$OTHERS" | sed -E 's/^([^|]*)\|([^|]*)\|(.*)$/  server \1 (\2): slots \3/'
    exit 7
fi
SLOTS="$(echo "$SERVERS" | grep "^$SERVER_ID|" | cut -d'|' -f3 || true)"
if [ -z "$SLOTS" ]; then
    echo "No POV is streaming from server $SERVER_ID (http://$HUB/api/demo-stream/servers). Nothing was changed."
    exit 3
fi
STATE="$(rcon "g_gameState" | grep -o 'is:"[A-Z_]*' | head -n 1 | cut -c5-)"
if [ "$STATE" != "PRE_GAME" ]; then
    echo "g_gameState is '$STATE', not PRE_GAME: a match may be running. Nothing was changed."
    exit 4
fi
if ! rcon "qlx !resynchold" | grep -q "^demo_stream_resync_hold "; then
    echo "The plugin does not answer 'qlx !resynchold': it is not loaded. Nothing was changed."
    exit 5
fi
WAS="$(rcon "qlx_demoStreamResyncHold" | grep -o 'is:"[0-9]*' | head -n 1 | cut -c5-)"
if [ "$WAS" != "0" ] && [ "$WAS" != "1" ]; then
    echo "Cannot read qlx_demoStreamResyncHold (got '$WAS'). Nothing was changed."
    exit 5
fi
restore() {
    local now
    now="$(rcon "set qlx_demoStreamResyncHold $WAS" "qlx_demoStreamResyncHold" | grep -o 'is:"[0-9]*' | head -n 1 | cut -c5- || true)"
    if [ "$now" = "$WAS" ]; then
        echo "qlx_demoStreamResyncHold put back to $WAS"
    else
        echo "WARNING: could not confirm qlx_demoStreamResyncHold is back to $WAS (read '$now'); check the server"
    fi
}
trap restore EXIT

echo "== $STAMP mode=$MODE slots=$SLOTS (qlx_demoStreamResyncHold was $WAS)"
rcon "set qlx_demoStreamResyncHold $VALUE" > /dev/null
sleep 3   # the plugin re-reads its cvars about once a second
echo "-- before"
rcon "qlx_demoStreamResyncHold" "qlx_stream" "qlx !resynchold" | grep -E "ResyncHold\" is|resyncs|^ +[0-9]+ +[01] |^demo_stream_resync_hold "
if ! rcon "qlx !resynchold" | grep -q "^demo_stream_resync_hold [^:]*: $MODE,"; then
    echo "The plugin does not report '$MODE' after the cvar was set. Nothing was restarted."
    exit 6
fi

MARK="$("${SSH[@]}" "$HUB_SSH" "wc -l < $HUB_LOG")"
echo "hub restart at $(date -u +%H:%M:%SZ): $("${SSH[@]}" "$HUB_SSH" "supervisorctl restart ql-stats-hub" | tr '\n' ' ')"
PIDS=()
for SLOT in $SLOTS; do
    python "$HERE/demo_stream_measure_recovery.py" "ws://$HUB/api/ws/demo-stream/$SERVER_ID/$SLOT" \
        "$WATCH_SECONDS" "$OUT/$STAMP-$MODE-slot$SLOT.dm_91" > "$OUT/$STAMP-$MODE-slot$SLOT.txt" 2>&1 &
    PIDS+=("$!")
done
for PID in "${PIDS[@]}"; do wait "$PID" || true; done
for SLOT in $SLOTS; do
    echo "slot $SLOT: $(head -n 1 "$OUT/$STAMP-$MODE-slot$SLOT.txt")"
    echo "slot $SLOT: $(python "$HERE/demo_stream_count_empty_runs.py" "$OUT/$STAMP-$MODE-slot$SLOT.dm_91")"
done
echo "no decodable snapshot lines since the restart: $("${SSH[@]}" "$HUB_SSH" "tail -n +$((MARK + 1)) $HUB_LOG | grep -c 'no decodable snapshot' || true")"

echo "-- after"
rcon "qlx_stream" "qlx !resynchold" | grep -E "resyncs|^demo_stream_resync_hold "
echo "-- plugin log"
rcon "qlx !resynchold log" | grep -v "^> "
echo "kept in $OUT/$STAMP-$MODE.log"
