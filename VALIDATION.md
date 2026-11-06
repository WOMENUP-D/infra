# Migration validation — 2026-10-26 (Asia/Tashkent)

All preparation was local except read-only SSH inventory, SQL catalogue queries,
and public DNS/HTTP/TLS probes. No production data was written, migrations run,
services restarted/reloaded/deployed, Git refs pushed, or volumes deleted.
Only this infra repository changed; backend, frontend and AgroZanjir were untouched.

| Check | Result |
| --- | --- |
| Repository instructions and initial Git status | No applicable AGENTS.md found; all three repos initially clean |
| Shared PostgreSQL inventory | PostgreSQL 18.1; existing `womanup_db` owned by non-admin `womanup_user`; public schema empty |
| Port/network/project inventory | AgroZanjir owns 80/443; external networks present; no WomanUP project/root/proxy alias collision |
| Python configuration/recovery/isolation unit tests | 14 passed in Linux Python 3.12 container |
| Full real Alembic migration chain | Passed as non-admin `womanup_user` on isolated local PostgreSQL 18 + pgvector; revision `0012` |
| Real dump/restore and media recovery | Passed with actual migrated schema, probe row and media; safety snapshot and previous media retained |
| Other-tenant and extension preservation | Control database row unchanged; three admin-owned extensions preserved after restore |
| Compose | v5.1.3: profile `tools`, config parsing, JSON isolation assertions passed; no host ports, no Postgres/Redis service, external DB/ingress networks |
| ShellCheck | v0.11.0, warning severity, SC1091 excluded: all project shell scripts passed |
| actionlint | All five deployment workflows passed; explicit secret mappings and shell input handling |
| Semgrep | v1.179.0, registry `p/ci`: 32 applicable rules, 27 source targets, zero findings after fixes |
| Gitleaks | v8.30.1, redacted scan of deployable source: zero leaks |
| Caddy configuration | Internal Caddy, ingress site block, and combined reference ingress validated locally, with no public listeners/issuance |
| Trivy image scan | v0.75.0, remote registry mode, fixable HIGH/CRITICAL gate: **failed**, 8 HIGH / 0 CRITICAL on reference Caddy digest |
| Public DNS/TLS | Cloudflare proxy addresses; current public site HTTP 200; new origin SNI handshake fails (no WomanUP route/cert) |
| GitHub settings access | CLI API HTTP 401; values/secrets not read or changed; secure application password input still required |

## Security findings

Semgrep initially flagged four `secrets: inherit` callers and direct workflow input
interpolation in a run step. Callers now explicitly map only named secrets (SSH
only for bootstrap), and the run step uses a quoted environment variable. Required
production settings remain in the reusable job's `prod` environment; optional
integrations remain optional. Runtime render/transport checks reject missing
required values without printing them.

Trivy found 48 fixable HIGH entries in the original Caddy image. The pin was
updated to the reference infrastructure digest
`881bbc60f9986d5ab8e7cfd6cf7e4ef3c9c0439fef2429d035d065577882f028`, which reduces
the result to eight HIGH entries. A separate scan of the current upstream digest
`eb4d35b7452d1ab6171fbdbe8d9275b2301dad6dad92115d91e19fb9b24d510f` reported the
same eight entries. This change does not modify AgroZanjir's running image.

| Package | Remaining vulnerability IDs | Reported fixed version |
| --- | --- | --- |
| brotli-libs | CVE-2026-111497 | 1.2.1-r0 |
| curl, libcurl | CVE-2026-92392 (one entry each) | 8.23.0-r0 |
| golang.org/x/net | CVE-2026-78669 | 0.60.0 |
| Go stdlib | CVE-2026-111943 | 1.26.10 or 1.27.3 |
| Go stdlib | CVE-2026-78667, CVE-2026-78669, CVE-2026-97031 | 1.26.9 or 1.27.2 |

Use a patched, rescanned image or obtain explicit review of these findings before
production rollout. A custom proxy rebuild is outside this deployment migration.
Scanner reports are ignored local artifacts under `reports/migration/`.

An initial unfiltered Gitleaks directory scan included ignored `.tools` artifacts
and reported seven findings. The deployable-source scan was rerun separately and
is clean; no ignored artifact enters the Git bundle. These unfiltered artifact
findings were not classified as production-source findings or silently counted
as a passing scan. An attempted Docker-socket mount for Trivy was rejected by
automatic review; subsequent successful image scans used direct registry mode
without the socket. Trivy config scanning does not support this Compose input and
was not counted as validation; Compose isolation is checked explicitly instead.

## Reproduction

Run from infra on Linux with Docker already provisioned (local validation only):

```bash
python3 -m unittest discover -s tests -v
shellcheck -S warning -e SC1091 scripts/*.sh
actionlint -shellcheck= .github/workflows/*.yml
python3 scripts/validate_images.py .
CONFIG_DIR=/path/to/dummy-config docker compose --env-file /path/to/dummy-config/deploy.env --profile tools config --quiet
CONFIG_DIR=/path/to/dummy-config docker compose --env-file /path/to/dummy-config/deploy.env --profile tools config --format json | python3 scripts/validate_compose.py
```

Dummy `deploy.env` must set APP_DOMAIN, DB_NETWORK and INGRESS_NETWORK; dummy
`backend.env` and `frontend.env` can be empty. Never print real Compose config:
its output includes credentials. The local integration test is opt-in and refuses
any Docker context except `desktop-linux`; it creates unique temporary containers
and an internal network, no published ports or persistent volumes:

```bash
WOMANUP_LOCAL_INTEGRATION=1 python3 tests/integration_database.py
```

It requires the locally built `womenup-backend-ci:python-3.14-alpine` image and the
pinned test pgvector image. Application migrations run only in that isolated test.
Application/frontend code and images were not rebuilt or promoted. Their existing
CI suites and published-image scans remain required for future app releases.

## Checks still required at rollout

1. Provide pgvector for the existing shared PostgreSQL 18 host and preinstall
   `vector`, `pg_trgm`, `uuid-ossp` in `womanup_db` through an approved admin plan.
2. Configure/review infra `prod` values and verify the existing application password
   by running the deployment preflight under approved rollout access.
3. Resolve/review the Caddy findings above and verify released app digests remain
   available and appropriately scanned.
4. Identify and transfer the current production database/media; the new DB is empty.
5. Apply/reload the reviewed public-ingress route with owner approval, issue the
   origin certificate, verify direct origin TLS, then switch Cloudflare origin DNS.
   Verify actual Full (strict) mode in the zone configuration.
6. Verify public readiness, homepage, auth/provider operations, worker heartbeat,
   scheduled backups, encrypted off-host retention and an isolated restore drill.

See README.md for the ordered rollout and recovery commands. Nothing here is
authorization to push, deploy, migrate, reload ingress or alter shared services.
