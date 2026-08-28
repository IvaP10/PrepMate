import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest
import httpx

import local_settings_api
import local_ai_provider
import local_runtime
import database
from local_ai_provider import LocalProviderError, ProviderResponse


def _request(api_key: str | None = "valid-test-key") -> local_settings_api.ProviderSettingsRequest:
    return local_settings_api.ProviderSettingsRequest(
        provider="openai",
        model="gpt-test",
        endpoint="",
        api_key=api_key,
    )


def test_provider_settings_are_persisted_only_after_a_successful_probe(monkeypatch):
    probe = AsyncMock(return_value=ProviderResponse(
        text="OK", provider="openai", model="gpt-test", latency_ms=12,
    ))
    save_key = Mock()
    save_preferences = Mock(return_value={
        "provider": "openai",
        "model": "gpt-test",
        "endpoint": "",
        "theme": "light",
        "has_api_key": True,
    })
    monkeypatch.setattr(local_settings_api, "test_connection_with_settings", probe)
    monkeypatch.setattr(local_settings_api, "get_local_preferences", lambda: {
        "provider": "openai", "model": "old-model", "endpoint": "",
    })
    monkeypatch.setattr(local_settings_api, "set_provider_api_key", save_key)
    monkeypatch.setattr(local_settings_api, "save_local_preferences", save_preferences)

    result = asyncio.run(local_settings_api.update_settings(_request()))

    probe.assert_awaited_once()
    save_key.assert_called_once_with("openai", "valid-test-key")
    save_preferences.assert_called_once_with(provider="openai", model="gpt-test", endpoint="")
    assert result["connection"] == {"success": True, "latency_ms": 12}


def test_failed_provider_probe_does_not_persist_key_or_preferences(monkeypatch):
    monkeypatch.setattr(local_settings_api, "get_local_preferences", lambda: {
        "provider": "openai", "model": "old-model", "endpoint": "",
    })
    monkeypatch.setattr(
        local_settings_api,
        "test_connection_with_settings",
        AsyncMock(side_effect=LocalProviderError("provider rejected the key")),
    )
    save_key = Mock()
    save_preferences = Mock()
    monkeypatch.setattr(local_settings_api, "set_provider_api_key", save_key)
    monkeypatch.setattr(local_settings_api, "save_local_preferences", save_preferences)

    with pytest.raises(local_settings_api.HTTPException) as rejected:
        asyncio.run(local_settings_api.update_settings(_request()))

    assert rejected.value.status_code == 422
    save_key.assert_not_called()
    save_preferences.assert_not_called()


def test_loading_settings_uses_a_nonsecret_marker_without_reading_keychain(tmp_path, monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("PREPMATE_DATA_DIR", str(tmp_path))
    local_runtime.save_local_preferences(provider="openai", model="gpt-test", endpoint="")
    local_runtime.set_provider_api_key("openai", "synthetic-test-key")
    monkeypatch.setattr(
        local_runtime,
        "get_provider_api_key",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("startup read the Keychain")),
    )

    settings = local_runtime.get_local_preferences()

    assert settings["has_api_key"] is True
    assert "synthetic-test-key" not in (tmp_path / "settings.json").read_text(encoding="utf-8")


def test_keyless_loopback_save_never_reads_keychain(monkeypatch):
    probe = AsyncMock(return_value=ProviderResponse(
        text="OK", provider="openai_compatible", model="local-model", latency_ms=4,
    ))
    monkeypatch.setattr(local_settings_api, "test_connection_with_settings", probe)
    monkeypatch.setattr(local_settings_api, "has_provider_api_key", lambda _provider: False)
    monkeypatch.setattr(
        local_settings_api,
        "get_provider_api_key",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("keyless save read the Keychain")),
    )
    monkeypatch.setattr(local_settings_api, "get_local_preferences", lambda: {
        "provider": "openai", "model": "old-model", "endpoint": "", "has_api_key": False,
    })
    monkeypatch.setattr(local_settings_api, "save_local_preferences", lambda **_kwargs: {
        "provider": "openai_compatible",
        "model": "local-model",
        "endpoint": "http://localhost:11434/v1",
        "theme": "light",
        "has_api_key": False,
        "requires_api_key": False,
    })

    result = asyncio.run(local_settings_api.update_settings(local_settings_api.ProviderSettingsRequest(
        provider="openai_compatible",
        model="local-model",
        endpoint="http://localhost:11434/v1",
        api_key=None,
    )))

    assert result["connection"] == {"success": True, "latency_ms": 4}


def test_google_provider_key_is_not_placed_in_a_request_url():
    source = __import__("pathlib").Path(__import__("local_ai_provider").__file__).read_text(encoding="utf-8")

    assert 'headers={"x-goog-api-key": api_key' in source
    assert 'params={"key": api_key}' not in source


