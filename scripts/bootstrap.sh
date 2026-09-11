#!/usr/bin/env bash
set -euo pipefail
ROOT="${1:-/opt/womanup}"
SSH_PORT="${2:-22}"
[[ "$ROOT" =~ ^/opt/[a-z0-9-]+$ ]]
[[ "$SSH_PORT" =~ ^[0-9]{1,5}$ ]] && (( SSH_PORT > 0 && SSH_PORT < 65536 ))
[[ $EUID == 0 ]] || { echo "Bootstrap requires sudo" >&2; exit 1; }
source /etc/os-release
architecture=$(dpkg --print-architecture)
install -d -m 0700 "$ROOT"
exec 9>"$ROOT/deploy.lock"
flock -w 1800 9
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y ca-certificates curl gnupg git python3 ufw
install -m 0755 -d /etc/apt/keyrings
if [[ ! -f /etc/apt/keyrings/docker.asc ]]; then
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  fingerprint=$(gpg --show-keys --with-colons /etc/apt/keyrings/docker.asc | awk -F: '$1=="fpr" {print $10; exit}')
  [[ "$fingerprint" == 9DC858229FC7DD38854AE2D88D81803C0EBFCD88 ]]
  chmod a+r /etc/apt/keyrings/docker.asc
fi
printf 'deb [arch=%s signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu %s stable\n' \
  "$architecture" "$VERSION_CODENAME" > /etc/apt/sources.list.d/docker.list
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl enable --now docker
# Remove backup units installed by older WomanUP bootstrap releases.
systemctl disable --now womanup-backup.timer womanup-backup.service 2>/dev/null || true
rm -f /etc/systemd/system/womanup-backup.timer /etc/systemd/system/womanup-backup.service
systemctl daemon-reload
# Preserve existing daemon settings; bound logs for newly created containers.
python3 - <<'PY'
import json
from pathlib import Path
path = Path("/etc/docker/daemon.json")
config = json.loads(path.read_text()) if path.exists() else {}
config.setdefault("log-driver", "local")
config.setdefault("log-opts", {"max-size": "10m", "max-file": "3"})
path.write_text(json.dumps(config, indent=2) + "\n")
PY
docker compose version
ufw allow "$SSH_PORT/tcp"
ufw allow 80/tcp
ufw allow 443/tcp
ufw default deny incoming
ufw default allow outgoing
ufw --force enable
install -d -m 0700 "$ROOT/config" "$ROOT/releases" "$ROOT/state"
echo "Bootstrap complete; existing volumes and application data were preserved."
