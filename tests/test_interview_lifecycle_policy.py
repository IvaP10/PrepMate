import asyncio
from pathlib import Path

import interview
from interview import (
    _analysis_report_state,
    _can_voluntarily_cancel,
    _detailed_response_status,
    _stored_report_question_status,
)


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


def test_detailed_response_status_preserves_unanswered_and_ungradable_truth():
    assert _detailed_response_status({"response": ""}) == "Not Answered"
    assert _detailed_response_status({
        "response": "I tried Redis.",
        "assessment": {"insufficient_evidence": True},
        "insufficient_evidence": True,
        "score": None,
    }) == "Incomplete"
    assert _detailed_response_status({
        "response": "I used Redis to cache profiles.",
        "assessment": None,
        "score": None,
    }) == "Unable to Evaluate"
    assert _detailed_response_status({
        "response": "I used Redis to cache profiles.",
        "assessment": {"overall_score": 72},
        "score": 72,
    }) == "Completed"


def test_legacy_canonical_question_with_answer_is_not_returned_as_unanswered():
    assert _stored_report_question_status({"response": "I owned the rollout.", "score": 82}) == "Completed"
    assert _stored_report_question_status({"response": "I owned the rollout.", "status": "Not Answered", "score": 82}) == "Completed"
    assert _stored_report_question_status({"response": ""}) == "Not Answered"


def test_analysis_report_state_distinguishes_recovery_and_incomplete_attempts():
    base = {
        "report_ready": False,
        "stored_report": None,
        "job_status": None,
        "manual_retry_count": 0,
    }
    assert _analysis_report_state(
        interview_status="recovering",
        attempt_status="recovering",
        **base,
    ) == "recovering"
    assert _analysis_report_state(
        interview_status="cancelled",
        attempt_status="incomplete",
        **base,
    ) == "unavailable"
    assert _analysis_report_state(
        interview_status="analysis_pending",
        attempt_status="completed",
        **base,
    ) == "generating"


def test_interview_start_has_no_remote_capacity_or_plan_gate():
    source = Path(interview.__file__).read_text(encoding="utf-8")

    assert "_require_interview_start_capacity" not in source
    assert "_interview_start_limiter" not in source
    assert "entitlement_snapshot" not in source
