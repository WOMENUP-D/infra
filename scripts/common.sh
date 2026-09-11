#!/usr/bin/env bash
set -euo pipefail
ROOT="${1:-/opt/womanup}"
[[ "$ROOT" =~ ^/opt/[a-z0-9-]+$ ]] || { echo "Invalid deployment root" >&2; exit 1; }
RELEASE="${RELEASE:-$ROOT/current}"
export CONFIG_DIR="$ROOT/config"
mkdir -p "$ROOT/state" "$ROOT/backups"
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
revision() {
  if [[ "$(c exec -T postgres psql -U postgres -d womanup -Atc "SELECT to_regclass('public.alembic_version') IS NOT NULL")" == t ]]; then
    c exec -T postgres psql -U postgres -d womanup -Atc 'SELECT version_num FROM alembic_version ORDER BY version_num'
  fi
}
grant_app() {
  c exec -T postgres psql -v ON_ERROR_STOP=1 -U postgres -d womanup <<'SQL'
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO womanup_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO womanup_app;
REVOKE ALL ON alembic_version FROM womanup_app;
REVOKE UPDATE, DELETE, TRUNCATE ON audit_logs FROM womanup_app;
SQL
}
public_check() {
  local path="$1"
  local domain
  domain=$(sed -n 's/^APP_DOMAIN=//p' "$CONFIG_DIR/deploy.env")
  curl --fail --silent --show-error --retry 12 --retry-all-errors --retry-delay 5 \
    --connect-timeout 5 --max-time 15 "https://$domain$path" >/dev/null
}
