"""Direct provider calls for the local desktop runtime.

The desktop app never sends a PrepMate credential or routes prompts through a
PrepMate service. This module reads the selected provider's key from the OS
keychain and sends the request straight to that provider's public API.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

import httpx

from local_runtime import (
    get_local_preferences,
    get_provider_api_key,
    provider_requires_api_key,
    validate_provider_endpoint,
)
from security_utils import redact_messages_for_external


class LocalProviderError(RuntimeError):
    pass


@dataclass
class ProviderResponse:
    text: str
    provider: str
    model: str
    latency_ms: int
    prompt_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0


def _content_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, dict) and item.get("text"):
                parts.append(str(item["text"]))
            elif getattr(item, "text", None):
                parts.append(str(item.text))
        return "".join(parts).strip()
    return str(value or "").strip()


def _usage(payload: dict[str, Any]) -> tuple[int, int, int]:
    usage = payload.get("usage") if isinstance(payload, dict) else {}
    if not isinstance(usage, dict):
        usage = {}
    prompt = int(usage.get("prompt_tokens") or usage.get("input_tokens") or usage.get("promptTokenCount") or 0)
    output = int(usage.get("completion_tokens") or usage.get("output_tokens") or usage.get("candidatesTokenCount") or 0)
    cached = int(usage.get("cached_tokens") or usage.get("cachedContentTokenCount") or 0)
    return prompt, output, cached


def _raise_for_provider(response: httpx.Response, provider: str) -> None:
    if response.is_success:
        return
    detail = ""
    try:
        payload = response.json()
        if isinstance(payload, dict):
            error = payload.get("error")
            detail = error.get("message") if isinstance(error, dict) else payload.get("message", "")
    except Exception:
        detail = ""
    raise LocalProviderError(
        f"{provider} API request failed ({response.status_code})"
        + (f": {str(detail)[:240]}" if detail else "")
    )


def _openai_url(provider: str, endpoint: str) -> str:
    if provider == "openai":
        return "https://api.openai.com/v1/chat/completions"
    normalized = endpoint.rstrip("/")
    return normalized if normalized.endswith("/chat/completions") else normalized + "/chat/completions"


def _official_openai_payload(
    *,
    model: str,
    messages: list[dict[str, str]],
    temperature: float,
    max_tokens: int,
) -> dict[str, Any]:
    """Build a Chat Completions payload accepted by current OpenAI models.

    GPT-5 reasoning models reject the sampling temperature used by older
    models. The modern completion-limit field works across current official
    OpenAI chat models and includes reasoning tokens in its budget.
    """
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_completion_tokens": max_tokens,
    }
    normalized = model.strip().lower()
    if not normalized.startswith(("gpt-5", "o1", "o3", "o4")):
        payload["temperature"] = temperature
    return payload


async def complete_chat(
    messages: list[dict[str, str]],
    *,
    temperature: float,
    max_tokens: int,
    json_mode: bool = False,
    json_schema: dict[str, Any] | None = None,
    _preferences: dict[str, Any] | None = None,
    _api_key: str | None = None,
) -> ProviderResponse:
    preferences = _preferences or get_local_preferences()
    provider = str(preferences.get("provider") or "").strip().lower()
    model = str(preferences.get("model") or "").strip()
    endpoint = str(preferences.get("endpoint") or "").strip()
    if not provider or not model:
        raise LocalProviderError("Choose an AI provider and model in Settings")
    if provider == "openai_compatible":
        endpoint = validate_provider_endpoint(endpoint)
    if _api_key is not None:
        api_key = str(_api_key).strip()
    else:
        try:
            api_key = get_provider_api_key(provider)
        except RuntimeError as exc:
            if provider_requires_api_key(provider, endpoint):
                raise LocalProviderError("The operating-system keychain is unavailable") from exc
            api_key = ""
    if not api_key and provider_requires_api_key(provider, endpoint):
        raise LocalProviderError("Add the selected provider API key in Settings")

    request_messages = redact_messages_for_external([
        {"role": str(item.get("role") or "user"), "content": str(item.get("content") or "")}
        for item in messages
    ])
    if json_mode or json_schema:
        schema_hint = json.dumps(json_schema, separators=(",", ":")) if json_schema else "a JSON object"
        request_messages.append(
            {
                "role": "system",
                "content": "Return only valid JSON. Match this schema when supplied: " + schema_hint,
            }
        )

    provider_timeout = __import__("os").getenv("PREPMATE_PROVIDER_TIMEOUT") or __import__("os").getenv("INTERAI_PROVIDER_TIMEOUT", "60")
    timeout = max(5.0, min(120.0, float(provider_timeout)))
    started = time.monotonic()
    async with httpx.AsyncClient(timeout=timeout) as client:
        if provider in {"openai", "openai_compatible"}:
            payload: dict[str, Any]
            if provider == "openai":
                payload = _official_openai_payload(
                    model=model,
                    messages=request_messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            else:
                # OpenAI-compatible local servers commonly implement the
                # older field names even when the official API has moved on.
                payload = {
                    "model": model,
                    "messages": request_messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                }
            if json_mode or json_schema:
                payload["response_format"] = {"type": "json_object"}
            headers = {"Content-Type": "application/json"}
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
            response = await client.post(
                _openai_url(provider, endpoint),
                headers=headers,
                json=payload,
            )
            _raise_for_provider(response, provider)
            body = response.json()
            choices = body.get("choices") or []
            text = _content_text((choices[0].get("message") or {}).get("content")) if choices else ""
            prompt_tokens, output_tokens, cached_tokens = _usage(body)
        elif provider == "anthropic":
            system_messages = [item["content"] for item in request_messages if item["role"] == "system"]
            anthropic_messages = [item for item in request_messages if item["role"] != "system"]
            response = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": model,
                    "system": "\n\n".join(system_messages),
                    "messages": anthropic_messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                },
            )
            _raise_for_provider(response, provider)
            body = response.json()
            text = _content_text(body.get("content"))
            prompt_tokens, output_tokens, cached_tokens = _usage(body)
        elif provider == "google":
            system_messages = [item["content"] for item in request_messages if item["role"] == "system"]
            contents: list[dict[str, Any]] = []
            for item in request_messages:
                if item["role"] == "system":
                    continue
                role = "model" if item["role"] == "assistant" else "user"
                if contents and contents[-1]["role"] == role:
                    contents[-1]["parts"].append({"text": item["content"]})
                else:
                    contents.append({"role": role, "parts": [{"text": item["content"]}]})
            body_payload: dict[str, Any] = {
                "contents": contents,
                "generationConfig": {
                    "temperature": temperature,
                    "maxOutputTokens": max_tokens,
                    **({"responseMimeType": "application/json"} if json_mode or json_schema else {}),
                },
            }
            if system_messages:
                body_payload["systemInstruction"] = {"parts": [{"text": "\n\n".join(system_messages)}]}
            response = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                headers={"x-goog-api-key": api_key, "content-type": "application/json"},
                json=body_payload,
            )
            _raise_for_provider(response, provider)
            body = response.json()
            candidates = body.get("candidates") or []
            content = (candidates[0].get("content") or {}) if candidates else {}
            text = _content_text(content.get("parts")) if isinstance(content, dict) else ""
            prompt_tokens, output_tokens, cached_tokens = _usage(body.get("usageMetadata") or {})
        else:  # pragma: no cover - settings validation prevents this branch
            raise LocalProviderError("Unsupported AI provider")

    if not text:
        raise LocalProviderError(f"{provider} returned an empty response")
    return ProviderResponse(
        text=text,
        provider=provider,
        model=model,
        latency_ms=int((time.monotonic() - started) * 1000),
        prompt_tokens=prompt_tokens,
        output_tokens=output_tokens,
        cached_tokens=cached_tokens,
    )


async def test_connection() -> ProviderResponse:
    return await complete_chat(
        [{"role": "user", "content": "Reply with the single word OK."}],
        temperature=0,
        max_tokens=64,
    )


async def test_connection_with_settings(
    *,
    provider: str,
    model: str,
    endpoint: str,
    api_key: str | None,
) -> ProviderResponse:
    """Probe staged settings without writing the key or preferences to disk."""
    return await complete_chat(
        [{"role": "user", "content": "Reply with the single word OK."}],
        temperature=0,
        max_tokens=64,
        _preferences={"provider": provider, "model": model, "endpoint": endpoint},
        _api_key=api_key,
    )
