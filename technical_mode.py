# ============================================================================
# MODULE: technical_mode.py
# PURPOSE: Technical interview rounds — AI-generated DSA prompts, code
#          execution, whiteboard saves, anti-cheat event logging.
# STRUCTURE:
#   - Pydantic request models
#   - AI problem generation and validation helpers
#   - Route handlers
# ENDPOINTS (prefix /api/technical):
#   - GET  /sessions/{interview_id}/rounds  -> list rounds for an interview (199)
#   - POST /rounds/{round_id}/run           -> execute custom input via code runner
#   - GET  /runs/{run_id}                   -> poll case execution state
#   - POST /rounds/{round_id}/whiteboard    -> persist whiteboard JSON (381)
#   - POST /anti-cheat                      -> log AntiCheatEvents row (398)
# DEPENDS ON: auth, config, database (async_execute), interview_profiles,
#             learning_engine
# CONSUMED BY: app.py, Frontend/app/interview/[id]/technical/page.tsx
# DATA TABLES: TechnicalInterviewRounds, TechnicalRunEvents,
#              TechnicalMistakeClusters, AntiCheatEvents
#              (Phase 2 merges AntiCheatEvents -> InterviewEvents)
# ============================================================================

from __future__ import annotations

import json
import hashlib
import asyncio
import time
import uuid
import logging
import ipaddress
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Literal, Optional
from urllib.parse import urlparse

import aiohttp
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from auth import get_current_user
from config import settings
from database import async_execute, get_db_connection, return_db_connection
from entitlements import is_technical_interview_type, normalize_technical_profile
from evaluation_engine import EVALUATION_VERSION, evaluate_answer
from interview_profiles import get_profile_config, normalize_profile_type
from learning_engine import build_error_signature, ingest_technical_run
from llm_router import LLMRoutingError, complete_json_async
from prompt_security import data_block
from rate_limiter import UserRateLimiter
from security_utils import decrypt_data, decrypt_json, encrypt_data

logger = logging.getLogger("technical_mode")

router = APIRouter(prefix="/api/technical", tags=["Technical Interview"])

INTEGRITY_WARNING_THRESHOLD = 5
INTEGRITY_WARNING_EVENT_TYPES = {
    "tab_switch",
    "window_blur",
    "fullscreen_exit",
    "screen_share_stopped",
    "face_missing",
    "face_off_center",
    "camera_obstructed",
    "technical_permission_failed",
    "interview_permission_failed",
    "large_paste",
    "paste_blocked",
    "drop_blocked",
    "mobile_phone_detected",
    "multiple_people_detected",
    "large_code_jump",
    "screen_not_monitor",
    "no_clarification_before_coding",
    "suspicious_clipboard_pattern",
}
INTEGRITY_SEVERE_ONLY_EVENT_TYPES = {
    "suspicious_fast_submit",
    "visible_output_hardcode",
    "session_flagged",
}
TERMINAL_TECHNICAL_INTERVIEW_STATUSES = {
    "analysis_pending",
    "analysis_queued",
    "analysis_running",
    "analyzing",
    "completed",
    "ended",
    "report_ready",
    "partial",
    "partial_report",
    "no_evidence",
    "cancelled",
    "expired",
    "abandoned",
    "failed",
    "analyzed",
}


SUPPORTED_LANGUAGES = "python|javascript|cpp|java"
SUPPORTED_LANGUAGE_NAMES = {"python", "javascript", "cpp", "java"}
PROGRAMMING_LANGUAGE_ALIASES = {
    "python": "python",
    "python3": "python",
    "py": "python",
    "javascript": "javascript",
    "js": "javascript",
    "node": "javascript",
    "nodejs": "javascript",
    "cpp": "cpp",
    "c++": "cpp",
    "c++17": "cpp",
    "java": "java",
}


class CodeRunRequest(BaseModel):
    language: str = Field(pattern=f"^({SUPPORTED_LANGUAGES})$")
    code: str = Field(min_length=1, max_length=20000)
    stdin: Optional[str] = Field(default="", max_length=4000)
    idempotency_key: Optional[str] = Field(default=None, min_length=8, max_length=120)
    editor_revision: Optional[int] = Field(default=None, ge=0)
    editor_hash: Optional[str] = Field(default=None, pattern=r"^[a-fA-F0-9]{64}$")


class TechnicalTestRequest(CodeRunRequest):
    custom_input: Optional[str] = Field(default=None, max_length=8000)


class TechnicalEventRequest(BaseModel):
    interview_id: str
    round_id: Optional[str] = None
    event_type: str = Field(max_length=50)
    payload: Dict[str, Any] = Field(default_factory=dict)


class WhiteboardSaveRequest(BaseModel):
    whiteboard_json: Dict[str, Any]


class DraftSaveRequest(BaseModel):
    code: str = Field(default="", max_length=20000)
    language: str = Field(pattern=f"^({SUPPORTED_LANGUAGES})$")


class TechnicalResponseRequest(BaseModel):
    response_text: str = Field(min_length=1, max_length=20000)
    response_payload: Dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str = Field(min_length=8, max_length=120)
    phase: Literal["primary", "followup"] = "primary"
    parent_response_id: Optional[str] = Field(default=None, max_length=64)


class TechnicalWorkflowRequest(BaseModel):
    stage: Literal["clarification", "approach", "complexity", "explanation", "followup"]
    content: str = Field(min_length=1, max_length=12000)
    idempotency_key: str = Field(min_length=8, max_length=120)
    response_seconds: Optional[float] = Field(default=None, ge=0, le=7200)



class AntiCheatEventRequest(BaseModel):
    interview_id: str
    event_type: str = Field(max_length=50)
    payload: Dict[str, Any] = Field(default_factory=dict)


CODEFORCES_RATING_TARGETS = {
    "top_tier": [1800, 2000],
    "mid_tier": [1000, 1200],
    "startup": [800, 1000],
    "custom": [1000, 1200],  # default; overridden dynamically via _custom_tier_difficulty()
}
DIFFICULTY_LABELS = {
    "top_tier": ["Medium", "Hard"],
    "mid_tier": ["Easy", "Medium"],
    "startup": ["Easy", "Medium"],
    "custom": ["Easy", "Medium"],  # default; overridden dynamically
}
HIDDEN_TEST_TAGS = [
    "empty_input",
    "duplicate_values",
    "large_input",
    "negative_values",
    "boundary_index",
]
AI_GENERATION_MAX_ATTEMPTS = 1
VISIBLE_RUN_RATE_LIMITER = UserRateLimiter(
    max_calls=10,
    time_window=60,
    redis_prefix="technical_visible_run",
)
EXECUTION_JOB_VERSION = "technical-execution-v1"
ROUND_SPEC_VERSION = "technical-round-spec-v1"
MAX_EXECUTION_OUTPUT_BYTES = 64 * 1024
SENSITIVE_TECHNICAL_EVENT_TYPES = {
    "technical_transcript",
    "spoken_explanation",
    "written_approach",
    "clarifying_question",
    "complexity_explanation",
    "final_explanation",
    "targeted_followup",
    "workflow_evidence",
}
TECHNICAL_WORKFLOW_STAGES = (
    "clarification",
    "approach",
    "coding",
    "visible_tests",
    "final_submission",
    "complexity",
    "explanation",
    "followup",
)


def _custom_tier_difficulty(job_description: str, job_title: str) -> tuple:
    """Infer difficulty from job title/description keywords for custom tier."""
    text = f"{job_title} {job_description}".lower()
    senior_signals = ["senior", "staff", "principal", "lead", "architect", "l5", "l6", "l7", "sde-3", "sde3"]
    junior_signals = ["junior", "intern", "entry", "associate", "new grad", "fresher", "l3", "l4", "sde-1", "sde1"]
    if any(s in text for s in senior_signals):
        return [1600, 1800], ["Medium", "Hard"]
    elif any(s in text for s in junior_signals):
        return [800, 1000], ["Easy", "Medium"]
    return [1000, 1400], ["Easy", "Medium"]


TECHNICAL_PROBLEM_JSON_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["problems"],
    "properties": {
        "problems": {
            "type": "array",
            "minItems": 2,
            "maxItems": 2,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "title",
                    "difficulty",
                    "cf_rating",
                    "algorithm_pattern",
                    "statement",
                    "input_format",
                    "output_format",
                    "constraints",
                    "visible_tests",
                    "hidden_tests",
                    "expected_time_complexity",
                    "expected_space_complexity",
                    "hint",
                    "reference_solution",
                ],
                "properties": {
                    "title": {"type": "string", "maxLength": 40},
                    "difficulty": {"type": "string"},
                    "cf_rating": {"type": "integer"},
                    "algorithm_pattern": {"type": "string"},
                    "statement": {"type": "string"},
                    "input_format": {"type": "string"},
                    "output_format": {"type": "string"},
                    "constraints": {"type": "string"},
                    "visible_tests": {
                        "type": "array",
                        "minItems": 3,
                        "maxItems": 3,
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["stdin", "expected", "explanation"],
                            "properties": {
                                "stdin": {"type": "string"},
                                "expected": {"type": "string"},
                                "explanation": {"type": "string"},
                            },
                        },
                    },
                    "hidden_tests": {
                        "type": "array",
                        "minItems": 7,
                        "maxItems": 7,
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["stdin", "expected"],
                            "properties": {
                                "stdin": {"type": "string"},
                                "expected": {"type": "string"},
                            },
                        },
                    },
                    "expected_time_complexity": {"type": "string"},
                    "expected_space_complexity": {"type": "string"},
                    "hint": {"type": "string"},
                    "reference_solution": {"type": "string"},
                },
            },
        }
    },
}


def _stable_seed(*parts: str) -> int:
    digest = hashlib.sha256(":".join(parts).encode("utf-8")).hexdigest()
    return int(digest[:16], 16)


def _technical_generation_cache_key(profile_type: str, interview_id: str, generation_context: Optional[Dict[str, Any]]) -> str:
    context = generation_context or {}
    stable_context = {
        "interview_id": interview_id,
        "profile_type": normalize_profile_type(profile_type),
        "generated_on": date.today().isoformat(),
        "job_title": context.get("job_title") or "",
        "job_description": str(context.get("job_description") or "")[:1500],
        "target_skills": context.get("target_skills") or [],
        "programming_language": context.get("programming_language") or "python",
        "personalization_anchors": context.get("personalization_anchors") or {},
        "mistake_history": context.get("mistake_history") or [],
        "custom_targets": context.get("custom_targets"),
        "custom_labels": context.get("custom_labels"),
    }
    digest = hashlib.sha256(json.dumps(stable_context, sort_keys=True, default=str).encode("utf-8")).hexdigest()
    return f"technical_problem_generation:{digest}"


async def _load_cached_generation(cache_key: str) -> Optional[Dict[str, Any]]:
    try:
        row = await async_execute(
            """
            SELECT payload
            FROM LLMCache
            WHERE cache_key = %s
              AND (expires_at IS NULL OR expires_at > NOW())
            """,
            (cache_key,),
            fetchone=True,
        )
    except Exception:
        return None
    if not row:
        return None
    payload = _json_value(row[0], {})
    return payload if isinstance(payload, dict) else None


async def _save_cached_generation(cache_key: str, payload: Dict[str, Any]) -> None:
    try:
        await async_execute(
            """
            INSERT INTO LLMCache (cache_key, event_type, payload, expires_at)
            VALUES (%s, 'technical_problem_generation', %s, %s)
            ON CONFLICT (cache_key) DO UPDATE SET
                payload = EXCLUDED.payload,
                expires_at = EXCLUDED.expires_at,
                created_at = NOW()
            """,
            (
                cache_key,
                json.dumps(payload),
                datetime.now(timezone.utc) + timedelta(days=1),
            ),
        )
    except Exception:
        logger.warning("Technical problem generation cache write skipped")


def _safe_json_value(value: Any, fallback: Any) -> Any:
    if value is None:
        return fallback
    try:
        decrypted = decrypt_json(value)
        if decrypted is not None:
            return decrypted
    except Exception:
        pass
    return _json_value(value, fallback)


def _string_list(values: Any, limit: int = 12) -> List[str]:
    items: List[str] = []
    for item in values or []:
        if isinstance(item, dict):
            text = item.get("name") or item.get("language") or item.get("title") or item.get("skill")
        else:
            text = item
        text = str(text or "").strip()
        if text and text not in items:
            items.append(text[:80])
        if len(items) >= limit:
            break
    return items


def _selected_programming_language(settings_json: Optional[Dict[str, Any]]) -> str:
    raw_value = (settings_json or {}).get("programming_language") or "python"
    normalized = str(raw_value).strip().lower().replace(" ", "")
    return PROGRAMMING_LANGUAGE_ALIASES.get(normalized, "python")


def _normalize_round_types(values: Any) -> List[str]:
    aliases = {
        "dsa": "coding",
        "code": "coding",
        "coding": "coding",
        "debug": "debugging",
        "debugging": "debugging",
        "concept": "technical_concept",
        "technical": "technical_concept",
        "technical_concept": "technical_concept",
        "system design": "system_design",
        "system-design": "system_design",
        "system_design": "system_design",
        "ml": "ml",
        "backend": "backend",
        "database": "database",
        "os": "os",
        "network": "network",
        "oop": "oop",
    }
    if isinstance(values, str):
        values = [values]
    normalized: List[str] = []
    for value in values or []:
        mapped = aliases.get(str(value or "").strip().lower())
        if mapped and mapped not in normalized:
            normalized.append(mapped)
    return normalized or ["coding", "debugging"]


def _merge_profile_payloads(resume: Dict[str, Any], profile: Dict[str, Any]) -> Dict[str, Any]:
    """Merge editable profile and parsed resume without dropping either source."""
    merged: Dict[str, Any] = {**profile, **resume}

    merged["summary"] = (
        resume.get("summary")
        or profile.get("summary")
        or profile.get("professionalSummary")
        or ""
    )
    merged["target_role"] = (
        resume.get("target_role")
        or resume.get("targetRole")
        or profile.get("target_role")
        or profile.get("targetRole")
        or ""
    )
    merged["skills"] = _string_list(
        [*(resume.get("skills") or []), *(profile.get("skills") or [])],
        24,
    )

    for field, aliases in {
        "projects": ("projects",),
        "experience": ("experience", "experiences"),
    }.items():
        combined: List[Dict[str, Any]] = []
        seen = set()
        for source in (resume, profile):
            source_items: Any = []
            for alias in aliases:
                if source.get(alias):
                    source_items = source.get(alias)
                    break
            for item in source_items or []:
                if not isinstance(item, dict):
                    continue
                identity = str(
                    item.get("name")
                    or item.get("title")
                    or item.get("position")
                    or item.get("description")
                    or ""
                ).strip().lower()
                if not identity or identity in seen:
                    continue
                seen.add(identity)
                combined.append(item)
        merged[field] = combined
    return merged


def _profile_anchor_context(profile: Dict[str, Any], external_signals: Dict[str, Any]) -> Dict[str, Any]:
    projects = []
    for project in (profile.get("projects") or [])[:4]:
        if isinstance(project, dict):
            projects.append({
                "name": project.get("name") or "",
                "description": str(project.get("description") or "")[:220],
                "technologies": _string_list(
                    project.get("technologies")
                    or project.get("tech_stack")
                    or project.get("techStack")
                    or [],
                    8,
                ),
            })
    experiences = []
    for experience in (profile.get("experience") or profile.get("experiences") or [])[:3]:
        if isinstance(experience, dict):
            experiences.append({
                "title": experience.get("title") or experience.get("position") or "",
                "company": experience.get("company") or "",
                "description": str(experience.get("description") or "")[:220],
            })
    github = external_signals.get("github", {}) if isinstance(external_signals, dict) else {}
    repositories = []
    for repo in (github.get("repositories") or [])[:3]:
        if isinstance(repo, dict):
            repositories.append({
                "name": repo.get("name") or "",
                "language": repo.get("language") or "",
                "description": str(repo.get("description") or "")[:160],
            })
    return {
        "summary": str(profile.get("summary") or profile.get("professionalSummary") or "")[:400],
        "target_role": profile.get("target_role") or profile.get("targetRole") or "",
        "skills": _string_list(profile.get("skills") or [], 18),
        "projects": projects,
        "experience": experiences,
        "github_repositories": repositories,
    }