def test_official_openai_payload_uses_current_reasoning_model_fields(monkeypatch):
    captured: dict[str, object] = {}

    class Client:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, url, **kwargs):
            captured.update({"url": url, **kwargs})
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": "OK"}}]},
                request=httpx.Request("POST", url),
            )

    monkeypatch.setattr(local_ai_provider.httpx, "AsyncClient", Client)
    asyncio.run(local_ai_provider.complete_chat(
        [{"role": "user", "content": "hello"}],
        temperature=0.2,
        max_tokens=128,
        _preferences={"provider": "openai", "model": "gpt-5-mini", "endpoint": ""},
        _api_key="valid-test-key",
    ))

    payload = captured["json"]
    assert isinstance(payload, dict)
    assert payload["max_completion_tokens"] == 128
    assert "max_tokens" not in payload
    assert "temperature" not in payload


def test_openai_compatible_payload_retains_legacy_fields(monkeypatch):
    captured: dict[str, object] = {}

    class Client:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, url, **kwargs):
            captured.update({"url": url, **kwargs})
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": "OK"}}]},
                request=httpx.Request("POST", url),
            )

    monkeypatch.setattr(local_ai_provider.httpx, "AsyncClient", Client)
    asyncio.run(local_ai_provider.complete_chat(
        [{"role": "user", "content": "hello"}],
        temperature=0.2,
        max_tokens=128,
        _preferences={
            "provider": "openai_compatible",
            "model": "local-model",
            "endpoint": "http://127.0.0.1:11434/v1",
        },
        _api_key="",
    ))

    payload = captured["json"]
    assert isinstance(payload, dict)
    assert payload["max_tokens"] == 128
    assert payload["temperature"] == 0.2
    assert "max_completion_tokens" not in payload


def test_cache_clear_is_scoped_to_a_configured_workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("PREPMATE_DATA_DIR", str(tmp_path))
    data_dir = local_runtime.local_data_dir()
    (data_dir / "models").mkdir()
    (data_dir / "models" / "synthetic.bin").write_bytes(b"model")
    (data_dir / "prepmate.sqlite3").write_bytes(b"history-placeholder")

    result = local_runtime.clear_local_caches()

    assert result["data_directory"] == str(data_dir)
    assert not (data_dir / "models").exists()
    assert (data_dir / "prepmate.sqlite3").exists()
    assert Path(result["data_directory"]) == data_dir


def test_complete_wipe_is_scoped_recreates_schema_and_clears_test_keychain(tmp_path, monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("PREPMATE_DATA_DIR", str(tmp_path))
    database.close_connection_pool()
    try:
        database.ensure_local_schema()
        local_runtime.save_local_preferences(
            provider="openai",
            model="synthetic-model",
            endpoint="",
        )
        local_runtime.set_provider_api_key("openai", "synthetic-test-key")
        (tmp_path / "models").mkdir()
        (tmp_path / "models" / "synthetic.bin").write_bytes(b"synthetic")
        (tmp_path / "prepmate.sqlite3.backup-synthetic").write_bytes(b"backup")
        with database.get_db() as connection:
            connection.execute(
                "UPDATE UserInfo SET full_name = 'Private Synthetic Name' WHERE user_id = ?",
                (local_runtime.LOCAL_USER_ID,),
            )
            connection.commit()

        result = local_runtime.wipe_local_data()

        with database.get_db() as connection:
            users = connection.execute(
                "SELECT user_id, full_name FROM UserInfo ORDER BY user_id"
            ).fetchall()
        assert result["database_recreated"] is True
        assert users == [(local_runtime.LOCAL_USER_ID, "Local user")]
        assert local_runtime.get_provider_api_key("openai") == ""
        assert not (tmp_path / "settings.json").exists()
        assert not (tmp_path / "models").exists()
        assert not list(tmp_path.glob("*.sqlite3.backup-*"))
    finally:
        database.close_connection_pool()


def test_diagnostics_exclude_provider_secrets_paths_and_content(monkeypatch):
    secret_endpoint = "https://private-provider.example/v1"
    monkeypatch.setattr(local_settings_api, "get_local_preferences", lambda: {
        "provider": "openai_compatible",
        "model": "private-model-name",
        "endpoint": secret_endpoint,
        "has_api_key": True,
    })
    monkeypatch.setattr(local_settings_api, "verify_local_schema", lambda: {
        "version": 3,
        "revision": database.LOCAL_SCHEMA_REVISION,
    })
    monkeypatch.setattr(local_settings_api, "executor_status", lambda: {
        "healthy": False,
        "executor": "unavailable",
        "available_languages": [],
    })

    payload = asyncio.run(local_settings_api.get_redacted_diagnostics())
    serialized = __import__("json").dumps(payload)

    assert payload["provider"]["endpoint_scope"] == "remote_https"
    assert payload["provider"]["credential_configured"] is True
    assert secret_endpoint not in serialized
    assert "private-model-name" not in serialized
    assert "data_directory" not in serialized
