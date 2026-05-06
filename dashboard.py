from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
import re
import logging
import json

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator

from auth import get_current_admin, get_current_user
from database import get_db_connection, return_db_connection
from security_utils import stable_hash

router = APIRouter(tags=["Dashboard"])
logger = logging.getLogger("ai_interviewer.dashboard")


class JobResponse(BaseModel):
    job_id: int
    title: str
    description: str
    company: Optional[str]
    location: Optional[str]
    salary_range: Optional[str]
    experience_level: Optional[str]
    created_at: datetime


class JobProfileCreate(BaseModel):
    role: str = Field(min_length=2, max_length=255)
    company: Optional[str] = Field(default=None, max_length=255)
    tech_stack: List[str] = Field(default_factory=list)

    @field_validator("role", "company")
    @classmethod
    def normalize_profile_text(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        text = value.strip()
        return text or None

    @field_validator("tech_stack")
    @classmethod
    def normalize_tech_stack(cls, value: List[str]) -> List[str]:
        tags: List[str] = []
        seen = set()
        for item in value or []:
            text = str(item).strip()
            if not text:
                continue
            key = text.lower()
            if key in seen:
                continue
            seen.add(key)
            tags.append(text[:40])
        return tags[:12]


class JobProfileResponse(BaseModel):
    profile_id: int
    role: str
    company: Optional[str]
    tech_stack: List[str]
    is_selected: bool
    created_at: datetime


class SupportSubmissionCreate(BaseModel):
    kind: str
    title: Optional[str] = None
    message: str = Field(min_length=10, max_length=5000)
    steps: Optional[str] = Field(default=None, max_length=4000)
    rating: Optional[int] = Field(default=None, ge=1, le=5)
    interview_id: Optional[str] = None
    page_url: Optional[str] = Field(default=None, max_length=1000)

    @field_validator("kind")
    @classmethod
    def validate_kind(cls, value: str) -> str:
        normalized = (value or "").strip().lower()
        if normalized not in {"bug", "feedback"}:
            raise ValueError("kind must be either 'bug' or 'feedback'")
        return normalized

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        text = value.strip()
        return text or None

    @field_validator("steps", "page_url")
    @classmethod
    def normalize_optional_text(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        text = value.strip()
        return text or None


class SupportSubmissionUpdate(BaseModel):
    status: Optional[str] = None
    admin_notes: Optional[str] = Field(default=None, max_length=4000)

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip().lower()
        if normalized not in {"open", "reviewing", "resolved", "closed"}:
            raise ValueError("Unsupported status")
        return normalized

    @field_validator("admin_notes")
    @classmethod
    def normalize_notes(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        text = value.strip()
        return text or None


def _avg(values: List[float]) -> float:
    clean = [float(value) for value in values if value is not None]
    return round(sum(clean) / len(clean), 1) if clean else 0.0


def _clip(value: float, low: float = 0, high: float = 100) -> float:
    return round(max(low, min(high, value)), 1)


def _score_band(score: float) -> str:
    if score >= 85:
        return "Strong"
    if score >= 70:
        return "Ready with refinement"
    if score >= 55:
        return "Developing"
    return "Needs focused practice"


def _json_value(value: Any, fallback: Any) -> Any:
    if value is None:
        return fallback
    return value


def _text_tokens(value: str) -> List[str]:
    return re.findall(r"[A-Za-z][A-Za-z0-9+#.-]{1,}", value.lower())


METRIC_RE = re.compile(
    r"(?i)(?:\b\d+(?:\.\d+)?\s?(?:%|x|k|m|ms|s|sec|secs|seconds|mins|minutes|hrs|hours|days|users|customers|requests|qps|rps|rows|records|tickets|bugs|issues|projects|models|apis|endpoints|features|revenue|cost|latency|uptime|accuracy|precision|recall)\b|(?:₹|\$)\s?\d+(?:[,.]\d+)*)"
)


def _contains_metric(value: str) -> bool:
    return bool(METRIC_RE.search(value or ""))


def _question_family(question_type: str, question: str) -> str:
    text = f"{question_type or ''} {question or ''}".lower()
    if any(token in text for token in ["tell me about yourself", "introduce yourself", "background"]):
        return "Tell me about yourself"
    if any(token in text for token in ["why this role", "why do you want", "why should", "company", "role"]):
        return "Why this role"
    if any(token in text for token in ["project", "built", "implemented", "portfolio"]):
        return "Explain your project"
    return "Technical deep-dive"


def _drill_steps_for(question_type: str, question: str, topic: str, anchor: str) -> List[Dict[str, str]]:
    family = _question_family(question_type, question)
    topic_text = topic or "this topic"
    if family == "Explain your project":
        return [
            {"title": "Outcome first", "instruction": f"Open with what {anchor} achieved and why it mattered."},
            {"title": "Your ownership", "instruction": "State the exact part you designed, built, fixed, or measured."},
            {"title": "Technical choice", "instruction": f"Name the stack or design decision that mattered most for {topic_text}."},
            {"title": "Trade-off", "instruction": "Explain one constraint, alternative, or failure mode you considered."},
            {"title": "Result", "instruction": "Close with a number, user impact, latency gain, accuracy change, or shipped outcome."},
        ]
    if family == "Why this role":
        return [
            {"title": "Role hook", "instruction": f"Name the specific part of the role that matches your work in {topic_text}."},
            {"title": "Evidence", "instruction": f"Use {anchor} or one prior project as proof that you have done similar work."},
            {"title": "Company fit", "instruction": "Connect one company need, product area, or user problem to your skills."},
            {"title": "Contribution", "instruction": "Say what you can improve or own in the first few months."},
            {"title": "Close", "instruction": "End with a concise reason the role is a logical next step, not a generic preference."},
        ]
    if family == "Tell me about yourself":
        return [
            {"title": "Present identity", "instruction": f"Start with who you are professionally and your focus in {topic_text}."},
            {"title": "Proof story", "instruction": f"Use {anchor} as the concrete example that proves the claim."},
            {"title": "Skill bridge", "instruction": "Name two skills or decisions from that story that map to the interview role."},
            {"title": "Result", "instruction": "Include one measurable outcome or visible deliverable."},
            {"title": "Forward link", "instruction": "Close by connecting your background to the role you are interviewing for."},
        ]
    return [
        {"title": "Direct answer", "instruction": f"Answer the {topic_text} question in one sentence before explaining."},
        {"title": "Mechanism", "instruction": "Describe the components, data flow, algorithm, or API boundary involved."},
        {"title": "Trade-off", "instruction": "Compare the chosen approach with one alternative and say why yours fit."},
        {"title": "Failure case", "instruction": "Mention one edge case, bottleneck, or debugging signal."},
        {"title": "Proof", "instruction": "End with evidence: a metric, test result, production behavior, or project outcome."},
    ]


def _strong_answer_for(response: Dict[str, Any], anchor: str) -> str:
    family = _question_family(response.get("question_type") or "", response.get("question") or "")
    topic = response.get("topic") or "the topic"
    if family == "Explain your project":
        return (
            f"In {anchor}, I owned the part related to {topic}. The key decision was to explain the problem, "
            "the stack I used, the constraint I hit, and the measurable result. A strong version would name the "
            "technical choice, the trade-off, and the outcome in one tight story."
        )
    if family == "Why this role":
        return (
            f"I would connect this role to my past work in {topic}, then prove the match with {anchor}. "
            "A strong answer names the exact role requirement, one concrete example from my work, and the impact I can create next."
        )
    if family == "Tell me about yourself":
        return (
            f"I am a candidate focused on {topic}, with proof from {anchor}. A strong answer gives the current focus, "
            "one relevant project or experience, a measurable outcome, and a direct bridge to this role."
        )
    return (
        f"The direct answer is the first sentence. Then I would explain how {topic} works, the main trade-off, "
        f"one edge case, and proof from {anchor} or a measurable result."
    )


def _profile_list(items: Any) -> List[Dict[str, Any]]:
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def _profile_context(cursor, user_id: str) -> Dict[str, Any]:
    cursor.execute(
        """
        SELECT mock_interview_count, practice_interview_count, profile_completed,
               resume_json, profile_json, interviews_remaining, plan_type,
               external_profile_signals
        FROM UserInfo
        WHERE user_id = %s
        """,
        (user_id,)
    )
    row = cursor.fetchone()
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    resume_json = row[3] or {}
    profile_json = row[4] or {}
    context = dict(resume_json or profile_json or {})
    context["projects"] = context.get("projects") or profile_json.get("projects") or []
    context["experience"] = (
        context.get("experience")
        or context.get("experiences")
        or profile_json.get("experience")
        or profile_json.get("experiences")
        or []
    )
    context["skills"] = context.get("skills") or profile_json.get("skills") or []
    context["external_profile_signals"] = row[7] or {}
    return {
        "mock_interview_count": row[0] or 0,
        "practice_interview_count": row[1] or 0,
        "profile_completed": bool(row[2]),
        "resume_json": resume_json,
        "profile_json": profile_json,
        "interviews_remaining": row[5] or 0,
        "plan_type": row[6] or "free",
        "profile_context": context,
    }


def _profile_anchor(profile_context: Dict[str, Any]) -> str:
    for project in _profile_list(profile_context.get("projects")):
        name = str(project.get("name") or "").strip()
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


def _target_role(profile_context: Dict[str, Any]) -> str:
    return (
        profile_context.get("target_role")
        or profile_context.get("targetRole")
        or "your target role"
    )


def _profile_keywords(profile_context: Dict[str, Any]) -> set[str]:
    keywords: set[str] = set()

    for project in _profile_list(profile_context.get("projects"))[:5]:
        keywords.update(_text_tokens(str(project.get("name") or "")))
        keywords.update(_text_tokens(str(project.get("description") or "")))
        techs = project.get("technologies") or []
        if isinstance(techs, list):
            for tech in techs[:8]:
                keywords.update(_text_tokens(str(tech)))

    for exp in _profile_list(profile_context.get("experience"))[:4]:
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


def _recent_interviews(cursor, user_id: str, limit: int = 20) -> List[Dict[str, Any]]:
    cursor.execute(
        """
        SELECT interview_id, interview_type, job_title,
               overall_score, created_at, interview_mode
        FROM Interviews
        WHERE user_id = %s AND status = 'completed' AND overall_score IS NOT NULL
        ORDER BY created_at DESC
        LIMIT %s
        """,
        (user_id, limit)
    )
    rows = cursor.fetchall()
    items = []
    for row in rows:
        items.append({
            "interview_id": row[0],
            "interview_type": row[1],
            "job_title": row[2],
            "score": float(row[3]) if row[3] is not None else 0.0,
            "date": row[4].isoformat() if row[4] else None,
            "mode": row[5],
        })
    items.reverse()
    return items


def _response_rows(cursor, interview_ids: List[str]) -> List[Dict[str, Any]]:
    if not interview_ids:
        return []

    placeholders = ",".join(["%s"] * len(interview_ids))
    cursor.execute(
        f"""
        SELECT iq.question_text, iq.question_type, iq.is_followup,
               COALESCE(iq.topic_label, i.job_title, 'General') AS topic_label,
               ir.score, ir.response_time_seconds, ir.technical_accuracy,
               ir.communication, ir.problem_solving, ir.confidence, ir.relevance,
               ir.answer_quality_flags, ir.evidence_quotes, ir.ai_feedback,
               ir.user_response, ir.interview_id, ir.created_at
        FROM InterviewResponses ir
        JOIN InterviewQuestions iq ON ir.question_id = iq.question_id
        JOIN Interviews i ON ir.interview_id = i.interview_id
        WHERE ir.interview_id IN ({placeholders})
        ORDER BY ir.created_at
        """,
        tuple(interview_ids)
    )

    items = []
    for row in cursor.fetchall():
        items.append({
            "question": row[0],
            "question_type": row[1] or "main",
            "is_followup": bool(row[2]),
            "topic": row[3] or "General",
            "score": float(row[4]) if row[4] is not None else None,
            "response_time": float(row[5]) if row[5] is not None else None,
            "technical_accuracy": float(row[6]) if row[6] is not None else None,
            "communication": float(row[7]) if row[7] is not None else None,
            "problem_solving": float(row[8]) if row[8] is not None else None,
            "confidence": float(row[9]) if row[9] is not None else None,
            "relevance": float(row[10]) if row[10] is not None else None,
            "answer_quality_flags": row[11] or [],
            "evidence_quotes": row[12] or [],
            "feedback": row[13] or "",
            "response": row[14] or "",
            "interview_id": row[15],
            "created_at": row[16],
        })
    return items


def _weak_pattern_details(flag: str) -> Dict[str, str]:
    mapping = {
        "too_short": {
            "impact": "Your answer ends before the interviewer sees your reasoning.",
            "coaching": "Use: answer, example, result, trade-off.",
        },
        "vague": {
            "impact": "You sound generally aware, but not convincingly hands-on.",
            "coaching": "Name the exact tool, decision, constraint, and measurable result.",
        },
        "off_topic": {
            "impact": "The interviewer has to work to find your real answer.",
            "coaching": "Start with the direct answer first, then add the extra context.",
        },
        "no_evidence": {
            "impact": "Claims do not feel proven, so your credibility drops.",
            "coaching": "Attach each claim to a project, internship, repo, or metric.",
        },
    }
    return mapping.get(flag, {
        "impact": "This pattern is dragging down answer quality.",
        "coaching": "Tighten the answer with a direct point and one concrete example.",
    })


def _build_coaching_snapshot(profile_context: Dict[str, Any], interviews: List[Dict[str, Any]], responses: List[Dict[str, Any]]) -> Dict[str, Any]:
    total_questions = len(responses)
    total_interviews = len(interviews)
    scores = [item["score"] for item in interviews]
    latest_score = scores[-1] if scores else 0.0
    avg_overall = _avg(scores)
    improvement = scores[-1] - scores[0] if len(scores) > 1 else 0.0

    topic_scores: Dict[str, List[float]] = defaultdict(list)
    response_times: List[float] = []
    question_type_scores = {"main": [], "followup": []}
    rubric_scores = {
        "technical_depth": [],
        "communication": [],
        "problem_solving": [],
        "confidence": [],
        "relevance": [],
    }
    quality_counter: Counter = Counter()
    evidence_supported_answers = 0
    profile_keywords = _profile_keywords(profile_context)
    aligned_answers = 0
    low_score_examples: List[Dict[str, Any]] = []
    scored_responses: List[Dict[str, Any]] = []
    quantified_answers = 0

    for response in responses:
        score = response.get("score")
        if score is not None:
            topic_scores[response["topic"]].append(score)
            if response["is_followup"]:
                question_type_scores["followup"].append(score)
            else:
                question_type_scores["main"].append(score)
            scored_responses.append(response)

        if response.get("response_time") is not None:
            response_times.append(response["response_time"])

        if response.get("technical_accuracy") is not None:
            rubric_scores["technical_depth"].append(response["technical_accuracy"])
        if response.get("communication") is not None:
            rubric_scores["communication"].append(response["communication"])
        if response.get("problem_solving") is not None:
            rubric_scores["problem_solving"].append(response["problem_solving"])
        if response.get("confidence") is not None:
            rubric_scores["confidence"].append(response["confidence"])
        if response.get("relevance") is not None:
            rubric_scores["relevance"].append(response["relevance"])

        flags = response.get("answer_quality_flags") or []
        if isinstance(flags, str):
            flags = [flags]
        quality_counter.update(flags)

        evidence_quotes = response.get("evidence_quotes") or []
        if isinstance(evidence_quotes, list) and evidence_quotes:
            evidence_supported_answers += 1

        response_text = str(response.get("response") or "").lower()
        if _contains_metric(response_text):
            quantified_answers += 1
        if profile_keywords and any(keyword in response_text for keyword in profile_keywords):
            aligned_answers += 1

        if score is not None and score < 65 and response.get("feedback"):
            low_score_examples.append({
                "question": str(response.get("question") or "")[:120],
                "topic": response.get("topic") or "General",
                "score": score,
                "feedback": response.get("feedback") or "",
                "is_followup": response.get("is_followup", False),
            })

    rubric_breakdown = {
        key: _avg(values)
        for key, values in rubric_scores.items()
    }
    weak_topics = [
        {"topic": topic, "avg_score": _avg(values), "attempts": len(values)}
        for topic, values in sorted(topic_scores.items(), key=lambda item: _avg(item[1]))
        if values
    ][:4]

    main_avg = _avg(question_type_scores["main"])
    followup_avg = _avg(question_type_scores["followup"])
    followup_gap = round(followup_avg - main_avg, 1) if question_type_scores["followup"] else 0.0

    weak_topic_penalty = len([item for item in weak_topics if item["avg_score"] < 65]) * 4
    readiness = _clip((avg_overall * 0.65) + (latest_score * 0.20) + ((50 + improvement * 2) * 0.15) - weak_topic_penalty)

    total_questions_safe = max(total_questions, 1)
    off_topic_rate = quality_counter.get("off_topic", 0) / total_questions_safe
    vague_rate = quality_counter.get("vague", 0) / total_questions_safe
    no_evidence_rate = quality_counter.get("no_evidence", 0) / total_questions_safe
    too_short_rate = quality_counter.get("too_short", 0) / total_questions_safe
    evidence_rate = evidence_supported_answers / total_questions_safe
    alignment_rate = aligned_answers / total_questions_safe

    answer_clarity = _clip(
        (rubric_breakdown["communication"] * 0.55)
        + (rubric_breakdown["relevance"] * 0.45)
        - (off_topic_rate * 35)
        - (vague_rate * 22)
    )
    technical_depth = _clip(
        (rubric_breakdown["technical_depth"] * 0.45)
        + (rubric_breakdown["problem_solving"] * 0.35)
        + ((followup_avg or avg_overall) * 0.20)
    )
    proof_of_work = _clip(
        68
        - (no_evidence_rate * 32)
        - (too_short_rate * 20)
        + (evidence_rate * 18)
        + (alignment_rate * 18)
    )

    anchor = _profile_anchor(profile_context)
    target_role = _target_role(profile_context)
    pillar_scores = {
        "interview_readiness": readiness,
        "answer_clarity": answer_clarity,
        "technical_depth": technical_depth,
        "proof_of_work": proof_of_work,
    }

    pillar_insights = {
        "interview_readiness": (
            "Your recent sessions are getting more interview-ready."
            if improvement >= 5
            else "You need more consistency across sessions before this feels interview-ready."
        ),
        "answer_clarity": (
            "Your explanations are mostly landing clearly."
            if answer_clarity >= 70
            else "Your answers need a cleaner structure so interviewers can follow your thinking faster."
        ),
        "technical_depth": (
            "You are showing decent depth when pushed."
            if technical_depth >= 70
            else "Follow-up questions are still exposing shallow reasoning or missing trade-offs."
        ),
        "proof_of_work": (
            f"You are using {anchor} and other proof points well."
            if proof_of_work >= 70
            else f"You need to tie more answers back to {anchor}, your resume, or measurable outcomes."
        ),
    }

    weakest_pillar_key = min(pillar_scores.items(), key=lambda item: item[1])[0] if pillar_scores else "interview_readiness"
    focus_map = {
        "interview_readiness": {
            "title": "Stabilize interview readiness",
            "reason": "Your overall performance still swings too much between questions.",
            "action": "Run one full mock and rehearse your two weakest answers before the next attempt.",
        },
        "answer_clarity": {
            "title": "Make answers easier to follow",
            "reason": "Your ideas are not landing cleanly enough under time pressure.",
            "action": "Practice 60-second answers with a direct point, example, result, and trade-off.",
        },
        "technical_depth": {
            "title": "Get stronger under probing",
            "reason": "Follow-up questions are exposing missing depth.",
            "action": "Prepare one deeper explanation with constraints, trade-offs, and edge cases.",
        },
        "proof_of_work": {
            "title": "Back claims with proof",
            "reason": "You are not using enough concrete proof points from your work.",
            "action": f"Prepare 3 proof stories from {anchor} that you can reuse across common questions.",
        },
    }
    focus = focus_map[weakest_pillar_key]
    primary_focus = {
        **focus,
        "interviewer_signal": f"For {target_role}, interviewers are likely noticing whether you can explain decisions from {anchor} with specifics and confidence.",
        "project_anchor": anchor,
    }

    student_summary = {
        "headline": f"You are {_score_band(readiness).lower()} for {target_role}.",
        "blocker": primary_focus["reason"],
        "next_step": primary_focus["action"],
        "interviewer_signal": primary_focus["interviewer_signal"],
        "proof_point": f"Use {anchor} as your safest go-to story when you need evidence quickly.",
    }

    coaching_metrics = {
        key: {
            "score": value,
            "label": _score_band(value),
            "insight": pillar_insights[key],
        }
        for key, value in pillar_scores.items()
    }

    weak_patterns = [
        {
            "pattern": flag.replace("_", " ").title(),
            "count": count,
            "impact": _weak_pattern_details(flag)["impact"],
            "coaching": _weak_pattern_details(flag)["coaching"],
        }
        for flag, count in quality_counter.most_common(4)
        if flag
    ]

    pressure_points = [
        {
            "question": item["question"],
            "topic": item["topic"],
            "score": round(item["score"], 1),
            "kind": "follow-up" if item["is_followup"] else "main",
            "coaching": item["feedback"],
        }
        for item in sorted(low_score_examples, key=lambda row: row["score"])[:4]
    ]

    worst_responses = sorted(
        [item for item in scored_responses if item.get("question") and item.get("response")],
        key=lambda row: float(row.get("score") or 0),
    )
    weakest_answer = worst_responses[0] if worst_responses else None

    today_drill = None
    if weakest_answer:
        today_drill = {
            "question": weakest_answer.get("question"),
            "question_type": _question_family(weakest_answer.get("question_type") or "", weakest_answer.get("question") or ""),
            "topic": weakest_answer.get("topic") or "General",
            "score": round(float(weakest_answer.get("score") or 0), 1),
            "user_answer": weakest_answer.get("response") or "",
            "steps": _drill_steps_for(
                weakest_answer.get("question_type") or "",
                weakest_answer.get("question") or "",
                weakest_answer.get("topic") or "General",
                anchor,
            ),
        }

    answer_comparisons = [
        {
            "question": item.get("question"),
            "topic": item.get("topic") or "General",
            "score": round(float(item.get("score") or 0), 1),
            "their_answer": item.get("response") or "",
            "strong_answer": _strong_answer_for(item, anchor),
        }
        for item in worst_responses[:3]
    ]

    now = datetime.utcnow()
    best_answer_candidates = [
        item for item in scored_responses
        if item.get("response") and item.get("created_at")
        and (now - item["created_at"]).days <= 7
    ] or [item for item in scored_responses if item.get("response")]
    best_answer = None
    if best_answer_candidates:
        item = max(best_answer_candidates, key=lambda row: float(row.get("score") or 0))
        best_answer = {
            "question": item.get("question"),
            "topic": item.get("topic") or "General",
            "score": round(float(item.get("score") or 0), 1),
            "answer": item.get("response") or "",
            "date": item.get("created_at").isoformat() if item.get("created_at") else None,
        }

    pattern_diagnoses: List[Dict[str, str]] = []
    if quantified_answers == 0 and total_questions:
        pattern_diagnoses.append({
            "title": "You never give a number",
            "diagnosis": f"Across {total_questions} answers you used a specific metric 0 times.",
            "fix": "Add one measurable result, scale marker, latency change, accuracy change, or usage number to each proof story.",
        })
    elif total_questions and quantified_answers / total_questions < 0.35:
        pattern_diagnoses.append({
            "title": "Numbers are too rare",
            "diagnosis": f"Only {quantified_answers} of {total_questions} answers contained a concrete metric or result.",
            "fix": "Prepare three reusable metrics from your projects before the next mock.",
        })

    if quality_counter.get("off_topic", 0):
        pattern_diagnoses.append({
            "title": "You bury your point",
            "diagnosis": f"{quality_counter.get('off_topic', 0)} answers made the interviewer search for the direct answer.",
            "fix": "Make the first sentence the answer, then add context only after the point is clear.",
        })
    if quality_counter.get("no_evidence", 0):
        pattern_diagnoses.append({
            "title": "Your claims float",
            "diagnosis": f"{quality_counter.get('no_evidence', 0)} answers made claims without a project, repo, internship, or result attached.",
            "fix": f"Anchor claims to {anchor} or another named proof point before moving on.",
        })
    if followup_gap < -8 and question_type_scores["followup"]:
        pattern_diagnoses.append({
            "title": "Depth drops on follow-ups",
            "diagnosis": f"You scored {main_avg:.1f} on main questions but {followup_avg:.1f} on follow-ups.",
            "fix": "After the first answer, prepare one trade-off, one edge case, and one failure mode for the follow-up.",
        })
    if not pattern_diagnoses:
        pattern_diagnoses.append({
            "title": "Your next gains are structural",
            "diagnosis": f"Across {total_questions} answers, the fastest improvement is consistency rather than more content.",
            "fix": "Use the same structure every time: direct answer, proof, trade-off, result.",
        })
    pattern_diagnoses = pattern_diagnoses[:4]

    weak_question_drill_queue = [
        {
            "question": item.get("question"),
            "topic": item.get("topic") or "General",
            "score": round(float(item.get("score") or 0), 1),
            "question_type": _question_family(item.get("question_type") or "", item.get("question") or ""),
            "interview_id": item.get("interview_id"),
            "steps": _drill_steps_for(
                item.get("question_type") or "",
                item.get("question") or "",
                item.get("topic") or "General",
                anchor,
            ),
        }
        for item in worst_responses[:3]
    ]

    practice_priorities = [
        {
            "title": primary_focus["title"],
            "reason": primary_focus["reason"],
            "action": primary_focus["action"],
        }
    ]
    if weak_topics:
        practice_priorities.append({
            "title": f"Fix {weak_topics[0]['topic']}",
            "reason": f"Average score is {weak_topics[0]['avg_score']:.1f}% across {weak_topics[0]['attempts']} questions.",
            "action": f"Prepare one concise explanation and one deeper follow-up answer for {weak_topics[0]['topic']}.",
        })
    if weak_patterns:
        practice_priorities.append({
            "title": weak_patterns[0]["pattern"],
            "reason": weak_patterns[0]["impact"],
            "action": weak_patterns[0]["coaching"],
        })
    practice_priorities = practice_priorities[:3]

    return {
        "score_trend": interviews,
        "skill_gap": {
            "labels": [topic for topic in list(topic_scores.keys())[:8]],
            "values": [_avg(values) for values in list(topic_scores.values())[:8]],
        },
        "rubric_breakdown": rubric_breakdown,
        "question_type_breakdown": {
            "main_avg": main_avg,
            "followup_avg": followup_avg,
            "main_count": len(question_type_scores["main"]),
            "followup_count": len(question_type_scores["followup"]),
        },
        "response_time": {
            "average": _avg(response_times),
            "fastest": round(min(response_times), 1) if response_times else 0,
            "slowest": round(max(response_times), 1) if response_times else 0,
        },
        "summary": {
            "total_interviews": total_interviews,
            "total_questions": total_questions,
            "average_score": avg_overall,
            "best_score": max(scores) if scores else 0,
            "worst_score": min(scores) if scores else 0,
            "improvement": round(improvement, 1),
        },
        "coaching_metrics": coaching_metrics,
        "pillar_scores": pillar_scores,
        "primary_focus": primary_focus,
        "student_summary": student_summary,
        "today_drill": today_drill,
        "answer_comparisons": answer_comparisons,
        "pattern_diagnoses": pattern_diagnoses,
        "weak_question_drill_queue": weak_question_drill_queue,
        "best_answer_of_week": best_answer,
        "quantification": {
            "answers_with_metrics": quantified_answers,
            "total_answers": total_questions,
        },
        "followup_performance": {
            "main_avg": main_avg,
            "followup_avg": followup_avg,
            "pressure_gap": followup_gap,
            "followup_count": len(question_type_scores["followup"]),
            "insight": (
                "You hold up well when interviewers go deeper."
                if followup_gap >= 0
                else "Your follow-up answers are weaker than your first-pass answers. Prepare deeper reasoning and trade-offs."
            ),
        },
        "weak_patterns": weak_patterns,
        "weak_topics": weak_topics,
        "question_pressure_points": pressure_points,
        "evidence_health": {
            "score": round(proof_of_work, 1),
            "supported_answers": evidence_supported_answers,
            "flagged_answers": quality_counter.get("no_evidence", 0),
            "alignment_rate": round(alignment_rate * 100, 1),
            "note": (
                f"You are using {anchor} effectively."
                if proof_of_work >= 70
                else f"Use {anchor} more often when you need a concrete proof point."
            ),
        },
        "practice_priorities": practice_priorities,
    }


@router.get("/stats")
async def get_dashboard_stats(
    current_user: Dict = Depends(get_current_user)
):
    connection = get_db_connection()
    cursor = connection.cursor()

    try:
        profile_data = _profile_context(cursor, current_user["user_id"])
        interviews = _recent_interviews(cursor, current_user["user_id"], limit=12)
        responses = _response_rows(cursor, [item["interview_id"] for item in interviews])
        coaching = _build_coaching_snapshot(profile_data["profile_context"], interviews, responses)

        completion = 0
        if profile_data["resume_json"]:
            completion += 40
        if profile_data["profile_json"]:
            completion += 30
        if profile_data["profile_completed"]:
            completion += 30

        recent_interviews = [
            {
                "interview_id": item["interview_id"],
                "interview_type": item["interview_type"],
                "job_title": item["job_title"],
                "overall_score": item["score"],
                "created_at": item["date"],
            }
            for item in interviews[-5:]
        ]

        return {
            "total_interviews": profile_data["mock_interview_count"] + profile_data["practice_interview_count"],
            "mock_interviews": profile_data["mock_interview_count"],
            "practice_interviews": profile_data["practice_interview_count"],
            "average_score": coaching["summary"]["average_score"],
            "recent_interviews": recent_interviews,
            "profile_completion": completion,
            "interviews_remaining": profile_data["interviews_remaining"],
            "plan_type": profile_data["plan_type"],
            "coaching_metrics": coaching["coaching_metrics"],
            "primary_focus": coaching["primary_focus"],
            "student_summary": coaching["student_summary"],
            "today_drill": coaching["today_drill"],
            "what_to_fix": coaching["pattern_diagnoses"][:2],
            "quantification": coaching["quantification"],
        }

    finally:
        cursor.close()
        return_db_connection(connection)


@router.get("/coach/exercises")
async def get_coach_exercises(
    current_user: Dict = Depends(get_current_user),
):
    connection = get_db_connection()
    cursor = connection.cursor()
    try:
        cursor.execute(
            """
            SELECT exercise_id, interview_id, exercise_type, title, prompt,
                   project_anchor, weakness_key, status, created_at, completed_at
            FROM CoachExercises
            WHERE user_id = %s
            ORDER BY
                CASE WHEN status = 'pending' THEN 0 ELSE 1 END,
                created_at DESC
            LIMIT 20
            """,
            (current_user["user_id"],)
        )
        return {
            "exercises": [
                {
                    "exercise_id": row[0],
                    "interview_id": row[1],
                    "exercise_type": row[2],
                    "title": row[3],
                    "prompt": row[4],
                    "project_anchor": row[5],
                    "weakness_key": row[6],
                    "status": row[7],
                    "created_at": row[8].isoformat() if row[8] else None,
                    "completed_at": row[9].isoformat() if row[9] else None,
                }
                for row in cursor.fetchall()
            ]
        }
    finally:
        cursor.close()
        return_db_connection(connection)


@router.patch("/coach/exercises/{exercise_id}/complete")
async def complete_coach_exercise(
    exercise_id: str,
    current_user: Dict = Depends(get_current_user),
):
    connection = get_db_connection()
    cursor = connection.cursor()
    try:
        cursor.execute(
            """
            UPDATE CoachExercises
            SET status = 'completed', completed_at = NOW()
            WHERE exercise_id = %s AND user_id = %s
            RETURNING exercise_id
            """,
            (exercise_id, current_user["user_id"])
        )
        if not cursor.fetchone():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Exercise not found")
        connection.commit()
        return {"success": True}
    except HTTPException:
        connection.rollback()
        raise
    finally:
        cursor.close()
        return_db_connection(connection)


def _job_profile_from_row(row: Any) -> Dict[str, Any]:
    tech_stack = row[3] or []
    if isinstance(tech_stack, str):
        try:
            tech_stack = json.loads(tech_stack)
        except Exception:
            tech_stack = []
    return {
        "profile_id": row[0],
        "role": row[1],
        "company": row[2],
        "tech_stack": tech_stack if isinstance(tech_stack, list) else [],
        "is_selected": bool(row[4]),
        "created_at": row[5],
    }


@router.get("/job-profiles", response_model=List[JobProfileResponse])
async def get_job_profiles(
    current_user: Dict = Depends(get_current_user)
):
    connection = get_db_connection()
    cursor = connection.cursor()

    try:
        cursor.execute(
            """
            SELECT profile_id, role, company, tech_stack, is_selected, created_at
            FROM JobProfiles
            WHERE user_id = %s
            ORDER BY is_selected DESC, created_at DESC
            """,
            (current_user["user_id"],)
        )
        return [_job_profile_from_row(row) for row in cursor.fetchall()]

    finally:
        cursor.close()
        return_db_connection(connection)


@router.post("/job-profiles", response_model=JobProfileResponse)
async def create_job_profile(
    request: JobProfileCreate,
    current_user: Dict = Depends(get_current_user)
):
    connection = get_db_connection()
    cursor = connection.cursor()

    try:
        cursor.execute(
            "SELECT COUNT(*) FROM JobProfiles WHERE user_id = %s",
            (current_user["user_id"],)
        )
        is_first = (cursor.fetchone()[0] or 0) == 0

        if is_first:
            cursor.execute(
                "UPDATE JobProfiles SET is_selected = FALSE WHERE user_id = %s",
                (current_user["user_id"],)
            )

        cursor.execute(
            """
            INSERT INTO JobProfiles (user_id, role, company, tech_stack, is_selected)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING profile_id, role, company, tech_stack, is_selected, created_at
            """,
            (
                current_user["user_id"],
                request.role,
                request.company,
                json.dumps(request.tech_stack),
                is_first,
            )
        )
        row = cursor.fetchone()
        connection.commit()
        return _job_profile_from_row(row)

    except Exception:
        connection.rollback()
        logger.error("Failed to create job profile")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create job profile"
        )

    finally:
        cursor.close()
        return_db_connection(connection)


@router.post("/job-profiles/{profile_id}/select", response_model=JobProfileResponse)
async def select_job_profile(
    profile_id: int,
    current_user: Dict = Depends(get_current_user)
):
    connection = get_db_connection()
    cursor = connection.cursor()

    try:
        cursor.execute(
            "SELECT 1 FROM JobProfiles WHERE profile_id = %s AND user_id = %s",
            (profile_id, current_user["user_id"])
        )
        if not cursor.fetchone():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Job profile not found"
            )

        cursor.execute(
            "UPDATE JobProfiles SET is_selected = FALSE WHERE user_id = %s",
            (current_user["user_id"],)
        )
        cursor.execute(
            """
            UPDATE JobProfiles
            SET is_selected = TRUE, updated_at = NOW()
            WHERE profile_id = %s AND user_id = %s
            RETURNING profile_id, role, company, tech_stack, is_selected, created_at
            """,
            (profile_id, current_user["user_id"])
        )
        row = cursor.fetchone()
        connection.commit()
        return _job_profile_from_row(row)

    except HTTPException:
        connection.rollback()
        raise
    except Exception:
        connection.rollback()
        logger.error("Failed to select job profile")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to select job profile"
        )

    finally:
        cursor.close()
        return_db_connection(connection)


