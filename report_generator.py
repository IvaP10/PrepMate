from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta
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


def _text_tokens(value: str) -> List[str]:
    return re.findall(r"[A-Za-z][A-Za-z0-9+#.-]{1,}", value.lower())


def _normalize_profile_list(items: Any) -> List[Dict[str, Any]]:
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def _profile_anchor(profile_context: Dict[str, Any]) -> str:
    projects = _normalize_profile_list(profile_context.get("projects"))
    if projects:
        name = (projects[0].get("name") or "").strip()
        if name:
            return name

    github = profile_context.get("external_profile_signals", {}).get("github", {})
    repos = github.get("repositories") if isinstance(github, dict) else []
    if isinstance(repos, list):
        for repo in repos:
            if isinstance(repo, dict) and repo.get("name"):
                return str(repo["name"])

    skills = profile_context.get("skills") or []
    if isinstance(skills, list):
        for skill in skills:
            if isinstance(skill, dict) and skill.get("name"):
                return str(skill["name"])
            if isinstance(skill, str) and skill.strip():
                return skill.strip()

    return "your strongest project"


def _target_role(profile_context: Dict[str, Any], interview_meta: Dict[str, Any]) -> str:
    return (
        profile_context.get("target_role")
        or profile_context.get("targetRole")
        or interview_meta.get("job_title")
        or "your target role"
    )


def _profile_keywords(profile_context: Dict[str, Any]) -> set[str]:
    keywords: set[str] = set()

    for project in _normalize_profile_list(profile_context.get("projects"))[:5]:
        keywords.update(_text_tokens(str(project.get("name") or "")))
        keywords.update(_text_tokens(str(project.get("description") or "")))
        techs = project.get("technologies") or []
        if isinstance(techs, list):
            for tech in techs[:8]:
                keywords.update(_text_tokens(str(tech)))

    for exp in _normalize_profile_list(profile_context.get("experience"))[:4]:
        keywords.update(_text_tokens(str(exp.get("title") or exp.get("position") or "")))
        keywords.update(_text_tokens(str(exp.get("company") or "")))

    skills = profile_context.get("skills") or []
    if isinstance(skills, list):
        for skill in skills[:20]:
            if isinstance(skill, dict):
                keywords.update(_text_tokens(str(skill.get("name") or "")))
            else:
                keywords.update(_text_tokens(str(skill)))

    github = profile_context.get("external_profile_signals", {}).get("github", {})
    repos = github.get("repositories") if isinstance(github, dict) else []
    if isinstance(repos, list):
        for repo in repos[:5]:
            if isinstance(repo, dict):
                keywords.update(_text_tokens(str(repo.get("name") or "")))
                keywords.update(_text_tokens(str(repo.get("language") or "")))

    return {token for token in keywords if len(token) > 2}


def _collect_skill_scores(turns: List[Dict[str, Any]]) -> Dict[str, float]:
    scores: Dict[str, float] = {}
    for key, _ in SKILL_KEYS:
        scores[key] = _avg([
            (turn.get("evaluation_json") or {}).get("scores", {}).get(key)
            for turn in turns
        ])
    return scores


def _pillar_scores(turns: List[Dict[str, Any]], skill_scores: Dict[str, float], profile_context: Dict[str, Any]) -> Dict[str, float]:
    if not turns:
        return {
            "interview_readiness": 0.0,
            "answer_clarity": 0.0,
            "technical_depth": 0.0,
            "proof_of_work": 0.0,
        }

    overall_scores = [float(turn.get("score") or 0) for turn in turns]
    overall = _avg(overall_scores)
    improvement = overall_scores[-1] - overall_scores[0] if len(overall_scores) > 1 else 0
    quality = _quality_counter(turns)
    weak_penalty = min(15, (quality.get("off_topic", 0) * 4) + (quality.get("too_short", 0) * 2))
    readiness = _clip((overall * 0.7) + ((50 + improvement * 2) * 0.2) + (skill_scores.get("confidence", 0) * 0.1) - weak_penalty)

    clarity_penalty = min(25, quality.get("off_topic", 0) * 6 + quality.get("vague", 0) * 4)
    answer_clarity = _clip(((skill_scores.get("communication", 0) * 0.55) + (skill_scores.get("relevance", 0) * 0.45)) - clarity_penalty)

    followup_scores = [float(turn.get("score") or 0) for turn in turns if turn.get("is_followup")]
    followup_avg = _avg(followup_scores) if followup_scores else overall
    technical_depth = _clip(
        (skill_scores.get("technical_accuracy", 0) * 0.45)
        + (skill_scores.get("problem_solving", 0) * 0.35)
        + (followup_avg * 0.20)
    )

    keywords = _profile_keywords(profile_context)
    aligned_turns = 0
    evidence_count = 0
    for turn in turns:
        response = str(turn.get("response") or "").lower()
        if keywords and any(keyword in response for keyword in keywords):
            aligned_turns += 1
        quotes = turn.get("evidence_quotes") or []
        if isinstance(quotes, list) and quotes:
            evidence_count += 1

    alignment_rate = aligned_turns / len(turns) if turns else 0
    evidence_rate = evidence_count / len(turns) if turns else 0
    proof_of_work = _clip(
        70
        - (quality.get("no_evidence", 0) * 8)
        - (quality.get("too_short", 0) * 4)
        + (evidence_rate * 20)
        + (alignment_rate * 18)
    )

    return {
        "interview_readiness": readiness,
        "answer_clarity": answer_clarity,
        "technical_depth": technical_depth,
        "proof_of_work": proof_of_work,
    }


