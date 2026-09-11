#!/usr/bin/env bash
# Explicit disaster recovery; application images must match the restored schema.
set -euo pipefail
source "$(dirname "$0")/common.sh" "${1:-/opt/womanup}"
backup="${2:?Pass an absolute backup path}"
[[ "${3:-}" == RESTORE ]] || { echo "Third argument must be RESTORE" >&2; exit 1; }
backup=$(realpath "$backup")
[[ "$backup" == "$ROOT/backups/"* && "$backup" == *.dump ]]
lock_server
c exec -T postgres pg_restore --list < "$backup" >/dev/null
bash "$RELEASE/scripts/backup.sh" "$ROOT" pre-restore
c stop backend worker
rm -f "$ROOT/state/backend.hash"
if ! c exec -T postgres pg_restore -U postgres -d womanup --clean --if-exists \
  --exit-on-error --single-transaction < "$backup"; then
  echo "Restore failed; backend and worker remain stopped for inspection." >&2
  exit 1
fi
grant_app
echo "Restore complete. Select the matching backend image in infra and dispatch deployment."
