#!/usr/bin/env bash
# Disaster recovery, run by hand. Nothing calls this automatically.
#
#   bash scripts/restore.sh /opt/womanup /opt/womanup/backups/<file>.dump RESTORE
#
# The third argument is there so that a half-remembered command line cannot
# overwrite the live database. The backend image must match the schema being
# restored — after a restore, dispatch the deployment for the release the dump
# was taken from.
set -euo pipefail
source "$(dirname "$0")/common.sh" "${1:-/opt/womanup}"
backup="${2:?Pass an absolute backup path}"
[[ "${3:-}" == RESTORE ]] || { echo "Third argument must be RESTORE" >&2; exit 1; }
backup=$(realpath "$backup")
[[ "$backup" == "$ROOT/backups/"* && "$backup" == *.dump ]]
lock_server
# Read the dump before anything is stopped: an unreadable file is not a reason
# to take the site down.
c exec -T postgres pg_restore --list < "$backup" > /dev/null
# And keep what is about to be replaced.
bash "$RELEASE/scripts/backup.sh" "$ROOT" pre-restore
c stop backend worker
rm -f "$ROOT/state/backend.hash"
if ! c exec -T postgres pg_restore -U postgres -d womanup --clean --if-exists \
  --exit-on-error --single-transaction < "$backup"; then
  echo "Restore failed; the database is unchanged and the apps remain stopped." >&2
  exit 1
fi
echo "Restore complete. Select the matching backend image in infra and dispatch deployment."
