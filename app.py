# ============================================================================
# MODULE: app.py
# PURPOSE: FastAPI entrypoint. Wires lifespan (DB/Redis/observability + bg
#          subscription sweeper), security headers, CORS, all router mounts,
#          and /live, /ready, /health, /api/status, / endpoints.
# STRUCTURE:
#   - lifespan() context manager (lines 45-67)
#   - SecurityHeadersMiddleware (lines 88-95)
#   - CORS middleware (lines 100-105)
#   - global_exception_handler (lines 108-113)
#   - Router mounts (lines 116-122)
#   - liveness/readiness/status endpoints
# ENDPOINTS:
#   - GET  /live       -> process-only liveness
#   - GET  /ready      -> production dependency/readiness gate
#   - GET  /health     -> backward-compatible readiness document
#   - GET  /api/status -> public_status()
#   - GET  /           -> root()
#   - (all other routes injected by routers under /api/*)
# DEPENDS ON: config, database, redis_client, auth, user_profile, workspace_api,
#             payment, interview, pre_interview, technical_mode, websocket_manager,
#             background_tasks, observability
# CONSUMED BY: uvicorn entrypoint (uvicorn app:app)
# DATA TABLES: WorkerHeartbeats/AnalysisJobs/TechnicalExecutionJobs via /ready;
#              routers handle the rest
# ============================================================================

from dotenv import load_dotenv
import os
import secrets
import json
import re
import time
import uuid
load_dotenv(os.path.join(os.path.dirname(__file__), "key.env"))

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, Field
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import ipaddress
from urllib.parse import urlparse
import uvicorn
import logging
import asyncio
import httpx
import threading
import sys
from pathlib import Path
from typing import Any, Optional
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response as StarletteResponse

from config import settings
from database import init_connection_pool, close_connection_pool, ensure_runtime_schema, verify_schema_migrations, get_db_connection, return_db_connection
from readiness_contract import build_flow_readiness_payload
from redis_client import init_redis_client, close_redis
from auth import CSRF_COOKIE_NAME, COOKIE_NAME, get_current_user, router as auth_router
from user_profile import router as profile_router
from workspace_api import router as workspace_router
from payment import (
    _razorpay_checkout_ready,
    _razorpay_missing_config,
    router as payment_router,
)
from interview import router as interview_router
from blueprint_api import router as blueprint_router
from pre_interview import router as pre_interview_router
from technical_mode import router as technical_router
from analysis import router as analysis_router
from websocket_manager import ConnectionManager
from background_tasks import check_expired_subscriptions, process_notification_reminders, cleanup_stale_interviews
from observability import active_http_requests, init_observability, observe_http_request, observe_readiness, prometheus_metrics
from streaming_tts import prewarm_speech_pipeline

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("interai")

_background_tasks = []

async def periodic_connection_cleanup(ws_mgr: ConnectionManager) -> None:
    while True:
        try:
            await asyncio.sleep(60)
            ws_mgr.cleanup_stale_connections()
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error("Error in periodic connection cleanup: %s", str(e))


async def warm_interview_speech() -> None:
    try:
        await asyncio.wait_for(
            prewarm_speech_pipeline(),
            timeout=max(10, settings.KOKORO_PREWARM_TIMEOUT_SECONDS),
        )
    except asyncio.TimeoutError:
        logger.error("Interview speech warmup timed out; text fallback remains available")


@asynccontextmanager
async def lifespan(app: FastAPI):

    development_worker_process = None
    init_connection_pool()
    if settings.ENVIRONMENT in {"development", "test"}:
        ensure_runtime_schema()
    else:
        logger.info("Skipping runtime schema mutation outside development/test; run migrations before deploy")
        verify_schema_migrations()
    init_redis_client()
    _background_tasks.clear()

    if settings.ENVIRONMENT == "development" and settings.DEVELOPMENT_AUTO_WORKER:
        worker_path = Path(__file__).resolve().with_name("worker.py")
        development_worker_process = await asyncio.create_subprocess_exec(
            sys.executable,
            str(worker_path),
            cwd=str(worker_path.parent),
        )
        logger.info("Development durable worker process started")

    task = asyncio.create_task(check_expired_subscriptions())
    _background_tasks.append(task)
    logger.info("Background subscription checker started")

    notification_task = asyncio.create_task(process_notification_reminders())
    _background_tasks.append(notification_task)
    logger.info("Background notification preferences processor started")

    cleanup_task = asyncio.create_task(periodic_connection_cleanup(ws_manager))
    _background_tasks.append(cleanup_task)
    logger.info("Background connection and session metadata cleaner started")

    stale_cleaner_task = asyncio.create_task(cleanup_stale_interviews())
    _background_tasks.append(stale_cleaner_task)
    logger.info("Background stale interview cleaner started")

    if settings.ENVIRONMENT != "test":
        speech_warmup_task = asyncio.create_task(
            warm_interview_speech(),
            name="interview-speech-warmup",
        )
        _background_tasks.append(speech_warmup_task)
        logger.info("Interview speech warmup started in the background")

    logger.info("Application started successfully")

    try:
        yield
    finally:
        if development_worker_process and development_worker_process.returncode is None:
            development_worker_process.terminate()
            try:
                await asyncio.wait_for(development_worker_process.wait(), timeout=10)
            except asyncio.TimeoutError:
                development_worker_process.kill()
                await development_worker_process.wait()
        for task in _background_tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.warning("Background task failed during shutdown", exc_info=True)
        _background_tasks.clear()
        close_connection_pool()
        close_redis()
        logger.info("Application shutdown complete")

