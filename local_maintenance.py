"""Crash-recovery maintenance for the local desktop runtime."""

from __future__ import annotations

import asyncio
import logging


logger = logging.getLogger("prepmate.local_maintenance")


async def recover_orphaned_analysis_attempts() -> None:
    """Requeue completed attempts that have no usable canonical report graph."""
    from analysis_pipeline import (
        ANALYSIS_STAGE_VERSION,
        SESSION_PERFORMANCE_VERSION,
        enqueue_analysis_result,
    )
    from database import async_execute

    rows = await async_execute(
        """
        SELECT i.interview_id, i.user_id
        FROM Interviews i
        WHERE i.attempt_status = 'completed'
          AND i.status IN (
              'analysis_pending', 'analysis_running',
              'completed', 'partial', 'failed'
          )
          AND NOT EXISTS (
              SELECT 1
              FROM SessionPerformanceAnalyses analysis
              WHERE analysis.interview_id = i.interview_id
                AND analysis.user_id = i.user_id
                AND analysis.schema_version = ?
                AND analysis.producer_version = ?
                AND analysis.is_current = TRUE
                AND analysis.status = 'ready'
                AND analysis.analysis_json_encrypted IS NOT NULL
                AND analysis.evidence_index_encrypted IS NOT NULL
                AND EXISTS (
                    SELECT 1 FROM ReportArtifacts artifact
                    WHERE artifact.analysis_id = analysis.analysis_id
                      AND artifact.interview_id = analysis.interview_id
                      AND artifact.user_id = analysis.user_id
                      AND artifact.status IN ('completed', 'partial')
                      AND artifact.payload_encrypted IS NOT NULL
                )
                AND EXISTS (
                    SELECT 1 FROM ReportSideEffectOutbox side_effect
                    WHERE side_effect.analysis_id = analysis.analysis_id
                      AND side_effect.interview_id = analysis.interview_id
                      AND side_effect.user_id = analysis.user_id
                      AND side_effect.event_type = 'improve_sync'
                )
          )
          AND NOT EXISTS (
              SELECT 1
              FROM AnalysisJobs job
              WHERE job.interview_id = i.interview_id
                AND job.user_id = i.user_id
                AND job.producer_version = ?
                AND job.status IN ('queued', 'running')
          )
        ORDER BY COALESCE(i.completed_at, i.created_at)
        LIMIT 20
        """,
        (SESSION_PERFORMANCE_VERSION, ANALYSIS_STAGE_VERSION, ANALYSIS_STAGE_VERSION),
        fetchall=True,
    )
    for interview_id, user_id in rows or []:
        try:
            result = await enqueue_analysis_result(
                str(interview_id),
                str(user_id),
                "orphaned_analysis_recovery",
                force_canonical_rebuild=True,
            )
            state_name = str(result.get("state") or "rejected")
            job_id = result.get("job_id")
            await async_execute(
                """
                UPDATE Interviews
                SET analysis_job_id = COALESCE(?, analysis_job_id),
                    analysis_status = CASE
                        WHEN ? IN ('queued', 'already_running') THEN 'queued'
                        WHEN ? IN ('ready', 'report_ready') THEN 'completed'
                        ELSE 'failed'
                    END
                WHERE interview_id = ? AND user_id = ?
                  AND attempt_status = 'completed'
                """,
                (job_id, state_name, state_name, interview_id, user_id),
            )
        except Exception:
            logger.exception("Could not recover local analysis attempt %s", interview_id)


async def maintenance_loop(stop_event: asyncio.Event, interval_seconds: float = 60.0) -> None:
    while not stop_event.is_set():
        try:
            await recover_orphaned_analysis_attempts()
        except Exception:
            logger.exception("Local maintenance pass failed")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
        except asyncio.TimeoutError:
            pass
