from interview_evidence import (
    choose_adaptive_next_action,
    ensure_interview_evidence_state,
    record_adaptive_action,
    select_next_battleground,
    update_interview_evidence_state,
)


def _section(section_id="s1", *, points=None, importance="high", current_turns=0, max_turns=2, selection_reason="resume anchor"):
    points = points or ["Explains the decision"]
    return {
        "section_id": section_id,
        "label": f"Topic {section_id}",
        "kind": "behavioral",
        "importance": importance,
        "opening_question": f"Tell me about {section_id}?",
        "taxonomy_keys": [f"behavioral:{section_id}"],
        "expected_points": points,
        "rubric": {"weights": {"relevance": 1.0}},
        "selection_reason": selection_reason,
        "min_turns": 1,
        "max_turns": max_turns,
        "max_followups": min(2, max_turns - 1),
        "current_turns": current_turns,
        "time_budget_seconds": 120,
    }


def _evaluation(*, covered=None, missed=None, score=86, contradictions=None, semantic_state="completed"):
    return {
        "overall_score": score,
        "authoritative": score is not None,
        "confidence": 0.88,
        "flags": [],
        "signals": {
            "word_count": 42,
            "specificity_evidence": {"score": 82},
            "structure": {"score": 78},
            "ownership": {"applicable": True, "score": 80},
        },
        "scores": {"technical_accuracy": None},
        "semantic_status": {
            "state": semantic_state,
            "semantic_confidence": 0.90,
            "answer_relevant": True,
        },
        "evidence": {
            "covered_points": covered or [],
            "missed_points": missed or [],
            "incorrect_claims": [],
            "contradictions": contradictions or [],
        },
        "follow_up": {"action": "advance", "reason": "baseline"},
    }


def test_state_tracks_coverage_confidence_and_remaining_evidence():
    blueprint = {"battlegrounds": [_section(points=["Decision", "Measured result"])]}
    state = ensure_interview_evidence_state(None, blueprint)

    update_interview_evidence_state(
        state,
        blueprint["battlegrounds"][0],
        _evaluation(covered=["s1:point:1"], missed=["s1:point:2"], score=64),
        question_id="question-1",
    )

    section = state["sections"]["s1"]
    assert section["covered_point_ids"] == ["s1:point:1"]
    assert section["missing_point_ids"] == ["s1:point:2"]
    assert section["confidence"] == 0.88
    assert state["evaluated_answer_count"] == 1
    assert state["weak_or_incomplete_areas"][0]["section_id"] == "s1"


def test_profile_policy_controls_strong_answer_depth():
    blueprint = {"battlegrounds": [_section()]}
    state = ensure_interview_evidence_state(None, blueprint)
    update_interview_evidence_state(
        state,
        blueprint["battlegrounds"][0],
        _evaluation(covered=["s1:point:1"]),
        question_id="question-1",
    )

    top_tier = choose_adaptive_next_action(
        evaluation=_evaluation(covered=["s1:point:1"]),
        evidence_state=state,
        active_section_id="s1",
        profile_type="top_tier",
        followups_used=0,
        maximum_followups=2,
        remaining_seconds=300,
    )
    mid_tier = choose_adaptive_next_action(
        evaluation=_evaluation(covered=["s1:point:1"]),
        evidence_state=state,
        active_section_id="s1",
        profile_type="mid_tier",
        followups_used=0,
        maximum_followups=2,
        remaining_seconds=300,
    )

    assert top_tier["action"] == "challenge_tradeoff"
    assert mid_tier["action"] == "advance"


def test_missing_evidence_and_contradictions_choose_targeted_actions():
    blueprint = {"battlegrounds": [_section(points=["Decision", "Measured result"])]}
    state = ensure_interview_evidence_state(None, blueprint)
    first = _evaluation(covered=["s1:point:1"], missed=["s1:point:2"], score=64)
    update_interview_evidence_state(state, blueprint["battlegrounds"][0], first, question_id="question-1")

    missing = choose_adaptive_next_action(
        evaluation=first,
        evidence_state=state,
        active_section_id="s1",
        profile_type="mid_tier",
        followups_used=0,
        maximum_followups=2,
        remaining_seconds=300,
    )
    assert missing["action"] == "probe_evidence"
    assert missing["missing_point_ids"] == ["s1:point:2"]

    contradiction = _evaluation(
        covered=["s1:point:1"],
        missed=["s1:point:2"],
        score=64,
        contradictions=["ownership claim conflicts with the earlier answer"],
    )
    update_interview_evidence_state(state, blueprint["battlegrounds"][0], contradiction, question_id="question-2")
    decision = choose_adaptive_next_action(
        evaluation=contradiction,
        evidence_state=state,
        active_section_id="s1",
        profile_type="mid_tier",
        followups_used=0,
        maximum_followups=2,
        remaining_seconds=300,
    )
    assert decision["action"] == "verify_contradiction"

    record_adaptive_action(state, "s1", "verify_contradiction")
    resolved = _evaluation(covered=["s1:point:1", "s1:point:2"], score=86)
    update_interview_evidence_state(state, blueprint["battlegrounds"][0], resolved, question_id="question-3")
    assert state["sections"]["s1"]["contradictions"] == []
    assert state["sections"]["s1"]["contradiction_history"]


def test_next_section_skips_sufficiently_covered_topic():
    first = _section("s1", current_turns=1)
    second = _section("s2", importance="critical")
    blueprint = {"battlegrounds": [first, second]}
    state = ensure_interview_evidence_state(None, blueprint)
    update_interview_evidence_state(state, first, _evaluation(covered=["s1:point:1"]), question_id="q1")

    selected = select_next_battleground(
        blueprint,
        state,
        current_section_id="s1",
        profile_type="custom",
        remaining_seconds=300,
    )

    assert selected["section_id"] == "s2"
