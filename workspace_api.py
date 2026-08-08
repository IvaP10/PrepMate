# ============================================================================
# MODULE: workspace_api.py
# PURPOSE: Authenticated workspace API — learning snapshot, exercises (coach +
#          generated), interview profile, job profiles, jobs catalog, recent
#          activity, technical-round history, performance trend, analytics,
#          support submissions.  Mounted under /api/workspace.
# STRUCTURE:
#   - Pydantic models (top ~300 lines)
#   - Helpers for snapshots/aggregations (~middle)
#   - Route handlers (lines 1029-1900)
# ENDPOINTS (prefix /api/workspace):
#   - GET  /stats                         -> headline counters (line 1029)
#   - GET  /learning                      -> learning snapshot (1154)
#   - POST /exercises/{id}/attempt        -> grade attempt (1172)
#   - POST /exercises/{id}/run            -> run code via Piston (1193)
#   - GET/PUT /interview-profile          -> profile_type selector (1275/1303)
#   - GET/POST /job-profiles              -> CRUD per-user job profiles (1349/1373)
#   - POST /job-profiles/{id}/select      -> set selected (1425)
#   - GET  /jobs[/{id}]                   -> public job catalog (1477/1516)
#   - POST /select-job/{id}               -> link UserInfo.job_id (1559)
#   - GET  /recent-activity               -> last N days (1609)
#   - GET  /technical-rounds              -> tech round history (1659)
#   - GET  /performance-trend             -> per-day score series (1715)
#   - GET  /analytics                     -> aggregate analytics (1747)
#   - POST /support                       -> create SupportSubmission (1767)
#   - GET  /support/submissions           -> list (admin only) (1832)
#   - PATCH /support/submissions/{id}     -> update status/notes (1889)
# DEPENDS ON: auth, config, database, interview_profiles, learning_engine,
#             security_utils
# CONSUMED BY: app.py, Frontend/components/app-shell.tsx,
#              Frontend/lib/api.ts (~20 helpers)
# DATA TABLES: UserInfo, Interviews, InterviewResponses, JobProfiles, Jobs,
#              GeneratedExercises, ExerciseAttempts,
#              TechnicalInterviewRounds, LearnerSkillStates, SupportSubmissions
# ============================================================================

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
import re
import logging
import json
import time
import uuid
import hashlib

import aiohttp
from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator

from auth import get_current_admin, get_current_user

from database import async_execute, get_db_connection, return_db_connection
from analysis_pipeline import ANALYSIS_STAGE_VERSION
from interview_profiles import DEFAULT_PROFILE_TYPE, PROFILE_CONFIGS, normalize_profile_type
from learning_engine import (
    _active_mission_payload,
    _exercise_from_row,
    _improvement_history_payload,
    build_error_signature,
    submit_exercise_attempt,
)
from security_utils import decrypt_data, encrypt_data, stable_hash

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


JOB_PROFILE_SELECT = """
    SELECT profile_id, role, company, tech_stack, is_selected, created_at,
           job_description_encrypted, job_description_hash,
           normalized_requirements, normalization_version,
           experience_level, parser_version, updated_at
    FROM JobProfiles
"""

JOB_PROFILE_RETURNING = """
    RETURNING profile_id, role, company, tech_stack, is_selected, created_at,
              job_description_encrypted, job_description_hash,
              normalized_requirements, normalization_version,
              experience_level, parser_version, updated_at
"""

JOB_REQUIREMENT_NORMALIZATION_VERSION = "job-requirements-v1"
JOB_PROFILE_PARSER_VERSION = "job-target-v1"


def _normalize_profile_tags(value: List[str]) -> List[str]:
    tags: List[str] = []
    seen = set()
    for item in value or []:
        text = re.sub(r"\s+", " ", str(item)).strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        tags.append(text[:80])
    return tags[:30]


def normalize_job_requirements(
    job_description: str,
    tech_stack: List[str],
    supplied_requirements: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Build queryable, deterministic JD signals without trusting client scores."""
    description = re.sub(r"\s+", " ", str(job_description or "")).strip()
    requirements = _normalize_profile_tags(supplied_requirements or [])
    for sentence in re.split(r"(?<=[.!?])\s+|[\r\n•]+", str(job_description or "")):
        cleaned = re.sub(r"\s+", " ", sentence).strip(" -•\t")
        lowered = cleaned.lower()
        if cleaned and any(token in lowered for token in ("must", "required", "experience", "proficient", "knowledge", "responsib")):
            requirements.append(cleaned[:300])
    requirements = _normalize_profile_tags(requirements)[:20]

    skill_candidates = _normalize_profile_tags(tech_stack or [])
    known_skills = (
        "python", "java", "javascript", "typescript", "react", "next.js",
        "fastapi", "django", "node.js", "postgresql", "mysql", "mongodb",
        "redis", "docker", "kubernetes", "aws", "azure", "gcp", "sql",
        "machine learning", "system design", "data structures", "algorithms",
    )
    lowered_description = description.lower()
    for skill in known_skills:
        if re.search(rf"(?<!\w){re.escape(skill)}(?!\w)", lowered_description):
            skill_candidates.append(skill)
    skills = _normalize_profile_tags(skill_candidates)[:30]

    stop_words = {
        "and", "the", "with", "for", "from", "that", "this", "will", "you",
        "your", "our", "are", "have", "has", "role", "team", "work", "years",
        "experience", "required", "preferred", "responsibilities", "skills",
    }
    counts: Counter[str] = Counter(
        token.lower()
        for token in re.findall(r"[A-Za-z][A-Za-z0-9+#.-]{2,}", description)
        if token.lower() not in stop_words
    )
    return {
        "version": JOB_REQUIREMENT_NORMALIZATION_VERSION,
        "skills": skills,
        "requirements": requirements,
        "keywords": [token for token, _ in counts.most_common(24)],
    }


def _encrypt_job_description(value: Optional[str]) -> Optional[bytes]:
    text = str(value or "").strip()
    return encrypt_data(text).encode("utf-8") if text else None


def _decrypt_job_description(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, memoryview):
        value = value.tobytes()
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    if not isinstance(value, str):
        return None
    decrypted = decrypt_data(value)
    return decrypted or None


class JobProfileCreate(BaseModel):
    role: str = Field(min_length=2, max_length=255)
    company: Optional[str] = Field(default=None, max_length=255)
    tech_stack: List[str] = Field(default_factory=list)
    job_description: Optional[str] = Field(default=None, max_length=60_000)
    experience_level: Optional[str] = Field(default=None, max_length=60)
    requirements: List[str] = Field(default_factory=list, max_length=30)

    @field_validator("role", "company", "experience_level")
    @classmethod
    def normalize_profile_text(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        text = value.strip()
        return text or None

    @field_validator("tech_stack")
    @classmethod
    def normalize_tech_stack(cls, value: List[str]) -> List[str]:
        return _normalize_profile_tags(value)[:20]

    @field_validator("requirements")
    @classmethod
    def normalize_requirements(cls, value: List[str]) -> List[str]:
        return _normalize_profile_tags(value)[:30]


class JobProfileUpdate(BaseModel):
    role: Optional[str] = Field(default=None, min_length=2, max_length=255)
    company: Optional[str] = Field(default=None, max_length=255)
    tech_stack: Optional[List[str]] = None
    job_description: Optional[str] = Field(default=None, max_length=60_000)
    experience_level: Optional[str] = Field(default=None, max_length=60)
    requirements: Optional[List[str]] = None

    @field_validator("role", "company", "experience_level")
    @classmethod
    def normalize_update_text(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        text = re.sub(r"\s+", " ", value).strip()
        return text or None

    @field_validator("tech_stack", "requirements")
    @classmethod
    def normalize_update_lists(cls, value: Optional[List[str]]) -> Optional[List[str]]:
        return _normalize_profile_tags(value or []) if value is not None else None


class JobProfileResponse(BaseModel):
    profile_id: int
    role: str
    company: Optional[str]
    tech_stack: List[str]
    job_description: Optional[str] = None
    job_description_hash: Optional[str] = None
    normalized_requirements: Dict[str, Any] = Field(default_factory=dict)
    normalization_version: Optional[str] = None
    experience_level: Optional[str] = None
    parser_version: Optional[str] = None
    is_selected: bool
    created_at: datetime
    updated_at: Optional[datetime] = None


class InterviewProfileRequest(BaseModel):
    profile_type: str

    @field_validator("profile_type")
    @classmethod
    def validate_profile_type(cls, value: str) -> str:
        normalized = normalize_profile_type(value)
        if normalized != (value or "").strip().lower():
            raise ValueError("Unsupported interview profile type")
        return normalized


class InterviewProfileResponse(BaseModel):
    profile_type: str
    label: str
    options: List[Dict[str, Any]]


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


class ExerciseAttemptCreate(BaseModel):
    mission_id: str = Field(min_length=8, max_length=64)
    roadmap_node_id: str = Field(min_length=8, max_length=64)
    submitted_answer: Optional[str] = Field(default="", max_length=8000)
    submitted_payload: Dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str = Field(min_length=8, max_length=120)
    attempt_session_id: str = Field(min_length=8, max_length=64)

    @field_validator("submitted_payload")
    @classmethod
    def validate_payload_size(cls, value: Dict[str, Any]) -> Dict[str, Any]:
        try:
            if len(json.dumps(value or {}, default=str)) > 20000:
                raise ValueError("submitted_payload is too large")
        except TypeError:
            raise ValueError("submitted_payload must be JSON serializable") from None
        return value or {}


class ExerciseAttemptSessionCreate(BaseModel):
    mission_id: str = Field(min_length=8, max_length=64)
    roadmap_node_id: str = Field(min_length=8, max_length=64)
    draft_payload: Dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str = Field(min_length=8, max_length=120)

    @field_validator("draft_payload")
    @classmethod
    def validate_draft_payload_size(cls, value: Dict[str, Any]) -> Dict[str, Any]:
        try:
            if len(json.dumps(value or {}, default=str)) > 20000:
                raise ValueError("draft_payload is too large")
        except TypeError:
            raise ValueError("draft_payload must be JSON serializable") from None
        return value or {}


class ExerciseAttemptSessionUpdate(BaseModel):
    mission_id: str = Field(min_length=8, max_length=64)
    roadmap_node_id: str = Field(min_length=8, max_length=64)
    idempotency_key: str = Field(min_length=8, max_length=120)
    status: Optional[str] = Field(default=None, pattern="^(draft|in_progress|save_failed|abandoned)$")
    draft_payload: Optional[Dict[str, Any]] = None

    @field_validator("draft_payload")
    @classmethod
    def validate_update_payload_size(cls, value: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if value is None:
            return None
        try:
            if len(json.dumps(value or {}, default=str)) > 20000:
                raise ValueError("draft_payload is too large")
        except TypeError:
            raise ValueError("draft_payload must be JSON serializable") from None
        return value or {}


class ExerciseRunRequest(BaseModel):
    language: str = Field(pattern="^(python|javascript|java)$")
    code: str = Field(min_length=1, max_length=20000)
    stdin: Optional[str] = Field(default="", max_length=4000)


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


def _json_object(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def _encrypted_json_object(value: Any) -> Dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, memoryview):
        value = value.tobytes()
    if isinstance(value, (bytes, bytearray)):
        value = bytes(value).decode("utf-8", errors="strict")
    return _json_object(decrypt_data(str(value)))


def _decrypt_text_blob(encrypted: Any, legacy: Any = None) -> str:
    if encrypted is not None:
        try:
            value = encrypted
            if isinstance(value, memoryview):
                value = value.tobytes()
            if isinstance(value, (bytes, bytearray)):
                value = bytes(value).decode("utf-8", errors="strict")
            decrypted = decrypt_data(str(value))
            if decrypted and decrypted != "[encrypted]":
                return str(decrypted)
        except Exception:
            logger.warning("Technical source payload could not be decrypted", exc_info=True)
    value = str(legacy or "")
    return "" if value == "[encrypted]" else value


def _encrypt_json_bytes(value: Any) -> bytes:
    return encrypt_data(json.dumps(value or {}, default=str)).encode("utf-8")


def _sensitive_json_marker(value: Any) -> str:
    field_count = len(value) if isinstance(value, (dict, list)) else int(value not in (None, ""))
    return json.dumps({"encrypted": True, "field_count": field_count})


def _decrypt_attempt_draft(encrypted: Any, legacy: Any) -> Dict[str, Any]:
    if encrypted is not None:
        return _encrypted_json_object(encrypted)
    parsed = _json_object(legacy)
    return {} if parsed.get("encrypted") else parsed


def _candidate_report_cta(
    interview_id: str,
    *,
    interview_status: Any,
    report_present: bool,
    has_candidate_evidence: bool,
    canonical_report_ready: bool,
) -> Dict[str, Any]:
    """Return a truthful history action without hiding real candidate evidence.

    A canonical performance row enriches Performance and Improve, but it is not
    a prerequisite for opening a stored report or the report-generation page.
    Evidence-free legacy rows remain unavailable.
    """
    normalized_status = str(interview_status or "").strip().lower()
    _ = canonical_report_ready
    if has_candidate_evidence and normalized_status in {"analysis_pending", "analysis_running", "uploading"}:
        return {
            "label": "View report progress",
            "nav": "report",
            "entity_id": interview_id,
        }
    if has_candidate_evidence and report_present:
        return {
            "label": "View Full Report",
            "nav": "report",
            "entity_id": interview_id,
        }
    if has_candidate_evidence and normalized_status in {"completed", "report_ready", "partial", "failed"}:
        return {
            "label": "Open report",
            "nav": "report",
            "entity_id": interview_id,
        }
    return {
        "label": "Report unavailable",
        "nav": "unavailable",
        "entity_id": interview_id,
    }


EXERCISE_FILE_NAMES = {
    "python": "main.py",
    "javascript": "main.js",
    "java": "Main.java",
}
PISTON_RUNTIME_CACHE: Dict[str, Dict[str, str]] = {}


async def _resolve_piston_runtime(language: str) -> Dict[str, str]:
    if language in PISTON_RUNTIME_CACHE:
        return PISTON_RUNTIME_CACHE[language]
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=6)) as session:
        headers = {"Authorization": f"Bearer {settings.PISTON_API_TOKEN}"} if settings.PISTON_API_TOKEN else {}
        async with session.get(settings.PISTON_API_URL.rstrip("/") + "/runtimes", headers=headers) as response:
            if response.status >= 400:
                raise HTTPException(status_code=502, detail="Could not load code runtimes")
            runtimes = await response.json()
    aliases = {
        "python": {"python", "py"},
        "javascript": {"javascript", "js", "node"},
        "java": {"java"},
    }[language]
    for runtime in runtimes:
        names = {runtime.get("language"), *(runtime.get("aliases") or [])}
        if aliases & {str(name).lower() for name in names if name}:
            resolved = {"language": runtime["language"], "version": runtime["version"]}
            PISTON_RUNTIME_CACHE[language] = resolved
            return resolved
    raise HTTPException(status_code=502, detail=f"No isolated sandbox runtime for {language}")


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

    from security_utils import decrypt_json
    resume_json = decrypt_json(row[3]) or {}
    profile_json = decrypt_json(row[4]) or {}
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


def _non_technical_interview_where(alias: str = "i") -> str:
    return f"""
      AND NOT (
        LOWER(COALESCE({alias}.interview_type, '')) IN ('technical', 'technical interview', 'technical mode', 'coding', 'technical_round')
        OR COALESCE(({alias}.settings->>'technical_mode')::boolean, false)
        OR EXISTS (
            SELECT 1
            FROM TechnicalInterviewRounds tir_filter
            WHERE tir_filter.interview_id = {alias}.interview_id
        )
      )
    """


def _gradable_interview_where(alias: str = "i") -> str:
    return f"""
      AND {alias}.status IN ('completed', 'report_ready', 'partial')
      AND {alias}.overall_score IS NOT NULL
      AND {alias}.report_json IS NOT NULL
      AND COALESCE({alias}.report_json->>'readiness_label', '') <> 'Not gradable'
      AND COALESCE({alias}.report_json->>'version', '') NOT ILIKE '%%no_evidence%%'
    """


def _recent_interviews(cursor, user_id: str, limit: int = 20) -> List[Dict[str, Any]]:
    cursor.execute(
        f"""
        SELECT i.interview_id, i.interview_type, i.job_title,
               i.overall_score, i.created_at, i.interview_mode,
               i.status, i.attempt_status, i.duration_seconds
        FROM Interviews i
        WHERE i.user_id = %s
          AND i.status IN ('completed', 'report_ready', 'partial', 'failed')
          AND i.attempt_status = 'completed'
          AND EXISTS (
              SELECT 1 FROM InterviewResponses response
              WHERE response.interview_id = i.interview_id
          )
        {_non_technical_interview_where("i")}
        ORDER BY i.created_at DESC
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
            "score": float(row[3]) if row[3] is not None else None,
            "date": row[4].isoformat() if row[4] else None,
            "mode": row[5],
            "status": row[6],
            "attempt_status": row[7],
            "duration_seconds": int(row[8]) if row[8] is not None else None,
        })
    items.reverse()
    return items


def _response_rows(cursor, interview_ids: List[str]) -> List[Dict[str, Any]]:
    if not interview_ids:
        return []

    placeholders = ",".join(["%s"] * len(interview_ids))
    cursor.execute(
        f"""
        SELECT ir.response_id, iq.question_text, iq.question_type, iq.is_followup,
               COALESCE(iq.topic_label, i.job_title, 'General') AS topic_label,
               ir.score, ir.response_time_seconds, ir.technical_accuracy,
               ir.communication, ir.problem_solving, ir.confidence, ir.relevance,
               ir.answer_quality_flags, ir.evidence_quotes, ir.ai_feedback,
               ir.user_response, ir.answer_text_encrypted,
               ir.interview_id, ir.created_at,
               latest_assessment.assessment_json,
               latest_assessment.overall_score
        FROM InterviewResponses ir
        JOIN InterviewQuestions iq ON ir.question_id = iq.question_id
        JOIN Interviews i ON ir.interview_id = i.interview_id
        LEFT JOIN LATERAL (
            SELECT ra.assessment_json, ra.overall_score
            FROM ResponseAssessments ra
            WHERE ra.response_id = ir.response_id
            ORDER BY ra.created_at DESC
            LIMIT 1
        ) latest_assessment ON TRUE
        WHERE ir.interview_id IN ({placeholders})
        ORDER BY ir.created_at
        """,
        tuple(interview_ids)
    )

    items = []
    for row in cursor.fetchall():
        assessment = _json_object(row[19])
        dimensions = assessment.get("dimension_scores") if isinstance(assessment.get("dimension_scores"), dict) else {}
        scores = assessment.get("scores") if isinstance(assessment.get("scores"), dict) else {}
        assessment_score = row[20]
        if assessment_score is None:
            assessment_score = assessment.get("overall_score")
        insufficient = bool(
            assessment.get("insufficient_evidence")
            or assessment.get("evidence_status") == "insufficient_evidence"
        )
        authoritative = bool(assessment_score is not None and not insufficient)

        encrypted_answer = row[16]
        if isinstance(encrypted_answer, memoryview):
            encrypted_answer = encrypted_answer.tobytes()
        if isinstance(encrypted_answer, (bytes, bytearray)):
            encrypted_answer = bytes(encrypted_answer).decode("utf-8", errors="strict")
        answer_text = decrypt_data(encrypted_answer) if isinstance(encrypted_answer, str) else ""
        if not answer_text or answer_text.startswith("enc:"):
            answer_text = "" if row[15] == "[encrypted]" else str(row[15] or "")

        assessment_flags = assessment.get("flags") if isinstance(assessment.get("flags"), list) else []
        legacy_flags = row[12] if isinstance(row[12], list) else []
        evidence = assessment.get("evidence") if isinstance(assessment.get("evidence"), dict) else {}
        assessment_quotes = evidence.get("evidence_quotes") if isinstance(evidence.get("evidence_quotes"), list) else []
        missed_points = evidence.get("missed_points") if isinstance(evidence.get("missed_points"), list) else []
        missed_labels = [
            str(item.get("label") or item.get("point") or "").strip()
            if isinstance(item, dict) else str(item).strip()
            for item in missed_points
        ]
        follow_up = assessment.get("follow_up") if isinstance(assessment.get("follow_up"), dict) else {}
        feedback = ", ".join(item for item in missed_labels if item)
        if not feedback:
            feedback = str(follow_up.get("prompt") or row[14] or "")

        def numeric(*values: Any) -> Optional[float]:
            for value in values:
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    return float(value)
            return None

        items.append({
            "response_id": row[0],
            "question": row[1],
            "question_type": row[2] or "main",
            "is_followup": bool(row[3]),
            "topic": row[4] or "General",
            "score": numeric(assessment_score) if authoritative else None,
            "response_time": float(row[6]) if row[6] is not None else None,
            "technical_accuracy": numeric(dimensions.get("correctness"), scores.get("technical_accuracy")) if authoritative else None,
            "communication": numeric(dimensions.get("communication"), scores.get("directness")) if authoritative else None,
            "problem_solving": numeric(dimensions.get("star_structure"), dimensions.get("depth"), scores.get("structure")) if authoritative else None,
            "confidence": numeric(assessment.get("confidence")) if authoritative else None,
            "relevance": numeric(dimensions.get("relevance"), scores.get("relevance")) if authoritative else None,
            "answer_quality_flags": list(dict.fromkeys([*legacy_flags, *assessment_flags])),
            "evidence_quotes": row[13] or assessment_quotes,
            "feedback": feedback,
            "response": answer_text,
            "interview_id": row[17],
            "created_at": row[18],
            "evidence_status": assessment.get("evidence_status"),
            "authoritative": authoritative,
        })
    return items


def _technical_problem_analytics(cursor, user_id: str) -> Dict[str, Any]:
    cursor.execute(
        """
        SELECT tir.round_id, tir.interview_id, tir.round_type, tir.language,
               tir.prompt, tir.status, tir.created_at, tir.metadata,
               COUNT(tre.run_id) AS run_count,
               SUM(CASE WHEN tre.exit_code = 0 THEN 1 ELSE 0 END) AS successful_runs,
               AVG(tre.runtime_ms) AS avg_runtime_ms,
               MAX(tre.created_at) AS last_run_at
        FROM TechnicalInterviewRounds tir
        LEFT JOIN TechnicalRunEvents tre ON tre.round_id = tir.round_id
        WHERE tir.user_id = %s
        GROUP BY tir.round_id, tir.interview_id, tir.round_type, tir.language,
                 tir.prompt, tir.status, tir.created_at, tir.metadata
        ORDER BY tir.created_at DESC
        LIMIT 20
        """,
        (user_id,),
    )
    rows = cursor.fetchall()
    problems: List[Dict[str, Any]] = []
    type_totals: Dict[str, Dict[str, Any]] = defaultdict(lambda: {
        "attempts": 0,
        "runs": 0,
        "successful_runs": 0,
    })

    for row in rows:
        round_type = row[2] or "technical"
        metadata = row[7] or {}
        run_count = int(row[8] or 0)
        successful_runs = int(row[9] or 0)
        type_totals[round_type]["attempts"] += 1
        type_totals[round_type]["runs"] += run_count
        type_totals[round_type]["successful_runs"] += successful_runs
        problems.append({
            "round_id": row[0],
            "interview_id": row[1],
            "round_type": round_type,
            "language": row[3],
            "prompt": row[4],
            "status": row[5],
            "created_at": row[6].isoformat() if row[6] else None,
            "metadata": _json_object(metadata),
            "run_count": run_count,
            "successful_runs": successful_runs,
            "avg_runtime_ms": round(float(row[10]), 1) if row[10] is not None else 0,
            "last_run_at": row[11].isoformat() if row[11] else None,
        })

    cursor.execute(
        """
        SELECT COUNT(*)
        FROM AntiCheatEvents
        WHERE user_id = %s
        """,
        (user_id,),
    )
    anti_cheat_count = int((cursor.fetchone() or [0])[0] or 0)
    total_runs = sum(item["run_count"] for item in problems)
    successful_runs = sum(item["successful_runs"] for item in problems)

    return {
        "summary": {
            "total_problems": len(problems),
            "total_runs": total_runs,
            "successful_runs": successful_runs,
            "success_rate": round((successful_runs / total_runs) * 100, 1) if total_runs else 0,
            "anti_cheat_events": anti_cheat_count,
        },
        "by_round_type": [
            {
                "round_type": round_type,
                "attempts": values["attempts"],
                "runs": values["runs"],
                "successful_runs": values["successful_runs"],
                "success_rate": round((values["successful_runs"] / values["runs"]) * 100, 1) if values["runs"] else 0,
            }
            for round_type, values in type_totals.items()
        ],
        "recent_problems": problems[:8],
    }


def _nullable_avg(values: List[float]) -> Optional[float]:
    return round(sum(values) / len(values), 1) if values else None


def _score_summary(trend: List[Dict[str, Any]]) -> Dict[str, Any]:
    scores = [float(item["score"]) for item in trend if item.get("score") is not None]
    return {
        "latest_score": round(scores[-1], 1) if scores else None,
        "average_score": _nullable_avg(scores),
        "best_score": round(max(scores), 1) if scores else None,
        "improvement_percentage": round(scores[-1] - scores[0], 1) if len(scores) > 1 else None,
        "trend": trend,
    }


def _json_list(value: Any) -> List[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except Exception:
            return []
    return []


def _human_label(value: Any) -> str:
    text = re.sub(r"[_\-]+", " ", str(value or "")).strip()
    return re.sub(r"\s+", " ", text).title()


def _short_text(value: Any, limit: int = 120) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0] + "…"


def _format_percent_value(value: Optional[float]) -> Optional[str]:
    if value is None:
        return None
    return f"{round(float(value), 1):g}%"