_docs_url = "/docs" if settings.ENVIRONMENT == "development" else None
_redoc_url = "/redoc" if settings.ENVIRONMENT == "development" else None

app = FastAPI(
    title="InterAI Backend",
    description="Backend for AI interview platform",
    version="2.0.0",
    lifespan=lifespan,
    docs_url=_docs_url,
    redoc_url=_redoc_url,
)
init_observability(app)

ws_manager = ConnectionManager()
app.state.ws_manager = ws_manager

_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,63}$")


class RequestTracingMiddleware(BaseHTTPMiddleware):
    """Attach a safe request identifier and emit privacy-safe structured timing logs."""

    async def dispatch(self, request: Request, call_next):
        supplied = str(request.headers.get("X-Request-ID") or "").strip()
        request_id = supplied if _REQUEST_ID_PATTERN.fullmatch(supplied) else str(uuid.uuid4())
        request.state.request_id = request_id
        started = time.perf_counter()
        active_http_requests(1)
        status_code = 500
        try:
            response: StarletteResponse = await call_next(request)
            status_code = response.status_code
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            duration = time.perf_counter() - started
            active_http_requests(-1)
            route = getattr(request.scope.get("route"), "path", None) or "unmatched"
            observe_http_request(request.method, route, status_code, duration)
            logger.info(json.dumps({
                "event": "http_request",
                "request_id": request_id,
                "method": request.method,
                "route": route,
                "status_code": status_code,
                "latency_ms": round(duration * 1000, 2),
            }, separators=(",", ":")))

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response: StarletteResponse = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        response.headers["Cross-Origin-Resource-Policy"] = "same-site"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "base-uri 'self'; "
            "object-src 'none'; "
            "frame-ancestors 'none'; "
            "img-src 'self' data: blob: https:; "
            "media-src 'self' data: blob:; "
            "connect-src 'self' https: ws: wss:; "
            "script-src 'self' 'unsafe-inline' https://checkout.razorpay.com; "
            "style-src 'self' 'unsafe-inline'; "
            "frame-src https://api.razorpay.com https://checkout.razorpay.com"
        )
        if settings.ENVIRONMENT == "production":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains; preload"
        response.headers["Permissions-Policy"] = (
            "camera=(self), microphone=(self), display-capture=(self), "
            "geolocation=(), payment=(self), usb=(), serial=(), bluetooth=()"
        )
        return response

class CSRFMiddleware(BaseHTTPMiddleware):
    _unsafe_methods = {"POST", "PUT", "PATCH", "DELETE"}
    _exempt_paths = {
        "/api/auth/signup",
        "/api/auth/login",
        "/api/auth/google",
        "/api/auth/forgot-password",
        "/api/auth/reset-password",
        "/api/auth/verify-email",
        "/api/payment/razorpay/webhook",
    }

    async def dispatch(self, request: Request, call_next):
        path = request.url.path.rstrip("/") or "/"
        if request.method in self._unsafe_methods and path not in self._exempt_paths:
            session_cookie = request.cookies.get(COOKIE_NAME)
            if session_cookie:
                csrf_cookie = request.cookies.get(CSRF_COOKIE_NAME)
                csrf_header = request.headers.get("X-CSRF-Token")
                if not csrf_cookie or not csrf_header or not secrets.compare_digest(csrf_cookie, csrf_header):
                    return JSONResponse(
                        status_code=status.HTTP_403_FORBIDDEN,
                        content={"detail": "Invalid CSRF token"}
                    )
        return await call_next(request)

