#!/usr/bin/env bash
(
set -euo pipefail
psql -v ON_ERROR_STOP=1 --username postgres --dbname womanup <<'SQL'
\getenv admin_password POSTGRES_PASSWORD
\getenv migration_password MIGRATION_DB_PASSWORD
\getenv app_password APP_DB_PASSWORD
SELECT 'CREATE ROLE womanup_migrator LOGIN' WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname='womanup_migrator') \gexec
SELECT 'CREATE ROLE womanup_app LOGIN' WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname='womanup_app') \gexec
ALTER ROLE postgres PASSWORD :'admin_password';
ALTER ROLE womanup_migrator PASSWORD :'migration_password' NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
ALTER ROLE womanup_app PASSWORD :'app_password' NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT CONNECT ON DATABASE womanup TO womanup_migrator, womanup_app;
ALTER SCHEMA public OWNER TO womanup_migrator;
GRANT USAGE ON SCHEMA public TO womanup_app;
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
ALTER DEFAULT PRIVILEGES FOR ROLE womanup_migrator IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO womanup_app;
ALTER DEFAULT PRIVILEGES FOR ROLE womanup_migrator IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO womanup_app;
SQL
)
