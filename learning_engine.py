# ============================================================================
# MODULE: learning_engine.py
# PURPOSE: Skill evidence ingestion + exercise generation + attempt grading +
#          anti-cheat/malpractice ingestion + learning snapshot for dashboard.
# STRUCTURE:
#   - STRICT/SEVERE event type sets + PASS_SCORE constant (lines 29-32)
#                                          << Phase 3: move thresholds to app_config
#   - Helpers: _json_load, _clip, _normalize_score (lines 35-55)
#   - ingest_interview_evidence(...) — extract skill evidence from a turn
#   - submit_exercise_attempt(...) — grade an attempt, update mastery
#   - build_learning_snapshot(...) — dashboard payload
#   - build_error_signature(...) — technical_mode mistake clustering
#   - ingest_technical_run(...) — write TechnicalRunEvents row + cluster
# ENDPOINTS: none (called from interview.py, workspace_api.py, technical_mode.py)
# DEPENDS ON: database, llm_router, prompt_security
# CONSUMED BY: interview.py, workspace_api.py, technical_mode.py
# DATA TABLES: LearnerSkillStates, SkillEvidenceEvents, ProjectKnowledgeGaps,
#              GeneratedExercises, ExerciseAttempts, MalpracticeEvents,
#              TechnicalRunEvents, TechnicalMistakeClusters
#              (Phase 2: MalpracticeEvents -> InterviewEvents)
#              (Phase 4: exercise prompts move to prompt_templates.py + llm_cache)
# ============================================================================

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from database import async_execute, get_db_connection, return_db_connection
from improve_scoring import (
    calculate_activity_score,
    calculate_mission_progress,
    calculate_readiness,
    calculate_skill_score,
    mastery_status_for_checkpoint,
    result_status_for_score,
)
from llm_router import complete_json_async
from mission_priority import calculate_mission_priority
from prompt_security import SYSTEM_DATA_BOUNDARY, data_block
from security_utils import decrypt_data, encrypt_data


logger = logging.getLogger("learning_engine")
SEVERE_EVENT_TYPES = {"tab_switch", "fullscreen_exit", "paste", "paste_blocked"}
PASS_SCORE = 75
EVIDENCE_EVALUATOR_VERSION = "learning-evidence-v1"


def _json_load(value: Any, fallback: Any) -> Any:
    if value is None:
        return fallback
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except Exception:
        return fallback


def _clip(value: float, low: float = 0, high: float = 100) -> float:
    return round(max(low, min(high, value)), 1)


def _normalize_score(value: Any) -> float:
    try:
        numeric = float(value)
    except Exception:
        return 0.0
    if 0 < numeric <= 1:
        numeric *= 100
    return _clip(numeric)


def _slug(value: str, fallback: str = "general") -> str:
    text = re.sub(r"[^a-z0-9+#.-]+", "-", (value or "").lower()).strip("-")
    return (text or fallback)[:100]


def _label_from_key(skill_key: str) -> str:
    text = skill_key.split(":", 1)[-1]
    if text.lower() == "dsa":
        return "DSA"
    return text.replace("-", " ").replace("_", " ").title()


def _is_technical_skill_key(skill_key: str) -> bool:
    return str(skill_key or "").startswith(("technical:", "algorithm:", "debugging:"))


def _bounded(value: str, limit: int = 1200) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].strip()


def _exercise_text(*parts: Any) -> str:
    return " ".join(str(part or "").lower() for part in parts)


def _drill_category(skill_key: Optional[str], exercise_type: Optional[str], prompt: Optional[Dict[str, Any]] = None) -> str:
    text = _exercise_text(skill_key, exercise_type, (prompt or {}).get("prompt"), (prompt or {}).get("question"))
    if any(token in text for token in ("technical", "algorithm", "bug", "code", "edge", "complexity", "debug", "syntax", "runtime", "dsa")):
        return "coding"
    if any(token in text for token in ("resume", "project", "ownership", "proof", "impact", "keyword")):
        return "resume"
    return "interview"


def _canonical_drill(skill_key: Optional[str], exercise_type: Optional[str], prompt: Optional[Dict[str, Any]] = None) -> str:
    text = _exercise_text(skill_key, exercise_type, (prompt or {}).get("title"), (prompt or {}).get("prompt"), (prompt or {}).get("question"))
    category = _drill_category(skill_key, exercise_type, prompt)
    if category == "coding":
        if "complex" in text:
            return "Complexity Explanation Drill"
        if any(token in text for token in ("debug", "bug", "runtime", "syntax", "failure", "repair")):
            return "Debugging Discipline Drill"
        if any(token in text for token in ("edge", "boundary", "empty", "duplicate", "negative")):
            return "Edge Case Drill"
        if any(token in text for token in ("dry", "trace", "walk")):
            return "Dry Run Drill"
        if "review" in text or "submit" in text:
            return "Final Review Drill"
        if any(token in text for token in ("breakdown", "understanding")):
            return "Problem Breakdown Drill"
        return "Topic Practice Set"
    if category == "resume":
        if "bullet" in text:
            return "Resume Bullet Rewrite"
        if any(token in text for token in ("impact", "metric", "result")):
            return "Impact Writing Drill"
        if any(token in text for token in ("keyword", "ats", "role")):
            return "Keyword Fix Task"
        if "project" in text or "proof" in text:
            return "Project Defense Drill"
        return "Resume-to-Interview Drill"
    if "proof" in text or "evidence" in text or "metric" in text:
        return "Proof of Work Drill"
    if "project" in text:
        return "Project Explanation Drill"
    if "follow" in text or "chain" in text:
        return "Follow-up Pressure Drill"
    if any(token in text for token in ("concise", "short", "rambling")):
        return "Concise Answer Drill"
    if any(token in text for token in ("communication", "filler", "clarity")):
        return "Communication Drill"
    if any(token in text for token in ("honesty", "bluff", "depth")):
        return "Honesty & Depth Drill"
    return "Answer Structure Drill"


def _source_label(skill_key: Optional[str], exercise_type: Optional[str], prompt: Optional[Dict[str, Any]] = None, evidence: Optional[List[Dict[str, Any]]] = None) -> str:
    category = _drill_category(skill_key, exercise_type, prompt)
    text = _exercise_text(skill_key, exercise_type, json.dumps(evidence or []))
    if category == "coding":
        return "Coding reports"
    if category == "resume":
        return "Interview + Resume" if "interview" in text or (prompt or {}).get("question") else "Resume review"
    return "Interview reports"


def _evidence_summary(evidence: Optional[List[Dict[str, Any]]], fallback: str) -> str:
    items = evidence if isinstance(evidence, list) else []
    for item in items:
        if not isinstance(item, dict):
            continue
        for key in ("summary", "repair_action", "why_bad", "gap_summary", "quote", "question", "mistake"):
            value = item.get(key)
            if isinstance(value, dict):
                value = value.get("diagnosis") or value.get("type")
            readable = _readable_evidence_value(value)
            if readable:
                return _bounded(readable, 240)
    return fallback


def _readable_evidence_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        for key in ("summary", "repair_action", "diagnosis", "type", "question"):
            readable = _readable_evidence_value(value.get(key))
            if readable:
                return readable
        return ""
    text = str(value).strip()
    if not text:
        return ""
    if text.startswith("[") or text.startswith("{"):
        try:
            parsed = json.loads(text)
        except Exception:
            if '"verdict"' in text or "'verdict'" in text:
                return "Coding report captured test-case evidence; review the failing edge case before retrying."
            return text
        case_summary = _case_list_summary(parsed)
        if case_summary:
            return case_summary
        if isinstance(parsed, list):
            for item in parsed:
                readable = _readable_evidence_value(item)
                if readable:
                    return readable
        if isinstance(parsed, dict):
            return _readable_evidence_value(parsed)
    return text


def _case_list_summary(value: Any) -> str:
    if not isinstance(value, list) or not value:
        return ""
    cases = [case for case in value if isinstance(case, dict) and "passed" in case]
    if not cases:
        return ""
    failed = [case for case in cases if not case.get("passed")]
    hidden_failed = sum(1 for case in failed if case.get("hidden"))
    visible_failed = len(failed) - hidden_failed
    passed = len(cases) - len(failed)
    if not failed:
        return f"All {len(cases)} captured test case(s) passed."
    if visible_failed:
        return f"{visible_failed} visible test(s) and {hidden_failed} hidden test(s) failed; start with the first visible mismatch."
    return f"{hidden_failed} hidden test(s) failed while {passed}/{len(cases)} captured cases passed."


def _drill_metadata(exercise: Dict[str, Any]) -> Dict[str, Any]:
    prompt = exercise.get("prompt") if isinstance(exercise.get("prompt"), dict) else {}
    evidence = exercise.get("source_evidence") if isinstance(exercise.get("source_evidence"), list) else []
    skill_label = _label_from_key(str(exercise.get("skill_key") or exercise.get("exercise_type") or "interview answer"))
    category = _drill_category(exercise.get("skill_key"), exercise.get("exercise_type"), prompt)
    canonical = _canonical_drill(exercise.get("skill_key"), exercise.get("exercise_type"), prompt)
    source = _source_label(exercise.get("skill_key"), exercise.get("exercise_type"), prompt, evidence)
    task = prompt.get("prompt") or prompt.get("question") or "Complete the assigned drill."
    mistake = prompt.get("mistake")
    if isinstance(mistake, dict):
        mistake = mistake.get("diagnosis") or mistake.get("type")
    mistake_text = str(mistake or prompt.get("error_signature") or f"Weakness in {skill_label}.")
    evidence_text = _evidence_summary(evidence, f"Detected from {source.lower()}.")
    return {
        "canonical_drill": canonical,
        "category": category,
        "goal": f"Fix {skill_label} with a focused {canonical.lower()}.",
        "mistake_found": _bounded(mistake_text, 260),
        "evidence_from_report": evidence_text,
        "user_task": _bounded(str(task), 420),
        "found_from": source,
        "retest_nav": "coding" if category == "coding" else "interview",
    }


def _row_get(row: Any, index: int, default: Any = None) -> Any:
    try:
        return row[index]
    except Exception:
        return default


def _timestamp(value: Any) -> Optional[str]:
    return value.isoformat() if hasattr(value, "isoformat") else None


def _safe_json(value: Any) -> str:
    return json.dumps(value or {}, default=str)


def _encrypted_text_bytes(value: Any) -> Optional[bytes]:
    text = str(value or "")
    return encrypt_data(text).encode("utf-8") if text else None


def _encrypted_json_bytes(value: Any) -> bytes:
    return encrypt_data(_safe_json(value)).encode("utf-8")


def _sensitive_json_marker(value: Any) -> str:
    if isinstance(value, dict):
        field_count = len(value)
    elif isinstance(value, list):
        field_count = len(value)
    else:
        field_count = 1 if value not in (None, "") else 0
    return _safe_json({"encrypted": True, "field_count": field_count})


def _feedback_storage_marker(value: Any) -> str:
    feedback = value if isinstance(value, dict) else {}
    mistake = feedback.get("mistake") if isinstance(feedback.get("mistake"), dict) else {}
    return _safe_json({
        "encrypted": True,
        "result_status": feedback.get("result_status"),
        "condition_summary": feedback.get("condition_summary") or {},
        "mistake": {"type": mistake.get("type")},
        "has_progress_signal": bool(feedback.get("progress_signal")),
    })


def _decrypt_sensitive_json(encrypted: Any, legacy: Any = None) -> Dict[str, Any]:
    if encrypted is not None:
        if isinstance(encrypted, memoryview):
            encrypted = encrypted.tobytes()
        if isinstance(encrypted, (bytes, bytearray)):
            encrypted = bytes(encrypted).decode("utf-8")
        decrypted = decrypt_data(str(encrypted))
        parsed = _json_load(decrypted, {})
        return parsed if isinstance(parsed, dict) else {}
    parsed = _json_load(legacy, {})
    if isinstance(parsed, dict) and not parsed.get("encrypted"):
        return parsed
    return {}


def _mission_title(skill_key: str, evidence_text: str) -> str:
    text = f"{skill_key} {evidence_text}".lower()
    if str(skill_key or "").startswith("communication:"):
        return f"Strengthen {_label_from_key(skill_key)}"
    if "interai" in text:
        return "Explain InterAI Convincingly"
    if "technical" in text or "code" in text:
        return "Improve Coding Problem Solving"
    if "resume" in text:
        return "Defend Resume Claims"
    if "project" in text:
        return "Explain Projects Clearly"
    return "Improve Communication and Conciseness"


def _phase_one_activity_definitions(skill_label: str, evidence_text: str, mode: str = "mock") -> List[Dict[str, Any]]:
    weakness = _bounded(evidence_text or f"Improve {skill_label}.", 360)
    if mode == "technical":
        return [
            {
                "activity_type": "baseline",
                "title": "Previous Round Analysed",
                "description": weakness,
                "estimated_minutes": 1,
                "expected_result": "The technical weakness was selected from attempted code, runs, submissions, hints, and test results.",
                "availability_status": "unlocked",
                "attempt_status": "submitted",
                "result_status": "passed",
                "mastery_status": "practising",
            },
            {
                "activity_type": "rewrite_answer",
                "title": "Explain What Went Wrong",
                "description": "Name the approach you used, why it failed or was inefficient, and the better pattern.",
                "estimated_minutes": 4,
                "expected_result": "Separate approach choice, implementation, complexity, and edge-case failures.",
                "prompt": {
                    "title": "Diagnose the failed attempt",
                    "question": f"Using the previous evidence, explain the main issue in {skill_label}.",
                    "weak_answer": weakness,
                    "required_elements": ["user_approach", "failure_reason", "better_approach", "complexity"],
                    "pass_conditions": [
                        {"id": "technical_decision", "label": "Names the approach or decision used", "weight": 1},
                        {"id": "decision_and_result", "label": "Explains why it failed or was inefficient", "weight": 1},
                        {"id": "result", "label": "States the better expected result", "weight": 1},
                    ],
                },
            },
            {
                "activity_type": "guided_spoken_response",
                "title": "Retry Plan Before Coding",
                "description": "Plan the same question again without seeing a full solution.",
                "estimated_minutes": 4,
                "expected_result": "State the pattern, data structure, complexity, and edge cases before coding.",
                "prompt": {
                    "title": "State your retry plan",
                    "question": f"Before coding, explain how you would retry the same {skill_label} problem.",
                    "input_type": "voice_or_text",
                    "timer_seconds": 90,
                    "pass_conditions": [
                        {"id": "states_problem_early", "label": "Starts with the required task or invariant", "weight": 1},
                        {"id": "technical_decision", "label": "Names the useful concept or data structure", "weight": 1},
                        {"id": "decision_and_result", "label": "Compares complexity with the previous attempt", "weight": 1},
                    ],
                },
            },
            {
                "activity_type": "rewrite_answer",
                "title": "Edge-Case Checklist",
                "description": "Write the checks that would catch the previous mistake before submitting.",
                "estimated_minutes": 4,
                "expected_result": "List concrete boundary, duplicate, empty, large-input, or hidden-test risks that apply to this attempted problem.",
                "prompt": {
                    "title": "Write your edge-case checklist",
                    "question": f"List the edge cases you would test before submitting a retry for {skill_label}.",
                    "required_elements": ["boundary", "failing_case", "expected_result"],
                    "pass_conditions": [
                        {"id": "technical_decision", "label": "Names a specific case, not a generic reminder", "weight": 1},
                        {"id": "result", "label": "States the expected output or invariant", "weight": 1},
                    ],
                },
            },
            {
                "activity_type": "unseen_checkpoint",
                "title": "Transfer Checkpoint",
                "description": "Verify the weakness on a related problem before asking for the next full Technical Round.",
                "estimated_minutes": 6,
                "expected_result": "Recognise a related pattern without high hint dependency.",
                "is_checkpoint": True,
                "prompt": {
                    "title": "Related-pattern checkpoint",
                    "question": f"Explain how you would recognise and solve a related {skill_label} problem without hints.",
                    "timer_seconds": 120,
                    "hide_hints": True,
                    "pass_conditions": [
                        {"id": "states_problem_early", "label": "Identifies the required pattern from the prompt", "weight": 1},
                        {"id": "technical_decision", "label": "Chooses the concept or data structure", "weight": 1},
                        {"id": "decision_and_result", "label": "Gives expected complexity and one edge case", "weight": 1},
                    ],
                },
            },
        ]

    return [
        {
            "activity_type": "baseline",
            "title": "Baseline Analysed",
            "description": weakness,
            "estimated_minutes": 1,
            "expected_result": "The weak answer pattern has been identified from stored interview evidence.",
            "availability_status": "unlocked",
            "attempt_status": "submitted",
            "result_status": "passed",
            "mastery_status": "practising",
        },
        {
            "activity_type": "compare_answers",
            "title": "Learn the Stronger Answer Shape",
            "description": "Learn the four-part repair, then identify why it works before practising it.",
            "estimated_minutes": 3,
            "expected_result": "Identify why a direct, structured answer is stronger.",
            "prompt": {
                "title": "Which answer is stronger?",
                "question": f"Which answer better fixes this issue: {skill_label}?",
                "learning_guide": [
                    {"label": "Answer", "text": "Start with the direct answer in one sentence."},
                    {"label": "Own", "text": "State exactly what you personally chose, built, fixed, or measured."},
                    {"label": "Prove", "text": "Add one project detail, constraint, metric, or concrete example."},
                    {"label": "Reflect", "text": "Close with the result, trade-off, limitation, or what you would change."},
                ],
                "answers": [
                    {"id": "a", "label": "Answer A", "text": "I know the topic and have used it in projects, so I can explain it if needed."},
                    {"id": "b", "label": "Answer B", "text": "First I define the concept, then explain how it works, give one example, and state where I used it."},
                ],
                "correct_option": "b",
                "pass_conditions": [
                    {"id": "choose_problem_first", "label": "Select the structured answer", "weight": 2},
                    {"id": "explain_reason", "label": "Explain why structure and an example make it stronger", "weight": 1},
                ],
            },
        },
        {
            "activity_type": "arrange_blocks",
            "title": "Arrange the Answer",
            "description": "Put the answer blocks in interviewer-friendly order.",
            "estimated_minutes": 4,
            "expected_result": "Order the answer as direct point, context, working, example, result.",
            "prompt": {
                "title": "Arrange the answer blocks",
                "question": f"Arrange these blocks to answer a weak {skill_label} question clearly.",
                "blocks": [
                    {"id": "solution", "text": "Explain how the idea works or what happens step by step."},
                    {"id": "role", "text": "Give one example, project detail, or decision you personally handled."},
                    {"id": "problem", "text": "Start with the direct answer to the question."},
                    {"id": "result", "text": "Close with the use case, result, trade-off, or limitation."},
                    {"id": "user", "text": "Connect the answer to the specific interview context."},
                ],
                "correct_order": ["problem", "user", "solution", "role", "result"],
                "pass_conditions": [
                    {"id": "problem_first", "label": "Start with the direct answer", "weight": 1},
                    {"id": "all_blocks_ordered", "label": "Use all blocks in the expected order", "weight": 2},
                    {"id": "role_before_result", "label": "Place example or evidence before result", "weight": 1},
                ],
            },
        },
        {
            "activity_type": "rewrite_answer",
            "title": "Retry the Weak Answer",
            "description": "Rewrite the previous weak answer using the correct structure.",
            "estimated_minutes": 4,
            "expected_result": "Answer directly, explain how it works, add one example, and close with a use case or result.",
            "prompt": {
                "title": "Rewrite the weak answer",
                "question": f"Rewrite your answer for {skill_label}.",
                "weak_answer": weakness,
                "required_elements": ["direct_answer", "how_it_works", "example", "result"],
                "pass_conditions": [
                    {"id": "states_problem_early", "label": "Starts with a direct answer", "weight": 1},
                    {"id": "technical_decision", "label": "Explains how or why it works", "weight": 1},
                    {"id": "result", "label": "Includes an example, evidence, use case, or result", "weight": 1},
                ],
            },
        },
        {
            "activity_type": "guided_spoken_response",
            "title": "Open Mic: Explain It Aloud",
            "description": "Speak the repaired answer out loud, review the transcript, and retry without consuming interview credits.",
            "estimated_minutes": 4,
            "expected_result": "Give a short, ordered answer with a direct point, example, and result.",
            "prompt": {
                "title": "Open-mic answer practice",
                "question": f"Answer the same weak {skill_label} question again.",
                "input_type": "voice_or_text",
                "timer_seconds": 60,
                "pass_conditions": [
                    {"id": "states_problem_early", "label": "Direct answer appears early", "weight": 1},
                    {"id": "technical_decision", "label": "Explains the mechanism or reasoning", "weight": 1},
                    {"id": "decision_and_result", "label": "Includes one example and one result or trade-off", "weight": 1},
                ],
            },
        },
        {
            "activity_type": "unseen_checkpoint",
            "title": "Transfer Checkpoint",
            "description": "Answer a related question without hints to verify the skill.",
            "estimated_minutes": 5,
            "expected_result": "Pass a related answer without visible structure or model answer.",
            "is_checkpoint": True,
            "prompt": {
                "title": "Unseen checkpoint",
                "question": f"Explain a related {skill_label} question using definition, working, example, and use case.",
                "timer_seconds": 60,
                "hide_hints": True,
                "pass_conditions": [
                    {"id": "states_problem_early", "label": "Starts with the definition or direct answer", "weight": 1},
                    {"id": "technical_decision", "label": "Explains how it works", "weight": 1},
                    {"id": "result", "label": "Adds example, use case, trade-off, or result", "weight": 1},
                ],
            },
        },
    ]


