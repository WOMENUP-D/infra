#!/usr/bin/env bash
set -euo pipefail
umask 077
source "$(dirname "$0")/common.sh" "${1:-/opt/womanup}"
lock_server
python3 "$RELEASE/scripts/backup.py" "$ROOT" backup
