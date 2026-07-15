from __future__ import annotations

import logging
from typing import Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from analysis_pipeline import enqueue_analysis
from auth import get_current_user
from database import async_execute

router = APIRouter(prefix="/api/analysis", tags=["Analysis"])
logger = logging.getLogger("analysis")

_REPORT_READY_STATUSES = {"completed", "partial", "failed"}
_ANALYSIS_STATUSES = {"analysis_pending", "analysis_running"}


def _analysis_trigger_decision(status_value: object, has_report: bool) -> str:
    status_name = str(status_value or "").lower()
    if status_name in _REPORT_READY_STATUSES and has_report:
        return "ready"
    if status_name in _ANALYSIS_STATUSES or status_name in _REPORT_READY_STATUSES:
        return "enqueue"
    return "reject"


class AnalysisTriggerRequest(BaseModel):
    interview_id: str
    reason: Optional[str] = "manual_trigger"


@router.post("/reconcile-performance", status_code=status.HTTP_202_ACCEPTED)
async def reconcile_performance(current_user: Dict = Depends(get_current_user)):
    rows = await async_execute(
        """
        SELECT i.interview_id
        FROM Interviews i
        WHERE i.user_id = %s
          AND i.status IN ('completed', 'partial', 'failed')
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
          AND NOT EXISTS (
              SELECT 1 FROM SessionPerformanceAnalyses spa
              WHERE spa.interview_id = i.interview_id
                AND spa.user_id = i.user_id
                AND spa.schema_version = 'session-performance-v3'
                AND spa.status = 'ready'
                AND spa.analysis_json_encrypted IS NOT NULL
          )
        ORDER BY i.completed_at DESC NULLS LAST
        LIMIT 25
        """,
        (current_user["user_id"],),
        fetchall=True,
    )
    queued = []
    for row in rows or []:
        job_id = await enqueue_analysis(
            str(row[0]),
            current_user["user_id"],
            "performance_reconciliation",
            force_canonical_rebuild=True,
        )
        if job_id:
            queued.append({"interview_id": str(row[0]), "job_id": job_id})
    return {"status": "queued" if queued else "up_to_date", "queued": queued, "queued_count": len(queued)}


@router.post("/trigger")
async def trigger_analysis(request: AnalysisTriggerRequest, current_user: Dict = Depends(get_current_user)):
    interview = await async_execute(
        """
        SELECT interview_id, user_id, status, report_json, report_json_encrypted, analysis_job_id
        FROM Interviews
        WHERE interview_id = %s AND user_id = %s
        """,
        (request.interview_id, current_user["user_id"]),
        fetchone=True,
    )
    if not interview:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Interview not found")
    decision = _analysis_trigger_decision(interview[2], bool(interview[3] or interview[4]))
    if decision == "reject":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="End the interview before requesting its report.",
        )
    if decision == "ready":
        return {"job_id": interview[5], "status": interview[2], "report_ready": True}

    job_id = await enqueue_analysis(request.interview_id, current_user["user_id"], request.reason or "manual_trigger")
    await async_execute(
        """
        UPDATE Interviews
        SET analysis_job_id = %s,
            status = CASE
                WHEN status IN ('completed', 'partial', 'failed')
                     AND report_json IS NULL AND report_json_encrypted IS NULL
                THEN 'analysis_pending'
                ELSE status
            END
        WHERE interview_id = %s AND user_id = %s
          AND status IN ('analysis_pending', 'analysis_running', 'completed', 'partial', 'failed')
        """,
        (job_id, request.interview_id, current_user["user_id"]),
    )
    return {"job_id": job_id, "status": "analysis_pending", "report_ready": False}