class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    @staticmethod
    def _payload_too_large_response() -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            content={
                "detail": f"Request body exceeds {settings.MAX_REQUEST_BODY_MB} MB",
                "error": {
                    "code": "payload_too_large",
                    "message": f"Request body exceeds {settings.MAX_REQUEST_BODY_MB} MB",
                    "retryable": False,
                },
            },
        )

    async def dispatch(self, request: Request, call_next):
        content_length = request.headers.get("content-length")
        max_bytes = settings.MAX_REQUEST_BODY_MB * 1024 * 1024
        try:
            body_size = int(content_length or "0")
        except ValueError:
            body_size = 0
        if body_size > max_bytes:
            return self._payload_too_large_response()

        received_bytes = 0
        original_receive = request._receive

        async def limited_receive():
            nonlocal received_bytes
            message = await original_receive()
            if message.get("type") == "http.request":
                received_bytes += len(message.get("body") or b"")
                if received_bytes > max_bytes:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"Request body exceeds {settings.MAX_REQUEST_BODY_MB} MB",
                    )
            return message

        request._receive = limited_receive
        try:
            return await call_next(request)
        except HTTPException as exc:
            if exc.status_code == status.HTTP_413_REQUEST_ENTITY_TOO_LARGE:
                return self._payload_too_large_response()
            raise

app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(CSRFMiddleware)
app.add_middleware(RequestSizeLimitMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.ALLOWED_ORIGINS.split(",") if origin.strip()],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Requested-With", "X-CSRF-Token", "X-Request-ID", "Idempotency-Key"],
)
app.add_middleware(RequestTracingMiddleware)


def _request_id(request: Request) -> str:
    return str(getattr(request.state, "request_id", "") or "")

def _error_code_for_status(status_code: int) -> str:
    if status_code == status.HTTP_400_BAD_REQUEST:
        return "validation_error"
    if status_code == status.HTTP_401_UNAUTHORIZED:
        return "unauthorized"
    if status_code == status.HTTP_403_FORBIDDEN:
        return "forbidden"
    if status_code == status.HTTP_404_NOT_FOUND:
        return "not_found"
    if status_code == status.HTTP_409_CONFLICT:
        return "conflict"
    if status_code == status.HTTP_429_TOO_MANY_REQUESTS:
        return "rate_limited"
    if status_code in {status.HTTP_408_REQUEST_TIMEOUT, status.HTTP_502_BAD_GATEWAY, status.HTTP_503_SERVICE_UNAVAILABLE, status.HTTP_504_GATEWAY_TIMEOUT}:
        return "retryable"
    return "internal_failure" if status_code >= 500 else "request_failed"


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    code = _error_code_for_status(exc.status_code)
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "detail": exc.detail,
            "request_id": _request_id(request),
            "error": {
                "code": code,
                "message": exc.detail,
                "retryable": code in {"rate_limited", "retryable"},
            },
        },
        headers=exc.headers,
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    public_errors = [
        {
            "type": str(error.get("type") or "validation_error"),
            "loc": [str(value) for value in (error.get("loc") or [])],
            "msg": str(error.get("msg") or "Invalid request"),
        }
        for error in exc.errors()
    ]
    detail = public_errors[0]["msg"] if public_errors else "Request validation failed"
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "detail": detail,
            "errors": public_errors,
            "request_id": _request_id(request),
            "error": {
                "code": "validation_error",
                "message": detail,
                "retryable": False,
            },
        },
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    request_id = _request_id(request)
    logger.exception("Unhandled request failure request_id=%s", request_id)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "detail": "An unexpected error occurred",
            "request_id": request_id,
            "error": {
                "code": "internal_failure",
                "message": "An unexpected error occurred",
                "retryable": True,
            },
        },
    )

app.include_router(auth_router, prefix="/api/auth")
app.include_router(profile_router, prefix="/api/profile")
app.include_router(workspace_router, prefix="/api/workspace")
app.include_router(payment_router, prefix="/api/payment")
app.include_router(interview_router, prefix="/api/interview")
app.include_router(blueprint_router)
app.include_router(pre_interview_router)
app.include_router(technical_router)
app.include_router(analysis_router)

PROCESS_STARTED_AT = datetime.now(timezone.utc)


def _database_migration_check() -> dict:
    """Verify both connectivity and the complete, exact Alembic contract."""
    from database import ALEMBIC_HEAD_REVISION

    result = verify_schema_migrations()
    return {
        "healthy": result.get("revision") == ALEMBIC_HEAD_REVISION,
        "revision": result.get("revision"),
        "expected_revision": ALEMBIC_HEAD_REVISION,
    }


