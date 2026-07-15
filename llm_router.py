# ============================================================================
# MODULE: llm_router.py
# PURPOSE: OpenAI-only text and JSON completion helpers with cache,
#          observability, and existing caller-compatible signatures.
# ============================================================================

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

from config import settings
from database import async_execute
from observability import log_ai_event
from security_utils import redact_text, redact_messages_for_external

logger = logging.getLogger("llm_router")


@dataclass
class LLMResult:
    text: str
    provider: str
    model: str
    latency_ms: int
    estimated_cost_usd: float = 0.0
    prompt_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0


class LLMRoutingError(RuntimeError):
    pass


_openai_async_client = None
_openai_sync_client = None


def _stable_cache_key(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    text = str(raw)
    if len(text) <= 160:
        return text
    return f"llm:{hashlib.sha256(text.encode('utf-8')).hexdigest()}"


async def _load_llm_cache(cache_key: Optional[str], event_type: str) -> Optional[Dict[str, Any]]:
    key = _stable_cache_key(cache_key)
    if not key:
        return None
    try:
        row = await async_execute(
            """
            SELECT payload
            FROM LLMCache
            WHERE cache_key = %s
              AND event_type = %s
              AND (expires_at IS NULL OR expires_at > NOW())
            """,
            (key, event_type),
            fetchone=True,
        )
        if not row:
            return None
        payload = row[0] if isinstance(row[0], dict) else json.loads(row[0])
        return payload if isinstance(payload, dict) else None
    except Exception:
        logger.debug("LLM cache read failed for %s", event_type, exc_info=True)
        return None


async def _save_llm_cache(cache_key: Optional[str], event_type: str, payload: Dict[str, Any]) -> None:
    key = _stable_cache_key(cache_key)
    if not key:
        return
    try:
        await async_execute(
            """
            INSERT INTO LLMCache (cache_key, event_type, payload, expires_at)
            VALUES (%s, %s, %s::jsonb, NULL)
            ON CONFLICT (cache_key) DO UPDATE
            SET event_type = EXCLUDED.event_type,
                payload = EXCLUDED.payload,
                expires_at = EXCLUDED.expires_at,
                created_at = NOW()
            """,
            (key, event_type, json.dumps(payload)),
        )
    except Exception:
        logger.debug("LLM cache write failed for %s", event_type, exc_info=True)


def _token_estimate(messages: List[Dict[str, str]]) -> int:
    text = "\n".join(str(message.get("content", "")) for message in messages)
    return max(1, len(text.split()))


def _strip_json_markdown(text: str) -> str:
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.replace("```json", "").replace("```", "").strip()
    return cleaned


def _model_for_event(event_type: Optional[str] = None) -> str:
    event = (event_type or "").strip().lower()
    if event in {"report_generation", "report_generation_llm"}:
        return settings.OPENAI_REPORT_MODEL or settings.OPENAI_CHAT_MODEL
    if event in {"resume_ai_fallback", "resume_parse_fast"}:
        return settings.OPENAI_RESUME_MODEL or settings.OPENAI_CHAT_MODEL
    if event in {"question_generator_main", "question_generator_followup", "question_generator_knowledge_map"}:
        return settings.OPENAI_QUESTION_MODEL or settings.OPENAI_CHAT_MODEL
    if event in {
        "answer_semantic_evaluation",
        "response_semantic_evaluation",
        "turn_semantic_evaluation",
    }:
        return settings.OPENAI_EVALUATION_MODEL or settings.OPENAI_CHAT_MODEL
    return settings.OPENAI_CHAT_MODEL


def _model_costs(model: str) -> tuple[float, float, float]:
    if model == settings.OPENAI_EVALUATION_MODEL:
        return (
            settings.MODEL_EVALUATION_INPUT_COST_PER_M_TOKENS,
            settings.MODEL_EVALUATION_CACHED_INPUT_COST_PER_M_TOKENS,
            settings.MODEL_EVALUATION_OUTPUT_COST_PER_M_TOKENS,
        )
    return (
        settings.MODEL_EXTERNAL_INPUT_COST_PER_M_TOKENS,
        settings.MODEL_EXTERNAL_CACHED_INPUT_COST_PER_M_TOKENS,
        settings.MODEL_EXTERNAL_OUTPUT_COST_PER_M_TOKENS,
    )


def _estimate_cost_usd(model: str, prompt_tokens: int, output_tokens: int, cached_tokens: int = 0) -> float:
    input_cost, cached_input_cost, output_cost = _model_costs(model)
    cached = max(0, min(int(cached_tokens or 0), int(prompt_tokens or 0)))
    uncached = max(0, int(prompt_tokens or 0) - cached)
    return round(
        ((uncached / 1_000_000) * input_cost)
        + ((cached / 1_000_000) * cached_input_cost)
        + ((max(0, int(output_tokens or 0)) / 1_000_000) * output_cost),
        6,
    )


def _reservation_idempotency_key(
    event_type: str,
    *,
    cache_key: Optional[str],
    metadata: Optional[Dict[str, Any]],
) -> str:
    anchor = cache_key
    if not anchor and metadata:
        anchor = str(
            metadata.get("idempotency_key")
            or metadata.get("response_id")
            or metadata.get("analysis_id")
            or ""
        )
    if not anchor:
        anchor = str(uuid.uuid4())
    digest = hashlib.sha256(
        f"{event_type}:{anchor}".encode("utf-8")
    ).hexdigest()
    return f"{event_type}:{digest}"[:160]


def _semantic_request_budget(settings_payload: Any, duration_seconds: Any) -> int:
    payload = settings_payload
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except Exception:
            payload = {}
    if not isinstance(payload, dict):
        payload = {}
    duration_minutes = 0
    try:
        if duration_seconds:
            duration_minutes = max(1, int(duration_seconds) // 60)
    except (TypeError, ValueError):
        duration_minutes = 0
    if not duration_minutes:
        duration = payload.get("duration")
        if not isinstance(duration, dict):
            duration = {}
        raw_minutes = payload.get("duration_minutes") or duration.get("max_minutes") or 30
        try:
            duration_minutes = max(1, int(raw_minutes))
        except (TypeError, ValueError):
            duration_minutes = 30
    return min(12, max(1, (duration_minutes + 4) // 5))


def _usage_from_response(response: Any) -> tuple[int, int, int]:
    usage = getattr(response, "usage", None)
    if not usage:
        return 0, 0, 0
    prompt_tokens = int(
        getattr(usage, "input_tokens", 0)
        or getattr(usage, "prompt_tokens", 0)
        or 0
    )
    output_tokens = int(
        getattr(usage, "output_tokens", 0)
        or getattr(usage, "completion_tokens", 0)
        or 0
    )
    prompt_details = (
        getattr(usage, "input_tokens_details", None)
        or getattr(usage, "prompt_tokens_details", None)
    )
    cached_tokens = int(getattr(prompt_details, "cached_tokens", 0) or 0) if prompt_details else 0
    return prompt_tokens, output_tokens, cached_tokens


def _reserve_budget_sync(
    *,
    interview_id: Optional[str],
    user_id: Optional[str],
    event_type: str,
    model: str,
    prompt_tokens: int,
    max_tokens: int,
    idempotency_key: str,
) -> Optional[Dict[str, Any]]:
    if not interview_id:
        return None
    reservation_id = str(uuid.uuid4())
    reserved_cost = _estimate_cost_usd(model, prompt_tokens, max_tokens)
    try:
        from database import get_db_connection, return_db_connection

        connection = get_db_connection()
        cursor = connection.cursor()
        try:
            cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", ("llm:monthly-budget",))
            cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"llm:interview:{interview_id}",))
            cursor.execute(
                """
                SELECT COALESCE(llm_cost_usd, 0), settings, duration_seconds
                FROM Interviews
                WHERE interview_id = %s
                FOR UPDATE
                """,
                (interview_id,),
            )
            row = cursor.fetchone()
            if not row:
                raise LLMRoutingError("Interview budget owner was not found")
            interview_cost = float(row[0] or 0)

            cursor.execute(
                """
                SELECT reservation_id, estimated_cost
                FROM AIUsageReservations
                WHERE interview_id = %s
                  AND status = 'reserved'
                  AND expires_at IS NOT NULL
                  AND expires_at <= NOW()
                FOR UPDATE
                """,
                (interview_id,),
            )
            expired = cursor.fetchall()
            if expired:
                expired_cost = sum(float(item[1] or 0) for item in expired)
                cursor.execute(
                    """
                    UPDATE AIUsageReservations
                    SET status = 'released', actual_cost = NULL, settled_at = NOW()
                    WHERE reservation_id = ANY(%s)
                    """,
                    ([item[0] for item in expired],),
                )
                cursor.execute(
                    """
                    UPDATE Interviews
                    SET llm_cost_usd = GREATEST(
                        0,
                        COALESCE(llm_cost_usd, 0) - %s
                    )
                    WHERE interview_id = %s
                    """,
                    (expired_cost, interview_id),
                )
                interview_cost = max(0.0, interview_cost - expired_cost)

            cursor.execute(
                """
                SELECT reservation_id, estimated_cost, status, expires_at
                FROM AIUsageReservations
                WHERE interview_id = %s AND idempotency_key = %s
                FOR UPDATE
                """,
                (interview_id, idempotency_key),
            )
            existing = cursor.fetchone()
            if existing and existing[2] == "settled":
                raise LLMRoutingError("OpenAI request was already settled")
            if existing and existing[2] == "reserved":
                raise LLMRoutingError("OpenAI request is already in progress")

            if event_type in {
                "answer_semantic_evaluation",
                "response_semantic_evaluation",
                "turn_semantic_evaluation",
            }:
                semantic_budget = _semantic_request_budget(row[1], row[2])
                cursor.execute(
                    """
                    SELECT COUNT(*)
                    FROM AIUsageReservations
                    WHERE interview_id = %s
                      AND event_type IN (
                          'answer_semantic_evaluation',
                          'response_semantic_evaluation',
                          'turn_semantic_evaluation'
                      )
                      AND status IN ('reserved', 'settled')
                    """,
                    (interview_id,),
                )
                semantic_calls = int((cursor.fetchone() or [0])[0] or 0)
                if semantic_calls >= semantic_budget:
                    raise LLMRoutingError("Per-interview semantic request budget reached")

            cursor.execute(
                """
                SELECT COALESCE(SUM(llm_cost_usd), 0)
                FROM Interviews
                WHERE created_at >= date_trunc('month', NOW())
                """
            )
            monthly_cost = float((cursor.fetchone() or [0])[0] or 0)
            monthly_limit = settings.MODEL_MONTHLY_BUDGET_USD * settings.MODEL_MONTHLY_HARD_STOP_RATIO
            if interview_cost + reserved_cost > settings.MODEL_MAX_INTERVIEW_COST_USD:
                raise LLMRoutingError("Per-interview OpenAI budget reached")
            if monthly_cost + reserved_cost > monthly_limit:
                raise LLMRoutingError("Monthly OpenAI budget reached")
            cursor.execute(
                "UPDATE Interviews SET llm_cost_usd = COALESCE(llm_cost_usd, 0) + %s WHERE interview_id = %s",
                (reserved_cost, interview_id),
            )
            if existing and existing[2] == "released":
                reservation_id = existing[0]
                cursor.execute(
                    """
                    UPDATE AIUsageReservations
                    SET estimated_cost = %s,
                        actual_cost = NULL,
                        status = 'reserved',
                        settled_at = NULL,
                        expires_at = NOW() + INTERVAL '10 minutes',
                        created_at = NOW()
                    WHERE reservation_id = %s
                    """,
                    (reserved_cost, reservation_id),
                )
            else:
                cursor.execute(
                    """
                    INSERT INTO AIUsageReservations (
                        reservation_id, interview_id, user_id, event_type,
                        estimated_cost, status, idempotency_key,
                        expires_at, created_at
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, 'reserved', %s,
                        NOW() + INTERVAL '10 minutes', NOW()
                    )
                    """,
                    (
                        reservation_id,
                        interview_id,
                        user_id,
                        event_type,
                        reserved_cost,
                        idempotency_key,
                    ),
                )
            connection.commit()
            return {
                "reservation_id": reservation_id,
                "reserved_cost": reserved_cost,
                "idempotency_key": idempotency_key,
            }
        except Exception:
            connection.rollback()
            raise
        finally:
            cursor.close()
            return_db_connection(connection)
    except LLMRoutingError:
        raise
    except Exception as exc:
        if settings.ENVIRONMENT == "production":
            raise LLMRoutingError("OpenAI budget service unavailable") from exc
        logger.debug("OpenAI budget reservation skipped outside production", exc_info=True)
        return None


def _settle_budget_sync(
    reservation: Optional[Dict[str, Any]],
    *,
    interview_id: Optional[str],
    actual_cost: Optional[float],
) -> None:
    if not reservation or not interview_id:
        return
    from database import get_db_connection, return_db_connection

    connection = get_db_connection()
    cursor = connection.cursor()
    try:
        cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"llm:interview:{interview_id}",))
        cursor.execute(
            """
            SELECT estimated_cost, status
            FROM AIUsageReservations
            WHERE reservation_id = %s
            FOR UPDATE
            """,
            (reservation["reservation_id"],),
        )
        reservation_row = cursor.fetchone()
        if not reservation_row or reservation_row[1] != "reserved":
            connection.commit()
            return
        reserved_cost = float(reservation_row[0] or 0)
        if actual_cost is None:
            final_cost = 0.0
            status_value = "released"
        else:
            final_cost = max(0.0, float(actual_cost))
            status_value = "settled"
        delta = final_cost - reserved_cost
        cursor.execute(
            """
            UPDATE AIUsageReservations
            SET actual_cost = %s, status = %s, settled_at = NOW()
            WHERE reservation_id = %s AND status = 'reserved'
            """,
            (final_cost, status_value, reservation["reservation_id"]),
        )
        if cursor.rowcount != 1:
            connection.commit()
            return
        cursor.execute(
            """
            UPDATE Interviews
            SET llm_cost_usd = GREATEST(0, COALESCE(llm_cost_usd, 0) + %s)
            WHERE interview_id = %s
            """,
            (delta, interview_id),
        )
        connection.commit()
    except Exception:
        connection.rollback()
        if settings.ENVIRONMENT == "production":
            logger.error("Failed to settle OpenAI budget reservation")
        else:
            logger.debug("OpenAI budget settlement skipped", exc_info=True)
    finally:
        cursor.close()
        return_db_connection(connection)