def _format_number_value(value: Optional[float], suffix: str = "") -> Optional[str]:
    if value is None:
        return None
    numeric = float(value)
    text = f"{round(numeric, 1):g}"
    return f"{text}{suffix}"


def _add_section(sections: List[Dict[str, Any]], section: Dict[str, Any]) -> None:
    if section.get("rows") or section.get("metrics") or section.get("items") or section.get("trend"):
        sections.append(section)


def _dynamic_payload(mode: str, has_data: bool, overview: List[Dict[str, Any]], sections: List[Dict[str, Any]], next_focus: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    payload = {
        "mode": mode,
        "has_data": has_data,
        "overview": [item for item in overview if item.get("value") not in (None, "")],
        "sections": sections,
    }
    if next_focus:
        payload["next_focus"] = next_focus
    return payload


PERFORMANCE_DIMENSION_LABELS = {
    "communication_clarity": "Communication clarity",
    "communication": "Communication clarity",
    "answer_structure_star": "Answer structure",
    "star_structure": "Answer structure",
    "relevance": "Answer relevance",
    "evidence_confidence": "Evidence confidence",
    "technical_competency": "Technical competency",
    "technical_accuracy": "Technical accuracy",
    "correctness": "Technical correctness",
    "problem_solving": "Problem solving",
    "depth": "Technical depth",
    "ownership": "Ownership",
    "specificity_evidence": "Specificity and evidence",
    "tradeoffs": "Trade-off reasoning",
    "overall_interview_performance": "Overall interview performance",
    "code_quality": "Code quality",
}


def _performance_raw_number(*values: Any) -> Optional[float]:
    for value in values:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value.strip().rstrip("%"))
            except (TypeError, ValueError):
                continue
    return None


def _performance_number(*values: Any) -> Optional[float]:
    value = _performance_raw_number(*values)
    return _clip(value) if value is not None else None


def _analysis_dimensions(analysis: Dict[str, Any]) -> Dict[str, float]:
    raw = analysis.get("dimension_scores") or analysis.get("dimensions") or {}
    if not isinstance(raw, dict):
        return {}
    dimensions: Dict[str, float] = {}
    for key, value in raw.items():
        score = _performance_number(value)
        if score is not None:
            dimensions[str(key)] = score
    return dimensions


def _analysis_report(analysis: Dict[str, Any]) -> Dict[str, Any]:
    report = analysis.get("report")
    return report if isinstance(report, dict) else {}


def _question_score(item: Dict[str, Any]) -> Optional[float]:
    return _performance_number(item.get("overall_score"), item.get("provisional_score"))


def _is_project_question(item: Dict[str, Any]) -> bool:
    text = " ".join(str(item.get(key) or "") for key in ("question", "skill", "project_facet")).lower()
    taxonomy = item.get("taxonomy_keys") or []
    if isinstance(taxonomy, list):
        text += " " + " ".join(str(value).lower() for value in taxonomy)
    return any(token in text for token in ("project", "portfolio"))


def _canonical_project_explanation(comparable: List[Dict[str, Any]]) -> Dict[str, Any]:
    project_scores: List[float] = []
    sessions: set[str] = set()
    breakdown_values: Dict[str, List[float]] = defaultdict(list)
    breakdown_keys = {
        "clarity": ("communication", "directness", "relevance"),
        "technical_depth": ("correctness", "depth", "technical_accuracy"),
        "architecture": ("tradeoffs", "structure"),
        "impact": ("specificity_evidence", "ownership"),
    }
    for session in comparable:
        analysis = session.get("analysis") or {}
        for question in analysis.get("question_analyses") or analysis.get("questions") or []:
            if not isinstance(question, dict) or not _is_project_question(question):
                continue
            score = _question_score(question)
            if score is not None:
                project_scores.append(score)
                sessions.add(str(session.get("interview_id") or ""))
            dimensions = question.get("dimension_scores") or {}
            if not isinstance(dimensions, dict):
                continue
            for label, keys in breakdown_keys.items():
                values = [
                    _performance_number(dimensions.get(key))
                    for key in keys
                ]
                available = [value for value in values if value is not None]
                if available:
                    breakdown_values[label].append(sum(available) / len(available))

    breakdown = [
        {
            "label": _human_label(label),
            "score": round(sum(values) / len(values), 1),
        }
        for label, values in breakdown_values.items()
        if values
    ]
    return {
        "score": round(sum(project_scores) / len(project_scores), 1) if project_scores else None,
        "answer_count": len(project_scores),
        "session_count": len({value for value in sessions if value}),
        "breakdown": breakdown,
        "detail": (
            f"Based on {len(project_scores)} project answer{'s' if len(project_scores) != 1 else ''} "
            f"across {len(sessions)} comparable interview{'s' if len(sessions) != 1 else ''}."
            if project_scores else "No project explanation has enough scored evidence yet."
        ),
    }


def _canonical_communication_summary(comparable: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not comparable:
        return {"fluency_clarity": None, "confidence": None, "patterns": []}
    latest_analysis = comparable[-1].get("analysis") or {}
    dimensions = _analysis_dimensions(latest_analysis)
    report = _analysis_report(latest_analysis)
    behavioral = report.get("behavioral_metrics") if isinstance(report.get("behavioral_metrics"), dict) else {}
    measured = latest_analysis.get("measured_communication") or {}
    audio = measured.get("audio") if isinstance(measured, dict) else {}
    audio = audio if isinstance(audio, dict) else {}

    fluency = _performance_number(
        dimensions.get("communication_clarity"),
        dimensions.get("communication"),
    )
    words_per_minute = _performance_raw_number(
        behavioral.get("words_per_minute"),
        audio.get("words_per_minute"),
    )
    filler_count = _performance_raw_number(
        behavioral.get("filler_count"),
        audio.get("filler_count"),
    )
    voiced_seconds = _performance_raw_number(
        behavioral.get("voiced_duration_seconds"),
        audio.get("voiced_duration_seconds"),
    )
    response_latency = _performance_raw_number(
        behavioral.get("response_latency_seconds_avg"),
        audio.get("response_latency_seconds_avg"),
    )
    filler_rate = (
        round(float(filler_count) / (float(voiced_seconds) / 60.0), 1)
        if filler_count is not None and voiced_seconds and voiced_seconds > 0 else None
    )

    delivery_confidence: Optional[float] = None
    if filler_rate is not None or words_per_minute is not None or response_latency is not None:
        delivery_confidence = 88.0
        if filler_rate is not None:
            delivery_confidence -= max(0.0, filler_rate - 1.0) * 8.0
        if words_per_minute is not None:
            if words_per_minute < 105:
                delivery_confidence -= min(18.0, (105 - words_per_minute) * 0.35)
            elif words_per_minute > 185:
                delivery_confidence -= min(18.0, (words_per_minute - 185) * 0.3)
        if response_latency is not None and response_latency > 4:
            delivery_confidence -= min(12.0, (response_latency - 4) * 2.0)
        delivery_confidence = _clip(delivery_confidence)

    pattern_sessions: Dict[str, set[str]] = defaultdict(set)
    pattern_counts: Counter[str] = Counter()
    pattern_details = {
        "Weak self-introduction": "The opening answer needs a clearer role, proof point, and target-role bridge.",
        "Unclear project explanations": "Project answers need clearer ownership, architecture, trade-offs, and impact.",
        "Excessive filler words": "Measured filler density is interrupting otherwise useful answers.",
        "Rambling or indirect answers": "The direct answer is arriving too late or drifting away from the question.",
        "Incomplete answers": "Answers stop before showing reasoning, evidence, or a result.",
        "Vague explanations": "Claims need exact decisions, constraints, and measurable outcomes.",
        "Missing evidence": "Claims are not consistently backed by a project, example, or metric.",
    }
    flag_labels = {
        "too_short": "Incomplete answers",
        "no_response": "Incomplete answers",
        "vague": "Vague explanations",
        "off_topic": "Rambling or indirect answers",
        "low_lexical_relevance": "Rambling or indirect answers",
        "no_evidence": "Missing evidence",
        "insufficient_evidence": "Missing evidence",
    }
    for session in comparable[-5:]:
        session_id = str(session.get("interview_id") or "unknown")
        analysis = session.get("analysis") or {}
        for question in analysis.get("question_analyses") or analysis.get("questions") or []:
            if not isinstance(question, dict):
                continue
            score = _question_score(question)
            question_text = str(question.get("question") or "").lower()
            if score is not None and score < 70:
                if "tell me about yourself" in question_text or "introduce" in question_text:
                    pattern_sessions["Weak self-introduction"].add(session_id)
                    pattern_counts.update(["Weak self-introduction"])
                if _is_project_question(question):
                    pattern_sessions["Unclear project explanations"].add(session_id)
                    pattern_counts.update(["Unclear project explanations"])
            for flag in question.get("answer_quality_flags") or []:
                label = flag_labels.get(str(flag).strip().lower())
                if label:
                    pattern_sessions[label].add(session_id)
                    pattern_counts.update([label])
        session_measured = analysis.get("measured_communication") or {}
        session_audio = session_measured.get("audio") if isinstance(session_measured, dict) else {}
        session_audio = session_audio if isinstance(session_audio, dict) else {}
        session_fillers = _performance_raw_number(session_audio.get("filler_count"))
        session_voiced = _performance_raw_number(session_audio.get("voiced_duration_seconds"))
        if session_fillers is not None and session_voiced and session_voiced > 0:
            session_rate = session_fillers / (session_voiced / 60.0)
            if session_rate > 2:
                pattern_sessions["Excessive filler words"].add(session_id)
                pattern_counts.update(["Excessive filler words"])

    patterns = [
        {
            "label": label,
            "detail": pattern_details[label],
            "count": int(pattern_counts[label]),
            "session_count": len(sessions),
            "recurring": len(sessions) >= 2,
        }
        for label, sessions in sorted(
            pattern_sessions.items(),
            key=lambda item: (-len(item[1]), -pattern_counts[item[0]], item[0]),
        )
    ][:5]
    fluency_detail_parts = []
    if words_per_minute is not None:
        fluency_detail_parts.append(f"{round(words_per_minute):g} words/min")
    if filler_rate is not None:
        fluency_detail_parts.append(f"{filler_rate:g} fillers/min")
    return {
        "fluency_clarity": {
            "score": fluency,
            "detail": ", ".join(fluency_detail_parts) or "Based on transcript clarity and answer structure.",
        },
        "confidence": {
            "score": delivery_confidence,
            "detail": (
                "Estimated from measured pacing, hesitation, and filler use."
                if delivery_confidence is not None
                else "Voice delivery evidence was not measurable in the latest interview."
            ),
        },
        "patterns": patterns,
    }


def _canonical_dimension_directions(comparable: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    series: Dict[str, List[float]] = defaultdict(list)
    for session in comparable[-5:]:
        for key, score in _analysis_dimensions(session.get("analysis") or {}).items():
            series[key].append(score)
    changes = []
    for key, values in series.items():
        if len(values) < 2:
            continue
        delta = round(values[-1] - values[0], 1)
        if abs(delta) < 4:
            continue
        changes.append({
            "label": PERFORMANCE_DIMENSION_LABELS.get(key, _human_label(key)),
            "delta": delta,
            "latest_score": round(values[-1], 1),
            "session_count": len(values),
        })
    return {
        "improving": sorted((item for item in changes if item["delta"] > 0), key=lambda item: -item["delta"])[:4],
        "declining": sorted((item for item in changes if item["delta"] < 0), key=lambda item: item["delta"])[:4],
    }


def _canonical_technical_summary(comparable: List[Dict[str, Any]], trend: List[Dict[str, Any]]) -> Dict[str, Any]:
    gap_sessions: Dict[str, set[str]] = defaultdict(set)
    gap_scores: Dict[str, List[float]] = defaultdict(list)
    for session in comparable[-5:]:
        session_id = str(session.get("interview_id") or "unknown")
        analysis = session.get("analysis") or {}
        technical = analysis.get("technical") if isinstance(analysis.get("technical"), dict) else {}
        for gap in technical.get("weak_topics") or []:
            if not isinstance(gap, dict):
                continue
            label = _human_label(gap.get("topic") or gap.get("skill") or gap.get("label"))
            if not label:
                continue
            gap_sessions[label].add(session_id)
            score = _performance_number(gap.get("score"), gap.get("average_score"))
            if score is not None:
                gap_scores[label].append(score)
        for question in analysis.get("question_analyses") or []:
            if not isinstance(question, dict):
                continue
            score = _question_score(question)
            if score is None or score >= 65:
                continue
            taxonomy = question.get("taxonomy_keys") or []
            labels = taxonomy if isinstance(taxonomy, list) and taxonomy else [question.get("skill")]
            for raw_label in labels[:2]:
                label = _human_label(raw_label)
                if label and label not in {"General", "Technical"}:
                    gap_sessions[label].add(session_id)
                    gap_scores[label].append(score)
    knowledge_gaps = [
        {
            "label": label,
            "session_count": len(sessions),
            "score": round(sum(gap_scores[label]) / len(gap_scores[label]), 1) if gap_scores[label] else None,
        }
        for label, sessions in sorted(
            gap_sessions.items(),
            key=lambda item: (-len(item[1]), item[0]),
        )
        if len(sessions) >= 2
    ][:6]
    return {
        "trend": trend[-5:],
        "knowledge_gaps": knowledge_gaps,
        "latest_score": next((item.get("score") for item in reversed(trend) if item.get("score") is not None), None),
    }


def _canonical_ai_insights(
    comparable: List[Dict[str, Any]],
    trend: List[Dict[str, Any]],
    communication: Dict[str, Any],
    directions: Dict[str, List[Dict[str, Any]]],
) -> List[str]:
    if not comparable:
        return []
    report = _analysis_report(comparable[-1].get("analysis") or {})
    student_summary = report.get("student_summary") if isinstance(report.get("student_summary"), dict) else {}
    candidates = [
        report.get("summary"),
        student_summary.get("blocker"),
        student_summary.get("next_step"),
        student_summary.get("interviewer_signal"),
    ]
    scored_trend = [item for item in trend[-5:] if item.get("score") is not None]
    if len(scored_trend) >= 2:
        delta = round(float(scored_trend[-1]["score"]) - float(scored_trend[0]["score"]), 1)
        direction = "improved" if delta > 0 else "declined" if delta < 0 else "held steady"
        candidates.append(f"Comparable interview performance has {direction} by {abs(delta):g} points across the visible history.")
    recurring = [item for item in communication.get("patterns") or [] if item.get("recurring")]
    if recurring:
        candidates.append(f"{recurring[0]['label']} is the most persistent communication pattern across recent interviews.")
    if directions.get("improving"):
        candidates.append(f"{directions['improving'][0]['label']} is the clearest improving area.")
    if directions.get("declining"):
        candidates.append(f"{directions['declining'][0]['label']} needs attention after declining across comparable interviews.")

    insights: List[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        text = _short_text(candidate, 180)
        key = text.lower()
        if not text or key in seen:
            continue
        seen.add(key)
        insights.append(text)
        if len(insights) == 5:
            break
    return insights


def _canonical_strengths(comparable: List[Dict[str, Any]]) -> List[str]:
    if not comparable:
        return []
    latest_report = _analysis_report(comparable[-1].get("analysis") or {})
    strengths = [
        _short_text(item, 150)
        for item in latest_report.get("strengths") or []
        if str(item or "").strip()
    ]
    series: Dict[str, List[float]] = defaultdict(list)
    for session in comparable[-5:]:
        for key, score in _analysis_dimensions(session.get("analysis") or {}).items():
            series[key].append(score)
    stable = sorted(
        (
            (key, values)
            for key, values in series.items()
            if len(values) >= 2 and sum(values) / len(values) >= 75
        ),
        key=lambda item: -(sum(item[1]) / len(item[1])),
    )
    for key, values in stable:
        strengths.append(
            f"{PERFORMANCE_DIMENSION_LABELS.get(key, _human_label(key))} has remained strong across {len(values)} comparable interviews."
        )
    unique: List[str] = []
    seen: set[str] = set()
    for strength in strengths:
        key = strength.lower()
        if not strength or key in seen:
            continue
        seen.add(key)
        unique.append(strength)
        if len(unique) == 5:
            break
    return unique


PERFORMANCE_ANALYTICS_DIMENSION_LABELS = {
    "communication_clarity": "Communication",
    "communication": "Communication",
    "technical_competency": "Technical Knowledge",
    "technical_accuracy": "Technical Knowledge",
    "correctness": "Technical Knowledge",
    "problem_solving": "Problem Solving",
    "depth": "Depth",
    "relevance": "Answer Relevance",
    "star_structure": "Behavioral / STAR",
    "behavioral": "Behavioral / STAR",
    "tradeoffs": "System Design",
    "architecture": "System Design",
    "ownership": "Project / Resume Knowledge",
    "specificity_evidence": "Project / Resume Knowledge",
    "code_quality": "Code Quality",
}


def _performance_iso(value: Any) -> Optional[str]:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    text = str(value).strip()
    return text or None


def _analytics_question_type(item: Dict[str, Any]) -> str:
    question = str(item.get("question") or "").lower()
    raw_type = str(item.get("question_type") or "").lower()
    if item.get("is_followup"):
        return "Follow-up Questions"
    if any(token in f"{raw_type} {question}" for token in ("system design", "architecture", "trade-off", "tradeoff")):
        return "System Design"
    if any(token in f"{raw_type} {question}" for token in ("project", "resume", "portfolio")):
        return "Project / Resume Questions"
    if any(token in f"{raw_type} {question}" for token in ("behavior", "star", "leadership", "conflict", "failure")):
        return "Behavioral"
    if any(token in f"{raw_type} {question}" for token in ("situational", "what would you", "how would you")):
        return "Situational"
    if any(token in f"{raw_type} {question}" for token in ("coding", "algorithm", "implement", "code")):
        return "Coding Discussion"
    return "Technical Concept Questions"


def _analytics_topic_labels(item: Dict[str, Any], mode: str) -> List[str]:
    raw_values: List[Any] = []
    if mode == "technical":
        for key in ("taxonomy_keys", "topics"):
            raw = item.get(key)
            raw_values.extend(raw if isinstance(raw, list) else [raw] if raw else [])
        raw_values.extend([item.get("algorithm_pattern"), item.get("topic"), item.get("round_type")])
    else:
        raw = item.get("taxonomy_keys")
        raw_values.extend(raw if isinstance(raw, list) else [raw] if raw else [])
        raw_values.extend([item.get("skill"), item.get("topic"), item.get("topic_label")])
    labels: List[str] = []
    for value in raw_values:
        label = _human_label(value)
        if not label or label.lower() in {"general", "main", "question", "technical"}:
            continue
        if label not in labels:
            labels.append(label)
    return labels[:4]


def _analytics_bucket() -> Dict[str, Any]:
    return {
        "scores": [],
        "session_scores": defaultdict(list),
        "session_ids": [],
        "evidence": [],
        "issues": Counter(),
        "successes": 0,
    }


def _analytics_add(
    bucket: Dict[str, Any],
    score: Any,
    session: Dict[str, Any],
    evidence: Optional[Dict[str, Any]] = None,
    *,
    issue: Optional[str] = None,
    success: bool = False,
) -> None:
    numeric = _performance_number(score)
    if numeric is None:
        return
    session_id = str(session.get("interview_id") or "")
    bucket["scores"].append(numeric)
    bucket["session_scores"][session_id].append(numeric)
    if session_id and session_id not in bucket["session_ids"]:
        bucket["session_ids"].append(session_id)
    if evidence:
        key = json.dumps(evidence, sort_keys=True, default=str)
        if not any(json.dumps(item, sort_keys=True, default=str) == key for item in bucket["evidence"]):
            bucket["evidence"].append(evidence)
    if issue:
        bucket["issues"].update([_short_text(issue, 120)])
    if success:
        bucket["successes"] += 1


def _analytics_bucket_row(
    label: str,
    bucket: Dict[str, Any],
    *,
    count_key: str,
    count: int,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    scores = [float(value) for value in bucket.get("scores") or []]
    session_scores = bucket.get("session_scores") or {}
    ordered_session_ids = [item for item in bucket.get("session_ids") or [] if item in session_scores]
    session_averages = [
        _nullable_avg([float(value) for value in session_scores[session_id]])
        for session_id in ordered_session_ids
    ]
    session_averages = [value for value in session_averages if value is not None]
    recent_count = min(3, len(session_averages))
    recent_average = _nullable_avg(session_averages[-recent_count:]) if recent_count else None
    baseline_average = None
    delta = None
    direction = None
    if len(session_averages) >= 2:
        split = max(1, len(session_averages) // 2)
        baseline_average = _nullable_avg(session_averages[:split])
        delta = round(float(recent_average or 0) - float(baseline_average or 0), 1)
        direction = "up" if delta >= 4 else "down" if delta <= -4 else "stable"
    issues = bucket.get("issues") or Counter()
    issue_counts = [
        {"label": label, "count": count}
        for label, count in issues.most_common(3)
    ] if hasattr(issues, "most_common") else []
    row: Dict[str, Any] = {
        "label": label,
        "average_score": _nullable_avg(scores),
        "recent_average": recent_average,
        "delta": delta,
        "trend": direction,
        count_key: count,
        "evidence_count": count,
        "round_count": len(session_scores),
        "success_count": int(bucket.get("successes") or 0),
        "common_issue": issue_counts[0]["label"] if issue_counts else None,
        "issue_counts": issue_counts,
        "evidence": (bucket.get("evidence") or [])[:24],
    }
    if extra:
        row.update(extra)
    return row


def _analytics_summary(comparable: List[Dict[str, Any]]) -> Dict[str, Any]:
    scores = [
        float(item["overall_score"])
        for item in comparable
        if item.get("evidence_status") == "sufficient" and item.get("overall_score") is not None
    ]
    durations = [
        float(item["duration_seconds"])
        for item in comparable
        if item.get("duration_seconds") is not None
    ]
    recent_change = None
    trend = None
    if len(scores) >= 2:
        recent_change = round(scores[-1] - scores[max(0, len(scores) - 5)], 1)
        trend = "Improving" if recent_change >= 4 else "Declining" if recent_change <= -4 else "Stable"
    return {
        "total_rounds": len(comparable),
        "average_score": _nullable_avg(scores),
        "latest_score": scores[-1] if scores else None,
        "best_score": round(max(scores), 1) if scores else None,
        "recent_change": recent_change,
        "average_duration_seconds": _nullable_avg(durations),
        "trend": trend,
    }


def _canonical_round_history_item(session: Dict[str, Any], mode: str) -> Dict[str, Any]:
    analysis = session.get("analysis") or {}
    report = _analysis_report(analysis)
    score = (
        _performance_number(session.get("overall_score"))
        if session.get("evidence_status") == "sufficient"
        else None
    )
    result: Dict[str, Any] = {
        "interview_id": session.get("interview_id"),
        "analysis_id": session.get("analysis_id"),
        "mode": "technical" if mode == "technical" else "interview",
        "role": session.get("role") or report.get("job_title") or None,
        "company": (session.get("settings") or {}).get("company"),
        "completed_at": _performance_iso(session.get("created_at")),
        "score": score,
        "duration_seconds": session.get("duration_seconds"),
        "score_state": (
            "ready"
            if score is not None
            else "run_only"
            if session.get("evidence_status") == "draft_or_run_only"
            else "insufficient"
        ),
        "source_kind": "canonical_v4",
        "round_id": None,
        "change": None,
    }
    if mode == "technical":
        technical = analysis.get("technical") if isinstance(analysis.get("technical"), dict) else {}
        matrix = [item for item in technical.get("test_matrix") or [] if isinstance(item, dict)]
        attempted = [item for item in matrix if item.get("evidence_state") not in {None, "no_evidence", "no_candidate_evidence"}]
        submitted = [item for item in attempted if item.get("evidence_state") == "final_submission" or item.get("submission_id")]
        solved = [
            item for item in submitted
            if str(item.get("final_verdict") or "").lower() in {"accepted", "correct", "solved", "meets_bar"}
            or (_performance_number(item.get("final_pass_rate")) or 0) >= 100
        ]
        result.update({
            "problems_attempted": len(attempted),
            "problems_total": len(matrix) or int(technical.get("round_count") or 0),
            "problems_solved": len(solved),
            "questions_completed": None,
            "questions_total": None,
            "key_result": (
                f"{len(solved)}/{len(matrix)} solved" if matrix else None
            ),
            "round_id": next((item.get("round_id") for item in matrix if item.get("round_id")), None),
        })
    else:
        questions = [item for item in analysis.get("question_analyses") or analysis.get("questions") or [] if isinstance(item, dict)]
        counts = report.get("counts") if isinstance(report.get("counts"), dict) else {}
        total = int(counts.get("questions_asked") or len(questions))
        answered = int(counts.get("questions_answered") or sum(
            1 for item in questions
            if _question_score(item) is not None and "no_response" not in {str(flag).lower() for flag in item.get("answer_quality_flags") or []}
        ))
        fully = int(counts.get("questions_fully_answered") or 0)
        result.update({
            "questions_completed": answered,
            "questions_total": total,
            "problems_attempted": None,
            "problems_total": None,
            "problems_solved": None,
            "key_result": f"{fully}/{total} fully answered" if total else None,
        })
    return result


def _cumulative_performance_analytics(
    comparable: List[Dict[str, Any]],
    mode: str,
) -> Dict[str, Any]:
    analytics: Dict[str, Any] = {
        "summary": _analytics_summary(comparable),
        "skills": [],
        "topics": [],
        "question_types": [],
        "patterns": [],
        "behavior": [],
        "improvement": {"improving": [], "declining": [], "stable": []},
    }
    if not comparable:
        return analytics

    if mode != "technical":
        skill_buckets: Dict[str, Dict[str, Any]] = defaultdict(_analytics_bucket)
        topic_buckets: Dict[str, Dict[str, Any]] = defaultdict(_analytics_bucket)
        type_buckets: Dict[str, Dict[str, Any]] = defaultdict(_analytics_bucket)
        pattern_buckets: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"count": 0, "sessions": set(), "evidence": []})
        followup_scores: List[float] = []
        initial_scores: List[float] = []
        successful_followups = 0
        shallow_followups: List[Dict[str, Any]] = []
        behavior_values: Dict[str, List[float]] = defaultdict(list)
        answer_counts = Counter()

        for session in comparable:
            analysis = session.get("analysis") or {}
            report = _analysis_report(analysis)
            questions = [item for item in analysis.get("question_analyses") or analysis.get("questions") or [] if isinstance(item, dict)]
            if not questions:
                continue
            main_by_id = {
                str(item.get("question_id") or item.get("response_id")): _question_score(item)
                for item in questions
                if not item.get("is_followup") and _question_score(item) is not None
            }
            for question in questions:
                score = _question_score(question)
                if score is None:
                    continue
                flags = [
                    _flag_label(raw_flag)
                    for raw_flag in question.get("answer_quality_flags") or []
                    if str(raw_flag).strip()
                ]
                primary_issue = flags[0] if flags else ("Low-scoring answer" if score < 70 else None)
                evidence = {
                    "interview_id": session.get("interview_id"),
                    "date": _performance_iso(session.get("created_at")),
                    "question": _short_text(question.get("question"), 120),
                    "question_type": _analytics_question_type(question),
                    "score": score,
                    "response_id": question.get("response_id"),
                }
                if primary_issue:
                    evidence["issue"] = primary_issue
                dimensions = question.get("dimension_scores") if isinstance(question.get("dimension_scores"), dict) else {}
                for raw_key, value in dimensions.items():
                    label = PERFORMANCE_ANALYTICS_DIMENSION_LABELS.get(str(raw_key).lower())
                    if label:
                        dimension_score = _performance_number(value)
                        _analytics_add(
                            skill_buckets[label],
                            dimension_score,
                            session,
                            evidence,
                            issue=primary_issue,
                            success=dimension_score is not None and dimension_score >= 80,
                        )
                for topic in _analytics_topic_labels(question, "interview"):
                    _analytics_add(
                        topic_buckets[topic],
                        score,
                        session,
                        evidence,
                        issue=primary_issue,
                        success=score >= 80,
                    )
                _analytics_add(
                    type_buckets[_analytics_question_type(question)],
                    score,
                    session,
                    evidence,
                    issue=primary_issue,
                    success=score >= 80,
                )
                if question.get("is_followup"):
                    followup_scores.append(score)
                    if score >= 70:
                        successful_followups += 1
                    parent_score = main_by_id.get(str((question.get("follow_up_chain") or {}).get("parent_question_id") or ""))
                    if parent_score is None and main_by_id:
                        parent_score = max(main_by_id.values())
                    if parent_score is not None and parent_score >= 70 and score < 70:
                        shallow_followups.append(evidence)
                else:
                    initial_scores.append(score)
                for raw_flag in question.get("answer_quality_flags") or []:
                    flag = str(raw_flag).strip().lower()
                    label = {
                        "too_short": "Answers stop before the reasoning or result is complete",
                        "no_response": "Questions are left unanswered",
                        "vague": "Explanations lack specific evidence",
                        "off_topic": "Answers drift away from the question",
                        "low_lexical_relevance": "Answers do not directly address the question",
                        "no_evidence": "Claims are not backed by an example or result",
                        "missing_tradeoffs": "System-design answers omit trade-offs",
                        "unsupported_or_unspecific": "Claims are not supported with concrete detail",
                        "ownership_unclear": "Project answers do not make ownership clear",
                    }.get(flag)
                    if label:
                        bucket = pattern_buckets[label]
                        bucket["count"] += 1
                        bucket["sessions"].add(str(session.get("interview_id") or ""))
                        bucket["evidence"].append(evidence)
            behavioral = report.get("behavioral_metrics") if isinstance(report.get("behavioral_metrics"), dict) else {}
            measured = analysis.get("measured_communication") if isinstance(analysis.get("measured_communication"), dict) else {}
            audio = measured.get("audio") if isinstance(measured.get("audio"), dict) else {}
            for key, values in {
                "average_answer_seconds": [behavioral.get("average_response_time_seconds")],
                "response_latency_seconds": [behavioral.get("response_latency_seconds_avg"), audio.get("response_latency_seconds_avg")],
                "words_per_minute": [behavioral.get("words_per_minute"), audio.get("words_per_minute")],
            }.items():
                numeric_values = [_performance_raw_number(value) for value in values]
                numeric_values = [value for value in numeric_values if value is not None]
                if numeric_values:
                    behavior_values[key].append(numeric_values[0])
            counts = report.get("counts") if isinstance(report.get("counts"), dict) else {}
            answer_counts.update({
                "asked": int(counts.get("questions_asked") or len(questions)),
                "answered": int(counts.get("questions_answered") or 0),
                "fully": int(counts.get("questions_fully_answered") or 0),
                "partial": int(counts.get("questions_partially_answered") or 0),
                "not_answered": int(counts.get("questions_not_answered") or 0),
            })

        def build_rows(buckets: Dict[str, Dict[str, Any]], count_key: str) -> List[Dict[str, Any]]:
            return [
                _analytics_bucket_row(label, bucket, count_key=count_key, count=len(bucket.get("scores") or []))
                for label, bucket in sorted(
                    buckets.items(),
                    key=lambda item: (-len(item[1].get("scores") or []), item[0]),
                )
                if bucket.get("scores")
            ]

        analytics["skills"] = build_rows(skill_buckets, "evaluated_questions")
        analytics["topics"] = build_rows(topic_buckets, "question_count")
        analytics["question_types"] = build_rows(type_buckets, "question_count")
        if initial_scores or followup_scores:
            analytics["follow_up"] = {
                "initial_average": _nullable_avg(initial_scores),
                "followup_average": _nullable_avg(followup_scores),
                "followups_answered_successfully": successful_followups,
                "followups_evaluated": len(followup_scores),
                "shallow_followups": shallow_followups[:12],
            }
        recurring = []
        for label, bucket in pattern_buckets.items():
            session_count = len({item for item in bucket["sessions"] if item})
            if bucket["count"] >= 2 and session_count >= 2:
                recurring.append({
                    "label": label,
                    "count": bucket["count"],
                    "round_count": session_count,
                    "evidence": bucket["evidence"][:12],
                })
        if len(shallow_followups) >= 2 and len({item.get("interview_id") for item in shallow_followups}) >= 2:
            recurring.append({
                "label": "Basic answers hold up, but deeper follow-ups lose technical depth",
                "count": len(shallow_followups),
                "round_count": len({item.get("interview_id") for item in shallow_followups}),
                "evidence": shallow_followups[:12],
            })
        analytics["patterns"] = sorted(recurring, key=lambda item: (-item["count"], item["label"]))
        behavior_metrics = []
        for label, key, suffix in (
            ("Average answer duration", "average_answer_seconds", " sec"),
            ("Average time before answering", "response_latency_seconds", " sec"),
            ("Average speaking pace", "words_per_minute", " wpm"),
        ):
            values = behavior_values.get(key) or []
            if values:
                behavior_metrics.append({"label": label, "value": _nullable_avg(values), "display": _format_number_value(_nullable_avg(values), suffix)})
        for label, key in (
            ("Questions asked", "asked"),
            ("Questions answered", "answered"),
            ("Fully answered", "fully"),
            ("Partial answers", "partial"),
            ("Not answered", "not_answered"),
        ):
            if answer_counts.get(key):
                behavior_metrics.append({"label": label, "value": int(answer_counts[key]), "display": str(int(answer_counts[key]))})
        asked = answer_counts.get("asked")
        if asked:
            for label, key in (("Fully answered", "fully"), ("Partial answers", "partial"), ("Not answered", "not_answered")):
                if answer_counts.get(key):
                    percentage = round(answer_counts[key] / asked * 100, 1)
                    behavior_metrics.append({"label": f"{label} %", "value": percentage, "display": _format_percent_value(percentage)})
        analytics["behavior"] = behavior_metrics
    else:
        topic_buckets: Dict[str, Dict[str, Any]] = defaultdict(_analytics_bucket)
        failure_buckets: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"count": 0, "sessions": set(), "evidence": []})
        test_failure_buckets: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"count": 0, "sessions": set(), "evidence": []})
        total_problems = attempted = submitted = solved = 0
        visible_passed = visible_total = hidden_passed = hidden_total = 0
        coded_not_submitted = never_attempted = 0
        run_counts: List[float] = []
        solved_times: List[float] = []
        unsolved_times: List[float] = []
        complexity_rows: List[Dict[str, Any]] = []
        submission_issues: List[Dict[str, Any]] = []
        for session in comparable:
            analysis = session.get("analysis") or {}
            technical = analysis.get("technical") if isinstance(analysis.get("technical"), dict) else {}
            matrix = [item for item in technical.get("test_matrix") or [] if isinstance(item, dict)]
            total_problems += len(matrix) or int(technical.get("round_count") or 0)
            for item in matrix:
                state = str(item.get("evidence_state") or "no_evidence")
                attempted_item = state not in {"no_evidence", "no_candidate_evidence"}
                submitted_item = state == "final_submission" or bool(item.get("submission_id"))
                verdict = str(item.get("final_verdict") or "").lower()
                score = _performance_number(item.get("final_pass_rate"), item.get("score"))
                evidence = {
                    "interview_id": session.get("interview_id"),
                    "date": _performance_iso(session.get("created_at")),
                    "problem": _short_text(item.get("title") or item.get("problem") or item.get("round_type"), 110),
                    "score": score,
                    "round_id": item.get("round_id"),
                }
                if attempted_item:
                    attempted += 1
                    if submitted_item:
                        submitted += 1
                    else:
                        coded_not_submitted += 1
                    solved_item = submitted_item and (
                        verdict in {"accepted", "correct", "solved", "meets_bar"}
                        or (score is not None and score >= 100)
                    )
                    if solved_item:
                        solved += 1
                    if score is not None:
                        for topic in _analytics_topic_labels(item, "technical"):
                            _analytics_add(
                                topic_buckets[topic],
                                score,
                                session,
                                evidence,
                                issue=str(item.get("failure_reason") or item.get("main_issue") or "").strip() or None,
                                success=solved_item,
                            )
                    if item.get("run_count") is not None:
                        run_counts.append(float(item.get("run_count") or 0))
                    elapsed = _performance_raw_number(item.get("time_used_seconds"))
                    if elapsed is not None:
                        (solved_times if submitted_item and (score or 0) >= 100 else unsolved_times).append(elapsed / 60)
                    visible_passed += int(item.get("visible_passed") or 0)
                    visible_total += int(item.get("visible_total") or 0)
                    hidden_passed += int(item.get("hidden_passed") or 0)
                    hidden_total += int(item.get("hidden_total") or 0)
                    raw_issue = item.get("failure_reason") or item.get("main_issue")
                    issue = str(raw_issue or "").strip()
                    issue_lower = issue.lower()
                    if any(token in issue_lower for token in ("platform", "service unavailable", "execution service", "infrastructure")):
                        issue = ""
                    if not issue and submitted_item and verdict not in {"accepted", "correct", "solved", "meets_bar", ""}:
                        issue = _human_label(verdict)
                    if not issue and not submitted_item:
                        issue = "No final submission"
                    if issue:
                        issue = _short_text(issue, 120)
                        bucket = failure_buckets[issue]
                        bucket["count"] += 1
                        bucket["sessions"].add(str(session.get("interview_id") or ""))
                        bucket["evidence"].append(evidence)
                    if not submitted_item:
                        submission_issues.append({
                            **evidence,
                            "issue": "No final submission",
                            "time_used_seconds": item.get("time_used_seconds"),
                            "run_count": item.get("run_count"),
                        })
                    visible_total_for_pattern = int(item.get("visible_total") or 0)
                    hidden_total_for_pattern = int(item.get("hidden_total") or 0)
                    visible_passed_for_pattern = int(item.get("visible_passed") or 0)
                    hidden_passed_for_pattern = int(item.get("hidden_passed") or 0)
                    test_pattern = None
                    if hidden_total_for_pattern and hidden_passed_for_pattern < hidden_total_for_pattern:
                        test_pattern = (
                            "Visible tests pass, hidden tests fail"
                            if visible_total_for_pattern and visible_passed_for_pattern == visible_total_for_pattern
                            else "Hidden tests fail"
                        )
                    elif visible_total_for_pattern and visible_passed_for_pattern < visible_total_for_pattern:
                        test_pattern = "Visible tests fail"
                    if str(issue).lower() == "runtime error":
                        test_pattern = "Runtime failures"
                    if test_pattern:
                        test_bucket = test_failure_buckets[test_pattern]
                        test_bucket["count"] += 1
                        test_bucket["sessions"].add(str(session.get("interview_id") or ""))
                        test_bucket["evidence"].append({**evidence, "issue": test_pattern})
                    expected = item.get("expected_time_complexity")
                    actual = item.get("user_time_complexity") or item.get("complexity")
                    if expected or actual:
                        complexity_rows.append({
                            "problem": evidence.get("problem"),
                            "expected": expected,
                            "actual": actual,
                            "round_id": item.get("round_id"),
                        })
                else:
                    never_attempted += 1
        analytics["topics"] = [
            _analytics_bucket_row(label, bucket, count_key="problems_attempted", count=len(bucket.get("scores") or []), extra={
                "problems_solved": int(bucket.get("successes") or 0),
                "average_test_pass": _nullable_avg([float(item) for item in bucket.get("scores") or []]),
            })
            for label, bucket in sorted(topic_buckets.items(), key=lambda item: (-len(item[1].get("scores") or []), item[0]))
            if bucket.get("scores")
        ]
        analytics["submission"] = {
            "problems_attempted": attempted,
            "problems_total": total_problems,
            "problems_submitted": submitted,
            "problems_solved": solved,
            "submission_rate": round(submitted / attempted * 100, 1) if attempted else None,
            "coded_not_submitted": coded_not_submitted,
            "never_attempted": never_attempted,
            "problems": submission_issues[:24],
        }
        test_metrics = []
        if visible_total:
            test_metrics.append({"label": "Visible tests passed", "value": round(visible_passed / visible_total * 100, 1), "display": _format_percent_value(round(visible_passed / visible_total * 100, 1))})
        if hidden_total:
            test_metrics.append({"label": "Hidden tests passed", "value": round(hidden_passed / hidden_total * 100, 1), "display": _format_percent_value(round(hidden_passed / hidden_total * 100, 1))})
        analytics["tests"] = test_metrics
        analytics["test_patterns"] = [
            {
                "label": label,
                "count": bucket["count"],
                "round_count": len({item for item in bucket["sessions"] if item}),
                "evidence": bucket["evidence"][:12],
            }
            for label, bucket in sorted(test_failure_buckets.items(), key=lambda item: (-item[1]["count"], item[0]))
            if bucket["count"] >= 2 and len({item for item in bucket["sessions"] if item}) >= 2
        ]
        time_metrics = []
        if run_counts and _nullable_avg(run_counts) is not None and _nullable_avg(run_counts) < 2:
            time_metrics.append({
                "label": "Runs code too few times before submitting",
                "value": _nullable_avg(run_counts),
                "display": _format_number_value(_nullable_avg(run_counts), " runs/problem"),
                "count": len(run_counts),
            })
        if unsolved_times:
            unsolved_average = _nullable_avg(unsolved_times)
            solved_average = _nullable_avg(solved_times)
            time_metrics.append({
                "label": "Unsolved problems consume time without a final result",
                "value": unsolved_average,
                "display": (
                    f"{_format_number_value(unsolved_average, ' min')} average"
                    + (f" vs {_format_number_value(solved_average, ' min')} for solved problems" if solved_average is not None else "")
                ),
                "count": len(unsolved_times),
            })
        analytics["time"] = time_metrics
        analytics["patterns"] = [
            {"label": label, "count": bucket["count"], "round_count": len({item for item in bucket["sessions"] if item}), "evidence": bucket["evidence"][:12]}
            for label, bucket in sorted(failure_buckets.items(), key=lambda item: (-item[1]["count"], item[0]))
            if bucket["count"] >= 2 and len({item for item in bucket["sessions"] if item}) >= 2
        ]
        if complexity_rows:
            analytics["complexity"] = complexity_rows[:24]
        analytics["summary"].update({
            "problems_attempted": attempted,
            "problems_total": total_problems,
            "problems_solved": solved,
            "submission_rate": round(submitted / attempted * 100, 1) if attempted else None,
        })

    for key in ("skills", "topics", "question_types"):
        for row in analytics.get(key) or []:
            direction = row.get("trend")
            if direction in {"up", "down", "stable"}:
                analytics["improvement"][{"up": "improving", "down": "declining", "stable": "stable"}[direction]].append({
                    "label": row.get("label"),
                    "baseline": row.get("average_score") if row.get("delta") is None else round(float(row.get("recent_average") or 0) - float(row.get("delta") or 0), 1),
                    "recent": row.get("recent_average"),
                    "delta": row.get("delta"),
                    "round_count": row.get("round_count"),
                })
    return analytics


