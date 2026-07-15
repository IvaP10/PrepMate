import asyncio

import interview
from interview import _can_voluntarily_cancel


def test_only_live_attempts_can_be_voluntarily_cancelled():
    assert _can_voluntarily_cancel("in_progress")
    assert _can_voluntarily_cancel("uploading")
    assert _can_voluntarily_cancel("recovering")

    assert not _can_voluntarily_cancel("analysis_pending")
    assert not _can_voluntarily_cancel("analysis_running")
    assert not _can_voluntarily_cancel("completed")
    assert not _can_voluntarily_cancel("partial")
    assert not _can_voluntarily_cancel("failed")
    assert not _can_voluntarily_cancel("cancelled")


def test_persisted_behavioral_evidence_checks_owner_through_interview(monkeypatch):
    captured = {}

    async def fake_execute(query, params, **kwargs):
        captured["query"] = " ".join(query.split())
        captured["params"] = params
        return (True,)

    monkeypatch.setattr(interview, "async_execute", fake_execute)

    assert asyncio.run(interview._has_persisted_candidate_evidence("interview-1", "user-1")) is True
    assert "JOIN Interviews owner ON owner.interview_id = response.interview_id" in captured["query"]
    assert "response.user_id" not in captured["query"]
    assert captured["params"][:2] == ("interview-1", "user-1")
