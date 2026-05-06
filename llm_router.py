from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urlparse

from config import settings
from observability import log_ai_event
from security_utils import redact_text

logger = logging.getLogger("llm_router")


@dataclass
class LLMResult:
    text: str
    provider: str
    model: str
    latency_ms: int


class LLMRoutingError(RuntimeError):
    pass


def _token_estimate(messages: List[Dict[str, str]]) -> int:
    text = "\n".join(str(message.get("content", "")) for message in messages)
    return max(1, len(text.split()))


def _request_json(url: str, payload: Dict[str, Any], headers: Dict[str, str], timeout: int = 45) -> Dict[str, Any]:
    parsed_url = urlparse(url)
    if parsed_url.scheme != "https":
        raise LLMRoutingError("Refusing non-HTTPS model provider request")
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise LLMRoutingError(f"Provider HTTP {exc.code}") from None
    except urllib.error.URLError as exc:
        raise LLMRoutingError(f"Provider request failed: {redact_text(exc.reason)}") from None


def _strip_json_markdown(text: str) -> str:
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.replace("```json", "").replace("```", "").strip()
    return cleaned


def _gemini_messages(messages: List[Dict[str, str]]) -> tuple[Optional[str], List[Dict[str, Any]]]:
    system_parts: List[str] = []
    contents: List[Dict[str, Any]] = []
    for message in messages:
        role = message.get("role", "user")
        content = str(message.get("content", ""))
        if role == "system":
            system_parts.append(content)
            continue
        gemini_role = "model" if role == "assistant" else "user"
        contents.append({"role": gemini_role, "parts": [{"text": content}]})
    return ("\n".join(system_parts) if system_parts else None), contents


def _call_gemini(messages: List[Dict[str, str]], temperature: float, max_tokens: int, json_mode: bool) -> LLMResult:
    if not settings.GEMINI_API_KEY:
        raise LLMRoutingError("Gemini not configured")

    system_instruction, contents = _gemini_messages(messages)
    payload: Dict[str, Any] = {
        "contents": contents,
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": max_tokens,
        },
    }
    if system_instruction:
        payload["systemInstruction"] = {"parts": [{"text": system_instruction}]}
    if json_mode:
        payload["generationConfig"]["responseMimeType"] = "application/json"

    started = time.time()
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{settings.GEMINI_MODEL}:generateContent"
    body = _request_json(
        url,
        payload,
        {
            "Content-Type": "application/json",
            "x-goog-api-key": settings.GEMINI_API_KEY,
        },
    )
    candidates = body.get("candidates") or []
    parts = candidates[0].get("content", {}).get("parts", []) if candidates else []
    text = "".join(str(part.get("text", "")) for part in parts).strip()
    if not text:
        raise LLMRoutingError("Gemini returned empty text")
    return LLMResult(text=text, provider="gemini", model=settings.GEMINI_MODEL, latency_ms=int((time.time() - started) * 1000))


def _call_groq(messages: List[Dict[str, str]], temperature: float, max_tokens: int, json_mode: bool) -> LLMResult:
    if not settings.GROQ_API_KEY:
        raise LLMRoutingError("Groq not configured")

    payload: Dict[str, Any] = {
        "model": settings.GROQ_CHAT_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    started = time.time()
    body = _request_json(
        "https://api.groq.com/openai/v1/chat/completions",
        payload,
        {
            "Authorization": f"Bearer {settings.GROQ_API_KEY}",
            "Content-Type": "application/json",
        },
    )
    text = body["choices"][0]["message"]["content"].strip()
    if not text:
        raise LLMRoutingError("Groq returned empty text")
    return LLMResult(text=text, provider="groq", model=settings.GROQ_CHAT_MODEL, latency_ms=int((time.time() - started) * 1000))


_openai_client = None


def _get_openai_client():
    global _openai_client
    if not settings.OPENAI_API_KEY:
        raise LLMRoutingError("OpenAI emergency provider not configured")
    if _openai_client is None:
        from openai import OpenAI

        _openai_client = OpenAI(api_key=settings.OPENAI_API_KEY)
    return _openai_client


def _call_openai(messages: List[Dict[str, str]], temperature: float, max_tokens: int, json_mode: bool) -> LLMResult:
    client = _get_openai_client()
    kwargs: Dict[str, Any] = {
        "model": settings.OPENAI_CHAT_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    started = time.time()
    response = client.chat.completions.create(**kwargs)
    text = response.choices[0].message.content.strip()
    if not text:
        raise LLMRoutingError("OpenAI returned empty text")
    return LLMResult(text=text, provider="openai", model=settings.OPENAI_CHAT_MODEL, latency_ms=int((time.time() - started) * 1000))


def _providers() -> Iterable:
    return (_call_gemini, _call_groq, _call_openai)


def complete_text_sync(
    messages: List[Dict[str, str]],
    *,
    event_type: str,
    temperature: float = 0.5,
    max_tokens: int = 800,
    user_id: Optional[str] = None,
    interview_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> LLMResult:
    errors: List[str] = []
    prompt_tokens = _token_estimate(messages)
    for provider in _providers():
        try:
            result = provider(messages, temperature, max_tokens, False)
            log_ai_event(
                event_type=event_type,
                provider=result.provider,
                model=result.model,
                success=True,
                latency_ms=result.latency_ms,
                user_id=user_id,
                interview_id=interview_id,
                prompt_tokens=prompt_tokens,
                output_tokens=max(1, len(result.text.split())),
                metadata=metadata,
            )
            return result
        except Exception as exc:
            errors.append(f"{provider.__name__}: {type(exc).__name__}")
            logger.warning("LLM provider failed for %s: %s", event_type, redact_text(exc))

    log_ai_event(
        event_type=event_type,
        success=False,
        user_id=user_id,
        interview_id=interview_id,
        prompt_tokens=prompt_tokens,
        metadata={"errors": errors, **(metadata or {})},
    )
    raise LLMRoutingError(f"All LLM providers failed: {', '.join(errors)}")


def complete_json_sync(
    messages: List[Dict[str, str]],
    *,
    event_type: str,
    temperature: float = 0.2,
    max_tokens: int = 1200,
    user_id: Optional[str] = None,
    interview_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    result = None
    errors: List[str] = []
    prompt_tokens = _token_estimate(messages)

    for provider in _providers():
        try:
            result = provider(messages, temperature, max_tokens, True)
            parsed = json.loads(_strip_json_markdown(result.text))
            log_ai_event(
                event_type=event_type,
                provider=result.provider,
                model=result.model,
                success=True,
                latency_ms=result.latency_ms,
                user_id=user_id,
                interview_id=interview_id,
                prompt_tokens=prompt_tokens,
                output_tokens=max(1, len(result.text.split())),
                metadata=metadata,
            )
            return parsed
        except Exception as exc:
            provider_name = getattr(provider, "__name__", "provider")
            errors.append(f"{provider_name}: {type(exc).__name__}")
            logger.warning("JSON LLM provider failed for %s: %s", event_type, redact_text(exc))

    log_ai_event(
        event_type=event_type,
        success=False,
        user_id=user_id,
        interview_id=interview_id,
        prompt_tokens=prompt_tokens,
        metadata={"errors": errors, **(metadata or {})},
    )
    raise LLMRoutingError(f"All JSON LLM providers failed: {', '.join(errors)}")


def chunk_text(text: str, chunk_size: int = 24) -> Iterable[str]:
    words = text.split()
    if not words:
        return
    for index in range(0, len(words), chunk_size):
        yield " ".join(words[index:index + chunk_size]) + (" " if index + chunk_size < len(words) else "")
