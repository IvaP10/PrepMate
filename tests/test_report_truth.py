from analysis_pipeline import _is_report_ready_status
from interview import _interview_report_ready
from report_generator import build_async_behavioral_report, build_async_technical_report


def test_report_ready_lifecycle_status_accepts_a_persisted_report():
    report = {"overall_score": 78}

    assert _interview_report_ready("report_ready", report) is True
    assert _is_report_ready_status("report_ready", report) is True


def test_interview_report_counts_unanswered_questions_as_zero_and_keeps_facts_separate():
    report = build_async_behavioral_report(
        interview_id="interview-1",
        profile_type="mid_tier",
        nlp_output={
            "turns": [
                {
                    "response_id": "response-1",
                    "question": "Describe an owned result.",
                    "question_type": "behavioral",
                    "response": "I led the migration and reduced p95 latency by 25 percent.",
                    "overall_score": 80,
                    "rubric_scores": {"communication": 80},
                    "evidence_basis": {"covered_point_ids": ["action", "result"]},
                    "insufficient_evidence": False,
                },
                {
                    "question_id": "question-2",
                    "question": "Describe a conflict.",
                    "question_type": "behavioral",
                    "response": "",
                },
            ]
        },
        audio_output={},
        video_output={},
        cheating_output={},
    )

    assert report["overall_score"] == 40.0
    assert report["counts"] == {
        "questions_asked": 2,
        "questions_answered": 1,
        "questions_fully_answered": 1,
        "questions_partially_answered": 0,
        "questions_not_answered": 1,
        "questions_unable_to_evaluate": 0,
    }
    assert report["questions"][1]["status"] == "Not Answered"
    assert report["questions"][1]["score"] == 0
    assert report["questions"][0]["response"] == "I led the migration and reduced p95 latency by 25 percent."
    assert "improvements" not in report
    assert "practice_plan" not in report
    assert "student_summary" not in report
    assert "recommended_action" not in str(report)


def test_interview_response_without_evaluator_is_unable_to_evaluate():
    report = build_async_behavioral_report(
        interview_id="interview-2",
        profile_type="mid_tier",
        nlp_output={
            "turns": [{
                "response_id": "response-2",
                "question": "What did you build?",
                "response": "I built a service.",
            }]
        },
        audio_output={},
        video_output={},
        cheating_output={},
    )

    question = report["questions"][0]
    assert question["status"] == "Unable to Evaluate"
    assert question["score"] is None
    assert report["counts"]["questions_unable_to_evaluate"] == 1


def test_technical_report_scores_submitted_problem_and_keeps_unattempted_problem_at_zero():
    report = build_async_technical_report(
        interview_id="technical-1",
        profile_type="top_tier",
        nlp_output={},
        technical_output={
            "round_count": 2,
            "submission_count": 1,
            "run_event_count": 3,
            "test_matrix": [
                {
                    "round_id": "round-1",
                    "title": "Pair Sum",
                    "language": "python",
                    "prompt": "Full original prompt\nwith all details.",
                    "evidence_state": "final_submission",
                    "submission_id": "submission-1",
                    "source_code": "def solve():\n    return []",
                    "visible_passed": 2,
                    "visible_total": 2,
                    "hidden_passed": 1,
                    "hidden_total": 2,
                    "run_count": 3,
                },
                {
                    "round_id": "round-2",
                    "title": "Graph traversal",
                    "prompt": "Second prompt",
                    "evidence_state": "no_evidence",
                },
            ],
        },
        cheating_output={},
    )

    first, second = report["technical"]["problems"]
    assert report["overall_score"] == 37.5
    assert report["counts"]["problems_attempted"] == 1
    assert report["counts"]["problems_submitted"] == 1
    assert first["status"] == "Submitted"
    assert first["score_points"] == 37.5
    assert first["main_issue"] == "The final submission failed 1 evaluated test(s)."
    assert first["prompt"] == "Full original prompt\nwith all details."
    assert first["source_code"] == "def solve():\n    return []"
    assert second["status"] == "Not Attempted"
    assert second["score"] == 0
    assert second["main_issue"] is None
    assert "improvement_plan" not in report
    assert "next_drills" not in str(report)


def test_technical_run_without_submission_is_incomplete_not_failed_submission():
    report = build_async_technical_report(
        interview_id="technical-2",
        profile_type="top_tier",
        nlp_output={},
        technical_output={
            "round_count": 1,
            "run_event_count": 1,
            "test_matrix": [{
                "round_id": "round-1",
                "title": "Pair Sum",
                "evidence_state": "run_only",
                "run_count": 1,
                "visible_passed": 1,
                "visible_total": 2,
            }],
        },
        cheating_output={},
    )

    problem = report["problems"][0]
    assert problem["status"] == "Incomplete"
    assert problem["score"] == 0
    assert "No final submission" in problem["main_issue"]
    assert report["evidence_status"]["status"] == "draft_or_run_only"


def test_round_analysis_only_contains_repeated_supported_patterns():
    report = build_async_behavioral_report(
        interview_id="interview-3",
        profile_type="mid_tier",
        nlp_output={
            "turns": [
                {
                    "response_id": "r1",
                    "question": "Tell me about a project.",
                    "response": "I built it.",
                    "overall_score": 40,
                    "rubric_scores": {},
                    "evidence_basis": {"missed_point_ids": ["result"]},
                    "insufficient_evidence": False,
                },
                {
                    "response_id": "r2",
                    "question": "Tell me about a conflict.",
                    "response": "I handled it.",
                    "overall_score": 40,
                    "rubric_scores": {},
                    "evidence_basis": {"missed_point_ids": ["result"]},
                    "insufficient_evidence": False,
                },
            ]
        },
        audio_output={},
        video_output={},
        cheating_output={},
    )

    assert report["round_analysis"][0]["pattern"] == "Missing expected points"
    assert report["round_analysis"][0]["evidence_count"] == 2
    assert "next" not in str(report["round_analysis"]).lower()
