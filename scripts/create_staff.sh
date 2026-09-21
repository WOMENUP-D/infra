#!/usr/bin/env bash
# Open a desk account, or set a new password on one, from GitHub Actions — so
# the first administrator does not depend on somebody having SSH to the server.
#
#   printf '%s\n' "$password" | sudo bash scripts/create_staff.sh /opt/womanup admin@example.uz admin
#
# The password arrives on stdin, never as an argument: arguments are visible in
# `ps` to every user of the machine. It reaches the container through the
# environment for the same reason, and the backend command never prints it.
set -euo pipefail
source "$(dirname "$0")/common.sh" "${1:-/opt/womanup}"
email="${2:?Pass the sign-in address}"
role="${3:-admin}"
[[ "$email" =~ ^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$ ]] || {
  echo "Not an e-mail address." >&2
  exit 1
}
[[ "$role" =~ ^(admin|regional_coordinator|moderator|trainer)$ ]] || {
  echo "Not a staff role: admin, regional_coordinator, moderator or trainer." >&2
  exit 1
}
WOMANUP_STAFF_PASSWORD=""
IFS= read -r WOMANUP_STAFF_PASSWORD || true
[[ -n "$WOMANUP_STAFF_PASSWORD" ]] || { echo "No password arrived on stdin." >&2; exit 1; }
export WOMANUP_STAFF_PASSWORD
# Not while a deploy has the backend stopped or half-migrated.
lock_server
# --update: running this again for the same address sets a new password rather
# than failing, which is what somebody locked out of the panel needs.
c run --rm --no-deps -T -e WOMANUP_STAFF_PASSWORD migrate \
  python -m app.create_staff --email "$email" --role "$role" --update
