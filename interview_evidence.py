"""Lightweight deterministic evidence state for one live interview.

The blueprint remains the source of truth for what may be asked.  This module
only materializes the evidence already produced by ``evaluation_engine`` so
the live controller can choose a useful next action without another model
call.  It deliberately stores identifiers, aggregates, and state labels, not
candidate answer text.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, Iterable, List, Mapping, Optional

from interview_profiles import get_profile_config, normalize_profile_type


INTERVIEW_EVIDENCE_STATE_VERSION = "interview-evidence-state-v1"

_IMPORTANCE_RANK = {"critical": 3, "high": 2, "medium": 1, "low": 0}
_WEAK_FLAGS = {
    "empty_answer",
    "too_short",
    "brief_answer",
    "low_lexical_relevance",
    "weak_structure",
    "ownership_unclear",
    "unsupported_or_unspecific",
    "indirect_response",
    "missing_tradeoffs",
    "technical_accuracy_unknown",
    "semantic_analysis_failed",
    "semantic_analysis_invalid",
    "insufficient_evidence",
}
_DEPTH_ACTIONS = {"challenge_tradeoff", "probe_evidence", "simplify_prerequisite"}
_VALID_ACTIONS = {
    "clarify",
    "verify_contradiction",
    "simplify_prerequisite",
    "probe_evidence",
    "challenge_tradeoff",
    "advance",
}
_RECORDED_ACTIONS = _VALID_ACTIONS | {"retry", "deepen", "end"}


def _text(value: Any, limit: int = 240) -> str:
    return " ".join(str(value or "").split()).strip()[:limit]


def _unique(values: Iterable[Any]) -> List[str]:
    result: List[str] = []
    seen: set[str] = set()
    for value in values:
        item = _text(value)
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _number(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _clamp(value: Any, low: float = 0.0, high: float = 1.0) -> Optional[float]:
    number = _number(value)
    if number is None:
        return None
    return max(low, min(high, number))


def _point_contract(section: Mapping[str, Any], section_id: str) -> List[Dict[str, str]]:
    """Normalize blueprint points to the IDs used by live evaluation."""

    raw_points = section.get("expected_points")
    if not isinstance(raw_points, list) or not raw_points:
        raw_points = section.get("expected_point_specs")
    specs = section.get("expected_point_specs")
    specs = specs if isinstance(specs, list) else []
    result: List[Dict[str, str]] = []
    seen: set[str] = set()
    for index, point in enumerate(raw_points if isinstance(raw_points, list) else [], start=1):
        spec = specs[index - 1] if index <= len(specs) and isinstance(specs[index - 1], dict) else {}
        if isinstance(point, dict):
            point_id = _text(
                point.get("point_id")
                or point.get("expected_point_id")
                or point.get("id")
                or point.get("key")
                or spec.get("expected_point_id")
            )
            label = _text(point.get("label") or point.get("text") or point.get("description") or point_id)
        else:
            label = _text(point)
            # ``interview._expected_point_contract`` uses this same stable
            # shape for string-based blueprint points.
            point_id = f"{section_id}:point:{index}"
        if not label:
            continue
        point_id = point_id or f"{section_id}:point:{index}"
        if point_id in seen:
            continue
        seen.add(point_id)
        result.append({"point_id": point_id, "label": label})
    return result


def _new_section_state(section: Mapping[str, Any]) -> Dict[str, Any]:
    section_id = _text(section.get("section_id") or section.get("id") or "general", 120)
    points = _point_contract(section, section_id)
    point_ids = [point["point_id"] for point in points]
    return {
        "section_id": section_id,
        "topic": _text(section.get("label") or section_id, 160),
        "kind": _text(section.get("kind") or "behavioral", 60),
        "importance": _text(section.get("importance") or "medium", 30),
        "expected_points": points,
        "expected_point_ids": point_ids,
        "covered_point_ids": [],
        "explicitly_missed_point_ids": [],
        "missing_point_ids": point_ids,
        "unknown_point_ids": point_ids,
        "incorrect_claims": [],
        "contradictions": [],
        "contradiction_history": [],
        "question_ids": [],
        "sufficiently_covered_question_ids": [],
        "answer_count": 0,
        "confidence": None,
        "best_confidence": None,
        "last_score": None,
        "best_score": None,
        "coverage_known": False,
        "weak": False,
        "incomplete": True,
        "strong": False,
        "sufficiently_covered": False,
        "last_action": None,
        "depth_probe_count": 0,
    }


def _base_state(knowledge_map: Mapping[str, Any]) -> Dict[str, Any]:
    sections: Dict[str, Dict[str, Any]] = {}
    for section in knowledge_map.get("battlegrounds", []) if isinstance(knowledge_map, Mapping) else []:
        if not isinstance(section, dict):
            continue
        state = _new_section_state(section)
        sections[state["section_id"]] = state
    return {
        "version": INTERVIEW_EVIDENCE_STATE_VERSION,
        "evaluated_answer_count": 0,
        "last_updated_turn": 0,
        "sections": sections,
        "asked_question_ids": [],
        "sufficiently_covered_question_ids": [],
        "demonstrated_concepts": [],
        "missing_expected_evidence": [],
        "unknown_expected_evidence": [],
        "contradictions": [],
        "weak_or_incomplete_areas": [],
        "strong_areas": [],
        "sufficiently_covered_topics": [],
        "answer_confidence": {},
        "remaining_required_sections": list(sections),
    }


def _merge_existing_section(section: Dict[str, Any], blueprint_section: Mapping[str, Any]) -> Dict[str, Any]:
    """Keep durable state while adding fields introduced by a newer blueprint."""

    fresh = _new_section_state(blueprint_section)
    merged = {**fresh, **section}
    merged["section_id"] = fresh["section_id"]
    merged["topic"] = fresh["topic"]
    merged["kind"] = fresh["kind"]
    merged["importance"] = fresh["importance"]
    merged["expected_points"] = fresh["expected_points"]
    merged["expected_point_ids"] = fresh["expected_point_ids"]
    for key in (
        "covered_point_ids",
        "explicitly_missed_point_ids",
        "incorrect_claims",
        "contradictions",
        "contradiction_history",
        "question_ids",
        "sufficiently_covered_question_ids",
    ):
        if not isinstance(merged.get(key), list):
            merged[key] = []
    return merged


def ensure_interview_evidence_state(
    existing: Any,
    knowledge_map: Mapping[str, Any],
) -> Dict[str, Any]:
    """Return a bounded state compatible with the current frozen blueprint."""

    state = deepcopy(existing) if isinstance(existing, dict) else _base_state(knowledge_map)
    if state.get("version") != INTERVIEW_EVIDENCE_STATE_VERSION:
        state = _base_state(knowledge_map)
    sections = state.get("sections")
    if not isinstance(sections, dict):
        sections = {}
    blueprint_sections = [
        item for item in knowledge_map.get("battlegrounds", [])
        if isinstance(item, dict)
    ] if isinstance(knowledge_map, Mapping) else []
    for blueprint_section in blueprint_sections:
        section_id = _text(blueprint_section.get("section_id") or blueprint_section.get("id") or "general", 120)
        existing_section = sections.get(section_id)
        sections[section_id] = _merge_existing_section(
            existing_section if isinstance(existing_section, dict) else {},
            blueprint_section,
        )
    state["sections"] = sections
    for key in (
        "asked_question_ids",
        "sufficiently_covered_question_ids",
        "demonstrated_concepts",
        "missing_expected_evidence",
        "unknown_expected_evidence",
        "contradictions",
        "weak_or_incomplete_areas",
        "strong_areas",
        "sufficiently_covered_topics",
    ):
        if not isinstance(state.get(key), list):
            state[key] = []
    if not isinstance(state.get("answer_confidence"), dict):
        state["answer_confidence"] = {}
    if not isinstance(state.get("evaluated_answer_count"), int):
        state["evaluated_answer_count"] = 0
    if not isinstance(state.get("last_updated_turn"), int):
        state["last_updated_turn"] = int(state.get("evaluated_answer_count") or 0)
    _refresh_aggregates(state)
    return state


def _section_for_question(
    state: Dict[str, Any],
    question_spec: Mapping[str, Any],
) -> Dict[str, Any]:
    section_id = _text(question_spec.get("section_id") or question_spec.get("id") or "general", 120)
    sections = state.setdefault("sections", {})
    section = sections.get(section_id)
    if not isinstance(section, dict):
        section = _new_section_state({**question_spec, "section_id": section_id})
        sections[section_id] = section
    return section


def _canonical_point_ids(values: Any, section: Mapping[str, Any]) -> List[str]:
    if not isinstance(values, list):
        return []
    contract = section.get("expected_points") if isinstance(section.get("expected_points"), list) else []
    by_value: Dict[str, str] = {}
    for point in contract:
        if not isinstance(point, dict):
            continue
        point_id = _text(point.get("point_id"))
        label = _text(point.get("label"))
        if point_id:
            by_value[point_id.lower()] = point_id
        if label and point_id:
            by_value[label.lower()] = point_id
    return _unique(
        by_value.get(_text(value).lower(), _text(value))
        for value in values
        if _text(value)
    )


def _refresh_section_status(section: Dict[str, Any], evaluation: Mapping[str, Any]) -> None:
    expected_ids = list(section.get("expected_point_ids") or [])
    covered = set(section.get("covered_point_ids") or [])
    explicit_missed = set(section.get("explicitly_missed_point_ids") or [])
    section["covered_point_ids"] = [item for item in expected_ids if item in covered]
    section["explicitly_missed_point_ids"] = [item for item in expected_ids if item in explicit_missed and item not in covered]
    section["missing_point_ids"] = [item for item in expected_ids if item not in covered]
    section["unknown_point_ids"] = (
        [item for item in expected_ids if item not in covered]
        if not section.get("coverage_known")
        else []
    )

    score = _number(evaluation.get("overall_score"))
    authoritative = bool(evaluation.get("authoritative")) and score is not None
    flags = {str(item) for item in (evaluation.get("flags") or [])}
    contradictions = section.get("contradictions") or []
    weak_signal = bool(flags & _WEAK_FLAGS) or bool(contradictions)
    signals = evaluation.get("signals") if isinstance(evaluation.get("signals"), dict) else {}
    specificity = _number((signals.get("specificity_evidence") or {}).get("score")) or 0.0
    structure = _number((signals.get("structure") or {}).get("score")) or 0.0
    ownership = _number((signals.get("ownership") or {}).get("score"))
    semantic_completed = (evaluation.get("semantic_status") or {}).get("state") == "completed"
    coverage_ratio = len(section["covered_point_ids"]) / len(expected_ids) if expected_ids else 1.0
    strong_quality = authoritative and score is not None and score >= 80 and not weak_signal
    if semantic_completed:
        strong_quality = strong_quality and coverage_ratio >= 0.75 and not section["explicitly_missed_point_ids"]
    else:
        # Deterministic-only evaluations cannot prove point-level coverage, but
        # a high-quality answer is still useful evidence against mechanically
        # repeating the same topic.
        strong_quality = strong_quality and specificity >= 50 and structure >= 45
        if ownership is not None and ownership < 60:
            strong_quality = False

    section["strong"] = bool(strong_quality)
    section["weak"] = bool(
        not authoritative
        or score is None
        or score < 60
        or weak_signal
        or bool(section["explicitly_missed_point_ids"])
    )
    section["incomplete"] = bool(
        section["explicitly_missed_point_ids"]
        or not authoritative
        or score is None
        or score < 70
        or (semantic_completed and bool(section["missing_point_ids"]))
    )
    section["sufficiently_covered"] = bool(
        authoritative
        and score is not None
        and not weak_signal
        and not contradictions
        and (
            (semantic_completed and not section["missing_point_ids"] and score >= 65)
            or (not semantic_completed and strong_quality)
        )
    )


def _refresh_aggregates(state: Dict[str, Any]) -> None:
    sections = state.get("sections") if isinstance(state.get("sections"), dict) else {}
    missing: List[Dict[str, Any]] = []
    unknown: List[Dict[str, Any]] = []
    contradictions: List[Dict[str, Any]] = []
    weak: List[Dict[str, Any]] = []
    strong: List[str] = []
    sufficient: List[str] = []
    demonstrated: List[str] = []
    asked: List[str] = []
    covered_questions: List[str] = []
    confidence: Dict[str, Optional[float]] = {}
    for section_id, section in sections.items():
        if not isinstance(section, dict):
            continue
        topic = _text(section.get("topic") or section_id)
        for point_id in section.get("missing_point_ids") or []:
            label = next(
                (
                    _text(point.get("label"))
                    for point in section.get("expected_points") or []
                    if isinstance(point, dict) and _text(point.get("point_id")) == str(point_id)
                ),
                str(point_id),
            )
            item = {"section_id": section_id, "topic": topic, "point_id": point_id, "label": label}
            if section.get("coverage_known") or point_id in (section.get("explicitly_missed_point_ids") or []):
                missing.append(item)
            else:
                unknown.append(item)
        for item in section.get("contradictions") or []:
            contradictions.append({"section_id": section_id, "topic": topic, "detail": item})
        if section.get("weak") or section.get("incomplete"):
            weak.append({
                "section_id": section_id,
                "topic": topic,
                "reason": "weak_or_incomplete_evidence",
                "missing_point_ids": list(section.get("missing_point_ids") or []),
            })
        if section.get("strong"):
            strong.append(section_id)
        if section.get("sufficiently_covered"):
            sufficient.append(section_id)
            covered_questions.extend(section.get("question_ids") or [])
        confidence[section_id] = _clamp(section.get("confidence"), 0.0, 1.0)
        asked.extend(str(item) for item in section.get("question_ids") or [] if item)
        demonstrated.extend(str(item) for item in section.get("covered_point_ids") or [] if item)

    state["asked_question_ids"] = _unique(asked)
    state["sufficiently_covered_question_ids"] = _unique(covered_questions)
    state["demonstrated_concepts"] = _unique(demonstrated)
    state["missing_expected_evidence"] = missing
    state["unknown_expected_evidence"] = unknown
    state["contradictions"] = contradictions
    state["weak_or_incomplete_areas"] = weak
    state["strong_areas"] = _unique(strong)
    state["sufficiently_covered_topics"] = _unique(sufficient)
    state["answer_confidence"] = confidence
    state["remaining_required_sections"] = [
        section_id for section_id, section in sections.items()
        if isinstance(section, dict) and not section.get("sufficiently_covered")
    ]


def update_interview_evidence_state(
    state: Dict[str, Any],
    question_spec: Mapping[str, Any],
    evaluation: Mapping[str, Any],
    *,
    question_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Apply one already-computed evaluation to the current interview state."""

    if not isinstance(evaluation, Mapping):
        return state
    question_kind = _text(question_spec.get("kind") or question_spec.get("question_type") or "behavioral", 60).lower()
    if question_kind in {"warmup", "introduction"} or _text(question_spec.get("section_id"), 80).lower() == "warmup":
        return state
    section = _section_for_question(state, question_spec)
    question_key = _text(question_id or question_spec.get("question_id"), 100)
    if question_key and question_key not in section["question_ids"]:
        section["question_ids"].append(question_key)
    evidence = evaluation.get("evidence") if isinstance(evaluation.get("evidence"), dict) else {}
    covered = _canonical_point_ids(evidence.get("covered_points"), section)
    missed = _canonical_point_ids(evidence.get("missed_points"), section)
    section["covered_point_ids"] = _unique([*(section.get("covered_point_ids") or []), *covered])
    section["explicitly_missed_point_ids"] = _unique([
        *(section.get("explicitly_missed_point_ids") or []),
        *[item for item in missed if item not in covered],
    ])
    section["incorrect_claims"] = _unique([
        *(section.get("incorrect_claims") or []),
        *(evidence.get("incorrect_claims") or []),
    ])
    current_contradictions = _unique(evidence.get("contradictions") or [])
    section["contradiction_history"] = _unique([
        *(section.get("contradiction_history") or []),
        *current_contradictions,
    ])
    if current_contradictions:
        section["contradictions"] = _unique([
            *(section.get("contradictions") or []),
            *current_contradictions,
        ])
    elif section.get("last_action") == "verify_contradiction":
        # A clean answer immediately after a verification probe resolves the
        # active contradiction while retaining its bounded history for audit.
        section["contradictions"] = []
    semantic_state = (evaluation.get("semantic_status") or {}).get("state")
    section["coverage_known"] = bool(section.get("coverage_known") or semantic_state == "completed")
    section["answer_count"] = int(section.get("answer_count") or 0) + 1
    score = _number(evaluation.get("overall_score"))
    if score is not None:
        section["last_score"] = round(score, 1)
        prior_best = _number(section.get("best_score"))
        section["best_score"] = round(max(score, prior_best if prior_best is not None else score), 1)
    answer_confidence = _clamp(evaluation.get("confidence"), 0.0, 1.0)
    if answer_confidence is not None:
        previous_confidence = _number(section.get("confidence"))
        count_before = max(0, int(section["answer_count"]) - 1)
        section["confidence"] = round(
            ((previous_confidence * count_before) + answer_confidence) / section["answer_count"]
            if previous_confidence is not None and count_before
            else answer_confidence,
            3,
        )
        best_confidence = _number(section.get("best_confidence"))
        section["best_confidence"] = round(max(answer_confidence, best_confidence or 0.0), 3)
    _refresh_section_status(section, evaluation)
    if section.get("sufficiently_covered") and question_key and question_key not in section["sufficiently_covered_question_ids"]:
        section["sufficiently_covered_question_ids"].append(question_key)
    state["evaluated_answer_count"] = int(state.get("evaluated_answer_count") or 0) + 1
    state["last_updated_turn"] = state["evaluated_answer_count"]
    _refresh_aggregates(state)
    return state


