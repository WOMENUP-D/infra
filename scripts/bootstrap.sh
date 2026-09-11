#!/usr/bin/env bash
set -euo pipefail
ROOT="${1:-/opt/womanup}"
SSH_PORT="${2:-22}"
[[ "$ROOT" =~ ^/opt/[a-z0-9-]+$ ]]
[[ "$SSH_PORT" =~ ^[0-9]{1,5}$ ]] && (( SSH_PORT > 0 && SSH_PORT < 65536 ))
[[ $EUID == 0 ]] || { echo "Bootstrap requires sudo" >&2; exit 1; }
source /etc/os-release
[[ "$ID" == ubuntu && "$VERSION_ID" == 24.04 && "$(dpkg --print-architecture)" == amd64 ]] || {
  echo "Supported baseline: Ubuntu 24.04 amd64" >&2; exit 1;
}
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
printf '%s\n' 'deb [arch=amd64 signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu noble stable' > /etc/apt/sources.list.d/docker.list
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl enable --now docker
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
install -d -m 0700 "$ROOT/config" "$ROOT/releases" "$ROOT/state" "$ROOT/backups"
cat > /etc/systemd/system/womanup-backup.service <<EOF
[Unit]
Description=WomanUP PostgreSQL backup
After=docker.service
ConditionPathExists=$ROOT/current/scripts/backup.sh
[Service]
Type=oneshot
ExecStart=/usr/bin/bash $ROOT/current/scripts/backup.sh $ROOT daily
UMask=0077
EOF
cat > /etc/systemd/system/womanup-backup.timer <<'EOF'
[Unit]
Description=Daily WomanUP backup
[Timer]
OnCalendar=*-*-* 03:15:00 UTC
Persistent=true
RandomizedDelaySec=600
[Install]
WantedBy=timers.target
EOF
systemctl daemon-reload
systemctl enable --now womanup-backup.timer
echo "Bootstrap complete; existing volumes and application data were preserved."