def _quality_counter(turns: List[Dict[str, Any]]) -> Counter:
    counter: Counter = Counter()
    for turn in turns:
        flags = turn.get("answer_quality_flags") or []
        if isinstance(flags, str):
            flags = [flags]
        counter.update(flags)
    return counter


def _topic_breakdown(turns: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_topic: Dict[str, List[float]] = defaultdict(list)
    for turn in turns:
        topic = turn.get("topic_label") or turn.get("job_title") or "General"
        by_topic[topic].append(float(turn.get("score") or 0))

    return [
        {"topic": topic, "score": _avg(scores), "turns": len(scores)}
        for topic, scores in sorted(by_topic.items(), key=lambda item: _avg(item[1]))
    ]


def _top_strengths(skill_scores: Dict[str, float], turns: List[Dict[str, Any]]) -> List[str]:
    strengths: List[str] = []
    for key, label in sorted(SKILL_KEYS, key=lambda item: skill_scores.get(item[0], 0), reverse=True):
        if skill_scores.get(key, 0) >= 70:
            strengths.append(f"{label}: your stronger answers showed usable interview signal.")

    best_turns = sorted(turns, key=lambda t: float(t.get("score") or 0), reverse=True)[:2]
    for turn in best_turns:
        feedback = (turn.get("feedback") or "").strip()
        if feedback and len(strengths) < 4:
            strengths.append(feedback)

    return strengths[:4] or ["You completed the session and produced enough signal for targeted coaching."]


def _improvement_items(skill_scores: Dict[str, float], quality: Counter, turns: List[Dict[str, Any]], profile_context: Dict[str, Any]) -> List[Dict[str, str]]:
    items: List[Dict[str, str]] = []
    anchor = _profile_anchor(profile_context)

    weakest = sorted(SKILL_KEYS, key=lambda item: skill_scores.get(item[0], 0))[:3]
    for key, label in weakest:
        score = skill_scores.get(key, 0)
        if score < 75:
            items.append({
                "title": label,
                "detail": f"Current average is {score:.1f}/100. Make the next answer sharper with a direct claim, one concrete example from {anchor}, and the trade-off you handled.",
            })

    quality_guidance = {
        "too_short": "Several answers were too short. Use a 45-90 second structure: direct answer, example, result, trade-off.",
        "vague": "Some answers were broad. Add the exact tools, decisions, numbers, and constraints you handled.",
        "off_topic": "Some answers drifted from the question. Start with the exact answer first, then add context.",
        "no_evidence": f"You need better proof points. Pull examples from {anchor}, your resume, or measurable outcomes instead of generic claims.",
    }
    for flag, _ in quality.most_common(3):
        if flag in quality_guidance:
            items.append({"title": flag.replace("_", " ").title(), "detail": quality_guidance[flag]})

    low_turns = sorted(turns, key=lambda t: float(t.get("score") or 0))[:2]
    for turn in low_turns:
        if turn.get("feedback") and len(items) < 5:
            items.append({
                "title": "Answer-level fix",
                "detail": str(turn["feedback"]),
            })

    return items[:5]


def _practice_plan(improvements: List[Dict[str, str]]) -> List[Dict[str, str]]:
    defaults = [
        ("Day 1", "Rewrite your two weakest answers using direct answer, example, result, trade-off."),
        ("Day 2", "Record three 60-second project explanations and remove vague claims."),
        ("Day 3", "Practice one technical deep dive with edge cases and scaling trade-offs."),
        ("Day 4", "Practice behavioral answers with situation, action, measurable result, reflection."),
        ("Day 5", "Run a timed mock and keep each answer under 90 seconds unless asked to go deeper."),
        ("Day 6", "Review GitHub/resume projects and prepare proof points for your strongest skills."),
        ("Day 7", "Repeat the interview and compare follow-up scores against this session."),
    ]
    if improvements:
        defaults[0] = ("Day 1", improvements[0]["detail"])
    return [{"day": day, "task": task} for day, task in defaults]


def _stronger_answer_outline(turn: Dict[str, Any]) -> str:
    question = (turn.get("question") or "the question").strip()
    return (
        f"Open with a direct answer to: {question[:120]}. "
        "Then give one concrete example, name the technical decision you made, explain the trade-off, "
        "and close with the result or lesson learned."
    )


def _student_summary(interview_meta: Dict[str, Any], pillar_scores: Dict[str, float], improvements: List[Dict[str, str]], profile_context: Dict[str, Any]) -> Dict[str, str]:
    anchor = _profile_anchor(profile_context)
    role = _target_role(profile_context, interview_meta)
    weakest = min(pillar_scores.items(), key=lambda item: item[1])[0] if pillar_scores else "interview_readiness"
    blocker_map = {
        "interview_readiness": "your answers are still uneven from question to question",
        "answer_clarity": "your ideas are there, but they are not landing cleanly enough",
        "technical_depth": "you are not going deep enough when the interviewer probes",
        "proof_of_work": "you are not backing claims with concrete proof often enough",
    }
    blocker = blocker_map.get(weakest, "your weaker answers still need better structure and proof")
    next_step = improvements[0]["detail"] if improvements else f"Rehearse one strong story from {anchor} and keep it ready for follow-up questions."

    return {
        "headline": f"You are {_score_band(pillar_scores.get('interview_readiness', 0)).lower()} for {role}.",
        "blocker": blocker,
        "next_step": next_step,
        "interviewer_signal": f"An interviewer for {role} is likely noticing whether you can explain decisions from {anchor} without drifting or getting vague.",
        "proof_point": f"Use {anchor} as your safest proof point when you need a concrete example.",
    }


def build_report_v2(
    interview_meta: Dict[str, Any],
    turns: List[Dict[str, Any]],
    profile_context: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    profile_context = profile_context or {}
    overall = _avg([float(turn.get("score") or 0) for turn in turns])
    skill_scores = _collect_skill_scores(turns)
    quality = _quality_counter(turns)
    topic_breakdown = _topic_breakdown(turns)
    pillar_scores = _pillar_scores(turns, skill_scores, profile_context)
    improvements = _improvement_items(skill_scores, quality, turns, profile_context)
    avg_time = _avg([float(turn.get("time_taken") or 0) for turn in turns])
    student_summary = _student_summary(interview_meta, pillar_scores, improvements, profile_context)

    per_turn_feedback = []
    for turn in turns:
        per_turn_feedback.append({
            "question": turn.get("question", ""),
            "question_type": turn.get("question_type") or "main",
            "is_followup": bool(turn.get("is_followup")),
            "response": turn.get("response", ""),
            "topic": turn.get("topic_label") or "General",
            "score": float(turn.get("score") or 0),
            "feedback": turn.get("feedback") or "",
            "time_taken": turn.get("time_taken"),
            "coaching_hint": turn.get("coaching_hint") or "",
            "answer_quality_flags": turn.get("answer_quality_flags") or [],
            "evidence_quotes": turn.get("evidence_quotes") or [],
            "retry_state": turn.get("retry_state") or {},
            "stronger_answer_outline": _stronger_answer_outline(turn),
        })

    next_session_at = (datetime.utcnow() + timedelta(days=7)).date().isoformat()
    summary = (
        f"{_score_band(overall)} for {interview_meta.get('job_title') or 'the target role'}. "
        f"You answered {len(turns)} questions with an average score of {overall:.1f}/100. "
        f"The highest-leverage next step is: {improvements[0]['detail'] if improvements else 'repeat the session with more specific examples.'}"
    )

    return {
        "version": "report_v2",
        "summary": summary,
        "readiness_label": _score_band(overall),
        "overall_score": overall,
        "job_title": interview_meta.get("job_title"),
        "mode": interview_meta.get("mode"),
        "interview_type": interview_meta.get("interview_type"),
        "skill_scores": skill_scores,
        "pillar_scores": pillar_scores,
        "topic_breakdown": topic_breakdown,
        "behavioral_metrics": {
            "average_response_time_seconds": avg_time,
            "answer_quality_flags": dict(quality),
            "question_count": len(turns),
        },
        "student_summary": student_summary,
        "strengths": _top_strengths(skill_scores, turns),
        "improvements": improvements,
        "practice_plan": _practice_plan(improvements),
        "per_turn_feedback": per_turn_feedback,
        "next_recommended_session_date": next_session_at,
    }