def _redis_check() -> dict:
    from redis_client import get_redis_client

    client = get_redis_client()
    if client is None or client.ping() is not True:
        raise RuntimeError("redis_ping_failed")
    return {"healthy": True}


def _worker_and_job_check() -> dict:
    """Require both worker roles and flag work that survived well past a lease."""
    from database import get_db_connection, return_db_connection

    max_age = max(10, int(settings.WORKER_HEARTBEAT_MAX_AGE_SECONDS))
    connection = get_db_connection()
    cursor = connection.cursor()
    try:
        cursor.execute(
            """
            SELECT worker_type,
                   ROUND(EXTRACT(EPOCH FROM (clock_timestamp() - MAX(heartbeat_at)))::numeric, 3)
            FROM WorkerHeartbeats
            WHERE worker_type IN ('analysis', 'technical')
            GROUP BY worker_type
            """
        )
        ages = {str(row[0]): float(row[1]) for row in cursor.fetchall()}

        cursor.execute(
            """
            SELECT
                COUNT(*) FILTER (
                    WHERE status = 'running'
                      AND (lease_expires_at IS NULL
                           OR lease_expires_at < NOW() - (%s * INTERVAL '1 second'))
                ),
                COUNT(*) FILTER (
                    WHERE status = 'queued'
                      AND COALESCE(next_attempt_at, created_at)
                          < NOW() - (%s * INTERVAL '1 second')
                ),
                COUNT(*) FILTER (WHERE status = 'queued'),
                COALESCE(MAX(EXTRACT(EPOCH FROM (NOW() - COALESCE(next_attempt_at, created_at))))
                    FILTER (WHERE status = 'queued'), 0)
            FROM AnalysisJobs
            """,
            (max_age, max_age * 2),
        )
        analysis_row = cursor.fetchone()

        cursor.execute(
            """
            SELECT
                COUNT(*) FILTER (
                    WHERE status IN ('leased', 'running')
                      AND (lease_expires_at IS NULL
                           OR lease_expires_at < NOW() - (%s * INTERVAL '1 second'))
                ),
                COUNT(*) FILTER (
                    WHERE status = 'queued'
                      AND COALESCE(next_attempt_at, created_at)
                          < NOW() - (%s * INTERVAL '1 second')
                ),
                COUNT(*) FILTER (WHERE status = 'queued'),
                COALESCE(MAX(EXTRACT(EPOCH FROM (NOW() - COALESCE(next_attempt_at, created_at))))
                    FILTER (WHERE status = 'queued'), 0)
            FROM TechnicalExecutionJobs
            """,
            (max_age, max_age * 2),
        )
        technical_row = cursor.fetchone()
    finally:
        cursor.close()
        return_db_connection(connection)

    workers = {
        worker_type: {
            # PostgreSQL NOW() is fixed at transaction start. A heartbeat
            # committed after that point can therefore appear fractionally in
            # the future on a reused pooled connection. Treat that harmless
            # race as age zero instead of failing the public preflight.
            "healthy": worker_type in ages and ages[worker_type] <= max_age,
            "heartbeat_age_seconds": max(0.0, ages[worker_type]) if worker_type in ages else None,
            "max_age_seconds": max_age,
        }
        for worker_type in ("analysis", "technical")
    }
    analysis_stuck = (int(analysis_row[0] or 0), int(analysis_row[1] or 0))
    technical_stuck = (int(technical_row[0] or 0), int(technical_row[1] or 0))
    stuck_jobs = {
        "analysis": {"expired_leases": analysis_stuck[0], "overdue_queued": analysis_stuck[1]},
        "technical": {"expired_leases": technical_stuck[0], "overdue_queued": technical_stuck[1]},
    }
    queues = {
        "analysis": {"depth": int(analysis_row[2] or 0), "oldest_age_seconds": float(analysis_row[3] or 0)},
        "technical": {"depth": int(technical_row[2] or 0), "oldest_age_seconds": float(technical_row[3] or 0)},
    }
    return {
        "healthy": all(item["healthy"] for item in workers.values())
        and not any(sum(values.values()) for values in stuck_jobs.values()),
        "workers": workers,
        "stuck_jobs": stuck_jobs,
        "queues": queues,
    }


