from __future__ import annotations

from typing import Any, Dict


MISSION_PRIORITY_WEIGHTS = {
    "role_relevance": 0.30,
    "severity": 0.25,
    "repetition": 0.20,
    "prerequisite_impact": 0.15,
    "recency": 0.10,
}


def _score(value: Any) -> float:
    try:
        numeric = float(value)
    except Exception:
        numeric = 0.0
    if 0 < numeric <= 1:
        numeric *= 100
    return max(0.0, min(100.0, numeric))


def calculate_mission_priority(factors: Dict[str, Any]) -> Dict[str, Any]:
    normalized = {
        "role_relevance": _score(factors.get("role_relevance")),
        "severity": _score(factors.get("severity")),
        "repetition": _score(factors.get("repetition", factors.get("frequency"))),
        "prerequisite_impact": _score(
            factors.get("prerequisite_impact", factors.get("dependency_impact"))
        ),
        "recency": _score(factors.get("recency")),
    }
    priority = round(sum(normalized[key] * weight for key, weight in MISSION_PRIORITY_WEIGHTS.items()), 1)
    return {
        "priority_score": priority,
        "factors": normalized,
        "formula": MISSION_PRIORITY_WEIGHTS,
    }
