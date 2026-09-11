#!/usr/bin/env bash
set -euo pipefail
name="womanup-db-test-${GITHUB_RUN_ID:-$$}"
temp=$(mktemp -d)
trap 'docker rm -f "$name" >/dev/null 2>&1 || true; rm -rf -- "$temp"' EXIT
python3 - "$temp/database.env" <<'PY'
from pathlib import Path
import secrets, sys
Path(sys.argv[1]).write_text("POSTGRES_DB=womanup\n" + "".join(
    key + "=" + secrets.token_hex(32) + "\n"
    for key in ("POSTGRES_PASSWORD", "MIGRATION_DB_PASSWORD", "APP_DB_PASSWORD")
))
PY
docker run -d --name "$name" --env-file "$temp/database.env" \
  -v "$PWD/platform/database.sh:/docker-entrypoint-initdb.d/10-roles.sh:ro" \
  pgvector/pgvector:pg16@sha256:ccc6e83d6e35e931dc7c5def2022729d5a6c370318d099181995567ff1fb4d6b
for _ in {1..60}; do
  if docker exec "$name" pg_isready -U postgres -d womanup; then break; fi
  sleep 2
done
# Repeated initialization must preserve data and role boundaries.
docker exec "$name" bash /docker-entrypoint-initdb.d/10-roles.sh
docker exec -i "$name" psql -v ON_ERROR_STOP=1 -U womanup_migrator -d womanup <<'SQL'
CREATE TABLE audit_logs (id integer PRIMARY KEY);
INSERT INTO audit_logs VALUES (1);
REVOKE UPDATE, DELETE, TRUNCATE ON audit_logs FROM womanup_app;
SQL
test "$(docker exec "$name" psql -U womanup_app -d womanup -Atc 'SELECT count(*) FROM audit_logs')" = 1
if docker exec "$name" psql -v ON_ERROR_STOP=1 -U womanup_app -d womanup -c 'DELETE FROM audit_logs'; then
  echo "Application role unexpectedly deleted audit records" >&2
  exit 1
fi
docker exec "$name" pg_dump -U postgres -d womanup -Fc > "$temp/backup.dump"
docker exec "$name" createdb -U postgres -T template0 restore_test
docker exec -i "$name" pg_restore -U postgres -d restore_test --exit-on-error --single-transaction < "$temp/backup.dump"
test "$(docker exec "$name" psql -U womanup_app -d restore_test -Atc 'SELECT count(*) FROM audit_logs')" = 1
test "$(docker exec "$name" psql -U postgres -d restore_test -Atc "SELECT tableowner FROM pg_tables WHERE tablename='audit_logs'")" = womanup_migrator
echo "Database initialization, role isolation, backup and restore passed."
