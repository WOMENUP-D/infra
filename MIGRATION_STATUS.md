# WomanUP migration status — 2026-11-06

## New server is deployed and verified

- Server: `65.108.142.153`; IPv6: `2a01:4f9:1a:9280::2`.
- Root: `/opt/womanup`; Compose project: `womanup`.
- Backend version: `7ef4cf077842b1eac67ead03000743b28b61d983`.
- Successful platform deployment: https://github.com/WOMENUP-D/infra/actions/runs/42193863765
- API, worker and frontend are healthy. Homepage, `/health/ready`, `/healthz`,
  and `/api/v1/programs` passed HTTPS checks against the new origin. Both the
  new IPv4 and IPv6 passed certificate-verified HTTPS readiness checks.
- Shared PostgreSQL remains 18.1 with the original volume/network. The app uses
  `womanup_db` / `womanup_user`; vector 0.8.7, pg_trgm and uuid-ossp are enabled.
- All 57 application tables are owned by `womanup_user`; schema revision is `0039`.
- Existing AgroZanjir and YouthCapital application containers remain healthy.
- The project backup timer is enabled at 03:45 Asia/Tashkent. Local snapshots
  include only this database's application schema and project-local media.

## Existing data copied while the old app remained running

The source is `root@2.29.31.201`, database `womanup` in `womanup-postgres-1`.
A repeatable-read exported PostgreSQL snapshot was used for both pg_dump and
per-table verification, so the dump and manifest describe the same consistent
point despite ongoing source writes. The snapshot completed at:

**2026-11-06 14:19:13 Asia/Tashkent (09:19:13 UTC).**

The refreshed import was checked against all 57 source-table row counts and
content checksums: **2,694 rows**, with every table matching. A target safety
snapshot was retained before import. Only the new target backend/worker were
paused for the import; the old backend, worker, frontend, Caddy and PostgreSQL
were left running. Source volumes and data were retained.

Source inspection found no app media mounts or configured S3 storage. Database
media references were transferred with the rest of the data. Existing signing
and provider secrets and frontend runtime configuration match between servers.
No credentials, database dumps, certificate keys or record contents are in Git.

**The old server continues accepting writes. Changes made there after the snapshot
need another synchronization before switching traffic.** Coordinate a final
synchronization with the traffic switch to prevent missing writes; this setup
does not continuously replicate the databases.

## HTTPS and ingress are ready; traffic remains on the old server

The valid project-specific Let's Encrypt certificate was securely transferred
into the existing public Caddy's protected certificate storage. Its expiry is
2026-12-10. New-origin TLS verification passed without disabling validation.
The existing public Caddy on the new host forwards `womanup.uz` to
`womanup-proxy:8080`; existing routes were preserved and Caddy was gracefully
reloaded. WomanUP's internal Caddy preserves its API/frontend path routing.

The added WomanUP site block is recorded in `platform/ingress.caddy`. Retain that
block when updating the shared ingress owner's infrastructure/Caddyfile; its
shared-infra deployment replaces the managed Caddyfile. Normal app-only releases
do not replace that shared configuration.

Cloudflare was inspected read-only and is signed in with Full (strict) enabled.
**No DNS or Cloudflare settings were changed.** The observed origin records remain:

| Record | Current origin | New origin for the user's eventual switch |
| --- | --- | --- |
| A womanup.uz | 2.29.31.201 | 65.108.142.153 |
| AAAA womanup.uz | 2a01:4f9:c014:95b::1 | 2a01:4f9:1a:9280::2 |
| CNAME www | womanup.uz | unchanged |

Keep proxying and Full (strict). Update both origin address records when switching;
leaving the old AAAA record can continue routing requests to the old server.
After traffic points to the new ingress, standard HTTP-01 renewal can reach it;
the transferred certificate avoids the initial Full (strict) issuance bootstrap
problem. TLS-ALPN challenges are disabled in the WomanUP site block.

Test the new server without changing DNS, from PowerShell:

```powershell
curl.exe --fail --resolve womanup.uz:443:65.108.142.153 https://womanup.uz/health/ready
curl.exe --fail --resolve womanup.uz:443:65.108.142.153 https://womanup.uz/healthz
```

The old site also passed a direct HTTPS readiness check after the transfer and
retained its original container uptimes. The user's instruction reserves the
traffic switch and any decision to stop the old deployment to the user.
