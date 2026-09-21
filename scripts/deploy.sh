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

restore_backend() {
  # Put the last release that was known to work back in service, with the
  # configuration it worked with. Only sound while the schema is unchanged,
  # which every caller checks first.
  local old_image="$1"
  [[ -n "$old_image" ]] || { echo "No previous backend image recorded." >&2; return 1; }
  cmp -s "$CONFIG_DIR/postgres.env" "$ROOT/config.previous/postgres.env" || {
    echo "Database credentials changed; not restoring the previous release." >&2
    return 1
  }
  export BACKEND_IMAGE="$old_image"
  [[ -f "$ROOT/config.previous/backend.env" ]] && cp "$ROOT/config.previous/backend.env" "$CONFIG_DIR/backend.env"
  c up -d --no-deps --wait --wait-timeout 180 backend worker \
    && internal_http_check http://backend:8000/health/ready \
    && echo "Previous backend restored; desired release remains failed." >&2
}

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
  # Ask before breaking anything: the incoming image reads the rendered
  # configuration it would run with, and the migration's own settings, while
  # the current release keeps serving. A release that cannot start is refused
  # here, where refusing costs nothing.
  if ! c run --rm --no-deps -T migrate python - < "$RELEASE/scripts/preflight.py"; then
    echo "Preflight failed; the running release was left untouched." >&2
    return 1
  fi
  # Then keep a copy of what the migration is about to change. Still nothing
  # has been stopped, so a backup that cannot be taken costs nothing either.
  if ! bash "$RELEASE/scripts/backup.sh" "$ROOT" pre-migration; then
    echo "No pre-migration backup could be taken; the running release was left untouched." >&2
    return 1
  fi
  before=$(revision)
  c stop backend worker
  if ! c run --rm --no-deps migrate; then
    after=$(revision)
    if [[ "$before" == "$after" ]]; then
      echo "Migration failed without changing the schema; restoring the running release." >&2
      restore_backend "$old_image" || echo "Could not restore the previous release." >&2
    else
      echo "Migration failed after changing the schema; apps remain stopped." >&2
      echo "Restore the pre-migration backup under $ROOT/backups with scripts/restore.sh, or finish the migration by hand." >&2
    fi
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
    if [[ "$before" == "$after" ]]; then
      restore_backend "$old_image" || echo "Automatic rollback unavailable." >&2
    else
      echo "Automatic rollback unavailable after a schema change." >&2
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
# Both apps are up on this configuration, so it becomes the one to fall back
# to. Keeping this until the end is the point: a deploy that fails must leave
# the last configuration that worked untouched, not overwrite it with the one
# that just failed.
cp -a "$CONFIG_DIR/." "$ROOT/config.previous/"
c ps
echo "Reconciled $(basename "$(readlink -f "$RELEASE")")"
