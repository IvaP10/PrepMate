# ============================================================================
# MODULE: report_generator.py
# PURPOSE: Build the final report_json from a list of interview turns —
#          per-skill scores, score band, strengths/weaknesses, summary copy.
# STRUCTURE:
#   - SKILL_KEYS canonical list (lines 21-27)
#   - _avg / _score_band helpers (lines 30-42)
#   - build_report_v2(turns, persona, ...) entry point (later in file)
# ENDPOINTS: none
# DEPENDS ON: stdlib only
# CONSUMED BY: interview.py
# DATA TABLES: none (interview.py persists the returned dict to Interviews.report_json)
# ============================================================================

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List
import re


SKILL_KEYS = [
    ("technical_accuracy", "Technical depth"),
    ("communication", "Communication"),
    ("problem_solving", "Problem solving"),
    ("confidence", "Confidence"),
    ("relevance", "Relevance"),
]


def _avg(values: List[float]) -> float:
    clean = [float(v) for v in values if v is not None]
    return round(sum(clean) / len(clean), 1) if clean else 0.0


def _nullable_avg(values: List[Any]) -> float | None:
    clean = [float(value) for value in values if isinstance(value, (int, float))]
    return round(sum(clean) / len(clean), 1) if clean else None


def _weighted_available(weighted_values: List[tuple[Any, float]]) -> float | None:
    available = [(float(value), weight) for value, weight in weighted_values if isinstance(value, (int, float))]
    total_weight = sum(weight for _, weight in available)
    if not available or total_weight <= 0:
        return None
    return round(sum(value * weight for value, weight in available) / total_weight, 1)


def _score_band(score: float) -> str:
    if score >= 85:
        return "Strong"
    if score >= 70:
        return "Ready with refinement"
    if score >= 55:
        return "Developing"
    return "Needs focused practice"


def _clip(score: float, low: float = 0, high: float = 100) -> float:
    return round(max(low, min(high, score)), 1)


def _dimension_average(turns: List[Dict[str, Any]], key: str) -> float | None:
    return _nullable_avg([
        (turn.get("rubric_scores") or {}).get(key)
        for turn in turns
        if not turn.get("insufficient_evidence")
    ])