def _strict_json_schema(schema: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not schema:
        return None

    def walk(node: Any) -> Any:
        if not isinstance(node, dict):
            return node
        out = dict(node)
        if out.get("type") == "object":
            out.setdefault("additionalProperties", False)
            props = out.get("properties")
            if isinstance(props, dict):
                out["properties"] = {key: walk(value) for key, value in props.items()}
                out.setdefault("required", list(props.keys()))
        if isinstance(out.get("items"), dict):
            out["items"] = walk(out["items"])
        for key in ("anyOf", "oneOf", "allOf"):
            if isinstance(out.get(key), list):
                out[key] = [walk(item) for item in out[key]]
        return out

    return walk(schema)


def _responses_kwargs(
    *,
    model: str,
    messages: List[Dict[str, str]],
    temperature: float,
    max_tokens: int,
    json_mode: bool,
    json_schema: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    kwargs: Dict[str, Any] = {
        "model": model,
        "input": redact_messages_for_external(messages),
        "store": False,
        "max_output_tokens": max_tokens,
    }
    lower_model = model.lower()
    if not lower_model.startswith(("gpt-5", "o1", "o2", "o3", "o4")):
        kwargs["temperature"] = temperature
    if json_schema:
        kwargs["text"] = {
            "format": {
                "type": "json_schema",
                "name": "interai_structured_response",
                "schema": _strict_json_schema(json_schema),
                "strict": True,
            }
        }
    elif json_mode:
        kwargs["text"] = {"format": {"type": "json_object"}}
    return kwargs


def _get_openai_async_client():
    global _openai_async_client
    if not settings.OPENAI_API_KEY:
        raise LLMRoutingError("OPENAI_API_KEY is not configured")
    if _openai_async_client is None:
        from openai import AsyncOpenAI

        _openai_async_client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    return _openai_async_client


def _get_openai_sync_client():
    global _openai_sync_client
    if not settings.OPENAI_API_KEY:
        raise LLMRoutingError("OPENAI_API_KEY is not configured")
    if _openai_sync_client is None:
        from openai import OpenAI

        _openai_sync_client = OpenAI(api_key=settings.OPENAI_API_KEY)
    return _openai_sync_client


async def _call_openai_async(
    messages: List[Dict[str, str]],
    *,
    event_type: str,
    temperature: float,
    max_tokens: int,
    json_mode: bool,
    json_schema: Optional[Dict[str, Any]] = None,
) -> LLMResult:
    client = _get_openai_async_client()
    model = _model_for_event(event_type)
    kwargs = _responses_kwargs(
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        json_mode=json_mode,
        json_schema=json_schema,
    )
    started = time.time()
    response = await client.responses.create(timeout=20.0, **kwargs)
    text = (response.output_text or "").strip()
    if not text:
        raise LLMRoutingError("OpenAI returned empty text")
    prompt_tokens, output_tokens, cached_tokens = _usage_from_response(response)
    return LLMResult(
        text=text,
        provider="openai",
        model=model,
        latency_ms=int((time.time() - started) * 1000),
        prompt_tokens=prompt_tokens,
        output_tokens=output_tokens,
        cached_tokens=cached_tokens,
    )


def _call_openai_sync(
    messages: List[Dict[str, str]],
    *,
    event_type: str,
    temperature: float,
    max_tokens: int,
    json_mode: bool,
    json_schema: Optional[Dict[str, Any]] = None,
) -> LLMResult:
    client = _get_openai_sync_client()
    model = _model_for_event(event_type)
    kwargs = _responses_kwargs(
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        json_mode=json_mode,
        json_schema=json_schema,
    )
    started = time.time()
    response = client.responses.create(timeout=20.0, **kwargs)
    text = (response.output_text or "").strip()
    if not text:
        raise LLMRoutingError("OpenAI returned empty text")
    prompt_tokens, output_tokens, cached_tokens = _usage_from_response(response)
    return LLMResult(
        text=text,
        provider="openai",
        model=model,
        latency_ms=int((time.time() - started) * 1000),
        prompt_tokens=prompt_tokens,
        output_tokens=output_tokens,
        cached_tokens=cached_tokens,
    )


def _log_metadata(
    metadata: Optional[Dict[str, Any]],
    *,
    provider_policy: Optional[str],
    estimated_cost_usd: float = 0.0,
    cache_hit: bool = False,
) -> Dict[str, Any]:
    return {
        **(metadata or {}),
        "provider_policy": "openai_required",
        "requested_provider_policy": provider_policy,
        "estimated_cost_usd": estimated_cost_usd,
        "cache_hit": cache_hit,
        "model_router": "openai_only",
    }


def chunk_text(text: str, chunk_size: int = 24) -> Iterable[str]:
    words = text.split()
    for index in range(0, len(words), chunk_size):
        yield " ".join(words[index:index + chunk_size]) + (" " if index + chunk_size < len(words) else "")


async def complete_text_async(
    messages: List[Dict[str, str]],
    *,
    event_type: str,
    temperature: float = 0.5,
    max_tokens: int = 800,
    user_id: Optional[str] = None,
    interview_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    provider_policy: Optional[str] = None,
    cache_key: Optional[str] = None,
) -> LLMResult:
    prompt_tokens = _token_estimate(messages)
    cached = await _load_llm_cache(cache_key, event_type)
    if cached and cached.get("kind") == "text":
        text = str(cached.get("text") or "")
        log_ai_event(
            event_type=event_type,
            provider="llm_cache",
            model="cache",
            success=True,
            latency_ms=0,
            user_id=user_id,
            interview_id=interview_id,
            prompt_tokens=0,
            output_tokens=max(1, len(text.split())),
            metadata=_log_metadata(metadata, provider_policy=provider_policy, cache_hit=True),
        )
        return LLMResult(text=text, provider="llm_cache", model="cache", latency_ms=0)

    model = _model_for_event(event_type)
    reservation_key = _reservation_idempotency_key(
        event_type,
        cache_key=cache_key,
        metadata=metadata,
    )
    reservation = await asyncio.to_thread(
        _reserve_budget_sync,
        interview_id=interview_id,
        user_id=user_id,
        event_type=event_type,
        model=model,
        prompt_tokens=prompt_tokens,
        max_tokens=max_tokens,
        idempotency_key=reservation_key,
    )
    try:
        result = await _call_openai_async(
            messages,
            event_type=event_type,
            temperature=temperature,
            max_tokens=max_tokens,
            json_mode=False,
        )
        actual_prompt_tokens = result.prompt_tokens or prompt_tokens
        output_tokens = result.output_tokens or max(1, len(result.text.split()))
        result.estimated_cost_usd = _estimate_cost_usd(
            result.model,
            actual_prompt_tokens,
            output_tokens,
            result.cached_tokens,
        )
        await asyncio.to_thread(
            _settle_budget_sync,
            reservation,
            interview_id=interview_id,
            actual_cost=result.estimated_cost_usd,
        )
        log_ai_event(
            event_type=event_type,
            provider=result.provider,
            model=result.model,
            success=True,
            latency_ms=result.latency_ms,
            user_id=user_id,
            interview_id=interview_id,
            prompt_tokens=actual_prompt_tokens,
            output_tokens=output_tokens,
            metadata=_log_metadata(
                {**(metadata or {}), "cached_tokens": result.cached_tokens},
                provider_policy=provider_policy,
                estimated_cost_usd=result.estimated_cost_usd,
            ),
        )
        await _save_llm_cache(cache_key, event_type, {"kind": "text", "text": result.text, "provider": result.provider, "model": result.model})
        return result
    except Exception as exc:
        await asyncio.to_thread(
            _settle_budget_sync,
            reservation,
            interview_id=interview_id,
            actual_cost=None,
        )
        logger.warning("OpenAI text call failed for %s: %s", event_type, redact_text(exc))
        log_ai_event(
            event_type=event_type,
            provider="openai",
            model=_model_for_event(event_type),
            success=False,
            user_id=user_id,
            interview_id=interview_id,
            prompt_tokens=prompt_tokens,
            metadata={**(metadata or {}), "error": type(exc).__name__, "provider_policy": "openai_required"},
        )
        raise LLMRoutingError(f"OpenAI text call failed: {type(exc).__name__}") from exc


async def complete_json_async(
    messages: List[Dict[str, str]],
    *,
    event_type: str,
    temperature: float = 0.2,
    max_tokens: int = 1200,
    user_id: Optional[str] = None,
    interview_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    json_schema: Optional[Dict[str, Any]] = None,
    provider_policy: Optional[str] = None,
    cache_key: Optional[str] = None,
) -> Dict[str, Any]:
    prompt_tokens = _token_estimate(messages)
    cached = await _load_llm_cache(cache_key, event_type)
    if cached and cached.get("kind") == "json" and isinstance(cached.get("data"), dict):
        payload = cached["data"]
        log_ai_event(
            event_type=event_type,
            provider="llm_cache",
            model="cache",
            success=True,
            latency_ms=0,
            user_id=user_id,
            interview_id=interview_id,
            prompt_tokens=0,
            output_tokens=max(1, len(json.dumps(payload).split())),
            metadata=_log_metadata(metadata, provider_policy=provider_policy, cache_hit=True),
        )
        return payload

    model = _model_for_event(event_type)
    reservation_key = _reservation_idempotency_key(
        event_type,
        cache_key=cache_key,
        metadata=metadata,
    )
    reservation = await asyncio.to_thread(
        _reserve_budget_sync,
        interview_id=interview_id,
        user_id=user_id,
        event_type=event_type,
        model=model,
        prompt_tokens=prompt_tokens,
        max_tokens=max_tokens,
        idempotency_key=reservation_key,
    )
    try:
        result = await _call_openai_async(
            messages,
            event_type=event_type,
            temperature=temperature,
            max_tokens=max_tokens,
            json_mode=True,
            json_schema=json_schema,
        )
        parsed = json.loads(_strip_json_markdown(result.text))
        actual_prompt_tokens = result.prompt_tokens or prompt_tokens
        output_tokens = result.output_tokens or max(1, len(result.text.split()))
        result.estimated_cost_usd = _estimate_cost_usd(
            result.model,
            actual_prompt_tokens,
            output_tokens,
            result.cached_tokens,
        )
        await asyncio.to_thread(
            _settle_budget_sync,
            reservation,
            interview_id=interview_id,
            actual_cost=result.estimated_cost_usd,
        )
        log_ai_event(
            event_type=event_type,
            provider=result.provider,
            model=result.model,
            success=True,
            latency_ms=result.latency_ms,
            user_id=user_id,
            interview_id=interview_id,
            prompt_tokens=actual_prompt_tokens,
            output_tokens=output_tokens,
            metadata=_log_metadata(
                {**(metadata or {}), "cached_tokens": result.cached_tokens},
                provider_policy=provider_policy,
                estimated_cost_usd=result.estimated_cost_usd,
            ),
        )
        await _save_llm_cache(cache_key, event_type, {"kind": "json", "data": parsed, "provider": result.provider, "model": result.model})
        return parsed
    except Exception as exc:
        await asyncio.to_thread(
            _settle_budget_sync,
            reservation,
            interview_id=interview_id,
            actual_cost=None,
        )
        logger.warning("OpenAI JSON call failed for %s: %s", event_type, redact_text(exc))
        log_ai_event(
            event_type=event_type,
            provider="openai",
            model=_model_for_event(event_type),
            success=False,
            user_id=user_id,
            interview_id=interview_id,
            prompt_tokens=prompt_tokens,
            metadata={**(metadata or {}), "error": type(exc).__name__, "provider_policy": "openai_required"},
        )
        raise LLMRoutingError(f"OpenAI JSON call failed: {type(exc).__name__}") from exc


def complete_text_sync(
    messages: List[Dict[str, str]],
    *,
    event_type: str,
    temperature: float = 0.5,
    max_tokens: int = 800,
    user_id: Optional[str] = None,
    interview_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    provider_policy: Optional[str] = None,
    cache_key: Optional[str] = None,
) -> LLMResult:
    prompt_tokens = _token_estimate(messages)
    model = _model_for_event(event_type)
    reservation_key = _reservation_idempotency_key(
        event_type,
        cache_key=cache_key,
        metadata=metadata,
    )
    reservation = _reserve_budget_sync(
        interview_id=interview_id,
        user_id=user_id,
        event_type=event_type,
        model=model,
        prompt_tokens=prompt_tokens,
        max_tokens=max_tokens,
        idempotency_key=reservation_key,
    )
    try:
        result = _call_openai_sync(messages, event_type=event_type, temperature=temperature, max_tokens=max_tokens, json_mode=False)
    except Exception:
        _settle_budget_sync(reservation, interview_id=interview_id, actual_cost=None)
        raise
    actual_prompt_tokens = result.prompt_tokens or prompt_tokens
    output_tokens = result.output_tokens or max(1, len(result.text.split()))
    result.estimated_cost_usd = _estimate_cost_usd(result.model, actual_prompt_tokens, output_tokens, result.cached_tokens)
    _settle_budget_sync(reservation, interview_id=interview_id, actual_cost=result.estimated_cost_usd)
    log_ai_event(
        event_type=event_type,
        provider=result.provider,
        model=result.model,
        success=True,
        latency_ms=result.latency_ms,
        user_id=user_id,
        interview_id=interview_id,
        prompt_tokens=actual_prompt_tokens,
        output_tokens=output_tokens,
        metadata=_log_metadata(metadata, provider_policy=provider_policy, estimated_cost_usd=result.estimated_cost_usd),
    )
    return result


def complete_json_sync(
    messages: List[Dict[str, str]],
    *,
    event_type: str,
    temperature: float = 0.2,
    max_tokens: int = 1200,
    user_id: Optional[str] = None,
    interview_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    json_schema: Optional[Dict[str, Any]] = None,
    provider_policy: Optional[str] = None,
    cache_key: Optional[str] = None,
) -> Dict[str, Any]:
    prompt_tokens = _token_estimate(messages)
    model = _model_for_event(event_type)
    reservation_key = _reservation_idempotency_key(
        event_type,
        cache_key=cache_key,
        metadata=metadata,
    )
    reservation = _reserve_budget_sync(
        interview_id=interview_id,
        user_id=user_id,
        event_type=event_type,
        model=model,
        prompt_tokens=prompt_tokens,
        max_tokens=max_tokens,
        idempotency_key=reservation_key,
    )
    try:
        result = _call_openai_sync(
            messages,
            event_type=event_type,
            temperature=temperature,
            max_tokens=max_tokens,
            json_mode=True,
            json_schema=json_schema,
        )
        parsed = json.loads(_strip_json_markdown(result.text))
    except Exception:
        _settle_budget_sync(reservation, interview_id=interview_id, actual_cost=None)
        raise
    actual_prompt_tokens = result.prompt_tokens or prompt_tokens
    output_tokens = result.output_tokens or max(1, len(result.text.split()))
    result.estimated_cost_usd = _estimate_cost_usd(result.model, actual_prompt_tokens, output_tokens, result.cached_tokens)
    _settle_budget_sync(reservation, interview_id=interview_id, actual_cost=result.estimated_cost_usd)
    log_ai_event(
        event_type=event_type,
        provider=result.provider,
        model=result.model,
        success=True,
        latency_ms=result.latency_ms,
        user_id=user_id,
        interview_id=interview_id,
        prompt_tokens=actual_prompt_tokens,
        output_tokens=output_tokens,
        metadata=_log_metadata(metadata, provider_policy=provider_policy, estimated_cost_usd=result.estimated_cost_usd),
    )
    return parsed
