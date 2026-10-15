#!/usr/bin/env bash
# Builds the static linux/amd64 ql-ping-echo into assets/ (committed: qlsm
# installs the addon zip and cannot build anything). Works from Git Bash on
# Windows too: the target is set per command, not by the host.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/echo"
CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -trimpath -ldflags="-s -w" -o ../assets/ql-ping-echo .
echo "built $(cd .. && pwd)/assets/ql-ping-echo"