def _canonical_performance_cohort(
    rows: List[Dict[str, Any]],
) -> tuple[Dict[str, Any], Dict[str, Any], List[Dict[str, Any]]]:
    """Separate latest-attempt state from the latest official scoring cohort."""
    latest_attempt = rows[0]
    score_anchor = next(
        (
            item
            for item in rows
            if item.get("evidence_status") == "sufficient"
            and item.get("overall_score") is not None
        ),
        latest_attempt,
    )
    comparable = [
        item for item in rows
        if item.get("taxonomy_version") == score_anchor.get("taxonomy_version")
        and item.get("rubric_version") == score_anchor.get("rubric_version")
        and item.get("evaluator_version") == score_anchor.get("evaluator_version")
        and item.get("profile_family") == score_anchor.get("profile_family")
        and item.get("evidence_status") == score_anchor.get("evidence_status")
    ]
    return latest_attempt, score_anchor, comparable


def _canonical_performance_payloads(cursor: Any, user_id: str, limit: int = 100) -> Dict[str, Optional[Dict[str, Any]]]:
    cursor.execute(
        """
        SELECT analysis.analysis_id, analysis.interview_id, analysis.mode,
               analysis.schema_version, analysis.evidence_hash,
               analysis.status, analysis.analysis_json, analysis.evidence_index_json,
               analysis.analysis_json_encrypted, analysis.evidence_index_encrypted,
               analysis.overall_score, analysis.evaluator_version,
               analysis.taxonomy_version, analysis.rubric_version,
               analysis.duration_seconds, analysis.evidence_status,
               COALESCE(interview.completed_at, interview.created_at) AS session_at,
               analysis.created_at AS analyzed_at,
               interview.job_title,
               interview.settings
        FROM SessionPerformanceAnalyses analysis
        JOIN Interviews interview
          ON interview.interview_id = analysis.interview_id
         AND interview.user_id = analysis.user_id
        WHERE analysis.user_id = %s
          AND analysis.status = 'ready'
          AND analysis.schema_version = 'session-performance-v4'
          AND analysis.producer_version = %s
          AND analysis.is_current = TRUE
          AND analysis.analysis_json_encrypted IS NOT NULL
          AND analysis.evidence_index_encrypted IS NOT NULL
        ORDER BY COALESCE(interview.completed_at, interview.created_at) DESC,
                 analysis.created_at DESC
        LIMIT %s
        """,
        (user_id, ANALYSIS_STAGE_VERSION, min(max(int(limit or 100), 1), 200)),
    )
    grouped: Dict[str, List[Dict[str, Any]]] = {"interview": [], "technical": []}
    for row in cursor.fetchall() or []:
        encrypted_shape = len(row) >= 17
        analysis = (
            _encrypted_json_object(row[8])
            if encrypted_shape else _json_object(row[6])
        )
        evidence_index = (
            _encrypted_json_object(row[9])
            if encrypted_shape else _json_object(row[7])
        )
        offset = 2 if encrypted_shape else 0
        mode = "technical" if str(row[2] or "").lower() == "technical" else "interview"
        grouped[mode].append({
            "analysis_id": row[0],
            "interview_id": row[1],
            "mode": row[2] or ("technical" if mode == "technical" else "mock"),
            "schema_version": row[3],
            "evidence_hash": row[4],
            "status": row[5],
            "analysis": analysis,
            "evidence_index": evidence_index,
            "overall_score": float(row[8 + offset]) if row[8 + offset] is not None else None,
            "evaluator_version": row[9 + offset],
            "taxonomy_version": row[10 + offset],
            "rubric_version": row[11 + offset],
            "duration_seconds": int(row[12 + offset]) if row[12 + offset] is not None else None,
            "evidence_status": row[13 + offset],
            "created_at": row[14 + offset],
            "analyzed_at": row[15 + offset] if len(row) > 15 + offset else row[14 + offset],
            "role": row[18] if encrypted_shape and len(row) > 18 else None,
            "settings": _json_object(row[19]) if encrypted_shape and len(row) > 19 else {},
            "profile_family": (
                analysis.get("profile_type")
                or ((analysis.get("report") or {}).get("profile_type") if isinstance(analysis.get("report"), dict) else None)
                or "unknown"
            ),
        })

    payloads: Dict[str, Optional[Dict[str, Any]]] = {"interview": None, "technical": None}
    for mode, rows in grouped.items():
        if not rows:
            continue
        latest_attempt, latest, comparable = _canonical_performance_cohort(rows)

        def evidence_ids_for(item: Dict[str, Any]) -> List[str]:
            index = item.get("evidence_index") or {}
            response_ids = [
                str(entry.get("response_id"))
                for entry in index.get("responses", [])
                if isinstance(entry, dict) and entry.get("response_id")
            ]
            response_ids.extend(str(value) for value in index.get("response_ids", []) if value)
            round_ids = [
                str(entry.get("submission_id") or entry.get("round_id"))
                for entry in index.get("technical_rounds", [])
                if isinstance(entry, dict)
                and entry.get("has_candidate_evidence", True)
                and (entry.get("submission_id") or entry.get("round_id"))
            ]
            round_ids.extend(str(value) for value in index.get("submission_ids", []) if value)
            round_ids.extend(str(value) for value in index.get("round_ids", []) if value)
            round_ids.extend(
                str(entry.get("run_id"))
                for entry in index.get("technical_runs", [])
                if isinstance(entry, dict) and entry.get("run_id")
            )
            round_ids.extend(
                str(entry.get("snapshot_id"))
                for entry in index.get("technical_drafts", [])
                if isinstance(entry, dict) and entry.get("snapshot_id")
            )
            round_ids.extend(str(value) for value in index.get("run_ids", []) if value)
            round_ids.extend(str(value) for value in index.get("snapshot_ids", []) if value)
            return list(dict.fromkeys([*response_ids, *round_ids]))

        def report_anchor_for(item: Dict[str, Any]) -> Optional[str]:
            index = item.get("evidence_index") or {}
            if mode == "technical":
                return next(
                    (
                        str(entry.get("round_id"))
                        for key in (
                            "technical_rounds",
                            "technical_runs",
                            "technical_drafts",
                        )
                        for entry in index.get(key, [])
                        if isinstance(entry, dict) and entry.get("round_id")
                    ),
                    None,
                )
            ids = evidence_ids_for(item)
            return ids[0] if ids else None

        comparable.reverse()
        comparable_ids = {str(item.get("analysis_id")) for item in comparable}
        round_history = []
        for item in rows:
            history_item = _canonical_round_history_item(item, mode)
            history_item["included_in_trend"] = str(item.get("analysis_id")) in comparable_ids
            round_history.append(history_item)
        round_history.sort(key=lambda item: item.get("completed_at") or "", reverse=True)
        trend = [
            {
                "analysis_id": item["analysis_id"],
                "interview_id": item["interview_id"],
                "score": item["overall_score"] if item["evidence_status"] == "sufficient" else None,
                "date": item["created_at"].isoformat() if item["created_at"] else None,
                "evidence_status": item["evidence_status"],
                "evidence_ids": evidence_ids_for(item),
                ("round_id" if mode == "technical" else "response_id"): (
                    report_anchor_for(item)
                ),
            }
            for item in comparable
        ]
        overview: List[Dict[str, Any]] = []
        has_official_score = (
            latest["overall_score"] is not None
            and latest["evidence_status"] == "sufficient"
        )
        latest_has_official_score = (
            latest_attempt["overall_score"] is not None
            and latest_attempt["evidence_status"] == "sufficient"
        )
        if has_official_score:
            overview.append({
                "label": (
                    "Previous official score"
                    if latest_attempt["analysis_id"] != latest["analysis_id"]
                    else "Overall score"
                ),
                "value": _format_percent_value(latest["overall_score"]),
                "raw_value": latest["overall_score"],
            })
        overview.append({
            "label": "Evidence status",
            "value": _human_label(latest_attempt["evidence_status"] or "unknown"),
        })
        if latest_attempt["duration_seconds"] is not None:
            overview.append({
                "label": "Session duration",
                "value": _format_number_value(round(latest_attempt["duration_seconds"] / 60, 1), " min"),
                "raw_value": latest_attempt["duration_seconds"],
            })

        analysis = latest["analysis"]
        latest_attempt_analysis = latest_attempt["analysis"]
        latest_evidence_ids = evidence_ids_for(latest)
        latest_round_id = next(
            (
                str(entry.get("round_id"))
                for key in (
                    "technical_rounds",
                    "technical_runs",
                    "technical_drafts",
                )
                for entry in (latest.get("evidence_index") or {}).get(key, [])
                if isinstance(entry, dict) and entry.get("round_id")
            ),
            None,
        )
        sections: List[Dict[str, Any]] = []
        scored_trend = [item for item in trend if item.get("score") is not None][-5:]
        if scored_trend:
            sections.append({
                "id": "score_trend",
                "title": "Comparable score trend",
                "kind": "trend",
                "trend": scored_trend,
            })
        dimensions = analysis.get("dimensions") or analysis.get("dimension_scores") or {}
        if isinstance(dimensions, dict) and latest["evidence_status"] == "sufficient":
            rows_payload = [
                {
                    "dimension": _human_label(key),
                    "score": float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None,
                    "source_analysis_id": latest["analysis_id"],
                    "evidence_ids": latest_evidence_ids,
                    "interview_id": latest["interview_id"],
                    ("round_id" if mode == "technical" else "response_id"): (
                        latest_round_id if mode == "technical" else (latest_evidence_ids[0] if latest_evidence_ids else None)
                    ),
                }
                for key, value in dimensions.items()
            ]
            if rows_payload:
                sections.append({
                    "id": "dimension_scores",
                    "title": "Evidence-backed dimensions",
                    "kind": "score_rows",
                    "rows": rows_payload,
                })
        question_rows = analysis.get("question_analyses") or analysis.get("questions") or []
        if isinstance(question_rows, list) and question_rows:
            evidence_rows = []
            for item in question_rows[:50]:
                if not isinstance(item, dict):
                    continue
                score_value = item.get("overall_score")
                if score_value is None:
                    score_value = item.get("provisional_score")
                try:
                    numeric_score = float(score_value) if score_value is not None else None
                except (TypeError, ValueError):
                    numeric_score = None
                flags = [
                    str(flag).strip()
                    for flag in (item.get("answer_quality_flags") or [])
                    if str(flag).strip()
                ]
                missed_points = item.get("missed_point_ids") or []
                incorrect_claims = item.get("incorrect_claim_ids") or []
                contradictions = item.get("contradictions") or []
                dimension_scores = item.get("dimension_scores") or {}
                low_dimension = any(
                    isinstance(value, (int, float))
                    and not isinstance(value, bool)
                    and float(value) < 70
                    for value in dimension_scores.values()
                ) if isinstance(dimension_scores, dict) else False
                needs_repair = bool(
                    item.get("insufficient_evidence")
                    or numeric_score is None
                    or numeric_score < 70
                    or flags
                    or missed_points
                    or incorrect_claims
                    or contradictions
                    or low_dimension
                )
                if not needs_repair:
                    continue
                if item.get("insufficient_evidence") or numeric_score is None:
                    answer_status = "Needs reframing"
                elif numeric_score < 50:
                    answer_status = "Needs rebuilding"
                else:
                    answer_status = "Needs reframing"
                if flags:
                    issue = _flag_label(flags[0])
                elif incorrect_claims or contradictions:
                    issue = "Correct or clarify the inaccurate claim"
                elif missed_points:
                    issue = "Add the missing evidence or trade-off"
                elif low_dimension:
                    issue = "Restructure the answer for clarity and completeness"
                else:
                    issue = "Reframe the answer with a direct point and proof"
                evidence_rows.append({
                    "question": _short_text(item.get("question"), 95),
                    "topic": _human_label(item.get("skill") or ((item.get("taxonomy_keys") or ["General"])[0])),
                    "score": _format_percent_value(numeric_score),
                    "status": answer_status,
                    "issue": issue,
                    "response_id": item.get("response_id"),
                    "evidence_id": item.get("response_id"),
                })
            if evidence_rows:
                sections.append({
                    "id": "answers_needing_work",
                    "title": "Answers That Need Work",
                    "kind": "table",
                    "columns": [
                        {"key": "question", "label": "Question"},
                        {"key": "topic", "label": "Topic"},
                        {"key": "score", "label": "Score"},
                        {"key": "status", "label": "Status"},
                        {"key": "issue", "label": "Issue"},
                    ],
                    "rows": evidence_rows,
                })
        technical = analysis.get("technical") if isinstance(analysis.get("technical"), dict) else {}
        if mode == "technical" and technical:
            technical_metrics = []
            if technical.get("correctness_score") is not None and latest["evidence_status"] == "sufficient":
                technical_metrics.append({
                    "label": "Test correctness",
                    "value": _format_percent_value(float(technical["correctness_score"])),
                    "raw_value": float(technical["correctness_score"]),
                })
            for label, key in (
                ("Prepared rounds", "round_count"),
                ("Final submissions", "submission_count"),
                ("Recorded runs", "run_event_count"),
                ("Saved drafts", "draft_count"),
                ("Assessed written responses", "typed_assessed_count"),
            ):
                if technical.get(key) is not None:
                    technical_metrics.append({"label": label, "value": str(int(technical.get(key) or 0))})
            if technical_metrics:
                sections.append({
                    "id": "technical_summary",
                    "title": "Round evidence",
                    "kind": "metrics",
                    "metrics": technical_metrics,
                })

            problem_rows = []
            for item in technical.get("test_matrix") or []:
                if not isinstance(item, dict):
                    continue
                problem_rows.append({
                    "round_id": item.get("round_id"),
                    "evidence_state": item.get("evidence_state") or "unknown",
                    "evidence_id": item.get("submission_id") or item.get("response_id") or item.get("latest_run_id") or item.get("snapshot_id"),
                    "problem": item.get("title") or _human_label(item.get("round_type") or "Technical response"),
                    "language": item.get("language"),
                    "result": _human_label(item.get("final_verdict") or "unknown"),
                    "score": (
                        _format_percent_value(item.get("final_pass_rate") if item.get("final_pass_rate") is not None else item.get("score"))
                        if latest["evidence_status"] == "sufficient" else None
                    ),
                    "runtime": _format_number_value(item.get("runtime_ms"), " ms"),
                })
            if problem_rows:
                sections.append({
                    "id": "technical_problem_evidence",
                    "title": "Technical round evidence",
                    "kind": "table",
                    "columns": [
                        {"key": "problem", "label": "Problem"},
                        {"key": "language", "label": "Language"},
                        {"key": "result", "label": "Result"},
                        {"key": "score", "label": "Tests"},
                        {"key": "runtime", "label": "Runtime"},
                    ],
                    "rows": problem_rows,
                })
        next_focus = (
            latest_attempt_analysis.get("next_focus")
            if isinstance(latest_attempt_analysis.get("next_focus"), dict)
            else analysis.get("next_focus")
            if isinstance(analysis.get("next_focus"), dict)
            else None
        )
        if not next_focus and mode == "technical" and technical.get("weak_topics"):
            weak_topic = next((item for item in technical["weak_topics"] if isinstance(item, dict)), None)
            if weak_topic:
                next_focus = {
                    "title": _human_label(weak_topic.get("topic") or "Technical reasoning"),
                    "description": weak_topic.get("repair_action"),
                }
        source_analysis_ids = [item["analysis_id"] for item in comparable]
        latest_attempt_evidence_count = len(evidence_ids_for(latest_attempt))
        score_evidence_count = len(evidence_ids_for(latest))
        confidence = (
            "insufficient"
            if not latest_has_official_score
            else (
                "high"
                if len(comparable) >= 3 and score_evidence_count >= 3
                else ("medium" if score_evidence_count >= 2 else "low")
            )
        )
        cohort_material = "|".join(str(value or "") for value in (
            mode, latest["evaluator_version"], latest["taxonomy_version"],
            latest["rubric_version"], latest["profile_family"], latest["evidence_status"],
        ))
        excluded_count = len(rows) - len(comparable)
        overview.extend([
            {"label": "Confidence", "value": _human_label(confidence)},
            {
                "label": "Latest-attempt evidence",
                "value": str(latest_attempt_evidence_count),
                "raw_value": latest_attempt_evidence_count,
            },
            {"label": "Comparable sessions", "value": str(len(comparable)), "raw_value": len(comparable)},
        ])
        communication_summary = _canonical_communication_summary(comparable)
        dimension_directions = _canonical_dimension_directions(comparable)
        technical_summary = _canonical_technical_summary(
            comparable,
            trend if mode == "technical" else [],
        )
        cumulative_analytics = _cumulative_performance_analytics(comparable, mode)
        if mode != "technical":
            interview_dimensions = _analysis_dimensions(latest.get("analysis") or {})
            technical_summary["latest_score"] = _performance_number(
                interview_dimensions.get("technical_competency"),
                interview_dimensions.get("technical_accuracy"),
                interview_dimensions.get("correctness"),
                interview_dimensions.get("depth"),
            )
        project_explanation = _canonical_project_explanation(comparable)
        strengths = _canonical_strengths(comparable)
        ai_insights = _canonical_ai_insights(
            comparable,
            trend,
            communication_summary,
            dimension_directions,
        )
        payload = _dynamic_payload(mode, True, overview, sections, next_focus)
        payload.update({
            "source": "canonical",
            "source_kind": "canonical_v4",
            "analysis_id": latest_attempt["analysis_id"],
            "interview_id": latest_attempt["interview_id"],
            "official_analysis_id": latest["analysis_id"] if has_official_score else None,
            "official_interview_id": latest["interview_id"] if has_official_score else None,
            "official_score": latest["overall_score"] if has_official_score else None,
            "official_scored_at": latest["created_at"].isoformat() if has_official_score and latest["created_at"] else None,
            "overall_score": latest_attempt["overall_score"] if latest_has_official_score else None,
            "duration_seconds": latest_attempt["duration_seconds"],
            "evidence_status": latest_attempt["evidence_status"],
            "evidence_index": latest_attempt["evidence_index"],
            "current_value": latest_attempt["overall_score"] if latest_has_official_score else None,
            "confidence": confidence,
            "evidence_count": latest_attempt_evidence_count,
            "has_evidence": latest_attempt_evidence_count > 0,
            "has_official_score": has_official_score,
            "score_state": (
                "ready"
                if latest_attempt["overall_score"] is not None
                and latest_attempt["evidence_status"] == "sufficient"
                else "run_only"
                if latest_attempt["evidence_status"] == "draft_or_run_only"
                else "insufficient"
            ),
            "included_in_trend": (
                latest_attempt["overall_score"] is not None
                and latest_attempt["evidence_status"] == "sufficient"
            ),
            "time_window": {
                "from": trend[0]["date"] if trend else None,
                "to": trend[-1]["date"] if trend else None,
            },
            "source_analysis_ids": source_analysis_ids,
            "next_recommended_focus": next_focus,
            "empty_state_explanation": (
                "This cohort does not have enough official evidence for a readiness percentage."
                if not latest_has_official_score else None
            ),
            "comparison_notice": (
                "The latest attempt did not produce an official score. The previous official score is shown separately for reference."
                if latest_attempt["analysis_id"] != latest["analysis_id"]
                else (
                    f"{excluded_count} session(s) use incompatible assessment criteria and are preserved outside this trend."
                    if excluded_count else (
                    f"Trend lines compare {len(comparable)} session(s) assessed with the same mode, profile family, evidence sufficiency, evaluator, taxonomy, and rubric."
                    if len(comparable) > 1 else None
                    )
                )
            ),
            "comparability": {
                "taxonomy_version": latest["taxonomy_version"],
                "rubric_version": latest["rubric_version"],
                "evaluator_version": latest["evaluator_version"],
                "profile_family": latest["profile_family"],
                "evidence_status": latest["evidence_status"],
                "latest_attempt_evidence_status": latest_attempt["evidence_status"],
                "cohort_id": hashlib.sha256(cohort_material.encode("utf-8")).hexdigest()[:20],
                "comparable_analysis_count": len(comparable),
                "excluded_incompatible_count": excluded_count,
            },
            "trend": trend,
            "round_history": round_history,
            "analytics": cumulative_analytics,
            "page_summary": {
                "communication": communication_summary,
                "technical": technical_summary,
                "project_explanation": project_explanation,
                "insights": {
                    "recurring_mistakes": [
                        item for item in communication_summary.get("patterns", [])
                        if item.get("recurring")
                    ],
                    "improving": dimension_directions.get("improving", []),
                    "declining": dimension_directions.get("declining", []),
                    "ai_insights": ai_insights,
                },
                "strengths": strengths,
            },
        })
        payloads[mode] = payload
    return payloads


