"""Deterministic, evidence-backed weakness lifecycle derivation and persistence."""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from database import get_db_connection, return_db_connection


TAXONOMY_VERSION = "taxonomy-v1"
RUBRIC_VERSION = "evidence-rubric-v2"


def _number(value: Any) -> Optional[float]:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _confidence_number(value: Any) -> float:
    if isinstance(value, str):
        return {"low": 0.35, "medium": 0.7, "high": 0.9}.get(value.lower(), 0.0)
    numeric = _number(value)
    if numeric is None:
        return 0.0
    return max(0.0, min(1.0, numeric / 100.0 if numeric > 1 else numeric))


def _sort_key(observation: Dict[str, Any]) -> tuple[str, str]:
    return (str(observation.get("observed_at") or ""), str(observation.get("source_key") or ""))


def derive_weakness_lifecycle(observations: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """Apply the product's exact lifecycle thresholds to comparable evidence."""
    comparable = [
        {**item, "score": _number(item.get("score")), "confidence": _confidence_number(item.get("confidence"))}
        for item in observations
        if _number(item.get("score")) is not None
    ]
    comparable.sort(key=_sort_key)
    if not comparable:
        return {
            "lifecycle_state": "new",
            "observation_count": 0,
            "session_count": 0,
            "baseline_score": None,
            "latest_score": None,
            "confidence": 0.0,
            "resolved_at": None,
        }

    negatives = [item for item in comparable if float(item["score"]) < 75]
    sessions = {str(item.get("interview_id") or item.get("analysis_id") or item.get("source_key")) for item in comparable}
    baseline = float(comparable[0]["score"])
    latest = float(comparable[-1]["score"])
    average_confidence = sum(float(item["confidence"]) for item in comparable) / len(comparable)
    independent_passes = [
        item
        for item in comparable
        if float(item["score"]) >= 75 and float(item["confidence"]) >= 0.60
    ]
    independent_sources = {str(item.get("source_key") or item.get("analysis_id")) for item in independent_passes}
    first_negative_analysis = next(
        (str(item.get("analysis_id")) for item in comparable if float(item["score"]) < 75),
        None,
    )
    has_external_validation = any(
        item.get("evidence_type") in {"held_out_variation", "held_out_checkpoint", "later_interview"}
        or (first_negative_analysis and str(item.get("analysis_id")) != first_negative_analysis)
        for item in independent_passes
    )

    resolved = len(independent_sources) >= 2 and has_external_validation
    latest_two_average = (
        sum(float(item["score"]) for item in comparable[-2:]) / 2.0
        if len(comparable) >= 2
        else latest
    )
    if resolved:
        lifecycle = "resolved"
    elif len(comparable) >= 3 and latest_two_average >= baseline + 10:
        lifecycle = "improving"
    elif len(comparable) >= 3 and latest_two_average <= baseline - 10:
        lifecycle = "worsening"
    elif len(negatives) >= 3 and len(sessions) >= 2 and average_confidence >= 0.60:
        lifecycle = "repeated"
    elif len(negatives) >= 2:
        lifecycle = "occasional"
    else:
        lifecycle = "new"

    return {
        "lifecycle_state": lifecycle,
        "observation_count": len(comparable),
        "negative_observation_count": len(negatives),
        "session_count": len(sessions),
        "baseline_score": round(baseline, 2),
        "latest_score": round(latest, 2),
        "latest_two_average": round(latest_two_average, 2),
        "confidence": round(average_confidence, 3),
        "resolved_at": datetime.now(timezone.utc) if resolved else None,
    }


def infer_root_cause(observations: Iterable[Dict[str, Any]]) -> Dict[str, str]:
    items = list(observations)
    patterns = {
        "answer-planning": {"rambling", "late-direct-answer", "missing-structure", "weak-structure", "too-long", "indirect-response"},
        "evidence-recall": {"no-evidence", "missing-metric", "unsupported-claim", "unsupported-or-unspecific", "missing-ownership", "ownership-unclear"},
        "state-definition": {"recurrence", "dynamic-programming", "state-transition", "boundary-condition"},
        "architecture-mental-model": {"data-flow", "architecture", "component-boundary", "project-depth"},
        "debugging-discipline": {"execution_failure", "hidden-test-failure", "test-case-failure", "syntax-or-structure"},
    }
    best_label, best_sources = "possible-unspecified-cause", set()
    for label, tokens in patterns.items():
        sources = {
            str(item.get("question_spec_id") or item.get("round_id") or item.get("source_key"))
            for item in items
            if tokens.intersection({str(flag).lower().replace("_", "-") for flag in item.get("flags", [])})
        }
        if len(sources) > len(best_sources):
            best_label, best_sources = label, sources

    executable_failure = any(item.get("source_kind") == "technical_execution" and float(_number(item.get("score")) or 0) < 75 for item in items)
    explanation_gap = any(
        flag in {"missing-explanation", "missing-complexity", "missing-tradeoff", "no-evidence"}
        for item in items
        for flag in {str(value).lower().replace("_", "-") for value in item.get("flags", [])}
    )
    supported = len(best_sources) >= 2 or (executable_failure and explanation_gap)
    return {
        "hypothesis": best_label if supported else f"possible {best_label.replace('-', ' ')}",
        "confidence": "medium" if supported else "low",
    }


def _safe_skill_key(value: Any) -> str:
    text = re.sub(r"[^a-z0-9:+#._-]+", "-", str(value or "general").lower()).strip("-")
    return (text or "general")[:160]


def _persist_sync(
    user_id: str,
    analysis_id: str,
    interview_id: str,
    observations: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    updated: List[Dict[str, Any]] = []
    try:
        grouped: Dict[str, List[Dict[str, Any]]] = {}
        for observation in observations:
            score = _number(observation.get("score"))
            if score is None:
                continue
            skill_key = _safe_skill_key(observation.get("skill_key"))
            grouped.setdefault(skill_key, []).append({**observation, "score": score})

        for skill_key, current in grouped.items():
            cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"weakness:{user_id}:{skill_key}",))
            cursor.execute(
                """
                SELECT weakness_state_id
                FROM WeaknessStates
                WHERE user_id = %s AND skill_key = %s
                  AND taxonomy_version = %s AND rubric_version = %s
                FOR UPDATE
                """,
                (user_id, skill_key, TAXONOMY_VERSION, RUBRIC_VERSION),
            )
            existing = cursor.fetchone()
            if not existing and not any(float(item["score"]) < 75 for item in current):
                continue
            state_id = existing[0] if existing else str(uuid.uuid4())
            if not existing:
                cursor.execute(
                    """
                    INSERT INTO WeaknessStates (
                        weakness_state_id, user_id, skill_key, taxonomy_version,
                        rubric_version, lifecycle_state, observation_count,
                        session_count, confidence, evidence_summary
                    ) VALUES (%s, %s, %s, %s, %s, 'new', 0, 0, 0, '{}'::jsonb)
                    """,
                    (state_id, user_id, skill_key, TAXONOMY_VERSION, RUBRIC_VERSION),
                )

            for item in current:
                source_key = str(item.get("source_key") or item.get("response_id") or item.get("round_id") or analysis_id)
                link_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{state_id}:{analysis_id}:{source_key}"))
                evidence = {
                    **item,
                    "analysis_id": analysis_id,
                    "interview_id": interview_id,
                    "source_key": source_key,
                }
                cursor.execute(
                    """
                    INSERT INTO WeaknessEvidenceLinks (
                        link_id, weakness_state_id, analysis_id, response_id,
                        round_id, score, confidence, evidence_json
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (link_id) DO NOTHING
                    """,
                    (
                        link_id, state_id, analysis_id, item.get("response_id"),
                        item.get("round_id"), item["score"],
                        _confidence_number(item.get("confidence")), json.dumps(evidence, default=str),
                    ),
                )

            cursor.execute(
                """
                SELECT wel.analysis_id, wel.response_id, wel.round_id, wel.score,
                       wel.confidence, wel.evidence_json, wel.created_at,
                       spa.interview_id
                FROM WeaknessEvidenceLinks wel
                JOIN SessionPerformanceAnalyses spa ON spa.analysis_id = wel.analysis_id
                WHERE wel.weakness_state_id = %s
                ORDER BY wel.created_at, wel.link_id
                """,
                (state_id,),
            )
            history = []
            for row in cursor.fetchall():
                evidence = row[5] if isinstance(row[5], dict) else json.loads(row[5] or "{}")
                history.append({
                    **evidence,
                    "analysis_id": row[0], "response_id": row[1], "round_id": row[2],
                    "score": float(row[3]) if row[3] is not None else None,
                    "confidence": float(row[4] or 0), "observed_at": row[6],
                    "interview_id": row[7],
                    "source_key": evidence.get("source_key") or row[1] or row[2] or row[0],
                })
            lifecycle = derive_weakness_lifecycle(history)
            root_cause = infer_root_cause(history)
            summary = {
                "negative_observations": lifecycle.get("negative_observation_count", 0),
                "latest_two_average": lifecycle.get("latest_two_average"),
                "supporting_analysis_ids": list(dict.fromkeys(str(item["analysis_id"]) for item in history))[-5:],
            }
            cursor.execute(
                """
                UPDATE WeaknessStates
                SET lifecycle_state = %s, observation_count = %s, session_count = %s,
                    baseline_score = %s, latest_score = %s, confidence = %s,
                    root_cause_hypothesis = %s, root_cause_confidence = %s,
                    evidence_summary = %s,
                    first_observed_at = COALESCE(
                        (SELECT MIN(created_at) FROM WeaknessEvidenceLinks WHERE weakness_state_id = %s),
                        first_observed_at
                    ),
                    last_observed_at = COALESCE(
                        (SELECT MAX(created_at) FROM WeaknessEvidenceLinks WHERE weakness_state_id = %s),
                        last_observed_at
                    ),
                    resolved_at = %s, updated_at = NOW()
                WHERE weakness_state_id = %s
                """,
                (
                    lifecycle["lifecycle_state"], lifecycle["observation_count"],
                    lifecycle["session_count"], lifecycle["baseline_score"],
                    lifecycle["latest_score"], lifecycle["confidence"],
                    root_cause["hypothesis"], root_cause["confidence"],
                    json.dumps(summary), state_id, state_id, lifecycle["resolved_at"], state_id,
                ),
            )
            updated.append({"weakness_state_id": state_id, "skill_key": skill_key, **lifecycle, **root_cause})
        conn.commit()
        return updated
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()
        return_db_connection(conn)


async def persist_weakness_states(
    user_id: str,
    analysis_id: str,
    interview_id: str,
    observations: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    return await asyncio.to_thread(_persist_sync, user_id, analysis_id, interview_id, observations)