_OPENAI_PROBE_TTL_SECONDS = 60.0
_OPENAI_PROBE_FAILURE_TTL_SECONDS = 5.0
_openai_probe_cache: dict = {"checked_at": 0.0, "result": None}
_openai_probe_lock = threading.Lock()
_SANDBOX_PROBE_TTL_SECONDS = 30.0
_sandbox_probe_cache: dict = {"checked_at": 0.0, "key": None, "result": None}


def _openai_probe_cache_fresh(cached: Optional[dict], checked_at: Any, now: float) -> bool:
    if not cached:
        return False
    ttl = _OPENAI_PROBE_TTL_SECONDS if cached.get("healthy") else _OPENAI_PROBE_FAILURE_TTL_SECONDS
    return now - float(checked_at or 0) < ttl


def _openai_configuration_check() -> dict:
    models = {
        "chat": settings.OPENAI_CHAT_MODEL,
        "question": settings.OPENAI_QUESTION_MODEL,
        "technical": settings.OPENAI_TECHNICAL_MODEL,
        "evaluation": settings.OPENAI_EVALUATION_MODEL,
        "report": settings.OPENAI_REPORT_MODEL,
        "resume": settings.OPENAI_RESUME_MODEL,
        "transcription": settings.OPENAI_TRANSCRIBE_MODEL,
    }
    configured = bool(str(settings.OPENAI_API_KEY).strip()) and all(
        bool(str(model).strip()) for model in models.values()
    )
    base = {"configured": configured, "models": models, "probe": "model_catalog"}
    if not configured:
        return {**base, "healthy": False, "error": "openai_not_configured"}

    now = time.monotonic()
    cached = _openai_probe_cache.get("result")
    if _openai_probe_cache_fresh(cached, _openai_probe_cache.get("checked_at"), now):
        return {**base, **cached, "cached": True}

    with _openai_probe_lock:
        now = time.monotonic()
        cached = _openai_probe_cache.get("result")
        if _openai_probe_cache_fresh(cached, _openai_probe_cache.get("checked_at"), now):
            return {**base, **cached, "cached": True}
        try:
            response = httpx.get(
                "https://api.openai.com/v1/models",
                headers={"Authorization": f"Bearer {settings.OPENAI_API_KEY}"},
                timeout=5.0,
            )
            response.raise_for_status()
            payload = response.json()
            if isinstance(payload, dict) and isinstance(payload.get("data"), list):
                available = {
                    str(item.get("id"))
                    for item in payload["data"]
                    if isinstance(item, dict) and item.get("id")
                }
            elif isinstance(payload, dict) and payload.get("id"):
                available = {str(payload["id"])}
            else:
                available = set()

            def model_available(model: str) -> bool:
                return any(model == item or item.startswith(f"{model}-") for item in available)

            missing_models = [
                role for role, model in models.items()
                if not model_available(str(model))
            ]
            healthy = bool(available) and not missing_models
            result = {
                "healthy": healthy,
                "available_model_count": len(available),
                "missing_models": missing_models,
            }
            if not healthy:
                result["error"] = "openai_models_unavailable" if missing_models else "openai_probe_invalid_response"
        except Exception:
            result = {"healthy": False, "error": "openai_unavailable"}
        _openai_probe_cache["checked_at"] = time.monotonic()
        _openai_probe_cache["result"] = result
        return {**base, **result, "cached": False}


def _technical_content_check() -> dict:
    required_taxonomies = {
        item.strip().lower()
        for item in str(settings.TECHNICAL_REQUIRED_TAXONOMIES or "").split(",")
        if item.strip()
    }
    try:
        connection = get_db_connection()
        cursor = connection.cursor()
        try:
            cursor.execute(
                """
                SELECT round_type, taxonomy_keys, spec_json, validation_result
                FROM TechnicalProblemBank
                WHERE status = 'active'
                """
            )
            rows = cursor.fetchall() or []
        finally:
            cursor.close()
            return_db_connection(connection)
    except Exception:
        return {
            "healthy": False,
            "error": "technical_problem_bank_unavailable",
            "active_count": 0,
            "coding_count": 0,
            "missing_taxonomies": sorted(required_taxonomies),
            "bank_version": settings.TECHNICAL_BANK_VERSION,
        }

    active_count = 0
    coding_count = 0
    covered: set[str] = set()
    for row in rows:
        validation = row[3] if isinstance(row[3], dict) else {}
        if not (
            validation.get("passed")
            or validation.get("valid")
            or str(validation.get("status") or "").lower() in {"passed", "validated", "active"}
        ):
            continue
        active_count += 1
        if str(row[0] or "").lower() == "coding":
            coding_count += 1
        taxonomy_values = row[1] if isinstance(row[1], list) else []
        spec_json = row[2] if isinstance(row[2], dict) else {}
        taxonomy_values = [*taxonomy_values, spec_json.get("algorithm_pattern") or ""]
        for value in taxonomy_values:
            normalized = str(value or "").lower().replace("_", "-").replace(" ", "-")
            covered.update(
                taxonomy for taxonomy in required_taxonomies
                if taxonomy in normalized
            )

    missing_taxonomies = sorted(required_taxonomies - covered)
    healthy = (
        active_count >= max(1, int(settings.TECHNICAL_MIN_ACTIVE_PROBLEMS))
        and coding_count >= max(1, int(settings.TECHNICAL_MIN_CODING_PROBLEMS))
        and not missing_taxonomies
    )
    return {
        "healthy": healthy,
        "error": None if healthy else "technical_content_incomplete",
        "active_count": active_count,
        "coding_count": coding_count,
        "missing_taxonomies": missing_taxonomies,
        "bank_version": settings.TECHNICAL_BANK_VERSION,
    }


