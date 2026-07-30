import os
from unittest.mock import MagicMock, patch

os.environ.setdefault("ENVIRONMENT", "test")

from workspace_api import (
    _build_performance_page_payload,
    _canonical_communication_summary,
    _canonical_dimension_directions,
    _canonical_performance_cohort,
    _canonical_performance_payloads,
    _canonical_project_explanation,
    _interview_performance_payload,
    _legacy_performance_history,
    _performance_payload_trend,
)


def _session(interview_id: str, communication: float, technical: float, project_score: float):
    return {
        "interview_id": interview_id,
        "analysis": {
            "dimension_scores": {
                "communication_clarity": communication,
                "technical_competency": technical,
            },
            "question_analyses": [
                {
                    "question": "Tell me about yourself",
                    "overall_score": 62,
                    "answer_quality_flags": ["too_short"],
                },
                {
                    "question": "Explain your project architecture and impact",
                    "overall_score": project_score,
                    "dimension_scores": {
                        "communication": communication,
                        "depth": technical,
                        "tradeoffs": technical - 4,
                        "ownership": project_score,
                    },
                },
            ],
            "measured_communication": {
                "audio": {
                    "filler_count": 3,
                    "voiced_duration_seconds": 120,
                    "words_per_minute": 148,
                    "response_latency_seconds_avg": 2.4,
                }
            },
            "report": {
                "summary": "The candidate is improving with stronger project evidence.",
                "strengths": ["Clear ownership in the strongest project answer."],
                "ai_enhanced": True,
            },
        },
    }


def _canonical_row(
    analysis_id: str,
    *,
    score: float | None,
    evidence_status: str,
    profile_family: str = "mid_tier",
):
    return {
        "analysis_id": analysis_id,
        "overall_score": score,
        "evidence_status": evidence_status,
        "taxonomy_version": "taxonomy-v1",
        "rubric_version": "rubric-v1",
        "evaluator_version": "evaluator-v1",
        "profile_family": profile_family,
    }


def test_latest_insufficient_attempt_does_not_hide_older_official_cohort():
    latest_attempt = _canonical_row(
        "analysis-new-insufficient",
        score=None,
        evidence_status="insufficient_evidence",
    )
    latest_official = _canonical_row(
        "analysis-official-2",
        score=78,
        evidence_status="sufficient",
    )
    older_official = _canonical_row(
        "analysis-official-1",
        score=70,
        evidence_status="sufficient",
    )

    attempt, score_anchor, comparable = _canonical_performance_cohort([
        latest_attempt,
        latest_official,
        older_official,
    ])

    assert attempt["analysis_id"] == "analysis-new-insufficient"
    assert score_anchor["analysis_id"] == "analysis-official-2"
    assert [item["analysis_id"] for item in comparable] == [
        "analysis-official-2",
        "analysis-official-1",
    ]


def test_canonical_performance_orders_by_interview_time_not_reconciliation_time():
    cursor = MagicMock()
    cursor.fetchall.return_value = []

    assert _canonical_performance_payloads(cursor, "user-1") == {
        "interview": None,
        "technical": None,
    }

    query = cursor.execute.call_args.args[0]
    assert "JOIN Interviews interview" in query
    assert "COALESCE(interview.completed_at, interview.created_at) AS session_at" in query
    assert (
        "ORDER BY COALESCE(interview.completed_at, interview.created_at) DESC"
        in query
    )


def test_legacy_history_excludes_interviews_with_canonical_v4_analysis():
    cursor = MagicMock()
    cursor.fetchall.return_value = []

    assert _legacy_performance_history(cursor, "user-1") == []

    query = cursor.execute.call_args.args[0]
    assert "NOT EXISTS" in query
    assert "SessionPerformanceAnalyses analysis" in query
    assert "analysis.schema_version = 'session-performance-v4'" in query
    assert "analysis.is_current = TRUE" in query


def test_communication_patterns_are_only_marked_recurring_across_sessions():
    one_session = _canonical_communication_summary([_session("i-1", 62, 58, 60)])
    two_sessions = _canonical_communication_summary([
        _session("i-1", 62, 58, 60),
        _session("i-2", 74, 70, 73),
    ])

    assert one_session["patterns"][0]["recurring"] is False
    assert any(item["label"] == "Weak self-introduction" and item["recurring"] for item in two_sessions["patterns"])
    assert two_sessions["confidence"]["score"] is not None


def test_project_explanation_uses_every_scored_project_answer():
    result = _canonical_project_explanation([
        _session("i-1", 62, 58, 60),
        _session("i-2", 74, 70, 80),
    ])

    assert result["score"] == 70
    assert result["answer_count"] == 2
    assert result["session_count"] == 2
    assert {item["label"] for item in result["breakdown"]} == {
        "Clarity",
        "Technical Depth",
        "Architecture",
        "Impact",
    }


