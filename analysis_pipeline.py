from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import re
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence

from config import settings
from database import async_execute
from local_runtime import get_local_preferences
from evaluation_engine import EVALUATION_VERSION, evaluate_answer
from learning_engine import (
    ensure_mission_from_weakness,
    ensure_mission_from_technical_report,
    ingest_interview_evidence,
    validate_mission_with_analysis,
)
from report_generator import build_async_behavioral_report, build_async_technical_report
from security_utils import decrypt_data, decrypt_json, decrypt_json_field, encrypt_data, stable_hash
from weakness_engine import (
    RUBRIC_VERSION,
    TAXONOMY_VERSION,
    persist_weakness_states,
    retire_superseded_analysis_evidence,
)

logger = logging.getLogger("analysis_pipeline")

ANALYSIS_STAGES = (
    "evidence_load",
    "transcript_analysis",
    "technical_analysis",
    "self_review_summary",
    "deterministic_report",
    "semantic_enhancement",
    "report_validation",
    "performance_projection",
    "weakness_update",
    "improve_update",
    "complete",
)
ANALYSIS_PREFLIGHT_STAGES = ("assessment_completion",)
ANALYSIS_EXECUTION_STAGES = ANALYSIS_PREFLIGHT_STAGES + ANALYSIS_STAGES

