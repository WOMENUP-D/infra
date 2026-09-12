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
| POSTGRES_PASSWORD | The single PostgreSQL password used by the database, API, and migrations: 64-128 hexadecimal characters |
| JWT_SECRET_KEY | JWT signing key, at least 48 characters |

Optional named secrets are `FIREBASE_PRIVATE_KEY`, `ANTHROPIC_API_KEY`,
`SMS_PROVIDER_TOKEN`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`,
`SMTP_FROM`, `EDU_JOB_CLIENT_SECRET`,
`INVEST_HUB_CLIENT_SECRET`, `COMMERCE_CLIENT_SECRET`, `S3_ACCESS_KEY`, and
`S3_SECRET_KEY`. Create only those used by the application.

Generate the database password with openssl rand -hex 32.
Generate the JWT key with openssl rand -hex 48. Store a Firebase private key with
literal `\n` separators. Never put backend secrets in frontend variables.

Verify the SSH host key through the VPS console/provider before recording it.
For a nondefault SSH port the known_hosts hostname is [host]:port. The workflow
does not trust an unverified ssh-keyscan result or disable host verification.

### prod environment variables

| Name | Value / purpose |
| --- | --- |
| APP_DOMAIN | `womanup.uz`; bare hostname, no scheme or path |
| DEPLOY_ROOT | `/opt/womanup`; supported format `/opt/<lowercase-name>` |
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

Production mode, database connection, debug mode and same-origin CORS are
enforced by the renderer and are intentionally not configurable.

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

## First launch

1. Commit and push infrastructure, Dockerfiles, workflows and lockfiles to their
   respective repositories. Create the prod environment and configure values above.
2. Point womanup.uz DNS A at the VPS. Remove or correct any stale AAAA record.
   Open inbound TCP 80/443 and the SSH port in the provider firewall.
3. Run **Server Bootstrap** from infra main. It requires an Ubuntu server and
   sudo-capable key-based SSH access. It installs Docker/Compose,
   logging defaults, firewall rules, and deployment directories.
   It then initializes PostgreSQL and Caddy and deploys any already published images.
4. Push/merge backend and frontend changes to main or dispatch their release
   workflows. Their first successful promotions fill the initially empty image files.
5. Check deploy workflow results, https://womanup.uz/health/ready,
   https://womanup.uz/healthz and the homepage. Configure provider credentials and
   Firebase authorized domains as required for login/email/AI functionality.

The initial metadata files intentionally contain no fake digest. Services with no
release yet are skipped. The frontend may return API errors until backend is deployed.
Bootstrap can be repeated; it does not reset existing database volumes or secrets.
It installs current packages from Docker's official signed apt repository.
Run it during a maintenance window because package upgrades may restart Docker.
An existing server with unrelated workloads requires a separate migration review.

Only Caddy publishes host ports. PostgreSQL has an internal Docker network;
backend and worker have outbound access for providers. Docker-published ports can
bypass UFW, which is why database and application ports are never published.

## Deployment and recovery

The backend image serves both API and worker. Deployment pulls the candidate,
stops API/worker, runs Alembic once with the same PostgreSQL account used by the
application, and waits for Compose health plus HTTP readiness over the private
Docker network. Public DNS and HTTPS are verified separately after deployment and
never determine rollback. The worker
health check uses a heartbeat after successful database work, with a 30-minute
tolerance for long ingestion jobs. Frontend uses its own image and health checks.

A failed migration leaves API and worker stopped and the workflow red. If health
checks fail without a schema or database-credential change, the previous backend
image/configuration is restored. A schema change blocks automatic rollback;
inspect the migration and restore compatibility explicitly. Frontend health
failures restore the previous image/configuration. First-deployment failures have
no previous image to restore. Failed releases never become successful state.

Git remains the desired state even after a rollback. Resolve a failed release by
fixing forward or committing a previously successful image digest/version to its
image.env, then deploy again. A code rollback after schema changes must be verified
compatible by the operator; no automated schema downgrade runs.

Server layout under DEPLOY_ROOT:

- repository.git and releases/<infra-sha>: received infra history and releases.
- current: active infrastructure release.
- config: root-only runtime env files; config.previous: previous runtime settings.
- state: last successful images, configuration hashes and schema version.

No secret files are committed or uploaded as Actions artifacts. Temporary runner
and server transport files and registry credentials are removed after successful
transfer/processing. Interrupted runner/network transfers can leave a root/user-only
/tmp/womanup.* payload; remove that specific stale directory after investigation.
The same PostgreSQL account is used by the container, application, and Alembic.
Coordinate password rotation with deployments; do not edit server env files by hand.
This repository does not create, schedule, retain, or restore database backups.

## Deployment gate

Each deployment workflow has two ordered jobs: `validate`, then `deploy`.
`deploy` has `needs: validate`, so no SSH connection or server mutation is possible
when validation fails. The validation job checks the image-reference contract, the
rendered Compose definition (including tmpfs mount paths), and workflow/shell syntax.
It does not run fake deployment, rollback, database, or Docker mock simulations.

Application CI remains responsible for application tests and security scanning.

Live first-launch, public DNS/TLS, and provider authentication checks must be
completed against the configured VPS. Retain successful GHCR
digests for rollback; no automatic image/volume pruning runs on production.