def record_adaptive_action(
    state: Dict[str, Any],
    section_id: Any,
    action: str,
) -> Dict[str, Any]:
    section = (state.get("sections") or {}).get(_text(section_id, 120))
    normalized = action if action in _RECORDED_ACTIONS else "advance"
    if isinstance(section, dict):
        section["last_action"] = normalized
        if normalized in _DEPTH_ACTIONS:
            section["depth_probe_count"] = int(section.get("depth_probe_count") or 0) + 1
    _refresh_aggregates(state)
    return state


def _action_for_missing_evidence(
    section: Mapping[str, Any],
    evaluation: Mapping[str, Any],
    profile_type: str,
) -> str:
    evidence = evaluation.get("evidence") if isinstance(evaluation.get("evidence"), dict) else {}
    incorrect = list(evidence.get("incorrect_claims") or [])
    if incorrect or _number((evaluation.get("scores") or {}).get("technical_accuracy")) is not None and float((evaluation.get("scores") or {}).get("technical_accuracy") or 0) < 45:
        return "simplify_prerequisite"
    flags = {str(item) for item in (evaluation.get("flags") or [])}
    signals = evaluation.get("signals") if isinstance(evaluation.get("signals"), dict) else {}
    ownership = _number((signals.get("ownership") or {}).get("score"))
    if profile_type in {"startup", "mid_tier", "custom"} and (ownership is None or ownership < 65 or "ownership_unclear" in flags):
        return "probe_evidence"
    if "missing_tradeoffs" in flags or (signals.get("tradeoffs") or {}).get("applicable") and float((signals.get("tradeoffs") or {}).get("score") or 0) < 45:
        return "challenge_tradeoff"
    return str(get_profile_config(profile_type).get("adaptive_policy", {}).get("missing_evidence_action") or "probe_evidence")


