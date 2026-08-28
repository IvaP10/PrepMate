import os

os.environ.setdefault("ENVIRONMENT", "test")

from mission_priority import MISSION_PRIORITY_WEIGHTS, calculate_mission_priority
from weakness_engine import _observation_summary, derive_weakness_lifecycle, infer_root_cause


def _observation(
    score,
    *,
    source,
    interview="interview-1",
    confidence=0.75,
    evidence_type="interview",
    flags=None,
):
    return {
        "score": score,
        "confidence": confidence,
        "source_key": source,
        "interview_id": interview,
        "analysis_id": interview.replace("interview", "analysis"),
        "evidence_type": evidence_type,
        "flags": flags or [],
        "observed_at": source,
    }


def test_weakness_lifecycle_new_occasional_and_repeated_thresholds():
    first = [_observation(52, source="1")]
    second = [*first, _observation(58, source="2")]
    repeated = [*second, _observation(55, source="3", interview="interview-2")]

    assert derive_weakness_lifecycle(first)["lifecycle_state"] == "new"
    assert derive_weakness_lifecycle(second)["lifecycle_state"] == "occasional"
    assert derive_weakness_lifecycle(repeated)["lifecycle_state"] == "repeated"


def test_weakness_lifecycle_improving_worsening_and_resolved_require_real_proof():
    improving = [
        _observation(45, source="1"),
        _observation(61, source="2", interview="interview-2"),
        _observation(66, source="3", interview="interview-3"),
    ]
    worsening = [
        _observation(80, source="1"),
        _observation(62, source="2", interview="interview-2"),
        _observation(58, source="3", interview="interview-3"),
    ]
    unresolved_passes = [
        _observation(50, source="1"),
        _observation(78, source="2", confidence=0.8),
        _observation(82, source="3", confidence=0.9),
    ]
    resolved = [
        _observation(50, source="1"),
        _observation(78, source="2", confidence=0.8, evidence_type="held_out_variation"),
        _observation(82, source="3", confidence=0.9, evidence_type="later_interview", interview="interview-2"),
    ]

    assert derive_weakness_lifecycle(improving)["lifecycle_state"] == "improving"
    assert derive_weakness_lifecycle(worsening)["lifecycle_state"] == "worsening"
    assert derive_weakness_lifecycle(unresolved_passes)["lifecycle_state"] != "resolved"
    assert derive_weakness_lifecycle(resolved)["lifecycle_state"] == "resolved"


def test_root_cause_stays_possible_until_two_independent_supports_exist():
    one = [_observation(45, source="q1", flags=["weak_structure"])]
    two = [
        *one,
        _observation(50, source="q2", interview="interview-2", flags=["indirect_response"]),
    ]

    assert infer_root_cause(one)["confidence"] == "low"
    assert infer_root_cause(one)["hypothesis"].startswith("possible")
    assert infer_root_cause(two) == {
        "hypothesis": "answer-planning",
        "confidence": "medium",
    }


def test_report_backed_observation_summary_names_the_answer_problem():
    summary = _observation_summary({
        "question": "Tell me about a backend decision you owned.",
        "score": 42,
        "flags": ["weak_structure", "unsupported_or_unspecific"],
    }, "behavioral:ownership")

    assert "Tell me about a backend decision you owned" in summary
    assert "direct, well-structured response" in summary
    assert "concrete action, result, or example" in summary


def test_mission_priority_uses_the_plan_weights_exactly():
    assert MISSION_PRIORITY_WEIGHTS == {
        "role_relevance": 0.30,
        "severity": 0.25,
        "repetition": 0.20,
        "prerequisite_impact": 0.15,
        "recency": 0.10,
    }
    result = calculate_mission_priority({
        "role_relevance": 100,
        "severity": 80,
        "repetition": 60,
        "prerequisite_impact": 40,
        "recency": 20,
    })
    assert result["priority_score"] == 70.0
