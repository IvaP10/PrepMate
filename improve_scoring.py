from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple


PASS_SCORE = 75.0
PARTIAL_PASS_SCORE = 55.0
STRONG_PASS_SCORE = 90.0


def clamp_score(value: Any, low: float = 0.0, high: float = 100.0) -> float:
    try:
        numeric = float(value)
    except Exception:
        numeric = 0.0
    if 0 < numeric <= 1:
        numeric *= 100
    return round(max(low, min(high, numeric)), 1)


def result_status_for_score(score: float) -> str:
    score = clamp_score(score)
    if score >= STRONG_PASS_SCORE:
        return "strong_pass"
    if score >= PASS_SCORE:
        return "passed"
    if score >= PARTIAL_PASS_SCORE:
        return "partial_pass"
    return "failed"


def mastery_status_for_checkpoint(
    *,
    checkpoint_score: Optional[float],
    guided_passes: int,
    variation_passes: int,
    current_status: str = "untrained",
) -> str:
    if checkpoint_score is not None:
        # Passing the held-out exercise proves transfer inside the practice
        # pathway only.  A weakness is verified/resolved later, after a
        # comparable interview supplies independent evidence.
        return "held_out_passed" if checkpoint_score >= PASS_SCORE and guided_passes >= 2 and variation_passes >= 1 else "needs_reinforcement"
    if guided_passes >= 2 and variation_passes >= 1:
        return "ready_for_checkpoint"
    if guided_passes or variation_passes or current_status in {"practising", "needs_reinforcement"}:
        return "practising"
    return "untrained"


def normalize_conditions(
    expected_conditions: Iterable[Any],
    provided_results: Optional[Iterable[Any]] = None,
) -> List[Dict[str, Any]]:
    expected: List[Dict[str, Any]] = []
    for index, item in enumerate(expected_conditions or []):
        if isinstance(item, dict):
            condition_id = str(item.get("id") or item.get("key") or f"condition_{index + 1}")
            label = str(item.get("label") or item.get("text") or item.get("condition") or condition_id.replace("_", " "))
            weight = float(item.get("weight") or 1)
        else:
            condition_id = f"condition_{index + 1}"
            label = str(item)
            weight = 1.0
        expected.append({"id": condition_id, "label": label, "weight": max(weight, 0.1), "met": False})

    provided_by_id: Dict[str, Dict[str, Any]] = {}
    for index, item in enumerate(provided_results or []):
        if not isinstance(item, dict):
            continue
        condition_id = str(item.get("id") or item.get("key") or f"condition_{index + 1}")
        provided_by_id[condition_id] = item

    normalized: List[Dict[str, Any]] = []
    for condition in expected:
        provided = provided_by_id.get(condition["id"], {})
        met = bool(provided.get("met") if "met" in provided else provided.get("passed", False))
        normalized.append({
            **condition,
            "met": met,
            "evidence": str(provided.get("evidence") or ""),
        })
    return normalized


def calculate_activity_score(
    expected_conditions: Iterable[Any],
    provided_results: Optional[Iterable[Any]] = None,
    *,
    penalty_points: float = 0.0,
    bonus_points: float = 0.0,
) -> Dict[str, Any]:
    conditions = normalize_conditions(expected_conditions, provided_results)
    total_weight = sum(float(item["weight"]) for item in conditions) or 1.0
    met_weight = sum(float(item["weight"]) for item in conditions if item["met"])
    raw_score = (met_weight / total_weight) * 100
    score = clamp_score(raw_score - float(penalty_points or 0) + float(bonus_points or 0))
    return {
        "score": score,
        "result_status": result_status_for_score(score),
        "condition_results": conditions,
        "passed_conditions": [item["label"] for item in conditions if item["met"]],
        "failed_conditions": [item["label"] for item in conditions if not item["met"]],
        "score_components": {
            "condition_score": round(raw_score, 1),
            "penalty_points": float(penalty_points or 0),
            "bonus_points": float(bonus_points or 0),
        },
    }


def average(values: Iterable[Any]) -> Optional[float]:
    clean = [clamp_score(value) for value in values if value is not None]
    if not clean:
        return None
    return round(sum(clean) / len(clean), 1)


def calculate_skill_score(
    *,
    baseline_score: float,
    guided_scores: Iterable[Any],
    variation_scores: Iterable[Any],
    checkpoint_score: Optional[float],
) -> float:
    baseline = clamp_score(baseline_score)
    guided_avg = average(guided_scores)
    variation_avg = average(variation_scores)
    checkpoint = clamp_score(checkpoint_score) if checkpoint_score is not None else None

    if checkpoint is None:
        weighted = (baseline * 0.35)
        remaining_weight = 0.65
        if guided_avg is not None and variation_avg is not None:
            weighted += guided_avg * 0.42 + variation_avg * 0.23
        elif guided_avg is not None:
            weighted += guided_avg * remaining_weight
        elif variation_avg is not None:
            weighted += variation_avg * remaining_weight
        else:
            weighted += baseline * remaining_weight
        return clamp_score(weighted)

    guided_value = guided_avg if guided_avg is not None else baseline
    variation_value = variation_avg if variation_avg is not None else baseline
    return clamp_score((baseline * 0.35) + (guided_value * 0.30) + (variation_value * 0.15) + (checkpoint * 0.20))


def calculate_readiness(skills: Iterable[Dict[str, Any]]) -> float:
    weighted_total = 0.0
    weight_total = 0.0
    for skill in skills or []:
        weight = float(skill.get("role_weight") or 1)
        score = clamp_score(skill.get("latest_score", skill.get("baseline_score", 0)))
        weighted_total += score * max(weight, 0.1)
        weight_total += max(weight, 0.1)
    return clamp_score(weighted_total / weight_total) if weight_total else 0.0


def calculate_mission_progress(nodes: Iterable[Dict[str, Any]], skills: Iterable[Dict[str, Any]]) -> float:
    node_list = list(nodes or [])
    skill_list = list(skills or [])
    required_nodes = [node for node in node_list if not node.get("optional")]
    passed_nodes = [
        node for node in required_nodes
        if node.get("result_status") in {"passed", "strong_pass"} or node.get("mastery_status") == "verified"
    ]
    held_out_bonus = sum(0.5 for skill in skill_list if skill.get("mastery_status") == "held_out_passed")
    recovery_credit = sum(
        0.25 for node in required_nodes
        if node.get("recovery_of_node_id") and node.get("result_status") in {"passed", "strong_pass"}
    )
    total_units = max(len(required_nodes) + len(skill_list) * 0.5, 1)
    return clamp_score(((len(passed_nodes) + held_out_bonus + recovery_credit) / total_units) * 100)


def compare_interview_scores(current: Dict[str, Any], previous: Dict[str, Any]) -> Dict[str, Any]:
    compatible = (
        current.get("skill_key")
        and current.get("skill_key") == previous.get("skill_key")
        and current.get("rubric_version")
        and current.get("rubric_version") == previous.get("rubric_version")
        and str(current.get("scoring_scale") or "0-100") == str(previous.get("scoring_scale") or "0-100")
    )
    if not compatible:
        return {"comparable": False, "reason": "Skill, rubric, or scoring scale differs."}
    current_score = clamp_score(current.get("score"))
    previous_score = clamp_score(previous.get("score"))
    return {
        "comparable": True,
        "before": previous_score,
        "after": current_score,
        "delta": round(current_score - previous_score, 1),
    }
