# ============================================================================
# MODULE: observability.py
# PURPOSE: Sentry init + a single log_ai_event(...) fan-out that writes to
#          AIEventLogs and posts to Langfuse/PostHog.
# STRUCTURE:
#   - init_observability / capture_exception (lines 28-58)
#   - log_ai_event(...) entrypoint (lines 61-89)
#   - _write_ai_event_to_db
#   - _post_json + Langfuse/PostHog senders (lines 176-244)
# ENDPOINTS: none
# DEPENDS ON: config, security_utils, database (lazy)
# CONSUMED BY: app.py, ai_services, llm_router, interview, dashboard
# DATA TABLES: AIEventLogs (write)
# NOTE (Phase 4): extend log_ai_event to upsert hour-bucket rows in `model_telemetry`.
# ============================================================================

from __future__ import annotations

import asyncio
import base64
import httpx
import json
import logging
import threading
import time
import urllib.request
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from config import settings
from security_utils import redact_text, stable_hash

logger = logging.getLogger("observability")

_sentry_ready = False
_otel_ready = False

try:
    from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

    HTTP_REQUESTS = Counter(
        "interai_http_requests_total", "HTTP requests", ("method", "route", "status")
    )
    HTTP_LATENCY = Histogram(
        "interai_http_request_duration_seconds", "HTTP request latency", ("method", "route")
    )
    HTTP_ACTIVE = Gauge("interai_http_requests_active", "Active HTTP requests")
    AI_EVENTS = Counter(
        "interai_ai_events_total", "AI pipeline events", ("event_type", "provider", "success")
    )
    AI_LATENCY = Histogram(
        "interai_ai_event_duration_seconds", "AI event latency", ("event_type", "provider")
    )
    DEPENDENCY_HEALTH = Gauge(
        "interai_dependency_healthy", "Readiness dependency health", ("dependency",)
    )
    WORKER_HEARTBEAT_AGE = Gauge(
        "interai_worker_heartbeat_age_seconds", "Age of the latest durable worker heartbeat", ("worker_type",)
    )
    JOB_QUEUE_DEPTH = Gauge(
        "interai_job_queue_depth", "Queued durable jobs", ("worker_type",)
    )
    JOB_QUEUE_OLDEST_AGE = Gauge(
        "interai_job_queue_oldest_age_seconds", "Age of the oldest queued durable job", ("worker_type",)
    )
    STUCK_JOBS = Gauge(
        "interai_stuck_jobs", "Durable jobs whose lease or queue age exceeded policy", ("worker_type", "reason")
    )
except Exception:  # pragma: no cover - optional dependency guard for constrained tools
    CONTENT_TYPE_LATEST = "text/plain; version=0.0.4; charset=utf-8"
    HTTP_REQUESTS = HTTP_LATENCY = HTTP_ACTIVE = AI_EVENTS = AI_LATENCY = None
    DEPENDENCY_HEALTH = WORKER_HEARTBEAT_AGE = JOB_QUEUE_DEPTH = JOB_QUEUE_OLDEST_AGE = STUCK_JOBS = None


def init_observability(app: Any = None) -> None:
    global _sentry_ready, _otel_ready
    if not _sentry_ready and settings.SENTRY_DSN:
        try:
            import sentry_sdk

            sentry_sdk.init(
                dsn=settings.SENTRY_DSN,
                environment=settings.ENVIRONMENT,
                traces_sample_rate=0.05 if settings.ENVIRONMENT == "production" else 0.0,
            )
            _sentry_ready = True
            logger.info("Sentry initialized")
        except Exception:
            logger.error("Sentry initialization failed")

    if _otel_ready or not settings.OTEL_EXPORTER_OTLP_ENDPOINT:
        return
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
        from opentelemetry.instrumentation.psycopg2 import Psycopg2Instrumentor
        from opentelemetry.instrumentation.redis import RedisInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        provider = TracerProvider(resource=Resource.create({"service.name": settings.OTEL_SERVICE_NAME}))
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
        trace.set_tracer_provider(provider)
        if app is not None:
            FastAPIInstrumentor.instrument_app(app)
        HTTPXClientInstrumentor().instrument()
        Psycopg2Instrumentor().instrument()
        RedisInstrumentor().instrument()
        _otel_ready = True
        logger.info("OpenTelemetry initialized")
    except Exception:
        logger.error("OpenTelemetry initialization failed", exc_info=True)


def observe_http_request(method: str, route: str, status_code: int, duration_seconds: float) -> None:
    if HTTP_REQUESTS is None:
        return
    HTTP_REQUESTS.labels(method=method, route=route, status=str(status_code)).inc()
    HTTP_LATENCY.labels(method=method, route=route).observe(max(0.0, duration_seconds))


