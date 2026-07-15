# InterAI

InterAI is an evidence-based interview practice application. A FastAPI API, Next.js frontend, PostgreSQL database, Redis cache, and separate durable worker power four connected areas:

- Interview Round: a single continuous, screen-shared voice interview with a required microphone and an optional camera.
- Technical Round: a separate proctored, typed coding/debugging/concept/system-design flow whose code runs in a private gVisor sandbox.
- Performance: canonical, version-comparable analysis only; missing evidence stays unknown.
- Improve: interactive missions, timed activities, saved drafts, held-out checkpoints, and later-interview validation.

Both Interview and Technical flows offer four distinct profiles: Top Tier, Mid Tier, Startup, and Custom. Every session starts from an internal, immutable, versioned blueprint tied to a resume version and job target; exact questions and internal scoring plans are never exposed before the attempt.

## Local development

Requirements: Python 3.12+, Node.js 20+, PostgreSQL 16, and Redis 7. Copy `key.env.example` to `key.env`, use non-placeholder secrets, and keep `ENVIRONMENT=development` for local HTTP.

```bash
python3 -m pip install -r requirements.txt
cd Frontend && npm ci && cd ..
python3 -m alembic upgrade head
```

Run three processes in separate terminals:

```bash
uvicorn app:app --reload --host 0.0.0.0 --port 8000
python3 worker.py
cd Frontend && npm run dev
```

The API commits analysis and code-execution jobs; only `worker.py` claims them. Production code never runs untrusted submissions on the API host.

## Option A Docker deployment

Docker Compose supplies PostgreSQL, Redis, the migration job, API, worker, Next.js, Caddy TLS proxy, a network-private Prometheus collector with alert rules, and authenticated encrypted PostgreSQL backups. `/metrics` is intentionally absent from Caddy's public routes and the bundled collector scrapes it only across the private `app` network. Leave `METRICS_BEARER_TOKEN` empty for this bundled topology; a replacement collector must send that bearer token when one is configured. Production requires a separate private sandbox executor; the public application stack never mounts a Docker socket. Execution hosts install and register gVisor's `runsc` runtime and run the executor-only Compose file documented in [`infra/sandbox/README.md`](infra/sandbox/README.md).

```bash
cp key.env.example key.env
# Fill all production values, including HTTPS origins/URLs, secure cookies,
# PISTON_API_URL for the private executor, and BACKUP_ENCRYPTION_KEY.
docker compose --env-file key.env config --quiet
docker compose --env-file key.env up --build -d
curl -fsS https://YOUR_DOMAIN/live
curl -fsS https://YOUR_DOMAIN/ready
```

`/live` proves only that the API process is alive. `/ready` is the deployment gate: database connectivity and exact Alembic head, Redis, OpenAI configuration, isolated sandbox runtimes, fresh analysis/technical worker heartbeats, and stuck-job checks must all pass. The API container health check uses `/ready`, so the frontend and proxy are not declared ready over a degraded pipeline.

Run Compose with `--env-file key.env`; this keeps PostgreSQL credentials and required private-service/backup settings used for interpolation aligned with the API, worker, migration, and backup services.

After readiness passes, run the dependency-free latency gate against each intended deployment route. Protected routes accept `--cookie` (or `--bearer` where bearer auth is enabled) for a dedicated disposable test account:

```bash
python3 scripts/load_smoke.py --path /live --requests 200 --concurrency 20 --p95-ms 500
python3 scripts/load_smoke.py --path /api/dashboard/home --cookie "interai_session=$LOAD_TEST_SESSION" --requests 100 --concurrency 10 --p95-ms 1000
```

## Evidence and scoring contract

- Raw answers, transcripts, resume/JD content, reports, and source code use encrypted-at-rest columns.
- Responses are immutable; assessments are append-only and versioned.
- The application owns state transitions, follow-ups, weighted rubrics, code correctness, mission progress, and entitlements.
- OpenAI is limited to transcription, structured semantic evidence, optional wording, and narrative. Structured calls use strict schemas and `store=false`.
- A required dimension without evidence is `null`. Empty or short answers are insufficient evidence, never an authoritative zero.
- Coding correctness comes only from visible and encrypted hidden tests run in the private gVisor sandbox.
- Performance reads `SessionPerformanceAnalyses`; it does not recompute a competing score from legacy rows.
- Passing an Improve exercise does not resolve a weakness. A held-out variation plus later comparable interview evidence is required.
- Client-supplied Improve scores, bonuses, condition results, and mastery decisions are ignored.

Raw audio/video retention defaults to disabled (`RAW_VIDEO_RETENTION_HOURS=0`, `AUDIO_RETENTION_DAYS=0`). The app persists transcripts, real timing, and approved browser-derived signals instead.

## Validation

```bash
python3 -m pytest -q
python3 -m alembic upgrade head
python3 -m compileall -q .
cd Frontend && npm run lint -- --incremental false && npm run build
```

For a release, also prove an empty-database migration and an existing-database upgrade, worker lease/restart recovery, duplicate answer/finalization behavior, sandbox hidden-test secrecy and adversarial resource-limit probes, export/delete coverage, authenticated browser flows across all four areas, and the latency gates in the implementation plan.

## Operational notes

- Use `python3 -m alembic upgrade head`; do not apply `schema.sql` or individual SQL migrations in production.
- AES-256-GCM authenticated backups are written to the `postgres_backups` volume and retained for seven days. A backup is not accepted until the isolated restore drill in [`infra/OPERATIONS_RUNBOOK.md`](infra/OPERATIONS_RUNBOOK.md) passes.
- Run the public desktop/mobile browser gate with `cd Frontend && npm run test:e2e`. The authenticated release suite fails closed unless a disposable account and exact seeded lifecycle IDs are supplied to `npm run test:e2e:release`.
- Keep Caddy’s application domain, `APP_BASE_URL`, `API_BASE_URL`, `ALLOWED_ORIGINS`, cookie domain, and `COOKIE_SECURE=true` aligned in production.
- Public execution endpoints, local subprocesses, and host-runtime fallbacks are rejected as production dependencies.
