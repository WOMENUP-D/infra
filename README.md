# WomanUP Production Infrastructure

Production is owned by this repository. Application workflows publish images and
commit only their image metadata here; they never receive VPS credentials.

## Release flow

1. A push to an application's main branch runs Semgrep SAST, Gitleaks, dependency
   scanning, and application tests.
2. A successful build publishes a candidate image with SBOM and provenance.
   Trivy scans the exact digest before its permanent version tag is assigned.
3. The application commits apps/backend/image.env or apps/frontend/image.env here.
4. The corresponding deploy workflow enters the GitHub environment **prod**,
   checks current main, transfers its Git bundle and runtime configuration over
   verified SSH, and reconciles Docker Compose on the server.

Version tags are backend-<full-git-sha> and frontend-<full-git-sha>. CI reuses
existing versions; production uses the sha256 digest, never latest. GHCR itself
does not enforce write-once tags: restrict package writers and retain released
digests. Changing a tag cannot change an already committed production digest.

Both deploy workflows share a production concurrency group and a server lock.
Each reconciles both desired files but only updates services whose image,
configuration, or health changed. This prevents a coalesced queued workflow from
losing the other application's release. Older Git snapshots are rejected on the
server. Do not force-push infra main.

## GitHub configuration

Create **Settings > Environments > prod** in **WOMENUP-D/infra**. Restrict deployment
branches to main. These are environment secrets and variables, not files in Git
and not application repository settings. Reviewers are optional if fully automatic
deployment is desired.

### prod environment secrets

| Name | Value |
| --- | --- |
| VPS_HOST | VPS IPv4 address or SSH DNS hostname |
| VPS_USERNAME | Existing SSH user with noninteractive sudo, or root |
| VPS_SSH_KEY | Dedicated deployment private key, multiline OpenSSH/PEM |
| VPS_KNOWN_HOSTS | Verified OpenSSH known_hosts entry for this server |
| GHCR_READ_TOKEN | Classic PAT with read:packages, authorized for both private images |
| DB_USER | `womanup_user`, the existing project role (store as a secret) |
| POSTGRES_PASSWORD | Existing `womanup_user` password, used only for application access; never the PostgreSQL administrator password |
| JWT_SECRET_KEY | JWT signing key, at least 48 characters |