async def _load_technical_generation_context(
    interview_id: str,
    user_id: str,
    settings_json: Dict[str, Any],
    job_title: str,
) -> Dict[str, Any]:
    snapshot_row = None
    try:
        snapshot_row = await async_execute(
            """
            SELECT resume_payload_encrypted, job_context_encrypted,
                   blueprint_context_encrypted, profile_type
            FROM AttemptContextSnapshots
            WHERE interview_id = %s AND user_id = %s
            """,
            (interview_id, user_id),
            fetchone=True,
        )
    except Exception:
        logger.warning("Attempt context snapshot could not be loaded", exc_info=True)
    frozen_row = None
    try:
        frozen_row = await async_execute(
            """
            SELECT ib.blueprint_json_encrypted, ib.blueprint_json,
                   i.questions_data, i.resume_id, i.job_profile_id,
                   rv.resume_payload_encrypted, rv.resume_json,
                   jp.job_description_encrypted, jp.role, jp.company,
                   jp.tech_stack, jp.normalized_requirements
            FROM Interviews i
            LEFT JOIN InterviewBlueprints ib
              ON ib.blueprint_id = i.blueprint_id AND ib.user_id = i.user_id
            LEFT JOIN ResumeVersions rv
              ON rv.resume_id = i.resume_id AND rv.user_id = i.user_id
            LEFT JOIN JobProfiles jp
              ON jp.profile_id = i.job_profile_id AND jp.user_id = i.user_id
            WHERE i.interview_id = %s AND i.user_id = %s
            """,
            (interview_id, user_id),
            fetchone=True,
        )
    except Exception:
        logger.warning("Frozen technical interview context could not be loaded", exc_info=True)

    resume_json: Dict[str, Any] = {}
    profile_json: Dict[str, Any] = {}
    external_signals: Dict[str, Any] = {}
    frozen_blueprint: Dict[str, Any] = {}
    frozen_jd = ""
    frozen_role = ""
    frozen_company = ""
    frozen_tech_stack: List[str] = []
    frozen_requirements: Dict[str, Any] = {}
    snapshot_profile_type = ""
    if frozen_row:
        if frozen_row[0]:
            try:
                frozen_blueprint = json.loads(_decrypt_storage_blob(frozen_row[0]))
            except Exception:
                logger.warning("Frozen blueprint payload could not be decrypted")
        if not frozen_blueprint:
            frozen_blueprint = _json_value(frozen_row[1], {}) or _json_value(frozen_row[2], {}) or {}
        if frozen_row[5]:
            try:
                resume_json = json.loads(_decrypt_storage_blob(frozen_row[5]))
            except Exception:
                logger.warning("Frozen resume payload could not be decrypted")
        if not resume_json:
            resume_json = _safe_json_value(frozen_row[6], {}) or {}
        if frozen_row[7]:
            try:
                frozen_jd = _decrypt_storage_blob(frozen_row[7])
            except Exception:
                logger.warning("Frozen job description could not be decrypted")
        frozen_role = str(frozen_row[8] or "")
        frozen_company = str(frozen_row[9] or "")
        frozen_tech_stack = _string_list(_json_value(frozen_row[10], []), 18)
        requirements_value = _json_value(frozen_row[11], {})
        frozen_requirements = requirements_value if isinstance(requirements_value, dict) else {}

    if snapshot_row:
        try:
            snapshot_resume = json.loads(_decrypt_storage_blob(snapshot_row[0]))
            snapshot_job = json.loads(_decrypt_storage_blob(snapshot_row[1]))
            snapshot_blueprint = json.loads(_decrypt_storage_blob(snapshot_row[2]))
            if isinstance(snapshot_resume, dict):
                resume_json = snapshot_resume
            if isinstance(snapshot_blueprint, dict):
                frozen_blueprint = snapshot_blueprint
            if isinstance(snapshot_job, dict):
                frozen_jd = str(snapshot_job.get("job_description") or "")
                frozen_role = str(snapshot_job.get("role") or "")
                frozen_company = str(snapshot_job.get("company") or "")
                frozen_tech_stack = _string_list(snapshot_job.get("tech_stack") or [], 18)
                requirements = snapshot_job.get("normalized_requirements")
                frozen_requirements = requirements if isinstance(requirements, dict) else frozen_requirements
            snapshot_profile_type = str(snapshot_row[3] or "")
        except Exception:
            logger.warning("Immutable technical attempt context could not be decrypted", exc_info=True)

    # Compatibility path for interviews created before immutable resume/job
    # references were introduced. New blueprint starts never depend on mutable
    # UserInfo state here.
    if not resume_json:
        legacy_profile = await async_execute(
            """
            SELECT resume_json, profile_json, external_profile_signals
            FROM UserInfo WHERE user_id = %s
            """,
            (user_id,), fetchone=True,
        )
        if legacy_profile:
            resume_json = _safe_json_value(legacy_profile[0], {}) or {}
            profile_json = _safe_json_value(legacy_profile[1], {}) or {}
            external_signals = _safe_json_value(legacy_profile[2], {}) or {}
    if not isinstance(resume_json, dict):
        resume_json = {}
    if not isinstance(profile_json, dict):
        profile_json = {}
    if not isinstance(external_signals, dict):
        external_signals = {}

    merged_profile = _merge_profile_payloads(resume_json, profile_json)
    anchors = _profile_anchor_context(merged_profile, external_signals)

    blueprint_sections = frozen_blueprint.get("battlegrounds") or []
    if not isinstance(blueprint_sections, list):
        blueprint_sections = []
    mistake_history: List[Dict[str, Any]] = []
    for section in blueprint_sections:
        if not isinstance(section, dict) or not isinstance(section.get("prior_weakness"), dict):
            continue
        weakness = section["prior_weakness"]
        mistake_history.append({
            "source": "frozen_blueprint",
            "type": weakness.get("category") or "technical_weakness",
            "key": weakness.get("skill_key") or weakness.get("key") or "",
            "title": weakness.get("label") or section.get("label") or "",
            "confidence": weakness.get("confidence_score") or weakness.get("confidence"),
        })

    # Blueprints created before weakness snapshots were introduced still need
    # historical evidence to personalize the round. New blueprints remain
    # immutable because their embedded weakness snapshot wins and skips these
    # mutable compatibility reads.
    if not mistake_history:
        try:
            mistake_rows = await async_execute(
                """
                SELECT mistake_type, mistake_key, occurrence_count, evidence
                FROM TechnicalMistakeClusters
                WHERE user_id = %s
                ORDER BY occurrence_count DESC, last_seen_at DESC
                LIMIT 8
                """,
                (user_id,),
                fetchall=True,
            )
            for row in mistake_rows or []:
                mistake_history.append({
                    "source": "technical_history",
                    "type": row[0] or "technical_weakness",
                    "key": row[1] or "",
                    "title": str(row[1] or "").replace("_", " "),
                    "occurrences": int(row[2] or 0),
                    "evidence": _json_value(row[3], []),
                })
        except Exception:
            logger.warning("Legacy technical mistake history could not be loaded", exc_info=True)

        try:
            mission_rows = await async_execute(
                """
                SELECT weakness_type, skill_key, title, evidence_summary, priority_score
                FROM ImprovementMissions
                WHERE user_id = %s AND status IN ('active', 'awaiting_validation')
                ORDER BY priority_score DESC, updated_at DESC
                LIMIT 6
                """,
                (user_id,),
                fetchall=True,
            )
            for row in mission_rows or []:
                mistake_history.append({
                    "source": "improve_mission",
                    "type": row[0] or "technical_weakness",
                    "key": row[1] or "",
                    "title": row[2] or "",
                    "evidence": row[3] or "",
                    "confidence": row[4],
                })
        except Exception:
            logger.warning("Legacy Improve weakness history could not be loaded", exc_info=True)

    profile_type = normalize_profile_type(snapshot_profile_type or settings_json.get("profile_type"))
    configured_skills = _string_list(
        settings_json.get("target_skills")
        or settings_json.get("tech_stack")
        or frozen_tech_stack
        or [],
        18,
    )
    target_skills = _string_list([*configured_skills, *(anchors.get("skills") or [])], 18)
    encrypted_jd = settings_json.get("job_description_encrypted")
    job_desc = ""
    if encrypted_jd:
        try:
            job_desc = decrypt_data(str(encrypted_jd))
        except Exception:
            logger.warning("Interview JD snapshot could not be decrypted")
    job_desc = (job_desc or frozen_jd or str(settings_json.get("job_description") or ""))[:12000]
    requirement_topics = _string_list(
        frozen_requirements.get("requirements")
        or frozen_requirements.get("skills")
        or [],
        12,
    )
    blueprint_topics = _string_list(
        [
            section.get("label")
            for section in blueprint_sections
            if isinstance(section, dict) and section.get("label")
        ],
        12,
    )
    resolved_title = (
        (f"{frozen_role} at {frozen_company}" if frozen_role and frozen_company else frozen_role)
        or job_title
        or settings_json.get("job_title")
        or anchors.get("target_role")
        or "Software Engineer"
    )

    # For custom tier, dynamically adjust difficulty based on JD/title
    if profile_type == "custom":
        custom_targets, custom_labels = _custom_tier_difficulty(job_desc, resolved_title)
    else:
        custom_targets, custom_labels = None, None

    return {
        "job_title": resolved_title,
        "job_description": job_desc,
        "target_skills": target_skills,
        "programming_language": _selected_programming_language(settings_json),
        "technical_round_types": _normalize_round_types(
            settings_json.get("technical_rounds")
            or settings_json.get("technical_round_types")
            or ["coding", "debugging"]
        ),
        "technical_topics": _string_list(
            [*(settings_json.get("technical_topics") or []), *requirement_topics, *blueprint_topics],
            20,
        ),
        "question_count": max(1, min(12, int(settings_json.get("question_count") or 2))),
        "duration_minutes": max(10, min(120, int(settings_json.get("duration_minutes") or 60))),
        "interview_mode": str(settings_json.get("interview_mode") or "mock").strip().lower(),
        "difficulty_level": str(settings_json.get("difficulty_level") or "adaptive").strip().lower(),
        "personalization_anchors": anchors,
        "mistake_history": mistake_history,
        "blueprint_hash": frozen_blueprint.get("blueprint_hash"),
        "blueprint_sections": blueprint_sections,
        "job_profile_id": frozen_row[4] if frozen_row else None,
        "resume_id": frozen_row[3] if frozen_row else None,
        "profile_type": profile_type,
        "custom_targets": custom_targets,
        "custom_labels": custom_labels,
        "tier_followup_prompts": {
            "interview": settings_json.get("profile_instruction") or "",
            "technical": settings_json.get("technical_instruction") or "",
            "followup": settings_json.get("followup_instruction") or "",
        },
        "interview_id": interview_id,
    }


def _starter_code_for_python() -> str:
    return (
        "import sys\n\n"
        "def solve():\n"
        "    data = sys.stdin.read().strip().split()\n"
        "    # Parse input and write your solution.\n"
        "    pass\n\n"
        "if __name__ == \"__main__\":\n"
        "    solve()\n"
    )


def _starter_code_for_cpp() -> str:
    return (
        "#include <bits/stdc++.h>\n"
        "using namespace std;\n\n"
        "int main() {\n"
        "    ios::sync_with_stdio(false);\n"
        "    cin.tie(nullptr);\n"
        "    // Parse input and write your solution.\n"
        "    return 0;\n"
        "}\n"
    )


def _starter_code_for_javascript() -> str:
    return (
        "const fs = require('fs');\n\n"
        "const input = fs.readFileSync(0, 'utf8').trim().split(/\\s+/);\n"
        "// Parse input and write your solution.\n"
        "// Use console.log(...) for output.\n"
    )


def _starter_code_for_java() -> str:
    return (
        "import java.io.*;\n"
        "import java.util.*;\n\n"
        "public class Main {\n"
        "    public static void main(String[] args) throws Exception {\n"
        "        FastScanner fs = new FastScanner(System.in);\n"
        "        StringBuilder out = new StringBuilder();\n"
        "        // Parse input and write your solution.\n"
        "        System.out.print(out.toString());\n"
        "    }\n\n"
        "    static class FastScanner {\n"
        "        private final InputStream in;\n"
        "        private final byte[] buffer = new byte[1 << 16];\n"
        "        private int ptr = 0, len = 0;\n"
        "        FastScanner(InputStream is) { in = is; }\n"
        "        private int read() throws IOException {\n"
        "            if (ptr >= len) { len = in.read(buffer); ptr = 0; }\n"
        "            return len <= 0 ? -1 : buffer[ptr++];\n"
        "        }\n"
        "        String next() throws IOException {\n"
        "            StringBuilder sb = new StringBuilder();\n"
        "            int c;\n"
        "            do { c = read(); } while (c <= ' ' && c != -1);\n"
        "            while (c > ' ') { sb.append((char)c); c = read(); }\n"
        "            return sb.length() == 0 ? null : sb.toString();\n"
        "        }\n"
        "    }\n"
        "}\n"
    )


def _starter_code_by_language() -> Dict[str, str]:
    return {
        "python": _starter_code_for_python(),
        "javascript": _starter_code_for_javascript(),
        "cpp": _starter_code_for_cpp(),
        "java": _starter_code_for_java(),
    }


def _generation_messages(
    profile_type: str,
    interview_id: str,
    attempt: int,
    generation_context: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, str]]:
    normalized = normalize_profile_type(profile_type)
    profile_config = get_profile_config(normalized)
    context = generation_context or {}

    # Use dynamic targets for custom tier, else use defaults
    if normalized == "custom" and context.get("custom_targets"):
        targets = context["custom_targets"]
        diff_labels = context["custom_labels"]
    else:
        targets = CODEFORCES_RATING_TARGETS[normalized]
        diff_labels = DIFFICULTY_LABELS[normalized]

    today = date.today().isoformat()
    seed = _stable_seed(interview_id, normalized, str(attempt), today)
    job_title = context.get("job_title") or "Software Engineer"
    job_description = context.get("job_description") or ""
    target_skills = context.get("target_skills") or []

    context_payload = {
        "role": job_title,
        "target_skills": target_skills,
    }
    if normalized == "custom" and job_description:
        context_payload["job_description"] = job_description[:1500]
    if "personalization_anchors" in context:
        context_payload["personalization_anchors"] = context["personalization_anchors"]
    if "mistake_history" in context:
        context_payload["mistake_history"] = context["mistake_history"]

    tier_guidance = ""
    if normalized == "top_tier":
        tier_guidance = (
            "\n\nTIER GUIDANCE (Top Tier / FAANG):\n"
            "- Generate problems that would realistically appear in Google, Meta, Amazon, or Stripe interviews.\n"
            "- Problem 1 should test multi-step reasoning (e.g., graph + DP, binary search on answer, monotonic stack).\n"
            "- Problem 2 should require advanced algorithmic thinking (e.g., segment tree, trie, advanced DP, union-find).\n"
            "- Both problems must have non-trivial edge cases and require optimal time/space complexity.\n"
            "- Avoid basic array/string problems that any beginner could solve."
        )
    elif normalized == "mid_tier":
        tier_guidance = (
            "\n\nTIER GUIDANCE (Mid Tier / Product Companies):\n"
            "- Generate problems typical of Atlassian, Shopify, Freshworks, Razorpay interviews.\n"
            "- Problem 1 should test clean implementation of a standard pattern (hash map, two-pointer, BFS).\n"
            "- Problem 2 should be a slightly harder variant requiring careful edge-case handling.\n"
            "- Focus on readable, correct code over clever optimization.\n"
            "- Both problems should be solvable within 25-30 minutes by a competent mid-level engineer."
        )
    elif normalized == "startup":
        tier_guidance = (
            "\n\nTIER GUIDANCE (Startup):\n"
            "- Generate problems typical of early-stage startup interviews where speed matters.\n"
            "- Problem 1 should be solvable in 10-15 minutes with a clean, working solution.\n"
            "- Problem 2 should test practical thinking — a problem that could arise in real product development.\n"
            "- Prefer greedy, hash map, sorting, and simple recursion patterns.\n"
            "- Avoid problems requiring 30+ minutes of algorithmic thinking.\n"
            "- Prioritize problems that test 'can this person build working software quickly'."
        )
    elif normalized == "custom":
        tier_guidance = (
            "\n\nTIER GUIDANCE (Custom / Company-Specific):\n"
            "- Tailor problems specifically to the job description and company provided.\n"
            "- If the JD mentions specific technologies, frame problems around those domains.\n"
            "- Match difficulty to the seniority level implied by the role title.\n"
            "- Problems should feel relevant to the actual work described in the JD."
        )

    return [
        {
            "role": "system",
            "content": (
                "You generate original competitive-programming interview problems as strict JSON. "
                "Return only JSON that matches the requested schema. Every test case must have a deterministic "
                "single stdin string and exact expected stdout. Hidden tests must not duplicate visible tests. "
                "The Python reference_solution must read stdin and print stdout exactly.\n"
                "TITLE RULES: Each title must be at most 6 words and short (e.g. 'Two Sum', 'Valid Parentheses', "
                "'LRU Cache', 'Merge Intervals'). Do NOT use branded names, company names, or long descriptions."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Generate exactly 2 original coding problems for a {job_title} interview "
                f"at {profile_config['label']} level.\n"
                f"Current date: {today}. Use this date only as a generation/versioning signal.\n"
                f"Interview id seed: {seed}.\n"
                f"Company style: {profile_config['technical_instruction']}\n"
                f"Target skills: {', '.join(target_skills) if target_skills else 'general DSA and problem solving'}\n"
                f"Context:\n{data_block('generation_context', json.dumps(context_payload, default=str)[:3500])}\n\n"
                f"Problem 1: difficulty={diff_labels[0]}, CF rating={targets[0]}.\n"
                f"Problem 2: difficulty={diff_labels[1]}, CF rating={targets[1]}.\n\n"
                "REQUIREMENTS:\n"
                "- Title: max 6 words, short and clean (e.g. 'Two Sum', 'Max Subarray')\n"
                "- Original DSA interview task only. Do not reproduce leaked or branded company questions.\n"
                "- Prefer arrays, strings, hash maps, trees, graphs, heaps, binary search, sliding window, recursion/backtracking, or dynamic programming.\n"
                "- Each problem: title, difficulty, cf_rating, algorithm_pattern, statement, "
                "input_format, output_format, constraints\n"
                "- Exactly 3 visible_tests with explanations, exactly 7 hidden_tests\n"
                "- Hidden tests MUST include edge cases: empty/minimal input, max constraints, "
                "negative numbers, duplicates, already-sorted, single element\n"
                "- Each hidden test should include a tag from: empty_input, duplicate_values, "
                "large_input, negative_values, boundary_index\n"
                "- expected_time_complexity, expected_space_complexity, one-line hint\n"
                "- Python reference_solution using stdin/stdout\n"
                "- No functions-only tasks, no interactive problems, no randomness, "
                "no external libraries beyond Python standard library"
                + tier_guidance
            ),
        },
    ]


def _require_text(value: Any, field: str, min_length: int = 1) -> str:
    text = str(value or "").strip()
    if len(text) < min_length:
        raise ValueError(f"{field} is required")
    return text


def _normalize_test_case(case: Dict[str, Any], field: str, require_explanation: bool) -> Dict[str, str]:
    if not isinstance(case, dict):
        raise ValueError(f"{field} must be an object")
    normalized = {
        "stdin": _require_text(case.get("stdin"), f"{field}.stdin"),
        "expected": _require_text(case.get("expected"), f"{field}.expected"),
    }
    if require_explanation:
        normalized["explanation"] = _require_text(case.get("explanation"), f"{field}.explanation")
    else:
        tag = str(case.get("tag") or case.get("category") or "").strip().lower().replace(" ", "_").replace("-", "_")
        if tag in HIDDEN_TEST_TAGS:
            normalized["tag"] = tag
    return normalized


async def _validate_reference_solution(problem: Dict[str, Any], all_cases: List[Dict[str, str]]) -> None:
    reference_solution = _require_text(problem.get("reference_solution"), "reference_solution", min_length=40)
    tasks = [
        _execute_code("python", reference_solution, case["stdin"])
        for case in all_cases
    ]
    results = await asyncio.gather(*tasks)
    for index, (case, result) in enumerate(zip(all_cases, results), start=1):
        verdict = _judge0_verdict(result)
        if verdict != "Accepted":
            raise ValueError(f"reference solution failed case {index}: {verdict}")
        stdout_normalized = result.get("stdout", "")
        if not _outputs_match(stdout_normalized, case["expected"]):
            raise ValueError(
                f"reference solution output mismatch on case {index}: expected {case['expected']!r}, got {stdout_normalized!r}"
            )


async def _normalize_generated_problem(
    problem: Dict[str, Any],
    *,
    profile_type: str,
    profile_label: str,
    expected_difficulty: str,
    expected_rating: int,
    round_number: int,
    generation_context: Optional[Dict[str, Any]] = None,
    generated_source: str = "ai",
    source_label: str = "AI",
    generation_error: Optional[str] = None,
    validate_reference: bool = True,
) -> Dict[str, Any]:
    if not isinstance(problem, dict):
        raise ValueError("problem must be an object")

    visible_raw = problem.get("visible_tests")
    hidden_raw = problem.get("hidden_tests")
    if not isinstance(visible_raw, list) or len(visible_raw) != 3:
        raise ValueError("each problem must include exactly 3 visible tests")
    if not isinstance(hidden_raw, list) or len(hidden_raw) != 7:
        raise ValueError("each problem must include exactly 7 hidden tests")

    visible_tests = [_normalize_test_case(case, f"visible_tests[{i}]", True) for i, case in enumerate(visible_raw)]
    hidden_tests = [_normalize_test_case(case, f"hidden_tests[{i}]", False) for i, case in enumerate(hidden_raw)]
    for index, case in enumerate(hidden_tests):
        case.setdefault("tag", HIDDEN_TEST_TAGS[index % len(HIDDEN_TEST_TAGS)])
    all_stdin = [case["stdin"] for case in [*visible_tests, *hidden_tests]]
    if len(set(all_stdin)) != len(all_stdin):
        raise ValueError("test case inputs must be unique")

    rating = int(problem.get("cf_rating") or expected_rating)
    if rating != expected_rating:
        rating = expected_rating

    # Truncate title to max 40 chars / ~6 words
    raw_title = _require_text(problem.get("title"), "title")
    if len(raw_title) > 40:
        raw_title = raw_title[:40].rsplit(" ", 1)[0]

    normalized = {
        "generated_source": generated_source,
        "source": source_label,
        "generation_error": generation_error or "",
        "executor": _active_executor_name(),
        "title": raw_title,
        "problem_title": raw_title,
        "difficulty": expected_difficulty,
        "cf_rating": rating,
        "rating": rating,
        "algorithm_pattern": _require_text(problem.get("algorithm_pattern"), "algorithm_pattern"),
        "statement": _require_text(problem.get("statement"), "statement", min_length=80),
        "input_format": _require_text(problem.get("input_format"), "input_format"),
        "output_format": _require_text(problem.get("output_format"), "output_format"),
        "constraints": _require_text(problem.get("constraints"), "constraints"),
        "visible_tests": visible_tests,
        "hidden_tests": hidden_tests,
        "expected_time_complexity": _require_text(problem.get("expected_time_complexity"), "expected_time_complexity"),
        "expected_space_complexity": _require_text(problem.get("expected_space_complexity"), "expected_space_complexity"),
        "hint": _require_text(problem.get("hint"), "hint"),
        "reference_solution": _require_text(problem.get("reference_solution"), "reference_solution", min_length=40),
        "company_profile": profile_type,
        "profile_type": profile_type,
        "company_profile_label": profile_label,
        "job_title": (generation_context or {}).get("job_title") or "",
        "target_skills": (generation_context or {}).get("target_skills") or [],
        "programming_language": (generation_context or {}).get("programming_language") or "python",
        "personalization_anchors": (generation_context or {}).get("personalization_anchors") or {},
        "mistake_history": (generation_context or {}).get("mistake_history") or [],
        "tier_followup_prompts": (generation_context or {}).get("tier_followup_prompts") or {},
        "round_number": round_number,
        "starter_code_by_language": _starter_code_by_language(),
        "hidden_validation_tags": ["correctness", "edge_cases", "complexity"],
    }
    if validate_reference:
        await _validate_reference_solution(normalized, [*visible_tests, *hidden_tests])
    return normalized


