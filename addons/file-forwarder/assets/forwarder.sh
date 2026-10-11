#!/bin/sh
# file-forwarder: ships demo files from a game host to the site VPS with rclone, keeps a
# ledger of what was delivered, and removes expired raw demos only when that is proven.
# Runs on the game host as the QLDS user from a systemd timer (and by hand for "Sync now").
#
# Usage: sh forwarder.sh [run|purge]        (default run)
#   run    upload new/changed files, then delete the files of `expire` rows that are older
#          than RETENTION_DAYS AND ledgered AND whose delivery (ledger delivered_at) is at
#          least DELIVERED_GRACE_HOURS old. The ledger alone decides, no remote listing: the
#          NAS pulls raw/ with a MOVE sync, so a delivered raw demo is normally gone from the
#          VPS by then. A file is never deleted in the run that delivered it.
#   purge  run, then, whatever the file age: delete ledgered files of `keep` rows only when
#          the remote listing holds them (name and size; those directories stay on the VPS),
#          and ledgered files of `expire` rows when the remote listing holds them OR their
#          delivery is at least DELIVERED_GRACE_HOURS old (the NAS has had time to pull them).
#          Everything else is kept and counted in kept_unconfirmed (empty a host / collect
#          everything before the VPS goes away). Purge still applies the raw upload limits
#          (MAX_RAW_MB_PER_RUN, MAX_RAW_REMOTE_MB) to its upload step, so emptying a host with a
#          big raw backlog takes several purge runs.
#
# Configuration: $FORWARDER_CONF (default /home/ql/file-forwarder/forwarder.conf), an sh file:
#   REMOTE              rclone remote name                          (qldemos)
#   SRC_GLOBS           space separated directories, globs allowed  (/home/ql/qlds-*/demos)
#   PATTERNS            space separated glob:remote_dir:keep|expire
#                       (*.qlmatch:qlmatch:keep *.replay.json.gz:qlmatch:keep *.dm_91:raw:expire)
#   RETENTION_DAYS      age after which `expire` rows may be deleted (14)
#   DELIVERED_GRACE_HOURS  a delivered file may be deleted only this long after its
#                       delivery, positive (24)
#   MIN_AGE_MIN         a file is sent only when older than this    (2)
#   MAX_RAW_MB_PER_RUN  stop sending files for remote_dir `raw` once this much was sent
#                       in one run, newest first; the rest waits for the next run (2048)
#   MAX_RAW_REMOTE_MB   send nothing to remote_dir `raw` in a run that finds the remote raw
#                       directory already holding this much (one `rclone lsjson` before the
#                       uploads; not a failure, the files wait). A listing that fails does not
#                       block the uploads. Positive (5000)
#   STATE_DIR           ledger, last-run, lock                      (/home/ql/.forwarder-state)
#   RCLONE              rclone binary                               (rclone)
#
# Ledger $STATE_DIR/delivered.tsv: name<TAB>size<TAB>mtime<TAB>delivered_at (ISO UTC,
# 2026-10-11T10:00:00Z), one line per delivered file. A file counts as delivered only when
# name, size and mtime all match a line. A file is NEVER deleted without such a line. A line
# whose delivered_at cannot be read never makes its file old enough to delete.
# The remote directory is flat, so a name present in more than one source directory (same
# pattern row) would overwrite itself there. Every file of such a name is treated as failed:
# not uploaded, not ledgered, never deleted, logged with its path, exit 1 until the operator
# resolves it.
#
# Exit codes: 0 ok, 1 some uploads failed (retried next run), 2 configuration error (nothing
# is uploaded or deleted). Kept files (kept_unconfirmed, purge only) do not change the exit
# code. A run that finds the lock held exits 0 at once with a "locked" line and leaves
# last-run alone.
# Every finished run writes one line to $STATE_DIR/last-run:
#   time=<iso> mode=<run|purge> uploaded=<n> failed=<n> deleted=<n> kept_unconfirmed=<n> exit=<code>
#
# Names containing a newline or a tab are never sent (counted as failed); a name cannot hold
# a slash. Needs GNU find (-printf), awk and GNU date (`date -u +%s`); names with spaces and
# non-ASCII letters are fine.
set -eu
set -f
LC_ALL=C
export LC_ALL

NL='
'
TAB=$(printf '\t')

mode="${1:-run}"
case "$mode" in
    run|purge) ;;
    *) echo "[forwarder] usage: forwarder.sh [run|purge]" >&2; exit 2 ;;