@router.get("/jobs", response_model=List[JobResponse])
async def get_all_jobs(
    current_user: Dict = Depends(get_current_user)
):
    connection = get_db_connection()
    cursor = connection.cursor()

    try:
        cursor.execute(
            """
            SELECT job_id, title, description, company, location,
                   salary_range, experience_level, created_at
            FROM Jobs
            ORDER BY created_at DESC
            """
        )

        rows = cursor.fetchall()
        jobs = []

        for row in rows:
            jobs.append(JobResponse(**{
                "job_id": row[0],
                "title": row[1],
                "description": row[2],
                "company": row[3],
                "location": row[4],
                "salary_range": row[5],
                "experience_level": row[6],
                "created_at": row[7]
            }))

        return jobs

    finally:
        cursor.close()
        return_db_connection(connection)


@router.get("/jobs/{job_id}", response_model=JobResponse)
async def get_job_details(
    job_id: int,
    current_user: Dict = Depends(get_current_user)
):
    connection = get_db_connection()
    cursor = connection.cursor()

    try:
        cursor.execute(
            """
            SELECT job_id, title, description, company, location,
                   salary_range, experience_level, created_at
            FROM Jobs
            WHERE job_id = %s
            """,
            (job_id,)
        )

        row = cursor.fetchone()

        if not row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Job not found"
            )

        return JobResponse(**{
            "job_id": row[0],
            "title": row[1],
            "description": row[2],
            "company": row[3],
            "location": row[4],
            "salary_range": row[5],
            "experience_level": row[6],
            "created_at": row[7]
        })

    finally:
        cursor.close()
        return_db_connection(connection)


