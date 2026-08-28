# ============================================================================
# MODULE: interview.py
# PURPOSE: Live interview engine — WebSocket video/audio loop, persona, opening
#          statement, knowledge-map driven battlegrounds, follow-ups, evaluation,
#          coaching hints, optional self-review signals, async report queueing.
#          Mounted under /api/interview.
# STRUCTURE:
#   - Pydantic request/response models (~lines 50-100)
#   - Helper functions (knowledge-map persistence, scoring) (~lines 100-300)
#   - REST endpoints (lines 301-642)
#   - WebSocket handler (lines 644-1374)
#   - GET status / report + DELETE cancel (lines 1376-1576)
# ENDPOINTS (prefix /api/interview):
#   - POST   /start               -> create Interviews row + persona (317)
#   - WS     /ws/video            -> local live interview loop
#   - GET    /status/{id}         -> in-progress / completed state (1376)
#   - GET    /report/{id}         -> final report_json (1411)
#   - DELETE /cancel/{id}         -> mark cancelled (1521)
# DEPENDS ON: database, config, local_cache, ai_services, body_language,
#             persona_generator, strictness_config, analysis_pipeline, coach,
#             learning_engine, knowledge_map, interview_profiles, security_utils
# CONSUMED BY: app.py, Frontend/app/interview/[id]/page.tsx (WS),
#              Frontend/lib/api.ts (startInterviewSession, fetchInterviewStatus,
#              fetchInterviewReport)
# DATA TABLES: Interviews, InterviewQuestions, InterviewResponses,
#              ClientBodyLanguageMetrics, optional self-review signal storage,
#              SkillEvidenceEvents (via learning_engine)
#              (Phase 2 merges *Events into InterviewEvents; Phase 2 drops 5
#               redundant scoring columns on InterviewResponses)
# ============================================================================

from fastapi import APIRouter, Depends, HTTPException, status, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator, model_validator
from typing import Any, Dict, List, Literal, Optional
from collections import deque
from datetime import datetime, timedelta, timezone
from time import time
import json
import re
import uuid
import logging
import asyncio
import hashlib
import math
from local_runtime import (
    LOCAL_USER_ID,
    api_token_matches,
    configured_api_token,
    has_provider_api_key,
    is_allowed_local_origin,
    is_loopback_host,
)

from local_runtime import local_user
from database import get_db_connection, return_db_connection, async_execute
from config import settings
from local_cache import get_local_cache
from ai_services import transcribe_audio
from analysis_pipeline import (
    ANALYSIS_STAGE_VERSION,
    _safe_report_payload,
    enqueue_analysis,
    operator_retry_analysis,
)
from body_language import normalize_client_metrics
from persona_generator import generate_persona
from interview_capabilities import is_technical_interview_type, normalize_technical_profile
from knowledge_map import (
    build_knowledge_map,
    get_next_battleground,
    mark_turn_used,
    is_interview_complete,
    should_transition,
    get_transition_to_next,
    generate_battleground_question,
    generate_contextual_followup
)
from interview_profiles import (
    DEFAULT_PROFILE_TYPE,
    TECHNICAL_CODING_QUESTION_COUNT,
    TECHNICAL_MINUTES_PER_QUESTION,
    TECHNICAL_TOTAL_DURATION_MINUTES,
    get_profile_config,
    normalize_profile_type,
)
from security_utils import redact_text, stable_hash, collect_profile_identifiers, redact_pii_text
from security_utils import decrypt_data, decrypt_json_field, encrypt_data
from interview_blueprint import compile_interview_blueprint, validate_blueprint, weakness_label
from evaluation_engine import EVALUATION_VERSION, evaluate_answer
from learning_engine import ensure_mission_from_response_assessment
from attempt_context import create_attempt_context_snapshot
from ws_contract import (
    CONTROLLER_RENEWAL_SECONDS,
    WSContractError,
    acquire_controller_lease,
    canonical_integrity_event,
    claim_event_sequence,
    parse_client_event,
    release_controller_lease,
    renew_controller_lease,
)

router = APIRouter(tags=["Interview"])
logger = logging.getLogger("ai_interviewer.interview")
REPORT_READY_STATUSES = {"completed", "report_ready", "partial", "failed"}
ANALYSIS_ACTIVE_STATUSES = {"analysis_pending", "analysis_running"}
LIVE_INTERVIEW_STATUSES = {"in_progress", "uploading", "recovering"}
FINALIZED_INTERVIEW_STATUSES = REPORT_READY_STATUSES | ANALYSIS_ACTIVE_STATUSES | {"cancelled"}
MIN_LIVE_ANSWER_WORDS = 2
MIN_LIVE_ANSWER_CHARS = 6
MIN_LIVE_AUDIO_DURATION_MS = 650
MAX_LIVE_ANSWER_QUALITY_FAILURES = 3
def _is_usable_live_answer(answer: str) -> bool:
    cleaned = re.sub(r"\s+", " ", str(answer or "")).strip()
    words = re.findall(r"\b[\w']+\b", cleaned)
    compact = re.sub(r"[^\w]", "", cleaned, flags=re.UNICODE)
    return len(words) >= MIN_LIVE_ANSWER_WORDS and len(compact) >= MIN_LIVE_ANSWER_CHARS


def _live_answer_quality(evaluation: Dict[str, Any]) -> tuple[bool, str]:
    """Fail closed when an answer is clearly unrelated or nonsensical."""

    signals = evaluation.get("signals") if isinstance(evaluation, dict) else {}
    signals = signals if isinstance(signals, dict) else {}
    lexical = signals.get("lexical_relevance") if isinstance(signals, dict) else {}
    lexical = lexical if isinstance(lexical, dict) else {}
    structure = signals.get("structure") if isinstance(signals, dict) else {}
    structure = structure if isinstance(structure, dict) else {}
    specificity = signals.get("specificity_evidence") if isinstance(signals, dict) else {}
    specificity = specificity if isinstance(specificity, dict) else {}
    ownership = signals.get("ownership") if isinstance(signals, dict) else {}
    ownership = ownership if isinstance(ownership, dict) else {}
    directness = signals.get("directness") if isinstance(signals, dict) else {}
    directness = directness if isinstance(directness, dict) else {}
    semantic = evaluation.get("semantic_status") if isinstance(evaluation, dict) else {}
    semantic = semantic if isinstance(semantic, dict) else {}

    if semantic.get("state") == "completed" and semantic.get("answer_relevant") is False:
        return False, "answer_not_relevant"

    word_count = int(signals.get("word_count") or 0)
    if word_count < 8:
        return False, "answer_too_brief"

    relevance = float(lexical.get("score") or 0)
    structure_score = float(structure.get("score") or 0)
    evidence_score = float(specificity.get("score") or 0)
    ownership_score = float(ownership.get("score") or 0)
    directness_score = float(directness.get("score") or 0)
    if relevance >= 25:
        return True, "relevant"
    if (
        relevance < 18
        and structure_score < 35
        and evidence_score < 35
        and ownership_score < 60
    ):
        return False, "answer_not_relevant"
    if directness_score < 20 and structure_score < 35 and evidence_score < 35:
        return False, "answer_not_direct"
    return True, "relevant_without_keyword_overlap"


def _live_answer_feedback(reason: str) -> str:
    if reason == "answer_too_brief":
        return "That answer was too brief to evaluate. Please answer the question directly and complete your thought."
    if reason == "answer_not_direct":
        return "That response was not direct enough for the question. Please answer the question first, then explain why."
    return "That response did not answer the question. Please stay on the requested topic and give a concrete answer."


def _live_retry_question(
    question: str,
    topic: str,
    reason: str,
    attempt: int,
) -> str:
    focus = str(topic or "the requested topic").strip()[:120]
    original = re.sub(r"\s+", " ", str(question or "")).strip()[:420]
    # Keep retries anchored to the original prompt instead of nesting the
    # previous retry instruction inside the next question.
    retry_prefixes = (
        r"^Please answer the question directly about .+?:\s*",
        r"^I still need a relevant answer about .+?\. Give one concrete example, then answer:\s*",
    )
    for _ in range(3):
        unwrapped = original
        for prefix in retry_prefixes:
            unwrapped = re.sub(prefix, "", unwrapped, count=1, flags=re.IGNORECASE).strip()
        if unwrapped == original:
            break
        original = unwrapped
    if attempt <= 1:
        return f"Please answer the question directly about {focus}: {original}"
    return f"I still need a relevant answer about {focus}. Give one concrete example, then answer: {original}"


def _can_voluntarily_cancel(status_value: object) -> bool:
    return str(status_value or "").lower() in LIVE_INTERVIEW_STATUSES


async def _has_persisted_candidate_evidence(interview_id: str, user_id: str) -> bool:
    row = await async_execute(
        """
        SELECT (
            EXISTS (
                SELECT 1
                FROM InterviewResponses response
                JOIN Interviews owner ON owner.interview_id = response.interview_id
                WHERE response.interview_id = ? AND owner.user_id = ?
            )
            OR EXISTS (
                SELECT 1 FROM TechnicalSubmissions
                WHERE interview_id = ? AND user_id = ?
            )
            OR EXISTS (
                SELECT 1 FROM TechnicalRunEvents event
                JOIN TechnicalInterviewRounds round ON round.round_id = event.round_id
                WHERE round.interview_id = ? AND event.user_id = ?
            )
            OR EXISTS (
                SELECT 1 FROM TechnicalCodeSnapshots
                WHERE interview_id = ? AND user_id = ? AND source_chars > 0
            )
            OR EXISTS (
                SELECT 1 FROM TechnicalExecutionJobs
                WHERE interview_id = ? AND user_id = ?
                  AND status IN ('queued', 'leased', 'running', 'completed')
            )
        )
        """,
        (
            interview_id, user_id,
            interview_id, user_id,
            interview_id, user_id,
            interview_id, user_id,
            interview_id, user_id,
        ),
        fetchone=True,
    )
    return bool(row and row[0])
_INTERVIEW_RECOVERY_TASKS: Dict[str, asyncio.Task] = {}


async def _record_server_integrity_event(
    interview_id: str,
    user_id: str,
    event_type: str,
    payload: Optional[Dict[str, Any]] = None,
) -> None:
    canonical_type = canonical_integrity_event(event_type)
    event_id = str(uuid.uuid4())
    encoded = json.dumps(payload or {}, sort_keys=True, separators=(",", ":"), default=str)
    await async_execute(
        """
        INSERT INTO AttemptIntegrityEvents (
            event_id, interview_id, user_id, client_session_id, sequence,
            event_type, severity, source, observed_at, received_at,
            payload_encrypted, payload_hash, idempotency_key
        ) VALUES (?, ?, ?, ?, 1, ?, 'info', 'server', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, ?, ?, ?)
        ON CONFLICT DO NOTHING
        """,
        (
            event_id, interview_id, user_id, event_id, canonical_type,
            encrypt_data(encoded).encode("utf-8"),
            hashlib.sha256(encoded.encode("utf-8")).hexdigest(), event_id,
        ),
    )


async def _mark_interview_recovering(interview_id: str, user_id: str) -> None:
    recovery_deadline = datetime.now(timezone.utc) + timedelta(seconds=settings.SESSION_RECOVERY_GRACE_SECONDS)
    updated = await async_execute(
        """
        UPDATE Interviews
        SET status = 'recovering',
            attempt_status = 'recovering',
            recovery_deadline_at = ?,
            lifecycle_revision = lifecycle_revision + 1,
            settings = json_set(
                COALESCE(settings, '{}'),
                '$.recovery_deadline', ?,
                '$.recovery_reason', 'connection_interrupted'
            )
        WHERE interview_id = ? AND user_id = ? AND status IN ('in_progress', 'uploading')
        RETURNING interview_id
        """,
        (recovery_deadline, recovery_deadline.isoformat(), interview_id, user_id),
        fetchone=True,
    )
    if not updated:
        return
    await _record_server_integrity_event(
        interview_id,
        user_id,
        "connection_interrupted",
        {"recovery_deadline": recovery_deadline.isoformat()},
    )
    await async_execute(
        """
        INSERT INTO SelfReviewEvents (interview_id, user_id, event_type, payload)
        VALUES (?, ?, 'connection_interrupted', ?)
        """,
        (interview_id, user_id, json.dumps({"recovery_deadline": recovery_deadline.isoformat()})),
    )


async def _abandon_interview_after_recovery(interview_id: str, user_id: str) -> None:
    try:
        await asyncio.sleep(settings.SESSION_RECOVERY_GRACE_SECONDS)
        expired = await async_execute(
            """
            UPDATE Interviews
            SET status = 'cancelled', completed_at = COALESCE(completed_at, CURRENT_TIMESTAMP),
                attempt_status = 'incomplete', analysis_status = 'not_requested',
                completion_kind = 'recovery_expired', recovery_deadline_at = NULL,
                lifecycle_revision = lifecycle_revision + 1,
                overall_score = NULL,
                duration_seconds = CASE
                    WHEN started_at IS NULL THEN duration_seconds
                    ELSE MAX(0, CAST(
                        (julianday(CURRENT_TIMESTAMP) - julianday(started_at)) * 86400
                        AS INTEGER
                    ))
                END,
                feedback_summary = 'Attempt incomplete because connection recovery expired.',
                settings = json_patch(
                    json_remove(COALESCE(settings, '{}'), '$.recovery_deadline', '$.recovery_reason'),
                    json_object('abandonment_reason', 'recovery_timeout')
                )
            WHERE interview_id = ? AND user_id = ? AND status = 'recovering'
            RETURNING interview_id, user_id, completed_at
            """,
            (interview_id, user_id),
            fetchone=True,
        )
        if expired:
            await async_execute(
                """
                UPDATE TechnicalInterviewRounds
                SET status = 'cancelled',
                    completed_at = COALESCE(completed_at, ?, CURRENT_TIMESTAMP)
                WHERE interview_id = ?
                  AND user_id = ?
                  AND status NOT IN ('submitted', 'completed', 'expired', 'cancelled')
                """,
                (expired[2], interview_id, user_id),
            )
        if expired:
            await _record_server_integrity_event(interview_id, user_id, "recovery_expired")
    finally:
        _INTERVIEW_RECOVERY_TASKS.pop(interview_id, None)


def _schedule_interview_recovery(interview_id: str, user_id: str) -> None:
    previous = _INTERVIEW_RECOVERY_TASKS.pop(interview_id, None)
    if previous:
        previous.cancel()
    _INTERVIEW_RECOVERY_TASKS[interview_id] = asyncio.create_task(
        _abandon_interview_after_recovery(interview_id, user_id)
    )


def _cancel_interview_recovery(interview_id: str) -> None:
    task = _INTERVIEW_RECOVERY_TASKS.pop(interview_id, None)
    if task:
        task.cancel()


def _quick_live_score(answer: str, response_seconds: float) -> Dict[str, Any]:
    words = [word for word in (answer or "").split() if word.strip()]
    text = (answer or "").lower()
    score = 45
    flags: List[str] = []
    if len(words) >= 45:
        score += 16
    else:
        flags.append("too_short")
    if any(token in text for token in ("built", "implemented", "designed", "debugged", "owned", "deployed")):
        score += 10
    else:
        flags.append("no_evidence")
    if any(token in text for token in ("because", "trade-off", "constraint", "edge case", "alternative")):
        score += 10
    else:
        flags.append("missing_tradeoff")
    if any(char.isdigit() for char in text) or any(token in text for token in ("%", "users", "latency", "cost", "accuracy")):
        score += 10
    else:
        flags.append("missing_metric")
    if 8 <= response_seconds <= 240:
        score += 9
    return {
        "score": max(0, min(100, score)),
        "flags": flags,
        "feedback": "Live heuristic score; final scoring runs in async analysis.",
    }

class StartInterviewRequest(BaseModel):
    interview_mode: Literal["mock"] = "mock"
    interview_type: str = "Mock Interview"
    blueprint_id: Optional[str] = Field(default=None, max_length=64)
    start_idempotency_key: Optional[str] = Field(default=None, min_length=8, max_length=120)
    preflight_id: Optional[str] = Field(default=None, min_length=8, max_length=64)
    job_id: Optional[int] = None
    job_profile_id: Optional[int] = None
    resume_id: Optional[str] = Field(default=None, max_length=64)
    profile_type: Optional[str] = None
    custom_job_title: Optional[str] = None
    custom_job_description: Optional[str] = None
    company_name: Optional[str] = None
    experience_level: Optional[str] = Field(default=None, max_length=40)
    difficulty_level: str = Field(default="adaptive", pattern="^(adaptive|easy|medium|hard)$")
    duration_minutes: Optional[int] = Field(default=None, ge=10, le=120)
    focus: List[str] = Field(default_factory=lambda: ["mixed"], max_length=6)
    programming_language: str = Field(default="python", pattern="^(python|javascript|cpp|java)$")
    technical_topics: List[str] = Field(default_factory=list, max_length=12)
    technical_round_types: List[str] = Field(default_factory=list, max_length=12)
    question_count: Optional[int] = Field(default=None, ge=1, le=12)
    input_mode: str = Field(default="text", pattern="^(voice|text|voice_or_text)$")
    camera_mode: str = Field(default="optional", pattern="^(off|optional)$")

    @field_validator("profile_type")
    @classmethod
    def validate_profile_type(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        normalized = normalize_profile_type(value)
        if normalized != value.strip().lower():
            raise ValueError("Unsupported interview profile type")
        return normalized

    @field_validator("focus")
    @classmethod
    def validate_focus(cls, value: List[str]) -> List[str]:
        allowed = {"mixed", "resume", "project", "projects", "behavioral", "hr", "role", "role-specific", "technical"}
        normalized = list(dict.fromkeys(str(item).strip().lower() for item in value if str(item).strip()))
        invalid = [item for item in normalized if item not in allowed]
        if invalid:
            raise ValueError(f"Unsupported interview focus: {', '.join(invalid)}")
        return normalized or ["mixed"]

    @field_validator("technical_round_types")
    @classmethod
    def validate_technical_round_types(cls, value: List[str]) -> List[str]:
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
        normalized: List[str] = []
        for item in value or []:
            key = str(item or "").strip().lower()
            mapped = aliases.get(key)
            if not mapped:
                raise ValueError(f"Unsupported technical round type: {item}")
            if mapped not in normalized:
                normalized.append(mapped)
        return normalized

class CreateInterviewBlueprintRequest(BaseModel):
    interview_mode: str = Field(default="mock", pattern="^mock$")
    interview_type: str = Field(default="Mock Interview", min_length=2, max_length=50)
    resume_id: Optional[str] = Field(default=None, max_length=64)
    job_id: Optional[int] = None
    job_profile_id: Optional[int] = None
    profile_type: Optional[str] = None
    custom_job_title: Optional[str] = Field(default=None, max_length=255)
    custom_job_description: Optional[str] = Field(default=None, max_length=12000)
    company_name: Optional[str] = Field(default=None, max_length=255)
    experience_level: Optional[str] = Field(default=None, max_length=40)
    difficulty_level: str = Field(default="adaptive", pattern="^(adaptive|easy|medium|hard)$")
    duration_minutes: int = Field(default=45, ge=10, le=120)
    focus: List[str] = Field(default_factory=lambda: ["mixed"], max_length=6)
    programming_language: str = Field(default="python", pattern="^(python|javascript|cpp|java)$")
    technical_topics: List[str] = Field(default_factory=list, max_length=12)
    technical_round_types: List[str] = Field(default_factory=list, max_length=12)
    question_count: Optional[int] = Field(default=None, ge=1, le=12)
    input_mode: str = Field(default="voice_or_text", pattern="^(voice|text|voice_or_text)$")
    camera_mode: str = Field(default="optional", pattern="^(off|optional)$")

    @field_validator("profile_type")
    @classmethod
    def validate_profile_type(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        normalized = normalize_profile_type(value)
        if normalized != value.strip().lower():
            raise ValueError("Unsupported interview profile type")
        return normalized

    @field_validator("focus")
    @classmethod
    def validate_focus(cls, value: List[str]) -> List[str]:
        return StartInterviewRequest.validate_focus(value)

    @field_validator("technical_round_types")
    @classmethod
    def validate_technical_round_types(cls, value: List[str]) -> List[str]:
        return StartInterviewRequest.validate_technical_round_types(value)

class InterviewResponse(BaseModel):
    interview_id: str
    session_id: str
    mode: str
    message: str
    persona: Dict
    settings: Dict
    attempt_status: str = "active"
    analysis_status: str = "not_requested"
    integrity_status: str = "clean"
    started_at: Optional[datetime] = None
    deadline_at: Optional[datetime] = None
    server_time: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    recovery_grace_seconds: int = settings.SESSION_RECOVERY_GRACE_SECONDS
    lifecycle_revision: int = 1


class MediaUploadUrlRequest(BaseModel):
    media_kind: str
    content_type: Optional[str] = Field(default=None, max_length=80)
    chunk_index: Optional[int] = Field(default=None, ge=0, le=10000)
    chunk_count: Optional[int] = Field(default=None, ge=1, le=10000)
    byte_size: Optional[int] = Field(default=None, ge=0, le=25 * 1024 * 1024)


class MediaChunkCompleteRequest(BaseModel):
    asset_id: str = Field(min_length=1, max_length=64)
    media_kind: str
    object_key: str = Field(min_length=1, max_length=512)
    content_type: Optional[str] = Field(default=None, max_length=80)
    byte_size: int = Field(default=0, ge=0, le=25 * 1024 * 1024)
    chunk_index: Optional[int] = Field(default=None, ge=0, le=10000)
    chunk_count: Optional[int] = Field(default=None, ge=1, le=10000)
    checksum: Optional[str] = Field(default=None, pattern=r"^[a-fA-F0-9]{64}$")
    metadata: Dict[str, Any] = Field(default_factory=dict)


def _raw_media_retention_enabled(media_kind: str) -> bool:
    kind = str(media_kind or "").strip().lower()
    if kind == "video":
        return settings.RAW_VIDEO_RETENTION_HOURS > 0
    if kind == "audio":
        return settings.AUDIO_RETENTION_DAYS > 0
    return False


def _validated_media_content_type(media_kind: str, content_type: Optional[str]) -> str:
    normalized = str(content_type or "").split(";", 1)[0].strip().lower()
    allowed = {
        "video": {"video/webm"},
        "audio": {"audio/webm", "audio/ogg"},
    }
    if normalized not in allowed.get(media_kind, set()):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Unsupported interview media content type.",
        )
    return normalized


def _require_raw_media_retention(media_kind: str) -> str:
    kind = str(media_kind or "").strip().lower()
    if kind not in {"audio", "video"}:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="media_kind must be audio or video")
    if not _raw_media_retention_enabled(kind):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Raw media retention is disabled. Only transcript, timing, and approved browser metrics are stored.",
        )
    return kind

def _db_execute(query, params=None, fetchone=False, fetchall=False, commit=False):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(query, params)
        result = None
        if fetchone:
            result = cursor.fetchone()
        elif fetchall:
            result = cursor.fetchall()
        if commit:
            conn.commit()
        return result, cursor.rowcount
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()
        return_db_connection(conn)

def _json_load(value, default):
    if value is None:
        return default
    from security_utils import decrypt_json
    try:
        decrypted = decrypt_json(value)
        if decrypted is not None:
            return decrypted
    except Exception:
        pass
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except Exception:
        return default


