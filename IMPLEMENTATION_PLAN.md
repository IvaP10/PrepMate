# InterAI Production Pipeline Implementation Plan

This plan turns the July 14 production specification into dependency-ordered delivery gates. A phase is complete only when its backend contract, frontend behavior, migrations, and focused tests pass together.

## Delivery status

| Phase | Status | Delivered in current foundation pass |
|---|---|---|
| 0. Baseline and CI gates | Existing / verified | Full backend suite, evaluation gate, frontend tests, lint/build, Alembic probe |
| 1. Resume immutability and attempt context | Implemented | Copy-on-write fact corrections, immutable referenced versions, encrypted materialized attempt snapshots, frontend version labels |
| 2. Attempt/analysis lifecycle separation | Implemented foundation | New attempt, analysis, integrity states; lifecycle revision; status envelope; dual writes on start, recovery, cancel, finalize and analysis |
| 3. Preflight and integrity | Implemented preflight foundation | Persisted five-minute browser preflight, backend health recheck, blueprint/owner/flow binding, single-use consumption |
| 4. WebSocket and voice hardening | Implemented / deployed proof gated | Renewable 15-second controller leases, production event envelopes, Redis sequence/idempotency enforcement, canonical integrity events and exact-question recovery are implemented; controlled camera/microphone/screen-share coverage passes locally and remains to be repeated on deployed HTTPS |
| 5. Technical execution hardening | Implemented / infrastructure gated | Standard 202 execution contract, encrypted source snapshots, immutable final evidence, hidden-detail filtering and infrastructure retries are implemented; deployed Linux gVisor acceptance remains infrastructure-gated |
| 6. Report truth | Implemented | Canonical manifests, DB sealing guards, 11 versioned stages, score/finding provenance, deterministic fallback, same-identity retries and truthful report UI states are implemented |
| 7. Performance truth | Implemented | Interview and Technical remain separate; canonical cohorts require matching mode, profile family, evidence sufficiency, evaluator, taxonomy and rubric, with evidence-linked claims and explicit incompatible-history notices |
| 8. Guided Improve | Implemented / deployed proof gated | Durable single-current-node missions, identity-bound attempt sessions, real-work deterministic submissions, held-out checkpoint secrecy, predicted readiness and version-compatible later official reassessment are integrated; the signed-in browser path persists and grades real work locally |
| 9. Operations | Implemented / deployment acceptance gated | Privacy-safe metrics, Prometheus/OTLP/Sentry, fail-closed Redis limits, versioned field encryption, complete export coverage, encrypted backups, restore drill, alert rules, load harness, OpenAI canary and runbook are implemented; the local restore, OpenAI and baseline load proofs pass |
| 10. Promotion | Harness implemented / deployment acceptance gated | Dedicated executor topology, authenticated browser fixtures, canary/rollback procedure and release CI are executable; controlled beta duration, managed-service provisioning, production load/chaos and Linux gVisor evidence require the target environment |

## Phase gates

### Gate A — immutable official attempt creation

- A ready server-owned blueprint and confirmed resume are required outside tests.
- Browser preflight is owned by the user, bound to the blueprint and flow, expires after five minutes, and is consumed once.
- Start, entitlement reservation, interview insert, context snapshot, blueprint consumption and preflight consumption share one database transaction.
- Snapshot consumers never reload mutable resume/JD/profile state for a new official attempt.
- Correcting a referenced resume creates a child version and never changes historical context.

### Gate B — terminal lifecycle truth

- `attempt_status`, `analysis_status`, and `integrity_status` are independent authoritative fields.
- Completed and incomplete attempts are read-only and cannot reopen.
- Recovery expiry and voluntary exit produce incomplete attempts with no official score.
- Report retry changes analysis state without deleting the completed attempt.
- Status APIs return server time, deadline, recovery deadline, lifecycle revision, read-only state and next action.

### Gate C — live interview hardening

- Replace long controller keys with 15-second leases renewed every five seconds.
- Add globally unique event IDs and monotonic per-client sequence enforcement.
- Commit/acknowledge each question before moving to the next turn.
- Make reconnect restore the exact committed question within the fixed recovery window.
- Instrument STT, evaluation and TTS latency budgets and add controlled-media Playwright coverage.

### Gate D — technical isolation and submission truth

- Keep workflow state separate from execution-job state.
- Make final submission source immutable and prevent later runs from replacing it.
- Validate generated problems using reference solutions and mutation cases before activation.
- Run the adversarial suite on a dedicated Linux gVisor host with no application Docker socket.
- Keep hidden inputs and expected outputs out of all browser payloads.

### Gate E — evidence, reports, performance and Improve

- Seal a canonical append-only evidence manifest before analysis.
- Require valid evidence IDs for every report finding and cumulative claim.
- Publish deterministic reports when semantic enhancement is unavailable.
- Compare only compatible evaluator/taxonomy/rubric cohorts.
- Keep Interview and Technical scores separate.
- Require real work for Improve completion, hold checkpoint rubrics back, and distinguish predicted from officially verified transfer.

### Gate F — production operations

- Add distributed telemetry, SLO metrics and privacy-safe structured logs.
- Prove encrypted backup restore, rollback, canary, load, soak and chaos procedures.
- Use managed secrets and least-privilege database roles.
- Promote Technical Round only after deployed gVisor probes pass.

## Files that must not be rewritten during later phases

- Authentication and payment contracts unless a new evidence table must join account export/deletion.
- Alembic revisions `001` through `010`; all schema work stays forward-only.
- Deterministic code verdict logic; OpenAI never overrides compilation or tests.
- Raw-media retention policy; camera, microphone and screen media remain non-durable.
- Historical attempts, reports and performance cohorts; migrations backfill or add compatibility reads rather than editing history.

## Required release checks

```bash
python3 -m alembic heads
ENVIRONMENT=test python3 -m pytest -q
ENVIRONMENT=test python3 tests/test_e2e_system.py
ENVIRONMENT=test python3 evaluation/run_gates.py
cd Frontend && npm test
cd Frontend && npm run lint
cd Frontend && npm run build
cd Frontend && npm run test:e2e
docker compose config --quiet
```

Production promotion additionally requires real browser permission/media fixtures, a live cost-capped OpenAI canary, the Linux gVisor adversarial probe, declared-capacity load tests, and a successful backup restore drill.
