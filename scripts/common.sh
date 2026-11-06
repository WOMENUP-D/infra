#!/usr/bin/env bash
set -euo pipefail
ROOT="${1:-/opt/womanup}"
[[ "$ROOT" == /opt/womanup && ! -L "$ROOT" ]] || { echo "Invalid deployment root" >&2; exit 1; }
RELEASE="${RELEASE:-$ROOT/current}"
export CONFIG_DIR="$ROOT/config"
mkdir -p "$ROOT/state"
touch "$ROOT/state/backend.env" "$ROOT/state/frontend.env"
c() {
  docker compose --project-name womanup --project-directory "$RELEASE" \
    --env-file "$CONFIG_DIR/deploy.env" \
    --env-file "$ROOT/state/backend.env" --env-file "$ROOT/state/frontend.env" \
    -f "$RELEASE/compose.yml" "$@"
}
lock_server() {
  if [[ "${WOMANUP_LOCKED:-}" != 1 ]]; then
    exec 9>"$ROOT/deploy.lock"
    flock -w 1800 9
    export WOMANUP_LOCKED=1
  fi
}
healthy() {
  local id
  id=$(c ps -q "$1")
  [[ -n "$id" ]] && [[ "$(docker inspect --format '{{.State.Health.Status}}' "$id")" == healthy ]]
}
running() {
  local id
  id=$(c ps -q "$1")
  [[ -n "$id" ]] && [[ "$(docker inspect --format '{{.State.Running}}' "$id")" == true ]]
}
revision() {
  python3 "$RELEASE/scripts/database.py" "$CONFIG_DIR" revision
}
internal_http_check() {
  local url="$1"
  for _ in {1..12}; do
    if c exec -T caddy wget -qO /dev/null "$url"; then
      return 0
    fi
    sleep 5
  done
  echo "Internal HTTP check failed: $url" >&2
  return 1
}