def _activity_words(value: str) -> List[str]:
    return re.findall(r"[a-z0-9+#.-]+", str(value or "").lower())


def _activity_has_decision_signal(value: str) -> bool:
    text = str(value or "").lower()
    return bool(
        re.search(
            r"\b(?:because|choose|chose|chosen|decide|decided|use|used|using|"
            r"approach|pattern|algorithm|data structure|hash ?map|array|tree|graph|"
            r"queue|stack|database|index|cache|api|service|pipeline|architecture|"
            r"trade-?off|constraint|alternative|complexity|latency|scale|cost)\b",
            text,
        )
    )


def _activity_has_result_signal(value: str) -> bool:
    text = str(value or "").lower()
    return bool(
        _contains_metric(text)
        or re.search(r"\bo\s*\([^)]+\)", text)
        or re.search(
            r"\b(?:result|outcome|impact|ship(?:ped)?|reduce[sd]?|improve[sd]?|"
            r"pass(?:ed)?|test(?:ed|s)?|verify|verified|expected|use case|example|"
            r"edge case|boundary|duplicate|empty input|trade-?off|limitation|"
            r"time|space|latency|users?)\b",
            text,
        )
    )


def _activity_starts_directly(value: str, prompt: Dict[str, Any]) -> bool:
    words = _activity_words(value)
    if len(words) < 6:
        return False
    opening = " ".join(words[:28])
    if re.match(r"^(?:well|so basically|basically|maybe|i think maybe|to be honest)\b", opening):
        return False

    question_words = {
        word
        for word in _activity_words(str(prompt.get("question") or prompt.get("prompt") or ""))
        if len(word) >= 5 and word not in {"which", "would", "using", "answer", "explain", "question", "related"}
    }
    if question_words.intersection(words[:28]):
        return True
    return bool(
        re.match(r"^(?:i|my|the|a|an|first)\b", opening)
        and (
            _activity_has_decision_signal(opening)
            or re.search(r"\b(?:define|means|solves|handles|starts|works|built|owned|implemented|designed)\b", opening)
        )
    )


def _condition_results_for_activity(prompt: Dict[str, Any], answer: str, payload: Dict[str, Any], activity_type: str) -> List[Dict[str, Any]]:
    text = (answer or payload.get("transcript") or payload.get("rewrite") or "").strip()
    lower = text.lower()
    conditions = prompt.get("pass_conditions") or []
    results: List[Dict[str, Any]] = []
    for condition in conditions:
        condition_id = str(condition.get("id") if isinstance(condition, dict) else condition)
        met = False
        evidence = ""
        if condition_id == "choose_problem_first":
            met = str(payload.get("selected_option") or "").lower() == str(prompt.get("correct_option") or "").lower()
            evidence = "Selected the problem-first answer." if met else "Selected the technology-first answer."
        elif condition_id == "explain_reason":
            reason = str(payload.get("reason") or answer or "")
            reason_text = reason.lower()
            met = len(_activity_words(reason)) >= 6 and bool(
                re.search(
                    r"\b(?:direct|clear|structure[sd]?|specific|example|evidence|context|"
                    r"relevant|concise|reason|result|trade-?off|ownership|stronger)\b",
                    reason_text,
                )
            )
            evidence = "A structural rationale was provided." if met else "The rationale did not explain why the answer shape is stronger."
        elif condition_id == "problem_first":
            order = payload.get("block_order") or []
            met = bool(order and order[0] == "problem")
            evidence = f"First block: {order[0] if order else 'none'}"
        elif condition_id == "all_blocks_ordered":
            met = list(payload.get("block_order") or []) == list(prompt.get("correct_order") or [])
            evidence = "Order matched expected structure." if met else "Order did not match expected structure."
        elif condition_id == "role_before_result":
            order = list(payload.get("block_order") or [])
            met = "role" in order and "result" in order and order.index("role") < order.index("result")
            evidence = "Role appears before result." if met else "Role/result order is unclear."
        elif condition_id == "owned_component":
            met = any(token in lower for token in ("component", "api", "backend", "frontend", "database", "pipeline", "service", "flow", "module"))
            evidence = "Owned component named." if met else "No concrete owned component found."
        elif condition_id == "personal_action" or condition_id == "personal_role":
            met = bool(re.search(r"\b(?:i|my|me|owned|designed|implemented|debugged|built)\b", lower))
            evidence = "Personal ownership language found." if met else "Personal ownership language is missing."
        elif condition_id == "technical_decision":
            met = _activity_has_decision_signal(text)
            evidence = "Technical decision or reason found." if met else "No decision reasoning found."
        elif condition_id == "result" or condition_id == "outcome":
            met = _activity_has_result_signal(text)
            evidence = "Outcome signal found." if met else "Outcome signal is missing."
        elif condition_id == "states_problem_early":
            met = _activity_starts_directly(text, prompt)
            evidence = "The response starts with a direct answer or approach." if met else "The direct answer or approach appears too late."
        elif condition_id == "decision_and_result":
            met = _activity_has_decision_signal(text) and _activity_has_result_signal(text)
            evidence = "Decision and result both found." if met else "Decision or result is missing."
        elif condition_id == "decision_reasoning":
            met = _activity_has_decision_signal(text)
            evidence = "Decision reasoning found." if met else "Decision reasoning is missing."
        else:
            met = bool(text and len(text.split()) >= 12)
            evidence = "Sufficient answer detail." if met else "Answer is too short."
        results.append({"id": condition_id, "met": met, "evidence": evidence})
    return results


def _deterministic_activity_result(prompt: Dict[str, Any], rubric: Dict[str, Any], answer: str, payload: Dict[str, Any], activity_type: str) -> Dict[str, Any]:
    expected = rubric.get("conditions") or prompt.get("pass_conditions") or rubric.get("checks") or []
    provided = _condition_results_for_activity(prompt, answer, payload, activity_type)
    result = calculate_activity_score(
        expected,
        provided,
    )
    failed = result["failed_conditions"]
    correction = failed[0] if failed else "Keep the same structure in the next variation."
    return {
        "score": result["score"],
        "mastery_passed": result["result_status"] in {"passed", "strong_pass"},
        "result_status": result["result_status"],
        "condition_results": result["condition_results"],
        "passed_conditions": result["passed_conditions"],
        "failed_conditions": result["failed_conditions"],
        "score_components": result["score_components"],
        "feedback": {
            "summary": f"{len(result['passed_conditions'])} of {len(result['condition_results'])} conditions met.",
            "strengths": result["passed_conditions"][:2],
            "improvements": result["failed_conditions"][:2],
            "specific_feedback": correction if failed else "This attempt met the targeted behavior.",
            "mistake": {
                "type": "target-condition-miss" if failed else "none",
                "quote": "[answer encrypted]" if answer else "",
                "diagnosis": correction if failed else "Target behavior demonstrated.",
            },
            "why_bad": "This condition blocks a clear interview answer." if failed else "",
            "better_structure": prompt.get("expected_order") or prompt.get("correct_order") or [],
            "improved_answer": "",
            "next_drills": [],
            "retry_instruction": f"Retry with focus on: {correction}" if failed else "",
            "progress_signal": f"Deterministic activity score: {result['score']}%.",
        },
    }


def _sanitize_mission_attempt_payload(activity_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Keep only activity inputs; all score/mastery fields are server-owned."""
    common = {"idempotency_key", "attempt_session_id", "mission_id", "roadmap_node_id"}
    activity_fields = {
        "compare_answers": {"selected_option", "reason"},
        "arrange_blocks": {"block_order"},
        "rewrite_answer": {"rewrite"},
        "guided_spoken_response": {"transcript"},
        "unseen_checkpoint": {"answer", "transcript"},
        "checkpoint": {"answer", "transcript"},
    }
    allowed = common | activity_fields.get(str(activity_type or ""), {"answer", "transcript"})
    return {key: value for key, value in (payload or {}).items() if key in allowed}


def _hash_code(code: str) -> str:
    return hashlib.sha256((code or "").encode("utf-8")).hexdigest()


def _contains_metric(value: str) -> bool:
    return bool(
        re.search(
            r"(?i)(?:\b\d+(?:\.\d+)?\s?(?:%|x|k|m|ms|sec|seconds|users|requests|rows|bugs|latency|accuracy|revenue|cost)\b|(?:₹|\$)\s?\d+)",
            value or "",
        )
    )


def _first_sentence(value: str, limit: int = 220) -> str:
    text = _bounded(value, limit).replace("\n", " ").strip()
    if not text:
        return ""
    parts = re.split(r"(?<=[.!?])\s+", text)
    return _bounded(parts[0] if parts else text, limit)


def _feedback_list(value: Any, fallback: List[str], limit: int = 5) -> List[str]:
    if not isinstance(value, list):
        return fallback[:limit]
    items = [_bounded(str(item), 500) for item in value if str(item or "").strip()]
    return (items or fallback)[:limit]


def _safe_float(value: Any, fallback: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return fallback


def _project_anchor(profile_context: Dict[str, Any]) -> str:
    projects = profile_context.get("projects") or []
    if isinstance(projects, list):
        for project in projects:
            if isinstance(project, dict) and project.get("name"):
                return str(project["name"]).strip()
    repos = (profile_context.get("external_profile_signals") or {}).get("github", {}).get("repositories", [])
    if isinstance(repos, list):
        for repo in repos:
            if isinstance(repo, dict) and repo.get("name"):
                return str(repo["name"]).strip()
    skills = profile_context.get("skills") or []
    if isinstance(skills, list) and skills:
        first = skills[0]
        return str(first.get("name") if isinstance(first, dict) else first).strip()
    return "your strongest project"


def _question_family(question_type: str, question: str) -> str:
    text = f"{question_type or ''} {question or ''}".lower()
    if any(token in text for token in ("project", "built", "implemented", "portfolio", "repo")):
        return "project"
    if any(token in text for token in ("algorithm", "complexity", "data structure", "system", "api", "database", "debug")):
        return "technical"
    if any(token in text for token in ("follow", "trade-off", "scale", "edge case")):
        return "followup"
    return "interview"


def skill_key_from_turn(turn: Dict[str, Any], profile_context: Dict[str, Any]) -> str:
    question = str(turn.get("question") or "")
    topic = str(turn.get("topic_label") or turn.get("topic") or "General")
    family = _question_family(str(turn.get("question_type") or ""), question)
    if family == "project":
        return f"project:{_slug(_project_anchor(profile_context))}:defense"
    if family == "technical":
        return f"technical:{_slug(topic)}"
    if turn.get("is_followup") or family == "followup":
        return f"interview-followup:{_slug(topic)}"
    return f"interview:{_slug(topic)}"


def _skill_category(skill_key: str) -> str:
    if skill_key.startswith("project:"):
        return "project"
    if _is_technical_skill_key(skill_key):
        return "technical"
    return "interview"


def _score_delta(score: float) -> float:
    return round(max(-35, min(25, score - 70)), 1)


def _next_review_for(score: float) -> datetime:
    if score < 55:
        return datetime.now(timezone.utc) + timedelta(hours=18)
    if score < 75:
        return datetime.now(timezone.utc) + timedelta(days=2)
    if score < 88:
        return datetime.now(timezone.utc) + timedelta(days=5)
    return datetime.now(timezone.utc) + timedelta(days=10)


async def _upsert_skill_state(user_id: str, skill_key: str, category: str, evidence_score: float) -> Dict[str, Any]:
    row = await async_execute(
        """
        SELECT mastery_score, confidence_score, evidence_count
        FROM LearnerSkillStates
        WHERE user_id = %s AND skill_key = %s
        """,
        (user_id, skill_key),
        fetchone=True,
    )
    next_review_at = _next_review_for(evidence_score)
    if row:
        old_mastery = float(row[0] or 0)
        old_confidence = float(row[1] or 0)
        old_count = int(row[2] or 0)
        weight = 0.32 if old_count < 4 else 0.22
        mastery = _clip((old_mastery * (1 - weight)) + (evidence_score * weight))
        confidence = _clip(old_confidence + (10 if old_count < 4 else 4), 0, 100)
        await async_execute(
            """
            UPDATE LearnerSkillStates
            SET skill_category = %s,
                mastery_score = %s,
                confidence_score = %s,
                evidence_count = evidence_count + 1,
                last_evidence_at = NOW(),
                next_review_at = %s,
                updated_at = NOW()
            WHERE user_id = %s AND skill_key = %s
            """,
            (category, mastery, confidence, next_review_at, user_id, skill_key),
        )
        evidence_count = old_count + 1
    else:
        mastery = _clip(evidence_score)
        confidence = 18.0
        evidence_count = 1
        await async_execute(
            """
            INSERT INTO LearnerSkillStates (
                user_id, skill_key, skill_category, mastery_score, confidence_score,
                evidence_count, last_evidence_at, next_review_at
            )
            VALUES (%s, %s, %s, %s, %s, 1, NOW(), %s)
            """,
            (user_id, skill_key, category, mastery, confidence, next_review_at),
        )
    return {
        "skill_key": skill_key,
        "label": _label_from_key(skill_key),
        "mastery_score": mastery,
        "confidence_score": confidence,
        "evidence_count": evidence_count,
        "next_review_at": next_review_at.isoformat(),
    }


def _canonical_evidence_hash(score: float, evidence: Dict[str, Any]) -> str:
    payload = {
        "score": _normalize_score(score),
        "evidence": evidence if isinstance(evidence, dict) else {},
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _server_evidence_source_id(
    *,
    source_type: str,
    interview_id: Optional[str],
    response_id: Optional[str],
    evidence: Dict[str, Any],
) -> str:
    if source_type == "interview_response" and response_id:
        return str(response_id)

    if source_type == "technical_run":
        round_id = str(evidence.get("round_id") or "unknown-round")
        fingerprint = {
            "round_id": round_id,
            "code_hash": evidence.get("code_hash"),
            "exit_code": evidence.get("exit_code"),
            "output_hash": evidence.get("output_hash"),
        }
        canonical = json.dumps(fingerprint, sort_keys=True, separators=(",", ":"), default=str)
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]
        return f"{round_id}:{digest}"

    fingerprint = {
        "interview_id": interview_id,
        "question": evidence.get("question"),
        "answer_excerpt": evidence.get("answer_excerpt"),
        "evidence_type": source_type,
    }
    canonical = json.dumps(fingerprint, sort_keys=True, separators=(",", ":"), default=str)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]
    return f"{interview_id or 'no-interview'}:{digest}"


async def _insert_skill_evidence(
    user_id: str,
    interview_id: Optional[str],
    response_id: Optional[str],
    skill_key: str,
    evidence_type: str,
    score: float,
    evidence: Dict[str, Any],
) -> Dict[str, Any]:
    """Insert evidence and advance mastery exactly once for a server-owned source."""
    source_type = "interview_response" if evidence_type == "interview_turn" else evidence_type
    source_id = _server_evidence_source_id(
        source_type=source_type,
        interview_id=interview_id,
        response_id=response_id,
        evidence=evidence,
    )
    evidence_hash = _canonical_evidence_hash(score, evidence)
    category = _skill_category(skill_key)
    normalized_score = _normalize_score(score)
    next_review_at = _next_review_for(normalized_score)

    def _run() -> Dict[str, Any]:
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                INSERT INTO SkillEvidenceEvents (
                    user_id, interview_id, response_id, skill_key, evidence_type,
                    score_delta, evidence, source_type, source_id,
                    evaluator_version, evidence_hash
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (user_id, skill_key, source_type, source_id, evaluator_version)
                DO NOTHING
                RETURNING evidence_id
                """,
                (
                    user_id,
                    interview_id,
                    response_id,
                    skill_key,
                    evidence_type,
                    _score_delta(normalized_score),
                    json.dumps(evidence, sort_keys=True, default=str),
                    source_type,
                    source_id,
                    EVIDENCE_EVALUATOR_VERSION,
                    evidence_hash,
                ),
            )
            inserted = cursor.fetchone()
            if not inserted:
                conn.commit()
                return {
                    "inserted": False,
                    "source_type": source_type,
                    "source_id": source_id,
                    "evidence_hash": evidence_hash,
                    "mastery": None,
                }

            cursor.execute(
                """
                INSERT INTO LearnerSkillStates (
                    user_id, skill_key, skill_category, mastery_score,
                    confidence_score, evidence_count, last_evidence_at,
                    next_review_at, updated_at
                )
                VALUES (%s, %s, %s, %s, 18, 1, NOW(), %s, NOW())
                ON CONFLICT (user_id, skill_key) DO UPDATE SET
                    skill_category = EXCLUDED.skill_category,
                    mastery_score = ROUND(
                        LearnerSkillStates.mastery_score *
                            (1 - CASE WHEN LearnerSkillStates.evidence_count < 4 THEN 0.32 ELSE 0.22 END)
                        + EXCLUDED.mastery_score *
                            CASE WHEN LearnerSkillStates.evidence_count < 4 THEN 0.32 ELSE 0.22 END,
                        1
                    ),
                    confidence_score = LEAST(
                        100,
                        LearnerSkillStates.confidence_score
                            + CASE WHEN LearnerSkillStates.evidence_count < 4 THEN 10 ELSE 4 END
                    ),
                    evidence_count = LearnerSkillStates.evidence_count + 1,
                    last_evidence_at = NOW(),
                    next_review_at = EXCLUDED.next_review_at,
                    updated_at = NOW()
                RETURNING mastery_score, confidence_score, evidence_count, next_review_at
                """,
                (user_id, skill_key, category, normalized_score, next_review_at),
            )
            state = cursor.fetchone()
            conn.commit()
            mastery = {
                "skill_key": skill_key,
                "label": _label_from_key(skill_key),
                "mastery_score": float(state[0]),
                "confidence_score": float(state[1]),
                "evidence_count": int(state[2]),
                "next_review_at": state[3].isoformat() if hasattr(state[3], "isoformat") else str(state[3]),
            }
            return {
                "inserted": True,
                "source_type": source_type,
                "source_id": source_id,
                "evidence_hash": evidence_hash,
                "mastery": mastery,
            }
        except Exception:
            conn.rollback()
            raise
        finally:
            cursor.close()
            return_db_connection(conn)

    return await asyncio.to_thread(_run)