def _is_private_service_url(value: str) -> bool:
    parsed = urlparse(str(value or ""))
    hostname = (parsed.hostname or "").lower()
    if not hostname:
        return False
    if hostname in {"localhost", "127.0.0.1", "::1", "sandbox"}:
        return True
    if "." not in hostname or hostname.endswith((".internal", ".local")):
        return True
    try:
        return ipaddress.ip_address(hostname).is_private
    except ValueError:
        return False


async def _sandbox_executor_check() -> dict:
    base_url = str(settings.PISTON_API_URL or "").rstrip("/")
    expected = {
        runtime.strip().lower()
        for runtime in str(settings.PISTON_EXPECTED_RUNTIMES or "").split(",")
        if runtime.strip()
    }
    private = _is_private_service_url(base_url)
    if not base_url or not private:
        return {
            "healthy": False,
            "private": private,
            "missing_runtimes": sorted(expected),
        }

    cache_key = (
        base_url,
        tuple(sorted(expected)),
        settings.ENVIRONMENT,
        settings.PISTON_API_TOKEN,
    )
    now = time.monotonic()
    cached = _sandbox_probe_cache.get("result")
    if (
        cached
        and _sandbox_probe_cache.get("key") == cache_key
        and now - float(_sandbox_probe_cache.get("checked_at") or 0) < _SANDBOX_PROBE_TTL_SECONDS
    ):
        return {**cached, "cached": True}

    # A real probe includes isolated-container startup. Keep it bounded, but do
    # not use the normal request timeout: cold gVisor/Docker starts can exceed
    # three seconds even when the executor is healthy.
    timeout = min(7.0, max(1.0, float(settings.PISTON_TIMEOUT_SECONDS)))
    headers = (
        {"Authorization": f"Bearer {settings.PISTON_API_TOKEN}"}
        if settings.PISTON_API_TOKEN else {}
    )
    async with httpx.AsyncClient(timeout=timeout) as client:
        health_response = await client.get(
            f"{base_url.removesuffix('/api/v2')}/health",
            headers=headers,
        )
        health_response.raise_for_status()
        health_payload = health_response.json()
        response = await client.get(f"{base_url}/runtimes", headers=headers)
        response.raise_for_status()
        payload = response.json()
    if not isinstance(health_payload, dict) or not health_payload.get("ready"):
        raise RuntimeError("sandbox_health_contract_invalid")
    oci_runtime = str(health_payload.get("oci_runtime") or "").strip().lower()
    secure_runtime = (
        oci_runtime == "runsc"
        and bool(health_payload.get("oci_runtime_available"))
    )
    if not isinstance(payload, list):
        raise RuntimeError("sandbox_runtime_contract_invalid")
    available = set()
    for runtime in payload:
        if not isinstance(runtime, dict):
            continue
        available.add(str(runtime.get("language") or "").strip().lower())
        available.update(
            str(alias).strip().lower()
            for alias in (runtime.get("aliases") or [])
            if str(alias).strip()
        )
    missing = sorted(expected - available)
    execution_probe = False
    if not missing:
        async with httpx.AsyncClient(timeout=timeout) as probe_client:
            probe_response = await probe_client.post(
                f"{base_url}/execute",
                headers=headers,
                json={
                    "language": "python",
                    "version": "3.12",
                    "files": [{"name": "main.py", "content": "print('interai-ready')"}],
                    "stdin": "",
                    "run_timeout": 1_000,
                    "compile_timeout": 1_000,
                },
            )
        probe_response.raise_for_status()
        probe_payload = probe_response.json()
        execution_probe = (
            isinstance(probe_payload, dict)
            and str((probe_payload.get("run") or {}).get("stdout") or "").strip() == "interai-ready"
            and int((probe_payload.get("run") or {}).get("code") or 0) == 0
        )
    result = {
        "healthy": (
            private
            and not missing
            and execution_probe
            and (settings.ENVIRONMENT != "production" or secure_runtime)
        ),
        "private": private,
        "oci_runtime": oci_runtime or None,
        "secure_runtime": secure_runtime,
        "available_runtimes": sorted(runtime for runtime in available if runtime),
        "missing_runtimes": missing,
        "execution_probe": execution_probe,
    }
    _sandbox_probe_cache.update({
        "checked_at": time.monotonic(),
        "key": cache_key,
        "result": result,
    })
    return {**result, "cached": False}