esac

log() { echo "[forwarder] $*"; }

STATE_DIR="${STATE_DIR:-/home/ql/.forwarder-state}"
REMOTE=qldemos
SRC_GLOBS='/home/ql/qlds-*/demos'
PATTERNS='*.qlmatch:qlmatch:keep *.replay.json.gz:qlmatch:keep *.dm_91:raw:expire'
RETENTION_DAYS=14
DELIVERED_GRACE_HOURS=24
MIN_AGE_MIN=2
MAX_RAW_MB_PER_RUN=2048
MAX_RAW_REMOTE_MB=5000
RCLONE=rclone

uploaded=0
failed=0
deleted=0
kept_unconfirmed=0
TMP=

write_last_run() {
    mkdir -p "$STATE_DIR" 2>/dev/null || return 0
    line="time=$(date -u +%Y-%m-%dT%H:%M:%SZ) mode=$mode uploaded=$uploaded failed=$failed deleted=$deleted kept_unconfirmed=$kept_unconfirmed exit=$1"
    echo "$line" > "$STATE_DIR/last-run.new" 2>/dev/null && mv -f "$STATE_DIR/last-run.new" "$STATE_DIR/last-run" || true
    log "$line"
}

config_error() {
    log "ERROR: $*"
    write_last_run 2
    exit 2
}