def _missing_answer_signals(answer: str, flags: List[str]) -> List[str]:
    text = (answer or "").lower()
    missing: List[str] = []
    if "no_evidence" in flags or not any(token in text for token in ("built", "implemented", "designed", "debugged", "owned", "deployed")):
        missing.append("specific proof from your work")
    if "vague" in flags or not any(token in text for token in ("because", "trade-off", "alternative", "constraint", "edge case")):
        missing.append("trade-off or constraint")
    if not _contains_metric(text):
        missing.append("measurable result")
    if "too_short" in flags or len(text.split()) < 45:
        missing.append("complete answer structure")
    return missing[:3]


async def _upsert_project_gap(
    user_id: str,
    project_key: str,
    gap_key: str,
    gap_summary: str,
    evidence: Dict[str, Any],
) -> None:
    row = await async_execute(
        """
        SELECT gap_id, evidence
        FROM ProjectKnowledgeGaps
        WHERE user_id = %s AND project_key = %s AND gap_key = %s AND status = 'open'
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (user_id, project_key, gap_key),
        fetchone=True,
    )
    if row:
        existing = _json_load(row[1], {})
        examples = existing.get("examples") if isinstance(existing, dict) else []
        if not isinstance(examples, list):
            examples = []
        examples = ([evidence] + examples)[:5]
        updated = {**(existing if isinstance(existing, dict) else {}), "examples": examples}
        await async_execute(
            """
            UPDATE ProjectKnowledgeGaps
            SET gap_summary = %s, evidence = %s, next_check_at = %s, updated_at = NOW()
            WHERE gap_id = %s
            """,
            (gap_summary, json.dumps(updated), datetime.now(timezone.utc) + timedelta(days=1), row[0]),
        )
        return
    await async_execute(
        """
        INSERT INTO ProjectKnowledgeGaps (
            user_id, project_key, gap_key, gap_summary, evidence, next_check_at
        )
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (
            user_id,
            project_key,
            gap_key,
            gap_summary,
            json.dumps({"examples": [evidence]}),
            datetime.now(timezone.utc) + timedelta(days=1),
        ),
    )