def _decrypt_json_blob(value: Any, default: Any = None) -> Any:
    if value is None:
        return default
    if isinstance(value, memoryview):
        value = value.tobytes()
    if isinstance(value, (bytes, bytearray)):
        value = bytes(value).decode("utf-8", errors="strict")
    try:
        decrypted = decrypt_data(str(value))
        parsed = json.loads(decrypted)
        return parsed
    except Exception:
        return default

def _score_value(scores: Dict, key: str) -> Optional[float]:
    value = (scores or {}).get(key)
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _profile_context_from_rows(resume_json: Dict[str, Any], profile_json: Dict[str, Any], external_profile_signals: Dict[str, Any]) -> Dict[str, Any]:
    context = dict(resume_json or profile_json or {})
    if "projects" not in context and isinstance(profile_json, dict):
        context["projects"] = profile_json.get("projects", [])
    if "experience" not in context and isinstance(profile_json, dict):
        context["experience"] = profile_json.get("experience") or profile_json.get("experiences") or []
    context["external_profile_signals"] = external_profile_signals or {}
    return context


def _profile_has_minimum(profile: Dict[str, Any]) -> bool:
    if not isinstance(profile, dict):
        return False
    return bool(str(profile.get("name") or "").strip() and profile.get("skills"))


def _best_available_profile(profile_json: Any, resume_json: Any) -> Dict[str, Any]:
    profile = _json_load(profile_json, {})
    resume = _json_load(resume_json, {})
    if _profile_has_minimum(profile):
        return profile
    if _profile_has_minimum(resume):
        return resume
    merged = {**(resume if isinstance(resume, dict) else {}), **(profile if isinstance(profile, dict) else {})}
    if not merged.get("skills"):
        merged["skills"] = (profile if isinstance(profile, dict) else {}).get("skills") or (resume if isinstance(resume, dict) else {}).get("skills") or []
    return merged


def _load_previous_weaknesses(cursor: Any, user_id: str, limit: int = 5) -> List[Dict[str, Any]]:
    """Load evidence-backed weaknesses for deterministic blueprint priority."""
    cursor.execute(
        """
        SELECT skill_key, mastery_score, confidence_score, evidence_count, last_evidence_at
        FROM LearnerSkillStates
        WHERE user_id = ?
          AND evidence_count > 0
          AND mastery_score < 70
        ORDER BY confidence_score DESC, mastery_score ASC, last_evidence_at DESC NULLS LAST
        LIMIT ?
        """,
        (user_id, limit),
    )
    normalized: List[Dict[str, Any]] = []
    seen_labels = set()
    for row in cursor.fetchall() or []:
        label = weakness_label(row[0])
        if not label or label.lower() in seen_labels:
            continue
        seen_labels.add(label.lower())
        normalized.append({
            "skill_key": row[0],
            "label": label,
            "mastery_score": float(row[1] or 0),
            "confidence_score": float(row[2] or 0),
            "evidence_count": int(row[3] or 0),
            "last_evidence_at": row[4].isoformat() if row[4] else None,
            "source": "learner_skill_state",
        })
        if len(normalized) >= limit:
            break
    return normalized


def _rows_to_turns(rows: List[Any]) -> List[Dict[str, Any]]:
    turns: List[Dict[str, Any]] = []
    for row in rows or []:
        encrypted_assessment_layout = len(row) >= 30
        assessment_offset = 1 if encrypted_assessment_layout else 0
        encrypted_answer = row[5]
        if isinstance(encrypted_answer, memoryview):
            encrypted_answer = encrypted_answer.tobytes()
        if isinstance(encrypted_answer, (bytes, bytearray)):
            encrypted_answer = bytes(encrypted_answer).decode("utf-8", errors="strict")
        answer = decrypt_data(encrypted_answer) if encrypted_answer else ""
        legacy_answer = "" if row[6] == "[encrypted]" else str(row[6] or "")
        assessment = (
            decrypt_json_field(row[17], row[18], {})
            if encrypted_assessment_layout
            else _json_load(row[17], {}) if len(row) > 17 else {}
        )
        assessment_score = row[16] if len(row) > 16 else None
        turns.append({
            "response_id": row[0],
            "question": row[1],
            "question_type": row[2],
            "is_followup": row[3],
            "topic_label": row[4],
            "response": answer or legacy_answer,
            "score": float(assessment_score) if assessment_score is not None else None,
            "feedback": assessment.get("feedback") or row[8],
            "time_taken": row[9],
            "nonverbal_metrics": _json_load(row[10], {}),
            "coaching_hint": row[11],
            "evaluation_json": assessment or _json_load(row[12], {}),
            "answer_quality_flags": _json_load(row[13], []),
            "evidence_quotes": _json_load(row[14], []),
            "retry_state": _json_load(row[15], {}),
            "assessment": assessment or None,
            "evaluator_version": row[18 + assessment_offset] if len(row) > 18 + assessment_offset else None,
            "insufficient_evidence": bool(assessment.get("insufficient_evidence")) if assessment else True,
            "question_id": row[19 + assessment_offset] if len(row) > 19 + assessment_offset else None,
            "question_order": row[20 + assessment_offset] if len(row) > 20 + assessment_offset else None,
            "expected_points": _json_load(row[21 + assessment_offset], []) if len(row) > 21 + assessment_offset else [],
            "rubric_json": _json_load(row[22 + assessment_offset], {}) if len(row) > 22 + assessment_offset else {},
            "question_spec_id": row[23 + assessment_offset] if len(row) > 23 + assessment_offset else None,
            "taxonomy_keys": _json_load(row[24 + assessment_offset], []) if len(row) > 24 + assessment_offset else [],
            "section_id": row[25 + assessment_offset] if len(row) > 25 + assessment_offset else None,
            "parent_question_id": row[26 + assessment_offset] if len(row) > 26 + assessment_offset else None,
            "provenance": _json_load(row[27 + assessment_offset], {}) if len(row) > 27 + assessment_offset else {},
            "created_at": row[28 + assessment_offset].isoformat() if len(row) > 28 + assessment_offset and row[28 + assessment_offset] else None,
        })
    return turns


def _load_report_payload(cursor, interview_id: str) -> List[Dict[str, Any]]:
    cursor.execute(
        """
        WITH latest_responses AS (
            SELECT candidate_response.*,
                   ROW_NUMBER() OVER (
                       PARTITION BY candidate_response.question_id
                       ORDER BY candidate_response.created_at DESC
                   ) AS response_rank
            FROM InterviewResponses candidate_response
        ), latest_assessments AS (
            SELECT response_id, overall_score, assessment_json_encrypted,
                   assessment_json, evaluator_version,
                   ROW_NUMBER() OVER (
                       PARTITION BY response_id
                       ORDER BY created_at DESC
                   ) AS assessment_rank
            FROM ResponseAssessments
        )
        SELECT ir.response_id,
               iq.question_text, iq.question_type, iq.is_followup,
               iq.topic_label, ir.answer_text_encrypted, ir.user_response, ir.score, ir.ai_feedback,
               ir.response_time_seconds, ir.nonverbal_metrics, ir.coaching_hint,
               ir.evaluation_json, ir.answer_quality_flags, ir.evidence_quotes,
               ir.retry_state, assessment.overall_score,
               assessment.assessment_json_encrypted, assessment.assessment_json,
               assessment.evaluator_version,
               iq.question_id, iq.question_order, iq.expected_points, iq.rubric_json,
               iq.question_spec_id, iq.taxonomy_keys, iq.blueprint_section_id,
               iq.parent_question_id, iq.provenance, ir.created_at
        FROM InterviewQuestions iq
        LEFT JOIN latest_responses ir
          ON ir.question_id = iq.question_id AND ir.response_rank = 1
        LEFT JOIN latest_assessments assessment
          ON assessment.response_id = ir.response_id AND assessment.assessment_rank = 1
        WHERE iq.interview_id = ?
        ORDER BY iq.question_order, ir.created_at NULLS LAST
        """,
        (interview_id,)
    )
    return _rows_to_turns(cursor.fetchall())


def _report_payload_ready(value: Any) -> bool:
    return isinstance(_json_load(value, None), dict)


def _interview_report_ready(status_value: Any, report_json: Any) -> bool:
    return str(status_value or "").lower() in REPORT_READY_STATUSES and _report_payload_ready(report_json)


def _detailed_response_status(turn: Dict[str, Any]) -> str:
    if not str(turn.get("response") or "").strip():
        return "Not Answered"
    if bool(turn.get("insufficient_evidence")):
        return "Incomplete"
    if not isinstance(turn.get("assessment"), dict) or turn.get("score") is None:
        return "Unable to Evaluate"
    return "Completed"


def _stored_report_question_status(question: Dict[str, Any]) -> str:
    """Normalize legacy canonical question rows before returning the report."""
    response = str(
        question.get("response")
        or question.get("transcript")
        or question.get("user_answer")
        or ""
    ).strip()
    explicit = str(question.get("status") or "").strip()
    if explicit == "Not Answered" and response:
        if question.get("insufficient_evidence") or question.get("evidence_status") == "insufficient_evidence":
            return "Incomplete"
        return "Completed" if question.get("score") is not None or question.get("overall_score") is not None else "Unable to Evaluate"
    if explicit in {"Completed", "Incomplete", "Unable to Evaluate", "Not Answered"}:
        return explicit
    if not response:
        return "Not Answered"
    if question.get("insufficient_evidence") or question.get("evidence_status") == "insufficient_evidence":
        return "Incomplete"
    return "Completed" if question.get("score") is not None or question.get("overall_score") is not None else "Unable to Evaluate"


def _analysis_report_state(
    *,
    interview_status: Any,
    attempt_status: Any,
    report_ready: bool,
    stored_report: Any,
    job_status: Any,
    manual_retry_count: int,
) -> str:
    normalized_status = str(interview_status or "").lower()
    normalized_attempt = str(attempt_status or "").lower()
    normalized_job = str(job_status or "").lower()
    if normalized_attempt == "incomplete" or normalized_status == "cancelled":
        return "unavailable"
    if normalized_attempt == "recovering" or normalized_status == "recovering":
        return "recovering"
    if report_ready and isinstance(stored_report, dict):
        return str(
            stored_report.get("report_state")
            or ("partial" if normalized_status == "partial" else "ready")
        )
    if normalized_job == "failed":
        return "failed"
    if manual_retry_count > 0 and normalized_job in {"queued", "running"}:
        return "retrying"
    return "generating"


async def _has_current_canonical_analysis(interview_id: str, user_id: str) -> bool:
    row = await async_execute(
        """
        SELECT EXISTS (
            SELECT 1
            FROM SessionPerformanceAnalyses analysis
            WHERE analysis.interview_id = ?
              AND analysis.user_id = ?
              AND analysis.schema_version = 'session-performance-v4'
              AND analysis.producer_version = ?
              AND analysis.status = 'ready'
              AND analysis.is_current = TRUE
              AND analysis.analysis_json_encrypted IS NOT NULL
              AND analysis.evidence_index_encrypted IS NOT NULL
              AND EXISTS (
                  SELECT 1
                  FROM ReportArtifacts artifact
                  WHERE artifact.analysis_id = analysis.analysis_id
                    AND artifact.interview_id = analysis.interview_id
                    AND artifact.user_id = analysis.user_id
                    AND artifact.audience = 'candidate'
                    AND artifact.status IN ('completed', 'partial')
                    AND artifact.payload_encrypted IS NOT NULL
              )
        )
        """,
        (interview_id, user_id, ANALYSIS_STAGE_VERSION),
        fetchone=True,
    )
    return bool(row and row[0])


