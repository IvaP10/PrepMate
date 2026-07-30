"""Durable technical-execution worker.

The FastAPI process only enqueues jobs.  This worker claims PostgreSQL rows with
leases, executes candidate code exclusively through private Piston, and commits
masked public results.  Restarting either process does not lose a queued job.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import socket
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from database import get_db_connection, return_db_connection
from security_utils import decrypt_data
from technical_mode import (
    EXECUTION_JOB_VERSION,
    _case_verdict,
    _execute_code,
    _judge0_verdict,
)


logger = logging.getLogger("technical_worker")
WORKER_VERSION = "technical-worker-v1"
LEASE_SECONDS = 45
MAX_RETRIES = 3


def _decode_encrypted_blob(value: Any) -> str:
    if isinstance(value, memoryview):
        value = value.tobytes()
    if isinstance(value, (bytes, bytearray)):
        value = bytes(value).decode("utf-8", errors="strict")
    return decrypt_data(str(value or ""))


def _json_value(value: Any, fallback: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value) if value is not None else fallback
    except Exception:
        return fallback


def _record_committed_submission(
    workflow_state: Any,
    committed_submission: Dict[str, Any],
) -> Dict[str, Any]:
    state = dict(workflow_state) if isinstance(workflow_state, dict) else {}
    existing_final = state.get("final_submission")
    if not isinstance(existing_final, dict) or not existing_final.get("committed"):
        state["final_submission"] = committed_submission
    history = state.get("submission_history")
    if not isinstance(history, list):
        history = []
    if not any(
        isinstance(item, dict) and item.get("execution_job_id") == committed_submission.get("execution_job_id")
        for item in history
    ):
        history.append(committed_submission)
    state["submission_history"] = history[-10:]
    state["latest_submission"] = committed_submission
    return state


def worker_id() -> str:
    configured = str(os.getenv("TECHNICAL_WORKER_ID") or "").strip()
    return configured or f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"


def heartbeat(worker: str, metadata: Optional[Dict[str, Any]] = None) -> List[str]:
    connection = get_db_connection()
    cursor = connection.cursor()
    try:
        cursor.execute(
            """
            UPDATE TechnicalExecutionJobs
            SET status = 'failed',
                error_message = COALESCE(error_message, 'execution lease expired repeatedly'),
                completed_at = NOW(), updated_at = NOW(),
                lease_owner = NULL, lease_expires_at = NULL
            WHERE status IN ('leased', 'running')
              AND lease_expires_at < NOW()
              AND retry_count >= %s
            RETURNING round_id, action
            """,
            (MAX_RETRIES,),
        )
        exhausted = cursor.fetchall() or []
        exhausted_interviews: List[str] = []
        for round_id, action in exhausted:
            cursor.execute(
                "SELECT interview_id FROM TechnicalInterviewRounds WHERE round_id = %s",
                (round_id,),
            )
            interview_row = cursor.fetchone()
            if interview_row:
                exhausted_interviews.append(str(interview_row[0]))
            if action == "submit":
                cursor.execute(
                    "UPDATE TechnicalInterviewRounds SET status = 'active' WHERE round_id = %s AND status = 'submitting'",
                    (round_id,),
                )
        cursor.execute(
            """
            INSERT INTO WorkerHeartbeats (
                worker_id, worker_type, version, metadata, started_at, heartbeat_at
            )
            VALUES (%s, 'technical', %s, %s, NOW(), NOW())
            ON CONFLICT (worker_id) DO UPDATE SET
                version = EXCLUDED.version,
                metadata = EXCLUDED.metadata,
                heartbeat_at = NOW()
            """,
            (worker, WORKER_VERSION, json.dumps(metadata or {})),
        )
        cursor.execute(
            """
            SELECT interview.interview_id
            FROM Interviews interview
            WHERE COALESCE((interview.settings->>'technical_finalize_requested')::boolean, FALSE) = TRUE
              AND interview.status IN ('in_progress', 'uploading')
              AND NOT EXISTS (
                  SELECT 1 FROM TechnicalExecutionJobs job
                  WHERE job.interview_id = interview.interview_id
                    AND job.status IN ('queued', 'leased', 'running')
              )
            ORDER BY interview.created_at
            LIMIT 20
            """
        )
        exhausted_interviews.extend(str(row[0]) for row in cursor.fetchall() or [])
        connection.commit()
        return list(dict.fromkeys(exhausted_interviews))
    except Exception:
        connection.rollback()
        logger.warning("Technical worker heartbeat failed", exc_info=True)
        return []
    finally:
        cursor.close()
        return_db_connection(connection)


def _mark_finalize_requested_if_drained_sync(interview_id: str) -> Optional[str]:
    connection = get_db_connection()
    cursor = connection.cursor()
    try:
        cursor.execute(
            """
            SELECT user_id, status, settings
            FROM Interviews
            WHERE interview_id = %s
            FOR UPDATE
            """,
            (interview_id,),
        )
        interview = cursor.fetchone()
        if not interview:
            connection.commit()
            return None
        settings_payload = _json_value(interview[2], {})
        if not isinstance(settings_payload, dict) or not settings_payload.get("technical_finalize_requested"):
            connection.commit()
            return None
        cursor.execute(
            """
            SELECT COUNT(*)
            FROM TechnicalExecutionJobs
            WHERE interview_id = %s AND status IN ('queued', 'leased', 'running')
            """,
            (interview_id,),
        )
        if int((cursor.fetchone() or [0])[0] or 0):
            connection.commit()
            return None
        if str(interview[1] or "").lower() not in {"in_progress", "uploading"}:
            connection.commit()
            return None

        pending_transcript = settings_payload.pop("pending_transcript_encrypted", None)
        settings_payload.pop("technical_finalize_requested", None)
        settings_payload["technical_finalize_committed_at"] = datetime.now(timezone.utc).isoformat()
        cursor.execute(
            """
            UPDATE Interviews
            SET status = 'analysis_pending',
                attempt_status = 'completed',
                analysis_status = 'queued',
                completion_kind = CASE
                    WHEN deadline_at IS NOT NULL AND NOW() >= deadline_at THEN 'deadline'
                    ELSE 'natural'
                END,
                recovery_deadline_at = NULL,
                lifecycle_revision = lifecycle_revision + 1,
                settings = %s,
                completed_at = COALESCE(completed_at, NOW()),
                duration_seconds = CASE
                    WHEN started_at IS NULL THEN duration_seconds
                    ELSE GREATEST(0, EXTRACT(EPOCH FROM (COALESCE(completed_at, NOW()) - started_at))::integer)
                END,
                transcript_encrypted = COALESCE(%s, transcript_encrypted),
                full_transcript = CASE
                    WHEN %s IS NULL THEN full_transcript
                    ELSE '{"encrypted":true,"captured":true}'::jsonb
                END,
                feedback_summary = 'Technical execution complete. Async analysis is queued.'
            WHERE interview_id = %s
            """,
            (
                json.dumps(settings_payload),
                str(pending_transcript).encode("utf-8") if pending_transcript else None,
                pending_transcript,
                interview_id,
            ),
        )
        cursor.execute(
            """
            UPDATE TechnicalInterviewRounds round
            SET status = CASE
                    WHEN interview.completion_kind = 'deadline' THEN 'expired'
                    ELSE 'completed'
                END,
                completed_at = COALESCE(round.completed_at, interview.completed_at, NOW())
            FROM Interviews interview
            WHERE round.interview_id = interview.interview_id
              AND round.user_id = interview.user_id
              AND interview.interview_id = %s
              AND round.status NOT IN ('submitted', 'completed', 'expired', 'cancelled')
            """,
            (interview_id,),
        )
        connection.commit()
        return str(interview[0])
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()
        return_db_connection(connection)


async def finalize_requested_interview_if_drained(interview_id: str) -> Optional[str]:
    user_id = await asyncio.to_thread(_mark_finalize_requested_if_drained_sync, interview_id)
    if not user_id:
        return None
    from analysis_pipeline import enqueue_analysis
    from database import async_execute

    try:
        job_id = await enqueue_analysis(
            interview_id,
            user_id,
            "technical_execution_drained",
        )
    except Exception:
        logger.exception(
            "Could not queue analysis after technical execution drained: %s",
            interview_id,
        )
        await async_execute(
            """
            UPDATE Interviews
            SET analysis_status = 'failed',
                feedback_summary = 'Technical execution completed, but analysis could not be queued. It will be retried automatically.'
            WHERE interview_id = %s AND user_id = %s
              AND attempt_status = 'completed'
            """,
            (interview_id, user_id),
        )
        return None
    if job_id:
        await async_execute(
            "UPDATE Interviews SET analysis_job_id = %s WHERE interview_id = %s AND user_id = %s",
            (job_id, interview_id, user_id),
        )
    else:
        await async_execute(
            """
            UPDATE Interviews
            SET analysis_status = 'failed',
                feedback_summary = 'Technical execution completed, but analysis could not be queued. It will be retried automatically.'
            WHERE interview_id = %s AND user_id = %s
              AND attempt_status = 'completed'
            """,
            (interview_id, user_id),
        )
    return job_id


def claim_execution_job(worker: str) -> Optional[Dict[str, Any]]:
    connection = get_db_connection()
    cursor = connection.cursor()
    try:
        cursor.execute(
            """
            WITH candidate AS (
                SELECT job_id
                FROM TechnicalExecutionJobs
                WHERE (
                    status = 'queued'
                    AND (next_attempt_at IS NULL OR next_attempt_at <= NOW())
                ) OR (
                    status IN ('leased', 'running')
                    AND lease_expires_at < NOW()
                    AND retry_count < %s
                )
                ORDER BY created_at, job_id
                FOR UPDATE SKIP LOCKED
                LIMIT 1
            )
            UPDATE TechnicalExecutionJobs target
            SET status = 'leased',
                lease_owner = %s,
                lease_expires_at = NOW() + (%s * INTERVAL '1 second'),
                heartbeat_at = NOW(),
                updated_at = NOW(),
                error_message = NULL,
                retry_count = CASE
                    WHEN target.status IN ('leased', 'running')
                    THEN target.retry_count + 1
                    ELSE target.retry_count
                END
            FROM candidate
            WHERE target.job_id = candidate.job_id
            RETURNING target.job_id, target.idempotency_key, target.user_id,
                      target.interview_id, target.round_id, target.action,
                      target.suite, target.language, target.source_code_encrypted,
                      target.source_hash, target.cases_encrypted,
                      target.retry_count, target.result_json
            """,
            (MAX_RETRIES, worker, LEASE_SECONDS),
        )
        row = cursor.fetchone()
        connection.commit()
        if not row:
            return None
        return {
            "job_id": str(row[0]),
            "idempotency_key": str(row[1]),
            "user_id": str(row[2]),
            "interview_id": str(row[3]),
            "round_id": str(row[4]),
            "action": str(row[5]),
            "suite": str(row[6]),
            "language": str(row[7]),
            "source_code_encrypted": row[8],
            "source_hash": str(row[9]),
            "cases_encrypted": row[10],
            "retry_count": int(row[11] or 0),
            "initial_result": _json_value(row[12], {}),
        }
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()
        return_db_connection(connection)


def mark_running(job_id: str, worker: str) -> bool:
    connection = get_db_connection()
    cursor = connection.cursor()
    try:
        cursor.execute(
            """
            UPDATE TechnicalExecutionJobs
            SET status = 'running', heartbeat_at = NOW(),
                lease_expires_at = NOW() + (%s * INTERVAL '1 second'),
                updated_at = NOW()
            WHERE job_id = %s AND lease_owner = %s AND status = 'leased'
            RETURNING job_id
            """,
            (LEASE_SECONDS, job_id, worker),
        )
        acquired = bool(cursor.fetchone())
        connection.commit()
        return acquired
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()
        return_db_connection(connection)


def refresh_lease(job_id: str, worker: str, result: Dict[str, Any]) -> bool:
    connection = get_db_connection()
    cursor = connection.cursor()
    try:
        cursor.execute(
            """
            UPDATE TechnicalExecutionJobs
            SET heartbeat_at = NOW(),
                lease_expires_at = NOW() + (%s * INTERVAL '1 second'),
                result_json = %s,
                updated_at = NOW()
            WHERE job_id = %s AND lease_owner = %s AND status = 'running'
            RETURNING job_id
            """,
            (LEASE_SECONDS, json.dumps(result), job_id, worker),
        )
        owned = bool(cursor.fetchone())
        connection.commit()
        return owned
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()
        return_db_connection(connection)


async def execute_claimed_job(job: Dict[str, Any], worker: str) -> Dict[str, Any]:
    source = _decode_encrypted_blob(job["source_code_encrypted"])
    cases = json.loads(_decode_encrypted_blob(job["cases_encrypted"]))
    if not source or not isinstance(cases, list) or not cases:
        raise RuntimeError("Encrypted execution payload is missing or invalid")

    initial = job.get("initial_result") if isinstance(job.get("initial_result"), dict) else {}
    visible_total = int(initial.get("visible_total") or 0)
    hidden_total = int(initial.get("hidden_total") or 0)
    result: Dict[str, Any] = {
        **initial,
        "version": EXECUTION_JOB_VERSION,
        "status": "running",
        "cases": [],
        "visible_passed": 0,
        "hidden_passed": 0,
        "pass_count": 0,
        "runtime_ms": 0,
        "memory_kb": 0,
        "executor": "isolated_sandbox",
    }
    for index, case in enumerate(cases):
        if not isinstance(case, dict):
            raise RuntimeError("Execution case contract is invalid")
        execution = await _execute_code(job["language"], source, str(case.get("stdin") or ""))
        hidden = not bool(case.get("visible", index < visible_total))
        has_expected = case.get("expected") is not None
        verdict = _case_verdict(execution, case) if has_expected else _judge0_verdict(execution)
        passed = verdict == "Accepted"
        if passed and hidden:
            result["hidden_passed"] += 1
        elif passed:
            result["visible_passed"] += 1
        result["pass_count"] = result["visible_passed"] + result["hidden_passed"]
        result["runtime_ms"] += int(execution.get("runtime_ms") or 0)
        result["memory_kb"] = max(result["memory_kb"], int(execution.get("memory_kb") or 0))
        public_case = {
            "index": index,
            "case_number": index + 1,
            "hidden": hidden,
            "verdict": verdict,
            "passed": passed,
            "runtime_ms": int(execution.get("runtime_ms") or 0),
            "memory_kb": int(execution.get("memory_kb") or 0),
        }
        if not hidden:
            public_case.update({
                "stdin": str(case.get("stdin") or ""),
                "expected": str(case.get("expected") or "") if has_expected else None,
                "actual": str(execution.get("stdout") or ""),
                "stderr": str(execution.get("stderr") or ""),
            })
        result["cases"].append(public_case)
        if len(cases) == 1 and not has_expected:
            result.update({
                "stdout": str(execution.get("stdout") or ""),
                "stderr": str(execution.get("stderr") or ""),
                "exit_code": int(execution.get("exit_code") or 0),
                "verdict": verdict,
            })
        if not await asyncio.to_thread(refresh_lease, job["job_id"], worker, result):
            raise RuntimeError("Execution job lease was lost")
    result["visible_total"] = visible_total
    result["hidden_total"] = hidden_total
    result["total_count"] = len(cases)
    result["status"] = "completed"
    return result


def complete_execution_job(job: Dict[str, Any], worker: str, result: Dict[str, Any]) -> bool:
    connection = get_db_connection()
    cursor = connection.cursor()
    try:
        cursor.execute(
            """
            UPDATE TechnicalExecutionJobs
            SET status = 'completed', result_json = %s, error_message = NULL,
                completed_at = NOW(), updated_at = NOW(), heartbeat_at = NOW(),
                lease_owner = NULL, lease_expires_at = NULL
            WHERE job_id = %s AND lease_owner = %s AND status = 'running'
            RETURNING job_id
            """,
            (json.dumps(result), job["job_id"], worker),
        )
        if not cursor.fetchone():
            connection.rollback()
            return False

        first_visible = next((case for case in result.get("cases") or [] if not case.get("hidden")), {})
        exit_code = 0 if int(result.get("pass_count") or 0) == int(result.get("total_count") or 0) else 1
        cursor.execute(
            """
            INSERT INTO TechnicalRunEvents (
                run_id, round_id, user_id, language, source_chars, source_excerpt,
                source_code, source_code_encrypted, code_hash, stdout, stderr, exit_code, error_signature,
                runtime_ms, metadata, hidden_validation_result
            )
            VALUES (%s, %s, %s, %s, 0, '[encrypted]', '[encrypted]', %s, %s,
                    %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (run_id) DO NOTHING
            """,
            (
                job["job_id"],
                job["round_id"],
                job["user_id"],
                job["language"],
                job["source_code_encrypted"],
                job["source_hash"],
                json.dumps(result.get("cases") or []),
                str(first_visible.get("stderr") or ""),
                exit_code,
                f"technical:{job['source_hash'][:32]}:{exit_code}",
                int(result.get("runtime_ms") or 0),
                json.dumps({"action": job["action"], "suite": job["suite"], "encrypted_source": True}),
                json.dumps(result),
            ),
        )
        if job["action"] == "submit":
            cursor.execute(
                "SELECT COUNT(*) FROM TechnicalSubmissions WHERE round_id = %s AND user_id = %s",
                (job["round_id"], job["user_id"]),
            )
            submit_number = int((cursor.fetchone() or [0])[0] or 0) + 1
            cursor.execute(
                """
                INSERT INTO TechnicalSubmissions (
                    submission_id, round_id, interview_id, user_id, language,
                    code_hash, source_excerpt, source_code, source_code_encrypted, submit_number,
                    visible_passed, visible_total, hidden_passed, hidden_total,
                    runtime_ms, memory_kb, status, result_json, execution_job_id
                )
                VALUES (%s, %s, %s, %s, %s, %s, '[encrypted]', '[encrypted]', %s, %s,
                        %s, %s, %s, %s, %s, %s, 'submitted', %s, %s)
                """,
                (
                    str(uuid.uuid4()),
                    job["round_id"],
                    job["interview_id"],
                    job["user_id"],
                    job["language"],
                    job["source_hash"],
                    job["source_code_encrypted"],
                    submit_number,
                    int(result.get("visible_passed") or 0),
                    int(result.get("visible_total") or 0),
                    int(result.get("hidden_passed") or 0),
                    int(result.get("hidden_total") or 0),
                    int(result.get("runtime_ms") or 0),
                    int(result.get("memory_kb") or 0),
                    json.dumps({**result, "hidden_cases_masked": True}),
                    job["job_id"],
                ),
            )
            cursor.execute(
                "SELECT mode, max_submissions, workflow_state FROM TechnicalInterviewRounds WHERE round_id = %s FOR UPDATE",
                (job["round_id"],),
            )
            round_policy = cursor.fetchone() or ("mock", 1, {})
            terminal = str(round_policy[0] or "mock") != "practice" or submit_number >= int(round_policy[1] or 1)
            workflow_state = _json_value(round_policy[2], {})
            if not isinstance(workflow_state, dict):
                workflow_state = {}
            committed_submission = {
                "committed": True,
                "execution_job_id": job["job_id"],
                "submit_number": submit_number,
                "source_hash": job["source_hash"],
                "passed": int(result.get("pass_count") or 0),
                "total": int(result.get("total_count") or 0),
            }
            # The first committed final is immutable. Practice-mode retries are
            # retained as submission history, but cannot replace that evidence.
            workflow_state = _record_committed_submission(workflow_state, committed_submission)
            cursor.execute(
                """
                UPDATE TechnicalInterviewRounds
                SET status = %s, workflow_state = %s, completed_at = NULL
                WHERE round_id = %s
                """,
                ("awaiting_explanation" if terminal else "active", json.dumps(workflow_state), job["round_id"]),
            )
        connection.commit()
        return True
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()
        return_db_connection(connection)


def fail_execution_job(job: Dict[str, Any], worker: str, error: str) -> str:
    connection = get_db_connection()
    cursor = connection.cursor()
    try:
        cursor.execute(
            "SELECT retry_count FROM TechnicalExecutionJobs WHERE job_id = %s AND lease_owner = %s FOR UPDATE",
            (job["job_id"], worker),
        )
        row = cursor.fetchone()
        if not row:
            connection.rollback()
            return "lost"
        retry_count = int(row[0] or 0) + 1
        if retry_count < MAX_RETRIES:
            delay_seconds = min(30, 2 ** retry_count)
            cursor.execute(
                """
                UPDATE TechnicalExecutionJobs
                SET status = 'queued', retry_count = %s,
                    next_attempt_at = NOW() + (%s * INTERVAL '1 second'),
                    lease_owner = NULL, lease_expires_at = NULL, heartbeat_at = NOW(),
                    error_message = %s, updated_at = NOW()
                WHERE job_id = %s AND lease_owner = %s
                """,
                (retry_count, delay_seconds, error[:2000], job["job_id"], worker),
            )
            next_status = "queued"
        else:
            cursor.execute(
                """
                UPDATE TechnicalExecutionJobs
                SET status = 'failed', retry_count = %s, error_message = %s,
                    completed_at = NOW(), updated_at = NOW(), heartbeat_at = NOW(),
                    lease_owner = NULL, lease_expires_at = NULL
                WHERE job_id = %s AND lease_owner = %s
                """,
                (retry_count, error[:2000], job["job_id"], worker),
            )
            if job["action"] == "submit":
                cursor.execute(
                    "UPDATE TechnicalInterviewRounds SET status = 'active' WHERE round_id = %s AND status = 'submitting'",
                    (job["round_id"],),
                )
            next_status = "failed"
        connection.commit()
        return next_status
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()
        return_db_connection(connection)


async def run_once(worker: str) -> bool:
    job = await asyncio.to_thread(claim_execution_job, worker)
    if not job:
        return False
    if not await asyncio.to_thread(mark_running, job["job_id"], worker):
        return False
    try:
        result = await execute_claimed_job(job, worker)
        committed = await asyncio.to_thread(complete_execution_job, job, worker, result)
        if not committed:
            logger.warning("Technical job lease lost before commit: %s", job["job_id"])
    except Exception as exc:
        logger.exception("Technical execution job failed: %s", job["job_id"])
        await asyncio.to_thread(fail_execution_job, job, worker, str(exc))
    finally:
        exhausted = await asyncio.to_thread(
            heartbeat, worker, {"state": "idle", "last_job_id": job["job_id"]}
        )
        for interview_id in [job["interview_id"], *exhausted]:
            try:
                await finalize_requested_interview_if_drained(interview_id)
            except Exception:
                logger.exception("Deferred technical finalization failed for %s", interview_id)
    return True


async def serve(worker: str, poll_seconds: float = 0.5, once: bool = False) -> None:
    last_heartbeat = 0.0
    while True:
        now = time.monotonic()
        if now - last_heartbeat >= 10:
            exhausted = await asyncio.to_thread(heartbeat, worker, {"state": "idle"})
            for interview_id in exhausted:
                try:
                    await finalize_requested_interview_if_drained(interview_id)
                except Exception:
                    logger.exception("Deferred technical finalization failed for %s", interview_id)
            last_heartbeat = now
        worked = await run_once(worker)
        if once:
            return
        if not worked:
            await asyncio.sleep(max(0.1, poll_seconds))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run durable technical execution jobs")
    parser.add_argument("--once", action="store_true", help="Claim at most one job")
    parser.add_argument("--poll-seconds", type=float, default=0.5)
    args = parser.parse_args()
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    asyncio.run(serve(worker_id(), poll_seconds=args.poll_seconds, once=args.once))


if __name__ == "__main__":
    main()
