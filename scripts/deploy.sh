#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/common.sh" "${1:-/opt/womanup}"
lock_server
python3 "$RELEASE/scripts/validate_images.py" "$RELEASE"
platform_hash=$(cat "$RELEASE/compose.yml" "$RELEASE/platform/Caddyfile" "$RELEASE/platform/database.sh" "$CONFIG_DIR/postgres.env" "$CONFIG_DIR/deploy.env" | sha256sum | cut -d' ' -f1)
platform_changed=0
if [[ ! -f "$ROOT/state/platform.hash" || "$(cat "$ROOT/state/platform.hash")" != "$platform_hash" ]]; then
  platform_changed=1
fi
if (( platform_changed )) || ! healthy postgres; then
  c up -d --wait --wait-timeout 180 postgres
fi
if (( platform_changed )); then
  c exec -T postgres bash /docker-entrypoint-initdb.d/10-roles.sh
  c run --rm --no-deps caddy caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
  printf '%s\n' "$platform_hash" > "$ROOT/state/platform.hash"
fi
if (( platform_changed )) || ! running caddy; then
  c up -d --no-deps caddy
fi

deploy_backend() {
  local desired="$RELEASE/apps/backend/image.env" old_image before after hash
  if ! grep -q '^BACKEND_IMAGE=' "$desired"; then return; fi
  hash=$(cat "$desired" "$CONFIG_DIR/backend.env" "$CONFIG_DIR/migration.env" "$CONFIG_DIR/postgres.env" "$RELEASE/compose.yml" | sha256sum | cut -d' ' -f1)
  if [[ -f "$ROOT/state/backend.hash" && "$(cat "$ROOT/state/backend.hash")" == "$hash" ]] && healthy backend && healthy worker; then return; fi
  rm -f "$ROOT/state/backend.hash"
  old_image=$(sed -n 's/^BACKEND_IMAGE=//p' "$ROOT/state/backend.env")
  export BACKEND_IMAGE
  BACKEND_IMAGE=$(sed -n 's/^BACKEND_IMAGE=//p' "$desired")
  c pull backend worker migrate
  if ! bash "$RELEASE/scripts/backup.sh" "$ROOT" pre-migration; then
    echo "No pre-migration backup could be taken; the running release was left untouched." >&2
    return 1
  fi
  before=$(revision)
  c stop backend worker
  if ! c run --rm --no-deps migrate; then
    echo "Migration failed; apps remain stopped. Inspect the migration, and the pre-migration backup under $ROOT/backups, before recovery." >&2
    return 1
  fi
  after=$(revision)
  if c up -d --no-deps --wait --wait-timeout 180 backend worker \
    && internal_http_check http://backend:8000/health/ready; then
    cp "$desired" "$ROOT/state/backend.env"
    printf '%s\n' "$hash" > "$ROOT/state/backend.hash"
    printf '%s\n' "$after" > "$ROOT/state/schema"
    echo "Backend and worker healthy."
  else
    c stop backend worker
    if [[ -n "$old_image" && "$before" == "$after" ]] && cmp -s "$CONFIG_DIR/postgres.env" "$ROOT/config.previous/postgres.env"; then
      export BACKEND_IMAGE="$old_image"
      cp "$ROOT/config.previous/backend.env" "$CONFIG_DIR/backend.env"
      c up -d --no-deps --wait --wait-timeout 180 backend worker
      internal_http_check http://backend:8000/health/ready
      echo "Previous backend restored; desired release remains failed." >&2
    else
      echo "Automatic rollback unavailable after schema/credential changes or on first deployment." >&2
    fi
    return 1
  fi
  unset BACKEND_IMAGE
}
deploy_frontend() {
  local desired="$RELEASE/apps/frontend/image.env" old_image hash
  if ! grep -q '^FRONTEND_IMAGE=' "$desired"; then return; fi
  hash=$(cat "$desired" "$CONFIG_DIR/frontend.env" "$RELEASE/compose.yml" | sha256sum | cut -d' ' -f1)
  if [[ -f "$ROOT/state/frontend.hash" && "$(cat "$ROOT/state/frontend.hash")" == "$hash" ]] && healthy frontend; then return; fi
  rm -f "$ROOT/state/frontend.hash"
  old_image=$(sed -n 's/^FRONTEND_IMAGE=//p' "$ROOT/state/frontend.env")
  export FRONTEND_IMAGE
  FRONTEND_IMAGE=$(sed -n 's/^FRONTEND_IMAGE=//p' "$desired")
  c pull frontend
  if c up -d --no-deps --wait --wait-timeout 180 frontend \
    && internal_http_check http://frontend:3000/healthz \
    && internal_http_check http://frontend:3000/; then
    cp "$desired" "$ROOT/state/frontend.env"
    printf '%s\n' "$hash" > "$ROOT/state/frontend.hash"
    echo "Frontend healthy."
  else
    if [[ -n "$old_image" ]]; then
      export FRONTEND_IMAGE="$old_image"
      cp "$ROOT/config.previous/frontend.env" "$CONFIG_DIR/frontend.env"
      c up -d --no-deps --wait --wait-timeout 180 frontend
      internal_http_check http://frontend:3000/healthz
      echo "Previous frontend restored; desired release remains failed." >&2
    else
      c stop frontend
    fi
    return 1
  fi
  unset FRONTEND_IMAGE
}
# Always reconcile both files: GitHub may coalesce pending runs from different apps.
deploy_backend
deploy_frontend
c ps
echo "Reconciled $(basename "$(readlink -f "$RELEASE")")"
