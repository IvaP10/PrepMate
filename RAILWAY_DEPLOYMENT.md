# Railway v1 deployment

Railway does not run this repository's `docker-compose.yml` as one deployment.
Create separate services in one Railway project so they share private
networking:

1. Railway PostgreSQL service named `Postgres`.
2. Railway Redis service named `Redis`.
3. API service named `api`, connected to this repository with config path
   `/railway.api.toml`.
4. Worker service named `worker`, connected to the same repository with config
   path `/railway.worker.toml`.
5. Frontend service named `frontend`, root directory `/Frontend`, and config
   path `/Frontend/railway.toml`.
6. A separate dedicated Linux gVisor executor host for candidate code.

The API and frontend need public domains. The worker, PostgreSQL, Redis, and
executor must not have public application domains.

## Required service references

Add these variables to both `api` and `worker`:

```dotenv
PG_HOST=${{Postgres.PGHOST}}
PG_PORT=${{Postgres.PGPORT}}
PG_DBNAME=${{Postgres.PGDATABASE}}
PG_USER=${{Postgres.PGUSER}}
PG_PASSWORD=${{Postgres.PGPASSWORD}}
REDIS_URL=${{Redis.REDIS_URL}}
```

Use the same sealed values on `api` and `worker` for:

```dotenv
ENVIRONMENT=production
MODEL_DEFAULT_POLICY=openai_required
COOKIE_SECURE=true
JWT_SECRET=<at-least-32-random-characters>
ENCRYPTION_MASTER_KEY=<at-least-32-random-characters>
ENCRYPTION_SALT=<stable-random-salt>
OPENAI_API_KEY=<secret>
SMTP_EMAIL=<verified-sender-address>
SMTP_PASSWORD=<smtp-app-password>
RAZORPAY_KEY_ID=<secret>
RAZORPAY_KEY_SECRET=<secret>
RAZORPAY_WEBHOOK_SECRET=<secret>
PISTON_API_TOKEN=<at-least-32-random-characters>
INTERNAL_SERVICE_TOKEN=<same-private-service-token>
```

Set the public URLs after Railway creates the API and frontend domains:

```dotenv
APP_BASE_URL=https://${{frontend.RAILWAY_PUBLIC_DOMAIN}}
API_BASE_URL=https://${{api.RAILWAY_PUBLIC_DOMAIN}}/api
ALLOWED_ORIGINS=https://${{frontend.RAILWAY_PUBLIC_DOMAIN}}
COOKIE_DOMAIN=
```

Set `PISTON_API_URL` to the `/api/v2` URL of the dedicated private gVisor
controller. Railway application containers do not expose the scoped Docker
socket or `runsc` runtime required by `infra/sandbox/service.py`, so a
Railway-only project cannot safely provide the Technical Round executor.

Add these build-time variables to `frontend`:

```dotenv
NEXT_PUBLIC_API_BASE_URL=https://${{api.RAILWAY_PUBLIC_DOMAIN}}/api
NEXT_PUBLIC_RAZORPAY_KEY_ID=<matching-public-checkout-key>
NEXT_PUBLIC_SUPPORT_EMAIL=<support-address>
NEXT_PUBLIC_PRIVACY_EMAIL=<privacy-address>
NEXT_PUBLIC_LEGAL_EMAIL=<legal-address>
```

`NEXT_PUBLIC_*` values are compiled into the browser bundle. Changing them
requires a frontend rebuild and redeploy.

## First deployment order

1. Run `git fetch --prune`, then `python3 scripts/release_source_guard.py`.
   Do not deploy until it prints the exact clean commit that is present on the
   upstream branch connected to Railway.
2. Load the production OpenAI values and run
   `python3 scripts/openai_canary.py --env-file key.env` (omit the flag when
   the platform already injects the environment). Require `ok=true` and
   `store=false`; model listing alone does not prove that the account has
   generation quota.
3. Start the private gVisor executor and pass `scripts/verify_sandbox.py`.
4. Deploy PostgreSQL and Redis.
5. Deploy `api`. Its pre-deploy command applies Alembic migrations.
6. Deploy `worker`.
7. Deploy `frontend` from the same commit printed by the source guard.
8. Confirm `GET https://<api-domain>/ready` returns `200`.
9. Confirm both `GET /api/preflight?flow=interview` and
   `GET /api/preflight?flow=technical` return `200`.
10. Run the authenticated browser release suite against the Railway domains.

Railway's `/live` deployment healthcheck only proves that the process accepted
traffic. `/ready` is the release gate: it additionally checks migrations,
Redis, workers, OpenAI, the real isolated execution probe, and payments.
The OpenAI canary and adversarial sandbox probe remain separate gates because a
cheap readiness request must not spend generation quota or run hostile code.
