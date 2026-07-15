"""Durable deterministic interview-blueprint API.

The public preview intentionally omits exact questions.  Starting and consuming
the ready blueprint is owned by the interview runtime.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from auth import get_current_user
from database import get_db_connection, return_db_connection
from interview_blueprint import (
    BLUEPRINT_COMPILER_VERSION,
    build_blueprint_preview,
    compile_interview_blueprint,
    validate_blueprint,
)
from interview_profiles import get_profile_duration
from security_utils import decrypt_data, decrypt_json, encrypt_data


router = APIRouter(prefix="/api/interview", tags=["Interview Blueprints"])


class BlueprintCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_idempotency_key: Optional[str] = Field(default=None, min_length=8, max_length=120)
    resume_id: Optional[str] = Field(default=None, max_length=64)
    job_profile_id: Optional[int] = Field(default=None, ge=1)
    interview_mode: Literal["mock"] = "mock"
    interview_type: str = Field(default="behavioral", min_length=2, max_length=80)
    profile_type: Literal["top_tier", "mid_tier", "startup", "custom"] = "mid_tier"


def server_owned_interview_policy(profile_type: str) -> Dict[str, Any]:
    """Return the immutable settings users are not allowed to shape."""
    duration = get_profile_duration(profile_type)
    target_minutes = max(45, min(60, int(duration["target_minutes"])))
    return {
        "difficulty_level": "adaptive",
        "duration_minutes": target_minutes,
        "focus": ["mixed"],
        "question_count": None,
        "round_config": {},
    }


def _json_value(value: Any, fallback: Any) -> Any:
    if value is None:
        return fallback
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except Exception:
        return fallback


def _decrypt_blob(value: Any, fallback: Any) -> Any:
    if value is None:
        return fallback
    if isinstance(value, memoryview):
        value = value.tobytes()
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    if not isinstance(value, str):
        return fallback
    try:
        return json.loads(decrypt_data(value))
    except Exception:
        return fallback


def _encrypted_blob(value: Any) -> bytes:
    return encrypt_data(json.dumps(value, ensure_ascii=False, default=str)).encode("utf-8")


def _blueprint_payload(plain_value: Any, encrypted_value: Any, fallback: Any) -> Any:
    decrypted = _decrypt_blob(encrypted_value, None)
    if isinstance(decrypted, dict):
        return decrypted
    return _json_value(plain_value, fallback)


def _materialize_resume(payload: Dict[str, Any], facts_payload: Dict[str, Any]) -> Dict[str, Any]:
    result = dict(payload or {})
    for fact in facts_payload.get("facts") or []:
        if not isinstance(fact, dict):
            continue
        field_name = str(fact.get("field") or "")
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,60}", field_name):
            continue
        if fact.get("status") == "corrected":
            result[field_name] = fact.get("corrected_value")
        elif fact.get("status") == "rejected":
            result.pop(field_name, None)
    return result


def _preview_response(
    *,
    blueprint_id: str,
    status_value: str,
    expires_at: Any,
    created_at: Any,
    blueprint: Dict[str, Any],
    resume_id: str,
    job_profile_id: int,
) -> Dict[str, Any]:
    return {
        "blueprint_id": blueprint_id,
        "status": status_value,
        "resume_id": resume_id,
        "job_profile_id": job_profile_id,
        "compiler_version": blueprint.get("compiler_version") or BLUEPRINT_COMPILER_VERSION,
        "blueprint_hash": blueprint.get("blueprint_hash"),
        "expires_at": expires_at.isoformat() if hasattr(expires_at, "isoformat") else expires_at,
        "created_at": created_at.isoformat() if hasattr(created_at, "isoformat") else created_at,
        "preview": build_blueprint_preview(blueprint),
    }


@router.post("/blueprints", status_code=status.HTTP_201_CREATED)
async def create_interview_blueprint(
    request: BlueprintCreateRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    connection = get_db_connection()
    cursor = connection.cursor()
    try:
        if request.resume_id:
            cursor.execute(
                """
                SELECT resume_id, resume_payload_encrypted, resume_json,
                       facts_encrypted, confirmation_status
                FROM ResumeVersions
                WHERE resume_id = %s AND user_id = %s
                """,
                (request.resume_id, current_user["user_id"]),
            )
        else:
            cursor.execute(
                """
                SELECT resume_id, resume_payload_encrypted, resume_json,
                       facts_encrypted, confirmation_status
                FROM ResumeVersions
                WHERE user_id = %s AND is_active = TRUE
                ORDER BY version_number DESC
                LIMIT 1
                """,
                (current_user["user_id"],),
            )
        resume_row = cursor.fetchone()
        if not resume_row:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Resume version not found")
        if str(resume_row[4] or "") != "confirmed":
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Review all uncertain resume facts before creating a blueprint",
            )
        resume_payload = _decrypt_blob(resume_row[1], None)
        if not isinstance(resume_payload, dict):
            resume_payload = decrypt_json(resume_row[2]) if resume_row[2] is not None else {}
        if not isinstance(resume_payload, dict):
            raise HTTPException(status.HTTP_409_CONFLICT, "Resume payload is unavailable")
        facts_payload = _decrypt_blob(resume_row[3], {"facts": []})
        resume_payload = _materialize_resume(resume_payload, facts_payload if isinstance(facts_payload, dict) else {"facts": []})

        if request.job_profile_id:
            cursor.execute(
                """
                SELECT profile_id, role, company, job_description_encrypted,
                       normalized_requirements, experience_level
                FROM JobProfiles
                WHERE profile_id = %s AND user_id = %s
                """,
                (request.job_profile_id, current_user["user_id"]),
            )
        else:
            cursor.execute(
                """
                SELECT profile_id, role, company, job_description_encrypted,
                       normalized_requirements, experience_level
                FROM JobProfiles
                WHERE user_id = %s AND is_selected = TRUE
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (current_user["user_id"],),
            )
        job_row = cursor.fetchone()
        if not job_row:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Job target not found")
        encrypted_jd = job_row[3]
        if isinstance(encrypted_jd, memoryview):
            encrypted_jd = encrypted_jd.tobytes()
        if isinstance(encrypted_jd, bytes):
            encrypted_jd = encrypted_jd.decode("utf-8")
        job_description = decrypt_data(encrypted_jd) if isinstance(encrypted_jd, str) else ""
        has_full_job_description = bool(str(job_description or "").strip())
        requirements = _json_value(job_row[4], {})
        if not job_description and isinstance(requirements, dict):
            job_description = "\n".join(str(item) for item in requirements.get("requirements") or [])
        role = str(job_row[1] or "").strip()
        company = str(job_row[2] or "").strip()
        if request.profile_type == "custom" and not (role and has_full_job_description):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Custom requires the role and full job description",
            )
        role = role or "General Interview"
        job_title = f"{role} at {company}" if company else role
        experience_level = job_row[5]
        policy = server_owned_interview_policy(request.profile_type)

        if request.request_idempotency_key:
            cursor.execute(
                """
                SELECT blueprint_id, status, expires_at, created_at, blueprint_json,
                       blueprint_json_encrypted, resume_id, job_profile_id
                FROM InterviewBlueprints
                WHERE user_id = %s AND request_idempotency_key = %s
                """,
                (current_user["user_id"], request.request_idempotency_key),
            )
            idempotent_row = cursor.fetchone()
            if idempotent_row:
                connection.rollback()
                return _preview_response(
                    blueprint_id=idempotent_row[0],
                    status_value=idempotent_row[1],
                    expires_at=idempotent_row[2],
                    created_at=idempotent_row[3],
                    blueprint=_blueprint_payload(idempotent_row[4], idempotent_row[5], {}),
                    resume_id=idempotent_row[6],
                    job_profile_id=idempotent_row[7],
                )

        cursor.execute(
            """
            SELECT skill_key, mastery_score, confidence_score, evidence_count,
                   last_evidence_at
            FROM LearnerSkillStates
            WHERE user_id = %s AND evidence_count > 0 AND mastery_score < 70
            ORDER BY confidence_score DESC, mastery_score ASC, last_evidence_at DESC NULLS LAST
            LIMIT 5
            """,
            (current_user["user_id"],),
        )
        previous_weaknesses = [
            {
                "skill_key": row[0],
                "label": str(row[0] or "").replace(":", " ").replace("-", " ").title(),
                "mastery_score": float(row[1] or 0),
                "confidence_score": float(row[2] or 0),
                "evidence_count": int(row[3] or 0),
                "last_evidence_at": row[4].isoformat() if row[4] else None,
            }
            for row in cursor.fetchall()
        ]
        blueprint = validate_blueprint(compile_interview_blueprint(
            resume_data=resume_payload,
            job_title=job_title,
            job_description=job_description,
            interview_type=request.interview_type,
            duration_minutes=policy["duration_minutes"],
            profile_type=request.profile_type,
            focus=policy["focus"],
            previous_weaknesses=previous_weaknesses,
            difficulty_level=policy["difficulty_level"],
            experience_level=experience_level,
            question_count=policy["question_count"],
            round_config=policy["round_config"],
        ))
        settings_json = {
            "resume_id": resume_row[0],
            "job_profile_id": job_row[0],
            "role": role,
            "company": company or None,
            "profile_type": request.profile_type,
            "focus": policy["focus"],
            "difficulty_level": policy["difficulty_level"],
            "duration_minutes": policy["duration_minutes"],
            "question_count": policy["question_count"],
        }

        cursor.execute(
            """
            SELECT blueprint_id, status, expires_at, created_at, blueprint_json,
                   blueprint_json_encrypted
            FROM InterviewBlueprints
            WHERE user_id = %s AND resume_id = %s AND job_profile_id = %s
              AND blueprint_hash = %s AND status = 'ready'
              AND (expires_at IS NULL OR expires_at > NOW())
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (current_user["user_id"], resume_row[0], job_row[0], blueprint["blueprint_hash"]),
        )
        existing = cursor.fetchone()
        if existing:
            persisted = _blueprint_payload(existing[4], existing[5], blueprint)
            connection.rollback()
            return _preview_response(
                blueprint_id=existing[0],
                status_value=existing[1],
                expires_at=existing[2],
                created_at=existing[3],
                blueprint=persisted,
                resume_id=resume_row[0],
                job_profile_id=job_row[0],
            )

        blueprint_id = str(uuid.uuid4())
        cursor.execute(
            """
            INSERT INTO InterviewBlueprints (
                blueprint_id, user_id, resume_id, job_profile_id,
                interview_mode, interview_type, experience_level,
                difficulty_level, duration_minutes, focus, round_config,
                blueprint_json, blueprint_json_encrypted, settings_json, blueprint_hash,
                compiler_version, request_idempotency_key,
                status, expires_at, created_at
            )
            VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, 'ready', NOW() + INTERVAL '24 hours', NOW()
            )
            RETURNING expires_at, created_at
            """,
            (
                blueprint_id,
                current_user["user_id"],
                resume_row[0],
                job_row[0],
                request.interview_mode,
                request.interview_type,
                experience_level,
                policy["difficulty_level"],
                policy["duration_minutes"],
                json.dumps(policy["focus"]),
                json.dumps(policy["round_config"]),
                json.dumps({"encrypted": True, "preview": build_blueprint_preview(blueprint)}),
                _encrypted_blob(blueprint),
                json.dumps(settings_json),
                blueprint["blueprint_hash"],
                BLUEPRINT_COMPILER_VERSION,
                request.request_idempotency_key,
            ),
        )
        persisted_row = cursor.fetchone()
        connection.commit()
        return _preview_response(
            blueprint_id=blueprint_id,
            status_value="ready",
            expires_at=persisted_row[0],
            created_at=persisted_row[1],
            blueprint=blueprint,
            resume_id=resume_row[0],
            job_profile_id=job_row[0],
        )
    except HTTPException:
        connection.rollback()
        raise
    except ValueError as exc:
        connection.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()
        return_db_connection(connection)


@router.get("/blueprints/{blueprint_id}")
async def get_interview_blueprint(
    blueprint_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    connection = get_db_connection()
    cursor = connection.cursor()
    try:
        cursor.execute(
            """
            SELECT blueprint_id, resume_id, job_profile_id, status,
                   expires_at, created_at, blueprint_json, blueprint_json_encrypted
            FROM InterviewBlueprints
            WHERE blueprint_id = %s AND user_id = %s
            """,
            (blueprint_id, current_user["user_id"]),
        )
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Interview blueprint not found")
        blueprint = _blueprint_payload(row[6], row[7], {})
        effective_status = str(row[3] or "")
        expiry = row[4]
        if expiry and getattr(expiry, "tzinfo", None) is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        if effective_status == "ready" and expiry and expiry <= datetime.now(timezone.utc):
            effective_status = "expired"
        return _preview_response(
            blueprint_id=row[0],
            status_value=effective_status,
            expires_at=row[4],
            created_at=row[5],
            blueprint=blueprint,
            resume_id=row[1],
            job_profile_id=row[2],
        )
    finally:
        cursor.close()
        return_db_connection(connection)