@router.post("/select-job/{job_id}")
async def select_job(
    job_id: int,
    current_user: Dict = Depends(get_current_user)
):
    connection = get_db_connection()
    cursor = connection.cursor()

    try:
        cursor.execute(
            "SELECT job_id FROM Jobs WHERE job_id = %s",
            (job_id,)
        )

        if not cursor.fetchone():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Job not found"
            )

        cursor.execute(
            "UPDATE UserInfo SET job_id = %s WHERE user_id = %s",
            (job_id, current_user["user_id"])
        )

        connection.commit()
        logger.info("User %s selected job %s", stable_hash(current_user["user_id"], "user"), stable_hash(job_id, "job"))

        return {
            "success": True,
            "message": "Job selected successfully",
            "job_id": job_id
        }

    except HTTPException:
        connection.rollback()
        raise
    except Exception:
        connection.rollback()
        logger.error("Failed to select job")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to select job"
        )

    finally:
        cursor.close()
        return_db_connection(connection)


@router.get("/recent-activity")
async def get_recent_activity(
    current_user: Dict = Depends(get_current_user),
    days: int = 30
):
    connection = get_db_connection()
    cursor = connection.cursor()

    try:
        days = min(max(days, 1), 365)
        start_date = datetime.utcnow() - timedelta(days=days)

        cursor.execute(
            """
            SELECT interview_id, interview_type, job_title,
                   overall_score, created_at, completed_at
            FROM Interviews
            WHERE user_id = %s AND created_at >= %s
            ORDER BY created_at DESC
            """,
            (current_user["user_id"], start_date)
        )

        rows = cursor.fetchall()
        activities = []

        for row in rows:
            activities.append({
                "interview_id": row[0],
                "interview_type": row[1],
                "job_title": row[2],
                "overall_score": float(row[3]) if row[3] is not None else 0.0,
                "created_at": row[4].isoformat() if row[4] else None,
                "completed_at": row[5].isoformat() if row[5] else None
            })

        return {
            "activities": activities,
            "total_count": len(activities),
            "date_range": {
                "from": start_date.isoformat(),
                "to": datetime.utcnow().isoformat()
            }
        }

    finally:
        cursor.close()
        return_db_connection(connection)


