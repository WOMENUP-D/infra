# Enable pgvector on the existing shared PostgreSQL service

Verified read-only on 2026-11-06: the service uses `postgres:18.1`, PostgreSQL 18.1,
Debian 13, and volume `infrastructure-postgres_postgres_data` mounted at
`/var/lib/postgresql`. `vector` is unavailable; the other two extensions are
available but not installed in `womanup_db`.

These are manual operator instructions, not commands executed by this migration.
Steps 1–3 prepare an image without restarting production. Step 4 interrupts every
application using shared PostgreSQL and requires a coordinated maintenance window,
verified recoverable shared-host backups, and separate approval. No second database
instance is created. The same service name, settings, secrets, network and data volume
are retained; Docker replaces the service container when its image changes.

## 1. Connect and preserve the current configuration/image

From PowerShell:

```powershell
ssh -i "C:\Users\vbaho\.ssh\hetzner_ax41_deploy_ed25519" deploy@65.108.142.153
```

The remaining commands run in the server shell:

```bash
cd /srv/infrastructure/postgres
sudo cp -a compose.yaml compose.yaml.before-pgvector
base_image=$(docker inspect --format '{{.Image}}' infrastructure-postgres-postgres-1)
docker tag "$base_image" infrastructure-postgres-base:18.1-current
mkdir -p "$HOME/womanup-pgvector-build"
cd "$HOME/womanup-pgvector-build"
```

## 2. Build an extension-capable image from the exact running image

```bash
cat > Dockerfile <<'DOCKERFILE'
FROM infrastructure-postgres-base:18.1-current
RUN set -eux; \
    before="$(postgres --version)"; \
    apt-mark hold postgresql-18 postgresql-client-18; \
    apt-get update; \
    apt-get install -y --no-install-recommends postgresql-18-pgvector; \
    test "$(postgres --version)" = "$before"; \
    test -f /usr/share/postgresql/18/extension/vector.control; \
    rm -rf /var/lib/apt/lists/*
DOCKERFILE
docker build --pull=false -t infrastructure-postgres-pgvector:18.1-womanup .
```

This installs the PG18 extension package inside the image, not on the host or in
the running container. If package resolution fails, stop and review the build;
do not remove the PostgreSQL package holds or change major versions.

## 3. Check the image without mounting production data

```bash
docker run --rm --network none --entrypoint sh \
  infrastructure-postgres-pgvector:18.1-womanup -ec \
  'postgres --version; test -f /usr/share/postgresql/18/extension/vector.control; test -f /usr/lib/postgresql/18/lib/vector.so'
```

This only checks image files; it does not launch PostgreSQL. Review/scan the image
and confirm recoverable shared backups before the maintenance step.

## 4. Approved maintenance only: change the existing service image

```bash
cd /srv/infrastructure/postgres
sudoedit compose.yaml
```

Replace only `image: postgres:18.1` with:

```yaml
image: infrastructure-postgres-pgvector:18.1-womanup
```

Leave all other lines unchanged, especially `postgres_data:/var/lib/postgresql`.
Then, only during the approved maintenance window:

```bash
docker compose config --quiet
docker compose up -d --no-deps --no-build --force-recreate postgres
for attempt in $(seq 1 60); do
  if docker exec infrastructure-postgres-postgres-1 pg_isready -U postgres; then break; fi
  sleep 2
done
docker inspect --format '{{.State.Health.Status}}' infrastructure-postgres-postgres-1
docker inspect --format '{{range .Mounts}}{{if eq .Destination "/var/lib/postgresql"}}{{.Name}}{{end}}{{end}}' infrastructure-postgres-postgres-1
```

Require health `healthy` and volume name `infrastructure-postgres_postgres_data`.
Do not use `docker compose down`, `down -v`, volume removal, or a new Compose project.
Verify all existing applications reconnect. Record the custom image/config in the
shared infrastructure owner's source repository so later maintenance preserves it.

## 5. Enable extensions only in WomanUP's database

Once shared PostgreSQL is healthy and this database change is approved:

```bash
docker exec -i infrastructure-postgres-postgres-1 \
  psql -X -U postgres -d womanup_db -v ON_ERROR_STOP=1 <<'SQL'
BEGIN;
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
COMMIT;
SELECT current_database(), extname, extversion
FROM pg_extension
WHERE extname IN ('vector', 'pg_trgm', 'uuid-ossp')
ORDER BY extname;
SQL
```

Every returned database name must be `womanup_db`; expect three extensions. These
commands use the existing administrator's local container connection and do not
need its password in GitHub. Keep `womanup_user` unprivileged; do not change its
role flags. Then run the WomanUP application preflight during the separately
approved deployment. This procedure does not run app migrations or deploy it.

If the replacement fails before enabling extensions, restore only the original
image line and rerun the same service-specific `up` command with the same volume.
After extensions are enabled/used, retain an extension-capable image; reverting
blindly to the image without its library will break vector operations. Never drop
extensions with CASCADE as a rollback shortcut.

Package and per-database activation reference:
https://github.com/pgvector/pgvector#installation

## Applied on 2026-11-06

Completed against the existing shared service under the user's setup approval:

- Built `infrastructure-postgres-pgvector:18.1-womanup` from the exact existing
  PostgreSQL image; installed pgvector package 0.8.7-1.pgdg13+1 without upgrading
  PostgreSQL. The PostgreSQL binary SHA-256 was identical before and after.
- Saved the original Compose configuration and a verified WomanUP database dump
  under `/srv/infrastructure/postgres/maintenance/womanup-pgvector/`.
- Stored the build definition at `/srv/infrastructure/postgres/Dockerfile.pgvector`
  and changed only the shared service's image line. No host APT/Docker/network
  configuration was changed.
- Recreated only the shared PostgreSQL service, preserving
  `infrastructure-postgres_postgres_data` at `/var/lib/postgresql`.
- Enabled vector 0.8.7, pg_trgm 1.6 and uuid-ossp 1.1 only in `womanup_db`.
  A vector-distance query returned the expected value. The project role remains
  unprivileged, and live application-password and network preflights pass.
- Shared PostgreSQL and existing AgroZanjir/YouthCapital app containers are healthy.

A retry of the user's manually approved deployment stopped before schema changes
because Alembic did not escape percent signs in encoded passwords. The fix and a
regression test were pushed to backend main (`7ef4cf0`). Further migrations and
domain cutover are held pending transfer of existing production data, as requested.
The old server SSH connection details are still needed.

GitHub prod now explicitly sets INGRESS_NETWORK=agrozanjir_web and VPS_SSH_PORT=22.
Existing database and registry credentials were retained.