async def _finalize_interview_for_analysis(
    *,
    interview_id: str,
    user_id: str,
    reason: str,
    transcript: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    transcript_json = json.dumps(transcript) if transcript is not None else None
    canonical_report_ready = await _has_current_canonical_analysis(interview_id, user_id)

    def _mark_finalized() -> Dict[str, Any]:
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                SELECT status, report_json, analysis_job_id, completed_at,
                       report_json_encrypted, interview_type, settings
                FROM Interviews
                WHERE interview_id = ? AND user_id = ?
                """,
                (interview_id, user_id),
            )
            row = cursor.fetchone()
            if not row:
                conn.commit()
                return {"found": False}

            current_status = str(row[0] or "").lower()
            report_payload = _decrypt_json_blob(row[4], None) or _json_load(row[1], None)
            report_ready = (
                current_status in REPORT_READY_STATUSES
                and isinstance(report_payload, dict)
                and canonical_report_ready
            )
            technical_interview = is_technical_interview_type(str(row[5] or ""))
            if current_status == "cancelled":
                conn.commit()
                return {
                    "found": True,
                    "status": "cancelled",
                    "analysis_job_id": row[2],
                    "completed_at": row[3],
                    "report_ready": False,
                    "queue_analysis": False,
                    "cancelled": True,
                }
            if report_ready:
                conn.commit()
                return {
                    "found": True,
                    "status": current_status,
                    "analysis_job_id": row[2],
                    "completed_at": row[3],
                    "report_ready": True,
                    "queue_analysis": False,
                }

            if technical_interview:
                cursor.execute(
                    """
                    SELECT COUNT(*)
                    FROM TechnicalExecutionJobs
                    WHERE interview_id = ? AND user_id = ?
                      AND status IN ('queued', 'leased', 'running')
                    """,
                    (interview_id, user_id),
                )
                pending_execution_count = int((cursor.fetchone() or [0])[0] or 0)
                if pending_execution_count:
                    settings_payload = _json_load(row[6], {})
                    if not isinstance(settings_payload, dict):
                        settings_payload = {}
                    settings_payload["technical_finalize_requested"] = True
                    settings_payload["technical_finalize_reason"] = reason[:80]
                    settings_payload["technical_finalize_requested_at"] = datetime.now(timezone.utc).isoformat()
                    if transcript_json is not None:
                        settings_payload["pending_transcript_encrypted"] = encrypt_data(transcript_json)
                    cursor.execute(
                        "UPDATE Interviews SET settings = ? WHERE interview_id = ? AND user_id = ?",
                        (json.dumps(settings_payload), interview_id, user_id),
                    )
                    conn.commit()
                    return {
                        "found": True,
                        "status": "execution_pending",
                        "analysis_job_id": row[2],
                        "completed_at": row[3],
                        "report_ready": False,
                        "queue_analysis": False,
                        "pending_execution": True,
                        "pending_execution_count": pending_execution_count,
                    }

            if current_status not in ANALYSIS_ACTIVE_STATUSES:
                transcript_marker = None
                transcript_encrypted = None
                if transcript_json is not None:
                    transcript_marker = json.dumps({
                        "encrypted": True,
                        "turn_count": len(transcript or []),
                        "captured": bool(transcript),
                    })
                    transcript_encrypted = encrypt_data(transcript_json).encode("utf-8")
                cursor.execute(
                    """
                    UPDATE Interviews
                    SET status = 'analysis_pending',
                        attempt_status = 'completed', analysis_status = 'queued',
                        completion_kind = CASE WHEN deadline_at IS NOT NULL AND CURRENT_TIMESTAMP >= deadline_at THEN 'deadline' ELSE 'natural' END,
                        recovery_deadline_at = NULL,
                        lifecycle_revision = lifecycle_revision + 1,
                        completed_at = COALESCE(completed_at, CURRENT_TIMESTAMP),
                        duration_seconds = CASE
                            WHEN started_at IS NULL THEN duration_seconds
                            ELSE MAX(0, CAST(
                                (julianday(COALESCE(completed_at, CURRENT_TIMESTAMP)) - julianday(started_at)) * 86400
                                AS INTEGER
                            ))
                        END,
                        full_transcript = CASE
                            WHEN ? IS NULL THEN full_transcript
                            ELSE ?
                        END,
                        transcript_encrypted = CASE
                            WHEN ? IS NULL THEN transcript_encrypted
                            ELSE ?
                        END,
                        feedback_summary = 'Interview complete. Async analysis is queued.'
                    WHERE interview_id = ?
                      AND user_id = ?
                      AND status <> 'cancelled'
                    RETURNING status, analysis_job_id, completed_at
                    """,
                    (
                        transcript_marker,
                        transcript_marker,
                        transcript_encrypted,
                        transcript_encrypted,
                        interview_id,
                        user_id,
                    ),
                )
                updated = cursor.fetchone()
                if updated:
                    if technical_interview:
                        cursor.execute(
                            """
                            UPDATE TechnicalInterviewRounds AS round
                            SET status = CASE
                                    WHEN interview.completion_kind = 'deadline' THEN 'expired'
                                    ELSE 'completed'
                                END,
                                completed_at = COALESCE(
                                    round.completed_at,
                                    interview.completed_at,
                                    CURRENT_TIMESTAMP
                                )
                            FROM Interviews interview
                            WHERE round.interview_id = interview.interview_id
                              AND round.user_id = interview.user_id
                              AND interview.interview_id = ?
                              AND interview.user_id = ?
                              AND round.status NOT IN (
                                  'submitted', 'completed', 'expired', 'cancelled'
                              )
                            """,
                            (interview_id, user_id),
                        )
                    conn.commit()
                    return {
                        "found": True,
                        "status": updated[0],
                        "analysis_job_id": updated[1],
                        "completed_at": updated[2],
                        "report_ready": False,
                        "queue_analysis": True,
                    }

            conn.commit()
            return {
                "found": True,
                "status": current_status,
                "analysis_job_id": row[2],
                "completed_at": row[3],
                "report_ready": False,
                "queue_analysis": True,
            }
        except Exception:
            conn.rollback()
            raise
        finally:
            cursor.close()
            return_db_connection(conn)

    outcome = await asyncio.to_thread(_mark_finalized)
    if not outcome.get("found"):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Interview not found")
    if outcome.get("cancelled") or outcome.get("report_ready"):
        return outcome

    try:
        job_id = await enqueue_analysis(interview_id, user_id, reason)
    except Exception:
        logger.exception(
            "Could not queue analysis after finalizing interview %s",
            stable_hash(interview_id, "interview"),
        )
        await async_execute(
            """
            UPDATE Interviews
            SET analysis_status = 'failed',
                feedback_summary = 'Interview complete, but analysis could not be queued. It will be retried automatically.'
            WHERE interview_id = ? AND user_id = ?
              AND attempt_status = 'completed'
            """,
            (interview_id, user_id),
        )
        outcome["analysis_queue_failed"] = True
        return outcome
    if job_id:
        await async_execute(
            """
            UPDATE Interviews
            SET analysis_job_id = ?
            WHERE interview_id = ?
              AND user_id = ?
              AND status IN ('analysis_pending', 'analysis_running')
            """,
            (job_id, interview_id, user_id),
        )
        outcome["analysis_job_id"] = job_id
    else:
        await async_execute(
            """
            UPDATE Interviews
            SET analysis_status = 'failed',
                feedback_summary = 'Interview complete, but analysis could not be queued. It will be retried automatically.'
            WHERE interview_id = ? AND user_id = ?
              AND attempt_status = 'completed'
            """,
            (interview_id, user_id),
        )
        outcome["analysis_queue_failed"] = True
    return outcome


def _should_request_retry(evaluation: Dict, question_type: str, interview_mode: Optional[str]) -> bool:
    if interview_mode != "practice" or question_type == "retry":
        return False
    flags = set(evaluation.get("answer_quality_flags") or [])
    score = float(evaluation.get("score") or 0)
    return bool(flags & {"off_topic", "too_short", "vague", "no_evidence"}) and score < 55

def _build_retry_prompt(original_question: str, evaluation: Dict) -> str:
    flags = set(evaluation.get("answer_quality_flags") or [])
    if "off_topic" in flags:
        instruction = "Focus directly on the question first, then add one relevant example."
    elif "too_short" in flags:
        instruction = "Give a fuller answer: direct point, concrete example, result, and one trade-off."
    elif "no_evidence" in flags:
        instruction = "Add proof from a project, job, GitHub repo, or measurable outcome."
    else:
        instruction = "Make it more specific with decisions, tools, constraints, and results."
    return f"Let's retry that. {instruction} Same question: {original_question}"

def _build_personalized_opening(persona: Dict, profile: Dict, signals: Dict, interview_mode: str) -> str:
    name = re.sub(r"\s+", " ", str(profile.get("name") or "")).strip() or "there"
    role = profile.get("target_role") or persona.get("job_title") or "this role"
    interviewer = persona.get("name", "your interviewer")

    projects = profile.get("projects") if isinstance(profile.get("projects"), list) else []
    for project in projects:
        project_name = (
            project.get("name") or project.get("title")
            if isinstance(project, dict)
            else project
        )
        project_name = re.sub(r"\s+", " ", str(project_name or "")).strip()[:100]
        if project_name:
            return (
                f"Hi {name}, I am {interviewer}. What was the hardest decision you personally owned "
                f"in {project_name} that best demonstrates your fit for the {role} role?"
            )

    experience = profile.get("experience") or profile.get("experiences") or []
    if not isinstance(experience, list):
        experience = [experience]
    for item in experience:
        if isinstance(item, dict):
            title = item.get("title") or item.get("position") or item.get("role")
            company = item.get("company") or item.get("organization")
            experience_anchor = " at ".join(
                value for value in (str(title or "").strip(), str(company or "").strip()) if value
            )
        else:
            experience_anchor = str(item or "").strip()
        experience_anchor = re.sub(r"\s+", " ", experience_anchor).strip()[:120]
        if experience_anchor:
            return (
                f"Hi {name}, I am {interviewer}. Which decision you personally owned during your "
                f"{experience_anchor} experience best demonstrates your fit for the {role} role?"
            )

    return (
        f"Hi {name}, I am {interviewer}. "
        f"What should I know about your background and interest in the {role} role?"
    )


def _build_opening_script(persona: Dict, profile: Dict) -> Dict[str, str]:
    """Return the non-scored greeting and the short context prompt separately."""
    name = re.sub(
        r"\s+",
        " ",
        str(profile.get("name") or profile.get("full_name") or ""),
    ).strip() or "there"
    role = profile.get("target_role") or persona.get("job_title") or "this role"
    interviewer = persona.get("name", "your interviewer")
    return {
        "greeting": (
            f"Hi {name}, I'm {interviewer}, your interviewer for the {role} role. "
            "We'll start with a brief introduction, then move through evidence-based "
            "questions from your background and the role. I'll explain each step, and "
            "your introduction is context only; scoring starts with the first round question."
        ),
        "intro_question": (
            f"Could you give me a brief introduction and tell me what interests you about the {role} role?"
        ),
    }


def _candidate_job_context(
    *,
    role: Any,
    company: Any,
    job_description: Any,
    profile_type: Any,
    profile_label: Any,
    blueprint: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Return only non-sensitive labels that are safe in plaintext settings.

    The full description and its derived requirements stay in the encrypted
    attempt snapshot.  Runtime code that needs them must decrypt that snapshot
    in memory instead of copying excerpts into ``Interviews.settings``.
    """
    clean_role = re.sub(r"\s+", " ", str(role or "General Interview")).strip()[:180]
    clean_company = re.sub(r"\s+", " ", str(company or "")).strip()[:120]
    return {
        "role": clean_role,
        "company": clean_company or None,
        "job_title": f"{clean_role} at {clean_company}" if clean_company else clean_role,
        "profile_type": str(profile_type or "mid_tier"),
        "profile_label": str(profile_label or profile_type or "Mid Tier"),
    }


def _load_resume_version(
    cursor: Any,
    *,
    user_id: str,
    resume_id: Optional[str],
    fallback_resume: Dict[str, Any],
) -> tuple[Optional[str], Dict[str, Any]]:
    if not resume_id:
        return None, fallback_resume
    cursor.execute(
        """
        SELECT resume_id, resume_payload_encrypted, resume_json, confirmation_status,
               facts_encrypted
        FROM ResumeVersions
        WHERE resume_id = ? AND user_id = ?
        """,
        (resume_id, user_id),
    )
    row = cursor.fetchone()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resume version not found")
    if str(row[3] or "").lower() != "confirmed":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Confirm the selected resume before preparing an official attempt")
    encrypted_payload = row[1]
    if isinstance(encrypted_payload, memoryview):
        encrypted_payload = encrypted_payload.tobytes()
    if isinstance(encrypted_payload, (bytes, bytearray)):
        encrypted_payload = bytes(encrypted_payload).decode("utf-8", errors="strict")
    resume_payload = {}
    if encrypted_payload:
        resume_payload = _json_load(decrypt_data(str(encrypted_payload)), {})
    if not resume_payload:
        resume_payload = _json_load(row[2], {})
    facts_payload = _decrypt_json_blob(row[4], {"facts": []})
    if isinstance(facts_payload, dict) and facts_payload.get("facts"):
        # Import lazily to avoid coupling module initialization while keeping
        # one materialization policy for resume review and official attempts.
        from pre_interview import _materialize_resume
        resume_payload = _materialize_resume(resume_payload, facts_payload)
    return str(row[0]), resume_payload if isinstance(resume_payload, dict) else {}


def _blueprint_preview(blueprint: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [
        {
            "section_id": section.get("section_id"),
            "topic": section.get("label"),
            "kind": section.get("kind"),
            "importance": section.get("importance"),
            "difficulty": section.get("estimated_difficulty"),
            "time_budget_seconds": section.get("time_budget_seconds"),
            "taxonomy_keys": section.get("taxonomy_keys") or [],
            "selection_reason": section.get("selection_reason"),
            "maximum_followups": max(0, min(2, int(section.get("max_turns") or 1) - 1)),
        }
        for section in blueprint.get("battlegrounds", [])
        if isinstance(section, dict)
    ]


async def _legacy_create_interview_blueprint_unused(
    request: CreateInterviewBlueprintRequest,
    current_user: Dict = Depends(local_user),
):
    """Compile and freeze a previewable blueprint for the local user."""

    def _compile_and_store() -> Dict[str, Any]:
        connection = get_db_connection()
        cursor = connection.cursor()
        try:
            cursor.execute(
                """
                SELECT profile_json, resume_json, job_id, interview_profile_type
                FROM UserInfo
                WHERE user_id = ?
                """,
                (current_user["user_id"],),
            )
            user_row = cursor.fetchone()
            if not user_row:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Complete your profile first")

            profile_json = _json_load(user_row[0], {})
            legacy_resume = _json_load(user_row[1], {})
            resume_id, resume_json = _load_resume_version(
                cursor,
                user_id=current_user["user_id"],
                resume_id=request.resume_id,
                fallback_resume=legacy_resume,
            )
            profile = _best_available_profile(profile_json, resume_json)
            profile_type = normalize_profile_type(request.profile_type or user_row[3])
            if is_technical_interview_type(request.interview_type):
                profile_type = normalize_technical_profile(profile_type)

            job_profile_id = request.job_profile_id
            job_title = ""
            job_description = ""
            if job_profile_id:
                cursor.execute(
                    """
                    SELECT role, company, tech_stack, normalized_requirements,
                           normalized_requirements_encrypted
                    FROM JobProfiles
                    WHERE profile_id = ? AND user_id = ?
                    """,
                    (job_profile_id, current_user["user_id"]),
                )
                job_row = cursor.fetchone()
                if not job_row:
                    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job profile not found")
                role, company, tech_stack, normalized_requirements, normalized_requirements_encrypted = job_row
                requirements_payload = _decrypt_json_blob(
                    normalized_requirements_encrypted,
                    _json_load(normalized_requirements, {}),
                )
                job_title = f"{role} at {company}" if company else str(role)
                job_description = json.dumps({
                    "tech_stack": _json_load(tech_stack, []),
                    "requirements": requirements_payload,
                })
            elif request.custom_job_title or request.custom_job_description:
                role = (request.custom_job_title or "Custom Role").strip()
                company = (request.company_name or "").strip()
                job_title = f"{role} at {company}" if company else role
                job_description = (request.custom_job_description or "").strip()
            else:
                job_id = request.job_id or user_row[2]
                if job_id:
                    cursor.execute("SELECT title, description FROM Jobs WHERE job_id = ?", (job_id,))
                    job_row = cursor.fetchone()
                    if not job_row:
                        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
                    job_title, job_description = job_row
                else:
                    job_title = profile.get("target_role") or profile.get("targetRole") or "General Interview"
                    job_description = profile.get("summary") or profile.get("professionalSummary") or ""

            weaknesses = _load_previous_weaknesses(cursor, current_user["user_id"])
            blueprint = validate_blueprint(compile_interview_blueprint(
                resume_data=profile,
                job_title=str(job_title or "General Interview"),
                job_description=str(job_description or ""),
                interview_type=request.interview_type,
                duration_minutes=request.duration_minutes,
                profile_type=profile_type,
                focus=request.focus,
                previous_weaknesses=weaknesses,
            ))
            blueprint_id = str(uuid.uuid4())
            expires_at = datetime.now(timezone.utc) + timedelta(hours=24)
            round_types = (
                ["coding"]
                if is_technical_interview_type(request.interview_type) and settings.TECHNICAL_CODING_ONLY
                else request.technical_round_types or (
                    ["coding", "debugging"] if is_technical_interview_type(request.interview_type) else []
                )
            )
            settings_json = {
                "profile_type": profile_type,
                "job_title": job_title,
                "experience_level": request.experience_level,
                "difficulty_level": request.difficulty_level,
                "duration_minutes": request.duration_minutes,
                "focus": request.focus,
                "programming_language": request.programming_language,
                "technical_topics": request.technical_topics,
                "technical_rounds": round_types,
                "question_count": request.question_count,
                "input_mode": request.input_mode,
                "camera_mode": request.camera_mode,
            }
            cursor.execute(
                """
                INSERT INTO InterviewBlueprints (
                    blueprint_id, user_id, status, interview_mode, interview_type,
                    resume_id, job_profile_id, blueprint_json, settings_json,
                    blueprint_hash, expires_at, created_at
                )
                VALUES (?, ?, 'ready', ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (
                    blueprint_id,
                    current_user["user_id"],
                    request.interview_mode,
                    request.interview_type,
                    resume_id,
                    job_profile_id,
                    json.dumps(blueprint),
                    json.dumps(settings_json),
                    blueprint["blueprint_hash"],
                    expires_at,
                ),
            )
            connection.commit()
            return {
                "blueprint_id": blueprint_id,
                "status": "ready",
                "schema_version": blueprint.get("schema_version"),
                "blueprint_hash": blueprint.get("blueprint_hash"),
                "interview_mode": request.interview_mode,
                "interview_type": request.interview_type,
                "settings": settings_json,
                "preview": _blueprint_preview(blueprint),
                "total_time_budget": blueprint.get("total_time_budget"),
                "expires_at": expires_at.isoformat(),
            }
        except Exception:
            connection.rollback()
            raise
        finally:
            cursor.close()
            return_db_connection(connection)

    return await asyncio.to_thread(_compile_and_store)


async def _legacy_get_interview_blueprint_unused(
    blueprint_id: str,
    current_user: Dict = Depends(local_user),
):
    row = await async_execute(
        """
        SELECT status, interview_mode, interview_type, blueprint_json, settings_json,
               blueprint_hash, expires_at, consumed_by_interview_id
        FROM InterviewBlueprints
        WHERE blueprint_id = ? AND user_id = ?
        """,
        (blueprint_id, current_user["user_id"]),
        fetchone=True,
    )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Interview blueprint not found")
    blueprint = validate_blueprint(_json_load(row[3], {}))
    current_status = str(row[0] or "").lower()
    if current_status == "ready" and row[6] and _coerce_blueprint_datetime(row[6]) <= datetime.now(timezone.utc):
        current_status = "expired"
    return {
        "blueprint_id": blueprint_id,
        "status": current_status,
        "interview_mode": row[1],
        "interview_type": row[2],
        "settings": _json_load(row[4], {}),
        "blueprint_hash": row[5],
        "preview": _blueprint_preview(blueprint),
        "total_time_budget": blueprint.get("total_time_budget"),
        "expires_at": row[6].isoformat() if row[6] else None,
        "consumed_by_interview_id": row[7],
    }


def _coerce_blueprint_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _existing_start_response(cursor: Any, user_id: str, key: Optional[str]) -> Optional[InterviewResponse]:
    if not key:
        return None
    cursor.execute(
        """
        SELECT interview_id, session_id, interview_mode, persona_data, settings
        FROM Interviews
        WHERE user_id = ? AND start_idempotency_key = ?
        """,
        (user_id, key),
    )
    row = cursor.fetchone()
    if not row:
        return None
    return InterviewResponse(
        interview_id=row[0],
        session_id=row[1],
        mode=row[2],
        message="Interview already started for this request.",
        persona=_json_load(row[3], {}),
        settings=_json_load(row[4], {}),
    )


def _answer_hash(question_id: str, answer: str) -> str:
    return hashlib.sha256(f"{question_id}\n{answer.strip()}".encode("utf-8")).hexdigest()


def _assessment_hash(response_id: str, question_spec: Dict[str, Any], answer_hash: str) -> str:
    payload = json.dumps(
        {
            "response_id": response_id,
            "answer_hash": answer_hash,
            "evaluation_version": EVALUATION_VERSION,
            "taxonomy_keys": question_spec.get("taxonomy_keys") or [],
            "expected_points": question_spec.get("expected_points") or [],
            "rubric": question_spec.get("rubric") or {},
        },
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _persist_raw_answer(
    *,
    response_id: str,
    interview_id: str,
    question_id: str,
    answer: str,
    response_seconds: float,
    idempotency_key: str,
    input_mode: str,
    timing: Dict[str, Any],
    nonverbal_metrics: Dict[str, Any],
) -> Dict[str, Any]:
    """Insert raw evidence once before any semantic or follow-up work."""
    connection = get_db_connection()
    cursor = connection.cursor()
    raw_hash = _answer_hash(question_id, answer)
    try:
        cursor.execute(
            """
            INSERT INTO InterviewResponses (
                response_id, interview_id, question_id, user_response,
                response_time_seconds, idempotency_key, evidence_hash,
                answer_text_encrypted, transcript_encrypted, raw_answer_hash,
                input_mode, timing_json, nonverbal_metrics, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT (interview_id, idempotency_key) DO NOTHING
            RETURNING response_id
            """,
            (
                response_id,
                interview_id,
                question_id,
                "[encrypted]",
                max(0, int(response_seconds or 0)),
                idempotency_key,
                raw_hash,
                encrypt_data(answer).encode("utf-8"),
                encrypt_data(answer).encode("utf-8"),
                raw_hash,
                input_mode,
                json.dumps(timing or {}),
                json.dumps(nonverbal_metrics or {}),
            ),
        )
        inserted = cursor.fetchone()
        if inserted:
            connection.commit()
            return {
                "response_id": inserted[0],
                "inserted": True,
                "raw_answer_hash": raw_hash,
                "assessment": None,
            }

        cursor.execute(
            """
            SELECT ir.response_id, ir.question_id, ir.raw_answer_hash,
                   (
                       SELECT assessment_id
                       FROM ResponseAssessments
                       WHERE response_id = ir.response_id
                       ORDER BY created_at DESC
                       LIMIT 1
                   ) AS assessment_id,
                   (
                       SELECT assessment_json_encrypted
                       FROM ResponseAssessments
                       WHERE response_id = ir.response_id
                       ORDER BY created_at DESC
                       LIMIT 1
                   ) AS assessment_json_encrypted,
                   (
                       SELECT assessment_json
                       FROM ResponseAssessments
                       WHERE response_id = ir.response_id
                       ORDER BY created_at DESC
                       LIMIT 1
                   ) AS assessment_json
            FROM InterviewResponses ir
            WHERE ir.interview_id = ? AND ir.idempotency_key = ?
            """,
            (interview_id, idempotency_key),
        )
        existing = cursor.fetchone()
        connection.commit()
        if not existing:
            raise RuntimeError("Idempotent response disappeared after conflict")
        if str(existing[1]) != str(question_id) or str(existing[2] or "") != raw_hash:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Idempotency key was already used for different answer evidence",
            )
        return {
            "response_id": existing[0],
            "inserted": False,
            "raw_answer_hash": raw_hash,
            "assessment_id": existing[3],
            "assessment": decrypt_json_field(existing[4], existing[5], None),
        }
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()
        return_db_connection(connection)


def _expected_point_contract(question_spec: Dict[str, Any], question_id: str) -> List[Dict[str, str]]:
    result: List[Dict[str, str]] = []
    for index, point in enumerate(question_spec.get("expected_points") or [], start=1):
        if isinstance(point, dict):
            point_id = str(point.get("point_id") or point.get("id") or "").strip()
            label = str(point.get("label") or point.get("text") or point_id).strip()
        else:
            point_id = ""
            label = str(point or "").strip()
        if label:
            result.append({
                "point_id": point_id or f"{question_spec.get('section_id') or question_id}:point:{index}",
                "label": label,
            })
    return result


def _sanitize_live_evaluation(
    evaluation: Dict[str, Any],
    *,
    question_spec: Dict[str, Any],
    question_id: str,
) -> Dict[str, Any]:
    """Discard model references outside the frozen server-owned question spec."""
    cleaned = json.loads(json.dumps(evaluation, default=str))
    contract = _expected_point_contract(question_spec, question_id)
    allowed: Dict[str, str] = {}
    for point in contract:
        allowed[point["point_id"].strip().lower()] = point["point_id"]
        allowed[point["label"].strip().lower()] = point["point_id"]

    evidence = cleaned.setdefault("evidence", {})
    for key in ("covered_points", "missed_points"):
        normalized: List[str] = []
        for value in evidence.get(key) or []:
            mapped = allowed.get(str(value or "").strip().lower())
            if mapped and mapped not in normalized:
                normalized.append(mapped)
        evidence[key] = normalized

    semantic_state = (cleaned.get("semantic_status") or {}).get("state")
    covered = len(evidence.get("covered_points") or [])
    missed = len(evidence.get("missed_points") or [])
    incorrect = len(evidence.get("incorrect_claims") or [])
    denominator = covered + missed + (incorrect * 1.5)
    technical_accuracy: Optional[float] = None
    if semantic_state == "completed" and denominator > 0:
        technical_accuracy = round(max(0.0, min(100.0, covered * 100.0 / denominator)), 1)
    cleaned.setdefault("scores", {})["technical_accuracy"] = technical_accuracy

    kind = str(question_spec.get("kind") or "technical").lower()
    core_missing = kind in {"technical", "project", "technical_concept", "system_design"} and technical_accuracy is None
    if core_missing:
        cleaned["overall_score"] = None
        cleaned["insufficient_evidence"] = True
    else:
        cleaned["insufficient_evidence"] = bool(
            int((cleaned.get("signals") or {}).get("word_count") or 0) < 8
        )
    cleaned["expected_point_contract"] = contract
    return cleaned


def _question_insert_payload(
    *,
    question_id: str,
    question_text: str,
    question_type: str,
    battleground: Dict[str, Any],
    parent_question_id: Optional[str],
    profile_type: Optional[str],
    job_title: Optional[str],
    generation_metadata: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "question_id": question_id,
        "question_text": question_text,
        "question_type": question_type,
        "topic_label": battleground.get("label"),
        "profile_type": profile_type,
        "job_title": job_title,
        "parent_question_id": parent_question_id,
        "taxonomy_keys": battleground.get("taxonomy_keys") or [],
        "expected_points": _expected_point_contract(battleground, question_id),
        "rubric": battleground.get("rubric") or {},
        "selection_reason": battleground.get("selection_reason"),
        "section_id": battleground.get("section_id"),
        "provenance": battleground.get("provenance") or {"selection": "deterministic"},
        "difficulty": battleground.get("estimated_difficulty") or "medium",
        "generation_metadata": generation_metadata,
    }


def _commit_live_assessment(
    *,
    response_id: str,
    interview_id: str,
    assessment: Dict[str, Any],
    evidence_hash: str,
    knowledge_map: Dict[str, Any],
    next_question: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Atomically commit the append-only assessment, map state and next question."""
    connection = get_db_connection()
    cursor = connection.cursor()
    assessment_id = str(uuid.uuid4())
    try:
        cursor.execute(
            """
            INSERT INTO ResponseAssessments (
                assessment_id, response_id, interview_id, evaluator_version,
                evidence_hash, overall_score, assessment_json,
                assessment_json_encrypted, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT (response_id, evaluator_version, evidence_hash) DO NOTHING
            RETURNING assessment_id
            """,
            (
                assessment_id,
                response_id,
                interview_id,
                EVALUATION_VERSION,
                evidence_hash,
                assessment.get("overall_score"),
                json.dumps({"encrypted": True}),
                encrypt_data(json.dumps(assessment, default=str)).encode("utf-8"),
            ),
        )
        inserted = cursor.fetchone()
        if not inserted:
            cursor.execute(
                """
                SELECT assessment_id, assessment_json_encrypted, assessment_json
                FROM ResponseAssessments
                WHERE response_id = ? AND evaluator_version = ? AND evidence_hash = ?
                """,
                (response_id, EVALUATION_VERSION, evidence_hash),
            )
            existing = cursor.fetchone()
            connection.commit()
            return {
                "assessment_id": existing[0] if existing else None,
                "assessment": decrypt_json_field(existing[1], existing[2], assessment) if existing else assessment,
                "duplicate": True,
            }

        if next_question:
            cursor.execute(
                "SELECT COALESCE(MAX(question_order), -1) + 1 FROM InterviewQuestions WHERE interview_id = ?",
                (interview_id,),
            )
            question_order = int((cursor.fetchone() or [0])[0] or 0)
            cursor.execute(
                """
                INSERT INTO InterviewQuestions (
                    question_id, interview_id, question_text, question_order,
                    question_type, topic_label, profile_type, rubric_version,
                    source, expected_signal, difficulty_level, is_followup,
                    parent_question_id, generation_metadata, taxonomy_keys,
                    expected_points, rubric_json, selection_reason,
                    blueprint_section_id, provenance, question_spec_id,
                    max_followups, time_budget_seconds, expected_point_ids
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'deterministic_policy',
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?)
                ON CONFLICT (question_id) DO NOTHING
                """,
                (
                    next_question["question_id"],
                    interview_id,
                    next_question["question_text"],
                    question_order,
                    next_question["question_type"],
                    next_question.get("topic_label"),
                    next_question.get("profile_type"),
                    EVALUATION_VERSION,
                    json.dumps(next_question.get("expected_points") or []),
                    next_question.get("difficulty") or "medium",
                    next_question["question_type"] in {"followup", "retry"},
                    next_question.get("parent_question_id"),
                    json.dumps(next_question.get("generation_metadata") or {}),
                    json.dumps(next_question.get("taxonomy_keys") or []),
                    json.dumps(next_question.get("expected_points") or []),
                    json.dumps(next_question.get("rubric") or {}),
                    next_question.get("selection_reason"),
                    next_question.get("section_id"),
                    json.dumps(next_question.get("provenance") or {}),
                    next_question["question_id"],
                    int(next_question.get("max_followups") or 2),
                    int(next_question.get("time_budget_seconds") or 0) or None,
                    json.dumps([
                        str(point.get("point_id") or point.get("id"))
                        for point in (next_question.get("expected_points") or [])
                        if isinstance(point, dict) and (point.get("point_id") or point.get("id"))
                    ]),
                ),
            )
        cursor.execute(
            """
            UPDATE Interviews
            SET questions_data = ?, questions_data_encrypted = ?
            WHERE interview_id = ?
            """,
            (
                json.dumps({"encrypted": True}),
                encrypt_data(json.dumps(knowledge_map, default=str)).encode("utf-8"),
                interview_id,
            ),
        )
        connection.commit()
        return {"assessment_id": assessment_id, "assessment": assessment, "duplicate": False}
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()
        return_db_connection(connection)


def _followup_template(action: str, topic: str) -> str:
    templates = {
        "clarify": f"What is the main point about {topic}, and what example supports it?",
        "verify_contradiction": f"Which claim about {topic} is correct, and what evidence supports it?",
        "simplify_prerequisite": f"For {topic}, what is the core idea, and why is it needed?",
        "probe_evidence": f"What did you personally do with {topic}, and what result did it produce?",
        "challenge_tradeoff": f"What alternative did you consider for {topic}, and why did you choose this approach?",
    }
    return templates.get(action, f"What specific example supports your point about {topic}?")

@router.post("/start", response_model=InterviewResponse)
async def start_interview(
    request: StartInterviewRequest,
    current_user: Dict = Depends(local_user)
):
    connection = get_db_connection()
    cursor = connection.cursor()

    try:
        cursor.execute(
            """
            SELECT profile_completed, job_id, profile_json, resume_json,
                   interview_profile_type
            FROM UserInfo
            WHERE user_id = ?
            """,
            (current_user["user_id"],)
        )

        row = cursor.fetchone()

        if not row:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Please complete your profile before starting an interview"
            )

        existing_start = _existing_start_response(
            cursor,
            current_user["user_id"],
            request.start_idempotency_key,
        )
        if existing_start:
            connection.commit()
            return existing_start

        frozen_blueprint: Optional[Dict[str, Any]] = None
        frozen_settings: Dict[str, Any] = {}
        frozen_resume_id: Optional[str] = request.resume_id
        frozen_job_profile_id: Optional[int] = request.job_profile_id
        if request.blueprint_id:
            cursor.execute(
                """
                SELECT blueprint_id, interview_mode, interview_type, resume_id,
                       job_profile_id, blueprint_json, settings_json, status,
                       expires_at, consumed_by_interview_id, round_config,
                       blueprint_json_encrypted,
                       (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP) AS is_unexpired
                FROM InterviewBlueprints
                WHERE blueprint_id = ? AND user_id = ?
                """,
                (request.blueprint_id, current_user["user_id"]),
            )
            blueprint_row = cursor.fetchone()
            if not blueprint_row:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Interview blueprint not found")
            blueprint_status = str(blueprint_row[7] or "").lower()
            if blueprint_row[9]:
                cursor.execute(
                    """
                    SELECT interview_id, session_id, interview_mode, persona_data, settings
                    FROM Interviews
                    WHERE interview_id = ? AND user_id = ?
                    """,
                    (blueprint_row[9], current_user["user_id"]),
                )
                consumed_interview = cursor.fetchone()
                if consumed_interview and request.start_idempotency_key:
                    connection.commit()
                    return InterviewResponse(
                        interview_id=consumed_interview[0],
                        session_id=consumed_interview[1],
                        mode=consumed_interview[2],
                        message="This blueprint was already consumed by the committed interview.",
                        persona=_json_load(consumed_interview[3], {}),
                        settings=_json_load(consumed_interview[4], {}),
                    )
            if blueprint_status != "ready":
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Interview blueprint is not ready")
            if not bool(blueprint_row[12]):
                cursor.execute(
                    "UPDATE InterviewBlueprints SET status = 'expired' WHERE blueprint_id = ? AND status = 'ready'",
                    (request.blueprint_id,),
                )
                raise HTTPException(status_code=status.HTTP_410_GONE, detail="Interview blueprint has expired")
            request.interview_mode = str(blueprint_row[1] or request.interview_mode)
            request.interview_type = str(blueprint_row[2] or request.interview_type)
            frozen_resume_id = blueprint_row[3]
            frozen_job_profile_id = blueprint_row[4]
            request.resume_id = frozen_resume_id
            request.job_profile_id = frozen_job_profile_id
            frozen_blueprint = validate_blueprint(
                _decrypt_json_blob(blueprint_row[11], None)
                or _json_load(blueprint_row[5], {})
            )
            frozen_settings = _json_load(blueprint_row[6], {})
            if not isinstance(frozen_settings, dict):
                frozen_settings = {}
            for field_name in (
                "experience_level",
                "difficulty_level",
                "duration_minutes",
                "programming_language",
                "question_count",
            ):
                if frozen_settings.get(field_name) is not None:
                    setattr(request, field_name, frozen_settings[field_name])
            if frozen_settings.get("focus"):
                request.focus = list(frozen_settings["focus"])
            if frozen_settings.get("technical_topics"):
                request.technical_topics = list(frozen_settings["technical_topics"])
            if frozen_settings.get("technical_rounds"):
                request.technical_round_types = list(frozen_settings["technical_rounds"])
            if frozen_settings.get("profile_type"):
                request.profile_type = str(frozen_settings["profile_type"])
            frozen_round_config = _json_load(blueprint_row[10], {})
            if isinstance(frozen_round_config, dict):
                if frozen_round_config.get("language"):
                    request.programming_language = str(frozen_round_config["language"])
                if frozen_round_config.get("round_types"):
                    request.technical_round_types = list(frozen_round_config["round_types"])
                if frozen_round_config.get("topics"):
                    request.technical_topics = list(frozen_round_config["topics"])
                if frozen_round_config.get("duration_minutes") is not None:
                    request.duration_minutes = int(frozen_round_config["duration_minutes"])
                if frozen_round_config.get("question_count") is not None:
                    request.question_count = int(frozen_round_config["question_count"])

        profile_json = _json_load(row[2], {})
        legacy_resume_json = _json_load(row[3], {})
        selected_resume_id, resume_json = _load_resume_version(
            cursor,
            user_id=current_user["user_id"],
            resume_id=frozen_resume_id,
            fallback_resume=legacy_resume_json,
        )
        profile_json = _best_available_profile(profile_json, resume_json)
        external_profile_signals = {}
        is_technical_mode = is_technical_interview_type(request.interview_type)
        request.input_mode = "voice" if request.input_mode == "voice" else "text"
        profile_type = normalize_profile_type(request.profile_type or row[4])
        if is_technical_mode:
            profile_type = normalize_technical_profile(profile_type)
        profile_config = get_profile_config(profile_type)
        strictness_level = profile_config["strictness_level"]

        if request.blueprint_id:
            if not request.preflight_id:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="A completed browser preflight is required before starting an official attempt",
                )
            expected_flow = "technical" if is_technical_mode else "interview"
            cursor.execute(
                """
                SELECT flow, input_mode, camera_ready, microphone_ready, microphone_level_detected,
                       screen_share_ready, network_ready, backend_ready, provider_ready,
                       sandbox_ready, worker_ready, expires_at, consumed_at,
                       (expires_at > CURRENT_TIMESTAMP) AS is_unexpired
                FROM AttemptPreflightChecks
                WHERE preflight_id = ? AND user_id = ? AND blueprint_id = ?
                """,
                (request.preflight_id, current_user["user_id"], request.blueprint_id),
            )
            preflight = cursor.fetchone()
            if not preflight:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Preflight check not found")
            required_ready = all(bool(value) for value in (preflight[6], preflight[7], preflight[8], preflight[10]))
            if request.input_mode == "voice":
                required_ready = required_ready and bool(preflight[3]) and bool(preflight[4])
            if str(preflight[0]) != expected_flow or str(preflight[1]) != request.input_mode or preflight[12] is not None:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Preflight does not match this attempt or was already consumed")
            if not bool(preflight[13]):
                raise HTTPException(status_code=status.HTTP_410_GONE, detail="Preflight expired. Run the environment check again")
            if not required_ready:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Preflight requirements are not ready")

        selected_job_profile = None
        if frozen_job_profile_id:
            cursor.execute(
                """
                SELECT profile_id, role, company, tech_stack,
                       job_description_encrypted, normalized_requirements,
                       normalized_requirements_encrypted
                FROM JobProfiles
                WHERE profile_id = ? AND user_id = ?
                """,
                (frozen_job_profile_id, current_user["user_id"])
            )
            selected_job_profile = cursor.fetchone()
            if not selected_job_profile:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Job profile not found"
                )
        has_name = bool(str(profile_json.get("name", "")).strip())
        has_skills = bool(profile_json.get("skills"))
        if not selected_job_profile and (not has_name or not has_skills):
            missing = []
            if not has_name:
                missing.append("name")
            if not has_skills:
                missing.append("at least one skill")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Please complete your profile: missing {', '.join(missing)}"
            )

        job_id = request.job_id or row[1]

        role = ""
        company = ""
        if selected_job_profile:
            tech_stack = selected_job_profile[3] or []
            if isinstance(tech_stack, str):
                try:
                    tech_stack = json.loads(tech_stack)
                except Exception:
                    tech_stack = []
            role = selected_job_profile[1]
            company = selected_job_profile[2]
            job_title = f"{role} at {company}" if company else role
            encrypted_jd = selected_job_profile[4]
            if isinstance(encrypted_jd, memoryview):
                encrypted_jd = encrypted_jd.tobytes()
            if isinstance(encrypted_jd, bytes):
                encrypted_jd = encrypted_jd.decode("utf-8")
            job_description = decrypt_data(encrypted_jd) if encrypted_jd else ""
            normalized_requirements = _decrypt_json_blob(
                selected_job_profile[6],
                _json_load(selected_job_profile[5], {}),
            )
            if not job_description and isinstance(normalized_requirements, dict):
                job_description = "\n".join(
                    str(item) for item in normalized_requirements.get("requirements") or []
                )
            if not job_description and tech_stack:
                job_description = "Tech stack: " + ", ".join(tech_stack)
            profile_json = {
                **profile_json,
                "target_role": role,
                "skills": profile_json.get("skills") or tech_stack,
            }
        elif request.custom_job_title or request.custom_job_description or request.company_name:
            role = (request.custom_job_title or "").strip() or "Custom Role"
            company = (request.company_name or "").strip()
            job_title = f"{role} at {company}" if company else role
            job_description = (request.custom_job_description or "").strip()
            profile_json = {
                **profile_json,
                "target_role": role,
                "skills": profile_json.get("skills") or ["Software Engineering"],
            }
        elif job_id:
            cursor.execute(
                "SELECT title, description FROM Jobs WHERE job_id = ?",
                (job_id,)
            )
            job_row = cursor.fetchone()
            if not job_row:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Job not found"
                )
            job_title = job_row[0]
            job_description = job_row[1]
        else:
            job_title = (
                profile_json.get("target_role")
                or profile_json.get("targetRole")
                or resume_json.get("target_role")
                or "General Interview"
            ) or "General Interview"
            job_description = (
                profile_json.get("summary")
                or profile_json.get("professionalSummary")
                or resume_json.get("summary")
                or ""
            ) or ""

        if frozen_blueprint:
            job_title = str(
                frozen_settings.get("job_title")
                or frozen_blueprint.get("job_target")
                or job_title
                or "General Interview"
            )

        if profile_type == "custom" and not (
            str(role or "").strip()
            and str(job_description or "").strip()
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Custom requires the role and full job description",
            )

        persona = generate_persona(strictness_level, job_title)

        # Duration, difficulty, focus, and question count are product policy,
        # never candidate controls. The interviewer adapts naturally in this
        # 45-60 minute window based on the selected company profile and answers.
        if is_technical_mode:
            duration_minutes = TECHNICAL_TOTAL_DURATION_MINUTES
            duration_config = {
                "min_minutes": duration_minutes,
                "target_minutes": duration_minutes,
                "max_minutes": duration_minutes,
            }
        else:
            duration_config = profile_config["duration"]
            duration_minutes = max(45, min(60, int(duration_config["target_minutes"])))
            duration_config = {
                "min_minutes": max(45, min(duration_minutes, int(duration_config.get("min_minutes") or 45))),
                "target_minutes": duration_minutes,
                "max_minutes": min(60, max(duration_minutes, int(duration_config.get("max_minutes") or 60))),
            }
        request.difficulty_level = "adaptive"
        request.focus = ["mixed"]
        request.question_count = TECHNICAL_CODING_QUESTION_COUNT if is_technical_mode and settings.TECHNICAL_CODING_ONLY else None
        request.technical_topics = []
        request.technical_round_types = ["coding"] if is_technical_mode and settings.TECHNICAL_CODING_ONLY else []
        request.camera_mode = "optional"

        planner_profile = dict(profile_json or resume_json or {})
        planner_profile["external_profile_signals"] = external_profile_signals
        interview_id = str(uuid.uuid4())
        session_id = str(uuid.uuid4())

        if frozen_blueprint:
            # The ready blueprint is immutable session input. Runtime counters live
            # only in the interview snapshot copied here.
            knowledge_map = json.loads(json.dumps(frozen_blueprint))
        else:
            knowledge_map = await build_knowledge_map(
                resume_data=planner_profile,
                job_title=job_title,
                job_description=job_description,
                interview_type=request.interview_type,
                duration_minutes=duration_minutes,
                profile_type=profile_type,
                profile_instruction=profile_config["interview_instruction"],
                user_id=current_user["user_id"],
                interview_id=None,
                focus=request.focus,
                previous_weaknesses=_load_previous_weaknesses(cursor, current_user["user_id"]),
            )

        interview_settings = {
            "mode": request.interview_mode,
            "interview_mode": request.interview_mode,
            "interview_type": request.interview_type,
            "job_title": job_title,
            "job_context": _candidate_job_context(
                role=role or job_title,
                company=company,
                job_description=job_description,
                profile_type=profile_type,
                profile_label=profile_config["label"],
                blueprint=knowledge_map,
            ),
            "profile_type": profile_type,
            "profile_label": profile_config["label"],
            "profile_config_version": profile_config["config_version"],
            "profile_instruction": profile_config["interview_instruction"],
            "followup_instruction": profile_config["followup_instruction"],
            "technical_instruction": profile_config["technical_instruction"],
            "behavioral_instruction": profile_config["behavioral_instruction"],
            "strictness_level": strictness_level,
            "duration": duration_config,
            "duration_minutes": duration_minutes,
            "duration_policy": "technical_fixed_per_question" if is_technical_mode else "adaptive_target",
            "difficulty_level": "adaptive",
            "focus": ["mixed"],
            "experience_level": request.experience_level,
            "programming_language": request.programming_language,
            "technical_topics": request.technical_topics,
            "question_count": request.question_count,
            "input_mode": request.input_mode,
            "camera_mode": request.camera_mode,
            "recovery_grace_seconds": settings.SESSION_RECOVERY_GRACE_SECONDS,
            "total_battlegrounds": len(knowledge_map.get("battlegrounds", [])),
            "max_turns_per_battleground": 3 if request.interview_mode == "mock" else 2,
            "hints_enabled": False,
            "immediate_feedback": False,
            "time_limit_per_question": TECHNICAL_MINUTES_PER_QUESTION * 60 if is_technical_mode else 300,
            "nonverbal_analysis": "browser_local_camera_coaching",
            "technical_mode": is_technical_mode,
            "technical_activation_required": is_technical_mode,
            "technical_rounds": (
                ["coding"]
                if is_technical_mode and settings.TECHNICAL_CODING_ONLY
                else list(profile_config.get("technical_rounds") or ["coding", "technical_concept"])
            ) if is_technical_mode else [],
            "blueprint_id": request.blueprint_id,
            "blueprint_hash": knowledge_map.get("blueprint_hash"),
            # The immutable interview snapshot owns the full JD used by the
            # Technical compiler. Only its hash remains queryable in plaintext.
            "job_description_encrypted": encrypt_data(job_description or "") if job_description else None,
            "job_description_hash": hashlib.sha256((job_description or "").encode("utf-8")).hexdigest(),
        }

        # Technical rounds are prepared before activation.  Their server-owned
        # clock starts only from POST /api/technical/sessions/{id}/activate.
        created_at = datetime.now(timezone.utc)
        started_at = None if is_technical_mode else created_at
        deadline_at = (
            None
            if is_technical_mode
            else started_at + timedelta(minutes=int(duration_config["max_minutes"]))
        )
        cursor.execute(
            """
            INSERT INTO Interviews (
                interview_id, user_id, interview_mode, interview_type,
                job_title, strictness_level, status, session_id,
                persona_data, questions_data, questions_data_encrypted,
                settings, resume_id, job_profile_id,
                blueprint_id, start_idempotency_key, started_at, deadline_at,
                duration_seconds, created_at, attempt_status, analysis_status,
                integrity_status, lifecycle_revision
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, 'active',
                    'not_requested', 'clean', 1)
            """,
            (
                interview_id, current_user["user_id"], request.interview_mode,
                request.interview_type, job_title, strictness_level, "in_progress",
                session_id, json.dumps(persona), json.dumps({"encrypted": True}),
                encrypt_data(json.dumps(knowledge_map, default=str)).encode("utf-8"),
                json.dumps(interview_settings), selected_resume_id, frozen_job_profile_id,
                request.blueprint_id, request.start_idempotency_key,
                started_at,
                deadline_at,
                duration_minutes * 60,
                created_at,
            )
        )

        if request.blueprint_id:
            if not selected_resume_id:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Official attempts require a confirmed resume and frozen blueprint",
                )
            snapshot_id, context_hash = create_attempt_context_snapshot(
                cursor,
                interview_id=interview_id,
                user_id=current_user["user_id"],
                resume_id=selected_resume_id,
                job_profile_id=frozen_job_profile_id,
                blueprint_id=request.blueprint_id,
                profile_type=profile_type,
                profile_config_version=str(profile_config["config_version"]),
                role=str(role or job_title or "General Interview"),
                company=str(company or ""),
                resume_payload=resume_json,
                job_context={
                    "role": role or job_title,
                    "company": company,
                    "job_description": job_description,
                    "job_profile_id": frozen_job_profile_id,
                },
                blueprint_context=knowledge_map,
            )
            interview_settings["context_snapshot_id"] = snapshot_id
            interview_settings["context_hash"] = context_hash
            cursor.execute(
                "UPDATE Interviews SET settings = ? WHERE interview_id = ?",
                (json.dumps(interview_settings), interview_id),
            )
        elif settings.ENVIRONMENT != "test":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Create a server-owned blueprint and complete preflight before starting an official attempt",
            )

        if request.blueprint_id:
            cursor.execute(
                """
                UPDATE InterviewBlueprints
                SET status = 'consumed', consumed_at = CURRENT_TIMESTAMP, consumed_by_interview_id = ?
                WHERE blueprint_id = ? AND user_id = ?
                  AND status = 'ready' AND consumed_by_interview_id IS NULL
                RETURNING blueprint_id
                """,
                (interview_id, request.blueprint_id, current_user["user_id"]),
            )
            if not cursor.fetchone():
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Interview blueprint was already consumed")

        if request.preflight_id:
            cursor.execute(
                """
                UPDATE AttemptPreflightChecks
                SET consumed_at = CURRENT_TIMESTAMP, consumed_by_interview_id = ?
                WHERE preflight_id = ? AND consumed_at IS NULL
                RETURNING preflight_id
                """,
                (interview_id, request.preflight_id),
            )
            if not cursor.fetchone():
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Preflight was already consumed")

        cursor.execute(
            "UPDATE UserInfo SET interview_profile_type = ?, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?",
            (profile_type, current_user["user_id"])
        )

        if is_technical_mode:
            pass
        elif request.interview_mode == "mock":
            cursor.execute(
                "UPDATE UserInfo SET mock_interview_count = mock_interview_count + 1 WHERE user_id = ?",
                (current_user["user_id"],)
            )
        else:
            cursor.execute(
                "UPDATE UserInfo SET practice_interview_count = practice_interview_count + 1 WHERE user_id = ?",
                (current_user["user_id"],)
            )

        connection.commit()

        logger.info(
            "%s interview started: %s",
            request.interview_mode.upper(),
            stable_hash(interview_id, "interview"),
        )

        return InterviewResponse(**{
            "interview_id": interview_id,
            "session_id": session_id,
            "mode": request.interview_mode,
            "message": (
                f"{request.interview_mode.title()} interview started. "
                f"The interviewer will cover {len(knowledge_map.get('battlegrounds', []))} evidence-backed topic areas."
            ),
            "persona": persona,
            "settings": interview_settings,
            "attempt_status": "active",
            "analysis_status": "not_requested",
            "integrity_status": "clean",
            "started_at": started_at,
            "deadline_at": deadline_at,
            "server_time": datetime.now(timezone.utc),
            "recovery_grace_seconds": settings.SESSION_RECOVERY_GRACE_SECONDS,
            "lifecycle_revision": 1,
        })

    except HTTPException:
        connection.rollback()
        raise
    except Exception:
        connection.rollback()
        logger.exception("Failed to start interview")
        if settings.ENVIRONMENT == "test":
            raise
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to start interview. Please try again."
        )

    finally:
        cursor.close()
        return_db_connection(connection)

