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
from learning_engine import (
    ensure_mission_from_weakness,
    ingest_interview_evidence,
    validate_mission_with_analysis,
)
from llm_router import complete_json_async
from premium_report_builder import build_premium_report
from report_generator import build_async_behavioral_report, build_async_technical_report
from security_utils import decrypt_data, decrypt_json, encrypt_data, stable_hash
from weakness_engine import RUBRIC_VERSION, TAXONOMY_VERSION, persist_weakness_states

logger = logging.getLogger("analysis_pipeline")

ANALYSIS_STAGES = (
    "evidence_load",
    "transcript_analysis",
    "technical_analysis",
    "integrity_summary",
    "deterministic_report",
    "semantic_enhancement",
    "report_validation",
    "performance_projection",
    "weakness_update",
    "improve_update",
    "complete",
)

ANALYSIS_STAGE_VERSION = "evidence-v3"
ANALYSIS_LEASE_SECONDS = 90
ANALYSIS_MAX_RETRIES = 3
TERMINAL_INTERVIEW_STATUSES = {"completed", "partial", "failed", "cancelled"}
REPORT_READY_INTERVIEW_STATUSES = {"completed", "partial", "failed"}
EVIDENCE_MANIFEST_VERSION = "evidence-manifest-v1"


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
    cursor.execute(
        "SELECT manifest_id, evidence_hash FROM EvidenceManifests WHERE interview_id = %s AND user_id = %s FOR UPDATE",
        (interview_id, user_id),
    )
    existing = cursor.fetchone()
    if existing:
        return str(existing[0]), str(existing[1])

    cursor.execute("SELECT NOW()")
    sealed_at = cursor.fetchone()[0]
    item_queries = (
        (
            "interview_question", "question-contract-v1",
            """SELECT question.question_id, question.created_at, question.taxonomy_keys,
                      question.expected_points, question.rubric_json, question.question_type,
                      question.rubric_version, question.provenance
               FROM InterviewQuestions question
               JOIN Interviews interview ON interview.interview_id = question.interview_id
               WHERE question.interview_id = %s AND interview.user_id = %s AND question.created_at <= %s""",
        ),
        (
            "interview_response", "response-v1",
            """SELECT response_id, created_at, question_id, user_response, response_time_seconds,
                      evaluation_json, answer_quality_flags, evidence_quotes, stt_confidence,
                      answer_text_encrypted, raw_answer_hash, evidence_hash, input_mode, timing_json
               FROM InterviewResponses response
               WHERE response.interview_id = %s
                 AND EXISTS (SELECT 1 FROM Interviews interview WHERE interview.interview_id = response.interview_id AND interview.user_id = %s)
                 AND response.created_at <= %s""",
        ),
        (
            "response_assessment", "assessment-v1",
            """SELECT assessment_id, created_at, response_id, evaluator_version, evidence_hash, overall_score, assessment_json
               FROM ResponseAssessments assessment
               WHERE assessment.interview_id = %s
                 AND EXISTS (SELECT 1 FROM Interviews interview WHERE interview.interview_id = assessment.interview_id AND interview.user_id = %s)
                 AND assessment.created_at <= %s""",
        ),
        (
            "technical_submission", "technical-submission-v1",
            """SELECT submission_id, created_at, round_id, code_hash, submit_number, visible_passed,
                      visible_total, hidden_passed, hidden_total, status, execution_job_id
               FROM TechnicalSubmissions WHERE interview_id = %s AND user_id = %s AND created_at <= %s""",
        ),
        (
            "technical_run", "technical-run-v1",
            """SELECT run.run_id, run.created_at, run.round_id, run.code_hash, run.exit_code,
                      run.error_signature, run.runtime_ms, run.metadata, run.hidden_validation_result
               FROM TechnicalRunEvents run JOIN TechnicalInterviewRounds round ON round.round_id = run.round_id
               WHERE round.interview_id = %s AND run.user_id = %s AND run.created_at <= %s""",
        ),
        (
            "technical_code_snapshot", "code-snapshot-v1",
            """SELECT snapshot_id, created_at, round_id, code_hash, source_chars, metadata
               FROM TechnicalCodeSnapshots WHERE interview_id = %s AND user_id = %s AND created_at <= %s""",
        ),
        (
            "technical_reasoning", "technical-reasoning-v1",
            """SELECT evidence_id::text, created_at, round_id, evidence_type, content, payload,
                      content_encrypted, evidence_hash, idempotency_key
               FROM TechnicalReasoningEvidence WHERE interview_id = %s AND user_id = %s AND created_at <= %s""",
        ),
        (
            "integrity_event", "attempt-integrity-v1",
            """SELECT event_id, received_at, client_session_id, sequence, event_type, severity, source,
                      observed_at, payload_hash
               FROM AttemptIntegrityEvents WHERE interview_id = %s AND user_id = %s AND received_at <= %s""",
        ),
        (
            "anti_cheat_event", "anti-cheat-v1",
            """SELECT event_id::text, created_at, event_type, payload
               FROM AntiCheatEvents WHERE interview_id = %s AND user_id = %s AND created_at <= %s""",
        ),
        (
            "media_asset", "media-manifest-v1",
            """SELECT asset_id, created_at, media_kind, checksum, byte_size, chunk_index, chunk_count, status
               FROM InterviewMediaAssets WHERE interview_id = %s AND user_id = %s AND created_at <= %s""",
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
        INSERT INTO EvidenceManifests (
            manifest_id, interview_id, user_id, schema_version, evidence_hash,
            item_count, manifest_json, manifest_encrypted, sealed_at
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            manifest_id, interview_id, user_id, EVIDENCE_MANIFEST_VERSION,
            evidence_hash, len(items), json.dumps(safe_manifest),
            encrypt_data(json.dumps(canonical, default=str)).encode("utf-8"), sealed_at,
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


def aggregate_cheating_risk(event_counts: Counter, media_summary: Dict[str, Any], code_summary: Dict[str, Any]) -> Dict[str, Any]:
    weights = {
        "fullscreen_exit": 20,
        "tab_switch": 18,
        "window_blur": 8,
        "paste": 22,
        "paste_blocked": 18,
        "large_paste": 28,
        "clipboard_code": 15,
        "second_speaker": 35,
        "face_missing": 25,
        "multiple_faces": 30,
        "multiple_people_detected": 35,
        "mobile_phone_detected": 35,
        "large_code_jump": 24,
        "screen_not_monitor": 28,
        "no_clarification_before_coding": 8,
        "suspicious_clipboard_pattern": 24,
        "identity_mismatch": 40,
        "gaze_offscreen": 10,
        "visible_output_hardcode": 28,
    }
    score = 0
    flags: List[Dict[str, Any]] = []
    for event_type, count in event_counts.items():
        weight = weights.get(event_type, 4)
        contribution = min(weight * count, weight * 3)
        score += contribution
        flags.append({"event_type": event_type, "count": count, "severity": "high" if weight >= 20 else "medium"})

    media_flags = media_summary.get("flags") or []
    code_flags = code_summary.get("authenticity_flags") or []
    score += min(len(media_flags) * 12, 36)
    score += min(len(code_flags) * 15, 45)
    normalized = max(0, min(100, score))
    return {
        "risk_score": normalized,
        "risk_level": _score_band(100 - normalized),
        "events": flags,
        "media_flags": media_flags,
        "code_flags": code_flags,
    }


async def enqueue_analysis(
    interview_id: str,
    user_id: str,
    reason: str = "session_end",
    *,
    force_canonical_rebuild: bool = False,
) -> Optional[str]:
    def _get_or_create_job() -> tuple[Optional[str], bool]:
        from database import get_db_connection, return_db_connection

        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"analysis:{interview_id}",))
            cursor.execute(
                """
                SELECT status, report_json, analysis_job_id, evidence_sealed_at, evidence_hash,
                       attempt_status
                FROM Interviews
                WHERE interview_id = %s AND user_id = %s
                FOR UPDATE
                """,
                (interview_id, user_id),
            )
            interview_row = cursor.fetchone()
            if not interview_row:
                conn.commit()
                return None, False

            if str(interview_row[5] or "") != "completed":
                conn.commit()
                return None, False

            if _is_report_ready_status(interview_row[0], interview_row[1]):
                cursor.execute(
                    """
                    SELECT 1 FROM SessionPerformanceAnalyses
                    WHERE interview_id = %s AND user_id = %s
                      AND schema_version = 'session-performance-v3'
                      AND status = 'ready'
                      AND analysis_json_encrypted IS NOT NULL
                    LIMIT 1
                    """,
                    (interview_id, user_id),
                )
                canonical_ready = bool(cursor.fetchone())
                if canonical_ready or not force_canonical_rebuild:
                    conn.commit()
                    return interview_row[2], False

            manifest_id, evidence_hash = _seal_evidence_manifest(cursor, interview_id, user_id)
            cursor.execute(
                """
                UPDATE Interviews
                SET evidence_hash = %s,
                    evidence_sealed_at = COALESCE(evidence_sealed_at, NOW())
                WHERE interview_id = %s AND user_id = %s
                """,
                (evidence_hash, interview_id, user_id),
            )
            idempotency_key = f"analysis:{evidence_hash}"
            cursor.execute(
                """
                SELECT job_id, status, retry_count
                FROM AnalysisJobs
                WHERE user_id = %s AND idempotency_key = %s
                LIMIT 1
                FOR UPDATE
                """,
                (user_id, idempotency_key),
            )
            existing = cursor.fetchone()

            if existing and existing[1] in {"queued", "running"}:
                conn.commit()
                return existing[0], True

            if existing and (existing[2] or 0) >= ANALYSIS_MAX_RETRIES:
                conn.commit()
                return existing[0], False

            if existing:
                cursor.execute(
                    """
                    UPDATE AnalysisJobs
                    SET status = 'queued', next_attempt_at = NOW(), error_message = NULL,
                        completed_at = NULL, updated_at = NOW(), lease_owner = NULL,
                        lease_expires_at = NULL, heartbeat_at = NULL
                    WHERE job_id = %s
                    """,
                    (existing[0],),
                )
                cursor.execute(
                    "UPDATE Interviews SET analysis_job_id = %s WHERE interview_id = %s",
                    (existing[0], interview_id),
                )
                conn.commit()
                return existing[0], True

            job_id = str(uuid.uuid4())
            cursor.execute(
                """
                INSERT INTO AnalysisJobs (
                    job_id, interview_id, user_id, status, trigger_reason,
                    progress, retry_count, idempotency_key, evidence_hash, manifest_id,
                    next_attempt_at, created_at, updated_at
                )
                VALUES (%s, %s, %s, 'queued', %s, 0, 0, %s, %s, %s, NOW(), NOW(), NOW())
                """,
                (job_id, interview_id, user_id, reason, idempotency_key, evidence_hash, manifest_id),
            )
            cursor.execute(
                "UPDATE Interviews SET analysis_job_id = %s WHERE interview_id = %s",
                (job_id, interview_id),
            )
            conn.commit()
            return job_id, True
        except Exception:
            conn.rollback()
            raise
        finally:
            cursor.close()
            return_db_connection(conn)

    job_id, should_start = await asyncio.to_thread(_get_or_create_job)
    if not job_id:
        return None
    if not should_start:
        logger.info(
            "Analysis enqueue skipped for %s; report already ready or retry limit reached",
            stable_hash(interview_id, "interview"),
        )
    return job_id


async def operator_retry_analysis(interview_id: str, actor_user_id: str) -> Dict[str, Any]:
    """Requeue the same sealed analysis identity without duplicating a report."""
    def _retry() -> Dict[str, Any]:
        from database import get_db_connection, return_db_connection

        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"analysis:{interview_id}",))
            cursor.execute(
                """
                SELECT (i.attempt_status = 'completed' OR i.status IN ('completed', 'partial', 'failed')) AS completed_attempt,
                       i.report_json, i.report_json_encrypted,
                       job.job_id, job.status, job.manual_retry_count, job.evidence_hash, job.manifest_id
                FROM Interviews i
                LEFT JOIN LATERAL (
                    SELECT job_id, status, manual_retry_count, evidence_hash, manifest_id
                    FROM AnalysisJobs WHERE interview_id = i.interview_id
                    ORDER BY created_at DESC LIMIT 1 FOR UPDATE
                ) job ON TRUE
                WHERE i.interview_id = %s
                FOR UPDATE OF i
                """,
                (interview_id,),
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
                    next_attempt_at = NOW(), error_message = NULL,
                    current_stage = 'evidence_load', progress = 0,
                    completed_at = NULL, updated_at = NOW(),
                    lease_owner = NULL, lease_expires_at = NULL, heartbeat_at = NULL
                WHERE job_id = %s
                RETURNING job_id, manual_retry_count
                """,
                (row[3],),
            )
            retried = cursor.fetchone()
            cursor.execute(
                """
                UPDATE Interviews
                SET status = 'analysis_pending', analysis_status = 'queued', analysis_job_id = %s
                WHERE interview_id = %s
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
        ) VALUES (%s, %s, %s, '{}'::jsonb, NOW(), NOW())
        ON CONFLICT (worker_id) DO UPDATE
        SET worker_type = EXCLUDED.worker_type,
            version = EXCLUDED.version,
            heartbeat_at = NOW()
        """,
        (worker_id, worker_type, ANALYSIS_STAGE_VERSION),
    )


async def claim_analysis_job(worker_id: str) -> Optional[tuple[str, str, str]]:
    return await async_execute(
        """
        WITH candidate AS (
            SELECT job_id
            FROM AnalysisJobs
            WHERE retry_count < %s
              AND COALESCE(next_attempt_at, NOW()) <= NOW()
              AND (
                  status = 'queued'
                  OR (status = 'running' AND lease_expires_at < NOW())
              )
            ORDER BY created_at ASC
            FOR UPDATE SKIP LOCKED
            LIMIT 1
        )
        UPDATE AnalysisJobs AS job
        SET status = 'running',
            lease_owner = %s,
            lease_expires_at = NOW() + (%s * INTERVAL '1 second'),
            heartbeat_at = NOW(),
            started_at = COALESCE(started_at, NOW()),
            updated_at = NOW()
        FROM candidate
        WHERE job.job_id = candidate.job_id
        RETURNING job.job_id, job.interview_id, job.user_id
        """,
        (ANALYSIS_MAX_RETRIES, worker_id, ANALYSIS_LEASE_SECONDS),
        fetchone=True,
    )


async def _claim_specific_analysis_job(job_id: str, worker_id: str) -> Optional[tuple[str, str, str]]:
    return await async_execute(
        """
        UPDATE AnalysisJobs
        SET status = 'running', lease_owner = %s,
            lease_expires_at = NOW() + (%s * INTERVAL '1 second'),
            heartbeat_at = NOW(), started_at = COALESCE(started_at, NOW()),
            updated_at = NOW()
        WHERE job_id = %s
          AND retry_count < %s
          AND COALESCE(next_attempt_at, NOW()) <= NOW()
          AND (status = 'queued' OR (status = 'running' AND lease_expires_at < NOW()))
        RETURNING job_id, interview_id, user_id
        """,
        (worker_id, ANALYSIS_LEASE_SECONDS, job_id, ANALYSIS_MAX_RETRIES),
        fetchone=True,
    )


async def _renew_analysis_lease(job_id: str, worker_id: str) -> None:
    row = await async_execute(
        """
        UPDATE AnalysisJobs
        SET lease_expires_at = NOW() + (%s * INTERVAL '1 second'),
            heartbeat_at = NOW(), updated_at = NOW()
        WHERE job_id = %s AND status = 'running' AND lease_owner = %s
        RETURNING job_id
        """,
        (ANALYSIS_LEASE_SECONDS, job_id, worker_id),
        fetchone=True,
    )
    if not row:
        raise RuntimeError("analysis_job_lease_lost")


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
            claimed = await claim_analysis_job(worker_id)
            if not claimed:
                await asyncio.sleep(idle_seconds)
                continue
            await run_analysis_job(claimed[0], worker_id=worker_id, claimed_job=claimed)
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
              (delete_after IS NOT NULL AND delete_after <= NOW())
              OR (status = 'pending' AND created_at < NOW() - INTERVAL '1 hour')
              OR (%s AND media_kind = 'video')
              OR (%s AND media_kind = 'audio')
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


async def _queue_learning_from_analysis(interview_id: str, user_id: str) -> None:
    try:
        profile_row = await async_execute(
            """
            SELECT u.profile_json, u.resume_json, s.resume_payload_encrypted
            FROM UserInfo u
            LEFT JOIN AttemptContextSnapshots s
              ON s.interview_id = %s AND s.user_id = u.user_id
            WHERE u.user_id = %s
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
        logger.warning("Learning exercise generation skipped for %s", stable_hash(interview_id, "interview"))


