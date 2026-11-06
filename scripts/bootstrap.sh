#!/usr/bin/env bash
set -euo pipefail
umask 077
ROOT="${1:-/opt/womanup}"
[[ "$ROOT" == /opt/womanup ]]
[[ $EUID == 0 ]] || { echo "Bootstrap requires sudo" >&2; exit 1; }
# Host software, accounts, Docker, APT, firewall, SSH and shared databases are
# operator-owned prerequisites. Do not install or reconfigure them.
for command in docker python3 git flock; do
  command -v "$command" >/dev/null || { echo "Missing prerequisite: $command" >&2; exit 1; }
done
docker info >/dev/null
docker compose version
[[ ! -L "$ROOT" ]] || { echo "Deployment root cannot be a symlink" >&2; exit 1; }
install -d -m 0700 "$ROOT"
exec 9>"$ROOT/deploy.lock"
flock -w 1800 9
install -d -m 0700 "$ROOT/config" "$ROOT/config.previous" "$ROOT/releases" "$ROOT/state" \
  "$ROOT/backups" "$ROOT/data" "$ROOT/data/media"
# WomanUP has no local-media writer today; reserve private project storage.
# Only project-owned maintenance units are installed. Existing shared units and
# all application services remain untouched. No backup runs before configuration.
command -v systemctl >/dev/null || { echo "systemd is required for the backup timer" >&2; exit 1; }
cat > /etc/systemd/system/womanup-backup.service <<UNIT
[Unit]
Description=WomanUP database and local media snapshot
After=docker.service
ConditionPathExists=$ROOT/current/scripts/backup.sh
ConditionPathExists=$ROOT/config/database.env
[Service]
Type=oneshot
User=root
UMask=0077
ExecStart=/usr/bin/bash $ROOT/current/scripts/backup.sh $ROOT
UNIT
cat > /etc/systemd/system/womanup-backup.timer <<'UNIT'
[Unit]
Description=Daily WomanUP project snapshot
[Timer]
OnCalendar=*-*-* 03:45:00 Asia/Tashkent
Persistent=true
[Install]
WantedBy=timers.target
UNIT
chmod 0644 /etc/systemd/system/womanup-backup.service /etc/systemd/system/womanup-backup.timer
systemctl daemon-reload
systemctl enable --now womanup-backup.timer
echo "WomanUP storage and project backup timer prepared. No application services started."
