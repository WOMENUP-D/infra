#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/common.sh" "${1:-/opt/womanup}"
lock_server
umask 077
name="$ROOT/backups/$(date -u +%Y%m%dT%H%M%S%N)-${2:-daily}.dump"
[[ "$name" =~ ^/opt/[a-z0-9-]+/backups/[0-9TZ]+-(daily|pre-migration|pre-restore)\.dump$ ]]
trap 'rm -f "$name.partial"' EXIT
c exec -T postgres pg_dump -U postgres -d womanup --format=custom > "$name.partial"
test -s "$name.partial"
c exec -T postgres pg_restore --list < "$name.partial" >/dev/null
mv "$name.partial" "$name"
# Prune only verified backup files, and only after producing a new backup.
find "$ROOT/backups" -maxdepth 1 -type f -name '*.dump' -mmin +10080 -delete
echo "Backup created: $name"
