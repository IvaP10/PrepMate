"""Immutable materialized context for one official attempt."""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from evaluation_engine import EVALUATION_VERSION
from security_utils import encrypt_data


TAXONOMY_VERSION = "interai-taxonomy-v1"
RUBRIC_VERSION = "interai-rubric-v1"


def canonical_context_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _encrypted_blob(payload: dict[str, Any]) -> bytes:
    encoded = json.dumps(payload, separators=(",", ":"), ensure_ascii=False, default=str)
    return encrypt_data(encoded).encode("utf-8")


def create_attempt_context_snapshot(
    cursor: Any,
    *,
    interview_id: str,
    user_id: str,
    resume_id: str,
    job_profile_id: int | None,
    blueprint_id: str,
    profile_type: str,
    profile_config_version: str,
    role: str,
    company: str,
    resume_payload: dict[str, Any],
    job_context: dict[str, Any],
    blueprint_context: dict[str, Any],
) -> tuple[str, str]:
    """Persist the only mutable-context materialization an attempt may read."""
    normalized = {
        "resume": resume_payload,
        "job": job_context,
        "blueprint": blueprint_context,
        "profile_type": profile_type,
        "profile_config_version": profile_config_version,
        "evaluator_version": EVALUATION_VERSION,
        "taxonomy_version": TAXONOMY_VERSION,
        "rubric_version": RUBRIC_VERSION,
    }
    context_hash = canonical_context_hash(normalized)
    snapshot_id = str(uuid.uuid4())
    company_hash = hashlib.sha256((company or "").strip().lower().encode("utf-8")).hexdigest()
    cursor.execute(
        """
        INSERT INTO AttemptContextSnapshots (
            snapshot_id, interview_id, user_id, resume_id, job_profile_id,
            blueprint_id, profile_type, profile_config_version, role, company_hash,
            context_hash, resume_payload_encrypted, job_context_encrypted,
            blueprint_context_encrypted, evaluator_version, taxonomy_version,
            rubric_version, created_at
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
        """,
        (
            snapshot_id, interview_id, user_id, resume_id, job_profile_id,
            blueprint_id, profile_type, profile_config_version, role, company_hash,
            context_hash, _encrypted_blob(resume_payload), _encrypted_blob(job_context),
            _encrypted_blob(blueprint_context), EVALUATION_VERSION, TAXONOMY_VERSION,
            RUBRIC_VERSION,
        ),
    )
    cursor.execute(
        "UPDATE Interviews SET context_snapshot_id = %s WHERE interview_id = %s AND user_id = %s",
        (snapshot_id, interview_id, user_id),
    )
    cursor.execute(
        "UPDATE ResumeVersions SET immutable_at = COALESCE(immutable_at, NOW()) WHERE resume_id = %s AND user_id = %s",
        (resume_id, user_id),
    )
    return snapshot_id, context_hash