def _fallback_anchor_text(generation_context: Optional[Dict[str, Any]]) -> Dict[str, str]:
    context = generation_context or {}
    skills = _string_list(context.get("target_skills") or [], 5)
    role = str(context.get("job_title") or "Software Engineer").strip()

    # Extract project name from personalization_anchors if available
    project_name = ""
    anchors_data = context.get("personalization_anchors") or {}
    if isinstance(anchors_data, dict):
        projects = anchors_data.get("projects") or []
        if projects and isinstance(projects[0], dict):
            project_name = projects[0].get("name") or ""

    return {
        "role": role,
        "skills": ", ".join(skills) or "arrays, strings, and algorithms",
        "project": project_name,
    }


def _fallback_problem_candidates(anchors: Dict[str, str], targets: List[int], profile_type: str) -> List[Dict[str, Any]]:
    # The algorithm, I/O contract, reference solution, and tests stay fixed. Only
    # this bounded context sentence is personalized.
    role = anchors.get("role") or "Software Engineer"
    project = anchors.get("project") or ""
    skill_focus = anchors.get("skills") or "core algorithms"
    personalization = f"This exercise is selected for a {role} candidate"
    if project:
        personalization += f" and uses the candidate's {project} project as familiar context"
    personalization += f", with emphasis on transferable reasoning for {skill_focus}. "
    prefix = ""

    all_candidates = [
        {
            "title": "Pair Sum",
            "difficulty": "Easy",
            "cf_rating": targets[0] if len(targets) > 0 else 1000,
            "algorithm_pattern": "hash set",
            "statement": (
                f"{prefix}You are given n integers and a target value. Determine whether "
                "two different integers in the list can be paired to exactly equal the target. "
                "Each integer may be used at most once."
            ),
            "input_format": "The first line contains n and target. The second line contains n integers.",
            "output_format": "Print YES if a valid pair exists, otherwise print NO.",
            "constraints": "2 <= n <= 200000; -10^9 <= value, target <= 10^9.",
            "visible_tests": [
                {"stdin": "4 9\n2 7 11 15\n", "expected": "YES\n", "explanation": "2 and 7 sum to 9."},
                {"stdin": "5 50\n1 4 8 12 16\n", "expected": "NO\n", "explanation": "No two values reach 50."},
                {"stdin": "2 10\n5 5\n", "expected": "YES\n", "explanation": "The two 5 values sum to 10."},
            ],
            "hidden_tests": [
                {"stdin": "3 0\n-4 4 9\n", "expected": "YES\n"},
                {"stdin": "6 14\n1 2 3 4 5 6\n", "expected": "NO\n"},
                {"stdin": "7 -3\n-8 1 5 9 2 4 6\n", "expected": "YES\n"},
                {"stdin": "4 100\n100 1 2 3\n", "expected": "NO\n"},
                {"stdin": "5 6\n3 3 10 -2 8\n", "expected": "YES\n"},
                {"stdin": "8 17\n9 1 6 11 4 13 2 20\n", "expected": "YES\n"},
                {"stdin": "2 -10\n-4 -5\n", "expected": "NO\n"},
            ],
            "expected_time_complexity": "O(n)",
            "expected_space_complexity": "O(n)",
            "hint": "Store seen numbers and look for the complement.",
            "reference_solution": (
                "import sys\n\n"
                "def solve():\n"
                "    data = list(map(int, sys.stdin.read().strip().split()))\n"
                "    if not data:\n"
                "        return\n"
                "    n, target = data[0], data[1]\n"
                "    nums = data[2:2+n]\n"
                "    seen = set()\n"
                "    for value in nums:\n"
                "        if target - value in seen:\n"
                "            print('YES')\n"
                "            return\n"
                "        seen.add(value)\n"
                "    print('NO')\n\n"
                "if __name__ == '__main__':\n"
                "    solve()\n"
            ),
        },
        {
            "title": "Max Window Sum",
            "difficulty": "Medium",
            "cf_rating": targets[1] if len(targets) > 1 else 1200,
            "algorithm_pattern": "sliding window",
            "statement": (
                "You are given an array of n integers and a window length k. "
                "Find the maximum sum across all contiguous subarrays of exactly k elements."
            ),
            "input_format": "The first line contains n and k. The second line contains n integers.",
            "output_format": "Print one integer, the maximum sum across all length-k windows.",
            "constraints": "1 <= k <= n <= 200000; -10^9 <= value <= 10^9.",
            "visible_tests": [
                {"stdin": "5 2\n4 -1 3 2 8\n", "expected": "10\n", "explanation": "The best window is [2, 8]."},
                {"stdin": "4 4\n1 2 3 4\n", "expected": "10\n", "explanation": "Only the full array is available."},
                {"stdin": "6 3\n-5 -2 -7 -1 -3 -4\n", "expected": "-8\n", "explanation": "Least negative window is [-1, -3, -4]."},
            ],
            "hidden_tests": [
                {"stdin": "3 1\n9 -2 7\n", "expected": "9\n"},
                {"stdin": "6 2\n1 100 -50 80 2 3\n", "expected": "81\n"},
                {"stdin": "7 3\n5 5 5 5 5 5 5\n", "expected": "15\n"},
                {"stdin": "8 4\n10 -1 -1 -1 10 -1 -1 10\n", "expected": "18\n"},
                {"stdin": "5 5\n-1 -2 -3 -4 -5\n", "expected": "-15\n"},
                {"stdin": "9 3\n2 4 6 8 10 12 14 16 18\n", "expected": "48\n"},
                {"stdin": "4 2\n-10 50 -10 50\n", "expected": "40\n"},
            ],
            "expected_time_complexity": "O(n)",
            "expected_space_complexity": "O(1)",
            "hint": "Slide the window: subtract the outgoing element and add the incoming one.",
            "reference_solution": (
                "import sys\n\n"
                "def solve():\n"
                "    data = list(map(int, sys.stdin.read().strip().split()))\n"
                "    if not data:\n"
                "        return\n"
                "    n, k = data[0], data[1]\n"
                "    values = data[2:2+n]\n"
                "    current = sum(values[:k])\n"
                "    best = current\n"
                "    for index in range(k, n):\n"
                "        current += values[index] - values[index - k]\n"
                "        if current > best:\n"
                "            best = current\n"
                "    print(best)\n\n"
                "if __name__ == '__main__':\n"
                "    solve()\n"
            ),
        },
        {
            "title": "Longest Chain in DAG",
            "difficulty": "Hard",
            "cf_rating": targets[1] if len(targets) > 1 else 1400,
            "algorithm_pattern": "topological sort + DP",
            "statement": (
                "You are given a directed acyclic graph with n nodes and m edges. "
                "Each directed edge a b means node a must be processed before node b. "
                "Find the length of the longest chain (number of nodes) in the graph."
            ),
            "input_format": "The first line contains n and m. Each of the next m lines contains a directed edge a b.",
            "output_format": "Print one integer, the number of nodes in the longest chain.",
            "constraints": "1 <= n <= 200000; 0 <= m <= 200000; the graph is a DAG.",
            "visible_tests": [
                {"stdin": "4 3\n1 2\n2 3\n1 4\n", "expected": "3\n", "explanation": "Chain 1 -> 2 -> 3 has length 3."},
                {"stdin": "5 0\n", "expected": "1\n", "explanation": "No edges, every node is its own chain."},
                {"stdin": "6 6\n1 2\n1 3\n2 4\n3 4\n4 5\n5 6\n", "expected": "5\n", "explanation": "1 -> 2 -> 4 -> 5 -> 6."},
            ],
            "hidden_tests": [
                {"stdin": "3 2\n1 2\n2 3\n", "expected": "3\n"},
                {"stdin": "4 2\n1 3\n2 3\n", "expected": "2\n"},
                {"stdin": "7 6\n1 2\n2 4\n4 7\n1 3\n3 5\n5 6\n", "expected": "4\n"},
                {"stdin": "1 0\n", "expected": "1\n"},
                {"stdin": "6 5\n1 2\n1 3\n1 4\n4 5\n5 6\n", "expected": "4\n"},
                {"stdin": "8 7\n1 2\n2 3\n3 8\n4 5\n5 6\n6 7\n7 8\n", "expected": "5\n"},
                {"stdin": "5 4\n2 5\n1 5\n3 5\n4 5\n", "expected": "2\n"},
            ],
            "expected_time_complexity": "O(n + m)",
            "expected_space_complexity": "O(n + m)",
            "hint": "Process zero-indegree nodes first and relax the depth of each neighbor.",
            "reference_solution": (
                "import sys\n"
                "from collections import deque\n\n"
                "def solve():\n"
                "    data = list(map(int, sys.stdin.read().strip().split()))\n"
                "    if not data:\n"
                "        return\n"
                "    n, m = data[0], data[1]\n"
                "    graph = [[] for _ in range(n)]\n"
                "    indegree = [0] * n\n"
                "    pos = 2\n"
                "    for _ in range(m):\n"
                "        a, b = data[pos] - 1, data[pos + 1] - 1\n"
                "        pos += 2\n"
                "        graph[a].append(b)\n"
                "        indegree[b] += 1\n"
                "    depth = [1] * n\n"
                "    queue = deque(i for i, degree in enumerate(indegree) if degree == 0)\n"
                "    while queue:\n"
                "        node = queue.popleft()\n"
                "        for nxt in graph[node]:\n"
                "            if depth[node] + 1 > depth[nxt]:\n"
                "                depth[nxt] = depth[node] + 1\n"
                "            indegree[nxt] -= 1\n"
                "            if indegree[nxt] == 0:\n"
                "                queue.append(nxt)\n"
                "    print(max(depth) if depth else 0)\n\n"
                "if __name__ == '__main__':\n"
                "    solve()\n"
            ),
        },
    ]
    all_candidates.extend([
        {
            "title": "Target Subarray Count",
            "difficulty": "Medium",
            "cf_rating": targets[0] if len(targets) > 0 else 1200,
            "algorithm_pattern": "prefix sum + hashmap",
            "statement": (
                f"{prefix}Given an array of n integers and a target k, count how many contiguous "
                "subarrays have sum exactly k. Values may be negative, so a two-pointer solution is not sufficient."
            ),
            "input_format": "The first line contains n and k. The second line contains n integers.",
            "output_format": "Print one integer, the number of subarrays with sum exactly k.",
            "constraints": "1 <= n <= 200000; -10^9 <= value, k <= 10^9.",
            "visible_tests": [
                {"stdin": "5 3\n1 2 1 2 1\n", "expected": "4\n", "explanation": "Four windows sum to 3."},
                {"stdin": "3 0\n0 0 0\n", "expected": "6\n", "explanation": "Every non-empty subarray sums to 0."},
                {"stdin": "4 -1\n-1 1 -1 1\n", "expected": "3\n", "explanation": "Negative targets are valid."},
            ],
            "hidden_tests": [
                {"stdin": "1 5\n5\n", "expected": "1\n"},
                {"stdin": "4 10\n1 2 3 4\n", "expected": "1\n"},
                {"stdin": "6 2\n1 -1 1 -1 1 -1\n", "expected": "0\n"},
                {"stdin": "5 1\n1 0 0 0 0\n", "expected": "5\n"},
                {"stdin": "5 -2\n-2 -2 2 -2 2\n", "expected": "5\n"},
                {"stdin": "7 4\n2 2 2 2 -2 4 0\n", "expected": "6\n"},
                {"stdin": "3 7\n8 -1 0\n", "expected": "1\n"},
            ],
            "expected_time_complexity": "O(n)",
            "expected_space_complexity": "O(n)",
            "hint": "Track how often each prefix sum has appeared.",
            "reference_solution": (
                "import sys\n"
                "from collections import defaultdict\n\n"
                "def solve():\n"
                "    data = list(map(int, sys.stdin.read().strip().split()))\n"
                "    if not data:\n"
                "        return\n"
                "    n, k = data[0], data[1]\n"
                "    nums = data[2:2+n]\n"
                "    seen = defaultdict(int)\n"
                "    seen[0] = 1\n"
                "    prefix = 0\n"
                "    ans = 0\n"
                "    for value in nums:\n"
                "        prefix += value\n"
                "        ans += seen[prefix - k]\n"
                "        seen[prefix] += 1\n"
                "    print(ans)\n\n"
                "if __name__ == '__main__':\n"
                "    solve()\n"
            ),
        },
        {
            "title": "Lower Bound Queries",
            "difficulty": "Easy",
            "cf_rating": targets[0] if len(targets) > 0 else 1000,
            "algorithm_pattern": "binary search",
            "statement": (
                f"{prefix}You are given a sorted non-decreasing array and q query values. "
                "For each query x, print the first 0-based index whose value is at least x, or -1 if no such index exists."
            ),
            "input_format": "The first line contains n and q. The second line contains n integers. The third line contains q integers.",
            "output_format": "Print q integers separated by spaces.",
            "constraints": "1 <= n, q <= 200000; -10^9 <= values, queries <= 10^9.",
            "visible_tests": [
                {"stdin": "5 3\n1 3 3 7 9\n3 4 10\n", "expected": "1 3 -1\n", "explanation": "First positions are 1, 3, and missing."},
                {"stdin": "4 2\n-5 -2 0 10\n-3 -6\n", "expected": "1 0\n", "explanation": "Lower bound handles negatives."},
                {"stdin": "3 3\n2 2 2\n2 1 3\n", "expected": "0 0 -1\n", "explanation": "Duplicates return the first index."},
            ],
            "hidden_tests": [
                {"stdin": "1 1\n5\n5\n", "expected": "0\n"},
                {"stdin": "1 2\n5\n6 4\n", "expected": "-1 0\n"},
                {"stdin": "5 4\n1 2 4 8 16\n0 1 15 17\n", "expected": "0 0 4 -1\n"},
                {"stdin": "6 3\n-10 -10 -3 0 1 1\n-10 -9 1\n", "expected": "0 2 4\n"},
                {"stdin": "3 1\n100 200 300\n250\n", "expected": "2\n"},
                {"stdin": "4 4\n1 1 1 1\n1 2 0 -1\n", "expected": "0 -1 0 0\n"},
                {"stdin": "5 2\n2 4 6 8 10\n7 8\n", "expected": "3 3\n"},
            ],
            "expected_time_complexity": "O((n + q) log n)",
            "expected_space_complexity": "O(1) beyond output",
            "hint": "Use a standard lower-bound binary search for each query.",
            "reference_solution": (
                "import sys\n"
                "from bisect import bisect_left\n\n"
                "def solve():\n"
                "    data = list(map(int, sys.stdin.read().strip().split()))\n"
                "    if not data:\n"
                "        return\n"
                "    n, q = data[0], data[1]\n"
                "    arr = data[2:2+n]\n"
                "    queries = data[2+n:2+n+q]\n"
                "    out = []\n"
                "    for x in queries:\n"
                "        i = bisect_left(arr, x)\n"
                "        out.append(str(i if i < n else -1))\n"
                "    print(' '.join(out))\n\n"
                "if __name__ == '__main__':\n"
                "    solve()\n"
            ),
        },
        {
            "title": "Largest Island",
            "difficulty": "Medium",
            "cf_rating": targets[1] if len(targets) > 1 else 1400,
            "algorithm_pattern": "grid BFS",
            "statement": (
                f"{prefix}Given an n by m grid of 0s and 1s, find the size of the largest connected "
                "component of 1s using 4-directional movement."
            ),
            "input_format": "The first line contains n and m. Each of the next n lines contains m digits or space-separated 0/1 values.",
            "output_format": "Print one integer, the largest island size.",
            "constraints": "1 <= n, m <= 1000; n*m <= 200000.",
            "visible_tests": [
                {"stdin": "3 4\n1100\n0110\n0011\n", "expected": "6\n", "explanation": "All ones are connected diagonally through 4-neighbor steps via the middle."},
                {"stdin": "2 3\n000\n000\n", "expected": "0\n", "explanation": "There are no islands."},
                {"stdin": "1 5\n10101\n", "expected": "1\n", "explanation": "Separated ones are distinct islands."},
            ],
            "hidden_tests": [
                {"stdin": "1 1\n1\n", "expected": "1\n"},
                {"stdin": "1 1\n0\n", "expected": "0\n"},
                {"stdin": "2 2\n11\n11\n", "expected": "4\n"},
                {"stdin": "3 3\n100\n010\n001\n", "expected": "1\n"},
                {"stdin": "4 4\n1110\n0010\n0111\n0001\n", "expected": "8\n"},
                {"stdin": "2 5\n1 0 1 1 1\n1 0 0 0 1\n", "expected": "4\n"},
                {"stdin": "3 5\n11111\n00001\n11111\n", "expected": "11\n"},
            ],
            "expected_time_complexity": "O(n*m)",
            "expected_space_complexity": "O(n*m)",
            "hint": "Run BFS/DFS from each unvisited land cell.",
            "reference_solution": (
                "import sys\n"
                "from collections import deque\n\n"
                "def solve():\n"
                "    lines = [line.strip() for line in sys.stdin.read().splitlines() if line.strip()]\n"
                "    if not lines:\n"
                "        return\n"
                "    n, m = map(int, lines[0].split())\n"
                "    grid = []\n"
                "    for line in lines[1:1+n]:\n"
                "        parts = line.split()\n"
                "        grid.append(parts if len(parts) == m else list(line.strip()))\n"
                "    seen = [[False] * m for _ in range(n)]\n"
                "    best = 0\n"
                "    for r in range(n):\n"
                "        for c in range(m):\n"
                "            if grid[r][c] != '1' or seen[r][c]:\n"
                "                continue\n"
                "            q = deque([(r, c)])\n"
                "            seen[r][c] = True\n"
                "            size = 0\n"
                "            while q:\n"
                "                x, y = q.popleft()\n"
                "                size += 1\n"
                "                for dx, dy in ((1,0),(-1,0),(0,1),(0,-1)):\n"
                "                    nx, ny = x + dx, y + dy\n"
                "                    if 0 <= nx < n and 0 <= ny < m and not seen[nx][ny] and grid[nx][ny] == '1':\n"
                "                        seen[nx][ny] = True\n"
                "                        q.append((nx, ny))\n"
                "            best = max(best, size)\n"
                "    print(best)\n\n"
                "if __name__ == '__main__':\n"
                "    solve()\n"
            ),
        },
    ])

    seed = _stable_seed(anchors.get("role", ""), anchors.get("skills", ""), profile_type, date.today().isoformat())
    if profile_type == "top_tier":
        pool = [all_candidates[1], all_candidates[2], all_candidates[3], all_candidates[5]]
        start = seed % len(pool)
        candidates = [pool[start], pool[(start + 1) % len(pool)]]
        candidates[0]["cf_rating"] = targets[0]
        candidates[0]["difficulty"] = "Medium"
        candidates[1]["cf_rating"] = targets[1]
        candidates[1]["difficulty"] = "Hard"
    else:
        pool = [all_candidates[0], all_candidates[1], all_candidates[3], all_candidates[4]]
        start = seed % len(pool)
        candidates = [pool[start], pool[(start + 1) % len(pool)]]
        candidates[0]["cf_rating"] = targets[0]
        candidates[0]["difficulty"] = "Easy"
        candidates[1]["cf_rating"] = targets[1]
        candidates[1]["difficulty"] = "Medium"
    for candidate in candidates:
        candidate["statement"] = personalization + str(candidate.get("statement") or "")
    return candidates


async def _fallback_problem_set(
    profile_type: str,
    profile_label: str,
    targets: List[int],
    generation_context: Optional[Dict[str, Any]],
    reason: str,
) -> List[Dict[str, Any]]:
    anchors = _fallback_anchor_text(generation_context)
    problems = _fallback_problem_candidates(anchors, targets, profile_type)
    normalized_problems = []
    for index, problem in enumerate(problems):
        normalized_problems.append(
            await _normalize_generated_problem(
                problem,
                profile_type=profile_type,
                profile_label=profile_label,
                expected_difficulty=problem["difficulty"],
                expected_rating=targets[index],
                round_number=index + 1,
                generation_context=generation_context,
                generated_source="fallback",
                source_label="Backup",
                generation_error=reason[:500],
                validate_reference=False,
            )
        )
    return normalized_problems


