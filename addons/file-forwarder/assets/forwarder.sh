#!/bin/sh
# file-forwarder: ships demo files from a game host to the site VPS with rclone, keeps a
# ledger of what was delivered, and removes expired raw demos only when that is proven.
# Runs on the game host as the QLDS user from a systemd timer (and by hand for "Sync now").
#
# Usage: sh forwarder.sh [run|purge]        (default run)
#   run    upload new/changed files, then delete expired files of `expire` rows that are
#          ledgered AND confirmed on the remote
#   purge  run, then delete EVERY ledgered file that is confirmed on the remote right now,
#          whatever its age or pattern row (empty a host / collect everything before the
#          VPS goes away). Purge still applies the raw backlog cap (MAX_RAW_MB_PER_RUN) to
#          its upload step, so emptying a host with a big raw backlog takes several purge runs.
#
# Configuration: $FORWARDER_CONF (default /home/ql/file-forwarder/forwarder.conf), an sh file:
#   REMOTE              rclone remote name                          (qldemos)
#   SRC_GLOBS           space separated directories, globs allowed  (/home/ql/qlds-*/demos)
#   PATTERNS            space separated glob:remote_dir:keep|expire
#                       (*.qlmatch:qlmatch:keep *.replay.json.gz:qlmatch:keep *.dm_91:raw:expire)
#   RETENTION_DAYS      age after which `expire` rows may be deleted (14)
#   MIN_AGE_MIN         a file is sent only when older than this    (2)
#   MAX_RAW_MB_PER_RUN  stop sending files for remote_dir `raw` once this much was sent
#                       in one run, newest first; the rest waits for the next run (2048)
#   STATE_DIR           ledger, last-run, lock                      (/home/ql/.forwarder-state)
#   RCLONE              rclone binary                               (rclone)
#
# Ledger $STATE_DIR/delivered.tsv: name<TAB>size<TAB>mtime<TAB>delivered_at, one line per
# delivered file. A file counts as delivered only when name, size and mtime all match a line.
# A file is NEVER deleted without such a line and a remote confirmation (the remote listing,
# one `rclone lsjson` per remote dir per run, holds that name with the same size).
# The remote directory is flat, so a name present in more than one source directory (same
# pattern row) would overwrite itself there. Every file of such a name is treated as failed:
# not uploaded, not ledgered, never deleted, logged with its path, exit 1 until the operator
# resolves it.
#
# Exit codes: 0 ok, 1 some uploads failed or could not be verified (retried next run),
# 2 configuration error (nothing is uploaded or deleted). A run that finds the lock held
# exits 0 at once with a "locked" line and leaves last-run alone.
# Every finished run writes one line to $STATE_DIR/last-run:
#   time=<iso> mode=<run|purge> uploaded=<n> failed=<n> deleted=<n> kept_unconfirmed=<n> exit=<code>
#
# Names containing a newline or a tab are never sent (counted as failed); a name cannot hold
# a slash. Needs GNU find (-printf) and awk; names with spaces and non-ASCII letters are fine.
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
MIN_AGE_MIN=2
MAX_RAW_MB_PER_RUN=2048
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
check_int RETENTION_DAYS "$RETENTION_DAYS"
check_int MIN_AGE_MIN "$MIN_AGE_MIN"
check_int MAX_RAW_MB_PER_RUN "$MAX_RAW_MB_PER_RUN"
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
        if [ "$rdir" = raw ] && [ "$sent_raw" -ge "$cap_bytes" ]; then
            log "raw cap of ${MAX_RAW_MB_PER_RUN} MB reached, $name waits for the next run"
            continue
        fi
        if "$RCLONE" copyto "$path" "$REMOTE:$rdir/$name"; then
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
        if "$RCLONE" lsjson "$REMOTE:$1" > "$rl.json" 2>/dev/null; then
            # A small JSON scanner: strings are read with their escapes, so a name holding a
            # brace or a quote cannot split a record. A record is the object at depth 1; its
            # Name and Size are paired only inside that record. \uXXXX below 0x80 is decoded;
            # a name with a control character or any other \u escape is left out (unconfirmed,
            # so the file is kept).
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
                            if (!bad) { name = nm; have_name = 1 }
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
            }' "$rl.json" > "$rl" || : > "$rl"
        else
            log "cannot list $REMOTE:$1, nothing in it counts as confirmed"
            : > "$rl"
        fi
    fi
    grep -Fxq -- "$2$TAB$3" "$rl"
}

# cleanup_row <glob> <remote_dir> <min age minutes or empty>
cleanup_row() {
    list="$TMP/cl.$n"
    list_files "$1" "$3" "$list"
    dups="$TMP/dupc.$n"
    dup_names "$1" "$dups"
    while IFS="$TAB" read -r mt sz path; do
        [ -n "$path" ] || continue
        name="${path##*/}"
        mt="${mt%%.*}"
        if grep -Fxq -- "$name" "$dups"; then
            log "kept $path: same name exists in another source directory"
            continue
        fi
        is_ledgered "$name$TAB$sz$TAB$mt" || continue
        if remote_has "$2" "$name" "$sz"; then
            if rm -f -- "$path"; then
                deleted=$((deleted + 1))
                log "deleted $path"
            fi
        else
            kept_unconfirmed=$((kept_unconfirmed + 1))
            log "kept $path: delivered earlier but the remote copy is missing or differs"
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
        cleanup_row "$glob" "$rdir" ""
    elif [ "$kind" = expire ]; then
        cleanup_row "$glob" "$rdir" "$retention_min"
    fi
done

code=0
if [ "$failed" -gt 0 ] || [ "$kept_unconfirmed" -gt 0 ]; then code=1; fi
write_last_run "$code"
exit "$code"
