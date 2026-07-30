import inspect
import os
from pathlib import Path
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

os.environ.setdefault("ENVIRONMENT", "test")

from workspace_api import (
    ExerciseAttemptCreate,
    ExerciseAttemptSessionUpdate,
    _attempt_session_response,
    create_exercise_attempt_session,
    update_exercise_attempt_session,
)
from improve_scoring import mastery_status_for_checkpoint
from learning_engine import (
    _deterministic_activity_result,
    _decrypt_sensitive_json,
    _encrypted_json_bytes,
    _active_mission_payload,
    _phase_one_activity_definitions,
    _persist_mission_attempt_transaction,
    _public_checkpoint_material,
    _reassessment_is_compatible,
    _reassessment_resource,
    _sanitize_mission_attempt_payload,
)


ROOT = Path(__file__).resolve().parents[1]


def _score(activity, payload, answer=""):
    prompt = activity["prompt"]
    return _deterministic_activity_result(
        prompt,
        {"conditions": prompt.get("pass_conditions", [])},
        answer,
        payload,
        activity["activity_type"],
    )


def test_all_interview_activity_types_accept_valid_server_measurable_evidence():
    activities = _phase_one_activity_definitions("communication", "A weak answer.", mode="mock")
    assert "compare_answers" not in {activity["activity_type"] for activity in activities}
    outline, arrange, rewrite, spoken, checkpoint = activities[1:]
    answer = (
        "I would use a database index because the API needs predictable lookups. "
        "A B-tree narrows the search, and my project test showed lower latency, "
        "with the trade-off of slower writes and extra storage."
    )

    results = [
        _score(
            outline,
            {"rewrite": answer},
            answer,
        ),
        _score(
            arrange,
            {"block_order": ["problem", "user", "solution", "role", "result"]},
            "problem -> user -> solution -> role -> result",
        ),
        _score(rewrite, {"rewrite": answer}, answer),
        _score(spoken, {"transcript": answer}, answer),
        _score(checkpoint, {"answer": answer, "transcript": answer}, answer),
    ]

    assert [item["result_status"] for item in results] == ["strong_pass"] * 5


def test_generated_path_titles_tell_the_user_exactly_what_to_do():
    interview_activities = _phase_one_activity_definitions("communication", "A weak answer.", mode="mock")
    technical_activities = _phase_one_activity_definitions("hash maps", "A failed attempt.", mode="technical")
    interview_titles = [activity["title"] for activity in interview_activities]
    technical_titles = [activity["title"] for activity in technical_activities]

    assert "Write a 4-Part Answer: Direct Point, Decision, Proof, and Result" in interview_titles
    assert "Place the Direct Answer First, Then Context, Proof, and Result" in interview_titles
    assert "Explain the Repaired Answer Aloud in 60 Seconds" in interview_titles
    assert "State the Algorithm, Data Structure, Complexity, and Edge Cases Before Coding" in technical_titles
    assert "List the Exact Edge Cases and Expected Outputs Before Submitting" in technical_titles
    assert not {"Transfer Checkpoint", "Arrange the Answer", "Retry Plan Before Coding"}.intersection(
        interview_titles + technical_titles
    )
    assert all("recommended_resource" not in activity.get("prompt", {}) for activity in interview_activities + technical_activities)


def test_activity_title_is_only_rendered_in_the_modal_header():
    source = (ROOT / "Frontend/components/improve/improve-content.tsx").read_text()

    assert "Before attempt" not in source
    assert "Attempt in progress" not in source
    assert "Time expired. This attempt cannot be submitted" not in source
    assert "secondsLeft" not in source
    assert "formatActivityType(node.activity_type)" not in source
    assert '<h3 className="mt-1 text-2xl font-semibold text-foreground">{roadmapDisplayTitle(node, mode)}</h3>' not in source


def test_improve_attempts_have_no_countdown_or_hidden_deadline():
    sources = (
        inspect.getsource(create_exercise_attempt_session),
        inspect.getsource(update_exercise_attempt_session),
        inspect.getsource(_persist_mission_attempt_transaction),
        inspect.getsource(_active_mission_payload),
    )

    assert all("deadline_at > NOW()" not in source for source in sources)
    assert "timer_seconds" not in sources[0]
    assert "remaining_seconds = NULL" in sources[1]


def test_learning_resources_are_selected_after_official_reassessment():
    interview_resource = _reassessment_resource("mock")
    technical_resource = _reassessment_resource("technical")

    assert interview_resource["provider"] == "YouTube"
    assert "youtube.com" in interview_resource["url"]
    assert technical_resource["provider"] == "GeeksforGeeks"
    assert "geeksforgeeks.org" in technical_resource["url"]


def test_technical_spoken_plan_recognizes_algorithm_complexity_and_edge_case():
    spoken = _phase_one_activity_definitions("hash maps", "A failed attempt.", mode="technical")[2]
    answer = (
        "I would use a hash map to track counts in one pass, giving O(n) time and "
        "O(n) space, then test empty input and duplicate values."
    )

    result = _score(spoken, {"transcript": answer}, answer)

    assert result["score"] == 100.0
    assert result["mastery_passed"] is True