async def _report_action_for_mode(user_id: str, mode: str) -> Optional[Dict[str, Any]]:
    row = await async_execute(
        """
        SELECT mission.mission_id, node.roadmap_node_id, node.exercise_id,
               node.activity_type, node.title
        FROM ImprovementMissions mission
        LEFT JOIN LATERAL (
            SELECT roadmap_node_id, exercise_id, activity_type, title
            FROM ImprovementRoadmapNodes
            WHERE mission_id = mission.mission_id AND user_id = mission.user_id
              AND availability_status IN ('current', 'available')
              AND exercise_id IS NOT NULL
              AND result_status NOT IN ('passed', 'strong_pass')
            ORDER BY CASE WHEN availability_status = 'current' THEN 0 ELSE 1 END,
                     order_index
            LIMIT 1
        ) node ON TRUE
        WHERE mission.user_id = %s AND mission.mode = %s AND mission.status = 'active'
        ORDER BY mission.priority_score DESC, mission.updated_at DESC
        LIMIT 1
        """,
        (user_id, "technical" if mode == "technical" else "mock"),
        fetchone=True,
    )
    if not row:
        return None
    return {
        "action": "open_improve_activity",
        "mission_id": row[0],
        "roadmap_node_id": row[1],
        "exercise_id": row[2],
        "activity_type": row[3],
        "label": row[4],
    }