@router.websocket("/ws/video")
async def websocket_video_interview(websocket: WebSocket):
    origin = websocket.headers.get("origin")
    token = websocket.headers.get("x-prepmate-token") or websocket.headers.get("x-interai-token") or websocket.query_params.get("desktop_token")
    host = websocket.url.hostname or websocket.headers.get("host", "")
    authorized = (
        is_loopback_host(host)
        and (is_allowed_local_origin(origin) or (configured_api_token() and api_token_matches(token)))
        and api_token_matches(token)
    )
    if not authorized:
        await websocket.close(code=1008, reason="Local desktop authorization failed")
        return

    user_id = LOCAL_USER_ID
    coordination_store = get_local_cache()
    ws_connection_id = str(uuid.uuid4())
    active_session_key: Optional[str] = None
    controller_lease_task: Optional[asyncio.Task] = None
    session_bound = False
    ws_closing = False
    background_tasks = set()
    interview_id: Optional[str] = None
    completion_sent = False

    try:
        await websocket.accept()
        logger.info("Video WebSocket connected: %s", stable_hash(user_id, "user"))

        interview_mode: Optional[str] = None
        knowledge_map: Optional[Dict] = None
        persona: Optional[Dict] = None
        ws_settings: Dict = {}
        pipeline_initialized = False
        current_battleground: Optional[Dict] = None
        nonverbal_data: deque[Dict] = deque(maxlen=20)
        question_start_time: Optional[datetime] = None
        conversation_history: List[Dict] = []
        persisted_question_ids: set[str] = set()
        current_question_text: Optional[str] = None
        current_question_id: Optional[str] = None
        current_question_type: str = "main"
        current_parent_question_id: Optional[str] = None
        warmup_pending: bool = False
        opening_intro_delivered: bool = False
        # Pipeline removed — monitoring managed client-side
        resume_context: str = ""
        report_profile_context: Dict[str, Any] = {}
        session_started_at: Optional[datetime] = None
        session_activated_at: Optional[datetime] = None
        session_deadline_at: Optional[datetime] = None
        quality_failure_streak = 0

        msg_timestamps: deque[float] = deque()
        server_frame_counter: int = 0
        integrity_server_sequence: int = 0
        question_ack_state: Dict[str, Dict[str, Any]] = {}
        answer_processing_lock = asyncio.Lock()

        def track_ws_task(coro):
            task = asyncio.create_task(coro)
            background_tasks.add(task)

            def _finish_task(done_task):
                background_tasks.discard(done_task)
                if done_task.cancelled():
                    return
                try:
                    exc = done_task.exception()
                except asyncio.CancelledError:
                    return
                if exc and not ws_closing:
                    logger.warning("WS background task failed: %s", redact_text(exc))

            task.add_done_callback(_finish_task)
            return task

        async def send_ws_message(data: dict):
            if ws_closing:
                return
            try:
                await websocket.send_json(data)
            except Exception as e:
                message = str(e)
                if ws_closing or "websocket.close" in message or "response already completed" in message:
                    logger.debug("Skipped WS send after close: %s", redact_text(e))
                else:
                    logger.error("Failed to send WS message: %s", redact_text(e))

        async def renew_controller_loop():
            nonlocal ws_closing
            while not ws_closing and active_session_key:
                await asyncio.sleep(CONTROLLER_RENEWAL_SECONDS)
                if ws_closing or not active_session_key:
                    return
                try:
                    renewed = renew_controller_lease(coordination_store, active_session_key, ws_connection_id)
                except Exception:
                    renewed = False
                if renewed:
                    continue
                logger.warning("Interview controller lease renewal failed")
                await send_ws_message({
                    "type": "error",
                    "code": "controller_lease_lost",
                    "message": "The interview controller lease was lost. Reconnecting safely…",
                })
                try:
                    await websocket.close(code=1013, reason="Controller lease lost")
                except Exception:
                    pass
                return

        async def persist_integrity_event(
            event_type: str,
            payload: Dict[str, Any],
            *,
            source: str = "browser",
            event_id: str = "",
            client_session_id: str = "",
            sequence: int = 0,
            sent_at: str = "",
        ) -> bool:
            nonlocal integrity_server_sequence
            if not interview_id or not user_id:
                return False
            canonical_type = canonical_integrity_event(event_type)
            if not sequence:
                integrity_server_sequence += 1
                sequence = integrity_server_sequence
            resolved_event_id = event_id or str(uuid.uuid4())
            resolved_client_session = client_session_id or ws_connection_id
            observed_at = datetime.now(timezone.utc)
            if sent_at:
                try:
                    observed_at = _coerce_blueprint_datetime(sent_at)
                except Exception:
                    pass
            safe_payload = payload if isinstance(payload, dict) else {}
            encoded_payload = json.dumps(safe_payload, sort_keys=True, separators=(",", ":"), default=str)
            payload_hash = hashlib.sha256(encoded_payload.encode("utf-8")).hexdigest()
            inserted = await async_execute(
                """
                INSERT INTO AttemptIntegrityEvents (
                    event_id, interview_id, user_id, client_session_id, sequence,
                    event_type, severity, source, observed_at, received_at,
                    payload_encrypted, payload_hash, idempotency_key
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?, ?, ?)
                ON CONFLICT DO NOTHING
                RETURNING event_id
                """,
                (
                    resolved_event_id, interview_id, user_id, resolved_client_session,
                    sequence, canonical_type,
                    "info",
                    source, observed_at, encrypt_data(encoded_payload).encode("utf-8"),
                    payload_hash, resolved_event_id,
                ),
                fetchone=True,
            )
            return bool(inserted)

        async def update_question_delivery_metadata(question_id: str, metadata: Dict[str, Any]):
            if not question_id:
                return
            await asyncio.to_thread(
                _db_execute,
                """
                UPDATE InterviewQuestions
                SET generation_metadata = json_patch(COALESCE(generation_metadata, '{}'), ?)
                WHERE question_id = ?
                """,
                (json.dumps(metadata), question_id),
                commit=True,
            )

        async def retry_question_if_unacked(question_id: str, payload: Dict[str, Any]):
            await asyncio.sleep(1.5)
            state = question_ack_state.get(question_id)
            if not state or state.get("acked"):
                return
            state["retries"] = int(state.get("retries") or 0) + 1
            retry_payload = {
                **payload,
                "retry": True,
                "question_audio": None,
            }
            await send_ws_message(retry_payload)
            await update_question_delivery_metadata(
                question_id,
                {
                    "delivery_retry": {
                        "sequence": state.get("sequence"),
                        "retry_count": state["retries"],
                        "retried_at": datetime.now(timezone.utc).isoformat(),
                    }
                },
            )

        async def send_question_message(payload: Dict[str, Any]):
            nonlocal server_frame_counter
            question_id = payload.get("question_id")
            if not question_id:
                await send_ws_message(payload)
                return
            server_frame_counter += 1
            sequence = server_frame_counter
            enriched = {
                **payload,
                "delivery_id": f"{question_id}:{sequence}",
                "sequence": sequence,
                "requires_ack": True,
            }
            question_ack_state[question_id] = {
                "sequence": sequence,
                "sent_at": datetime.now(timezone.utc).isoformat(),
                "acked": False,
                "retries": 0,
            }
            await update_question_delivery_metadata(
                question_id,
                {
                    "delivery": {
                        "sequence": sequence,
                        "delivery_id": enriched["delivery_id"],
                        "sent_at": question_ack_state[question_id]["sent_at"],
                    }
                },
            )
            await send_ws_message(enriched)
            track_ws_task(retry_question_if_unacked(question_id, enriched))

        def get_topic_number(battleground_id: Any) -> int:
            if not knowledge_map:
                return 1
            for index, bg in enumerate(knowledge_map.get("battlegrounds", []), start=1):
                if bg.get("id") == battleground_id:
                    return index
            return 1

        async def send_processing_idle():
            await send_ws_message({
                "type": "vad_state",
                "speaking": False,
                "processing": False,
            })

        def configured_duration_seconds(key: str, fallback_minutes: int) -> int:
            duration = ws_settings.get("duration") if isinstance(ws_settings, dict) else {}
            if not isinstance(duration, dict):
                duration = {}
            try:
                minutes = int(duration.get(key) or fallback_minutes)
            except (TypeError, ValueError):
                minutes = fallback_minutes
            return max(1, minutes) * 60

        def interview_elapsed_seconds() -> int:
            if not session_activated_at:
                return 0
            return max(0, int((datetime.now(timezone.utc) - session_activated_at).total_seconds()))

        def has_candidate_evidence() -> bool:
            for item in conversation_history:
                if item.get("role") != "candidate":
                    continue
                content = str(item.get("content") or "").strip()
                if len(content.split()) >= 3:
                    return True
            return False

        def below_minimum_duration() -> bool:
            return interview_elapsed_seconds() < configured_duration_seconds("min_minutes", 45)

        def reached_maximum_duration() -> bool:
            if session_deadline_at:
                return datetime.now(timezone.utc) >= session_deadline_at
            return interview_elapsed_seconds() >= configured_duration_seconds("max_minutes", 60)

        async def persist_knowledge_map_state():
            if not interview_id or knowledge_map is None:
                return
            await asyncio.to_thread(
                _db_execute,
                """
                UPDATE Interviews
                SET questions_data = ?, questions_data_encrypted = ?
                WHERE interview_id = ?
                """,
                (
                    json.dumps({"encrypted": True}),
                    encrypt_data(json.dumps(knowledge_map, default=str)).encode("utf-8"),
                    interview_id,
                ),
                commit=True,
            )

        async def persist_answer_quality_streak(value: int):
            if not interview_id:
                return
            ws_settings["answer_quality_failure_streak"] = max(0, int(value))
            await async_execute(
                """
                UPDATE Interviews
                SET settings = json_patch(
                    COALESCE(settings, '{}'),
                    json_object('answer_quality_failure_streak', ?)
                )
                WHERE interview_id = ? AND user_id = ?
                """,
                (max(0, int(value)), interview_id, user_id),
            )

        async def persist_asked_question(
            *,
            question_id: str,
            question_text: str,
            question_type: str,
            battleground: Dict[str, Any],
            parent_question_id: Optional[str] = None,
            generation_metadata: Optional[Dict[str, Any]] = None,
        ):
            if not interview_id or question_id in persisted_question_ids:
                return
            question_order = len(
                [entry for entry in conversation_history if entry.get("role") == "interviewer"]
            )
            metadata = {
                "profile_type": ws_settings.get("profile_type"),
                "profile_label": ws_settings.get("profile_label"),
                "job_title": ws_settings.get("job_title"),
                "source": "live_ai",
                "scoring_excluded": question_type in {"warmup", "introduction"},
                **(generation_metadata or {}),
            }
            section_id = str(battleground.get("section_id") or "").strip() or None
            expected_points = []
            for index, point in enumerate(battleground.get("expected_points") or [], start=1):
                if isinstance(point, dict):
                    point_id = str(point.get("point_id") or point.get("id") or "").strip()
                    label = str(point.get("label") or point.get("text") or point_id).strip()
                else:
                    label = str(point or "").strip()
                    point_id = ""
                if not label:
                    continue
                expected_points.append({
                    "point_id": point_id or f"{section_id or question_id}:point:{index}",
                    "label": label,
                })
            await asyncio.to_thread(
                _db_execute,
                """
                INSERT INTO InterviewQuestions (
                    question_id, interview_id, question_text, question_order,
                    question_type, topic_label, profile_type, rubric_version, source,
                    expected_signal, difficulty_level, is_followup, parent_question_id,
                    generation_metadata, taxonomy_keys, expected_points, rubric_json,
                    selection_reason, blueprint_section_id, provenance,
                    question_spec_id, max_followups, time_budget_seconds,
                    expected_point_ids
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                          ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (question_id) DO NOTHING
                """,
                (
                    question_id,
                    interview_id,
                    question_text,
                    question_order,
                    question_type,
                    battleground.get("label"),
                    ws_settings.get("profile_type"),
                    "tiered_dynamic_v1",
                    "live_ai",
                    battleground.get("expected_signal") or battleground.get("estimated_difficulty"),
                    ws_settings.get("strictness_level", "medium"),
                    question_type in {"followup", "retry"},
                    parent_question_id,
                    json.dumps(metadata),
                    json.dumps(battleground.get("taxonomy_keys") or []),
                    json.dumps(expected_points),
                    json.dumps(battleground.get("rubric") or {}),
                    battleground.get("selection_reason"),
                    section_id,
                    json.dumps(battleground.get("provenance") or {"selection": "deterministic"}),
                    question_id,
                    int(battleground.get("max_followups") or 2),
                    int(battleground.get("time_budget_seconds") or 0) or None,
                    json.dumps([point["point_id"] for point in expected_points]),
                ),
                commit=True,
            )
            persisted_question_ids.add(question_id)

        async def complete_interview(
            include_closing_audio: bool = False,
            *,
            force: bool = False,
            reason: str = "session_end",
        ):
            nonlocal completion_sent
            if not interview_id:
                return
            if completion_sent:
                return
            if not force and not has_candidate_evidence():
                logger.info(
                    "Skipping automatic finalization for %s because no candidate evidence was captured",
                    stable_hash(interview_id, "interview"),
                )
                return
            completion_sent = True

            transcript = [
                {"role": item.get("role"), "content": item.get("content")}
                for item in conversation_history
                if item.get("role") in {"interviewer", "candidate"}
            ]

            try:
                finalization = await _finalize_interview_for_analysis(
                    interview_id=interview_id,
                    user_id=user_id,
                    reason=reason,
                    transcript=transcript,
                )
            except Exception:
                completion_sent = False
                raise

            if finalization.get("cancelled"):
                return

            job_id = finalization.get("analysis_job_id")

            # Fire coach exercise generation as a background task
            payload = {
                "type": "interview_complete",
                "analysis_status": finalization.get("status") or "analysis_pending",
                "analysis_job_id": job_id,
                "redirect_to": f"/interview/{interview_id}/report",
                "stop_monitoring": True,
            }

            if include_closing_audio:
                closing_text = (
                    "That covers everything I wanted to go through today. "
                    "Thank you for your time. Your recording is being analyzed now, "
                    "and your detailed report will appear when processing finishes."
                )
                payload["closing_text"] = closing_text

            await send_ws_message(payload)

        async def register_live_quality_failure(
            code: str,
            message: str,
            *,
            finalize_on_threshold: bool = True,
        ) -> bool:
            nonlocal quality_failure_streak
            quality_failure_streak += 1
            await persist_answer_quality_streak(quality_failure_streak)
            await send_ws_message({
                "type": "answer_rejected",
                "code": code,
                "retryable": quality_failure_streak < MAX_LIVE_ANSWER_QUALITY_FAILURES,
                "quality_failure_streak": quality_failure_streak,
                "message": message,
            })
            await send_ws_message({
                "type": "answer_quality_feedback",
                "severity": "error" if quality_failure_streak >= MAX_LIVE_ANSWER_QUALITY_FAILURES else "warning",
                "message": message,
            })
            should_finalize = quality_failure_streak >= MAX_LIVE_ANSWER_QUALITY_FAILURES
            if should_finalize and finalize_on_threshold:
                await send_ws_message({
                    "type": "interview_ending",
                    "message": "I could not get a relevant answer after three attempts, so this interview is ending.",
                    "reason": "repeated_low_quality_answers",
                })
                await complete_interview(
                    include_closing_audio=False,
                    force=True,
                    reason="repeated_low_quality_answers",
                )
            return should_finalize

        async def ask_minimum_duration_followup(
            *,
            active_bg: Dict[str, Any],
            parent_question_id: str,
            parent_question_text: str,
            candidate_response: str,
            live_score: float,
        ):
            nonlocal knowledge_map
            nonlocal current_question_id
            nonlocal current_question_text
            nonlocal current_question_type
            nonlocal current_parent_question_id
            nonlocal question_start_time

            followup_question_id = str(uuid.uuid4())
            elapsed_minutes = interview_elapsed_seconds() // 60
            min_minutes = configured_duration_seconds("min_minutes", 45) // 60
            followup_text = await generate_contextual_followup(
                battleground_label=active_bg.get("label") or "the current topic",
                main_question=parent_question_text,
                candidate_response=candidate_response,
                conversation_history=conversation_history,
                performance_score=live_score,
                interview_mode=interview_mode or "mock",
                profile_instruction=(
                    f"{ws_settings.get('followup_instruction', '')} "
                    f"The interview minimum is {min_minutes} minutes and only {elapsed_minutes} minutes have elapsed. "
                    "Ask a deeper evidence-based follow-up from the candidate's actual answer instead of closing."
                ).strip(),
                profile_type=ws_settings.get("profile_type", "mid_tier"),
                job_title=ws_settings.get("job_title", ""),
                resume_context=resume_context,
                job_context=ws_settings.get("job_context"),
                question_id=followup_question_id,
                parent_question_id=parent_question_id,
                user_id=user_id,
                interview_id=interview_id,
            )

            if knowledge_map:
                for bg in knowledge_map.get("battlegrounds", []):
                    if bg.get("id") == active_bg.get("id"):
                        bg["max_turns"] = int(bg.get("max_turns") or 0) + 1
                        break
                knowledge_map = mark_turn_used(knowledge_map, active_bg["id"])
                await persist_knowledge_map_state()

            current_question_id = followup_question_id
            current_question_text = followup_text
            current_question_type = "followup"
            current_parent_question_id = parent_question_id
            question_start_time = datetime.now(timezone.utc)
            nonverbal_data.clear()

            conversation_history.append({
                "role": "interviewer",
                "content": followup_text,
                "battleground_id": active_bg.get("id"),
                "type": "followup",
            })

            await persist_asked_question(
                question_id=followup_question_id,
                question_text=followup_text,
                question_type="followup",
                battleground=active_bg,
                parent_question_id=parent_question_id,
                generation_metadata={
                    "reason": "minimum_duration_guard",
                    "elapsed_seconds": interview_elapsed_seconds(),
                    "minimum_seconds": configured_duration_seconds("min_minutes", 45),
                },
            )

            await send_question_message({
                "type": "question",
                "question_id": followup_question_id,
                "question_type": "followup",
                "topic": active_bg.get("label") or "Interview depth",
                "battleground_id": active_bg.get("id"),
                "question_text": followup_text,
                "question_audio": None,
                # Timing remains an internal pacing control. Candidates should
                # see a natural continuation, not the interview duration or
                # an internal progress calculation.
                "progress": "Continuing the conversation",
            })

        async def _process_candidate_response(
            response_text: str,
            *,
            idempotency_key: Optional[str] = None,
            client_question_id: Optional[str] = None,
            input_mode: str = "voice",
            timing: Optional[Dict[str, Any]] = None,
        ):
            nonlocal knowledge_map
            nonlocal current_battleground
            nonlocal question_start_time
            nonlocal current_question_text
            nonlocal current_question_id
            nonlocal current_question_type
            nonlocal current_parent_question_id
            nonlocal warmup_pending
            nonlocal quality_failure_streak

            try:
                cleaned_response = (response_text or "").strip()
                if not cleaned_response:
                    await send_ws_message({
                        "type": "error",
                        "message": "Empty response received"
                    })
                    return

                if not current_question_text or not current_battleground or not knowledge_map or not interview_id:
                    await send_ws_message({
                        "type": "error",
                        "message": "No active interview question"
                    })
                    return

                if not warmup_pending and not _is_usable_live_answer(cleaned_response):
                    await register_live_quality_failure(
                        "answer_too_short",
                        "I need a complete answer. Please finish your thought and answer the question directly.",
                    )
                    return

                question_id = current_question_id or str(uuid.uuid4())
                if client_question_id and str(client_question_id) != str(question_id):
                    await send_ws_message({
                        "type": "error",
                        "code": "stale_question",
                        "message": "This answer belongs to an earlier question and was not applied.",
                        "current_question_id": question_id,
                    })
                    return

                time_taken = (
                    (datetime.now(timezone.utc) - question_start_time).total_seconds()
                    if question_start_time else 0
                )
                timing_payload = dict(timing or {})
                timing_payload.setdefault("response_latency_seconds", round(max(0.0, time_taken), 3))
                measured_response_seconds = timing_payload.get("voiced_duration_seconds")
                if not isinstance(measured_response_seconds, (int, float)) or measured_response_seconds <= 0:
                    measured_response_seconds = time_taken

                question_kind = "warmup" if warmup_pending else current_question_type
                parent_question_id = None if warmup_pending else current_parent_question_id
                question_spec = (
                    {
                        "section_id": "warmup",
                        "label": "Warm-up",
                        "kind": "behavioral",
                        "taxonomy_keys": ["behavioral:introduction"],
                        "expected_points": ["personal ownership", "role relevance"],
                        "rubric": {
                            "version": "warmup_v1",
                            "weights": {"relevance": 0.5, "communication": 0.5},
                            "unknown_dimensions_are_null": True,
                        },
                        "selection_reason": "Session introduction",
                        "estimated_difficulty": "easy",
                    }
                    if warmup_pending
                    else current_battleground
                )
                if question_id not in persisted_question_ids:
                    await persist_asked_question(
                        question_id=question_id,
                        question_text=current_question_text,
                        question_type=question_kind,
                        battleground=question_spec,
                        parent_question_id=parent_question_id,
                        generation_metadata={
                            "warmup": warmup_pending,
                            "fallback_persisted_after_answer": True,
                        },
                    )

                response_id = str(uuid.uuid4())
                conversation_history.append({
                    "role": "candidate",
                    "content": cleaned_response,
                    "question_id": question_id,
                })
                resolved_key = str(idempotency_key or "").strip() or (
                    f"legacy:{question_id}:{_answer_hash(question_id, cleaned_response)[:24]}"
                )
                raw = await asyncio.to_thread(
                    _persist_raw_answer,
                    response_id=response_id,
                    interview_id=interview_id,
                    question_id=question_id,
                    answer=cleaned_response,
                    response_seconds=float(measured_response_seconds or 0),
                    idempotency_key=resolved_key,
                    input_mode=input_mode,
                    timing=timing_payload,
                    nonverbal_metrics={"samples": list(nonverbal_data), "source": "browser_measured"},
                )
                response_id = str(raw["response_id"])
                if not raw["inserted"]:
                    stored_assessment = raw.get("assessment")
                    if stored_assessment:
                        await send_ws_message({
                            "type": "answer_committed",
                            "response_id": response_id,
                            "idempotency_key": resolved_key,
                            "duplicate": True,
                            "assessment": stored_assessment if interview_mode == "practice" else {
                                "version": stored_assessment.get("version"),
                                "insufficient_evidence": stored_assessment.get("insufficient_evidence"),
                                "semantic_status": stored_assessment.get("semantic_status"),
                            },
                            "decision": stored_assessment.get("decision"),
                            "next_question": stored_assessment.get("next_question"),
                        })
                        return
                    # The raw answer was committed before a prior worker or
                    # socket failed. Re-run only the missing assessment; the
                    # assessment/next-question transaction below is idempotent.
                    await send_ws_message({
                        "type": "answer_pending",
                        "response_id": response_id,
                        "idempotency_key": resolved_key,
                        "duplicate": True,
                        "recovering": True,
                    })

                point_contract = _expected_point_contract(question_spec, question_id)
                rubric = {
                    **(question_spec.get("rubric") or {}),
                    "expected_points": point_contract,
                }
                context = {
                    "interview_type": (
                        ws_settings.get("interview_type")
                        or question_spec.get("kind")
                        or "mock"
                    ),
                    "question_type": question_spec.get("kind") or question_kind,
                    "taxonomy_keys": question_spec.get("taxonomy_keys") or [],
                    "source_anchors": question_spec.get("source_anchors") or [],
                    "semantic_analysis_enabled": True,
                }
                try:
                    evaluation = await asyncio.wait_for(
                        evaluate_answer(
                            current_question_text,
                            cleaned_response,
                            rubric,
                            context,
                            measured_response_seconds,
                            [],
                            user_id=user_id,
                            interview_id=interview_id,
                            response_id=response_id,
                        ),
                        timeout=6.0,
                    )
                except asyncio.TimeoutError:
                    evaluation = await evaluate_answer(
                        current_question_text,
                        cleaned_response,
                        rubric,
                        {**context, "semantic_analysis_enabled": False},
                        measured_response_seconds,
                        [],
                        user_id=user_id,
                        interview_id=interview_id,
                        response_id=response_id,
                    )
                    evaluation["semantic_status"] = {
                        **(evaluation.get("semantic_status") or {}),
                        "state": "failed",
                        "attempted": True,
                        "reason": "semantic_timeout",
                    }
                evaluation = _sanitize_live_evaluation(
                    evaluation,
                    question_spec=question_spec,
                    question_id=question_id,
                )

                if warmup_pending:
                    # The introduction helps the interviewer orient follow-up
                    # wording only.  It is persisted as context evidence, but
                    # can never contribute a score, quality failure, or
                    # learning signal.
                    evaluation.update({
                        "overall_score": None,
                        "provisional_score": None,
                        "authoritative": False,
                        "insufficient_evidence": True,
                        "evidence_status": "context_only",
                        "scoring_excluded": True,
                        "answer_quality_flags": [],
                    })
                    answer_is_relevant, quality_reason = True, "context_only"
                else:
                    answer_is_relevant, quality_reason = _live_answer_quality(evaluation)
                quality_retry = False
                quality_end = False
                quality_feedback = ""
                if answer_is_relevant:
                    if quality_failure_streak:
                        quality_failure_streak = 0
                        await persist_answer_quality_streak(0)
                else:
                    quality_feedback = _live_answer_feedback(quality_reason)
                    quality_end = await register_live_quality_failure(
                        quality_reason,
                        quality_feedback,
                        finalize_on_threshold=False,
                    )
                    quality_retry = not quality_end

                active_bg = current_battleground
                if isinstance(evaluation.get("overall_score"), (int, float)) and not warmup_pending:
                    recent_scores = active_bg.setdefault("recent_authoritative_scores", [])
                    recent_scores.append(float(evaluation["overall_score"]))
                    del recent_scores[:-2]
                    if len(recent_scores) == 2 and all(score >= 80 for score in recent_scores):
                        levels = ["easy", "medium", "hard"]
                        current_level = str(active_bg.get("estimated_difficulty") or "medium").lower()
                        current_level = {"matched": "medium", "stretch": "hard", "diagnostic": "easy"}.get(current_level, current_level)
                        active_bg["estimated_difficulty"] = levels[min(2, levels.index(current_level) + 1)] if current_level in levels else "hard"
                    elif len(recent_scores) == 2 and all(score < 50 for score in recent_scores):
                        active_bg["estimated_difficulty"] = "diagnostic"

                requested_action = str((evaluation.get("follow_up") or {}).get("action") or "advance")
                followups_used = int(active_bg.get("policy_followups_used") or 0)
                should_follow = (
                    not warmup_pending
                    and requested_action != "advance"
                    and followups_used < 2
                    and not reached_maximum_duration()
                )

                next_bg: Optional[Dict[str, Any]] = None
                next_question: Optional[Dict[str, Any]] = None
                next_ws_payload: Optional[Dict[str, Any]] = None
                if quality_end:
                    next_bg = None
                    decision_action = "end"
                    decision_reason = "repeated_low_quality_answers"
                elif quality_retry:
                    next_bg = active_bg
                    decision_action = "retry"
                    decision_reason = quality_reason
                elif warmup_pending:
                    warmup_pending = False
                    next_bg = current_battleground or get_next_battleground(knowledge_map)
                    decision_action = "advance"
                    decision_reason = "warmup_complete"
                elif should_follow:
                    next_bg = active_bg
                    decision_action = requested_action
                    decision_reason = str((evaluation.get("follow_up") or {}).get("reason") or "deterministic_policy")
                else:
                    active_bg["current_turns"] = max(
                        int(active_bg.get("current_turns") or 0),
                        int(active_bg.get("max_turns") or 1),
                    )
                    next_bg = get_next_battleground(knowledge_map)
                    decision_action = "advance"
                    decision_reason = (
                        "followup_budget_exhausted" if followups_used >= 2
                        else "topic_time_exhausted" if reached_maximum_duration()
                        else str((evaluation.get("follow_up") or {}).get("reason") or "coverage_met")
                    )

                minimum_duration_depth = False
                if next_bg is None and not quality_end and below_minimum_duration() and not reached_maximum_duration():
                    next_bg = active_bg
                    should_follow = True
                    minimum_duration_depth = True
                    decision_action = "deepen"
                    decision_reason = "minimum_duration_evidence_depth"

                if next_bg and not reached_maximum_duration():
                    next_question_id = str(uuid.uuid4())
                    if quality_retry:
                        next_question_type = "warmup" if warmup_pending else "retry"
                        next_parent_id = None if warmup_pending else question_id
                        next_question_text = _live_retry_question(
                            current_question_text,
                            (
                                "your background and interest in this role"
                                if current_question_type == "warmup"
                                else str(active_bg.get("label") or "the requested topic")
                            ),
                            quality_reason,
                            quality_failure_streak,
                        )
                        reason_metadata = {
                            "reason": decision_reason,
                            "action": decision_action,
                            "policy_version": EVALUATION_VERSION,
                            "answered_question_id": question_id,
                            "quality_failure_streak": quality_failure_streak,
                        }
                    elif should_follow:
                        next_question_type = "followup"
                        next_parent_id = question_id
                        if minimum_duration_depth:
                            next_question_text = await generate_contextual_followup(
                                battleground_label=str(active_bg.get("label") or "this topic"),
                                main_question=current_question_text,
                                candidate_response=cleaned_response,
                                conversation_history=conversation_history,
                                performance_score=float(evaluation.get("provisional_score") or 0),
                                interview_mode=interview_mode or "mock",
                                profile_instruction=(
                                    f"{ws_settings.get('followup_instruction', '')} "
                                    "Continue naturally with one new, evidence-based question from the candidate's answer. "
                                    "Do not repeat the previous wording and do not coach the answer."
                                ).strip(),
                                profile_type=ws_settings.get("profile_type", "mid_tier"),
                                job_title=ws_settings.get("job_title", ""),
                                resume_context=resume_context,
                                job_context=ws_settings.get("job_context"),
                                followup_action=decision_action,
                                question_id=next_question_id,
                                parent_question_id=question_id,
                                user_id=user_id,
                                interview_id=interview_id,
                            )
                        else:
                            next_question_text = await generate_contextual_followup(
                                battleground_label=str(active_bg.get("label") or "this topic"),
                                main_question=current_question_text,
                                candidate_response=cleaned_response,
                                conversation_history=conversation_history,
                                performance_score=float(evaluation.get("provisional_score") or 0),
                                interview_mode=interview_mode or "mock",
                                profile_instruction=(
                                    f"{ws_settings.get('followup_instruction', '')} "
                                    f"The deterministic follow-up action is {decision_action}. "
                                    "Ask one new question that stays on this topic and refers to a concrete detail from the candidate's answer. "
                                    "Do not switch topics, repeat the previous question, or give coaching."
                                ).strip(),
                                profile_type=ws_settings.get("profile_type", "mid_tier"),
                                job_title=ws_settings.get("job_title", ""),
                                resume_context=resume_context,
                                job_context=ws_settings.get("job_context"),
                                followup_action=decision_action,
                                question_id=next_question_id,
                                parent_question_id=question_id,
                                user_id=user_id,
                                interview_id=interview_id,
                            )
                        active_bg["policy_followups_used"] = followups_used + 1
                        knowledge_map = mark_turn_used(knowledge_map, active_bg["id"])
                        reason_metadata = {
                            "reason": decision_reason,
                            "action": decision_action,
                            "policy_version": EVALUATION_VERSION,
                            "answered_question_id": question_id,
                        }
                    else:
                        next_question_type = "main"
                        next_parent_id = None
                        next_question_text = await generate_battleground_question(
                            battleground=next_bg,
                            resume_context=resume_context,
                            conversation_history=conversation_history,
                            interview_mode=interview_mode or "mock",
                            profile_instruction=ws_settings.get("profile_instruction", ""),
                            profile_type=ws_settings.get("profile_type", "mid_tier"),
                            job_title=ws_settings.get("job_title", ""),
                            transition_hint="",
                            question_id=next_question_id,
                            parent_question_id=None,
                            user_id=user_id,
                            interview_id=interview_id,
                        )
                        knowledge_map = mark_turn_used(knowledge_map, next_bg["id"])
                        reason_metadata = {
                            "reason": "next_blueprint_section",
                            "policy_version": EVALUATION_VERSION,
                            "answered_question_id": question_id,
                        }
                    next_question = _question_insert_payload(
                        question_id=next_question_id,
                        question_text=next_question_text,
                        question_type=next_question_type,
                        battleground=next_bg,
                        parent_question_id=next_parent_id,
                        profile_type=ws_settings.get("profile_type"),
                        job_title=ws_settings.get("job_title"),
                        generation_metadata=reason_metadata,
                    )
                    next_ws_payload = {
                        "type": "question",
                        "question_id": next_question_id,
                        "question_type": next_question_type,
                        "topic": next_bg.get("label"),
                        "battleground_id": next_bg.get("id"),
                        "question_text": next_question_text,
                        "question_audio": None,
                        "progress": (
                            f"Topic {get_topic_number(next_bg.get('id'))} of {len(knowledge_map['battlegrounds'])}"
                            + (" — follow-up" if next_question_type == "followup" else "")
                        ),
                    }

                evaluation["decision"] = {
                    "action": decision_action,
                    "reason": decision_reason,
                    "followups_used": int(active_bg.get("policy_followups_used") or 0),
                    "maximum_followups": 2,
                    "finalize": next_question is None,
                }
                if quality_feedback:
                    evaluation["quality_gate"] = {
                        "status": "retry" if quality_retry else "ended",
                        "reason": quality_reason,
                        "failure_streak": quality_failure_streak,
                    }
                evaluation["response_id"] = response_id
                evaluation["question_id"] = question_id
                evaluation["idempotency_key"] = resolved_key
                evaluation["next_question"] = (
                    {
                        "question_id": next_question["question_id"],
                        "question_type": next_question["question_type"],
                        "topic": next_question.get("topic_label"),
                        "question_text": next_question["question_text"],
                    }
                    if next_question else None
                )
                committed = await asyncio.to_thread(
                    _commit_live_assessment,
                    response_id=response_id,
                    interview_id=interview_id,
                    assessment=evaluation,
                    evidence_hash=_assessment_hash(response_id, question_spec, raw["raw_answer_hash"]),
                    knowledge_map=knowledge_map,
                    next_question=next_question,
                )
                if next_question:
                    persisted_question_ids.add(next_question["question_id"])

                public_assessment = evaluation if interview_mode == "practice" else {
                    "version": evaluation.get("version"),
                    "insufficient_evidence": evaluation.get("insufficient_evidence"),
                    "semantic_status": evaluation.get("semantic_status"),
                }
                await send_ws_message({
                    "type": "answer_committed",
                    "response_id": response_id,
                    "idempotency_key": resolved_key,
                    "duplicate": bool(committed.get("duplicate")),
                    "assessment": public_assessment,
                    "decision": evaluation["decision"],
                    "next_question": evaluation["next_question"],
                })

                if not next_question or not next_ws_payload:
                    await complete_interview(include_closing_audio=True)
                    return

                current_battleground = next_bg
                current_question_id = next_question["question_id"]
                current_question_text = next_question["question_text"]
                current_question_type = next_question["question_type"]
                current_parent_question_id = next_question.get("parent_question_id")
                question_start_time = datetime.now(timezone.utc)
                nonverbal_data.clear()
                conversation_history.append({
                    "role": "interviewer",
                    "content": current_question_text,
                    "battleground_id": next_bg.get("id") if next_bg else None,
                    "type": current_question_type,
                })
                await send_question_message(next_ws_payload)
            finally:
                await send_processing_idle()

        async def process_candidate_response(
            response_text: str,
            *,
            idempotency_key: Optional[str] = None,
            client_question_id: Optional[str] = None,
            input_mode: str = "voice",
            timing: Optional[Dict[str, Any]] = None,
        ):
            if answer_processing_lock.locked():
                await send_ws_message({
                    "type": "answer_rejected",
                    "code": "answer_processing",
                    "retryable": True,
                    "message": "I am still processing your previous answer. Please wait for the next question.",
                })
                await send_processing_idle()
                return
            async with answer_processing_lock:
                await _process_candidate_response(
                    response_text,
                    idempotency_key=idempotency_key,
                    client_question_id=client_question_id,
                    input_mode=input_mode,
                    timing=timing,
                )

        while True:
            try:
                # A browser reload or a dropped display-capture stream can
                # make Starlette raise RuntimeError here instead of the
                # normal WebSocketDisconnect.  Treat that as a terminal
                # receive failure.  Leaving it in the generic handler below
                # immediately re-enters receive_text(), producing a hot loop
                # that starves every HTTP endpoint on the API process.
                try:
                    data = await websocket.receive_text()
                except WebSocketDisconnect:
                    raise
                except RuntimeError as exc:
                    logger.info("Video WebSocket receive ended: %s", redact_text(exc))
                    break

                if len(data) > settings.WS_MAX_MESSAGE_SIZE:
                    await send_ws_message({
                        "type": "error",
                        "message": f"Message too large (max {settings.WS_MAX_MESSAGE_SIZE // 1024}KB)"
                    })
                    continue

                now_ts = time()
                msg_timestamps.append(now_ts)
                cutoff = now_ts - settings.WS_MESSAGE_WINDOW
                while msg_timestamps and msg_timestamps[0] < cutoff:
                    msg_timestamps.popleft()
                if len(msg_timestamps) > settings.WS_MESSAGE_RATE_LIMIT:
                    await send_ws_message({
                        "type": "error",
                        "message": "Rate limit exceeded — slow down"
                    })
                    await websocket.close(code=4008, reason="Rate limit exceeded")
                    return

                raw_message = json.loads(data)
                client_event = parse_client_event(
                    raw_message,
                    allow_legacy=settings.ENVIRONMENT == "test",
                )
                if not client_event.legacy:
                    if coordination_store is None:
                        await send_ws_message({
                            "type": "error",
                            "code": "event_dedup_unavailable",
                            "message": "The event controller is temporarily unavailable. Reconnecting safely…",
                        })
                        await websocket.close(code=1013, reason="Event deduplication unavailable")
                        return
                    if interview_id and client_event.interview_id != interview_id:
                        await send_ws_message({
                            "type": "error",
                            "code": "event_interview_mismatch",
                            "message": "The event does not belong to this interview.",
                        })
                        continue
                    try:
                        claim_status = claim_event_sequence(coordination_store, client_event)
                    except Exception:
                        await send_ws_message({
                            "type": "error",
                            "code": "event_dedup_unavailable",
                            "message": "The event controller is temporarily unavailable. Reconnecting safely…",
                        })
                        await websocket.close(code=1013, reason="Event deduplication unavailable")
                        return
                    if claim_status == "duplicate":
                        await send_ws_message({
                            "type": "event_ack",
                            "event_id": client_event.event_id,
                            "status": "duplicate",
                        })
                        continue
                    if claim_status == "out_of_order":
                        await send_ws_message({
                            "type": "error",
                            "code": "event_sequence_out_of_order",
                            "event_id": client_event.event_id,
                            "message": "The client event sequence is out of order.",
                        })
                        continue
                message = {
                    **client_event.payload,
                    "type": client_event.event_type,
                    "event_id": client_event.event_id,
                    "sequence": client_event.sequence,
                    "client_session_id": client_event.client_session_id,
                    "interview_id": client_event.interview_id or client_event.payload.get("interview_id"),
                    "sent_at": client_event.sent_at,
                }
                msg_type = client_event.event_type

                if msg_type == "question_ack":
                    ack_question_id = message.get("question_id")
                    state = question_ack_state.get(ack_question_id)
                    if ack_question_id and state:
                        state["acked"] = True
                        await update_question_delivery_metadata(
                            ack_question_id,
                            {
                                "delivery_ack": {
                                    "sequence": state.get("sequence"),
                                    "acked_at": datetime.now(timezone.utc).isoformat(),
                                    "client_delivery_id": message.get("delivery_id"),
                                }
                            },
                        )
                    continue

                if msg_type == "start_session":
                    interview_id = message.get("interview_id")

                    row, _ = await asyncio.to_thread(
                        _db_execute,
                        """
                        SELECT persona_data, questions_data, strictness_level, interview_mode, settings,
                               status, report_json, started_at, deadline_at, report_json_encrypted,
                               questions_data_encrypted
                        FROM Interviews
                        WHERE interview_id = ? AND user_id = ?
                        """,
                        (interview_id, user_id),
                        fetchone=True
                    )

                    if not row:
                        await send_ws_message({
                            "type": "error",
                            "message": "Interview not found"
                        })
                        continue

                    current_status = str(row[5] or "").lower()
                    was_recovering = current_status == "recovering"
                    if current_status == "cancelled":
                        await send_ws_message({
                            "type": "error",
                            "message": "This interview was cancelled and cannot be resumed.",
                        })
                        await websocket.close(code=4009, reason="Interview cancelled")
                        return
                    if current_status not in LIVE_INTERVIEW_STATUSES:
                        await send_ws_message({
                            "type": "interview_already_finalized",
                            "status": current_status,
                            "report_ready": current_status in REPORT_READY_STATUSES and isinstance(
                                _decrypt_json_blob(row[9], None) or _json_load(row[6], None),
                                dict,
                            ),
                            "redirect_to": f"/interview/{interview_id}/report",
                            "message": "This interview has already ended.",
                        })
                        await websocket.close(code=1000, reason="Interview already ended")
                        return

                    if current_status == "recovering":
                        _cancel_interview_recovery(interview_id)
                        await async_execute(
                            """
                            UPDATE Interviews
                            SET status = 'in_progress',
                                attempt_status = 'active',
                                recovery_deadline_at = NULL,
                                lifecycle_revision = lifecycle_revision + 1,
                                settings = json_patch(
                                    json_remove(COALESCE(settings, '{}'), '$.recovery_deadline', '$.recovery_reason'),
                                    json_object(
                                        'reconnection_count',
                                        COALESCE(CAST(json_extract(settings, '$.reconnection_count') AS INTEGER), 0) + 1
                                    )
                                )
                            WHERE interview_id = ? AND user_id = ? AND status = 'recovering'
                            """,
                            (interview_id, user_id),
                        )
                        await async_execute(
                            """
                            INSERT INTO SelfReviewEvents (interview_id, user_id, event_type, payload)
                            VALUES (?, ?, 'connection_restored', '{}')
                            """,
                            (interview_id, user_id),
                        )
                        await persist_integrity_event("connection_restored", {}, source="server")
                        current_status = "in_progress"

                    if coordination_store is None:
                        await send_ws_message({
                            "type": "error",
                            "code": "controller_lease_unavailable",
                            "message": "The interview controller could not be secured. Please retry shortly.",
                        })
                        await websocket.close(code=1013, reason="Controller lease unavailable")
                        return
                    if not active_session_key:
                        try:
                            active_session_key = f"attempt-controller:{interview_id}"
                            acquired = acquire_controller_lease(coordination_store, active_session_key, ws_connection_id)
                            if not acquired:
                                await persist_integrity_event(
                                    "duplicate_controller_rejected",
                                    {"connection_id_hash": stable_hash(ws_connection_id, "connection")},
                                    source="server",
                                )
                                await send_ws_message({
                                    "type": "error",
                                    "code": "duplicate_controller_rejected",
                                    "message": "This interview is already open in another tab.",
                                })
                                await websocket.close(code=4010, reason="Duplicate interview session")
                                return
                            controller_lease_task = track_ws_task(renew_controller_loop())
                        except Exception:
                            active_session_key = None
                            logger.warning("Local active interview lock failed; rejecting unsafe session binding")
                            await send_ws_message({
                                "type": "error",
                                "code": "controller_lease_unavailable",
                                "message": "The interview controller could not be secured. Please retry shortly.",
                            })
                            await websocket.close(code=1013, reason="Controller lease unavailable")
                            return
                    session_bound = True

                    persona = row[0] if isinstance(row[0], dict) else json.loads(row[0])
                    knowledge_map = decrypt_json_field(row[10], row[1], {})
                    if not isinstance(knowledge_map, dict):
                        raise RuntimeError("The encrypted interview question plan is invalid")
                    interview_mode = row[3]
                    ws_settings = row[4] if isinstance(row[4], dict) else json.loads(row[4]) if row[4] else {}
                    opening_intro_delivered = bool(ws_settings.get("opening_intro_delivered"))
                    session_started_at = (
                        _coerce_blueprint_datetime(row[7])
                        if row[7]
                        else datetime.now(timezone.utc)
                    )
                    activated_raw = ws_settings.get("interview_activated_at")
                    session_activated_at = (
                        _coerce_blueprint_datetime(activated_raw)
                        if activated_raw else None
                    )
                    session_deadline_at = (
                        session_activated_at + timedelta(
                            seconds=configured_duration_seconds("max_minutes", 60)
                        )
                        if session_activated_at else None
                    )
                    ws_settings = {
                        **ws_settings,
                        "interview_type": ws_settings.get("interview_type") or "mock",
                        "started_at": session_started_at.isoformat(),
                        "interview_activated_at": session_activated_at.isoformat() if session_activated_at else None,
                        "deadline_at": session_deadline_at.isoformat() if session_deadline_at else None,
                    }
                    try:
                        quality_failure_streak = max(
                            0,
                            int(ws_settings.get("answer_quality_failure_streak") or 0),
                        )
                    except (TypeError, ValueError):
                        quality_failure_streak = 0
                    persisted_question_ids.clear()
                    current_question_id = None

                    snapshot_row = await async_execute(
                        """
                        SELECT resume_payload_encrypted
                        FROM AttemptContextSnapshots
                        WHERE interview_id = ? AND user_id = ?
                        """,
                        (interview_id, user_id),
                        fetchone=True,
                    )
                    resume_row = None
                    if not snapshot_row:
                        resume_row, _ = await asyncio.to_thread(
                            _db_execute,
                            "SELECT resume_json, profile_json FROM UserInfo WHERE user_id = ?",
                            (user_id,),
                            fetchone=True
                        )
                    profile_for_opening: Dict[str, Any] = {}
                    external_signals: Dict[str, Any] = {}
                    if snapshot_row:
                        frozen_resume = _decrypt_json_blob(snapshot_row[0], {})
                        rj = frozen_resume if isinstance(frozen_resume, dict) else {}
                        pj: Dict[str, Any] = {}
                        profile_for_opening = rj
                        report_profile_context = _profile_context_from_rows(rj, pj, external_signals)
                        parts = []
                        if rj.get("summary"):
                            parts.append(f"Summary: {rj.get('summary', '')}")
                        if rj.get("target_role"):
                            parts.append(f"Target Role: {rj.get('target_role', '')}")
                        skills = rj.get("skills", [])
                        if skills:
                            skill_names = [s.get("name", s) if isinstance(s, dict) else str(s) for s in skills[:15]]
                            parts.append(f"Skills: {', '.join(skill_names)}")
                        for exp in (rj.get("experience", []) or rj.get("experiences", []))[:3]:
                            if isinstance(exp, dict):
                                parts.append(f"Experience: {exp.get('title') or exp.get('position') or ''} at {exp.get('company', '')} - {str(exp.get('description') or '')[:150]}")
                        for proj in (rj.get("projects", []) or [])[:3]:
                            if isinstance(proj, dict):
                                parts.append(f"Project: {proj.get('name', '')} - {str(proj.get('description') or '')[:150]}")
                        resume_context = redact_pii_text(
                            "\n".join(parts),
                            extra_values=collect_profile_identifiers(rj),
                        )[:4000]
                    elif resume_row:
                        rj = _json_load(resume_row[0], {})
                        pj = _json_load(resume_row[1], {})
                        profile_for_opening = rj or pj
                        report_profile_context = _profile_context_from_rows(rj, pj, external_signals)
                        parts = []
                        if rj.get("summary") or pj.get("professionalSummary"):
                            parts.append(f"Summary: {rj.get('summary') or pj.get('professionalSummary', '')}")
                        if rj.get("target_role") or pj.get("targetRole"):
                            parts.append(f"Target Role: {rj.get('target_role') or pj.get('targetRole', '')}")
                        skills = rj.get("skills", []) or pj.get("skills", [])
                        if skills:
                            skill_names = [s.get("name", s) if isinstance(s, dict) else str(s) for s in skills[:15]]
                            parts.append(f"Skills: {', '.join(skill_names)}")
                        exps = rj.get("experience", []) or rj.get("experiences", []) or pj.get("experience", []) or pj.get("experiences", [])
                        for exp in exps[:3]:
                            if isinstance(exp, dict):
                                title = exp.get("title") or exp.get("position") or ""
                                parts.append(f"Experience: {title} at {exp.get('company', '')} - {exp.get('description', '')[:150]}")
                        projs = rj.get("projects", []) or pj.get("projects", [])
                        for proj in projs[:3]:
                            if isinstance(proj, dict):
                                parts.append(f"Project: {proj.get('name', '')} - {proj.get('description', '')[:150]}")
                        resume_context = redact_pii_text(
                            "\n".join(parts),
                            extra_values=collect_profile_identifiers(rj or {}, pj or {}),
                        )

                    opening_profile = {
                        **profile_for_opening,
                        "target_role": ws_settings.get("job_title") or profile_for_opening.get("target_role"),
                    }
                    opening_script = _build_opening_script(persona, opening_profile)
                    opening_text = opening_script["intro_question"]
                    opening_intro_text = (
                        opening_script["greeting"]
                        if not opening_intro_delivered
                        else None
                    )

                    current_battleground = get_next_battleground(knowledge_map)
                    if not current_battleground:
                        await send_ws_message({
                            "type": "error",
                            "message": "No questions available for this interview"
                        })
                        continue

                    existing_questions, _ = await asyncio.to_thread(
                        _db_execute,
                        """
                        WITH latest_responses AS (
                            SELECT candidate_response.*,
                                   ROW_NUMBER() OVER (
                                       PARTITION BY candidate_response.question_id
                                       ORDER BY candidate_response.created_at DESC
                                   ) AS response_rank
                            FROM InterviewResponses candidate_response
                            WHERE candidate_response.interview_id = ?
                        ), latest_assessments AS (
                            SELECT assessment_json_encrypted, assessment_json, response_id,
                                   ROW_NUMBER() OVER (
                                       PARTITION BY response_id
                                       ORDER BY created_at DESC
                                   ) AS assessment_rank
                            FROM ResponseAssessments
                        )
                        SELECT iq.question_id, iq.question_text, iq.question_type,
                               iq.parent_question_id, iq.topic_label,
                               iq.blueprint_section_id, iq.question_order, iq.created_at,
                               ir.response_id, ir.answer_text_encrypted, ir.user_response,
                               ir.idempotency_key, ir.input_mode, ir.timing_json,
                               COALESCE(ra.assessment_json_encrypted, ra.assessment_json)
                        FROM InterviewQuestions iq
                        LEFT JOIN latest_responses ir
                          ON ir.question_id = iq.question_id AND ir.response_rank = 1
                        LEFT JOIN latest_assessments ra
                          ON ra.response_id = ir.response_id AND ra.assessment_rank = 1
                        WHERE iq.interview_id = ?
                        ORDER BY iq.question_order, iq.created_at, iq.question_id
                        """,
                        (interview_id, interview_id),
                        fetchall=True,
                    )

                    if existing_questions:
                        # Existing persisted questions are authoritative on a
                        # reconnect.  Mark the greeting as delivered without
                        # replaying it into an already-running transcript.
                        if not opening_intro_delivered:
                            opening_intro_delivered = True
                            ws_settings["opening_intro_delivered"] = True
                            ws_settings["opening_intro_version"] = "realistic-opening-v1"
                            await async_execute(
                                """
                                UPDATE Interviews
                                SET settings = json_patch(COALESCE(settings, '{}'), ?)
                                WHERE interview_id = ? AND user_id = ?
                                """,
                                (
                                    json.dumps({
                                        "opening_intro_delivered": True,
                                        "opening_intro_version": "realistic-opening-v1",
                                    }),
                                    interview_id,
                                    user_id,
                                ),
                            )
                        conversation_history.clear()
                        persisted_question_ids.clear()
                        resumable_row = None
                        pending_assessment = None
                        for existing in existing_questions:
                            persisted_question_ids.add(str(existing[0]))
                            conversation_history.append({
                                "role": "interviewer",
                                "content": str(existing[1] or ""),
                                "type": str(existing[2] or "main"),
                            })
                            encrypted_answer = existing[9]
                            if isinstance(encrypted_answer, memoryview):
                                encrypted_answer = encrypted_answer.tobytes()
                            if isinstance(encrypted_answer, (bytes, bytearray)):
                                encrypted_answer = bytes(encrypted_answer).decode("utf-8", errors="strict")
                            answer_text = decrypt_data(encrypted_answer) if encrypted_answer else ""
                            if not answer_text and existing[10] != "[encrypted]":
                                answer_text = str(existing[10] or "")
                            if existing[8] is None:
                                resumable_row = existing
                            elif existing[14] is None:
                                resumable_row = existing
                                pending_assessment = {
                                    "answer": answer_text,
                                    "idempotency_key": existing[11],
                                    "input_mode": existing[12] or "voice",
                                    "timing": _json_load(existing[13], {}),
                                }
                            elif answer_text:
                                conversation_history.append({
                                    "role": "candidate",
                                    "content": answer_text,
                                    "question_id": str(existing[0]),
                                })

                        resumable_row = resumable_row or existing_questions[-1]
                        current_question_id = str(resumable_row[0])
                        current_question_text = str(resumable_row[1] or "")
                        current_question_type = str(resumable_row[2] or "main")
                        current_parent_question_id = (
                            str(resumable_row[3]) if resumable_row[3] else None
                        )
                        warmup_pending = current_question_type == "warmup"
                        section_id = str(resumable_row[5] or "")
                        current_battleground = next(
                            (
                                battleground
                                for battleground in knowledge_map.get("battlegrounds", [])
                                if str(battleground.get("section_id") or "") == section_id
                            ),
                            get_next_battleground(knowledge_map),
                        )
                        if not current_battleground:
                            await complete_interview(include_closing_audio=False, force=True, reason="recovery_finalize")
                            continue
                        question_start_time = (
                            _coerce_blueprint_datetime(resumable_row[7])
                            if resumable_row[7]
                            else datetime.now(timezone.utc)
                        )
                        await send_ws_message({
                            "type": "session_started",
                            "mode": interview_mode,
                            "resumed": True,
                            "recovered_connection": was_recovering,
                            "question_id": current_question_id,
                            "question_type": current_question_type,
                            "opening_intro_text": None,
                            "opening_intro_id": f"opening-intro:{interview_id}",
                            "opening_text": current_question_text,
                            "opening_audio": None,
                            "audio_pending": False,
                            "current_question": current_question_text,
                            "current_topic": resumable_row[4] or current_battleground.get("label") or "Interview",
                            "progress": "Attempt restored",
                            "total_topics": len(knowledge_map.get("battlegrounds", [])),
                            "settings": ws_settings,
                            "persona": persona,
                        })
                        if pending_assessment and pending_assessment["answer"]:
                            track_ws_task(process_candidate_response(
                                pending_assessment["answer"],
                                idempotency_key=pending_assessment["idempotency_key"],
                                client_question_id=current_question_id,
                                input_mode=pending_assessment["input_mode"],
                                timing=pending_assessment["timing"],
                            ))
                        elif resumable_row[8] is not None and resumable_row[14] is not None:
                            assessment = _json_load(resumable_row[14], {})
                            if not assessment.get("next_question"):
                                track_ws_task(complete_interview(
                                    include_closing_audio=False,
                                    force=True,
                                    reason="recovery_finalize",
                                ))
                        continue

                    # The warm-up is a committed, context-only question too,
                    # so text/voice clients receive its stable id in the first
                    # frame.  The greeting state is persisted before delivery
                    # so reconnects cannot duplicate it.
                    warmup_pending = True
                    current_question_id = str(uuid.uuid4())
                    current_question_text = opening_text
                    current_question_type = "warmup"
                    question_start_time = datetime.now(timezone.utc)
                    await persist_asked_question(
                        question_id=current_question_id,
                        question_text=opening_text,
                        question_type="warmup",
                        battleground={
                            "section_id": "warmup",
                            "label": "Warm-up",
                            "kind": "behavioral",
                            "taxonomy_keys": ["behavioral:introduction"],
                            "expected_points": ["personal ownership", "role relevance"],
                            "rubric": {
                                "version": "warmup_v1",
                                "weights": {"relevance": 0.5, "communication": 0.5},
                                "unknown_dimensions_are_null": True,
                            },
                            "selection_reason": "Session introduction",
                            "estimated_difficulty": "easy",
                        },
                        generation_metadata={"warmup": True, "source": "deterministic"},
                    )

                    if opening_intro_text:
                        opening_intro_delivered = True
                        ws_settings["opening_intro_delivered"] = True
                        ws_settings["opening_intro_version"] = "realistic-opening-v1"
                        await async_execute(
                            """
                            UPDATE Interviews
                            SET settings = json_patch(COALESCE(settings, '{}'), ?)
                            WHERE interview_id = ? AND user_id = ?
                            """,
                            (
                                json.dumps({
                                    "opening_intro_delivered": True,
                                    "opening_intro_version": "realistic-opening-v1",
                                }),
                                interview_id,
                                user_id,
                            ),
                        )

                    await send_ws_message({
                        "type": "session_started",
                        "mode": interview_mode,
                        "question_id": current_question_id,
                        "question_type": current_question_type,
                        "opening_intro_text": opening_intro_text,
                        "opening_intro_id": f"opening-intro:{interview_id}",
                        "opening_text": opening_text,
                        "opening_audio": None,
                        "audio_pending": False,
                        "current_question": opening_text,
                        "current_topic": "Warm-up",
                        "progress": "Warm-up",
                        "total_topics": len(knowledge_map.get("battlegrounds", [])),
                        "settings": ws_settings,
                        "persona": persona
                    })
                    conversation_history.append({
                        "role": "interviewer",
                        "scoring_excluded": True,
                        "content": opening_text,
                        "type": "opening",
                    })

                elif msg_type == "init_pipeline":
                    await persist_integrity_event("camera_started", {}, source="server")
                    if str(message.get("input_mode") or "voice") == "voice":
                        await persist_integrity_event("microphone_started", {}, source="server")
                    if session_activated_at is None:
                        session_activated_at = datetime.now(timezone.utc)
                        session_started_at = session_activated_at
                        session_deadline_at = session_activated_at + timedelta(
                            seconds=configured_duration_seconds("max_minutes", 60)
                        )
                        ws_settings["interview_activated_at"] = session_activated_at.isoformat()
                        ws_settings["started_at"] = session_activated_at.isoformat()
                        ws_settings["deadline_at"] = session_deadline_at.isoformat()
                        await async_execute(
                            """
                            UPDATE Interviews
                            SET started_at = ?,
                                deadline_at = ?,
                                settings = json_patch(
                                    COALESCE(settings, '{}'),
                                    json_object(
                                        'interview_activated_at', ?,
                                        'started_at', ?,
                                        'deadline_at', ?
                                    )
                                )
                            WHERE interview_id = ? AND user_id = ?
                              AND status IN ('in_progress', 'recovering')
                            """,
                            (
                                session_activated_at,
                                session_deadline_at,
                                session_activated_at.isoformat(),
                                session_activated_at.isoformat(),
                                session_deadline_at.isoformat(),
                                interview_id,
                                user_id,
                            ),
                        )
                    pipeline_initialized = True
                    await send_ws_message({
                        "type": "pipeline_ready",
                        "pipeline_mode": "legacy",
                        "stt_connected": has_provider_api_key("openai"),
                        "tts_connected": False,
                        "avatar_connected": False,
                        "avatar_session": None,
                        "activated_at": session_activated_at.isoformat(),
                        "deadline_at": session_deadline_at.isoformat(),
                    })

                elif msg_type in {"audio_stream", "vad_speech_start", "vad_speech_end", "interrupt", "avatar_sdp_answer", "avatar_ice"}:
                    continue

                elif msg_type == "audio_chunk":
                    if not pipeline_initialized:
                        await send_ws_message({
                            "type": "error",
                            "code": "media_not_ready",
                            "message": "Complete the camera and microphone readiness check before answering.",
                        })
                        await send_processing_idle()
                        continue
                    audio_data = message.get("audio")
                    if not audio_data:
                        await send_ws_message({
                            "type": "error",
                            "message": "Audio chunk missing"
                        })
                        await send_processing_idle()
                        continue

                    mime_type = message.get("mime_type")
                    logger.info(
                        "Interview audio received interview=%s mime=%s duration_ms=%s",
                        stable_hash(interview_id or "", "interview"),
                        str(mime_type or "audio/webm")[:80],
                        message.get("duration_ms"),
                    )
                    timing = message.get("timing") if isinstance(message.get("timing"), dict) else {}
                    duration_values = []
                    for raw_duration in (
                        message.get("duration_ms"),
                        float(timing.get("voiced_duration_seconds")) * 1000
                        if isinstance(timing.get("voiced_duration_seconds"), (int, float))
                        else None,
                    ):
                        try:
                            parsed_duration = float(raw_duration)
                        except (TypeError, ValueError):
                            continue
                        if math.isfinite(parsed_duration) and parsed_duration > 0:
                            duration_values.append(parsed_duration)
                    if any(duration < MIN_LIVE_AUDIO_DURATION_MS for duration in duration_values):
                        await register_live_quality_failure(
                            "audio_too_short",
                            "I need a complete answer. Please finish your thought and answer the question directly.",
                        )
                        await send_processing_idle()
                        continue
                    transcribed_text = await transcribe_audio(audio_data, mime_type=mime_type)
                    if not transcribed_text or not _is_usable_live_answer(transcribed_text):
                        await register_live_quality_failure(
                            "transcription_too_short",
                            "I couldn't hear a complete answer. Please finish your thought and answer the question directly.",
                        )
                        await send_processing_idle()
                        continue

                    await send_ws_message({
                        "type": "transcription_final",
                        "role": "user",
                        "text": transcribed_text,
                    })
                    await process_candidate_response(
                        transcribed_text,
                        idempotency_key=message.get("idempotency_key"),
                        client_question_id=message.get("question_id"),
                        input_mode="voice",
                        timing=message.get("timing"),
                    )

                elif msg_type == "text_answer":
                    await send_ws_message({
                        "type": "error",
                        "message": "This Interview Round accepts microphone responses only.",
                    })

                elif msg_type == "video_frame":
                    continue

                elif msg_type == "body_language_metrics":
                    if not interview_id:
                        continue
                    analysis = normalize_client_metrics(
                        message.get("metrics") or {},
                        interview_mode or "mock",
                    )
                    nonverbal_data.append(analysis)
                    await asyncio.to_thread(
                        _db_execute,
                        """
                        INSERT INTO ClientBodyLanguageMetrics (interview_id, user_id, payload)
                        VALUES (?, ?, ?)
                        """,
                        (interview_id, user_id, json.dumps(analysis)),
                        commit=True,
                    )
                    await send_ws_message({
                        "type": "body_language",
                        "confidence_score": analysis.get("confidence", 0),
                        "emotion": analysis.get("emotion", "not_tracked"),
                        "eye_contact": analysis.get("eye_contact", False),
                        "posture": analysis.get("posture", "unknown"),
                        "analysis_method": analysis.get("analysis_method"),
                    })

                elif msg_type == "self_review_signal":
                    if not interview_id:
                        continue
                    event_type = canonical_integrity_event(message.get("event_type"))
                    payload = message.get("payload") or {}
                    await persist_integrity_event(
                        event_type,
                        payload,
                        event_id=client_event.event_id,
                        client_session_id=client_event.client_session_id,
                        sequence=client_event.sequence,
                        sent_at=client_event.sent_at,
                    )
                    await asyncio.to_thread(
                        _db_execute,
                        """
                        INSERT INTO SelfReviewEvents (interview_id, user_id, event_type, payload)
                        VALUES (?, ?, ?, ?)
                        """,
                        (
                            interview_id,
                            user_id,
                            event_type,
                            json.dumps(payload),
                        ),
                        commit=True,
                    )
                    if client_event.event_id:
                        await send_ws_message({
                            "type": "event_ack",
                            "event_id": client_event.event_id,
                            "status": "committed",
                        })
                elif msg_type == "response_complete":
                    await process_candidate_response(
                        message.get("response", ""),
                        idempotency_key=message.get("idempotency_key"),
                        client_question_id=message.get("question_id"),
                        input_mode=str(message.get("input_mode") or "voice"),
                        timing=message.get("timing"),
                    )

                elif msg_type == "end_interview":
                    metrics = {}

                    await send_ws_message({
                        "type": "interview_ending",
                        "message": "Analyzing Interview...",
                        "pipeline_metrics": metrics,
                    })
                    await complete_interview(
                        include_closing_audio=False,
                        force=True,
                        reason="client_end",
                    )

                elif msg_type == "ping":
                    await send_ws_message({
                        "type": "pong",
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    })

            except WebSocketDisconnect:
                raise
            except json.JSONDecodeError:
                await send_ws_message({
                    "type": "error",
                    "message": "Invalid message format"
                })
            except WSContractError as exc:
                await send_ws_message({
                    "type": "error",
                    "code": exc.code,
                    "message": str(exc),
                })
            except Exception as e:
                logger.error("Error processing WebSocket message: %s", redact_text(e), exc_info=True)
                await send_ws_message({
                    "type": "error",
                    "message": "An error occurred processing your request"
                })

    except WebSocketDisconnect:
        logger.info("Video WebSocket disconnected: %s", stable_hash(user_id, "user"))
    except Exception as e:
        logger.error("WebSocket error: %s", redact_text(e))
    finally:
        ws_closing = True
        for task in list(background_tasks):
            task.cancel()
        if background_tasks:
            await asyncio.gather(*background_tasks, return_exceptions=True)
        if coordination_store and active_session_key:
            try:
                release_controller_lease(coordination_store, active_session_key, ws_connection_id)
            except Exception:
                pass
        if session_bound and interview_id and user_id and not completion_sent:
            try:
                await _mark_interview_recovering(interview_id, user_id)
                _schedule_interview_recovery(interview_id, user_id)
            except Exception:
                logger.warning("Failed to schedule interview recovery", exc_info=True)
        try:
            await websocket.close()
        except Exception:
            pass