@pytest.mark.parametrize("activity_index", [1, 2, 3, 4, 5])
def test_client_condition_bonus_and_mastery_claims_never_affect_scoring(activity_index):
    activity = _phase_one_activity_definitions("communication", "A weak answer.", mode="mock")[activity_index]
    forged = {
        "condition_results": [
            {"id": item["id"], "met": True, "evidence": "client assertion"}
            for item in activity["prompt"].get("pass_conditions", [])
        ],
        "bonus_points": 100,
        "score": 100,
        "mastery_passed": True,
    }

    result = _score(activity, forged, "")

    assert result["score"] == 0.0
    assert result["mastery_passed"] is False


def test_mission_payload_allowlist_discards_every_server_owned_field():
    payload = _sanitize_mission_attempt_payload(
        "rewrite_answer",
        {
            "rewrite": "I owned the API and measured a 20% latency reduction.",
            "idempotency_key": "attempt-123",
            "attempt_session_id": "session-123",
            "mission_id": "mission-123",
            "roadmap_node_id": "roadmap-123",
            "score": 100,
            "bonus_points": 100,
            "condition_results": [{"id": "result", "met": True}],
            "mastery_passed": True,
        },
    )

    assert payload == {
        "rewrite": "I owned the API and measured a 20% latency reduction.",
        "idempotency_key": "attempt-123",
        "attempt_session_id": "session-123",
        "mission_id": "mission-123",
        "roadmap_node_id": "roadmap-123",
    }


def test_checkpoint_is_held_out_passed_not_verified():
    assert mastery_status_for_checkpoint(
        checkpoint_score=82,
        guided_passes=2,
        variation_passes=1,
    ) == "held_out_passed"


def test_checkpoint_public_payload_never_exposes_rubric_or_pass_conditions():
    prompt, rubric, evidence = _public_checkpoint_material(
        {
            "question": "Explain a related problem.",
            "timer_seconds": 60,
            "pass_conditions": [{"id": "hidden", "label": "Secret criterion"}],
            "model_answer": "Secret answer",
        },
        {"pass_score": 75, "checks": ["Secret criterion"]},
        [{"answer_excerpt": "Previously practised answer"}],
        True,
    )

    assert prompt == {"question": "Explain a related problem.", "timer_seconds": 60}
    assert rubric == {}
    assert evidence == []


def test_official_reassessment_requires_matching_versions_sufficient_evidence_and_later_time():
    checkpoint_time = datetime(2026, 7, 14, 10, 0, tzinfo=timezone.utc)
    reassessment_time = datetime(2026, 7, 14, 11, 0, tzinfo=timezone.utc)
    versions = ("evaluator-v2", "taxonomy-v2", "rubric-v2")

    assert _reassessment_is_compatible(
        source_versions=versions,
        reassessment_versions=versions,
        evidence_status="sufficient",
        checkpoint_completed_at=checkpoint_time,
        reassessment_created_at=reassessment_time,
    )
    assert not _reassessment_is_compatible(
        source_versions=versions,
        reassessment_versions=("evaluator-v3", "taxonomy-v2", "rubric-v2"),
        evidence_status="sufficient",
        checkpoint_completed_at=checkpoint_time,
        reassessment_created_at=reassessment_time,
    )
    assert not _reassessment_is_compatible(
        source_versions=versions,
        reassessment_versions=versions,
        evidence_status="insufficient_evidence",
        checkpoint_completed_at=checkpoint_time,
        reassessment_created_at=reassessment_time,
    )


def test_attempt_contract_requires_idempotency_and_does_not_overwrite_missing_draft():
    with pytest.raises(ValidationError):
        ExerciseAttemptCreate(submitted_answer="answer")

    update = ExerciseAttemptSessionUpdate(
        mission_id="mission-123",
        roadmap_node_id="roadmap-123",
        idempotency_key="attempt-123",
        status="in_progress",
    )
    assert update.draft_payload is None


def test_attempt_draft_round_trips_only_through_encrypted_storage():
    draft = {"rewrite": "I owned the private candidate API answer."}
    encrypted = _encrypted_json_bytes(draft)
    marker = {"encrypted": True, "field_count": 1}

    assert b"private candidate API answer" not in encrypted
    assert _decrypt_sensitive_json(encrypted, marker) == draft

    now = datetime.now(timezone.utc)
    response = _attempt_session_response(
        ("session-1", "draft", encrypted, marker, "attempt-123", None, 42, now, now,
         "mission-1", "roadmap-1", "exercise-1")
    )
    assert response["draft_payload"] == draft
    assert response["mission_id"] == "mission-1"


def test_persistable_deterministic_feedback_does_not_echo_candidate_answer():
    activity = _phase_one_activity_definitions("communication", "A weak answer.", mode="mock")[3]
    answer = "I owned a private API because latency mattered, and tests showed a 20% improvement."

    result = _score(activity, {"rewrite": answer}, answer)

    assert answer not in str(result["feedback"])