async def _safe_readiness_check(name: str, awaitable) -> tuple[str, dict]:
    try:
        timeout = 8.0 if name == "sandbox_executor" else 3.5
        result = await asyncio.wait_for(awaitable, timeout=timeout)
        return name, result
    except Exception as exc:
        logger.warning("Readiness check failed: %s (%s)", name, type(exc).__name__)
        return name, {"healthy": False, "error": f"{name}_unavailable"}


def _payment_configuration_check() -> dict:
    missing = _razorpay_missing_config()
    return {
        "healthy": _razorpay_checkout_ready(),
        "provider": "razorpay",
        "missing": missing,
        "error": None if not missing else "payment_configuration_incomplete",
    }


async def collect_readiness() -> dict:
    checks = dict(await asyncio.gather(
        _safe_readiness_check("database_migrations", asyncio.to_thread(_database_migration_check)),
        _safe_readiness_check("redis", asyncio.to_thread(_redis_check)),
        _safe_readiness_check("workers_jobs", asyncio.to_thread(_worker_and_job_check)),
        _safe_readiness_check("openai", asyncio.to_thread(_openai_configuration_check)),
        _safe_readiness_check("technical_content", asyncio.to_thread(_technical_content_check)),
        _safe_readiness_check("sandbox_executor", _sandbox_executor_check()),
        _safe_readiness_check("payments", asyncio.to_thread(_payment_configuration_check)),
    ))
    ready = all(bool(check.get("healthy")) for check in checks.values())
    return {
        "status": "ready" if ready else "not_ready",
        "ready": ready,
        "time": datetime.now(timezone.utc).isoformat(),
        "checks": checks,
    }


def _flow_readiness_payload(flow: str, checks: dict) -> dict:
    return build_flow_readiness_payload(
        flow,
        checks,
        recovery_grace_seconds=settings.SESSION_RECOVERY_GRACE_SECONDS,
    )


def _development_auto_reload_enabled() -> bool:
    """Avoid recursive repository polling unless local reload is requested."""
    return (
        settings.ENVIRONMENT == "development"
        and settings.DEVELOPMENT_AUTO_RELOAD
    )


@app.get("/live")
async def live():
    """Process liveness only: deliberately independent of DB, Redis and OpenAI."""
    return {
        "status": "alive",
        "time": datetime.now(timezone.utc).isoformat(),
        "started_at": PROCESS_STARTED_AT.isoformat(),
    }