conf="${FORWARDER_CONF:-/home/ql/file-forwarder/forwarder.conf}"
[ -r "$conf" ] || config_error "cannot read config $conf"
case "$conf" in */*) ;; *) conf="./$conf" ;; esac
. "$conf"

check_int() {
    case "$2" in
        ''|*[!0-9]*) config_error "$1 must be a non-negative integer, got '$2'" ;;
    esac
}
check_pos() {
    case "$2" in
        ''|*[!0-9]*|0*) config_error "$1 must be a positive integer, got '$2'" ;;
    esac
}
check_int RETENTION_DAYS "$RETENTION_DAYS"
check_int MIN_AGE_MIN "$MIN_AGE_MIN"
check_int MAX_RAW_MB_PER_RUN "$MAX_RAW_MB_PER_RUN"
check_pos DELIVERED_GRACE_HOURS "$DELIVERED_GRACE_HOURS"
check_pos MAX_RAW_REMOTE_MB "$MAX_RAW_REMOTE_MB"
# The run's start time: deliveries recorded by this run are never older than this, so with a
# positive grace none of them can be deleted by this run.
run_start=$(date -u +%s)
case "$run_start" in
    ''|*[!0-9]*) config_error "date -u +%s gave '$run_start', need GNU date" ;;
esac
[ -n "$REMOTE" ] || config_error "REMOTE is empty"
[ -n "$STATE_DIR" ] || config_error "STATE_DIR is empty"
[ -n "$PATTERNS" ] || config_error "PATTERNS is empty"
for row in $PATTERNS; do
    rest="${row#*:}"
    [ "$rest" != "$row" ] || config_error "pattern '$row' is not glob:remote_dir:keep|expire"
    glob="${row%%:*}"
    rdir="${rest%%:*}"
    kind="${rest#*:}"
    [ -n "$glob" ] || config_error "pattern '$row' has an empty glob"
    case "$rdir" in
        ''|-*|.*|*[!A-Za-z0-9_.-]*) config_error "pattern '$row' has a bad remote_dir '$rdir' (use A-Za-z0-9_.- only)" ;;
    esac
    case "$kind" in
        keep|expire) ;;
        *) config_error "pattern '$row' must end in keep or expire" ;;
    esac
done
command -v "$RCLONE" >/dev/null 2>&1 || config_error "rclone binary '$RCLONE' not found"

mkdir -p "$STATE_DIR" || config_error "cannot create $STATE_DIR"

# Lock: mkdir is atomic and portable (no flock needed). A lock older than 6 hours is left by a
# run that was killed hard (power loss, kill -9; a normal exit or TERM removes it) and is
# taken over.
LOCK="$STATE_DIR/lock"
if ! mkdir "$LOCK" 2>/dev/null; then
    if [ -n "$(find "$LOCK" -maxdepth 0 -mmin +360 2>/dev/null)" ]; then
        log "removing stale lock $LOCK (older than 6 hours)"
        rmdir "$LOCK" 2>/dev/null || true
    fi
    if ! mkdir "$LOCK" 2>/dev/null; then
        log "locked: another run holds $LOCK, exiting"
        exit 0
    fi
fi
TMP="$STATE_DIR/tmp.$$"
cleanup() {
    [ -z "$TMP" ] || rm -rf "$TMP"
    rmdir "$LOCK" 2>/dev/null || true
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
# Work directories left by runs that were killed hard (we hold the lock, so none is live).
find "$STATE_DIR" -maxdepth 1 -type d -name 'tmp.*' -exec rm -rf {} + 2>/dev/null || true
mkdir -p "$TMP"

# Source directories (globs expanded here, once).
set +f
dirs=
for d in $SRC_GLOBS; do
    if [ -d "$d" ]; then dirs="$dirs $d"; fi
done
set -f
if [ -z "$dirs" ]; then
    log "no source directory found for '$SRC_GLOBS', nothing to do"
fi

LEDGER="$STATE_DIR/delivered.tsv"
KEYS="$TMP/keys"
: > "$KEYS"
if [ -f "$LEDGER" ]; then cut -f 1-3 "$LEDGER" > "$KEYS" || true; fi

retention_min=$((RETENTION_DAYS * 1440))
cap_bytes=$((MAX_RAW_MB_PER_RUN * 1048576))
sent_raw=0

# list_files <glob> <min age minutes or empty> <outfile>
# Candidate regular files, newest first, as "mtime<TAB>size<TAB>path". Never *.partial and
# never a name with a newline or tab (those are listed by count_unsafe instead).
list_files() {
    age=
    if [ -n "$2" ]; then age="-mmin +$2"; fi
    if [ -z "$dirs" ]; then : > "$3"; return 0; fi
    find $dirs -maxdepth 1 -type f -name "$1" ! -name '*.partial' ! -name "*$NL*" ! -name "*$TAB*" \
        $age -printf '%T@\t%s\t%p\n' 2>/dev/null | sort -t "$TAB" -k1,1nr > "$3" || true
}

# count_unsafe <glob> <min age minutes>: names that match but may not be sent
count_unsafe() {
    if [ -z "$dirs" ]; then echo 0; return 0; fi
    find $dirs -maxdepth 1 -type f -name "$1" ! -name '*.partial' \( -name "*$NL*" -o -name "*$TAB*" \) \
        -mmin "+$2" -printf 'x\n' 2>/dev/null | wc -l | tr -d ' '
}

is_ledgered() { grep -Fxq -- "$1" "$KEYS"; }

# dup_names <glob> <outfile>: names that exist in more than one source directory (any age);
# the flat remote directory cannot hold both, so none of them is sent or deleted.
dup_names() {
    list_files "$1" "" "$TMP/all.list"
    awk -F '\t' '{ n = $3; sub(/.*\//, "", n); c[n]++ } END { for (k in c) if (c[k] > 1) print k }' \
        "$TMP/all.list" > "$2"
}

# list_remote <remote_dir> <outfile>: the remote listing as "name<TAB>size" lines. Returns 1
# when the listing fails (missing dir, network); the outfile is then empty.
list_remote() {
    if "$RCLONE" lsjson "$REMOTE:$1" > "$2.json" 2>/dev/null </dev/null; then
        # A small JSON scanner: strings are read with their escapes, so a name holding a
        # brace or a quote cannot split a record. A record is the object at depth 1; its
        # Name and Size are paired only inside that record. \uXXXX below 0x80 is decoded;
        # a name with a control character or any other \u escape is written empty (it then
        # confirms nothing, so the file is kept, but its size still counts).
        awk '
        function hexval(h,   i, c, v) {
            v = 0; h = tolower(h)
            for (i = 1; i <= length(h); i++) {
                c = index("0123456789abcdef", substr(h, i, 1))
                if (c == 0) return -1
                v = v * 16 + c - 1
            }
            return v
        }
        function unescape(s,   out, i, c, e, code) {
            out = ""; i = 1
            while (i <= length(s)) {
                c = substr(s, i, 1)
                if (c != "\\") { out = out c; i++; continue }
                e = substr(s, i + 1, 1)
                if (e == "u") {
                    code = hexval(substr(s, i + 2, 4))
                    if (code < 32 || code >= 128) { bad = 1; return "" }
                    out = out sprintf("%c", code); i += 6; continue
                }
                if (e == "n" || e == "t" || e == "r" || e == "b" || e == "f") { bad = 1; return "" }
                out = out e
                i += 2
            }
            return out
        }
        { buf = buf $0 "\n" }
        END {
            n = length(buf); depth = 0; i = 1; key = ""
            while (i <= n) {
                c = substr(buf, i, 1)
                if (c == "\"") {
                    j = i + 1; raw = ""
                    while (j <= n) {
                        d = substr(buf, j, 1)
                        if (d == "\\") { raw = raw d substr(buf, j + 1, 1); j += 2; continue }
                        if (d == "\"") break
                        raw = raw d; j++
                    }
                    i = j + 1
                    k = i
                    while (k <= n && substr(buf, k, 1) ~ /[ \t\r\n]/) k++
                    if (substr(buf, k, 1) == ":") { key = raw; i = k + 1 }
                    else if (depth == 1 && key == "Name") {
                        bad = 0; nm = unescape(raw)
                        name = bad ? "" : nm; have_name = 1
                        key = ""
                    }
                    continue
                }
                if (c == "{") {
                    depth++
                    if (depth == 1) { have_name = 0; have_size = 0; key = "" }
                } else if (c == "}") {
                    if (depth == 1 && have_name && have_size) printf "%s\t%s\n", name, size
                    depth--
                } else if (depth == 1 && key == "Size" && c ~ /[-0-9]/) {
                    j = i
                    while (j <= n && substr(buf, j, 1) ~ /[-0-9]/) j++
                    size = substr(buf, i, j - i); have_size = 1; key = ""
                    i = j; continue
                }
                i++
            }
        }' "$2.json" > "$2" || : > "$2"
        return 0
    fi
    : > "$2"
    return 1
}

# The remote raw budget: one listing before the uploads. A failed listing does not block
# them (the uploads then fail on their own if the remote is away).
raw_full=0
for row in $PATTERNS; do
    rest="${row#*:}"
    if [ "${rest%%:*}" = raw ]; then
        if list_remote raw "$TMP/budget"; then
            remote_raw=$(awk -F '\t' '$2 > 0 { s += $2 } END { printf "%.0f\n", s }' "$TMP/budget")
            if [ "$remote_raw" -ge $((MAX_RAW_REMOTE_MB * 1048576)) ]; then
                raw_full=1
                log "remote raw/ already holds $((remote_raw / 1048576)) MB (MAX_RAW_REMOTE_MB ${MAX_RAW_REMOTE_MB}), no raw upload this run"
            fi
        else
            log "cannot list $REMOTE:raw, raw uploads go ahead without the MAX_RAW_REMOTE_MB check"
        fi
        break
    fi
done

# Upload phase.
n=0
for row in $PATTERNS; do
    n=$((n + 1))
    glob="${row%%:*}"
    rest="${row#*:}"
    rdir="${rest%%:*}"
    list="$TMP/up.$n"
    list_files "$glob" "$MIN_AGE_MIN" "$list"
    dups="$TMP/dup.$n"
    dup_names "$glob" "$dups"

    bad=$(count_unsafe "$glob" "$MIN_AGE_MIN")
    if [ "$bad" -gt 0 ]; then
        log "skipping $bad file(s) matching $glob whose name has a newline or tab"
        failed=$((failed + bad))
    fi

    while IFS="$TAB" read -r mt sz path; do
        [ -n "$path" ] || continue
        name="${path##*/}"
        mt="${mt%%.*}"
        key="$name$TAB$sz$TAB$mt"
        if grep -Fxq -- "$name" "$dups"; then
            failed=$((failed + 1))
            log "name collision: $path has the same name as a file in another source directory, not sent"
            continue
        fi
        if is_ledgered "$key"; then continue; fi
        if [ "$rdir" = raw ] && [ "$raw_full" = 1 ]; then continue; fi
        if [ "$rdir" = raw ] && [ "$sent_raw" -ge "$cap_bytes" ]; then
            log "raw cap of ${MAX_RAW_MB_PER_RUN} MB reached, $name waits for the next run"
            continue
        fi
        if "$RCLONE" copyto "$path" "$REMOTE:$rdir/$name" </dev/null; then
            printf '%s\t%s\t%s\t%s\n' "$name" "$sz" "$mt" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$LEDGER"
            echo "$key" >> "$KEYS"
            uploaded=$((uploaded + 1))
            if [ "$rdir" = raw ]; then sent_raw=$((sent_raw + sz)); fi
            log "uploaded $name -> $rdir/"
        else
            failed=$((failed + 1))
            log "upload of $name failed"
        fi
    done < "$list"
