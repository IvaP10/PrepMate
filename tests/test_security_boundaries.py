import asyncio
from unittest.mock import AsyncMock

import pytest
import httpx
from fastapi import HTTPException
from pydantic import ValidationError
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

import analysis
import blueprint_api
import interview
import pre_interview
import technical_mode
import workspace_api
from app import LocalAccessMiddleware


def test_camera_mode_cannot_be_made_mandatory():
    with pytest.raises(ValidationError):
        interview.StartInterviewRequest(camera_mode="required")
    with pytest.raises(ValidationError):
        interview.CreateInterviewBlueprintRequest(camera_mode="required")


class _Cursor:
    def __init__(self, rows=()):
        self.rows = list(rows)
        self.executions = []

    def execute(self, query, params=None):
        self.executions.append((query, params))

    def fetchone(self):
        return self.rows.pop(0) if self.rows else None

    def close(self):
        return None


class _Connection:
    def __init__(self, rows=()):
        self.cursor_value = _Cursor(rows)

    def cursor(self):
        return self.cursor_value

    def commit(self):
        return None

    def rollback(self):
        return None


def _access_application() -> Starlette:
    async def ok(_request):
        return JSONResponse({"ok": True})

    application = Starlette(routes=[Route("/ok", ok), Route("/live", ok)])
    application.add_middleware(LocalAccessMiddleware)
    return application


async def _access_get(path: str, *, headers: dict[str, str] | None = None) -> httpx.Response:
    transport = httpx.ASGITransport(app=_access_application())
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8123") as client:
        return await client.get(path, headers=headers)


def test_local_api_accepts_only_loopback_hosts_and_origins(monkeypatch):
    monkeypatch.delenv("INTERAI_API_TOKEN", raising=False)
    assert asyncio.run(_access_get("/ok")).status_code == 200
    assert asyncio.run(_access_get("/ok", headers={"host": "evil.example"})).status_code == 403
    assert asyncio.run(_access_get("/ok", headers={"origin": "https://evil.example"})).status_code == 403
    assert asyncio.run(_access_get("/ok", headers={"origin": "http://localhost:3000"})).status_code == 200


def test_packaged_local_api_requires_its_per_launch_token(monkeypatch):
    monkeypatch.setenv("INTERAI_API_TOKEN", "test-desktop-session-token")
    assert asyncio.run(_access_get("/ok")).status_code == 401
    assert asyncio.run(_access_get("/ok", headers={"X-InterAI-Token": "wrong"})).status_code == 401
    assert asyncio.run(_access_get("/ok", headers={"X-InterAI-Token": "test-desktop-session-token"})).status_code == 200
    assert asyncio.run(_access_get("/live")).status_code == 200


def test_analysis_lookup_is_scoped_to_the_local_profile(monkeypatch):
    database_call = AsyncMock(return_value=None)
    monkeypatch.setattr(analysis, "async_execute", database_call)

    with pytest.raises(HTTPException) as missing:
        asyncio.run(analysis.trigger_analysis(
            analysis.AnalysisTriggerRequest(interview_id="other-profile-interview"),
            {"user_id": "local-profile"},
        ))

    assert missing.value.status_code == 404
    assert database_call.await_args.args[1] == ("other-profile-interview", "local-profile")


def test_workspace_exercise_lookup_is_scoped_to_the_local_profile(monkeypatch):
    database_call = AsyncMock(return_value=None)
    monkeypatch.setattr(workspace_api, "async_execute", database_call)

    with pytest.raises(HTTPException) as missing:
        asyncio.run(workspace_api.run_exercise_code(
            "other-profile-exercise",
            workspace_api.ExerciseRunRequest(language="python", code="print(1)"),
            {"user_id": "local-profile"},
        ))

    assert missing.value.status_code == 404
    assert database_call.await_args.args[1] == ("other-profile-exercise", "local-profile")


def test_blueprint_lookup_is_scoped_to_the_local_profile(monkeypatch):
    connection = _Connection([None])
    monkeypatch.setattr(blueprint_api, "get_db_connection", lambda: connection)
    monkeypatch.setattr(blueprint_api, "return_db_connection", lambda _connection: None)

    with pytest.raises(HTTPException) as missing:
        asyncio.run(blueprint_api.get_interview_blueprint(
            "other-profile-blueprint",
            {"user_id": "local-profile"},
        ))

    assert missing.value.status_code == 404
    query, params = connection.cursor_value.executions[0]
    assert "blueprint_id = ? AND user_id = ?" in " ".join(query.split())
    assert params == ("other-profile-blueprint", "local-profile")


def test_resume_lookup_is_scoped_to_the_local_profile():
    cursor = _Cursor([None])

    result = pre_interview._load_resume_version(cursor, "local-profile", "other-profile-resume")

    assert result is None
    query, params = cursor.executions[0]
    assert "user_id = ? AND resume_id = ?" in " ".join(query.split())
    assert params == ("local-profile", "other-profile-resume")


def test_technical_run_lookup_is_scoped_to_the_local_profile(monkeypatch):
    database_call = AsyncMock(side_effect=[None, None])
    monkeypatch.setattr(technical_mode, "async_execute", database_call)

    with pytest.raises(HTTPException) as missing:
        asyncio.run(technical_mode.get_run_status(
            "other-profile-run",
            {"user_id": "local-profile"},
        ))

    assert missing.value.status_code == 404
    assert database_call.await_args_list[0].args[1] == ("other-profile-run", "local-profile")
    assert database_call.await_args_list[1].args[1] == ("other-profile-run", "local-profile")