async def _generate_ai_problem_set(
    profile_type: str,
    interview_id: str,
    user_id: str,
    generation_context: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    normalized = normalize_profile_type(profile_type)
    profile_config = get_profile_config(normalized)
    context = generation_context or {}
    # Use dynamic targets for custom tier
    if normalized == "custom" and context.get("custom_targets"):
        targets = context["custom_targets"]
        diff_labels = context["custom_labels"]
    else:
        targets = CODEFORCES_RATING_TARGETS[normalized]
        diff_labels = DIFFICULTY_LABELS[normalized]
    last_error = "invalid generated problem set"
    cache_key = _technical_generation_cache_key(normalized, interview_id, generation_context)
    cached_payload = await _load_cached_generation(cache_key)
    if cached_payload:
        problems = cached_payload.get("problems") if isinstance(cached_payload, dict) else None
        if isinstance(problems, list) and len(problems) == 2:
            try:
                return await asyncio.gather(*[
                    _normalize_generated_problem(
                        problem,
                        profile_type=normalized,
                        profile_label=profile_config["label"],
                        expected_difficulty=diff_labels[index],
                        expected_rating=targets[index],
                        round_number=index + 1,
                        generation_context=generation_context,
                    )
                    for index, problem in enumerate(problems)
                ])
            except Exception as exc:
                logger.warning("Cached technical problem set failed validation: %s", exc)

    for attempt in range(1, AI_GENERATION_MAX_ATTEMPTS + 1):
        try:
            payload = await asyncio.wait_for(
                complete_json_async(
                    _generation_messages(normalized, interview_id, attempt, generation_context),
                    event_type="technical_problem_generation",
                    temperature=0.35,
                    max_tokens=6000,
                    user_id=user_id,
                    interview_id=interview_id,
                    metadata={
                        "profile_type": normalized,
                        "attempt": attempt,
                        "job_title": (generation_context or {}).get("job_title"),
                        "target_skills": (generation_context or {}).get("target_skills") or [],
                    },
                    json_schema=TECHNICAL_PROBLEM_JSON_SCHEMA,
                ),
                timeout=25,
            )
            problems = payload.get("problems") if isinstance(payload, dict) else None
            if not isinstance(problems, list) or len(problems) != 2:
                raise ValueError("AI response must include exactly 2 problems")
            diff_used = diff_labels
            normalized_tasks = [
                _normalize_generated_problem(
                    problem,
                    profile_type=normalized,
                    profile_label=profile_config["label"],
                    expected_difficulty=diff_used[index],
                    expected_rating=targets[index],
                    round_number=index + 1,
                    generation_context=generation_context,
                )
                for index, problem in enumerate(problems)
            ]
            normalized_problems = await asyncio.gather(*normalized_tasks)
            await _save_cached_generation(cache_key, {"problems": problems})
            return normalized_problems
        except HTTPException as exc:
            last_error = str(exc.detail or exc)
            logger.warning("AI problem generation attempt %d failed: %s", attempt, last_error)
        except (LLMRoutingError, ValueError, TypeError, KeyError) as exc:
            last_error = str(exc)
            logger.warning("AI problem generation attempt %d failed: %s", attempt, last_error)
        except asyncio.TimeoutError:
            last_error = "ai_generation_timeout"
            logger.warning("AI problem generation attempt %d timed out", attempt)
        except Exception as exc:
            last_error = str(exc)
            logger.warning("AI problem generation attempt %d failed: %s", attempt, last_error)

    try:
        return await _fallback_problem_set(
            normalized,
            profile_config["label"],
            targets,
            generation_context,
            last_error,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Could not prepare technical problems: {exc}") from exc


def _prompt_from_metadata(metadata: Dict[str, Any]) -> str:
    return "\n\n".join(
        [
            str(metadata.get("statement") or "").strip(),
            "Input Format\n" + str(metadata.get("input_format") or "").strip(),
            "Output Format\n" + str(metadata.get("output_format") or "").strip(),
            "Constraints\n" + str(metadata.get("constraints") or "").strip(),
        ]
    ).strip()


def _decrypt_storage_blob(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, memoryview):
        value = value.tobytes()
    if isinstance(value, (bytes, bytearray)):
        value = bytes(value).decode("utf-8", errors="strict")
    return decrypt_data(str(value))


def _encrypted_json_text(value: Any) -> str:
    return encrypt_data(json.dumps(value, separators=(",", ":"), ensure_ascii=False))


async def _load_active_problem_bank() -> List[Dict[str, Any]]:
    try:
        rows = await async_execute(
            """
            SELECT problem_id, problem_family_id, version, round_type,
                   taxonomy_keys, prerequisite_keys, difficulty, title,
                   problem_statement, spec_json, visible_tests,
                   hidden_tests_encrypted, expected_time_complexity,
                   expected_space_complexity, supported_languages,
                   validator_version, validation_result
            FROM TechnicalProblemBank
            WHERE status = 'active'
            ORDER BY activated_at DESC NULLS LAST, updated_at DESC, problem_id
            LIMIT 100
            """,
            fetchall=True,
        )
    except Exception:
        logger.warning("Active technical problem bank could not be loaded; using authored fallback specs")
        return []

    bank: List[Dict[str, Any]] = []
    for row in rows or []:
        validation = _json_value(row[16], {})
        if not isinstance(validation, dict) or not bool(
            validation.get("passed")
            or validation.get("valid")
            or str(validation.get("status") or "").lower() in {"passed", "validated", "active"}
        ):
            logger.warning("Skipping unvalidated active problem bank entry: %s", row[0])
            continue
        try:
            hidden = json.loads(_decrypt_storage_blob(row[11])) if row[11] else []
        except Exception:
            logger.warning("Skipping problem bank entry with unreadable hidden tests: %s", row[0])
            continue
        bank.append({
            "problem_id": str(row[0]),
            "problem_family_id": str(row[1] or row[0]),
            "version": int(row[2] or 1),
            "round_type": _normalize_round_types([row[3]])[0],
            "taxonomy_keys": _json_value(row[4], []),
            "prerequisite_keys": _json_value(row[5], []),
            "difficulty": str(row[6] or "medium").lower(),
            "title": str(row[7] or "Technical problem"),
            "statement": str(row[8] or ""),
            "spec_json": _json_value(row[9], {}),
            "visible_tests": _json_value(row[10], []),
            "hidden_tests": hidden if isinstance(hidden, list) else [],
            "expected_time_complexity": row[12],
            "expected_space_complexity": row[13],
            "supported_languages": _json_value(row[14], []),
            "validator_version": str(row[15] or "unknown"),
            "validation_result": validation,
            "source": "problem_bank",
        })
    return bank


def _noncoding_authored_spec(round_type: str, context: Dict[str, Any]) -> Dict[str, Any]:
    role = str(context.get("job_title") or "Software Engineer")
    topics = _string_list(context.get("technical_topics") or context.get("target_skills") or [], 4)
    topic = topics[0] if topics else {
        "technical_concept": "reliability",
        "system_design": "a production notification service",
        "ml": "model evaluation and drift",
        "backend": "API reliability and concurrency",
        "database": "transactions and indexing",
        "os": "process scheduling and memory",
        "network": "HTTP, retries, and idempotency",
        "oop": "object boundaries and dependency inversion",
    }.get(round_type, "software engineering fundamentals")
    prompts = {
        "technical_concept": (
            f"For a {role} system, explain {topic}. Describe how it works, when you would use it, "
            "its main trade-offs, and one failure mode you would actively monitor."
        ),
        "system_design": (
            f"Design {topic} for a {role} workload. Walk through requirements, API and data flow, "
            "storage choices, scaling, failure handling, observability, and the trade-offs you made."
        ),
        "ml": (
            f"Explain how you would design and validate {topic} in production. Cover data quality, "
            "offline and online evaluation, serving, monitoring, drift, and rollback."
        ),
        "backend": (
            f"Explain how you would implement {topic} in a production backend. Cover boundaries, "
            "concurrency, failure handling, observability, and testing."
        ),
        "database": (
            f"Reason through {topic} for a high-traffic service. Cover schema design, query plans, "
            "consistency, contention, failure recovery, and measurement."
        ),
        "os": (
            f"Explain {topic} from an operating-system perspective and connect it to an application "
            "performance incident, including diagnosis and mitigation."
        ),
        "network": (
            f"Explain {topic} across a distributed request path. Cover timeouts, retry safety, "
            "partial failure, observability, and security boundaries."
        ),
        "oop": (
            f"Model {topic} using object-oriented design. Explain responsibilities, invariants, "
            "extension points, testability, and where inheritance would be harmful."
        ),
    }
    profile_type = normalize_technical_profile(context.get("profile_type"))
    profile_frame = {
        "top_tier": "Assume top-tier scale, ambiguous requirements, and strict reliability constraints. ",
        "mid_tier": "Use a practical production scenario with clear delivery and testing constraints. ",
        "startup": "Assume a small team, limited runway, fast iteration, and changing requirements. ",
        "custom": "Anchor every choice to the selected job description and company context. ",
    }[profile_type]
    prompt = profile_frame + prompts.get(round_type, prompts["technical_concept"])
    expected_points = [
        {"point_id": f"{round_type}:mechanism", "label": "correct mechanism or architecture"},
        {"point_id": f"{round_type}:application", "label": "concrete application to the scenario"},
        {"point_id": f"{round_type}:tradeoffs", "label": "explicit trade-offs and alternatives"},
        {"point_id": f"{round_type}:failures", "label": "failure modes and mitigations"},
        {"point_id": f"{round_type}:measurement", "label": "validation or observability strategy"},
    ]
    return {
        "round_type": round_type,
        "title": round_type.replace("_", " ").title(),
        "statement": prompt,
        "taxonomy_keys": [f"technical:{round_type}", f"technical:{str(topic).lower().replace(' ', '-')[:50]}"],
        "prerequisite_keys": [],
        "difficulty": (
            str(context.get("difficulty_level"))
            if str(context.get("difficulty_level") or "adaptive") != "adaptive"
            else {"top_tier": "hard", "mid_tier": "medium", "startup": "easy", "custom": "medium"}[profile_type]
        ),
        "visible_tests": [],
        "hidden_tests": [],
        "expected_points": expected_points,
        "rubric": {
            "version": "technical-concept-v1",
            "weights": {
                "correctness": 0.30,
                "depth": 0.20,
                "application": 0.15,
                "trade_offs": 0.15,
                "failure_modes": 0.10,
                "communication": 0.10,
            },
            "required_dimensions": ["correctness", "depth", "application", "trade_offs", "failure_modes"],
            "unknown_dimensions_are_null": True,
        },
        "source": "authored_fallback",
        "validator_version": "authored-noncoding-v1",
        "profile_types": [profile_type],
    }


def _difficulty_rank(value: Any) -> int:
    return {"easy": 1, "medium": 2, "hard": 3}.get(str(value or "").strip().lower(), 2)


def _selection_terms(context: Dict[str, Any]) -> set[str]:
    values: List[str] = []
    values.extend(_string_list(context.get("technical_topics") or [], 24))
    values.extend(_string_list(context.get("target_skills") or [], 24))
    values.append(str(context.get("job_title") or ""))
    values.append(str(context.get("job_description") or "")[:4000])
    for weakness in context.get("mistake_history") or []:
        if isinstance(weakness, dict):
            values.extend([str(weakness.get("key") or ""), str(weakness.get("title") or "")])
    return {
        token
        for value in values
        for token in re.findall(r"[a-z0-9+#.]{2,}", value.lower())
    }


def _bank_candidate_score(
    item: Dict[str, Any],
    *,
    profile_type: str,
    context: Dict[str, Any],
    round_number: int,
) -> tuple[int, str]:
    requested = str(context.get("difficulty_level") or "adaptive").lower()
    desired = requested if requested in {"easy", "medium", "hard"} else {
        "top_tier": "hard",
        "mid_tier": "medium",
        "startup": "easy",
        "custom": "medium",
    }[profile_type]
    score = 100 - abs(_difficulty_rank(item.get("difficulty")) - _difficulty_rank(desired)) * 30
    spec_json = item.get("spec_json") if isinstance(item.get("spec_json"), dict) else {}
    allowed_profiles = _string_list(
        spec_json.get("profile_types") or item.get("profile_types") or [], 8
    )
    if allowed_profiles:
        score += 35 if profile_type in allowed_profiles else -100
    terms = _selection_terms(context)
    candidate_text = " ".join([
        str(item.get("title") or ""),
        str(item.get("statement") or ""),
        " ".join(_string_list(item.get("taxonomy_keys") or [], 30)),
        " ".join(_string_list(item.get("prerequisite_keys") or [], 30)),
    ]).lower()
    score += min(60, sum(6 for term in terms if term in candidate_text))
    tie_breaker = hashlib.sha256(
        "|".join([
            str(context.get("blueprint_hash") or context.get("interview_id") or ""),
            profile_type,
            str(round_number),
            str(item.get("problem_family_id") or item.get("problem_id") or ""),
            str(item.get("version") or 1),
        ]).encode("utf-8")
    ).hexdigest()
    return score, tie_breaker


async def _authored_coding_specs(
    profile_type: str,
    context: Dict[str, Any],
) -> List[Dict[str, Any]]:
    normalized = normalize_technical_profile(profile_type)
    targets = (
        context.get("custom_targets")
        if normalized == "custom"
        else CODEFORCES_RATING_TARGETS[normalized]
    ) or CODEFORCES_RATING_TARGETS[normalized]
    candidates = _fallback_problem_candidates(_fallback_anchor_text(context), targets, normalized)
    return [
        {
            **problem,
            "round_type": "coding",
            "taxonomy_keys": [f"technical:coding:{str(problem.get('algorithm_pattern') or 'problem-solving').replace(' ', '-')}"] ,
            "prerequisite_keys": [],
            "expected_points": [
                {"point_id": "coding:approach", "label": "explains the chosen approach"},
                {"point_id": "coding:complexity", "label": "states justified time and space complexity"},
                {"point_id": "coding:edge-cases", "label": "handles boundary and failure cases"},
                {"point_id": "coding:explanation", "label": "explains final implementation and trade-offs"},
            ],
            "rubric": {
                "version": "coding-v1",
                "weights": {
                    "passed_tests": 0.35,
                    "approach": 0.15,
                    "efficiency": 0.15,
                    "edge_cases": 0.10,
                    "debugging": 0.10,
                    "explanation": 0.10,
                    "code_quality": 0.05,
                },
                "coding_correctness_owner": "deterministic_sandbox_tests",
                "unknown_dimensions_are_null": True,
            },
            "source": "authored_fallback",
            "validator_version": "authored-coding-v1",
        }
        for problem in candidates
    ]


def _authored_debugging_spec(context: Dict[str, Any], language: str) -> Dict[str, Any]:
    starters = {
        "python": (
            "import sys\n\n"
            "def solve():\n"
            "    data = list(map(int, sys.stdin.read().split()))\n"
            "    n, target = data[0], data[1]\n"
            "    values = data[2:2+n]\n"
            "    seen = set()\n"
            "    for value in values:\n"
            "        if value in seen:  # BUG: checks the wrong value\n"
            "            print('YES')\n"
            "            return\n"
            "        seen.add(value)\n"
            "    print('NO')\n\n"
            "solve()\n"
        ),
        "javascript": (
            "const fs = require('fs');\nconst d = fs.readFileSync(0,'utf8').trim().split(/\\s+/).map(Number);\n"
            "const n=d[0], target=d[1], values=d.slice(2,2+n), seen=new Set();\n"
            "let ok=false; for (const value of values) { if (seen.has(value)) { ok=true; break; } seen.add(value); }\n"
            "console.log(ok ? 'YES' : 'NO');\n"
        ),
        "cpp": (
            "#include <bits/stdc++.h>\nusing namespace std;\nint main(){int n; long long target; if(!(cin>>n>>target)) return 0; "
            "unordered_set<long long> seen; bool ok=false; for(int i=0;i<n;i++){long long value;cin>>value; "
            "if(seen.count(value)) ok=true; seen.insert(value);} cout<<(ok?\"YES\":\"NO\")<<'\\n';}\n"
        ),
        "java": (
            "import java.util.*; public class Main { public static void main(String[] args) { Scanner sc=new Scanner(System.in); "
            "int n=sc.nextInt(); long target=sc.nextLong(); Set<Long> seen=new HashSet<>(); boolean ok=false; "
            "for(int i=0;i<n;i++){ long value=sc.nextLong(); if(seen.contains(value)) ok=true; seen.add(value); } "
            "System.out.println(ok?\"YES\":\"NO\"); } }\n"
        ),
    }
    return {
        "round_type": "debugging",
        "title": "Repair Pair Sum",
        "difficulty": "medium",
        "algorithm_pattern": "hash set",
        "statement": (
            "The supplied program should print YES when two different input positions sum to the target, "
            "otherwise NO. It currently checks the wrong condition. Explain the defect, repair it, and "
            "validate the correction against duplicates, negatives, and boundary values."
        ),
        "input_format": "The first line contains n and target. The second line contains n integers.",
        "output_format": "Print YES if a valid pair exists, otherwise print NO.",
        "constraints": "2 <= n <= 200000; -10^9 <= value, target <= 10^9.",
        "visible_tests": [
            {"stdin": "4 5\n1 2 3 9\n", "expected": "YES\n", "explanation": "2 + 3 equals 5."},
            {"stdin": "3 8\n1 2 4\n", "expected": "NO\n", "explanation": "No pair reaches 8."},
            {"stdin": "2 10\n5 5\n", "expected": "YES\n", "explanation": "Two distinct positions may hold equal values."},
        ],
        "hidden_tests": [
            {"stdin": "2 -3\n-1 -2\n", "expected": "YES\n", "tag": "negative_values"},
            {"stdin": "4 0\n0 1 2 3\n", "expected": "NO\n", "tag": "boundary_index"},
            {"stdin": "5 7\n1 1 1 1 6\n", "expected": "YES\n", "tag": "duplicate_values"},
            {"stdin": "3 4\n2 5 8\n", "expected": "NO\n", "tag": "boundary_index"},
        ],
        "starter_code": starters[language],
        "taxonomy_keys": ["technical:debugging", "technical:hash-set", "technical:edge-cases"],
        "prerequisite_keys": ["technical:collections"],
        "expected_points": [
            {"point_id": "debugging:defect", "label": "identifies the incorrect membership condition"},
            {"point_id": "debugging:repair", "label": "checks target minus current value before insertion"},
            {"point_id": "debugging:edge-cases", "label": "tests duplicates, negatives, and distinct indices"},
            {"point_id": "debugging:complexity", "label": "justifies expected linear time and linear space"},
        ],
        "rubric": {
            "version": "debugging-v1",
            "weights": {"passed_tests": 0.35, "approach": 0.15, "efficiency": 0.15, "edge_cases": 0.10, "debugging": 0.10, "explanation": 0.10, "code_quality": 0.05},
            "coding_correctness_owner": "deterministic_sandbox_tests",
            "unknown_dimensions_are_null": True,
        },
        "expected_time_complexity": "O(n)",
        "expected_space_complexity": "O(n)",
        "hint": "Compare each value with the complement needed to reach the target.",
        "source": "authored_fallback",
        "validator_version": "authored-debugging-v1",
    }


async def _round_templates_for_profile(
    profile_type: str,
    interview_id: str,
    user_id: str,
    generation_context: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Freeze typed round specs from validated bank entries or authored fallbacks.

    Live preparation never calls OpenAI and never inserts generated drafts into a
    candidate session.
    """
    normalized = normalize_technical_profile(profile_type)
    context = {**(generation_context or {}), "profile_type": normalized}
    selected_language = _selected_programming_language(context)
    selected_starter = _starter_code_by_language()[selected_language]
    round_types = _normalize_round_types(context.get("technical_round_types"))
    question_count = max(1, min(12, int(context.get("question_count") or len(round_types))))
    requested_types = [round_types[index % len(round_types)] for index in range(question_count)]
    bank = await _load_active_problem_bank()
    authored_coding = await _authored_coding_specs(normalized, context)
    authored_index = 0
    templates: List[Dict[str, Any]] = []
    total_duration = max(10, min(120, int(context.get("duration_minutes") or 60))) * 60
    per_round_duration = max(300, total_duration // question_count)
    mode = "practice" if str(context.get("interview_mode") or "mock").lower() == "practice" else "mock"
    used_problem_ids: set[str] = set()

    for index, round_type in enumerate(requested_types, start=1):
        supported = [
            item for item in bank
            if item.get("round_type") == round_type
            and (
                not item.get("supported_languages")
                or selected_language in _string_list(item.get("supported_languages"), 20)
            )
        ]
        if supported:
            supported.sort(
                key=lambda item: _bank_candidate_score(
                    item,
                    profile_type=normalized,
                    context=context,
                    round_number=index,
                ),
                reverse=True,
            )
            selected = next(
                (item for item in supported if str(item.get("problem_id")) not in used_problem_ids),
                supported[0],
            )
            spec = dict(selected)
            used_problem_ids.add(str(spec.get("problem_id")))
        elif round_type == "coding":
            spec = dict(authored_coding[authored_index % len(authored_coding)])
            authored_index += 1
        elif round_type == "debugging":
            spec = _authored_debugging_spec(context, selected_language)
        else:
            spec = _noncoding_authored_spec(round_type, context)

        visible_tests = spec.get("visible_tests") if isinstance(spec.get("visible_tests"), list) else []
        hidden_tests = spec.get("hidden_tests") if isinstance(spec.get("hidden_tests"), list) else []
        expected_points = spec.get("expected_points") or (spec.get("spec_json") or {}).get("expected_points") or []
        rubric = spec.get("rubric") or (spec.get("spec_json") or {}).get("rubric") or {}
        statement = str(spec.get("statement") or "")
        metadata = {
            "spec_version": ROUND_SPEC_VERSION,
            "generated_source": "problem_bank" if spec.get("problem_id") else "authored_fallback",
            "source": spec.get("source") or "authored_fallback",
            "title": spec.get("title") or round_type.replace("_", " ").title(),
            "problem_title": spec.get("title") or round_type.replace("_", " ").title(),
            "difficulty": spec.get("difficulty") or context.get("difficulty_level") or "adaptive",
            "statement": statement,
            "input_format": spec.get("input_format") or (spec.get("spec_json") or {}).get("input_format") or "",
            "output_format": spec.get("output_format") or (spec.get("spec_json") or {}).get("output_format") or "",
            "constraints": spec.get("constraints") or (spec.get("spec_json") or {}).get("constraints") or "",
            "visible_tests": visible_tests,
            "expected_time_complexity": spec.get("expected_time_complexity"),
            "expected_space_complexity": spec.get("expected_space_complexity"),
            "hint": spec.get("hint") or (spec.get("spec_json") or {}).get("hint") or "",
            "profile_type": normalized,
            "programming_language": selected_language,
            "round_number": index,
            "round_type": round_type,
            "taxonomy_keys": spec.get("taxonomy_keys") or [],
            "prerequisite_keys": spec.get("prerequisite_keys") or [],
            "expected_points": expected_points,
            "rubric": rubric,
            "validator_version": spec.get("validator_version") or "authored-v1",
            "workflow": (
                ["clarification", "approach", "coding", "visible_tests", "final_submission", "complexity", "explanation", "followup"]
                if round_type in {"coding", "debugging"}
                else ["response", "targeted_followup"]
            ),
        }
        round_spec_id = hashlib.sha256(
            f"{interview_id}|{index}|{round_type}|{spec.get('problem_id') or metadata['title']}|{spec.get('version') or 1}".encode("utf-8")
        ).hexdigest()[:64]
        frozen_spec = {
            **metadata,
            "round_spec_id": round_spec_id,
            "problem_id": spec.get("problem_id"),
            "problem_family_id": spec.get("problem_family_id") or spec.get("problem_id"),
            "problem_version": int(spec.get("version") or 1),
            "hidden_tests_encrypted": _encrypted_json_text(hidden_tests) if hidden_tests else None,
        }
        templates.append({
            "round_type": round_type,
            "language": selected_language,
            "prompt": _prompt_from_metadata(metadata) if round_type in {"coding", "debugging"} else statement,
            "starter_code": (
                str(spec.get("starter_code") or selected_starter)
                if round_type in {"coding", "debugging"}
                else ""
            ),
            "metadata": metadata,
            "round_spec": frozen_spec,
            "round_spec_id": round_spec_id,
            "problem_id": spec.get("problem_id"),
            "problem_version": int(spec.get("version") or 1),
            "round_number": index,
            "duration_seconds": per_round_duration,
            "mode": mode,
            "max_submissions": 3 if mode == "practice" else 1,
        })
    return templates


def _should_regenerate_rounds(
    rows: List[Any],
    expected_language: Optional[str] = None,
    expected_round_types: Optional[List[str]] = None,
) -> bool:
    if expected_round_types and len(rows) != len(expected_round_types):
        return True
    for index, row in enumerate(rows):
        metadata = _json_value(row[7], {})
        if metadata.get("spec_version") != ROUND_SPEC_VERSION:
            return True
        if expected_round_types and row[1] != expected_round_types[index]:
            return True
        if expected_language and row[2] != expected_language:
            return True
    return False

FILE_NAMES = {
    "python": "main.py",
    "javascript": "main.js",
    "java": "Main.java",
    "cpp": "main.cpp",
}

PISTON_LANGUAGE_ALIASES = {
    "python": {"python", "python3", "py"},
    "javascript": {"javascript", "js", "node", "nodejs"},
    "java": {"java"},
    "cpp": {"cpp", "c++", "g++", "clang++", "gcc"},
}
PISTON_RUNTIME_CACHE: Dict[str, Dict[str, str]] = {}


def _json_value(value: Any, fallback: Any) -> Any:
    if value is None:
        return fallback
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except Exception:
        return fallback


def _code_excerpt(code: str, limit: int = 3000) -> str:
    text = code or ""
    if len(text) <= limit:
        return text
    return text[:limit].rsplit("\n", 1)[0]


def _is_private_piston_url(value: Optional[str]) -> bool:
    """Accept only loopback/private addresses or Docker-style service names."""
    raw = str(value or "").strip()
    if not raw:
        return False
    try:
        parsed = urlparse(raw)
        host = (parsed.hostname or "").strip().lower()
    except Exception:
        return False
    if parsed.scheme not in {"http", "https"} or not host:
        return False
    if host == "emkc.org" or host.endswith(".emkc.org"):
        return False
    if host in {"localhost", "host.docker.internal"} or "." not in host:
        return True
    try:
        address = ipaddress.ip_address(host)
        return bool(address.is_private or address.is_loopback or address.is_link_local)
    except ValueError:
        return host.endswith((".local", ".internal"))


def _active_executor_name() -> str:
    if _is_private_piston_url(settings.PISTON_API_URL):
        return "isolated_sandbox"
    return "unavailable"


def _public_executor_label(executor: str) -> str:
    if executor == "isolated_sandbox":
        return "Isolated sandbox"
    if executor == "unavailable":
        return "Unavailable"
    return "Code runner"


def _executor_status_payload() -> Dict[str, Any]:
    executor = _active_executor_name()
    available = executor != "unavailable"
    return {
        "executor": executor,
        "executor_label": _public_executor_label(executor),
        "executor_available": available,
        "executor_status": "configured" if available else "unavailable",
        "executor_unavailable_reason": (
            None
            if available
            else "The private isolated code sandbox is not configured."
        ),
    }


def _require_executor_available() -> None:
    if _active_executor_name() == "unavailable":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Code execution is unavailable. Configure the private isolated sandbox; "
                "public runners and backend host execution are disabled."
            ),
        )


def _generation_summary(rows: List[Any]) -> Dict[str, Any]:
    metadata = _json_value(rows[0][7], {}) if rows else {}
    source = metadata.get("generated_source") or "unknown"
    return {
        "source": source,
        "generated_source": source,
        "fallback": source == "fallback",
        "error": metadata.get("generation_error") or "",
        **_executor_status_payload(),
    }


def _public_round_metadata(metadata: Dict[str, Any], *, include_hint: bool = False) -> Dict[str, Any]:
    allowed_keys = {
        "generated_source",
        "source",
        "generation_error",
        "executor",
        "title",
        "problem_title",
        "difficulty",
        "cf_rating",
        "rating",
        "statement",
        "input_format",
        "output_format",
        "constraints",
        "visible_tests",
        "expected_time_complexity",
        "expected_space_complexity",
        "hint",
        "company_profile",
        "profile_type",
        "company_profile_label",
        "job_title",
        "personalization_anchors",
        "target_skills",
        "programming_language",
        "tier_followup_prompts",
        "mistake_history",
        "round_number",
        "starter_code_by_language",
        "spec_version",
        "round_type",
        "taxonomy_keys",
        "prerequisite_keys",
        "expected_points",
        "rubric",
        "validator_version",
        "workflow",
        "round_spec_id",
        "problem_id",
        "problem_family_id",
        "problem_version",
    }
    public = {key: metadata[key] for key in allowed_keys if key in metadata}
    if not include_hint:
        public.pop("hint", None)
    public["visible_tests"] = [
        {
            "stdin": str(case.get("stdin", "")),
            "expected": str(case.get("expected", "")),
            "explanation": str(case.get("explanation", "")),
        }
        for case in metadata.get("visible_tests", [])
        if isinstance(case, dict)
    ]
    return public


def _public_run_job(job: Dict[str, Any]) -> Dict[str, Any]:
    passed = int(job.get("pass_count") or 0)
    total = int(job.get("total_count") or 0)
    status_value = str(job.get("status") or "queued")
    return {
        "run_id": job["run_id"],
        "round_id": job.get("round_id"),
        "suite": job.get("suite"),
        "status": job.get("status", "queued"),
        "language": job.get("language"),
        "visible_passed": job.get("visible_passed", 0),
        "visible_total": job.get("visible_total", 0),
        "hidden_passed": job.get("hidden_passed") if job.get("suite") == "full" else None,
        "hidden_total": job.get("hidden_total") if job.get("suite") == "full" else None,
        "pass_count": passed,
        "total_count": total,
        "cases": _public_execution_cases(job.get("cases")),
        "runtime_ms": job.get("runtime_ms", 0),
        "memory_kb": job.get("memory_kb", 0),
        "locked": job.get("locked", False),
        "submits_left": job.get("submits_left"),
        "error": job.get("error"),
        "executor": job.get("executor") or _active_executor_name(),
        **_execution_contract_fields(
            status_value=status_value,
            result=job,
            passed=passed,
            total=total,
        ),
    }


def _coerce_utc_datetime(value: Any) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        utc_candidate = parsed.replace(tzinfo=timezone.utc)
        if utc_candidate > datetime.now(timezone.utc) + timedelta(minutes=5):
            # Some legacy rows were written by DB NOW() into timestamp-without-time-zone
            # while the DB session timezone was local. Created-at should not be in the future.
            local_tz = datetime.now().astimezone().tzinfo or timezone.utc
            return parsed.replace(tzinfo=local_tz).astimezone(timezone.utc)
        parsed = utc_candidate
    return parsed.astimezone(timezone.utc)


def _coerce_deadline_utc(value: Any) -> Optional[datetime]:
    """Migration-owned deadline timestamps are stored as naive UTC values."""
    if not value:
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _technical_duration_seconds(profile_type: Optional[str]) -> int:
    return 60 * 60


def _round_expiry_payload(
    *,
    created_at: Any,
    metadata: Dict[str, Any],
    fallback_profile_type: Optional[str] = None,
) -> Dict[str, Any]:
    started_at = _coerce_utc_datetime(created_at)
    profile_type = normalize_profile_type(
        str(metadata.get("profile_type") or metadata.get("company_profile") or fallback_profile_type or "")
    )
    duration_seconds = _technical_duration_seconds(profile_type)
    expires_at = started_at + timedelta(seconds=duration_seconds) if started_at else None
    now = datetime.now(timezone.utc)
    remaining = max(0, int((expires_at - now).total_seconds())) if expires_at else None
    return {
        "started_at": started_at.isoformat() if started_at else None,
        "expires_at": expires_at.isoformat() if expires_at else None,
        "remaining_seconds": remaining,
        "target_duration_seconds": duration_seconds,
        "expired": bool(expires_at and now >= expires_at),
    }


def _serialize_round_rows(rows: List[Any]) -> List[Dict[str, Any]]:
    serialized = []
    for row in rows:
        metadata = _json_value(row[7], {})
        mode = str(row[16] if len(row) > 16 else "mock")
        whiteboard = row[5] or {}
        if len(row) > 20 and row[20]:
            try:
                whiteboard = json.loads(_decrypt_storage_blob(row[20]))
            except Exception:
                whiteboard = {}
        round_started_at = row[21] if len(row) > 21 else row[8] if len(row) > 8 else None
        expiry = _round_expiry_payload(created_at=round_started_at, metadata=metadata)
        if str(row[6] or "").lower() == "pending":
            expiry = {
                "started_at": None,
                "expires_at": None,
                "remaining_seconds": int(row[14] or 0),
                "target_duration_seconds": int(row[14] or 0),
                "expired": False,
            }
        persisted_deadline = _coerce_deadline_utc(row[15] if len(row) > 15 else None)
        if persisted_deadline:
            remaining = max(0, int((persisted_deadline - datetime.now(timezone.utc)).total_seconds()))
            expiry = {
                "started_at": expiry.get("started_at"),
                "expires_at": persisted_deadline.isoformat(),
                "remaining_seconds": remaining,
                "target_duration_seconds": int(row[14] or 0) if len(row) > 14 else expiry.get("target_duration_seconds"),
                "expired": remaining <= 0,
            }
        effective_status = "expired" if expiry["expired"] and row[6] not in {"submitted", "cancelled"} else row[6]
        serialized.append({
            "round_id": row[0],
            "round_type": row[1],
            "language": row[2],
            "prompt": row[3],
            "starter_code": row[4],
            "whiteboard_json": whiteboard,
            "status": effective_status,
            "metadata": _public_round_metadata(metadata, include_hint=mode == "practice"),
            "started_at": expiry["started_at"],
            "expires_at": expiry["expires_at"],
            "remaining_seconds": expiry["remaining_seconds"],
            "target_duration_seconds": expiry["target_duration_seconds"],
            "locked_reason": "expired" if effective_status == "expired" else None,
            "round_spec_id": row[10] if len(row) > 10 else None,
            "problem_id": row[11] if len(row) > 11 else None,
            "round_number": row[12] if len(row) > 12 else len(serialized) + 1,
            "round_spec": _public_round_metadata(
                _json_value(row[13], {}), include_hint=mode == "practice"
            ) if len(row) > 13 else {},
            "mode": mode,
            "max_submissions": int(row[17] or 1) if len(row) > 17 else 1,
            "problem_version": int(row[18] or 1) if len(row) > 18 else None,
            "workflow_state": _json_value(row[19], {}) if len(row) > 19 else {},
        })
    return serialized


TECHNICAL_ROUND_SELECT = """
    SELECT round_id, round_type, language, prompt, starter_code, whiteboard_json, status, metadata,
           created_at, completed_at, round_spec_id, problem_id, round_number, round_spec,
           duration_seconds, deadline_at, mode, max_submissions,
           problem_version, workflow_state, whiteboard_encrypted, started_at
    FROM TechnicalInterviewRounds
    WHERE interview_id = %s AND user_id = %s
    ORDER BY round_number, created_at, round_id
"""


def _persist_frozen_round_templates_sync(
    interview_id: str,
    user_id: str,
    templates: List[Dict[str, Any]],
) -> List[Any]:
    connection = get_db_connection()
    cursor = connection.cursor()
    try:
        cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"technical:{interview_id}",))
        cursor.execute(TECHNICAL_ROUND_SELECT, (interview_id, user_id))
        existing = cursor.fetchall() or []
        if existing:
            connection.commit()
            return existing

        session_started_at = datetime.now(timezone.utc).replace(tzinfo=None)
        cursor.execute(
            "SELECT deadline_at FROM Interviews WHERE interview_id = %s AND user_id = %s FOR UPDATE",
            (interview_id, user_id),
        )
        interview_deadline = (cursor.fetchone() or [None])[0]
        for template_index, template in enumerate(templates):
            round_started_at = session_started_at if template_index == 0 else None
            deadline_at = (
                session_started_at + timedelta(seconds=int(template["duration_seconds"]))
                if template_index == 0
                else None
            )
            if deadline_at and interview_deadline:
                deadline_at = min(deadline_at, interview_deadline)
            round_status = "active" if template_index == 0 else "pending"
            cursor.execute(
                """
                INSERT INTO TechnicalInterviewRounds (
                    round_id, interview_id, user_id, round_type, language,
                    prompt, starter_code, whiteboard_json, metadata, round_spec_id,
                    problem_id, round_number, round_spec, duration_seconds,
                    deadline_at, mode, max_submissions, problem_version,
                    workflow_state, status, started_at, created_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, '{}'::jsonb, %s, %s, %s)
                ON CONFLICT (interview_id, round_number) DO NOTHING
                """,
                (
                    str(uuid.uuid4()),
                    interview_id,
                    user_id,
                    template["round_type"],
                    template["language"],
                    template["prompt"],
                    template["starter_code"],
                    json.dumps({}),
                    json.dumps(template["metadata"]),
                    template["round_spec_id"],
                    template.get("problem_id"),
                    template["round_number"],
                    json.dumps(template["round_spec"]),
                    template["duration_seconds"],
                    deadline_at,
                    template["mode"],
                    template["max_submissions"],
                    template.get("problem_version"),
                    round_status,
                    round_started_at,
                    session_started_at,
                ),
            )
        cursor.execute(TECHNICAL_ROUND_SELECT, (interview_id, user_id))
        rows = cursor.fetchall() or []
        connection.commit()
        return rows
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()
        return_db_connection(connection)


async def _ensure_technical_rounds(interview_id: str, user_id: str) -> Dict[str, Any]:
    interview = await async_execute(
        """
        SELECT interview_id, settings, job_title, status, interview_type, deadline_at
        FROM Interviews
        WHERE interview_id = %s AND user_id = %s
        """,
        (interview_id, user_id),
        fetchone=True,
    )
    if not interview:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Interview not found")
    settings_json = interview[1] or {}
    if isinstance(settings_json, str):
        settings_json = json.loads(settings_json)
    if not is_technical_interview_type(str(interview[4] or "")):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Technical rounds are available only for a Technical Interview blueprint.",
        )
    profile_type = normalize_technical_profile(normalize_profile_type(settings_json.get("profile_type")))
    selected_language = _selected_programming_language(settings_json)
    interview_status = str(interview[3] or "").lower()
    existing = await async_execute(
        TECHNICAL_ROUND_SELECT,
        (interview_id, user_id),
        fetchall=True,
    )
    target_duration_seconds = max(
        600,
        min(7200, int(settings_json.get("duration_minutes") or 60) * 60),
    )
    stored_context = settings_json.get("job_context") if isinstance(settings_json.get("job_context"), dict) else {}
    job_context = {
        "role": stored_context.get("role") or interview[2] or settings_json.get("job_title") or "General Interview",
        "company": stored_context.get("company"),
        "job_title": stored_context.get("job_title") or interview[2] or settings_json.get("job_title") or "General Interview",
        "jd_summary": stored_context.get("jd_summary"),
        "key_skills": stored_context.get("key_skills") or [],
        "profile_type": profile_type,
        "profile_label": stored_context.get("profile_label") or profile_type.replace("_", " ").title(),
    }
    if interview_status in TERMINAL_TECHNICAL_INTERVIEW_STATUSES:
        return {
            "rounds": _serialize_round_rows(existing or []),
            "generation": _generation_summary(existing or []),
            **_executor_status_payload(),
            "prepared": bool(existing),
            "profile_type": profile_type,
            "job_context": job_context,
            "target_duration_seconds": target_duration_seconds,
            "read_only": True,
            "interview_status": interview_status,
        }
    if existing:
        return {
            "rounds": _serialize_round_rows(existing),
            "generation": _generation_summary(existing),
            **_executor_status_payload(),
            "prepared": True,
            "profile_type": profile_type,
            "job_context": job_context,
            "target_duration_seconds": target_duration_seconds,
            "read_only": False,
            "interview_status": interview_status,
        }

    generation_context = await _load_technical_generation_context(
        interview_id,
        user_id,
        settings_json,
        interview[2] or settings_json.get("job_title") or "",
    )
    templates = await _round_templates_for_profile(
        profile_type,
        interview_id,
        user_id,
        generation_context,
    )
    existing = await asyncio.to_thread(
        _persist_frozen_round_templates_sync,
        interview_id,
        user_id,
        templates,
    )
    try:
        await _record_technical_event(
            interview_id,
            None,
            user_id,
            "technical_rounds_frozen",
            {
                "round_count": len(existing),
                "round_types": [row[1] for row in existing],
                "spec_version": ROUND_SPEC_VERSION,
                "executor": _active_executor_name(),
            },
        )
    except Exception:
        pass
    return {
        "rounds": _serialize_round_rows(existing),
        "generation": _generation_summary(existing),
        **_executor_status_payload(),
        "prepared": True,
        "profile_type": profile_type,
        "job_context": job_context,
        "target_duration_seconds": target_duration_seconds,
        "read_only": False,
        "interview_status": interview_status,
    }



@router.post("/sessions/{interview_id}/prepare")
async def prepare_technical_rounds(interview_id: str, current_user: Dict = Depends(get_current_user)):
    prepared = await _ensure_technical_rounds(interview_id, current_user["user_id"])
    return {"status": "ready", **prepared}


@router.get("/sessions/{interview_id}/rounds")
async def get_or_create_rounds(interview_id: str, current_user: Dict = Depends(get_current_user)):
    return await _ensure_technical_rounds(interview_id, current_user["user_id"])


def _execution_idempotency_key(
    request: CodeRunRequest,
    *,
    round_id: str,
    action: str,
    suite: str,
    input_value: str = "",
) -> str:
    explicit = str(request.idempotency_key or "").strip()
    if explicit:
        return explicit
    digest = hashlib.sha256(
        "|".join([round_id, action, suite, request.language, request.code, input_value]).encode("utf-8")
    ).hexdigest()
    return f"legacy:{action}:{digest[:80]}"[:120]


def _public_execution_error(status_value: str, retry_count: int) -> Optional[str]:
    if status_value == "failed":
        return "Execution could not be completed after retrying. Your code is still saved."
    if status_value == "queued" and retry_count > 0:
        return "Execution is being retried."
    return None


def _public_execution_cases(value: Any) -> List[Dict[str, Any]]:
    """Return only browser-safe visible case details.

    Hidden-case pass/fail, timing, input, expected output, and process output are
    private assessment evidence.  The browser receives only the aggregate
    hidden passed/total counters on a completed full-suite job.
    """
    if not isinstance(value, list):
        return []
    public: List[Dict[str, Any]] = []
    allowed = {
        "index", "case_number", "verdict", "passed", "runtime_ms", "memory_kb",
        "stdin", "expected", "actual", "stderr",
    }
    for case in value:
        if not isinstance(case, dict) or bool(case.get("hidden")):
            continue
        public.append({key: case[key] for key in allowed if key in case})
    return public


def _execution_contract_fields(
    *,
    status_value: str,
    result: Dict[str, Any],
    passed: int,
    total: int,
) -> Dict[str, Any]:
    verdict = str(result.get("verdict") or "")
    finished = status_value in {"completed", "failed"}
    compile_failed = finished and verdict.lower() in {"compile error", "compilation error"}
    return {
        "poll_after_ms": 250,
        "compile": {
            "status": "failed" if compile_failed else ("succeeded" if status_value == "completed" else status_value),
        },
        "run": {
            "status": status_value,
            "verdict": verdict or None,
            "runtime_ms": int(result.get("runtime_ms") or 0),
            "memory_kb": int(result.get("memory_kb") or 0),
        },
        "test_summary": {"passed": passed, "total": total},
        "hidden_details": None,
    }


def _execution_job_public_from_row(row: Any) -> Dict[str, Any]:
    result = _json_value(row[6], {}) if len(row) > 6 else {}
    if not isinstance(result, dict):
        result = {}
    status_value = str(row[5] or "queued")
    retry_count = int(row[8] or 0) if len(row) > 8 else 0
    passed = int(result.get("pass_count") or 0)
    total = int(result.get("total_count") or 0)
    return {
        "run_id": str(row[0]),
        "round_id": str(row[1]),
        "action": str(row[2] or "test"),
        "suite": str(row[3] or "visible"),
        "language": str(row[4] or "python"),
        "status": status_value,
        "visible_passed": int(result.get("visible_passed") or 0),
        "visible_total": int(result.get("visible_total") or 0),
        "hidden_passed": result.get("hidden_passed") if str(row[3]) == "full" else None,
        "hidden_total": result.get("hidden_total") if str(row[3]) == "full" else None,
        "pass_count": passed,
        "total_count": total,
        "cases": _public_execution_cases(result.get("cases")),
        "stdout": str(result.get("stdout") or ""),
        "stderr": str(result.get("stderr") or ""),
        "exit_code": result.get("exit_code"),
        "verdict": result.get("verdict"),
        "runtime_ms": int(result.get("runtime_ms") or 0),
        "memory_kb": int(result.get("memory_kb") or 0),
        "locked": bool(result.get("locked")),
        "submits_left": result.get("submits_left"),
        "executor": "isolated_sandbox",
        "error": _public_execution_error(status_value, retry_count),
        "retry_count": retry_count,
        **_execution_contract_fields(
            status_value=status_value,
            result=result,
            passed=passed,
            total=total,
        ),
    }


EXECUTION_JOB_SELECT = """
    SELECT job_id, round_id, action, suite, language, status, result_json,
           error_message, retry_count, source_hash
    FROM TechnicalExecutionJobs
"""


async def _existing_execution_job(
    user_id: str,
    idempotency_key: str,
    *,
    round_id: str,
    action: str,
    source_hash: str,
) -> Optional[Dict[str, Any]]:
    row = await async_execute(
        EXECUTION_JOB_SELECT + " WHERE user_id = %s AND idempotency_key = %s",
        (user_id, idempotency_key),
        fetchone=True,
    )
    if not row:
        return None
    if str(row[1]) != str(round_id) or str(row[2]) != action or str(row[9]) != source_hash:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Idempotency key was already used for a different technical action.",
        )
    payload = _execution_job_public_from_row(row)
    payload["idempotency_key"] = idempotency_key
    payload["idempotent_replay"] = True
    return payload


def _enqueue_execution_job_sync(
    *,
    round_row: Any,
    user_id: str,
    request: CodeRunRequest,
    action: str,
    suite: str,
    cases: List[Dict[str, Any]],
    idempotency_key: str,
    lock_submission: bool,
    visible_total: int,
    hidden_total: int,
) -> Any:
    source_hash = hashlib.sha256(request.code.encode("utf-8")).hexdigest()
    if request.editor_hash and request.editor_hash.lower() != source_hash:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Editor source hash does not match the submitted source.",
        )
    connection = get_db_connection()
    cursor = connection.cursor()
    try:
        cursor.execute(
            EXECUTION_JOB_SELECT + " WHERE user_id = %s AND idempotency_key = %s FOR UPDATE",
            (user_id, idempotency_key),
        )
        existing = cursor.fetchone()
        if existing:
            cursor.execute(
                "SELECT source_hash, interview_id FROM TechnicalExecutionJobs WHERE job_id = %s",
                (existing[0],),
            )
            contract = cursor.fetchone()
            if (
                str(existing[1]) != str(round_row[0])
                or str(existing[2]) != action
                or not contract
                or str(contract[0]) != source_hash
            ):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Idempotency key was already used for a different technical action.",
                )
            connection.commit()
            return existing

        cursor.execute(
            """
            SELECT tir.status, tir.mode, tir.max_submissions,
                   tir.deadline_at, tir.workflow_state, i.deadline_at
            FROM TechnicalInterviewRounds tir
            JOIN Interviews i
              ON i.interview_id = tir.interview_id
             AND i.user_id = tir.user_id
            WHERE tir.round_id = %s AND tir.user_id = %s
            FOR UPDATE
            """,
            (round_row[0], user_id),
        )
        locked_round = cursor.fetchone()
        if not locked_round:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Technical round not found")
        round_status = str(locked_round[0] or "active").lower()
        deadline = _coerce_deadline_utc(locked_round[3])
        interview_deadline = _coerce_deadline_utc(locked_round[5]) if len(locked_round) > 5 else None
        if interview_deadline and (not deadline or interview_deadline < deadline):
            deadline = interview_deadline
        if deadline and datetime.now(timezone.utc) >= deadline:
            cursor.execute(
                "UPDATE TechnicalInterviewRounds SET status = 'expired', completed_at = COALESCE(completed_at, NOW()) WHERE round_id = %s",
                (round_row[0],),
            )
            raise HTTPException(status_code=status.HTTP_410_GONE, detail="Time has expired for this technical round.")
        if round_status != "active":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This technical round is not accepting this action.")

        max_submissions = max(1, int(locked_round[2] or (3 if locked_round[1] == "practice" else 1)))
        submits_left: Optional[int] = None
        if lock_submission:
            workflow_state = _json_value(locked_round[4], {}) if len(locked_round) > 4 else None
            if isinstance(workflow_state, dict) and not workflow_state.get("approach"):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Commit your initial approach before the one-way final submission.",
                )
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM TechnicalExecutionJobs
                WHERE round_id = %s AND user_id = %s AND action = 'submit'
                  AND status IN ('queued', 'leased', 'running', 'completed')
                """,
                (round_row[0], user_id),
            )
            used = int((cursor.fetchone() or [0])[0] or 0)
            if used >= max_submissions:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Submit limit reached for this problem")
            submits_left = max(0, max_submissions - used - 1)
            cursor.execute(
                "UPDATE TechnicalInterviewRounds SET status = 'submitting' WHERE round_id = %s AND user_id = %s",
                (round_row[0], user_id),
            )

        job_id = str(uuid.uuid4())
        encrypted_source = encrypt_data(request.code).encode("utf-8")
        initial_result = {
            "version": EXECUTION_JOB_VERSION,
            "suite": suite,
            "status": "queued",
            "visible_passed": 0,
            "visible_total": visible_total,
            "hidden_passed": 0,
            "hidden_total": hidden_total,
            "pass_count": 0,
            "total_count": len(cases),
            "cases": [],
            "locked": lock_submission,
            "submits_left": submits_left,
            "executor": "isolated_sandbox",
            "editor_revision": request.editor_revision,
            "editor_hash": source_hash,
        }
        cursor.execute(
            """
            INSERT INTO TechnicalCodeSnapshots (
                snapshot_id, round_id, interview_id, user_id, language,
                source_chars, code_hash, source_excerpt, source_code,
                source_code_encrypted, metadata
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, '[encrypted]', '[encrypted]', %s, %s)
            """,
            (
                str(uuid.uuid4()), round_row[0], round_row[1], user_id, request.language,
                len(request.code), source_hash, encrypted_source,
                json.dumps({
                    "action": action,
                    "suite": suite,
                    "execution_job_id": job_id,
                    "editor_revision": request.editor_revision,
                    "editor_hash_verified": bool(request.editor_hash),
                    "encrypted_source": True,
                }),
            ),
        )
        cursor.execute(
            """
            INSERT INTO TechnicalExecutionJobs (
                job_id, idempotency_key, user_id, interview_id, round_id,
                action, suite, language, source_code, source_code_encrypted,
                source_hash, cases_json, cases_encrypted, status, next_attempt_at,
                result_json, created_at, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, '[]'::jsonb, %s, 'queued', NOW(), %s, NOW(), NOW())
            RETURNING job_id, round_id, action, suite, language, status,
                      result_json, error_message, retry_count
            """,
            (
                job_id,
                idempotency_key,
                user_id,
                round_row[1],
                round_row[0],
                action,
                suite,
                request.language,
                "[encrypted]",
                encrypted_source,
                source_hash,
                encrypt_data(json.dumps(cases, separators=(",", ":"), ensure_ascii=False)).encode("utf-8"),
                json.dumps(initial_result),
            ),
        )
        inserted = cursor.fetchone()
        connection.commit()
        return inserted
    except HTTPException:
        connection.rollback()
        raise
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()
        return_db_connection(connection)


async def _queue_execution_job(
    *,
    round_row: Any,
    user_id: str,
    request: CodeRunRequest,
    action: str,
    suite: str,
    cases: List[Dict[str, Any]],
    lock_submission: bool,
    visible_total: int,
    hidden_total: int,
    input_value: str = "",
) -> Dict[str, Any]:
    idempotency_key = _execution_idempotency_key(
        request,
        round_id=round_row[0],
        action=action,
        suite=suite,
        input_value=input_value,
    )
    source_hash = hashlib.sha256(request.code.encode("utf-8")).hexdigest()
    replay = await _existing_execution_job(
        user_id,
        idempotency_key,
        round_id=round_row[0],
        action=action,
        source_hash=source_hash,
    )
    if replay:
        return replay
    if not lock_submission:
        allowed = await VISIBLE_RUN_RATE_LIMITER.check_limit(f"{user_id}:{round_row[0]}")
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Visible test limit reached. Wait a minute before running again.",
            )
    row = await asyncio.to_thread(
        _enqueue_execution_job_sync,
        round_row=round_row,
        user_id=user_id,
        request=request,
        action=action,
        suite=suite,
        cases=cases,
        idempotency_key=idempotency_key,
        lock_submission=lock_submission,
        visible_total=visible_total,
        hidden_total=hidden_total,
    )
    payload = _execution_job_public_from_row(row)
    payload["idempotency_key"] = idempotency_key
    payload["idempotent_replay"] = False
    await _record_technical_event(
        round_row[1],
        round_row[0],
        user_id,
        f"{action}_queued",
        {"run_id": payload["run_id"], "suite": suite, "language": request.language},
    )
    return payload


@router.post("/rounds/{round_id}/run", status_code=status.HTTP_202_ACCEPTED)
async def run_code(round_id: str, request: CodeRunRequest, current_user: Dict = Depends(get_current_user)):
    round_row = await _load_round_for_user(round_id, current_user["user_id"])
    await _ensure_round_action_allowed(round_row, current_user["user_id"], "run")
    if str(round_row[2]) not in {"coding", "debugging", "dsa"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This round does not execute code.")
    if request.language != str(round_row[14] if len(round_row) > 14 else request.language):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Language must match the frozen round spec.")
    _require_executor_available()
    return await _queue_execution_job(
        round_row=round_row,
        user_id=current_user["user_id"],
        request=request,
        action="run",
        suite="custom",
        cases=[{"stdin": request.stdin or "", "visible": True}],
        lock_submission=False,
        visible_total=1,
        hidden_total=0,
        input_value=request.stdin or "",
    )



@router.post("/rounds/{round_id}/test", status_code=status.HTTP_202_ACCEPTED)
async def run_visible_tests(round_id: str, request: TechnicalTestRequest, current_user: Dict = Depends(get_current_user)):
    return await _start_test_suite_job(round_id, request, current_user, suite="visible", lock_submission=False)


@router.post("/rounds/{round_id}/custom-run", status_code=status.HTTP_202_ACCEPTED)
async def run_custom_input(round_id: str, request: TechnicalTestRequest, current_user: Dict = Depends(get_current_user)):
    round_row = await _load_round_for_user(round_id, current_user["user_id"])
    await _ensure_round_action_allowed(round_row, current_user["user_id"], "custom_run")
    if str(round_row[2]) not in {"coding", "debugging", "dsa"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This round does not execute code.")
    if request.language != str(round_row[14] if len(round_row) > 14 else request.language):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Language must match the frozen round spec.")
    _require_executor_available()
    custom_input = request.custom_input if request.custom_input is not None else request.stdin or ""
    return await _queue_execution_job(
        round_row=round_row,
        user_id=current_user["user_id"],
        request=request,
        action="run",
        suite="custom",
        cases=[{"stdin": custom_input, "visible": True}],
        lock_submission=False,
        visible_total=1,
        hidden_total=0,
        input_value=custom_input,
    )



@router.post("/rounds/{round_id}/submit", status_code=status.HTTP_202_ACCEPTED)
async def submit_solution(round_id: str, request: TechnicalTestRequest, current_user: Dict = Depends(get_current_user)):
    return await _start_test_suite_job(round_id, request, current_user, suite="full", lock_submission=True)


@router.get("/runs/{run_id}")
async def get_run_status(run_id: str, current_user: Dict = Depends(get_current_user)):
    durable = await async_execute(
        EXECUTION_JOB_SELECT + " WHERE job_id = %s AND user_id = %s",
        (run_id, current_user["user_id"]),
        fetchone=True,
    )
    if durable:
        return _execution_job_public_from_row(durable)

    # Compatibility read for jobs completed before TechnicalExecutionJobs was introduced.
    row = await async_execute(
        """
        SELECT run_id, round_id, language, stdout, stderr, exit_code, runtime_ms, hidden_validation_result
        FROM TechnicalRunEvents
        WHERE run_id = %s AND user_id = %s
        """,
        (run_id, current_user["user_id"]),
        fetchone=True,
    )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    validation = _json_value(row[7], {})
    cases = _public_execution_cases(_json_value(row[3], []))
    passed = int(validation.get("pass_count") or 0)
    total = int(validation.get("total_count") or 0)
    status_value = str(validation.get("status") or "completed")
    result = validation if isinstance(validation, dict) else {}
    return {
        "run_id": row[0],
        "round_id": row[1],
        "suite": validation.get("suite"),
        "status": status_value,
        "language": row[2],
        "visible_passed": validation.get("visible_passed", 0),
        "visible_total": validation.get("visible_total", 0),
        "hidden_passed": validation.get("hidden_passed"),
        "hidden_total": validation.get("hidden_total"),
        "pass_count": passed,
        "total_count": total,
        "cases": cases,
        "runtime_ms": row[6] or 0,
        "memory_kb": validation.get("memory_kb", 0),
        "locked": validation.get("locked", False),
        "submits_left": validation.get("submits_left"),
        "error": row[4] or None,
        "executor": validation.get("executor") or _active_executor_name(),
        "retry_count": 0,
        **_execution_contract_fields(
            status_value=status_value,
            result=result,
            passed=passed,
            total=total,
        ),
    }


def _persist_technical_response_raw_sync(
    round_row: Any,
    user_id: str,
    request: TechnicalResponseRequest,
) -> Dict[str, Any]:
    connection = get_db_connection()
    cursor = connection.cursor()
    try:
        round_spec = _json_value(round_row[10], {}) if len(round_row) > 10 else {}
        metadata = _json_value(round_row[4], {})
        expected_points = round_spec.get("expected_points") or metadata.get("expected_points") or []
        expected_point_ids = [
            str(point.get("point_id") or point.get("id"))
            for point in expected_points
            if isinstance(point, dict) and (point.get("point_id") or point.get("id"))
        ]
        taxonomy_keys = round_spec.get("taxonomy_keys") or metadata.get("taxonomy_keys") or []
        rubric = round_spec.get("rubric") or metadata.get("rubric") or {}
        primary_question_id = str(
            round_row[16] if len(round_row) > 16 and round_row[16] else f"tech:{round_row[0]}"
        )[:64]
        question_id = primary_question_id
        question_text = str(round_row[3])
        parent_question_id: Optional[str] = None
        parent_response_id: Optional[str] = None
        is_followup = request.phase == "followup"
        if is_followup:
            cursor.execute(
                """
                SELECT ir.response_id, assessment.assessment_json
                FROM InterviewResponses ir
                JOIN LATERAL (
                    SELECT assessment_json
                    FROM ResponseAssessments
                    WHERE response_id = ir.response_id
                    ORDER BY created_at DESC
                    LIMIT 1
                ) assessment ON TRUE
                WHERE ir.interview_id = %s AND ir.question_id = %s
                ORDER BY ir.created_at DESC
                LIMIT 1
                """,
                (round_row[1], primary_question_id),
            )
            parent = cursor.fetchone()
            if not parent or (request.parent_response_id and str(parent[0]) != request.parent_response_id):
                raise HTTPException(status_code=409, detail="The targeted follow-up is not available.")
            parent_assessment = _json_value(parent[1], {})
            decision = parent_assessment.get("decision") if isinstance(parent_assessment, dict) else {}
            if not isinstance(decision, dict) or decision.get("action") != "targeted_followup":
                raise HTTPException(status_code=409, detail="The targeted follow-up is not available.")
            question_text = str(decision.get("followup_prompt") or "").strip()
            if not question_text:
                raise HTTPException(status_code=409, detail="The targeted follow-up prompt is unavailable.")
            parent_question_id = primary_question_id
            parent_response_id = str(parent[0])
            question_id = "tf_" + hashlib.sha256(
                f"{round_row[0]}|{parent_response_id}|{question_text}".encode("utf-8")
            ).hexdigest()[:48]
        cursor.execute(
            """
            INSERT INTO InterviewQuestions (
                question_id, interview_id, question_text, question_order, question_type,
                topic_label, rubric_version, source, expected_signal, taxonomy_keys,
                expected_points, rubric_json, selection_reason, blueprint_section_id,
                provenance, generation_metadata, difficulty_level, is_followup,
                parent_question_id, question_spec_id, expected_point_ids
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'frozen_technical_spec', %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (question_id) DO NOTHING
            """,
            (
                question_id,
                round_row[1],
                question_text,
                int(round_spec.get("round_number") or 1) * 10 + (1 if is_followup else 0),
                round_row[2],
                metadata.get("title") or str(round_row[2]).replace("_", " ").title(),
                rubric.get("version") or "technical-concept-v1",
                "Technical response assessed against the frozen rubric",
                json.dumps(taxonomy_keys),
                json.dumps(expected_points),
                json.dumps(rubric),
                "Frozen technical round selection",
                str(round_row[16] if len(round_row) > 16 else round_row[0])[:80],
                json.dumps({
                    "round_id": round_row[0],
                    "round_spec_version": round_spec.get("spec_version"),
                    "parent_response_id": parent_response_id,
                }),
                json.dumps({"technical_round_id": round_row[0], "phase": request.phase}),
                str(metadata.get("difficulty") or "adaptive")[:20],
                is_followup,
                parent_question_id,
                question_id,
                json.dumps(expected_point_ids),
            ),
        )
        cursor.execute(
            """
            SELECT ir.response_id, ra.assessment_json, ir.raw_answer_hash,
                   ir.evidence_hash, ir.question_id
            FROM InterviewResponses ir
            LEFT JOIN LATERAL (
                SELECT assessment_json
                FROM ResponseAssessments
                WHERE response_id = ir.response_id
                ORDER BY created_at DESC
                LIMIT 1
            ) ra ON TRUE
            WHERE ir.interview_id = %s AND ir.idempotency_key = %s
            """,
            (round_row[1], request.idempotency_key),
        )
        existing = cursor.fetchone()
        if existing:
            attempted_hash = hashlib.sha256(request.response_text.strip().encode("utf-8")).hexdigest()
            if str(existing[4]) != question_id or (existing[2] and str(existing[2]) != attempted_hash):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Idempotency key was already used for a different response.",
                )
            connection.commit()
            return {
                "response_id": str(existing[0]),
                "question_id": question_id,
                "duplicate": True,
                "assessment": _json_value(existing[1], None),
                "raw_hash": str(existing[2] or attempted_hash),
                "evidence_hash": str(existing[3] or attempted_hash),
                "rubric": rubric,
                "expected_points": expected_points,
                "taxonomy_keys": taxonomy_keys,
                "question_text": question_text,
                "phase": request.phase,
            }

        cursor.execute(
            """
            SELECT status, deadline_at
            FROM TechnicalInterviewRounds
            WHERE round_id = %s AND user_id = %s
            FOR UPDATE
            """,
            (round_row[0], user_id),
        )
        locked_round = cursor.fetchone()
        if not locked_round:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Technical round not found")
        deadline = _coerce_deadline_utc(locked_round[1])
        if deadline and datetime.now(timezone.utc) >= deadline:
            cursor.execute(
                "UPDATE TechnicalInterviewRounds SET status = 'expired', completed_at = COALESCE(completed_at, NOW()) WHERE round_id = %s",
                (round_row[0],),
            )
            raise HTTPException(status_code=status.HTTP_410_GONE, detail="Time has expired for this technical round.")
        if str(locked_round[0] or "active").lower() != "active":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This technical round is already closed.")

        answer = request.response_text.strip()
        response_id = str(uuid.uuid4())
        raw_hash = hashlib.sha256(answer.encode("utf-8")).hexdigest()
        evidence_hash = hashlib.sha256(
            f"{round_row[1]}|{question_id}|{raw_hash}|{request.idempotency_key}".encode("utf-8")
        ).hexdigest()
        response_seconds = request.response_payload.get("response_seconds")
        if not isinstance(response_seconds, (int, float)):
            response_seconds = None
        cursor.execute(
            """
            INSERT INTO InterviewResponses (
                response_id, interview_id, question_id, user_response,
                response_time_seconds, nonverbal_metrics, idempotency_key,
                evidence_hash, answer_text_encrypted, transcript_encrypted,
                raw_answer_hash, input_mode, timing_json, created_at
            )
            VALUES (%s, %s, %s, '[encrypted]', %s, %s, %s, %s, %s, %s,
                    %s, 'text', %s, NOW())
            ON CONFLICT (interview_id, idempotency_key) DO NOTHING
            RETURNING response_id
            """,
            (
                response_id,
                round_row[1],
                question_id,
                int(response_seconds) if response_seconds is not None else None,
                json.dumps({"source": "technical_text_response"}),
                request.idempotency_key,
                evidence_hash,
                encrypt_data(answer).encode("utf-8"),
                encrypt_data(answer).encode("utf-8"),
                raw_hash,
                json.dumps({
                    "response_seconds": response_seconds,
                    "client_timing": request.response_payload.get("timing") or {},
                }),
            ),
        )
        inserted = cursor.fetchone()
        if not inserted:
            cursor.execute(
                "SELECT response_id FROM InterviewResponses WHERE interview_id = %s AND idempotency_key = %s",
                (round_row[1], request.idempotency_key),
            )
            response_id = str(cursor.fetchone()[0])
            duplicate = True
        else:
            duplicate = False
        connection.commit()
        return {
            "response_id": response_id,
            "question_id": question_id,
            "duplicate": duplicate,
            "assessment": None,
            "raw_hash": raw_hash,
            "evidence_hash": evidence_hash,
            "rubric": rubric,
            "expected_points": expected_points,
            "taxonomy_keys": taxonomy_keys,
            "question_text": question_text,
            "phase": request.phase,
        }
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()
        return_db_connection(connection)


def _commit_technical_response_assessment_sync(
    round_row: Any,
    user_id: str,
    response_id: str,
    evidence_hash: str,
    assessment: Dict[str, Any],
    finalize_round: bool,
) -> Dict[str, Any]:
    connection = get_db_connection()
    cursor = connection.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO ResponseAssessments (
                assessment_id, response_id, interview_id, evaluator_version,
                evidence_hash, overall_score, assessment_json, created_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (response_id, evaluator_version, evidence_hash) DO NOTHING
            """,
            (
                str(uuid.uuid4()),
                response_id,
                round_row[1],
                EVALUATION_VERSION,
                evidence_hash,
                assessment.get("overall_score") if isinstance(assessment.get("overall_score"), (int, float)) else None,
                json.dumps(assessment),
            ),
        )
        assessment_inserted = cursor.rowcount > 0
        if assessment_inserted:
            encrypted_assessment_link = encrypt_data(json.dumps({
                "response_id": response_id,
                "evaluator_version": EVALUATION_VERSION,
                "evidence_hash": evidence_hash,
                "decision": assessment.get("decision"),
            }, separators=(",", ":"), ensure_ascii=False, default=str)).encode("utf-8")
            cursor.execute(
                """
                INSERT INTO TechnicalReasoningEvidence (
                    user_id, interview_id, round_id, evidence_type, content, payload,
                    content_encrypted, evidence_hash
                )
                VALUES (%s, %s, %s, 'technical_response', '[encrypted]', %s, %s, %s)
                """,
                (
                    user_id,
                    round_row[1],
                    round_row[0],
                    json.dumps({
                        "encrypted": True,
                        "response_id": response_id,
                        "evaluator_version": EVALUATION_VERSION,
                        "evidence_hash": evidence_hash,
                    }),
                    encrypted_assessment_link,
                    evidence_hash,
                ),
            )
        if finalize_round:
            cursor.execute(
                """
                UPDATE TechnicalInterviewRounds
                SET status = 'submitted', completed_at = COALESCE(completed_at, NOW())
                WHERE round_id = %s AND user_id = %s AND status = 'active'
                """,
                (round_row[0], user_id),
            )
            assessment["next_round_id"] = _activate_next_round_locked(
                cursor, str(round_row[1]), user_id
            )
        connection.commit()
        return assessment
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()
        return_db_connection(connection)


def _technical_response_decision(
    assessment: Dict[str, Any],
    expected_points: List[Dict[str, Any]],
    *,
    phase: str,
) -> Dict[str, Any]:
    if phase == "followup":
        return {"action": "complete", "reason": "targeted_followup_committed", "finalize": True}
    evidence = assessment.get("evidence") if isinstance(assessment.get("evidence"), dict) else {}
    missed = [str(item) for item in evidence.get("missed_points") or [] if str(item)]
    score = assessment.get("overall_score")
    needs_followup = bool(
        missed
        or assessment.get("evidence_status") == "insufficient_evidence"
        or (isinstance(score, (int, float)) and float(score) < 75)
    )
    if not needs_followup:
        return {"action": "complete", "reason": "expected_coverage_met", "finalize": True}
    labels = {
        str(point.get("point_id") or point.get("id")): str(point.get("label") or point.get("point_id") or "")
        for point in expected_points
        if isinstance(point, dict)
    }
    target_id = missed[0] if missed else None
    target_label = labels.get(str(target_id), "the key mechanism, trade-off, and failure evidence")
    return {
        "action": "targeted_followup",
        "reason": "missing_or_low_confidence_technical_evidence",
        "finalize": False,
        "target_point_id": target_id,
        "followup_prompt": (
            f"Go one level deeper on {target_label}. Explain the mechanism, a concrete application, "
            "the most important trade-off, and how you would detect or recover from failure."
        ),
    }


def _public_technical_assessment(assessment: Dict[str, Any], mode: str) -> Dict[str, Any]:
    if str(mode or "mock").lower() == "practice":
        return assessment
    semantic = assessment.get("semantic_status") if isinstance(assessment.get("semantic_status"), dict) else {}
    return {
        "version": assessment.get("version"),
        "evidence_status": "recorded",
        "semantic_status": {"state": semantic.get("state")},
        "feedback": "Response committed. Scores and evidence will appear in the final report.",
    }


@router.post("/rounds/{round_id}/response")
async def submit_technical_response(
    round_id: str,
    request: TechnicalResponseRequest,
    current_user: Dict = Depends(get_current_user),
):
    round_row = await _load_round_for_user(round_id, current_user["user_id"])
    if str(round_row[2]) in {"coding", "debugging", "dsa"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Coding rounds require a code submission.")
    raw = await asyncio.to_thread(
        _persist_technical_response_raw_sync,
        round_row,
        current_user["user_id"],
        request,
    )
    if raw.get("assessment"):
        stored_assessment = raw["assessment"]
        decision = stored_assessment.get("decision") or {"action": "complete", "finalize": True}
        return {
            "round_id": round_id,
            "response_id": raw["response_id"],
            "idempotency_key": request.idempotency_key,
            "status": "committed",
            "duplicate": True,
            "assessment": _public_technical_assessment(stored_assessment, str(round_row[12] or "mock")),
            "decision": decision,
        }
    context = {
        "interview_type": str(round_row[2]),
        "question_type": str(round_row[2]),
        "taxonomy_keys": raw.get("taxonomy_keys") or [],
        "semantic_analysis_enabled": True,
        "semantic_budget_available": True,
    }
    rubric = {
        **(raw.get("rubric") or {}),
        "expected_points": raw.get("expected_points") or [],
    }
    assessment = await evaluate_answer(
        raw.get("question_text") or round_row[3],
        request.response_text,
        rubric,
        context,
        request.response_payload.get("response_seconds"),
        [],
        user_id=current_user["user_id"],
        interview_id=round_row[1],
        response_id=raw["response_id"],
    )
    assessment["decision"] = _technical_response_decision(
        assessment,
        raw.get("expected_points") or [],
        phase=request.phase,
    )
    assessment["round_id"] = round_id
    assessment = await asyncio.to_thread(
        _commit_technical_response_assessment_sync,
        round_row,
        current_user["user_id"],
        raw["response_id"],
        raw["evidence_hash"],
        assessment,
        bool(assessment["decision"].get("finalize")),
    )
    return {
        "round_id": round_id,
        "response_id": raw["response_id"],
        "idempotency_key": request.idempotency_key,
        "status": "committed",
        "duplicate": bool(raw.get("duplicate")),
        "assessment": _public_technical_assessment(assessment, str(round_row[12] or "mock")),
        "decision": assessment["decision"],
        "next_round_id": assessment.get("next_round_id"),
    }


@router.post("/events")
async def record_technical_event(request: TechnicalEventRequest, current_user: Dict = Depends(get_current_user)):
    interview = await async_execute(
        "SELECT 1 FROM Interviews WHERE interview_id = %s AND user_id = %s",
        (request.interview_id, current_user["user_id"]),
        fetchone=True,
    )
    if not interview:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Interview not found")
    await _record_technical_event(request.interview_id, request.round_id, current_user["user_id"], request.event_type, request.payload)
    if request.event_type in {
        "paste",
        "paste_blocked",
        "large_paste",
        "drop_blocked",
        "clipboard_code",
        "fullscreen_exit",
        "tab_switch",
        "window_blur",
        "screen_share_stopped",
        "technical_permission_failed",
        "large_code_jump",
        "suspicious_fast_submit",
        "visible_output_hardcode",
        "mobile_phone_detected",
        "multiple_people_detected",
        "screen_not_monitor",
        "no_clarification_before_coding",
        "suspicious_clipboard_pattern",
    }:
        await async_execute(
            """
            INSERT INTO AntiCheatEvents (interview_id, user_id, event_type, payload)
            VALUES (%s, %s, %s, %s)
            """,
            (
                request.interview_id,
                current_user["user_id"],
                request.event_type,
                json.dumps({
                    **_safe_event_metadata(request.payload),
                    "encrypted_payload": encrypt_data(json.dumps(request.payload, separators=(",", ":"), ensure_ascii=False, default=str)),
                }),
            ),
        )
        severity = "severe" if request.event_type in INTEGRITY_SEVERE_ONLY_EVENT_TYPES else "medium"
        await _record_proctoring_flag(request.interview_id, current_user["user_id"], request.event_type, severity, request.payload)
    return {"success": True}


@router.post("/rounds/{round_id}/whiteboard")
async def save_whiteboard(round_id: str, request: WhiteboardSaveRequest, current_user: Dict = Depends(get_current_user)):
    round_row = await _load_round_for_user(round_id, current_user["user_id"])
    await _ensure_round_action_allowed(round_row, current_user["user_id"], "whiteboard")
    updated = await async_execute(
        """
        UPDATE TechnicalInterviewRounds
        SET whiteboard_json = '{"encrypted":true}'::jsonb,
            whiteboard_encrypted = %s
        WHERE round_id = %s AND user_id = %s
        RETURNING round_id
        """,
        (
            encrypt_data(json.dumps(request.whiteboard_json, separators=(",", ":"), ensure_ascii=False)).encode("utf-8"),
            round_id,
            current_user["user_id"],
        ),
        fetchone=True,
    )
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Technical round not found")
    return {"success": True}


def _activate_next_round_locked(cursor: Any, interview_id: str, user_id: str) -> Optional[str]:
    cursor.execute(
        """
        SELECT round_id
        FROM TechnicalInterviewRounds
        WHERE interview_id = %s AND user_id = %s AND status = 'pending'
        ORDER BY round_number
        LIMIT 1
        FOR UPDATE
        """,
        (interview_id, user_id),
    )
    next_row = cursor.fetchone()
    if not next_row:
        return None
    cursor.execute(
        """
        UPDATE TechnicalInterviewRounds round
        SET status = 'active', started_at = NOW(),
            deadline_at = LEAST(
                NOW() + (round.duration_seconds * INTERVAL '1 second'),
                COALESCE(interview.deadline_at, NOW() + (round.duration_seconds * INTERVAL '1 second'))
            )
        FROM Interviews interview
        WHERE round.round_id = %s
          AND round.interview_id = interview.interview_id
          AND round.user_id = interview.user_id
        RETURNING round.round_id
        """,
        (next_row[0],),
    )
    activated = cursor.fetchone()
    return str(activated[0]) if activated else None


def _persist_workflow_evidence_sync(
    round_id: str,
    user_id: str,
    request: TechnicalWorkflowRequest,
) -> Dict[str, Any]:
    connection = get_db_connection()
    cursor = connection.cursor()
    try:
        cursor.execute(
            """
            SELECT round_id, interview_id, round_type, status, deadline_at,
                   workflow_state, round_number
            FROM TechnicalInterviewRounds
            WHERE round_id = %s AND user_id = %s
            FOR UPDATE
            """,
            (round_id, user_id),
        )
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Technical round not found")
        round_type = str(row[2] or "").lower()
        round_status = str(row[3] or "active").lower()
        if round_type not in {"coding", "debugging", "dsa"}:
            raise HTTPException(status_code=409, detail="Workflow evidence applies only to coding or debugging rounds.")
        if round_status in {"pending", "submitted", "completed", "expired", "cancelled"}:
            raise HTTPException(status_code=409, detail="This technical round is not accepting workflow evidence.")
        deadline = _coerce_deadline_utc(row[4])
        if deadline and datetime.now(timezone.utc) >= deadline:
            cursor.execute(
                "UPDATE TechnicalInterviewRounds SET status='expired', completed_at=COALESCE(completed_at,NOW()) WHERE round_id=%s",
                (round_id,),
            )
            raise HTTPException(status_code=410, detail="Time has expired for this technical round.")

        cursor.execute(
            """
            SELECT evidence_id
            FROM TechnicalReasoningEvidence
            WHERE user_id = %s AND round_id = %s AND idempotency_key = %s
            """,
            (user_id, round_id, request.idempotency_key),
        )
        existing = cursor.fetchone()
        workflow_state = _json_value(row[5], {})
        if not isinstance(workflow_state, dict):
            workflow_state = {}
        if existing:
            connection.commit()
            return {
                "round_id": round_id,
                "stage": request.stage,
                "status": "committed",
                "duplicate": True,
                "workflow_state": workflow_state,
                "next_round_id": None,
            }

        content = request.content.strip()
        evidence_hash = hashlib.sha256(
            f"{round_id}|{request.stage}|{content}|{request.idempotency_key}".encode("utf-8")
        ).hexdigest()
        encrypted_payload = encrypt_data(json.dumps({
            "stage": request.stage,
            "content": content,
            "response_seconds": request.response_seconds,
            "idempotency_key": request.idempotency_key,
        }, separators=(",", ":"), ensure_ascii=False)).encode("utf-8")
        safe_payload = {
            "encrypted": True,
            "stage": request.stage,
            "chars": len(content),
            "response_seconds": request.response_seconds,
            "idempotency_key": request.idempotency_key,
        }
        cursor.execute(
            """
            INSERT INTO TechnicalReasoningEvidence (
                user_id, interview_id, round_id, evidence_type, content, payload,
                content_encrypted, idempotency_key, evidence_hash
            ) VALUES (%s, %s, %s, %s, '[encrypted]', %s, %s, %s, %s)
            """,
            (
                user_id, row[1], round_id, f"workflow_{request.stage}",
                json.dumps(safe_payload), encrypted_payload,
                request.idempotency_key, evidence_hash,
            ),
        )
        workflow_state[request.stage] = {
            "committed": True,
            "chars": len(content),
            "evidence_hash": evidence_hash,
        }
        next_round_id = None
        completed_post_submission = bool(
            workflow_state.get("complexity") and workflow_state.get("explanation")
        )
        next_status = "submitted" if round_status == "awaiting_explanation" and completed_post_submission else round_status
        cursor.execute(
            """
            UPDATE TechnicalInterviewRounds
            SET workflow_state = %s,
                status = %s,
                completed_at = CASE WHEN %s = 'submitted' THEN COALESCE(completed_at, NOW()) ELSE completed_at END
            WHERE round_id = %s AND user_id = %s
            """,
            (json.dumps(workflow_state), next_status, next_status, round_id, user_id),
        )
        if next_status == "submitted":
            next_round_id = _activate_next_round_locked(cursor, str(row[1]), user_id)
        connection.commit()
        return {
            "round_id": round_id,
            "stage": request.stage,
            "status": "committed",
            "round_status": next_status,
            "duplicate": False,
            "workflow_state": workflow_state,
            "next_round_id": next_round_id,
        }
    except HTTPException:
        connection.rollback()
        raise
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()
        return_db_connection(connection)


@router.post("/rounds/{round_id}/workflow")
async def submit_workflow_evidence(
    round_id: str,
    request: TechnicalWorkflowRequest,
    current_user: Dict = Depends(get_current_user),
):
    return await asyncio.to_thread(
        _persist_workflow_evidence_sync,
        round_id,
        current_user["user_id"],
        request,
    )


@router.post("/rounds/{round_id}/save-draft")
async def save_draft(round_id: str, request: DraftSaveRequest, current_user: Dict = Depends(get_current_user)):
    round_row = await _load_round_for_user(round_id, current_user["user_id"])
    await _ensure_round_action_allowed(round_row, current_user["user_id"], "save_draft")
    if request.language != str(round_row[14] if len(round_row) > 14 else request.language):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Language must match the frozen round spec.")
    await _record_code_snapshot(
        round_row,
        current_user["user_id"],
        request.language,
        request.code,
        {"event": "save_draft"}
    )
    return {"success": True}



async def _count_integrity_warnings(interview_id: str) -> int:
    row = await async_execute(
        """
        SELECT COUNT(*)
        FROM MalpracticeEvents
        WHERE interview_id = %s
          AND severity = 'warning'
          AND event_type = ANY(%s)
        """,
        (interview_id, list(INTEGRITY_WARNING_EVENT_TYPES)),
        fetchone=True,
    )
    return int(row[0] or 0) if row else 0


async def _flag_technical_interview(interview_id: str, user_id: str, warning_count: int) -> None:
    row = await async_execute(
        "SELECT settings FROM Interviews WHERE interview_id = %s AND user_id = %s",
        (interview_id, user_id),
        fetchone=True,
    )
    if not row:
        return
    settings_json = row[0] or {}
    if isinstance(settings_json, str):
        settings_json = json.loads(settings_json)
    if not isinstance(settings_json, dict):
        settings_json = {}
    settings_json["integrity_status"] = "flagged"
    settings_json["integrity_warning_count"] = warning_count
    settings_json["integrity_flagged_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    await async_execute(
        "UPDATE Interviews SET settings = %s WHERE interview_id = %s AND user_id = %s",
        (json.dumps(settings_json), interview_id, user_id),
    )


@router.get("/sessions/{interview_id}/integrity")
async def get_technical_integrity(interview_id: str, current_user: Dict = Depends(get_current_user)):
    interview = await async_execute(
        "SELECT settings FROM Interviews WHERE interview_id = %s AND user_id = %s",
        (interview_id, current_user["user_id"]),
        fetchone=True,
    )
    if not interview:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Interview not found")
    settings_json = interview[0] or {}
    if isinstance(settings_json, str):
        settings_json = json.loads(settings_json)
    warning_count = await _count_integrity_warnings(interview_id)
    flagged = (
        isinstance(settings_json, dict) and settings_json.get("integrity_status") == "flagged"
    )
    return {
        "warning_count": warning_count,
        "threshold": INTEGRITY_WARNING_THRESHOLD,
        "flagged": flagged,
    }


@router.post("/anti-cheat")
async def record_anti_cheat_event(request: AntiCheatEventRequest, current_user: Dict = Depends(get_current_user)):
    interview = await async_execute(
        "SELECT 1 FROM Interviews WHERE interview_id = %s AND user_id = %s",
        (request.interview_id, current_user["user_id"]),
        fetchone=True,
    )
    if not interview:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Interview not found")
    await async_execute(
        """
        INSERT INTO AntiCheatEvents (interview_id, user_id, event_type, payload)
        VALUES (%s, %s, %s, %s)
        """,
        (
            request.interview_id,
            current_user["user_id"],
            request.event_type,
            json.dumps({
                **_safe_event_metadata(request.payload),
                "encrypted_payload": encrypt_data(json.dumps(request.payload, separators=(",", ":"), ensure_ascii=False, default=str)),
            }),
        ),
    )
    if request.event_type in INTEGRITY_SEVERE_ONLY_EVENT_TYPES:
        severity = "severe"
    elif request.event_type in INTEGRITY_WARNING_EVENT_TYPES:
        severity = "warning"
    else:
        severity = "warning"
    await async_execute(
        """
        INSERT INTO MalpracticeEvents (interview_id, user_id, event_type, severity, payload)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (
            request.interview_id,
            current_user["user_id"],
            request.event_type,
            severity,
            json.dumps({
                **_safe_event_metadata(request.payload),
                "encrypted_payload": encrypt_data(json.dumps(request.payload, separators=(",", ":"), ensure_ascii=False, default=str)),
            }),
        ),
    )
    await _record_proctoring_flag(
        request.interview_id,
        current_user["user_id"],
        request.event_type,
        "high" if severity == "severe" else "medium",
        request.payload,
    )
    warning_count = await _count_integrity_warnings(request.interview_id)
    flagged = warning_count >= INTEGRITY_WARNING_THRESHOLD
    if flagged:
        await _flag_technical_interview(request.interview_id, current_user["user_id"], warning_count)
        await async_execute(
            """
            INSERT INTO MalpracticeEvents (interview_id, user_id, event_type, severity, payload)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (
                request.interview_id,
                current_user["user_id"],
                "session_flagged",
                "severe",
                json.dumps({"warning_count": warning_count, "threshold": INTEGRITY_WARNING_THRESHOLD}),
            ),
        )
    return {
        "success": True,
        "warning_count": warning_count,
        "threshold": INTEGRITY_WARNING_THRESHOLD,
        "flagged": flagged,
    }


async def _load_round_for_user(round_id: str, user_id: str):
    round_row = await async_execute(
        """
        SELECT tir.round_id, tir.interview_id, tir.round_type, tir.prompt, tir.metadata, tir.status,
               tir.created_at, tir.completed_at, i.status AS interview_status, i.settings,
               tir.round_spec, tir.deadline_at, tir.mode, tir.max_submissions,
               tir.language, tir.duration_seconds, tir.round_spec_id,
               tir.workflow_state, tir.problem_version, i.deadline_at AS interview_deadline
        FROM TechnicalInterviewRounds tir
        JOIN Interviews i ON i.interview_id = tir.interview_id AND i.user_id = tir.user_id
        WHERE tir.round_id = %s AND tir.user_id = %s
        """,
        (round_id, user_id),
        fetchone=True,
    )
    if not round_row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Technical round not found")
    return round_row


async def _ensure_round_action_allowed(round_row, user_id: str, action: str) -> None:
    round_status = str(round_row[5] or "active").lower()
    metadata = _json_value(round_row[4], {})
    created_at = round_row[6] if len(round_row) > 6 else None
    interview_status = str(round_row[8] if len(round_row) > 8 else "").lower()
    settings_json = round_row[9] if len(round_row) > 9 else {}
    if isinstance(settings_json, str):
        try:
            settings_json = json.loads(settings_json)
        except Exception:
            settings_json = {}
    if not isinstance(settings_json, dict):
        settings_json = {}

    if interview_status in TERMINAL_TECHNICAL_INTERVIEW_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This interview is no longer accepting technical round changes.",
        )

    if settings_json.get("integrity_status") == "flagged" and action != "save_draft":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This technical round is locked after repeated integrity warnings.",
        )

    if round_status in {"submitted", "submitting", "completed"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This technical round has already been submitted.",
        )
    if round_status == "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Complete the current technical round before starting this one.",
        )
    if round_status == "awaiting_explanation" and action not in {"save_draft"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The final code is locked. Complete the complexity and final explanation steps.",
        )
    if round_status in {"expired", "cancelled"}:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="This technical round is closed.",
        )
    if round_status == "flagged" and action != "save_draft":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This technical round is locked.",
        )

    persisted_deadline = _coerce_deadline_utc(round_row[11] if len(round_row) > 11 else None)
    interview_deadline = _coerce_deadline_utc(round_row[19] if len(round_row) > 19 else None)
    if interview_deadline and (not persisted_deadline or interview_deadline < persisted_deadline):
        persisted_deadline = interview_deadline
    expiry = _round_expiry_payload(created_at=created_at, metadata=metadata)
    if persisted_deadline:
        expiry = {
            **expiry,
            "expires_at": persisted_deadline.isoformat(),
            "remaining_seconds": max(0, int((persisted_deadline - datetime.now(timezone.utc)).total_seconds())),
            "expired": datetime.now(timezone.utc) >= persisted_deadline,
        }
    if expiry["expired"]:
        await async_execute(
            """
            UPDATE TechnicalInterviewRounds
            SET status = 'expired', completed_at = COALESCE(completed_at, NOW())
            WHERE round_id = %s AND user_id = %s AND status NOT IN ('submitted', 'expired', 'cancelled')
            """,
            (round_row[0], user_id),
        )
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Time has expired for this technical round.",
        )


def _frozen_round_cases(round_row: Any, suite: str) -> tuple[List[Dict[str, Any]], int, int]:
    metadata = _json_value(round_row[4], {})
    round_spec = _json_value(round_row[10], {}) if len(round_row) > 10 else {}
    visible = round_spec.get("visible_tests") or metadata.get("visible_tests") or []
    if not isinstance(visible, list):
        visible = []
    hidden: List[Dict[str, Any]] = []
    encrypted_hidden = round_spec.get("hidden_tests_encrypted")
    if encrypted_hidden:
        try:
            decoded = json.loads(decrypt_data(str(encrypted_hidden)))
            hidden = decoded if isinstance(decoded, list) else []
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="The frozen hidden-test contract could not be loaded.",
            ) from None
    elif isinstance(metadata.get("hidden_tests"), list):
        # One-release compatibility read for already-started legacy rounds.
        hidden = metadata.get("hidden_tests") or []
    cases = [dict(case, visible=True) for case in visible if isinstance(case, dict)]
    if suite == "full":
        cases.extend(dict(case, visible=False) for case in hidden if isinstance(case, dict))
    return cases, len(visible), len(hidden) if suite == "full" else 0


async def _start_test_suite_job(
    round_id: str,
    request: TechnicalTestRequest,
    current_user: Dict,
    *,
    suite: str,
    lock_submission: bool,
    submit_number: int = 0,
):
    round_row = await _load_round_for_user(round_id, current_user["user_id"])
    if lock_submission:
        replay_key = _execution_idempotency_key(
            request,
            round_id=round_id,
            action="submit",
            suite=suite,
        )
        replay = await _existing_execution_job(
            current_user["user_id"],
            replay_key,
            round_id=round_id,
            action="submit",
            source_hash=hashlib.sha256(request.code.encode("utf-8")).hexdigest(),
        )
        if replay:
            return replay
    try:
        await _ensure_round_action_allowed(
            round_row,
            current_user["user_id"],
            "submit" if lock_submission else "test",
        )
    except HTTPException as exc:
        if not lock_submission or exc.status_code != status.HTTP_409_CONFLICT:
            raise
        replay = await _existing_execution_job(
            current_user["user_id"],
            replay_key,
            round_id=round_id,
            action="submit",
            source_hash=hashlib.sha256(request.code.encode("utf-8")).hexdigest(),
        )
        if replay:
            return replay
        raise
    if str(round_row[2]) not in {"coding", "debugging", "dsa"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This round does not execute code.")
    frozen_language = str(round_row[14] if len(round_row) > 14 else request.language)
    if request.language != frozen_language:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Language must match the frozen round spec.")
    _require_executor_available()
    cases, visible_total, hidden_total = _frozen_round_cases(round_row, suite)
    if not cases:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No test cases are available for this problem")
    return await _queue_execution_job(
        round_row=round_row,
        user_id=current_user["user_id"],
        request=request,
        action="submit" if lock_submission else "test",
        suite=suite,
        cases=cases,
        lock_submission=lock_submission,
        visible_total=visible_total,
        hidden_total=hidden_total,
    )



async def _execute_code(language: str, code: str, stdin: str) -> Dict[str, Any]:
    _require_executor_available()
    try:
        return await _execute_piston(language, code, stdin)
    except HTTPException:
        raise
    except Exception:
        logger.warning("Private isolated sandbox execution failed", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The private code execution service is temporarily unavailable.",
        ) from None


async def _resolve_piston_runtime(language: str) -> Dict[str, str]:
    if language in PISTON_RUNTIME_CACHE:
        return PISTON_RUNTIME_CACHE[language]
    aliases = PISTON_LANGUAGE_ALIASES.get(language)
    if not aliases:
        raise HTTPException(status_code=400, detail="Unsupported language")
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=6)) as session:
            headers = {"Authorization": f"Bearer {settings.PISTON_API_TOKEN}"} if settings.PISTON_API_TOKEN else {}
            async with session.get(settings.PISTON_API_URL.rstrip("/") + "/runtimes", headers=headers) as response:
                if response.status >= 400:
                    raise HTTPException(status_code=502, detail="Could not load code runtimes")
                runtimes = await response.json()
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=502, detail="Code execution service unavailable") from None
    for runtime in runtimes:
        names = {runtime.get("language"), *(runtime.get("aliases") or [])}
        if aliases & {str(name).lower() for name in names if name}:
            resolved = {"language": runtime["language"], "version": runtime["version"]}
            PISTON_RUNTIME_CACHE[language] = resolved
            return resolved
    raise HTTPException(status_code=502, detail=f"No code runtime for {language}")


async def _execute_piston(language: str, code: str, stdin: str) -> Dict[str, Any]:
    runtime = await _resolve_piston_runtime(language)
    payload = {
        "language": runtime["language"],
        "version": runtime["version"],
        "files": [{"name": FILE_NAMES[language], "content": code}],
        "stdin": stdin or "",
        "compile_timeout": 10000,
        "run_timeout": 2000,
        "compile_cpu_time": 10000,
        "run_cpu_time": 2000,
        "compile_memory_limit": 256 * 1024 * 1024,
        "run_memory_limit": 256 * 1024 * 1024,
    }
    started = time.time()
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
        raise HTTPException(status_code=502, detail="Code execution service unavailable") from None
    run = result.get("run") or {}
    compile_result = result.get("compile") or {}
    stdout = str(run.get("stdout") or "")
    stderr = str(run.get("stderr") or compile_result.get("stderr") or compile_result.get("output") or "")
    combined = (stdout + stderr).encode("utf-8", errors="replace")
    if len(combined) > MAX_EXECUTION_OUTPUT_BYTES:
        stdout_bytes = stdout.encode("utf-8", errors="replace")[:MAX_EXECUTION_OUTPUT_BYTES]
        stdout = stdout_bytes.decode("utf-8", errors="ignore")
        remaining = max(0, MAX_EXECUTION_OUTPUT_BYTES - len(stdout.encode("utf-8")))
        stderr = stderr.encode("utf-8", errors="replace")[:remaining].decode("utf-8", errors="ignore")
        stderr = (stderr + "\n[output truncated at 64 KB]").strip()
    run_code = run.get("code")
    compile_code = compile_result.get("code")
    exit_code = int(run_code if run_code is not None else (compile_code if compile_code is not None else 0))
    execution_status = str(run.get("status") or compile_result.get("status") or "").upper()
    timed_out = execution_status == "TO"
    accepted = exit_code == 0 and not execution_status
    wall_time_ms = int(run.get("wall_time") or compile_result.get("wall_time") or 0)
    memory_bytes = int(run.get("memory") or compile_result.get("memory") or 0)
    return {
        "stdout": stdout,
        "stderr": stderr,
        "exit_code": exit_code,
        "status_id": 3 if accepted else (5 if timed_out else 6),
        "status_description": "Accepted" if accepted else ("Time Limit Exceeded" if timed_out else "Runtime Error"),
        "runtime_ms": wall_time_ms or int((time.time() - started) * 1000),
        "memory_kb": max(0, memory_bytes // 1024),
        "executor": "isolated_sandbox",
    }


def _judge0_verdict(result: Dict[str, Any]) -> str:
    status_id = int(result.get("status_id") or 0)
    if status_id == 3:
        return "Accepted"
    if status_id == 4:
        return "Wrong Answer"
    if status_id == 5:
        return "TLE"
    return "Runtime Error"


def _outputs_match(stdout: str, expected: str) -> bool:
    """Compare output after normalizing whitespace and line endings."""
    actual = (stdout or "").replace("\r\n", "\n").strip()
    exp = str(expected or "").replace("\r\n", "\n").strip()
    return actual == exp


def _case_verdict(result: Dict[str, Any], case: Dict[str, Any]) -> str:
    verdict = _judge0_verdict(result)
    if verdict != "Accepted":
        return verdict
    return "Accepted" if _outputs_match(result.get("stdout", ""), str(case.get("expected", ""))) else "Wrong Answer"


async def _record_code_snapshot(round_row, user_id: str, language: str, code: str, metadata: Dict[str, Any]):
    await async_execute(
        """
        INSERT INTO TechnicalCodeSnapshots (
            snapshot_id, round_id, interview_id, user_id, language,
            source_chars, code_hash, source_excerpt, source_code,
            source_code_encrypted, metadata
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, '[encrypted]', '[encrypted]', %s, %s)
        """,
        (
            str(uuid.uuid4()),
            round_row[0],
            round_row[1],
            user_id,
            language,
            len(code),
            hashlib.sha256(code.encode("utf-8")).hexdigest(),
            encrypt_data(code).encode("utf-8"),
            json.dumps(metadata),
        ),
    )


def _safe_event_metadata(payload: Dict[str, Any], *, idempotency_key: Optional[str] = None) -> Dict[str, Any]:
    safe: Dict[str, Any] = {"encrypted": True}
    for key, value in (payload or {}).items():
        if isinstance(value, bool) or isinstance(value, (int, float)):
            safe[str(key)[:60]] = value
        elif key in {"kind", "capture", "renderer", "round_type", "surface", "stage"}:
            safe[str(key)[:60]] = str(value)[:80]
    if idempotency_key:
        safe["idempotency_key"] = idempotency_key
    return safe


async def _record_technical_event(
    interview_id: str,
    round_id: Optional[str],
    user_id: str,
    event_type: str,
    payload: Dict[str, Any],
    *,
    idempotency_key: Optional[str] = None,
):
    encrypted_payload = encrypt_data(
        json.dumps(payload or {}, separators=(",", ":"), ensure_ascii=False, default=str)
    ).encode("utf-8")
    safe_payload = _safe_event_metadata(payload or {}, idempotency_key=idempotency_key)
    await async_execute(
        """
        INSERT INTO TechnicalTelemetryEvents (
            interview_id, round_id, user_id, event_type, payload,
            payload_encrypted, idempotency_key
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (user_id, round_id, idempotency_key)
            WHERE idempotency_key IS NOT NULL
            DO NOTHING
        """,
        (
            interview_id, round_id, user_id, event_type[:50],
            json.dumps(safe_payload), encrypted_payload, idempotency_key,
        ),
    )
    if event_type in {
        "technical_transcript",
        "spoken_explanation",
        "written_approach",
        "clarifying_question",
        "hint_requested",
        "constraint_reveal",
    }:
        content = str(
            (payload or {}).get("text")
            or (payload or {}).get("transcript")
            or (payload or {}).get("question")
            or (payload or {}).get("approach")
            or ""
        ).strip()
        evidence_hash = hashlib.sha256(
            f"{interview_id}|{round_id}|{event_type}|{content}|{idempotency_key or ''}".encode("utf-8")
        ).hexdigest()
        await async_execute(
            """
            INSERT INTO TechnicalReasoningEvidence (
                user_id, interview_id, round_id, evidence_type, content, payload,
                content_encrypted, idempotency_key, evidence_hash
            )
            VALUES (%s, %s, %s, %s, '[encrypted]', %s, %s, %s, %s)
            ON CONFLICT (user_id, round_id, idempotency_key)
                WHERE idempotency_key IS NOT NULL
                DO NOTHING
            """,
            (
                user_id, interview_id, round_id, event_type[:50],
                json.dumps(safe_payload), encrypted_payload, idempotency_key, evidence_hash,
            ),
        )


async def _record_proctoring_flag(interview_id: str, user_id: str, flag_type: str, severity: str, evidence: Dict[str, Any]) -> None:
    try:
        await async_execute(
            """
            INSERT INTO ProctoringFlags (interview_id, user_id, flag_type, severity, evidence)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (
                interview_id,
                user_id,
                flag_type[:60],
                severity,
                json.dumps({
                    **_safe_event_metadata(evidence or {}),
                    "encrypted_payload": encrypt_data(json.dumps(evidence or {}, separators=(",", ":"), ensure_ascii=False, default=str)),
                }),
            ),
        )
    except Exception:
        logger.warning("Proctoring flag write skipped for %s", flag_type)