@router.post("/{interview_id}/media/upload-url")
async def create_media_upload_url(
    interview_id: str,
    request: MediaUploadUrlRequest,
    current_user: Dict = Depends(local_user),
):
    interview = await async_execute(
        "SELECT 1 FROM Interviews WHERE interview_id = ? AND user_id = ?",
        (interview_id, current_user["user_id"]),
        fetchone=True,
    )
    if not interview:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Interview not found")

    asset_id = str(uuid.uuid4())
    safe_kind = _require_raw_media_retention(request.media_kind)
    safe_content_type = _validated_media_content_type(safe_kind, request.content_type)
    chunk = request.chunk_index if request.chunk_index is not None else 0
    object_key = f"interviews/{current_user['user_id']}/{interview_id}/{safe_kind}/{asset_id}-{chunk}.webm"
    await async_execute(
        """
        INSERT INTO InterviewMediaAssets (
            asset_id, interview_id, user_id, media_kind, object_key, content_type,
            byte_size, chunk_index, chunk_count, metadata, status
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')
        """,
        (
            asset_id,
            interview_id,
            current_user["user_id"],
            safe_kind,
            object_key,
            safe_content_type,
            request.byte_size or 0,
            request.chunk_index,
            request.chunk_count,
            json.dumps({"upload_provider": settings.MEDIA_UPLOAD_PROVIDER}),
        ),
    )
    return {
        "asset_id": asset_id,
        "object_key": object_key,
        "upload_url": f"{settings.API_BASE_URL.rstrip('/')}/interview/{interview_id}/media/chunk-complete",
        "method": "POST",
        "storage_provider": settings.MEDIA_UPLOAD_PROVIDER,
        "fields": {"asset_id": asset_id, "object_key": object_key},
    }