ANALYSIS_STAGE_VERSION = "evidence-v10"
ANALYSIS_LEASE_SECONDS = 90
ANALYSIS_MAX_RETRIES = 3
REPORT_SIDE_EFFECT_LEASE_SECONDS = 120
REPORT_SIDE_EFFECT_MAX_ATTEMPTS = 8
TERMINAL_INTERVIEW_STATUSES = {"completed", "report_ready", "partial", "failed", "cancelled"}
REPORT_READY_INTERVIEW_STATUSES = {"completed", "report_ready", "partial", "failed"}
EVIDENCE_MANIFEST_VERSION = "evidence-manifest-v2"
SESSION_PERFORMANCE_VERSION = "session-performance-v4"
CRITICAL_ANALYSIS_STAGES = {
    "assessment_completion",
    "transcript_analysis",
    "technical_analysis",
    "deterministic_report",
    "report_validation",
    "performance_projection",
    "complete",
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


def _json_dumps(value: Any) -> str:
    return json.dumps(value, default=str)


def _analysis_job_idempotency_key(interview_id: str, evidence_hash: str) -> str:
    # Empty or identical evidence can legitimately occur in different
    # attempts. Keep durable job identity scoped to the owning interview so a
    # reconciliation can never reuse or replace another attempt's manifest.
    return f"analysis:{ANALYSIS_STAGE_VERSION}:{interview_id}:{evidence_hash}"


def _report_payload_ready(report_json: Any) -> bool:
    return isinstance(_json_value(report_json, None), dict)


def _is_report_ready_status(status_value: Any, report_json: Any) -> bool:
    return str(status_value or "").lower() in REPORT_READY_INTERVIEW_STATUSES and _report_payload_ready(report_json)


def _score_band(score: float) -> str:
    if score >= 75:
        return "Low"
    if score >= 45:
        return "Medium"
    return "High"


def _manifest_hashable(value: Any) -> Any:
    if isinstance(value, memoryview):
        value = value.tobytes()
    if isinstance(value, (bytes, bytearray)):
        return {"bytes_sha256": hashlib.sha256(bytes(value)).hexdigest()}
    if isinstance(value, dict):
        return {str(key): _manifest_hashable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_manifest_hashable(item) for item in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _seal_evidence_manifest(cursor: Any, interview_id: str, user_id: str) -> tuple[str, str]:
    cursor.execute("SELECT CURRENT_TIMESTAMP")
    sealed_at = cursor.fetchone()[0]
    item_queries = (
        (
            "interview_question", "question-contract-v1",
            """SELECT question.question_id, question.created_at, question.taxonomy_keys,
                      question.expected_points, question.rubric_json, question.question_type,
                      question.rubric_version, question.provenance
               FROM InterviewQuestions question
               JOIN Interviews interview ON interview.interview_id = question.interview_id
               WHERE question.interview_id = ? AND interview.user_id = ? AND question.created_at <= ?""",
        ),
        (
            "interview_response", "response-v1",
            """SELECT response_id, created_at, question_id, user_response, response_time_seconds,
                      evaluation_json, answer_quality_flags, evidence_quotes, stt_confidence,
                      answer_text_encrypted, raw_answer_hash, evidence_hash, input_mode, timing_json
               FROM InterviewResponses response
               WHERE response.interview_id = ?
                 AND EXISTS (SELECT 1 FROM Interviews interview WHERE interview.interview_id = response.interview_id AND interview.user_id = ?)
                 AND response.created_at <= ?""",
        ),
        (
            "response_assessment", "assessment-v1",
            """SELECT assessment_id, created_at, response_id, evaluator_version, evidence_hash, overall_score,
                      assessment_json_encrypted, assessment_json
               FROM ResponseAssessments assessment
               WHERE assessment.interview_id = ?
                 AND EXISTS (SELECT 1 FROM Interviews interview WHERE interview.interview_id = assessment.interview_id AND interview.user_id = ?)
                 AND assessment.created_at <= ?""",
        ),
        (
            "technical_round", "technical-round-v1",
            """SELECT round_id, created_at, round_type, language, prompt,
                      problem_id, round_spec_id, problem_version, round_number,
                      round_spec, metadata
               FROM TechnicalInterviewRounds
               WHERE interview_id = ? AND user_id = ? AND created_at <= ?""",
        ),
        (
            "technical_submission", "technical-submission-v1",
            """SELECT submission_id, created_at, round_id, code_hash, submit_number, visible_passed,
                      visible_total, hidden_passed, hidden_total, status, execution_job_id
               FROM TechnicalSubmissions WHERE interview_id = ? AND user_id = ? AND created_at <= ?""",
        ),
        (
            "technical_run", "technical-run-v1",
            """SELECT run.run_id, run.created_at, run.round_id, run.code_hash, run.exit_code,
                      run.error_signature, run.runtime_ms, run.metadata, run.hidden_validation_result
               FROM TechnicalRunEvents run JOIN TechnicalInterviewRounds round ON round.round_id = run.round_id
               WHERE round.interview_id = ? AND run.user_id = ? AND run.created_at <= ?""",
        ),
        (
            "technical_code_snapshot", "code-snapshot-v1",
            """SELECT snapshot_id, created_at, round_id, code_hash, source_chars, metadata
               FROM TechnicalCodeSnapshots WHERE interview_id = ? AND user_id = ? AND created_at <= ?""",
        ),
        (
            "technical_reasoning", "technical-reasoning-v1",
            """SELECT evidence_id, created_at, round_id, evidence_type, content, payload,
                      content_encrypted, evidence_hash, idempotency_key
               FROM TechnicalReasoningEvidence WHERE interview_id = ? AND user_id = ? AND created_at <= ?""",
        ),
        (
            "integrity_event", "attempt-integrity-v1",
            """SELECT event_id, received_at, client_session_id, sequence, event_type, severity, source,
                      observed_at, payload_hash
               FROM AttemptIntegrityEvents WHERE interview_id = ? AND user_id = ? AND received_at <= ?""",
        ),
        (
            "anti_cheat_event", "anti-cheat-v1",
            """SELECT event_id, created_at, event_type, payload
               FROM SelfReviewEvents WHERE interview_id = ? AND user_id = ? AND created_at <= ?""",
        ),
        (
            "media_asset", "media-manifest-v1",
            """SELECT asset_id, created_at, media_kind, checksum, byte_size, chunk_index, chunk_count, status
               FROM InterviewMediaAssets WHERE interview_id = ? AND user_id = ? AND created_at <= ?""",
        ),
    )
    items: List[Dict[str, Any]] = []
    for evidence_type, schema_version, query in item_queries:
        cursor.execute(query, (interview_id, user_id, sealed_at))
        for row in cursor.fetchall() or []:
            evidence_id = str(row[0])
            created_at = row[1]
            content_hash = hashlib.sha256(
                json.dumps(
                    _manifest_hashable(row[2:]),
                    sort_keys=True, default=str, separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            items.append({
                "evidence_type": evidence_type,
                "evidence_id": evidence_id,
                "schema_version": schema_version,
                "content_hash": content_hash,
                "created_at": created_at.isoformat() if hasattr(created_at, "isoformat") else str(created_at),
            })
    items.sort(key=lambda item: (item["evidence_type"], item["evidence_id"], item["content_hash"]))
    canonical = {
        "schema_version": EVIDENCE_MANIFEST_VERSION,
        "interview_id": interview_id,
        "user_id": user_id,
        "sealed_at": sealed_at.isoformat() if hasattr(sealed_at, "isoformat") else str(sealed_at),
        "items": items,
    }
    evidence_hash = hashlib.sha256(
        "\n".join(
            f"{item['evidence_type']}|{item['evidence_id']}|{item['content_hash']}|{item['schema_version']}"
            for item in items
        ).encode("utf-8")
    ).hexdigest()
    manifest_id = str(uuid.uuid4())
    safe_manifest = {
        "schema_version": EVIDENCE_MANIFEST_VERSION,
        "evidence_hash": evidence_hash,
        "item_count": len(items),
        "items": items,
    }
    cursor.execute(
        """
        SELECT manifest_id, evidence_hash, schema_version, revision_no, producer_version
        FROM EvidenceManifests
        WHERE interview_id = ? AND user_id = ? AND is_current = TRUE
        """,
        (interview_id, user_id),
    )
    existing = cursor.fetchone()
    if (
        existing
        and str(existing[1]) == evidence_hash
        and str(existing[2]) == EVIDENCE_MANIFEST_VERSION
        and str(existing[4] or "") == ANALYSIS_STAGE_VERSION
    ):
        return str(existing[0]), evidence_hash

    previous_manifest_id = str(existing[0]) if existing else None
    next_revision = int(existing[3] or 0) + 1 if existing else 1
    if existing:
        cursor.execute(
            """
            UPDATE EvidenceManifests
            SET is_current = FALSE
            WHERE manifest_id = ?
            """,
            (existing[0],),
        )
    cursor.execute(
        """
        INSERT INTO EvidenceManifests (
            manifest_id, interview_id, user_id, schema_version, evidence_hash,
            item_count, manifest_json, manifest_encrypted,
            revision_no, is_current, supersedes_manifest_id, producer_version,
            sealed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, TRUE, ?, ?, ?)
        """,
        (
            manifest_id, interview_id, user_id, EVIDENCE_MANIFEST_VERSION,
            evidence_hash, len(items), json.dumps(safe_manifest),
            encrypt_data(json.dumps(canonical, default=str)).encode("utf-8"),
            next_revision, previous_manifest_id, ANALYSIS_STAGE_VERSION, sealed_at,
        ),
    )
    return manifest_id, evidence_hash


def _clip(score: float, low: float = 0.0, high: float = 100.0) -> float:
    return round(max(low, min(high, float(score or 0))), 1)


def _event_counts(rows: List[Any]) -> Counter:
    counter: Counter = Counter()
    for row in rows or []:
        counter[str(row[0] or "unknown")] += int(row[1] or 0)
    return counter


def _word_count(text: str) -> int:
    return len(str(text or "").split())


def _candidate_word_count(transcript: List[Dict[str, Any]]) -> int:
    return sum(_word_count(item.get("text", "")) for item in transcript if item.get("role") == "candidate")


def _candidate_transcript_role(value: Any) -> Optional[str]:
    normalized = str(value or "").strip().lower()
    if normalized in {"candidate", "user", "candidate_user"}:
        return "candidate"
    if normalized in {"interviewer", "assistant", "ai", "coach"}:
        return "interviewer"
    return None


def _technical_reasoning_transcript_entry(
    evidence_type: Any,
    encrypted_payload: Any,
) -> Optional[Dict[str, str]]:
    """Turn encrypted Technical reasoning evidence into a candidate transcript row."""
    if not encrypted_payload:
        return None
    try:
        payload = _json_value(_decrypt_storage_text(encrypted_payload), {})
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    text = str(
        payload.get("content")
        or payload.get("text")
        or payload.get("transcript")
        or payload.get("question")
        or payload.get("approach")
        or ""
    ).strip()
    if not text:
        return None
    normalized_type = str(evidence_type or "").strip().lower()
    labels = {
        "technical_transcript": "Spoken reasoning",
        "spoken_explanation": "Spoken explanation",
        "written_approach": "Written approach",
        "workflow_clarification": "Clarification",
        "workflow_approach": "Approach",
        "workflow_complexity": "Complexity analysis",
        "workflow_explanation": "Final explanation",
        "workflow_followup": "Follow-up explanation",
    }
    label = labels.get(normalized_type)
    if not label:
        return None
    return {"role": "candidate", "text": text, "label": label}


def summarize_self_review_signals(event_counts: Counter, media_summary: Dict[str, Any], code_summary: Dict[str, Any]) -> Dict[str, Any]:
    events: List[Dict[str, Any]] = []
    for event_type, count in event_counts.items():
        if int(count or 0) > 0:
            events.append({"event_type": event_type, "count": int(count)})

    media_flags = media_summary.get("flags") or []
    code_flags = code_summary.get("authenticity_flags") or []
    return {
        "mode": "self_review",
        "scored": False,
        "signal_count": sum(item["count"] for item in events) + len(media_flags) + len(code_flags),
        "events": events,
        "media_flags": media_flags,
        "code_flags": code_flags,
    }


async def enqueue_analysis_result(
    interview_id: str,
    user_id: str,
    reason: str = "session_end",
    *,
    force_canonical_rebuild: bool = False,
) -> Dict[str, Any]:
    def _get_or_create_job() -> Dict[str, Any]:
        from database import get_db_connection, return_db_connection

        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("BEGIN IMMEDIATE")
            cursor.execute(
                """
                SELECT status, report_json, analysis_job_id, evidence_sealed_at, evidence_hash,
                       attempt_status
                FROM Interviews
                WHERE interview_id = ? AND user_id = ?
                """,
                (interview_id, user_id),
            )
            interview_row = cursor.fetchone()
            if not interview_row:
                conn.commit()
                return {"job_id": None, "state": "rejected", "reason": "interview_not_found"}

            attempt_status = str(interview_row[5] or "").lower()
            interview_status = str(interview_row[0] or "").lower()
            if attempt_status != "completed":
                if interview_status not in {"analysis_pending", "analysis_running"}:
                    conn.commit()
                    return {
                        "job_id": None,
                        "state": "rejected",
                        "reason": "attempt_not_completed",
                    }
                # Repair technical attempts finalized by an older worker that
                # reached the analysis state without committing the attempt
                # lifecycle columns. The analysis status itself is terminal
                # proof that the live round has already ended.
                cursor.execute(
                    """
                    UPDATE Interviews
                    SET attempt_status = 'completed',
                        analysis_status = CASE
                            WHEN status = 'analysis_running' THEN 'running'
                            ELSE 'queued'
                        END,
                        completed_at = COALESCE(completed_at, CURRENT_TIMESTAMP)
                    WHERE interview_id = ? AND user_id = ?
                    """,
                    (interview_id, user_id),
                )

            if _is_report_ready_status(interview_row[0], interview_row[1]):
                cursor.execute(
                    """
                    SELECT 1
                    FROM SessionPerformanceAnalyses analysis
                    WHERE analysis.interview_id = ? AND analysis.user_id = ?
                      AND analysis.schema_version = ?
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
                      AND EXISTS (
                          SELECT 1
                          FROM ReportSideEffectOutbox side_effect
                          WHERE side_effect.analysis_id = analysis.analysis_id
                            AND side_effect.interview_id = analysis.interview_id
                            AND side_effect.user_id = analysis.user_id
                            AND side_effect.event_type = 'improve_sync'
                      )
                    LIMIT 1
                    """,
                    (interview_id, user_id, SESSION_PERFORMANCE_VERSION, ANALYSIS_STAGE_VERSION),
                )
                canonical_ready = bool(cursor.fetchone())
                if canonical_ready or not force_canonical_rebuild:
                    if canonical_ready:
                        cursor.execute(
                            """
                            UPDATE Interviews
                            SET analysis_status = 'completed'
                            WHERE interview_id = ? AND user_id = ?
                            """,
                            (interview_id, user_id),
                        )
                        if interview_row[2]:
                            cursor.execute(
                                """
                                UPDATE AnalysisJobs
                                SET status = 'completed', progress = 100,
                                    current_stage = 'complete',
                                    error_message = NULL,
                                    completed_at = COALESCE(completed_at, CURRENT_TIMESTAMP),
                                    updated_at = CURRENT_TIMESTAMP,
                                    lease_owner = NULL,
                                    lease_expires_at = NULL
                                WHERE job_id = ? AND status = 'failed'
                                """,
                                (interview_row[2],),
                            )
                    conn.commit()
                    return {
                        "job_id": interview_row[2],
                        "state": "ready" if canonical_ready else "report_ready",
                        "reason": None,
                    }

            manifest_id, evidence_hash = _seal_evidence_manifest(cursor, interview_id, user_id)
            cursor.execute(
                """
                UPDATE Interviews
                SET evidence_hash = ?,
                    evidence_sealed_at = CURRENT_TIMESTAMP
                WHERE interview_id = ? AND user_id = ?
                """,
                (evidence_hash, interview_id, user_id),
            )
            idempotency_key = _analysis_job_idempotency_key(
                interview_id,
                evidence_hash,
            )
            cursor.execute(
                """
                SELECT job_id, status, retry_count, manual_retry_count
                FROM AnalysisJobs
                WHERE user_id = ? AND idempotency_key = ?
                LIMIT 1
                """,
                (user_id, idempotency_key),
            )
            existing = cursor.fetchone()

            if existing and existing[1] in {"queued", "running"}:
                conn.commit()
                return {
                    "job_id": existing[0],
                    "state": "already_running",
                    "reason": None,
                }

            if existing and (existing[2] or 0) >= ANALYSIS_MAX_RETRIES:
                manual_retries = int(existing[3] or 0)
                if not force_canonical_rebuild or manual_retries >= 3:
                    conn.commit()
                    return {
                        "job_id": existing[0],
                        "state": "retry_exhausted",
                        "reason": "automatic_retry_limit_reached",
                    }
                cursor.execute(
                    """
                    UPDATE AnalysisJobs
                    SET status = 'queued', retry_count = 0,
                        manual_retry_count = manual_retry_count + 1,
                        next_attempt_at = CURRENT_TIMESTAMP, error_message = NULL,
                        completed_at = NULL, updated_at = CURRENT_TIMESTAMP,
                        lease_owner = NULL, lease_expires_at = NULL,
                        heartbeat_at = NULL, trigger_reason = ?,
                        producer_version = ?, manifest_id = ?,
                        evidence_hash = ?, current_stage = 'evidence_load',
                        progress = 0
                    WHERE job_id = ?
                    """,
                    (
                        reason, ANALYSIS_STAGE_VERSION, manifest_id,
                        evidence_hash, existing[0],
                    ),
                )
                cursor.execute(
                    "UPDATE Interviews SET analysis_job_id = ? WHERE interview_id = ?",
                    (existing[0], interview_id),
                )
                conn.commit()
                return {
                    "job_id": existing[0],
                    "state": "queued",
                    "reason": "manual_reconciliation_retry",
                }

            if existing:
                cursor.execute(
                    """
                    UPDATE AnalysisJobs
                    SET status = 'queued', next_attempt_at = CURRENT_TIMESTAMP, error_message = NULL,
                        completed_at = NULL, updated_at = CURRENT_TIMESTAMP, lease_owner = NULL,
                        lease_expires_at = NULL, heartbeat_at = NULL,
                        trigger_reason = ?, producer_version = ?,
                        manifest_id = ?, evidence_hash = ?,
                        current_stage = 'evidence_load', progress = 0
                    WHERE job_id = ?
                    """,
                    (
                        reason, ANALYSIS_STAGE_VERSION, manifest_id, evidence_hash,
                        existing[0],
                    ),
                )
                cursor.execute(
                    "UPDATE Interviews SET analysis_job_id = ? WHERE interview_id = ?",
                    (existing[0], interview_id),
                )
                conn.commit()
                return {"job_id": existing[0], "state": "queued", "reason": None}

            job_id = str(uuid.uuid4())
            cursor.execute(
                """
                INSERT INTO AnalysisJobs (
                    job_id, interview_id, user_id, status, trigger_reason,
                    progress, retry_count, idempotency_key, evidence_hash, manifest_id,
                    producer_version, next_attempt_at, created_at, updated_at
                )
                VALUES (?, ?, ?, 'queued', ?, 0, 0, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """,
                (
                    job_id, interview_id, user_id, reason, idempotency_key,
                    evidence_hash, manifest_id, ANALYSIS_STAGE_VERSION,
                ),
            )
            cursor.execute(
                "UPDATE Interviews SET analysis_job_id = ? WHERE interview_id = ?",
                (job_id, interview_id),
            )
            conn.commit()
            return {"job_id": job_id, "state": "queued", "reason": None}
        except Exception:
            conn.rollback()
            raise
        finally:
            cursor.close()
            return_db_connection(conn)

    result = await asyncio.to_thread(_get_or_create_job)
    if result.get("state") not in {"queued", "already_running"}:
        logger.info(
            "Analysis enqueue resolved state=%s for %s",
            result.get("state"), stable_hash(interview_id, "interview"),
        )
    return result


async def enqueue_analysis(
    interview_id: str,
    user_id: str,
    reason: str = "session_end",
    *,
    force_canonical_rebuild: bool = False,
    return_result: bool = False,
) -> Any:
    """Compatibility wrapper for callers that only need the durable job id."""
    result = await enqueue_analysis_result(
        interview_id,
        user_id,
        reason,
        force_canonical_rebuild=force_canonical_rebuild,
    )
    if return_result:
        return result
    return str(result["job_id"]) if result.get("job_id") else None


async def operator_retry_analysis(interview_id: str, actor_user_id: str) -> Dict[str, Any]:
    """Requeue the same sealed analysis identity without duplicating a report."""
    def _retry() -> Dict[str, Any]:
        from database import get_db_connection, return_db_connection

        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("BEGIN IMMEDIATE")
            cursor.execute(
                """
                WITH latest_job AS (
                    SELECT job_id, interview_id, status, manual_retry_count, evidence_hash, manifest_id,
                           ROW_NUMBER() OVER (
                               PARTITION BY interview_id
                               ORDER BY created_at DESC, job_id DESC
                           ) AS job_rank
                    FROM AnalysisJobs
                    WHERE interview_id = ?
                )
                SELECT (i.attempt_status = 'completed' OR i.status IN ('completed', 'report_ready', 'partial', 'failed')) AS completed_attempt,
                       i.report_json, i.report_json_encrypted,
                       job.job_id, job.status, job.manual_retry_count, job.evidence_hash, job.manifest_id
                FROM Interviews i
                LEFT JOIN latest_job job
                  ON job.interview_id = i.interview_id AND job.job_rank = 1
                WHERE i.interview_id = ?
                """,
                (interview_id, interview_id),
            )
            row = cursor.fetchone()
            if not row:
                raise ValueError("analysis_not_found")
            if not bool(row[0]):
                raise ValueError("attempt_not_completed")
            if row[1] is not None or row[2] is not None:
                raise ValueError("report_already_published")
            if not row[3] or str(row[4] or "") != "failed":
                raise ValueError("analysis_not_failed")
            manual_retries = int(row[5] or 0)
            if manual_retries >= 3:
                raise ValueError("manual_retry_limit_reached")
            if not row[6] or not row[7]:
                raise ValueError("sealed_analysis_identity_missing")
            cursor.execute(
                """
                UPDATE AnalysisJobs
                SET status = 'queued', retry_count = 0,
                    manual_retry_count = manual_retry_count + 1,
                    next_attempt_at = CURRENT_TIMESTAMP, error_message = NULL,
                    current_stage = 'evidence_load', progress = 0,
                    completed_at = NULL, updated_at = CURRENT_TIMESTAMP,
                    lease_owner = NULL, lease_expires_at = NULL, heartbeat_at = NULL
                WHERE job_id = ?
                RETURNING job_id, manual_retry_count
                """,
                (row[3],),
            )
            retried = cursor.fetchone()
            cursor.execute(
                """
                UPDATE Interviews
                SET status = 'analysis_pending', analysis_status = 'queued', analysis_job_id = ?
                WHERE interview_id = ?
                """,
                (row[3], interview_id),
            )
            conn.commit()
            return {
                "job_id": str(retried[0]),
                "status": "queued",
                "manual_retry_count": int(retried[1] or 0),
                "operator_id_hash": stable_hash(actor_user_id, "operator"),
                "same_evidence_identity": True,
            }
        except Exception:
            conn.rollback()
            raise
        finally:
            cursor.close()
            return_db_connection(conn)

    return await asyncio.to_thread(_retry)


async def _record_worker_heartbeat(worker_id: str, worker_type: str = "analysis") -> None:
    await async_execute(
        """
        INSERT INTO WorkerHeartbeats (
            worker_id, worker_type, version, metadata, started_at, heartbeat_at
        ) VALUES (?, ?, ?, '{}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        ON CONFLICT (worker_id) DO UPDATE
        SET worker_type = EXCLUDED.worker_type,
            version = EXCLUDED.version,
            heartbeat_at = CURRENT_TIMESTAMP
        """,
        (worker_id, worker_type, ANALYSIS_STAGE_VERSION),
    )


async def claim_analysis_job(worker_id: str) -> Optional[tuple[str, str, str]]:
    return await async_execute(
        """
        UPDATE AnalysisJobs
        SET status = 'running',
            lease_owner = ?,
            lease_expires_at = datetime(CURRENT_TIMESTAMP, '+' || CAST(? AS TEXT) || ' seconds'),
            heartbeat_at = CURRENT_TIMESTAMP,
            started_at = COALESCE(started_at, CURRENT_TIMESTAMP),
            updated_at = CURRENT_TIMESTAMP
        WHERE job_id = (
            SELECT job_id
            FROM AnalysisJobs
            WHERE retry_count < ?
              AND COALESCE(next_attempt_at, CURRENT_TIMESTAMP) <= CURRENT_TIMESTAMP
              AND (
                  status = 'queued'
                  OR (status = 'running' AND lease_expires_at < CURRENT_TIMESTAMP)
              )
            ORDER BY created_at ASC
            LIMIT 1
        )
        RETURNING job_id, interview_id, user_id
        """,
        (worker_id, ANALYSIS_LEASE_SECONDS, ANALYSIS_MAX_RETRIES),
        fetchone=True,
    )


async def _claim_specific_analysis_job(job_id: str, worker_id: str) -> Optional[tuple[str, str, str]]:
    return await async_execute(
        """
        UPDATE AnalysisJobs
        SET status = 'running', lease_owner = ?,
            lease_expires_at = datetime(CURRENT_TIMESTAMP, '+' || CAST(? AS TEXT) || ' seconds'),
            heartbeat_at = CURRENT_TIMESTAMP, started_at = COALESCE(started_at, CURRENT_TIMESTAMP),
            updated_at = CURRENT_TIMESTAMP
        WHERE job_id = ?
          AND retry_count < ?
          AND COALESCE(next_attempt_at, CURRENT_TIMESTAMP) <= CURRENT_TIMESTAMP
          AND (status = 'queued' OR (status = 'running' AND lease_expires_at < CURRENT_TIMESTAMP))
        RETURNING job_id, interview_id, user_id
        """,
        (worker_id, ANALYSIS_LEASE_SECONDS, job_id, ANALYSIS_MAX_RETRIES),
        fetchone=True,
    )


async def _renew_analysis_lease(job_id: str, worker_id: str) -> None:
    row = await async_execute(
        """
        UPDATE AnalysisJobs
        SET lease_expires_at = datetime(CURRENT_TIMESTAMP, '+' || CAST(? AS TEXT) || ' seconds'),
            heartbeat_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
        WHERE job_id = ? AND status = 'running' AND lease_owner = ?
        RETURNING job_id
        """,
        (ANALYSIS_LEASE_SECONDS, job_id, worker_id),
        fetchone=True,
    )
    if not row:
        raise RuntimeError("analysis_job_lease_lost")


async def claim_report_side_effect(
    worker_id: str,
) -> Optional[tuple[str, str, str, str, str, Any, Any, int, int]]:
    return await async_execute(
        """
        UPDATE ReportSideEffectOutbox
        SET status = 'processing',
            attempt_count = attempt_count + 1,
            lease_owner = ?,
            lease_expires_at = datetime(CURRENT_TIMESTAMP, '+' || CAST(? AS TEXT) || ' seconds'),
            updated_at = CURRENT_TIMESTAMP
        WHERE event_id = (
            SELECT event_id
            FROM ReportSideEffectOutbox
            WHERE attempt_count < max_attempts
              AND available_at <= CURRENT_TIMESTAMP
              AND (
                  status = 'queued'
                  OR (status = 'processing' AND lease_expires_at < CURRENT_TIMESTAMP)
              )
            ORDER BY created_at ASC
            LIMIT 1
        )
        RETURNING event_id, event_type, analysis_id,
                  interview_id, user_id, payload_encrypted, payload,
                  attempt_count, max_attempts
        """,
        (worker_id, REPORT_SIDE_EFFECT_LEASE_SECONDS),
        fetchone=True,
    )


async def _renew_report_side_effect_lease(event_id: str, worker_id: str) -> None:
    renewed = await async_execute(
        """
        UPDATE ReportSideEffectOutbox
        SET lease_expires_at = datetime(CURRENT_TIMESTAMP, '+' || CAST(? AS TEXT) || ' seconds'),
            updated_at = CURRENT_TIMESTAMP
        WHERE event_id = ? AND status = 'processing' AND lease_owner = ?
        RETURNING event_id
        """,
        (REPORT_SIDE_EFFECT_LEASE_SECONDS, event_id, worker_id),
        fetchone=True,
    )
    if not renewed:
        raise RuntimeError("report_side_effect_lease_lost")


async def _complete_report_side_effect(
    event_id: str,
    worker_id: str,
    *,
    delivery_note: Optional[str] = None,
) -> None:
    completed = await async_execute(
        """
        UPDATE ReportSideEffectOutbox
        SET status = 'completed', completed_at = COALESCE(completed_at, CURRENT_TIMESTAMP),
            updated_at = CURRENT_TIMESTAMP, lease_owner = NULL, lease_expires_at = NULL,
            last_error = ?
        WHERE event_id = ? AND status = 'processing' AND lease_owner = ?
        RETURNING event_id
        """,
        (delivery_note, event_id, worker_id),
        fetchone=True,
    )
    if not completed:
        raise RuntimeError("report_side_effect_lease_lost")


async def _fail_report_side_effect(event_id: str, worker_id: str, exc: Exception) -> str:
    safe_error = f"{type(exc).__name__}:report_side_effect_failed"[:240]
    row = await async_execute(
        """
        UPDATE ReportSideEffectOutbox
        SET status = CASE
                WHEN attempt_count >= max_attempts THEN 'dead_letter'
                ELSE 'queued'
            END,
            available_at = CASE
                WHEN attempt_count >= max_attempts THEN available_at
                ELSE datetime(
                    CURRENT_TIMESTAMP,
                    '+' || CAST(MIN(1800, (1 << MAX(attempt_count - 1, 0)) * 5) AS TEXT) || ' seconds'
                )
            END,
            dead_letter_at = CASE
                WHEN attempt_count >= max_attempts THEN COALESCE(dead_letter_at, CURRENT_TIMESTAMP)
                ELSE NULL
            END,
            last_error = ?, updated_at = CURRENT_TIMESTAMP,
            lease_owner = NULL, lease_expires_at = NULL
        WHERE event_id = ? AND status = 'processing' AND lease_owner = ?
        RETURNING status
        """,
        (safe_error, event_id, worker_id),
        fetchone=True,
    )
    return str((row or ["lease_lost"])[0])


def _acquire_report_side_effect_fence(interview_id: str) -> tuple[Any, Any]:
    from database import get_db_connection

    conn = get_db_connection()
    cursor = conn.cursor()
    # SQLite serializes the publication transaction itself; worker claims and
    # unique publication keys provide the cross-thread idempotency fence.
    cursor.execute("BEGIN IMMEDIATE")
    return conn, cursor


def _release_report_side_effect_fence(lock: tuple[Any, Any]) -> None:
    from database import return_db_connection

    conn, cursor = lock
    try:
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()
        return_db_connection(conn)


async def process_report_side_effect(
    event: tuple[str, str, str, str, str, Any, Any, int, int],
    worker_id: str,
) -> None:
    (
        event_id, event_type, analysis_id, interview_id, user_id,
        encrypted_payload, legacy_payload, _, _,
    ) = event
    lock: Optional[tuple[Any, Any]] = None
    try:
        if str(event_type or "") != "improve_sync":
            raise RuntimeError("unsupported_report_side_effect_type")
        lock = await asyncio.to_thread(
            _acquire_report_side_effect_fence,
            interview_id,
        )
        current = await async_execute(
            """
            SELECT is_current, status, producer_version,
                   evidence_status, overall_score
            FROM SessionPerformanceAnalyses
            WHERE analysis_id = ? AND interview_id = ? AND user_id = ?
            """,
            (analysis_id, interview_id, user_id),
            fetchone=True,
        )
        if not current:
            raise RuntimeError("report_side_effect_analysis_missing")
        if (
            not bool(current[0])
            or str(current[1] or "") != "ready"
            or str(current[2] or "") != ANALYSIS_STAGE_VERSION
        ):
            await _complete_report_side_effect(
                event_id,
                worker_id,
                delivery_note="superseded_before_delivery",
            )
            return

        # Improve is downstream of a gradable canonical report.  A ready
        # publication can still legitimately carry insufficient, draft-only,
        # or run-only evidence; those states must remain visible in Report and
        # Performance without generating coaching exercises.
        evidence_status = str(current[3] or "") if len(current) > 3 else "sufficient"
        overall_score = current[4] if len(current) > 4 else True
        if evidence_status != "sufficient" or overall_score is None:
            await _complete_report_side_effect(
                event_id,
                worker_id,
                delivery_note="improve_not_available_for_insufficient_evidence",
            )
            return

        payload = decrypt_json_field(encrypted_payload, legacy_payload, {})
        if not isinstance(payload, dict) or str(payload.get("analysis_id") or "") != analysis_id:
            raise RuntimeError("report_side_effect_payload_invalid")
        observations = [
            item for item in (payload.get("observations") or [])
            if isinstance(item, dict)
        ]
        weak_topics = [
            item for item in (payload.get("weak_topics") or [])
            if isinstance(item, dict)
        ]
        mode = "technical" if str(payload.get("mode") or "") == "technical" else "mock"

        await retire_superseded_analysis_evidence(interview_id, analysis_id)
        await _renew_report_side_effect_lease(event_id, worker_id)
        await persist_weakness_states(user_id, analysis_id, interview_id, observations)
        await _renew_report_side_effect_lease(event_id, worker_id)
        await validate_mission_with_analysis(
            user_id, interview_id, analysis_id, mode, observations
        )
        await _renew_report_side_effect_lease(event_id, worker_id)
        await _queue_learning_from_analysis(
            interview_id,
            user_id,
            suppress_errors=False,
        )
        await _renew_report_side_effect_lease(event_id, worker_id)

        report_focus_mission = None
        if mode == "technical":
            report_focus_mission = await ensure_mission_from_technical_report(
                user_id,
                interview_id,
                analysis_id,
                weak_topics,
            )
        if not report_focus_mission:
            await ensure_mission_from_weakness(
                user_id,
                interview_id,
                analysis_id,
                mode,
            )
        await _complete_report_side_effect(event_id, worker_id)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        outcome = await _fail_report_side_effect(event_id, worker_id, exc)
        logger.warning(
            "Report side-effect delivery %s for %s (state=%s)",
            type(exc).__name__, stable_hash(interview_id, "interview"), outcome,
        )
    finally:
        if lock is not None:
            await asyncio.to_thread(
                _release_report_side_effect_fence,
                lock,
            )


async def analysis_worker_loop(
    worker_id: str,
    *,
    stop_event: Optional[asyncio.Event] = None,
    idle_seconds: float = 1.0,
) -> None:
    next_retention_sweep = 0.0
    while not (stop_event and stop_event.is_set()):
        try:
            now = asyncio.get_running_loop().time()
            if now >= next_retention_sweep:
                await _purge_expired_media_assets()
                next_retention_sweep = now + 60.0
            await _record_worker_heartbeat(worker_id)
            did_work = False
            side_effect = await claim_report_side_effect(worker_id)
            if side_effect:
                did_work = True
                await process_report_side_effect(side_effect, worker_id)
            claimed = await claim_analysis_job(worker_id)
            if claimed:
                did_work = True
                await run_analysis_job(claimed[0], worker_id=worker_id, claimed_job=claimed)
            if not did_work:
                await asyncio.sleep(idle_seconds)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Analysis worker iteration failed")
            await asyncio.sleep(idle_seconds)


async def _purge_expired_media_assets() -> int:
    """Delete due local-manifest rows; Option A never stores raw media bytes."""
    remove_all_video = settings.RAW_VIDEO_RETENTION_HOURS <= 0
    remove_all_audio = settings.AUDIO_RETENTION_DAYS <= 0
    rows = await async_execute(
        """
        DELETE FROM InterviewMediaAssets
        WHERE storage_provider = 'local_manifest'
          AND (
              (delete_after IS NOT NULL AND delete_after <= CURRENT_TIMESTAMP)
              OR (status = 'pending' AND created_at < datetime(CURRENT_TIMESTAMP, '-1 hour'))
              OR (? AND media_kind = 'video')
              OR (? AND media_kind = 'audio')
          )
        RETURNING asset_id
        """,
        (remove_all_video, remove_all_audio),
        fetchall=True,
    )
    return len(rows or [])


async def analysis_job_reconciler(interval_seconds: int = 20) -> None:
    """Backward-compatible worker entrypoint; API processes must not start it."""
    await analysis_worker_loop(f"legacy-analysis-{uuid.uuid4().hex[:10]}", idle_seconds=float(interval_seconds))


async def _queue_learning_from_analysis(
    interview_id: str,
    user_id: str,
    *,
    suppress_errors: bool = True,
) -> None:
    try:
        profile_row = await async_execute(
            """
            SELECT u.profile_json, u.resume_json, s.resume_payload_encrypted
            FROM UserInfo u
            LEFT JOIN AttemptContextSnapshots s
              ON s.interview_id = ? AND s.user_id = u.user_id
            WHERE u.user_id = ?
            """,
            (interview_id, user_id),
            fetchone=True,
        )
        profile_context: Dict[str, Any] = {}
        if profile_row:
            if profile_row[2]:
                try:
                    profile_context = json.loads(_decrypt_storage_text(profile_row[2]))
                except Exception:
                    profile_context = {}
            if not profile_context:
                profile_context = decrypt_json(profile_row[0]) or decrypt_json(profile_row[1]) or {}
            if not isinstance(profile_context, dict):
                profile_context = {}
        assessed_turns = [_score_turn(turn) for turn in await _load_turns(interview_id)]
        learning_turns = [
            {
                **turn,
                "topic_label": turn.get("topic"),
                "score": turn.get("overall_score"),
            }
            for turn in assessed_turns
            if turn.get("overall_score") is not None and not turn.get("insufficient_evidence")
        ]
        await ingest_interview_evidence(user_id, interview_id, learning_turns, profile_context)
    except Exception:
        if not suppress_errors:
            raise
        logger.warning("Learning exercise generation skipped for %s", stable_hash(interview_id, "interview"))

def _sha256_json(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _encrypted_bytes(value: Any) -> bytes:
    return encrypt_data(_json_dumps(value)).encode("utf-8")


def _decrypt_storage_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, memoryview):
        value = value.tobytes()
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    return decrypt_data(str(value))


def _technical_round_id(provenance: Any) -> Optional[str]:
    if not isinstance(provenance, dict):
        return None
    value = provenance.get("round_id") or provenance.get("technical_round_id")
    return str(value) if value else None


def _technical_source_text(encrypted: Any, legacy_code: Any = None, legacy_excerpt: Any = None) -> str:
    if encrypted:
        try:
            decrypted = _decrypt_storage_text(encrypted)
            if decrypted and decrypted != "[encrypted]":
                return decrypted
        except Exception:
            logger.warning("Technical source payload could not be decrypted", exc_info=True)
    for value in (legacy_code, legacy_excerpt):
        text = str(value or "")
        if text and text != "[encrypted]":
            return text
    return ""


def _technical_source_excerpt(source_code: str, legacy_excerpt: Any = None, limit: int = 3000) -> str:
    excerpt = str(legacy_excerpt or "")
    if excerpt and excerpt != "[encrypted]":
        return excerpt
    if len(source_code) <= limit:
        return source_code
    return source_code[:limit].rsplit("\n", 1)[0]


def _candidate_authored_technical_draft(source_code: Any, starter_code: Any, metadata: Any) -> bool:
    if isinstance(metadata, dict) and metadata.get("candidate_edited") is False:
        return False
    normalized_source = str(source_code or "").replace("\r\n", "\n").replace("\r", "\n")
    normalized_starter = str(starter_code or "").replace("\r\n", "\n").replace("\r", "\n")
    return bool(normalized_source) and normalized_source != normalized_starter


def _safe_report_payload(report: Dict[str, Any]) -> Dict[str, Any]:
    allowed = {
        "version", "interview_id", "analysis_id", "report_type", "profile_type",
        "overall_score", "score_breakdown", "counts", "dimension_scores",
        "behavioral_metrics", "technical_process", "evidence_summary", "evidence_status",
        "report_state", "strengths", "summary", "duration_seconds", "time_used_seconds",
        "time_allowed_seconds", "round_analysis", "timeline", "self_review_summary",
        "candidate_visible_self_review", "ai_enhanced", "ai_provider_policy",
        "ai_fallback_reason", "evidence_hash", "evidence_manifest_id",
        "generation_provenance", "score_provenance", "findings",
    }
    safe = {key: value for key, value in report.items() if key in allowed}
    technical = report.get("technical")
    if isinstance(technical, dict):
        safe["technical"] = {
            key: value
            for key, value in technical.items()
            if key not in {"problems", "test_matrix", "hidden_tests", "reference_solution"}
        }
        safe["technical"]["problems"] = [
            {
                key: value
                for key, value in item.items()
                if key not in {
                    "source_code", "prompt", "hidden_tests", "reference_solution", "solution",
                }
            }
            for item in technical.get("problems") or []
            if isinstance(item, dict)
        ]
    for key in ("questions", "per_turn_feedback"):
        safe[key] = [
            {
                item_key: item_value
                for item_key, item_value in item.items()
                if item_key not in {
                    "response", "transcript", "what_candidate_answered",
                    "hidden_tests", "reference_solution", "solution",
                }
            }
            for item in report.get(key) or []
            if isinstance(item, dict)
        ]
    findings = report.get("findings")
    if isinstance(findings, list):
        safe["findings"] = [
            {
                key: value
                for key, value in item.items()
                if key in {
                    "finding_key", "id", "title", "label", "what_happened",
                    "detail", "summary", "why_matters", "evidence_ids",
                }
            }
            for item in findings
            if isinstance(item, dict)
        ]
    return safe


def _report_has_noncritical_degradation(
    report: Dict[str, Any],
    stage_outputs: Dict[str, Dict[str, Any]],
) -> bool:
    """Keep deterministic evidence usable while making enhancement failures visible."""
    if any(
        isinstance(output, dict) and bool(output.get("error"))
        for output in stage_outputs.values()
    ):
        return True
    fallback_reason = str(report.get("ai_fallback_reason") or "").strip()
    return bool(fallback_reason and fallback_reason != "no_candidate_evidence")


def _valid_candidate_report(report: Any, interview_id: str) -> bool:
    """Reject failed or cross-session report payloads before publication."""
    if not isinstance(report, dict) or report.get("error"):
        return False
    if str(report.get("interview_id") or "") != str(interview_id):
        return False
    if str(report.get("report_type") or "").lower() not in {"behavioral", "technical"}:
        return False
    if not isinstance(report.get("evidence_status"), dict):
        return False
    overall_score = report.get("overall_score")
    return overall_score is None or isinstance(overall_score, (int, float))


def _stage_provenance(stage: str, output: Dict[str, Any], input_hash: str) -> Dict[str, Any]:
    ai_enhanced = stage in {"report_generation", "semantic_enhancement"} and bool(output.get("ai_enhanced"))
    return {
        "pipeline_version": ANALYSIS_STAGE_VERSION,
        "stage": stage,
        "input_hash": input_hash,
        "engine": "local_provider_narrative_enhancement" if ai_enhanced else "deterministic_inter_pipeline",
        "model": get_local_preferences().get("model") if ai_enhanced else None,
        "prompt_version": "report-narrative-v1" if ai_enhanced else None,
        "evaluator_versions": sorted({
            str(item.get("evaluator_version"))
            for item in (output.get("turns") or [])
            if isinstance(item, dict) and item.get("evaluator_version")
        }),
    }


def _collect_report_evidence_ids(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"response_id", "submission_id"} and item:
                found.add(str(item))
            elif key == "evidence_ids" and isinstance(item, list):
                found.update(str(entry) for entry in item if entry)
            else:
                found.update(_collect_report_evidence_ids(item))
    elif isinstance(value, list):
        for item in value:
            found.update(_collect_report_evidence_ids(item))
    return found


def _score_provenance(report: Dict[str, Any], evidence_hash: str) -> Dict[str, Any]:
    evidence_ids = sorted(_collect_report_evidence_ids(report))
    provenance: Dict[str, Any] = {}
    if report.get("overall_score") is not None:
        provenance["overall_score"] = {
            "source": "deterministic_report",
            "computation_version": ANALYSIS_STAGE_VERSION,
            "evidence_hash": evidence_hash,
            "evidence_ids": evidence_ids,
        }
    for key, value in (report.get("dimension_scores") or {}).items():
        if value is None:
            continue
        provenance[f"dimension_scores.{key}"] = {
            "source": "persisted_evaluator_or_deterministic_execution",
            "computation_version": ANALYSIS_STAGE_VERSION,
            "evidence_hash": evidence_hash,
            "evidence_ids": evidence_ids,
        }
    return provenance


def _contains_hidden_detail_leak(value: Any) -> bool:
    private_keys = {
        "hidden_details", "hidden_tests", "hidden_cases", "cases_encrypted",
        "reference_solution", "mutation_cases", "result_json", "all_submissions",
    }
    if isinstance(value, dict):
        if any(
            key in private_keys and item is not None and item != [] and item != {}
            for key, item in value.items()
        ):
            return True
        return any(_contains_hidden_detail_leak(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_hidden_detail_leak(item) for item in value)
    return False


async def _validate_report_for_publication(
    report: Dict[str, Any],
    *,
    interview_id: str,
    user_id: str,
    evidence_hash: str,
    manifest_id: str,
) -> None:
    ownership = await async_execute(
        """
        SELECT attempt_status, completion_kind, evidence_hash
        FROM Interviews WHERE interview_id = ? AND user_id = ?
        """,
        (interview_id, user_id), fetchone=True,
    )
    if not ownership or str(ownership[2] or "") != evidence_hash:
        raise RuntimeError("report_evidence_hash_or_ownership_mismatch")
    manifest = await async_execute(
        """
        SELECT manifest_json FROM EvidenceManifests
        WHERE manifest_id = ? AND interview_id = ? AND user_id = ? AND evidence_hash = ?
        """,
        (manifest_id, interview_id, user_id, evidence_hash), fetchone=True,
    )
    if not manifest:
        raise RuntimeError("report_evidence_manifest_missing")
    manifest_json = _json_value(manifest[0], {})
    valid_ids = {
        str(item.get("evidence_id"))
        for item in manifest_json.get("items", [])
        if isinstance(item, dict) and item.get("evidence_id")
    }
    missing_ids = sorted(_collect_report_evidence_ids(report) - valid_ids)
    if missing_ids:
        raise RuntimeError("report_references_unsealed_evidence")
    if report.get("overall_score") is not None and str(ownership[0] or "") != "completed":
        raise RuntimeError("official_score_requires_completed_attempt")
    expected_score_keys = set()
    if report.get("overall_score") is not None:
        expected_score_keys.add("overall_score")
    expected_score_keys.update(
        f"dimension_scores.{key}"
        for key, value in (report.get("dimension_scores") or {}).items()
        if value is not None
    )
    if not expected_score_keys.issubset(set((report.get("score_provenance") or {}).keys())):
        raise RuntimeError("report_score_provenance_missing")
    if _contains_hidden_detail_leak(report):
        raise RuntimeError("report_hidden_test_detail_leak")
    if report.get("evidence_hash") != evidence_hash or report.get("evidence_manifest_id") != manifest_id:
        raise RuntimeError("report_provenance_mismatch")


def _safe_stage_payload(stage: str, output: Dict[str, Any]) -> Dict[str, Any]:
    if stage == "evidence_load":
        return {
            "transcription": _safe_stage_payload("transcription_diarization", output.get("transcription") or {}),
            "audio": output.get("audio") or {},
            "video": output.get("video") or {},
        }
    if stage == "transcription_diarization":
        return {key: value for key, value in output.items() if key not in {"transcript", "speaker_segments"}}
    if stage in {"nlp_content", "transcript_analysis"}:
        return {
            **{key: value for key, value in output.items() if key != "turns"},
            "turns": [
                {
                    key: turn.get(key)
                    for key in (
                        "response_id", "question_spec_id", "topic", "taxonomy_keys",
                        "star_score", "communication_score", "technical_score",
                        "overall_score", "confidence", "insufficient_evidence",
                        "answer_quality_flags", "rubric_scores", "evaluator_version",
                    )
                }
                for turn in output.get("turns", [])
            ],
        }
    if stage in {"technical_code", "technical_analysis"}:
        safe = {
            key: value
            for key, value in output.items()
            if key not in {
                "submissions", "final_submissions", "all_submissions", "run_events",
                "drafts", "typed_responses", "source_code", "source_excerpt",
                "rounds",
            }
        }
        safe["test_matrix"] = [
            {
                key: value
                for key, value in item.items()
                if key not in {"source_code", "source_excerpt", "metadata", "result_json"}
            }
            for item in output.get("test_matrix") or []
            if isinstance(item, dict)
        ]
        return safe
    if stage in {"report_generation", "deterministic_report", "semantic_enhancement", "report_validation", "complete"}:
        return _safe_report_payload(output)
    return output


def _legacy_stage_outputs(outputs: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    evidence = outputs.get("evidence_load") or {}
    return {
        "transcription_diarization": evidence.get("transcription") or {},
        "audio_features": evidence.get("audio") or {},
        "video_features": evidence.get("video") or {},
        "nlp_content": outputs.get("transcript_analysis") or {},
        "technical_code": outputs.get("technical_analysis") or {},
        "self_review_signals": outputs.get("self_review_summary") or {},
        "report_generation": (
            outputs.get("complete")
            or outputs.get("report_validation")
            or outputs.get("semantic_enhancement")
            or outputs.get("deterministic_report")
            or {}
        ),
    }


def _turn_observations(turns: List[Dict[str, Any]], mode: str = "mock") -> List[Dict[str, Any]]:
    observations: List[Dict[str, Any]] = []
    technical_types = {
        "technical_concept", "system_design", "ml", "backend", "database",
        "os", "network", "oop", "sql", "technical_explanation",
    }
    for turn in turns:
        if turn.get("overall_score") is None:
            continue
        taxonomy = turn.get("taxonomy_keys") or []
        if not isinstance(taxonomy, list):
            taxonomy = []
        skill_keys = [str(item) for item in taxonomy if str(item).strip()]
        if not skill_keys:
            topic = re.sub(r"[^a-z0-9]+", "-", str(turn.get("topic") or "general").lower()).strip("-")
            skill_keys = [f"interview:{topic or 'general'}"]
        provenance = turn.get("provenance") or {}
        round_id = _technical_round_id(provenance)
        if mode == "technical" and not round_id:
            continue
        for skill_key in skill_keys:
            normalized_skill_key = skill_key
            if mode != "technical" and normalized_skill_key.lower().startswith(("technical:", "algorithm:", "debugging:")):
                normalized_skill_key = f"interview:{re.sub(r'[^a-z0-9]+', '-', normalized_skill_key.lower()).strip('-')}"
            observations.append({
                "skill_key": normalized_skill_key,
                "source_key": turn.get("response_id"),
                "source_kind": (
                    "technical_response"
                    if mode == "technical" and str(turn.get("question_type") or "").lower() in technical_types
                    else "interview_response"
                ),
                "evidence_type": "interview",
                "response_id": turn.get("response_id"),
                "round_id": round_id,
                "question_spec_id": turn.get("question_spec_id"),
                "question": turn.get("question"),
                "topic": turn.get("topic"),
                "score": turn.get("overall_score"),
                "confidence": turn.get("confidence_value") or turn.get("confidence"),
                "flags": turn.get("answer_quality_flags") or [],
                "covered_point_ids": (turn.get("evidence_basis") or {}).get("covered_point_ids") or [],
                "missed_point_ids": (turn.get("evidence_basis") or {}).get("missed_point_ids") or [],
            })
    return observations


async def _stage_canonical_performance(
    *,
    interview_id: str,
    user_id: str,
    stage_outputs: Dict[str, Dict[str, Any]],
    report: Dict[str, Any],
    job_evidence_hash: str,
) -> Dict[str, Any]:
    meta = await async_execute(
        """
        SELECT interview_mode, interview_type, duration_seconds
        FROM Interviews WHERE interview_id = ? AND user_id = ?
        """,
        (interview_id, user_id), fetchone=True,
    )
    report_type = str(report.get("report_type") or "").lower()
    interview_type = str((meta or [None, ""])[1] or "").lower()
    mode = "technical" if report_type == "technical" or "technical" in interview_type else "mock"
    turns = list((stage_outputs.get("nlp_content") or {}).get("turns") or [])
    technical = stage_outputs.get("technical_code") or {}
    observations = _turn_observations(turns, mode)
    observed_response_ids = {
        str(item.get("response_id"))
        for item in observations
        if item.get("response_id")
    }
    for item in technical.get("test_matrix") or []:
        score = item.get("final_pass_rate")
        source_kind = "technical_execution"
        if score is None and item.get("evidence_state") == "assessed_response":
            score = item.get("score")
            source_kind = "technical_response"
        if score is None:
            continue
        if source_kind == "technical_response" and item.get("response_id") in observed_response_ids:
            continue
        observations.append({
            "skill_key": f"technical:{item.get('algorithm_pattern') or item.get('round_type') or 'coding'}",
            "source_key": item.get("round_id") or item.get("response_id"),
            "source_kind": source_kind,
            "evidence_type": "interview",
            "round_id": item.get("round_id"),
            "response_id": item.get("response_id"),
            "question_spec_id": item.get("question_spec_id"),
            "score": score,
            "confidence": 0.9,
            "flags": [] if float(score or 0) >= 75 else [
                "technical-response-needs-work" if source_kind == "technical_response" else "test-case-failure"
            ],
        })

    question_analyses = [
        {
            "response_id": turn.get("response_id"),
            "round_id": _technical_round_id(turn.get("provenance") or {}),
            "question_spec_id": turn.get("question_spec_id"),
            "question": turn.get("question"),
            "taxonomy_keys": turn.get("taxonomy_keys") or [],
            "skill": turn.get("topic"),
            "project_facet": turn.get("blueprint_section_id"),
            "user_answer": turn.get("response"),
            "expected_point_ids": list(dict.fromkeys(
                ((turn.get("evidence_basis") or {}).get("covered_point_ids") or [])
                + ((turn.get("evidence_basis") or {}).get("missed_point_ids") or [])
            )),
            "covered_point_ids": (turn.get("evidence_basis") or {}).get("covered_point_ids") or [],
            "missed_point_ids": (turn.get("evidence_basis") or {}).get("missed_point_ids") or [],
            "incorrect_claim_ids": (turn.get("evidence_basis") or {}).get("incorrect_claim_ids") or [],
            "contradictions": (turn.get("evidence_basis") or {}).get("contradictions") or [],
            "follow_up_chain": {
                "parent_question_id": turn.get("parent_question_id"),
                "decision": (turn.get("evidence_basis") or {}).get("follow_up") or {},
            },
            "evidence_quotes": turn.get("evidence") or [],
            "dimension_scores": turn.get("rubric_scores") or {},
            "overall_score": turn.get("overall_score"),
            "provisional_score": turn.get("provisional_score"),
            "confidence": turn.get("confidence_value"),
            "insufficient_evidence": turn.get("insufficient_evidence"),
            "answer_quality_flags": turn.get("answer_quality_flags") or [],
            "evaluator_version": turn.get("evaluator_version"),
        }
        for turn in turns
    ]
    has_authoritative_turn = any(
        turn.get("overall_score") is not None
        and not turn.get("insufficient_evidence")
        for turn in turns
    )
    if technical.get("draft_or_run_only") and not technical.get("submission_count"):
        evidence_status = "draft_or_run_only"
    elif has_authoritative_turn or technical.get("submission_count"):
        evidence_status = "sufficient"
    else:
        evidence_status = "insufficient_evidence"
    evaluator_versions = sorted({str(turn.get("evaluator_version")) for turn in turns if turn.get("evaluator_version")})
    canonical = {
        "schema_version": SESSION_PERFORMANCE_VERSION,
        "mode": mode,
        "interview_id": interview_id,
        "question_analyses": question_analyses,
        "measured_communication": {
            "audio": stage_outputs.get("audio_features") or {},
            "video": stage_outputs.get("video_features") or {},
        },
        "technical": technical,
        "integrity": stage_outputs.get("self_review_signals") or {},
        "dimension_scores": report.get("dimension_scores") or {},
        "overall_score": report.get("overall_score"),
        "evidence_status": evidence_status,
        "evaluator_versions": evaluator_versions,
        "taxonomy_version": TAXONOMY_VERSION,
        "rubric_version": RUBRIC_VERSION,
        "report": report,
    }
    evidence_index = {
        "responses": [
            {
                "response_id": item.get("response_id"),
                "round_id": item.get("round_id"),
                "question_spec_id": item.get("question_spec_id"),
                "taxonomy_keys": item.get("taxonomy_keys") or [],
                "evidence_quotes": item.get("evidence_quotes") or [],
            }
            for item in question_analyses
        ],
        "technical_rounds": [
            {
                "round_id": item.get("round_id"),
                "submission_id": item.get("submission_id"),
                "response_id": item.get("response_id"),
                "response_ids": item.get("response_ids") or [],
                "run_id": item.get("run_id") or item.get("latest_run_id"),
                "snapshot_id": item.get("snapshot_id"),
                "evidence_state": item.get("evidence_state"),
                "has_candidate_evidence": item.get("evidence_state") not in {None, "no_evidence"},
                "final_verdict": item.get("final_verdict"),
                "reasoning_evidence_ids": next((
                    reasoning.get("evidence_ids") or []
                    for reasoning in technical.get("reasoning_evidence") or []
                    if reasoning.get("round_id") == item.get("round_id")
                ), []),
            }
            for item in technical.get("test_matrix") or []
        ],
        "technical_reasoning": [
            {
                "round_id": item.get("round_id"),
                "evidence_ids": item.get("evidence_ids") or [],
                "evidence_types": item.get("evidence_types") or [],
            }
            for item in technical.get("reasoning_evidence") or []
            if item.get("evidence_ids")
        ],
        "technical_runs": [
            {
                "run_id": item.get("run_id"),
                "round_id": item.get("round_id"),
            }
            for item in technical.get("run_events") or []
            if item.get("run_id")
        ],
        "technical_drafts": [
            {
                "snapshot_id": item.get("snapshot_id"),
                "round_id": item.get("round_id"),
            }
            for item in technical.get("drafts") or []
            if item.get("snapshot_id")
        ],
    }
    safe_canonical = {
        key: value
        for key, value in canonical.items()
        if key not in {"question_analyses", "technical", "report"}
    }
    safe_canonical["question_count"] = len(question_analyses)
    safe_canonical["technical_evidence_count"] = len(technical.get("test_matrix") or [])
    safe_evidence_index = {
        "response_ids": [item.get("response_id") for item in question_analyses if item.get("response_id")],
        "round_ids": [
            item.get("round_id")
            for item in technical.get("test_matrix") or []
            if item.get("round_id") and item.get("evidence_state") != "no_evidence"
        ],
        "submission_ids": [
            item.get("submission_id")
            for item in technical.get("test_matrix") or []
            if item.get("submission_id")
        ],
        "reasoning_evidence_ids": [
            evidence_id
            for item in technical.get("reasoning_evidence") or []
            for evidence_id in (item.get("evidence_ids") or [])
        ],
        "run_ids": [
            item.get("run_id")
            for item in technical.get("run_events") or []
            if item.get("run_id")
        ],
        "snapshot_ids": [
            item.get("snapshot_id")
            for item in technical.get("drafts") or []
            if item.get("snapshot_id")
        ],
    }
    evidence_hash = _sha256_json({
        "job_evidence_hash": job_evidence_hash,
        "evaluator_versions": evaluator_versions,
        "question_assessments": [
            (item.get("response_id"), item.get("overall_score"), item.get("evaluator_version"))
            for item in question_analyses
        ],
        "technical": {
            "submissions_or_rounds": (
                safe_evidence_index["submission_ids"]
                or safe_evidence_index["round_ids"]
            ),
            "reasoning_evidence_ids": safe_evidence_index["reasoning_evidence_ids"],
            "run_ids": safe_evidence_index["run_ids"],
            "snapshot_ids": safe_evidence_index["snapshot_ids"],
        },
    })
    # Keep the legacy JSON columns as non-sensitive markers. The complete
    # candidate report and evidence graph live in the encrypted companion
    # columns; retaining a second plaintext copy defeats local-at-rest
    # protection and makes raw SQLite backups disclose interview content.
    encrypted_column_marker = "[encrypted]"
    safe_canonical_json = encrypted_column_marker
    safe_evidence_index_json = encrypted_column_marker
    canonical_encrypted = _encrypted_bytes(canonical)
    evidence_index_encrypted = _encrypted_bytes(evidence_index)

    def _stage_revision() -> tuple[str, bool, bool]:
        from database import get_db_connection, return_db_connection

        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("BEGIN IMMEDIATE")
            cursor.execute(
                """
                SELECT analysis_id, evidence_hash, revision_no,
                       analysis_json_encrypted, evidence_index_encrypted,
                       producer_version, status
                FROM SessionPerformanceAnalyses
                WHERE interview_id = ? AND mode = ?
                  AND schema_version = ? AND is_current = TRUE
                """,
                (interview_id, mode, SESSION_PERFORMANCE_VERSION),
            )
            existing = cursor.fetchone()
            if (
                existing
                and str(existing[1]) == evidence_hash
                and existing[3] is not None
                and existing[4] is not None
                and str(existing[5] or "") == ANALYSIS_STAGE_VERSION
                and str(existing[6] or "") == "ready"
            ):
                conn.commit()
                return str(existing[0]), False, True

            previous_analysis_id = str(existing[0]) if existing else None
            cursor.execute(
                """
                SELECT analysis_id
                FROM SessionPerformanceAnalyses
                WHERE interview_id = ? AND mode = ?
                  AND schema_version = ? AND evidence_hash = ?
                  AND producer_version = ? AND status = 'staged'
                ORDER BY revision_no DESC
                LIMIT 1
                """,
                (
                    interview_id, mode, SESSION_PERFORMANCE_VERSION,
                    evidence_hash, ANALYSIS_STAGE_VERSION,
                ),
            )
            staged = cursor.fetchone()
            if staged:
                cursor.execute(
                    """
                    UPDATE SessionPerformanceAnalyses
                    SET model = ?, analysis_json = ?,
                        evidence_index_json = ?,
                        analysis_json_encrypted = ?,
                        evidence_index_encrypted = ?,
                        overall_score = ?, evaluator_version = ?,
                        taxonomy_version = ?, rubric_version = ?,
                        duration_seconds = ?, evidence_status = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE analysis_id = ? AND status = 'staged'
                    """,
                    (
                        ",".join(evaluator_versions) or None,
                        safe_canonical_json, safe_evidence_index_json,
                        canonical_encrypted, evidence_index_encrypted,
                        report.get("overall_score"),
                        ",".join(evaluator_versions) or "none",
                        TAXONOMY_VERSION, RUBRIC_VERSION,
                        (meta or [None, None, None])[2], evidence_status,
                        staged[0],
                    ),
                )
                conn.commit()
                return str(staged[0]), False, False

            cursor.execute(
                """
                SELECT COALESCE(MAX(revision_no), 0)
                FROM SessionPerformanceAnalyses
                WHERE interview_id = ? AND mode = ? AND schema_version = ?
                """,
                (interview_id, mode, SESSION_PERFORMANCE_VERSION),
            )
            next_revision = int((cursor.fetchone() or [0])[0] or 0) + 1

            analysis_id = str(uuid.uuid4())
            cursor.execute(
                """
                INSERT INTO SessionPerformanceAnalyses (
                    analysis_id, user_id, interview_id, mode, schema_version,
                    evidence_hash, status, model, analysis_json, evidence_index_json,
                    analysis_json_encrypted, evidence_index_encrypted, overall_score,
                    evaluator_version, taxonomy_version, rubric_version,
                    duration_seconds, evidence_status, revision_no, is_current,
                    supersedes_analysis_id, producer_version, created_at, updated_at
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, 'staged', ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, FALSE, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                )
                """,
                (
                    analysis_id, user_id, interview_id, mode,
                    SESSION_PERFORMANCE_VERSION, evidence_hash,
                    ",".join(evaluator_versions) or None,
                        safe_canonical_json, safe_evidence_index_json,
                    canonical_encrypted, evidence_index_encrypted,
                    report.get("overall_score"),
                    ",".join(evaluator_versions) or "none",
                    TAXONOMY_VERSION, RUBRIC_VERSION,
                    (meta or [None, None, None])[2], evidence_status,
                    next_revision, previous_analysis_id, ANALYSIS_STAGE_VERSION,
                ),
            )
            conn.commit()
            return analysis_id, True, False
        except Exception:
            conn.rollback()
            raise
        finally:
            cursor.close()
            return_db_connection(conn)

    analysis_id, created, already_published = await asyncio.to_thread(_stage_revision)
    return {
        "analysis_id": analysis_id,
        "evidence_hash": evidence_hash,
        "created": created,
        "already_published": already_published,
        "mode": mode,
        "observations": observations,
        "evidence_status": evidence_status,
    }


def _report_publication_key(analysis_id: str) -> str:
    return f"report:{analysis_id}:candidate"


async def _stage_candidate_report_artifact(
    *,
    interview_id: str,
    user_id: str,
    analysis_id: str,
    report: Dict[str, Any],
    safe_report: Dict[str, Any],
    report_encrypted: bytes,
    manifest_evidence_hash: str,
    canonical_evidence_hash: str,
) -> Dict[str, str]:
    publication_key = _report_publication_key(analysis_id)
    default_artifact_id = str(uuid.uuid5(uuid.NAMESPACE_URL, publication_key))

    def _stage() -> Dict[str, str]:
        from database import get_db_connection, return_db_connection

        # Keep the closure's artifact identity explicit.  Assigning to the
        # outer name in the existing-row branch would make it a local and
        # crash first-time publication with UnboundLocalError.
        artifact_id_for_stage = default_artifact_id
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("BEGIN IMMEDIATE")
            cursor.execute(
                """
                SELECT status, is_current, evidence_hash, producer_version
                FROM SessionPerformanceAnalyses
                WHERE analysis_id = ? AND interview_id = ? AND user_id = ?
                """,
                (analysis_id, interview_id, user_id),
            )
            analysis = cursor.fetchone()
            if not analysis:
                raise RuntimeError("staged_analysis_not_found")
            if str(analysis[2] or "") != canonical_evidence_hash:
                raise RuntimeError("staged_analysis_evidence_mismatch")
            if str(analysis[3] or "") != ANALYSIS_STAGE_VERSION:
                raise RuntimeError("staged_analysis_producer_mismatch")
            if str(analysis[0] or "") not in {"staged", "ready"}:
                raise RuntimeError("staged_analysis_has_invalid_status")

            cursor.execute(
                """
                SELECT artifact_id, status
                FROM ReportArtifacts
                WHERE publication_key = ?
                """,
                (publication_key,),
            )
            existing = cursor.fetchone()
            if existing and str(existing[1] or "") != "staged":
                conn.commit()
                return {
                    "artifact_id": str(existing[0]),
                    "publication_key": publication_key,
                }
            if existing:
                cursor.execute(
                    """
                    UPDATE ReportArtifacts
                    SET report_type = ?, payload = ?,
                        payload_encrypted = ?, evidence_hash = ?,
                        provenance_json = ?, analysis_id = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE artifact_id = ? AND status = 'staged'
                    """,
                    (
                        report.get("report_type") or "interview",
                        "[encrypted]", report_encrypted, manifest_evidence_hash,
                        _json_dumps(report.get("generation_provenance") or {}),
                        analysis_id, existing[0],
                    ),
                )
                artifact_id_for_stage = str(existing[0])
            else:
                cursor.execute(
                    """
                    INSERT INTO ReportArtifacts (
                        artifact_id, interview_id, user_id, analysis_id,
                        publication_key, report_type, audience, payload,
                        payload_encrypted, evidence_hash, status, provenance_json
                    ) VALUES (
                        ?, ?, ?, ?, ?, ?, 'candidate', ?,
                        ?, ?, 'staged', ?
                    )
                    """,
                    (
                        artifact_id_for_stage, interview_id, user_id, analysis_id,
                        publication_key, report.get("report_type") or "interview",
                        "[encrypted]", report_encrypted, manifest_evidence_hash,
                        _json_dumps(report.get("generation_provenance") or {}),
                    ),
                )
            conn.commit()
            return {"artifact_id": artifact_id_for_stage, "publication_key": publication_key}
        except Exception:
            conn.rollback()
            raise
        finally:
            cursor.close()
            return_db_connection(conn)

    return await asyncio.to_thread(_stage)


async def _publish_staged_report(
    *,
    job_id: str,
    worker_id: str,
    interview_id: str,
    user_id: str,
    analysis_id: str,
    artifact_id: str,
    publication_key: str,
    final_status: str,
    report: Dict[str, Any],
    safe_report: Dict[str, Any],
    report_encrypted: bytes,
    manifest_evidence_hash: str,
    canonical_evidence_hash: str,
    mode: str,
    observations: List[Dict[str, Any]],
    weak_topics: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Make canonical Performance, Report, History, and the Improve event visible together."""

    def _publish() -> Dict[str, Any]:
        from database import get_db_connection, return_db_connection

        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("BEGIN IMMEDIATE")
            cursor.execute(
                """
                SELECT status, lease_owner, manifest_id, evidence_hash
                FROM AnalysisJobs
                WHERE job_id = ? AND interview_id = ? AND user_id = ?
                """,
                (job_id, interview_id, user_id),
            )
            job = cursor.fetchone()
            if not job or str(job[0] or "") != "running" or str(job[1] or "") != worker_id:
                raise RuntimeError("analysis_job_lease_lost_before_publication")
            if not job[2] or str(job[3] or "") != manifest_evidence_hash:
                raise RuntimeError("analysis_job_manifest_mismatch_before_publication")

            cursor.execute(
                """
                SELECT evidence_hash, is_current, producer_version
                FROM EvidenceManifests
                WHERE manifest_id = ? AND interview_id = ? AND user_id = ?
                """,
                (job[2], interview_id, user_id),
            )
            manifest = cursor.fetchone()
            if (
                not manifest
                or str(manifest[0] or "") != manifest_evidence_hash
                or str(manifest[2] or "") != ANALYSIS_STAGE_VERSION
            ):
                raise RuntimeError("analysis_job_manifest_invalid_before_publication")

            if not bool(manifest[1]):
                cursor.execute(
                    """
                    UPDATE SessionPerformanceAnalyses
                    SET status = 'superseded', is_current = FALSE, updated_at = CURRENT_TIMESTAMP
                    WHERE analysis_id = ? AND status = 'staged'
                    """,
                    (analysis_id,),
                )
                cursor.execute(
                    """
                    UPDATE ReportArtifacts
                    SET status = 'superseded', updated_at = CURRENT_TIMESTAMP
                    WHERE artifact_id = ? AND status = 'staged'
                    """,
                    (artifact_id,),
                )
                cursor.execute(
                    """
                    UPDATE AnalysisJobs
                    SET status = 'completed', progress = 100,
                        current_stage = 'complete', completed_at = CURRENT_TIMESTAMP,
                        updated_at = CURRENT_TIMESTAMP, lease_owner = NULL,
                        lease_expires_at = NULL,
                        error_message = 'superseded_by_newer_evidence'
                    WHERE job_id = ? AND lease_owner = ? AND status = 'running'
                    """,
                    (job_id, worker_id),
                )
                conn.commit()
                return {
                    "analysis_id": analysis_id,
                    "artifact_id": artifact_id,
                    "publication_key": publication_key,
                    "superseded": True,
                }

            cursor.execute(
                """
                SELECT status
                FROM Interviews
                WHERE interview_id = ? AND user_id = ?
                """,
                (interview_id, user_id),
            )
            interview = cursor.fetchone()
            if not interview:
                raise RuntimeError("report_publication_owner_missing")
            if str(interview[0] or "") == "cancelled":
                raise RuntimeError("cancelled_interview_cannot_publish_report")

            cursor.execute(
                """
                SELECT status, is_current, evidence_hash, producer_version,
                       analysis_json_encrypted, evidence_index_encrypted, mode
                FROM SessionPerformanceAnalyses
                WHERE analysis_id = ? AND interview_id = ? AND user_id = ?
                """,
                (analysis_id, interview_id, user_id),
            )
            analysis = cursor.fetchone()
            if not analysis:
                raise RuntimeError("staged_analysis_not_found")
            if str(analysis[0] or "") not in {"staged", "ready"}:
                raise RuntimeError("staged_analysis_has_invalid_status")
            if str(analysis[2] or "") != canonical_evidence_hash:
                raise RuntimeError("staged_analysis_evidence_mismatch")
            if str(analysis[3] or "") != ANALYSIS_STAGE_VERSION:
                raise RuntimeError("staged_analysis_producer_mismatch")
            if analysis[4] is None or analysis[5] is None:
                raise RuntimeError("staged_analysis_payload_missing")
            if str(analysis[6] or "") != mode:
                raise RuntimeError("staged_analysis_mode_mismatch")

            cursor.execute(
                """
                SELECT status, evidence_hash, analysis_id, payload_encrypted
                FROM ReportArtifacts
                WHERE artifact_id = ? AND publication_key = ?
                  AND interview_id = ? AND user_id = ?
                """,
                (artifact_id, publication_key, interview_id, user_id),
            )
            artifact = cursor.fetchone()
            if not artifact or str(artifact[0] or "") not in {"staged", "completed", "partial"}:
                raise RuntimeError("staged_report_artifact_not_found")
            if (
                str(artifact[1] or "") != manifest_evidence_hash
                or str(artifact[2] or "") != analysis_id
            ):
                raise RuntimeError("staged_report_artifact_mismatch")
            if artifact[3] is None:
                raise RuntimeError("staged_report_artifact_payload_missing")

            if not bool(analysis[1]):
                cursor.execute(
                    """
                    UPDATE SessionPerformanceAnalyses
                    SET is_current = FALSE, updated_at = CURRENT_TIMESTAMP
                    WHERE interview_id = ? AND mode = ?
                      AND schema_version = ? AND is_current = TRUE
                      AND analysis_id <> ?
                    """,
                    (interview_id, mode, SESSION_PERFORMANCE_VERSION, analysis_id),
                )
            cursor.execute(
                """
                UPDATE SessionPerformanceAnalyses
                SET status = 'ready', is_current = TRUE, updated_at = CURRENT_TIMESTAMP
                WHERE analysis_id = ?
                """,
                (analysis_id,),
            )
            cursor.execute(
                """
                UPDATE ReportArtifacts
                SET status = 'superseded', updated_at = CURRENT_TIMESTAMP
                WHERE interview_id = ? AND user_id = ? AND audience = 'candidate'
                  AND artifact_id <> ?
                  AND status IN ('completed', 'partial')
                """,
                (interview_id, user_id, artifact_id),
            )
            cursor.execute(
                """
                UPDATE ReportArtifacts
                SET status = ?, published_at = COALESCE(published_at, CURRENT_TIMESTAMP),
                    updated_at = CURRENT_TIMESTAMP
                WHERE artifact_id = ? AND status IN ('staged', 'completed', 'partial')
                """,
                (final_status, artifact_id),
            )
            cursor.execute(
                """
                UPDATE Interviews
                SET status = ?, overall_score = ?, feedback_summary = ?,
                    analysis_status = CASE WHEN ? = 'completed' THEN 'ready' ELSE ? END,
                    report_json = ?, report_json_encrypted = ?,
                    completed_at = COALESCE(completed_at, CURRENT_TIMESTAMP)
                WHERE interview_id = ? AND user_id = ? AND status <> 'cancelled'
                """,
                (
                    final_status, report.get("overall_score"),
                    "Analysis completed.",
                    final_status, final_status, "[encrypted]",
                    report_encrypted, interview_id, user_id,
                ),
            )

            outbox_payload = {
                "schema_version": "report-side-effects-v1",
                "analysis_id": analysis_id,
                "interview_id": interview_id,
                "mode": mode,
                "observations": observations,
                "weak_topics": weak_topics,
                "producer_version": ANALYSIS_STAGE_VERSION,
            }
            outbox_idempotency_key = f"improve:{analysis_id}:{ANALYSIS_STAGE_VERSION}"
            event_id = str(uuid.uuid5(uuid.NAMESPACE_URL, outbox_idempotency_key))
            cursor.execute(
                """
                INSERT INTO ReportSideEffectOutbox (
                    event_id, idempotency_key, publication_key, event_type,
                    analysis_id, interview_id, user_id, payload, payload_encrypted, status,
                    max_attempts, available_at
                ) VALUES (
                    ?, ?, ?, 'improve_sync', ?, ?, ?,
                    ?, ?, 'queued', ?, CURRENT_TIMESTAMP
                )
                ON CONFLICT (idempotency_key) DO NOTHING
                """,
                (
                    event_id, outbox_idempotency_key, publication_key,
                    analysis_id, interview_id, user_id,
                    _json_dumps({"encrypted": True, "schema_version": "report-side-effects-v1"}),
                    _encrypted_bytes(outbox_payload), REPORT_SIDE_EFFECT_MAX_ATTEMPTS,
                ),
            )
            cursor.execute(
                """
                UPDATE AnalysisJobs
                SET status = ?, progress = 100, current_stage = 'complete',
                    completed_at = COALESCE(completed_at, CURRENT_TIMESTAMP), updated_at = CURRENT_TIMESTAMP,
                    lease_owner = NULL, lease_expires_at = NULL, heartbeat_at = CURRENT_TIMESTAMP,
                    error_message = NULL
                WHERE job_id = ? AND lease_owner = ? AND status = 'running'
                """,
                (final_status, job_id, worker_id),
            )
            conn.commit()
            return {
                "analysis_id": analysis_id,
                "artifact_id": artifact_id,
                "outbox_event_id": event_id,
                "publication_key": publication_key,
            }
        except Exception:
            conn.rollback()
            raise
        finally:
            cursor.close()
            return_db_connection(conn)

    return await asyncio.to_thread(_publish)


async def _load_completed_stage(
    job_id: str,
    stage: str,
    evidence_hash: str,
) -> Optional[Dict[str, Any]]:
    row = await async_execute(
        """
        SELECT output_encrypted, output_json
        FROM AnalysisStageOutputs
        WHERE job_id = ? AND stage_name = ? AND stage_version = ?
          AND evidence_hash = ? AND status = 'completed'
        LIMIT 1
        """,
        (job_id, stage, ANALYSIS_STAGE_VERSION, evidence_hash),
        fetchone=True,
    )
    if not row:
        return None
    if row[0]:
        return _json_value(_decrypt_storage_text(row[0]), {})
    return _json_value(row[1], {})


async def _refresh_analysis_job_manifest(
    job_id: str,
    interview_id: str,
    user_id: str,
) -> tuple[str, str]:
    def _refresh() -> tuple[str, str]:
        from database import get_db_connection, return_db_connection

        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("BEGIN IMMEDIATE")
            manifest_id, evidence_hash = _seal_evidence_manifest(
                cursor, interview_id, user_id
            )
            cursor.execute(
                """
                UPDATE AnalysisJobs
                SET manifest_id = ?, evidence_hash = ?,
                    producer_version = ?, updated_at = CURRENT_TIMESTAMP
                WHERE job_id = ?
                """,
                (manifest_id, evidence_hash, ANALYSIS_STAGE_VERSION, job_id),
            )
            cursor.execute(
                """
                UPDATE Interviews
                SET evidence_hash = ?, evidence_sealed_at = CURRENT_TIMESTAMP
                WHERE interview_id = ? AND user_id = ?
                """,
                (evidence_hash, interview_id, user_id),
            )
            conn.commit()
            return manifest_id, evidence_hash
        except Exception:
            conn.rollback()
            raise
        finally:
            cursor.close()
            return_db_connection(conn)

    return await asyncio.to_thread(_refresh)


async def run_analysis_job(
    job_id: str,
    *,
    worker_id: Optional[str] = None,
    claimed_job: Optional[tuple[str, str, str]] = None,
) -> None:
    worker_id = worker_id or f"direct-analysis-{uuid.uuid4().hex[:10]}"
    job = claimed_job or await _claim_specific_analysis_job(job_id, worker_id)
    if not job:
        return

    _, interview_id, user_id = job
    logger.info(
        "Starting async analysis job %s for %s",
        stable_hash(job_id, "analysis"), stable_hash(interview_id, "interview"),
    )
    try:
        await async_execute(
            """
            UPDATE Interviews SET status = 'analysis_running', analysis_status = 'running'
            WHERE interview_id = ? AND status <> 'cancelled'
              AND NOT (status IN ('completed', 'report_ready', 'partial', 'failed') AND report_json IS NOT NULL)
            """,
            (interview_id,),
        )
        job_evidence_row = await async_execute(
            "SELECT evidence_hash, manifest_id FROM AnalysisJobs WHERE job_id = ?",
            (job_id,), fetchone=True,
        )
        job_evidence_hash = (job_evidence_row or [""])[0] or ""
        manifest_id = str((job_evidence_row or [None, ""])[1] or "")
        if not job_evidence_hash or not manifest_id:
            raise RuntimeError("analysis_job_is_missing_sealed_evidence")
        stage_outputs: Dict[str, Dict[str, Any]] = {}

        for index, stage in enumerate(ANALYSIS_EXECUTION_STAGES, start=1):
            await _renew_analysis_lease(job_id, worker_id)
            started = datetime.now(timezone.utc)
            upstream_hashes = {
                name: _sha256_json(stage_outputs[name])
                for name in ANALYSIS_EXECUTION_STAGES
                if name in stage_outputs
            }
            stage_evidence_hash = _sha256_json({
                "job_evidence_hash": job_evidence_hash,
                "stage": stage,
                "stage_version": ANALYSIS_STAGE_VERSION,
                "upstream": upstream_hashes,
            })
            input_hash = _sha256_json({
                "job_evidence_hash": job_evidence_hash,
                "stage": stage,
                "upstream": upstream_hashes,
            })
            cached_output = await _load_completed_stage(job_id, stage, stage_evidence_hash)
            if cached_output is not None:
                output = cached_output
                status, error = "completed", None
            else:
                try:
                    output = await _run_stage(stage, interview_id, user_id, stage_outputs)
                    status, error = "completed", None
                except Exception as exc:
                    logger.exception(
                        "Analysis stage %s failed for %s",
                        stage, stable_hash(interview_id, "interview"),
                    )
                    output = {"error": "stage_failed", "stage": stage}
                    status, error = "failed", str(exc)[:500]
                provenance = _stage_provenance(stage, output, input_hash)
                await async_execute(
                    """
                    INSERT INTO AnalysisStageOutputs (
                        output_id, job_id, interview_id, stage_name, stage_version,
                        evidence_hash, input_hash, model, prompt_version, provenance_json,
                        status, output_json, output_encrypted,
                        error_message, started_at, completed_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT (job_id, stage_name, stage_version, evidence_hash) DO UPDATE
                    SET input_hash = EXCLUDED.input_hash,
                        model = EXCLUDED.model,
                        prompt_version = EXCLUDED.prompt_version,
                        provenance_json = EXCLUDED.provenance_json,
                        status = EXCLUDED.status,
                        output_json = EXCLUDED.output_json,
                        output_encrypted = EXCLUDED.output_encrypted,
                        error_message = EXCLUDED.error_message,
                        started_at = EXCLUDED.started_at,
                        completed_at = EXCLUDED.completed_at
                    """,
                    (
                        str(uuid.uuid4()), job_id, interview_id, stage,
                        ANALYSIS_STAGE_VERSION, stage_evidence_hash, input_hash,
                        provenance.get("model"), provenance.get("prompt_version"), _json_dumps(provenance), status,
                        _json_dumps({"encrypted": True, "stage": stage}),
                        _encrypted_bytes(output), error, started,
                    ),
                )
            stage_outputs[stage] = output
            if stage == "assessment_completion" and int(output.get("repaired_count") or 0):
                manifest_id, job_evidence_hash = await _refresh_analysis_job_manifest(
                    job_id, interview_id, user_id
                )
            progress = (
                100
                if stage == "complete"
                else math.floor(index / len(ANALYSIS_EXECUTION_STAGES) * 100)
            )
            await async_execute(
                """
                UPDATE AnalysisJobs SET progress = ?, current_stage = ?, updated_at = CURRENT_TIMESTAMP
                WHERE job_id = ? AND lease_owner = ?
                """,
                (progress, stage, job_id, worker_id),
            )
            if status == "failed" and stage in CRITICAL_ANALYSIS_STAGES:
                raise RuntimeError(f"critical_analysis_stage_failed:{stage}:{error or 'unknown'}")

        legacy_stage_outputs = _legacy_stage_outputs(stage_outputs)
        report = legacy_stage_outputs.get("report_generation") or {}
        report_is_partial = _report_has_noncritical_degradation(report, stage_outputs)
        report = {
            **report,
            "report_state": (
                "ungradable" if report.get("overall_score") is None
                else ("partial" if report_is_partial else "ready")
            ),
            "evidence_hash": job_evidence_hash,
            "evidence_manifest_id": manifest_id,
            "generation_provenance": {
                "pipeline_version": ANALYSIS_STAGE_VERSION,
                "stage_versions": {
                    stage: ANALYSIS_STAGE_VERSION
                    for stage in ANALYSIS_EXECUTION_STAGES
                },
                "report_stage": _stage_provenance(
                    "report_generation", report,
                    _sha256_json({name: _sha256_json(value) for name, value in stage_outputs.items()}),
                ),
            },
            "score_provenance": _score_provenance(report, job_evidence_hash),
        }
        if not _valid_candidate_report(report, interview_id):
            raise RuntimeError("report_generation_did_not_produce_a_valid_candidate_report")
        await _validate_report_for_publication(
            report,
            interview_id=interview_id,
            user_id=user_id,
            evidence_hash=job_evidence_hash,
            manifest_id=manifest_id,
        )
        final_status = (
            "partial"
            if report_is_partial
            else "completed"
        )
        staged_analysis = await _stage_canonical_performance(
            interview_id=interview_id,
            user_id=user_id,
            stage_outputs=legacy_stage_outputs,
            report=report,
            job_evidence_hash=job_evidence_hash,
        )
        analysis_id = str(staged_analysis["analysis_id"])
        mode = str(staged_analysis["mode"])
        report = {
            **report,
            "analysis_id": analysis_id,
        }
        report.pop("recruiter_only", None)
        safe_report = _safe_report_payload(report)
        full_report_encrypted = _encrypted_bytes(report)
        staged_artifact = await _stage_candidate_report_artifact(
            interview_id=interview_id,
            user_id=user_id,
            analysis_id=analysis_id,
            report=report,
            safe_report=safe_report,
            report_encrypted=full_report_encrypted,
            manifest_evidence_hash=job_evidence_hash,
            canonical_evidence_hash=str(staged_analysis["evidence_hash"]),
        )
        await _renew_analysis_lease(job_id, worker_id)
        await _publish_staged_report(
            job_id=job_id,
            worker_id=worker_id,
            interview_id=interview_id,
            user_id=user_id,
            analysis_id=analysis_id,
            artifact_id=staged_artifact["artifact_id"],
            publication_key=staged_artifact["publication_key"],
            final_status=final_status,
            report=report,
            safe_report=safe_report,
            report_encrypted=full_report_encrypted,
            manifest_evidence_hash=job_evidence_hash,
            canonical_evidence_hash=str(staged_analysis["evidence_hash"]),
            mode=mode,
            observations=list(staged_analysis.get("observations") or []),
            weak_topics=list(
                (legacy_stage_outputs.get("technical_code") or {}).get("weak_topics")
                or []
            ),
        )
        try:
            await _schedule_media_cleanup(interview_id)
        except Exception:
            logger.warning(
                "Media cleanup scheduling deferred for %s",
                stable_hash(interview_id, "interview"),
            )
    except Exception as exc:
        logger.exception("Async analysis job failed for %s", stable_hash(interview_id, "interview"))
        retry_row = await async_execute(
            """
            UPDATE AnalysisJobs
            SET retry_count = retry_count + 1,
                status = CASE WHEN retry_count + 1 >= ? THEN 'failed' ELSE 'queued' END,
                next_attempt_at = CASE
                    WHEN retry_count + 1 >= ? THEN NULL
                    ELSE datetime(
                        CURRENT_TIMESTAMP,
                        '+' || CAST((1 << retry_count) * 5 AS TEXT) || ' seconds'
                    )
                END,
                error_message = ?, updated_at = CURRENT_TIMESTAMP,
                completed_at = CASE WHEN retry_count + 1 >= ? THEN CURRENT_TIMESTAMP ELSE NULL END,
                lease_owner = NULL, lease_expires_at = NULL
            WHERE job_id = ? AND lease_owner = ?
            RETURNING status
            """,
            (
                ANALYSIS_MAX_RETRIES, ANALYSIS_MAX_RETRIES, str(exc)[:500],
                ANALYSIS_MAX_RETRIES, job_id, worker_id,
            ),
            fetchone=True,
        )
        if retry_row and retry_row[0] == "failed":
            await async_execute(
                """
                UPDATE Interviews
                SET status = CASE WHEN attempt_status = 'completed' THEN 'completed' ELSE status END,
                    analysis_status = 'failed'
                WHERE interview_id = ? AND status <> 'cancelled' AND report_json IS NULL
                """,
                (interview_id,),
            )


async def _run_stage(stage: str, interview_id: str, user_id: str, outputs: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    if stage == "evidence_load":
        return {
            "transcription": await _run_stage("transcription_diarization", interview_id, user_id, {}),
            "audio": await _run_stage("audio_features", interview_id, user_id, {}),
            "video": await _run_stage("video_features", interview_id, user_id, {}),
        }
    if stage == "transcript_analysis":
        return await _run_stage("nlp_content", interview_id, user_id, {})
    if stage == "assessment_completion":
        rows = await async_execute(
            """
            SELECT response.response_id, response.answer_text_encrypted,
                   response.user_response, response.response_time_seconds,
                   response.evidence_hash, question.question_text,
                   question.question_type, question.taxonomy_keys,
                   question.expected_points, question.rubric_json
            FROM InterviewResponses response
            JOIN InterviewQuestions question
              ON question.question_id = response.question_id
            WHERE response.interview_id = ?
              AND question.question_type NOT IN ('warmup', 'introduction')
              AND NOT EXISTS (
                  SELECT 1
                  FROM ResponseAssessments assessment
                  WHERE assessment.response_id = response.response_id
                    AND assessment.evaluator_version = ?
              )
            ORDER BY response.created_at
            LIMIT 60
            """,
            (interview_id, EVALUATION_VERSION),
            fetchall=True,
        )
        repaired: List[str] = []
        failures: List[str] = []
        for row in rows or []:
            response_id = str(row[0])
            answer = _decrypt_storage_text(row[1]) if row[1] else ""
            if not answer and row[2] != "[encrypted]":
                answer = str(row[2] or "")
            if not answer.strip():
                failures.append(response_id)
                continue
            taxonomy_keys = _json_value(row[7], [])
            expected_points = _json_value(row[8], [])
            rubric = _json_value(row[9], {})
            if not isinstance(rubric, dict):
                rubric = {}
            rubric = {**rubric, "expected_points": expected_points}
            context = {
                "interview_type": str(row[6] or "mock"),
                "question_type": str(row[6] or "main"),
                "taxonomy_keys": taxonomy_keys if isinstance(taxonomy_keys, list) else [],
                "semantic_analysis_enabled": True,
                "recovery_assessment": True,
            }
            try:
                try:
                    assessment = await asyncio.wait_for(
                        evaluate_answer(
                            str(row[5] or ""),
                            answer,
                            rubric,
                            context,
                            row[3],
                            [],
                            user_id=user_id,
                            interview_id=interview_id,
                            response_id=response_id,
                        ),
                        timeout=8.0,
                    )
                except asyncio.TimeoutError:
                    assessment = await evaluate_answer(
                        str(row[5] or ""),
                        answer,
                        rubric,
                        {**context, "semantic_analysis_enabled": False},
                        row[3],
                        [],
                        user_id=user_id,
                        interview_id=interview_id,
                        response_id=response_id,
                    )
                    assessment["semantic_status"] = {
                        **(assessment.get("semantic_status") or {}),
                        "state": "failed",
                        "attempted": True,
                        "reason": "recovery_semantic_timeout",
                    }
                assessment["recovered_during_analysis"] = True
                assessment_hash = hashlib.sha256(
                    f"{response_id}|{row[4] or ''}|{EVALUATION_VERSION}".encode("utf-8")
                ).hexdigest()
                await async_execute(
                    """
                    INSERT INTO ResponseAssessments (
                        assessment_id, response_id, interview_id,
                        evaluator_version, evidence_hash, overall_score,
                        assessment_json, assessment_json_encrypted, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT (response_id, evaluator_version, evidence_hash)
                    DO NOTHING
                    """,
                    (
                        str(uuid.uuid4()), response_id, interview_id,
                        EVALUATION_VERSION, assessment_hash,
                        assessment.get("overall_score")
                        if isinstance(assessment.get("overall_score"), (int, float))
                        else None,
                        _json_dumps({"encrypted": True}),
                        _encrypted_bytes(assessment),
                    ),
                )
                repaired.append(response_id)
            except Exception:
                logger.exception(
                    "Could not recover assessment response=%s",
                    stable_hash(response_id, "response"),
                )
                failures.append(response_id)
        if failures:
            raise RuntimeError(
                f"assessment_completion_failed:{len(failures)}"
            )
        return {
            "missing_count": len(rows or []),
            "repaired_count": len(repaired),
            "repaired_response_ids": repaired,
        }
    if stage == "technical_analysis":
        return await _run_stage(
            "technical_code", interview_id, user_id,
            {"nlp_content": outputs.get("transcript_analysis") or {}},
        )
    if stage == "self_review_summary":
        evidence = outputs.get("evidence_load") or {}
        return await _run_stage(
            "self_review_signals", interview_id, user_id,
            {
                "video_features": evidence.get("video") or {},
                "technical_code": outputs.get("technical_analysis") or {},
            },
        )
    if stage in {"deterministic_report", "semantic_enhancement"}:
        legacy = _legacy_stage_outputs(outputs)
        if stage == "deterministic_report":
            legacy["__deterministic_only"] = {"enabled": True}
        return await _run_stage("report_generation", interview_id, user_id, legacy)
    if stage == "report_validation":
        semantic = outputs.get("semantic_enhancement") or {}
        report = (
            semantic
            if semantic and not semantic.get("error")
            else outputs.get("deterministic_report") or {}
        )
        if not _valid_candidate_report(report, interview_id):
            raise RuntimeError("report_schema_validation_failed")
        return {**report, "validation": {"status": "passed", "version": "report-validation-v1"}}
    if stage == "performance_projection":
        report = outputs.get("report_validation") or {}
        return {
            "projection_version": "performance-projection-v1",
            "overall_score": report.get("overall_score"),
            "dimension_scores": report.get("dimension_scores") or {},
            "gradable": report.get("overall_score") is not None,
        }
    if stage in {"weakness_update", "improve_update"}:
        return {
            "status": "deferred_until_canonical_analysis_commit",
            "stage": stage,
            "version": "canonical-update-v1",
        }
    if stage == "complete":
        validated = outputs.get("report_validation") or {}
        semantic = outputs.get("semantic_enhancement") or {}
        return (
            validated
            if validated and not validated.get("error")
            else semantic
            if semantic and not semantic.get("error")
            else outputs.get("deterministic_report") or {}
        )

    if stage == "transcription_diarization":
        rows = await async_execute(
            """
            SELECT q.question_text, q.question_order, q.created_at,
                   r.answer_text_encrypted, r.user_response, r.created_at
            FROM InterviewQuestions q
            LEFT JOIN InterviewResponses r ON r.question_id = q.question_id
            WHERE q.interview_id = ?
            ORDER BY q.question_order, r.created_at
            """,
            (interview_id,),
            fetchall=True,
        )
        transcript: List[Dict[str, Any]] = []
        seen_turns: set[tuple[str, str]] = set()

        def append_turn(role_value: Any, text_value: Any, *, label: Optional[str] = None) -> None:
            role = _candidate_transcript_role(role_value)
            text = str(text_value or "").strip()
            if not role or not text:
                return
            key = (role, " ".join(text.split()).lower())
            if key in seen_turns:
                return
            seen_turns.add(key)
            turn: Dict[str, Any] = {"role": role, "text": text}
            if label:
                turn["label"] = label
            transcript.append(turn)

        seen_questions: set[tuple[int, str]] = set()
        for question_text, question_order, _, answer_encrypted, legacy_answer, _ in rows or []:
            question_key = (int(question_order or 0), str(question_text or ""))
            if question_key not in seen_questions:
                append_turn("interviewer", question_text)
                seen_questions.add(question_key)
            answer = _decrypt_storage_text(answer_encrypted) if answer_encrypted else ""
            if not answer and legacy_answer != "[encrypted]":
                answer = str(legacy_answer or "")
            if answer:
                append_turn("candidate", answer)

        # The websocket completion payload is an encrypted fallback for a
        # connection that ended after a transcript turn but before its normal
        # question/response row was committed. Merge it without duplicating
        # the canonical persisted turns above.
        stored_transcript_row = await async_execute(
            """
            SELECT transcript_encrypted
            FROM Interviews
            WHERE interview_id = ? AND user_id = ?
            """,
            (interview_id, user_id),
            fetchone=True,
        )
        if stored_transcript_row and stored_transcript_row[0]:
            try:
                stored_transcript = _json_value(
                    _decrypt_storage_text(stored_transcript_row[0]),
                    [],
                )
            except Exception:
                stored_transcript = []
            for item in stored_transcript if isinstance(stored_transcript, list) else []:
                if not isinstance(item, dict):
                    continue
                append_turn(
                    item.get("role"),
                    item.get("text") or item.get("content") or item.get("transcript"),
                )

        # Coding rounds persist spoken and written reasoning separately from
        # InterviewResponses. Include those encrypted evidence rows so a
        # Technical report cannot silently publish an empty transcript.
        technical_rows = await async_execute(
            """
            SELECT round.round_id, round.prompt, round.round_number,
                   evidence.evidence_type, evidence.content_encrypted
            FROM TechnicalInterviewRounds round
            LEFT JOIN TechnicalReasoningEvidence evidence
              ON evidence.round_id = round.round_id
             AND evidence.user_id = round.user_id
            WHERE round.interview_id = ? AND round.user_id = ?
            ORDER BY round.round_number, round.created_at,
                     evidence.created_at, evidence.evidence_id
            """,
            (interview_id, user_id),
            fetchall=True,
        )
        seen_technical_rounds: set[str] = set()
        for round_id, prompt, _, evidence_type, encrypted_payload in technical_rows or []:
            round_key = str(round_id or "")
            if round_key and round_key not in seen_technical_rounds:
                append_turn("interviewer", prompt, label="Technical problem")
                seen_technical_rounds.add(round_key)
            entry = _technical_reasoning_transcript_entry(
                evidence_type,
                encrypted_payload,
            )
            if entry:
                append_turn(
                    entry["role"],
                    entry["text"],
                    label=entry.get("label"),
                )

        candidate_word_count = _candidate_word_count(transcript)
        return {
            "provider": "local_existing_turns",
            "transcript": transcript,
            "speaker_segments": [
                {
                    "speaker": item["role"],
                    "text": item["text"],
                    **({"label": item["label"]} if item.get("label") else {}),
                }
                for item in transcript
            ],
            "word_count": sum(len((item["text"] or "").split()) for item in transcript),
            "candidate_word_count": candidate_word_count,
            "interviewer_word_count": sum(_word_count(item["text"]) for item in transcript if item["role"] == "interviewer"),
            "confidence": "medium" if candidate_word_count >= 5 else "low",
            "insufficient_evidence": candidate_word_count < 5,
        }

    if stage == "audio_features":
        rows = await async_execute(
            """
            WITH latest_assessments AS (
                SELECT response_id, assessment_json_encrypted, assessment_json,
                       ROW_NUMBER() OVER (
                           PARTITION BY response_id
                           ORDER BY created_at DESC, assessment_id DESC
                       ) AS assessment_rank
                FROM ResponseAssessments
            )
            SELECT ir.timing_json, ir.input_mode,
                   ra.assessment_json_encrypted, ra.assessment_json
            FROM InterviewResponses ir
            LEFT JOIN latest_assessments ra
              ON ra.response_id = ir.response_id AND ra.assessment_rank = 1
            WHERE ir.interview_id = ?
            ORDER BY ir.created_at
            """,
            (interview_id,),
            fetchall=True,
        )
        voiced_seconds: List[float] = []
        pause_seconds: List[float] = []
        response_latencies: List[float] = []
        audio_word_count = 0
        filler_count = 0
        for timing_raw, input_mode, assessment_encrypted, assessment_legacy in rows or []:
            if str(input_mode or "").lower() not in {"voice", "audio", "voice_or_text"}:
                continue
            timing = _json_value(timing_raw, {})
            assessment = decrypt_json_field(assessment_encrypted, assessment_legacy, {})
            signals = assessment.get("signals") if isinstance(assessment, dict) else {}
            if not isinstance(signals, dict):
                signals = {}
            for target, key in (
                (voiced_seconds, "voiced_duration_seconds"),
                (pause_seconds, "pause_duration_seconds"),
                (response_latencies, "response_latency_seconds"),
            ):
                value = timing.get(key)
                if isinstance(value, (int, float)) and value >= 0:
                    target.append(float(value))
            audio_word_count += int(signals.get("word_count") or 0)
            fillers = signals.get("fillers")
            if isinstance(fillers, dict):
                filler_count += int(fillers.get("count") or 0)
        total_voiced_seconds = sum(voiced_seconds)
        words_per_minute = (
            round(audio_word_count / (total_voiced_seconds / 60.0), 1)
            if total_voiced_seconds > 0 and audio_word_count > 0
            else None
        )
        return {
            "words_per_minute": words_per_minute,
            "voiced_duration_seconds": round(total_voiced_seconds, 3) if voiced_seconds else None,
            "pause_duration_seconds": round(sum(pause_seconds), 3) if pause_seconds else None,
            "response_latency_seconds_avg": (
                round(sum(response_latencies) / len(response_latencies), 3)
                if response_latencies
                else None
            ),
            "filler_count": filler_count if rows else None,
            "source": "persisted_browser_audio_timing",
            "confidence": "measured" if total_voiced_seconds > 0 else "unknown",
            "insufficient_evidence": total_voiced_seconds <= 0,
        }

    if stage == "video_features":
        metrics = await async_execute(
            """
            SELECT payload
            FROM ClientBodyLanguageMetrics
            WHERE interview_id = ?
            ORDER BY created_at DESC
            LIMIT 200
            """,
            (interview_id,),
            fetchall=True,
        )
        payloads = [_json_value(row[0], {}) for row in metrics or []]
        face_values = [
            bool(payload.get("face_detected"))
            for payload in payloads
            if payload.get("face_detected") is not None
        ]
        centered_values = [
            bool(payload.get("face_centered"))
            for payload in payloads
            if payload.get("face_centered") is not None
        ]
        face_missing = sum(1 for present in face_values if not present)
        flags = []
        if face_missing >= 5:
            flags.append({"event_type": "face_missing", "count": face_missing})
        return {
            "source": "browser_local_camera_metrics",
            "face_present_percent": (
                round((sum(face_values) / len(face_values)) * 100, 1)
                if face_values
                else None
            ),
            "face_centered_percent": (
                round((sum(centered_values) / len(centered_values)) * 100, 1)
                if centered_values
                else None
            ),
            "sample_count": len(payloads),
            "flags": flags,
            "confidence": "measured" if payloads else "unknown",
            "insufficient_evidence": not payloads,
        }

    if stage == "nlp_content":
        turns = await _load_turns(interview_id)
        # The greeting and context-only introduction are persisted for an
        # auditable transcript, but they are never candidate evidence.
        scored_turns = [
            _score_turn(turn)
            for turn in turns
            if not turn.get("scoring_excluded")
        ]
        return {
            "turns": scored_turns,
            "average_star_score": _average_available([turn["star_score"] for turn in scored_turns]),
            "communication_score": _average_available([turn["communication_score"] for turn in scored_turns]),
            "content_depth_score": _average_available([turn["technical_score"] for turn in scored_turns]),
            "authoritative_turn_count": sum(1 for turn in scored_turns if turn.get("authoritative")),
            "insufficient_evidence_turn_count": sum(1 for turn in scored_turns if turn.get("insufficient_evidence")),
        }

    if stage == "technical_code":
        session_row = await async_execute(
            """
            SELECT started_at, completed_at, duration_seconds, deadline_at, settings
            FROM Interviews
            WHERE interview_id = ?
            """,
            (interview_id,),
            fetchone=True,
        )
        session_settings = _json_value(session_row[4], {}) if session_row else {}
        if not isinstance(session_settings, dict):
            session_settings = {}
        technical_settings = session_settings.get("technical") if isinstance(session_settings.get("technical"), dict) else {}
        duration_used_seconds = session_row[2] if session_row and session_row[2] is not None else None
        if duration_used_seconds is None and session_row and session_row[0] and session_row[1]:
            duration_used_seconds = max(0, int((session_row[1] - session_row[0]).total_seconds()))
        duration_allowed_seconds = (
            technical_settings.get("duration_seconds")
            or technical_settings.get("total_duration_seconds")
            or session_settings.get("duration_seconds")
        )
        if duration_allowed_seconds is None and session_row and session_row[0] and session_row[3]:
            duration_allowed_seconds = max(0, int((session_row[3] - session_row[0]).total_seconds()))
        round_rows = await async_execute(
            """
            SELECT round_id, round_type, language, prompt, metadata,
                   status, created_at, completed_at, duration_seconds,
                   deadline_at, round_number, started_at
            FROM TechnicalInterviewRounds
            WHERE interview_id = ?
            ORDER BY created_at, round_id
            """,
            (interview_id,),
            fetchall=True,
        )
        round_catalog: Dict[str, Dict[str, Any]] = {}
        for row in round_rows or []:
            round_id = str(row[0])
            metadata = _json_value(row[4], {})
            if not isinstance(metadata, dict):
                metadata = {}
            prompt = str(row[3] or "")
            round_catalog[round_id] = {
                "round_id": row[0],
                "round_type": row[1],
                "language": row[2],
                "prompt": prompt,
                "metadata": metadata,
                "status": row[5],
                "created_at": row[6],
                "completed_at": row[7],
                "duration_seconds": row[8],
                "deadline_at": row[9],
                "round_number": row[10],
                "started_at": row[11],
                "algorithm_pattern": metadata.get("algorithm_pattern"),
                "expected_time_complexity": metadata.get("expected_time_complexity"),
                "expected_space_complexity": metadata.get("expected_space_complexity"),
                "title": metadata.get("title") or (prompt.splitlines()[0][:80] if prompt else "Technical round"),
            }
        submission_rows = await async_execute(
            """
            SELECT ts.submission_id, ts.round_id, ts.language, ts.source_excerpt, ts.source_code, ts.submit_number,
                   ts.visible_passed, ts.visible_total, ts.hidden_passed, ts.hidden_total,
                   ts.runtime_ms, ts.memory_kb, ts.status, ts.result_json, ts.created_at,
                   tir.prompt, tir.metadata, ts.source_code_encrypted
            FROM TechnicalSubmissions ts
            JOIN TechnicalInterviewRounds tir ON tir.round_id = ts.round_id
            WHERE ts.interview_id = ?
            ORDER BY ts.round_id, ts.submit_number DESC, ts.created_at DESC
            """,
            (interview_id,),
            fetchall=True,
        )
        latest_by_round: Dict[str, Dict[str, Any]] = {}
        all_submissions: List[Dict[str, Any]] = []
        for row in submission_rows or []:
            result_json = _json_value(row[13], {})
            metadata = _json_value(row[16], {})
            source_code = _technical_source_text(row[17], row[4], row[3])
            item = {
                "submission_id": row[0],
                "round_id": row[1],
                "language": row[2],
                "source_excerpt": _technical_source_excerpt(source_code, row[3]),
                "source_chars": len(source_code),
                "source_code": source_code,
                "submit_number": int(row[5] or 0),
                "visible_passed": int(row[6] or 0),
                "visible_total": int(row[7] or 0),
                "hidden_passed": int(row[8] or 0),
                "hidden_total": int(row[9] or 0),
                "runtime_ms": row[10],
                "memory_kb": row[11],
                "status": row[12] or "submitted",
                "result_json": result_json,
                "created_at": row[14],
                "prompt": row[15] or "",
                "metadata": metadata,
                "algorithm_pattern": metadata.get("algorithm_pattern"),
                "expected_time_complexity": metadata.get("expected_time_complexity"),
                "expected_space_complexity": metadata.get("expected_space_complexity"),
                "title": metadata.get("title") or (row[15] or "Technical problem").splitlines()[0][:80],
            }
            all_submissions.append(item)
            if item["round_id"] not in latest_by_round:
                latest_by_round[item["round_id"]] = item

        final_submissions = list(latest_by_round.values())
        for item in final_submissions:
            round_item = round_catalog.get(str(item.get("round_id"))) or {}
            started_at = round_item.get("started_at") or round_item.get("created_at")
            if started_at and item.get("created_at"):
                try:
                    item["elapsed_seconds"] = max(0, int((item["created_at"] - started_at).total_seconds()))
                except (AttributeError, TypeError):
                    pass
        visible_passed = sum(item["visible_passed"] for item in final_submissions)
        visible_total = sum(item["visible_total"] for item in final_submissions)
        hidden_passed = sum(item["hidden_passed"] for item in final_submissions)
        hidden_total = sum(item["hidden_total"] for item in final_submissions)
        total_passed = visible_passed + hidden_passed
        total_cases = visible_total + hidden_total
        correctness_score = round((total_passed / total_cases) * 100, 1) if total_cases else None
        # Runtime and source length do not prove code quality. This dimension is
        # deliberately null until a dedicated rubric assessment exists.
        code_quality_score = None

        run_rows = await async_execute(
            """
            SELECT tre.run_id, tre.round_id, tre.language, tre.source_chars, tre.source_excerpt, tre.source_code,
                   tre.exit_code, tre.runtime_ms, tre.metadata, tre.hidden_validation_result,
                   tir.prompt, tir.metadata, tre.source_code_encrypted, tre.created_at
            FROM TechnicalRunEvents tre
            JOIN TechnicalInterviewRounds tir ON tir.round_id = tre.round_id
            WHERE tir.interview_id = ?
            ORDER BY tre.created_at DESC
            """,
            (interview_id,),
            fetchall=True,
        )
        submissions = [
            {
                "run_id": row[0],
                "round_id": row[1],
                "language": row[2],
                "source_chars": row[3],
                "source_excerpt": row[4] or "",
                "source_code": _technical_source_text(row[12], row[5], row[4]),
                "exit_code": row[6],
                "runtime_ms": row[7],
                "metadata": _json_value(row[8], {}),
                "validation": _json_value(row[9], {}),
                "prompt": row[10] or "",
                "round_metadata": _json_value(row[11], {}),
                "created_at": row[13],
            }
            for row in run_rows or []
        ]
        for item in submissions:
            validation = item.get("validation") or {}
            metadata = item.get("round_metadata") or item.get("metadata") or {}
            item["visible_passed"] = int(validation.get("visible_passed") or 0)
            item["visible_total"] = int(validation.get("visible_total") or 0)
            item["hidden_passed"] = int(validation.get("hidden_passed") or 0)
            item["hidden_total"] = int(validation.get("hidden_total") or 0)
            item["total_count"] = int(validation.get("total_count") or 0)
            item["pass_count"] = int(validation.get("pass_count") or 0)
            item["algorithm_pattern"] = metadata.get("algorithm_pattern")
            item["title"] = metadata.get("title") or (item.get("prompt") or "Technical problem").splitlines()[0][:80]
            item["source_excerpt"] = _technical_source_excerpt(item.get("source_code") or "", item.get("source_excerpt"))
            round_item = round_catalog.get(str(item.get("round_id"))) or {}
            started_at = round_item.get("started_at") or round_item.get("created_at")
            if started_at and item.get("created_at"):
                try:
                    item["elapsed_seconds"] = max(0, int((item["created_at"] - started_at).total_seconds()))
                except (AttributeError, TypeError):
                    pass
        latest = submissions[0] if submissions else {}
        draft_rows = await async_execute(
            """
            WITH ranked_snapshots AS (
                SELECT tcs.snapshot_id, tcs.round_id, tcs.language, tcs.source_chars,
                       tcs.source_excerpt, tcs.source_code,
                       tcs.metadata AS snapshot_metadata, tcs.created_at,
                       tir.prompt, tir.metadata AS round_metadata,
                       tcs.source_code_encrypted, tir.starter_code,
                       ROW_NUMBER() OVER (
                           PARTITION BY tcs.round_id
                           ORDER BY tcs.created_at DESC, tcs.snapshot_id DESC
                       ) AS snapshot_rank
                FROM TechnicalCodeSnapshots tcs
                JOIN TechnicalInterviewRounds tir ON tir.round_id = tcs.round_id
                WHERE tcs.interview_id = ?
                  AND tcs.source_chars > 0
            )
            SELECT snapshot_id, round_id, language, source_chars,
                   source_excerpt, source_code, snapshot_metadata, created_at,
                   prompt, round_metadata, source_code_encrypted, starter_code
            FROM ranked_snapshots
            WHERE snapshot_rank = 1
            """,
            (interview_id,),
            fetchall=True,
        )
        drafts = []
        for row in draft_rows or []:
            source_code = _technical_source_text(row[10], row[5], row[4])
            snapshot_metadata = _json_value(row[6], {})
            if not _candidate_authored_technical_draft(source_code, row[11], snapshot_metadata):
                continue
            drafts.append({
                "snapshot_id": row[0],
                "round_id": row[1],
                "language": row[2],
                "source_chars": row[3],
                "source_excerpt": row[4] or "",
                "source_code": source_code,
                "metadata": snapshot_metadata,
                "created_at": row[7],
                "prompt": row[8] or "",
                "round_metadata": _json_value(row[9], {}),
            })
        for item in drafts:
            metadata = item.get("round_metadata") or item.get("metadata") or {}
            item["algorithm_pattern"] = metadata.get("algorithm_pattern")
            item["title"] = metadata.get("title") or (item.get("prompt") or "Technical problem").splitlines()[0][:80]
            item["source_excerpt"] = _technical_source_excerpt(item.get("source_code") or "", item.get("source_excerpt"))
            round_item = round_catalog.get(str(item.get("round_id"))) or {}
            started_at = round_item.get("started_at") or round_item.get("created_at")
            if started_at and item.get("created_at"):
                try:
                    item["elapsed_seconds"] = max(0, int((item["created_at"] - started_at).total_seconds()))
                except (AttributeError, TypeError):
                    pass
        latest_signal = latest or (drafts[0] if drafts else {})
        reasoning_rows = await async_execute(
            """
            SELECT evidence_id, round_id, evidence_type, content,
                   content_encrypted, payload, created_at
            FROM TechnicalReasoningEvidence
            WHERE interview_id = ?
            ORDER BY created_at
            """,
            (interview_id,),
            fetchall=True,
        )
        reasoning_by_round: Dict[str, List[Dict[str, Any]]] = {}
        for row in reasoning_rows or []:
            encrypted_payload = _decrypt_storage_text(row[4]) if row[4] else ""
            decrypted = _json_value(encrypted_payload, {}) if encrypted_payload else {}
            content = ""
            if isinstance(decrypted, dict):
                content = str(
                    decrypted.get("content")
                    or decrypted.get("text")
                    or decrypted.get("transcript")
                    or decrypted.get("question")
                    or decrypted.get("approach")
                    or ""
                ).strip()
            if not content and row[3] and row[3] != "[encrypted]":
                content = str(row[3]).strip()
            safe_payload = _json_value(row[5], {})
            item = {
                "evidence_id": str(row[0]),
                "round_id": str(row[1]) if row[1] else None,
                "evidence_type": str(row[2] or "technical_reasoning"),
                "content": content,
                "word_count": _word_count(content),
                "payload": safe_payload if isinstance(safe_payload, dict) else {},
                "created_at": row[6],
            }
            reasoning_by_round.setdefault(str(row[1] or "unassigned"), []).append(item)

        telemetry_rows = await async_execute(
            """
            SELECT round_id, event_type, payload, created_at
            FROM TechnicalTelemetryEvents
            WHERE interview_id = ?
            ORDER BY created_at
            """,
            (interview_id,),
            fetchall=True,
        )
        activity_events = []
        for row in telemetry_rows or []:
            payload = _json_value(row[2], {})
            if not isinstance(payload, dict):
                payload = {}
            detail = payload.get("label") or payload.get("event_label") or payload.get("reason")
            activity_events.append({
                "round_id": str(row[0]) if row[0] else None,
                "event_type": row[1],
                "detail": str(detail) if detail else None,
                "created_at": row[3],
            })

        technical_question_types = {
            "technical_concept", "system_design", "ml", "backend", "database",
            "os", "network", "oop", "sql", "technical_explanation",
        }
        typed_turns = [
            turn
            for turn in (outputs.get("nlp_content", {}).get("turns") or [])
            if str(turn.get("question_type") or "").lower() in technical_question_types
        ]
        typed_scores = [
            turn.get("overall_score")
            for turn in typed_turns
            if not turn.get("insufficient_evidence") and turn.get("overall_score") is not None
        ]
        typed_assessed_round_ids = {
            _technical_round_id(turn.get("provenance") or {})
            for turn in typed_turns
            if not turn.get("insufficient_evidence")
            and turn.get("overall_score") is not None
            and _technical_round_id(turn.get("provenance") or {})
        }
        submitted_round_ids = {
            str(item.get("round_id"))
            for item in final_submissions
            if item.get("round_id")
        }
        reasoning_evidence: List[Dict[str, Any]] = []
        communication_scores: List[float] = []
        tradeoff_scores: List[float] = []
        for round_key, evidence_items in reasoning_by_round.items():
            usable_items = [
                item for item in evidence_items
                if item.get("content")
                and item.get("evidence_type") not in {"hint_requested", "constraint_reveal"}
            ]
            combined = "\n".join(str(item["content"]) for item in usable_items).strip()
            words = _word_count(combined)
            evidence_types = sorted({
                str(item.get("evidence_type"))
                for item in usable_items
                if item.get("evidence_type")
            })
            communication_score: Optional[float] = None
            if words >= 80:
                communication_score = 85.0
            elif words >= 40:
                communication_score = 75.0
            elif words >= 20:
                communication_score = 65.0
            elif words >= 8:
                communication_score = 50.0

            lower_text = combined.lower()
            has_complexity = any(
                value in lower_text
                for value in ("o(", "complexity", "time complexity", "space complexity")
            )
            has_tradeoff = any(
                value in lower_text
                for value in (
                    "trade-off", "tradeoff", "instead", "alternative",
                    "memory", "latency", "because", "however",
                )
            )
            has_explanation = any(
                value in evidence_types
                for value in ("workflow_explanation", "spoken_explanation", "technical_transcript")
            )
            tradeoff_score: Optional[float] = None
            if has_complexity or has_tradeoff:
                tradeoff_score = min(
                    100.0,
                    45.0
                    + (25.0 if has_complexity else 0.0)
                    + (20.0 if has_tradeoff else 0.0)
                    + (10.0 if has_explanation else 0.0),
                )

            official_dimension_eligible = (
                round_key in submitted_round_ids
                or round_key in typed_assessed_round_ids
            )
            if official_dimension_eligible and communication_score is not None:
                communication_scores.append(communication_score)
            if official_dimension_eligible and tradeoff_score is not None:
                tradeoff_scores.append(tradeoff_score)
            reasoning_evidence.append({
                "round_id": None if round_key == "unassigned" else round_key,
                "evidence_ids": [
                    str(item.get("evidence_id"))
                    for item in evidence_items
                    if item.get("evidence_id")
                ],
                "evidence_types": evidence_types,
                "word_count": words,
                "communication_score": (
                    communication_score if official_dimension_eligible else None
                ),
                "tradeoff_score": (
                    tradeoff_score if official_dimension_eligible else None
                ),
                "official_dimension_eligible": official_dimension_eligible,
            })
        typed_matrix = [
            {
                "round_id": _technical_round_id(turn.get("provenance") or {}),
                "response_id": turn.get("response_id"),
                "question_spec_id": turn.get("question_spec_id"),
                "title": turn.get("topic") or str(turn.get("question_type") or "Technical response").replace("_", " ").title(),
                "round_type": turn.get("question_type"),
                "taxonomy_keys": turn.get("taxonomy_keys") or [],
                "score": turn.get("overall_score"),
                "dimension_scores": turn.get("rubric_scores") or {},
                "confidence": turn.get("confidence"),
                "insufficient_evidence": bool(turn.get("insufficient_evidence")),
                "final_verdict": (
                    "insufficient_evidence"
                    if turn.get("insufficient_evidence")
                    else ("meets_bar" if float(turn.get("overall_score") or 0) >= 75 else "needs_work")
                ),
            }
            for turn in typed_turns
        ]
        latest_run_by_round: Dict[str, Dict[str, Any]] = {}
        for item in submissions:
            key = str(item.get("round_id")) if item.get("round_id") else ""
            if key and key not in latest_run_by_round:
                latest_run_by_round[key] = item
        latest_draft_by_round = {
            str(item.get("round_id")): item
            for item in drafts
            if item.get("round_id")
        }
        run_counts_by_round = Counter(
            str(item.get("round_id"))
            for item in submissions
            if item.get("round_id")
        )
        draft_counts_by_round = Counter(
            str(item.get("round_id"))
            for item in drafts
            if item.get("round_id")
        )
        matrix_by_round: Dict[str, Dict[str, Any]] = {}
        for key, round_item in round_catalog.items():
            matrix_by_round[key] = {
                **round_item,
                "evidence_state": "no_evidence",
                "insufficient_evidence": True,
                "final_verdict": "no_evidence",
                "visible_passed": 0,
                "visible_total": 0,
                "hidden_passed": 0,
                "hidden_total": 0,
                "final_pass_rate": None,
                "source_excerpt": "",
                "source_code": "",
                "run_count": int(run_counts_by_round.get(key) or 0),
                "draft_count": int(draft_counts_by_round.get(key) or 0),
                "time_allowed_seconds": round_item.get("duration_seconds"),
            }
        for item in final_submissions:
            key = str(item.get("round_id")) if item.get("round_id") else ""
            if not key:
                continue
            matrix_by_round[key] = {
                **matrix_by_round.get(key, {}),
                "submission_id": item.get("submission_id"),
                "round_id": item.get("round_id"),
                "round_type": matrix_by_round.get(key, {}).get("round_type") or "coding",
                "title": item.get("title"),
                "language": item.get("language"),
                "prompt": item.get("prompt", ""),
                "metadata": item.get("metadata") or matrix_by_round.get(key, {}).get("metadata") or {},
                "submit_number": item.get("submit_number"),
                "visible_passed": item.get("visible_passed", 0),
                "visible_total": item.get("visible_total", 0),
                "hidden_passed": item.get("hidden_passed", 0),
                "hidden_total": item.get("hidden_total", 0),
                "runtime_ms": item.get("runtime_ms"),
                "time_used_seconds": item.get("elapsed_seconds"),
                "time_allowed_seconds": matrix_by_round.get(key, {}).get("time_allowed_seconds"),
                "memory_kb": item.get("memory_kb"),
                "algorithm_pattern": item.get("algorithm_pattern"),
                "expected_time_complexity": item.get("expected_time_complexity"),
                "expected_space_complexity": item.get("expected_space_complexity"),
                "source_excerpt": item.get("source_excerpt", ""),
                "source_code": item.get("source_code", ""),
                "final_pass_rate": round(
                    ((item["visible_passed"] + item["hidden_passed"])
                     / max(item["visible_total"] + item["hidden_total"], 1)) * 100,
                    1,
                ),
                "final_verdict": (
                    "accepted"
                    if (item["visible_passed"] + item["hidden_passed"])
                    == (item["visible_total"] + item["hidden_total"])
                    and (item["visible_total"] + item["hidden_total"]) > 0
                    else "needs_work"
                ),
                "evidence_state": "final_submission",
                "insufficient_evidence": False,
            }
        for key, run in latest_run_by_round.items():
            if key not in matrix_by_round:
                continue
            item = matrix_by_round[key]
            item["latest_run_id"] = run.get("run_id")
            if item.get("evidence_state") == "no_evidence":
                validation = run.get("validation") or {}
                item.update({
                    "round_id": run.get("round_id"),
                    "round_type": item.get("round_type") or "coding",
                    "title": run.get("title") or item.get("title"),
                    "language": run.get("language") or item.get("language"),
                    "prompt": run.get("prompt") or item.get("prompt", ""),
                    "algorithm_pattern": run.get("algorithm_pattern") or item.get("algorithm_pattern"),
                    "source_excerpt": run.get("source_excerpt", ""),
                    "source_code": run.get("source_code", ""),
                    "visible_passed": int(run.get("visible_passed") or validation.get("visible_passed") or 0),
                    "visible_total": int(run.get("visible_total") or validation.get("visible_total") or 0),
                    "hidden_passed": int(run.get("hidden_passed") or validation.get("hidden_passed") or 0),
                    "hidden_total": int(run.get("hidden_total") or validation.get("hidden_total") or 0),
                    "total_count": int(run.get("total_count") or validation.get("total_count") or 0),
                    "pass_count": int(run.get("pass_count") or validation.get("pass_count") or 0),
                    "runtime_ms": run.get("runtime_ms"),
                    "time_used_seconds": run.get("elapsed_seconds"),
                    "time_allowed_seconds": item.get("time_allowed_seconds"),
                    "evidence_state": "run_only",
                    "final_verdict": "run_only",
                    "insufficient_evidence": True,
                })
        for key, draft in latest_draft_by_round.items():
            if key not in matrix_by_round:
                continue
            item = matrix_by_round[key]
            item["snapshot_id"] = draft.get("snapshot_id")
            if item.get("evidence_state") == "no_evidence":
                item.update({
                    "round_id": draft.get("round_id"),
                    "round_type": item.get("round_type") or "coding",
                    "title": draft.get("title") or item.get("title"),
                    "language": draft.get("language") or item.get("language"),
                    "prompt": draft.get("prompt") or item.get("prompt", ""),
                    "algorithm_pattern": draft.get("algorithm_pattern") or item.get("algorithm_pattern"),
                    "source_excerpt": draft.get("source_excerpt", ""),
                    "source_code": draft.get("source_code", ""),
                    "evidence_state": "draft_only",
                    "final_verdict": "draft_only",
                    "insufficient_evidence": True,
                    "time_used_seconds": draft.get("elapsed_seconds"),
                    "time_allowed_seconds": item.get("time_allowed_seconds"),
                })
        unlinked_typed: List[Dict[str, Any]] = []
        for typed in typed_matrix:
            key = str(typed.get("round_id")) if typed.get("round_id") else ""
            if not key or key not in matrix_by_round:
                unlinked_typed.append(typed)
                continue
            item = matrix_by_round[key]
            response_id = typed.get("response_id")
            response_ids = item.setdefault("response_ids", [])
            if response_id and response_id not in response_ids:
                response_ids.append(response_id)
            if not item.get("response_id"):
                item["response_id"] = response_id
            if typed.get("question_spec_id"):
                item.setdefault("question_spec_id", typed.get("question_spec_id"))
            if typed.get("taxonomy_keys"):
                item["taxonomy_keys"] = typed.get("taxonomy_keys")
            item["typed_response_count"] = int(item.get("typed_response_count") or 0) + 1
            if typed.get("score") is not None:
                item["typed_score"] = typed.get("score")
            if typed.get("dimension_scores"):
                item["typed_dimension_scores"] = typed.get("dimension_scores")
            if item.get("evidence_state") in {"no_evidence", "insufficient_evidence"}:
                item["score"] = typed.get("score")
                item["dimension_scores"] = typed.get("dimension_scores") or {}
                item["confidence"] = typed.get("confidence")
                item["insufficient_evidence"] = bool(typed.get("insufficient_evidence"))
                item["evidence_state"] = (
                    "insufficient_evidence"
                    if typed.get("insufficient_evidence")
                    else "assessed_response"
                )
                item["final_verdict"] = typed.get("final_verdict") or item.get("final_verdict")
        test_matrix = list(matrix_by_round.values()) + unlinked_typed
        return {
            "round_count": len(round_catalog),
            "rounds": list(round_catalog.values()),
            "submission_count": len(final_submissions),
            "typed_response_count": len(typed_turns),
            "typed_assessed_count": len(typed_scores),
            "typed_response_score": _average_available(typed_scores),
            "reasoning_evidence_count": sum(
                len(item.get("evidence_ids") or []) for item in reasoning_evidence
            ),
            "reasoning_round_count": sum(
                1 for item in reasoning_evidence if item.get("word_count")
            ),
            "reasoning_communication_score": _average_available(communication_scores),
            "reasoning_tradeoff_score": _average_available(tradeoff_scores),
            "reasoning_evidence": reasoning_evidence,
            "run_event_count": len(submissions),
            "draft_count": len(drafts),
            "draft_or_run_only": bool((submissions or drafts) and not final_submissions),
            "latest_exit_code": latest.get("exit_code"),
            "correctness_score": correctness_score,
            "code_quality_score": code_quality_score,
            "authenticity_flags": _technical_authenticity_flags(final_submissions or submissions or drafts),
            "confidence": "medium" if (final_submissions or typed_scores) else "low",
            "insufficient_evidence": not final_submissions and not typed_scores,
            "submissions": final_submissions,
            "all_submissions": all_submissions,
            "run_events": submissions,
            "drafts": drafts,
            "test_matrix": test_matrix,
            "activity_events": activity_events,
            "duration_used_seconds": duration_used_seconds,
            "duration_allowed_seconds": duration_allowed_seconds,
            "typed_responses": typed_turns,
            "weak_topics": _technical_weak_topics(final_submissions, submissions, drafts, typed_matrix),
            "evidence": {
                "final_submission_present": bool(final_submissions),
                "draft_or_run_only": bool((submissions or drafts) and not final_submissions),
                "final_draft_present": bool(drafts),
                "draft_count": len(drafts),
                "latest_language": latest_signal.get("language"),
                "latest_runtime_ms": latest.get("runtime_ms"),
                "latest_source_chars": latest_signal.get("source_chars"),
                "visible_passed": visible_passed,
                "visible_total": visible_total,
                "hidden_passed": hidden_passed,
                "hidden_total": hidden_total,
                "reasoning_evidence_ids": [
                    evidence_id
                    for item in reasoning_evidence
                    for evidence_id in (item.get("evidence_ids") or [])
                ],
            },
        }

    if stage == "self_review_signals":
        rows = await async_execute(
            """
            SELECT event_type, COUNT(*)
            FROM SelfReviewEvents
            WHERE interview_id = ?
            GROUP BY event_type
            """,
            (interview_id,),
            fetchall=True,
        )
        return summarize_self_review_signals(
            _event_counts(rows or []),
            outputs.get("video_features", {}),
            outputs.get("technical_code", {}),
        )

    if stage == "report_generation":
        meta = await async_execute(
            """
            SELECT interview_mode, interview_type, job_title, strictness_level, settings
            FROM Interviews
            WHERE interview_id = ?
            """,
            (interview_id,),
            fetchone=True,
        )
        interview_type = meta[1] if meta else "behavioral"
        settings_json = _json_value(meta[4], {}) if meta else {}
        profile_type = settings_json.get("profile_type", "mid_tier")
        has_technical_rounds = bool(await async_execute(
            """
            SELECT 1
            FROM TechnicalInterviewRounds
            WHERE interview_id = ?
            LIMIT 1
            """,
            (interview_id,),
            fetchone=True,
        ))
        is_technical_report = (
            bool(settings_json.get("technical_mode"))
            or has_technical_rounds
            or "technical" in str(interview_type).lower()
            or str(interview_type).lower() in {"coding", "technical_round"}
        )
        if is_technical_report:
            heuristic_report = build_async_technical_report(
                interview_id=interview_id,
                profile_type=profile_type,
                nlp_output=outputs.get("nlp_content", {}),
                technical_output=outputs.get("technical_code", {}),
                self_review_output=outputs.get("self_review_signals", {}),
            )
        else:
            heuristic_report = build_async_behavioral_report(
                interview_id=interview_id,
                profile_type=profile_type,
                nlp_output=outputs.get("nlp_content", {}),
                audio_output=outputs.get("audio_features", {}),
                video_output=outputs.get("video_features", {}),
                self_review_output=outputs.get("self_review_signals", {}),
            )
        # Canonical reports expose only persisted evaluator and execution evidence.
        # The legacy premium builder inferred unsupported traits from transcript/code
        # shape, so it is intentionally excluded from the authoritative path.

        transcript_output = outputs.get("transcription_diarization", {})
        technical_output = outputs.get("technical_code", {})
        heuristic_report = _with_transcript(heuristic_report, transcript_output)
        return {
            **heuristic_report,
            "ai_enhanced": False,
            "ai_provider_policy": "disabled_for_candidate_report",
            "ai_fallback_reason": None,
        }

    return {"stage": stage, "status": "skipped"}



async def _load_turns(interview_id: str) -> List[Dict[str, Any]]:
    rows = await async_execute(
        """
        WITH latest_responses AS (
            SELECT candidate_response.*,
                   ROW_NUMBER() OVER (
                       PARTITION BY candidate_response.question_id
                       ORDER BY candidate_response.created_at DESC, candidate_response.response_id DESC
                   ) AS response_rank
            FROM InterviewResponses candidate_response
        ),
        latest_assessments AS (
            SELECT response_id, evaluator_version,
                   assessment_json_encrypted, assessment_json,
                   ROW_NUMBER() OVER (
                       PARTITION BY response_id
                       ORDER BY created_at DESC, assessment_id DESC
                   ) AS assessment_rank
            FROM ResponseAssessments
        )
        SELECT ir.response_id, iq.question_id, iq.question_text, iq.question_type, iq.topic_label,
               iq.is_followup, ir.answer_text_encrypted, ir.user_response, ir.response_time_seconds,
               iq.question_spec_id, iq.taxonomy_keys, iq.blueprint_section_id,
               iq.parent_question_id, assessment.evaluator_version,
               assessment.assessment_json_encrypted, assessment.assessment_json,
               ir.timing_json, ir.input_mode,
               iq.provenance, iq.expected_points, iq.rubric_json, iq.question_order,
               ir.created_at
        FROM InterviewQuestions iq
        LEFT JOIN latest_responses ir
          ON ir.question_id = iq.question_id AND ir.response_rank = 1
        LEFT JOIN latest_assessments assessment
          ON assessment.response_id = ir.response_id AND assessment.assessment_rank = 1
        WHERE iq.interview_id = ?
        ORDER BY iq.question_order, ir.created_at NULLS LAST
        """,
        (interview_id,),
        fetchall=True,
    )
    turns: List[Dict[str, Any]] = []
    for row in rows or []:
        encrypted_answer = _decrypt_storage_text(row[6]) if row[6] else ""
        legacy_answer = "" if row[7] == "[encrypted]" else str(row[7] or "")
        turns.append({
            "response_id": row[0],
            "question_id": row[1],
            "question": row[2] or "",
            "question_type": row[3] or "main",
            "scoring_excluded": str(row[3] or "").strip().lower() in {"warmup", "introduction"},
            "topic": row[4] or "General",
            "is_followup": bool(row[5]),
            "response": encrypted_answer or legacy_answer,
            "time_taken": row[8],
            "question_spec_id": row[9],
            "taxonomy_keys": _json_value(row[10], []),
            "blueprint_section_id": row[11],
            "parent_question_id": row[12],
            "evaluator_version": row[13],
            "assessment": decrypt_json_field(row[14], row[15], None),
            "timing": _json_value(row[16], {}),
            "input_mode": row[17],
            "provenance": _json_value(row[18], {}),
            "expected_points": _json_value(row[19], []),
            "rubric_json": _json_value(row[20], {}),
            "question_order": row[21],
            "created_at": row[22],
        })
    return turns


async def _persist_scored_turns(turns: List[Dict[str, Any]]) -> None:
    # Raw response evidence is immutable. Assessments are append-only and are
    # never copied back into InterviewResponses by the reporting worker.
    return None


def _evidence_snippets(response: str) -> List[str]:
    sentences = [part.strip() for part in response.replace("\n", " ").split(".") if part.strip()]
    evidence = [
        sentence[:220]
        for sentence in sentences
        if any(ch.isdigit() for ch in sentence)
        or any(token in sentence.lower() for token in {"built", "led", "owned", "reduced", "improved", "launched", "debugged", "designed"})
    ]
    if evidence:
        return evidence[:3]
    return [response.strip()[:220]] if response.strip() else []


def _turn_confidence(word_count: int, evidence_count: int, filler_count: int) -> str:
    if word_count < 18 or evidence_count == 0:
        return "low"
    if word_count >= 45 and evidence_count >= 2 and filler_count <= 3:
        return "high"
    return "medium"


def _legacy_score_turn(turn: Dict[str, Any]) -> Dict[str, Any]:
    response = turn.get("response", "")
    words = response.split()
    word_count = len(words)
    has_metric = any(ch.isdigit() for ch in response)
    ownership = response.lower().count(" i ") + int(response.lower().startswith("i "))
    filler_count = _count_text_fillers(response)
    evidence = _evidence_snippets(response)
    question_tokens = {token for token in re.findall(r"[a-zA-Z]{4,}", str(turn.get("question") or "").lower())}
    response_tokens = {token for token in re.findall(r"[a-zA-Z]{4,}", response.lower())}
    overlap = len(question_tokens & response_tokens)
    relevance = 35.0 if not question_tokens else min(100.0, 40.0 + (overlap / max(len(question_tokens), 1)) * 80.0)
    structure_markers = sum(1 for token in ("first", "second", "because", "result", "trade", "challenge", "approach", "impact") if token in response.lower())
    structure = min(100.0, 35.0 + min(word_count, 80) * 0.45 + structure_markers * 8.0)
    ownership_score = min(100.0, 35.0 + min(ownership, 6) * 10.0)
    specificity = min(100.0, 30.0 + len(evidence) * 18.0 + (18.0 if has_metric else 0.0) + min(_keyword_hits(response) * 5.0, 20.0))
    tradeoff = 82.0 if any(token in response.lower() for token in ("trade", "constraint", "edge", "risk", "alternative", "because")) else 40.0
    clarity = min(100.0, max(20.0, 86.0 - filler_count * 5.0 - max(0, word_count - 180) * 0.08))
    if word_count < 5:
        return {
            **turn,
            "star_score": 0.0,
            "communication_score": 0.0,
            "technical_score": 0.0,
            "overall_score": 0.0,
            "feedback": "No candidate response was captured, so this turn is not gradable.",
            "confidence": "low",
            "insufficient_evidence": True,
            "evidence": [],
            "answer_quality_flags": ["no_response"],
            "rubric_scores": {
                "relevance": 0.0,
                "structure": 0.0,
                "ownership": 0.0,
                "specificity": 0.0,
                "tradeoff": 0.0,
                "clarity": 0.0,
            },
            "evidence_basis": {
                "word_count": word_count,
                "has_metric": has_metric,
                "filler_count": filler_count,
            },
        }
    insufficient_evidence = word_count < 18 or not evidence
    star_score = _clip((structure * 0.25) + (ownership_score * 0.25) + (specificity * 0.30) + (tradeoff * 0.20))
    communication = _clip(clarity)
    technical = _clip((specificity * 0.55) + (tradeoff * 0.25) + (relevance * 0.20))
    if insufficient_evidence:
        star_score = min(star_score, 45)
        technical = min(technical, 40)
        communication = min(communication, 60)
    overall = round((relevance * 0.20) + (structure * 0.18) + (ownership_score * 0.14) + (specificity * 0.22) + (tradeoff * 0.12) + (clarity * 0.14), 1)
    if insufficient_evidence:
        overall = min(overall, 48.0)
    flags: List[str] = []
    if word_count < 18:
        flags.append("too_short")
    if not evidence:
        flags.append("no_evidence")
    if ownership_score < 50:
        flags.append("missing_ownership")
    if tradeoff < 50:
        flags.append("missing_tradeoff")
    return {
        **turn,
        "star_score": round(star_score, 1),
        "communication_score": round(communication, 1),
        "technical_score": round(technical, 1),
        "overall_score": overall,
        "feedback": _feedback_for_turn(overall, flags, evidence),
        "confidence": _turn_confidence(word_count, len(evidence), filler_count),
        "insufficient_evidence": insufficient_evidence,
        "evidence": evidence,
        "answer_quality_flags": flags,
        "rubric_scores": {
            "relevance": round(relevance, 1),
            "structure": round(structure, 1),
            "ownership": round(ownership_score, 1),
            "specificity": round(specificity, 1),
            "tradeoff": round(tradeoff, 1),
            "clarity": round(clarity, 1),
        },
        "evidence_basis": {
            "word_count": word_count,
            "has_metric": has_metric,
            "filler_count": filler_count,
            "question_overlap_terms": overlap,
        },
    }


def _average_available(values: Sequence[Any]) -> Optional[float]:
    clean = [float(value) for value in values if isinstance(value, (int, float))]
    return round(sum(clean) / len(clean), 1) if clean else None


def _confidence_label_from_number(value: Any) -> str:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return "low"
    if numeric >= 0.80:
        return "high"
    if numeric >= 0.60:
        return "medium"
    return "low"


def _assessment_feedback(assessment: Dict[str, Any], flags: List[str]) -> str:
    follow_up = assessment.get("follow_up") or {}
    if follow_up.get("prompt"):
        return str(follow_up["prompt"])
    labels = {
        "empty_answer": "No candidate response was captured, so this turn is not gradable.",
        "too_short": "Answer directly, then add the owned action, supporting detail, and result.",
        "unsupported_or_unspecific": "Support the claim with a concrete action, result, or verifiable example.",
        "ownership_unclear": "Clarify what you personally owned and changed.",
        "missing_tradeoffs": "Explain the constraint, alternative, and trade-off behind the decision.",
        "indirect_response": "Lead with the direct answer before adding context.",
        "technical_accuracy_unknown": "Technical correctness was not scored because valid correctness evidence was unavailable.",
    }
    for flag in flags:
        if flag in labels:
            return labels[flag]
    return "The recorded evaluator evidence supports this assessment."


def _score_turn(turn: Dict[str, Any]) -> Dict[str, Any]:
    if not str(turn.get("response") or "").strip():
        return {
            **turn,
            "star_score": None,
            "communication_score": None,
            "technical_score": None,
            "overall_score": 0.0,
            "feedback": "No candidate response was captured for this question.",
            "confidence": "high",
            "confidence_value": 1.0,
            "insufficient_evidence": True,
            "authoritative": False,
            "evidence": [],
            "answer_quality_flags": ["no_response"],
            "rubric_scores": {},
            "evidence_basis": {"assessment_status": "no_response"},
            "evaluator_version": turn.get("evaluator_version"),
        }
    assessment = turn.get("assessment")
    if not isinstance(assessment, dict):
        return {
            **turn,
            "star_score": None,
            "communication_score": None,
            "technical_score": None,
            "overall_score": None,
            "feedback": "No append-only evaluator assessment is available for this response.",
            "confidence": "low",
            "confidence_value": 0.0,
            "insufficient_evidence": True,
            "evidence": [],
            "answer_quality_flags": ["assessment_missing"],
            "rubric_scores": {},
            "evidence_basis": {"assessment_status": "missing"},
            "evaluator_version": turn.get("evaluator_version"),
        }

    scores = assessment.get("scores") if isinstance(assessment.get("scores"), dict) else {}
    evidence = assessment.get("evidence") if isinstance(assessment.get("evidence"), dict) else {}
    signals = assessment.get("signals") if isinstance(assessment.get("signals"), dict) else {}
    flags = [str(item) for item in (assessment.get("flags") or [])]
    confidence_value = float(assessment.get("confidence") or 0.0)
    star_score = _average_available([
        scores.get("structure"), scores.get("ownership"), scores.get("specificity_evidence"),
    ])
    communication_score = _average_available([
        scores.get("directness"), scores.get("filler_control"), scores.get("structure"),
    ])
    technical_score = scores.get("technical_accuracy")
    overall_score = assessment.get("overall_score")
    authoritative = bool(assessment.get("authoritative", overall_score is not None))
    insufficient = (
        not authoritative
        or overall_score is None
        or assessment.get("evidence_status") == "insufficient_evidence"
        or bool(assessment.get("insufficient_evidence"))
    )
    quotes = list(evidence.get("evidence_quotes") or evidence.get("deterministic_quotes") or [])
    return {
        **turn,
        "star_score": star_score,
        "communication_score": communication_score,
        "technical_score": technical_score,
        "overall_score": overall_score,
        "provisional_score": assessment.get("provisional_score"),
        "feedback": _assessment_feedback(assessment, flags),
        "confidence": _confidence_label_from_number(confidence_value),
        "confidence_value": confidence_value,
        "insufficient_evidence": insufficient,
        "authoritative": authoritative,
        "evidence": quotes,
        "answer_quality_flags": flags,
        "rubric_scores": scores,
        "evidence_basis": {
            "signals": signals,
            "covered_point_ids": evidence.get("covered_points") or [],
            "missed_point_ids": evidence.get("missed_points") or [],
            "incorrect_claim_ids": evidence.get("incorrect_claims") or [],
            "contradictions": evidence.get("contradictions") or [],
            "semantic_status": assessment.get("semantic_status") or {},
            "follow_up": assessment.get("follow_up") or {},
        },
        "evaluator_version": turn.get("evaluator_version") or assessment.get("version"),
    }


def _avg(values: List[float]) -> float:
    clean = [float(value) for value in values if value is not None]
    return round(sum(clean) / len(clean), 1) if clean else 0.0


def _count_text_fillers(text: str) -> int:
    fillers = {"um", "uh", "like", "basically", "actually", "sort", "kinda"}
    return sum(1 for token in text.lower().replace(",", " ").split() if token.strip(".!?") in fillers)


def _count_fillers(transcript: List[Dict[str, Any]]) -> float:
    candidate = " ".join(item.get("text", "") for item in transcript if item.get("role") == "candidate")
    return round(_count_text_fillers(candidate) / 2, 1)


def _keyword_hits(text: str) -> int:
    keywords = {
        "api", "database", "latency", "cache", "queue", "test", "debug",
        "model", "system", "complexity", "edge", "trade", "scale", "metric",
    }
    lowered = text.lower()
    return sum(1 for keyword in keywords if keyword in lowered)


def _feedback_for_turn(score: float, flags: List[str], evidence: List[str]) -> str:
    if "no_response" in flags:
        return "No candidate response was captured, so this turn is not gradable."
    if "too_short" in flags:
        return "The answer is too short to prove the claim. Add direct answer, owned action, technical detail, and result."
    if "no_evidence" in flags:
        return "The answer does not include a concrete project fact, metric, shipped result, or technical proof point."
    if "missing_tradeoff" in flags:
        return "The answer needs the constraint, trade-off, edge case, or reason behind the decision."
    if "missing_ownership" in flags:
        return "Clarify what you personally owned instead of describing the team's work generically."
    if score >= 80:
        return "Strong answer with specific evidence and enough structure to be credible."
    if score >= 60:
        return "Usable answer, but sharpen the evidence and make the reasoning easier to follow."
    if evidence:
        return "Some evidence was present, but the answer needs clearer structure and stronger relevance to the question."
    return "Answer needs clearer structure, ownership, and concrete proof."


def _feedback_for_score(score: float) -> str:
    if score >= 80:
        return "Strong answer with enough structure and evidence to be credible."
    if score >= 60:
        return "Usable answer, but it needs sharper evidence, metrics, or trade-off detail."
    return "Answer needs clearer structure, ownership, and concrete proof."


def _technical_authenticity_flags(submissions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    flags = []
    if submissions and submissions[0].get("source_chars", 0) > 5000:
        flags.append({"event_type": "large_final_submission", "detail": "Final source was unusually large."})
    return flags


def _technical_weak_topics(
    submissions: List[Dict[str, Any]],
    run_events: Optional[List[Dict[str, Any]]] = None,
    drafts: Optional[List[Dict[str, Any]]] = None,
    typed_responses: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    topics: Dict[str, Dict[str, Any]] = {}
    final_round_ids = {item.get("round_id") for item in submissions if item.get("round_id")}
    evidence_items: List[tuple[Dict[str, Any], str]] = []
    evidence_items.extend((item, "final_submission") for item in submissions)
    evidence_items.extend(
        (item, "run_only")
        for item in (run_events or [])
        if item.get("round_id") not in final_round_ids
    )
    run_round_ids = {item.get("round_id") for item in (run_events or []) if item.get("round_id")}
    evidence_items.extend(
        (item, "draft_only")
        for item in (drafts or [])
        if item.get("round_id") not in final_round_ids and item.get("round_id") not in run_round_ids
    )
    evidence_items.extend(
        (
            item,
            "assessed_response"
            if item.get("score") is not None and not item.get("insufficient_evidence")
            else "insufficient_evidence",
        )
        for item in (typed_responses or [])
    )

    for item, evidence_state in evidence_items:
        typed_evidence = evidence_state in {"assessed_response", "insufficient_evidence"}
        topic = item.get("algorithm_pattern") or (
            item.get("title") if typed_evidence else "technical correctness"
        ) or "technical correctness"
        total = int(item.get("visible_total") or 0) + int(item.get("hidden_total") or 0)
        passed = int(item.get("visible_passed") or 0) + int(item.get("hidden_passed") or 0)
        if not total:
            total = int(item.get("total_count") or 0)
            passed = int(item.get("pass_count") or 0)
        if typed_evidence and item.get("score") is not None:
            total = 100
            passed = max(0, min(100, int(float(item.get("score") or 0))))
        bucket = topics.setdefault(
            topic,
            {
                "topic": topic,
                "passed": 0,
                "total": 0,
                "round_ids": [],
                "evidence_states": set(),
                "titles": [],
                "typed_evidence": False,
            },
        )
        bucket["passed"] += passed
        bucket["total"] += total
        round_id = item.get("round_id")
        if round_id and round_id not in bucket["round_ids"]:
            bucket["round_ids"].append(round_id)
        bucket["evidence_states"].add(evidence_state)
        bucket["typed_evidence"] = bucket["typed_evidence"] or typed_evidence
        if item.get("title"):
            bucket["titles"].append(item.get("title"))
    weak = []
    for bucket in topics.values():
        total = bucket["total"]
        pass_rate = round((bucket["passed"] / total) * 100, 1) if total else 0.0
        evidence_states = sorted(bucket["evidence_states"])
        draft_or_run_only = any(state != "final_submission" for state in evidence_states)
        failed_final_case = (
            "final_submission" in evidence_states
            and total > 0
            and bucket["passed"] < total
        )
        if pass_rate < 80 or draft_or_run_only or failed_final_case:
            weak.append({
                "topic": bucket["topic"],
                "pass_rate": pass_rate,
                "round_ids": bucket["round_ids"],
                "evidence_state": ", ".join(evidence_states),
                "example_questions": list(dict.fromkeys(bucket["titles"]))[:3],
                "repair_action": (
                    "Complete the technical explanation with the decision, complexity, and edge case that were missing."
                    if bucket.get("typed_evidence") and total == 0
                    else "Submit a final solution for this pattern so correctness can be graded."
                    if draft_or_run_only and total == 0
                    else "Redo the failing solution with one minimal edge case first, then generalize the algorithm."
                ),
            })
    return sorted(weak, key=lambda item: item["pass_rate"])[:5]


def _with_transcript(report: Dict[str, Any], transcript_output: Dict[str, Any], **extra: Any) -> Dict[str, Any]:
    return {
        **report,
        "transcript": transcript_output.get("transcript") or [],
        "evidence_status": report.get("evidence_status") or {
            "status": "no_candidate_evidence" if transcript_output.get("insufficient_evidence") else "scored",
            "candidate_word_count": transcript_output.get("candidate_word_count", 0),
            "interviewer_word_count": transcript_output.get("interviewer_word_count", 0),
        },
        **extra,
    }


async def _schedule_media_cleanup(interview_id: str) -> None:
    now = datetime.now(timezone.utc)
    retention_windows = {
        "video": timedelta(hours=max(0, settings.RAW_VIDEO_RETENTION_HOURS)),
        "audio": timedelta(days=max(0, settings.AUDIO_RETENTION_DAYS)),
    }
    for media_kind, window in retention_windows.items():
        await async_execute(
            """
            UPDATE InterviewMediaAssets
            SET delete_after = MIN(COALESCE(delete_after, ?), ?),
                retention_status = CASE
                    WHEN retention_status IN ('retained', 'cleanup_scheduled')
                    THEN 'cleanup_scheduled'
                    ELSE retention_status
                END
            WHERE interview_id = ? AND media_kind = ?
            """,
            (now + window, now + window, interview_id, media_kind),
        )
