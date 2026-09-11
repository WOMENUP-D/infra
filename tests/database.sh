#!/usr/bin/env bash
set -euo pipefail
name="womanup-db-test-${GITHUB_RUN_ID:-$$}"
temp=$(mktemp -d)
trap 'docker rm -f "$name" >/dev/null 2>&1 || true; rm -rf -- "$temp"' EXIT
python3 - "$temp/database.env" <<'PY'
from pathlib import Path
import secrets, sys
Path(sys.argv[1]).write_text(
    "POSTGRES_DB=womanup\nPOSTGRES_USER=postgres\nPOSTGRES_PASSWORD="
    + secrets.token_hex(32) + "\n"
)
PY
docker run -d --name "$name" --env-file "$temp/database.env" \
  -v "$PWD/platform/database.sh:/docker-entrypoint-initdb.d/10-roles.sh:ro" \
  pgvector/pgvector:pg16@sha256:ccc6e83d6e35e931dc7c5def2022729d5a6c370318d099181995567ff1fb4d6b
for _ in {1..60}; do
  if docker exec "$name" pg_isready -U postgres -d womanup; then break; fi
  sleep 2
done
# Repeated initialization must be harmless and preserve the database.
docker exec "$name" bash /docker-entrypoint-initdb.d/10-roles.sh
test "$(docker exec "$name" psql -U postgres -d womanup -Atc "SELECT count(*) FROM pg_extension WHERE extname IN ('vector','pg_trgm','uuid-ossp')")" = 3
docker exec "$name" psql -v ON_ERROR_STOP=1 -U postgres -d womanup -c 'CREATE TABLE deployment_test (id integer PRIMARY KEY)'
echo "Database initialization with one PostgreSQL role passed."