def _performance_payload_score(payload: Optional[Dict[str, Any]]) -> Optional[float]:
    if not payload:
        return None
    direct = _performance_number(payload.get("overall_score"), payload.get("current_value"))
    if direct is not None:
        return direct
    return None


def _performance_payload_trend(payload: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not payload:
        return []
    trend = payload.get("trend")
    if not isinstance(trend, list):
        trend = next((
            section.get("trend")
            for section in payload.get("sections") or []
            if isinstance(section, dict) and section.get("kind") == "trend" and section.get("trend")
        ), [])
    return [item for item in trend or [] if isinstance(item, dict) and item.get("score") is not None][-5:]


def _performance_role_context(cursor: Any, user_id: str) -> Dict[str, Optional[str]]:
    cursor.execute(
        """
        SELECT role, company
        FROM JobProfiles
        WHERE user_id = %s
        ORDER BY is_selected DESC, updated_at DESC NULLS LAST, created_at DESC
        LIMIT 1
        """,
        (user_id,),
    )
    selected = cursor.fetchone()
    if selected:
        return {"role": selected[0], "company": selected[1]}
    try:
        profile = _profile_context(cursor, user_id).get("profile_context") or {}
        role = _target_role(profile)
        return {"role": role if role != "your target role" else None, "company": None}
    except Exception:
        logger.exception("Failed to load performance role context")
        return {"role": None, "company": None}


def _readiness_summary(
    interview_payload: Optional[Dict[str, Any]],
    technical_payload: Optional[Dict[str, Any]],
    role: Optional[str],
) -> Dict[str, Any]:
    interview_summary = (interview_payload or {}).get("page_summary") or {}
    communication = ((interview_summary.get("communication") or {}).get("fluency_clarity") or {}).get("score")
    interview_technical = (interview_summary.get("technical") or {}).get("latest_score")
    technical_round_score = _performance_payload_score(technical_payload)
    technical = _performance_number(technical_round_score, interview_technical)
    communication = _performance_number(communication)
    trend = _performance_payload_trend(interview_payload)
    scores = [float(item["score"]) for item in trend if item.get("score") is not None]
    consistency = None
    if len(scores) >= 2:
        changes = [abs(scores[index] - scores[index - 1]) for index in range(1, len(scores))]
        consistency = _clip(100 - ((sum(changes) / len(changes)) * 2.0))
    history = _clip((len(scores) / 5.0) * 100)

    components = [
        {"key": "communication", "label": "Communication", "score": communication, "weight": 30},
        {"key": "technical", "label": "Technical performance", "score": technical, "weight": 30},
        {"key": "consistency", "label": "Consistency", "score": consistency, "weight": 20},
        {"key": "history", "label": "Interview history", "score": history, "weight": 20},
    ]
    readiness = None
    if communication is not None and technical is not None and consistency is not None:
        readiness = _clip(
            communication * 0.30
            + technical * 0.30
            + consistency * 0.20
            + history * 0.20
        )
    return {
        "score": readiness,
        "label": _score_band(readiness) if readiness is not None else "Building evidence",
        "role": role,
        "components": components,
        "detail": (
            "Weighted from communication (30%), technical performance (30%), consistency (20%), and up to five comparable interviews (20%)."
            if readiness is not None
            else "Complete at least two comparable interviews with communication and technical evidence to calculate readiness."
        ),
    }


def _unique_performance_items(items: List[Any], limit: int = 5) -> List[Any]:
    unique: List[Any] = []
    seen: set[str] = set()
    for item in items:
        if item in (None, "", {}):
            continue
        key = json.dumps(item, sort_keys=True, default=str).lower() if isinstance(item, dict) else str(item).lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
        if len(unique) == limit:
            break
    return unique


def _build_performance_page_payload(
    interview_payload: Optional[Dict[str, Any]],
    technical_payload: Optional[Dict[str, Any]],
    role_context: Dict[str, Optional[str]],
) -> Dict[str, Any]:
    interview_summary = (interview_payload or {}).get("page_summary") or {}
    technical_round_summary = (technical_payload or {}).get("page_summary") or {}
    interview_insights = interview_summary.get("insights") or {}
    technical_insights = technical_round_summary.get("insights") or {}
    communication = interview_summary.get("communication") or {
        "fluency_clarity": {"score": None, "detail": "Communication analysis is not available yet."},
        "confidence": {"score": None, "detail": "Voice delivery evidence is not available yet."},
        "patterns": [],
    }
    interview_technical = interview_summary.get("technical") or {}
    technical_round = technical_round_summary.get("technical") or {}
    technical = {
        **interview_technical,
        **technical_round,
        "knowledge_gaps": _unique_performance_items([
            *(technical_round.get("knowledge_gaps") or []),
            *(interview_technical.get("knowledge_gaps") or []),
        ], limit=6),
    }
    project_explanation = interview_summary.get("project_explanation") or {
        "score": None,
        "answer_count": 0,
        "session_count": 0,
        "breakdown": [],
        "detail": "No project explanation has enough scored evidence yet.",
    }
    recurring = _unique_performance_items([
        *(interview_insights.get("recurring_mistakes") or []),
        *(technical_insights.get("recurring_mistakes") or []),
    ])
    improving = _unique_performance_items([
        *(interview_insights.get("improving") or []),
        *(technical_insights.get("improving") or []),
    ])
    declining = _unique_performance_items([
        *(interview_insights.get("declining") or []),
        *(technical_insights.get("declining") or []),
    ])
    ai_insights = _unique_performance_items([
        *(interview_insights.get("ai_insights") or []),
        *(technical_insights.get("ai_insights") or []),
    ])
    strengths = _unique_performance_items([
        *(interview_summary.get("strengths") or []),
        *(technical_round_summary.get("strengths") or []),
    ])
    role = role_context.get("role")
    return {
        "role": role_context,
        "interview_view": {
            "latest_score": _performance_payload_score(interview_payload),
            "trend": _performance_payload_trend(interview_payload),
            "communication": communication,
            "project_explanation": project_explanation,
            "insights": {
                "recurring_mistakes": interview_insights.get("recurring_mistakes") or [],
                "improving": interview_insights.get("improving") or [],
                "declining": interview_insights.get("declining") or [],
            },
            "strengths": interview_summary.get("strengths") or [],
        },
        "technical_view": {
            "latest_score": _performance_payload_score(technical_payload),
            "trend": _performance_payload_trend(technical_payload),
            "knowledge_gaps": technical_round.get("knowledge_gaps") or [],
            "insights": {
                "recurring_mistakes": technical_insights.get("recurring_mistakes") or [],
                "improving": technical_insights.get("improving") or [],
                "declining": technical_insights.get("declining") or [],
            },
            "strengths": technical_round_summary.get("strengths") or [],
        },
        "overall": {
            "latest_interview_score": _performance_payload_score(interview_payload),
            "performance_trend": _performance_payload_trend(interview_payload),
            "readiness": _readiness_summary(interview_payload, technical_payload, role),
        },
        "communication": communication,
        "technical": {
            "trend": _performance_payload_trend(technical_payload),
            "latest_score": _performance_payload_score(technical_payload),
            "knowledge_gaps": technical.get("knowledge_gaps") or [],
            "project_explanation": project_explanation,
        },
        "insights": {
            "recurring_mistakes": recurring,
            "improving": improving,
            "declining": declining,
            "ai_insights": ai_insights,
        },
        "strengths": strengths,
    }


def _question_type_label(question_type: str, question: str, is_followup: bool) -> str:
    if is_followup:
        return "Follow-up"
    raw_type = str(question_type or "").strip()
    if raw_type and raw_type.lower() not in {"main", "question", "general"}:
        return _human_label(raw_type)
    text = f"{question_type} {question}".lower()
    if "tell me about yourself" in text or "introduce" in text:
        return "Introduction"
    if "project" in text:
        return "Project"
    if any(token in text for token in ("technical", "algorithm", "system", "database", "api", "concept")):
        return "Technical"
    if any(token in text for token in ("behavior", "conflict", "failure", "team", "leadership")):
        return "Interview Round"
    return "General"


def _flag_label(flag: Any) -> str:
    mapping = {
        "too_short": "Incomplete answer",
        "vague": "Vague explanation",
        "off_topic": "Did not directly answer",
        "no_evidence": "Missing example or evidence",
        "no_response": "Unanswered",
        "low_lexical_relevance": "Needs clearer relevance",
        "missing_tradeoffs": "Missing trade-off",
        "technical_accuracy_unknown": "Technical accuracy not demonstrated",
        "insufficient_evidence": "Needs more evidence",
        "semantic_analysis_skipped": "Too little detail to assess deeply",
    }
    key = str(flag or "").strip().lower()
    return mapping.get(key, _human_label(key))


def _answer_status(response: Dict[str, Any]) -> str:
    text = str(response.get("response") or "").strip()
    flags = {str(flag).lower() for flag in response.get("answer_quality_flags") or []}
    score = response.get("score")
    relevance = response.get("relevance")
    technical_accuracy = response.get("technical_accuracy")
    if not text or "no_response" in flags:
        return "Unanswered"
    if not response.get("authoritative") and response.get("evidence_status") == "insufficient_evidence":
        return "Needs reframing"
    if "off_topic" in flags or (relevance is not None and relevance < 35):
        return "Avoided"
    if technical_accuracy is not None and technical_accuracy < 40:
        return "Incorrect"
    if score is not None and score < 40:
        return "Incorrect"
    if score is not None and score < 70:
        return "Partially answered"
    return "Properly answered"


def _answer_problem_type(response: Dict[str, Any]) -> Optional[str]:
    technical_accuracy = response.get("technical_accuracy")
    communication = response.get("communication")
    problem_solving = response.get("problem_solving")
    flags = {str(flag).lower() for flag in response.get("answer_quality_flags") or []}
    if "too_short" in flags:
        return "Incomplete answer"
    if "off_topic" in flags or "low_lexical_relevance" in flags:
        return "Needs clearer relevance"
    if "vague" in flags:
        return "Vague explanation"
    if "no_evidence" in flags or "insufficient_evidence" in flags:
        return "Missing evidence"
    if "missing_tradeoffs" in flags:
        return "Missing trade-off"
    if technical_accuracy is not None and technical_accuracy < 50:
        return "Knowledge gap"
    if problem_solving is not None and problem_solving < 55:
        return "Shallow reasoning"
    if communication is not None and communication < 55:
        return "Explanation structure"
    return None


def _interview_performance_payload(cursor, user_id: str) -> Dict[str, Any]:
    interviews = _recent_interviews(cursor, user_id, limit=40)
    responses = _response_rows(cursor, [item["interview_id"] for item in interviews])
    scored_responses = [item for item in responses if item.get("score") is not None]
    if not interviews or not responses:
        return _dynamic_payload("interview", False, [], [])

    scores_by_interview: Dict[str, List[float]] = defaultdict(list)
    for response in scored_responses:
        if response.get("interview_id"):
            scores_by_interview[str(response["interview_id"])].append(float(response["score"]))
    score_trend = [
        {
            "label": item.get("date"),
            "score": _nullable_avg(scores_by_interview.get(str(item.get("interview_id")), [])),
            "interview_id": item.get("interview_id"),
        }
        for item in interviews
        if scores_by_interview.get(str(item.get("interview_id")))
    ][-5:]
    responses_by_interview: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for response in responses:
        responses_by_interview[str(response.get("interview_id") or "")].append(response)
    round_history = [
        {
            "interview_id": item.get("interview_id"),
            "mode": "interview",
            "role": item.get("job_title"),
            "completed_at": item.get("date"),
            "score": _nullable_avg(scores_by_interview.get(str(item.get("interview_id")), [])),
            "duration_seconds": item.get("duration_seconds"),
            "score_state": "ready" if scores_by_interview.get(str(item.get("interview_id"))) else "insufficient",
            "source_kind": "recorded_evidence",
            "included_in_trend": bool(scores_by_interview.get(str(item.get("interview_id")))),
            "questions_completed": sum(1 for response in responses_by_interview.get(str(item.get("interview_id")), []) if response.get("response")),
            "questions_total": len(responses_by_interview.get(str(item.get("interview_id")), [])),
            "problems_attempted": None,
            "problems_total": None,
            "problems_solved": None,
            "change": None,
            "key_result": None,
        }
        for item in interviews
    ]
    response_scores = [float(item["score"]) for item in scored_responses]
    latest_score = float(score_trend[-1]["score"]) if score_trend and score_trend[-1].get("score") is not None else None
    overview: List[Dict[str, Any]] = []
    if latest_score is not None:
        overview.append({"label": "Overall interview score", "value": _format_percent_value(latest_score), "raw_value": latest_score})
    if len(score_trend) >= 2:
        delta = round(float(score_trend[-1]["score"]) - float(score_trend[0]["score"]), 1)
        overview.append({"label": "Score trend", "value": f"{delta:+g} pts", "raw_value": delta})

    dimension_sources = {
        "Correctness": [item.get("technical_accuracy") for item in responses],
        "Clarity": [item.get("communication") for item in responses],
        "Structure": [item.get("problem_solving") for item in responses],
        "Relevance": [item.get("relevance") for item in responses],
        "Confidence": [item.get("confidence") for item in responses],
    }
    dimensions = [
        {"metric": label, "score": _nullable_avg([float(v) for v in values if v is not None]), "attempts": len([v for v in values if v is not None])}
        for label, values in dimension_sources.items()
        if any(v is not None for v in values)
    ]
    dimensions = [item for item in dimensions if item["score"] is not None]
    if dimensions:
        strongest = max(dimensions, key=lambda item: item["score"])
        weakest = min(dimensions, key=lambda item: item["score"])
        overview.append({"label": "Strongest area", "value": strongest["metric"], "detail": _format_percent_value(strongest["score"])})
        overview.append({"label": "Main improvement area", "value": weakest["metric"], "detail": _format_percent_value(weakest["score"])})

    sections: List[Dict[str, Any]] = []
    if score_trend:
        _add_section(sections, {
            "id": "score_trend",
            "title": "Score Trend",
            "kind": "trend",
            "trend": score_trend,
        })

    answer_rows = []
    for response in responses:
        status = _answer_status(response)
        flags = [_flag_label(flag) for flag in response.get("answer_quality_flags") or []]
        problem_type = _answer_problem_type(response)
        needs_repair = bool(
            status != "Properly answered"
            or flags
            or problem_type
            or (
                response.get("score") is not None
                and float(response["score"]) < 70
            )
        )
        if not needs_repair:
            continue
        answer_rows.append({
            "question": _short_text(response.get("question"), 95),
            "type": _question_type_label(str(response.get("question_type") or ""), str(response.get("question") or ""), bool(response.get("is_followup"))),
            "topic": _human_label(response.get("topic") or "General"),
            "score": _format_percent_value(response.get("score")),
            "status": status,
            "issue": problem_type or (flags[0] if flags else ""),
            "missing_point": _short_text(response.get("feedback") or (", ".join(flags) if flags else ""), 120),
            "evidence_id": response.get("response_id"),
        })
    _add_section(sections, {
        "id": "answers_needing_work",
        "title": "Answers That Need Work",
        "kind": "table",
        "columns": [
            {"key": "question", "label": "Question"},
            {"key": "type", "label": "Type"},
            {"key": "topic", "label": "Topic"},
            {"key": "score", "label": "Score"},
            {"key": "status", "label": "Status"},
            {"key": "issue", "label": "Issue"},
        ],
        "rows": answer_rows,
    })

    question_groups: Dict[str, List[float]] = defaultdict(list)
    for response in scored_responses:
        label = _question_type_label(str(response.get("question_type") or ""), str(response.get("question") or ""), bool(response.get("is_followup")))
        question_groups[label].append(float(response["score"]))
    _add_section(sections, {
        "id": "question_type_performance",
        "title": "Question Type Performance",
        "kind": "score_rows",
        "rows": [
            {"label": label, "score": _nullable_avg(scores), "detail": f"{len(scores)} answer{'s' if len(scores) != 1 else ''}"}
            for label, scores in sorted(question_groups.items())
        ],
    })

    weak_rows = []
    for response in scored_responses:
        if float(response["score"]) >= 65:
            continue
        flags = [_flag_label(flag) for flag in response.get("answer_quality_flags") or []]
        weak_rows.append({
            "question": _short_text(response.get("question"), 90),
            "concept": _human_label(response.get("topic") or "General"),
            "problem": _answer_problem_type(response) or (flags[0] if flags else "Low answer score"),
            "missing_point": _short_text(response.get("feedback") or (", ".join(flags) if flags else ""), 140),
            "score": _format_percent_value(response.get("score")),
        })
    _add_section(sections, {
        "id": "weak_questions",
        "title": "Weak Questions and Concepts",
        "kind": "table",
        "columns": [
            {"key": "question", "label": "Question"},
            {"key": "concept", "label": "Concept"},
            {"key": "problem", "label": "Problem"},
            {"key": "missing_point", "label": "Missing point"},
            {"key": "score", "label": "Score"},
        ],
        "rows": weak_rows,
    })

    repeated_counts: Counter[str] = Counter()
    repeated_examples: Dict[str, str] = {}
    for response in responses:
        for flag in response.get("answer_quality_flags") or []:
            label = _flag_label(flag)
            repeated_counts.update([label])
            repeated_examples.setdefault(label, _short_text(response.get("question"), 90))
    repeated_rows = [
        {"mistake": label, "count": count, "example": repeated_examples.get(label, "")}
        for label, count in repeated_counts.most_common()
        if count >= 2
    ]
    _add_section(sections, {
        "id": "repeated_mistakes",
        "title": "Repeated Interview Mistakes",
        "kind": "table",
        "columns": [
            {"key": "mistake", "label": "Mistake"},
            {"key": "count", "label": "Times seen"},
            {"key": "example", "label": "Example question"},
        ],
        "rows": repeated_rows,
    })

    followups = [item for item in scored_responses if item.get("is_followup")]
    mains = [item for item in scored_responses if not item.get("is_followup")]
    if followups:
        main_avg = _nullable_avg([float(item["score"]) for item in mains])
        followup_avg = _nullable_avg([float(item["score"]) for item in followups])
        metrics = [
            {"label": "Main answers", "value": _format_percent_value(main_avg), "raw_value": main_avg},
            {"label": "Follow-ups", "value": _format_percent_value(followup_avg), "raw_value": followup_avg},
        ]
        if main_avg is not None and followup_avg is not None:
            drop = round(main_avg - followup_avg, 1)
            metrics.append({"label": "Change under follow-up", "value": f"{drop:+g} pts", "raw_value": drop})
        _add_section(sections, {
            "id": "followup_handling",
            "title": "Follow-up Handling",
            "kind": "metrics",
            "metrics": [item for item in metrics if item.get("value")],
        })

    project_rows = [
        row for row in answer_rows
        if row.get("type") == "Project" or "project" in str(row.get("question", "")).lower()
    ]
    _add_section(sections, {
        "id": "project_explanation",
        "title": "Project Explanation",
        "kind": "table",
        "columns": [
            {"key": "question", "label": "Question"},
            {"key": "status", "label": "Status"},
            {"key": "issue", "label": "Missing signal"},
            {"key": "score", "label": "Score"},
        ],
        "rows": project_rows,
    })

    next_focus = None
    if weak_rows:
        first = weak_rows[0]
        next_focus = {
            "title": first["problem"],
            "description": first["missing_point"] or f"Improve {first['concept']} answers first.",
            "source": first["question"],
        }
    elif dimensions:
        weakest = min(dimensions, key=lambda item: item["score"])
        next_focus = {
            "title": weakest["metric"],
            "description": f"Raise {weakest['metric'].lower()} on the next full mock interview.",
        }

    dimension_by_label = {str(item["metric"]).lower(): item["score"] for item in dimensions}
    pattern_sessions: Dict[str, set[str]] = defaultdict(set)
    pattern_counts: Counter[str] = Counter()
    fallback_flag_labels = {
        "too_short": "Incomplete answers",
        "no_response": "Incomplete answers",
        "vague": "Vague explanations",
        "off_topic": "Rambling or indirect answers",
        "low_lexical_relevance": "Rambling or indirect answers",
        "no_evidence": "Missing evidence",
        "insufficient_evidence": "Missing evidence",
    }
    for response in responses:
        session_id = str(response.get("interview_id") or "unknown")
        for flag in response.get("answer_quality_flags") or []:
            label = fallback_flag_labels.get(str(flag).lower())
            if label:
                pattern_sessions[label].add(session_id)
                pattern_counts.update([label])
    patterns = [
        {
            "label": label,
            "detail": "This pattern is based on persisted answer assessments.",
            "count": int(pattern_counts[label]),
            "session_count": len(sessions),
            "recurring": len(sessions) >= 2,
        }
        for label, sessions in sorted(pattern_sessions.items(), key=lambda item: (-len(item[1]), item[0]))
    ][:5]
    project_responses = [
        response for response in responses
        if _question_type_label(
            str(response.get("question_type") or ""),
            str(response.get("question") or ""),
            bool(response.get("is_followup")),
        ) == "Project"
        and response.get("score") is not None
    ]
    project_scores = [float(response["score"]) for response in project_responses]
    strengths = [
        f"{item['metric']} is a current strength at {round(float(item['score'])):g}%."
        for item in sorted(dimensions, key=lambda item: -float(item["score"]))
        if float(item["score"]) >= 75 and len(interviews) >= 2
    ][:4]
    payload = _dynamic_payload("interview", bool(responses), overview, sections, next_focus)
    payload["trend"] = score_trend
    payload["round_history"] = round_history
    payload["overall_score"] = latest_score
    payload["has_evidence"] = bool(responses)
    payload["has_official_score"] = latest_score is not None
    payload["score_state"] = "ready" if latest_score is not None else "insufficient"
    payload["source_kind"] = "recorded_evidence"
    payload["included_in_trend"] = False
    payload["page_summary"] = {
        "communication": {
            "fluency_clarity": {
                "score": _performance_number(dimension_by_label.get("clarity")),
                "detail": "Based on persisted transcript clarity assessments.",
            },
            "confidence": {
                "score": None,
                "detail": "Voice delivery analysis is still being prepared.",
            },
            "patterns": patterns,
        },
        "technical": {
            "trend": [],
            "knowledge_gaps": [],
            "latest_score": _performance_number(dimension_by_label.get("correctness")),
        },
        "project_explanation": {
            "score": round(sum(project_scores) / len(project_scores), 1) if project_scores else None,
            "answer_count": len(project_scores),
            "session_count": len({response.get("interview_id") for response in project_responses}),
            "breakdown": [],
            "detail": (
                f"Based on {len(project_scores)} persisted project answer{'s' if len(project_scores) != 1 else ''}."
                if project_scores else "No project explanation has enough scored evidence yet."
            ),
        },
        "insights": {
            "recurring_mistakes": [item for item in patterns if item.get("recurring")],
            "improving": [],
            "declining": [],
            "ai_insights": [
                _short_text(next_focus.get("description"), 180)
                for _ in [0]
                if next_focus and next_focus.get("description")
            ],
        },
        "strengths": strengths,
    }
    return payload


def _metadata_values(metadata: Dict[str, Any], keys: List[str]) -> List[str]:
    values: List[str] = []
    for key in keys:
        raw = metadata.get(key)
        if raw is None:
            continue
        if isinstance(raw, list):
            values.extend(str(item) for item in raw if str(item).strip())
        elif isinstance(raw, dict):
            values.extend(str(item) for item in raw.values() if str(item).strip())
        elif str(raw).strip():
            values.append(str(raw))
    return values


def _attempted_topics(prompt: str, metadata: Dict[str, Any]) -> List[str]:
    explicit = _metadata_values(metadata, ["topics", "topic", "subtopics", "tags", "algorithm_pattern"])
    topics: List[str] = []
    for value in explicit:
        label = _human_label(value)
        if label and label not in topics:
            topics.append(label)
    if topics:
        return topics[:4]
    text = f"{prompt} {json.dumps(metadata, default=str)}".lower()
    signals = [
        ("Dynamic Programming", ("dynamic programming", " dp ", "memo", "tabulation")),
        ("Sliding Window", ("sliding window", "window")),
        ("Two Pointers", ("two pointer", "left pointer", "right pointer")),
        ("Hashing", ("hash", "map", "set", "frequency")),
        ("Graphs", ("graph", "edge", "vertex")),
        ("Trees", ("tree", "root", "binary")),
        ("BFS", ("bfs", "queue")),
        ("DFS", ("dfs", "recursion", "recursive")),
        ("Arrays", ("array", "list", "subarray")),
        ("Strings", ("string", "substring", "character")),
    ]
    for label, needles in signals:
        if any(needle in text for needle in needles) and label not in topics:
            topics.append(label)
    return topics[:4]


def _expected_approach(metadata: Dict[str, Any]) -> Optional[str]:
    values = _metadata_values(metadata, ["better_approach", "accepted_approach", "accepted_approaches", "expected_approach", "algorithm_pattern", "pattern"])
    return _human_label(values[0]) if values else None


def _expected_complexity(metadata: Dict[str, Any], key_prefix: str) -> Optional[str]:
    values = _metadata_values(metadata, [
        f"expected_{key_prefix}_complexity",
        f"{key_prefix}_complexity",
        f"optimal_{key_prefix}_complexity",
    ])
    return values[0] if values else None


def _detect_code_approach(code: str) -> Optional[str]:
    if not code.strip():
        return None
    lower = code.lower()
    if any(token in lower for token in ("defaultdict", "hashmap", "map<", "unordered_map", "dict(", "set(")):
        return "Hashing"
    if any(token in lower for token in ("deque", "queue", "popleft", ".shift(")):
        return "BFS"
    if re.search(r"\bdfs\b|\brecurs", lower):
        return "DFS / Recursion"
    if re.search(r"\bdp\b|memo|lru_cache|tabulation", lower):
        return "Dynamic Programming"
    if re.search(r"\bleft\b.*\bright\b|\bright\b.*\bleft\b", lower, re.S):
        return "Two Pointers"
    if "window" in lower:
        return "Sliding Window"
    if ".sort(" in lower or "sorted(" in lower:
        return "Sorting"
    if len(re.findall(r"\bfor\b", lower)) >= 2 or len(re.findall(r"\bwhile\b", lower)) >= 2:
        return "Brute Force"
    if re.search(r"\bfor\b|\bwhile\b", lower):
        return "Linear Scan"
    return None


def _estimate_complexity(code: str, approach: Optional[str]) -> Optional[str]:
    if not code.strip() and not approach:
        return None
    label = str(approach or "").lower()
    if "brute" in label:
        return "O(n²)"
    if "sorting" in label:
        return "O(n log n)"
    if "bfs" in label or "dfs" in label:
        return "O(V + E)"
    if any(token in label for token in ("hash", "two pointers", "sliding", "linear")):
        return "O(n)"
    if "dynamic" in label:
        return "O(n)"
    lower = code.lower()
    if ".sort(" in lower or "sorted(" in lower:
        return "O(n log n)"
    if len(re.findall(r"\bfor\b", lower)) >= 2:
        return "O(n²)"
    if re.search(r"\bfor\b|\bwhile\b", lower):
        return "O(n)"
    return None


def _complexity_rank(value: Optional[str]) -> int:
    text = str(value or "").lower().replace(" ", "")
    if not text:
        return 0
    if "n²" in text or "n^2" in text or "n*n" in text:
        return 4
    if "nlogn" in text:
        return 3
    if "v+e" in text or "n" in text:
        return 2
    if "1" in text:
        return 1
    return 0


def _correctness_status(visible_passed: int, visible_total: int, hidden_passed: int, hidden_total: int) -> Optional[Dict[str, Any]]:
    total = visible_total + hidden_total
    if total <= 0:
        return None
    passed = visible_passed + hidden_passed
    status_label = "Correct" if passed == total else "Partially correct" if passed > 0 else "Incorrect"
    return {
        "status": status_label,
        "score": round((passed / total) * 100, 1),
        "tests": f"{passed}/{total}",
        "visible": f"{visible_passed}/{visible_total}" if visible_total else "",
        "hidden": f"{hidden_passed}/{hidden_total}" if hidden_total else "",
    }


def _failure_reason(
    attempted: bool,
    submitted: bool,
    correctness: Optional[Dict[str, Any]],
    latest_run: Dict[str, Any],
    user_approach: Optional[str],
    better_approach: Optional[str],
    user_complexity: Optional[str],
    expected_complexity: Optional[str],
) -> Optional[str]:
    if not attempted:
        return None
    validation = latest_run.get("hidden_validation_result") or {}
    validation_status = str(validation.get("status") or "").lower()
    run_total = int(validation.get("total_count") or 0)
    run_passed = int(validation.get("pass_count") or 0)
    if validation_status == "failed" or (latest_run.get("stderr") and not run_total):
        return "Runtime error"
    if run_total and run_passed < run_total:
        visible_total = int(validation.get("visible_total") or 0)
        visible_passed = int(validation.get("visible_passed") or 0)
        hidden_total = int(validation.get("hidden_total") or 0)
        hidden_passed = int(validation.get("hidden_passed") or 0)
        if visible_total and visible_passed < visible_total:
            return "Failed visible tests"
        if hidden_total and hidden_passed < hidden_total:
            return "Missed edge case"
        return "Failed tests"
    if not submitted:
        return "Incomplete implementation"
    if correctness and correctness.get("status") == "Correct":
        if _complexity_rank(user_complexity) > _complexity_rank(expected_complexity) > 0:
            return "Solved but inefficient"
        return None
    if correctness and correctness.get("visible") and correctness.get("hidden"):
        visible_ok = correctness["visible"].split("/")[0] == correctness["visible"].split("/")[1]
        hidden_ok = correctness["hidden"].split("/")[0] == correctness["hidden"].split("/")[1]
        if visible_ok and not hidden_ok:
            return "Missed edge case"
    if better_approach and user_approach and better_approach.lower() not in user_approach.lower():
        if _complexity_rank(user_complexity) > _complexity_rank(expected_complexity) > 0:
            return "Inefficient complexity"
        return "Wrong approach"
    if better_approach and user_approach and better_approach.lower() in user_approach.lower():
        return "Correct approach but wrong implementation"
    return "Incorrect condition"


def _concept_application_label(user_approach: Optional[str], better_approach: Optional[str], correctness: Optional[Dict[str, Any]], failure_reason: Optional[str]) -> Optional[str]:
    if not user_approach and not better_approach:
        return None
    if failure_reason == "Wrong approach":
        return "Knows code syntax, but missed the required pattern"
    if failure_reason == "Inefficient complexity":
        return "Solved with an inefficient approach"
    if failure_reason == "Correct approach but wrong implementation":
        return "Selected the right concept but implementation failed"
    if failure_reason == "Missed edge case":
        return "Correct direction, weak edge-case handling"
    if correctness and correctness.get("status") == "Correct":
        return "Applied the expected pattern successfully"
    return None


def _technical_performance_payload(cursor, user_id: str) -> Dict[str, Any]:
    cursor.execute(
        """
        SELECT tir.round_id, tir.interview_id, tir.round_type, tir.prompt, tir.metadata,
               tir.status, tir.created_at, tir.completed_at,
               COUNT(DISTINCT tre.run_id) AS run_count,
               COUNT(DISTINCT tcs.snapshot_id) AS snapshot_count,
               COUNT(DISTINCT ts.submission_id) AS submission_count
        FROM TechnicalInterviewRounds tir
        JOIN Interviews interview
          ON interview.interview_id = tir.interview_id
         AND interview.user_id = tir.user_id
        LEFT JOIN TechnicalRunEvents tre ON tre.round_id = tir.round_id
        LEFT JOIN TechnicalCodeSnapshots tcs ON tcs.round_id = tir.round_id
        LEFT JOIN TechnicalSubmissions ts ON ts.round_id = tir.round_id
        WHERE tir.user_id = %s
          AND interview.attempt_status = 'completed'
        GROUP BY tir.round_id, tir.interview_id, tir.round_type, tir.prompt,
                 tir.metadata, tir.status, tir.created_at, tir.completed_at
        ORDER BY tir.created_at ASC
        """,
        (user_id,),
    )
    rounds = cursor.fetchall()
    if not rounds:
        return _dynamic_payload("technical", False, [], [])

    round_ids = [row[0] for row in rounds]
    latest_submissions: Dict[str, Dict[str, Any]] = {}
    latest_runs: Dict[str, Dict[str, Any]] = {}
    reasoning_by_round: Dict[str, List[Dict[str, Any]]] = defaultdict(list)

    cursor.execute(
        """
        SELECT DISTINCT ON (round_id)
               round_id, visible_passed, visible_total, hidden_passed, hidden_total,
               source_code, result_json, runtime_ms, memory_kb, created_at,
               source_code_encrypted
        FROM TechnicalSubmissions
        WHERE user_id = %s AND round_id = ANY(%s)
        ORDER BY round_id, created_at DESC
        """,
        (user_id, round_ids),
    )
    for row in cursor.fetchall():
        latest_submissions[row[0]] = {
            "visible_passed": int(row[1] or 0),
            "visible_total": int(row[2] or 0),
            "hidden_passed": int(row[3] or 0),
            "hidden_total": int(row[4] or 0),
            "source_code": _decrypt_text_blob(row[10], row[5]),
            "result_json": _json_object(row[6]),
            "runtime_ms": row[7],
            "memory_kb": row[8],
            "created_at": row[9],
        }

    cursor.execute(
        """
        SELECT DISTINCT ON (round_id)
               round_id, exit_code, error_signature, stderr, source_code,
               hidden_validation_result, created_at, source_code_encrypted
        FROM TechnicalRunEvents
        WHERE user_id = %s AND round_id = ANY(%s)
        ORDER BY round_id, created_at DESC
        """,
        (user_id, round_ids),
    )
    for row in cursor.fetchall():
        latest_runs[row[0]] = {
            "exit_code": row[1],
            "error_signature": row[2],
            "stderr": row[3],
            "source_code": _decrypt_text_blob(row[7], row[4]),
            "hidden_validation_result": _json_object(row[5]),
            "created_at": row[6],
        }

    cursor.execute(
        """
        SELECT round_id, evidence_type, content, payload,
               content_encrypted, created_at
        FROM TechnicalReasoningEvidence
        WHERE user_id = %s AND round_id = ANY(%s)
        ORDER BY created_at ASC
        """,
        (user_id, round_ids),
    )
    for row in cursor.fetchall():
        decrypted_payload = _encrypted_json_object(row[4]) if row[4] else {}
        decrypted_content = str(
            decrypted_payload.get("content")
            or decrypted_payload.get("text")
            or decrypted_payload.get("transcript")
            or decrypted_payload.get("question")
            or decrypted_payload.get("approach")
            or ""
        ).strip()
        if not decrypted_content and row[2] and row[2] != "[encrypted]":
            decrypted_content = str(row[2]).strip()
        reasoning_by_round[row[0]].append({
            "type": row[1],
            "content": decrypted_content,
            "payload": _json_object(row[3]),
            "created_at": row[5],
        })

    problem_rows: List[Dict[str, Any]] = []
    scores: List[Dict[str, Any]] = []
    topic_totals: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"attempts": 0, "solved": 0, "scores": [], "issues": Counter(), "sessions": set()})
    failure_counts: Counter[str] = Counter()
    approach_counts: Counter[str] = Counter()
    hidden_failure_tags: Counter[str] = Counter()
    run_counts: List[float] = []
    time_per_problem: List[float] = []
    session_rounds: Dict[str, Dict[str, Any]] = defaultdict(lambda: {
        "total": 0,
        "attempted": 0,
        "submitted": 0,
        "solved": 0,
        "created_at": None,
        "completed_at": None,
    })
    session_scores: Dict[str, List[float]] = defaultdict(list)
    attempted_count = 0
    submitted_count = 0
    solved_count = 0

    for row in rounds:
        round_id, interview_id, round_type, prompt, raw_metadata, status_value, created_at, completed_at, run_count, snapshot_count, submission_count = row
        session = session_rounds[str(interview_id)]
        session["total"] += 1
        session["created_at"] = min(
            [value for value in (session.get("created_at"), created_at) if value is not None],
            default=None,
        )
        session["completed_at"] = max(
            [value for value in (session.get("completed_at"), completed_at) if value is not None],
            default=None,
        )
        metadata = _json_object(raw_metadata)
        submission = latest_submissions.get(round_id, {})
        latest_run = latest_runs.get(round_id, {})
        code = str(submission.get("source_code") or latest_run.get("source_code") or "")
        attempted = bool(int(run_count or 0) or int(snapshot_count or 0) or int(submission_count or 0))
        submitted = bool(int(submission_count or 0))
        if not attempted:
            continue
        attempted_count += 1
        session["attempted"] += 1
        if submitted:
            submitted_count += 1
            session["submitted"] += 1
        if run_count:
            run_counts.append(float(run_count))
        if created_at and completed_at:
            time_per_problem.append(max(0.0, (completed_at - created_at).total_seconds() / 60))

        submission_correctness = _correctness_status(
            int(submission.get("visible_passed") or 0),
            int(submission.get("visible_total") or 0),
            int(submission.get("hidden_passed") or 0),
            int(submission.get("hidden_total") or 0),
        )
        validation = latest_run.get("hidden_validation_result") or {}
        run_correctness = _correctness_status(
            int(validation.get("visible_passed") or 0),
            int(validation.get("visible_total") or 0),
            int(validation.get("hidden_passed") or 0),
            int(validation.get("hidden_total") or 0),
        )
        correctness = submission_correctness or run_correctness
        correctness_evidence = "Final submit" if submission_correctness else "Latest run" if run_correctness else ""
        if submission_correctness:
            scores.append({"label": created_at.isoformat() if created_at else None, "score": correctness["score"], "round_id": round_id, "interview_id": interview_id})
            session_scores[str(interview_id)].append(float(correctness["score"]))
            if submitted and correctness["status"] == "Correct":
                solved_count += 1
                session["solved"] += 1

        user_approach = _detect_code_approach(code)
        better_approach = _expected_approach(metadata)
        user_complexity = _estimate_complexity(code, user_approach)
        expected_time = _expected_complexity(metadata, "time")
        expected_space = _expected_complexity(metadata, "space")
        failure_reason = _failure_reason(attempted, submitted, correctness, latest_run, user_approach, better_approach, user_complexity, expected_time)
        if failure_reason:
            failure_counts.update([failure_reason])
        if user_approach:
            approach_counts.update([user_approach])
        for tag in _json_list(validation.get("hidden_failure_tags")):
            hidden_failure_tags.update([_human_label(tag)])

        topics = _attempted_topics(str(prompt or ""), metadata)
        for topic in topics:
            topic_totals[topic]["attempts"] += 1
            topic_totals[topic]["sessions"].add(str(interview_id))
            if correctness:
                topic_totals[topic]["scores"].append(correctness["score"])
                if submitted and correctness["status"] == "Correct":
                    topic_totals[topic]["solved"] += 1
            if failure_reason:
                topic_totals[topic]["issues"].update([failure_reason])

        concept_label = _concept_application_label(user_approach, better_approach, correctness, failure_reason)
        reasoning = reasoning_by_round.get(round_id, [])
        understanding = None
        if reasoning:
            hint_count = sum(1 for item in reasoning if item["type"] == "hint_requested")
            transcript_words = sum(len(str(item.get("content") or "").split()) for item in reasoning if item["type"] == "technical_transcript")
            if transcript_words >= 12 and hint_count == 0:
                understanding = "Explained direction before relying on hints"
            elif transcript_words >= 12:
                understanding = "Explained approach, but used hints"
            elif hint_count:
                understanding = "Needed hint support before approach evidence was clear"

        problem_rows.append({
            "interview_id": interview_id,
            "date": _performance_iso(completed_at or created_at),
            "round_id": round_id,
            "problem": _short_text(metadata.get("title") or prompt or round_type, 90),
            "topics": ", ".join(topics),
            "user_approach": user_approach or "",
            "better_approach": better_approach or "",
            "user_complexity": user_complexity or "",
            "expected_complexity": expected_time or "",
            "correctness": correctness["status"] if correctness else "",
            "evidence": correctness_evidence,
            "tests": correctness["tests"] if correctness else "",
            "hidden_tests": correctness["hidden"] if correctness and correctness.get("hidden") else "",
            "failure_reason": failure_reason or "",
            "concept_application": concept_label or "",
            "problem_understanding": understanding or "",
            "evidence_id": round_id,
            "run_count": int(run_count or 0),
        })

    if attempted_count == 0:
        return _dynamic_payload("technical", False, [], [])

    round_history = [
        {
            "interview_id": interview_id,
            "mode": "technical",
            "completed_at": _performance_iso(session.get("completed_at") or session.get("created_at")),
            "score": _nullable_avg(session_scores.get(interview_id) or []),
            "duration_seconds": None,
            "score_state": "ready" if session_scores.get(interview_id) else "run_only" if session.get("attempted") else "insufficient",
            "source_kind": "recorded_evidence",
            "included_in_trend": bool(session_scores.get(interview_id)),
            "questions_completed": None,
            "questions_total": None,
            "problems_attempted": session.get("attempted"),
            "problems_total": session.get("total"),
            "problems_solved": session.get("solved"),
            "change": None,
            "key_result": f"{session.get('solved', 0)}/{session.get('total', 0)} solved",
        }
        for interview_id, session in session_rounds.items()
    ]

    overview: List[Dict[str, Any]] = [
        {"label": "Problems attempted", "value": str(attempted_count), "raw_value": attempted_count},
        {"label": "Problems solved", "value": str(solved_count), "raw_value": solved_count},
    ]
    if submitted_count:
        success_rate = round((solved_count / submitted_count) * 100, 1)
        overview.append({"label": "Submit success rate", "value": _format_percent_value(success_rate), "raw_value": success_rate})
    if len(scores) >= 2:
        delta = round(float(scores[-1]["score"]) - float(scores[0]["score"]), 1)
        overview.append({"label": "Score trend", "value": f"{delta:+g} pts", "raw_value": delta})

    sections: List[Dict[str, Any]] = []
    if scores:
        _add_section(sections, {
            "id": "coding_score_trend",
            "title": "Coding Score Trend",
            "kind": "trend",
            "trend": scores[-5:],
        })

    topic_rows = []
    for topic, values in sorted(topic_totals.items()):
        attempts = values["attempts"]
        avg_score = _nullable_avg([float(score) for score in values["scores"]])
        current_level = ""
        if avg_score is not None:
            current_level = "Strong" if avg_score >= 80 else "Needs work"
        issue = values["issues"].most_common(1)[0][0] if values["issues"] else ""
        topic_rows.append({
            "topic": topic,
            "attempts": attempts,
            "round_count": len(values["sessions"]),
            "solved": values["solved"],
            "score": _format_percent_value(avg_score),
            "current_level": current_level,
            "main_issue": issue,
        })
    _add_section(sections, {
        "id": "topic_performance",
        "title": "Topic and Subtopic Performance",
        "kind": "table",
        "columns": [
            {"key": "topic", "label": "Topic"},
            {"key": "attempts", "label": "Attempts"},
            {"key": "solved", "label": "Solved"},
            {"key": "score", "label": "Avg score"},
            {"key": "current_level", "label": "Current level"},
            {"key": "main_issue", "label": "Where stuck"},
        ],
        "rows": topic_rows,
    })

    _add_section(sections, {
        "id": "problem_analysis",
        "title": "Problem Analysis",
        "kind": "table",
        "columns": [
            {"key": "problem", "label": "Problem"},
            {"key": "topics", "label": "Topic"},
            {"key": "user_approach", "label": "User approach"},
            {"key": "better_approach", "label": "Better approach"},
            {"key": "user_complexity", "label": "User complexity"},
            {"key": "expected_complexity", "label": "Expected"},
            {"key": "correctness", "label": "Correctness"},
            {"key": "evidence", "label": "Evidence"},
            {"key": "tests", "label": "Tests"},
            {"key": "failure_reason", "label": "Failure reason"},
        ],
        "rows": problem_rows,
    })

    concept_rows = [
        {
            "problem": row["problem"],
            "diagnosis": row["concept_application"],
            "approach": row["user_approach"],
            "expected": row["better_approach"],
        }
        for row in problem_rows
        if row.get("concept_application")
    ]
    _add_section(sections, {
        "id": "concept_application",
        "title": "Concept Knowledge vs Concept Application",
        "kind": "table",
        "columns": [
            {"key": "problem", "label": "Problem"},
            {"key": "diagnosis", "label": "Diagnosis"},
            {"key": "approach", "label": "Used"},
            {"key": "expected", "label": "Needed"},
        ],
        "rows": concept_rows,
    })

    understanding_rows = [
        {"problem": row["problem"], "evidence": row["problem_understanding"]}
        for row in problem_rows
        if row.get("problem_understanding")
    ]
    _add_section(sections, {
        "id": "problem_understanding",
        "title": "Problem Understanding",
        "kind": "table",
        "columns": [
            {"key": "problem", "label": "Problem"},
            {"key": "evidence", "label": "Evidence-based reading"},
        ],
        "rows": understanding_rows,
    })

    repeated_rows = [
        {"pattern": label, "count": count}
        for label, count in failure_counts.most_common()
        if count >= 2
    ]
    _add_section(sections, {
        "id": "repeated_coding_patterns",
        "title": "Repeated Coding Problems",
        "kind": "table",
        "columns": [
            {"key": "pattern", "label": "Pattern"},
            {"key": "count", "label": "Times seen"},
        ],
        "rows": repeated_rows,
    })

    if hidden_failure_tags:
        _add_section(sections, {
            "id": "hidden_test_failures",
            "title": "Hidden Test Failure Tags",
            "kind": "table",
            "columns": [
                {"key": "failure", "label": "Failure"},
                {"key": "count", "label": "Times seen"},
            ],
            "rows": [{"failure": label, "count": count} for label, count in hidden_failure_tags.most_common()],
        })

    behavior_metrics = []
    avg_runs = _nullable_avg(run_counts)
    avg_minutes = _nullable_avg(time_per_problem)
    if avg_runs is not None:
        behavior_metrics.append({"label": "Average runs per attempted problem", "value": _format_number_value(avg_runs), "raw_value": avg_runs})
    if avg_minutes is not None:
        behavior_metrics.append({"label": "Average time per attempted problem", "value": _format_number_value(avg_minutes, " min"), "raw_value": avg_minutes})
    if approach_counts:
        behavior_metrics.append({"label": "Most used approach", "value": approach_counts.most_common(1)[0][0]})
    _add_section(sections, {"id": "coding_progress", "title": "Coding Progress", "kind": "metrics", "metrics": behavior_metrics})

    next_focus = None
    if failure_counts:
        issue = failure_counts.most_common(1)[0][0]
        next_focus = {
            "title": issue,
            "description": "This is the highest-impact unresolved coding weakness from your attempted problems.",
        }
    elif topic_rows:
        weak_topic = min(
            [row for row in topic_rows if row.get("score")],
            key=lambda row: float(str(row["score"]).rstrip("%")),
            default=None,
        )
        if weak_topic:
            next_focus = {
                "title": weak_topic["topic"],
                "description": weak_topic.get("main_issue") or "Improve this attempted topic next.",
            }

    payload = _dynamic_payload("technical", True, overview, sections, next_focus)
    payload["trend"] = scores[-5:]
    payload["round_history"] = sorted(round_history, key=lambda item: item.get("completed_at") or "", reverse=True)
    payload["overall_score"] = scores[-1]["score"] if scores else None
    payload["has_evidence"] = True
    payload["has_official_score"] = bool(scores)
    payload["score_state"] = (
        "ready"
        if scores
        else "run_only"
        if submitted_count == 0
        else "insufficient"
    )
    payload["source_kind"] = "recorded_evidence"
    payload["included_in_trend"] = False
    payload["page_summary"] = {
        "communication": {},
        "technical": {
            "trend": scores[-5:],
            "knowledge_gaps": [],
            "latest_score": scores[-1]["score"] if scores else None,
        },
        "project_explanation": {},
        "insights": {
            "recurring_mistakes": [],
            "improving": [],
            "declining": [],
            "ai_insights": [
                _short_text(next_focus.get("description"), 180)
                for _ in [0]
                if next_focus and next_focus.get("description")
            ],
        },
        "strengths": [],
    }
    payload["analytics"] = _recorded_technical_analytics(
        problem_rows=problem_rows,
        topic_rows=topic_rows,
        round_history=round_history,
        attempted_count=attempted_count,
        total_problems=sum(session.get("total", 0) for session in session_rounds.values()),
        submitted_count=submitted_count,
        solved_count=solved_count,
        run_counts=run_counts,
    )
    return payload