done

# remote_has <remote_dir> <name> <size>: true when the remote listing holds that name with that
# size. The listing is fetched once per remote dir, after the uploads above. A failed listing
# (missing dir, network) is an empty one, so nothing counts as confirmed.
remote_has() {
    rl="$TMP/rl.$1"
    if [ ! -f "$rl" ]; then
        list_remote "$1" "$rl" || log "cannot list $REMOTE:$1, nothing in it counts as confirmed"
    fi
    grep -Fxq -- "$2$TAB$3" "$rl"
}

# Ledger keys (name<TAB>size<TAB>mtime) whose delivery is at least DELIVERED_GRACE_HOURS old
# at the start of this run. delivered_at must be exactly YYYY-MM-DDTHH:MM:SSZ; a key with any
# line that is not, or with fewer than 4 columns, is left out (never old enough). A key with
# several lines counts by its latest delivery. Epoch seconds are computed in awk (days from
# the civil date), so no date parsing tool is needed.
GRACED="$TMP/graced"
: > "$GRACED"
if [ -f "$LEDGER" ]; then
    awk -F '\t' -v cutoff="$((run_start - DELIVERED_GRACE_HOURS * 3600))" '
    function days(y, m, d) {
        if (m <= 2) { y--; m += 12 }
        return 365 * y + int(y / 4) - int(y / 100) + int(y / 400) + int((153 * (m - 3) + 2) / 5) + d - 719469
    }
    {
        k = $1 "\t" $2 "\t" $3
        t = $4
        ok = (NF >= 4 && t ~ /^[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z$/)
        if (ok) {
            y = substr(t, 1, 4) + 0; mo = substr(t, 6, 2) + 0; d = substr(t, 9, 2) + 0
            h = substr(t, 12, 2) + 0; mi = substr(t, 15, 2) + 0; s = substr(t, 18, 2) + 0
            ok = (mo >= 1 && mo <= 12 && d >= 1 && d <= 31 && h <= 23 && mi <= 59 && s <= 60)
        }
        if (!ok) { bad[k] = 1; next }
        e = days(y, mo, d) * 86400 + h * 3600 + mi * 60 + s
        if (!(k in late) || e > late[k]) late[k] = e
    }
    END { for (k in late) if (!(k in bad) && late[k] <= cutoff + 0) print k }' "$LEDGER" > "$GRACED" || : > "$GRACED"
fi

is_graced() { grep -Fxq -- "$1" "$GRACED"; }

# cleanup_row <glob> <remote_dir> <keep|expire> <min age minutes or empty>
cleanup_row() {
    list="$TMP/cl.$n"
    list_files "$1" "$4" "$list"
    dups="$TMP/dupc.$n"
    dup_names "$1" "$dups"
    while IFS="$TAB" read -r mt sz path; do
        [ -n "$path" ] || continue
        name="${path##*/}"
        mt="${mt%%.*}"
        key="$name$TAB$sz$TAB$mt"
        if grep -Fxq -- "$name" "$dups"; then
            log "kept $path: same name exists in another source directory"
            continue
        fi
        is_ledgered "$key" || continue
        if [ "$mode" = run ]; then
            if ! is_graced "$key"; then
                log "kept $path: delivered less than ${DELIVERED_GRACE_HOURS} hours ago (or its delivery time is unreadable)"
                continue
            fi
        elif { [ "$3" = expire ] && is_graced "$key"; } || remote_has "$2" "$name" "$sz"; then
            :
        else
            kept_unconfirmed=$((kept_unconfirmed + 1))
            if [ "$3" = expire ]; then
                log "kept $path: not on the remote and delivered less than ${DELIVERED_GRACE_HOURS} hours ago"
            else
                log "kept $path: the remote copy is missing or differs"
            fi
            continue
        fi
        if rm -f -- "$path"; then
            deleted=$((deleted + 1))
            log "deleted $path"
        fi
    done < "$list"
}

# Cleanup phase. Purge looks at every row and ignores age; run only at `expire` rows past
# the retention.
for row in $PATTERNS; do
    n=$((n + 1))
    glob="${row%%:*}"
    rest="${row#*:}"
    rdir="${rest%%:*}"
    kind="${rest#*:}"
    if [ "$mode" = purge ]; then
        cleanup_row "$glob" "$rdir" "$kind" ""
    elif [ "$kind" = expire ]; then
        cleanup_row "$glob" "$rdir" "$kind" "$retention_min"
    fi
done

code=0
if [ "$failed" -gt 0 ]; then code=1; fi
write_last_run "$code"
exit "$code"