Optional named secrets are `FIREBASE_PRIVATE_KEY`, `ANTHROPIC_API_KEY`,
`SMS_PROVIDER_TOKEN`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`,
`SMTP_FROM`, `EDU_JOB_CLIENT_SECRET`,
`INVEST_HUB_CLIENT_SECRET`, `COMMERCE_CLIENT_SECRET`, `S3_ACCESS_KEY`, and
`S3_SECRET_KEY`. Create only those used by the application.

Reuse the provisioned application password; this deployment never creates roles or rotates passwords.
The established `POSTGRES_PASSWORD` secret name is retained, but its meaning is
strictly the **application role's password**. Any nonempty single-line password is
supported; DSN reserved characters are percent-encoded. Do not paste it into logs,
shell commands, Git files, issues, or chat. Set it through GitHub's secret input.
Generate the JWT key with openssl rand -hex 48. Store a Firebase private key with
literal `\n` separators. Never put backend secrets in frontend variables.

Verify the SSH host key through the VPS console/provider before recording it.
For a nondefault SSH port the known_hosts hostname is [host]:port. The workflow
does not trust an unverified ssh-keyscan result or disable host verification.

### prod environment variables

| Name | Value / purpose |
| --- | --- |
| APP_DOMAIN | `womanup.uz`; bare hostname, no scheme or path |
| DEPLOY_ROOT | `/opt/womanup`; isolated project storage, enforced by scripts |
| DB_HOST | `postgres` |
| DB_PORT | `5432` |
| DB_NAME | `womanup_db` |
| DB_NETWORK | `infrastructure_database`, existing external Docker network |
| INGRESS_NETWORK | `agrozanjir_web`, existing public Caddy network |
| VPS_SSH_PORT | `22`, or the configured SSH port |
| GHCR_USERNAME | GitHub user owning GHCR_READ_TOKEN |
| FIREBASE_WEB_API_KEY | Optional public Firebase web configuration |
| FIREBASE_WEB_AUTH_DOMAIN | Optional public Firebase web configuration |
| FIREBASE_WEB_PROJECT_ID | Optional public Firebase web configuration |
| FIREBASE_WEB_APP_ID | Optional public Firebase web configuration |
| FIREBASE_WEB_STORAGE_BUCKET | Optional public Firebase web configuration |
| FIREBASE_WEB_SENDER_ID | Optional public Firebase web configuration |

Optional backend variables use their exact application names, including
the following. Unset optional entries use backend defaults.

```text
DB_POOL_SIZE DB_MAX_OVERFLOW
ACCESS_TOKEN_TTL_MINUTES REFRESH_TOKEN_TTL_DAYS
OTP_LENGTH OTP_TTL_SECONDS OTP_MAX_ATTEMPTS OTP_RESEND_COOLDOWN_SECONDS
FIREBASE_PROJECT_ID FIREBASE_CLIENT_EMAIL FIREBASE_ALLOWED_DOMAIN
DEFAULT_LANGUAGE
AI_MODEL AI_EFFORT AI_MAX_TOKENS ASSISTANT_GUEST_QUESTIONS
AI_RAG_TOP_K AI_MIN_CONFIDENCE EMBEDDING_DIMENSIONS
NEWS_INGEST_ENABLED NEWS_INGEST_INTERVAL_HOURS NEWS_INGEST_MAX_POSTS
NEWS_INGEST_LOOKBACK_HOURS NEWS_INGEST_DEDUP_DAYS
NEWS_INGEST_AUTO_PUBLISH NEWS_INGEST_ALLOWED_DOMAINS
SMS_PROVIDER_URL
EDU_JOB_BASE_URL EDU_JOB_CLIENT_ID
INVEST_HUB_BASE_URL INVEST_HUB_CLIENT_ID
COMMERCE_BASE_URL COMMERCE_CLIENT_ID
INTEGRATION_TIMEOUT_SECONDS INTEGRATION_MAX_RETRIES
S3_ENDPOINT_URL S3_BUCKET RATE_LIMIT_PER_MINUTE
```

Production mode, debug mode and same-origin CORS are enforced by the renderer.
The renderer reads DB_HOST, DB_PORT, DB_NAME and DB_USER, produces the backend's
existing DATABASE_URL, and gives the same configuration to API, worker and Alembic.
The verified project database/role names are validated to prevent tenant mistakes.

Firebase web values are returned by the frontend's allowlisted /public-config
endpoint at runtime. They are public by design. No frontend rebuild or infra-to-app
dispatch is needed to change them. After editing prod variables/secrets, manually
run deploy-platform; GitHub environment edits do not emit a Git push event.

### Application repositories

Each app needs just one manually configured repository secret:
INFRA_PUSH_TOKEN, a fine-grained PAT selected for WOMENUP-D/infra with Contents:
read and write. Approve it for the organization if required. It needs no workflow
write permission and no server or production-environment access. GITHUB_TOKEN
publishes that app's GHCR image.

Allow the automation identity to push image metadata directly to infra main.
A PAT cannot restrict writes to individual paths. Protect deployment code
(.github/**, scripts/**, platform/**, compose.yml) with an organization/repository
push ruleset that the automation identity cannot bypass, where supported.
Without that control, holders of the PAT are trusted infra code writers despite
the promotion script only staging an image file. Require review for human changes
to deployment code. Configure package access so GHCR_READ_TOKEN can read both
application packages; organization PAT/SSO policy may require authorization.

## Dedicated server migration: verified 2026-10-26 (Asia/Tashkent)

Read-only inspection of `deploy@65.108.142.153` confirmed:

- Shared PostgreSQL is `infrastructure-postgres-postgres-1`, PostgreSQL 18.1,
  attached to `infrastructure_database`, with no published database port.
- `womanup_db` exists, is owned by login role `womanup_user`, and has zero public
  application tables. The role has no superuser, create-role, create-database,
  replication or bypass-RLS privileges and can create objects in its public schema.
- **Blocking prerequisite:** only `plpgsql` is installed. `pg_trgm` and `uuid-ossp`
  are available, but **vector is not available in the shared server image**.
  The infrastructure owner must provide pgvector compatible with PostgreSQL 18
  and preinstall all three extensions in **womanup_db only**. This repository
  never modifies the shared image, starts PostgreSQL, installs extensions, or
  uses administrator credentials. Do not upgrade/change another project's schema.
  Changing the shared image may require a separate, approved host maintenance plan.
- AgroZanjir's Caddy owns TCP 80/443 and UDP 443. Its network is `agrozanjir_web`.
  No `/opt/womanup`, `womanup` Compose project, or `womanup-proxy` alias was present.
  Existing database, application and certificate volumes must be preserved.
- `womanup.uz` resolves to Cloudflare proxy addresses and currently serves HTTP 200
  over HTTPS. Its current origin is not established by public DNS; **do not assume
  the new empty database contains existing production data**. Direct TLS to
  65.108.142.153 with SNI `womanup.uz` fails; the new ingress has no WomanUP route
  or certificate. Cloudflare's actual encryption mode and origin DNS content must
  be verified by the zone owner; these cannot be determined from public responses.
- GitHub CLI environment reads returned HTTP 401. No GitHub setting was changed,
  and the existing application password was neither retrieved nor tested.

No AGENTS.md files were found in the workspace repositories or inspected parent
directories. AgroZanjir's infra was read as a reference; its files were not changed.

## Networking and TLS

Compose project `womanup` publishes **no host ports** and creates only its own
`womanup_edge` and `womanup_outbound` networks. Backend, worker and migrations join
the existing external database network. Only WomanUP's internal Caddy joins the
existing ingress network, using unique upstream alias `womanup-proxy` on port 8080.
The internal proxy addresses unique private aliases `womanup-api` and `womanup-web`
to avoid resolving AgroZanjir's identically named backend/frontend services on ingress.
Project Caddy data/config volumes retain their established names; no existing volume
is deleted or pruned, and shared ingress retains ownership of TLS certificates.

The existing WomanUP Caddy path routing and security headers are retained. TLS
termination moves to the existing public Caddy because binding 80/443 twice is
impossible. There is no Redis service or active Redis client in this project's
deployment; none is added, and AgroZanjir's Redis is untouched.

`platform/ingress.caddy` is a prepared site block for **the ingress owner to review
and add to its source-controlled Caddyfile**. WomanUP does not automatically edit,
mount or reload another project's Caddyfile. Without that one-time ingress change,
the application is not publicly reachable. The owner must retain the block in
future AgroZanjir deployments. Validate the combined configuration, then perform
an approved graceful reload of that Caddy; do not restart it or duplicate the ports.

Cloudflare Full (strict) requires an unexpired certificate matching `womanup.uz`
from a trusted CA or Cloudflare Origin CA:
[Cloudflare requirements](https://developers.cloudflare.com/ssl/origin-configuration/ssl-modes/full-strict/).
The prepared block disables TLS-ALPN challenges because Cloudflare terminates
public TLS. It uses HTTP-01 instead:
[Caddy ACME options](https://caddyserver.com/docs/caddyfile/directives/tls).
Stock Caddy on this host has no Cloudflare DNS provider module.

For issuance while retaining Cloudflare proxying and Full (strict), the zone owner
can create a temporary **path-scoped origin rule** for
`http://womanup.uz/.well-known/acme-challenge/*`, overriding DNS to a temporary
DNS-only hostname in the same Cloudflare account with A `65.108.142.153`, on port
80. Keep the request Host `womanup.uz`. DNS overrides currently require Enterprise;
see [Origin Rules availability](https://developers.cloudflare.com/rules/origin-rules/)
and [DNS override settings](https://developers.cloudflare.com/rules/origin-rules/features/).
Ensure this path bypasses edge HTTPS redirects, caching and access/WAF challenges.
Keep normal traffic on the old origin during issuance. Do not rely on HTTPS
redirects before the new origin has a certificate: strict validation can cause 526
and prevent HTTP-01 from completing. If path-scoped origin routing is unavailable,
schedule DNS-only issuance during the approved cutover window, or obtain and
securely provision a Cloudflare Origin CA certificate through the ingress owner.
DNS-01 requires a separately reviewed Caddy build and scoped DNS token.

Check origin issuance **before** moving normal traffic:

```bash
curl --fail --resolve womanup.uz:443:65.108.142.153 https://womanup.uz/health/ready
curl --fail --resolve womanup.uz:443:65.108.142.153 https://womanup.uz/healthz
```

Do not use `-k`. If using Origin CA, use `--cacert` with the official Origin CA root
instead. Verify certificate hostname, expiry and chain, then verify the same URLs
through Cloudflare, the homepage, login and worker heartbeat. Public checks remain
operator cutover gates; they do not determine automatic image rollback.

## Exact rollout order (approval required)

1. Review the local diff and this plan. Before any push to infra main, configure
   required reviewers on `prod` (no self-review/bypass), or disable the deployment
   workflows until release approval. Pushing deployment paths automatically queues
   a deploy; application main pushes can also promote image metadata to infra main.
   Pause those promotions for the migration window. Do not push/deploy without
   the user's explicit approval. Before production rollout, resolve or explicitly
   review the remaining Caddy image vulnerabilities recorded in `VALIDATION.md`.
2. The infrastructure owner resolves the missing pgvector capability under its
   own approved host maintenance plan and installs `vector`, `pg_trgm`, `uuid-ossp`
   in `womanup_db`. Preserve the existing shared PostgreSQL container/service,
   network, roles and all volumes; no second database instance is deployed.
3. Configure the **infra prod** secrets/variables above. Use the existing role
   password; remove any old administrator password from project settings. Keep
   `POSTGRES_PASSWORD` only as the application password. Use verified SSH host keys.
4. After approval, push the infra changes (application images need no rebuild).
   Run **Server Bootstrap** in bootstrap mode. It verifies Docker prerequisites
   and creates root-only WomanUP directories and its own daily backup timer.
   It does **not** deploy, migrate, start application/database/proxy services,
   install packages, or change APT/Docker/firewall/network/SSH.
5. Identify the old production database, current Alembic version, media location
   and image digests. Take a verified off-host backup. Quiesce old WomanUP writers
   for the final dump and media copy. Restore only this project's data into the
   provisioned `womanup_db`, as `womanup_user`, without roles/ownership/DB creation.
   Do not use cluster dumps, copy raw PostgreSQL data directories across versions,
   or apply the new local snapshot wrapper to an unidentified old database.
   If this is intentionally a fresh install, obtain explicit approval to omit
   data transfer; the existing public website makes that a decision to verify.
6. Approve and dispatch **deploy-platform**. It checks external networks, proxy
   alias/project conflicts, application authentication/ownership and required
   extensions before stopping WomanUP. It pulls pinned images, runs Alembic once,
   starts API/worker/frontend and internal Caddy, and verifies internal readiness.
   This is the first migration/service-changing step; do not run it before approval.
7. The ingress owner applies the reviewed `platform/ingress.caddy` site block and
   performs an approved graceful reload. Use the issuance procedure above to obtain
   a certificate while normal traffic still targets the old origin where possible.
   Check new-origin TLS and application readiness directly.
8. Change the Cloudflare origin A record to `65.108.142.153`, keep proxying and
   Full (strict), and correct stale origin AAAA records. Remove temporary challenge
   overrides after verifying that HTTP-01 renewal still reaches the new ingress.
   Verify public endpoints, authentication and provider integrations. Keep old
   writers stopped so rollback cannot create two diverging production databases.
9. Take and verify a new project snapshot, copy it to encrypted off-host storage,
   and validate recovery against an isolated test target. Re-enable application
   promotions only after successful cutover. Retain old origin data and volumes.

If a migration fails, WomanUP API/worker remain stopped. If application health
fails with unchanged schema, database credentials and deployment network config,
the previous image/config can be restored automatically. First deploy has no
rollback image. A schema change blocks automatic code rollback; inspect compatibility
and use an approved project restore if needed. DNS rollback alone is unsafe after
new writes. No automatic schema downgrade, volume pruning or deletion runs.

## Backup, restore and maintenance

Server layout under `/opt/womanup`: `repository.git`, `releases/<infra-sha>`,
`current`, root-only `config` and `config.previous`, `state`, `backups`, `data/media`.
The renderer writes `database.env` for project maintenance with only application
credentials. PostgreSQL client tools run in the existing shared container using
that role over TCP; the password is sent through stdin and never command arguments.
Old `postgres.env`/`migration.env` files from a previous host are unused and must
not be copied to the new host. Retire obsolete secret files only after review.

Run only after production approval, as root:

```bash
sudo bash /opt/womanup/current/scripts/backup.sh /opt/womanup
# During approved recovery, stop WomanUP writers using the common Compose wrapper:
sudo bash -c 'source /opt/womanup/current/scripts/common.sh /opt/womanup; lock_server; c stop backend worker'
sudo bash /opt/womanup/current/scripts/restore.sh /opt/womanup \
  /opt/womanup/backups/<snapshot> --confirm womanup_db
```

Backups are one `pg_dump` custom archive of WomanUP's public application schema
and data, plus `data/media`, with a scope manifest and SHA-256 checksums. No role,
cluster, Redis, proxy certificate or Docker-volume backup is taken. Required
extensions are administrator-owned prerequisites and are preserved on restore.
Restore requires stopped WomanUP writers, validates scope/checksums/archive paths,
takes a safety snapshot, and applies pg_restore in one transaction as the app role.
Previous media files are renamed and retained. Other databases are never targets.
Only restore trusted archives. After restore, review schema/image compatibility,
then approve redeployment; services are not automatically started.

The application currently has no local media-upload writer or media volume.
`data/media` is reserved project storage. If external S3 is enabled, its contents
are **not** in this local snapshot: use a dedicated WomanUP bucket/prefix and
perform a separate versioned, encrypted bucket-scoped backup/restore. Do not sync,
delete, or restore a shared bucket wholesale. Freeze writers for consistent DB/media
recovery. Bootstrap installs only `womanup-backup.service` and its daily timer
(03:45 Asia/Tashkent), conditional on project configuration. The command remains
available manually. Configure encrypted off-host copy, retention and monitoring
through the host owner's maintenance system before relying on these snapshots.
Bootstrap does not install restic, change shared timers or prune any volumes.

## Validation

Every entry point (backend, frontend, platform, bootstrap) uses `_deploy.yml`.
Its `deploy` job requires successful `validate`: image contract, Compose rendering
and isolation assertions, ShellCheck, actionlint, and configuration/recovery tests.
Application repositories continue to own their tests, SAST, secrets/dependency
scans and image security gates; they receive no production database settings.
See `VALIDATION.md` for checks actually executed for this migration and remaining
production checks. No migrations, restarts, deployments or database writes were
performed on the server during preparation.

## Push approval and manual production approval

Pushes validate the release definition only. Every deployment/bootstrap caller now
requires manual workflow dispatch with `approve_production=true` before its server
job runs. This preserves separate push and deployment approval during migration.
The merged app preflight validates incoming settings before stopping writers;
pre-migration snapshots and promotion of last-known-good config are retained.
HeadHunter and security settings from current main remain forwarded.

See [PGVECTOR.md](PGVECTOR.md) for the shared PostgreSQL owner's exact image-build,
maintenance and database-extension commands. These commands require separate approval.
The existing Create staff account workflow and its input checks are retained.
Additional HeadHunter credentials (`HH_CLIENT_ID`, `HH_CLIENT_SECRET`,
`HH_ACCESS_TOKEN`) remain prod secrets; the merged HH, rate-limit, retention,
cookie and vacancy-cache variables keep their established application names.
Snapshots are verified with pg_restore before publishing a manifest, check free
space, and retain at least three complete snapshots plus all snapshots from the
last seven days. Legacy loose dumps and unrelated files are retained.

See [MIGRATION_STATUS.md](MIGRATION_STATUS.md) for the completed new-server deployment,
verified data snapshot, and user-controlled traffic-switch details.
