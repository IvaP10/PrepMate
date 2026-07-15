import os
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

os.environ.setdefault("ENVIRONMENT", "test")

from workspace_api import ExerciseAttemptCreate, ExerciseAttemptSessionUpdate, _attempt_session_response
from improve_scoring import mastery_status_for_checkpoint
from learning_engine import (
    _deterministic_activity_result,
    _decrypt_sensitive_json,
    _encrypted_json_bytes,
    _phase_one_activity_definitions,
    _public_checkpoint_material,
    _reassessment_is_compatible,
    _sanitize_mission_attempt_payload,
)


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
    compare, arrange, rewrite, spoken, checkpoint = activities[1:]
    answer = (
        "I would use a database index because the API needs predictable lookups. "
        "A B-tree narrows the search, and my project test showed lower latency, "
        "with the trade-off of slower writes and extra storage."
    )

    results = [
        _score(
            compare,
            {
                "selected_option": "b",
                "reason": "It answers directly, uses a clear structure, and gives a concrete example.",
            },
            "It answers directly, uses a clear structure, and gives a concrete example.",
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
