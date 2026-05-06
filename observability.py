from __future__ import annotations

import base64
import json
import logging
import time
import urllib.request
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from config import settings
from security_utils import redact_text, stable_hash

logger = logging.getLogger("observability")

_sentry_ready = False


def init_observability() -> None:
    global _sentry_ready
    if _sentry_ready or not settings.SENTRY_DSN:
        return
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


def capture_exception(exc: BaseException, context: Optional[Dict[str, Any]] = None) -> None:
    logger.error("Captured exception: %s", type(exc).__name__)
    if not _sentry_ready:
        return
    try:
        import sentry_sdk

        with sentry_sdk.push_scope() as scope:
            for key, value in (context or {}).items():
                scope.set_extra(key, value)
            sentry_sdk.capture_exception(exc)
    except Exception:
        logger.error("Sentry capture failed")


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
