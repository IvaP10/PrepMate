import os
from unittest.mock import MagicMock, patch

os.environ.setdefault("ENVIRONMENT", "test")

from workspace_api import (
    _answer_problem_type,
    _answer_status,
    _build_performance_page_payload,
    _canonical_communication_summary,
    _canonical_dimension_directions,
    _combined_report_findings,
    _canonical_performance_cohort,
    _canonical_performance_payloads,
    _canonical_project_explanation,
    _canonical_round_findings,
    _cumulative_performance_analytics,
    _interview_performance_payload,
    _legacy_performance_history,
    _merge_recorded_technical_analytics,
    _performance_payload_trend,
    _performance_ready_count,
    _recorded_technical_analytics,
)


def test_missing_assessment_never_becomes_a_properly_answered_performance_row():
    response = {
        "response": "I used Redis to cache profile reads.",
        "answer_quality_flags": [],
        "score": None,
        "evidence_status": "assessment_missing",
        "authoritative": False,
    }

    assert _answer_status(response) == "Unable to evaluate"
    assert _answer_problem_type(response) == "Assessment unavailable"


def test_improve_unlock_count_only_uses_current_sufficient_performance():
    cursor = MagicMock()
    cursor.fetchone.return_value = (2,)

    assert _performance_ready_count(cursor, "user-1") == 2
    query, params = cursor.execute.call_args.args
    assert "status = 'ready'" in query
    assert "evidence_status = 'sufficient'" in query
    assert "is_current = TRUE" in query
    assert "GROUP BY mode" in query
    assert params[0] == "user-1"


def test_insufficient_assessment_stays_explicitly_unscored():
    response = {
        "response": "I helped on the service.",
        "answer_quality_flags": ["insufficient_evidence"],
        "score": None,
        "evidence_status": "insufficient_evidence",
        "authoritative": False,
    }

    assert _answer_status(response) == "Needs reframing"
    assert _answer_problem_type(response) == "Missing evidence"


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
    assert "FROM ReportArtifacts artifact" in query
    assert "artifact.status IN ('completed', 'partial')" in query
    assert "COALESCE(interview.completed_at, interview.created_at) AS session_at" in query
    assert (
        "ORDER BY COALESCE(interview.completed_at, interview.created_at) DESC"
        in query
    )
    assert "LIMIT" not in query


def test_legacy_history_excludes_interviews_with_canonical_v4_analysis():
    cursor = MagicMock()
    cursor.fetchall.return_value = []

    assert _legacy_performance_history(cursor, "user-1") == []

    query = cursor.execute.call_args.args[0]
    assert "NOT EXISTS" in query
    assert "SessionPerformanceAnalyses analysis" in query
    assert "analysis.schema_version = 'session-performance-v4'" in query
    assert "analysis.is_current = TRUE" in query
    assert "FROM ReportArtifacts artifact" in query


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


def test_interview_round_findings_stay_question_specific_and_report_linkable():
    session = {
        "interview_id": "i-1",
        "evidence_status": "sufficient",
        "analysis": {
            "question_analyses": [
                {
                    "response_id": "r-strong",
                    "question": "Walk me through the architecture you built",
                    "overall_score": 84,
                    "answer_quality_flags": [],
                },
                {
                    "response_id": "r-weak",
                    "question": "Why did you choose that database over the alternatives?",
                    "overall_score": 54,
                    "answer_quality_flags": ["missing_tradeoffs"],
                    "dimension_scores": {"tradeoffs": 42},
                },
            ],
            "report": {
                "summary": "Two questions were evaluated.",
                "questions": [
                    {
                        "response_id": "r-strong",
                        "status": "Completed",
                        "what_was_good": ["The architecture and ownership were supported by recorded project evidence."],
                    },
                    {
                        "response_id": "r-weak",
                        "status": "Completed",
                        "what_reduced_score": ["The answer named the selected database but did not compare alternatives or trade-offs."],
                    },
                ],
            },
        },
    }

    findings = _canonical_round_findings(session, "interview")

    assert findings["strengths"][0]["evidence_ids"] == ["r-strong"]
    assert findings["issues"][0]["label"] == "Missing justification or trade-offs"
    assert findings["issues"][0]["source_label"].startswith("Why did you choose")
    assert findings["issues"][0]["evidence_ids"] == ["r-weak"]
    assert "trade-offs" in findings["issues"][0]["detail"]
    assert findings["takeaway"]


def test_interview_round_findings_use_scored_question_evidence_when_report_has_no_question_breakdown():
    findings = _canonical_round_findings({
        "interview_id": "i-scored",
        "evidence_status": "sufficient",
        "analysis": {
            "question_analyses": [{
                "response_id": "r-scored",
                "question": "Describe a production decision you owned",
                "overall_score": 82,
                "dimension_scores": {"ownership": 84, "communication": 80},
                "answer_quality_flags": [],
            }],
            "report": {
                "summary": "The answer showed evidence-backed ownership.",
                "strengths": ["Clear ownership"],
            },
        },
    }, "interview")

    assert findings["issues"] == []
    assert findings["strengths"][0]["source_label"] == "Describe a production decision you owned"
    assert findings["strengths"][0]["evidence_ids"] == ["r-scored"]
    assert "82%" in findings["strengths"][0]["detail"]
    assert "Project / Resume Knowledge" in findings["strengths"][0]["detail"]