def _recorded_technical_analytics(
    *,
    problem_rows: List[Dict[str, Any]],
    topic_rows: List[Dict[str, Any]],
    round_history: List[Dict[str, Any]],
    attempted_count: int,
    total_problems: int,
    submitted_count: int,
    solved_count: int,
    run_counts: List[float],
) -> Dict[str, Any]:
    """Expose saved coding evidence without treating drafts as scored work."""
    submission_problems: List[Dict[str, Any]] = []
    failure_buckets: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {"count": 0, "sessions": set(), "evidence": []}
    )
    for row in problem_rows:
        interview_id = row.get("interview_id")
        evidence = {
            "interview_id": interview_id,
            "date": row.get("date"),
            "problem": row.get("problem"),
            "round_id": row.get("round_id"),
            "issue": row.get("failure_reason") or "No final submission",
        }
        if row.get("failure_reason"):
            bucket = failure_buckets[str(row["failure_reason"])]
            bucket["count"] += 1
            bucket["sessions"].add(str(interview_id or ""))
            bucket["evidence"].append(evidence)
        if row.get("evidence") == "Final submit":
            continue
        submission_problems.append({
            "problem": row.get("problem"),
            "interview_id": interview_id,
            "date": row.get("date"),
            "round_id": row.get("round_id"),
            "count": 1,
            "round_count": 1,
            "issue": "No final submission",
            "run_count": row.get("run_count"),
            "evidence": [evidence],
        })

    time_metrics: List[Dict[str, Any]] = []
    average_runs = _nullable_avg(run_counts)
    if average_runs is not None and average_runs < 2:
        time_metrics.append({
            "label": "Runs code too few times before submitting",
            "value": average_runs,
            "display": _format_number_value(average_runs, " runs/problem"),
            "count": len(run_counts),
            "explanation": "Saved coding evidence shows fewer than two validation runs per attempted problem on average.",
        })

    topics = [
        {
            "label": row.get("topic"),
            "problems_attempted": int(row.get("attempts") or 0),
            "problems_solved": int(row.get("solved") or 0),
            "average_score": _nullable_avg([float(score) for score in row.get("scores") or []]),
            "round_count": int(row.get("round_count") or 0),
            "common_issue": row.get("main_issue") or None,
            "evidence": [],
        }
        for row in topic_rows
        if row.get("topic")
    ]
    patterns = [
        {
            "label": label,
            "count": bucket["count"],
            "round_count": len({item for item in bucket["sessions"] if item}),
            "evidence": bucket["evidence"][:12],
        }
        for label, bucket in sorted(
            failure_buckets.items(), key=lambda item: (-item[1]["count"], item[0])
        )
        if bucket["count"] >= 2 and len({item for item in bucket["sessions"] if item}) >= 2
    ]
    return {
        "summary": {
            "total_rounds": len(round_history),
            "average_score": None,
            "latest_score": None,
            "best_score": None,
            "recent_change": None,
            "average_duration_seconds": None,
            "trend": None,
            "problems_attempted": attempted_count,
            "problems_total": total_problems,
            "problems_solved": solved_count,
            "submission_rate": round(submitted_count / attempted_count * 100, 1) if attempted_count else None,
        },
        "skills": [],
        "topics": topics,
        "question_types": [],
        "patterns": patterns,
        "test_patterns": [],
        "behavior": [],
        "tests": [],
        "submission": {
            "problems_attempted": attempted_count,
            "problems_total": total_problems,
            "problems_submitted": submitted_count,
            "problems_solved": solved_count,
            "submission_rate": round(submitted_count / attempted_count * 100, 1) if attempted_count else None,
            "coded_not_submitted": len(submission_problems),
            "problems": submission_problems,
        },
        "time": time_metrics,
        "improvement": {"improving": [], "declining": [], "stable": []},
    }


