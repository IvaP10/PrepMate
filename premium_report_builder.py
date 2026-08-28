# ============================================================================
# MODULE: premium_report_builder.py
# PURPOSE: Build premium "unknown unknowns" analysis for completed sessions.
#          Produces a deeply analytical evaluation payload that surfaces the
#          logical flaws, missed signals, and confidence gaps the candidate
#          did not realize they had.
# STRUCTURE:
#   - build_premium_report() entry point
#   - _build_technical_track() -> Track A (Technical Round)
#   - _build_behavioral_track() -> Track B (Mock Interview)
#   - Shared helpers: self-review signals, unknown-unknowns, executive summary
# CONSUMED BY: analysis_pipeline.py (report_generation stage)
# DATA TABLES: none (returns dict merged into report_json)
# ============================================================================

from __future__ import annotations

import re
from collections import Counter
from typing import Any, Dict, List, Optional


# ──────────────────────────────────────────
#  Public Entry Point
# ──────────────────────────────────────────

def build_premium_report(
    interview_type: str,
    stage_outputs: Dict[str, Dict[str, Any]],
    heuristic_report: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Build the premium analysis payload from pipeline stage outputs.

    Returns a dict to be merged into the report as ``report["premium_analysis"]``.
    """
    is_technical = "technical" in str(interview_type).lower() or str(interview_type).lower() in {"coding", "technical_round"}

    if _premium_evidence_is_limited(is_technical, stage_outputs, heuristic_report):
        return _evidence_limited_premium(is_technical, heuristic_report)

    self_review = stage_outputs.get("self_review_signals", {})
    integrity = _build_self_review_verdict(self_review, stage_outputs.get("video_features", {}))

    if is_technical:
        track = _build_technical_track(stage_outputs, heuristic_report)
    else:
        track = _build_behavioral_track(stage_outputs, heuristic_report)

    unknowns = _build_unknown_unknowns(track, integrity, heuristic_report, is_technical)
    executive = _build_executive_summary(track, integrity, heuristic_report, is_technical)

    return {
        "track": "technical" if is_technical else "behavioral",
        "executive_summary": executive,
        "self_review_verdict": integrity,
        "unknown_unknowns": unknowns,
        **track,
    }


def _premium_evidence_is_limited(
    is_technical: bool,
    stage_outputs: Dict[str, Dict[str, Any]],
    report: Dict[str, Any],
) -> bool:
    status = (report.get("evidence_status") or {}).get("status")
    if status == "no_candidate_evidence":
        return True
    if is_technical:
        tech = stage_outputs.get("technical_code", {})
        return int(tech.get("submission_count") or 0) == 0
    turns = (stage_outputs.get("nlp_content") or {}).get("turns") or []
    return not any(str(turn.get("response") or "").strip() for turn in turns)


def _evidence_limited_premium(is_technical: bool, report: Dict[str, Any]) -> Dict[str, Any]:
    reason = (
        "No final technical submission was captured, so premium technical analysis is limited to evidence status."
        if is_technical
        else "No gradable candidate answer was captured, so premium interview analysis is limited to evidence status."
    )
    return {
        "track": "technical" if is_technical else "behavioral",
        "executive_summary": reason,
        "self_review_verdict": {"label": "Self-review only", "signal_count": 0, "mode": "self_review"},
        "unknown_unknowns": [],
        "evidence_limited": True,
        "evidence_reason": reason,
        "source_report_state": (report.get("evidence_status") or {}).get("status"),
    }


# ──────────────────────────────────────────
#  Track A — Technical Round Evaluation
# ──────────────────────────────────────────

def _build_technical_track(
    outputs: Dict[str, Dict[str, Any]],
    report: Dict[str, Any],
) -> Dict[str, Any]:
    tech = outputs.get("technical_code", {})
    nlp = outputs.get("nlp_content", {})
    submissions = tech.get("submissions") or tech.get("all_submissions") or []
    test_matrix = tech.get("test_matrix") or []
    turns = nlp.get("turns") or []
    annotations = report.get("line_level_annotations") or []

    return {
        "logic_teardown": _logic_teardown(submissions, turns, test_matrix),
        "complexity_overheads": _complexity_overheads(submissions),
        "optimal_delta": _optimal_delta(submissions, report),
        "edge_case_forensics": _edge_case_forensics(test_matrix, annotations, submissions),
    }


def _logic_teardown(
    submissions: List[Dict[str, Any]],
    turns: List[Dict[str, Any]],
    test_matrix: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Logic vs. Implementation Teardown."""
    details: List[Dict[str, Any]] = []
    severity = "info"

    for sub in submissions:
        visible_passed = int(sub.get("visible_passed") or 0)
        visible_total = int(sub.get("visible_total") or 0)
        hidden_passed = int(sub.get("hidden_passed") or 0)
        hidden_total = int(sub.get("hidden_total") or 0)
        total = visible_total + hidden_total
        passed = visible_passed + hidden_passed

        if total > 0 and passed < total:
            fail_rate = round((1 - passed / total) * 100, 1)
            code_excerpt = (sub.get("source_excerpt") or "")[:300]

            # Check if visible tests passed but hidden failed — strong signal of
            # syntactically correct but logically flawed code.
            if visible_passed == visible_total and hidden_passed < hidden_total:
                severity = "critical"
                details.append({
                    "explanation": (
                        "Your implementation was syntactically pristine — it compiled and passed "
                        "all visible test cases. However, the underlying logic was fundamentally "
                        "flawed for this problem space. Hidden test cases exposed that your approach "
                        f"fails on {hidden_total - hidden_passed} out of {hidden_total} edge cases."
                    ),
                    "snippet": code_excerpt if code_excerpt else None,
                    "real_world_consequence": (
                        "In a real interview, visible tests are the safety net — hidden tests "
                        "are the actual evaluation. Passing visible but failing hidden is the "
                        "most dangerous outcome because it creates false confidence."
                    ),
                })
            elif passed == 0:
                severity = "critical"
                details.append({
                    "explanation": (
                        f"Zero of {total} test cases passed. The code either does not compile, "
                        "throws a runtime exception on all inputs, or uses an entirely incorrect "
                        "algorithmic approach. Treat this as a correctness blocker before optimizing."
                    ),
                    "snippet": code_excerpt if code_excerpt else None,
                    "real_world_consequence": (
                        "A zero-pass final submission gives the interviewer no working implementation "
                        "to evaluate, regardless of how well the approach was explained."
                    ),
                })
            else:
                severity = "warning" if severity != "critical" else severity
                details.append({
                    "explanation": (
                        f"Your code passed {passed} of {total} test cases ({fail_rate}% failure rate). "
                        "The implementation handles the basic cases but breaks on boundary conditions."
                    ),
                    "snippet": code_excerpt if code_excerpt else None,
                })

    if not details:
        # All tests passed — give positive but measured feedback
        for sub in submissions:
            total = int(sub.get("visible_total") or 0) + int(sub.get("hidden_total") or 0)
            passed = int(sub.get("visible_passed") or 0) + int(sub.get("hidden_passed") or 0)
            if total > 0 and passed == total:
                details.append({
                    "explanation": (
                        "All test cases passed. Your logic correctly handles both the visible "
                        "and hidden edge cases for this problem. The implementation aligns with "
                        "the expected algorithmic approach."
                    ),
                })
                severity = "info"

    verdict = {
        "critical": "Your code compiles but your logic is fundamentally broken.",
        "warning": "Partial correctness — your approach works on happy paths but crumbles at the edges.",
        "info": "Logic and implementation are aligned. Correctness is sound.",
    }.get(severity, "Unable to determine logic quality from available data.")

    return {
        "title": "Logic vs. Implementation Teardown",
        "severity": severity,
        "verdict": verdict,
        "details": details,
    }


def _complexity_overheads(submissions: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Hidden Complexity Overheads — flag memory spikes, unnecessary allocations."""
    details: List[Dict[str, Any]] = []
    severity = "info"

    ANTI_PATTERNS = [
        (r'(\+\s*=\s*["\']|str\s*\(|\.concat\s*\()',
         "String concatenation in a loop",
         "String concatenation inside loops creates O(n²) memory overhead. "
         "Use StringBuilder (Java), list join (Python), or string streams (C++)."),
        (r'(new\s+\w+\[|malloc\s*\(|calloc\s*\(|realloc\s*\()',
         "Allocation inside a hot path",
         "Object or array allocation inside loops causes GC pressure and cache misses."),
        (r'(\.sort\s*\(|sorted\s*\(|Arrays\.sort)',
         "Sorting inside a loop",
         "Sorting inside a loop escalates complexity from O(n log n) to O(n² log n) or worse."),
        (r'(\.indexOf\s*\(|\.find\s*\(|\.includes\s*\(|in\s+\w+\s*:)',
         "Linear search where a hash lookup would suffice",
         "Using indexOf or linear scan on an unsorted list is O(n) per call. "
         "A HashSet/dict lookup is O(1)."),
    ]

    for sub in submissions:
        code = sub.get("source_excerpt") or ""
        if not code:
            continue

        for pattern, name, explanation in ANTI_PATTERNS:
            matches = list(re.finditer(pattern, code))
            if matches:
                severity = "warning"
                # Find approximate line number
                for match in matches[:2]:
                    line_num = code[:match.start()].count("\n") + 1
                    snippet_start = max(0, match.start() - 40)
                    snippet_end = min(len(code), match.end() + 40)
                    details.append({
                        "line": line_num,
                        "explanation": f"{name}: {explanation}",
                        "snippet": code[snippet_start:snippet_end].strip(),
                    })

        # Check for excessive runtime or memory
        runtime = sub.get("runtime_ms")
        memory = sub.get("memory_kb")
        if runtime and int(runtime) > 2000:
            severity = "warning"
            details.append({
                "explanation": (
                    f"Execution time was {runtime}ms — well above the typical 500ms threshold "
                    "for competitive-tier problems. This suggests a sub-optimal time complexity."
                ),
            })
        if memory and int(memory) > 256000:
            severity = "warning"
            details.append({
                "explanation": (
                    f"Memory usage was {memory}KB — exceeding the 256MB threshold. "
                    "Check for unnecessary data structure duplication or recursive stack depth."
                ),
            })

    if not details:
        details.append({
            "explanation": "No obvious complexity anti-patterns detected in the submitted code."
        })

    return {
        "title": "Hidden Complexity Overheads",
        "severity": severity,
        "verdict": (
            "Performance anti-patterns detected in your code."
            if severity == "warning" else
            "No major complexity red flags found."
        ),
        "details": details,
    }


def _optimal_delta(
    submissions: List[Dict[str, Any]],
    report: Dict[str, Any],
) -> Dict[str, Any]:
    """The Optimal vs. Yours Delta."""
    details: List[Dict[str, Any]] = []
    severity = "info"
    ideal = report.get("ideal_solution") or {}
    complexity_diff = report.get("complexity_diff") or {}

    for sub in submissions:
        expected_time = sub.get("expected_time_complexity") or ideal.get("expected_time_complexity")
        expected_space = sub.get("expected_space_complexity") or ideal.get("expected_space_complexity")
        algo_pattern = sub.get("algorithm_pattern") or ideal.get("algorithm_pattern")

        if expected_time or expected_space or algo_pattern:
            your_approach = []
            if sub.get("runtime_ms"):
                your_approach.append(f"Runtime: {sub['runtime_ms']}ms")
            if sub.get("memory_kb"):
                your_approach.append(f"Memory: {sub['memory_kb']}KB")

            gold_standard = []
            if expected_time:
                gold_standard.append(f"Time: {expected_time}")
            if expected_space:
                gold_standard.append(f"Space: {expected_space}")
            if algo_pattern:
                gold_standard.append(f"Pattern: {algo_pattern}")

            if gold_standard:
                severity = "warning"
                details.append({
                    "explanation": (
                        "The gold standard approach for this problem uses "
                        f"{', '.join(gold_standard)}. "
                        + (f"Your submission measured {', '.join(your_approach)}." if your_approach else "")
                    ),
                    "your_approach": ", ".join(your_approach) if your_approach else "Not measured",
                    "gold_standard": ", ".join(gold_standard),
                })

    if complexity_diff:
        exp_time = complexity_diff.get("expected_time")
        exp_space = complexity_diff.get("expected_space")
        obs_runtime = complexity_diff.get("observed_runtime_ms")
        obs_memory = complexity_diff.get("observed_memory_kb")
        if exp_time or exp_space:
            severity = "warning"
            details.append({
                "explanation": (
                    f"Expected complexity: Time {exp_time or 'N/A'}, Space {exp_space or 'N/A'}. "
                    f"Observed runtime: {obs_runtime or 'N/A'}ms, memory: {obs_memory or 'N/A'}KB."
                ),
            })

    if not details:
        details.append({
            "explanation": (
                "No gold-standard comparison data available. Review the intended DSA pattern "
                "for this problem class and verify your approach matches it."
            ),
        })
        severity = "info"

    return {
        "title": "The 'Optimal vs. Yours' Delta",
        "severity": severity,
        "verdict": (
            "Your approach diverges from the gold standard."
            if severity == "warning" else
            "Comparison data is limited for this submission."
        ),
        "details": details,
    }


def _edge_case_forensics(
    test_matrix: List[Dict[str, Any]],
    annotations: List[Dict[str, Any]],
    submissions: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Edge-Case Forensic Analysis."""
    details: List[Dict[str, Any]] = []
    severity = "info"

    for test_row in test_matrix:
        visible_total = int(test_row.get("visible_total") or 0)
        visible_passed = int(test_row.get("visible_passed") or 0)
        hidden_total = int(test_row.get("hidden_total") or 0)
        hidden_passed = int(test_row.get("hidden_passed") or 0)

        if hidden_total > 0 and hidden_passed < hidden_total:
            failed_hidden = hidden_total - hidden_passed
            severity = "critical"
            details.append({
                "explanation": (
                    f"{failed_hidden} hidden test case(s) failed for "
                    f"'{test_row.get('title', 'Problem')}'. "
                    "Hidden tests typically target: negative integers, empty inputs, "
                    "single-element arrays, integer overflow (2³¹-1), null/None references, "
                    "maximum-size inputs, and duplicate values. Your code did not handle "
                    "at least one of these boundary conditions."
                ),
                "real_world_consequence": (
                    "Edge cases cause production incidents. A missed null check or overflow "
                    "is how P0 bugs ship."
                ),
            })

    for ann in annotations:
        line = ann.get("line") or ann.get("start_line")
        message = ann.get("message") or ann.get("detail") or ann.get("issue") or ""
        if message:
            severity = "warning" if severity == "info" else severity
            details.append({
                "line": line,
                "explanation": message,
            })

    if not details:
        all_passed = all(
            (int(row.get("visible_passed") or 0) + int(row.get("hidden_passed") or 0))
            == (int(row.get("visible_total") or 0) + int(row.get("hidden_total") or 0))
            for row in test_matrix
        ) if test_matrix else False

        if all_passed:
            details.append({
                "explanation": "All edge cases handled correctly. No boundary failures detected."
            })
        else:
            details.append({
                "explanation": (
                    "Insufficient test-case data to perform forensic edge-case analysis. "
                    "Ensure you submit at least one solution before the session ends."
                ),
            })

    return {
        "title": "Edge-Case Forensic Analysis",
        "severity": severity,
        "verdict": (
            "Critical edge-case failures detected — boundary handling is broken."
            if severity == "critical" else
            "Minor edge-case concerns flagged."
            if severity == "warning" else
            "Edge cases appear to be handled."
        ),
        "details": details,
    }


# ──────────────────────────────────────────
#  Track B — Mock Interview Evaluation
# ──────────────────────────────────────────

def _build_behavioral_track(
    outputs: Dict[str, Dict[str, Any]],
    report: Dict[str, Any],
) -> Dict[str, Any]:
    nlp = outputs.get("nlp_content", {})
    audio = outputs.get("audio_features", {})
    video = outputs.get("video_features", {})
    self_review = outputs.get("self_review_signals", {})
    turns = nlp.get("turns") or []

    return {
        "content_accuracy": _content_accuracy(turns, report),
        "vocal_delivery": _vocal_delivery(audio, turns),
        "self_review_signals": _self_review_signals(self_review, video),
    }


def _content_accuracy(
    turns: List[Dict[str, Any]],
    report: Dict[str, Any],
) -> Dict[str, Any]:
    """Technical Depth & Content Accuracy."""
    details: List[Dict[str, Any]] = []
    severity = "info"

    for turn in turns:
        score = float(turn.get("overall_score") or turn.get("score") or 0)
        question = str(turn.get("question") or "")[:200]
        response = str(turn.get("response") or "")[:400]
        feedback = str(turn.get("feedback") or "")
        topic = turn.get("topic") or "General"

        if score < 55 and response.strip():
            severity = "critical" if severity != "critical" else severity
            # Quote their exact words and contrast
            quoted = response[:180].strip()
            if quoted:
                details.append({
                    "quote": f'"{quoted}..."',
                    "explanation": (
                        f"On '{topic}': Your response scored {score:.0f}/100. "
                        f"{feedback}" if feedback else
                        f"On '{topic}': Your response scored {score:.0f}/100. "
                        "The answer lacked the architectural depth and trade-off analysis "
                        "expected at this level."
                    ),
                    "contrast": (
                        "A top-tier engineer would have: (1) stated the direct answer, "
                        "(2) named the specific trade-off, (3) given a concrete example "
                        "with measurable impact, and (4) acknowledged what they would do "
                        "differently in hindsight."
                    ),
                })
        elif score < 70 and response.strip():
            severity = "warning" if severity == "info" else severity
            quoted = response[:120].strip()
            if quoted:
                details.append({
                    "quote": f'"{quoted}..."',
                    "explanation": (
                        f"On '{topic}': Scored {score:.0f}/100. "
                        "Your answer showed surface-level understanding but missed "
                        "the deeper architectural implications."
                    ),
                })

    if not details:
        avg_score = _avg([float(t.get("overall_score") or t.get("score") or 0) for t in turns])
        if avg_score >= 75:
            details.append({
                "explanation": (
                    f"Average content score: {avg_score:.0f}/100. Your technical answers "
                    "demonstrated adequate depth with concrete examples."
                ),
            })
        else:
            details.append({
                "explanation": (
                    "Insufficient transcript data to perform deep content analysis. "
                    "Ensure your microphone is active throughout the session."
                ),
            })

    return {
        "title": "Technical Depth & Content Accuracy",
        "severity": severity,
        "verdict": (
            "Multiple answers lacked the depth expected at this interview level."
            if severity == "critical" else
            "Some answers need sharper technical grounding."
            if severity == "warning" else
            "Content accuracy is within acceptable range."
        ),
        "details": details[:8],
    }


def _vocal_delivery(
    audio: Dict[str, Any],
    turns: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Vocal Delivery & Confidence Metrics."""
    wpm = audio.get("words_per_minute") or 0
    filler_rate = audio.get("filler_words_per_minute") or 0
    latency = audio.get("response_latency_seconds_avg")
    clarity = audio.get("clarity_proxy") or 0

    details: List[Dict[str, Any]] = []
    severity = "info"

    # Speaking pace analysis
    if wpm > 0:
        if wpm > 170:
            severity = "warning"
            details.append({
                "explanation": (
                    f"Speaking pace: {wpm} words per minute — rapid-fire delivery. "
                    "Fast speech signals anxiety and reduces comprehension. "
                    "Aim for 130-150 WPM for a composed, authoritative delivery."
                ),
            })
        elif wpm < 90:
            severity = "warning"
            details.append({
                "explanation": (
                    f"Speaking pace: {wpm} words per minute — noticeably slow. "
                    "Very slow speech can signal uncertainty or over-thinking. "
                    "It may also cause the interviewer to lose engagement."
                ),
            })
        else:
            details.append({
                "explanation": (
                    f"Speaking pace: {wpm} words per minute — within the optimal range "
                    "(120-160 WPM). Your pacing projected composure."
                ),
            })

    # Filler word analysis
    if filler_rate > 0:
        if filler_rate > 4:
            severity = "critical"
            details.append({
                "explanation": (
                    f"Filler word rate: {filler_rate:.1f} per minute — critically high. "
                    'Words like "um," "like," "you know" at this frequency actively '
                    "undermine your perceived competence. Interviewers pattern-match "
                    "filler density to confidence levels."
                ),
            })
        elif filler_rate > 2:
            severity = "warning" if severity == "info" else severity
            details.append({
                "explanation": (
                    f"Filler word rate: {filler_rate:.1f} per minute — elevated. "
                    "Replace fillers with brief pauses. Silence projects confidence; "
                    "fillers project uncertainty."
                ),
            })
        else:
            details.append({
                "explanation": (
                    f"Filler word rate: {filler_rate:.1f} per minute — well controlled. "
                    "Minimal filler usage signals verbal discipline."
                ),
            })

    # Response latency
    if latency is not None:
        if latency > 8:
            severity = "warning" if severity == "info" else severity
            details.append({
                "explanation": (
                    f"Average response latency: {latency:.1f} seconds — long pauses detected. "
                    "Extended silence (>5s) before answering reads as being caught off-guard. "
                    "A 2-3 second 'let me think about that' pause is acceptable."
                ),
            })
        elif latency < 0.5 and turns:
            details.append({
                "explanation": (
                    f"Average response latency: {latency:.1f} seconds — extremely fast. "
                    "While quick responses can show readiness, they may also indicate "
                    "rehearsed or shallow answers."
                ),
            })

    # Dead silence / insufficient signal
    if not details:
        if audio.get("insufficient_evidence"):
            details.append({
                "explanation": (
                    "Insufficient audio signal captured. Vocal delivery metrics could not "
                    "be computed. Ensure your microphone is active and positioned correctly."
                ),
            })
        else:
            details.append({
                "explanation": "No vocal delivery anomalies detected."
            })

    metrics = {
        "words_per_minute": wpm,
        "filler_words_per_minute": round(filler_rate, 1),
        "response_latency_avg": round(latency, 1) if latency is not None else None,
        "clarity_proxy": round(clarity * 100, 1) if clarity else None,
    }

    return {
        "title": "Vocal Delivery & Confidence Metrics",
        "severity": severity,
        "verdict": (
            "Vocal delivery significantly undermines your credibility."
            if severity == "critical" else
            "Vocal delivery has improvement areas."
            if severity == "warning" else
            "Vocal delivery is within acceptable parameters."
        ),
        "details": details,
        "metrics": metrics,
    }


def _self_review_signals(
    self_review: Dict[str, Any],
    video: Dict[str, Any],
) -> Dict[str, Any]:
    """Summarize optional coaching signals without judging the user."""
    events = self_review.get("events") or []
    video_flags = video.get("flags") or []
    details: List[Dict[str, Any]] = []
    for event in events:
        event_type = str(event.get("event_type") or "signal")
        count = int(event.get("count") or 0)
        if count > 0:
            details.append({
                "event_type": event_type.replace("_", " ").title(),
                "count": count,
                "event_severity": "info",
                "explanation": "Optional coaching observed this signal for your private self-review. It is not a cheating or hiring decision.",
            })
    for flag in video_flags:
        if isinstance(flag, dict) and int(flag.get("count") or 0) > 0:
            details.append({
                "event_type": str(flag.get("event_type") or "camera signal").replace("_", " ").title(),
                "count": int(flag.get("count") or 0),
                "event_severity": "info",
                "explanation": "Optional camera coaching produced a self-review signal. The signal does not invalidate the session.",
            })
    if not details:
        details.append({
            "event_type": "No optional signals",
            "event_severity": "info",
            "explanation": "No optional coaching signals were recorded for this session.",
        })
    return {
        "title": "Optional self-review signals",
        "severity": "info",
        "verdict": "These signals are private coaching context only; PrepMate does not score or label them as cheating.",
        "details": details,
        "mode": "self_review",
    }


# ──────────────────────────────────────────
#  Shared Builders
# ──────────────────────────────────────────

def _build_self_review_verdict(
    self_review: Dict[str, Any],
    video: Dict[str, Any],
) -> Dict[str, Any]:
    events = self_review.get("events") or []
    return {
        "label": "Self-review only",
        "signal_count": sum(int(e.get("count") or 0) for e in events),
        "mode": "self_review",
    }


def _build_unknown_unknowns(
    track: Dict[str, Any],
    integrity: Dict[str, Any],
    report: Dict[str, Any],
    is_technical: bool,
) -> List[Dict[str, str]]:
    """Surface 3-5 things the candidate didn't know they didn't know."""
    unknowns: List[Dict[str, str]] = []

    if is_technical:
        # Logic teardown unknowns
        logic = track.get("logic_teardown", {})
        if logic.get("severity") == "critical":
            unknowns.append({
                "title": "False confidence from passing visible tests",
                "insight": (
                    "You likely left the session believing your solution was correct "
                    "because visible tests passed. But visible tests are deliberately "
                    "easy — they test the happy path. The hidden tests, which determine "
                    "your actual score, exposed fundamental logical gaps."
                ),
            })

        # Complexity unknowns
        complexity = track.get("complexity_overheads", {})
        if complexity.get("severity") == "warning":
            unknowns.append({
                "title": "Hidden performance costs you didn't notice",
                "insight": (
                    "Your code contains anti-patterns that create hidden quadratic or "
                    "exponential overhead. These won't fail on small test cases but will "
                    "TLE (Time Limit Exceeded) on production-scale inputs."
                ),
            })

        # Optimal delta unknowns
        delta = track.get("optimal_delta", {})
        if delta.get("severity") == "warning":
            unknowns.append({
                "title": "You used the wrong data structure entirely",
                "insight": (
                    "The gold standard approach for this problem uses a fundamentally "
                    "different algorithmic paradigm than what you implemented. Even if your "
                    "solution passes, interviewers assess whether you recognize the optimal "
                    "approach — not just whether your brute force works."
                ),
            })

        # Edge case unknowns
        edge = track.get("edge_case_forensics", {})
        if edge.get("severity") in {"critical", "warning"}:
            unknowns.append({
                "title": "Your mental model of the input space was incomplete",
                "insight": (
                    "You tested against your mental model of 'normal' inputs, but the actual "
                    "input space includes edge cases you never considered: empty collections, "
                    "negative values, integer boundaries, and null references."
                ),
            })
    else:
        # Content accuracy unknowns
        content = track.get("content_accuracy", {})
        if content.get("severity") in {"critical", "warning"}:
            unknowns.append({
                "title": "Your answers sound confident but lack substance",
                "insight": (
                    "You delivered answers with verbal confidence, but the actual content "
                    "was shallow. Interviewers distinguish between 'sounds like they know' "
                    "and 'actually knows.' Your answers fell into the first category."
                ),
            })

        # Vocal delivery unknowns
        vocal = track.get("vocal_delivery", {})
        if vocal.get("severity") in {"critical", "warning"}:
            metrics = vocal.get("metrics", {})
            filler = metrics.get("filler_words_per_minute") or 0
            if filler > 3:
                unknowns.append({
                    "title": "Your filler words are a subconscious confidence leak",
                    "insight": (
                        "You likely don't notice how often you say 'um,' 'like,' or 'you know.' "
                        "But interviewers do. High filler density is unconsciously mapped to "
                        "low confidence — regardless of your actual knowledge level."
                    ),
                })

        # Optional camera/screen observations remain private coaching context;
        # they are deliberately excluded from performance unknowns.

    # Always add at least one insight
    if not unknowns:
        overall = report.get("overall_score") or 0
        if overall < 70:
            unknowns.append({
                "title": "The gap between your self-assessment and your score is the real problem",
                "insight": (
                    "Most candidates overestimate their performance by 15-25 points. "
                    "If you left this session feeling 'it went okay,' your calibration "
                    "itself is the thing to fix."
                ),
            })
        else:
            unknowns.append({
                "title": "Consistency is the next frontier",
                "insight": (
                    "Your performance is above average, but interviewers evaluate consistency "
                    "across all questions — not just peaks. One weak answer in five can shift "
                    "a positive signal to a weaker signal."
                ),
            })

    return unknowns[:5]


def _build_executive_summary(
    track: Dict[str, Any],
    integrity: Dict[str, Any],
    report: Dict[str, Any],
    is_technical: bool,
) -> str:
    """2-3 sentence brutally honest executive summary."""
    overall = report.get("overall_score") or 0
    readiness = report.get("readiness_label") or "Unknown"
    review_note = "Optional coaching signals are private and are not used as a pass/fail judgment."

    if is_technical:
        logic = track.get("logic_teardown", {})
        logic_severity = logic.get("severity", "info")
        if logic_severity == "critical":
            return (
                f"Overall score: {overall:.0f}/100. {review_note} "
                "Your code compiled and ran, but the underlying logic is fundamentally broken. "
                "You passed visible test cases and likely left the session with false confidence — "
                "the hidden test cases tell a different story. Fix your algorithmic approach "
                "before practicing speed."
            )
        elif overall >= 80:
            return (
                f"Overall score: {overall:.0f}/100. {review_note} "
                f"Readiness: {readiness}. Your technical submission is solid — correctness, "
                "complexity, and edge-case handling are all within acceptable range. "
                "Focus now on verbalizing your thought process during coding."
            )
        else:
            return (
                f"Overall score: {overall:.0f}/100. {review_note} "
                f"Readiness: {readiness}. Your submission shows partial understanding but "
                "falls short of the bar. Review the optimal approach for this problem class "
                "and practice with tighter time constraints."
            )
    else:
        content = track.get("content_accuracy", {})
        vocal = track.get("vocal_delivery", {})
        content_severity = content.get("severity", "info")
        vocal_severity = vocal.get("severity", "info")

        if content_severity == "critical":
            return (
                f"Overall score: {overall:.0f}/100. {review_note} "
                "Multiple answers lacked the technical depth and specificity expected "
                "at this interview level. Your verbal delivery may feel confident to you, "
                "but the substance behind it is thin. Prioritize depth over breadth."
            )
        elif vocal_severity == "critical":
            return (
                f"Overall score: {overall:.0f}/100. {review_note} "
                "Your content knowledge is adequate, but your vocal delivery is actively "
                "undermining it. High filler word frequency and pacing issues project "
                "uncertainty regardless of what you actually say."
            )
        elif overall >= 80:
            return (
                f"Overall score: {overall:.0f}/100. {review_note} "
                f"Readiness: {readiness}. Strong session — your answers showed structured "
                "thinking with concrete examples. Polish consistency across all questions."
            )
        else:
            return (
                f"Overall score: {overall:.0f}/100. {review_note} "
                f"Readiness: {readiness}. Your session shows promise but needs focused "
                "work on answer depth, evidence quality, and delivery composure."
            )


# ──────────────────────────────────────────
#  Utility Helpers
# ──────────────────────────────────────────

def _avg(values: List[float]) -> float:
    clean = [float(v) for v in values if v is not None]
    return round(sum(clean) / len(clean), 1) if clean else 0.0