@router.get("/performance-trend")
async def get_performance_trend(
    current_user: Dict = Depends(get_current_user),
    limit: int = 10
):
    connection = get_db_connection()
    cursor = connection.cursor()

    try:
        limit = min(max(limit, 1), 100)
        interviews = _recent_interviews(cursor, current_user["user_id"], limit=limit)
        trend_data = [
            {
                "interview_id": item["interview_id"],
                "score": item["score"],
                "date": item["date"],
            }
            for item in interviews
        ]
        improvement = trend_data[-1]["score"] - trend_data[0]["score"] if len(trend_data) > 1 else 0.0

        return {
            "trend": trend_data,
            "improvement": round(improvement, 2),
            "total_interviews": len(trend_data)
        }

    finally:
        cursor.close()
        return_db_connection(connection)


@router.get("/analytics")
async def get_analytics(
    current_user: Dict = Depends(get_current_user),
):
    connection = get_db_connection()
    cursor = connection.cursor()

    try:
        profile_data = _profile_context(cursor, current_user["user_id"])
        interviews = _recent_interviews(cursor, current_user["user_id"], limit=20)
        responses = _response_rows(cursor, [item["interview_id"] for item in interviews])
        return _build_coaching_snapshot(profile_data["profile_context"], interviews, responses)

    finally:
        cursor.close()
        return_db_connection(connection)