def _merge_recorded_technical_analytics(
    canonical: Optional[Dict[str, Any]],
    recorded: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Keep canonical scores while adding persisted draft/submission evidence."""
    if not recorded or not recorded.get("has_data"):
        return canonical
    if not canonical:
        return recorded

    merged = dict(canonical)
    analytics = dict(canonical.get("analytics") or {})
    recorded_analytics = recorded.get("analytics") or {}
    for key in ("topics", "patterns", "test_patterns", "time", "time_patterns", "complexity"):
        if not analytics.get(key) and recorded_analytics.get(key):
            analytics[key] = recorded_analytics[key]

    canonical_submission = dict(analytics.get("submission") or {})
    recorded_submission = recorded_analytics.get("submission") or {}
    if recorded_submission:
        for key in (
            "problems_attempted",
            "problems_total",
            "problems_submitted",
            "problems_solved",
            "submission_rate",
        ):
            if recorded_submission.get(key) is not None:
                canonical_submission[key] = recorded_submission[key]
        existing_problems = list(canonical_submission.get("problems") or [])
        problems_by_key = {
            (
                item.get("interview_id"),
                item.get("round_id"),
                item.get("problem"),
            ): item
            for item in existing_problems
            if isinstance(item, dict)
        }
        for item in recorded_submission.get("problems") or []:
            if not isinstance(item, dict):
                continue
            key = (item.get("interview_id"), item.get("round_id"), item.get("problem"))
            if key not in problems_by_key:
                problems_by_key[key] = item
                continue
            existing = problems_by_key[key]
            if not existing.get("evidence") and item.get("evidence"):
                problems_by_key[key] = {**existing, "evidence": item["evidence"]}
        canonical_submission["problems"] = list(problems_by_key.values())
        canonical_submission["coded_not_submitted"] = max(
            int(canonical_submission.get("coded_not_submitted") or 0),
            int(recorded_submission.get("coded_not_submitted") or 0),
        )
        analytics["submission"] = canonical_submission

    merged["analytics"] = analytics
    if int((recorded_submission or {}).get("coded_not_submitted") or 0) > 0:
        merged["has_evidence"] = True
        merged["comparison_notice"] = (
            "Saved coding evidence is shown below. Technical scores remain unavailable until a final submission is captured."
        )
    return merged


def _legacy_performance_history(cursor: Any, user_id: str) -> List[Dict[str, Any]]:
    cursor.execute(
        """
        SELECT i.interview_id,
               CASE
                   WHEN LOWER(COALESCE(i.interview_type, '')) LIKE '%%technical%%'
                        OR EXISTS (
                            SELECT 1 FROM TechnicalInterviewRounds round
                            WHERE round.interview_id = i.interview_id
                        )
                   THEN 'technical'
                   ELSE 'interview'
               END AS mode,
               i.overall_score,
               COALESCE(i.completed_at, i.created_at) AS completed_at,
               i.interview_type,
               i.job_title,
               i.duration_seconds
        FROM Interviews i
        WHERE i.user_id = %s
          AND i.attempt_status = 'completed'
          AND i.overall_score > 0
          AND (i.report_json IS NOT NULL OR i.report_json_encrypted IS NOT NULL)
          AND NOT EXISTS (
              SELECT 1
              FROM SessionPerformanceAnalyses analysis
              WHERE analysis.interview_id = i.interview_id
                AND analysis.user_id = i.user_id
                AND analysis.schema_version = 'session-performance-v4'
                AND analysis.status = 'ready'
                AND analysis.is_current = TRUE
                AND analysis.analysis_json_encrypted IS NOT NULL
                AND analysis.evidence_index_encrypted IS NOT NULL
          )
        ORDER BY COALESCE(i.completed_at, i.created_at) DESC
        LIMIT 100
        """,
        (user_id,),
    )
    return [
        {
            "interview_id": str(row[0]),
            "mode": str(row[1]),
            "score": float(row[2]),
            "date": row[3].isoformat() if row[3] else None,
            "label": row[4] or ("Technical Round" if row[1] == "technical" else "Interview Round"),
            "role": row[5],
            "duration_seconds": int(row[6]) if row[6] is not None else None,
            "questions_completed": None,
            "questions_total": None,
            "problems_attempted": None,
            "problems_total": None,
            "problems_solved": None,
            "change": None,
            "key_result": None,
            "completed_at": row[3].isoformat() if row[3] else None,
            "source_kind": "legacy_report",
            "score_state": "legacy",
            "included_in_trend": False,
            "detail": "Saved from an older report without current evidence provenance.",
        }
        for row in cursor.fetchall() or []
    ]


def _performance_availability(cursor: Any, user_id: str) -> Dict[str, Any]:
    cursor.execute(
        """
        SELECT i.interview_id,
               CASE
                   WHEN LOWER(COALESCE(i.interview_type, '')) LIKE '%%technical%%'
                        OR EXISTS (
                            SELECT 1 FROM TechnicalInterviewRounds round
                            WHERE round.interview_id = i.interview_id
                        )
                   THEN 'technical'
                   ELSE 'interview'
               END AS mode,
               analysis.analysis_id,
               analysis.overall_score,
               analysis.evidence_status,
               job.status,
               job.retry_count,
               (i.report_json IS NOT NULL OR i.report_json_encrypted IS NOT NULL)
                   AND i.overall_score > 0 AS legacy_score_present,
               EXISTS (
                   SELECT 1 FROM TechnicalSubmissions submission
                   WHERE submission.interview_id = i.interview_id
                     AND submission.user_id = i.user_id
               ) AS final_submission_present,
               (
                   EXISTS (
                       SELECT 1 FROM TechnicalRunEvents event
                       JOIN TechnicalInterviewRounds round ON round.round_id = event.round_id
                       WHERE round.interview_id = i.interview_id
                         AND event.user_id = i.user_id
                   )
                   OR EXISTS (
                       SELECT 1 FROM TechnicalCodeSnapshots snapshot
                       WHERE snapshot.interview_id = i.interview_id
                         AND snapshot.user_id = i.user_id
                         AND snapshot.source_chars > 0
                   )
               ) AS run_or_draft_present,
               EXISTS (
                   SELECT 1 FROM InterviewResponses response
                   WHERE response.interview_id = i.interview_id
               ) AS response_present
        FROM Interviews i
        LEFT JOIN LATERAL (
            SELECT analysis_id, overall_score, evidence_status
            FROM SessionPerformanceAnalyses current_analysis
            WHERE current_analysis.interview_id = i.interview_id
              AND current_analysis.user_id = i.user_id
              AND current_analysis.schema_version = 'session-performance-v4'
              AND current_analysis.producer_version = %s
              AND current_analysis.is_current = TRUE
              AND current_analysis.status = 'ready'
              AND current_analysis.analysis_json_encrypted IS NOT NULL
              AND current_analysis.evidence_index_encrypted IS NOT NULL
            LIMIT 1
        ) analysis ON TRUE
        LEFT JOIN LATERAL (
            SELECT status, retry_count
            FROM AnalysisJobs latest_job
            WHERE latest_job.interview_id = i.interview_id
            ORDER BY latest_job.created_at DESC
            LIMIT 1
        ) job ON TRUE
        WHERE i.user_id = %s
          AND i.attempt_status = 'completed'
          AND i.status IN (
              'analysis_pending', 'analysis_running',
              'completed', 'partial', 'failed'
          )
        ORDER BY COALESCE(i.completed_at, i.created_at) DESC
        """,
        (ANALYSIS_STAGE_VERSION, user_id),
    )
    availability_rows = cursor.fetchall() or []
    cursor.execute(
        """
        SELECT EXISTS (
            SELECT 1 FROM WorkerHeartbeats
            WHERE worker_type = 'analysis'
              AND heartbeat_at >= NOW() - INTERVAL '30 seconds'
        )
        """
    )
    worker_available = bool((cursor.fetchone() or [False])[0])
    state_names = (
        "ready", "processing", "blocked", "failed",
        "insufficient", "run_only", "legacy", "missing",
    )
    by_mode: Dict[str, Dict[str, int]] = {
        mode: {"completed_count": 0, **{name: 0 for name in state_names}}
        for mode in ("interview", "technical")
    }
    sessions: List[Dict[str, Any]] = []
    missing_canonical_count = 0
    for row in availability_rows:
        mode = "technical" if str(row[1]) == "technical" else "interview"
        analysis_id = row[2]
        overall_score = row[3]
        evidence_status = str(row[4] or "")
        job_status = str(row[5] or "")
        legacy_score_present = bool(row[7])
        final_submission_present = bool(row[8])
        run_or_draft_present = bool(row[9])
        response_present = bool(row[10])
        if analysis_id:
            if overall_score is not None and evidence_status == "sufficient":
                state_name = "ready"
            elif evidence_status == "draft_or_run_only":
                state_name = "run_only"
            else:
                state_name = "insufficient"
        elif job_status in {"queued", "running"}:
            state_name = "processing" if worker_available else "blocked"
        elif job_status == "failed":
            state_name = "failed"
        elif mode == "technical" and run_or_draft_present and not final_submission_present:
            state_name = "run_only"
        elif legacy_score_present:
            state_name = "legacy"
        elif response_present or final_submission_present:
            state_name = "missing"
        else:
            state_name = "insufficient"
        if not analysis_id:
            missing_canonical_count += 1
        by_mode[mode]["completed_count"] += 1
        by_mode[mode][state_name] += 1
        sessions.append({
            "interview_id": str(row[0]),
            "mode": mode,
            "score_state": state_name,
            "analysis_id": str(analysis_id) if analysis_id else None,
            "job_status": job_status or None,
            "retry_count": int(row[6] or 0),
            "has_evidence": bool(
                response_present or final_submission_present or run_or_draft_present
            ),
            "has_official_score": state_name == "ready",
        })
    return {
        "completed_count": len(availability_rows),
        "missing_canonical_count": missing_canonical_count,
        "pending_count": sum(
            1 for item in sessions
            if item["score_state"] in {"processing", "blocked"}
        ),
        "blocked_count": sum(
            1 for item in sessions if item["score_state"] == "blocked"
        ),
        "failed_count": sum(
            1 for item in sessions if item["score_state"] == "failed"
        ),
        "worker_available": worker_available,
        "processing_sla_minutes": 15,
        "by_mode": by_mode,
        "sessions": sessions,
    }


def _performance_round_history(
    interview_payload: Optional[Dict[str, Any]],
    technical_payload: Optional[Dict[str, Any]],
    legacy_history: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for mode, payload in (("interview", interview_payload), ("technical", technical_payload)):
        for item in (payload or {}).get("round_history") or []:
            if isinstance(item, dict):
                items.append({**item, "mode": mode})
        if not (payload or {}).get("round_history"):
            for point in (payload or {}).get("trend") or []:
                if not isinstance(point, dict):
                    continue
                items.append({
                    "interview_id": point.get("interview_id"),
                    "mode": mode,
                    "role": point.get("role"),
                    "company": None,
                    "completed_at": point.get("date"),
                    "score": point.get("score"),
                    "duration_seconds": None,
                    "score_state": point.get("score_state") or "ready",
                    "source_kind": point.get("source_kind") or "recorded_evidence",
                    "round_id": point.get("round_id"),
                    "questions_completed": None,
                    "questions_total": None,
                    "problems_attempted": None,
                    "problems_total": None,
                    "problems_solved": None,
                    "change": None,
                    "key_result": None,
                })
    items.extend(item for item in legacy_history if isinstance(item, dict))
    items.sort(key=lambda item: item.get("completed_at") or item.get("date") or "", reverse=False)
    previous_by_mode: Dict[str, Optional[float]] = {}
    for item in items:
        item["date"] = item.get("completed_at") or item.get("date")
        score = _performance_number(item.get("score"))
        mode = str(item.get("mode") or "interview")
        previous = previous_by_mode.get(mode)
        item["change"] = round(score - previous, 1) if score is not None and previous is not None else None
        if score is not None and item.get("score_state") != "legacy":
            previous_by_mode[mode] = score
    items.sort(key=lambda item: item.get("completed_at") or item.get("date") or "", reverse=True)
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

    now = datetime.now(timezone.utc)
    best_answer_candidates = [
        item for item in scored_responses
        if item.get("response") and item.get("created_at")
        and (now - (item["created_at"].replace(tzinfo=timezone.utc) if item["created_at"].tzinfo is None else item["created_at"])).days <= 7
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


def _dashboard_skill_label(skill_key: Any) -> str:
    value = str(skill_key or "General").split(":")[-1]
    return re.sub(r"[-_]+", " ", value).strip().title() or "General"


def _home_next_action_base(action_type: str, label: str) -> Dict[str, Any]:
    return {
        "type": action_type,
        "label": label,
        "mode": None,
        "resume_id": None,
        "job_profile_id": None,
        "interview_id": None,
        "analysis_id": None,
        "mission_id": None,
        "roadmap_node_id": None,
        "exercise_id": None,
    }


def build_readonly_learning_snapshot(cursor: Any, user_id: str) -> Dict[str, Any]:
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
    skill_gaps = [
        {
            "skill_key": row[0],
            "label": _dashboard_skill_label(row[0]),
            "category": row[1],
            "mastery_score": float(row[2]) if row[2] is not None else None,
            "confidence_score": float(row[3] or 0),
            "evidence_count": int(row[4] or 0),
            "last_evidence_at": row[5].isoformat() if row[5] else None,
            "next_review_at": row[6].isoformat() if row[6] else None,
            "why_it_matters": f"Interview evidence still shows a gap in {_dashboard_skill_label(row[0])}.",
        }
        for row in cursor.fetchall() or []
    ]

    cursor.execute(
        """
        SELECT weakness_state_id, skill_key, lifecycle_state, observation_count,
               session_count, baseline_score, latest_score, confidence,
               root_cause_hypothesis, root_cause_confidence,
               evidence_summary, last_observed_at
        FROM WeaknessStates
        WHERE user_id = %s AND lifecycle_state <> 'resolved'
        ORDER BY
            CASE lifecycle_state
                WHEN 'worsening' THEN 0 WHEN 'repeated' THEN 1
                WHEN 'occasional' THEN 2 WHEN 'new' THEN 3 ELSE 4
            END,
            confidence DESC, last_observed_at DESC
        LIMIT 12
        """,
        (user_id,),
    )
    weakness_states = [
        {
            "weakness_state_id": row[0],
            "skill_key": row[1],
            "label": _dashboard_skill_label(row[1]),
            "lifecycle_state": row[2],
            "observation_count": int(row[3] or 0),
            "session_count": int(row[4] or 0),
            "baseline_score": float(row[5]) if row[5] is not None else None,
            "latest_score": float(row[6]) if row[6] is not None else None,
            "confidence": float(row[7] or 0),
            "root_cause_hypothesis": row[8],
            "root_cause_confidence": row[9],
            "evidence_summary": _json_object(row[10]),
            "last_observed_at": row[11].isoformat() if row[11] else None,
        }
        for row in cursor.fetchall() or []
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
    technical_mistakes = [
        {
            "cluster_id": row[0],
            "round_id": row[1],
            "mistake_type": _human_label(row[2]),
            "mistake_key": row[3],
            "examples": row[4] if isinstance(row[4], list) else [],
            "occurrence_count": int(row[5] or 0),
            "last_seen_at": row[6].isoformat() if row[6] else None,
        }
        for row in cursor.fetchall() or []
    ]

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
            "evidence": _json_object(row[4]),
            "status": row[5],
            "next_check_at": row[6].isoformat() if row[6] else None,
            "updated_at": row[7].isoformat() if row[7] else None,
        }
        for row in cursor.fetchall() or []
    ]

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
              SELECT 1 FROM ImprovementMissions mission
              WHERE mission.mission_id = GeneratedExercises.mission_id
                AND mission.user_id = GeneratedExercises.user_id
                AND mission.status = 'active'
          )
        ORDER BY CASE WHEN status = 'in_progress' THEN 0 ELSE 1 END, created_at DESC
        LIMIT 12
        """,
        (user_id,),
    )
    exercise_queue = [_exercise_from_row(row) for row in cursor.fetchall() or []]
    active_missions = {
        "interview": _active_mission_payload(cursor, user_id, mode="mock"),
        "technical": _active_mission_payload(cursor, user_id, mode="technical"),
    }
    active_mission = active_missions["interview"] or active_missions["technical"]
    improvement_history = _improvement_history_payload(cursor, user_id)

    cursor.execute(
        """
        SELECT event_type, severity, COUNT(*), MAX(created_at)
        FROM MalpracticeEvents
        WHERE user_id = %s
        GROUP BY event_type, severity
        ORDER BY MAX(created_at) DESC
        LIMIT 8
        """,
        (user_id,),
    )
    integrity_events = [
        {
            "event_type": row[0],
            "severity": row[1],
            "count": int(row[2] or 0),
            "last_seen_at": row[3].isoformat() if row[3] else None,
        }
        for row in cursor.fetchall() or []
    ]
    severe_count = sum(item["count"] for item in integrity_events if item["severity"] == "severe")
    warning_count = sum(item["count"] for item in integrity_events if item["severity"] != "severe")
    integrity_status = {
        "status": "flagged" if severe_count else "watched" if warning_count else "clean",
        "severe_count": severe_count,
        "warning_count": warning_count,
        "events": integrity_events,
    }

    roadmap = active_mission.get("roadmap", []) if active_mission else []
    next_node = next(
        (
            node for node in roadmap
            if node.get("availability_status") in {"current", "available"}
            and node.get("exercise_id")
            and node.get("result_status") not in {"passed", "strong_pass"}
        ),
        None,
    )
    if active_mission and next_node:
        next_action = _home_next_action_base(
            "continue_mission",
            next_node.get("title") or active_mission.get("title") or "Continue improvement mission",
        )
        next_action.update({
            "mode": active_mission.get("mode"),
            "mission_id": active_mission.get("mission_id"),
            "roadmap_node_id": next_node.get("roadmap_node_id"),
            "exercise_id": next_node.get("exercise_id"),
        })
    elif active_mission and active_mission.get("validation_status") == "validation_pending":
        next_action = _home_next_action_base(
            "start_interview",
            "Take a later comparable round to verify your improvement",
        )
        next_action["mode"] = active_mission.get("mode") or "mock"
        next_action["mission_id"] = active_mission.get("mission_id")
    else:
        next_action = _home_next_action_base("start_interview", "Complete an interview to generate new evidence")
        next_action["mode"] = "mock"

    weakest = weakness_states[0] if weakness_states else (skill_gaps[0] if skill_gaps else None)
    next_exercise = exercise_queue[0] if exercise_queue else None
    headline = (
        f"Your next useful rep is {next_exercise.get('title')}."
        if next_exercise
        else f"Your highest-priority weakness is {weakest.get('label')}."
        if weakest
        else "No learning evidence yet."
    )
    cursor.execute(
        """
        SELECT
            COUNT(*),
            COUNT(*) FILTER (
                WHERE NOT EXISTS (
                      SELECT 1 FROM SessionPerformanceAnalyses spa
                      WHERE spa.interview_id = i.interview_id
                        AND spa.user_id = i.user_id
                        AND spa.schema_version = 'session-performance-v4'
                        AND spa.status = 'ready'
                        AND spa.is_current = TRUE
                        AND spa.analysis_json_encrypted IS NOT NULL
                        AND spa.evidence_index_encrypted IS NOT NULL
                  )
            )
        FROM Interviews i
        WHERE i.user_id = %s
          AND i.status IN ('analysis_pending', 'analysis_running', 'completed', 'partial', 'failed')
          AND (
              i.attempt_status = 'completed'
              OR EXISTS (
                  SELECT 1 FROM InterviewResponses response
                  WHERE response.interview_id = i.interview_id
              )
              OR EXISTS (
                  SELECT 1 FROM TechnicalSubmissions submission
                  WHERE submission.interview_id = i.interview_id
                    AND submission.user_id = i.user_id
              )
              OR EXISTS (
                  SELECT 1 FROM TechnicalRunEvents event
                  JOIN TechnicalInterviewRounds round ON round.round_id = event.round_id
                  WHERE round.interview_id = i.interview_id
                    AND event.user_id = i.user_id
              )
              OR EXISTS (
                  SELECT 1 FROM TechnicalCodeSnapshots snapshot
                  WHERE snapshot.interview_id = i.interview_id
                    AND snapshot.user_id = i.user_id
                    AND snapshot.source_chars > 0
              )
              OR EXISTS (
                  SELECT 1 FROM TechnicalExecutionJobs execution
                  WHERE execution.interview_id = i.interview_id
                    AND execution.user_id = i.user_id
                    AND execution.status IN ('queued', 'leased', 'running', 'completed')
              )
          )
        """,
        (user_id,),
    )
    analysis_row = cursor.fetchone() or (0, 0)
    return {
        "student_summary": {
            "headline": headline,
            "blocker": weakest.get("root_cause_hypothesis") if weakest else None,
            "next_step": next_action["label"],
            "integrity": integrity_status["status"],
        },
        "next_action": next_action,
        "completed_fixes": improvement_history.get("skills", []),
        "practice_loop": {
            "active_drill": next_exercise,
            "latest_attempt": (improvement_history.get("recent_attempts") or [None])[0],
            "repeated_mistake": technical_mistakes[0].get("mistake_type") if technical_mistakes else None,
            "progress_summary": "Progress is derived from persisted graded attempts.",
            "mode_stats": [],
        },
        "skill_gaps": skill_gaps,
        "weakness_states": weakness_states,
        "technical_mistakes": technical_mistakes,
        "project_homework": project_homework,
        "exercise_queue": exercise_queue,
        "active_mission": active_mission,
        "active_missions": active_missions,
        "roadmap": roadmap,
        "improvement_history": improvement_history,
        "integrity_status": integrity_status,
        "analysis_availability": {
            "completed_count": int(analysis_row[0] or 0),
            "missing_canonical_count": int(analysis_row[1] or 0),
        },
    }


