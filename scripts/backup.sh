#!/usr/bin/env bash
# A verified dump of the production database: on a timer every night, and once
# more immediately before every migration. Read back by restore.sh.
#
# The portal holds the personal data of the women who registered on it. There
# is currently no other copy of it anywhere: a dropped volume, a bad migration
# or a mistaken DELETE is, without this, permanent.
set -euo pipefail
source "$(dirname "$0")/common.sh" "${1:-/opt/womanup}"
kind="${2:-daily}"
[[ "$kind" =~ ^(daily|pre-migration|pre-restore|manual)$ ]] || {
  echo "Unknown backup kind: $kind" >&2
  exit 1
}
lock_server
umask 077
install -d -m 0700 "$ROOT/backups"

# A week of nightly dumps — and never fewer than three whatever their age,
# because a fortnight of failed timers must not be what leaves the server with
# nothing to restore from.
KEEP_DAYS=7
KEEP_AT_LEAST=3

prune_old_backups() {
  local dumps=() index
  while IFS= read -r line; do dumps+=("$line"); done < <(ls -1t "$ROOT"/backups/*.dump 2>/dev/null || true)
  for (( index = KEEP_AT_LEAST; index < ${#dumps[@]}; index++ )); do
    if [[ -n "$(find "${dumps[index]}" -maxdepth 0 -mmin "+$(( KEEP_DAYS * 1440 ))")" ]]; then
      rm -f -- "${dumps[index]}"
    fi
  done
}

free_bytes() {
  df -PB1 "$ROOT/backups" | awk 'NR == 2 {print $4}'
}

# Old dumps go first, so the space check below measures what is really there.
prune_old_backups

size=$(c exec -T postgres psql -U postgres -d womanup -Atc "SELECT pg_database_size('womanup')" | tr -d '\r')
[[ "$size" =~ ^[0-9]+$ ]] || { echo "Could not measure the database; is postgres running?" >&2; exit 1; }
# The custom format is compressed and comes out well under the live size; this
# margin is deliberately generous, because a backup that fills the disk takes
# the site down with it.
needed=$(( size + size / 2 + 268435456 ))
available=$(free_bytes)
if (( available < needed )); then
  echo "Not enough free space under $ROOT/backups for a backup of this database." >&2
  echo "Free space on the volume or enlarge the disk, then run this again." >&2
  exit 1
fi

name="$ROOT/backups/$(date -u +%Y%m%dT%H%M%S%NZ)-$kind.dump"
[[ "$name" =~ ^/opt/[a-z0-9-]+/backups/[0-9]{8}T[0-9]+Z-(daily|pre-migration|pre-restore|manual)\.dump$ ]]
trap 'rm -f -- "$name.partial"' EXIT
c exec -T postgres pg_dump -U postgres -d womanup --format=custom > "$name.partial"
test -s "$name.partial"
# An unreadable dump is worse than no dump: it is a backup somebody trusts.
c exec -T postgres pg_restore --list < "$name.partial" > /dev/null
chmod 600 "$name.partial"
mv -- "$name.partial" "$name"
echo "Backup created: $name"