def active_http_requests(delta: int) -> None:
    if HTTP_ACTIVE is not None:
        HTTP_ACTIVE.inc(delta)


def observe_readiness(payload: dict) -> None:
    """Project privacy-safe readiness and durable-worker state into Prometheus."""
    if DEPENDENCY_HEALTH is None:
        return
    checks = payload.get("checks") or {}
    for dependency in ("database_migrations", "redis", "openai", "sandbox_executor", "workers_jobs"):
        DEPENDENCY_HEALTH.labels(dependency=dependency).set(
            1 if bool((checks.get(dependency) or {}).get("healthy")) else 0
        )
    workers_jobs = checks.get("workers_jobs") or {}
    workers = workers_jobs.get("workers") or {}
    queues = workers_jobs.get("queues") or {}
    stuck = workers_jobs.get("stuck_jobs") or {}
    for worker_type in ("analysis", "technical"):
        worker = workers.get(worker_type) or {}
        heartbeat_age = worker.get("heartbeat_age_seconds")
        WORKER_HEARTBEAT_AGE.labels(worker_type=worker_type).set(
            float(heartbeat_age) if heartbeat_age is not None else float(worker.get("max_age_seconds") or 0) * 10
        )
        queue = queues.get(worker_type) or {}
        JOB_QUEUE_DEPTH.labels(worker_type=worker_type).set(int(queue.get("depth") or 0))
        JOB_QUEUE_OLDEST_AGE.labels(worker_type=worker_type).set(float(queue.get("oldest_age_seconds") or 0))
        worker_stuck = stuck.get(worker_type) or {}
        for reason in ("expired_leases", "overdue_queued"):
            STUCK_JOBS.labels(worker_type=worker_type, reason=reason).set(int(worker_stuck.get(reason) or 0))


def prometheus_metrics() -> tuple[bytes, str]:
    if HTTP_REQUESTS is None:
        return b"# Prometheus client unavailable\n", CONTENT_TYPE_LATEST
    return generate_latest(), CONTENT_TYPE_LATEST




_telemetry_async_client: httpx.AsyncClient | None = None


def get_telemetry_async_client() -> httpx.AsyncClient:
    global _telemetry_async_client
    if _telemetry_async_client is None:
        _telemetry_async_client = httpx.AsyncClient(timeout=1.5)
    return _telemetry_async_client


_telemetry_tasks = set()


