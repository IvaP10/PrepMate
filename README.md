# InterAI

AI-powered interview preparation platform. Real-time video interviews with adaptive questioning, body language analysis, and detailed performance reports.

## What it does

- **Mock & Practice interviews** — WebSocket-based sessions with a dynamic AI interviewer persona. Practice mode gives real-time feedback; mock mode simulates a real interview.
- **Resume parsing** — Upload PDF/DOCX, parse with Docling-first ingestion plus local fallbacks, auto-extract structured data, links, and PII-stripped profile signals.
- **Body language analysis** — MediaPipe FaceMesh for gaze/head tracking, DeepFace for emotion detection, frame-by-frame fidget scoring.
- **Adaptive interview flow** — Knowledge map system builds a topic graph from your resume + job description, adjusts follow-ups based on how you're doing.
- **Payment** — Stripe + Razorpay, webhook-verified.

## Stack

| Layer | Tech |
|-------|------|
| Backend | FastAPI, Python 3.12 |
| Frontend | Next.js, TypeScript, Tailwind |
| Database | PostgreSQL (psycopg2 connection pool) |
| Cache | Redis |
| AI | OpenAI GPT-4o-mini (chat/eval), OpenAI transcription fallback, optional local provider interfaces |
| Vision | MediaPipe, DeepFace, OpenCV |
| Payments | Stripe, Razorpay |
| Auth | JWT + Google OAuth + bcrypt |

## Project layout

```
├── app.py                    # FastAPI entry point
├── config.py                 # Env loading + validation
├── database.py               # Postgres connection pool
├── redis_client.py           # Redis client
├── schema.sql                # Full database schema
│
├── auth.py                   # Signup, login, Google OAuth, JWT
├── user_profile.py           # Profile CRUD
├── dashboard.py              # Stats, jobs, performance trends
├── pre_interview.py          # Resume upload + parsing + AI extraction
├── interview.py              # Interview sessions + WebSocket handler
├── payment.py                # Plans, subscriptions, webhooks
│
├── ai_services.py            # OpenAI calls — transcription, TTS, eval, streaming
├── body_language.py          # MediaPipe + DeepFace face/emotion analysis
├── knowledge_map.py          # Interview topic graph + adaptive flow
├── persona_generator.py      # Dynamic interviewer personality
├── pipeline_orchestrator.py  # Experimental STT → LLM → TTS pipeline adapter
├── streaming_stt.py          # OpenAI transcription adapter; local STT provider work is scaffolded
├── streaming_tts.py          # Kokoro/OpenAI TTS adapter
├── avatar_engine.py          # Audio-only avatar adapter used by the current UI
├── providers.py              # Provider interfaces for STT, TTS, resume parsing, enrichment, eval
├── profile_enrichment.py     # GitHub REST enrichment; LinkedIn scraping intentionally excluded
├── report_generator.py       # Structured ReportV2 generation
├── strictness_config.py      # Difficulty calibration
├── websocket_manager.py      # WS connection management
├── rate_limiter.py           # Per-user rate limiting
├── encryption.py             # Fernet field-level encryption
├── resume_parser.py          # PDF/DOCX text extraction
│
└── Frontend/                 # Next.js app (see Frontend/README if exists)
    ├── app/                  # Pages and routes
    ├── components/           # React components
    ├── hooks/                # Custom hooks (VAD, face check, streaming metrics)
    └── context/              # React context providers
```

## Setup

### Prerequisites

- Python 3.12+
- PostgreSQL
- Redis
- Node.js 18+ (for frontend)

### Environment

Copy the example below into `key.env` at the project root:

```env
OPENAI_API_KEY=
OPENAI_WHISPER_MODEL=gpt-4o-mini-transcribe
STT_PROVIDER=openai
LOCAL_STT_MODEL=nvidia/parakeet-tdt-0.6b-v2
JWT_SECRET=
ENCRYPTION_MASTER_KEY=

PG_DBNAME=ai_interviewer
PG_USER=
PG_PASSWORD=
PG_HOST=localhost
PG_PORT=5432

GOOGLE_CLIENT_ID=

SMTP_EMAIL=
SMTP_PASSWORD=

RAZORPAY_KEY_ID=
RAZORPAY_KEY_SECRET=
RAZORPAY_WEBHOOK_SECRET=

STRIPE_SECRET_KEY=
STRIPE_WEBHOOK_SECRET=

REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0

PORT=8000
ALLOWED_ORIGINS=http://localhost:3000
```

For the frontend, create `Frontend/.env.local`:

```env
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000/api
NEXT_PUBLIC_GOOGLE_CLIENT_ID=your-google-client-id
NEXT_PUBLIC_RAZORPAY_KEY_ID=your-razorpay-key-id
```

> **JWT_SECRET** and **ENCRYPTION_MASTER_KEY** must each be at least 32 characters. Generate with `openssl rand -hex 32`.

### Database

```bash
psql -d ai_interviewer -f schema.sql
```

### Backend

```bash
pip install -r requirements.txt
python app.py
```

### Frontend

```bash
cd Frontend
npm install
npm run dev
```

## API

### Auth — `/api/auth`
| Method | Route | What it does |
|--------|-------|-------------|
| POST | `/signup` | Email/password registration |
| POST | `/login` | Email/password login |
| POST | `/google` | Google OAuth |
| GET | `/verify` | Validate JWT |
| POST | `/refresh` | Refresh JWT |

### Pre-Interview — `/api/pre-interview`
| Method | Route | What it does |
|--------|-------|-------------|
| POST | `/upload-resume-with-job` | Upload resume + select job |
| GET | `/form` | Auto-filled form from resume |
| POST | `/submit-form` | Submit reviewed profile |
| GET | `/profile-status` | Check completion |
| DELETE | `/reset-profile` | Reset and start over |

### Interview — `/api/interview`
| Method | Route | What it does |
|--------|-------|-------------|
| POST | `/start` | Start session |
| WS | `/ws/video/{ticket}` | Real-time interview WebSocket |
| GET | `/report/{id}` | Interview report |
| DELETE | `/cancel/{id}` | Cancel active interview |

### Profile — `/api/profile`
| Method | Route | What it does |
|--------|-------|-------------|
| GET | `/me` | Full profile |
| POST | `/update` | Update profile |
| DELETE | `/resume` | Delete resume |
| GET | `/statistics` | Interview stats |
| GET | `/interview-history` | Past interviews |

### Dashboard — `/api/dashboard`
| Method | Route | What it does |
|--------|-------|-------------|
| GET | `/stats` | Dashboard stats |
| GET | `/jobs` | Job listings |
| POST | `/select-job/{id}` | Select job |
| GET | `/performance-trend` | Performance over time |

### Payment — `/api/payment`
| Method | Route | What it does |
|--------|-------|-------------|
| GET | `/plans` | Available plans |
| POST | `/create-subscription` | Subscribe |
| GET | `/subscription` | Current subscription |
| POST | `/cancel-subscription` | Cancel |
| POST | `/webhook/stripe` | Stripe webhook |
| POST | `/webhook/razorpay` | Razorpay webhook |

## Security notes

- Passwords hashed with bcrypt
- JWT (HS256) with configurable expiry
- Google OAuth token verification via Google's API
- PII stripped from resume data before sending to OpenAI
- Field-level encryption (Fernet/HKDF) for stored resume text
- Parameterized SQL everywhere — no string interpolation
- Rate limiting on uploads and AI calls
- Circuit breaker on OpenAI to handle outages gracefully
- Webhook signature verification for Stripe and Razorpay
- CORS restricted to configured origins