async def _run_analysis_job_legacy(job_id: str) -> None:
    job = await async_execute(
        """
        UPDATE AnalysisJobs
        SET status = 'running',
            started_at = COALESCE(started_at, NOW()),
            updated_at = NOW()
        WHERE job_id = %s
          AND (
            status = 'queued'
            OR (status = 'running' AND updated_at < NOW() - INTERVAL '5 minutes')
          )
        RETURNING job_id, interview_id, user_id
        """,
        (job_id,),
        fetchone=True,
    )
    if not job:
        return

    _, interview_id, user_id = job
    logger.info("Starting async analysis job %s for %s", stable_hash(job_id, "analysis"), stable_hash(interview_id, "interview"))
    try:
        await async_execute(
            """
            UPDATE Interviews
            SET status = 'analysis_running'
            WHERE interview_id = %s
              AND status <> 'cancelled'
              AND NOT (status IN ('completed', 'partial', 'failed') AND report_json IS NOT NULL)
            """,
            (interview_id,),
        )

        stage_outputs: Dict[str, Dict[str, Any]] = {}
        for index, stage in enumerate(ANALYSIS_STAGES, start=1):
            started = datetime.now(timezone.utc)

            if stage == "report_generation":
                await async_execute(
                    """
                    UPDATE AnalysisJobs
                    SET progress = 90, current_stage = %s, updated_at = NOW()
                    WHERE job_id = %s
                    """,
                    (stage, job_id),
                )

            try:
                output = await _run_stage(stage, interview_id, user_id, stage_outputs)
                stage_outputs[stage] = output
                status = "completed"
                error = None
            except Exception as exc:
                logger.error("Analysis stage %s failed for %s", stage, stable_hash(interview_id, "interview"))
                output = {"error": "stage_failed", "stage": stage}
                stage_outputs[stage] = output
                status = "failed"
                error = str(exc)[:500]

            await async_execute(
                """
                INSERT INTO AnalysisStageOutputs (
                    output_id, job_id, interview_id, stage_name, status, output_json,
                    error_message, started_at, completed_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
                """,
                (
                    str(uuid.uuid4()),
                    job_id,
                    interview_id,
                    stage,
                    status,
                    _json_dumps(output),
                    error,
                    started,
                ),
            )
            progress = 100 if stage == "complete" else math.floor(index / len(ANALYSIS_STAGES) * 100)
            await async_execute(
                """
                UPDATE AnalysisJobs
                SET progress = %s, current_stage = %s, updated_at = NOW()
                WHERE job_id = %s
                """,
                (progress, stage, job_id),
            )

        legacy_stage_outputs = _legacy_stage_outputs(stage_outputs)
        report = legacy_stage_outputs.get("report_generation") or {}
        partial = any((stage_outputs.get(stage) or {}).get("error") for stage in ANALYSIS_STAGES)
        final_status = "partial" if partial else "completed"
        existing_artifact = await async_execute(
            """
            SELECT artifact_id
            FROM ReportArtifacts
            WHERE interview_id = %s AND user_id = %s AND audience = 'candidate'
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (interview_id, user_id),
            fetchone=True,
        )
        if existing_artifact:
            await async_execute(
                """
                UPDATE ReportArtifacts
                SET report_type = %s,
                    payload = %s
                WHERE artifact_id = %s
                """,
                (
                    report.get("report_type") or "interview",
                    _json_dumps(report),
                    existing_artifact[0],
                ),
            )
        else:
            await async_execute(
                """
                INSERT INTO ReportArtifacts (artifact_id, interview_id, user_id, report_type, audience, payload)
                VALUES (%s, %s, %s, %s, 'candidate', %s)
                """,
                (
                    str(uuid.uuid4()),
                    interview_id,
                    user_id,
                    report.get("report_type") or "interview",
                    _json_dumps(report),
                ),
            )
        await async_execute(
            """
            UPDATE Interviews
            SET status = %s,
                overall_score = %s,
                feedback_summary = %s,
                report_json = %s,
                completed_at = COALESCE(completed_at, NOW())
            WHERE interview_id = %s
              AND status <> 'cancelled'
              AND NOT (status IN ('completed', 'partial', 'failed') AND report_json IS NOT NULL)
            """,
            (
                final_status,
                report.get("overall_score", 0),
                report.get("summary", "Analysis completed."),
                _json_dumps(report),
                interview_id,
            ),
        )
        await async_execute(
            """
            UPDATE AnalysisJobs
            SET status = %s, progress = 100, current_stage = 'complete',
                completed_at = NOW(), updated_at = NOW()
            WHERE job_id = %s
            """,
            (final_status, job_id),
        )
        await _queue_learning_from_analysis(interview_id, user_id)
        await _schedule_media_cleanup(interview_id)
    except Exception as exc:
        logger.error("Async analysis job failed for %s", stable_hash(interview_id, "interview"))
        await async_execute(
            """
            UPDATE AnalysisJobs
            SET status = 'failed', error_message = %s, updated_at = NOW(), completed_at = NOW()
            WHERE job_id = %s
            """,
            (str(exc)[:500], job_id),
        )
        await async_execute(
            """
            UPDATE Interviews
            SET status = 'failed'
            WHERE interview_id = %s
              AND status <> 'cancelled'
              AND report_json IS NULL
            """,
            (interview_id,),
        )


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


def _safe_report_payload(report: Dict[str, Any]) -> Dict[str, Any]:
    allowed = {
        "version", "interview_id", "analysis_id", "report_type", "report_subtype",
        "profile_type", "readiness_label", "overall_score", "recommendation_confidence",
        "scoring_confidence", "evidence_policy", "evidence_summary", "evidence_status",
        "dimension_scores", "behavioral_metrics", "technical_process", "weak_topics",
        "findings",
        "candidate_visible_integrity", "ai_enhanced", "ai_provider_policy",
        "ai_fallback_reason", "report_actions",
        "report_state", "evidence_hash", "evidence_manifest_id", "generation_provenance",
        "score_provenance",
    }
    return {key: value for key, value in report.items() if key in allowed}


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
        "engine": "openai_narrative_enhancement" if ai_enhanced else "deterministic_inter_pipeline",
        "model": settings.OPENAI_REPORT_MODEL if ai_enhanced else None,
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
        FROM Interviews WHERE interview_id = %s AND user_id = %s
        """,
        (interview_id, user_id), fetchone=True,
    )
    if not ownership or str(ownership[2] or "") != evidence_hash:
        raise RuntimeError("report_evidence_hash_or_ownership_mismatch")
    manifest = await async_execute(
        """
        SELECT manifest_json FROM EvidenceManifests
        WHERE manifest_id = %s AND interview_id = %s AND user_id = %s AND evidence_hash = %s
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
        return {
            key: value
            for key, value in output.items()
            if key not in {
                "submissions", "final_submissions", "all_submissions", "run_events",
                "drafts", "typed_responses", "source_code", "source_excerpt",
            }
        }
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
        "cheating_risk": outputs.get("integrity_summary") or {},
        "report_generation": (
            outputs.get("complete")
            or outputs.get("report_validation")
            or outputs.get("semantic_enhancement")
            or outputs.get("deterministic_report")
            or {}
        ),
    }


def _turn_observations(turns: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
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
        for skill_key in skill_keys:
            observations.append({
                "skill_key": skill_key,
                "source_key": turn.get("response_id"),
                "source_kind": (
                    "technical_response"
                    if str(turn.get("question_type") or "").lower() in technical_types
                    else "interview_response"
                ),
                "evidence_type": "interview",
                "response_id": turn.get("response_id"),
                "round_id": provenance.get("technical_round_id"),
                "question_spec_id": turn.get("question_spec_id"),
                "score": turn.get("overall_score"),
                "confidence": turn.get("confidence_value") or turn.get("confidence"),
                "flags": turn.get("answer_quality_flags") or [],
                "covered_point_ids": (turn.get("evidence_basis") or {}).get("covered_point_ids") or [],
                "missed_point_ids": (turn.get("evidence_basis") or {}).get("missed_point_ids") or [],
            })
    return observations


async def _persist_canonical_performance(
    *,
    interview_id: str,
    user_id: str,
    stage_outputs: Dict[str, Dict[str, Any]],
    report: Dict[str, Any],
    job_evidence_hash: str,
) -> str:
    meta = await async_execute(
        """
        SELECT interview_mode, interview_type, duration_seconds
        FROM Interviews WHERE interview_id = %s AND user_id = %s
        """,
        (interview_id, user_id), fetchone=True,
    )
    report_type = str(report.get("report_type") or "").lower()
    interview_type = str((meta or [None, ""])[1] or "").lower()
    mode = "technical" if report_type == "technical" or "technical" in interview_type else "mock"
    turns = list((stage_outputs.get("nlp_content") or {}).get("turns") or [])
    technical = stage_outputs.get("technical_code") or {}
    observations = _turn_observations(turns)
    for item in technical.get("test_matrix") or []:
        if item.get("final_pass_rate") is None:
            continue
        observations.append({
            "skill_key": f"technical:{item.get('algorithm_pattern') or item.get('round_type') or 'coding'}",
            "source_key": item.get("round_id") or item.get("response_id"),
            "source_kind": "technical_execution",
            "evidence_type": "interview",
            "round_id": item.get("round_id"),
            "response_id": item.get("response_id"),
            "question_spec_id": item.get("question_spec_id"),
            "score": item.get("final_pass_rate"),
            "confidence": 0.9,
            "flags": [] if float(item.get("final_pass_rate") or 0) >= 75 else ["test-case-failure"],
        })

    question_analyses = [
        {
            "response_id": turn.get("response_id"),
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
    evidence_status = (
        "insufficient_evidence"
        if not any(turn.get("overall_score") is not None and not turn.get("insufficient_evidence") for turn in turns)
        and not technical.get("submission_count")
        else "sufficient"
    )
    evaluator_versions = sorted({str(turn.get("evaluator_version")) for turn in turns if turn.get("evaluator_version")})
    canonical = {
        "schema_version": "session-performance-v3",
        "mode": mode,
        "interview_id": interview_id,
        "question_analyses": question_analyses,
        "measured_communication": {
            "audio": stage_outputs.get("audio_features") or {},
            "video": stage_outputs.get("video_features") or {},
        },
        "technical": technical,
        "integrity": stage_outputs.get("cheating_risk") or {},
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
                "final_verdict": item.get("final_verdict"),
            }
            for item in technical.get("test_matrix") or []
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
        "response_ids": [item.get("response_id") for item in question_analyses],
        "round_ids": [item.get("round_id") for item in technical.get("test_matrix") or []],
        "submission_ids": [
            item.get("submission_id")
            for item in technical.get("test_matrix") or []
            if item.get("submission_id")
        ],
    }
    evidence_hash = _sha256_json({
        "job_evidence_hash": job_evidence_hash,
        "evaluator_versions": evaluator_versions,
        "question_assessments": [
            (item.get("response_id"), item.get("overall_score"), item.get("evaluator_version"))
            for item in question_analyses
        ],
        "technical": safe_evidence_index["submission_ids"] or safe_evidence_index["round_ids"],
    })
    analysis_id = str(uuid.uuid4())
    inserted = await async_execute(
        """
        INSERT INTO SessionPerformanceAnalyses (
            analysis_id, user_id, interview_id, mode, schema_version,
            evidence_hash, status, model, analysis_json, evidence_index_json,
            analysis_json_encrypted, evidence_index_encrypted, overall_score,
            evaluator_version, taxonomy_version, rubric_version,
            duration_seconds, evidence_status, created_at, updated_at
        ) VALUES (
            %s, %s, %s, %s, 'session-performance-v3', %s, 'ready', %s,
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW()
        )
        ON CONFLICT (interview_id, mode, schema_version) DO UPDATE SET
            analysis_json_encrypted = EXCLUDED.analysis_json_encrypted,
            evidence_index_encrypted = EXCLUDED.evidence_index_encrypted,
            status = 'ready',
            updated_at = NOW()
        WHERE SessionPerformanceAnalyses.evidence_hash = EXCLUDED.evidence_hash
          AND (
              SessionPerformanceAnalyses.analysis_json_encrypted IS NULL
              OR SessionPerformanceAnalyses.evidence_index_encrypted IS NULL
          )
        RETURNING analysis_id
        """,
        (
            analysis_id, user_id, interview_id, mode, evidence_hash,
            ",".join(evaluator_versions) or None,
            _json_dumps(safe_canonical), _json_dumps(safe_evidence_index),
            _encrypted_bytes(canonical), _encrypted_bytes(evidence_index),
            report.get("overall_score"), ",".join(evaluator_versions) or "none",
            TAXONOMY_VERSION, RUBRIC_VERSION, (meta or [None, None, None])[2],
            evidence_status,
        ),
        fetchone=True,
    )
    created = bool(inserted)
    if not created:
        existing = await async_execute(
            """
            SELECT analysis_id, evidence_hash
            FROM SessionPerformanceAnalyses
            WHERE interview_id = %s AND mode = %s AND schema_version = 'session-performance-v3'
            """,
            (interview_id, mode), fetchone=True,
        )
        if not existing:
            raise RuntimeError("canonical_performance_insert_failed")
        analysis_id = existing[0]
        if existing[1] != evidence_hash:
            logger.error("Immutable canonical analysis already exists with a different evidence hash for %s", stable_hash(interview_id, "interview"))
    if created:
        await persist_weakness_states(user_id, analysis_id, interview_id, observations)
        await validate_mission_with_analysis(
            user_id, interview_id, analysis_id, mode, observations
        )
    return analysis_id


async def _load_completed_stage(
    job_id: str,
    stage: str,
    evidence_hash: str,
) -> Optional[Dict[str, Any]]:
    row = await async_execute(
        """
        SELECT output_encrypted, output_json
        FROM AnalysisStageOutputs
        WHERE job_id = %s AND stage_name = %s AND stage_version = %s
          AND evidence_hash = %s AND status = 'completed'
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
            WHERE interview_id = %s AND status <> 'cancelled'
              AND NOT (status IN ('completed', 'partial', 'failed') AND report_json IS NOT NULL)
            """,
            (interview_id,),
        )
        job_evidence_row = await async_execute(
            "SELECT evidence_hash, manifest_id FROM AnalysisJobs WHERE job_id = %s",
            (job_id,), fetchone=True,
        )
        job_evidence_hash = (job_evidence_row or [""])[0] or ""
        manifest_id = str((job_evidence_row or [None, ""])[1] or "")
        if not job_evidence_hash or not manifest_id:
            raise RuntimeError("analysis_job_is_missing_sealed_evidence")
        stage_outputs: Dict[str, Dict[str, Any]] = {}

        for index, stage in enumerate(ANALYSIS_STAGES, start=1):
            await _renew_analysis_lease(job_id, worker_id)
            started = datetime.now(timezone.utc)
            upstream_hashes = {
                name: _sha256_json(stage_outputs[name])
                for name in ANALYSIS_STAGES
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
                stage_outputs[stage] = cached_output
                continue

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
            stage_outputs[stage] = output
            provenance = _stage_provenance(stage, output, input_hash)
            await async_execute(
                """
                INSERT INTO AnalysisStageOutputs (
                    output_id, job_id, interview_id, stage_name, stage_version,
                    evidence_hash, input_hash, model, prompt_version, provenance_json,
                    status, output_json, output_encrypted,
                    error_message, started_at, completed_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
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
                    _json_dumps(_safe_stage_payload(stage, output)),
                    _encrypted_bytes(output), error, started,
                ),
            )
            progress = 100 if stage == "complete" else math.floor(index / len(ANALYSIS_STAGES) * 100)
            await async_execute(
                """
                UPDATE AnalysisJobs SET progress = %s, current_stage = %s, updated_at = NOW()
                WHERE job_id = %s AND lease_owner = %s
                """,
                (progress, stage, job_id, worker_id),
            )

        legacy_stage_outputs = _legacy_stage_outputs(stage_outputs)
        report = legacy_stage_outputs.get("report_generation") or {}
        has_stage_errors = any((stage_outputs.get(stage) or {}).get("error") for stage in ANALYSIS_STAGES)
        report = {
            **report,
            "report_state": (
                "ungradable" if report.get("overall_score") is None
                else ("partial" if has_stage_errors else "ready")
            ),
            "evidence_hash": job_evidence_hash,
            "evidence_manifest_id": manifest_id,
            "generation_provenance": {
                "pipeline_version": ANALYSIS_STAGE_VERSION,
                "stage_versions": {stage: ANALYSIS_STAGE_VERSION for stage in ANALYSIS_STAGES},
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
            if has_stage_errors
            else "completed"
        )
        analysis_id = await _persist_canonical_performance(
            interview_id=interview_id,
            user_id=user_id,
            stage_outputs=legacy_stage_outputs,
            report=report,
            job_evidence_hash=job_evidence_hash,
        )
        mode = "technical" if str(report.get("report_type") or "").lower() == "technical" else "mock"
        await _queue_learning_from_analysis(interview_id, user_id)
        await ensure_mission_from_weakness(user_id, interview_id, analysis_id, mode)
        report_action = await _report_action_for_mode(user_id, mode)
        report = {
            **report,
            "analysis_id": analysis_id,
            "report_actions": [report_action] if report_action else [],
        }
        report.pop("recruiter_only", None)
        safe_report = _safe_report_payload(report)
        full_report_encrypted = _encrypted_bytes(report)
        existing_artifact = await async_execute(
            """
            SELECT artifact_id FROM ReportArtifacts
            WHERE interview_id = %s AND user_id = %s AND audience = 'candidate'
            ORDER BY created_at DESC LIMIT 1
            """,
            (interview_id, user_id), fetchone=True,
        )
        if existing_artifact:
            await async_execute(
                """
                UPDATE ReportArtifacts
                SET report_type = %s, payload = %s, payload_encrypted = %s,
                    evidence_hash = %s, status = %s, provenance_json = %s, updated_at = NOW()
                WHERE artifact_id = %s
                """,
                (
                    report.get("report_type") or "interview",
                    _json_dumps(safe_report), full_report_encrypted, job_evidence_hash,
                    final_status, _json_dumps(report.get("generation_provenance") or {}), existing_artifact[0],
                ),
            )
        else:
            await async_execute(
                """
                INSERT INTO ReportArtifacts (
                    artifact_id, interview_id, user_id, report_type, audience,
                    payload, payload_encrypted, evidence_hash, status, provenance_json
                ) VALUES (%s, %s, %s, %s, 'candidate', %s, %s, %s, %s, %s)
                """,
                (
                    str(uuid.uuid4()), interview_id, user_id,
                    report.get("report_type") or "interview",
                    _json_dumps(safe_report), full_report_encrypted, job_evidence_hash,
                    final_status, _json_dumps(report.get("generation_provenance") or {}),
                ),
            )
        await async_execute(
            """
            UPDATE Interviews
            SET status = %s, overall_score = %s, feedback_summary = %s,
                analysis_status = CASE WHEN %s = 'completed' THEN 'ready' ELSE %s END,
                report_json = %s, report_json_encrypted = %s,
                completed_at = COALESCE(completed_at, NOW())
            WHERE interview_id = %s AND status <> 'cancelled'
              AND NOT (status IN ('completed', 'partial', 'failed') AND report_json IS NOT NULL)
            """,
            (
                final_status, report.get("overall_score"),
                str(report.get("summary") or "Analysis completed.")[:1000],
                final_status, final_status,
                _json_dumps(safe_report), full_report_encrypted, interview_id,
            ),
        )
        await async_execute(
            """
            UPDATE AnalysisJobs
            SET status = %s, progress = 100, current_stage = 'complete',
                completed_at = NOW(), updated_at = NOW(), lease_owner = NULL,
                lease_expires_at = NULL, heartbeat_at = NOW()
            WHERE job_id = %s AND lease_owner = %s
            """,
            (final_status, job_id, worker_id),
        )
        await _schedule_media_cleanup(interview_id)
    except Exception as exc:
        logger.exception("Async analysis job failed for %s", stable_hash(interview_id, "interview"))
        retry_row = await async_execute(
            """
            UPDATE AnalysisJobs
            SET retry_count = retry_count + 1,
                status = CASE WHEN retry_count + 1 >= %s THEN 'failed' ELSE 'queued' END,
                next_attempt_at = CASE
                    WHEN retry_count + 1 >= %s THEN NULL
                    ELSE NOW() + (POWER(2, retry_count) * INTERVAL '5 seconds')
                END,
                error_message = %s, updated_at = NOW(),
                completed_at = CASE WHEN retry_count + 1 >= %s THEN NOW() ELSE NULL END,
                lease_owner = NULL, lease_expires_at = NULL
            WHERE job_id = %s AND lease_owner = %s
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
                WHERE interview_id = %s AND status <> 'cancelled' AND report_json IS NULL
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
    if stage == "technical_analysis":
        return await _run_stage(
            "technical_code", interview_id, user_id,
            {"nlp_content": outputs.get("transcript_analysis") or {}},
        )
    if stage == "integrity_summary":
        evidence = outputs.get("evidence_load") or {}
        return await _run_stage(
            "cheating_risk", interview_id, user_id,
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
        report = outputs.get("semantic_enhancement") or outputs.get("deterministic_report") or {}
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
        return outputs.get("report_validation") or outputs.get("semantic_enhancement") or outputs.get("deterministic_report") or {}

    if stage == "transcription_diarization":
        rows = await async_execute(
            """
            SELECT q.question_text, q.question_order, q.created_at,
                   r.answer_text_encrypted, r.user_response, r.created_at
            FROM InterviewQuestions q
            LEFT JOIN InterviewResponses r ON r.question_id = q.question_id
            WHERE q.interview_id = %s
            ORDER BY q.question_order, r.created_at
            """,
            (interview_id,),
            fetchall=True,
        )
        transcript: List[Dict[str, Any]] = []
        seen_questions: set[tuple[int, str]] = set()
        for question_text, question_order, _, answer_encrypted, legacy_answer, _ in rows or []:
            question_key = (int(question_order or 0), str(question_text or ""))
            if question_key not in seen_questions:
                transcript.append({"role": "interviewer", "text": question_text or ""})
                seen_questions.add(question_key)
            answer = _decrypt_storage_text(answer_encrypted) if answer_encrypted else ""
            if not answer and legacy_answer != "[encrypted]":
                answer = str(legacy_answer or "")
            if answer:
                transcript.append({"role": "candidate", "text": answer})
        candidate_word_count = _candidate_word_count(transcript)
        return {
            "provider": "local_existing_turns",
            "transcript": transcript,
            "speaker_segments": [{"speaker": item["role"], "text": item["text"]} for item in transcript],
            "word_count": sum(len((item["text"] or "").split()) for item in transcript),
            "candidate_word_count": candidate_word_count,
            "interviewer_word_count": sum(_word_count(item["text"]) for item in transcript if item["role"] == "interviewer"),
            "confidence": "medium" if candidate_word_count >= 5 else "low",
            "insufficient_evidence": candidate_word_count < 5,
        }

    if stage == "audio_features":
        rows = await async_execute(
            """
            SELECT ir.timing_json, ir.input_mode, ra.assessment_json
            FROM InterviewResponses ir
            LEFT JOIN LATERAL (
                SELECT assessment_json
                FROM ResponseAssessments
                WHERE response_id = ir.response_id
                ORDER BY created_at DESC
                LIMIT 1
            ) ra ON TRUE
            WHERE ir.interview_id = %s
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
        for timing_raw, input_mode, assessment_raw in rows or []:
            if str(input_mode or "").lower() not in {"voice", "audio", "voice_or_text"}:
                continue
            timing = _json_value(timing_raw, {})
            assessment = _json_value(assessment_raw, {})
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
            WHERE interview_id = %s
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
            "source": "browser_mediapipe_metrics",
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
        scored_turns = [_score_turn(turn) for turn in turns]
        return {
            "turns": scored_turns,
            "average_star_score": _average_available([turn["star_score"] for turn in scored_turns]),
            "communication_score": _average_available([turn["communication_score"] for turn in scored_turns]),
            "content_depth_score": _average_available([turn["technical_score"] for turn in scored_turns]),
            "authoritative_turn_count": sum(1 for turn in scored_turns if turn.get("authoritative")),
            "insufficient_evidence_turn_count": sum(1 for turn in scored_turns if turn.get("insufficient_evidence")),
        }

    if stage == "technical_code":
        submission_rows = await async_execute(
            """
            SELECT ts.submission_id, ts.round_id, ts.language, ts.source_excerpt, ts.source_code, ts.submit_number,
                   ts.visible_passed, ts.visible_total, ts.hidden_passed, ts.hidden_total,
                   ts.runtime_ms, ts.memory_kb, ts.status, ts.result_json, ts.created_at,
                   tir.prompt, tir.metadata
            FROM TechnicalSubmissions ts
            JOIN TechnicalInterviewRounds tir ON tir.round_id = ts.round_id
            WHERE ts.interview_id = %s
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
            source_code = row[4] or row[3] or ""
            item = {
                "submission_id": row[0],
                "round_id": row[1],
                "language": row[2],
                "source_excerpt": row[3] or "",
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
            SELECT tre.round_id, tre.language, tre.source_chars, tre.source_excerpt, tre.source_code,
                   tre.exit_code, tre.runtime_ms, tre.metadata, tre.hidden_validation_result,
                   tir.prompt, tir.metadata
            FROM TechnicalRunEvents tre
            JOIN TechnicalInterviewRounds tir ON tir.round_id = tre.round_id
            WHERE tir.interview_id = %s
            ORDER BY tre.created_at DESC
            """,
            (interview_id,),
            fetchall=True,
        )
        submissions = [
            {
                "round_id": row[0],
                "language": row[1],
                "source_chars": row[2],
                "source_excerpt": row[3] or "",
                "source_code": row[4] or row[3] or "",
                "exit_code": row[5],
                "runtime_ms": row[6],
                "metadata": _json_value(row[7], {}),
                "validation": _json_value(row[8], {}),
                "prompt": row[9] or "",
                "round_metadata": _json_value(row[10], {}),
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
        latest = submissions[0] if submissions else {}
        draft_rows = await async_execute(
            """
            SELECT DISTINCT ON (tcs.round_id)
                   tcs.round_id, tcs.language, tcs.source_chars, tcs.source_excerpt, tcs.source_code,
                   tcs.metadata, tcs.created_at, tir.prompt, tir.metadata
            FROM TechnicalCodeSnapshots tcs
            JOIN TechnicalInterviewRounds tir ON tir.round_id = tcs.round_id
            WHERE tcs.interview_id = %s
              AND tcs.source_chars > 0
            ORDER BY tcs.round_id, tcs.created_at DESC
            """,
            (interview_id,),
            fetchall=True,
        )
        drafts = [
            {
                "round_id": row[0],
                "language": row[1],
                "source_chars": row[2],
                "source_excerpt": row[3] or "",
                "source_code": row[4] or row[3] or "",
                "metadata": _json_value(row[5], {}),
                "created_at": row[6],
                "prompt": row[7] or "",
                "round_metadata": _json_value(row[8], {}),
            }
            for row in draft_rows or []
        ]
        for item in drafts:
            metadata = item.get("round_metadata") or item.get("metadata") or {}
            item["algorithm_pattern"] = metadata.get("algorithm_pattern")
            item["title"] = metadata.get("title") or (item.get("prompt") or "Technical problem").splitlines()[0][:80]
        latest_signal = latest or (drafts[0] if drafts else {})
        technical_question_types = {
            "technical_concept", "system_design", "ml", "backend", "database",
            "os", "network", "oop", "sql", "technical_explanation",
        }
        typed_turns = [
            turn
            for turn in (outputs.get("nlp_content", {}).get("turns") or [])
            if str(turn.get("question_type") or "").lower() in technical_question_types
        ]
        typed_matrix = [
            {
                "round_id": (turn.get("provenance") or {}).get("technical_round_id"),
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
        typed_scores = [
            turn.get("overall_score")
            for turn in typed_turns
            if not turn.get("insufficient_evidence") and turn.get("overall_score") is not None
        ]
        return {
            "submission_count": len(final_submissions),
            "typed_response_count": len(typed_turns),
            "typed_assessed_count": len(typed_scores),
            "typed_response_score": _average_available(typed_scores),
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
            "test_matrix": [
                {
                    "submission_id": item.get("submission_id"),
                    "round_id": item["round_id"],
                    "title": item["title"],
                    "language": item["language"],
                    "submit_number": item["submit_number"],
                    "visible_passed": item["visible_passed"],
                    "visible_total": item["visible_total"],
                    "hidden_passed": item["hidden_passed"],
                    "hidden_total": item["hidden_total"],
                    "runtime_ms": item["runtime_ms"],
                    "memory_kb": item["memory_kb"],
                    "prompt": item.get("prompt", ""),
                    "algorithm_pattern": item.get("algorithm_pattern"),
                    "source_excerpt": item.get("source_excerpt", ""),
                    "source_code": item.get("source_code", ""),
                    "final_pass_rate": round(((item["visible_passed"] + item["hidden_passed"]) / max(item["visible_total"] + item["hidden_total"], 1)) * 100, 1),
                    "final_verdict": "accepted" if (item["visible_passed"] + item["hidden_passed"]) == (item["visible_total"] + item["hidden_total"]) and (item["visible_total"] + item["hidden_total"]) > 0 else "needs_work",
                }
                for item in final_submissions
            ] + typed_matrix,
            "typed_responses": typed_turns,
            "weak_topics": _technical_weak_topics(final_submissions, submissions, drafts),
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
            },
        }

    if stage == "cheating_risk":
        rows = await async_execute(
            """
            SELECT event_type, COUNT(*)
            FROM AntiCheatEvents
            WHERE interview_id = %s
            GROUP BY event_type
            """,
            (interview_id,),
            fetchall=True,
        )
        return aggregate_cheating_risk(
            _event_counts(rows or []),
            outputs.get("video_features", {}),
            outputs.get("technical_code", {}),
        )

    if stage == "report_generation":
        meta = await async_execute(
            """
            SELECT interview_mode, interview_type, job_title, strictness_level, settings
            FROM Interviews
            WHERE interview_id = %s
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
            WHERE interview_id = %s
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
                cheating_output=outputs.get("cheating_risk", {}),
            )
        else:
            heuristic_report = build_async_behavioral_report(
                interview_id=interview_id,
                profile_type=profile_type,
                nlp_output=outputs.get("nlp_content", {}),
                audio_output=outputs.get("audio_features", {}),
                video_output=outputs.get("video_features", {}),
                cheating_output=outputs.get("cheating_risk", {}),
            )
        # Canonical reports expose only persisted evaluator and execution evidence.
        # The legacy premium builder inferred unsupported traits from transcript/code
        # shape, so it is intentionally excluded from the authoritative path.

        transcript_output = outputs.get("transcription_diarization", {})
        technical_output = outputs.get("technical_code", {})
        heuristic_report = _with_transcript(heuristic_report, transcript_output)
        candidate_word_count = int(transcript_output.get("candidate_word_count") or 0)
        if candidate_word_count < 5 and not technical_output.get("submission_count"):
            return _with_transcript(
                heuristic_report,
                transcript_output,
                ai_enhanced=False,
                ai_fallback_reason="no_candidate_evidence",
            )
        if (outputs.get("__deterministic_only") or {}).get("enabled"):
            return {
                **heuristic_report,
                "ai_enhanced": False,
                "ai_provider_policy": "deterministic_only",
                "ai_fallback_reason": None,
            }
        return await _enhance_report_with_openai(
            interview_id=interview_id,
            profile_type=profile_type,
            interview_type=interview_type,
            heuristic_report=heuristic_report,
            stage_outputs=outputs,
        )

    return {"stage": stage, "status": "skipped"}


async def _enhance_report_with_openai(
    *,
    interview_id: str,
    profile_type: str,
    interview_type: str,
    heuristic_report: Dict[str, Any],
    stage_outputs: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    turns = (stage_outputs.get("nlp_content") or {}).get("turns") or []
    compact_turns = [
        {
            "question": str(turn.get("question") or "")[:280],
            "topic": turn.get("topic"),
            "response": str(turn.get("response") or "")[:700],
            "score": turn.get("overall_score"),
            "feedback": turn.get("feedback"),
            "confidence": turn.get("confidence"),
            "insufficient_evidence": turn.get("insufficient_evidence"),
            "evidence": turn.get("evidence", [])[:3],
        }
        for turn in turns[:18]
    ]
    technical_stage = stage_outputs.get("technical_code") or {}
    semantic_technical = {
        "submission_count": int(technical_stage.get("submission_count") or 0),
        "typed_response_count": int(technical_stage.get("typed_response_count") or 0),
        "run_event_count": int(technical_stage.get("run_event_count") or 0),
        "draft_count": int(technical_stage.get("draft_count") or 0),
        "correctness_score": technical_stage.get("correctness_score"),
        "test_matrix": [
            {
                key: item.get(key)
                for key in (
                    "round_id", "response_id", "round_type", "title", "algorithm_pattern",
                    "visible_passed", "visible_total", "hidden_passed", "hidden_total",
                    "final_pass_rate", "final_verdict", "score", "confidence",
                )
            }
            for item in (technical_stage.get("test_matrix") or [])
            if isinstance(item, dict)
        ],
        "weak_topics": technical_stage.get("weak_topics") or [],
    }
    payload = {
        "heuristic_report": heuristic_report,
        "evidence_policy": {
            "scores_require_evidence": True,
            "insufficient_evidence_turns": sum(1 for turn in turns if turn.get("insufficient_evidence")),
            "low_confidence_turns": sum(1 for turn in turns if turn.get("confidence") == "low"),
        },
        "turns": compact_turns,
        "audio_features": stage_outputs.get("audio_features") or {},
        "video_features": stage_outputs.get("video_features") or {},
        "technical_code": semantic_technical,
        "cheating_risk": stage_outputs.get("cheating_risk") or {},
    }
    report_cache_key = "report_generation:" + stable_hash(json.dumps({
        "interview_id": interview_id,
        "interview_type": interview_type,
        "profile_type": profile_type,
        "version": heuristic_report.get("version"),
        "overall": heuristic_report.get("overall_score"),
        "candidate_words": (stage_outputs.get("transcription_diarization") or {}).get("candidate_word_count"),
        "technical_submissions": (stage_outputs.get("technical_code") or {}).get("submission_count"),
    }, sort_keys=True, default=str))
    if (heuristic_report.get("evidence_status") or {}).get("status") == "no_candidate_evidence":
        return {
            **heuristic_report,
            "ai_enhanced": False,
            "ai_provider_policy": "skipped",
            "ai_fallback_reason": "no_candidate_evidence",
            "evidence_policy": payload["evidence_policy"],
        }
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["summary", "readiness_label", "strengths", "improvements", "practice_plan", "student_summary"],
        "properties": {
            "summary": {"type": "string"},
            "readiness_label": {"type": "string"},
            "strengths": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 5},
            "improvements": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["title", "detail"],
                    "properties": {"title": {"type": "string"}, "detail": {"type": "string"}},
                },
                "minItems": 1,
                "maxItems": 5,
            },
            "practice_plan": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["day", "task"],
                    "properties": {"day": {"type": "string"}, "task": {"type": "string"}},
                },
                "minItems": 3,
                "maxItems": 7,
            },
            "student_summary": {
                "type": "object",
                "additionalProperties": False,
                "required": ["headline", "blocker", "next_step", "interviewer_signal", "proof_point"],
                "properties": {
                    "headline": {"type": "string"},
                    "blocker": {"type": "string"},
                    "next_step": {"type": "string"},
                    "interviewer_signal": {"type": "string"},
                    "proof_point": {"type": "string"},
                },
            },
        },
    }
    try:
        ai_report = await asyncio.wait_for(
            complete_json_async(
                [
                    {
                        "role": "system",
                        "content": (
                            "You are a senior interview debrief writer. Improve the report narrative using the "
                            "provided scores and transcript evidence. Do not invent facts, companies, projects, "
                            "or scores. Keep feedback actionable and candidate-visible."
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"Interview type: {interview_type}\nProfile type: {profile_type}\n"
                            "Generate concise report fields from this analysis payload:\n"
                            f"{json.dumps(payload, default=str)[:14000]}"
                        ),
                    },
                ],
                event_type="report_generation_llm",
                temperature=0.25,
                max_tokens=1800,
                interview_id=interview_id,
                metadata={
                    "profile_type": profile_type,
                    "interview_type": interview_type,
                    "report_version": heuristic_report.get("version"),
                },
                json_schema=schema,
                provider_policy="openai_preferred",
                cache_key=report_cache_key,
            ),
            timeout=120,
        )
        merged = {
            **heuristic_report,
            "version": f"{heuristic_report.get('version', 'async_report')}_openai_enhanced",
            "summary": ai_report.get("summary") or heuristic_report.get("summary"),
            "readiness_label": ai_report.get("readiness_label") or heuristic_report.get("readiness_label"),
            "strengths": ai_report.get("strengths") or heuristic_report.get("strengths", []),
            "improvements": ai_report.get("improvements") or heuristic_report.get("improvements", []),
            "practice_plan": ai_report.get("practice_plan") or heuristic_report.get("practice_plan", []),
            "improvement_plan": heuristic_report.get("improvement_plan", {}),
            "student_summary": ai_report.get("student_summary") or heuristic_report.get("student_summary", {}),
            "ai_enhanced": True,
            "ai_provider_policy": "openai_preferred",
            "evidence_policy": payload["evidence_policy"],
        }
        return merged
    except asyncio.TimeoutError:
        logger.error("OpenAI report generation timed out for %s; using heuristic report", stable_hash(interview_id, "interview"))
        return {
            **heuristic_report,
            "ai_enhanced": False,
            "ai_provider_policy": "openai_preferred",
            "ai_fallback_reason": "report_generation_llm_timeout",
            "evidence_policy": payload["evidence_policy"],
        }
    except Exception:
        logger.error("OpenAI report enhancement failed for %s; using heuristic report", stable_hash(interview_id, "interview"))
        return {
            **heuristic_report,
            "ai_enhanced": False,
            "ai_provider_policy": "openai_preferred",
            "ai_fallback_reason": "report_generation_llm_failed",
            "evidence_policy": payload["evidence_policy"],
        }


async def _load_turns(interview_id: str) -> List[Dict[str, Any]]:
    rows = await async_execute(
        """
        SELECT ir.response_id, iq.question_text, iq.question_type, iq.topic_label,
               ir.answer_text_encrypted, ir.user_response, ir.response_time_seconds,
               iq.question_spec_id, iq.taxonomy_keys, iq.blueprint_section_id,
               iq.parent_question_id, assessment.evaluator_version,
               assessment.assessment_json, ir.timing_json, ir.input_mode,
               iq.provenance
        FROM InterviewResponses ir
        JOIN InterviewQuestions iq ON ir.question_id = iq.question_id
        LEFT JOIN LATERAL (
            SELECT evaluator_version, assessment_json
            FROM ResponseAssessments
            WHERE response_id = ir.response_id
            ORDER BY created_at DESC
            LIMIT 1
        ) assessment ON TRUE
        WHERE ir.interview_id = %s
        ORDER BY iq.question_order, ir.created_at
        """,
        (interview_id,),
        fetchall=True,
    )
    turns: List[Dict[str, Any]] = []
    for row in rows or []:
        encrypted_answer = _decrypt_storage_text(row[4]) if row[4] else ""
        legacy_answer = "" if row[5] == "[encrypted]" else str(row[5] or "")
        turns.append({
            "response_id": row[0],
            "question": row[1] or "",
            "question_type": row[2] or "main",
            "topic": row[3] or "General",
            "response": encrypted_answer or legacy_answer,
            "time_taken": row[6],
            "question_spec_id": row[7],
            "taxonomy_keys": _json_value(row[8], []),
            "blueprint_section_id": row[9],
            "parent_question_id": row[10],
            "evaluator_version": row[11],
            "assessment": _json_value(row[12], None),
            "timing": _json_value(row[13], {}),
            "input_mode": row[14],
            "provenance": _json_value(row[15], {}),
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

    for item, evidence_state in evidence_items:
        topic = item.get("algorithm_pattern") or "technical correctness"
        total = int(item.get("visible_total") or 0) + int(item.get("hidden_total") or 0)
        passed = int(item.get("visible_passed") or 0) + int(item.get("hidden_passed") or 0)
        if not total:
            total = int(item.get("total_count") or 0)
            passed = int(item.get("pass_count") or 0)
        bucket = topics.setdefault(
            topic,
            {
                "topic": topic,
                "passed": 0,
                "total": 0,
                "round_ids": [],
                "evidence_states": set(),
                "titles": [],
            },
        )
        bucket["passed"] += passed
        bucket["total"] += total
        bucket["round_ids"].append(item.get("round_id"))
        bucket["evidence_states"].add(evidence_state)
        if item.get("title"):
            bucket["titles"].append(item.get("title"))
    weak = []
    for bucket in topics.values():
        total = bucket["total"]
        pass_rate = round((bucket["passed"] / total) * 100, 1) if total else 0.0
        evidence_states = sorted(bucket["evidence_states"])
        draft_or_run_only = any(state != "final_submission" for state in evidence_states)
        if pass_rate < 80 or draft_or_run_only:
            weak.append({
                "topic": bucket["topic"],
                "pass_rate": pass_rate,
                "round_ids": bucket["round_ids"],
                "evidence_state": ", ".join(evidence_states),
                "example_questions": list(dict.fromkeys(bucket["titles"]))[:3],
                "repair_action": (
                    "Submit a final solution for this pattern so correctness can be graded."
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
            SET delete_after = LEAST(COALESCE(delete_after, %s), %s),
                retention_status = CASE
                    WHEN retention_status IN ('retained', 'cleanup_scheduled')
                    THEN 'cleanup_scheduled'
                    ELSE retention_status
                END
            WHERE interview_id = %s AND media_kind = %s
            """,
            (now + window, now + window, interview_id, media_kind),
        )