@router.post("/support")
async def create_support_submission(
    request: SupportSubmissionCreate,
    current_user: Dict = Depends(get_current_user),
):
    connection = get_db_connection()
    cursor = connection.cursor()

    try:
        if request.interview_id:
            cursor.execute(
                "SELECT 1 FROM Interviews WHERE interview_id = %s AND user_id = %s",
                (request.interview_id, current_user["user_id"])
            )
            if not cursor.fetchone():
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Interview not found for this user"
                )

        cursor.execute(
            """
            INSERT INTO SupportSubmissions (
                user_id, interview_id, kind, title, message, steps, rating, page_url
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING submission_id, status, created_at
            """,
            (
                current_user["user_id"],
                request.interview_id,
                request.kind,
                request.title,
                request.message,
                request.steps,
                request.rating,
                request.page_url,
            )
        )
        row = cursor.fetchone()
        connection.commit()

        return {
            "submission_id": row[0],
            "status": row[1],
            "created_at": row[2].isoformat() if row and row[2] else None,
            "message": "Support request submitted successfully",
        }

    except HTTPException:
        connection.rollback()
        raise
    except Exception:
        connection.rollback()
        logger.error("Failed to create support submission")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to submit support request"
        )

    finally:
        cursor.close()
        return_db_connection(connection)


