from report_generator import build_async_behavioral_report, build_async_technical_report


def test_behavioral_report_without_candidate_evidence_is_explicitly_unscored():
    report = build_async_behavioral_report(
        interview_id="interview-1",
        profile_type="mid_tier",
        nlp_output={"turns": []},
        audio_output={},
        video_output={},
        cheating_output={},
    )

    assert report["overall_score"] is None
    assert report["evidence_status"]["status"] == "no_candidate_evidence"
    assert report["readiness_label"] == "Not gradable"
    assert "microphone" in report["improvements"][0]["detail"]
    assert "typed" not in report["improvements"][0]["detail"]


def test_technical_draft_or_run_is_not_presented_as_final_correctness():
    report = build_async_technical_report(
        interview_id="technical-1",
        profile_type="top_tier",
        nlp_output={"turns": []},
        technical_output={
            "submission_count": 0,
            "typed_response_count": 0,
            "typed_assessed_count": 0,
            "run_event_count": 1,
            "draft_count": 1,
            "evidence": {"run_ids": ["run-1"]},
        },
        cheating_output={},
    )

    assert report["overall_score"] is None
    assert report["report_subtype"] == "technical_draft_only"
    assert report["evidence_status"]["status"] == "draft_or_run_only"
    assert report["evidence_summary"]["submission_count"] == 0


def test_behavioral_finding_carries_sealed_response_reference_and_measurement():
    turn = {
        "response_id": "response-1",
        "question": "Describe an owned result.",
        "topic": "Ownership",
        "overall_score": 82,
        "communication_score": 80,
        "star_score": 85,
        "technical_score": 75,
        "confidence": "high",
        "confidence_value": 0.9,
        "insufficient_evidence": False,
        "feedback": "The answer named the owned change and measured result.",
        "evidence": ["Reduced p95 latency by 25 percent."],
    }
    report = build_async_behavioral_report(
        interview_id="interview-1",
        profile_type="mid_tier",
        nlp_output={
            "turns": [turn],
            "communication_score": 80,
            "average_star_score": 85,
            "content_depth_score": 75,
        },
        audio_output={}, video_output={}, cheating_output={},
    )

    finding = report["findings"][0]
    assert finding["evidence_ids"] == ["response-1"]
    assert finding["finding_key"].startswith("behavioral:response-1")
    assert finding["recommended_action"]
    assert finding["measurement"]


def test_technical_finding_uses_final_submission_not_run_or_draft():
    submission = {
        "submission_id": "submission-1",
        "round_id": "round-1",
        "language": "python",
        "visible_passed": 2,
        "visible_total": 2,
        "hidden_passed": 1,
        "hidden_total": 2,
        "submit_number": 1,
        "runtime_ms": 10,
        "memory_kb": 32,
        "title": "Pair Sum",
    }
    report = build_async_technical_report(
        interview_id="technical-1",
        profile_type="top_tier",
        nlp_output={"turns": []},
        technical_output={
            "submission_count": 1,
            "typed_response_count": 0,
            "typed_assessed_count": 0,
            "run_event_count": 3,
            "draft_count": 1,
            "correctness_score": 75,
            "submissions": [submission],
            "test_matrix": [],
            "weak_topics": [],
            "evidence": {"final_submission_present": True},
        },
        cheating_output={},
    )

    assert report["findings"][0]["evidence_ids"] == ["submission-1"]
    assert "3 of 4" in report["findings"][0]["what_happened"]