@router.post("/{interview_id}/media/chunk-complete")
async def complete_media_chunk(
    interview_id: str,
    request: MediaChunkCompleteRequest,
    current_user: Dict = Depends(local_user),
):
    safe_kind = _require_raw_media_retention(request.media_kind)
    safe_content_type = _validated_media_content_type(safe_kind, request.content_type)
    interview = await async_execute(
        "SELECT 1 FROM Interviews WHERE interview_id = ? AND user_id = ?",
        (interview_id, current_user["user_id"]),
        fetchone=True,
    )
    if not interview:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Interview not found")

    updated = await async_execute(
        """
        UPDATE InterviewMediaAssets
        SET byte_size = ?, checksum = ?,
            metadata = json_patch(COALESCE(metadata, '{}'), ?),
            status = 'completed', completed_at = CURRENT_TIMESTAMP
        WHERE asset_id = ? AND interview_id = ? AND user_id = ?
          AND status = 'pending'
          AND media_kind = ?
          AND object_key = ?
          AND content_type = ?
          AND (byte_size = 0 OR byte_size = ?)
          AND chunk_index IS ?
          AND chunk_count IS ?
        RETURNING asset_id
        """,
        (
            request.byte_size,
            request.checksum,
            json.dumps({"browser_recorded": bool((request.metadata or {}).get("browser_recorded"))}),
            request.asset_id,
            interview_id,
            current_user["user_id"],
            safe_kind,
            request.object_key,
            safe_content_type,
            request.byte_size,
            request.chunk_index,
            request.chunk_count,
        ),
        fetchone=True,
    )
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Media completion did not match a server-issued pending asset.",
        )
    return {"success": True, "asset_id": request.asset_id}


