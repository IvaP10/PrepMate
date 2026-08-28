"""Local PrepMate application server.

The desktop shell starts this process on localhost.  It owns the local SQLite
storage and interview/report workflows; the only remote dependency is the AI
provider selected in Local Settings.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response as StarletteResponse

from config import settings
from database import (
    close_connection_pool,
    ensure_local_schema,
    get_db_connection,
    init_connection_pool,
    return_db_connection,
    verify_local_schema,
)
from local_runtime import (
    api_token_matches,
    configured_api_token,
    get_local_preferences,
    is_allowed_local_origin,
    is_loopback_host,
    provider_requires_api_key,
)
from local_execution import executor_status
from local_settings_api import router as local_settings_router
from readiness_contract import build_feature_capabilities, build_flow_readiness_payload
from local_runtime import local_user
from user_profile import router as profile_router
from workspace_api import router as workspace_router
from interview import router as interview_router
from blueprint_api import router as blueprint_router
from pre_interview import router as pre_interview_router
from technical_mode import router as technical_router
from analysis import router as analysis_router
from websocket_manager import ConnectionManager

logger = logging.getLogger("prepmate.local-app")
PROCESS_STARTED_AT = datetime.now(timezone.utc)
APP_VERSION = "0.1.0-alpha.1"
ws_manager = ConnectionManager()
_worker_task: asyncio.Task | None = None
_worker_stop_event: asyncio.Event | None = None


async def _start_local_worker() -> None:
    global _worker_task, _worker_stop_event
    if settings.ENVIRONMENT == "test" or not settings.DEVELOPMENT_AUTO_WORKER:
        return
    from local_worker import run_local_workers

    _worker_stop_event = asyncio.Event()
    _worker_task = asyncio.create_task(
        run_local_workers(_worker_stop_event),
        name="prepmate-local-workers",
    )
    await asyncio.sleep(0.15)
    if _worker_task.done():
        try:
            _worker_task.result()
        except Exception:
            logger.exception("Local workers exited during startup")
        return
    logger.info("Local report, technical, and resume worker started")


async def _stop_local_worker() -> None:
    global _worker_task, _worker_stop_event
    if _worker_stop_event is not None:
        _worker_stop_event.set()
    if _worker_task is not None:
        try:
            await asyncio.wait_for(_worker_task, timeout=10)
        except asyncio.TimeoutError:
            _worker_task.cancel()
            await asyncio.gather(_worker_task, return_exceptions=True)
        except Exception:
            logger.exception("Local workers failed during shutdown")
    _worker_task = None
    _worker_stop_event = None


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_connection_pool()
    ensure_local_schema()
    await _start_local_worker()
    logger.info("PrepMate desktop storage: %s", verify_local_schema().get("revision"))
    try:
        yield
    finally:
        await _stop_local_worker()
        close_connection_pool()


app = FastAPI(
    title="PrepMate Desktop",
    description="Local interview practice, technical rounds, scoring, reports, and coaching.",
    version=APP_VERSION,
    lifespan=lifespan,
    docs_url="/docs" if settings.ENVIRONMENT == "development" and not configured_api_token() else None,
    redoc_url=None,
)
app.state.ws_manager = ws_manager


class RequestTracingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = str(request.headers.get("X-Request-ID") or "").strip()
        if len(request_id) < 8 or len(request_id) > 64:
            request_id = str(uuid.uuid4())
        request.state.request_id = request_id
        started = time.perf_counter()
        response: StarletteResponse = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        logger.debug("%s %s %s %.1fms", request.method, request.url.path, response.status_code, (time.perf_counter() - started) * 1000)
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response: StarletteResponse = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; base-uri 'self'; object-src 'none'; frame-ancestors 'none'; "
            "img-src 'self' data: blob:; media-src 'self' data: blob:; "
            "connect-src 'self' http://127.0.0.1:* http://localhost:*; "
            "script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'"
        )
        response.headers["Permissions-Policy"] = "camera=(self), microphone=(self), display-capture=(self), geolocation=()"
        return response


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        content_length = request.headers.get("content-length")
        try:
            too_large = int(content_length or "0") > settings.MAX_REQUEST_BODY_MB * 1024 * 1024
        except ValueError:
            too_large = False
        if too_large:
            return JSONResponse(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, content={"detail": "Request body is too large"})
        return await call_next(request)


class LocalAccessMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        host = request.url.hostname or request.headers.get("host", "")
        if not is_loopback_host(host):
            return JSONResponse(status_code=403, content={"detail": "PrepMate only accepts loopback requests"})

        origin = request.headers.get("origin")
        if origin and not is_allowed_local_origin(origin):
            return JSONResponse(status_code=403, content={"detail": "Request origin is not allowed"})

        if request.method != "OPTIONS" and configured_api_token() and request.url.path != "/live":
            if not api_token_matches(request.headers.get("X-PrepMate-Token") or request.headers.get("X-InterAI-Token")):
                return JSONResponse(status_code=401, content={"detail": "Desktop session token is missing or invalid"})
        return await call_next(request)


app.add_middleware(RequestSizeLimitMiddleware)
app.add_middleware(LocalAccessMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[],
    allow_origin_regex=r"^https?://(?:127\.0\.0\.1|localhost)(?::\d+)?$",
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-Request-ID", "X-PrepMate-Token", "X-InterAI-Token", "Idempotency-Key"],
)
app.add_middleware(RequestTracingMiddleware)
app.add_middleware(SecurityHeadersMiddleware)


def _request_id(request: Request) -> str:
    return str(getattr(request.state, "request_id", "") or "")


def _error_code(status_code: int) -> str:
    if status_code == 404:
        return "not_found"
    if status_code == 409:
        return "conflict"
    if status_code == 429:
        return "rate_limited"
    return "request_failed" if status_code < 500 else "internal_failure"


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    code = _error_code(exc.status_code)
    return JSONResponse(status_code=exc.status_code, content={
        "detail": exc.detail,
        "request_id": _request_id(request),
        "error": {"code": code, "message": str(exc.detail), "retryable": code == "rate_limited"},
    }, headers=exc.headers)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    detail = str((exc.errors() or [{}])[0].get("msg") or "Request validation failed")
    return JSONResponse(status_code=422, content={
        "detail": detail,
        "errors": exc.errors(),
        "request_id": _request_id(request),
        "error": {"code": "validation_error", "message": detail, "retryable": False},
    })


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled local request failure request_id=%s", _request_id(request))
    return JSONResponse(status_code=500, content={
        "detail": "An unexpected error occurred",
        "request_id": _request_id(request),
        "error": {"code": "internal_failure", "message": "An unexpected error occurred", "retryable": True},
    })


app.include_router(profile_router, prefix="/api/profile")
app.include_router(workspace_router, prefix="/api/workspace")
app.include_router(interview_router, prefix="/api/interview")
app.include_router(blueprint_router)
app.include_router(pre_interview_router)
app.include_router(technical_router)
app.include_router(analysis_router)
app.include_router(local_settings_router)


def _local_checks() -> dict[str, dict[str, Any]]:
    preferences = get_local_preferences()
    provider = str(preferences.get("provider") or "")
    endpoint = str(preferences.get("endpoint") or "")
    key_ready = bool(preferences.get("has_api_key")) or not provider_requires_api_key(provider, endpoint)
    provider_ready = bool(provider and preferences.get("model") and key_ready)
    try:
        schema = verify_local_schema()
        storage_check: dict[str, Any] = {"healthy": True, "storage": "sqlite", **schema}
        # Merely opening the app or checking readiness must not access secure
        # storage. The AES key is requested lazily by the first sensitive save.
        storage_check["field_encryption"] = "deferred-os-keychain-aes-gcm"
        storage_check["secure_storage_access"] = "deferred_until_save"
    except Exception as exc:
        logger.error("Local storage readiness failed: %s", type(exc).__name__)
        storage_check = {"healthy": False, "storage": "sqlite", "reason": "Local storage or keychain is unavailable"}

    if settings.ENVIRONMENT == "test":
        worker_alive = True
        worker_process = {"managed": False, "state": "test"}
    else:
        worker_alive = bool(_worker_task is not None and not _worker_task.done())
        worker_process = {
            "managed": True,
            "state": "running" if worker_alive else "stopped",
            "error": (
                type(_worker_task.exception()).__name__
                if _worker_task is not None and _worker_task.done() and not _worker_task.cancelled() and _worker_task.exception()
                else None
            ),
        }

    runner = executor_status()
    content_ready = bool(settings.TECHNICAL_ALLOW_AUTHORED_FALLBACK)
    content_count = 0
    connection = None
    try:
        connection = get_db_connection()
        row = connection.execute("SELECT COUNT(*) FROM TechnicalProblemBank WHERE status = 'active'").fetchone()
        content_count = int(row[0] or 0) if row else 0
        content_ready = content_ready or content_count > 0
    except Exception:
        logger.debug("Technical content readiness query failed", exc_info=True)
    finally:
        if connection is not None:
            return_db_connection(connection)
    checks = {
        "database": storage_check,
        "provider": {
            "healthy": provider_ready,
            "configured": provider_ready,
            "provider": provider,
            "model": preferences.get("model"),
            "voice_transcription": provider == "openai",
        },
        "workers": {
            "healthy": worker_alive,
            "required": True,
            "process": worker_process,
            "workers": {
                "analysis": {"healthy": worker_alive},
                "technical": {"healthy": worker_alive},
                "resume": {"healthy": worker_alive},
            },
            "stuck_jobs": {},
        },
        "code_runner": {**runner, "required": True},
        "technical_content": {
            "healthy": content_ready,
            "required": True,
            "active_problem_count": content_count,
            "source": "active-bank" if content_count else "bundled-fallback",
        },
    }
    return checks


def collect_readiness() -> dict[str, Any]:
    checks = _local_checks()
    ready = bool(checks["database"]["healthy"] and checks["provider"]["healthy"] and checks["workers"]["healthy"])
    return {
        "status": "ready" if ready else "not_ready",
        "ready": ready,
        "time": datetime.now(timezone.utc).isoformat(),
        "checks": checks,
        "features": build_feature_capabilities(checks),
        "runtime": "desktop",
    }


def _flow_readiness(flow: str, checks: dict[str, Any], input_mode: str = "text") -> dict[str, Any]:
    selected = {
        "storage": checks["database"],
        "provider": checks["provider"],
        "workers": checks["workers"],
    }
    if flow == "technical":
        selected["technical_content"] = checks["technical_content"]
        selected["code_runner"] = checks["code_runner"]
    elif input_mode == "voice" and not bool(selected["provider"].get("voice_transcription")):
        selected["provider"] = {
            **selected["provider"],
            "healthy": False,
            "reason": "Voice interviews currently require OpenAI transcription.",
        }
    return build_flow_readiness_payload(flow, selected, recovery_grace_seconds=settings.SESSION_RECOVERY_GRACE_SECONDS)


@app.get("/live")
async def live():
    return {"status": "alive", "runtime": "desktop", "time": datetime.now(timezone.utc).isoformat(), "started_at": PROCESS_STARTED_AT.isoformat()}


@app.get("/ready")
async def ready():
    payload = collect_readiness()
    return JSONResponse(status_code=200 if payload["ready"] else 503, content=payload)


@app.get("/api/preflight")
async def flow_preflight(flow: str = "interview", input_mode: str = "text"):
    normalized = str(flow or "").strip().lower()
    if normalized not in {"interview", "technical"}:
        raise HTTPException(status_code=422, detail="Flow must be interview or technical")
    normalized_input = str(input_mode or "").strip().lower()
    if normalized_input not in {"voice", "text"}:
        raise HTTPException(status_code=422, detail="Input mode must be voice or text")
    checks = _local_checks()
    payload = _flow_readiness(normalized, checks, normalized_input)
    payload["input_mode"] = normalized_input
    return JSONResponse(status_code=200 if payload["ready"] else 503, content=payload)


class BrowserPreflightRequest(BaseModel):
    blueprint_id: str = Field(min_length=8, max_length=64)
    flow: str = Field(pattern="^(interview|technical)$")
    input_mode: str = Field(default="text", pattern="^(voice|text)$")
    camera_ready: bool
    microphone_ready: bool
    microphone_level_detected: bool
    screen_share_ready: bool
    network_ready: bool
    error_codes: list[str] = Field(default_factory=list, max_length=12)


@app.post("/api/preflight")
async def persist_flow_preflight(request: BrowserPreflightRequest, current_user: dict = Depends(local_user)):
    readiness = _flow_readiness(request.flow, _local_checks(), request.input_mode)
    if not readiness["ready"]:
        return JSONResponse(status_code=503, content=readiness)
    browser_ready = (
        request.network_ready
        and (
            request.input_mode != "voice"
            or (request.microphone_ready and request.microphone_level_detected)
        )
    )
    if not browser_ready:
        raise HTTPException(status_code=422, detail="Browser preflight requirements are incomplete")

    preflight_id = str(uuid.uuid4())
    connection = get_db_connection()
    cursor = connection.cursor()
    try:
        cursor.execute(
            """
            SELECT interview_type, status, expires_at,
                   (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP) AS is_unexpired
            FROM InterviewBlueprints
            WHERE blueprint_id = ? AND user_id = ?
            """,
            (request.blueprint_id, current_user["user_id"]),
        )
        blueprint = cursor.fetchone()
        if not blueprint:
            raise HTTPException(status_code=404, detail="Interview blueprint not found")
        blueprint_flow = "technical" if "technical" in str(blueprint[0] or "").lower() else "interview"
        if str(blueprint[1] or "").lower() != "ready" or not bool(blueprint[3]):
            raise HTTPException(status_code=409, detail="Interview blueprint is not ready")
        if blueprint_flow != request.flow:
            raise HTTPException(status_code=409, detail="Preflight flow does not match the blueprint")
        selected = readiness["checks"]
        cursor.execute(
            """
            INSERT INTO AttemptPreflightChecks (
                preflight_id, user_id, blueprint_id, flow, input_mode, camera_ready,
                microphone_ready, microphone_level_detected, screen_share_ready,
                network_ready, backend_ready, provider_ready, sandbox_ready,
                worker_ready, error_codes, created_at, expires_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, TRUE, ?, ?, ?, ?, CURRENT_TIMESTAMP, datetime(CURRENT_TIMESTAMP, '+5 minutes'))
            RETURNING expires_at
            """,
            (
                preflight_id, current_user["user_id"], request.blueprint_id, request.flow, request.input_mode,
                request.camera_ready, request.microphone_ready, request.microphone_level_detected,
                request.screen_share_ready, request.network_ready,
                bool(selected["provider"]["healthy"]),
                bool(selected.get("code_runner", {"healthy": True})["healthy"]),
                bool(selected["workers"]["healthy"]), json.dumps(request.error_codes),
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
    return {**readiness, "input_mode": request.input_mode, "preflight_id": preflight_id, "blueprint_id": request.blueprint_id, "expires_at": expires_at.isoformat() if hasattr(expires_at, "isoformat") else str(expires_at)}


@app.get("/health")
async def health():
    payload = collect_readiness()
    return {**payload, "status": "healthy" if payload["ready"] else "degraded", "checks": {**payload["checks"], "websocket_connections": len(ws_manager.active_connections)}}


@app.get("/api/status")
async def public_status():
    payload = await health()
    checks = payload["checks"]
    return {
        "service": "PrepMate Desktop",
        "status": payload["status"],
        "updated_at": payload["time"],
        "runtime": "local",
        "features": payload.get("features", []),
        "components": {
            "local_storage": "operational" if checks["database"]["healthy"] else "degraded",
            "ai_provider": "configured" if checks["provider"]["healthy"] else "not_configured",
            "code_runner": "operational" if checks["code_runner"]["healthy"] else "unavailable",
            "background_processing": "operational" if checks["workers"]["healthy"] else "degraded",
        },
    }


@app.get("/")
async def root():
    return {"service": "PrepMate Desktop", "version": APP_VERSION, "status": "running", "storage": "local"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="127.0.0.1", port=settings.PORT, reload=False, log_level="info")
