# INTER Architecture

## Request Flow

1. The frontend authenticates through the backend and stores session state using secure cookies plus CSRF-aware API calls.
2. Resume upload sends a supported document to the backend parser, which extracts profile fields and lets the user confirm them before interview generation.
3. Mock interviews use backend-generated questions, websocket/session state, browser media controls, and async analysis after the session ends.
4. Technical rounds prepare DSA-first questions, render a Monaco workspace, execute visible tests for practice, execute final visible plus hidden tests on submit, and persist `TechnicalSubmissions`.
5. Analysis jobs build transcript, audio/video proxies, NLP scoring, technical scoring, integrity summary, and report artifacts.
6. Dashboard and analytics read persisted reports, learning-engine state, generated exercises, technical submissions, and activity events.

## Backend Components

- `app.py`: FastAPI entrypoint, middleware, CORS, security headers, router registration, health paths.
- `database.py`: PostgreSQL access helpers. Production schema changes should come through migrations.
- `auth.py`: account, session, JWT/cookie, and CSRF-adjacent auth flow.
- `pre_interview.py` and `resume_parser.py`: resume intake and profile extraction.
- `interview.py`: behavioral/mock interview session lifecycle.
- `technical_mode.py`: technical question generation, executor integration, run/test/submit flow, integrity events.
- `analysis_pipeline.py`: async analysis stages and report artifact persistence.
- `report_generator.py`: deterministic report assembly and no-evidence report handling.
- `dashboard.py`: dashboard stats, learning surfaces, recent activity, technical analytics, exercise runner.
- `learning_engine.py`: generated exercises, attempts, mastery, weak-topic drill queue.
- `payment.py`: Razorpay order and webhook flow.
- `llm_router.py`: configured model/provider routing, JSON completion helpers, cache-key support.

## Frontend Components

- `Frontend/app/interview/[id]/page.tsx`: mock interview runtime.
- `Frontend/app/interview/[id]/technical/page.tsx`: strict technical workspace with progressive disclosure, code editor, tests, mic transcript, and proctoring telemetry.
- `Frontend/app/interview/[id]/report/page.tsx`: candidate report tabs for summary, transcript, film room, weak topics, fix-it queue, and integrity.
- `Frontend/components/dashboard.tsx`: main authenticated shell, dashboard reps, interview entry, technical entry, analytics, membership, and settings.
- `Frontend/lib/api.ts`: frontend API contracts.
- `Frontend/lib/technical-permissions.ts`: fullscreen, monitor share, and camera permission lifecycle.
- `Frontend/hooks/use-face-check.ts` and `Frontend/hooks/use-object-detection.ts`: client-side integrity telemetry.

## AI Model Policy

The platform should retain the existing model routing and configured model names. Cost control comes from:

- stable `LLMCache` keys for question, report, and exercise generation
- shorter generation payloads
- deterministic daily seeds for technical batches
- avoiding repeat report enhancement when no candidate evidence exists
- using final execution artifacts for technical grading instead of extra model calls

## Technical Grading Source Of Truth

Practice runs in `TechnicalRunEvents` are useful telemetry, but final report correctness must use the latest/final `TechnicalSubmissions` per round. Correctness is:

```text
(visible_passed + hidden_passed) / (visible_total + hidden_total)
```

Visible-only runs should be displayed as practice evidence, not final grade evidence.

## Integrity Flow

The frontend emits low-cost integrity events from browser state:

- fullscreen exit
- screen share stopped
- non-monitor display surface when exposed by the browser
- repeated mobile-phone detection
- repeated multiple-person detection
- large code jumps
- suspicious paste/clipboard patterns
- no clarifying question before coding

The backend stores normalized evidence in `ProctoringFlags` and anti-cheat events. Skin-color fallback face telemetry is setup-quality evidence only and should not be punitive.

## Reporting Flow

1. Session ends.
2. Analysis job loads turns, technical submissions, client metrics, and integrity events.
3. No candidate evidence returns a no-evidence report with score zero.
4. Technical reports include submission matrix, mistakes, weak topics, ideal solution, complexity diff, annotations, and next drill.
5. Candidate and recruiter payloads are persisted through `ReportArtifacts`.
6. The report page renders transcript plus tabs instead of a single generic score page.

## CI And Local Gates

There is no external CI requirement in this repo snapshot. Use zero-extra-infra local gates:

- Python compile for touched backend modules.
- Frontend `npm run lint` (`tsc --noEmit`).
- Import/dead-code scan with `rg`.
- Manual browser QA for technical preflight, mock interview, report tabs, dashboard CTAs, and mobile/desktop layouts.