@router.post("/{interview_id}/end")
async def end_interview_session(
    interview_id: str,
    current_user: Dict = Depends(local_user),
):
    if not await _has_persisted_candidate_evidence(interview_id, current_user["user_id"]):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No candidate response or technical work has been captured for this attempt.",
        )
    finalization = await _finalize_interview_for_analysis(
        interview_id=interview_id,
        user_id=current_user["user_id"],
        reason="rest_end",
    )
    if finalization.get("cancelled"):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Interview is cancelled")
    return {
        "interview_id": interview_id,
        "status": finalization.get("status") or "analysis_pending",
        "analysis_job_id": finalization.get("analysis_job_id"),
        "report_ready": bool(finalization.get("report_ready")),
        "pending_execution": bool(finalization.get("pending_execution")),
        "pending_execution_count": int(finalization.get("pending_execution_count") or 0),
    }


@router.get("/{interview_id}/analysis-status")
async def get_analysis_status(
    interview_id: str,
    current_user: Dict = Depends(local_user),
):
    row = await async_execute(
        """
        WITH latest_jobs AS (
            SELECT job_id, interview_id, status, current_stage, progress,
                   error_message, updated_at, retry_count, manual_retry_count,
                   ROW_NUMBER() OVER (
                       PARTITION BY interview_id
                       ORDER BY created_at DESC
                   ) AS job_rank
            FROM AnalysisJobs
        )
        SELECT i.status, i.overall_score, i.completed_at, i.report_json,
               aj.job_id, aj.status, aj.current_stage, aj.progress, aj.error_message, aj.updated_at,
               aj.retry_count, i.report_json_encrypted, i.analysis_status,
               aj.manual_retry_count, i.attempt_status, i.settings
        FROM Interviews i
        LEFT JOIN latest_jobs aj
          ON aj.interview_id = i.interview_id AND aj.job_rank = 1
        WHERE i.interview_id = ? AND i.user_id = ?
        """,
        (interview_id, current_user["user_id"]),
        fetchone=True,
    )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Interview not found")
    current_status = row[0]
    stored_report = _decrypt_json_blob(row[11], None) or _json_load(row[3], None)
    canonical_ready = await _has_current_canonical_analysis(interview_id, current_user["user_id"])
    retry_count = int(row[10] or 0) if row[10] is not None else 0
    should_have_job = (
        (current_status in ANALYSIS_ACTIVE_STATUSES and retry_count < 3)
        or (
            current_status in REPORT_READY_STATUSES
            and (not isinstance(stored_report, dict) or not canonical_ready)
            and retry_count < 3
        )
    )
    if should_have_job:
        job_id = await enqueue_analysis(
            interview_id,
            current_user["user_id"],
            "status_poll",
            force_canonical_rebuild=not canonical_ready,
        )
        if job_id:
            await async_execute(
                """
                UPDATE Interviews
                SET analysis_job_id = ?,
                    status = CASE
                        WHEN status IN ('completed', 'report_ready', 'partial', 'failed')
                             AND report_json IS NULL AND report_json_encrypted IS NULL
                        THEN 'analysis_pending'
                        ELSE status
                    END
                WHERE interview_id = ?
                  AND user_id = ?
                  AND status IN ('analysis_pending', 'analysis_running', 'completed', 'report_ready', 'partial', 'failed')
                """,
                (job_id, interview_id, current_user["user_id"]),
            )
        row = await async_execute(
            """
            WITH latest_jobs AS (
                SELECT job_id, interview_id, status, current_stage, progress,
                       error_message, updated_at, retry_count, manual_retry_count,
                       ROW_NUMBER() OVER (
                           PARTITION BY interview_id
                           ORDER BY created_at DESC
                       ) AS job_rank
                FROM AnalysisJobs
            )
            SELECT i.status, i.overall_score, i.completed_at, i.report_json,
                   aj.job_id, aj.status, aj.current_stage, aj.progress, aj.error_message, aj.updated_at,
                   aj.retry_count, i.report_json_encrypted, i.analysis_status,
                   aj.manual_retry_count, i.attempt_status, i.settings
            FROM Interviews i
            LEFT JOIN latest_jobs aj
              ON aj.interview_id = i.interview_id AND aj.job_rank = 1
            WHERE i.interview_id = ? AND i.user_id = ?
            """,
            (interview_id, current_user["user_id"]),
            fetchone=True,
        )
    stored_report = _decrypt_json_blob(row[11], None) or _json_load(row[3], None)
    canonical_ready = await _has_current_canonical_analysis(interview_id, current_user["user_id"])
    manual_retry_count = int(row[13] or 0) if row[13] is not None else 0
    job_status = str(row[5] or "")
    settings_payload = _json_load(row[15], {})
    if not isinstance(settings_payload, dict):
        settings_payload = {}
    execution_pending = bool(settings_payload.get("technical_finalize_requested")) and str(row[0] or "").lower() in {
        "in_progress",
        "uploading",
    }
    public_status = "execution_pending" if execution_pending else row[0]
    report_ready = row[0] in REPORT_READY_STATUSES and isinstance(stored_report, dict) and canonical_ready
    report_state = _analysis_report_state(
        interview_status=public_status,
        attempt_status=row[14],
        report_ready=report_ready,
        stored_report=stored_report,
        job_status=job_status,
        manual_retry_count=manual_retry_count,
    )
    return {
        "interview_id": interview_id,
        "status": public_status,
        "overall_score": float(row[1]) if row[1] is not None else None,
        "completed_at": row[2].isoformat() if row[2] else None,
        "report_ready": report_ready,
        "report_state": report_state,
        "analysis_status": row[12],
        "attempt_status": row[14],
        "execution_pending": execution_pending,
        "processing_sla_minutes": 60,
        "retry_in_progress": report_state == "retrying",
        "retryable": job_status == "failed" and manual_retry_count < 3,
        "job": {
            "job_id": row[4],
            "status": row[5],
            "current_stage": row[6],
            "progress": row[7] or 0,
            # Detailed worker exceptions stay in server logs/storage. They can
            # contain provider, database, or infrastructure details and must
            # never be rendered directly to the candidate.
            "error_message": (
                "Report analysis failed. Your recorded evidence is safe; retry the report when available."
                if job_status == "failed"
                else None
            ),
            "error_code": "analysis_failed" if job_status == "failed" else None,
            "updated_at": row[9].isoformat() if row[9] else None,
            "retry_count": row[10] or 0,
            "manual_retry_count": manual_retry_count,
        } if row[4] else None,
    }