def test_readiness_uses_communication_technical_consistency_and_history():
    sessions = [
        _session("i-1", 62, 58, 60),
        _session("i-2", 74, 70, 73),
    ]
    communication = _canonical_communication_summary(sessions)
    directions = _canonical_dimension_directions(sessions)
    interview = {
        "overall_score": 72,
        "trend": [{"score": 60}, {"score": 72}],
        "page_summary": {
            "communication": communication,
            "technical": {"latest_score": 70, "knowledge_gaps": []},
            "project_explanation": _canonical_project_explanation(sessions),
            "insights": {**directions, "recurring_mistakes": [], "ai_insights": []},
            "strengths": [],
        },
    }

    page = _build_performance_page_payload(
        interview,
        {"has_data": False, "overview": [], "sections": []},
        {"role": "Backend Engineer", "company": "Acme"},
    )

    readiness = page["overall"]["readiness"]
    assert readiness["score"] is not None
    assert readiness["role"] == "Backend Engineer"
    assert [component["key"] for component in readiness["components"]] == [
        "communication",
        "technical",
        "consistency",
        "history",
    ]
    assert page["overall"]["performance_trend"] == [{"score": 60}, {"score": 72}]


def test_readiness_stays_unscored_until_consistency_can_be_measured():
    interview = {
        "overall_score": 72,
        "trend": [{"score": 72}],
        "page_summary": {
            "communication": {"fluency_clarity": {"score": 76}},
            "technical": {"latest_score": 70},
        },
    }

    page = _build_performance_page_payload(
        interview,
        {},
        {"role": "Backend Engineer", "company": None},
    )

    assert page["overall"]["readiness"]["score"] is None
    assert page["overall"]["readiness"]["label"] == "Building evidence"


def test_performance_views_keep_interview_and_technical_evidence_separate():
    interview = {
        "overall_score": 74,
        "trend": [{"score": 68}, {"score": 74}],
        "page_summary": {
            "communication": {
                "fluency_clarity": {"score": 72},
                "confidence": {"score": 70},
                "patterns": [{"label": "Long openings"}],
            },
            "project_explanation": {"score": 76, "breakdown": []},
            "insights": {
                "recurring_mistakes": [{"label": "Interview mistake"}],
                "improving": [{"label": "Clarity", "delta": 6}],
                "declining": [],
            },
            "strengths": ["Interview strength"],
        },
    }
    technical = {
        "overall_score": 61,
        "trend": [{"score": 55}, {"score": 61}],
        "page_summary": {
            "technical": {
                "knowledge_gaps": [{"label": "Dynamic programming", "score": 48}],
            },
            "insights": {
                "recurring_mistakes": [{"label": "Technical mistake"}],
                "improving": [],
                "declining": [{"label": "Complexity analysis", "delta": -4}],
            },
            "strengths": ["Technical strength"],
        },
    }

    page = _build_performance_page_payload(interview, technical, {})

    assert page["interview_view"]["latest_score"] == 74
    assert page["interview_view"]["insights"]["recurring_mistakes"] == [{"label": "Interview mistake"}]
    assert page["interview_view"]["strengths"] == ["Interview strength"]
    assert page["technical_view"]["latest_score"] == 61
    assert page["technical_view"]["knowledge_gaps"] == [{"label": "Dynamic programming", "score": 48}]
    assert page["technical_view"]["insights"]["recurring_mistakes"] == [{"label": "Technical mistake"}]
    assert page["technical_view"]["strengths"] == ["Technical strength"]


def test_performance_trend_returns_available_scores_immediately_and_caps_at_five():
    assert _performance_payload_trend({"trend": [{"score": 72}]}) == [{"score": 72}]
    points = [{"score": score} for score in range(10, 70, 10)]
    assert _performance_payload_trend({"trend": points}) == points[-5:]


def test_recorded_interview_fallback_exposes_first_score_to_graph():
    interviews = [{"interview_id": "i-1", "date": "2026-07-15", "score": 72}]
    responses = [{
        "interview_id": "i-1",
        "question": "Tell me about yourself",
        "question_type": "main",
        "is_followup": False,
        "response": "I build reliable backend systems.",
        "score": 72,
        "answer_quality_flags": [],
    }]
    with (
        patch("workspace_api._recent_interviews", return_value=interviews),
        patch("workspace_api._response_rows", return_value=responses),
    ):
        payload = _interview_performance_payload(None, "user-1")

    assert payload["trend"] == [{
        "label": "2026-07-15",
        "score": 72,
        "interview_id": "i-1",
    }]
    trend_section = next(section for section in payload["sections"] if section["kind"] == "trend")
    assert trend_section["trend"] == payload["trend"]
