#!/usr/bin/env bash
# Compares qlsm's vendor/qldemo against ql-stream-tools/live-overlay/lib/qldemo
# and refreshes the map pickup-entity tables. It does NOT copy vendor/qldemo
# in either direction anymore.
#
# vendor/qldemo started life as a copy of
#   ql-stream-tools/live-overlay/lib/qldemo/
# but qlsm has since carried its own fixes forward on top of it without
# merging them back upstream (replay generator version bump, score derived
# from death events instead of scores_duel, dropping the pre-fight-start
# pickup filter, plus further rounds since) — see git log on this directory.
# qlsm now treats vendor/qldemo as an INDEPENDENT fork of that parser, not a
# verbatim mirror, and there is no plan to merge it back. A blind copy in
# either direction — which is what this script used to do via rm+cp — would
# silently discard whichever side's fixes the other side is missing; that is
# exactly what happened before this rewrite.
#
# So this script only diffs the two trees file-by-file and reports what
# differs; porting anything is a manual, reviewed decision, not something
# this script does for you. maps/entities is a different story: it's a plain
# data vendor (per-map pickup tables) with no history of qlsm-side edits, so
# that half still copies for real.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Optional argument: explicit path to the ql-stream-tools checkout — needed
# when this script runs from a git worktree of qlsm, where the relative
# monorepo-sibling walk below cannot reach ql-stream-tools.
overlay=""
if [ $# -ge 1 ]; then
  overlay="$1/live-overlay"
  if [ ! -d "$overlay/lib/qldemo" ]; then
    echo "sync-vendor: $1 is not a ql-stream-tools checkout (no live-overlay/lib/qldemo)" >&2
    exit 1
  fi
else
  for candidate in \
      "$here/../../../../ql-stream-tools/live-overlay" \
      "$here/../../../../../ql-stream-tools/live-overlay" \
      "$here/../../../../../../ql-stream-tools/live-overlay"; do
    if [ -d "$candidate/lib/qldemo" ]; then
      overlay="$candidate"
      break
    fi
  done
fi
if [ -z "$overlay" ]; then
  echo "sync-vendor: ql-stream-tools/live-overlay/lib/qldemo not found near $here" >&2
  echo "sync-vendor: run from a monorepo workspace that has ql-stream-tools checked out," >&2
  echo "sync-vendor: or pass the ql-stream-tools path: bash sync-vendor.sh /path/to/ql-stream-tools" >&2
  exit 1
fi
src="$overlay/lib/qldemo"
dest="$here/vendor/qldemo"

echo "sync-vendor: diffing (read-only, no files touched):"
echo "  qlsm fork:  $dest"
echo "  upstream:   $src"
echo

diff_found=0
while IFS= read -r -d '' f; do
  rel="${f#"$src"/}"
  destfile="$dest/$rel"
  if [ ! -f "$destfile" ]; then
    echo "  only upstream:  $rel"
    diff_found=1
  elif ! cmp -s "$f" "$destfile"; then
    echo "  differs:        $rel"
    diff_found=1
  fi
done < <(find "$src" -type f -print0)

while IFS= read -r -d '' f; do
  rel="${f#"$dest"/}"
  if [ ! -f "$src/$rel" ]; then
    echo "  only qlsm fork: $rel"
    diff_found=1
  fi
done < <(find "$dest" -type f -print0)

if [ "$diff_found" -eq 0 ]; then
  echo "  (no differences)"
fi
echo
echo "sync-vendor: vendor/qldemo is not copied — port anything above by hand and"
echo "sync-vendor: review it, in whichever direction actually makes sense."

# maps/entities is a plain data vendor (no qlsm-side edits on record), so this
# half still refreshes for real. rm+cp instead of rsync --delete: this also
# runs on the operator's Windows Git Bash, which ships no rsync.
entities_src="$overlay/maps/entities"
if [ -d "$entities_src" ]; then
  rm -rf "$here/maps/entities"
  mkdir -p "$here/maps/entities"
  cp -a "$entities_src/." "$here/maps/entities/"
  {
    echo "source: ql-stream-tools/live-overlay/maps/entities (pickup tables)"
    echo "synced: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "refresh: bash sync-vendor.sh (see header comment)"
    echo "note: vendor/qldemo itself is no longer synced here — it is qlsm's own fork, diffed only"
  } > "$here/vendor/VENDOR-INFO.txt"
  echo
  echo "sync-vendor: maps/entities refreshed from $overlay"
fi