def log_ai_event(
    *,
    event_type: str,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    success: bool = True,
    latency_ms: Optional[int] = None,
    user_id: Optional[str] = None,
    interview_id: Optional[str] = None,
    prompt_tokens: Optional[int] = None,
    output_tokens: Optional[int] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    payload = {
        "event_type": event_type,
        "provider": provider,
        "model": model,
        "success": success,
        "latency_ms": latency_ms,
        "user_id": user_id,
        "interview_id": interview_id,
        "prompt_tokens": prompt_tokens,
        "output_tokens": output_tokens,
        "metadata": metadata or {},
        "timestamp": int(time.time() * 1000),
    }
    if AI_EVENTS is not None:
        event_label = str(event_type or "unknown")[:80]
        provider_label = str(provider or "none")[:40]
        AI_EVENTS.labels(event_type=event_label, provider=provider_label, success=str(bool(success)).lower()).inc()
        if latency_ms is not None:
            AI_LATENCY.labels(event_type=event_label, provider=provider_label).observe(max(0, latency_ms) / 1000)

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        task = loop.create_task(log_ai_event_async_worker(payload))
        _telemetry_tasks.add(task)
        task.add_done_callback(_telemetry_tasks.discard)
    else:
        threading.Thread(target=log_ai_event_sync_worker, args=(payload,), daemon=True).start()


async def log_ai_event_async_worker(payload: Dict[str, Any]) -> None:
    try:
        await asyncio.to_thread(_write_ai_event_to_db, payload)
        await _send_langfuse_event_async(payload)
        await _send_posthog_event_async(payload)
    except Exception as e:
        logger.error("Failed to run async telemetry logging worker: %s", type(e).__name__)



def log_ai_event_sync_worker(payload: Dict[str, Any]) -> None:
    _write_ai_event_to_db(payload)
    _send_langfuse_event(payload)
    _send_posthog_event(payload)


def _write_ai_event_to_db(payload: Dict[str, Any]) -> None:
    try:
        from database import get_db_connection, return_db_connection

        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                INSERT INTO AIEventLogs (
                    user_id, interview_id, event_type, provider, model,
                    prompt_tokens, output_tokens, latency_ms, success, metadata
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    payload.get("user_id"),
                    payload.get("interview_id"),
                    payload.get("event_type"),
                    payload.get("provider"),
                    payload.get("model"),
                    payload.get("prompt_tokens"),
                    payload.get("output_tokens"),
                    payload.get("latency_ms"),
                    payload.get("success"),
                    json.dumps(payload.get("metadata") or {}),
                ),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cursor.close()
            return_db_connection(conn)
    except Exception:
        logger.debug("AI event DB write skipped")


def _post_json(url: str, payload: Dict[str, Any], headers: Dict[str, str]) -> None:
    try:
        if urlparse(url).scheme != "https":
            logger.warning("Telemetry post skipped for non-HTTPS endpoint")
            return
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        urllib.request.urlopen(req, timeout=1.5).close()
    except Exception:
        logger.debug("Telemetry post skipped for %s", url)


async def _post_json_async(url: str, payload: Dict[str, Any], headers: Dict[str, str]) -> None:
    try:
        if urlparse(url).scheme != "https":
            logger.warning("Telemetry post skipped for non-HTTPS endpoint")
            return
        client = get_telemetry_async_client()
        await client.post(url, json=payload, headers=headers)
    except Exception:
        logger.debug("Telemetry post skipped for %s", url)


def _send_langfuse_event(payload: Dict[str, Any]) -> None:
    if not settings.LANGFUSE_PUBLIC_KEY or not settings.LANGFUSE_SECRET_KEY:
        return
    external = _external_payload(payload)
    auth = base64.b64encode(
        f"{settings.LANGFUSE_PUBLIC_KEY}:{settings.LANGFUSE_SECRET_KEY}".encode("utf-8")
    ).decode("ascii")
    _post_json(
        settings.LANGFUSE_HOST.rstrip("/") + "/api/public/ingestion",
        {
            "batch": [
                {
                    "type": "event-create",
                    "timestamp": external["timestamp"],
                    "body": {
                        "name": external["event_type"],
                        "userId": external.get("user_id"),
                        "metadata": external,
                    },
                }
            ]
        },
        {
            "Authorization": f"Basic {auth}",
            "Content-Type": "application/json",
        },
    )


async def _send_langfuse_event_async(payload: Dict[str, Any]) -> None:
    if not settings.LANGFUSE_PUBLIC_KEY or not settings.LANGFUSE_SECRET_KEY:
        return
    external = _external_payload(payload)
    auth = base64.b64encode(
        f"{settings.LANGFUSE_PUBLIC_KEY}:{settings.LANGFUSE_SECRET_KEY}".encode("utf-8")
    ).decode("ascii")
    await _post_json_async(
        settings.LANGFUSE_HOST.rstrip("/") + "/api/public/ingestion",
        {
            "batch": [
                {
                    "type": "event-create",
                    "timestamp": external["timestamp"],
                    "body": {
                        "name": external["event_type"],
                        "userId": external.get("user_id"),
                        "metadata": external,
                    },
                }
            ]
        },
        {
            "Authorization": f"Basic {auth}",
            "Content-Type": "application/json",
        },
    )


def _send_posthog_event(payload: Dict[str, Any]) -> None:
    if not settings.POSTHOG_API_KEY:
        return
    external = _external_payload(payload)
    _post_json(
        settings.POSTHOG_HOST.rstrip("/") + "/capture/",
        {
            "api_key": settings.POSTHOG_API_KEY,
            "event": external["event_type"],
            "distinct_id": external.get("user_id") or "system",
            "properties": external,
        },
        {"Content-Type": "application/json"},
    )


async def _send_posthog_event_async(payload: Dict[str, Any]) -> None:
    if not settings.POSTHOG_API_KEY:
        return
    external = _external_payload(payload)
    await _post_json_async(
        settings.POSTHOG_HOST.rstrip("/") + "/capture/",
        {
            "api_key": settings.POSTHOG_API_KEY,
            "event": external["event_type"],
            "distinct_id": external.get("user_id") or "system",
            "properties": external,
        },
        {"Content-Type": "application/json"},
    )


def _external_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    metadata = payload.get("metadata") or {}
    safe_metadata = {
        str(key)[:80]: redact_text(value)[:500]
        for key, value in metadata.items()
        if key not in {"prompt", "messages", "resume", "response", "answer", "transcript"}
    }
    external = dict(payload)
    external["user_id"] = stable_hash(payload.get("user_id"), "user") if payload.get("user_id") else None
    external["interview_id"] = stable_hash(payload.get("interview_id"), "interview") if payload.get("interview_id") else None
    external["metadata"] = safe_metadata
    return external