def choose_adaptive_next_action(
    *,
    evaluation: Mapping[str, Any],
    evidence_state: Mapping[str, Any],
    active_section_id: Any,
    profile_type: str,
    followups_used: int,
    maximum_followups: int,
    remaining_seconds: Optional[int] = None,
) -> Dict[str, Any]:
    """Choose a deterministic action using current and prior evidence."""

    normalized_profile = normalize_profile_type(profile_type)
    profile_config = get_profile_config(normalized_profile)
    policy = profile_config.get("adaptive_policy") if isinstance(profile_config.get("adaptive_policy"), dict) else {}
    base_followup = evaluation.get("follow_up") if isinstance(evaluation.get("follow_up"), dict) else {}
    baseline = str(base_followup.get("action") or "advance")
    if baseline not in _VALID_ACTIONS:
        baseline = "advance"
    sections = evidence_state.get("sections") if isinstance(evidence_state.get("sections"), dict) else {}
    section = sections.get(_text(active_section_id, 120))
    section = section if isinstance(section, dict) else {}
    can_follow = int(followups_used or 0) < min(2, max(0, int(maximum_followups or 0)))
    if remaining_seconds is not None and int(remaining_seconds) < 30:
        can_follow = False
    semantic = evaluation.get("semantic_status") if isinstance(evaluation.get("semantic_status"), dict) else {}
    semantic_confidence = _number(semantic.get("semantic_confidence")) or 0.0
    evidence = evaluation.get("evidence") if isinstance(evaluation.get("evidence"), dict) else {}
    contradictions = list(evidence.get("contradictions") or []) or list(section.get("contradictions") or [])
    contradiction_is_actionable = bool(section.get("contradictions")) or semantic_confidence >= 0.40
    if contradictions and contradiction_is_actionable and can_follow:
        return {
            "action": "verify_contradiction",
            "reason": "prior_or_current_contradiction_requires_verification",
            "baseline_action": baseline,
            "evidence_state_used": True,
        }

    if semantic.get("answer_relevant") is False or int((evaluation.get("signals") or {}).get("word_count") or 0) < 8:
        return {
            "action": "clarify" if can_follow else "advance",
            "reason": "answer_requires_direct_clarification" if can_follow else "followup_budget_unavailable",
            "baseline_action": baseline,
            "evidence_state_used": True,
        }

    missing = list(section.get("missing_point_ids") or [])
    explicit_missing = list(section.get("explicitly_missed_point_ids") or [])
    coverage_known = bool(section.get("coverage_known"))
    if (missing and coverage_known) or explicit_missing or section.get("weak") or section.get("incomplete"):
        missing_action = _action_for_missing_evidence(section, evaluation, normalized_profile)
        if can_follow:
            return {
                "action": missing_action,
                "reason": "remaining_expected_evidence_requires_targeted_followup",
                "baseline_action": baseline,
                "missing_point_ids": missing,
                "evidence_state_used": True,
            }
        return {
            "action": "advance",
            "reason": "followup_budget_unavailable_with_remaining_coverage_gap",
            "baseline_action": baseline,
            "missing_point_ids": missing,
            "evidence_state_used": True,
        }

    if section.get("sufficiently_covered"):
        strong_action = str(policy.get("strong_answer_action") or "advance")
        allow_depth = bool(policy.get("allow_strong_depth_probe"))
        depth_count = int(section.get("depth_probe_count") or 0)
        if can_follow and allow_depth and strong_action in _VALID_ACTIONS and depth_count < 1:
            return {
                "action": strong_action,
                "reason": "profile_justifies_one_deeper_probe_after_strong_evidence",
                "baseline_action": baseline,
                "evidence_state_used": True,
            }
        return {
            "action": "advance",
            "reason": "topic_already_sufficiently_covered",
            "baseline_action": baseline,
            "evidence_state_used": True,
        }

    # Do not repeat an evidence dimension that is already strong merely
    # because the single-answer evaluator suggested it. If another expected
    # point remains, the branch above has selected the more useful action.
    if baseline == "probe_evidence" and section.get("strong"):
        return {
            "action": "advance",
            "reason": "evidence_dimension_already_demonstrated",
            "baseline_action": baseline,
            "evidence_state_used": True,
        }
    if baseline == "challenge_tradeoff" and "challenge_tradeoff" == section.get("last_action") and not can_follow:
        return {
            "action": "advance",
            "reason": "tradeoff_probe_already_used",
            "baseline_action": baseline,
            "evidence_state_used": True,
        }
    return {
        "action": baseline if can_follow or baseline == "advance" else "advance",
        "reason": str(base_followup.get("reason") or "evidence_state_requires_no_override"),
        "baseline_action": baseline,
        "evidence_state_used": True,
    }


