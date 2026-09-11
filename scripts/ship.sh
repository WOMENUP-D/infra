#!/usr/bin/env bash
set -euo pipefail
umask 077
: "${VPS_HOST:?}" "${VPS_USERNAME:?}" "${VPS_SSH_KEY:?}" "${VPS_KNOWN_HOSTS:?}"
: "${GHCR_USERNAME:?}" "${GHCR_READ_TOKEN:?}"
ROOT="${DEPLOY_ROOT:?}"
PORT="${VPS_SSH_PORT:?}"
MODE="${1:-deploy}"
[[ "$ROOT" =~ ^/opt/[a-z0-9-]+$ ]]
[[ "$PORT" =~ ^[0-9]{1,5}$ ]] && (( PORT > 0 && PORT < 65536 ))
[[ "$VPS_HOST" =~ ^[a-zA-Z0-9][a-zA-Z0-9.-]*$ ]]
[[ "$VPS_USERNAME" =~ ^[a-z_][a-z0-9_-]*$ ]]
[[ "$MODE" == deploy || "$MODE" == bootstrap ]]
temp=$(mktemp -d)
trap 'rm -rf -- "$temp" .runtime' EXIT
printf '%s\n' "$VPS_SSH_KEY" > "$temp/key"
printf '%s\n' "$VPS_KNOWN_HOSTS" > "$temp/known_hosts"
ssh_args=(-i "$temp/key" -o BatchMode=yes -o StrictHostKeyChecking=yes -o "UserKnownHostsFile=$temp/known_hosts" -o ConnectTimeout=15 -o ServerAliveInterval=30)
target="$VPS_USERNAME@$VPS_HOST"
python3 scripts/render_config.py .runtime/config
if [[ "$MODE" == bootstrap ]]; then
  ssh "${ssh_args[@]}" -p "$PORT" "$target" "sudo -n bash -s -- '$ROOT' '$PORT'" < scripts/bootstrap.sh
fi
python3 - <<'PY'
import json, os
from pathlib import Path
path = Path(".runtime/registry.json")
path.write_text(json.dumps({"username": os.environ["GHCR_USERNAME"], "password": os.environ["GHCR_READ_TOKEN"]}))
path.chmod(0o600)
PY
git bundle create .runtime/infra.bundle main
tar -czf "$temp/payload.tgz" -C .runtime config registry.json infra.bundle -C "$GITHUB_WORKSPACE" scripts/receive.sh
incoming=$(ssh "${ssh_args[@]}" -p "$PORT" "$target" 'mktemp -d /tmp/womanup.XXXXXXXXXX')
[[ "$incoming" =~ ^/tmp/womanup\.[a-zA-Z0-9]+$ ]]
scp "${ssh_args[@]}" -P "$PORT" "$temp/payload.tgz" "$target:$incoming/payload.tgz"
ssh "${ssh_args[@]}" -p "$PORT" "$target" \
  "tar -xzf '$incoming/payload.tgz' -C '$incoming' && sudo -n bash '$incoming/scripts/receive.sh' '$ROOT'"
