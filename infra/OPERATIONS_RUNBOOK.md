# InterAI production operations runbook

Every command in this runbook is a gate. Store its timestamped JSON/text output with the release record. A skipped gate is a failed promotion, not an implicit pass.

## Pre-deploy

1. Render deployment configuration using production secrets without printing them:
   `docker compose --env-file key.env config --quiet`.
2. Run backend tests, evaluation gates, frontend unit/browser tests, lint and build.
3. Prove the current migration can downgrade one revision and upgrade to head on a disposable database.
4. Run `python scripts/openai_canary.py`; require `ok=true`, `store=false`, and cost below the configured cap.
5. On the dedicated Linux gVisor executor, run `python scripts/verify_sandbox.py`. Every line must be `PASS`.

## Backup and restore

- The backup container writes AES-256-GCM authenticated `.dump.enc` files and checksum manifests. Its health check fails when the latest backup is older than 26 hours or corrupt.
- Weekly, copy one encrypted backup to the isolated drill host and run:
  `python scripts/restore_drill.py /backups/FILE.dump.enc --target-db interai_restore_drill --expected-revision 015_improve_graph_invariants`.
- A restore passes only when authentication, `pg_restore`, Alembic revision and all four core tables validate. The drill database is deleted automatically.

## Canary and rollback

1. Deploy the new immutable image tag to one canary API and one worker with no more than 5% traffic.
2. Run `/live`, `/ready`, the authenticated Playwright release suite, the OpenAI canary and sandbox probe against the canary.
   The release suite uses `E2E_BASE_URL` for rendered pages and accepts an optional `E2E_API_BASE_URL` when the API is reached on a different origin during local or split-host validation; production reverse-proxy deployments normally leave it unset.
3. Observe 30 minutes: 5xx rate, p95 latency, WebSocket recovery, queue age, report completion, sandbox teardown and AI cost.
4. Promote in 25%, 50%, 100% steps only while all alerts remain clear.
5. Roll back immediately on evidence mismatch, migration mismatch, sandbox isolation failure, failed restore, acknowledged evidence loss, or sustained SLO breach. Route traffic to the prior immutable image; do not downgrade a forward-only database migration. Deploy a forward compatibility fix when schema rollback is unsafe.

## Load and chaos

- Run the mixed authenticated scenario with disposable IDs and session/CSRF values:
  `python scripts/load_scenario.py infra/load/release-scenario.json --base-url https://CANARY --iterations 1000 --concurrency 50 --p95-ms 1500`.
- Run `scripts/load_smoke.py` separately for `/live`, dashboard and readiness.
- Prove 100+ independent active interview controllers with unique disposable accounts: `python scripts/load_websockets.py infra/load/websocket-fixtures.json --base-url https://CANARY --ws-base-url wss://CANARY --connections 100 --hold-seconds 60`.
- During a staging soak, terminate one API, worker and Redis connection in turn. Attempt truth must remain in PostgreSQL, leases must recover, and `/ready` must become degraded rather than returning a false healthy state.
- Never run destructive chaos or mutation load against production candidate accounts.

## Alert response

- The bundled Prometheus collector is network-private and loads `infra/prometheus/alerts.yml`; verify it with `docker compose exec prometheus promtool check config /etc/prometheus/prometheus.yml` and confirm the `interai-api` target is up before canary traffic.
- Connect Prometheus to the deployment owner's authenticated Alertmanager receiver and fire a synthetic warning before promotion. Rule evaluation without confirmed delivery is not an accepted paging path.
- Database/migration/evidence/sandbox/restore alerts are release-stopping critical incidents.
- Worker heartbeat, queue age, OpenAI timeout, Redis lease, recovery expiry, TTS latency and schema failures are warning incidents until their documented SLO threshold is crossed.
- Logs and traces use request/interview/analysis IDs; never attach raw transcripts, resumes, source code, media, tokens or credentials.
