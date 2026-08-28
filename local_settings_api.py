"""Settings API for the standalone desktop app."""

from __future__ import annotations

import platform
import sys
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from local_ai_provider import LocalProviderError, test_connection, test_connection_with_settings
from database import verify_local_schema
from local_execution import executor_status
from local_runtime import (
    delete_provider_api_key,
    get_local_preferences,
    get_provider_api_key,
    has_provider_api_key,
    normalize_provider_preferences,
    save_local_preferences,
    save_local_theme,
    set_provider_api_key,
    clear_local_caches,
    wipe_local_data,
)


router = APIRouter(prefix="/api/local", tags=["local-settings"])
APP_VERSION = "0.1.0-alpha.1"


class ProviderSettingsRequest(BaseModel):
    provider: str = Field(min_length=2, max_length=32)
    model: str = Field(min_length=1, max_length=160)
    endpoint: str = Field(default="", max_length=500)
    api_key: str | None = Field(default=None, max_length=500)


class ThemeRequest(BaseModel):
    theme: str = Field(pattern="^(light|dark)$")


class WipeRequest(BaseModel):
    confirmation: str = Field(min_length=4, max_length=16)


@router.get("/settings")
async def get_settings() -> dict[str, Any]:
    return get_local_preferences()


@router.get("/diagnostics")
async def get_redacted_diagnostics() -> dict[str, Any]:
    """Return copy-safe capability metadata without paths, keys, or content."""
    preferences = get_local_preferences()
    endpoint = str(preferences.get("endpoint") or "").strip()
    endpoint_scope = "none"
    if endpoint:
        hostname = str(urlsplit(endpoint).hostname or "").lower()
        endpoint_scope = "loopback" if hostname in {"localhost", "127.0.0.1", "::1"} else "remote_https"
    execution = executor_status()
    schema = verify_local_schema()
    return {
        "format": "prepmate-redacted-diagnostics-v1",
        "application": {
            "version": APP_VERSION,
            "runtime": "packaged" if getattr(sys, "frozen", False) else "source",
        },
        "system": {
            "platform": platform.system(),
            "architecture": platform.machine(),
            "python": platform.python_version(),
        },
        "provider": {
            "type": str(preferences.get("provider") or "not_configured"),
            "model_configured": bool(str(preferences.get("model") or "").strip()),
            "credential_configured": bool(preferences.get("has_api_key")),
            "endpoint_scope": endpoint_scope,
        },
        "storage": {
            "schema_version": schema["version"],
            "schema_revision": schema["revision"],
        },
        "technical_execution": {
            "available": bool(execution.get("healthy")),
            "sandbox": execution.get("executor"),
            "languages": sorted(execution.get("available_languages") or []),
        },
        "redactions": [
            "api_keys", "encryption_key", "provider_endpoint", "model_name",
            "local_paths", "resumes", "answers", "transcripts", "reports", "logs",
        ],
    }


@router.put("/settings")
async def update_settings(request: ProviderSettingsRequest) -> dict[str, Any]:
    try:
        previous = get_local_preferences()
        provider, model, endpoint = normalize_provider_preferences(
            request.provider,
            request.model,
            request.endpoint,
        )
        candidate_key = str(request.api_key or "").strip()
        if not candidate_key and has_provider_api_key(provider):
            try:
                candidate_key = get_provider_api_key(provider)
            except RuntimeError:
                candidate_key = ""
        probe = await test_connection_with_settings(
            provider=provider,
            model=model,
            endpoint=endpoint,
            api_key=candidate_key,
        )
        result = save_local_preferences(provider=provider, model=model, endpoint=endpoint)
        if request.api_key is not None:
            try:
                set_provider_api_key(provider, request.api_key)
            except Exception:
                save_local_preferences(
                    provider=str(previous.get("provider") or "openai"),
                    model=str(previous.get("model") or "gpt-5-mini"),
                    endpoint=str(previous.get("endpoint") or ""),
                )
                raise
        return {
            **result,
            "has_api_key": bool(candidate_key) or result["has_api_key"],
            "connection": {"success": True, "latency_ms": probe.latency_ms},
        }
    except LocalProviderError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Connection test failed: {exc}") from exc
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc


@router.delete("/settings/key")
async def remove_api_key() -> dict[str, Any]:
    try:
        delete_provider_api_key()
    except RuntimeError as exc:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(exc)) from exc
    return {**get_local_preferences(), "success": True, "has_api_key": False}


@router.delete("/settings/keys")
async def remove_all_api_keys() -> dict[str, Any]:
    try:
        for provider in ("openai", "anthropic", "google", "openai_compatible"):
            delete_provider_api_key(provider)
    except RuntimeError as exc:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(exc)) from exc
    return {**get_local_preferences(), "success": True, "has_api_key": False}


@router.post("/settings/test")
async def test_settings() -> dict[str, Any]:
    try:
        result = await test_connection()
    except LocalProviderError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    return {
        "success": True,
        "provider": result.provider,
        "model": result.model,
        "latency_ms": result.latency_ms,
        "message": "The selected provider responded successfully.",
    }


@router.put("/theme")
async def update_theme(request: ThemeRequest) -> dict[str, Any]:
    try:
        save_local_theme(request.theme)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    return {"theme": request.theme}


@router.post("/data/wipe")
async def wipe_data(request: WipeRequest) -> dict[str, Any]:
    """Erase local user data only after an explicit confirmation phrase."""
    if request.confirmation.strip().upper() != "WIPE":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Type WIPE to confirm removal of local data.",
        )
    try:
        _start_local_worker = None
        # Stop the optional worker before replacing the SQLite file. Importing
        # lazily avoids an app/router import cycle during startup.
        try:
            from app import _stop_local_worker, _start_local_worker
            await _stop_local_worker()
        except Exception:
            pass
        try:
            result = wipe_local_data()
        finally:
            if _start_local_worker is not None:
                await _start_local_worker()
        return {"success": True, **result}
    except RuntimeError as exc:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(exc)) from exc


@router.post("/data/cache/clear")
async def clear_cache_data() -> dict[str, Any]:
    """Remove downloaded models and caches while retaining user history."""
    try:
        return {"success": True, **clear_local_caches()}
    except RuntimeError as exc:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(exc)) from exc


@router.get("/providers")
async def list_providers() -> dict[str, Any]:
    return {
        "providers": [
            {
                "id": "openai",
                "label": "OpenAI",
                "default_model": "gpt-5-mini",
                "models": ["gpt-5-mini", "gpt-5", "gpt-4o-mini"],
                "endpoint_required": False,
            },
            {
                "id": "anthropic",
                "label": "Anthropic",
                "default_model": "claude-sonnet-5",
                "models": ["claude-sonnet-5", "claude-haiku-4-5"],
                "endpoint_required": False,
            },
            {
                "id": "google",
                "label": "Google Gemini",
                "default_model": "gemini-3.7-flash",
                "models": ["gemini-3.7-flash", "gemini-2.5-flash", "gemini-2.5-pro"],
                "endpoint_required": False,
            },
            {
                "id": "openai_compatible",
                "label": "OpenAI-compatible",
                "default_model": "your-model",
                "models": [],
                "endpoint_required": True,
            },
        ]
    }
