#!/usr/bin/env bash
(
set -euo pipefail
psql -v ON_ERROR_STOP=1 --username postgres --dbname womanup <<'SQL'
\getenv password POSTGRES_PASSWORD
ALTER ROLE postgres PASSWORD :'password';
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
SQL
)