@router.get("/learning")
async def get_learning_dashboard(
    current_user: Dict = Depends(get_current_user),
):
    connection = get_db_connection()
    cursor = connection.cursor()
    try:
        return build_readonly_learning_snapshot(cursor, current_user["user_id"])
    finally:
        cursor.close()
        return_db_connection(connection)


@router.get("/exercises")
async def get_generated_exercises(current_user: Dict = Depends(get_current_user)):
    connection = get_db_connection()
    cursor = connection.cursor()
    try:
        snapshot = build_readonly_learning_snapshot(cursor, current_user["user_id"])
        return {"exercises": snapshot.get("exercise_queue", [])}
    finally:
        cursor.close()
        return_db_connection(connection)


def _attempt_session_response(row: Any) -> Dict[str, Any]:
    return {
        "attempt_session_id": row[0],
        "status": row[1],
        "draft_payload": _decrypt_attempt_draft(row[2], row[3]),
        "idempotency_key": row[4],
        "deadline_at": row[5].isoformat() if row[5] else None,
        "remaining_seconds": int(row[6]) if row[6] is not None else None,
        "updated_at": row[7].isoformat() if row[7] else None,
        "expires_at": row[8].isoformat() if row[8] else None,
        "mission_id": row[9] if len(row) > 9 else None,
        "roadmap_node_id": row[10] if len(row) > 10 else None,
        "exercise_id": row[11] if len(row) > 11 else None,
    }


@router.post("/exercises/{exercise_id}/attempt-session")
async def create_exercise_attempt_session(
    exercise_id: str,
    request: ExerciseAttemptSessionCreate,
    idempotency_header: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    current_user: Dict = Depends(get_current_user),
):
    if idempotency_header != request.idempotency_key:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Idempotency-Key header must match the request body",
        )
    ownership = await async_execute(
        """
        SELECT ge.exercise_id
        FROM GeneratedExercises ge
        JOIN ImprovementMissions mission ON mission.mission_id = ge.mission_id
        JOIN ImprovementRoadmapNodes node ON node.roadmap_node_id = ge.roadmap_node_id
        WHERE ge.exercise_id = %s
          AND ge.user_id = %s
          AND ge.mission_id = %s
          AND ge.roadmap_node_id = %s
          AND mission.user_id = %s
          AND node.user_id = %s
          AND mission.status = 'active'
          AND node.availability_status = 'current'
          AND node.result_status NOT IN ('passed', 'strong_pass')
          AND ge.status IN ('queued', 'in_progress')
        """,
        (
            exercise_id,
            current_user["user_id"],
            request.mission_id,
            request.roadmap_node_id,
            current_user["user_id"],
            current_user["user_id"],
        ),
        fetchone=True,
    )
    if not ownership:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Exercise or roadmap node not available")

    existing = await async_execute(
        """
        SELECT attempt_session_id, status, draft_payload_encrypted, draft_payload,
               idempotency_key,
               deadline_at, remaining_seconds, updated_at, expires_at,
               mission_id, roadmap_node_id, exercise_id
        FROM ImprovementAttemptSessions
        WHERE user_id = %s AND mission_id = %s AND roadmap_node_id = %s
          AND exercise_id = %s
          AND status IN ('draft', 'in_progress', 'save_failed')
          AND (expires_at IS NULL OR expires_at > NOW())
        ORDER BY updated_at DESC
        LIMIT 1
        """,
        (
            current_user["user_id"], request.mission_id, request.roadmap_node_id,
            exercise_id,
        ),
        fetchone=True,
    )
    if existing:
        return _attempt_session_response(existing)

    session_id = str(uuid.uuid4())
    row = await async_execute(
        """
        INSERT INTO ImprovementAttemptSessions (
            attempt_session_id, user_id, mission_id, roadmap_node_id, exercise_id,
            status, draft_payload, draft_payload_encrypted, idempotency_key, expires_at
        )
        VALUES (
            %s, %s, %s, %s, %s, 'in_progress', %s, %s, %s, NOW() + INTERVAL '24 hours'
        )
        ON CONFLICT (user_id, exercise_id, idempotency_key)
        DO UPDATE SET
            attempt_session_id = ImprovementAttemptSessions.attempt_session_id
        RETURNING attempt_session_id, status, draft_payload_encrypted, draft_payload,
                  idempotency_key,
                  deadline_at, remaining_seconds, updated_at, expires_at,
                  mission_id, roadmap_node_id, exercise_id
        """,
        (
            session_id,
            current_user["user_id"],
            request.mission_id,
            request.roadmap_node_id,
            exercise_id,
            _sensitive_json_marker(request.draft_payload),
            _encrypt_json_bytes(request.draft_payload),
            request.idempotency_key,
        ),
        fetchone=True,
    )
    logger.info(
        "improve_attempt_session_started",
        extra={
            "user_id": current_user["user_id"],
            "exercise_id": exercise_id,
            "mission_id": request.mission_id,
            "roadmap_node_id": request.roadmap_node_id,
        },
    )
    return _attempt_session_response(row)


@router.patch("/exercises/{exercise_id}/attempt-session/{attempt_session_id}")
async def update_exercise_attempt_session(
    exercise_id: str,
    attempt_session_id: str,
    request: ExerciseAttemptSessionUpdate,
    idempotency_header: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    current_user: Dict = Depends(get_current_user),
):
    if idempotency_header != request.idempotency_key:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Idempotency-Key header must match the request body",
        )
    draft_marker = _sensitive_json_marker(request.draft_payload) if request.draft_payload is not None else None
    draft_encrypted = _encrypt_json_bytes(request.draft_payload) if request.draft_payload is not None else None
    row = await async_execute(
        """
        UPDATE ImprovementAttemptSessions
        SET status = COALESCE(%s, status),
            draft_payload = COALESCE(%s::jsonb, draft_payload),
            draft_payload_encrypted = COALESCE(%s, draft_payload_encrypted),
            remaining_seconds = NULL,
            deadline_at = NULL,
            updated_at = NOW()
        WHERE attempt_session_id = %s
          AND exercise_id = %s
          AND user_id = %s
          AND mission_id = %s
          AND roadmap_node_id = %s
          AND idempotency_key = %s
          AND status IN ('draft', 'in_progress', 'save_failed')
          AND (expires_at IS NULL OR expires_at > NOW())
        RETURNING attempt_session_id, status, draft_payload_encrypted, draft_payload,
                  idempotency_key,
                  deadline_at, remaining_seconds, updated_at, expires_at,
                  mission_id, roadmap_node_id, exercise_id
        """,
        (
            request.status,
            draft_marker,
            draft_encrypted,
            attempt_session_id,
            exercise_id,
            current_user["user_id"],
            request.mission_id,
            request.roadmap_node_id,
            request.idempotency_key,
        ),
        fetchone=True,
    )
    if not row:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Attempt session is unavailable or expired")
    logger.info(
        "improve_attempt_session_updated",
        extra={"user_id": current_user["user_id"], "exercise_id": exercise_id, "attempt_session_id": attempt_session_id, "status": row[1]},
    )
    return _attempt_session_response(row)


@router.post("/exercises/{exercise_id}/attempt")
async def create_exercise_attempt(
    exercise_id: str,
    request: ExerciseAttemptCreate,
    idempotency_header: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    current_user: Dict = Depends(get_current_user),
):
    if idempotency_header and idempotency_header != request.idempotency_key:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Idempotency-Key header must match the request body",
        )
    submitted_answer = (request.submitted_answer or "").strip()
    payload = dict(request.submitted_payload or {})
    meaningful_payload = {
        key: value
        for key, value in payload.items()
        if key not in {"idempotency_key", "attempt_session_id", "mission_id", "roadmap_node_id"}
    }
    if not submitted_answer and not any(
        (isinstance(value, str) and value.strip())
        or (isinstance(value, (list, dict)) and bool(value))
        or (value is not None and not isinstance(value, (str, list, dict)))
        for value in meaningful_payload.values()
    ):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Attempt cannot be empty")
    payload["idempotency_key"] = request.idempotency_key
    payload["attempt_session_id"] = request.attempt_session_id
    payload["mission_id"] = request.mission_id
    payload["roadmap_node_id"] = request.roadmap_node_id
    try:
        return await submit_exercise_attempt(
            current_user["user_id"],
            exercise_id,
            submitted_answer,
            payload,
        )
    except ValueError as exc:
        detail = str(exc) or "Exercise not found"
        lowered = detail.lower()
        if "real submitted work" in lowered or "cannot be empty" in lowered:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=detail) from None
        if "idempotency" in lowered or "attempt session" in lowered or "current" in lowered or "expired" in lowered or "does not match" in lowered:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail) from None
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail) from None


@router.post("/exercises/{exercise_id}/run")
async def run_exercise_code(
    exercise_id: str,
    request: ExerciseRunRequest,
    current_user: Dict = Depends(get_current_user),
):
    exercise = await async_execute(
        """
        SELECT exercise_id, exercise_type, prompt
        FROM GeneratedExercises
        WHERE exercise_id = %s AND user_id = %s
        """,
        (exercise_id, current_user["user_id"]),
        fetchone=True,
    )
    if not exercise:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Exercise not found")

    started = time.time()
    runtime = await _resolve_piston_runtime(request.language)
    payload = {
        "language": runtime["language"],
        "version": runtime["version"],
        "files": [{"name": EXERCISE_FILE_NAMES[request.language], "content": request.code}],
        "stdin": request.stdin or "",
    }
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=settings.PISTON_TIMEOUT_SECONDS)) as session:
            headers = {"Authorization": f"Bearer {settings.PISTON_API_TOKEN}"} if settings.PISTON_API_TOKEN else {}
            async with session.post(settings.PISTON_API_URL.rstrip("/") + "/execute", json=payload, headers=headers) as response:
                if response.status >= 400:
                    raise HTTPException(status_code=502, detail="Code execution service failed")
                result = await response.json()
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=502, detail="Code execution service unavailable")

    run = result.get("run") or {}
    stdout = run.get("stdout") or ""
    stderr = run.get("stderr") or ""
    exit_code = run.get("code")
    runtime_ms = int((time.time() - started) * 1000)
    return {
        "exercise_id": exercise_id,
        "language": request.language,
        "stdout": stdout,
        "stderr": stderr,
        "exit_code": exit_code,
        "runtime_ms": runtime_ms,
        "error_signature": build_error_signature(stdout, stderr, exit_code),
    }


def _job_profile_from_row(row: Any) -> Dict[str, Any]:
    tech_stack = row[3] or []
    if isinstance(tech_stack, str):
        try:
            tech_stack = json.loads(tech_stack)
        except Exception:
            tech_stack = []
    normalized_requirements = row[8] if len(row) > 8 else {}
    if isinstance(normalized_requirements, str):
        try:
            normalized_requirements = json.loads(normalized_requirements)
        except Exception:
            normalized_requirements = {}
    return {
        "profile_id": row[0],
        "role": row[1],
        "company": row[2],
        "tech_stack": tech_stack if isinstance(tech_stack, list) else [],
        "job_description": _decrypt_job_description(row[6]) if len(row) > 6 else None,
        "job_description_hash": row[7] if len(row) > 7 else None,
        "normalized_requirements": normalized_requirements if isinstance(normalized_requirements, dict) else {},
        "normalization_version": row[9] if len(row) > 9 else None,
        "experience_level": row[10] if len(row) > 10 else None,
        "parser_version": row[11] if len(row) > 11 else None,
        "is_selected": bool(row[4]),
        "created_at": row[5],
        "updated_at": row[12] if len(row) > 12 else None,
    }


def _profile_options() -> List[Dict[str, Any]]:
    return [
        {
            "profile_type": key,
            "label": config["label"],
            "interview_instruction": config["interview_instruction"],
            "technical_instruction": config["technical_instruction"],
            "behavioral_instruction": config["behavioral_instruction"],
            "duration": config["duration"],
        }
        for key, config in PROFILE_CONFIGS.items()
    ]


@router.get("/interview-profile", response_model=InterviewProfileResponse)
async def get_interview_profile(
    current_user: Dict = Depends(get_current_user)
):
    connection = get_db_connection()
    cursor = connection.cursor()

    try:
        cursor.execute(
            """
            SELECT COALESCE(interview_profile_type, %s)
            FROM UserInfo
            WHERE user_id = %s
            """,
            (DEFAULT_PROFILE_TYPE, current_user["user_id"])
        )
        row = cursor.fetchone()
        profile_type = normalize_profile_type(row[0] if row else DEFAULT_PROFILE_TYPE)
        return {
            "profile_type": profile_type,
            "label": PROFILE_CONFIGS[profile_type]["label"],
            "options": _profile_options(),
        }
    finally:
        cursor.close()
        return_db_connection(connection)


@router.put("/interview-profile", response_model=InterviewProfileResponse)
async def update_interview_profile(
    request: InterviewProfileRequest,
    current_user: Dict = Depends(get_current_user)
):
    connection = get_db_connection()
    cursor = connection.cursor()

    try:
        profile_type = normalize_profile_type(request.profile_type)
        cursor.execute(
            """
            UPDATE UserInfo
            SET interview_profile_type = %s, updated_at = NOW()
            WHERE user_id = %s
            RETURNING interview_profile_type
            """,
            (profile_type, current_user["user_id"])
        )
        row = cursor.fetchone()
        if not row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Profile not found"
            )
        connection.commit()
        return {
            "profile_type": profile_type,
            "label": PROFILE_CONFIGS[profile_type]["label"],
            "options": _profile_options(),
        }
    except HTTPException:
        connection.rollback()
        raise
    except Exception:
        connection.rollback()
        logger.error("Failed to update interview profile")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update interview profile"
        )
    finally:
        cursor.close()
        return_db_connection(connection)