@router.get("/support/submissions")
async def list_support_submissions(
    current_user: Dict = Depends(get_current_admin),
    limit: int = Query(default=50, ge=1, le=200),
    status_filter: Optional[str] = Query(default=None, alias="status"),
):
    connection = get_db_connection()
    cursor = connection.cursor()

    try:
        where_sql = ""
        params: List[Any] = []
        if status_filter:
            where_sql = "WHERE s.status = %s"
            params.append(status_filter.strip().lower())

        cursor.execute(
            f"""
            SELECT s.submission_id, s.kind, s.status, s.title, s.message, s.steps,
                   s.rating, s.interview_id, s.page_url, s.admin_notes,
                   s.created_at, s.updated_at, l.email, COALESCE(u.full_name, '')
            FROM SupportSubmissions s
            JOIN UserInfo u ON s.user_id = u.user_id
            JOIN Login l ON s.user_id = l.user_id
            {where_sql}
            ORDER BY s.created_at DESC
            LIMIT %s
            """,
            tuple(params + [limit])
        )

        submissions = []
        for row in cursor.fetchall():
            submissions.append({
                "submission_id": row[0],
                "kind": row[1],
                "status": row[2],
                "title": row[3],
                "message": row[4],
                "steps": row[5],
                "rating": row[6],
                "interview_id": row[7],
                "page_url": row[8],
                "admin_notes": row[9],
                "created_at": row[10].isoformat() if row[10] else None,
                "updated_at": row[11].isoformat() if row[11] else None,
                "email": row[12],
                "full_name": row[13] or "User",
            })

        return {"submissions": submissions}

    finally:
        cursor.close()
        return_db_connection(connection)


