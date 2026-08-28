"""Provider-only LLM facade for the local desktop application."""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

from jsonschema import validate as validate_json

from local_ai_provider import LocalProviderError, complete_chat
from local_runtime import get_local_preferences

logger = logging.getLogger("prepmate.local-ai")


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


def _model_for_event(event_type: Optional[str] = None) -> str:
    preferences = get_local_preferences()
    return str(preferences.get("model") or "gpt-5-mini")


def _resolved_provider_policy(provider_policy: Optional[str] = None) -> str:
    return "local"


def _provider_order(event_type: Optional[str] = None, policy: Optional[str] = None) -> tuple[str, ...]:
    return ("local",)


def _cached_provider_allowed(cached: Dict[str, Any], policy: Optional[str], event_type: Optional[str] = None) -> bool:
    return True


def _token_estimate(messages: Iterable[Dict[str, str]]) -> int:
    return max(1, sum(len(str(message.get("content") or "").split()) for message in messages))


def _strip_json_markdown(text: str) -> str:
    value = str(text or "").strip()
    if value.startswith("```"):
        value = value.split("\n", 1)[1] if "\n" in value else value[3:]
        if value.endswith("```"):
            value = value[:-3]
    return value.strip()


def _validate_structured_payload(payload: Any, json_schema: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise LLMRoutingError("The selected provider returned a JSON object")
    if json_schema:
        validate_json(instance=payload, schema=json_schema)
    return payload


async def _complete(
    messages: List[Dict[str, str]],
    *,
    temperature: float,
    max_tokens: int,
    json_mode: bool,
    json_schema: Optional[Dict[str, Any]],
) -> LLMResult:
    started = time.monotonic()
    try:
        response = await complete_chat(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            json_mode=json_mode,
            json_schema=json_schema,
        )
    except LocalProviderError as exc:
        raise LLMRoutingError(str(exc)) from exc
    except Exception as exc:
        logger.warning("Local provider request failed: %s", type(exc).__name__)
        raise LLMRoutingError(f"Selected AI provider request failed: {type(exc).__name__}") from exc
    return LLMResult(
        text=response.text,
        provider=response.provider,
        model=response.model,
        latency_ms=response.latency_ms or int((time.monotonic() - started) * 1000),
        prompt_tokens=response.prompt_tokens,
        output_tokens=response.output_tokens,
        cached_tokens=response.cached_tokens,
    )


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
    return await _complete(messages, temperature=temperature, max_tokens=max_tokens, json_mode=False, json_schema=None)


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
    result = await _complete(messages, temperature=temperature, max_tokens=max_tokens, json_mode=True, json_schema=json_schema)
    try:
        payload = json.loads(_strip_json_markdown(result.text))
    except (TypeError, json.JSONDecodeError) as exc:
        raise LLMRoutingError("The selected provider returned invalid JSON") from exc
    try:
        return _validate_structured_payload(payload, json_schema)
    except Exception as exc:
        raise LLMRoutingError("The selected provider returned JSON that does not match the requested schema") from exc


def _run_sync(awaitable):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(awaitable)
    result: list[Any] = []
    error: list[BaseException] = []

    def runner() -> None:
        try:
            result.append(asyncio.run(awaitable))
        except BaseException as exc:  # pragma: no cover - only used by sync callers inside async code
            error.append(exc)

    thread = threading.Thread(target=runner)
    thread.start()
    thread.join()
    if error:
        raise error[0]
    return result[0]


def complete_text_sync(messages: List[Dict[str, str]], **kwargs: Any) -> LLMResult:
    return _run_sync(complete_text_async(messages, **kwargs))


def complete_json_sync(messages: List[Dict[str, str]], **kwargs: Any) -> Dict[str, Any]:
    return _run_sync(complete_json_async(messages, **kwargs))


def chunk_text(text: str, chunk_size: int = 24) -> Iterable[str]:
    words = str(text or "").split()
    for index in range(0, len(words), max(1, chunk_size)):
        yield " ".join(words[index:index + chunk_size]) + (" " if index + chunk_size < len(words) else "")


def _responses_kwargs(**kwargs: Any) -> Dict[str, Any]:
    """Compatibility helper for retired authoring scripts; no SaaS request uses it."""
    return dict(kwargs)