@router.get("/job-profiles", response_model=List[JobProfileResponse])
async def get_job_profiles(
    current_user: Dict = Depends(get_current_user)
):
    connection = get_db_connection()
    cursor = connection.cursor()

    try:
        cursor.execute(
            JOB_PROFILE_SELECT
            + " WHERE user_id = %s ORDER BY is_selected DESC, updated_at DESC NULLS LAST, created_at DESC",
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
        if not request.role:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Job role is required")
        cursor.execute(
            "SELECT 1 FROM UserInfo WHERE user_id = %s FOR UPDATE",
            (current_user["user_id"],),
        )
        if not cursor.fetchone():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
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

        job_description = str(request.job_description or "").strip()
        description_hash = hashlib.sha256(job_description.encode("utf-8")).hexdigest() if job_description else None
        cursor.execute(
            """
            SELECT profile_id
            FROM JobProfiles reusable_profile
            WHERE reusable_profile.user_id = %s
              AND LOWER(BTRIM(reusable_profile.role)) = LOWER(BTRIM(%s))
              AND LOWER(BTRIM(COALESCE(reusable_profile.company, ''))) = LOWER(BTRIM(%s))
              AND reusable_profile.job_description_hash IS NOT DISTINCT FROM %s
            ORDER BY reusable_profile.updated_at DESC NULLS LAST, reusable_profile.created_at DESC
            LIMIT 1
            """,
            (
                current_user["user_id"],
                request.role,
                request.company or "",
                description_hash,
            ),
        )
        reusable = cursor.fetchone()
        if reusable:
            cursor.execute(
                JOB_PROFILE_SELECT + " WHERE profile_id = %s AND user_id = %s",
                (reusable[0], current_user["user_id"]),
            )
            existing = cursor.fetchone()
            connection.commit()
            return _job_profile_from_row(existing)
        normalized_requirements = normalize_job_requirements(
            job_description,
            request.tech_stack,
            request.requirements,
        )
        cursor.execute(
            """
            INSERT INTO JobProfiles (
                user_id, role, company, tech_stack, is_selected,
                job_description_encrypted, job_description_hash,
                normalized_requirements, normalization_version,
                experience_level, parser_version, created_at, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
            """
            + JOB_PROFILE_RETURNING,
            (
                current_user["user_id"],
                request.role,
                request.company,
                json.dumps(request.tech_stack),
                is_first,
                _encrypt_job_description(job_description),
                description_hash,
                json.dumps(normalized_requirements),
                JOB_REQUIREMENT_NORMALIZATION_VERSION,
                request.experience_level,
                JOB_PROFILE_PARSER_VERSION,
            )
        )
        row = cursor.fetchone()
        connection.commit()
        return _job_profile_from_row(row)

    except HTTPException:
        connection.rollback()
        raise
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


@router.patch("/job-profiles/{profile_id}", response_model=JobProfileResponse)
async def update_job_profile(
    profile_id: int,
    request: JobProfileUpdate,
    current_user: Dict = Depends(get_current_user),
):
    connection = get_db_connection()
    cursor = connection.cursor()
    try:
        cursor.execute(
            JOB_PROFILE_SELECT
            + " WHERE profile_id = %s AND user_id = %s FOR UPDATE",
            (profile_id, current_user["user_id"]),
        )
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job profile not found")
        existing = _job_profile_from_row(row)
        fields = request.model_fields_set
        if "role" in fields and not request.role:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Job role is required")
        role = request.role if "role" in fields else existing["role"]
        company = request.company if "company" in fields else existing["company"]
        tech_stack = request.tech_stack if "tech_stack" in fields else existing["tech_stack"]
        job_description = (
            str(request.job_description or "").strip()
            if "job_description" in fields
            else str(existing.get("job_description") or "")
        )
        experience_level = (
            request.experience_level
            if "experience_level" in fields
            else existing.get("experience_level")
        )
        supplied_requirements = (
            request.requirements
            if "requirements" in fields
            else list((existing.get("normalized_requirements") or {}).get("requirements") or [])
        )
        normalized_requirements = normalize_job_requirements(
            job_description,
            tech_stack or [],
            supplied_requirements or [],
        )
        description_hash = hashlib.sha256(job_description.encode("utf-8")).hexdigest() if job_description else None
        cursor.execute(
            """
            UPDATE JobProfiles
            SET role = %s,
                company = %s,
                tech_stack = %s,
                job_description_encrypted = %s,
                job_description_hash = %s,
                normalized_requirements = %s,
                normalization_version = %s,
                experience_level = %s,
                parser_version = %s,
                updated_at = NOW()
            WHERE profile_id = %s AND user_id = %s
            """
            + JOB_PROFILE_RETURNING,
            (
                role,
                company,
                json.dumps(tech_stack or []),
                _encrypt_job_description(job_description),
                description_hash,
                json.dumps(normalized_requirements),
                JOB_REQUIREMENT_NORMALIZATION_VERSION,
                experience_level,
                JOB_PROFILE_PARSER_VERSION,
                profile_id,
                current_user["user_id"],
            ),
        )
        updated = cursor.fetchone()
        connection.commit()
        return _job_profile_from_row(updated)
    except HTTPException:
        connection.rollback()
        raise
    except Exception:
        connection.rollback()
        logger.exception("Failed to update job profile")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to update job profile")
    finally:
        cursor.close()
        return_db_connection(connection)


@router.delete("/job-profiles/{profile_id}")
async def delete_job_profile(
    profile_id: int,
    current_user: Dict = Depends(get_current_user),
):
    connection = get_db_connection()
    cursor = connection.cursor()
    try:
        cursor.execute(
            "SELECT 1 FROM JobProfiles WHERE profile_id = %s AND user_id = %s FOR UPDATE",
            (profile_id, current_user["user_id"]),
        )
        if not cursor.fetchone():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job profile not found")
        cursor.execute(
            """
            UPDATE InterviewBlueprints
            SET status = CASE WHEN status = 'ready' THEN 'expired' ELSE status END
            WHERE user_id = %s AND job_profile_id = %s
            """,
            (current_user["user_id"], profile_id),
        )
        cursor.execute(
            "DELETE FROM JobProfiles WHERE profile_id = %s AND user_id = %s",
            (profile_id, current_user["user_id"]),
        )
        cursor.execute(
            """
            UPDATE JobProfiles
            SET is_selected = TRUE, updated_at = NOW()
            WHERE profile_id = (
                SELECT profile_id
                FROM JobProfiles
                WHERE user_id = %s
                ORDER BY is_selected DESC, updated_at DESC NULLS LAST, created_at DESC
                LIMIT 1
            )
            """,
            (current_user["user_id"],),
        )
        connection.commit()
        return {"success": True, "profile_id": profile_id}
    except HTTPException:
        connection.rollback()
        raise
    except Exception:
        connection.rollback()
        logger.exception("Failed to delete job profile")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to delete job profile")
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
            "SELECT 1 FROM UserInfo WHERE user_id = %s FOR UPDATE",
            (current_user["user_id"],),
        )
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
            """,
            (profile_id, current_user["user_id"])
        )
        cursor.execute(
            JOB_PROFILE_SELECT + " WHERE profile_id = %s AND user_id = %s",
            (profile_id, current_user["user_id"]),
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


def _historical_job_target(
    *,
    settings_value: Any,
    linked_job_profile_id: Any = None,
    snapshot_profile_type: Any = None,
    snapshot_job_value: Any = None,
    fallback_title: Any = None,
) -> Dict[str, Any]:
    settings_payload = _json_object(settings_value)
    snapshot_job = _encrypted_json_object(snapshot_job_value) if snapshot_job_value is not None else {}
    compact_job = settings_payload.get("job_context")
    if not isinstance(compact_job, dict):
        compact_job = {}
    role = str(snapshot_job.get("role") or compact_job.get("role") or fallback_title or "").strip()
    company = str(snapshot_job.get("company") or compact_job.get("company") or "").strip()
    job_description = str(snapshot_job.get("job_description") or "").strip()
    if not job_description and settings_payload.get("job_description_encrypted"):
        job_description = str(decrypt_data(str(settings_payload["job_description_encrypted"])) or "").strip()
    raw_profile_type = snapshot_profile_type or compact_job.get("profile_type") or settings_payload.get("profile_type")
    profile_type = normalize_profile_type(str(raw_profile_type or DEFAULT_PROFILE_TYPE))
    legacy_saved_target = bool(
        not raw_profile_type
        and (
            linked_job_profile_id
            or snapshot_job.get("job_profile_id")
            or str(settings_payload.get("job_context_source") or "").strip().lower() == "saved_profile"
            or str(compact_job.get("source") or "").strip().lower() == "saved_profile"
        )
    )
    is_custom = profile_type == "custom" or legacy_saved_target
    description_hash = (
        hashlib.sha256(job_description.encode("utf-8")).hexdigest()
        if job_description
        else settings_payload.get("job_description_hash")
    )
    return {
        "profile_type": profile_type,
        "is_custom": is_custom,
        "role": role,
        "company": company or None,
        "job_description": job_description,
        "job_description_hash": description_hash,
    }


@router.post("/interviews/{interview_id}/copy-profile")
async def copy_interview_profile(
    interview_id: str,
    current_user: Dict = Depends(get_current_user),
):
    connection = get_db_connection()
    cursor = connection.cursor()
    try:
        cursor.execute(
            """
            SELECT i.job_title, i.settings, i.job_profile_id,
                   snapshot.profile_type, snapshot.job_context_encrypted
            FROM Interviews i
            LEFT JOIN AttemptContextSnapshots snapshot
              ON snapshot.interview_id = i.interview_id AND snapshot.user_id = i.user_id
            WHERE i.interview_id = %s AND i.user_id = %s
            FOR UPDATE OF i
            """,
            (interview_id, current_user["user_id"]),
        )
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Interview not found")
        target = _historical_job_target(
            settings_value=row[1],
            linked_job_profile_id=row[2],
            snapshot_profile_type=row[3],
            snapshot_job_value=row[4],
            fallback_title=row[0],
        )
        if not target["is_custom"]:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only interviews created from a custom job profile can be copied")
        if not target["role"] or not target["job_description"]:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This interview does not contain a reusable role and full job description")

        cursor.execute(
            """
            SELECT profile_id
            FROM JobProfiles
            WHERE user_id = %s
              AND LOWER(BTRIM(role)) = LOWER(BTRIM(%s))
              AND LOWER(BTRIM(COALESCE(company, ''))) = LOWER(BTRIM(%s))
              AND job_description_hash IS NOT DISTINCT FROM %s
            ORDER BY updated_at DESC NULLS LAST, created_at DESC
            LIMIT 1
            """,
            (
                current_user["user_id"],
                target["role"],
                target["company"] or "",
                target["job_description_hash"],
            ),
        )
        existing = cursor.fetchone()
        created = False
        cursor.execute("UPDATE JobProfiles SET is_selected = FALSE WHERE user_id = %s", (current_user["user_id"],))
        if existing:
            profile_id = int(existing[0])
            cursor.execute(
                "UPDATE JobProfiles SET is_selected = TRUE, updated_at = NOW() WHERE profile_id = %s AND user_id = %s",
                (profile_id, current_user["user_id"]),
            )
        else:
            created = True
            normalized_requirements = normalize_job_requirements(target["job_description"], [])
            cursor.execute(
                """
                INSERT INTO JobProfiles (
                    user_id, role, company, tech_stack, is_selected,
                    job_description_encrypted, job_description_hash,
                    normalized_requirements, normalization_version,
                    experience_level, parser_version, created_at, updated_at
                )
                VALUES (%s, %s, %s, '[]', TRUE, %s, %s, %s, %s, NULL, %s, NOW(), NOW())
                RETURNING profile_id
                """,
                (
                    current_user["user_id"],
                    target["role"],
                    target["company"],
                    _encrypt_job_description(target["job_description"]),
                    target["job_description_hash"],
                    json.dumps(normalized_requirements),
                    JOB_REQUIREMENT_NORMALIZATION_VERSION,
                    JOB_PROFILE_PARSER_VERSION,
                ),
            )
            profile_id = int(cursor.fetchone()[0])

        cursor.execute(
            JOB_PROFILE_SELECT + " WHERE profile_id = %s AND user_id = %s",
            (profile_id, current_user["user_id"]),
        )
        profile = _job_profile_from_row(cursor.fetchone())
        connection.commit()
        return {"profile": profile, "created": created}
    except HTTPException:
        connection.rollback()
        raise
    except Exception:
        connection.rollback()
        logger.exception("Failed to copy interview profile")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to copy interview profile")
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
        start_date = datetime.now(timezone.utc) - timedelta(days=days)

        cursor.execute(
            f"""
            SELECT i.interview_id, i.interview_type, i.job_title,
                   i.overall_score, i.created_at, i.completed_at,
                   i.duration_seconds, i.status,
                   (i.report_json IS NOT NULL OR i.report_json_encrypted IS NOT NULL) AS report_present,
                   (
                       EXISTS (
                           SELECT 1 FROM InterviewResponses response
                           WHERE response.interview_id = i.interview_id
                       )
                       OR EXISTS (
                           SELECT 1 FROM TechnicalSubmissions submission
                           WHERE submission.interview_id = i.interview_id
                             AND submission.user_id = i.user_id
                       )
                       OR EXISTS (
                           SELECT 1 FROM TechnicalRunEvents event
                           JOIN TechnicalInterviewRounds round ON round.round_id = event.round_id
                           WHERE round.interview_id = i.interview_id
                             AND event.user_id = i.user_id
                       )
                       OR EXISTS (
                           SELECT 1 FROM TechnicalCodeSnapshots snapshot
                           WHERE snapshot.interview_id = i.interview_id
                             AND snapshot.user_id = i.user_id
                             AND snapshot.source_chars > 0
                       )
                       OR EXISTS (
                           SELECT 1 FROM TechnicalExecutionJobs execution
                           WHERE execution.interview_id = i.interview_id
                             AND execution.user_id = i.user_id
                             AND execution.status IN ('queued', 'leased', 'running', 'completed')
                       )
                   ) AS has_candidate_evidence,
                   EXISTS (
                       SELECT 1 FROM SessionPerformanceAnalyses analysis
                       WHERE analysis.interview_id = i.interview_id
                         AND analysis.user_id = i.user_id
                         AND analysis.status = 'ready'
                         AND analysis.schema_version = 'session-performance-v4'
                         AND analysis.is_current = TRUE
                         AND analysis.analysis_json_encrypted IS NOT NULL
                         AND analysis.evidence_index_encrypted IS NOT NULL
                   ) AS canonical_report_ready,
                   i.job_profile_id, i.settings,
                   snapshot.profile_type, snapshot.job_context_encrypted
            FROM Interviews i
            LEFT JOIN AttemptContextSnapshots snapshot
              ON snapshot.interview_id = i.interview_id AND snapshot.user_id = i.user_id
            WHERE i.user_id = %s AND i.created_at >= %s
            {_non_technical_interview_where("i")}
            ORDER BY i.created_at DESC
            """,
            (current_user["user_id"], start_date)
        )

        rows = cursor.fetchall()
        cursor.execute(
            """
            SELECT profile_id, role, company, job_description_hash
            FROM JobProfiles
            WHERE user_id = %s
            """,
            (current_user["user_id"],),
        )
        saved_profiles = cursor.fetchall()
        saved_by_id = {int(profile[0]): int(profile[0]) for profile in saved_profiles}
        saved_by_content = {
            (
                str(profile[1] or "").strip().lower(),
                str(profile[2] or "").strip().lower(),
                profile[3],
            ): int(profile[0])
            for profile in saved_profiles
        }
        activities = []

        for row in rows:
            job_target = _historical_job_target(
                settings_value=row[12],
                linked_job_profile_id=row[11],
                snapshot_profile_type=row[13],
                snapshot_job_value=row[14],
                fallback_title=row[2],
            )
            saved_profile_id = saved_by_id.get(int(row[11])) if row[11] is not None else None
            if saved_profile_id is None:
                saved_profile_id = saved_by_content.get((
                    str(job_target["role"] or "").strip().lower(),
                    str(job_target["company"] or "").strip().lower(),
                    job_target["job_description_hash"],
                ))
            activities.append({
                "interview_id": row[0],
                "interview_type": row[1],
                "job_title": row[2],
                "overall_score": float(row[3]) if row[3] is not None else None,
                "created_at": row[4].isoformat() if row[4] else None,
                "completed_at": row[5].isoformat() if row[5] else None,
                "duration_seconds": int(row[6]) if row[6] is not None else None,
                "status": row[7],
                "job_target": {
                    "profile_type": job_target["profile_type"],
                    "is_custom": job_target["is_custom"],
                    "role": job_target["role"],
                    "company": job_target["company"],
                    "saved_profile_id": saved_profile_id,
                    "can_copy": bool(
                        job_target["is_custom"]
                        and saved_profile_id is None
                        and job_target["role"]
                        and job_target["job_description"]
                    ),
                },
                "cta": _candidate_report_cta(
                    row[0],
                    interview_status=row[7],
                    report_present=bool(row[8]),
                    has_candidate_evidence=bool(row[9]),
                    canonical_report_ready=bool(row[10]),
                ),
            })

        return {
            "activities": activities,
            "total_count": len(activities),
            "date_range": {
                "from": start_date.isoformat(),
                "to": datetime.now(timezone.utc).isoformat()
            }
        }

    finally:
        cursor.close()
        return_db_connection(connection)


@router.get("/technical-rounds")
async def get_technical_rounds(
    current_user: Dict = Depends(get_current_user),
    limit: int = Query(default=20, ge=1, le=100),
):
    connection = get_db_connection()
    cursor = connection.cursor()

    try:
        cursor.execute(
            """
            SELECT tir.round_id, tir.interview_id, tir.round_type, tir.language,
                   tir.prompt, tir.status, tir.created_at, tir.completed_at, tir.metadata,
                   COUNT(DISTINCT tre.run_id) AS run_count,
                   COUNT(DISTINCT CASE WHEN tre.exit_code = 0 THEN tre.run_id END) AS successful_runs,
                   AVG(tre.runtime_ms) AS avg_runtime_ms,
                   MAX(tre.created_at) AS last_run_at,
                   MAX(ts.visible_passed) AS visible_passed,
                   MAX(ts.visible_total) AS visible_total,
                   MAX(ts.hidden_passed) AS hidden_passed,
                   MAX(ts.hidden_total) AS hidden_total,
                   MAX(ts.status) AS final_verdict,
                   MAX(ts.created_at) AS submitted_at,
                   i.status AS interview_status,
                   i.completed_at AS interview_completed_at,
                   i.settings->>'profile_type' AS profile_type,
                   i.job_title,
                   i.duration_seconds,
                   (i.report_json IS NOT NULL OR i.report_json_encrypted IS NOT NULL) AS report_present,
                   (
                       EXISTS (
                           SELECT 1 FROM TechnicalSubmissions evidence_submission
                           WHERE evidence_submission.interview_id = i.interview_id
                             AND evidence_submission.user_id = i.user_id
                       )
                       OR EXISTS (
                           SELECT 1 FROM TechnicalRunEvents evidence_event
                           JOIN TechnicalInterviewRounds evidence_round
                             ON evidence_round.round_id = evidence_event.round_id
                           WHERE evidence_round.interview_id = i.interview_id
                             AND evidence_event.user_id = i.user_id
                       )
                       OR EXISTS (
                           SELECT 1 FROM TechnicalCodeSnapshots evidence_snapshot
                           WHERE evidence_snapshot.interview_id = i.interview_id
                             AND evidence_snapshot.user_id = i.user_id
                             AND evidence_snapshot.source_chars > 0
                       )
                       OR EXISTS (
                           SELECT 1 FROM TechnicalExecutionJobs evidence_execution
                           WHERE evidence_execution.interview_id = i.interview_id
                             AND evidence_execution.user_id = i.user_id
                             AND evidence_execution.status IN ('queued', 'leased', 'running', 'completed')
                       )
                   ) AS has_candidate_evidence,
                   EXISTS (
                       SELECT 1 FROM SessionPerformanceAnalyses analysis
                       WHERE analysis.interview_id = i.interview_id
                         AND analysis.user_id = i.user_id
                         AND analysis.mode = 'technical'
                         AND analysis.status = 'ready'
                         AND analysis.schema_version = 'session-performance-v4'
                         AND analysis.is_current = TRUE
                         AND analysis.analysis_json_encrypted IS NOT NULL
                         AND analysis.evidence_index_encrypted IS NOT NULL
                   ) AS canonical_report_ready,
                   (
                       SELECT analysis.overall_score
                       FROM SessionPerformanceAnalyses analysis
                       WHERE analysis.interview_id = i.interview_id
                         AND analysis.user_id = i.user_id
                         AND analysis.mode = 'technical'
                         AND analysis.status = 'ready'
                         AND analysis.schema_version = 'session-performance-v4'
                         AND analysis.is_current = TRUE
                         AND analysis.evidence_status = 'sufficient'
                         AND analysis.overall_score IS NOT NULL
                         AND analysis.analysis_json_encrypted IS NOT NULL
                         AND analysis.evidence_index_encrypted IS NOT NULL
                       ORDER BY analysis.created_at DESC
                       LIMIT 1
                   ) AS official_score
            FROM TechnicalInterviewRounds tir
            LEFT JOIN TechnicalRunEvents tre ON tre.round_id = tir.round_id
            LEFT JOIN TechnicalSubmissions ts ON ts.round_id = tir.round_id
            JOIN Interviews i ON i.interview_id = tir.interview_id
            WHERE tir.user_id = %s
            GROUP BY tir.round_id, tir.interview_id, tir.round_type, tir.language,
                     tir.prompt, tir.status, tir.created_at, tir.completed_at, tir.metadata,
                     i.interview_id, i.status, i.completed_at, i.settings
            ORDER BY tir.created_at DESC
            LIMIT %s
            """,
            (current_user["user_id"], limit),
        )
        rows = cursor.fetchall()
        rounds = [
            {
                "round_id": row[0],
                "interview_id": row[1],
                "round_type": row[2] or "technical",
                "language": row[3],
                "prompt": row[4],
                "status": row[5],
                "created_at": row[6].isoformat() if row[6] else None,
                "completed_at": row[7].isoformat() if row[7] else None,
                "metadata": _json_object(row[8]),
                "run_count": int(row[9] or 0),
                "successful_runs": int(row[10] or 0),
                "avg_runtime_ms": round(float(row[11]), 1) if row[11] is not None else 0,
                "last_run_at": row[12].isoformat() if row[12] else None,
                "visible_passed": int(row[13]) if row[13] is not None else None,
                "visible_total": int(row[14]) if row[14] is not None else None,
                "hidden_passed": int(row[15]) if row[15] is not None else None,
                "hidden_total": int(row[16]) if row[16] is not None else None,
                "final_verdict": row[17],
                "submitted_at": row[18].isoformat() if row[18] else None,
                "interview_status": row[19],
                "interview_completed_at": row[20].isoformat() if row[20] else None,
                "profile_type": row[21],
                "job_title": row[22],
                "duration_seconds": int(row[23]) if row[23] is not None else None,
                "report_present": bool(row[24]),
                "has_candidate_evidence": bool(row[25]),
                "canonical_report_ready": bool(row[26]),
                "official_score": float(row[27]) if row[27] is not None else None,
            }
            for row in rows
        ]
        grouped: Dict[str, Dict[str, Any]] = {}
        for item in rounds:
            session = grouped.setdefault(item["interview_id"], {
                "interview_id": item["interview_id"],
                "profile_type": item.get("profile_type"),
                "job_title": item.get("job_title"),
                "interview_status": item.get("interview_status"),
                "interview_completed_at": item.get("interview_completed_at"),
                "duration_seconds": item.get("duration_seconds"),
                "official_score": item.get("official_score"),
                "cta": _candidate_report_cta(
                    item["interview_id"],
                    interview_status=item.get("interview_status"),
                    report_present=bool(item.get("report_present")),
                    has_candidate_evidence=bool(item.get("has_candidate_evidence")),
                    canonical_report_ready=bool(item.get("canonical_report_ready")),
                ),
                "rounds": [],
            })
            session["rounds"].append(item)
            if not session.get("interview_completed_at") and item.get("completed_at"):
                session["interview_completed_at"] = item["completed_at"]
        sessions = list(grouped.values())
        sessions.sort(
            key=lambda session: max((round_item.get("created_at") or "") for round_item in session["rounds"]),
            reverse=True,
        )
        return {
            "rounds": rounds,
            "sessions": sessions,
            "total_count": len(rounds),
        }

    finally:
        cursor.close()
        return_db_connection(connection)


@router.get("/performance")
async def get_performance(
    current_user: Dict = Depends(get_current_user),
):
    connection = get_db_connection()
    cursor = connection.cursor()
    try:
        canonical = _canonical_performance_payloads(cursor, current_user["user_id"])
        availability = _performance_availability(cursor, current_user["user_id"])
        legacy_history = _legacy_performance_history(cursor, current_user["user_id"])
        interview_payload = canonical.get("interview")
        technical_payload = canonical.get("technical")
        try:
            recorded_interview = _interview_performance_payload(cursor, current_user["user_id"])
            canonical_evidence_count = int((interview_payload or {}).get("evidence_count") or 0)
            if recorded_interview.get("has_data") and (
                not interview_payload or canonical_evidence_count == 0
            ):
                recorded_interview.update({
                    "source": "recorded_evidence",
                    "source_kind": "recorded_evidence",
                    "evidence_status": "coaching_evidence",
                    "empty_state_explanation": None,
                })
                interview_payload = recorded_interview
        except Exception:
            logger.exception("Failed to build recorded interview performance fallback")
        if not technical_payload or technical_payload.get("score_state") != "ready":
            try:
                recorded_technical = _technical_performance_payload(cursor, current_user["user_id"])
                if recorded_technical.get("has_data"):
                    recorded_technical.update({
                        "source": "recorded_evidence",
                        "source_kind": "recorded_evidence",
                        "comparison_notice": "Showing submitted tests, runs, and attempted-problem evidence while the full analysis is prepared.",
                    })
                    technical_payload = _merge_recorded_technical_analytics(
                        technical_payload,
                        recorded_technical,
                    )
            except Exception:
                logger.exception("Failed to build recorded technical performance fallback")
        empty_interview = _dynamic_payload("interview", False, [], [])
        empty_interview["empty_reason"] = "Complete an Interview Round to create evidence-backed performance."
        empty_interview.update({
            "has_evidence": False,
            "has_official_score": False,
            "score_state": "missing",
            "source_kind": "unavailable",
            "included_in_trend": False,
        })
        empty_technical = _dynamic_payload("technical", False, [], [])
        empty_technical["empty_reason"] = "Complete a Technical Round to create evidence-backed performance."
        empty_technical.update({
            "has_evidence": False,
            "has_official_score": False,
            "score_state": "missing",
            "source_kind": "unavailable",
            "included_in_trend": False,
        })
        interview_payload = interview_payload or empty_interview
        technical_payload = technical_payload or empty_technical
        role_context = _performance_role_context(cursor, current_user["user_id"])
        round_history = _performance_round_history(
            interview_payload,
            technical_payload,
            legacy_history,
        )
        return {
            "interview": interview_payload,
            "technical": technical_payload,
            "page": _build_performance_page_payload(
                interview_payload,
                technical_payload,
                role_context,
            ),
            "source": {
                "interview": interview_payload.get("source", "unavailable"),
                "technical": technical_payload.get("source", "unavailable"),
            },
            "history": {
                "official": [
                    *(_performance_payload_trend(interview_payload)),
                    *(_performance_payload_trend(technical_payload)),
                ],
                "legacy": legacy_history,
            },
            "round_history": round_history,
            "availability": availability,
        }
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
            tuple(params + [limit]),
        )
        submissions = []
        for row in cursor.fetchall():
            submissions.append({
                "submission_id": row[0], "kind": row[1], "status": row[2],
                "title": row[3], "message": row[4], "steps": row[5],
                "rating": row[6], "interview_id": row[7], "page_url": row[8],
                "admin_notes": row[9],
                "created_at": row[10].isoformat() if row[10] else None,
                "updated_at": row[11].isoformat() if row[11] else None,
                "email": row[12], "full_name": row[13] or "User",
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