def _confidence_label(turns: List[Dict[str, Any]], *stage_outputs: Dict[str, Any]) -> str:
    if not turns:
        return "low"
    low_turns = sum(1 for turn in turns if turn.get("confidence") == "low" or turn.get("insufficient_evidence"))
    low_stages = sum(1 for output in stage_outputs if output.get("confidence") == "low" or output.get("insufficient_evidence"))
    if low_turns or low_stages:
        return "low" if low_turns >= max(1, len(turns) // 2) else "medium"
    if len(turns) >= 4 and all(turn.get("confidence") in {"medium", "high"} for turn in turns):
        return "high"
    return "medium"


def _evidence_summary(turns: List[Dict[str, Any]]) -> Dict[str, Any]:
    evidence_count = sum(1 for turn in turns if turn.get("evidence"))
    return {
        "turns_scored": len(turns),
        "turns_with_evidence": evidence_count,
        "insufficient_evidence_turns": sum(1 for turn in turns if turn.get("insufficient_evidence")),
    }


def _behavioral_findings(turns: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    for index, turn in enumerate(turns):
        response_id = turn.get("response_id")
        score = turn.get("overall_score")
        if not response_id or score is None or turn.get("insufficient_evidence"):
            continue
        strong = float(score) >= 70
        topic = str(turn.get("topic") or "General")
        findings.append({
            "finding_key": f"behavioral:{response_id}:{'strength' if strong else 'improvement'}",
            "what_happened": turn.get("feedback") or (
                "The response met the assessed evidence bar." if strong else "The response did not yet meet the assessed evidence bar."
            ),
            "where_happened": {"response_id": response_id, "topic": topic, "turn_index": index},
            "why_matters": "Interview decisions depend on specific, attributable evidence rather than unsupported general statements.",
            "evidence_ids": [response_id],
            "confidence": turn.get("confidence_value") or turn.get("confidence") or "low",
            "recommended_action": (
                "Reuse this evidence pattern in a concise STAR structure."
                if strong else "Add one owned action and one measurable result to the answer."
            ),
            "measurement": "A future answer names the owned action, result, and verification signal within 90 seconds.",
        })
    return findings


def _technical_findings(technical_output: Dict[str, Any]) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    for item in technical_output.get("submissions") or []:
        submission_id = item.get("submission_id")
        if not submission_id:
            continue
        passed = int(item.get("visible_passed") or 0) + int(item.get("hidden_passed") or 0)
        total = int(item.get("visible_total") or 0) + int(item.get("hidden_total") or 0)
        accepted = total > 0 and passed == total
        findings.append({
            "finding_key": f"technical:{submission_id}:deterministic_correctness",
            "what_happened": f"The final submission passed {passed} of {total} deterministic test cases.",
            "where_happened": {"submission_id": submission_id, "round_id": item.get("round_id")},
            "why_matters": "The final code verdict must follow the frozen visible and hidden test contract.",
            "evidence_ids": [submission_id],
            "confidence": 1.0,
            "recommended_action": (
                "Preserve the approach and explain its complexity and edge cases."
                if accepted else "Reproduce the failing boundary class and add a targeted local test before resubmitting."
            ),
            "measurement": "The next intentional final submission passes every frozen deterministic case.",
        })
    return findings


def _as_list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def _iso(value: Any) -> str | None:
    return value.isoformat() if hasattr(value, "isoformat") else None


def _source_counts(turns: List[Dict[str, Any]], technical_output: Dict[str, Any] | None = None) -> Dict[str, Any]:
    technical_output = technical_output or {}
    return {
        "candidate_turns": len(turns),
        "candidate_words": sum(len(str(turn.get("response") or "").split()) for turn in turns),
        "responses_with_evidence": sum(1 for turn in turns if turn.get("evidence")),
        "technical_submissions": int(technical_output.get("submission_count") or 0),
        "typed_technical_responses": int(technical_output.get("typed_response_count") or 0),
        "typed_technical_assessed": int(technical_output.get("typed_assessed_count") or 0),
        "technical_runs": int(technical_output.get("run_event_count") or 0),
        "technical_drafts": int(technical_output.get("draft_count") or 0),
    }


def _technical_title(item: Dict[str, Any], index: int) -> str:
    metadata = item.get("metadata") or item.get("round_metadata") or {}
    title = item.get("title") or metadata.get("title") or metadata.get("problem_title")
    if title:
        return str(title)
    prompt = str(item.get("prompt") or "").strip()
    return prompt.splitlines()[0][:80] if prompt else f"Problem {index + 1}"


def _technical_problem_payloads(technical_output: Dict[str, Any]) -> List[Dict[str, Any]]:
    problems: List[Dict[str, Any]] = []
    for index, item in enumerate(_as_list(technical_output.get("test_matrix"))):
        total = int(item.get("visible_total") or 0) + int(item.get("hidden_total") or 0)
        passed = int(item.get("visible_passed") or 0) + int(item.get("hidden_passed") or 0)
        is_typed = bool(item.get("response_id") or item.get("round_type")) and not total
        problems.append({
            "submission_id": item.get("submission_id"),
            "round_id": item.get("round_id"),
            "response_id": item.get("response_id"),
            "question_spec_id": item.get("question_spec_id"),
            "round_type": item.get("round_type"),
            "taxonomy_keys": item.get("taxonomy_keys") or [],
            "title": _technical_title(item, index),
            "language": item.get("language"),
            "prompt": item.get("prompt") or "",
            "algorithm_pattern": item.get("algorithm_pattern"),
            "visible_passed": int(item.get("visible_passed") or 0),
            "visible_total": int(item.get("visible_total") or 0),
            "hidden_passed": int(item.get("hidden_passed") or 0),
            "hidden_total": int(item.get("hidden_total") or 0),
            "runtime_ms": item.get("runtime_ms"),
            "memory_kb": item.get("memory_kb"),
            "score": item.get("score") if is_typed else (round((passed / total) * 100, 1) if total else None),
            "dimension_scores": item.get("dimension_scores") or {},
            "confidence": item.get("confidence"),
            "insufficient_evidence": bool(item.get("insufficient_evidence")),
            "final_pass_rate": item.get("final_pass_rate"),
            "final_verdict": item.get("final_verdict") or ("accepted" if total and passed == total else "needs_work"),
            "source_excerpt": item.get("source_excerpt") or "",
            "source_code": item.get("source_code") or item.get("source_excerpt") or "",
            "evidence_state": (
                "insufficient_evidence" if is_typed and item.get("insufficient_evidence")
                else ("assessed_response" if is_typed else "final_submission")
            ),
        })
    if problems:
        return problems

    for index, run in enumerate(_as_list(technical_output.get("run_events"))):
        validation = run.get("validation") or {}
        total_count = int(run.get("total_count") or validation.get("total_count") or 0)
        pass_count = int(run.get("pass_count") or validation.get("pass_count") or 0)
        problems.append({
            "round_id": run.get("round_id"),
            "title": _technical_title(run, index),
            "language": run.get("language"),
            "prompt": run.get("prompt") or "",
            "algorithm_pattern": run.get("algorithm_pattern") or (run.get("round_metadata") or {}).get("algorithm_pattern") or (run.get("metadata") or {}).get("algorithm_pattern"),
            "visible_passed": int(run.get("visible_passed") or validation.get("visible_passed") or 0),
            "visible_total": int(run.get("visible_total") or validation.get("visible_total") or 0),
            "hidden_passed": int(run.get("hidden_passed") or validation.get("hidden_passed") or 0),
            "hidden_total": int(run.get("hidden_total") or validation.get("hidden_total") or 0),
            "runtime_ms": run.get("runtime_ms"),
            "memory_kb": validation.get("memory_kb"),
            "score": round((pass_count / max(total_count, 1)) * 100, 1) if total_count else None,
            "final_pass_rate": None,
            "final_verdict": "run_only",
            "source_excerpt": run.get("source_excerpt") or "",
            "source_code": run.get("source_code") or run.get("source_excerpt") or "",
            "evidence_state": "run_only",
        })
    if problems:
        return problems

    for index, draft in enumerate(_as_list(technical_output.get("drafts"))):
        problems.append({
            "round_id": draft.get("round_id"),
            "title": _technical_title(draft, index),
            "language": draft.get("language"),
            "prompt": draft.get("prompt") or "",
            "algorithm_pattern": draft.get("algorithm_pattern") or (draft.get("round_metadata") or {}).get("algorithm_pattern") or (draft.get("metadata") or {}).get("algorithm_pattern"),
            "visible_passed": 0,
            "visible_total": 0,
            "hidden_passed": 0,
            "hidden_total": 0,
            "runtime_ms": None,
            "memory_kb": None,
            "score": None,
            "final_pass_rate": None,
            "final_verdict": "draft_only",
            "source_excerpt": draft.get("source_excerpt") or "",
            "source_code": draft.get("source_code") or draft.get("source_excerpt") or "",
            "evidence_state": "draft_only",
            "created_at": _iso(draft.get("created_at")),
        })
    return problems


def _technical_report_state(technical_output: Dict[str, Any]) -> str:
    if int(technical_output.get("submission_count") or 0):
        return "scored"
    if int(technical_output.get("run_event_count") or 0) or int(technical_output.get("draft_count") or 0):
        return "draft_or_run_only"
    return "no_technical_evidence"


def _technical_evidence_payload(technical_output: Dict[str, Any]) -> Dict[str, Any]:
    problems = _technical_problem_payloads(technical_output)
    return {
        "state": _technical_report_state(technical_output),
        "problems": problems,
        "submission_count": int(technical_output.get("submission_count") or 0),
        "run_count": int(technical_output.get("run_event_count") or 0),
        "draft_count": int(technical_output.get("draft_count") or 0),
        "evidence": technical_output.get("evidence", {}),
        "weak_topics": _as_list(technical_output.get("weak_topics")),
    }


def _technical_improvement_plan(technical_output: Dict[str, Any], weak_topics: List[Dict[str, Any]]) -> Dict[str, Any]:
    repeated_mistakes = [
        {
            "type": f"technical-{str(item.get('topic') or 'correctness').lower().replace(' ', '-')}",
            "count": len(item.get("round_ids") or []) or 1,
            "description": f"{item.get('topic', 'Technical correctness')} needs repair at {float(item.get('pass_rate') or 0):.1f}% pass rate.",
            "why_bad": item.get("repair_action") or "Interviewers value recovery: naming the failing case, fixing it, and proving the edge case.",
        }
        for item in weak_topics[:3]
    ]
    if not repeated_mistakes:
        repeated_mistakes = [
            {
                "type": "technical-repair",
                "count": max(1, int(technical_output.get("run_event_count") or 0)),
                "description": "Use failing runs to isolate the first broken assumption.",
                "why_bad": "Interviewers value recovery: naming the failing case, fixing it, and proving the edge case.",
            }
        ]

    weakest_topic = weak_topics[0] if weak_topics else {}
    topic_label = str(weakest_topic.get("topic") or "the weakest technical attempt")
    return {
        "repeated_mistakes": repeated_mistakes,
        "weak_areas": weak_topics,
        "strengths_to_reuse": ["Keep running visible tests before final submit."],
        "rewritten_examples": [],
        "next_drills": [
            {
                "mode": "fix_it",
                "title": f"Repair {topic_label}",
                "reason": weakest_topic.get("repair_action") or "Turn the last failing run into a clear fix plus edge-case explanation.",
                "success_criteria": ["failure explained", "smallest fix", "edge case tested", "complexity stated"],
            }
        ],
        "pre_next_interview_checklist": [
            "State the brute-force approach before optimizing.",
            "Run one custom edge case before final submit.",
            "Explain time and space complexity after the code passes.",
        ],
    }


def _no_evidence_report(*, interview_id: str, report_type: str, profile_type: str, transcript: List[Dict[str, Any]] | None = None) -> Dict[str, Any]:
    summary = "Not gradable: no candidate response was captured for this session."
    capture_guidance = (
        "Run the Interview Round again and keep the microphone active so spoken answers can be captured."
        if report_type == "behavioral"
        else "Run the Technical Round again and submit final code or a typed technical response before ending."
    )
    return {
        "version": f"async_{report_type}_report_v1_no_evidence",
        "interview_id": interview_id,
        "report_type": report_type,
        "profile_type": profile_type,
        "summary": summary,
        "readiness_label": "Not gradable",
        "overall_score": None,
        "recommendation": "Not gradable",
        "recommendation_confidence": 0.0,
        "scoring_confidence": "low",
        "evidence_policy": "Scores require candidate transcript or executable submission evidence. This session had no candidate evidence.",
        "evidence_status": {
            "status": "no_candidate_evidence",
            "candidate_word_count": 0,
            "reason": "No candidate response or technical submission was available.",
        },
        "evidence_summary": {
            "turns_scored": 0,
            "turns_with_evidence": 0,
            "insufficient_evidence_turns": 0,
        },
        "dimension_scores": {},
        "behavioral_metrics": {},
        "technical_process": {},
        "test_matrix": [],
        "weak_topics": [],
        "line_level_annotations": [],
        "transcript": transcript or [],
        "strengths": [],
        "improvements": [
            {
                "title": "Retake required",
                "detail": capture_guidance,
            }
        ],
        "practice_plan": [
            {"day": "Next attempt", "task": capture_guidance},
        ],
        "student_summary": {
            "headline": "This session could not be graded.",
            "blocker": "No candidate response was captured.",
            "next_step": "Retake the session with microphone or typed response capture enabled.",
            "interviewer_signal": "There is no candidate evidence to evaluate.",
            "proof_point": "No proof point was captured.",
        },
        "candidate_visible_integrity": "Session completed, but no candidate evidence was captured.",
        "recruiter_only": {},
    }


def _technical_draft_only_report(
    *,
    interview_id: str,
    profile_type: str,
    nlp_output: Dict[str, Any],
    technical_output: Dict[str, Any],
    cheating_output: Dict[str, Any],
) -> Dict[str, Any]:
    turns = nlp_output.get("turns") or []
    run_count = int(technical_output.get("run_event_count") or 0)
    draft_count = int(technical_output.get("draft_count") or 0)
    technical = _technical_evidence_payload(technical_output)
    weak_topics = _as_list(technical_output.get("weak_topics"))
    evidence_label = "Draft or run evidence was captured" if (draft_count or run_count) else "Transcript evidence was captured"
    return {
        "version": "async_technical_report_v2_draft_only",
        "interview_id": interview_id,
        "report_type": "technical",
        "report_subtype": "technical_draft_only",
        "profile_type": profile_type,
        "summary": f"Not gradable as a final technical submission. {evidence_label}, but no final submit was recorded.",
        "readiness_label": "Not gradable",
        "overall_score": None,
        "recommendation": "Final submission required",
        "recommendation_confidence": 0.0,
        "scoring_confidence": "low",
        "evidence_policy": "Technical scores require an intentional final submission. Practice runs and saved drafts are shown as evidence but are not graded as final work.",
        "evidence_summary": {
            **_evidence_summary(turns),
            "submission_count": 0,
            "run_event_count": run_count,
            "draft_count": draft_count,
            "technical_evidence": technical_output.get("evidence", {}),
            "source_counts": _source_counts(turns, technical_output),
        },
        "evidence_status": {
            "status": "draft_or_run_only",
            "submission_count": 0,
            "run_event_count": run_count,
            "draft_count": draft_count,
            "reason": "No TechnicalSubmissions row was available for this interview.",
        },
        "dimension_scores": {},
        "technical_process": {
            "submission_count": 0,
            "run_event_count": run_count,
            "draft_count": draft_count,
            "latest_exit_code": technical_output.get("latest_exit_code"),
            "code_origin_verdict": "Uncertain" if cheating_output.get("risk_level") == "Medium" else "Not assessed",
        },
        "technical": technical,
        "test_matrix": technical["problems"],
        "weak_topics": weak_topics,
        "improvement_plan": _technical_improvement_plan(technical_output, weak_topics),
        "practice_plan": _technical_practice_plan(technical_output),
        "ideal_solution": {},
        "complexity_diff": {},
        "line_level_annotations": [],
        "transcript": turns,
        "strengths": ["Draft code was captured for review." if draft_count else ("Practice run evidence was captured." if run_count else "Transcript evidence was captured.")],
        "improvements": [
            {
                "title": "Final submission",
                "detail": "Use the Submit button before ending the round so visible and hidden tests can be graded as final evidence.",
            }
        ],
        "candidate_visible_integrity": "Session completed, but no final technical submission was captured.",
        "recruiter_only": {
            "cheating_risk": cheating_output,
            "code_origin": cheating_output.get("code_flags", []),
        },
    }




def build_async_behavioral_report(
    *,
    interview_id: str,
    profile_type: str,
    nlp_output: Dict[str, Any],
    audio_output: Dict[str, Any],
    video_output: Dict[str, Any],
    cheating_output: Dict[str, Any],
) -> Dict[str, Any]:
    turns = nlp_output.get("turns") or []
    gradable_turns = [
        turn for turn in turns
        if turn.get("overall_score") is not None and not turn.get("insufficient_evidence")
    ]
    if not gradable_turns:
        return _no_evidence_report(interview_id=interview_id, report_type="behavioral", profile_type=profile_type)
    overall_score = float(_nullable_avg([turn.get("overall_score") for turn in gradable_turns]) or 0)
    communication = nlp_output.get("communication_score")
    star = nlp_output.get("average_star_score")
    technical = nlp_output.get("content_depth_score")
    evidence_confidence = _nullable_avg([
        float(turn.get("confidence_value") or 0) * 100
        for turn in gradable_turns
    ])
    recommendation = "Strong interview-performance signal" if overall_score >= 72 else "Targeted practice recommended"

    per_question = [
        {
            "response_id": turn.get("response_id"),
            "question": turn.get("question", ""),
            "question_type": turn.get("question_type", "main"),
            "topic": turn.get("topic", "General"),
            "response": turn.get("response", ""),
            "score": turn.get("overall_score"),
            "feedback": turn.get("feedback", ""),
            "confidence": turn.get("confidence", "low"),
            "insufficient_evidence": bool(turn.get("insufficient_evidence")),
            "evidence": turn.get("evidence", [])[:3],
            "evidence_quotes": turn.get("evidence", [])[:3],
            "answer_quality_flags": turn.get("answer_quality_flags", []),
            "rubric_scores": turn.get("rubric_scores", {}),
            "time_taken": turn.get("time_taken"),
            "stronger_answer_outline": _stronger_answer_outline(turn),
            "annotations": _turn_annotations(turn),
        }
        for turn in turns
    ]

    available_dimensions = [
        f"communication {communication:.1f}" if isinstance(communication, (int, float)) else None,
        f"answer structure {star:.1f}" if isinstance(star, (int, float)) else None,
        f"technical accuracy {technical:.1f}" if isinstance(technical, (int, float)) else None,
    ]
    dimension_summary = ", ".join(item for item in available_dimensions if item)
    summary = (
        f"{recommendation} for the {profile_type.replace('_', ' ')} benchmark. "
        f"Overall score is {overall_score:.1f}/100 from {len(gradable_turns)} assessed answer(s)."
        + (f" Measured dimensions: {dimension_summary}." if dimension_summary else "")
    )
    return {
        "version": "async_behavioral_report_v3_canonical",
        "interview_id": interview_id,
        "report_type": "behavioral",
        "profile_type": profile_type,
        "summary": summary,
        "readiness_label": _score_band(overall_score),
        "overall_score": overall_score,
        "recommendation": recommendation,
        "recommendation_confidence": _clip(55 + abs(overall_score - 60) * 0.5),
        "scoring_confidence": _confidence_label(turns, audio_output, video_output),
        "evidence_policy": "Scores are capped or marked low confidence when transcript, media, or proof-point evidence is weak.",
        "evidence_summary": {
            **_evidence_summary(turns),
            "source_counts": _source_counts(turns),
        },
        "dimension_scores": {
            "technical_competency": technical,
            "communication_clarity": communication,
            "evidence_confidence": evidence_confidence,
            "answer_structure_star": star,
            "relevance": _dimension_average(gradable_turns, "relevance"),
            "ownership": _dimension_average(gradable_turns, "ownership"),
            "specificity_evidence": _dimension_average(gradable_turns, "specificity_evidence"),
            "tradeoffs": _dimension_average(gradable_turns, "tradeoffs"),
            "overall_interview_performance": overall_score,
        },
        "behavioral_metrics": {
            "words_per_minute": audio_output.get("words_per_minute"),
            "filler_count": audio_output.get("filler_count"),
            "voiced_duration_seconds": audio_output.get("voiced_duration_seconds"),
            "pause_duration_seconds": audio_output.get("pause_duration_seconds"),
            "response_latency_seconds_avg": audio_output.get("response_latency_seconds_avg"),
            "face_present_percent": video_output.get("face_present_percent"),
            "face_centered_percent": video_output.get("face_centered_percent"),
        },
        "findings": _behavioral_findings(gradable_turns),
        "strengths": _async_strengths(gradable_turns),
        "improvements": _async_improvements(gradable_turns, star, communication),
        "improvement_plan": _build_improvement_plan(gradable_turns),
        "per_turn_feedback": per_question,
        "questions": per_question,
        "timeline": {
            "weak_moments": [turn.get("topic", "General") for turn in gradable_turns if float(turn.get("overall_score")) < 55][:3],
            "strong_moments": [turn.get("topic", "General") for turn in gradable_turns if float(turn.get("overall_score")) >= 75][:3],
        },
        "student_summary": _behavioral_student_summary(gradable_turns, overall_score),
        "candidate_visible_integrity": "Session completed.",
        "recruiter_only": {
            "cheating_risk": cheating_output,
        },
    }


def build_async_technical_report(
    *,
    interview_id: str,
    profile_type: str,
    nlp_output: Dict[str, Any],
    technical_output: Dict[str, Any],
    cheating_output: Dict[str, Any],
) -> Dict[str, Any]:
    submission_count = int(technical_output.get("submission_count") or 0)
    typed_response_count = int(technical_output.get("typed_response_count") or 0)
    typed_assessed_count = int(technical_output.get("typed_assessed_count") or 0)
    run_event_count = int(technical_output.get("run_event_count") or 0)
    draft_count = int(technical_output.get("draft_count") or 0)
    if not submission_count and not typed_response_count and not run_event_count and not draft_count:
        return _no_evidence_report(interview_id=interview_id, report_type="technical", profile_type=profile_type)
    if not submission_count and not typed_assessed_count:
        return _technical_draft_only_report(
            interview_id=interview_id,
            profile_type=profile_type,
            nlp_output=nlp_output,
            technical_output=technical_output,
            cheating_output=cheating_output,
        )
    correctness = technical_output.get("correctness_score") if submission_count else None
    code_quality = technical_output.get("code_quality_score") if submission_count else None
    communication = nlp_output.get("communication_score")
    typed_score = technical_output.get("typed_response_score") if typed_assessed_count else None
    tradeoff_reasoning = _dimension_average(nlp_output.get("turns") or [], "tradeoffs")
    overall = _weighted_available([
        (correctness, 0.50),
        (typed_score, 0.30),
        (communication, 0.12),
        (tradeoff_reasoning, 0.08),
    ])
    if overall is None:
        return _technical_draft_only_report(
            interview_id=interview_id,
            profile_type=profile_type,
            nlp_output=nlp_output,
            technical_output=technical_output,
            cheating_output=cheating_output,
        )
    recommendation = "Strong technical practice signal" if overall >= 72 else "Targeted practice recommended"
    technical = _technical_evidence_payload(technical_output)
    weak_topics = _as_list(technical_output.get("weak_topics"))
    summary = (
        f"{recommendation} for this technical round. "
        f"The score is based on {submission_count} executable final submission(s) and "
        f"{typed_assessed_count} assessed technical response(s); unknown dimensions remain unscored."
    )
    return {
        "version": "async_technical_report_v3_canonical",
        "interview_id": interview_id,
        "report_type": "technical",
        "profile_type": profile_type,
        "summary": summary,
        "readiness_label": _score_band(overall),
        "overall_score": overall,
        "recommendation": recommendation,
        "recommendation_confidence": _clip(55 + abs(overall - 60) * 0.5),
        "scoring_confidence": _confidence_label(nlp_output.get("turns") or [], technical_output),
        "evidence_policy": "Technical scores require executable run evidence and transcript/code evidence; missing evidence is exposed as low confidence.",
        "evidence_summary": {
            **_evidence_summary(nlp_output.get("turns") or []),
            "submission_count": technical_output.get("submission_count", 0),
            "typed_response_count": typed_response_count,
            "typed_assessed_count": typed_assessed_count,
            "run_event_count": run_event_count,
            "draft_count": draft_count,
            "technical_evidence": technical_output.get("evidence", {}),
            "source_counts": _source_counts(nlp_output.get("turns") or [], technical_output),
        },
        "evidence_status": {
            "status": "scored" if submission_count or typed_assessed_count else "low_evidence",
            "submission_count": technical_output.get("submission_count", 0),
            "typed_assessed_count": typed_assessed_count,
            "run_event_count": technical_output.get("run_event_count", 0),
        },
        "dimension_scores": {
            "code_correctness": correctness,
            "typed_technical_accuracy": typed_score,
            "tradeoff_reasoning": tradeoff_reasoning,
            "code_quality": code_quality,
            "communication_during_coding": communication,
            "overall_technical_performance": overall,
        },
        "technical_process": {
            "submission_count": technical_output.get("submission_count", 0),
            "typed_response_count": typed_response_count,
            "run_event_count": technical_output.get("run_event_count", 0),
            "latest_exit_code": technical_output.get("latest_exit_code"),
            "code_origin_verdict": "Integrity flags present" if cheating_output.get("risk_score") else "Not assessed",
        },
        "findings": _technical_findings(technical_output),
        "technical": technical,
        "test_matrix": technical["problems"],
        "weak_topics": weak_topics,
        "ideal_solution": _ideal_solution_summary(technical_output),
        "complexity_diff": _complexity_diff(technical_output),
        "line_level_annotations": _technical_annotations(technical_output),
        "strengths": _technical_strengths(technical_output, correctness, code_quality),
        "improvements": _technical_improvements(technical_output, correctness, code_quality),
        "improvement_plan": _technical_improvement_plan(technical_output, weak_topics),
        "practice_plan": _technical_practice_plan(technical_output),
        "per_turn_feedback": [
            {
                "question": turn.get("question", ""),
                "topic": turn.get("topic", "Technical explanation"),
                "response": turn.get("response", ""),
                "score": turn.get("overall_score"),
                "feedback": turn.get("feedback", ""),
                "answer_quality_flags": turn.get("answer_quality_flags", []),
                "evidence_quotes": turn.get("evidence", [])[:3],
            }
            for turn in nlp_output.get("turns") or []
        ],
        "candidate_visible_integrity": "Session completed.",
        "recruiter_only": {
            "cheating_risk": cheating_output,
            "code_origin": cheating_output.get("code_flags", []),
        },
    }


def _ideal_solution_summary(technical_output: Dict[str, Any]) -> Dict[str, Any]:
    submissions = technical_output.get("submissions") or []
    first = submissions[0] if submissions else {}
    return {
        "language": first.get("language"),
        "algorithm_pattern": first.get("algorithm_pattern"),
        "expected_time_complexity": first.get("expected_time_complexity"),
        "expected_space_complexity": first.get("expected_space_complexity"),
    }


def _complexity_diff(technical_output: Dict[str, Any]) -> Dict[str, Any]:
    submissions = technical_output.get("submissions") or []
    first = submissions[0] if submissions else {}
    return {
        "expected_time": first.get("expected_time_complexity"),
        "expected_space": first.get("expected_space_complexity"),
        "observed_runtime_ms": first.get("runtime_ms"),
        "observed_memory_kb": first.get("memory_kb"),
    }


def _technical_annotations(technical_output: Dict[str, Any]) -> List[Dict[str, Any]]:
    annotations: List[Dict[str, Any]] = []
    for item in technical_output.get("test_matrix") or []:
        total = int(item.get("visible_total") or 0) + int(item.get("hidden_total") or 0)
        passed = int(item.get("visible_passed") or 0) + int(item.get("hidden_passed") or 0)
        if total and passed < total:
            annotations.append({
                "type": "test_failure",
                "round_id": item.get("round_id"),
                "message": f"{total - passed} test case(s) failed. Start with the smallest failing edge case before optimizing.",
            })
    return annotations[:8]


def _turn_annotations(turn: Dict[str, Any]) -> List[Dict[str, Any]]:
    annotations: List[Dict[str, Any]] = []
    flags = turn.get("answer_quality_flags") or []
    for flag in flags:
        annotations.append({
            "type": str(flag),
            "message": _flag_guidance(str(flag)),
        })
    return annotations[:4]


def _flag_guidance(flag: str) -> str:
    return {
        "too_short": "The answer ended before it proved the claim with owned action and result.",
        "no_evidence": "The answer did not include a concrete project fact, metric, shipped result, or technical proof point.",
        "missing_ownership": "The answer did not make the candidate's personal ownership clear enough.",
        "missing_tradeoff": "The answer did not explain the trade-off, constraint, edge case, or reason behind the decision.",
        "no_response": "No candidate response was captured for this question.",
    }.get(flag, "This answer pattern lowered the evidence quality for the response.")


def _stronger_answer_outline(turn: Dict[str, Any]) -> str:
    flags = set(turn.get("answer_quality_flags") or [])
    topic = turn.get("topic") or "this question"
    steps = ["direct answer"]
    if "missing_ownership" in flags:
        steps.append("specific action you owned")
    else:
        steps.append("owned action")
    if "no_evidence" in flags or "too_short" in flags:
        steps.append("project fact or metric")
    steps.append("technical mechanism")
    if "missing_tradeoff" in flags:
        steps.append("trade-off or edge case")
    steps.append("result")
    return f"Repair the {topic} answer with: " + " -> ".join(steps) + "."


def _behavioral_student_summary(turns: List[Dict[str, Any]], overall_score: float) -> Dict[str, str]:
    weakest = min(turns, key=lambda turn: float(turn.get("overall_score") or 0))
    strongest = max(turns, key=lambda turn: float(turn.get("overall_score") or 0))
    return {
        "headline": f"{_score_band(overall_score)} based on {len(turns)} captured answer(s).",
        "blocker": weakest.get("feedback") or "The weakest captured answer needs more concrete evidence.",
        "next_step": _stronger_answer_outline(weakest),
        "interviewer_signal": f"Strongest captured topic: {strongest.get('topic', 'General')} ({float(strongest.get('overall_score') or 0):.1f}/100).",
        "proof_point": (strongest.get("evidence") or ["No proof point was captured in the strongest answer."])[0],
    }


def _technical_strengths(
    technical_output: Dict[str, Any],
    correctness: float | None,
    code_quality: float | None,
) -> List[str]:
    strengths: List[str] = []
    for item in _technical_problem_payloads(technical_output):
        total = int(item.get("visible_total") or 0) + int(item.get("hidden_total") or 0)
        passed = int(item.get("visible_passed") or 0) + int(item.get("hidden_passed") or 0)
        if total and passed == total:
            strengths.append(f"{item.get('title', 'Problem')} passed all {total} evaluated test case(s).")
        elif item.get("source_code"):
            strengths.append(f"{item.get('title', 'Problem')} has captured code available for review.")
    if isinstance(correctness, (int, float)) and correctness > 0 and not strengths:
        strengths.append(f"Final submissions passed {correctness:.1f}% of evaluated tests.")
    if isinstance(code_quality, (int, float)) and code_quality >= 70:
        strengths.append(f"Runtime and implementation signals produced a {code_quality:.1f}/100 code-quality score.")
    return strengths[:4]


def _technical_improvements(
    technical_output: Dict[str, Any],
    correctness: float | None,
    code_quality: float | None,
) -> List[Dict[str, str]]:
    items: List[Dict[str, str]] = []
    for problem in _technical_problem_payloads(technical_output):
        total = int(problem.get("visible_total") or 0) + int(problem.get("hidden_total") or 0)
        passed = int(problem.get("visible_passed") or 0) + int(problem.get("hidden_passed") or 0)
        if problem.get("evidence_state") != "final_submission":
            items.append({
                "title": f"Submit {problem.get('title', 'the problem')}",
                "detail": "A draft/run was captured, but no final submission exists, so the system cannot grade correctness.",
            })
        elif total and passed < total:
            items.append({
                "title": f"Repair {problem.get('title', 'the failed problem')}",
                "detail": f"{total - passed} of {total} evaluated test case(s) failed. Reproduce the smallest failing case, fix that, then retest.",
            })
    if isinstance(correctness, (int, float)) and correctness < 80 and not items:
        items.append({"title": "Correctness", "detail": "Use visible tests plus one custom boundary case before final submit."})
    if isinstance(code_quality, (int, float)) and code_quality < 70:
        items.append({"title": "Implementation quality", "detail": "Keep the solution smaller, avoid unnecessary allocations, and rerun after each focused fix."})
    return items[:4]


def _technical_practice_plan(technical_output: Dict[str, Any]) -> List[Dict[str, str]]:
    problems = _technical_problem_payloads(technical_output)
    if not problems:
        return [{"day": "Next attempt", "task": "Run and submit at least one technical problem so the report can grade real code."}]
    weakest = min(problems, key=lambda item: float(item.get("score") or 0))
    return [
        {"day": "Today", "task": f"Re-open {weakest.get('title', 'the weakest problem')} and write the smallest failing edge case first."},
        {"day": "Next drill", "task": "Implement the fix in one pass, then run visible and custom tests before submitting."},
        {"day": "Before next round", "task": "State time and space complexity after the solution passes the evaluated tests."},
    ]


def _async_strengths(turns: List[Dict[str, Any]]) -> List[str]:
    assessed = [turn for turn in turns if isinstance(turn.get("overall_score"), (int, float))]
    strong = [turn for turn in assessed if float(turn["overall_score"]) >= 75]
    if strong:
        return [
            f"{turn.get('topic', 'Question')} scored {float(turn.get('overall_score') or 0):.1f}/100: {turn.get('feedback', '')}"
            for turn in strong[:3]
        ]
    captured = [turn for turn in assessed if str(turn.get("response") or "").strip()]
    if not captured:
        return []
    best = max(captured, key=lambda turn: float(turn.get("overall_score") or 0))
    return [f"Best captured answer was {best.get('topic', 'General')} at {float(best.get('overall_score') or 0):.1f}/100."]


def _async_improvements(
    turns: List[Dict[str, Any]],
    star: float | None,
    communication: float | None,
) -> List[Dict[str, str]]:
    items = []
    if isinstance(star, (int, float)) and star < 75:
        items.append({"title": "STAR structure", "detail": "Make each behavioral answer explicit: situation, task, action you owned, and measurable result."})
    if isinstance(communication, (int, float)) and communication < 75:
        items.append({"title": "Communication clarity", "detail": "Reduce filler words and lead with the direct answer before context."})
    weakest = sorted(
        [turn for turn in turns if turn.get("overall_score") is not None],
        key=lambda turn: float(turn["overall_score"]),
    )[:1]
    for turn in weakest:
        items.append({"title": f"Question: {turn.get('topic', 'General')}", "detail": turn.get("feedback", "Add more concrete evidence.")})
    return items[:3]


def _turn_mistake(turn: Dict[str, Any]) -> Dict[str, Any]:
    response = str(turn.get("response") or "")
    lower = response.lower()
    if len(response.split()) < 45:
        kind = "too-short"
        diagnosis = "The answer is too short to prove claim, ownership, decision, and result."
        why_bad = "The interviewer has to guess what you owned and whether the work had impact."
        drill_mode = "write_it"
    elif not any(token in lower for token in ("i built", "i implemented", "i designed", "i owned", "my role", "i debugged")):
        kind = "missing-ownership"
        diagnosis = "Your personal ownership is not visible enough."
        why_bad = "Interviewers score your contribution, not the team's general activity."
        drill_mode = "best_vs_worst"
    elif not any(token in lower for token in ("because", "trade-off", "alternative", "constraint", "edge case", "failure")):
        kind = "missing-tradeoff"
        diagnosis = "The answer does not explain the constraint or trade-off behind the decision."
        why_bad = "Without trade-offs, the answer sounds memorized instead of judgment-based."
        drill_mode = "chain_it"
    elif not any(ch.isdigit() for ch in response):
        kind = "missing-result"
        diagnosis = "The answer does not close with a concrete result, metric, or shipped signal."
        why_bad = "Interviewers need evidence that the work mattered beyond implementation activity."
        drill_mode = "write_it"
    else:
        kind = "structure-needs-polish"
        diagnosis = "The evidence is present but the answer needs a cleaner order."
        why_bad = "Good details are easier to remember when they follow a predictable structure."
        drill_mode = "best_vs_worst"
    return {
        "type": kind,
        "diagnosis": diagnosis,
        "why_bad": why_bad,
        "quote": response.replace("\n", " ")[:240],
        "better_structure": ["Direct answer", "Owned action", "Technical mechanism", "Trade-off or edge case", "Measured result"],
        "improved_answer": "",
        "rewrite_instruction": _stronger_answer_outline(turn),
        "drill": {
            "mode": drill_mode,
            "title": f"Repair {kind.replace('-', ' ')}",
            "reason": why_bad,
            "success_criteria": ["direct answer", "ownership", "mechanism", "trade-off", "result"],
        },
    }


def _build_improvement_plan(turns: List[Dict[str, Any]]) -> Dict[str, Any]:
    weak_turns = sorted(turns, key=lambda turn: float(turn.get("overall_score") or 0))[:3]
    mistakes = [_turn_mistake(turn) for turn in weak_turns]
    counts = Counter(item["type"] for item in mistakes)
    repeated = [
        {
            "type": kind,
            "count": count,
            "description": next(item["diagnosis"] for item in mistakes if item["type"] == kind),
            "why_bad": next(item["why_bad"] for item in mistakes if item["type"] == kind),
        }
        for kind, count in counts.most_common()
    ]
    return {
        "repeated_mistakes": repeated,
        "weak_areas": [
            {
                "topic": turn.get("topic", "General"),
                "score": float(turn.get("overall_score") or 0),
                "mistake": mistakes[index] if index < len(mistakes) else None,
            }
            for index, turn in enumerate(weak_turns)
        ],
        "strengths_to_reuse": _async_strengths(turns),
        "rewritten_examples": [
            {
                "question": weak_turns[index].get("question", ""),
                "original_excerpt": item["quote"],
                "better_structure": item["better_structure"],
                "improved_answer": item.get("rewrite_instruction", ""),
            }
            for index, item in enumerate(mistakes)
        ],
        "next_drills": [item["drill"] for item in mistakes],
        "pre_next_interview_checklist": [
            "Prepare one metric or shipped result for each project story.",
            "Practice one answer in direct answer, ownership, mechanism, trade-off, result order.",
            "Redo the weakest question before starting another full mock.",
        ],
    }