async def _queue_exercise(
    user_id: str,
    interview_id: Optional[str],
    skill_key: str,
    exercise_type: str,
    prompt: Dict[str, Any],
    rubric: Dict[str, Any],
    source_evidence: List[Dict[str, Any]],
) -> Optional[str]:
    existing = await async_execute(
        """
        SELECT exercise_id
        FROM GeneratedExercises
        WHERE user_id = %s
          AND skill_key = %s
          AND exercise_type = %s
          AND status IN ('queued', 'in_progress')
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (user_id, skill_key, exercise_type),
        fetchone=True,
    )
    if existing:
        return existing[0]

    exercise_id = str(uuid.uuid4())
    await async_execute(
        """
        INSERT INTO GeneratedExercises (
            exercise_id, user_id, interview_id, skill_key, exercise_type,
            prompt, rubric, source_evidence, status
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'queued')
        """,
        (
            exercise_id,
            user_id,
            interview_id,
            skill_key,
            exercise_type,
            json.dumps(prompt),
            json.dumps(rubric),
            json.dumps(source_evidence),
        ),
    )
    return exercise_id


def _insert_mission_event_sync(
    cursor: Any,
    *,
    user_id: str,
    mission_id: Optional[str],
    event_type: str,
    payload: Dict[str, Any],
    roadmap_node_id: Optional[str] = None,
    exercise_id: Optional[str] = None,
    attempt_id: Optional[str] = None,
) -> None:
    cursor.execute(
        """
        INSERT INTO ImprovementMissionEvents (
            user_id, mission_id, roadmap_node_id, exercise_id, attempt_id, event_type, payload
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        (user_id, mission_id, roadmap_node_id, exercise_id, attempt_id, event_type, _safe_json(payload)),
    )


def _create_improve_exercise_sync(
    cursor: Any,
    *,
    user_id: str,
    mission_id: str,
    mission_skill_id: str,
    roadmap_node_id: str,
    interview_id: Optional[str],
    skill_key: str,
    activity_type: str,
    prompt: Dict[str, Any],
    order_index: int,
    is_checkpoint: bool = False,
) -> str:
    exercise_id = str(uuid.uuid4())
    rubric = {
        "pass_score": PASS_SCORE,
        "activity_type": activity_type,
        "rubric_version": "improve_phase_1_v1",
        "checks": [item.get("label") for item in prompt.get("pass_conditions", []) if isinstance(item, dict)],
        "conditions": prompt.get("pass_conditions", []),
    }
    cursor.execute(
        """
        INSERT INTO GeneratedExercises (
            exercise_id, user_id, interview_id, skill_key, exercise_type,
            prompt, rubric, source_evidence, status, exercise_mode, input_type,
            timer_seconds, priority_score, mission_id, mission_skill_id,
            roadmap_node_id, activity_type, variation_group, is_checkpoint,
            activity_metadata
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'queued', %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            exercise_id,
            user_id,
            interview_id,
            skill_key,
            activity_type,
            _safe_json(prompt),
            _safe_json(rubric),
            _safe_json(prompt.get("source_evidence") or []),
            activity_type,
            prompt.get("input_type") or "text",
            prompt.get("timer_seconds"),
            100 - order_index,
            mission_id,
            mission_skill_id,
            roadmap_node_id,
            activity_type,
            f"{skill_key}:phase1",
            bool(is_checkpoint),
            _safe_json({"phase": 1, "order_index": order_index}),
        ),
    )
    return exercise_id


def _ensure_active_improvement_mission(
    cursor: Any,
    user_id: str,
    skill_gaps: List[Dict[str, Any]],
    technical_mistakes: List[Dict[str, Any]],
    project_homework: List[Dict[str, Any]],
    mode: str = "mock",
    source_interview_id: Optional[str] = None,
    source_analysis_id: Optional[str] = None,
) -> Optional[str]:
    mode = "technical" if mode == "technical" else "mock"
    if mode == "technical":
        mode_guard = """
          AND weakness_type = 'technical_failure'
          AND COALESCE(weakness_key, '') LIKE 'technical:%%'
        """
    else:
        mode_guard = """
          AND COALESCE(weakness_type, '') <> 'technical_failure'
          AND COALESCE(weakness_key, '') NOT LIKE 'technical:%%'
          AND COALESCE(weakness_key, '') NOT LIKE 'algorithm:%%'
          AND COALESCE(weakness_key, '') NOT LIKE 'debugging:%%'
        """
    cursor.execute(
        f"""
        SELECT mission_id
        FROM ImprovementMissions
        WHERE user_id = %s AND mode = %s AND status = 'active'
        {mode_guard}
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (user_id, mode),
    )
    existing = cursor.fetchone()
    if existing:
        return existing[0]

    cursor.execute(
        """
        UPDATE ImprovementMissions
        SET status = 'superseded',
            updated_at = NOW()
        WHERE user_id = %s
          AND mode = %s
          AND status = 'active'
        """,
        (user_id, mode),
    )

    if mode == "technical":
        skill_gaps = []
        project_homework = []
    else:
        technical_mistakes = []

    if not (skill_gaps or technical_mistakes or project_homework):
        return None

    primary_gap = skill_gaps[0] if skill_gaps else {}
    technical = technical_mistakes[0] if technical_mistakes else {}
    project_gap = project_homework[0] if project_homework else {}
    skill_key = str(primary_gap.get("skill_key") or technical.get("skill_key") or technical.get("mistake_key") or project_gap.get("gap_key") or "project:interai:defense")
    skill_label = str(primary_gap.get("label") or technical.get("topic_label") or _label_from_key(skill_key))
    category = str(primary_gap.get("category") or ("technical" if mode == "technical" else _skill_category(skill_key)))
    baseline_score = _clip(float(primary_gap.get("mastery_score") or (38 if mode == "technical" else 54)))
    confidence = _clip(float(primary_gap.get("confidence_score") or (60 if mode == "technical" else 60)))
    evidence_count = int(primary_gap.get("evidence_count") or technical.get("occurrence_count") or 1)
    evidence_text = (
        str(project_gap.get("title") or "")
        or str(technical.get("summary") or "")
        or str(primary_gap.get("why_it_matters") or f"Interviewers can still expose weak depth in {skill_label}.")
    )
    priority = calculate_mission_priority({
        "role_relevance": 82 if "project" in skill_key or category in {"resume", "interview"} else 72,
        "severity": 100 - baseline_score,
        "repetition": min(100, evidence_count * 25),
        "prerequisite_impact": 86 if any(token in skill_key for token in ("project", "structure", "communication", "defense")) else 68,
        "recency": 100,
    })
    mission_id = str(uuid.uuid4())
    mission_skill_id = str(uuid.uuid4())
    title = f"Fix {skill_label}" if mode == "technical" else _mission_title(skill_key, evidence_text)
    target = _clip(max(75, baseline_score + 18))
    assignment_reason = _bounded(
        evidence_text
        or "Your previous interview showed a repeated weakness that blocks stronger answers.",
        420,
    )
    cursor.execute(
        """
        INSERT INTO ImprovementMissions (
            mission_id, user_id, source_interview_id, mode, source_analysis_id, weakness_key,
            weakness_type, mission_type, title,
            assignment_reason, diagnosis_json, priority_score, priority_factors,
            baseline_readiness, current_readiness, target_readiness, progress_percent,
            validation_status
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 0, 'active')
        """,
        (
            mission_id,
            user_id,
            source_interview_id or project_gap.get("interview_id") or None,
            mode,
            source_analysis_id,
            skill_key,
            "technical_failure" if mode == "technical" else "interview_answer",
            category,
            title,
            assignment_reason,
            _safe_json({
                "skill_key": skill_key,
                "skill_label": skill_label,
                "evidence_count": evidence_count,
                "confidence_score": confidence,
                "mode": mode,
                "improvement_pathway": "ordered_pathway",
            }),
            priority["priority_score"],
            _safe_json(priority),
            baseline_score,
            baseline_score,
            target,
        ),
    )
    cursor.execute(
        """
        INSERT INTO ImprovementMissionSkills (
            mission_skill_id, mission_id, user_id, skill_key, label, category,
            baseline_score, latest_score, target_score, role_weight, mastery_status,
            evidence_summary, criteria_json
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 1, 'practising', %s, %s)
        """,
        (
            mission_skill_id,
            mission_id,
            user_id,
            skill_key,
            skill_label,
            category,
            baseline_score,
            baseline_score,
            target,
            assignment_reason,
            _safe_json({"verification": "two guided passes, one variation pass, one unseen checkpoint"}),
        ),
    )

    activity_defs = _phase_one_activity_definitions(skill_label, assignment_reason, mode=mode)
    for order_index, activity in enumerate(activity_defs):
        roadmap_node_id = str(uuid.uuid4())
        activity_type = activity["activity_type"]
        prompt = {
            **(activity.get("prompt") or {}),
            "schema_version": "improve_activity_v1",
            "activity_type": activity_type,
            "skill_key": skill_key,
            "mission_id": mission_id,
            "roadmap_node_id": roadmap_node_id,
            "source_evidence": [{"summary": assignment_reason}],
        }
        is_baseline = activity_type == "baseline"
        exercise_id = None if is_baseline else _create_improve_exercise_sync(
            cursor,
            user_id=user_id,
            mission_id=mission_id,
            mission_skill_id=mission_skill_id,
            roadmap_node_id=roadmap_node_id,
            interview_id=None,
            skill_key=skill_key,
            activity_type=activity_type,
            prompt=prompt,
            order_index=order_index,
            is_checkpoint=bool(activity.get("is_checkpoint")),
        )
        cursor.execute(
            """
            INSERT INTO ImprovementRoadmapNodes (
                roadmap_node_id, mission_id, user_id, mission_skill_id, exercise_id,
                order_index, title, description, activity_type, availability_status,
                attempt_status, result_status, mastery_status, estimated_minutes,
                expected_result, evidence_json, completed_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    CASE WHEN %s THEN NOW() ELSE NULL END)
            """,
            (
                roadmap_node_id,
                mission_id,
                user_id,
                mission_skill_id,
                exercise_id,
                order_index,
                activity["title"],
                activity.get("description"),
                activity_type,
                activity.get("availability_status") or ("current" if order_index == 1 else "locked"),
                activity.get("attempt_status") or "draft",
                activity.get("result_status") or "not_attempted",
                activity.get("mastery_status") or "practising",
                int(activity.get("estimated_minutes") or 4),
                activity.get("expected_result"),
                _safe_json({"summary": assignment_reason}),
                is_baseline,
            ),
        )
    _insert_mission_event_sync(
        cursor,
        user_id=user_id,
        mission_id=mission_id,
        event_type="mission_generated",
        payload={"title": title, "priority": priority, "source": "deterministic_learning_snapshot"},
    )
    logger.info(
        "improve_mission_generated",
        extra={"user_id": user_id, "mission_id": mission_id, "priority_score": priority["priority_score"]},
    )
    return mission_id


def _ensure_mission_from_weakness_sync(
    user_id: str,
    interview_id: str,
    analysis_id: str,
    mode: str,
) -> Optional[str]:
    connection = get_db_connection()
    cursor = connection.cursor()
    try:
        technical_mode = mode == "technical"
        cursor.execute(
            """
            SELECT weakness_state_id, skill_key, lifecycle_state,
                   observation_count, baseline_score, latest_score, confidence,
                   root_cause_hypothesis, root_cause_confidence, evidence_summary
            FROM WeaknessStates
            WHERE user_id = %s AND lifecycle_state <> 'resolved'
              AND (
                  (%s = TRUE AND skill_key LIKE 'technical:%%')
                  OR (%s = FALSE AND skill_key NOT LIKE 'technical:%%')
              )
            ORDER BY
                CASE lifecycle_state
                    WHEN 'worsening' THEN 0 WHEN 'repeated' THEN 1
                    WHEN 'occasional' THEN 2 WHEN 'new' THEN 3 ELSE 4
                END,
                confidence DESC, last_observed_at DESC
            LIMIT 1
            """,
            (user_id, technical_mode, technical_mode),
        )
        row = cursor.fetchone()
        if not row:
            connection.commit()
            return None
        summary = _json_load(row[9], {})
        evidence_text = str(
            row[7]
            or (summary.get("summary") if isinstance(summary, dict) else "")
            or f"Evidence shows a {row[2]} weakness in {_label_from_key(row[1])}."
        )
        if technical_mode:
            mission_id = _ensure_active_improvement_mission(
                cursor,
                user_id,
                [],
                [{
                    "skill_key": row[1],
                    "mistake_key": row[1],
                    "topic_label": _label_from_key(row[1]),
                    "summary": evidence_text,
                    "occurrence_count": int(row[3] or 1),
                    "weakness_state_id": row[0],
                }],
                [],
                mode="technical",
                source_interview_id=interview_id,
                source_analysis_id=analysis_id,
            )
        else:
            latest_score = float(row[5]) if row[5] is not None else float(row[4] or 0)
            mission_id = _ensure_active_improvement_mission(
                cursor,
                user_id,
                [{
                    "skill_key": row[1],
                    "label": _label_from_key(row[1]),
                    "category": _skill_category(row[1]),
                    "mastery_score": latest_score,
                    "confidence_score": float(row[6] or 0) * 100,
                    "evidence_count": int(row[3] or 1),
                    "why_it_matters": evidence_text,
                    "weakness_state_id": row[0],
                }],
                [],
                [],
                mode="mock",
                source_interview_id=interview_id,
                source_analysis_id=analysis_id,
            )
        connection.commit()
        return mission_id
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()
        return_db_connection(connection)


async def ensure_mission_from_weakness(
    user_id: str,
    interview_id: str,
    analysis_id: str,
    mode: str,
) -> Optional[str]:
    return await asyncio.to_thread(
        _ensure_mission_from_weakness_sync,
        user_id,
        interview_id,
        analysis_id,
        "technical" if mode == "technical" else "mock",
    )


def _ensure_mission_from_response_assessment_sync(
    user_id: str,
    interview_id: str,
) -> Optional[str]:
    """Create a coaching mission from real partial-attempt evidence.

    A voluntarily ended round is not official readiness evidence, but its
    persisted response assessments are still useful for sentence repair and
    open-mic practice. This keeps Improve useful without grading the session.
    """
    connection = get_db_connection()
    cursor = connection.cursor()
    try:
        cursor.execute(
            """
            SELECT ra.assessment_id, ra.assessment_json,
                   iq.question_text, iq.topic_label, iq.question_type,
                   ir.answer_text_encrypted, ir.user_response
            FROM ResponseAssessments ra
            JOIN InterviewResponses ir ON ir.response_id = ra.response_id
            JOIN InterviewQuestions iq ON iq.question_id = ir.question_id
            JOIN Interviews i ON i.interview_id = ir.interview_id
            WHERE ra.interview_id = %s AND i.user_id = %s
            ORDER BY ra.created_at
            """,
            (interview_id, user_id),
        )
        candidates: List[Dict[str, Any]] = []
        for row in cursor.fetchall() or []:
            assessment = _json_load(row[1], {})
            flags = assessment.get("flags") if isinstance(assessment.get("flags"), list) else []
            provisional = assessment.get("provisional_score")
            try:
                provisional_score = float(provisional) if provisional is not None else 100.0
            except (TypeError, ValueError):
                provisional_score = 100.0
            if not flags and provisional_score >= 70:
                continue
            candidates.append({
                "assessment_id": str(row[0]),
                "assessment": assessment,
                "question": str(row[2] or ""),
                "topic": str(row[3] or "Interview answer"),
                "question_type": str(row[4] or "main"),
                "provisional_score": provisional_score,
                "flags": [str(flag) for flag in flags],
            })
        if not candidates:
            connection.commit()
            return None

        non_warmups = [item for item in candidates if item["question_type"] != "warmup"]
        chosen = min(non_warmups or candidates, key=lambda item: item["provisional_score"])
        question = chosen["question"]
        project_match = re.search(r"\b(?:in|for)\s+([^,?]{2,80})[,?]", question, re.IGNORECASE)
        project_name = project_match.group(1).strip() if project_match else ""
        label = (
            f"{project_name} explanation"
            if project_name else f"{chosen['topic']} answer structure"
        )
        slug = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")[:80] or "answer-structure"
        flag_labels = [re.sub(r"[_-]+", " ", flag).strip() for flag in chosen["flags"]]
        issue_text = ", ".join(flag_labels[:4]) or "weak structure or missing evidence"
        word_count = int((chosen["assessment"].get("signals") or {}).get("word_count") or 0)
        evidence_text = (
            f"For “{question}”, the recorded answer"
            f"{' used only ' + str(word_count) + ' words and' if word_count else ''} showed {issue_text}. "
            "Reframe it with a direct answer, your exact ownership, one concrete project detail, "
            "and the result or trade-off."
        )
        mission_id = _ensure_active_improvement_mission(
            cursor,
            user_id,
            [{
                "skill_key": f"project:{slug}:reframe" if project_name else f"communication:{slug}",
                "label": label,
                "category": "project" if project_name else "communication",
                "mastery_score": chosen["provisional_score"],
                "confidence_score": float(chosen["assessment"].get("confidence") or 0) * 100,
                "evidence_count": len(candidates),
                "why_it_matters": evidence_text,
            }],
            [],
            [],
            mode="mock",
            source_interview_id=interview_id,
            source_analysis_id=chosen["assessment_id"],
        )
        connection.commit()
        return mission_id
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()
        return_db_connection(connection)


async def ensure_mission_from_response_assessment(
    user_id: str,
    interview_id: str,
) -> Optional[str]:
    return await asyncio.to_thread(
        _ensure_mission_from_response_assessment_sync,
        user_id,
        interview_id,
    )


def _validate_mission_with_analysis_sync(
    user_id: str,
    interview_id: str,
    analysis_id: str,
    mode: str,
    observations: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    connection = get_db_connection()
    cursor = connection.cursor()
    try:
        cursor.execute(
            """
            SELECT mission.mission_id, mission.weakness_key,
                   mission.held_out_checkpoint_id, mission.validation_status,
                   checkpoint.completed_at,
                   source.evaluator_version, source.taxonomy_version, source.rubric_version,
                   current_analysis.evaluator_version, current_analysis.taxonomy_version,
                   current_analysis.rubric_version, current_analysis.evidence_status,
                   current_analysis.created_at
            FROM ImprovementMissions mission
            LEFT JOIN ImprovementRoadmapNodes checkpoint
              ON checkpoint.roadmap_node_id = mission.held_out_checkpoint_id
             AND checkpoint.mission_id = mission.mission_id
            LEFT JOIN SessionPerformanceAnalyses source
              ON source.analysis_id = mission.source_analysis_id
             AND source.user_id = mission.user_id
            JOIN SessionPerformanceAnalyses current_analysis
              ON current_analysis.analysis_id = %s
             AND current_analysis.interview_id = %s
             AND current_analysis.user_id = mission.user_id
             AND current_analysis.mode = mission.mode
            WHERE mission.user_id = %s AND mission.mode = %s AND mission.status = 'active'
              AND mission.validation_status IN ('validation_pending', 'needs_reinforcement')
              AND mission.source_interview_id IS DISTINCT FROM %s
            ORDER BY mission.priority_score DESC, mission.updated_at DESC
            LIMIT 1
            FOR UPDATE OF mission
            """,
            (
                analysis_id, interview_id, user_id,
                "technical" if mode == "technical" else "mock", interview_id,
            ),
        )
        mission = cursor.fetchone()
        if not mission:
            connection.commit()
            return None
        mission_id, weakness_key, held_out_checkpoint_id, _ = mission[:4]
        checkpoint_completed_at = mission[4]
        source_versions = tuple(str(value or "") for value in mission[5:8])
        reassessment_versions = tuple(str(value or "") for value in mission[8:11])
        evidence_status = str(mission[11] or "")
        reassessment_created_at = mission[12]
        compatible = _reassessment_is_compatible(
            source_versions=source_versions,
            reassessment_versions=reassessment_versions,
            evidence_status=evidence_status,
            checkpoint_completed_at=checkpoint_completed_at,
            reassessment_created_at=reassessment_created_at,
        )
        if not compatible:
            connection.commit()
            return {
                "mission_id": mission_id,
                "verified": False,
                "passed_later_interview": False,
                "held_out_passed": bool(held_out_checkpoint_id),
                "status": "not_reassessed",
            }
        comparable = [
            item for item in observations
            if str(item.get("skill_key") or "") == str(weakness_key or "")
            and item.get("score") is not None
        ]
        if not comparable:
            connection.commit()
            return None
        latest = comparable[-1]
        score = _normalize_score(latest.get("score"))
        raw_confidence = latest.get("confidence")
        if isinstance(raw_confidence, str):
            confidence = {"low": 0.35, "medium": 0.7, "high": 0.9}.get(raw_confidence.lower(), 0.0)
        else:
            try:
                confidence = float(raw_confidence or 0)
            except Exception:
                confidence = 0.0
            if confidence > 1:
                confidence /= 100
        passed = score >= PASS_SCORE and confidence >= 0.60
        validation_payload = {
            "analysis_id": analysis_id,
            "interview_id": interview_id,
            "skill_key": weakness_key,
            "source_key": latest.get("source_key"),
            "score": score,
            "confidence": confidence,
            "evaluator_version": reassessment_versions[0],
            "taxonomy_version": reassessment_versions[1],
            "rubric_version": reassessment_versions[2],
            "evidence_status": evidence_status,
        }
        evidence_hash = hashlib.sha256(
            json.dumps(validation_payload, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
        source_key = f"analysis:{analysis_id}:{weakness_key}"
        validation_id = str(uuid.uuid5(uuid.NAMESPACE_URL, source_key))
        cursor.execute(
            """
            INSERT INTO MissionValidationEvidence (
                validation_id, mission_id, user_id, analysis_id, interview_id,
                evidence_type, passed, score, confidence, evidence_json,
                source_key, evidence_hash
            ) VALUES (%s, %s, %s, %s, %s, 'later_interview', %s, %s, %s, %s, %s, %s)
            ON CONFLICT (mission_id, source_key, evidence_hash) DO NOTHING
            """,
            (
                validation_id, mission_id, user_id, analysis_id, interview_id,
                passed, score, confidence, _safe_json(validation_payload), source_key, evidence_hash,
            ),
        )
        cursor.execute(
            """
            SELECT EXISTS (
                SELECT 1 FROM MissionValidationEvidence
                WHERE mission_id = %s AND evidence_type = 'held_out_variation' AND passed = TRUE
            )
            """,
            (mission_id,),
        )
        held_out_passed = bool((cursor.fetchone() or [False])[0])
        verified = passed and held_out_passed and bool(held_out_checkpoint_id)
        if verified:
            cursor.execute(
                """
                UPDATE ImprovementMissions
                SET status = 'completed', validation_status = 'verified',
                    validated_by_interview_id = %s, later_interview_id = %s,
                    validation_analysis_id = %s, progress_percent = 100,
                    completed_at = COALESCE(completed_at, NOW()), updated_at = NOW()
                WHERE mission_id = %s AND user_id = %s
                """,
                (interview_id, interview_id, analysis_id, mission_id, user_id),
            )
            cursor.execute(
                """
                UPDATE WeaknessStates
                SET lifecycle_state = 'resolved', resolved_at = COALESCE(resolved_at, NOW()),
                    latest_score = %s, confidence = GREATEST(confidence, %s), updated_at = NOW()
                WHERE user_id = %s AND skill_key = %s
                """,
                (score, confidence, user_id, weakness_key),
            )
            cursor.execute(
                """
                UPDATE ImprovementMissionSkills
                SET mastery_status = 'verified',
                    verified_at = COALESCE(verified_at, NOW()),
                    needs_reinforcement_at = NULL,
                    updated_at = NOW()
                WHERE mission_id = %s AND user_id = %s AND skill_key = %s
                """,
                (mission_id, user_id, weakness_key),
            )
        elif not passed:
            cursor.execute(
                """
                UPDATE ImprovementMissions
                SET validation_status = 'needs_reinforcement', updated_at = NOW()
                WHERE mission_id = %s AND user_id = %s
                """,
                (mission_id, user_id),
            )
            cursor.execute(
                """
                UPDATE ImprovementMissionSkills
                SET mastery_status = 'needs_reinforcement',
                    needs_reinforcement_at = NOW(),
                    verified_at = NULL,
                    updated_at = NOW()
                WHERE mission_id = %s AND user_id = %s AND skill_key = %s
                """,
                (mission_id, user_id, weakness_key),
            )
            cursor.execute(
                """
                SELECT mission_skill_id
                FROM ImprovementMissionSkills
                WHERE mission_id = %s AND user_id = %s AND skill_key = %s
                LIMIT 1
                """,
                (mission_id, user_id, weakness_key),
            )
            skill_row = cursor.fetchone()
            if skill_row and held_out_checkpoint_id:
                _insert_recovery_node_sync(
                    cursor,
                    user_id=user_id,
                    mission_id=mission_id,
                    mission_skill_id=skill_row[0],
                    source_node_id=held_out_checkpoint_id,
                    skill_key=weakness_key,
                    reason="The later interview did not yet demonstrate the target behaviour with sufficient confidence.",
                )
        connection.commit()
        return {
            "mission_id": mission_id,
            "verified": verified,
            "passed_later_interview": passed,
            "held_out_passed": held_out_passed,
        }
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()
        return_db_connection(connection)


async def validate_mission_with_analysis(
    user_id: str,
    interview_id: str,
    analysis_id: str,
    mode: str,
    observations: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    return await asyncio.to_thread(
        _validate_mission_with_analysis_sync,
        user_id,
        interview_id,
        analysis_id,
        "technical" if mode == "technical" else "mock",
        observations,
    )


def _reassessment_is_compatible(
    *,
    source_versions: tuple[str, str, str],
    reassessment_versions: tuple[str, str, str],
    evidence_status: str,
    checkpoint_completed_at: Any,
    reassessment_created_at: Any,
) -> bool:
    return bool(
        all(source_versions)
        and source_versions == reassessment_versions
        and evidence_status == "sufficient"
        and checkpoint_completed_at is not None
        and reassessment_created_at is not None
        and reassessment_created_at > checkpoint_completed_at
    )


def _exercise_prompt_for_turn(turn: Dict[str, Any], exercise_type: str, anchor: str) -> Dict[str, Any]:
    question = str(turn.get("question") or "Explain a weak answer from your last interview.")
    topic = str(turn.get("topic_label") or turn.get("topic") or "General")
    short_question = _bounded(question, 180)
    if exercise_type == "project_defense":
        return {
            "title": f"Defend {anchor}",
            "prompt": f"Write a tighter answer to: {short_question}",
            "question": question,
            "interaction_type": "written_response",
            "steps": [
                "Answer directly in the first sentence.",
                f"State your exact ownership in {anchor}.",
                "Name one technical decision and why it fit.",
                "Add one trade-off, failure mode, or alternative.",
                "Close with a metric, shipped result, or visible outcome.",
            ],
        }
    if exercise_type == "followup_chain":
        return {
            "title": f"Handle the follow-up on {topic}",
            "prompt": f"Answer the original question, then add the strict follow-up you expect next: {short_question}",
            "question": question,
            "interaction_type": "written_response",
            "steps": [
                "Give the first-pass answer in 4 lines.",
                "Write the follow-up an interviewer would ask.",
                "Answer that follow-up with one edge case and one trade-off.",
            ],
        }
    return {
        "title": f"Recall card: {topic}",
        "prompt": f"Reconstruct a strong answer shape for: {short_question}",
        "question": question,
        "interaction_type": "recall_card",
        "steps": [
            "Write the answer without looking at notes.",
            "Check whether it has direct answer, proof, trade-off, and result.",
            "Rewrite only the weakest line.",
        ],
    }


async def ingest_interview_evidence(
    user_id: str,
    interview_id: str,
    turns: List[Dict[str, Any]],
    profile_context: Dict[str, Any],
) -> None:
    if not turns:
        return

    anchor = _project_anchor(profile_context)
    weak_turns: List[Dict[str, Any]] = []
    for turn in turns:
        score = float(turn.get("score") or 0)
        flags = turn.get("answer_quality_flags") or []
        if isinstance(flags, str):
            flags = [flags]
        skill_key = skill_key_from_turn(turn, profile_context)
        evidence = {
            "question": _bounded(turn.get("question") or "", 600),
            "answer_excerpt": _bounded(turn.get("response") or turn.get("user_response") or "", 800),
            "topic": turn.get("topic_label") or turn.get("topic"),
            "score": score,
            "flags": flags,
            "feedback": _bounded(turn.get("feedback") or "", 500),
        }
        recorded = await _insert_skill_evidence(
            user_id,
            interview_id,
            turn.get("response_id"),
            skill_key,
            "interview_turn",
            score,
            evidence,
        )
        if not recorded["inserted"]:
            continue

        if score < 70 or flags:
            weak_turns.append({**turn, "_skill_key": skill_key, "_flags": flags, "_score": score})

        family = _question_family(str(turn.get("question_type") or ""), str(turn.get("question") or ""))
        missing = _missing_answer_signals(str(turn.get("response") or ""), flags)
        if family == "project" and (score < 75 or missing):
            project_key = _slug(anchor)
            gap_key = _slug(f"{turn.get('topic_label') or turn.get('topic') or 'project'} {' '.join(missing) or 'depth'}")
            summary = f"{anchor}: prepare {', '.join(missing) if missing else 'a deeper project explanation'}."
            await _upsert_project_gap(user_id, project_key, gap_key, summary, evidence)

    weak_turns = sorted(weak_turns, key=lambda item: float(item.get("_score") or 0))[:3]
    for index, turn in enumerate(weak_turns):
        exercise_type = ["project_defense", "followup_chain", "recall_card"][min(index, 2)]
        if _question_family(str(turn.get("question_type") or ""), str(turn.get("question") or "")) != "project" and exercise_type == "project_defense":
            exercise_type = "followup_chain"
        prompt = _exercise_prompt_for_turn(turn, exercise_type, anchor)
        await _queue_exercise(
            user_id=user_id,
            interview_id=interview_id,
            skill_key=turn["_skill_key"],
            exercise_type=exercise_type,
            prompt=prompt,
            rubric={
                "pass_score": PASS_SCORE,
                "checks": ["direct answer", "specific proof", "trade-off", "metric or result"],
            },
            source_evidence=[{
                "question": _bounded(turn.get("question") or "", 500),
                "score": turn.get("_score"),
                "flags": turn.get("_flags"),
                "feedback": _bounded(turn.get("feedback") or "", 500),
            }],
        )


def build_error_signature(stdout: str, stderr: str, exit_code: Optional[int]) -> str:
    source = (stderr or stdout or "").strip()
    if not source:
        return "success" if exit_code == 0 else f"exit-code-{exit_code if exit_code is not None else 'unknown'}"
    first = next((line.strip() for line in source.splitlines() if line.strip()), source[:120])
    first = re.sub(r'File ".*?", line \d+', "File <submitted>, line n", first)
    first = re.sub(r"\bline \d+\b", "line n", first, flags=re.I)
    first = re.sub(r"\s+", " ", first)
    return first[:160]


def _case_list_failure_diagnosis(
    stdout: str,
    *,
    round_type: str,
    language: str,
) -> Optional[Dict[str, Any]]:
    try:
        cases = json.loads(stdout or "[]")
    except Exception:
        return None
    if not isinstance(cases, list) or not cases:
        return None
    failed = [case for case in cases if isinstance(case, dict) and not case.get("passed")]
    if not failed:
        return None
    hidden_failed = sum(1 for case in failed if case.get("hidden"))
    visible_failed = len(failed) - hidden_failed
    total = len(cases)
    passed = total - len(failed)
    first_visible = next((case for case in failed if not case.get("hidden")), None)
    if first_visible:
        summary = (
            f"{visible_failed} visible test(s) and {hidden_failed} hidden test(s) failed. "
            f"First visible mismatch expected {first_visible.get('expected', 'unknown')} "
            f"but got {first_visible.get('actual', 'unknown')}."
        )
    else:
        summary = f"{hidden_failed} hidden test(s) failed while {passed}/{total} cases passed."
    return {
        "mistake_type": "hidden-test-failure" if hidden_failed and not visible_failed else "test-case-failure",
        "mistake_key": f"{round_type}:{language}:failed-{visible_failed}-visible-{hidden_failed}-hidden"[:120],
        "summary": _bounded(summary, 500),
        "repair_action": "Reconstruct the smallest failing edge case, explain the expected output, then rerun before submitting.",
    }


async def classify_code_mistake(
    *,
    language: str,
    code: str,
    stdout: str,
    stderr: str,
    exit_code: Optional[int],
    round_type: str,
    prompt: str,
) -> Dict[str, Any]:
    signature = build_error_signature(stdout, stderr, exit_code)
    combined = f"{stderr}\n{stdout}".lower()
    if exit_code == 0:
        return {
            "mistake_type": "passed_execution",
            "mistake_key": f"{round_type}:{language}:passed",
            "summary": "The code executed successfully. Keep practicing explanation, complexity, and edge cases.",
            "repair_action": "Explain the approach, complexity, and one edge case without reading notes.",
        }
    case_diagnosis = _case_list_failure_diagnosis(stdout, round_type=round_type, language=language)
    if case_diagnosis:
        return case_diagnosis

    prompt_payload = {
        "language": language,
        "round_type": round_type,
        "prompt": _bounded(prompt, 700),
        "code_excerpt": _bounded(code, 1600),
        "stdout": _bounded(stdout, 600),
        "stderr": _bounded(stderr, 900),
        "exit_code": exit_code,
    }
    try:
        payload = await complete_json_async(
            [
                {
                    "role": "system",
                    "content": (
                        "You diagnose interview coding mistakes from execution evidence. "
                        "Return a compact JSON object with mistake_type, mistake_key, summary, and repair_action. "
                        "The mistake_key must be stable and specific, not a generic bucket. "
                        f"{SYSTEM_DATA_BOUNDARY}"
                    ),
                },
                {
                    "role": "user",
                    "content": data_block("technical_run", json.dumps(prompt_payload, ensure_ascii=False)),
                },
            ],
            event_type="technical_mistake_analysis",
            temperature=0.1,
            max_tokens=500,
            provider_policy="local_required",
            metadata={"round_type": round_type, "language": language},
        )
        mistake_type = _slug(str(payload.get("mistake_type") or "execution_failure"), "execution-failure")
        mistake_key = _slug(str(payload.get("mistake_key") or f"{round_type}:{language}:{signature}"), "execution-failure")
        return {
            "mistake_type": mistake_type,
            "mistake_key": f"{round_type}:{language}:{mistake_key}"[:120],
            "summary": _bounded(str(payload.get("summary") or signature), 500),
            "repair_action": _bounded(str(payload.get("repair_action") or "Fix the failure and explain why it happened."), 500),
        }
    except Exception:
        if "syntax" in combined or "indentation" in combined or "expected" in combined:
            mistake_type = "syntax-or-structure"
            action = "Run a syntax pass before execution: brackets, indentation, semicolons, and function boundaries."
        elif "nameerror" in combined or "referenceerror" in combined or "not defined" in combined:
            mistake_type = "identifier-mismatch"
            action = "Trace every renamed variable or function and keep one consistent name from input to return."
        elif "index" in combined or "out of range" in combined or "<= nums.length" in code:
            mistake_type = "boundary-condition"
            action = "Check loop bounds and empty-input cases before optimizing the solution."
        elif "typeerror" in combined or "cannot read" in combined or "none" in combined:
            mistake_type = "state-shape"
            action = "Write down the value shape at each line, then guard missing or null states."
        else:
            mistake_type = "execution-failure"
            action = "Reduce the failing case, state the expected output, and repair the first runtime error."
        return {
            "mistake_type": mistake_type,
            "mistake_key": f"{round_type}:{language}:{_slug(signature)}"[:120],
            "summary": signature.replace("-", " "),
            "repair_action": action,
        }


async def _upsert_mistake_cluster(
    user_id: str,
    round_id: str,
    diagnosis: Dict[str, Any],
    example: Dict[str, Any],
) -> None:
    row = await async_execute(
        """
        SELECT cluster_id, examples, occurrence_count
        FROM TechnicalMistakeClusters
        WHERE user_id = %s AND mistake_key = %s
        """,
        (user_id, diagnosis["mistake_key"]),
        fetchone=True,
    )
    if row:
        examples = _json_load(row[1], [])
        if not isinstance(examples, list):
            examples = []
        examples = ([example] + examples)[:5]
        await async_execute(
            """
            UPDATE TechnicalMistakeClusters
            SET round_id = %s,
                mistake_type = %s,
                examples = %s,
                occurrence_count = occurrence_count + 1,
                last_seen_at = NOW()
            WHERE cluster_id = %s
            """,
            (round_id, diagnosis["mistake_type"], json.dumps(examples), row[0]),
        )
        return
    await async_execute(
        """
        INSERT INTO TechnicalMistakeClusters (
            user_id, round_id, mistake_type, mistake_key, examples
        )
        VALUES (%s, %s, %s, %s, %s)
        """,
        (user_id, round_id, diagnosis["mistake_type"], diagnosis["mistake_key"], json.dumps([example])),
    )


async def ingest_technical_run(
    *,
    user_id: str,
    round_id: str,
    interview_id: Optional[str],
    round_type: str,
    prompt: str,
    language: str,
    code: str,
    stdout: str,
    stderr: str,
    exit_code: Optional[int],
    runtime_ms: int,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    metadata = metadata or {}
    topic_label = (
        metadata.get("algorithm_pattern")
        or metadata.get("topic")
        or metadata.get("problem_title")
        or metadata.get("title")
        or round_type
    )
    skill_key = str(metadata.get("skill_key") or f"technical:{_slug(str(topic_label))}")
    score = 82.0 if exit_code == 0 else 38.0
    evidence = {
        "round_id": round_id,
        "prompt": _bounded(prompt, 700),
        "language": language,
        "code_hash": _hash_code(code),
        "output_hash": hashlib.sha256(f"{stdout}\0{stderr}".encode("utf-8")).hexdigest(),
        "exit_code": exit_code,
        "runtime_ms": runtime_ms,
        "error_signature": build_error_signature(stdout, stderr, exit_code),
        "algorithm_pattern": metadata.get("algorithm_pattern"),
        "problem_title": metadata.get("title") or metadata.get("problem_title"),
    }
    recorded = await _insert_skill_evidence(
        user_id,
        interview_id,
        None,
        skill_key,
        "technical_run",
        score,
        evidence,
    )
    if not recorded["inserted"]:
        return

    if exit_code == 0:
        return

    diagnosis = await classify_code_mistake(
        language=language,
        code=code,
        stdout=stdout,
        stderr=stderr,
        exit_code=exit_code,
        round_type=round_type,
        prompt=prompt,
    )
    example = {
        **evidence,
        "skill_key": skill_key,
        "topic_label": _label_from_key(skill_key),
        "summary": diagnosis["summary"],
        "repair_action": diagnosis["repair_action"],
        "code_hash": _hash_code(code),
    }
    await _upsert_mistake_cluster(user_id, round_id, diagnosis, example)

    await _queue_exercise(
        user_id=user_id,
        interview_id=interview_id,
        skill_key=skill_key,
        exercise_type="bug_fix_drill" if round_type == "debugging" else "algorithm_repair",
        prompt={
            "title": "Repair the failed technical attempt",
            "prompt": diagnosis["repair_action"],
            "question": prompt,
            "interaction_type": "code_or_written_response",
            "language": language,
            "code_excerpt": _bounded(code, 1800),
            "error_signature": evidence["error_signature"],
            "steps": [
                "Name the exact failure before changing code.",
                "Fix the smallest broken part.",
                "Run the edge case that would have caught it.",
                "Explain the complexity or failure mode aloud.",
            ],
        },
        rubric={
            "pass_score": PASS_SCORE,
            "checks": ["failure explained", "code repaired", "edge case covered", "complexity or trade-off explained"],
        },
        source_evidence=[example],
    )


def _attempt_text_from_payload(submitted_answer: str, payload: Dict[str, Any]) -> str:
    answer = submitted_answer or ""
    if answer.strip() or not isinstance(payload, dict):
        return answer
    ordered_keys = [
        "main_answer",
        "predicted_follow_up",
        "follow_up_answer",
        "weak_line",
        "structure_gap",
        "rewrite",
        "diagnosis",
        "corrected_answer",
        "line_1",
        "line_2",
        "line_3",
        "line_4",
        "line_5",
        "text",
        "transcript",
        "code",
    ]
    parts = []
    for key in ordered_keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            label = key.replace("_", " ")
            parts.append(f"{label}: {value.strip()}")
    run_result = payload.get("run_result")
    if run_result:
        parts.append(json.dumps(run_result, ensure_ascii=False) if not isinstance(run_result, str) else run_result)
    return "\n".join(parts)


def _diagnose_attempt(prompt: Dict[str, Any], answer: str, payload: Dict[str, Any]) -> Dict[str, str]:
    text = (answer or "").strip()
    lower = text.lower()
    words = text.split()
    prompt_question = str(prompt.get("question") or prompt.get("prompt") or "this interview question")
    run_result = payload.get("run_result") if isinstance(payload, dict) else None
    run_text = json.dumps(run_result, ensure_ascii=False).lower() if run_result else ""

    if run_result and ("error" in run_text or '"exit_code": 0' not in run_text):
        if "index" in run_text or "out of range" in run_text:
            return {
                "type": "boundary-condition",
                "quote": _first_sentence(text or run_text, 220),
                "diagnosis": "The attempt does not explain or handle the boundary case that caused the failure.",
                "why_bad": "Interviewers expect you to catch the smallest failing input before generalizing the solution.",
                "retry": "Name the failing input, fix the boundary, and explain the edge case that proves it.",
            }
        if "nameerror" in run_text or "referenceerror" in run_text or "not defined" in run_text:
            return {
                "type": "identifier-mismatch",
                "quote": _first_sentence(text or run_text, 220),
                "diagnosis": "The code or explanation uses inconsistent names, so the solution cannot be trusted end to end.",
                "why_bad": "A naming mismatch signals that you are not tracing state carefully through the algorithm.",
                "retry": "Trace the variable names from input to return and rewrite the fix with one consistent name.",
            }
        return {
            "type": "execution-failure",
            "quote": _first_sentence(text or run_text, 220),
            "diagnosis": "The attempt stops at the code result instead of explaining the failure and repair.",
            "why_bad": "In technical interviews, a failed run is recoverable only if you can isolate the cause and verify the fix.",
            "retry": "Explain the first failing line, the smallest fix, and one test that would catch it again.",
        }

    if len(words) < 45:
        return {
            "type": "too-short",
            "quote": _first_sentence(text, 220),
            "diagnosis": "The answer is too thin to prove judgment, ownership, and impact.",
            "why_bad": "A short answer makes the interviewer do the work of guessing your role, decision, and result.",
            "retry": "Rewrite it with a direct answer, proof, trade-off, and result.",
        }
    if not any(token in lower for token in ("i built", "i implemented", "i designed", "i owned", "my role", "i debugged")):
        return {
            "type": "missing-ownership",
            "quote": _first_sentence(text, 220),
            "diagnosis": "The answer describes work without making your personal ownership visible.",
            "why_bad": "Interviewers score your contribution, not the team's general activity.",
            "retry": "Add one sentence that starts with what you personally owned, built, designed, or debugged.",
        }
    if not any(token in lower for token in ("because", "trade-off", "alternative", "constraint", "edge case", "failure")):
        return {
            "type": "missing-tradeoff",
            "quote": _first_sentence(text, 220),
            "diagnosis": "The answer makes a claim without showing the constraint or trade-off behind the decision.",
            "why_bad": "Without a trade-off, the answer sounds memorized instead of based on engineering judgment.",
            "retry": "Add the constraint, rejected alternative, or edge case that shaped your decision.",
        }
    if not _contains_metric(lower):
        return {
            "type": "missing-result",
            "quote": _first_sentence(text, 220),
            "diagnosis": "The answer does not end with a concrete result, metric, or shipped signal.",
            "why_bad": "Interviewers need evidence that the work mattered beyond implementation activity.",
            "retry": "Close with a number, test result, shipped outcome, user impact, or measured improvement.",
        }
    if not any(token in lower for token in ("api", "database", "model", "cache", "queue", "complexity", "latency", "test", "runtime")):
        return {
            "type": "missing-technical-mechanism",
            "quote": _first_sentence(text, 220),
            "diagnosis": "The answer does not name the mechanism, data flow, algorithm, or implementation detail.",
            "why_bad": "A senior interviewer will follow up until they see whether you understand the system beneath the story.",
            "retry": "Add the technical mechanism and one reason that mechanism fit the problem.",
        }

    question_terms = {w.lower().strip(".,?!:;()") for w in prompt_question.split() if len(w) > 4}
    answer_terms = {w.lower().strip(".,?!:;()") for w in words if len(w) > 4}
    if question_terms and not (question_terms & answer_terms):
        return {
            "type": "off-topic",
            "quote": _first_sentence(text, 220),
            "diagnosis": "The answer does not clearly reuse the topic or ask from the question.",
            "why_bad": "Even a strong story loses value if it does not answer the interviewer's actual prompt.",
            "retry": "Start the first sentence by directly answering the question before adding context.",
        }

    return {
        "type": "structure-needs-polish",
        "quote": _first_sentence(text, 220),
        "diagnosis": "The answer has usable evidence but can be sharper and easier to follow.",
        "why_bad": "A loosely ordered answer makes good evidence harder for the interviewer to remember.",
        "retry": "Rewrite the same content in direct answer, ownership, mechanism, trade-off, result order.",
    }


def _build_better_structure(mode: str, diagnosis_type: str) -> List[str]:
    if mode == "chain_it":
        return ["Main answer in one sentence", "Specific proof from your work", "Likely follow-up question", "Follow-up answer with edge case and trade-off"]
    if mode == "blind_start":
        return ["Direct answer first", "One proof point", "One constraint or trade-off", "Stop with the result"]
    if mode == "best_vs_worst":
        return ["Name the weak line", "State the missing signal", "Rewrite with proof", "Close with measurable impact"]
    if mode == "say_it":
        return ["Direct answer", "One owned action", "One technical detail", "Metric or result within 60 seconds"]
    if diagnosis_type in {"boundary-condition", "identifier-mismatch", "execution-failure"}:
        return ["Name the exact failure", "Explain the smallest fix", "Run the edge case", "State complexity or trade-off"]
    return ["Direct answer", "Your exact ownership", "Technical mechanism or decision", "Constraint, trade-off, or edge case", "Metric, shipped outcome, or test signal"]


def _rewrite_example(prompt: Dict[str, Any], answer: str, structure: List[str], diagnosis: Dict[str, str]) -> str:
    question = _bounded(str(prompt.get("question") or prompt.get("prompt") or "the question"), 180)
    available = _first_sentence(answer, 260)
    if available:
        return (
            f"Direct answer to '{question}': {available} "
            "[Add your exact ownership here]. [Name the technical mechanism or decision]. "
            "[Add the trade-off or edge case]. [Close with the measured result or shipped signal]."
        )
    return (
        f"Direct answer to '{question}': [state the answer]. "
        "[Add your exact ownership]. [Name the technical mechanism]. "
        "[Add one trade-off or edge case]. [Close with a metric, test result, or shipped outcome]."
    )


def _next_drills_for_feedback(mode: str, diagnosis: Dict[str, str], skill_key: str) -> List[Dict[str, Any]]:
    diagnosis_type = diagnosis["type"]
    if diagnosis_type in {"boundary-condition", "identifier-mismatch", "execution-failure"}:
        return [{
            "mode": "fix_it",
            "title": "Repair the failure and prove the edge case",
            "reason": diagnosis["why_bad"],
            "success_criteria": ["failure explained", "smallest fix identified", "edge case tested"],
            "target_skill_key": skill_key,
        }]
    if diagnosis_type == "missing-tradeoff":
        return [{
            "mode": "chain_it",
            "title": "Add the follow-up trade-off",
            "reason": "The next interviewer question will probe the constraint behind your decision.",
            "success_criteria": ["main answer", "follow-up predicted", "trade-off answered"],
            "target_skill_key": skill_key,
        }]
    if diagnosis_type == "too-short":
        return [{
            "mode": "write_it",
            "title": "Build a complete five-line answer",
            "reason": "The current answer is too short to show proof and judgment.",
            "success_criteria": ["direct answer", "ownership", "mechanism", "trade-off", "result"],
            "target_skill_key": skill_key,
        }]
    return [{
        "mode": "best_vs_worst" if mode != "best_vs_worst" else "write_it",
        "title": "Rewrite the weakest answer shape",
        "reason": diagnosis["why_bad"],
        "success_criteria": ["weak line named", "better structure used", "rewritten answer includes proof"],
        "target_skill_key": skill_key,
    }]


def _normalize_structured_feedback(
    raw_feedback: Dict[str, Any],
    *,
    prompt: Dict[str, Any],
    answer: str,
    payload: Dict[str, Any],
    exercise_type: str,
    skill_key: str,
    previous_scores: List[float],
) -> Dict[str, Any]:
    diagnosis = _diagnose_attempt(prompt, answer, payload)
    raw_mistake = raw_feedback.get("mistake") if isinstance(raw_feedback.get("mistake"), dict) else {}
    mistake = {
        "type": _bounded(str(raw_mistake.get("type") or diagnosis["type"]), 80),
        "quote": _bounded(str(raw_mistake.get("quote") or diagnosis["quote"] or answer[:220]), 280),
        "diagnosis": _bounded(str(raw_mistake.get("diagnosis") or diagnosis["diagnosis"]), 700),
    }
    better_structure = _feedback_list(raw_feedback.get("better_structure"), _build_better_structure(exercise_type, mistake["type"]))
    improved_answer = _bounded(str(raw_feedback.get("improved_answer") or _rewrite_example(prompt, answer, better_structure, diagnosis)), 1800)
    next_drills = raw_feedback.get("next_drills")
    if not isinstance(next_drills, list) or not next_drills:
        next_drills = _next_drills_for_feedback(exercise_type, diagnosis, skill_key)
    normalized_drills = []
    for drill in next_drills[:3]:
        if not isinstance(drill, dict):
            continue
        normalized_drills.append({
            "mode": _slug(str(drill.get("mode") or "write_it"), "write_it")[:50],
            "title": _bounded(str(drill.get("title") or "Rewrite the answer"), 160),
            "reason": _bounded(str(drill.get("reason") or diagnosis["why_bad"]), 500),
            "success_criteria": _feedback_list(drill.get("success_criteria"), ["direct answer", "specific proof", "trade-off", "result"], 4),
            "target_skill_key": _bounded(str(drill.get("target_skill_key") or skill_key), 120),
        })
    last_score = previous_scores[0] if previous_scores else None
    score = _normalize_score(raw_feedback.get("score", 0)) if "score" in raw_feedback else None
    delta = round(score - last_score, 1) if score is not None and last_score is not None else None
    progress_signal = raw_feedback.get("progress_signal")
    if not progress_signal:
        if delta is None:
            progress_signal = "First saved attempt for this skill; future retries will show a trend."
        elif delta > 0:
            progress_signal = f"Improved by {delta} points versus the previous attempt on this skill."
        elif delta < 0:
            progress_signal = f"Dropped by {abs(delta)} points versus the previous attempt; tighten the structure before moving on."
        else:
            progress_signal = "No score movement yet; the next retry should target the same mistake."
    summary = _bounded(str(raw_feedback.get("summary") or diagnosis["diagnosis"]), 700)
    strengths = _feedback_list(raw_feedback.get("strengths"), [], 4)
    improvements = _feedback_list(raw_feedback.get("improvements"), [diagnosis["retry"]], 5)
    return {
        "summary": summary,
        "strengths": strengths,
        "improvements": improvements,
        "specific_feedback": _bounded(str(raw_feedback.get("specific_feedback") or diagnosis["retry"]), 700),
        "mistake": mistake,
        "why_bad": _bounded(str(raw_feedback.get("why_bad") or diagnosis["why_bad"]), 700),
        "better_structure": better_structure,
        "improved_answer": improved_answer,
        "next_drills": normalized_drills,
        "retry_instruction": _bounded(str(raw_feedback.get("retry_instruction") or diagnosis["retry"]), 700),
        "progress_signal": _bounded(str(progress_signal), 700),
        "progress_delta": delta,
    }


def _score_text_attempt(
    prompt: Dict[str, Any],
    answer: str,
    payload: Optional[Dict[str, Any]] = None,
    *,
    exercise_type: str = "write_it",
    skill_key: str = "general",
    previous_scores: Optional[List[float]] = None,
) -> Dict[str, Any]:
    payload = payload or {}
    previous_scores = previous_scores or []
    diagnosis = _diagnose_attempt(prompt, answer, payload)
    text = (answer or "").strip()
    lower = text.lower()
    words = text.split()
    strengths: List[str] = []
    improvements: List[str] = []
    score = 20 if words else 0

    if len(words) >= 45:
        score += 18
        strengths.append("complete enough to evaluate")
    else:
        improvements.append("write at least 45 words so the answer has claim, proof, and trade-off")
    if any(token in lower for token in ("i built", "i implemented", "i designed", "i owned", "my role", "i debugged")):
        score += 16
        strengths.append("ownership is visible")
    else:
        improvements.append("state your exact ownership")
    if any(token in lower for token in ("because", "trade-off", "alternative", "constraint", "edge case", "failure")):
        score += 16
        strengths.append("includes reasoning beyond a claim")
    else:
        improvements.append("add one trade-off, constraint, or edge case")
    if _contains_metric(lower):
        score += 14
        strengths.append("uses a concrete result")
    else:
        improvements.append("add a number, result, shipped outcome, or test signal")
    if any(token in lower for token in ("api", "database", "model", "cache", "queue", "complexity", "latency", "test", "runtime")):
        score += 12
        strengths.append("technical detail is present")
    else:
        improvements.append("name the technical mechanism, data flow, or algorithm")
    if prompt.get("question") and len(words) > 0:
        question_terms = {w.lower().strip(".,?!:;()") for w in str(prompt["question"]).split() if len(w) > 4}
        answer_terms = {w.lower().strip(".,?!:;()") for w in words if len(w) > 4}
        if question_terms & answer_terms:
            score += 8
            strengths.append("stays connected to the question")
        else:
            improvements.append("reuse the exact topic from the question in your first sentence")

    score = _clip(score)
    structured_feedback = _normalize_structured_feedback(
        {
            "score": score,
            "summary": "This answer is interview-ready enough to bank." if score >= PASS_SCORE else diagnosis["diagnosis"],
            "strengths": strengths[:3],
            "improvements": improvements[:4],
            "specific_feedback": improvements[0] if improvements else diagnosis["retry"],
        },
        prompt=prompt,
        answer=answer,
        payload=payload,
        exercise_type=exercise_type,
        skill_key=skill_key,
        previous_scores=previous_scores,
    )
    return {
        "score": score,
        "mastery_passed": score >= PASS_SCORE,
        "feedback": structured_feedback,
    }


def _attempt_payload_from_row(row: Any) -> Dict[str, Any]:
    feedback = _json_load(_row_get(row, 4, {}), {})
    return {
        "attempt_id": row[0],
        "exercise_id": row[1],
        "score": _normalize_score(row[2]),
        "passed": bool(row[3]),
        "mastery_passed": bool(row[3]),
        "specific_feedback": feedback.get("specific_feedback") if isinstance(feedback, dict) else None,
        "feedback": feedback if isinstance(feedback, dict) else {},
        "next_drills": feedback.get("next_drills", []) if isinstance(feedback, dict) else [],
        "progress_signal": feedback.get("progress_signal") if isinstance(feedback, dict) else None,
        "result_status": _row_get(row, 5, result_status_for_score(_normalize_score(row[2]))),
        "condition_results": _json_load(_row_get(row, 6, []), []),
        "passed_conditions": _json_load(_row_get(row, 7, []), []),
        "failed_conditions": _json_load(_row_get(row, 8, []), []),
        "score_components": _json_load(_row_get(row, 9, {}), {}),
    }


def _sync_skill_state_update(cursor: Any, user_id: str, skill_key: str, category: str, score: float) -> Dict[str, Any]:
    cursor.execute(
        """
        SELECT mastery_score, confidence_score, evidence_count
        FROM LearnerSkillStates
        WHERE user_id = %s AND skill_key = %s
        """,
        (user_id, skill_key),
    )
    row = cursor.fetchone()
    next_review_at = _next_review_for(score)
    if row:
        old_mastery = float(row[0] or 0)
        old_confidence = float(row[1] or 0)
        old_count = int(row[2] or 0)
        weight = 0.32 if old_count < 4 else 0.22
        mastery = _clip((old_mastery * (1 - weight)) + (score * weight))
        confidence = _clip(old_confidence + (10 if old_count < 4 else 4), 0, 100)
        cursor.execute(
            """
            UPDATE LearnerSkillStates
            SET skill_category = %s,
                mastery_score = %s,
                confidence_score = %s,
                evidence_count = evidence_count + 1,
                last_evidence_at = NOW(),
                next_review_at = %s,
                updated_at = NOW()
            WHERE user_id = %s AND skill_key = %s
            """,
            (category, mastery, confidence, next_review_at, user_id, skill_key),
        )
        evidence_count = old_count + 1
    else:
        mastery = _clip(score)
        confidence = 18.0
        evidence_count = 1
        cursor.execute(
            """
            INSERT INTO LearnerSkillStates (
                user_id, skill_key, skill_category, mastery_score, confidence_score,
                evidence_count, last_evidence_at, next_review_at
            )
            VALUES (%s, %s, %s, %s, %s, 1, NOW(), %s)
            """,
            (user_id, skill_key, category, mastery, confidence, next_review_at),
        )
    return {
        "skill_key": skill_key,
        "label": _label_from_key(skill_key),
        "mastery_score": mastery,
        "confidence_score": confidence,
        "evidence_count": evidence_count,
        "next_review_at": next_review_at.isoformat(),
    }


def _recalculate_mission_sync(cursor: Any, user_id: str, mission_id: str) -> Dict[str, Any]:
    cursor.execute(
        """
        SELECT ims.mission_skill_id, ims.skill_key, ims.baseline_score, ims.role_weight,
               ea.score, ea.activity_type, ea.is_checkpoint, ea.mastery_passed
        FROM ImprovementMissionSkills ims
        LEFT JOIN ExerciseAttempts ea
          ON ea.mission_skill_id = ims.mission_skill_id
         AND ea.user_id = ims.user_id
        WHERE ims.user_id = %s AND ims.mission_id = %s
        ORDER BY ea.created_at ASC NULLS LAST
        """,
        (user_id, mission_id),
    )
    by_skill: Dict[str, Dict[str, Any]] = {}
    for row in cursor.fetchall():
        skill_id = row[0]
        item = by_skill.setdefault(
            skill_id,
            {
                "mission_skill_id": skill_id,
                "skill_key": row[1],
                "baseline_score": float(row[2] or 0),
                "role_weight": float(row[3] or 1),
                "guided_scores": [],
                "variation_scores": [],
                "checkpoint_score": None,
                "guided_passes": 0,
                "variation_passes": 0,
                "latest_score": float(row[2] or 0),
                "mastery_status": "practising",
            },
        )
        if row[4] is None:
            continue
        score = float(row[4] or 0)
        activity_type = str(row[5] or "")
        passed = bool(row[7])
        if bool(row[6]) or activity_type == "unseen_checkpoint":
            item["checkpoint_score"] = score
        elif activity_type in {"guided_spoken_response", "rewrite_answer"}:
            item["variation_scores"].append(score)
            item["variation_passes"] += 1 if passed else 0
        else:
            item["guided_scores"].append(score)
            item["guided_passes"] += 1 if passed else 0

    skills = []
    for item in by_skill.values():
        latest = calculate_skill_score(
            baseline_score=item["baseline_score"],
            guided_scores=item["guided_scores"],
            variation_scores=item["variation_scores"],
            checkpoint_score=item["checkpoint_score"],
        )
        mastery = mastery_status_for_checkpoint(
            checkpoint_score=item["checkpoint_score"],
            guided_passes=item["guided_passes"],
            variation_passes=item["variation_passes"],
            current_status=item.get("mastery_status", "practising"),
        )
        cursor.execute(
            """
            UPDATE ImprovementMissionSkills
            SET latest_score = %s,
                mastery_status = %s,
                updated_at = NOW(),
                verified_at = CASE WHEN %s = 'verified' THEN COALESCE(verified_at, NOW()) ELSE NULL END,
                needs_reinforcement_at = CASE WHEN %s = 'needs_reinforcement' THEN NOW() ELSE needs_reinforcement_at END
            WHERE mission_skill_id = %s AND user_id = %s
            """,
            (latest, mastery, mastery, mastery, item["mission_skill_id"], user_id),
        )
        item["latest_score"] = latest
        item["mastery_status"] = mastery
        skills.append(item)

    cursor.execute(
        """
        SELECT roadmap_node_id, result_status, mastery_status, recovery_of_node_id
        FROM ImprovementRoadmapNodes
        WHERE user_id = %s AND mission_id = %s
        ORDER BY order_index
        """,
        (user_id, mission_id),
    )
    nodes = [
        {
            "roadmap_node_id": row[0],
            "result_status": row[1],
            "mastery_status": row[2],
            "recovery_of_node_id": row[3],
        }
        for row in cursor.fetchall()
    ]
    readiness = calculate_readiness(skills)
    progress = calculate_mission_progress(nodes, skills)
    checkpoint_scores = [item.get("checkpoint_score") for item in skills if item.get("checkpoint_score") is not None]
    checkpoint_failed = any(float(score) < PASS_SCORE for score in checkpoint_scores)
    checkpoint_passed = bool(checkpoint_scores) and all(float(score) >= PASS_SCORE for score in checkpoint_scores)
    if checkpoint_failed:
        validation_status = "needs_reinforcement"
    elif checkpoint_passed:
        # A held-out exercise proves the drill, not transfer to a later
        # interview. Mission completion is handled only by later evidence.
        validation_status = "validation_pending"
    elif skills and any(item["guided_passes"] or item["variation_passes"] for item in skills):
        validation_status = "checkpoint_pending"
    else:
        validation_status = "active"
    if validation_status == "validation_pending":
        # Reserve the final ten percent for independent later-interview proof.
        progress = min(progress, 90.0)
    elif validation_status == "needs_reinforcement":
        progress = min(progress, 85.0)
    mission_status = "active"
    cursor.execute(
        """
        UPDATE ImprovementMissions
        SET current_readiness = %s,
            progress_percent = %s,
            status = %s,
            validation_status = %s,
            updated_at = NOW()
        WHERE mission_id = %s AND user_id = %s
        """,
        (readiness, progress, mission_status, validation_status, mission_id, user_id),
    )
    return {
        "readiness": readiness,
        "progress_percent": progress,
        "mission_status": mission_status,
        "validation_status": validation_status,
        "skills": skills,
    }


def _insert_recovery_node_sync(
    cursor: Any,
    *,
    user_id: str,
    mission_id: str,
    mission_skill_id: str,
    source_node_id: str,
    skill_key: str,
    reason: str,
) -> Optional[str]:
    cursor.execute(
        """
        SELECT roadmap_node_id
        FROM ImprovementRoadmapNodes
        WHERE user_id = %s AND mission_id = %s AND recovery_of_node_id = %s
          AND result_status IN ('not_attempted', 'partial_pass', 'failed')
        LIMIT 1
        """,
        (user_id, mission_id, source_node_id),
    )
    if cursor.fetchone():
        return None
    cursor.execute(
        """
        SELECT order_index
        FROM ImprovementRoadmapNodes
        WHERE roadmap_node_id = %s AND user_id = %s AND mission_id = %s
        FOR UPDATE
        """,
        (source_node_id, user_id, mission_id),
    )
    source_row = cursor.fetchone()
    if not source_row:
        return None
    order_index = int(source_row[0] or 0) + 1
    cursor.execute(
        """
        UPDATE ImprovementRoadmapNodes
        SET order_index = order_index + 1, updated_at = NOW()
        WHERE user_id = %s AND mission_id = %s AND order_index >= %s
        """,
        (user_id, mission_id, order_index),
    )
    roadmap_node_id = str(uuid.uuid4())
    prompt = {
        "schema_version": "improve_activity_v1",
        "activity_type": "compare_answers",
        "title": "Reason Before Retrying",
        "question": "Which answer explains the reasoning more clearly before you retry?",
        "answers": [
            {"id": "a", "label": "Answer A", "text": "We used PostgreSQL because it is scalable."},
            {"id": "b", "label": "Answer B", "text": "We used PostgreSQL because the product needed relational candidate, interview, attempt, and report records with transactional consistency."},
        ],
        "correct_option": "b",
        "pass_conditions": [
            {"id": "choose_problem_first", "label": "Select the reasoning-backed answer", "weight": 2},
            {"id": "explain_reason", "label": "Explain the requirement behind the choice", "weight": 1},
        ],
        "source_evidence": [{"summary": reason}],
    }
    exercise_id = _create_improve_exercise_sync(
        cursor,
        user_id=user_id,
        mission_id=mission_id,
        mission_skill_id=mission_skill_id,
        roadmap_node_id=roadmap_node_id,
        interview_id=None,
        skill_key=skill_key,
        activity_type="compare_answers",
        prompt=prompt,
        order_index=order_index,
    )
    cursor.execute(
        """
        INSERT INTO ImprovementRoadmapNodes (
            roadmap_node_id, mission_id, user_id, mission_skill_id, exercise_id,
            recovery_of_node_id, order_index, title, description, activity_type,
            availability_status, attempt_status, result_status, mastery_status,
            estimated_minutes, expected_result, evidence_json
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, 'Reason Before Retrying', %s,
                'compare_answers', 'current', 'draft', 'not_attempted',
                'needs_reinforcement', 2, %s, %s)
        """,
        (
            roadmap_node_id,
            mission_id,
            user_id,
            mission_skill_id,
            exercise_id,
            source_node_id,
            order_index,
            "A two-minute recovery exercise inserted after a failed attempt.",
            "Explain the requirement behind a technical choice before retrying.",
            _safe_json({"summary": reason}),
        ),
    )
    return roadmap_node_id


async def _persist_mission_attempt_transaction(
    *,
    user_id: str,
    exercise_id: str,
    skill_key: str,
    exercise_type: str,
    payload: Dict[str, Any],
    answer: str,
    result: Dict[str, Any],
    mission_id: str,
    mission_skill_id: str,
    roadmap_node_id: str,
    activity_type: str,
    is_checkpoint: bool,
) -> Dict[str, Any]:
    def _run() -> Dict[str, Any]:
        conn = get_db_connection()
        cursor = conn.cursor()
        idempotency_key = str(payload.get("idempotency_key") or "").strip()
        attempt_session_id = str(payload.get("attempt_session_id") or "").strip()
        try:
            if len(idempotency_key) < 8:
                raise ValueError("A valid idempotency key is required")
            if not attempt_session_id:
                raise ValueError("An active attempt session is required")

            cursor.execute(
                """
                SELECT ge.exercise_id, node.availability_status,
                       node.recovery_of_node_id, mission.status, ge.status
                FROM GeneratedExercises ge
                JOIN ImprovementRoadmapNodes node ON node.roadmap_node_id = ge.roadmap_node_id
                JOIN ImprovementMissions mission ON mission.mission_id = ge.mission_id
                WHERE ge.exercise_id = %s
                  AND ge.user_id = %s
                  AND ge.mission_id = %s
                  AND node.user_id = %s
                  AND mission.user_id = %s
                  AND node.roadmap_node_id = %s
                FOR UPDATE OF node, mission
                """,
                (exercise_id, user_id, mission_id, user_id, user_id, roadmap_node_id),
            )
            ownership = cursor.fetchone()
            if not ownership:
                raise ValueError("Exercise does not belong to this user or mission")

            # Re-check after the node lock. Concurrent requests for the same
            # activity serialize here, so the loser returns the committed row
            # instead of surfacing a unique-index error or moving mastery twice.
            cursor.execute(
                """
                SELECT attempt_id, exercise_id, score, mastery_passed, feedback,
                       COALESCE(feedback->>'result_status', ''),
                       condition_results, passed_conditions, failed_conditions, score_components
                FROM ExerciseAttempts
                WHERE user_id = %s AND exercise_id = %s AND idempotency_key = %s
                LIMIT 1
                """,
                (user_id, exercise_id, idempotency_key),
            )
            existing = cursor.fetchone()
            if existing:
                conn.commit()
                return _attempt_payload_from_row(existing)

            if ownership[3] != "active":
                raise ValueError("The improvement mission is no longer active")
            if ownership[1] != "current":
                raise ValueError("This roadmap node is not the current activity")
            if ownership[4] not in {"queued", "in_progress"}:
                raise ValueError("This exercise is no longer available")

            cursor.execute(
                """
                SELECT attempt_session_id
                FROM ImprovementAttemptSessions
                WHERE attempt_session_id = %s
                  AND user_id = %s
                  AND mission_id = %s
                  AND roadmap_node_id = %s
                  AND exercise_id = %s
                  AND idempotency_key = %s
                  AND status IN ('draft', 'in_progress', 'save_failed')
                  AND (expires_at IS NULL OR expires_at > NOW())
                  AND (
                      deadline_at > NOW()
                      OR (deadline_at IS NULL AND status = 'in_progress')
                      OR (deadline_at IS NULL AND COALESCE(remaining_seconds, 0) > 0)
                  )
                FOR UPDATE
                """,
                (
                    attempt_session_id, user_id, mission_id, roadmap_node_id,
                    exercise_id, idempotency_key,
                ),
            )
            if not cursor.fetchone():
                raise ValueError("Attempt session is invalid, expired, or belongs to another activity")

            attempt_id = str(uuid.uuid4())
            final_feedback = dict(result.get("feedback") or {})
            result_status = result.get("result_status") or result_status_for_score(result["score"])
            final_feedback["result_status"] = result_status
            final_feedback["condition_summary"] = {
                "passed": result.get("passed_conditions", []),
                "failed": result.get("failed_conditions", []),
            }
            cursor.execute(
                """
                INSERT INTO ExerciseAttempts (
                    attempt_id, exercise_id, user_id, submitted_answer, submitted_payload,
                    submitted_answer_encrypted, submitted_payload_encrypted,
                    score, feedback, mastery_passed, attempt_session_id, idempotency_key,
                    mission_id, mission_skill_id, roadmap_node_id, activity_type,
                    is_checkpoint, condition_results, passed_conditions, failed_conditions,
                    score_components
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    attempt_id,
                    exercise_id,
                    user_id,
                    "[encrypted answer]" if answer else "",
                    _sensitive_json_marker(payload),
                    _encrypted_text_bytes(_bounded(answer, 8000)),
                    _encrypted_json_bytes(payload),
                    result["score"],
                    _safe_json(final_feedback),
                    bool(result["mastery_passed"]),
                    payload.get("attempt_session_id"),
                    idempotency_key or None,
                    mission_id,
                    mission_skill_id,
                    roadmap_node_id,
                    activity_type,
                    bool(is_checkpoint),
                    _safe_json(result.get("condition_results", [])),
                    _safe_json(result.get("passed_conditions", [])),
                    _safe_json(result.get("failed_conditions", [])),
                    _safe_json(result.get("score_components", {})),
                ),
            )
            node_mastery = (
                "held_out_passed" if is_checkpoint and result_status in {"passed", "strong_pass"}
                else "needs_reinforcement" if is_checkpoint and result_status not in {"passed", "strong_pass"}
                else "needs_reinforcement" if result_status == "failed"
                else "practising" if result_status == "partial_pass"
                else "ready_for_checkpoint"
            )
            cursor.execute(
                """
                UPDATE GeneratedExercises
                SET status = %s,
                    completed_at = CASE WHEN %s THEN COALESCE(completed_at, NOW()) ELSE completed_at END,
                    updated_at = NOW()
                WHERE exercise_id = %s AND user_id = %s
                """,
                ("completed" if result["mastery_passed"] else "in_progress", result["mastery_passed"], exercise_id, user_id),
            )
            cursor.execute(
                """
                UPDATE ImprovementRoadmapNodes
                SET attempt_status = 'submitted',
                    result_status = %s,
                    mastery_status = %s,
                    availability_status = CASE
                        WHEN %s IN ('passed', 'strong_pass') THEN 'completed'
                        ELSE availability_status
                    END,
                    completed_at = CASE WHEN %s THEN COALESCE(completed_at, NOW()) ELSE completed_at END,
                    updated_at = NOW()
                WHERE roadmap_node_id = %s AND user_id = %s
                """,
                (
                    result_status, node_mastery, result_status,
                    result["mastery_passed"], roadmap_node_id, user_id,
                ),
            )
            if is_checkpoint:
                validation_payload = {
                    "attempt_id": attempt_id,
                    "exercise_id": exercise_id,
                    "roadmap_node_id": roadmap_node_id,
                    "result_status": result_status,
                    "score_components": result.get("score_components", {}),
                }
                validation_hash = hashlib.sha256(
                    json.dumps(validation_payload, sort_keys=True, default=str).encode("utf-8")
                ).hexdigest()
                validation_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{mission_id}:{attempt_id}:held-out"))
                cursor.execute(
                    """
                    INSERT INTO MissionValidationEvidence (
                        validation_id, mission_id, user_id, roadmap_node_id,
                        evidence_type, passed, score, confidence, evidence_json,
                        source_key, evidence_hash
                    ) VALUES (%s, %s, %s, %s, 'held_out_variation', %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (mission_id, source_key, evidence_hash) DO NOTHING
                    """,
                    (
                        validation_id, mission_id, user_id, roadmap_node_id,
                        bool(result["mastery_passed"]), result["score"], 0.8,
                        _safe_json(validation_payload), f"attempt:{attempt_id}", validation_hash,
                    ),
                )
                cursor.execute(
                    """
                    UPDATE ImprovementMissions
                    SET validation_status = %s,
                        held_out_checkpoint_id = CASE WHEN %s THEN %s ELSE held_out_checkpoint_id END,
                        updated_at = NOW()
                    WHERE mission_id = %s AND user_id = %s
                    """,
                    (
                        "validation_pending" if result["mastery_passed"] else "needs_reinforcement",
                        bool(result["mastery_passed"]), roadmap_node_id, mission_id, user_id,
                    ),
                )
            if payload.get("attempt_session_id"):
                cursor.execute(
                    """
                    UPDATE ImprovementAttemptSessions
                    SET status = 'submitted', deadline_at = NULL,
                        remaining_seconds = 0, updated_at = NOW()
                    WHERE attempt_session_id = %s AND user_id = %s
                      AND mission_id = %s AND roadmap_node_id = %s
                      AND exercise_id = %s AND idempotency_key = %s
                    """,
                    (
                        attempt_session_id, user_id, mission_id, roadmap_node_id,
                        exercise_id, idempotency_key,
                    ),
                )

            if result_status in {"passed", "strong_pass"}:
                recovery_of_node_id = ownership[2]
                if recovery_of_node_id:
                    cursor.execute(
                        """
                        UPDATE ImprovementRoadmapNodes
                        SET availability_status = 'current',
                            attempt_status = 'draft',
                            updated_at = NOW()
                        WHERE roadmap_node_id = %s AND user_id = %s
                          AND mission_id = %s
                        """,
                        (recovery_of_node_id, user_id, mission_id),
                    )
                    _insert_mission_event_sync(
                        cursor,
                        user_id=user_id,
                        mission_id=mission_id,
                        event_type="recovery_completed",
                        payload={"retry_node_id": recovery_of_node_id, "from_attempt_id": attempt_id},
                        roadmap_node_id=recovery_of_node_id,
                        exercise_id=exercise_id,
                        attempt_id=attempt_id,
                    )
                else:
                    cursor.execute(
                        """
                        SELECT roadmap_node_id
                        FROM ImprovementRoadmapNodes
                        WHERE user_id = %s AND mission_id = %s
                          AND availability_status = 'locked'
                        ORDER BY order_index
                        LIMIT 1
                        """,
                        (user_id, mission_id),
                    )
                    next_row = cursor.fetchone()
                    if next_row:
                        cursor.execute(
                            """
                            UPDATE ImprovementRoadmapNodes
                            SET availability_status = 'current', updated_at = NOW()
                            WHERE roadmap_node_id = %s AND user_id = %s
                            """,
                            (next_row[0], user_id),
                        )
                        _insert_mission_event_sync(
                            cursor,
                            user_id=user_id,
                            mission_id=mission_id,
                            event_type="node_unlocked",
                            payload={"unlocked_node_id": next_row[0], "from_attempt_id": attempt_id},
                            roadmap_node_id=next_row[0],
                            exercise_id=exercise_id,
                            attempt_id=attempt_id,
                        )
            elif result_status == "failed" and not ownership[2]:
                cursor.execute(
                    """
                    UPDATE ImprovementRoadmapNodes
                    SET availability_status = 'blocked', updated_at = NOW()
                    WHERE roadmap_node_id = %s AND user_id = %s
                    """,
                    (roadmap_node_id, user_id),
                )
                recovery_id = _insert_recovery_node_sync(
                    cursor,
                    user_id=user_id,
                    mission_id=mission_id,
                    mission_skill_id=mission_skill_id,
                    source_node_id=roadmap_node_id,
                    skill_key=skill_key,
                    reason=final_feedback.get("specific_feedback") or "The target behavior was not yet demonstrated.",
                )
                if recovery_id:
                    _insert_mission_event_sync(
                        cursor,
                        user_id=user_id,
                        mission_id=mission_id,
                        event_type="remediation_inserted",
                        payload={"recovery_node_id": recovery_id, "source_node_id": roadmap_node_id},
                        roadmap_node_id=recovery_id,
                        exercise_id=exercise_id,
                        attempt_id=attempt_id,
                    )

            mastery = _sync_skill_state_update(cursor, user_id, skill_key, _skill_category(skill_key), float(result["score"]))
            recalculated = _recalculate_mission_sync(cursor, user_id, mission_id)
            _insert_mission_event_sync(
                cursor,
                user_id=user_id,
                mission_id=mission_id,
                event_type="attempt_submitted",
                payload={
                    "score": result["score"],
                    "result_status": result_status,
                    "readiness": recalculated["readiness"],
                    "progress_percent": recalculated["progress_percent"],
                },
                roadmap_node_id=roadmap_node_id,
                exercise_id=exercise_id,
                attempt_id=attempt_id,
            )
            conn.commit()
            logger.info(
                "improve_attempt_saved",
                extra={
                    "user_id": user_id,
                    "mission_id": mission_id,
                    "exercise_id": exercise_id,
                    "attempt_id": attempt_id,
                    "result_status": result_status,
                },
            )
            return {
                "attempt_id": attempt_id,
                "exercise_id": exercise_id,
                "score": result["score"],
                "passed": result["mastery_passed"],
                "mastery_passed": result["mastery_passed"],
                "specific_feedback": final_feedback.get("specific_feedback"),
                "feedback": final_feedback,
                "next_drills": final_feedback.get("next_drills", []),
                "progress_signal": final_feedback.get("progress_signal"),
                "next_review_at": mastery["next_review_at"],
                "next_review_time": mastery["next_review_at"],
                "updated_mastery": mastery,
                "result_status": result_status,
                "condition_results": result.get("condition_results", []),
                "passed_conditions": result.get("passed_conditions", []),
                "failed_conditions": result.get("failed_conditions", []),
                "score_components": result.get("score_components", {}),
                "mission_progress": recalculated,
            }
        except Exception:
            conn.rollback()
            logger.exception(
                "improve_attempt_save_failed",
                extra={"user_id": user_id, "mission_id": mission_id, "exercise_id": exercise_id},
            )
            raise
        finally:
            cursor.close()
            return_db_connection(conn)

    return await asyncio.to_thread(_run)


async def submit_exercise_attempt(
    user_id: str,
    exercise_id: str,
    submitted_answer: str,
    submitted_payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    row = await async_execute(
        """
        SELECT exercise_id, skill_key, exercise_type, prompt, rubric, status,
               mission_id, mission_skill_id, roadmap_node_id, activity_type, is_checkpoint
        FROM GeneratedExercises
        WHERE exercise_id = %s AND user_id = %s
        """,
        (exercise_id, user_id),
        fetchone=True,
    )
    if not row:
        raise ValueError("Exercise not found")

    prompt = _json_load(row[3], {})
    rubric = _json_load(row[4], {})
    skill_key = row[1] or f"exercise:{row[2]}"
    mission_id = _row_get(row, 6)
    mission_skill_id = _row_get(row, 7)
    roadmap_node_id = _row_get(row, 8)
    activity_type = _row_get(row, 9) or prompt.get("activity_type") or row[2]
    is_checkpoint = bool(_row_get(row, 10, False) or prompt.get("is_checkpoint") or activity_type == "unseen_checkpoint")
    payload = dict(submitted_payload or {})
    if mission_id and mission_skill_id and roadmap_node_id:
        if str(payload.get("mission_id") or "") != str(mission_id):
            raise ValueError("Attempt mission does not match the exercise")
        if str(payload.get("roadmap_node_id") or "") != str(roadmap_node_id):
            raise ValueError("Attempt roadmap node does not match the exercise")
        payload = _sanitize_mission_attempt_payload(str(activity_type), payload)
    answer = _attempt_text_from_payload(submitted_answer or "", payload)
    if not answer.strip():
        raise ValueError("Attempt must include real submitted work")
    previous_rows = await async_execute(
        """
        SELECT ea.score, ea.feedback, ea.created_at
        FROM ExerciseAttempts ea
        JOIN GeneratedExercises ge ON ge.exercise_id = ea.exercise_id
        WHERE ea.user_id = %s
          AND COALESCE(ge.skill_key, ge.exercise_type) = %s
        ORDER BY ea.created_at DESC
        LIMIT 5
        """,
        (user_id, skill_key),
        fetchall=True,
    )
    previous_scores = [float(row[0] or 0) for row in previous_rows or []]
    if mission_id and mission_skill_id and roadmap_node_id:
        result = _deterministic_activity_result(prompt, rubric, answer, payload, str(activity_type))
        return await _persist_mission_attempt_transaction(
            user_id=user_id,
            exercise_id=exercise_id,
            skill_key=skill_key,
            exercise_type=row[2],
            payload=payload,
            answer=answer,
            result=result,
            mission_id=str(mission_id),
            mission_skill_id=str(mission_skill_id),
            roadmap_node_id=str(roadmap_node_id),
            activity_type=str(activity_type),
            is_checkpoint=is_checkpoint,
        )

    try:
        model_payload = await complete_json_async(
            [
                {
                    "role": "system",
                    "content": (
                        "Evaluate an interview-prep exercise attempt. Return valid JSON with score, mastery_passed, "
                        "and feedback. feedback must include: summary, strengths, improvements, specific_feedback, "
                        "mistake {type, quote, diagnosis}, why_bad, better_structure, improved_answer, next_drills, "
                        "retry_instruction, and progress_signal. The improved_answer must use only facts present "
                        "in the provided exercise or attempt. If a required fact is missing, state that it is missing; "
                        "do not invent facts or fill placeholder values. "
                        f"{SYSTEM_DATA_BOUNDARY}"
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Rubric:\n{data_block('rubric', json.dumps(rubric, ensure_ascii=False))}\n\n"
                        f"Exercise:\n{data_block('exercise', json.dumps(prompt, ensure_ascii=False))}\n\n"
                        f"Previous scores for this skill:\n{data_block('previous_scores', json.dumps(previous_scores, ensure_ascii=False))}\n\n"
                        f"Attempt:\n{data_block('attempt', answer, 4000)}"
                    ),
                },
            ],
            event_type="exercise_attempt_evaluation",
            temperature=0.15,
            max_tokens=1300,
            provider_policy="local_required",
            metadata={"exercise_type": row[2]},
        )
        score = _normalize_score(model_payload.get("score", 0))
        raw_feedback = model_payload.get("feedback") if isinstance(model_payload.get("feedback"), dict) else {}
        raw_feedback["score"] = score
        structured_feedback = _normalize_structured_feedback(
            raw_feedback,
            prompt=prompt,
            answer=answer,
            payload=payload,
            exercise_type=row[2],
            skill_key=skill_key,
            previous_scores=previous_scores,
        )
        pass_score = _safe_float(rubric.get("pass_score"), PASS_SCORE)
        result = {
            "score": score,
            "mastery_passed": bool(model_payload.get("mastery_passed", score >= pass_score)),
            "feedback": structured_feedback,
        }
    except Exception:
        result = _score_text_attempt(
            prompt,
            answer,
            payload,
            exercise_type=row[2],
            skill_key=skill_key,
            previous_scores=previous_scores,
        )

    attempt_id = str(uuid.uuid4())
    await async_execute(
        """
        INSERT INTO ExerciseAttempts (
            attempt_id, exercise_id, user_id, submitted_answer, submitted_payload,
            submitted_answer_encrypted, submitted_payload_encrypted,
            score, feedback, mastery_passed
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            attempt_id,
            exercise_id,
            user_id,
            "[encrypted answer]" if answer else "",
            _sensitive_json_marker(payload),
            _encrypted_text_bytes(_bounded(answer, 8000)),
            _encrypted_json_bytes(payload),
            result["score"],
            json.dumps(result["feedback"]),
            result["mastery_passed"],
        ),
    )
    await async_execute(
        """
        UPDATE GeneratedExercises
        SET status = %s,
            completed_at = CASE WHEN %s THEN NOW() ELSE completed_at END,
            updated_at = NOW()
        WHERE exercise_id = %s AND user_id = %s
        """,
        ("completed" if result["mastery_passed"] else "in_progress", result["mastery_passed"], exercise_id, user_id),
    )
    mastery = await _upsert_skill_state(user_id, skill_key, _skill_category(skill_key), float(result["score"]))

    return {
        "attempt_id": attempt_id,
        "exercise_id": exercise_id,
        "score": result["score"],
        "passed": result["mastery_passed"],
        "mastery_passed": result["mastery_passed"],
        "specific_feedback": result["feedback"].get("specific_feedback"),
        "feedback": result["feedback"],
        "next_drills": result["feedback"].get("next_drills", []),
        "progress_signal": result["feedback"].get("progress_signal"),
        "next_review_at": mastery["next_review_at"],
        "next_review_time": mastery["next_review_at"],
        "updated_mastery": mastery,
    }


def _public_checkpoint_material(
    prompt: Any,
    rubric: Any,
    source_evidence: Any,
    is_checkpoint: bool,
) -> tuple[Dict[str, Any], Dict[str, Any], List[Any]]:
    public_prompt = dict(prompt) if isinstance(prompt, dict) else {}
    public_rubric = dict(rubric) if isinstance(rubric, dict) else {}
    public_evidence = list(source_evidence) if isinstance(source_evidence, list) else []
    if not is_checkpoint:
        return public_prompt, public_rubric, public_evidence
    hidden_prompt_fields = {
        "pass_conditions", "conditions", "rubric", "checks", "coaching",
        "hints", "model_answer", "expected_order", "correct_order",
        "success_criteria", "hidden_pass_criteria", "source_evidence",
    }
    return (
        {key: value for key, value in public_prompt.items() if key not in hidden_prompt_fields},
        {},
        [],
    )


def _exercise_from_row(row: Any) -> Dict[str, Any]:
    prompt = _json_load(row[4], {})
    rubric = _json_load(row[5], {})
    source_evidence = _json_load(row[6], [])
    activity_metadata = _json_load(_row_get(row, 16, {}), {})
    is_checkpoint = bool(_row_get(row, 15, False))
    prompt, rubric, source_evidence = _public_checkpoint_material(
        prompt, rubric, source_evidence, is_checkpoint,
    )
    exercise = {
        "exercise_id": row[0],
        "interview_id": row[1],
        "skill_key": row[2],
        "exercise_type": row[3],
        "exercise_mode": prompt.get("mode") or row[3],
        "input_type": prompt.get("input_type") or prompt.get("interaction_type") or "text",
        "timer_seconds": prompt.get("timer_seconds"),
        "title": prompt.get("title") or _label_from_key(row[2] or row[3]),
        "prompt": prompt,
        "rubric": rubric,
        "source_evidence": source_evidence if isinstance(source_evidence, list) else [],
        "status": row[7],
        "created_at": row[8].isoformat() if row[8] else None,
        "completed_at": row[9].isoformat() if row[9] else None,
        "mission_id": _row_get(row, 10),
        "mission_skill_id": _row_get(row, 11),
        "roadmap_node_id": _row_get(row, 12),
        "activity_type": _row_get(row, 13) or prompt.get("activity_type"),
        "variation_group": _row_get(row, 14),
        "is_checkpoint": is_checkpoint,
        "activity_metadata": activity_metadata if isinstance(activity_metadata, dict) else {},
    }
    exercise["drill"] = _drill_metadata(exercise)
    return exercise


def _completed_fixes(attempt_rows: List[Any]) -> List[Dict[str, Any]]:
    completed: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for row in attempt_rows:
        skill_key = row[0] or row[1] or "general"
        if skill_key in seen:
            continue
        seen.add(skill_key)
        score = _normalize_score(row[2])
        passed = bool(row[4])
        status_label = "Improved" if passed else "Still needs work"
        if not passed and score >= 60:
            status_label = "Improving"
        completed.append({
            "area": _label_from_key(str(skill_key)),
            "before": "Weak",
            "after": status_label,
            "score": score,
            "completed_at": row[5].isoformat() if row[5] else None,
        })
        if len(completed) >= 6:
            break
    return completed


def _active_mission_payload(cursor: Any, user_id: str, mode: Optional[str] = None) -> Optional[Dict[str, Any]]:
    mode_filter = "AND mode = %s" if mode else ""
    type_filter = ""
    if mode == "technical":
        type_filter = """
          AND weakness_type = 'technical_failure'
          AND COALESCE(weakness_key, '') LIKE 'technical:%%'
        """
    elif mode == "mock":
        type_filter = """
          AND COALESCE(weakness_type, '') <> 'technical_failure'
          AND COALESCE(weakness_key, '') NOT LIKE 'technical:%%'
          AND COALESCE(weakness_key, '') NOT LIKE 'algorithm:%%'
          AND COALESCE(weakness_key, '') NOT LIKE 'debugging:%%'
        """
    params: tuple[Any, ...] = (user_id, mode) if mode else (user_id,)
    cursor.execute(
        f"""
        SELECT mission_id, mission_type, title, assignment_reason, diagnosis_json,
               priority_score, priority_factors, baseline_readiness, current_readiness,
               target_readiness, progress_percent, status, created_at, updated_at,
               completed_at, mode, weakness_key, weakness_type, prediction_json,
               validation_status, validated_by_interview_id
        FROM ImprovementMissions
        WHERE user_id = %s {mode_filter} {type_filter} AND status = 'active'
        ORDER BY created_at DESC
        LIMIT 1
        """,
        params,
    )
    mission = cursor.fetchone()
    if not mission:
        return None
    mission_id = mission[0]
    cursor.execute(
        """
        SELECT mission_skill_id, skill_key, label, category, baseline_score,
               latest_score, target_score, role_weight, mastery_status,
               evidence_summary, criteria_json, verified_at, needs_reinforcement_at
        FROM ImprovementMissionSkills
        WHERE user_id = %s AND mission_id = %s
        ORDER BY created_at
        """,
        (user_id, mission_id),
    )
    skills = [
        {
            "mission_skill_id": row[0],
            "skill_key": row[1],
            "label": row[2],
            "category": row[3],
            "baseline_score": float(row[4] or 0),
            "latest_score": float(row[5] or 0),
            "target_score": float(row[6] or 0),
            "role_weight": float(row[7] or 1),
            "mastery_status": row[8],
            "evidence_summary": row[9],
            "criteria": _json_load(row[10], {}),
            "verified_at": _timestamp(row[11]),
            "needs_reinforcement_at": _timestamp(row[12]),
        }
        for row in cursor.fetchall()
    ]
    cursor.execute(
        """
        SELECT node.roadmap_node_id, node.mission_skill_id, node.exercise_id,
               node.recovery_of_node_id, node.order_index, node.title,
               node.description, node.activity_type, node.availability_status,
               node.attempt_status, node.result_status, node.mastery_status,
               node.estimated_minutes, node.expected_result, node.evidence_json,
               node.completed_at, ge.prompt, ge.rubric, ge.status
        FROM ImprovementRoadmapNodes node
        LEFT JOIN GeneratedExercises ge ON ge.exercise_id = node.exercise_id
        WHERE node.user_id = %s AND node.mission_id = %s
        ORDER BY node.order_index
        """,
        (user_id, mission_id),
    )
    roadmap = [
        {
            "roadmap_node_id": row[0],
            "mission_skill_id": row[1],
            "exercise_id": row[2],
            "recovery_of_node_id": row[3],
            "order_index": row[4],
            "title": row[5],
            "description": row[6],
            "activity_type": row[7],
            "availability_status": row[8],
            "attempt_status": row[9],
            "result_status": row[10],
            "mastery_status": row[11],
            "estimated_minutes": row[12],
            "expected_result": row[13],
            "evidence": _json_load(row[14], {}),
            "completed_at": _timestamp(row[15]),
            "activity": _json_load(row[16], {}) if row[16] is not None else None,
            "rubric": _json_load(row[17], {}) if row[17] is not None else {},
            "exercise_status": row[18],
        }
        for row in cursor.fetchall()
    ]
    for node in roadmap:
        is_checkpoint = node.get("activity_type") in {"checkpoint", "unseen_checkpoint"}
        activity, rubric, _ = _public_checkpoint_material(
            node.get("activity"), node.get("rubric"), [], is_checkpoint,
        )
        node["activity"] = activity
        node["rubric"] = rubric
    current_nodes = [node for node in roadmap if node.get("availability_status") == "current"]
    cursor.execute(
        """
        SELECT attempt_session_id, roadmap_node_id, exercise_id, status,
               draft_payload_encrypted, draft_payload, idempotency_key,
               deadline_at, remaining_seconds,
               updated_at, expires_at
        FROM ImprovementAttemptSessions
        WHERE user_id = %s AND mission_id = %s AND status IN ('draft', 'in_progress', 'save_failed')
          AND (expires_at IS NULL OR expires_at > NOW())
          AND EXISTS (
              SELECT 1
              FROM ImprovementRoadmapNodes node
              WHERE node.roadmap_node_id = ImprovementAttemptSessions.roadmap_node_id
                AND node.user_id = ImprovementAttemptSessions.user_id
                AND node.mission_id = ImprovementAttemptSessions.mission_id
                AND node.exercise_id = ImprovementAttemptSessions.exercise_id
                AND node.availability_status = 'current'
                AND node.result_status NOT IN ('passed', 'strong_pass')
          )
          AND (
              deadline_at > NOW()
              OR (deadline_at IS NULL AND COALESCE(remaining_seconds, 0) > 0)
              OR (deadline_at IS NULL AND remaining_seconds IS NULL)
          )
        ORDER BY updated_at DESC
        LIMIT 1
        """,
        (user_id, mission_id),
    )
    session = cursor.fetchone()
    active_session = None
    if session:
        active_session = {
            "attempt_session_id": session[0],
            "mission_id": mission_id,
            "roadmap_node_id": session[1],
            "exercise_id": session[2],
            "status": session[3],
            "draft_payload": _decrypt_sensitive_json(session[4], session[5]),
            "idempotency_key": session[6],
            "deadline_at": _timestamp(session[7]),
            "remaining_seconds": int(session[8]) if session[8] is not None else None,
            "updated_at": _timestamp(session[9]),
            "expires_at": _timestamp(session[10]),
        }
    return {
        "mission_id": mission_id,
        "mission_type": mission[1],
        "mode": mission[15] if len(mission) > 15 else "mock",
        "title": mission[2],
        "assignment_reason": mission[3],
        "diagnosis": _json_load(mission[4], {}),
        "weakness_key": mission[16] if len(mission) > 16 else None,
        "weakness_type": mission[17] if len(mission) > 17 else None,
        "priority_score": float(mission[5] or 0),
        "priority_factors": _json_load(mission[6], {}),
        "baseline_readiness": float(mission[7] or 0),
        "current_readiness": float(mission[8] or 0),
        "target_readiness": float(mission[9] or 0),
        "progress_percent": float(mission[10] or 0),
        "status": mission[11],
        "created_at": _timestamp(mission[12]),
        "updated_at": _timestamp(mission[13]),
        "completed_at": _timestamp(mission[14]),
        "prediction": _json_load(mission[18], {}) if len(mission) > 18 else {},
        "validation_status": mission[19] if len(mission) > 19 else None,
        "validated_by_interview_id": mission[20] if len(mission) > 20 else None,
        "skills": skills,
        "roadmap": roadmap,
        "active_attempt_session": active_session,
        "primary_action": (
            {
                "action": "continue",
                "roadmap_node_id": current_nodes[0].get("roadmap_node_id"),
                "exercise_id": current_nodes[0].get("exercise_id"),
                "label": "Continue",
            }
            if len(current_nodes) == 1
            else {
                "action": "official_reassessment" if mission[19] == "validation_pending" else "none",
                "roadmap_node_id": None,
                "exercise_id": None,
                "label": "Take a later official round" if mission[19] == "validation_pending" else "No action available",
            }
        ),
    }


def _improvement_history_payload(cursor: Any, user_id: str) -> Dict[str, Any]:
    cursor.execute(
        """
        SELECT ims.skill_key, ims.label, im.mode, im.weakness_key, im.weakness_type,
               ims.baseline_score, ims.latest_score,
               ims.mastery_status, ims.verified_at, ims.needs_reinforcement_at,
               COUNT(ea.attempt_id), MAX(ea.created_at),
               MAX(CASE WHEN ea.is_checkpoint THEN ea.score ELSE NULL END)
        FROM ImprovementMissionSkills ims
        JOIN ImprovementMissions im
          ON im.mission_id = ims.mission_id
         AND im.user_id = ims.user_id
        LEFT JOIN ExerciseAttempts ea
          ON ea.user_id = ims.user_id
         AND ea.mission_skill_id = ims.mission_skill_id
        WHERE ims.user_id = %s
          AND im.status IN ('active', 'completed')
        GROUP BY ims.skill_key, ims.label, im.mode, im.weakness_key, im.weakness_type,
                 ims.baseline_score, ims.latest_score,
                 ims.mastery_status, ims.verified_at, ims.needs_reinforcement_at,
                 ims.updated_at
        ORDER BY MAX(ea.created_at) DESC NULLS LAST, ims.updated_at DESC
        LIMIT 12
        """,
        (user_id,),
    )
    skills = [
        {
            "skill_key": row[0],
            "label": row[1],
            "mode": row[2],
            "weakness_key": row[3],
            "weakness_type": row[4],
            "baseline_score": float(row[5] or 0),
            "latest_score": float(row[6] or 0),
            "improvement": round(float(row[6] or 0) - float(row[5] or 0), 1),
            "verification_status": row[7],
            "verified_at": _timestamp(row[8]),
            "needs_reinforcement_at": _timestamp(row[9]),
            "attempt_count": int(row[10] or 0),
            "last_attempt_at": _timestamp(row[11]),
            "latest_checkpoint_score": float(row[12]) if row[12] is not None else None,
            "baseline_source": "mission_baseline",
        }
        for row in cursor.fetchall()
    ]
    if not skills:
        cursor.execute(
            """
            SELECT COALESCE(ge.skill_key, ge.exercise_type) AS skill_key,
                   MIN(ea.score), MAX(ea.score), COUNT(ea.attempt_id), MAX(ea.created_at)
            FROM ExerciseAttempts ea
            JOIN GeneratedExercises ge ON ge.exercise_id = ea.exercise_id
            WHERE ea.user_id = %s
            GROUP BY COALESCE(ge.skill_key, ge.exercise_type)
            ORDER BY MAX(ea.created_at) DESC
            LIMIT 12
            """,
            (user_id,),
        )
        skills = [
            {
                "skill_key": row[0],
                "label": _label_from_key(str(row[0])),
                "mode": "technical" if _skill_category(str(row[0])) == "technical" else "interview",
                "weakness_key": row[0],
                "weakness_type": "technical_failure" if _skill_category(str(row[0])) == "technical" else "interview_answer",
                "baseline_score": _normalize_score(row[1]),
                "latest_score": _normalize_score(row[2]),
                "improvement": round(_normalize_score(row[2]) - _normalize_score(row[1]), 1),
                "verification_status": "practice_only",
                "verified_at": None,
                "needs_reinforcement_at": None,
                "attempt_count": int(row[3] or 0),
                "last_attempt_at": _timestamp(row[4]),
                "latest_checkpoint_score": None,
                "baseline_source": "derived_from_earliest_attempt",
            }
            for row in cursor.fetchall()
        ]
    cursor.execute(
        """
        SELECT mission_id, title, mode, weakness_key, weakness_type,
               baseline_readiness, current_readiness,
               target_readiness, progress_percent, status, completed_at
        FROM ImprovementMissions
        WHERE user_id = %s AND status = 'completed'
        ORDER BY completed_at DESC NULLS LAST, updated_at DESC
        LIMIT 8
        """,
        (user_id,),
    )
    missions = [
        {
            "mission_id": row[0],
            "title": row[1],
            "mode": row[2],
            "weakness_key": row[3],
            "weakness_type": row[4],
            "baseline_readiness": float(row[5] or 0),
            "current_readiness": float(row[6] or 0),
            "target_readiness": float(row[7] or 0),
            "progress_percent": float(row[8] or 0),
            "status": row[9],
            "completed_at": _timestamp(row[10]),
            "improvement": round(float(row[6] or 0) - float(row[5] or 0), 1),
        }
        for row in cursor.fetchall()
    ]
    cursor.execute(
        """
        SELECT ea.attempt_id, ea.exercise_id, ea.mission_id, ea.roadmap_node_id,
               ea.activity_type, ea.score, ea.mastery_passed, ea.is_checkpoint,
               ea.created_at, ea.condition_results, ge.skill_key
        FROM ExerciseAttempts ea
        LEFT JOIN GeneratedExercises ge
          ON ge.exercise_id = ea.exercise_id
         AND ge.user_id = ea.user_id
        WHERE ea.user_id = %s
        ORDER BY ea.created_at DESC
        LIMIT 20
        """,
        (user_id,),
    )
    attempts = [
        {
            "attempt_id": row[0],
            "exercise_id": row[1],
            "mission_id": row[2],
            "roadmap_node_id": row[3],
            "activity_type": row[4],
            "score": _normalize_score(row[5]),
            "passed": bool(row[6]),
            "is_checkpoint": bool(row[7]),
            "created_at": _timestamp(row[8]),
            "condition_results": _json_load(row[9], []),
            "skill_key": row[10],
            "mode": "technical" if _skill_category(str(row[10] or "")) == "technical" else "interview",
        }
        for row in cursor.fetchall()
    ]
    return {
        "skills": skills,
        "completed_missions": missions,
        "recent_attempts": attempts,
        "has_history": bool(skills or missions or attempts),
    }


def build_learning_snapshot(cursor, user_id: str) -> Dict[str, Any]:
    cursor.execute(
        """
        SELECT skill_key, skill_category, mastery_score, confidence_score,
               evidence_count, last_evidence_at, next_review_at
        FROM LearnerSkillStates
        WHERE user_id = %s
        ORDER BY mastery_score ASC, next_review_at ASC NULLS FIRST
        LIMIT 12
        """,
        (user_id,),
    )
    skill_rows = cursor.fetchall()
    skill_gaps = [
        {
            "skill_key": row[0],
            "label": _label_from_key(row[0]),
            "category": row[1],
            "mastery_score": round(float(row[2] or 0), 1),
            "confidence_score": round(float(row[3] or 0), 1),
            "evidence_count": int(row[4] or 0),
            "last_evidence_at": row[5].isoformat() if row[5] else None,
            "next_review_at": row[6].isoformat() if row[6] else None,
            "why_it_matters": f"Interviewers can still expose weak depth in {_label_from_key(row[0])}.",
        }
        for row in skill_rows
    ]

    cursor.execute(
        """
        SELECT cluster_id, round_id, mistake_type, mistake_key, examples,
               occurrence_count, last_seen_at
        FROM TechnicalMistakeClusters
        WHERE user_id = %s
        ORDER BY occurrence_count DESC, last_seen_at DESC
        LIMIT 8
        """,
        (user_id,),
    )
    technical_mistakes = []
    for row in cursor.fetchall():
        examples = _json_load(row[4], [])
        first = examples[0] if isinstance(examples, list) and examples else {}
        summary = _readable_evidence_value(first.get("summary")) if isinstance(first, dict) else ""
        repair_action = _readable_evidence_value(first.get("repair_action")) if isinstance(first, dict) else ""
        pattern = _readable_evidence_value(first.get("algorithm_pattern")) if isinstance(first, dict) else ""
        problem_title = _readable_evidence_value(first.get("problem_title")) if isinstance(first, dict) else ""
        skill_key = (
            first.get("skill_key")
            if isinstance(first, dict) and first.get("skill_key")
            else f"technical:{_slug(pattern or problem_title or row[3])}"
        )
        topic_label = _label_from_key(str(skill_key))
        technical_mistakes.append({
            "cluster_id": row[0],
            "round_id": row[1],
            "mistake_type": str(row[2] or "").replace("-", " ").title(),
            "mistake_key": row[3],
            "skill_key": skill_key,
            "topic_label": topic_label,
            "summary": summary or row[3],
            "repair_action": repair_action or "Redo this attempt with a smaller failing case.",
            "examples": examples if isinstance(examples, list) else [],
            "occurrence_count": int(row[5] or 0),
            "last_seen_at": row[6].isoformat() if row[6] else None,
        })

    if technical_mistakes:
        technical_focus_keys = {
            str(item.get("skill_key") or "")
            for item in technical_mistakes
            if item.get("skill_key")
        }
        filtered_skill_gaps: List[Dict[str, Any]] = []
        seen_gap_keys = set()
        for gap in skill_gaps:
            key = str(gap.get("skill_key") or "")
            is_technical_gap = gap.get("category") == "technical" or _is_technical_skill_key(key)
            if is_technical_gap and key not in technical_focus_keys:
                continue
            filtered_skill_gaps.append(gap)
            seen_gap_keys.add(key)

        for mistake in technical_mistakes:
            key = str(mistake.get("skill_key") or "")
            if not key or key in seen_gap_keys:
                continue
            label = str(mistake.get("topic_label") or _label_from_key(key))
            occurrence_count = int(mistake.get("occurrence_count") or 1)
            filtered_skill_gaps.append({
                "skill_key": key,
                "label": label,
                "category": "technical",
                "mastery_score": 38.0,
                "confidence_score": min(95.0, 35.0 + occurrence_count * 10.0),
                "evidence_count": occurrence_count,
                "last_evidence_at": mistake.get("last_seen_at"),
                "next_review_at": None,
                "why_it_matters": f"Your latest technical run shows repeated weakness in {label}.",
            })
            seen_gap_keys.add(key)

        skill_gaps = sorted(
            filtered_skill_gaps,
            key=lambda gap: (float(gap.get("mastery_score") or 0), str(gap.get("label") or "")),
        )[:12]

    cursor.execute(
        """
        SELECT gap_id, project_key, gap_key, gap_summary, evidence,
               status, next_check_at, updated_at
        FROM ProjectKnowledgeGaps
        WHERE user_id = %s AND status = 'open'
        ORDER BY next_check_at ASC NULLS FIRST, updated_at DESC
        LIMIT 8
        """,
        (user_id,),
    )
    project_homework = [
        {
            "gap_id": row[0],
            "project_key": row[1],
            "gap_key": row[2],
            "title": row[3],
            "evidence": _json_load(row[4], {}),
            "status": row[5],
            "next_check_at": row[6].isoformat() if row[6] else None,
            "updated_at": row[7].isoformat() if row[7] else None,
        }
        for row in cursor.fetchall()
    ]

    interview_skill_gaps = [
        gap for gap in skill_gaps
        if gap.get("category") != "technical" and not _is_technical_skill_key(str(gap.get("skill_key") or ""))
    ]
    _ensure_active_improvement_mission(cursor, user_id, interview_skill_gaps, [], project_homework, mode="mock")
    _ensure_active_improvement_mission(cursor, user_id, [], technical_mistakes, [], mode="technical")

    cursor.execute(
        """
        SELECT exercise_id, interview_id, skill_key, exercise_type, prompt,
               rubric, source_evidence, status, created_at, completed_at,
               mission_id, mission_skill_id, roadmap_node_id, activity_type,
               variation_group, is_checkpoint, activity_metadata
        FROM GeneratedExercises
        WHERE user_id = %s
          AND status IN ('queued', 'in_progress')
          AND mission_id IS NOT NULL
          AND EXISTS (
              SELECT 1
              FROM ImprovementMissions mission
              WHERE mission.mission_id = GeneratedExercises.mission_id
                AND mission.user_id = GeneratedExercises.user_id
                AND mission.status = 'active'
          )
        ORDER BY
            CASE WHEN status = 'in_progress' THEN 0 ELSE 1 END,
            created_at DESC
        LIMIT 12
        """,
        (user_id,),
    )
    exercise_queue = [_exercise_from_row(row) for row in cursor.fetchall()]

    cursor.execute(
        """
        SELECT ge.skill_key, ge.exercise_type, ea.score, ea.feedback,
               ea.mastery_passed, ea.created_at
        FROM ExerciseAttempts ea
        JOIN GeneratedExercises ge ON ge.exercise_id = ea.exercise_id
        WHERE ea.user_id = %s
        ORDER BY ea.created_at DESC
        LIMIT 60
        """,
        (user_id,),
    )
    attempt_rows = cursor.fetchall()
    mistake_counts: Counter[str] = Counter()
    skill_attempts: Dict[str, List[Dict[str, Any]]] = {}
    mode_attempts: Dict[str, List[Dict[str, Any]]] = {}
    latest_attempt = None
    for row in attempt_rows:
        feedback = _json_load(row[3], {})
        mistake = feedback.get("mistake") if isinstance(feedback, dict) else {}
        mistake_type = str((mistake.get("type") if isinstance(mistake, dict) else None) or "needs-structure")
        mistake_counts.update([mistake_type])
        item = {
            "skill_key": row[0],
            "exercise_type": row[1],
            "score": round(float(row[2] or 0), 1),
            "mistake_type": mistake_type,
            "mastery_passed": bool(row[4]),
            "created_at": row[5].isoformat() if row[5] else None,
            "progress_signal": feedback.get("progress_signal") if isinstance(feedback, dict) else None,
        }
        if latest_attempt is None:
            latest_attempt = item
        skill_attempts.setdefault(row[0] or row[1] or "general", []).append(item)
        mode_attempts.setdefault(row[1] or "general", []).append(item)

    for gap in skill_gaps:
        attempts = skill_attempts.get(gap["skill_key"], [])
        if attempts:
            latest = attempts[0]
            older = attempts[-1] if len(attempts) > 1 else None
            gap["last_attempt_score"] = latest["score"]
            gap["repeated_mistake"] = latest["mistake_type"].replace("-", " ")
            gap["trend_label"] = (
                f"up {round(latest['score'] - older['score'], 1)} pts over {len(attempts)} attempts"
                if older and latest["score"] > older["score"]
                else f"down {round(older['score'] - latest['score'], 1)} pts over {len(attempts)} attempts"
                if older and latest["score"] < older["score"]
                else "first tracked attempt" if len(attempts) == 1 else "flat across recent attempts"
            )

    mode_stats = []
    for mode, attempts in mode_attempts.items():
        passed = sum(1 for item in attempts if item["mastery_passed"])
        latest = attempts[0]
        oldest = attempts[-1]
        mode_stats.append({
            "mode": mode,
            "attempt_count": len(attempts),
            "pass_rate": round((passed / len(attempts)) * 100, 1) if attempts else 0,
            "latest_score": latest["score"],
            "score_delta": round(latest["score"] - oldest["score"], 1) if len(attempts) > 1 else None,
        })

    top_mistake = mistake_counts.most_common(1)[0][0] if mistake_counts else None
    progress_summary = (
        f"Most repeated mistake: {top_mistake.replace('-', ' ')} across {mistake_counts[top_mistake]} recent attempts."
        if top_mistake
        else "No exercise attempts tracked yet."
    )

    cursor.execute(
        """
        SELECT event_type, severity, COUNT(*), MAX(created_at)
        FROM MalpracticeEvents
        WHERE user_id = %s
        GROUP BY event_type, severity
        ORDER BY MAX(created_at) DESC
        """,
        (user_id,),
    )
    integrity_rows = cursor.fetchall()
    severe_count = sum(int(row[2] or 0) for row in integrity_rows if row[1] == "severe" or row[0] in SEVERE_EVENT_TYPES)
    warning_count = sum(int(row[2] or 0) for row in integrity_rows if row[1] != "severe" and row[0] not in SEVERE_EVENT_TYPES)
    integrity_status = {
        "status": "flagged" if severe_count else "watched" if warning_count else "clean",
        "severe_count": severe_count,
        "warning_count": warning_count,
        "events": [
            {
                "event_type": row[0],
                "severity": row[1],
                "count": int(row[2] or 0),
                "last_seen_at": row[3].isoformat() if row[3] else None,
            }
            for row in integrity_rows[:8]
        ],
    }

    weakest = skill_gaps[0] if skill_gaps else None
    next_exercise = exercise_queue[0] if exercise_queue else None
    if next_exercise:
        headline = f"Your next useful rep is {next_exercise['title']}."
        next_step = next_exercise["prompt"].get("prompt") or "Complete the first queued exercise."
    elif weakest:
        headline = f"Your weakest current area is {weakest['label']}."
        next_step = f"Run one focused mock or technical round targeting {weakest['label']}."
    else:
        headline = "No learner evidence yet."
        next_step = "Complete one mock interview or technical round so the coach can assign real practice."

    blocker = (
        technical_mistakes[0]["summary"]
        if technical_mistakes
        else project_homework[0]["title"]
        if project_homework
        else weakest["why_it_matters"]
        if weakest
        else "The system needs one real attempt before it can diagnose you."
    )

    student_summary_payload = {
        "headline": headline,
        "blocker": blocker,
        "next_step": next_step,
        "integrity": integrity_status["status"],
    }
    completed_fixes = _completed_fixes(attempt_rows)
    active_missions = {
        "interview": _active_mission_payload(cursor, user_id, mode="mock"),
        "technical": _active_mission_payload(cursor, user_id, mode="technical"),
    }
    active_mission = active_missions["interview"] or active_missions["technical"]
    improvement_history = _improvement_history_payload(cursor, user_id)

    return {
        "student_summary": student_summary_payload,
        "completed_fixes": completed_fixes,
        "practice_loop": {
            "active_drill": next_exercise,
            "latest_attempt": latest_attempt,
            "repeated_mistake": top_mistake,
            "progress_summary": progress_summary,
            "mode_stats": mode_stats[:8],
        },
        "skill_gaps": skill_gaps,
        "technical_mistakes": technical_mistakes,
        "project_homework": project_homework,
        "exercise_queue": exercise_queue,
        "active_mission": active_mission,
        "active_missions": active_missions,
        "roadmap": active_mission.get("roadmap", []) if active_mission else [],
        "improvement_history": improvement_history,
        "integrity_status": integrity_status,
    }