@app.get("/metrics", include_in_schema=False)
async def metrics(request: Request):
    configured = settings.METRICS_BEARER_TOKEN
    supplied = str(request.headers.get("Authorization") or "")
    if configured and not secrets.compare_digest(supplied, f"Bearer {configured}"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Metrics authentication required")
    observe_readiness(await collect_readiness())
    payload, content_type = prometheus_metrics()
    return StarletteResponse(content=payload, media_type=content_type)


@app.get("/ready")
async def ready():
    payload = await collect_readiness()
    return JSONResponse(
        status_code=status.HTTP_200_OK if payload["ready"] else status.HTTP_503_SERVICE_UNAVAILABLE,
        content=payload,
    )


@app.get("/api/preflight")
async def flow_preflight(flow: str = "interview"):
    normalized = str(flow or "").strip().lower()
    if normalized not in {"interview", "technical"}:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Flow must be interview or technical")
    checks = (await collect_readiness())["checks"]
    payload = _flow_readiness_payload(normalized, checks)
    return JSONResponse(
        status_code=status.HTTP_200_OK if payload["ready"] else status.HTTP_503_SERVICE_UNAVAILABLE,
        content=payload,
    )


class BrowserPreflightRequest(BaseModel):
    blueprint_id: str = Field(min_length=8, max_length=64)
    flow: str = Field(pattern="^(interview|technical)$")
    camera_ready: bool
    microphone_ready: bool
    microphone_level_detected: bool
    screen_share_ready: bool
    network_ready: bool
    error_codes: list[str] = Field(default_factory=list, max_length=12)


@app.post("/api/preflight")
async def persist_flow_preflight(
    request: BrowserPreflightRequest,
    current_user: dict = Depends(get_current_user),
):
    """Re-check backend health and persist a short-lived, start-bound browser preflight."""
    checks = (await collect_readiness())["checks"]
    readiness = _flow_readiness_payload(request.flow, checks)
    if not readiness["ready"]:
        return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content=readiness)
    required_browser_ready = (
        request.camera_ready
        and request.microphone_ready
        and request.microphone_level_detected
        and (request.flow == "interview" or request.screen_share_ready)
        and request.network_ready
    )
    if not required_browser_ready:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Browser preflight requirements are incomplete")

    preflight_id = str(uuid.uuid4())
    connection = get_db_connection()
    cursor = connection.cursor()
    try:
        cursor.execute(
            """
            SELECT interview_type, status, expires_at,
                   (expires_at IS NULL OR expires_at > NOW()) AS is_unexpired
            FROM InterviewBlueprints
            WHERE blueprint_id = %s AND user_id = %s
            """,
            (request.blueprint_id, current_user["user_id"]),
        )
        blueprint = cursor.fetchone()
        if not blueprint:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Interview blueprint not found")
        blueprint_flow = "technical" if "technical" in str(blueprint[0] or "").lower() else "interview"
        if str(blueprint[1] or "").lower() != "ready" or not bool(blueprint[3]):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Interview blueprint is not ready")
        if blueprint_flow != request.flow:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Preflight flow does not match the blueprint")
        selected = readiness["checks"]
        cursor.execute(
            """
            INSERT INTO AttemptPreflightChecks (
                preflight_id, user_id, blueprint_id, flow, camera_ready,
                microphone_ready, microphone_level_detected, screen_share_ready,
                network_ready, backend_ready, openai_ready, sandbox_ready,
                worker_ready, error_codes, created_at, expires_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE, %s, %s, %s, %s, NOW(), NOW() + INTERVAL '5 minutes')
            RETURNING expires_at
            """,
            (
                preflight_id, current_user["user_id"], request.blueprint_id, request.flow,
                request.camera_ready, request.microphone_ready, request.microphone_level_detected,
                request.screen_share_ready, request.network_ready,
                bool(selected.get("openai", {}).get("healthy")),
                bool(selected.get("sandbox_executor", {}).get("healthy")),
                bool(selected.get("workers", {}).get("healthy")),
                json.dumps(request.error_codes),
            ),
        )
        expires_at = cursor.fetchone()[0]
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()
        return_db_connection(connection)
    return {
        **readiness,
        "preflight_id": preflight_id,
        "blueprint_id": request.blueprint_id,
        "expires_at": expires_at.isoformat(),
    }


@app.get("/health")
async def health():
    """Backward-compatible health document; orchestration should use /live and /ready."""
    payload = await collect_readiness()
    return {
        **payload,
        "status": "healthy" if payload["ready"] else "degraded",
        "checks": {
            **payload["checks"],
            "websocket_connections": len(ws_manager.active_connections),
        },
    }


@app.get("/api/status")
async def public_status():
    health_payload = await health()
    checks = health_payload["checks"]
    return {
        "service": "InterAI",
        "status": health_payload["status"],
        "updated_at": health_payload["time"],
        "components": {
            "api": "operational",
            "database_migrations": "operational" if checks["database_migrations"]["healthy"] else "degraded",
            "redis": "operational" if checks["redis"]["healthy"] else "degraded",
            "workers": "operational" if checks["workers_jobs"]["healthy"] else "degraded",
            "llm_router": "operational" if checks["openai"]["healthy"] else "degraded",
            "code_runner": "operational" if checks["sandbox_executor"]["healthy"] else "degraded",
            "payments": "operational" if checks["payments"]["healthy"] else "degraded",
        },
    }

@app.get("/")
async def root():
    return {
        "service": "InterAI Backend",
        "version": "2.0.0",
        "status": "running"
    }

if __name__ == "__main__":
    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=settings.PORT,
        reload=_development_auto_reload_enabled(),
        reload_delay=1.0,
        log_level="info",
    )
