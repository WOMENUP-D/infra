#!/usr/bin/env bash
set -euo pipefail
ROOT="${1:-/opt/womanup}"
[[ "$ROOT" =~ ^/opt/[a-z0-9-]+$ ]]
[[ $EUID == 0 ]]
INCOMING=$(cd "$(dirname "$0")/.." && pwd)
[[ "$INCOMING" == /tmp/womanup.* ]]
umask 077
mkdir -p "$ROOT"
exec 9>"$ROOT/deploy.lock"
flock -w 1800 9
export WOMANUP_LOCKED=1
trap 'rm -rf -- "$INCOMING"; if [[ -n "${DOCKER_CONFIG:-}" ]]; then rm -rf -- "$DOCKER_CONFIG"; fi' EXIT
[[ -d "$ROOT/repository.git" ]] || git init --bare "$ROOT/repository.git"
git -C "$ROOT/repository.git" fetch "$INCOMING/infra.bundle" main
sha=$(git -C "$ROOT/repository.git" rev-parse FETCH_HEAD)
if git -C "$ROOT/repository.git" show-ref --verify --quiet refs/heads/main; then
  current=$(git -C "$ROOT/repository.git" rev-parse refs/heads/main)
  if [[ "$sha" != "$current" ]] && git -C "$ROOT/repository.git" merge-base --is-ancestor "$sha" "$current"; then
    echo "Skipping an obsolete queued deployment."
    exit 0
  fi
  git -C "$ROOT/repository.git" merge-base --is-ancestor "$current" "$sha" || {
    echo "Infra history diverged; refusing rollback by stale checkout." >&2; exit 1;
  }
fi
export RELEASE="$ROOT/releases/$sha"
mkdir -p "$RELEASE" "$ROOT/config" "$ROOT/config.previous" "$ROOT/state"
git -C "$ROOT/repository.git" archive "$sha" | tar -x -C "$RELEASE"
python3 "$RELEASE/scripts/validate_images.py" "$RELEASE"
cp -a "$ROOT/config/." "$ROOT/config.previous/"
cp "$INCOMING/config/"*.env "$ROOT/config/"
chmod 600 "$ROOT/config/"*.env
export DOCKER_CONFIG
DOCKER_CONFIG=$(mktemp -d "$ROOT/registry.XXXXXX")
username=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["username"])' "$INCOMING/registry.json")
python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["password"])' "$INCOMING/registry.json" | docker login ghcr.io --username "$username" --password-stdin
git -C "$ROOT/repository.git" update-ref refs/heads/main "$sha"
ln -sfn "$RELEASE" "$ROOT/current"
bash "$RELEASE/scripts/deploy.sh" "$ROOT"
