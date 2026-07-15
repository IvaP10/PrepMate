# Production acceptance matrix — 2026-07-14

This matrix is deliberately evidence-based. `Implemented` means the repository contract and local runtime proof pass. `Deployment gate` means the harness exists but only the target production environment can supply authoritative evidence.

| Area | Requirement | Status | Current evidence / required proof |
|---|---|---|---|
| Resume/setup | Referenced versions immutable; snapshots keep historical context | Implemented | Migrations 011/014, copy-on-write and attempt-foundation tests |
| Resume/setup | Four profile contracts and server-owned blueprint structure | Implemented | Profile, blueprint, question-quality and setup-pipeline tests; browser persistence proof for profile selection |
| Resume/setup | Modern resume/job targets remain consistent across legacy readiness reads | Passed locally | Real DOCX upload and job-target creation plus `/profile/me`, completion, pre-interview form/status runtime checks and regression tests |
| Interview | Backend deadline, one active question, sequenced events, reconnect, duplicate control, incomplete exit | Implemented | WebSocket contract, lifecycle, recovery and end-to-end system tests |
| Interview | Camera/microphone/screen real-browser lifecycle | Passed locally / deployment gate | Disposable signed-in fixture completed screen-share, camera and microphone preflight, WebSocket startup, committed warm-up delivery and active workspace rendering; deployed HTTPS proof is still required |
| Interview | No raw media retention | Implemented | Zero-retention configuration, privacy migration and readiness contract |
| Technical | Frozen problem/tests, immutable final, deterministic hidden verdicts | Implemented | Technical-mode and report-truth tests |
| Technical | Disposable gVisor isolation on dedicated executor | Deployment gate | Main Compose has no Docker socket; executor-only topology and expanded `scripts/verify_sandbox.py` must pass on Linux `runsc` |
| Reports | Async, retryable, idempotent, evidence-referential and truthful failure states | Implemented | Canonical manifest/stage pipeline, DB sealing triggers and report-truth tests |
| Performance | Mode separation, comparable versions, evidence-linked claims | Implemented | Canonical performance payload and mixed-cohort tests |
| Improve | One current action, locked future nodes, real work, held-out checkpoint, predicted versus verified transfer | Implemented | Migration 015, identity-bound mutations, checkpoint secrecy/reassessment tests and frontend build |
| Privacy | Export/deletion covers attempt, evidence, technical, report and Improve domains | Implemented | `user_profile.py` export/delete graph and privacy-operations contract tests |
| Encryption | Authenticated field encryption and key rotation | Implemented | Versioned AES-GCM envelope, legacy compatibility and prior-key keyring tests |
| Observability | Structured request/dependency/worker/queue/backup metrics, Prometheus, OTLP, Sentry and alert rules | Implemented | Private collector in Compose plus API/backup exporters; `promtool` validated both scrape targets and nine rules |
| Alert delivery | Authenticated receiver and incident notification proof | Deployment gate | Configure the deployment owner's Alertmanager receiver and preserve a timestamped synthetic warning delivery artifact |
| Rate limits | Distributed production enforcement | Implemented | Redis limiter fails closed in production; contract tests |
| OpenAI | Cost-capped live canary, no response storage | Passed locally | Live response succeeded with `gpt-5-nano`, `store=false`, 52 total tokens, estimated cost USD 0.00003455 |
| Database | Fresh migration and upgrade from revision 010 with history | Passed locally | Disposable database upgraded 000→010, seeded completed interview, then 010→015; backfill returned `completed:ready:clean` |
| Backup | Daily encrypted backup plus restore proof | Passed locally | Streaming 1.37 MB AES-GCM dump passed checksum/freshness validation and restored into an isolated DB at revision 015 with four core tables |
| Browser visuals | Public desktop/mobile geometry and routes | Passed locally | Four Playwright tests; full-page desktop/mobile screenshots visually inspected |
| Browser visuals | Authenticated product surfaces and lifecycle | Passed locally | Sixteen Playwright flows cover navigation, settings, export, support, job-target CRUD, profile persistence, login/logout, account/password round-trip, visible DOCX upload, actual dashboard-to-new-interview media handoff, Improve grading, technical execution behavior, checkout behavior and report rendering against the live API/worker/database/Redis stack; authenticated screenshots were visually inspected |
| Load | Declared-capacity public and ownership-boundary probe | Passed locally | 200 requests at concurrency 20: 1,587 RPS, p95 under 43 ms |
| Load | Authenticated mixed flow and 100+ WebSockets at launch capacity | Deployment gate | Seed `infra/load/release-scenario.example.json` and `websocket-fixtures.example.json`; run `load_scenario.py` and `load_websockets.py` against canary with disposable accounts |
| Operations | Canary, rollback, chaos and alert response procedures | Implemented harness | `infra/OPERATIONS_RUNBOOK.md`; target-environment execution records still required |
| Promotion | Two-week controlled beta, managed services/secrets, security review, production canary | Deployment gate | Requires deployment owner, infrastructure and elapsed beta evidence |

Production promotion remains prohibited while any deployment gate lacks a timestamped passing artifact.