@router.post("/{interview_id}/analysis/retry", status_code=status.HTTP_202_ACCEPTED)
async def retry_failed_analysis(
    interview_id: str,
    current_user: Dict = Depends(local_user),
):
    owned = await async_execute(
        "SELECT 1 FROM Interviews WHERE interview_id = ? AND user_id = ?",
        (interview_id, current_user["user_id"]),
        fetchone=True,
    )
    if not owned:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Interview not found")
    try:
        return await operator_retry_analysis(interview_id, current_user["user_id"])
    except ValueError as exc:
        code = str(exc)
        status_code = (
            status.HTTP_429_TOO_MANY_REQUESTS
            if code == "manual_retry_limit_reached"
            else status.HTTP_409_CONFLICT
        )
        raise HTTPException(status_code=status_code, detail=code.replace("_", " ").capitalize()) from None


@router.get("/status/{interview_id}")
async def get_interview_status(
    interview_id: str,
    current_user: Dict = Depends(local_user)
):
    connection = get_db_connection()
    cursor = connection.cursor()

    try:
        cursor.execute(
            """
            SELECT status, overall_score, completed_at, analysis_job_id,
                   attempt_status, analysis_status, integrity_status,
                   started_at, deadline_at, recovery_deadline_at, lifecycle_revision
            FROM Interviews
            WHERE interview_id = ? AND user_id = ?
            """,
            (interview_id, current_user["user_id"])
        )

        row = cursor.fetchone()
        if not row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Interview not found"
            )

        return {
            "interview_id": interview_id,
            "status": row[0],
            "overall_score": float(row[1]) if row[1] is not None else None,
            "completed_at": row[2].isoformat() if row[2] else None,
            "analysis_job_id": row[3],
            "attempt_status": row[4],
            "analysis_status": row[5],
            "integrity_status": row[6],
            "started_at": row[7].isoformat() if row[7] else None,
            "deadline_at": row[8].isoformat() if row[8] else None,
            "recovery_deadline": row[9].isoformat() if row[9] else None,
            "lifecycle_revision": int(row[10] or 1),
            "server_time": datetime.now(timezone.utc).isoformat(),
            "read_only": row[4] in {"completed", "incomplete"},
            "next_action": (
                "view_report" if row[5] == "ready" else
                "wait_for_report" if row[4] == "completed" else
                "return_to_dashboard" if row[4] == "incomplete" else
                "reconnect" if row[4] == "recovering" else "continue_attempt"
            ),
        }
    finally:
        cursor.close()
        return_db_connection(connection)

def _report_job_target(
    cursor: Any,
    *,
    interview_id: str,
    user_id: str,
    job_profile_id: Optional[int],
    settings_value: Any,
) -> Optional[Dict[str, Any]]:
    """Load the immutable role/JD used by a report and its reusable-save state."""
    cursor.execute(
        """
        SELECT profile_type, job_context_encrypted
        FROM AttemptContextSnapshots
        WHERE interview_id = ? AND user_id = ?
        LIMIT 1
        """,
        (interview_id, user_id),
    )
    snapshot_row = cursor.fetchone()
    snapshot_profile_type = snapshot_row[0] if snapshot_row and len(snapshot_row) > 1 else None
    snapshot_payload = snapshot_row[1] if snapshot_row and len(snapshot_row) > 1 else (snapshot_row[0] if snapshot_row else None)
    snapshot = _decrypt_json_blob(snapshot_payload, {}) if snapshot_payload else {}
    if not isinstance(snapshot, dict):
        snapshot = {}

    settings_payload = _json_load(settings_value, {})
    if not isinstance(settings_payload, dict):
        settings_payload = {}
    compact_context = settings_payload.get("job_context")
    if not isinstance(compact_context, dict):
        compact_context = {}

    raw_profile_type = snapshot_profile_type or compact_context.get("profile_type") or settings_payload.get("profile_type")
    profile_type = normalize_profile_type(str(raw_profile_type or DEFAULT_PROFILE_TYPE))
    legacy_saved_target = bool(
        not raw_profile_type
        and (
            job_profile_id
            or snapshot.get("job_profile_id")
            or str(settings_payload.get("job_context_source") or "").strip().lower() == "saved_profile"
            or str(compact_context.get("source") or "").strip().lower() == "saved_profile"
        )
    )
    is_custom = profile_type == "custom" or legacy_saved_target

    profile_row = None
    if job_profile_id:
        cursor.execute(
            """
            SELECT role, company, job_description_encrypted, job_description_hash
            FROM JobProfiles
            WHERE profile_id = ? AND user_id = ?
            """,
            (job_profile_id, user_id),
        )
        profile_row = cursor.fetchone()

    role = str(
        snapshot.get("role")
        or compact_context.get("role")
        or (profile_row[0] if profile_row else "")
        or settings_payload.get("job_title")
        or ""
    ).strip()
    company = str(
        snapshot.get("company")
        or compact_context.get("company")
        or (profile_row[1] if profile_row else "")
        or ""
    ).strip()
    job_description = str(snapshot.get("job_description") or "").strip()
    if not job_description:
        encrypted_description = settings_payload.get("job_description_encrypted")
        if encrypted_description:
            job_description = str(decrypt_data(str(encrypted_description)) or "").strip()
    if not job_description and profile_row:
        job_description = str(_decrypt_job_description_value(profile_row[2]) or "").strip()
    if not role:
        return None

    description_hash = (
        hashlib.sha256(job_description.encode("utf-8")).hexdigest()
        if job_description
        else (profile_row[3] if profile_row else None)
    )
    cursor.execute(
        """
        SELECT EXISTS (
            SELECT 1
            FROM JobProfiles reusable_profile
            WHERE reusable_profile.user_id = ?
              AND LOWER(trim(reusable_profile.role)) = LOWER(trim(?))
              AND LOWER(trim(COALESCE(reusable_profile.company, ''))) = LOWER(trim(?))
              AND reusable_profile.job_description_hash IS ?
        )
        """,
        (user_id, role, company, description_hash),
    )
    saved_row = cursor.fetchone()
    return {
        "profile_type": "custom" if is_custom else profile_type,
        "is_custom": is_custom,
        "role": role,
        "company": company or None,
        "job_description": job_description,
        "saved_for_reuse": bool(saved_row and saved_row[0]),
    }


def _decrypt_job_description_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, memoryview):
        value = value.tobytes()
    if isinstance(value, (bytes, bytearray)):
        value = bytes(value).decode("utf-8", errors="strict")
    return decrypt_data(str(value)) if value else ""


@router.get("/report/{interview_id}")
async def get_interview_report(
    interview_id: str,
    current_user: Dict = Depends(local_user)
):
    connection = get_db_connection()
    cursor = connection.cursor()

    try:
        cursor.execute(
            """
            SELECT interview_mode, interview_type, job_title, strictness_level,
                   overall_score, feedback_summary, report_json, created_at, completed_at,
                   status, report_json_encrypted, analysis_status, job_profile_id, settings,
                   duration_seconds, started_at, deadline_at
            FROM Interviews
            WHERE interview_id = ? AND user_id = ?
            """,
            (interview_id, current_user["user_id"])
        )

        row = cursor.fetchone()

        if not row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Interview not found"
            )

        turns = _load_report_payload(cursor, interview_id)
        detailed_responses = [
            {
                "response_id": turn.get("response_id"),
                "question_id": turn.get("question_id"),
                "question": turn.get("question", ""),
                "question_type": turn.get("question_type") or "main",
                "is_followup": bool(turn.get("is_followup")),
                "topic": turn.get("topic_label") or "General",
                "response": turn.get("response", ""),
                "score": turn.get("score"),
                "feedback": turn.get("feedback") or "",
                "time_taken": turn.get("time_taken"),
                "nonverbal_metrics": turn.get("nonverbal_metrics") or {},
                "coaching_hint": None,
                "evaluation_json": turn.get("evaluation_json") or {},
                "answer_quality_flags": turn.get("answer_quality_flags") or [],
                "evidence_quotes": turn.get("evidence_quotes") or [],
                "retry_state": turn.get("retry_state") or {},
                "assessment": turn.get("assessment"),
                "evaluator_version": turn.get("evaluator_version"),
                "insufficient_evidence": bool(turn.get("insufficient_evidence")),
                "status": _detailed_response_status(turn),
            }
            for turn in turns
        ]

        stored_report = _decrypt_json_blob(row[10], None) or row[6]
        if isinstance(stored_report, str):
            try:
                stored_report = json.loads(stored_report)
            except Exception:
                stored_report = None
        if isinstance(stored_report, dict):
            for question_key in ("questions", "per_turn_feedback"):
                questions = stored_report.get(question_key)
                if not isinstance(questions, list):
                    continue
                stored_report[question_key] = [
                    {
                        **question,
                        "status": _stored_report_question_status(question),
                    }
                    if isinstance(question, dict) else question
                    for question in questions
                ]

        canonical_ready = await _has_current_canonical_analysis(interview_id, current_user["user_id"])
        stale_report = isinstance(stored_report, dict) and not canonical_ready
        analysis_pending = row[9] in ANALYSIS_ACTIVE_STATUSES
        analysis_job_id = None
        if (
            (not isinstance(stored_report, dict) or stale_report)
            and row[9] not in {"in_progress", "cancelled", "failed"}
            and str(row[11] or "") != "failed"
        ):
            analysis_job_id = await enqueue_analysis(
                interview_id,
                current_user["user_id"],
                "report_poll",
                force_canonical_rebuild=stale_report,
            )
            if analysis_job_id:
                await async_execute(
                    """
                    UPDATE Interviews
                    SET analysis_job_id = ?,
                        status = CASE
                            WHEN status IN ('completed', 'partial') THEN 'analysis_pending'
                            ELSE status
                        END,
                        feedback_summary = COALESCE(feedback_summary, 'Interview complete. Async analysis is queued.')
                    WHERE interview_id = ? AND user_id = ?
                    """,
                    (analysis_job_id, interview_id, current_user["user_id"]),
                )
            analysis_pending = True
            stored_report = None

        job_target = _report_job_target(
            cursor,
            interview_id=interview_id,
            user_id=current_user["user_id"],
            job_profile_id=row[12],
            settings_value=row[13],
        )
        settings_payload = _json_load(row[13], {})
        if not isinstance(settings_payload, dict):
            settings_payload = {}
        duration_config = settings_payload.get("duration")
        if not isinstance(duration_config, dict):
            duration_config = {}
        technical_config = settings_payload.get("technical")
        if not isinstance(technical_config, dict):
            technical_config = {}
        duration_allowed_seconds = (
            technical_config.get("duration_seconds")
            or settings_payload.get("duration_allowed_seconds")
            or settings_payload.get("duration_seconds")
        )
        if duration_allowed_seconds is None:
            duration_minutes = duration_config.get("max_minutes") or duration_config.get("minutes") or settings_payload.get("duration_minutes")
            if isinstance(duration_minutes, (int, float)):
                duration_allowed_seconds = int(duration_minutes * 60)
        if duration_allowed_seconds is None and row[15] and row[16]:
            duration_allowed_seconds = max(0, int((row[16] - row[15]).total_seconds()))

        return {
            "interview_id": interview_id,
            "mode": row[0],
            "interview_type": row[1],
            "job_title": row[2],
            "strictness_level": row[3],
            "overall_score": float(row[4]) if row[4] is not None else None,
            "report": stored_report.get("summary") if isinstance(stored_report, dict) else row[5],
            "report_v2": stored_report,
            "created_at": row[7].isoformat() if row[7] else None,
            "completed_at": row[8].isoformat() if row[8] else None,
            "duration_seconds": int(row[14]) if row[14] is not None else None,
            "duration_allowed_seconds": int(duration_allowed_seconds) if duration_allowed_seconds is not None else None,
            "started_at": row[15].isoformat() if row[15] else None,
            "deadline_at": row[16].isoformat() if row[16] else None,
            "status": "analysis_pending" if analysis_pending and row[9] in {"completed", "partial", "uploading"} else row[9],
            "analysis_pending": analysis_pending,
            "analysis_job_id": analysis_job_id,
            "job_target": job_target,
            "detailed_responses": detailed_responses
        }

    finally:
        cursor.close()
        return_db_connection(connection)


@router.get("/report/{interview_id}/export")
async def export_interview_report_json(
    interview_id: str,
    current_user: Dict = Depends(local_user),
):
    """Export the candidate-safe official report and its linked evidence state."""
    connection = get_db_connection()
    cursor = connection.cursor()
    try:
        cursor.execute(
            """
            SELECT interview_mode, interview_type, job_title, status,
                   report_json, report_json_encrypted, created_at, completed_at
            FROM Interviews
            WHERE interview_id = ? AND user_id = ?
            """,
            (interview_id, current_user["user_id"]),
        )
        interview = cursor.fetchone()
        if not interview:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Interview not found")

        cursor.execute(
            """
            SELECT artifact_id, status, evidence_hash, provenance_json,
                   payload, created_at, published_at
            FROM ReportArtifacts
            WHERE interview_id = ? AND user_id = ? AND audience = 'candidate'
              AND status <> 'superseded'
            ORDER BY published_at DESC NULLS LAST, created_at DESC
            LIMIT 1
            """,
            (interview_id, current_user["user_id"]),
        )
        artifact = cursor.fetchone()

        cursor.execute(
            """
            SELECT analysis_id, mode, schema_version, evidence_hash,
                   status, is_current, producer_version, evidence_status,
                   overall_score, analysis_json, analysis_json_encrypted,
                   evidence_index_json, evidence_index_encrypted, created_at
            FROM SessionPerformanceAnalyses
            WHERE interview_id = ? AND user_id = ?
              AND schema_version = 'session-performance-v4'
              AND status = 'ready' AND is_current = TRUE
            ORDER BY revision_no DESC, created_at DESC
            LIMIT 1
            """,
            (interview_id, current_user["user_id"]),
        )
        canonical = cursor.fetchone()
        if not canonical or not artifact:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The official report is still being generated. Try again when the report is ready.",
            )

        stored_report = _decrypt_json_blob(interview[5], None) or _json_load(interview[4], None)
        if not isinstance(stored_report, dict) and artifact[4]:
            stored_report = _json_load(artifact[4], None)
        if not isinstance(stored_report, dict):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The official report is still being generated. Try again when the report is ready.",
            )

        canonical_projection = _decrypt_json_blob(canonical[10], None) or _json_load(canonical[9], {})
        if not isinstance(canonical_projection, dict):
            canonical_projection = {}
        evidence_index = _decrypt_json_blob(canonical[12], None) or _json_load(canonical[11], {})
        if not isinstance(evidence_index, dict):
            evidence_index = {}
        canonical_evidence_status = str(canonical[7] or "unknown")
        evidence_items: List[Dict[str, Any]] = []
        evidence_key_labels = {
            "response_ids": "response",
            "round_ids": "technical_round",
            "submission_ids": "technical_submission",
            "reasoning_evidence_ids": "reasoning",
            "run_ids": "technical_run",
            "snapshot_ids": "technical_draft",
        }
        seen_evidence = set()
        for key, kind in evidence_key_labels.items():
            values = evidence_index.get(key) or []
            if not isinstance(values, list):
                continue
            for value in values:
                identifier = str(value or "").strip()
                if not identifier or (kind, identifier) in seen_evidence:
                    continue
                seen_evidence.add((kind, identifier))
                evidence_items.append({
                    "kind": kind,
                    "id": identifier,
                    "status": canonical_evidence_status,
                })

        mission = None
        if canonical_evidence_status == "sufficient" and canonical[8] is not None:
            cursor.execute(
                """
                SELECT mission_id, mode, status, title, assignment_reason,
                       source_interview_id, source_analysis_id, validation_status,
                       progress_percent, current_readiness, target_readiness,
                       created_at, updated_at, completed_at
                FROM ImprovementMissions
                WHERE user_id = ? AND source_interview_id = ?
                  AND status IN ('active', 'completed')
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (current_user["user_id"], interview_id),
            )
            mission = cursor.fetchone()
        improve_pathway: Optional[Dict[str, Any]] = None
        if mission:
            cursor.execute(
                """
                SELECT roadmap_node_id, exercise_id, order_index, title,
                       activity_type, availability_status, attempt_status,
                       result_status, mastery_status, completed_at
                FROM ImprovementRoadmapNodes
                WHERE user_id = ? AND mission_id = ?
                ORDER BY order_index, roadmap_node_id
                """,
                (current_user["user_id"], mission[0]),
            )
            nodes = [
                {
                    "roadmap_node_id": row[0],
                    "exercise_id": row[1],
                    "order_index": int(row[2] or 0),
                    "title": row[3],
                    "activity_type": row[4],
                    "availability_status": row[5],
                    "attempt_status": row[6],
                    "result_status": row[7],
                    "mastery_status": row[8],
                    "completed_at": row[9].isoformat() if row[9] else None,
                }
                for row in cursor.fetchall() or []
            ]
            improve_pathway = {
                "mission_id": mission[0],
                "mode": mission[1],
                "status": mission[2],
                "title": mission[3],
                "assignment_reason": mission[4],
                "source_interview_id": mission[5],
                "source_analysis_id": mission[6],
                "validation_status": mission[7],
                "progress_percent": float(mission[8] or 0),
                "current_readiness": float(mission[9] or 0),
                "target_readiness": float(mission[10] or 0),
                "nodes": nodes,
            }

        safe_report = _safe_report_payload(stored_report)
        created_at = canonical[13]
        export_payload = {
            "schema_version": "prepmate-report-export-v1",
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "interview": {
                "interview_id": interview_id,
                "mode": interview[0],
                "interview_type": interview[1],
                "job_title": interview[2],
                "status": interview[3],
                "created_at": interview[6].isoformat() if interview[6] else None,
                "completed_at": interview[7].isoformat() if interview[7] else None,
            },
            "report": safe_report,
            "canonical_performance": {
                "analysis_id": canonical[0],
                "mode": canonical[1],
                "schema_version": canonical[2],
                "status": canonical[4],
                "is_current": bool(canonical[5]),
                "producer_version": canonical[6],
                "evidence_status": canonical[7],
                "overall_score": float(canonical[8]) if canonical[8] is not None else None,
                "evidence_hash": canonical[3],
                "created_at": created_at.isoformat() if created_at else None,
                "projection": canonical_projection,
            },
            "evidence": {
                "status": canonical_evidence_status,
                "items": evidence_items,
            },
            "improve_pathway": improve_pathway,
            "artifact": {
                "artifact_id": artifact[0],
                "status": artifact[1],
                "evidence_hash": artifact[2],
                "provenance": _json_load(artifact[3], {}) or {},
                "published_at": artifact[6].isoformat() if artifact[6] else None,
            },
        }
        safe_title = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(interview[2] or "interview"))[:48].strip("-") or "interview"
        filename = f"prepmate-report-{safe_title}-{interview_id[:8]}.json"
        return JSONResponse(
            content=export_payload,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    finally:
        cursor.close()
        return_db_connection(connection)

@router.post("/{interview_id}/abandon")
@router.delete("/cancel/{interview_id}")
async def cancel_interview(
    interview_id: str,
    current_user: Dict = Depends(local_user)
):
    connection = get_db_connection()
    cursor = connection.cursor()

    try:
        cursor.execute(
            """
            UPDATE Interviews
            SET status = 'cancelled',
                attempt_status = 'incomplete',
                analysis_status = 'not_requested',
                completion_kind = 'voluntary_exit',
                recovery_deadline_at = NULL,
                lifecycle_revision = lifecycle_revision + 1,
                completed_at = COALESCE(completed_at, CURRENT_TIMESTAMP),
                overall_score = NULL,
                duration_seconds = CASE
                    WHEN started_at IS NULL THEN duration_seconds
                    ELSE MAX(0, CAST(
                        (julianday(CURRENT_TIMESTAMP) - julianday(started_at)) * 86400
                        AS INTEGER
                    ))
                END,
                feedback_summary = 'Attempt ended incomplete by the candidate.',
                settings = json_patch(
                    json_remove(COALESCE(settings, '{}'), '$.recovery_deadline', '$.recovery_reason'),
                    json_object('abandonment_reason', 'voluntary_exit')
                )
            WHERE interview_id = ?
              AND user_id = ?
              AND status IN ('in_progress', 'uploading', 'recovering')
            RETURNING interview_id
            """,
            (interview_id, current_user["user_id"])
        )

        updated_row = cursor.fetchone()
        if cursor.rowcount == 0 or not updated_row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Interview not found or already completed"
            )
        cursor.execute(
            """
            UPDATE TechnicalInterviewRounds
            SET status = 'cancelled',
                completed_at = COALESCE(completed_at, CURRENT_TIMESTAMP)
            WHERE interview_id = ?
              AND user_id = ?
              AND status NOT IN ('submitted', 'completed', 'expired', 'cancelled')
            """,
            (interview_id, current_user["user_id"]),
        )
        connection.commit()
        _cancel_interview_recovery(interview_id)
        await _record_server_integrity_event(
            interview_id,
            current_user["user_id"],
            "voluntary_exit",
        )
        try:
            await ensure_mission_from_response_assessment(
                current_user["user_id"],
                interview_id,
            )
        except Exception:
            logger.exception(
                "Could not create a partial-attempt Improve mission interview=%s",
                stable_hash(interview_id, "interview"),
            )

        return {
            "success": True,
            "status": "cancelled",
            "official_score": None,
            "message": "Attempt ended incomplete. Start a new attempt when you are ready."
        }

    except HTTPException:
        connection.rollback()
        raise
    except Exception:
        connection.rollback()
        logger.error("Failed to cancel interview")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to cancel interview"
        )

    finally:
        cursor.close()
        return_db_connection(connection)
