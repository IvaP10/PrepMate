import importlib
import sys

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
