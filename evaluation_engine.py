"""Deterministic-first answer evaluation with selective semantic analysis.

The deterministic layer owns measurable signals, score aggregation, and the
follow-up action.  The language model is an optional evidence extractor for
meaning and factual coverage; it never chooses routing or supplies a score.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import re
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from prompt_security import SYSTEM_DATA_BOUNDARY, data_block


logger = logging.getLogger("evaluation_engine")

EVALUATION_VERSION = "answer_evaluation.v2"
SEMANTIC_EVENT_TYPE = "answer_semantic_evaluation"
SEMANTIC_TIMEOUT_SECONDS = 6.0
MAX_QUESTION_CHARS = 4_000
MAX_ANSWER_ANALYSIS_CHARS = 16_000
MAX_PROMPT_CONTEXT_CHARS = 5_000

FOLLOW_UP_ACTIONS = (
    "clarify",
    "simplify_prerequisite",
    "probe_evidence",
    "challenge_tradeoff",
    "verify_contradiction",
    "advance",
)

SEMANTIC_RESPONSE_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "covered_points",
        "missed_points",
        "incorrect_claims",
        "contradictions",
        "evidence_quotes",
        "semantic_confidence",
        "answer_relevant",
        "suggested_followup",
    ],
    "properties": {
        "covered_points": {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": 12,
        },
        "missed_points": {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": 12,
        },
        "incorrect_claims": {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": 8,
        },
        "contradictions": {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": 8,
        },
        "evidence_quotes": {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": 8,
        },
        "semantic_confidence": {
            "type": "number",
            "minimum": 0,
            "maximum": 1,
        },
        "answer_relevant": {
            "type": "boolean",
        },
        "suggested_followup": {
            "anyOf": [
                {"type": "string"},
                {"type": "null"},
            ]
        },
    },
}

# Weights are renormalized over scores that are actually available.  In
# particular, technical_accuracy is absent without a valid semantic result.
SCORE_WEIGHTS: Dict[str, float] = {
    "technical_accuracy": 0.30,
    "relevance": 0.20,
    "structure": 0.12,
    "ownership": 0.08,
    "specificity_evidence": 0.14,
    "filler_control": 0.06,
    "directness": 0.07,
    "tradeoffs": 0.03,
}

# These are the product rubrics. Unknown required dimensions stay ``None``;
# they are never renormalized away into an authoritative score.
QUESTION_TYPE_WEIGHTS: Dict[str, Dict[str, float]] = {
    "technical_concept": {
        "correctness": 0.30,
        "depth": 0.20,
        "application": 0.15,
        "trade_offs": 0.15,
        "failure_modes": 0.10,
        "communication": 0.10,
    },
    "project_explanation": {
        "contribution": 0.20,
        "architecture_data_flow": 0.20,
        "decisions_trade_offs": 0.15,
        "outcome_evaluation": 0.15,
        "relevance": 0.15,
        "communication": 0.10,
        "limitations": 0.05,
    },
    "behavioral": {
        "star_structure": 0.25,
        "relevance": 0.20,
        "ownership": 0.15,
        "specificity": 0.15,
        "result_learning": 0.15,
        "communication": 0.10,
    },
    "coding": {
        "passed_tests": 0.35,
        "approach": 0.15,
        "efficiency": 0.15,
        "edge_cases": 0.10,
        "debugging": 0.10,
        "explanation": 0.10,
        "code_quality": 0.05,
    },
}

_WORD_RE = re.compile(r"[A-Za-z0-9]+(?:['\N{RIGHT SINGLE QUOTATION MARK}-][A-Za-z0-9]+)?")
_SENTENCE_RE = re.compile(r"[^.!?\n]+(?:[.!?]+|$)")

_STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "because", "been", "being",
    "but", "by", "can", "could", "did", "do", "does", "for", "from", "had",
    "has", "have", "how", "i", "if", "in", "into", "is", "it", "its", "me",
    "my", "of", "on", "or", "our", "should", "so", "that", "the", "their",
    "then", "there", "these", "they", "this", "to", "us", "was", "we", "were",
    "what", "when", "where", "which", "who", "why", "will", "with", "would",
    "you", "your",
}

_FILLER_PATTERNS: Tuple[Tuple[str, re.Pattern[str]], ...] = tuple(
    (label, re.compile(pattern, re.IGNORECASE))
    for label, pattern in (
        ("um", r"\bum+\b"),
        ("uh", r"\buh+\b"),
        ("you know", r"\byou\s+know\b"),
        ("basically", r"\bbasically\b"),
        ("actually", r"\bactually\b"),
        ("kind of", r"\bkind\s+of\b"),
        ("sort of", r"\bsort\s+of\b"),
        ("I mean", r"\bi\s+mean\b"),
        ("like", r"\blike\b"),
    )
)

_ACTION_VERBS = (
    "analyzed", "automated", "built", "changed", "configured", "created",
    "debugged", "deployed", "designed", "developed", "diagnosed", "drove",
    "fixed", "implemented", "improved", "introduced", "led", "measured",
    "migrated", "optimized", "owned", "planned", "reduced", "refactored",
    "resolved", "shipped", "tested", "validated", "wrote",
)

_STAR_PATTERNS: Dict[str, re.Pattern[str]] = {
    "situation": re.compile(
        r"\b(?:situation|context|background|during|at the time|when (?:i|we)|on (?:a|the) project)\b",
        re.IGNORECASE,
    ),
    "task": re.compile(
        r"\b(?:task|goal|objective|challenge|problem|responsib(?:le|ility)|needed to|had to)\b",
        re.IGNORECASE,
    ),
    "action": re.compile(
        rf"\b(?:i|we)\s+(?:personally\s+)?(?:{'|'.join(_ACTION_VERBS)})\b",
        re.IGNORECASE,
    ),
    "result": re.compile(
        r"\b(?:result|outcome|impact|achieved|increased|decreased|reduced|saved|improved|grew|led to)\b",
        re.IGNORECASE,
    ),
}

_ORGANIZATION_PATTERNS: Dict[str, re.Pattern[str]] = {
    "sequence": re.compile(r"\b(?:first|second|next|then|finally|step|phase)\b", re.IGNORECASE),
    "reason": re.compile(r"\b(?:because|since|therefore|so that|which meant|as a result)\b", re.IGNORECASE),
    "example": re.compile(r"\b(?:for example|for instance|specifically|such as)\b", re.IGNORECASE),
    "contrast": re.compile(r"\b(?:however|although|whereas|in contrast|on the other hand)\b", re.IGNORECASE),
}

_TRADEOFF_PATTERNS: Dict[str, re.Pattern[str]] = {
    "explicit": re.compile(r"\b(?:trade[ -]?offs?|pros? and cons?|downside|drawback)\b", re.IGNORECASE),
    "contrast": re.compile(r"\b(?:however|although|whereas|on the other hand|but)\b", re.IGNORECASE),
    "cost": re.compile(r"\b(?:cost|latency|complexity|memory|performance|maintainability|reliability|accuracy)\b", re.IGNORECASE),
    "alternative": re.compile(r"\b(?:alternative|instead of|compared (?:with|to)|versus|option)\b", re.IGNORECASE),
    "constraint": re.compile(r"\b(?:constraint|limit(?:ation)?|risk|scale|edge case)\b", re.IGNORECASE),
}
_FAILURE_MODE_RE = re.compile(
    r"\b(?:failure|failure mode|edge case|invalid|timeout|retry|rollback|fallback|"
    r"degrad(?:e|ation)|outage|race condition|deadlock|overflow|underflow|partial)\b",
    re.IGNORECASE,
)
_LEARNING_RE = re.compile(
    r"\b(?:learn(?:ed|t|ing)?|lesson|retrospective|next time|would now|improved afterward)\b",
    re.IGNORECASE,
)

_OWNERSHIP_QUESTION_RE = re.compile(
    r"\b(?:you|your|contribution|role|ownership|experience|project|tell me about|describe a time)\b",
    re.IGNORECASE,
)
_EVIDENCE_QUESTION_RE = re.compile(
    r"\b(?:example|evidence|impact|result|measure|metric|project|experience|tell me about|describe a time|how did you)\b",
    re.IGNORECASE,
)
_TRADEOFF_QUESTION_RE = re.compile(
    r"\b(?:trade[ -]?off|compare|versus|choose|choice|why did|design|architecture|scal(?:e|ability)|optimi[sz]|alternative|constraint)\b",
    re.IGNORECASE,
)
_COMPLEX_QUESTION_RE = re.compile(
    r"\b(?:explain|describe|how|why|compare|design|debug|evaluate|analy[sz]e|tell me about)\b",
    re.IGNORECASE,
)

_SEMANTIC_RUBRIC_KEYS = {
    "answer_guide",
    "correct_answer",
    "criteria",
    "expected_answer",
    "expected_points",
    "facts",
    "factual_claims",
    "ideal_answer",
    "key_points",
    "must_cover",
    "rubric_points",
}


async def complete_json_async(*args: Any, **kwargs: Any) -> Dict[str, Any]:
    """Import the configured router only when the semantic policy uses it.

    This keeps the deterministic evaluator importable in workers and tests that
    intentionally do not load production secrets or an OpenAI client.
    """

    from llm_router import complete_json_async as routed_complete_json_async

    return await routed_complete_json_async(*args, **kwargs)


def _bounded_text(value: Any, limit: int) -> str:
    if value is None:
        return ""
    try:
        text = str(value)
    except Exception:
        return ""
    return text.strip()[:limit]


def _words(text: str) -> List[str]:
    return [match.group(0).lower() for match in _WORD_RE.finditer(text or "")]


def _content_terms(text: str) -> set[str]:
    return {
        token
        for token in _words(text)
        if len(token) >= 3 and token not in _STOP_WORDS and not token.isdigit()
    }


def _extract_text_fragments(value: Any, *, limit: int = 120) -> List[str]:
    """Flatten bounded JSON-like content without trusting its shape."""

    fragments: List[str] = []
    seen: set[int] = set()

    def visit(item: Any) -> None:
        if len(fragments) >= limit or item is None:
            return
        if isinstance(item, str):
            cleaned = item.strip()
            if cleaned:
                fragments.append(cleaned[:500])
            return
        if isinstance(item, (int, float, bool)):
            return
        item_id = id(item)
        if item_id in seen:
            return
        if isinstance(item, Mapping):
            seen.add(item_id)
            for key, nested in item.items():
                if isinstance(key, str) and key.lower() not in {
                    "weight", "score", "id", "version", "enabled", "required",
                }:
                    fragments.append(key.replace("_", " ")[:120])
                visit(nested)
                if len(fragments) >= limit:
                    break
            return
        if isinstance(item, Sequence) and not isinstance(item, (str, bytes, bytearray)):
            seen.add(item_id)
            for nested in item:
                visit(nested)
                if len(fragments) >= limit:
                    break

    visit(value)
    return fragments[:limit]


def _score_from_overlap(matched: int, total: int) -> float:
    if total <= 0 or matched <= 0:
        return 0.0
    return min(100.0, 15.0 + (85.0 * matched / total))


def _lexical_relevance(question: str, answer: str, rubric: Mapping[str, Any]) -> Dict[str, Any]:
    question_terms = _content_terms(question)
    rubric_text = " ".join(_extract_text_fragments(rubric))
    rubric_terms = _content_terms(rubric_text) - question_terms
    answer_terms = _content_terms(answer)
    matched_question = sorted(question_terms & answer_terms)
    matched_rubric = sorted(rubric_terms & answer_terms)

    question_score = _score_from_overlap(len(matched_question), len(question_terms))
    rubric_score = _score_from_overlap(len(matched_rubric), len(rubric_terms))
    if question_terms and rubric_terms:
        score = (question_score * 0.72) + (rubric_score * 0.28)
    elif question_terms:
        score = question_score
    elif rubric_terms:
        score = rubric_score
    else:
        # There are no lexical anchors.  This is explicitly neutral rather than
        # evidence that the answer is relevant or irrelevant.
        score = 50.0 if answer.strip() else 0.0

    return {
        "score": round(score, 1),
        "question_term_count": len(question_terms),
        "rubric_term_count": len(rubric_terms),
        "matched_question_terms": matched_question[:20],
        "matched_rubric_terms": matched_rubric[:20],
    }


def _structure_signal(answer: str) -> Dict[str, Any]:
    if not answer.strip():
        return {
            "score": 0.0,
            "star_markers": [],
            "organization_markers": [],
            "sentence_count": 0,
        }
    star_markers = [name for name, pattern in _STAR_PATTERNS.items() if pattern.search(answer)]
    organization_markers = [
        name for name, pattern in _ORGANIZATION_PATTERNS.items() if pattern.search(answer)
    ]
    sentence_count = sum(1 for match in _SENTENCE_RE.finditer(answer) if match.group(0).strip())
    paragraph_count = len([part for part in re.split(r"\n\s*\n", answer) if part.strip()])
    score = 10 + (len(star_markers) * 15) + (len(organization_markers) * 7)
    if sentence_count >= 2:
        score += 7
    if sentence_count >= 4:
        score += 7
    if paragraph_count >= 2:
        score += 4
    return {
        "score": round(min(100.0, score), 1),
        "star_markers": star_markers,
        "organization_markers": organization_markers,
        "sentence_count": sentence_count,
        "paragraph_count": paragraph_count,
    }


def _ownership_signal(question: str, answer: str) -> Dict[str, Any]:
    applicable = bool(_OWNERSHIP_QUESTION_RE.search(question))
    singular_action_re = re.compile(
        rf"\bi\s+(?:personally\s+)?(?:{'|'.join(_ACTION_VERBS)})\b", re.IGNORECASE
    )
    plural_action_re = re.compile(
        rf"\bwe\s+(?:{'|'.join(_ACTION_VERBS)})\b", re.IGNORECASE
    )
    singular_actions = [match.group(0) for match in singular_action_re.finditer(answer)]
    plural_actions = [match.group(0) for match in plural_action_re.finditer(answer)]
    first_person_count = len(re.findall(r"\b(?:i|my|me)\b", answer, re.IGNORECASE))

    if not applicable:
        score: Optional[float] = None
    elif singular_actions:
        score = min(100.0, 72.0 + (len(singular_actions) * 8.0))
        if len(plural_actions) > len(singular_actions) * 2:
            score = max(60.0, score - 10.0)
    elif first_person_count:
        score = 48.0
    elif plural_actions:
        score = 25.0
    else:
        score = 10.0 if answer.strip() else 0.0

    return {
        "score": round(score, 1) if score is not None else None,
        "applicable": applicable,
        "first_person_count": first_person_count,
        "owned_action_count": len(singular_actions),
        "team_action_count": len(plural_actions),
        "owned_action_phrases": singular_actions[:8],
    }


def _specificity_signal(answer: str) -> Dict[str, Any]:
    if not answer.strip():
        return {
            "score": 0.0,
            "number_count": 0,
            "metric_count": 0,
            "example_marker_count": 0,
            "causal_marker_count": 0,
            "action_detail_count": 0,
        }
    numbers = re.findall(r"(?<!\w)(?:\d+(?:\.\d+)?%?|\d+[xX])\b", answer)
    metrics = re.findall(
        r"\b(?:percent|milliseconds?|seconds?|minutes?|hours?|days?|users?|requests?|"
        r"transactions?|revenue|cost|latency|accuracy|throughput|errors?|failures?)\b",
        answer,
        re.IGNORECASE,
    )
    examples = re.findall(r"\b(?:for example|for instance|specifically|such as)\b", answer, re.IGNORECASE)
    causal = re.findall(r"\b(?:because|therefore|so that|which meant|as a result|led to)\b", answer, re.IGNORECASE)
    actions = re.findall(rf"\b(?:{'|'.join(_ACTION_VERBS)})\b", answer, re.IGNORECASE)
    evidence_dimensions = sum(bool(items) for items in (numbers, metrics, examples, causal, actions))
    score = 8.0
    score += min(22.0, len(numbers) * 11.0)
    score += min(18.0, len(metrics) * 6.0)
    score += min(14.0, len(examples) * 10.0)
    score += min(18.0, len(causal) * 7.0)
    score += min(20.0, len(actions) * 5.0)
    if evidence_dimensions >= 4:
        score += 8.0
    return {
        "score": round(min(100.0, score), 1),
        "number_count": len(numbers),
        "metric_count": len(metrics),
        "example_marker_count": len(examples),
        "causal_marker_count": len(causal),
        "action_detail_count": len(actions),
        "numeric_mentions": numbers[:8],
    }


def _filler_signal(answer: str, word_count: int) -> Dict[str, Any]:
    occurrences: Dict[str, int] = {}
    total = 0
    for label, pattern in _FILLER_PATTERNS:
        count = len(pattern.findall(answer))
        if count:
            occurrences[label] = count
            total += count
    rate = (total * 100.0 / word_count) if word_count else 0.0
    score = max(0.0, 100.0 - (rate * 9.0)) if word_count else 0.0
    return {
        "score": round(score, 1),
        "count": total,
        "rate_per_100_words": round(rate, 2),
        "occurrences": occurrences,
    }


def _directness_signal(
    question: str,
    answer: str,
    word_count: int,
    relevance_score: float,
) -> Dict[str, Any]:
    if word_count <= 0:
        return {"score": 0.0, "opening_relevance": 0.0, "concision": 0.0}
    question_terms = _content_terms(question)
    opening = " ".join(_words(answer)[:40])
    opening_terms = _content_terms(opening)
    opening_score = _score_from_overlap(len(question_terms & opening_terms), len(question_terms))
    if not question_terms:
        opening_score = 50.0

    if word_count < 5:
        concision = 15.0
    elif word_count < 15:
        concision = 55.0
    elif word_count <= 180:
        concision = 92.0
    elif word_count <= 300:
        concision = 72.0
    else:
        concision = 50.0
    score = (relevance_score * 0.50) + (opening_score * 0.32) + (concision * 0.18)
    return {
        "score": round(max(0.0, min(100.0, score)), 1),
        "opening_relevance": round(opening_score, 1),
        "concision": concision,
    }


def _tradeoff_signal(question: str, rubric: Mapping[str, Any], answer: str) -> Dict[str, Any]:
    rubric_text = " ".join(_extract_text_fragments(rubric))
    applicable = bool(_TRADEOFF_QUESTION_RE.search(f"{question} {rubric_text}"))
    markers = [name for name, pattern in _TRADEOFF_PATTERNS.items() if pattern.search(answer)]
    if not applicable:
        score: Optional[float] = None
    elif not answer.strip():
        score = 0.0
    else:
        score = min(100.0, 12.0 + (len(markers) * 18.0))
        if "explicit" in markers and len(markers) >= 3:
            score = min(100.0, score + 10.0)
    return {
        "score": round(score, 1) if score is not None else None,
        "applicable": applicable,
        "markers": markers,
    }


def _timing_signal(response_seconds: Any, word_count: int) -> Dict[str, Any]:
    try:
        seconds = float(response_seconds)
    except (TypeError, ValueError, OverflowError):
        seconds = 0.0
    if seconds <= 0 or seconds != seconds or seconds == float("inf"):
        return {"response_seconds": None, "words_per_minute": None}
    words_per_minute = (word_count * 60.0) / seconds
    return {
        "response_seconds": round(seconds, 2),
        "words_per_minute": round(words_per_minute, 1),
    }


def _deterministic_evidence_quotes(answer: str) -> List[str]:
    quotes: List[str] = []
    for match in _SENTENCE_RE.finditer(answer):
        sentence = match.group(0).strip()
        if not sentence:
            continue
        has_evidence = bool(
            re.search(r"\d", sentence)
            or re.search(rf"\b(?:i|we)\s+(?:{'|'.join(_ACTION_VERBS)})\b", sentence, re.IGNORECASE)
            or re.search(r"\b(?:because|as a result|led to|impact|outcome)\b", sentence, re.IGNORECASE)
        )
        if has_evidence:
            quotes.append(sentence[:300])
        if len(quotes) >= 4:
            break
    return quotes


def compute_deterministic_signals(
    question: Any,
    answer: Any,
    rubric: Optional[Mapping[str, Any]] = None,
    response_seconds: Any = None,
) -> Dict[str, Any]:
    """Compute all measurable signals without external services."""

    question_text = _bounded_text(question, MAX_QUESTION_CHARS)
    answer_text = _bounded_text(answer, MAX_ANSWER_ANALYSIS_CHARS)
    safe_rubric: Mapping[str, Any] = rubric if isinstance(rubric, Mapping) else {}
    word_count = len(_words(answer_text))
    lexical = _lexical_relevance(question_text, answer_text, safe_rubric)
    structure = _structure_signal(answer_text)
    ownership = _ownership_signal(question_text, answer_text)
    specificity = _specificity_signal(answer_text)
    fillers = _filler_signal(answer_text, word_count)
    directness = _directness_signal(
        question_text,
        answer_text,
        word_count,
        float(lexical["score"]),
    )
    tradeoffs = _tradeoff_signal(question_text, safe_rubric, answer_text)
    timing = _timing_signal(response_seconds, word_count)
    return {
        "word_count": word_count,
        "character_count": len(answer_text),
        "lexical_relevance": lexical,
        "structure": structure,
        "ownership": ownership,
        "specificity_evidence": specificity,
        "fillers": fillers,
        "directness": directness,
        "tradeoffs": tradeoffs,
        "timing": timing,
    }


def _rubric_requires_semantics(rubric: Mapping[str, Any]) -> bool:
    for key, value in rubric.items():
        normalized_key = str(key).strip().lower()
        if normalized_key in _SEMANTIC_RUBRIC_KEYS and bool(value):
            return True
    return False


def _semantic_policy(
    question: str,
    rubric: Mapping[str, Any],
    context: Mapping[str, Any],
    prior_evaluations: Sequence[Any],
    signals: Mapping[str, Any],
) -> Tuple[bool, str]:
    """Choose whether semantic evidence is worth one model call."""

    if context.get("semantic_analysis_enabled") is False or context.get("allow_semantic_analysis") is False:
        return False, "disabled_by_context"
    word_count = int(signals.get("word_count") or 0)
    if word_count < 12:
        return False, "insufficient_answer"
    if float(signals["lexical_relevance"]["score"]) < 25:
        return True, "low_lexical_relevance_requires_relevance_check"
    if prior_evaluations:
        return True, "prior_answers_require_consistency_check"
    if _rubric_requires_semantics(rubric):
        return True, "rubric_requires_semantic_judgment"

    interview_type = str(
        context.get("interview_type")
        or context.get("question_type")
        or context.get("mode")
        or ""
    ).lower()
    technical_context = any(
        token in interview_type
        for token in ("technical", "coding", "system_design", "system design", "case_study", "case study")
    )
    if technical_context and word_count >= 20:
        return True, "technical_depth_requires_semantic_judgment"
    if word_count >= 35 and _COMPLEX_QUESTION_RE.search(question):
        return True, "complex_answer_requires_semantic_judgment"
    return False, "deterministic_signals_sufficient"


def _safe_json(value: Any, limit: int) -> str:
    try:
        serialized = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    except Exception:
        serialized = "{}"
    return serialized[:limit]


def _semantic_cache_key(
    question: str,
    answer: str,
    rubric: Mapping[str, Any],
    context: Mapping[str, Any],
    prior_evaluations: Sequence[Any],
) -> str:
    payload = "\n".join(
        (
            EVALUATION_VERSION,
            question,
            answer,
            _safe_json(rubric, MAX_PROMPT_CONTEXT_CHARS),
            _safe_json(context, MAX_PROMPT_CONTEXT_CHARS),
            _safe_json(list(prior_evaluations)[-5:], MAX_PROMPT_CONTEXT_CHARS),
        )
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"answer-evaluation:{EVALUATION_VERSION}:{digest}"


def _semantic_messages(
    question: str,
    answer: str,
    rubric: Mapping[str, Any],
    context: Mapping[str, Any],
    prior_evaluations: Sequence[Any],
) -> List[Dict[str, str]]:
    system_message = (
        "You are a semantic evidence analyst for an interview evaluator. "
        "Extract coverage, relevance, and contradictions; do not assign scores or choose an interview action. "
        "Set answer_relevant to true only when the candidate directly answers the original question; "
        "set it to false for nonsense, unrelated content, refusal without an answer, or an answer that "
        "does not address the requested subject. "
        "Return only server-supplied expected-point IDs and claim IDs, never labels you invent. "
        "Use the rubric as the source of expected points. Mark a claim incorrect only when the supplied "
        "rubric/context supports that judgment; otherwise leave it unclassified. Every evidence quote must "
        "be an exact contiguous substring of the candidate answer. Contradictions must identify the conflicting "
        "statements and may use the supplied prior evaluations. suggested_followup is optional wording only. "
        f"{SYSTEM_DATA_BOUNDARY}"
    )
    blocks = "\n".join(
        (
            data_block("question", question, MAX_QUESTION_CHARS),
            data_block("candidate_answer", answer, MAX_ANSWER_ANALYSIS_CHARS),
            data_block("rubric", _safe_json(rubric, MAX_PROMPT_CONTEXT_CHARS)),
            data_block("interview_context", _safe_json(context, MAX_PROMPT_CONTEXT_CHARS)),
            data_block(
                "prior_evaluations",
                _safe_json(list(prior_evaluations)[-5:], MAX_PROMPT_CONTEXT_CHARS),
            ),
        )
    )
    return [
        {"role": "system", "content": system_message},
        {"role": "user", "content": blocks},
    ]


def _clean_string_list(value: Any, *, max_items: int, max_chars: int = 300) -> Optional[List[str]]:
    if not isinstance(value, list):
        return None
    cleaned: List[str] = []
    seen: set[str] = set()
    for item in value[:max_items]:
        if not isinstance(item, str):
            return None
        text = item.strip()[:max_chars]
        if text and text not in seen:
            seen.add(text)
            cleaned.append(text)
    return cleaned


def _validate_semantic_payload(
    payload: Any,
    answer: str,
    *,
    allowed_expected_point_ids: Optional[set[str]] = None,
    allowed_claim_ids: Optional[set[str]] = None,
) -> Tuple[Optional[Dict[str, Any]], str, int]:
    required = set(SEMANTIC_RESPONSE_SCHEMA["required"])
    if not isinstance(payload, dict) or set(payload) != required:
        return None, "invalid_response_shape", 0

    covered = _clean_string_list(payload.get("covered_points"), max_items=12)
    missed = _clean_string_list(payload.get("missed_points"), max_items=12)
    incorrect = _clean_string_list(payload.get("incorrect_claims"), max_items=8)
    contradictions = _clean_string_list(payload.get("contradictions"), max_items=8)
    raw_quotes = _clean_string_list(payload.get("evidence_quotes"), max_items=8)
    confidence = payload.get("semantic_confidence")
    answer_relevant = payload.get("answer_relevant")
    suggested = payload.get("suggested_followup")
    if any(item is None for item in (covered, missed, incorrect, contradictions, raw_quotes)):
        return None, "invalid_response_types", 0
    if (
        isinstance(confidence, bool)
        or not isinstance(confidence, (int, float))
        or not math.isfinite(float(confidence))
    ):
        return None, "invalid_semantic_confidence", 0
    if not isinstance(answer_relevant, bool):
        return None, "invalid_answer_relevance", 0
    if suggested is not None and not isinstance(suggested, str):
        return None, "invalid_suggested_followup", 0

    validated_quotes = [quote for quote in raw_quotes or [] if quote in answer]
    discarded_quotes = len(raw_quotes or []) - len(validated_quotes)
    discarded_references = 0
    if allowed_expected_point_ids:
        valid_covered = [item for item in covered or [] if item in allowed_expected_point_ids]
        valid_missed = [item for item in missed or [] if item in allowed_expected_point_ids]
        discarded_references += len(covered or []) - len(valid_covered)
        discarded_references += len(missed or []) - len(valid_missed)
        covered = valid_covered
        missed = valid_missed
    if allowed_claim_ids:
        valid_incorrect = [item for item in incorrect or [] if item in allowed_claim_ids]
        valid_contradictions = [item for item in contradictions or [] if item in allowed_claim_ids]
        discarded_references += len(incorrect or []) - len(valid_incorrect)
        discarded_references += len(contradictions or []) - len(valid_contradictions)
        incorrect = valid_incorrect
        contradictions = valid_contradictions
    covered_set = set(covered or [])
    missed = [item for item in missed or [] if item not in covered_set]
    normalized = {
        "covered_points": covered or [],
        "missed_points": missed or [],
        "incorrect_claims": incorrect or [],
        "contradictions": contradictions or [],
        "evidence_quotes": validated_quotes,
        "semantic_confidence": round(max(0.0, min(1.0, float(confidence))), 3),
        "answer_relevant": answer_relevant,
        "suggested_followup": suggested.strip()[:400] if isinstance(suggested, str) and suggested.strip() else None,
        "discarded_reference_count": discarded_references,
    }
    return normalized, "completed", discarded_quotes


def _technical_accuracy(semantic: Optional[Mapping[str, Any]]) -> Optional[float]:
    if not semantic or float(semantic.get("semantic_confidence") or 0.0) < 0.40:
        return None
    covered = len(semantic.get("covered_points") or [])
    missed = len(semantic.get("missed_points") or [])
    incorrect = len(semantic.get("incorrect_claims") or [])
    denominator = covered + missed + (incorrect * 1.5)
    if denominator <= 0:
        return None
    return round(max(0.0, min(100.0, (covered * 100.0) / denominator)), 1)


def _weighted_overall(scores: Mapping[str, Optional[float]]) -> float:
    weighted_sum = 0.0
    available_weight = 0.0
    for name, weight in SCORE_WEIGHTS.items():
        value = scores.get(name)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        weighted_sum += max(0.0, min(100.0, float(value))) * weight
        available_weight += weight
    if available_weight <= 0:
        return 0.0
    return round(weighted_sum / available_weight, 1)


def _average_known(*values: Optional[float]) -> Optional[float]:
    known = [float(value) for value in values if isinstance(value, (int, float)) and not isinstance(value, bool)]
    if not known:
        return None
    return round(sum(known) / len(known), 1)


def _question_rubric_kind(context_kind: str) -> str:
    normalized = str(context_kind or "").lower().replace("-", "_").replace(" ", "_")
    if "coding" in normalized:
        return "coding"
    if any(token in normalized for token in ("technical", "system_design", "debugging")):
        return "technical_concept"
    if "project" in normalized:
        return "project_explanation"
    return "behavioral"


def _communication_score(signals: Mapping[str, Any]) -> float:
    return round(
        (
            float(signals["directness"]["score"]) * 0.40
            + float(signals["structure"]["score"]) * 0.35
            + float(signals["fillers"]["score"]) * 0.25
        ),
        1,
    )


def _typed_dimension_scores(
    rubric_kind: str,
    signals: Mapping[str, Any],
    answer_text: str,
    technical_accuracy: Optional[float],
) -> Dict[str, Optional[float]]:
    relevance = float(signals["lexical_relevance"]["score"])
    structure = float(signals["structure"]["score"])
    specificity = float(signals["specificity_evidence"]["score"])
    ownership = signals["ownership"].get("score")
    tradeoffs = signals["tradeoffs"].get("score")
    communication = _communication_score(signals)
    failure_matches = len(_FAILURE_MODE_RE.findall(answer_text or ""))
    failure_modes = 100.0 if failure_matches >= 2 else (60.0 if failure_matches == 1 else 0.0)
    result_present = "result" in set(signals["structure"].get("star_markers") or [])
    learning_present = bool(_LEARNING_RE.search(answer_text or ""))
    result_learning = (50.0 if result_present else 0.0) + (50.0 if learning_present else 0.0)

    if rubric_kind == "technical_concept":
        return {
            "correctness": technical_accuracy,
            "depth": _average_known(technical_accuracy, structure),
            "application": _average_known(specificity, relevance),
            "trade_offs": float(tradeoffs) if isinstance(tradeoffs, (int, float)) else 0.0,
            "failure_modes": failure_modes,
            "communication": communication,
        }
    if rubric_kind == "project_explanation":
        return {
            "contribution": float(ownership) if isinstance(ownership, (int, float)) else None,
            "architecture_data_flow": technical_accuracy,
            "decisions_trade_offs": float(tradeoffs) if isinstance(tradeoffs, (int, float)) else 0.0,
            "outcome_evaluation": specificity,
            "relevance": relevance,
            "communication": communication,
            "limitations": failure_modes,
        }
    if rubric_kind == "coding":
        # Coding is scored by the Technical worker from persisted workflow and
        # sandbox evidence, never from answer-text heuristics.
        return {name: None for name in QUESTION_TYPE_WEIGHTS["coding"]}
    return {
        "star_structure": structure,
        "relevance": relevance,
        "ownership": float(ownership) if isinstance(ownership, (int, float)) else 0.0,
        "specificity": specificity,
        "result_learning": result_learning,
        "communication": communication,
    }


def _authoritative_typed_score(
    rubric_kind: str,
    dimensions: Mapping[str, Optional[float]],
    *,
    meaningful_word_count: int,
) -> Optional[float]:
    if meaningful_word_count < 8:
        return None
    weights = QUESTION_TYPE_WEIGHTS[rubric_kind]
    if any(
        isinstance(value, bool) or not isinstance(value, (int, float))
        for name, value in dimensions.items()
        if name in weights
    ):
        return None
    return round(
        sum(max(0.0, min(100.0, float(dimensions[name]))) * weight for name, weight in weights.items()),
        1,
    )


def _build_flags(
    signals: Mapping[str, Any],
    *,
    semantic_state: str,
    technical_accuracy: Optional[float],
    requires_technical_accuracy: bool,
    answer_was_truncated: bool,
) -> List[str]:
    flags: List[str] = []
    word_count = int(signals.get("word_count") or 0)
    relevance = float(signals["lexical_relevance"]["score"])
    if word_count == 0:
        flags.append("empty_answer")
    elif word_count < 8:
        flags.append("too_short")
    elif word_count < 20:
        flags.append("brief_answer")
    if relevance < 20:
        flags.append("low_lexical_relevance")
    if float(signals["structure"]["score"]) < 35 and word_count >= 12:
        flags.append("weak_structure")
    ownership = signals["ownership"]
    if ownership.get("applicable") and float(ownership.get("score") or 0) < 45:
        flags.append("ownership_unclear")
    if float(signals["specificity_evidence"]["score"]) < 40 and word_count >= 12:
        flags.append("unsupported_or_unspecific")
    if float(signals["fillers"]["rate_per_100_words"]) >= 4.0:
        flags.append("filler_heavy")
    if float(signals["directness"]["score"]) < 35 and word_count >= 8:
        flags.append("indirect_response")
    tradeoffs = signals["tradeoffs"]
    if tradeoffs.get("applicable") and float(tradeoffs.get("score") or 0) < 45:
        flags.append("missing_tradeoffs")
    words_per_minute = signals["timing"].get("words_per_minute")
    if isinstance(words_per_minute, (int, float)) and words_per_minute > 230:
        flags.append("rushed_delivery")
    if answer_was_truncated:
        flags.append("answer_truncated_for_analysis")
    if requires_technical_accuracy and technical_accuracy is None:
        flags.append("technical_accuracy_unknown")
    if semantic_state == "failed":
        flags.append("semantic_analysis_failed")
    elif semantic_state == "invalid":
        flags.append("semantic_analysis_invalid")
    elif semantic_state == "skipped":
        flags.append("semantic_analysis_skipped")
    return flags


def _follow_up_decision(
    question: str,
    signals: Mapping[str, Any],
    semantic: Optional[Mapping[str, Any]],
    technical_accuracy: Optional[float],
) -> Dict[str, Any]:
    """Select the action from fixed rules; semantic text never controls it."""

    word_count = int(signals.get("word_count") or 0)
    relevance = float(signals["lexical_relevance"]["score"])
    directness = float(signals["directness"]["score"])
    covered = list(semantic.get("covered_points") or []) if semantic else []
    missed = list(semantic.get("missed_points") or []) if semantic else []
    incorrect = list(semantic.get("incorrect_claims") or []) if semantic else []
    contradictions = list(semantic.get("contradictions") or []) if semantic else []
    semantic_confidence = float(semantic.get("semantic_confidence") or 0.0) if semantic else 0.0

    if semantic and semantic.get("answer_relevant") is False:
        action = "clarify"
        reason = "answer_not_relevant"
        prompt = "That answer did not address the question. Please answer it directly and stay on the requested topic."
    elif word_count < 8 or ((relevance < 15 or directness < 25) and not covered):
        action = "clarify"
        reason = "answer_too_brief_or_unclear"
        prompt = "Could you answer the question directly, then explain your reasoning in one or two steps?"
    elif contradictions and semantic_confidence >= 0.40:
        action = "verify_contradiction"
        reason = "semantic_contradiction_detected"
        prompt = "I heard two conflicting claims. Which one is correct, and what evidence supports it?"
    elif (
        technical_accuracy is not None
        and (technical_accuracy < 45 or len(missed) > len(covered) + 1)
    ) or (incorrect and semantic_confidence >= 0.50):
        action = "simplify_prerequisite"
        reason = "foundational_gap_detected"
        prompt = "Let us start with the underlying concept: what is it, and why is it needed?"
    elif (
        _EVIDENCE_QUESTION_RE.search(question)
        and (
            float(signals["specificity_evidence"]["score"]) < 50
            or (
                signals["ownership"].get("applicable")
                and float(signals["ownership"].get("score") or 0) < 45
            )
        )
    ):
        action = "probe_evidence"
        reason = "claim_needs_specific_evidence"
        prompt = "What exactly did you do, and what measurable result or concrete evidence shows the impact?"
    elif (
        signals["tradeoffs"].get("applicable")
        and float(signals["tradeoffs"].get("score") or 0) < 45
    ):
        action = "challenge_tradeoff"
        reason = "decision_tradeoff_missing"
        prompt = "What alternative did you consider, and what trade-off made you choose this approach?"
    else:
        action = "advance"
        reason = "answer_has_sufficient_evidence_to_continue"
        prompt = None

    return {
        "action": action,
        "reason": reason,
        "prompt": prompt,
        "semantic_suggestion": semantic.get("suggested_followup") if semantic else None,
    }


def _deterministic_confidence(signals: Mapping[str, Any]) -> float:
    word_count = int(signals.get("word_count") or 0)
    lexical = signals["lexical_relevance"]
    anchor_count = int(lexical.get("question_term_count") or 0) + int(lexical.get("rubric_term_count") or 0)
    confidence = 0.20
    confidence += min(0.24, word_count / 250.0)
    confidence += min(0.18, anchor_count / 50.0)
    confidence += 0.08 if signals["ownership"].get("applicable") else 0.03
    confidence += 0.05 if signals["tradeoffs"].get("applicable") else 0.02
    return round(max(0.15, min(0.72, confidence)), 3)


async def evaluate_answer(
    question: Any,
    answer: Any,
    rubric: Optional[Dict[str, Any]] = None,
    context: Optional[Dict[str, Any]] = None,
    response_seconds: Any = None,
    prior_evaluations: Optional[List[Any]] = None,
    user_id: Optional[str] = None,
    interview_id: Optional[str] = None,
    response_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Evaluate one answer and return a versioned, failure-safe result.

    A semantic request is made at most once, only when ``_semantic_policy``
    determines that lexical/measurable evidence cannot answer the rubric.  All
    model, timeout, and payload-validation failures degrade to a truthful
    deterministic result with ``technical_accuracy`` set to ``None``.
    """

    question_text = _bounded_text(question, MAX_QUESTION_CHARS)
    # One extra character is sufficient to retain the truncation fact without
    # keeping an unbounded candidate transcript in memory.
    raw_answer = _bounded_text(answer, MAX_ANSWER_ANALYSIS_CHARS + 1)
    answer_text = raw_answer[:MAX_ANSWER_ANALYSIS_CHARS]
    safe_rubric: Dict[str, Any] = rubric if isinstance(rubric, dict) else {}
    safe_context: Dict[str, Any] = context if isinstance(context, dict) else {}
    safe_prior: List[Any] = prior_evaluations if isinstance(prior_evaluations, list) else []

    signals = compute_deterministic_signals(
        question_text,
        answer_text,
        safe_rubric,
        response_seconds,
    )
    should_call_semantic, policy_reason = _semantic_policy(
        question_text,
        safe_rubric,
        safe_context,
        safe_prior,
        signals,
    )

    semantic: Optional[Dict[str, Any]] = None
    semantic_state = "skipped"
    semantic_reason = policy_reason
    discarded_quote_count = 0
    if should_call_semantic:
        semantic_state = "failed"
        semantic_reason = "semantic_call_failed"
        try:
            payload = await asyncio.wait_for(
                complete_json_async(
                    _semantic_messages(
                        question_text,
                        answer_text,
                        safe_rubric,
                        safe_context,
                        safe_prior,
                    ),
                    event_type=SEMANTIC_EVENT_TYPE,
                    temperature=0.1,
                    max_tokens=900,
                    user_id=user_id,
                    interview_id=interview_id,
                    metadata={
                        "evaluation_version": EVALUATION_VERSION,
                        "response_id": response_id,
                        "policy_reason": policy_reason,
                    },
                    json_schema=SEMANTIC_RESPONSE_SCHEMA,
                    provider_policy="openai_required",
                    cache_key=_semantic_cache_key(
                        question_text,
                        answer_text,
                        safe_rubric,
                        safe_context,
                        safe_prior,
                    ),
                ),
                timeout=SEMANTIC_TIMEOUT_SECONDS,
            )
            expected_point_ids = {
                str(item)
                for item in (
                    safe_rubric.get("expected_point_ids")
                    or safe_context.get("expected_point_ids")
                    or []
                )
                if str(item).strip()
            }
            claim_ids = {
                str(item)
                for item in (
                    safe_context.get("claim_ids")
                    or safe_context.get("resume_claim_ids")
                    or []
                )
                if str(item).strip()
            }
            semantic, validation_reason, discarded_quote_count = _validate_semantic_payload(
                payload,
                answer_text,
                allowed_expected_point_ids=expected_point_ids,
                allowed_claim_ids=claim_ids,
            )
            if semantic is None:
                semantic_state = "invalid"
                semantic_reason = validation_reason
            else:
                semantic_state = "completed"
                semantic_reason = policy_reason
        except Exception as exc:
            logger.warning(
                "Semantic answer evaluation failed (%s)",
                type(exc).__name__,
            )
            semantic = None
            semantic_state = "failed"
            semantic_reason = "semantic_timeout" if isinstance(exc, asyncio.TimeoutError) else "semantic_call_failed"

    technical_accuracy = _technical_accuracy(semantic)
    if semantic_state == "completed" and technical_accuracy is None:
        semantic_reason = "semantic_completed_accuracy_unknown"

    scores: Dict[str, Optional[float]] = {
        "technical_accuracy": technical_accuracy,
        "relevance": float(signals["lexical_relevance"]["score"]),
        "structure": float(signals["structure"]["score"]),
        "ownership": signals["ownership"].get("score"),
        "specificity_evidence": float(signals["specificity_evidence"]["score"]),
        "filler_control": float(signals["fillers"]["score"]),
        "directness": float(signals["directness"]["score"]),
        "tradeoffs": signals["tradeoffs"].get("score"),
    }
    provisional_score = _weighted_overall(scores)
    context_kind = str(
        safe_context.get("question_type")
        or safe_context.get("interview_type")
        or safe_context.get("mode")
        or ""
    ).lower()
    rubric_kind = _question_rubric_kind(context_kind)
    dimension_scores = _typed_dimension_scores(
        rubric_kind,
        signals,
        answer_text,
        technical_accuracy,
    )
    overall_score = _authoritative_typed_score(
        rubric_kind,
        dimension_scores,
        meaningful_word_count=int(signals.get("word_count") or 0),
    )
    authoritative = overall_score is not None

    deterministic_confidence = _deterministic_confidence(signals)
    if semantic_state == "completed" and semantic and technical_accuracy is not None:
        confidence = min(
            0.96,
            (deterministic_confidence * 0.42)
            + (float(semantic["semantic_confidence"]) * 0.58),
        )
    elif semantic_state == "completed" and semantic:
        confidence = min(0.55, deterministic_confidence * 0.72)
    elif semantic_state in {"failed", "invalid"}:
        confidence = min(0.45, deterministic_confidence * 0.72)
    else:
        confidence = min(0.55, deterministic_confidence)

    evidence = {
        "deterministic_quotes": _deterministic_evidence_quotes(answer_text),
        "covered_points": list(semantic.get("covered_points") or []) if semantic else [],
        "missed_points": list(semantic.get("missed_points") or []) if semantic else [],
        "incorrect_claims": list(semantic.get("incorrect_claims") or []) if semantic else [],
        "contradictions": list(semantic.get("contradictions") or []) if semantic else [],
        "evidence_quotes": list(semantic.get("evidence_quotes") or []) if semantic else [],
    }
    follow_up = _follow_up_decision(
        question_text,
        signals,
        semantic,
        technical_accuracy,
    )
    flags = _build_flags(
        signals,
        semantic_state=semantic_state,
        technical_accuracy=technical_accuracy,
        requires_technical_accuracy=rubric_kind in {"technical_concept", "project_explanation", "coding"},
        answer_was_truncated=len(raw_answer) > len(answer_text),
    )
    if not authoritative and "insufficient_evidence" not in flags:
        flags.append("insufficient_evidence")

    return {
        "version": EVALUATION_VERSION,
        "evaluation_ids": {
            "user_id": user_id,
            "interview_id": interview_id,
            "response_id": response_id,
        },
        "scores": scores,
        "question_rubric": rubric_kind,
        "dimension_scores": dimension_scores,
        "score_weights": QUESTION_TYPE_WEIGHTS[rubric_kind],
        "overall_score": overall_score,
        "provisional_score": provisional_score,
        "authoritative": authoritative,
        "evidence_status": "sufficient" if authoritative else "insufficient_evidence",
        "confidence": round(max(0.0, min(1.0, confidence)), 3),
        "signals": signals,
        "flags": flags,
        "evidence": evidence,
        "semantic_status": {
            "state": semantic_state,
            "attempted": should_call_semantic,
            "reason": semantic_reason,
            "policy_reason": policy_reason,
            "semantic_confidence": semantic.get("semantic_confidence") if semantic else None,
            "answer_relevant": semantic.get("answer_relevant") if semantic else None,
            "discarded_evidence_quote_count": discarded_quote_count,
            "discarded_reference_count": (
                int(semantic.get("discarded_reference_count") or 0)
                if semantic
                else 0
            ),
        },
        "follow_up": follow_up,
    }


__all__ = [
    "EVALUATION_VERSION",
    "FOLLOW_UP_ACTIONS",
    "SCORE_WEIGHTS",
    "SEMANTIC_RESPONSE_SCHEMA",
    "compute_deterministic_signals",
    "evaluate_answer",
]