@router.patch("/support/submissions/{submission_id}")
async def update_support_submission(
    submission_id: int,
    request: SupportSubmissionUpdate,
    current_user: Dict = Depends(get_current_admin),
):
    connection = get_db_connection()
    cursor = connection.cursor()

    try:
        updates = []
        params: List[Any] = []

        if request.status is not None:
            updates.append("status = %s")
            params.append(request.status)
        if request.admin_notes is not None:
            updates.append("admin_notes = %s")
            params.append(request.admin_notes)

        if not updates:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No support submission changes provided"
            )

        params.extend([submission_id])
        cursor.execute(
            f"""
            UPDATE SupportSubmissions
            SET {", ".join(updates)}, updated_at = NOW()
            WHERE submission_id = %s
            RETURNING submission_id, status, admin_notes, updated_at
            """,
            tuple(params)
        )
        row = cursor.fetchone()
        if not row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Support submission not found"
            )
        connection.commit()

        return {
            "submission_id": row[0],
            "status": row[1],
            "admin_notes": row[2],
            "updated_at": row[3].isoformat() if row[3] else None,
        }

    except HTTPException:
        connection.rollback()
        raise
    except Exception:
        connection.rollback()
        logger.error("Failed to update support submission")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update support submission"
        )

    finally:
        cursor.close()
        return_db_connection(connection)
