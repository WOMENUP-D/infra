#!/usr/bin/env bash
set -euo pipefail
umask 077
source "$(dirname "$0")/common.sh" "${1:-/opt/womanup}"
snapshot="${2:?Snapshot directory required}"
[[ "${3:-}" == --confirm && "${4:-}" == womanup_db ]] || {
  echo "Usage: restore.sh /opt/womanup SNAPSHOT --confirm womanup_db" >&2; exit 1;
}
lock_server
if [[ -n "$(c ps --status running -q backend worker)" ]]; then
  echo "Stop WomanUP backend and worker before restore; no services were changed." >&2
  exit 1
fi
python3 "$RELEASE/scripts/backup.py" "$ROOT" restore "$snapshot"