def select_next_battleground(
    knowledge_map: Mapping[str, Any],
    evidence_state: Mapping[str, Any],
    *,
    current_section_id: Any = None,
    profile_type: str = "mid_tier",
    remaining_seconds: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """Select the next blueprint section by evidence gap and policy priority."""

    if remaining_seconds is not None and int(remaining_seconds) < 30:
        return None
    sections = evidence_state.get("sections") if isinstance(evidence_state.get("sections"), dict) else {}
    normalized_profile = normalize_profile_type(profile_type)
    progression = str(
        (get_profile_config(normalized_profile).get("adaptive_policy") or {}).get("progression")
        or "balanced_coverage"
    )
    candidates: List[tuple[tuple[Any, ...], Dict[str, Any]]]
    candidates = []
    for index, battleground in enumerate(knowledge_map.get("battlegrounds", []) if isinstance(knowledge_map, Mapping) else []):
        if not isinstance(battleground, dict):
            continue
        try:
            current_turns = int(battleground.get("current_turns") or 0)
            max_turns = int(battleground.get("max_turns") or 0)
        except (TypeError, ValueError):
            continue
        if current_turns >= max_turns:
            continue
        section_id = _text(battleground.get("section_id") or battleground.get("id") or "general", 120)
        state = sections.get(section_id) if isinstance(sections.get(section_id), dict) else {}
        if state.get("sufficiently_covered"):
            continue
        answer_count = int(state.get("answer_count") or 0)
        missing_count = len(state.get("missing_point_ids") or []) if state.get("coverage_known") else 0
        importance = _IMPORTANCE_RANK.get(_text(battleground.get("importance") or "medium").lower(), 1)
        prior_weakness = 1 if battleground.get("prior_weakness") else 0
        current_penalty = 1 if str(section_id) == str(current_section_id or "") else 0
        jd_priority = (
            1
            if normalized_profile == "custom"
            and "job-description" in str(battleground.get("selection_reason") or "").lower()
            else 0
        )
        time_budget = int(battleground.get("time_budget_seconds") or 0)
        time_fit = 0 if remaining_seconds is None or time_budget <= int(remaining_seconds) else 1
        # Unattempted and high-importance sections win; known coverage gaps
        # outrank an ungrounded revisit. Blueprint order resolves ties.
        if progression == "depth_first":
            progression_key = 0 if missing_count else 1
        elif progression == "job_aligned_coverage":
            progression_key = 0 if jd_priority else 1
        elif progression == "speed_first":
            progression_key = 0 if answer_count == 0 else 1
        else:
            progression_key = 0
        key = (
            progression_key,
            0 if answer_count == 0 else 1,
            -importance,
            -missing_count,
            -jd_priority,
            -prior_weakness,
            time_fit,
            current_penalty,
            index,
        )
        candidates.append((key, battleground))
    if not candidates:
        return None
    if remaining_seconds is not None:
        fitting = [
            item for item in candidates
            if int(item[1].get("time_budget_seconds") or 0) <= int(remaining_seconds)
        ]
        if fitting:
            candidates = fitting
    candidates.sort(key=lambda item: item[0])
    return candidates[0][1]


__all__ = [
    "INTERVIEW_EVIDENCE_STATE_VERSION",
    "choose_adaptive_next_action",
    "ensure_interview_evidence_state",
    "record_adaptive_action",
    "select_next_battleground",
    "update_interview_evidence_state",
]
