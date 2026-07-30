import asyncio
import importlib
import json
import sys

from fastapi.exceptions import RequestValidationError
from starlette.requests import Request

from readiness_contract import build_flow_readiness_payload


def _fresh_app_module():
    # Some pure-unit modules install a deliberately tiny database stub during
    # collection. Readiness tests exercise the real application wiring and
    # must not depend on which test file pytest imported first.
    sys.modules.pop("app", None)
    sys.modules.pop("database", None)
    return importlib.import_module("app")


def _flow_readiness_payload(flow, checks):
    return build_flow_readiness_payload(flow, checks, recovery_grace_seconds=60)


def _checks():
    return {
        "database_migrations": {"healthy": True},
        "redis": {"healthy": True},
        "openai": {"healthy": True},
        "sandbox_executor": {"healthy": False},
        "workers_jobs": {
            "workers": {
                "analysis": {"healthy": True},
                "technical": {"healthy": False},
            },
            "stuck_jobs": {
                "analysis": {"expired_leases": 0, "overdue_queued": 0},
                "technical": {"expired_leases": 0, "overdue_queued": 0},
            },
        },
    }


def test_interview_preflight_requires_only_its_pipeline():
    payload = _flow_readiness_payload("interview", _checks())

    assert payload["ready"] is True
    assert "sandbox_executor" not in payload["checks"]
    assert set(payload["checks"]["workers"]["required"]) == {"analysis"}


def test_technical_preflight_requires_worker_and_private_executor():
    payload = _flow_readiness_payload("technical", _checks())

    assert payload["ready"] is False
    assert payload["checks"]["sandbox_executor"]["healthy"] is False
    assert set(payload["checks"]["workers"]["required"]) == {"analysis", "technical"}


def test_openai_readiness_probes_and_caches_model_availability(monkeypatch):
    app = _fresh_app_module()
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"id": "configured-model"}

    calls = []
    monkeypatch.setattr(app.settings, "OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(app.settings, "OPENAI_CHAT_MODEL", "configured-model")
    monkeypatch.setattr(app.settings, "OPENAI_EVALUATION_MODEL", "evaluation-model")
    monkeypatch.setattr(app.settings, "OPENAI_REPORT_MODEL", "report-model")
    monkeypatch.setattr(app.settings, "OPENAI_TRANSCRIBE_MODEL", "transcribe-model")
    monkeypatch.setattr(app.httpx, "get", lambda *args, **kwargs: calls.append((args, kwargs)) or Response())
    app._openai_probe_cache.update({"checked_at": 0.0, "result": None})

    first = app._openai_configuration_check()
    second = app._openai_configuration_check()

    assert first["healthy"] is True
    assert first["cached"] is False
    assert second["healthy"] is True
    assert second["cached"] is True
    assert len(calls) == 1
    assert calls[0][1]["timeout"] == 2.5


def test_openai_readiness_fails_closed_without_sending_error_details(monkeypatch):
    app = _fresh_app_module()
    monkeypatch.setattr(app.settings, "OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(app.httpx, "get", lambda *args, **kwargs: (_ for _ in ()).throw(TimeoutError("secret detail")))
    app._openai_probe_cache.update({"checked_at": 0.0, "result": None})

    result = app._openai_configuration_check()

    assert result["healthy"] is False
    assert result["error"] == "openai_unavailable"
    assert "secret" not in str(result)


def test_failed_openai_probe_is_retried_quickly(monkeypatch):
    app = _fresh_app_module()

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"id": "configured-model"}

    clock = {"now": 100.0}
    calls = {"count": 0}

    def get(*_args, **_kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise TimeoutError("temporary")
        return Response()

    monkeypatch.setattr(app.settings, "OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(app.settings, "OPENAI_CHAT_MODEL", "configured-model")
    monkeypatch.setattr(app.settings, "OPENAI_EVALUATION_MODEL", "evaluation-model")
    monkeypatch.setattr(app.settings, "OPENAI_REPORT_MODEL", "report-model")
    monkeypatch.setattr(app.settings, "OPENAI_TRANSCRIBE_MODEL", "transcribe-model")
    monkeypatch.setattr(app.httpx, "get", get)
    monkeypatch.setattr(app.time, "monotonic", lambda: clock["now"])
    app._openai_probe_cache.update({"checked_at": 0.0, "result": None})

    first = app._openai_configuration_check()
    cached_failure = app._openai_configuration_check()
    clock["now"] += app._OPENAI_PROBE_FAILURE_TTL_SECONDS + 0.1
    recovered = app._openai_configuration_check()

    assert first["healthy"] is False
    assert cached_failure["healthy"] is False
    assert cached_failure["cached"] is True
    assert recovered["healthy"] is True
    assert recovered["cached"] is False
    assert calls["count"] == 2


def test_worker_readiness_query_uses_wall_clock_instead_of_transaction_start():
    app = _fresh_app_module()

    assert any(
        isinstance(value, str) and "clock_timestamp()" in value
        for value in app._worker_and_job_check.__code__.co_consts
    )


def test_model_validator_errors_return_serializable_422_payload_without_input_leaks():
    app = _fresh_app_module()
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/interview/start",
            "headers": [],
            "query_string": b"",
            "server": ("testserver", 80),
            "client": ("127.0.0.1", 1234),
            "scheme": "http",
        }
    )
    error = RequestValidationError(
        [
            {
                "type": "value_error",
                "loc": ("body",),
                "msg": "Value error, The Interview Round requires voice input",
                "input": {"password": "must-not-leak"},
                "ctx": {"error": ValueError("The Interview Round requires voice input")},
            }
        ]
    )

    response = asyncio.run(app.validation_exception_handler(request, error))
    payload = json.loads(response.body)

    assert response.status_code == 422
    assert payload["detail"] == "Value error, The Interview Round requires voice input"
    assert payload["errors"] == [
        {
            "type": "value_error",
            "loc": ["body"],
            "msg": "Value error, The Interview Round requires voice input",
        }
    ]
    assert "must-not-leak" not in response.body.decode()
