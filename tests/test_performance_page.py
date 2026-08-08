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
    _cumulative_performance_analytics,
    _interview_performance_payload,
    _legacy_performance_history,
    _merge_recorded_technical_analytics,
    _performance_payload_trend,
    _recorded_technical_analytics,
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


def test_cumulative_interview_analytics_requires_repeated_round_evidence():
    sessions = [
        {
            "interview_id": "i-1",
            "created_at": "2026-08-01T10:00:00",
            "overall_score": 62,
            "evidence_status": "sufficient",
            "analysis": {
                "dimension_scores": {"communication_clarity": 60},
                "question_analyses": [
                    {
                        "response_id": "r-1",
                        "question": "Explain your project architecture",
                        "question_type": "project",
                        "skill": "Project",
                        "taxonomy_keys": ["system_design"],
                        "overall_score": 62,
                        "dimension_scores": {"communication_clarity": 60, "tradeoffs": 55},
                        "answer_quality_flags": ["missing_tradeoffs"],
                    },
                    {
                        "response_id": "r-2",
                        "question": "Why did you choose that database?",
                        "is_followup": True,
                        "overall_score": 48,
                        "dimension_scores": {"technical_accuracy": 48},
                        "answer_quality_flags": ["missing_tradeoffs"],
                    },
                ],
                "report": {"counts": {"questions_asked": 2, "questions_answered": 2}},
            },
        },
        {
            "interview_id": "i-2",
            "created_at": "2026-08-07T10:00:00",
            "overall_score": 78,
            "evidence_status": "sufficient",
            "analysis": {
                "dimension_scores": {"communication_clarity": 76},
                "question_analyses": [
                    {
                        "response_id": "r-3",
                        "question": "Explain your project architecture",
                        "question_type": "project",
                        "skill": "Project",
                        "taxonomy_keys": ["system_design"],
                        "overall_score": 78,
                        "dimension_scores": {"communication_clarity": 76, "tradeoffs": 74},
                        "answer_quality_flags": ["missing_tradeoffs"],
                    },
                    {
                        "response_id": "r-4",
                        "question": "What breaks at scale?",
                        "is_followup": True,
                        "overall_score": 60,
                        "dimension_scores": {"technical_accuracy": 60},
                        "answer_quality_flags": ["missing_tradeoffs"],
                    },
                ],
                "report": {"counts": {"questions_asked": 2, "questions_answered": 2}},
            },
        },
    ]

    analytics = _cumulative_performance_analytics(sessions, "interview")

    assert analytics["summary"]["total_rounds"] == 2
    assert any(item["label"] == "Communication" and item["evaluated_questions"] == 2 for item in analytics["skills"])
    assert any(item["label"] == "System Design" and item["question_count"] == 2 for item in analytics["topics"])
    assert analytics["follow_up"]["followups_evaluated"] == 2
    assert any(item["label"] == "System-design answers omit trade-offs" and item["round_count"] == 2 for item in analytics["patterns"])


def test_cumulative_technical_analytics_separates_attempts_from_unattempted_problems():
    sessions = [
        {
            "interview_id": "t-1",
            "created_at": "2026-08-02T10:00:00",
            "overall_score": 50,
            "evidence_status": "sufficient",
            "analysis": {
                "technical": {
                    "test_matrix": [
                        {"round_id": "p-1", "title": "Two Sum", "algorithm_pattern": "hashing", "evidence_state": "final_submission", "submission_id": "s-1", "final_pass_rate": 50, "final_verdict": "needs_work"},
                        {"round_id": "p-2", "title": "Graph", "algorithm_pattern": "graphs", "evidence_state": "no_evidence", "final_verdict": "no_evidence"},
                    ],
                },
            },
        },
    ]

    analytics = _cumulative_performance_analytics(sessions, "technical")

    assert analytics["submission"]["problems_attempted"] == 1
    assert analytics["submission"]["never_attempted"] == 1
    assert analytics["topics"][0]["label"] == "Hashing"


def test_draft_technical_evidence_surfaces_unsubmitted_code_without_a_score():
    recorded = _recorded_technical_analytics(
        problem_rows=[{
            "interview_id": "t-1",
            "date": "2026-08-08T10:00:00",
            "round_id": "p-1",
            "problem": "Target-Sum Subarrays",
            "evidence": "",
            "failure_reason": "Incomplete implementation",
            "run_count": 0,
        }],
        topic_rows=[{
            "topic": "Hashing",
            "attempts": 1,
            "solved": 0,
            "scores": [],
            "round_count": 1,
            "main_issue": "Incomplete implementation",
        }],
        round_history=[{"interview_id": "t-1"}],
        attempted_count=1,
        total_problems=2,
        submitted_count=0,
        solved_count=0,
        run_counts=[],
    )

    assert recorded["submission"]["coded_not_submitted"] == 1
    assert recorded["submission"]["problems"][0]["issue"] == "No final submission"
    assert recorded["topics"][0]["round_count"] == 1
    assert recorded["patterns"] == []

    merged = _merge_recorded_technical_analytics(
        {
            "score_state": "run_only",
            "analytics": {
                "topics": [],
                "submission": {"coded_not_submitted": 0, "problems": []},
            },
        },
        {"has_data": True, "analytics": recorded},
    )

    assert merged["analytics"]["submission"]["coded_not_submitted"] == 1
    assert merged["comparison_notice"].startswith("Saved coding evidence is shown")
