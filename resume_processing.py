"""Local worker-owned resume parsing.

The API only validates and enqueues encrypted bytes.  This module is imported
by the local background worker, which claims SQLite rows with leases,
executes native document parsers outside the API process, and persists the
same response shape the existing frontend already consumes.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import tempfile
import time
import uuid
from typing import Any, Optional

from database import get_db, transaction
from security_utils import decrypt_data, encrypt_data, stable_hash


logger = logging.getLogger("prepmate.resume_processing")

RESUME_JOB_LEASE_SECONDS = 180
RESUME_JOB_MAX_ATTEMPTS = 5
MAX_PENDING_RESUME_JOBS = 2_000
MAX_PENDING_RESUME_JOBS_PER_USER = 8
PARSE_TIMEOUT_SECONDS = 30.0


class ResumeProcessingQueueFull(RuntimeError):
    pass


class ResumeProcessingPermanentError(RuntimeError):
    pass


def _encrypted_payload(value: str) -> bytes:
    return encrypt_data(value).encode("utf-8")


def _decode_blob(value: Any) -> str:
    if isinstance(value, memoryview):
        value = value.tobytes()
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    if not isinstance(value, str) or not value:
        raise ValueError("resume_job_payload_missing")
    decoded = decrypt_data(value)
    if decoded == value and not value.startswith("enc:"):
        raise ValueError("resume_job_payload_not_encrypted")
    return decoded


def _payload_for_parse(content: bytes) -> str:
    return base64.b64encode(content).decode("ascii")


def _enqueue(
    *,
    user_id: str,
    job_kind: str,
    content_hash: str,
    payload: str,
    source_filename: Optional[str] = None,
    source_extension: Optional[str] = None,
) -> str:
    if job_kind != "parse":
        raise ValueError("unsupported_resume_job_kind")
    if not content_hash or len(content_hash) > 128:
        raise ValueError("invalid_resume_job_hash")
    with get_db() as connection:
        cursor = connection.cursor()
        try:
            with transaction(connection):
                cursor.execute(
                    """
                    SELECT job_id, status
                    FROM ResumeProcessingJobs
                    WHERE user_id = ? AND job_kind = ? AND content_hash = ?
                    """,
                    (user_id, job_kind, content_hash),
                )
                existing = cursor.fetchone()
                if existing:
                    job_id, status = str(existing[0]), str(existing[1])
                    if status == "dead_letter":
                        cursor.execute(
                            """
                            UPDATE ResumeProcessingJobs
                            SET payload_encrypted = ?, source_filename = ?,
                                source_extension = ?, status = 'queued',
                                attempt_count = 0, available_at = CURRENT_TIMESTAMP,
                                lease_owner = NULL, lease_expires_at = NULL,
                                last_error_code = NULL, dead_letter_at = NULL,
                                updated_at = CURRENT_TIMESTAMP
                            WHERE job_id = ?
                            """,
                            (
                                _encrypted_payload(payload),
                                source_filename,
                                source_extension,
                                job_id,
                            ),
                        )
                    return job_id

                cursor.execute(
                    """
                    SELECT COUNT(*), COUNT(*) FILTER (WHERE user_id = ?)
                    FROM ResumeProcessingJobs
                    WHERE status IN ('queued', 'processing')
                    """,
                    (user_id,),
                )
                global_count, user_count = cursor.fetchone() or (0, 0)
                if int(global_count or 0) >= MAX_PENDING_RESUME_JOBS:
                    raise ResumeProcessingQueueFull("resume_processing_global_capacity_reached")
                if int(user_count or 0) >= MAX_PENDING_RESUME_JOBS_PER_USER:
                    raise ResumeProcessingQueueFull("resume_processing_user_capacity_reached")

                job_id = str(uuid.uuid4())
                cursor.execute(
                    """
                    INSERT INTO ResumeProcessingJobs (
                        job_id, user_id, job_kind, content_hash,
                        source_filename, source_extension, payload_encrypted,
                        status, attempt_count, max_attempts, available_at,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 'queued', 0, ?,
                              CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    """,
                    (
                        job_id,
                        user_id,
                        job_kind,
                        content_hash,
                        source_filename,
                        source_extension,
                        _encrypted_payload(payload),
                        RESUME_JOB_MAX_ATTEMPTS,
                    ),
                )
                return job_id
        finally:
            cursor.close()


def enqueue_resume_parse_job(
    *,
    user_id: str,
    content: bytes,
    content_hash: str,
    source_filename: str,
    source_extension: str,
) -> str:
    return _enqueue(
        user_id=user_id,
        job_kind="parse",
        content_hash=content_hash,
        payload=_payload_for_parse(content),
        source_filename=os.path.basename(source_filename or "resume")[:255],
        source_extension=source_extension[:8],
    )


def get_resume_job(*, user_id: str, job_id: str) -> Optional[dict[str, Any]]:
    with get_db() as connection:
        cursor = connection.cursor()
        try:
            cursor.execute(
                """
                SELECT job_id, job_kind, status, attempt_count, max_attempts,
                       last_error_code, result_encrypted, created_at,
                       completed_at
                FROM ResumeProcessingJobs
                WHERE job_id = ? AND user_id = ?
                """,
                (job_id, user_id),
            )
            row = cursor.fetchone()
        finally:
            cursor.close()
    if not row:
        return None
    result: Optional[dict[str, Any]] = None
    if row[6] and str(row[2]) == "completed":
        try:
            decoded = json.loads(_decode_blob(row[6]))
            result = decoded if isinstance(decoded, dict) else None
        except Exception:
            logger.warning("Could not decode resume result: job=%s", stable_hash(job_id, "resume-job"))
    return {
        "job_id": str(row[0]),
        "job_kind": str(row[1]),
        "status": str(row[2]),
        "attempt_count": int(row[3] or 0),
        "max_attempts": int(row[4] or RESUME_JOB_MAX_ATTEMPTS),
        "error_code": str(row[5]) if row[5] else None,
        "result": result,
        "created_at": row[7].isoformat() if row[7] else None,
        "completed_at": row[8].isoformat() if row[8] else None,
    }


def _claim(worker_id: str) -> Optional[dict[str, Any]]:
    with get_db() as connection:
        cursor = connection.cursor()
        try:
            with transaction(connection):
                cursor.execute(
                    """
                    UPDATE ResumeProcessingJobs
                    SET status = 'processing',
                        attempt_count = attempt_count + 1,
                        lease_owner = ?,
                        lease_expires_at = datetime(CURRENT_TIMESTAMP, '+' || CAST(? AS TEXT) || ' seconds'),
                        updated_at = CURRENT_TIMESTAMP
                    WHERE job_id = (
                        SELECT job_id
                        FROM ResumeProcessingJobs
                        WHERE attempt_count < max_attempts
                          AND available_at <= CURRENT_TIMESTAMP
                          AND (
                              status = 'queued'
                              OR (status = 'processing' AND lease_expires_at < CURRENT_TIMESTAMP)
                          )
                        ORDER BY created_at
                        LIMIT 1
                    )
                    RETURNING job_id, user_id, job_kind, content_hash,
                              source_filename, source_extension,
                              payload_encrypted, attempt_count, max_attempts
                    """,
                    (worker_id, RESUME_JOB_LEASE_SECONDS),
                )
                row = cursor.fetchone()
                cursor.execute(
                    """
                    INSERT INTO WorkerHeartbeats (
                        worker_id, worker_type, version, metadata,
                        started_at, heartbeat_at
                    ) VALUES (?, 'resume', ?, '{}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    ON CONFLICT (worker_id) DO UPDATE SET
                        worker_type = EXCLUDED.worker_type,
                        version = EXCLUDED.version,
                        heartbeat_at = CURRENT_TIMESTAMP
                    """,
                    (worker_id, "resume-processing-v1"),
                )
            if not row:
                return None
            return {
                "job_id": str(row[0]),
                "user_id": str(row[1]),
                "job_kind": str(row[2]),
                "content_hash": row[3],
                "source_filename": row[4],
                "source_extension": row[5],
                "payload_encrypted": row[6],
                "attempt_count": int(row[7] or 0),
                "max_attempts": int(row[8] or RESUME_JOB_MAX_ATTEMPTS),
            }
        finally:
            cursor.close()


def _complete(job: dict[str, Any], worker_id: str, result: Optional[dict[str, Any]]) -> None:
    result_blob = _encrypted_payload(json.dumps(result or {}, ensure_ascii=False, default=str))
    with get_db() as connection:
        cursor = connection.cursor()
        try:
            with transaction(connection):
                cursor.execute(
                    """
                    UPDATE ResumeProcessingJobs
                    SET status = 'completed', result_encrypted = ?,
                        payload_encrypted = ?, completed_at = CURRENT_TIMESTAMP,
                        lease_owner = NULL, lease_expires_at = NULL,
                        last_error_code = NULL, updated_at = CURRENT_TIMESTAMP
                    WHERE job_id = ? AND status = 'processing' AND lease_owner = ?
                    """,
                    (result_blob, b"", job["job_id"], worker_id),
                )
                if cursor.rowcount != 1:
                    raise RuntimeError("resume_job_lease_lost")
        finally:
            cursor.close()


def _fail(job: dict[str, Any], worker_id: str, error_code: str, *, permanent: bool = False) -> str:
    terminal = permanent or int(job.get("attempt_count") or 0) >= int(job.get("max_attempts") or RESUME_JOB_MAX_ATTEMPTS)
    with get_db() as connection:
        cursor = connection.cursor()
        try:
            with transaction(connection):
                cursor.execute(
                    """
                    UPDATE ResumeProcessingJobs
                    SET status = CASE WHEN ? THEN 'dead_letter' ELSE 'queued' END,
                        available_at = CASE WHEN ? THEN available_at
                            ELSE datetime(
                                CURRENT_TIMESTAMP,
                                '+' || CAST(MIN(900, (1 << attempt_count)) AS TEXT) || ' seconds'
                            ) END,
                        lease_owner = NULL, lease_expires_at = NULL,
                        payload_encrypted = CASE WHEN ? THEN ? ELSE payload_encrypted END,
                        last_error_code = ?,
                        dead_letter_at = CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE NULL END,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE job_id = ? AND status = 'processing' AND lease_owner = ?
                    """,
                    (
                        terminal,
                        terminal,
                        terminal,
                        b"",
                        error_code[:80],
                        terminal,
                        job["job_id"],
                        worker_id,
                    ),
                )
                if cursor.rowcount != 1:
                    raise RuntimeError("resume_job_lease_lost")
        finally:
            cursor.close()
    return "dead_letter" if terminal else "queued"


async def _process_parse(job: dict[str, Any]) -> dict[str, Any]:
    from pre_interview import (
        _confirmation_status,
        _merge_resume_profiles,
        _persist_parsed_resume,
        _resume_fact_payload,
        _resume_taxonomy,
        extract_contact_info,
        extract_resume_with_rules,
        extract_social_links,
        extract_with_ai_upload,
        remove_pii,
        validate_resume_json,
    )
    from resume_parser import parse_resume_structured, validate_resume_bytes

    content = base64.b64decode(_decode_blob(job["payload_encrypted"]).encode("ascii"), validate=True)
    extension = str(job.get("source_extension") or "")
    validate_resume_bytes(content, extension)
    temp_path = ""
    started = time.perf_counter()
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=extension) as output:
            temp_path = output.name
            output.write(content)
        parsed_resume = await asyncio.wait_for(
            asyncio.to_thread(parse_resume_structured, temp_path, fast=False),
            timeout=PARSE_TIMEOUT_SECONDS,
        )
    except ValueError as exc:
        raise ResumeProcessingPermanentError(str(exc)) from exc
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass

    resume_text = str(parsed_resume.get("text") or "")
    if len(resume_text.strip()) < 40:
        raise ResumeProcessingPermanentError("resume_text_too_short")
    contact = extract_contact_info(resume_text)
    social = extract_social_links(resume_text)
    redacted_text = remove_pii(resume_text)[:50000]
    fallback_json = extract_resume_with_rules(resume_text, contact, social, parsed_resume)
    resume_json = fallback_json
    try:
        ai_json = await extract_with_ai_upload(redacted_text, user_id=job["user_id"])
        resume_json = _merge_resume_profiles(ai_json, fallback_json)
    except Exception as exc:
        logger.warning(
            "Resume AI enrichment failed; using deterministic extraction: job=%s error=%s",
            stable_hash(job["job_id"], "resume-job"),
            type(exc).__name__,
        )
    resume_json["email"] = contact["email"]
    resume_json["phone"] = contact["phone"]
    resume_json["linkedin"] = social["linkedin"]
    resume_json["github"] = social["github"]
    resume_json["portfolio"] = social["portfolio"]
    resume_json["links"] = {
        "linkedin": social["linkedin"],
        "github": social["github"],
        "portfolio": social["portfolio"],
        "all": parsed_resume.get("links", []),
    }
    resume_json["profile_sources"] = list(dict.fromkeys(
        (resume_json.get("profile_sources") or []) + [parsed_resume.get("parser", "resume_parser")]
    ))
    resume_json = validate_resume_json(resume_json)
    resume_json["links"] = {
        "linkedin": social["linkedin"],
        "github": social["github"],
        "portfolio": social["portfolio"],
        "all": parsed_resume.get("links", []),
    }
    parser_version = str(parsed_resume.get("parser") or "resume_parser")[:40]
    facts_payload = _resume_fact_payload(
        resume_json,
        source_text=resume_text,
        parser_version=parser_version,
    )
    persisted = await asyncio.to_thread(
        _persist_parsed_resume,
        user_id=job["user_id"],
        email=None,
        resume_json=resume_json,
        resume_text=resume_text,
        content_hash=job["content_hash"],
        source_filename=job.get("source_filename") or "resume",
        parser_version=parser_version,
        facts_payload=facts_payload,
    )
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    return {
        "success": True,
        "message": "Resume parsed and saved. Please review your details.",
        "extracted_profile": persisted["active_profile"],
        "profile_completed": persisted["profile_completed"],
        "parse_ms": elapsed_ms,
        "resume": persisted["resume"],
        "version_created": persisted["version_created"],
    }


async def _process_claimed(job: dict[str, Any], worker_id: str) -> None:
    try:
        result = await _process_parse(job)
        await asyncio.to_thread(_complete, job, worker_id, result)
    except asyncio.CancelledError:
        raise
    except ResumeProcessingPermanentError as exc:
        await asyncio.to_thread(_fail, job, worker_id, type(exc).__name__, permanent=True)
    except Exception as exc:
        logger.exception(
            "Resume processing attempt failed: job=%s kind=%s error=%s",
            stable_hash(job["job_id"], "resume-job"),
            job["job_kind"],
            type(exc).__name__,
        )
        await asyncio.to_thread(_fail, job, worker_id, type(exc).__name__)


async def resume_processing_worker_loop(
    worker_id: str,
    *,
    stop_event: asyncio.Event,
    idle_seconds: float = 1.0,
) -> None:
    while not stop_event.is_set():
        job = await asyncio.to_thread(_claim, worker_id)
        if job:
            await _process_claimed(job, worker_id)
            continue
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=max(0.1, idle_seconds))
        except asyncio.TimeoutError:
            pass
