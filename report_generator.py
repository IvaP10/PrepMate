"""Build deterministic, evidence-backed candidate reports.

The report is a record of what happened in a round. Coaching and practice
missions are created by the separate Improve pipeline and are intentionally
not included here.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Dict, Iterable, List
import re


def _as_list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def _as_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _self_review_summary(value: Any) -> Dict[str, Any]:
    """Expose optional coaching observations without punitive scoring."""
    source = _as_dict(value)
    events = []
    for event in _as_list(source.get("events")):
        if not isinstance(event, dict):
            continue
        count = int(event.get("count") or 0)
        if count <= 0:
            continue
        events.append({
            "event_type": _text(event.get("event_type") or "signal"),
            "count": count,
        })
    return {
        "mode": "self_review",
        "signals": events,
        "signal_count": sum(item["count"] for item in events),
        "message": "Optional coaching signals are private context and are not a cheating, hiring, or pass/fail score.",
    }


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _rounded(value: Any, digits: int = 1) -> float | None:
    numeric = _number(value)
    return round(numeric, digits) if numeric is not None else None


def _iso(value: Any) -> str | None:
    return value.isoformat() if hasattr(value, "isoformat") else (str(value) if value else None)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _average(values: Iterable[Any]) -> float | None:
    clean = [float(value) for value in values if isinstance(value, (int, float)) and not isinstance(value, bool)]
    return round(sum(clean) / len(clean), 1) if clean else None


def _first_sentence(value: Any, limit: int = 420) -> str:
    text = re.sub(r"\s+", " ", _text(value))
    if len(text) <= limit:
        return text
    sentence = re.split(r"(?<=[.!?])\s+", text[:limit])[-1]
    return text[:limit].rsplit(" ", 1)[0] if sentence == text[:limit] else text[:limit]


def _unique_strings(values: Iterable[Any]) -> List[str]:
    result: List[str] = []
    for value in values or []:
        item = _text(value)
        if item and item not in result:
            result.append(item)
    return result


def _evidence_parts(turn: Dict[str, Any]) -> Dict[str, Any]:
    basis = _as_dict(turn.get("evidence_basis"))
    assessment = _as_dict(turn.get("assessment"))
    evidence = _as_dict(assessment.get("evidence"))
    return {
        "basis": basis,
        "assessment": assessment,
        "evidence": evidence,
        "covered": _as_list(basis.get("covered_point_ids") or evidence.get("covered_points")),
        "missed": _as_list(basis.get("missed_point_ids") or evidence.get("missed_points")),
        "incorrect": _as_list(basis.get("incorrect_claim_ids") or evidence.get("incorrect_claims")),
        "contradictions": _as_list(basis.get("contradictions") or evidence.get("contradictions")),
        "quotes": _as_list(turn.get("evidence") or evidence.get("evidence_quotes") or evidence.get("deterministic_quotes")),
    }


def _point_label(point: Any, expected_points: List[Any]) -> str:
    if isinstance(point, dict):
        return _text(point.get("label") or point.get("description") or point.get("id"))
    point_id = _text(point)
    for expected in expected_points:
        if isinstance(expected, dict) and _text(expected.get("id") or expected.get("key")) == point_id:
            return _text(expected.get("label") or expected.get("description") or point_id)
    return point_id


def _labels(values: Iterable[Any], expected_points: List[Any]) -> List[str]:
    return _unique_strings(_point_label(value, expected_points) for value in values)


def _turn_status(turn: Dict[str, Any]) -> str:
    response = _text(turn.get("response"))
    if not response:
        return "Not Answered"
    score = _number(turn.get("overall_score"))
    assessment = turn.get("assessment")
    if turn.get("insufficient_evidence") or _as_dict(assessment).get("evidence_status") == "insufficient_evidence":
        return "Incomplete"
    if score is None:
        return "Unable to Evaluate"
    return "Completed"


def _turn_score(turn: Dict[str, Any], status: str) -> float | None:
    if status == "Not Answered":
        return 0.0
    if status in {"Incomplete", "Unable to Evaluate"}:
        return None
    score = _number(turn.get("overall_score"))
    return round(max(0.0, min(100.0, score)), 1) if score is not None else None


def _structure_status(turn: Dict[str, Any]) -> Dict[str, str]:
    parts = _evidence_parts(turn)
    signals = _as_dict(parts["basis"].get("signals") or parts["assessment"].get("signals"))
    structure = _as_dict(signals.get("structure"))
    markers = _as_dict(structure.get("star_markers") or parts["assessment"].get("star_markers"))
    result: Dict[str, str] = {}
    for key in ("situation", "task", "action", "result"):
        value = markers.get(key)
        if value is None:
            value = markers.get(f"{key}_present")
        if value is None:
            value = structure.get(f"{key}_present")
        if isinstance(value, bool):
            result[key] = "Present" if value else "Missing"
        elif _text(value):
            result[key] = _text(value)
    return result


def _question_analysis(turn: Dict[str, Any], index: int) -> Dict[str, Any]:
    status = _turn_status(turn)
    score = _turn_score(turn, status)
    parts = _evidence_parts(turn)
    expected_points = _as_list(turn.get("expected_points"))
    covered = _labels(parts["covered"], expected_points)
    missed = _labels(parts["missed"], expected_points)
    incorrect = _labels(parts["incorrect"], expected_points)
    contradictions = _unique_strings(parts["contradictions"])
    flags = _unique_strings(turn.get("answer_quality_flags") or parts["assessment"].get("flags"))
    answered = status not in {"Not Answered", "Unable to Evaluate"}
    fully_answered = status == "Completed" and not missed and not incorrect and not contradictions and not any(
        flag in {"too_short", "unsupported_or_unspecific", "ownership_unclear", "missing_tradeoffs", "indirect_response"}
        for flag in flags
    )
    reduced_score = _unique_strings([
        *[f"Missing: {item}" for item in missed],
        *[f"Incorrect: {item}" for item in incorrect],
        *[f"Contradiction: {item}" for item in contradictions],
        *[
            {
                "too_short": "The captured answer was too short for the recorded rubric.",
                "unsupported_or_unspecific": "A claim was recorded without a supporting action, result, or example.",
                "ownership_unclear": "Personal ownership was not clear in the recorded answer.",
                "missing_tradeoffs": "The recorded answer did not include the relevant trade-off evidence.",
                "indirect_response": "The recorded answer did not lead with a direct response.",
            }.get(flag, "")
            for flag in flags
        ],
    ])
    good = _unique_strings([
        *covered,
        *[f"Captured evidence: {quote}" for quote in parts["quotes"]],
    ])
    question = _text(turn.get("question"))
    question_type = _text(turn.get("question_type") or "main")
    lower_question = f"{question} {question_type} {_text(turn.get('topic'))}".lower()
    is_behavioral = any(token in lower_question for token in ("behavior", "experience", "project", "resume", "leadership", "conflict", "ownership", "tell me"))
    is_project_resume = "project" in lower_question or "resume" in lower_question
    output: Dict[str, Any] = {
        "index": index,
        "response_id": turn.get("response_id"),
        "question_id": turn.get("question_id") or turn.get("question_spec_id"),
        "question": question,
        "question_type": question_type,
        "is_followup": bool(turn.get("is_followup")),
        "topic": _text(turn.get("topic") or turn.get("topic_label") or "General"),
        "status": status,
        "time_used_seconds": turn.get("time_taken"),
        "score": score,
        "score_10": round(score / 10.0, 1) if score is not None else None,
        "max_score": 10,
        "response": _text(turn.get("response")),
        "transcript": _text(turn.get("response")),
        "what_candidate_answered": _text(turn.get("response")),
        "what_was_good": good,
        "what_reduced_score": reduced_score,
        "evidence": {
            "correctly_mentioned": covered,
            "missing": missed,
            "incorrect_claims": incorrect,
            "contradictions": contradictions,
            "quotes": _unique_strings(parts["quotes"]),
        },
        "answer_quality_flags": flags,
        "fully_answered": fully_answered,
        "partially_answered": answered and not fully_answered,
        "evaluator_version": turn.get("evaluator_version"),
    }
    if is_behavioral:
        star = _structure_status(turn)
        if star:
            output["answer_structure"] = star
    if is_project_resume and (covered or missed or incorrect):
        output["project_resume_coverage"] = {
            "covered": covered,
            "missing": missed,
            "incorrect": incorrect,
        }
    return output


def _interview_score_breakdown(turns: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    mappings = (
        ("technical_accuracy", "Technical accuracy", ("technical_accuracy", "correctness", "technical")),
        ("communication", "Communication", ("communication", "directness", "filler_control")),
        ("problem_solving", "Problem solving", ("problem_solving", "reasoning", "depth", "tradeoffs")),
        ("relevance", "Relevance", ("relevance", "specificity_evidence", "specificity")),
    )
    result: List[Dict[str, Any]] = []
    for key, label, source_keys in mappings:
        values: List[float] = []
        for turn in turns:
            if _turn_status(turn) != "Completed":
                continue
            scores = _as_dict(turn.get("rubric_scores"))
            values.extend(score for name, score in scores.items() if name in source_keys and _number(score) is not None)
        score = _average(values)
        if score is not None:
            result.append({"key": key, "label": label, "score": score, "question_count": len(values)})
    return result


def _interview_round_analysis(turns: List[Dict[str, Any]], questions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    patterns: List[Dict[str, Any]] = []
    completed = [item for item in questions if item["status"] == "Completed"]
    partial = [item for item in questions if item["partially_answered"]]
    missing = [item for item in completed if item["evidence"]["missing"]]
    incorrect = [item for item in completed if item["evidence"]["incorrect_claims"]]
    if len(missing) >= 2:
        patterns.append({
            "pattern": "Missing expected points",
            "evidence_count": len(missing),
            "detail": f"{len(missing)} of {len(completed)} completed answers were missing at least one recorded expected point.",
            "evidence_ids": [item.get("response_id") for item in missing if item.get("response_id")],
        })
    if len(incorrect) >= 2:
        patterns.append({
            "pattern": "Incorrect claims",
            "evidence_count": len(incorrect),
            "detail": f"{len(incorrect)} of {len(completed)} completed answers contained at least one recorded incorrect claim.",
            "evidence_ids": [item.get("response_id") for item in incorrect if item.get("response_id")],
        })
    if len(partial) >= 2:
        patterns.append({
            "pattern": "Partially answered questions",
            "evidence_count": len(partial),
            "detail": f"{len(partial)} of {len(questions)} questions had an answer but were not fully covered by the recorded evidence.",
            "evidence_ids": [item.get("response_id") for item in partial if item.get("response_id")],
        })
    if len(completed) >= 2 and len(completed) - len(missing) - len(incorrect) >= 2:
        strong = [item for item in completed if not item["evidence"]["missing"] and not item["evidence"]["incorrect_claims"]]
        if len(strong) >= 2:
            patterns.append({
                "pattern": "Recorded expected points covered",
                "evidence_count": len(strong),
                "detail": f"{len(strong)} completed answers covered the recorded expected points without an incorrect claim.",
                "evidence_ids": [item.get("response_id") for item in strong if item.get("response_id")],
            })
    return patterns


def build_async_behavioral_report(
    *,
    interview_id: str,
    profile_type: str,
    nlp_output: Dict[str, Any],
    audio_output: Dict[str, Any],
    video_output: Dict[str, Any],
    self_review_output: Dict[str, Any],
) -> Dict[str, Any]:
    raw_turns = [
        turn
        for turn in _as_list(nlp_output.get("turns"))
        if isinstance(turn, dict)
        and not turn.get("scoring_excluded")
        and str(turn.get("question_type") or "").strip().lower() not in {"warmup", "introduction"}
    ]
    questions = [_question_analysis(turn, index + 1) for index, turn in enumerate(raw_turns)]
    gradable = [
        item
        for item in questions
        if item["status"] == "Completed" and item["score"] is not None
    ]
    eligible_scores = [
        item["score"]
        for item in questions
        if item["status"] in {"Completed", "Not Answered"} and item["score"] is not None
    ]
    overall_score = _average(eligible_scores)
    all_not_answered = bool(questions) and all(item["status"] == "Not Answered" for item in questions)
    no_candidate_evidence = not questions or all_not_answered
    if all_not_answered:
        overall_score = 0.0
    elif not gradable:
        overall_score = None
    answered = [item for item in questions if item["status"] not in {"Not Answered", "Unable to Evaluate"}]
    fully = [item for item in questions if item["fully_answered"]]
    partial = [item for item in questions if item["partially_answered"]]
    not_answered = [item for item in questions if item["status"] == "Not Answered"]
    incomplete = [item for item in questions if item["status"] == "Incomplete"]
    unable = [item for item in questions if item["status"] == "Unable to Evaluate"]
    ungradable = [*incomplete, *unable]
    covered_strengths = _unique_strings(
        point
        for item in questions
        for point in item["evidence"]["correctly_mentioned"]
    )
    round_analysis = _interview_round_analysis(raw_turns, questions)
    score_breakdown = _interview_score_breakdown(raw_turns)
    status = "sufficient" if gradable else ("no_candidate_evidence" if no_candidate_evidence else "insufficient_evidence")
    summary = f"{len(answered)} of {len(questions)} questions answered; {len(fully)} fully answered, {len(partial)} partially answered, {len(not_answered)} not answered."
    return {
        "version": "evidence-report-v1",
        "interview_id": interview_id,
        "report_type": "behavioral",
        "profile_type": profile_type,
        "summary": summary,
        "overall_score": overall_score,
        "score_breakdown": score_breakdown,
        "dimension_scores": {item["key"]: item["score"] for item in score_breakdown},
        "counts": {
            "questions_asked": len(questions),
            "questions_answered": len(answered),
            "questions_fully_answered": len(fully),
            "questions_partially_answered": len(partial),
            "questions_not_answered": len(not_answered),
            "questions_unable_to_evaluate": len(unable),
        },
        "evidence_status": {
            "status": status,
            "candidate_question_count": len(questions),
            "candidate_answered_count": len(answered),
            "reason": "Scores use persisted question responses and append-only evaluator evidence.",
        },
        "evidence_summary": {
            "turns_scored": len(gradable),
            "turns_with_evidence": sum(1 for item in questions if item["what_was_good"] or item["what_reduced_score"]),
            "insufficient_evidence_turns": len(ungradable),
        },
        "behavioral_metrics": {
            "average_response_time_seconds": _average(item.get("time_used_seconds") for item in questions),
            "question_count": len(questions),
            "voiced_duration_seconds": audio_output.get("voiced_duration_seconds"),
            "pause_duration_seconds": audio_output.get("pause_duration_seconds"),
        },
        "strengths": covered_strengths[:8],
        "questions": questions,
        "per_turn_feedback": questions,
        "round_analysis": round_analysis,
        "timeline": _timeline_from_turns(raw_turns),
        "self_review_summary": _self_review_summary(self_review_output),
        "candidate_visible_self_review": _self_review_summary(self_review_output),
        "report_state": "ready" if overall_score is not None else "ungradable",
        "ai_enhanced": False,
        "ai_provider_policy": "disabled_for_candidate_report",
        "ai_fallback_reason": None,
    }


def _timeline_from_turns(turns: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    timeline: List[Dict[str, Any]] = []
    for index, turn in enumerate(turns, start=1):
        timestamp = turn.get("created_at") or turn.get("answered_at")
        if timestamp:
            timeline.append({
                "at": _iso(timestamp),
                "event": "Answer recorded",
                "detail": f"Question {index}",
                "response_id": turn.get("response_id"),
            })
    return timeline


def _technical_failure_counts(item: Dict[str, Any]) -> Dict[str, int]:
    result = _as_dict(item.get("result_json") or item.get("validation"))
    counts = Counter()
    for case in _as_list(result.get("cases")):
        if not isinstance(case, dict):
            continue
        verdict = _text(case.get("verdict") or case.get("status") or case.get("result")).lower()
        if not verdict:
            continue
        if "compile" in verdict:
            counts["compile"] += 1
        elif "runtime" in verdict or "error" in verdict or "timeout" in verdict or "tle" in verdict:
            counts["runtime"] += 1
        elif "pass" not in verdict and "accept" not in verdict:
            counts["wrong_answer"] += 1
    return dict(counts)


def _technical_title(item: Dict[str, Any], index: int) -> str:
    metadata = _as_dict(item.get("metadata") or item.get("round_metadata"))
    title = _text(item.get("title") or metadata.get("title") or metadata.get("problem_title"))
    if title:
        return title
    prompt = _text(item.get("prompt"))
    return prompt.splitlines()[0][:120] if prompt else f"Problem {index + 1}"


def _technical_rows(output: Dict[str, Any]) -> List[Dict[str, Any]]:
    matrix = [item for item in _as_list(output.get("test_matrix")) if isinstance(item, dict)]
    if matrix:
        return matrix
    rows: List[Dict[str, Any]] = []
    by_round: Dict[str, Dict[str, Any]] = {}
    for item in _as_list(output.get("submissions")):
        if isinstance(item, dict):
            by_round.setdefault(_text(item.get("round_id")), item)
    for item in _as_list(output.get("run_events")):
        if isinstance(item, dict):
            key = _text(item.get("round_id"))
            by_round.setdefault(key, {**item, "evidence_state": "run_only"})
    for item in _as_list(output.get("drafts")):
        if isinstance(item, dict):
            key = _text(item.get("round_id"))
            by_round.setdefault(key, {**item, "evidence_state": "draft_only"})
    round_catalog = [item for item in _as_list(output.get("rounds")) if isinstance(item, dict)]
    if round_catalog:
        seen: set[str] = set()
        for round_item in round_catalog:
            key = _text(round_item.get("round_id"))
            if key in by_round:
                rows.append(by_round[key])
            else:
                rows.append({**round_item, "evidence_state": "no_evidence"})
            seen.add(key)
        rows.extend(item for key, item in by_round.items() if key not in seen)
    else:
        rows.extend(by_round.values())
    return rows


def _technical_status(item: Dict[str, Any], total_tests: int) -> str:
    state = _text(item.get("evidence_state")).lower()
    if state in {"no_evidence", "no_candidate_evidence"}:
        return "Not Attempted"
    if state in {"unable_to_evaluate", "evaluation_failed"}:
        return "Unable to Evaluate"
    if state in {"run_only", "draft_only", "insufficient_evidence"}:
        return "Incomplete"
    if state == "assessed_response":
        return "Completed" if _number(item.get("score")) is not None else "Unable to Evaluate"
    if item.get("submission_id") or state == "final_submission":
        if total_tests == 0 and _text(item.get("status")).lower() in {"executor_unavailable", "failed", "error"}:
            return "Unable to Evaluate"
        return "Submitted"
    if item.get("run_id") or item.get("snapshot_id"):
        return "Incomplete"
    return "Not Attempted"


def _technical_problem(item: Dict[str, Any], index: int, problem_count: int, activity_events: List[Dict[str, Any]]) -> Dict[str, Any]:
    visible_passed = int(item.get("visible_passed") or 0)
    visible_total = int(item.get("visible_total") or 0)
    hidden_passed = int(item.get("hidden_passed") or 0)
    hidden_total = int(item.get("hidden_total") or 0)
    total_tests = visible_total + hidden_total
    passed_tests = visible_passed + hidden_passed
    status = _technical_status(item, total_tests)
    raw_score = _number(item.get("score"))
    if status == "Submitted":
        score = _rounded(item.get("final_pass_rate"), 1)
        if score is None and total_tests:
            score = round((passed_tests / total_tests) * 100, 1)
    elif status == "Completed":
        score = raw_score
    elif status == "Not Attempted":
        score = 0.0
    elif status == "Incomplete":
        score = raw_score if raw_score is not None else 0.0
    else:
        score = None
    max_points = 50.0
    score_points = round((score or 0.0) * max_points / 100.0, 1) if score is not None else None
    failure_counts = _technical_failure_counts(item)
    failed_tests = max(0, total_tests - passed_tests)
    if status == "Not Attempted":
        what_happened = "The problem was opened, but no executable solution, test run, draft, or submitted code was recorded."
    elif status == "Incomplete":
        if _text(item.get("evidence_state")).lower() == "draft_only":
            what_happened = "A saved code draft was recorded, but no test run or final submission was recorded."
        else:
            what_happened = f"{int(item.get('run_count') or 0)} test run(s) were recorded, but no final submission was recorded."
    elif status == "Unable to Evaluate":
        what_happened = "Candidate evidence was recorded, but the required evaluator or execution result was unavailable."
    elif status == "Completed":
        what_happened = "A written technical response was recorded and evaluated."
    else:
        what_happened = f"A final submission was recorded and passed {passed_tests} of {total_tests} evaluated tests."
    main_issue: str | None = None
    if status == "Submitted" and failed_tests:
        pieces = []
        for key, label in (("wrong_answer", "wrong-answer"), ("runtime", "runtime"), ("compile", "compile")):
            if failure_counts.get(key):
                pieces.append(f"{failure_counts[key]} {label}")
        detail = f" ({', '.join(pieces)})" if pieces else ""
        main_issue = f"The final submission failed {failed_tests} evaluated test(s){detail}."
    elif status == "Incomplete":
        main_issue = "No final submission was recorded, so final correctness could not be determined."
    elif status == "Unable to Evaluate":
        main_issue = "The available evidence does not contain a usable evaluator or execution result."
    elif status == "Completed":
        parts = _evidence_parts(item)
        reduced = _unique_strings([
            *[f"Missing: {_text(value)}" for value in parts["missed"]],
            *[f"Incorrect: {_text(value)}" for value in parts["incorrect"]],
        ])
        main_issue = "; ".join(reduced) if reduced else None
    test_evidence: Dict[str, Any] = {
        "visible": {"passed": visible_passed, "total": visible_total} if visible_total else None,
        "hidden": {"passed": hidden_passed, "total": hidden_total} if hidden_total else None,
        "final_run": {"passed": passed_tests, "total": total_tests} if total_tests else None,
        "submission": bool(item.get("submission_id")),
    }
    if failure_counts.get("compile"):
        test_evidence["compile"] = {"failed": failure_counts["compile"]}
    if failure_counts.get("runtime"):
        test_evidence["runtime"] = {"failed": failure_counts["runtime"]}
    complexity = item.get("observed_complexity") or item.get("complexity")
    if not isinstance(complexity, dict):
        complexity = {}
    events = [event for event in activity_events if _text(event.get("round_id")) == _text(item.get("round_id"))]
    activity = [
        {
            "at": _iso(event.get("created_at") or event.get("at")),
            "event": _text(event.get("event") or event.get("event_type") or "Activity").replace("_", " ").title(),
            "detail": _text(event.get("detail") or event.get("label")),
        }
        for event in events
        if event.get("created_at") or event.get("at")
    ]
    return {
        "index": index,
        "round_id": item.get("round_id"),
        "title": _technical_title(item, index - 1),
        "language": _text(item.get("language")),
        "status": status,
        "score": score,
        "score_points": score_points,
        "max_points": max_points,
        "time_used_seconds": item.get("time_used_seconds") or item.get("elapsed_seconds"),
        "time_allowed_seconds": item.get("time_allowed_seconds") or item.get("duration_seconds"),
        "runs": int(item.get("run_count") or 0),
        "submission_count": 1 if item.get("submission_id") else 0,
        "visible_passed": visible_passed,
        "visible_total": visible_total,
        "hidden_passed": hidden_passed,
        "hidden_total": hidden_total,
        "final_submission": bool(item.get("submission_id")),
        "prompt": _text(item.get("prompt")),
        "source_code": _text(item.get("source_code") or item.get("source_excerpt")),
        "source_label": "Submitted code" if item.get("submission_id") else "Last saved code",
        "what_happened": what_happened,
        "main_issue": main_issue,
        "test_evidence": test_evidence,
        "final_run": test_evidence.get("final_run"),
        "complexity": {key: _text(value) for key, value in complexity.items() if _text(value)},
        "activity": activity,
        "evidence_state": _text(item.get("evidence_state")),
        "evidence_ids": _unique_strings([item.get("submission_id"), item.get("run_id"), item.get("snapshot_id")]),
    }


def _technical_round_analysis(problems: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    patterns: List[Dict[str, Any]] = []
    incomplete = [item for item in problems if item["status"] == "Incomplete"]
    not_attempted = [item for item in problems if item["status"] == "Not Attempted"]
    submitted_failures = [item for item in problems if item["status"] == "Submitted" and item["main_issue"]]
    if not_attempted:
        patterns.append({
            "pattern": "Problems not attempted",
            "evidence_count": len(not_attempted),
            "detail": f"{len(not_attempted)} of {len(problems)} prepared problems had no executable solution, run, draft, or submission evidence.",
            "evidence_ids": [item.get("round_id") for item in not_attempted if item.get("round_id")],
        })
    if incomplete:
        patterns.append({
            "pattern": "No final submission",
            "evidence_count": len(incomplete),
            "detail": f"{len(incomplete)} of {len(problems)} problems had a draft or run but no final submission.",
            "evidence_ids": [item.get("round_id") for item in incomplete if item.get("round_id")],
        })
    if submitted_failures:
        patterns.append({
            "pattern": "Final test failures",
            "evidence_count": len(submitted_failures),
            "detail": f"{len(submitted_failures)} submitted problem(s) recorded at least one failed evaluated test.",
            "evidence_ids": [item.get("round_id") for item in submitted_failures if item.get("round_id")],
        })
    return patterns


def build_async_technical_report(
    *,
    interview_id: str,
    profile_type: str,
    nlp_output: Dict[str, Any],
    technical_output: Dict[str, Any],
    self_review_output: Dict[str, Any],
) -> Dict[str, Any]:
    rows = _technical_rows(technical_output)
    activity_events = [item for item in _as_list(technical_output.get("activity_events")) if isinstance(item, dict)]
    problems = [
        _technical_problem(item, index + 1, len(rows), activity_events)
        for index, item in enumerate(rows)
    ]
    if not problems and int(technical_output.get("round_count") or 0):
        problems = [
            _technical_problem({"round_id": f"round-{index + 1}", "evidence_state": "no_evidence"}, index + 1, int(technical_output["round_count"]), [])
            for index in range(int(technical_output["round_count"]))
        ]
    max_points = sum(item["max_points"] for item in problems if item["status"] != "Unable to Evaluate")
    earned_points = sum(item["score_points"] or 0.0 for item in problems if item["status"] != "Unable to Evaluate")
    attempted = [item for item in problems if item["status"] != "Not Attempted"]
    submitted = [item for item in problems if item["final_submission"]]
    assessed_responses = [item for item in problems if item["status"] == "Completed" and item["score"] is not None]
    overall_score = (
        round((earned_points / max_points) * 100, 1)
        if max_points and (submitted or assessed_responses)
        else None
    )
    solved = [
        item for item in submitted
        if item["final_run"] and item["final_run"]["total"] > 0 and item["final_run"]["passed"] == item["final_run"]["total"]
    ]
    visible_passed = sum(item["visible_passed"] for item in submitted)
    visible_total = sum(item["visible_total"] for item in submitted)
    hidden_passed = sum(item["hidden_passed"] for item in submitted)
    hidden_total = sum(item["hidden_total"] for item in submitted)
    state = (
        "insufficient_evidence"
        if problems and all(item["status"] == "Unable to Evaluate" for item in problems)
        else "sufficient"
        if submitted or any(item["status"] == "Completed" for item in problems)
        else "draft_or_run_only"
        if attempted
        else "no_candidate_evidence"
    )
    summary = f"{len(attempted)} of {len(problems)} problems attempted; {len(submitted)} submitted, {len(solved)} solved."
    return {
        "version": "evidence-report-v1",
        "interview_id": interview_id,
        "report_type": "technical",
        "profile_type": profile_type,
        "summary": summary,
        "overall_score": overall_score,
        "score_breakdown": [],
        "dimension_scores": {"correctness": overall_score} if submitted else {},
        "counts": {
            "problems_attempted": len(attempted),
            "problems_total": len(problems),
            "problems_submitted": len(submitted),
            "tests_passed": visible_passed + hidden_passed,
            "tests_total": visible_total + hidden_total,
            "visible_tests_passed": visible_passed,
            "visible_tests_total": visible_total,
            "hidden_tests_passed": hidden_passed,
            "hidden_tests_total": hidden_total,
            "problems_solved": len(solved),
        },
        "evidence_status": {
            "status": state,
            "round_count": len(problems),
            "submission_count": len(submitted),
            "run_count": int(technical_output.get("run_event_count") or 0),
            "draft_count": int(technical_output.get("draft_count") or 0),
            "reason": "Scores use persisted final submissions, deterministic test results, and append-only technical assessments.",
        },
        "evidence_summary": {
            "round_count": len(problems),
            "submission_count": len(submitted),
            "run_count": int(technical_output.get("run_event_count") or 0),
            "draft_count": int(technical_output.get("draft_count") or 0),
        },
        "technical_process": {
            "round_count": len(problems),
            "submission_count": len(submitted),
            "run_count": int(technical_output.get("run_event_count") or 0),
            "draft_count": int(technical_output.get("draft_count") or 0),
            "time_used_seconds": technical_output.get("duration_used_seconds"),
            "time_allowed_seconds": technical_output.get("duration_allowed_seconds"),
        },
        "duration_seconds": technical_output.get("duration_used_seconds"),
        "time_used_seconds": technical_output.get("duration_used_seconds"),
        "time_allowed_seconds": technical_output.get("duration_allowed_seconds"),
        "technical": {
            "problems": problems,
            "round_analysis": _technical_round_analysis(problems),
            "time_used_seconds": technical_output.get("duration_used_seconds"),
            "time_allowed_seconds": technical_output.get("duration_allowed_seconds"),
        },
        "test_matrix": problems,
        "problems": problems,
        "round_analysis": _technical_round_analysis(problems),
        "timeline": activity_events,
        "strengths": [],
        "self_review_summary": _self_review_summary(self_review_output),
        "candidate_visible_self_review": _self_review_summary(self_review_output),
        "report_state": "ready",
        "ai_enhanced": False,
        "ai_provider_policy": "disabled_for_candidate_report",
        "ai_fallback_reason": None,
    }