def test_technical_round_findings_distinguish_solved_and_failed_problem_evidence():
    session = {
        "interview_id": "t-1",
        "evidence_status": "sufficient",
        "analysis": {
            "report": {
                "summary": "Two problems were submitted; one was solved.",
                "technical": {
                    "problems": [
                        {
                            "round_id": "p-1",
                            "title": "Graph traversal",
                            "status": "Submitted",
                            "score": 100,
                            "final_submission": True,
                            "visible_passed": 3,
                            "visible_total": 3,
                            "hidden_passed": 4,
                            "hidden_total": 4,
                            "evidence_ids": ["s-1"],
                        },
                        {
                            "round_id": "p-2",
                            "title": "Sliding window",
                            "status": "Submitted",
                            "score": 50,
                            "final_submission": True,
                            "main_issue": "The final submission failed two evaluated edge cases.",
                            "what_happened": "The approach was selected, but the left boundary was not advanced after invalidation.",
                            "evidence_ids": ["s-2"],
                        },
                    ],
                },
            },
        },
    }

    findings = _canonical_round_findings(session, "technical")

    assert findings["strengths"][0]["source_label"] == "Graph traversal"
    assert findings["strengths"][0]["evidence_ids"] == ["s-1", "p-1"]
    assert findings["issues"][0]["label"] == "Correctness or edge cases"
    assert findings["issues"][0]["source_label"] == "Sliding window"
    assert findings["issues"][0]["evidence_ids"] == ["s-2", "p-2"]
    assert "left boundary" in findings["issues"][0]["what_happened"]


def test_combined_findings_use_every_report_without_averaging_incompatible_scores():
    rows = []
    for index, date in enumerate(("2026-08-10T10:00:00", "2026-08-01T10:00:00"), start=1):
        rows.append({
            "analysis_id": f"a-{index}",
            "interview_id": f"i-{index}",
            "created_at": date,
            "role": "Backend Engineer",
            "overall_score": 70 + index,
            "evidence_status": "sufficient",
            "taxonomy_version": f"taxonomy-{index}",
            "rubric_version": f"rubric-{index}",
            "analysis": {
                "question_analyses": [
                    {
                        "response_id": f"r-weak-{index}",
                        "question": f"Why did you choose storage option {index}?",
                        "overall_score": 55,
                        "answer_quality_flags": ["missing_tradeoffs"],
                    },
                    {
                        "response_id": f"r-strong-{index}",
                        "question": f"Explain the production incident {index}",
                        "overall_score": 84,
                        "answer_quality_flags": [],
                    },
                ],
                "report": {
                    "questions": [
                        {
                            "response_id": f"r-weak-{index}",
                            "what_reduced_score": [f"Report {index} did not compare the rejected storage alternatives."],
                        },
                        {
                            "response_id": f"r-strong-{index}",
                            "what_was_good": [f"Report {index} connected the action to a measured recovery result."],
                        },
                    ],
                },
            },
        })

    combined = _combined_report_findings(rows, "interview")

    assert combined["summary"]["total_reports"] == 2
    assert combined["summary"]["official_reports"] == 2
    assert combined["summary"]["reports_with_issues"] == 2
    assert combined["summary"]["reports_with_strengths"] == 2
    assert combined["summary"]["recurring_issue_count"] == 1
    assert combined["issues"][0]["label"] == "Missing justification or trade-offs"
    assert combined["issues"][0]["round_count"] == 2
    assert combined["issues"][0]["evidence_count"] == 2
    assert combined["issues"][0]["evidence"][0]["source_label"] == "Why did you choose storage option 1?"
    assert combined["issues"][0].get("average_score") is None
    assert len(combined["strengths"]) == 2


def test_combined_technical_findings_do_not_inflate_one_execution_failure_into_topics():
    combined = _combined_report_findings([{
        "analysis_id": "a-technical",
        "interview_id": "i-technical",
        "created_at": "2026-08-10T10:00:00",
        "overall_score": None,
        "evidence_status": "draft_or_run_only",
        "analysis": {
            "report": {
                "technical": {
                    "problems": [{
                        "round_id": "round-1",
                        "title": "Target-sum subarrays",
                        "status": "Draft only",
                        "evidence_state": "draft_only",
                        "main_issue": "The implementation was incomplete and had no final submission.",
                        "topics": ["Arrays", "Hashing", "Sliding Window"],
                    }],
                },
            },
        },
    }], "technical")

    assert combined["summary"]["total_reports"] == 1
    assert combined["summary"]["official_reports"] == 0
    assert [item["label"] for item in combined["issues"]] == ["Incomplete execution"]
    assert combined["issues"][0]["evidence"][0]["source_label"] == "Target-sum subarrays"


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


def test_recorded_technical_merge_deduplicates_the_same_round_problem():
    merged = _merge_recorded_technical_analytics(
        {
            "score_state": "run_only",
            "analytics": {
                "submission": {
                    "coded_not_submitted": 1,
                    "problems": [{
                        "interview_id": "t-1",
                        "round_id": "p-1",
                        "problem": "Target-Sum Subarrays",
                        "issue": "No final submission",
                        "evidence": [],
                    }],
                },
            },
        },
        {
            "has_data": True,
            "analytics": {
                "submission": {
                    "coded_not_submitted": 1,
                    "problems": [{
                        "interview_id": "t-1",
                        "round_id": "p-1",
                        "problem": "Target-Sum Subarrays",
                        "issue": "No final submission",
                        "run_count": 1,
                        "evidence": [{"interview_id": "t-1", "round_id": "p-1"}],
                    }],
                },
            },
        },
    )

    problems = merged["analytics"]["submission"]["problems"]
    assert len(problems) == 1
    assert problems[0]["run_count"] == 1
    assert problems[0]["evidence"] == [{"interview_id": "t-1", "round_id": "p-1"}]
