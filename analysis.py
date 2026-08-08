from __future__ import annotations

import base64
import json
import logging
from datetime import datetime
from typing import Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from analysis_pipeline import (
    ANALYSIS_STAGE_VERSION,
    SESSION_PERFORMANCE_VERSION,
    enqueue_analysis,
)
from auth import get_current_user
from database import async_execute

router = APIRouter(prefix="/api/analysis", tags=["Analysis"])
logger = logging.getLogger("analysis")

_REPORT_READY_STATUSES = {"completed", "report_ready", "partial", "failed"}
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


def _decode_reconcile_cursor(value: Optional[str]) -> tuple[Optional[datetime], Optional[str]]:
    if not value:
        return None, None
    try:
        padded = value + ("=" * (-len(value) % 4))
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
        return datetime.fromisoformat(str(payload["completed_at"])), str(payload["interview_id"])
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid reconciliation cursor.",
        ) from exc


def _encode_reconcile_cursor(completed_at: datetime, interview_id: str) -> str:
    payload = json.dumps({
        "completed_at": completed_at.isoformat(),
        "interview_id": interview_id,
    }, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


@router.post("/reconcile-performance", status_code=status.HTTP_202_ACCEPTED)
async def reconcile_performance(
    cursor: Optional[str] = Query(default=None),
    limit: int = Query(default=25, ge=1, le=100),
    current_user: Dict = Depends(get_current_user),
):
    cursor_value = cursor if isinstance(cursor, str) else None
    limit_value = limit if isinstance(limit, int) else 25
    cursor_completed_at, cursor_interview_id = _decode_reconcile_cursor(cursor_value)
    rows = await async_execute(
        """
        SELECT i.interview_id, COALESCE(i.completed_at, i.created_at) AS ordering_time
        FROM Interviews i
        WHERE i.user_id = %s
          AND i.status IN ('analysis_pending', 'analysis_running', 'completed', 'partial', 'failed')
          AND i.attempt_status = 'completed'
          AND (
              %s::timestamp IS NULL
              OR (COALESCE(i.completed_at, i.created_at), i.interview_id)
                 < (%s::timestamp, %s)
          )
          AND NOT EXISTS (
              SELECT 1 FROM SessionPerformanceAnalyses spa
              WHERE spa.interview_id = i.interview_id
                AND spa.user_id = i.user_id
                AND spa.schema_version = %s
                AND spa.producer_version = %s
                AND spa.status = 'ready'
                AND spa.is_current = TRUE
                AND spa.analysis_json_encrypted IS NOT NULL
                AND spa.evidence_index_encrypted IS NOT NULL
          )
        ORDER BY COALESCE(i.completed_at, i.created_at) DESC, i.interview_id DESC
        LIMIT %s
        """,
        (
            current_user["user_id"],
            cursor_completed_at, cursor_completed_at, cursor_interview_id,
            SESSION_PERFORMANCE_VERSION, ANALYSIS_STAGE_VERSION, limit_value,
        ),
        fetchall=True,
    )
    results = []
    counts = {
        "queued": 0,
        "already_running": 0,
        "ready": 0,
        "report_ready": 0,
        "retry_exhausted": 0,
        "rejected": 0,
    }
    for row in rows or []:
        enqueue_result = await enqueue_analysis(
            str(row[0]),
            current_user["user_id"],
            "performance_reconciliation",
            force_canonical_rebuild=True,
            return_result=True,
        )
        result = (
            enqueue_result
            if isinstance(enqueue_result, dict)
            else {
                "state": "queued" if enqueue_result else "rejected",
                "job_id": enqueue_result,
                "reason": None if enqueue_result else "analysis_not_queued",
            }
        )
        state_name = str(result.get("state") or "rejected")
        counts[state_name] = counts.get(state_name, 0) + 1
        results.append({
            "interview_id": str(row[0]),
            "job_id": result.get("job_id"),
            "state": state_name,
            "reason": result.get("reason"),
        })

    next_cursor = None
    if rows and len(rows) == limit_value and len(rows[-1]) > 1:
        next_cursor = _encode_reconcile_cursor(rows[-1][1], str(rows[-1][0]))
    active_count = counts.get("queued", 0) + counts.get("already_running", 0)
    return {
        "status": "queued" if active_count else ("attention_required" if counts.get("retry_exhausted") else "up_to_date"),
        "results": results,
        "queued": [
            item for item in results
            if item["state"] in {"queued", "already_running"}
        ],
        "queued_count": counts.get("queued", 0),
        "already_running_count": counts.get("already_running", 0),
        "retry_exhausted_count": counts.get("retry_exhausted", 0),
        "rejected_count": counts.get("rejected", 0),
        "ready_count": counts.get("ready", 0) + counts.get("report_ready", 0),
        "next_cursor": next_cursor,
        "has_more": next_cursor is not None,
        "processing_sla_minutes": 15,
    }


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
    canonical_row = await async_execute(
        """
        SELECT EXISTS (
            SELECT 1
            FROM SessionPerformanceAnalyses
            WHERE interview_id = %s
              AND user_id = %s
              AND schema_version = 'session-performance-v4'
              AND producer_version = %s
              AND status = 'ready'
              AND is_current = TRUE
              AND analysis_json_encrypted IS NOT NULL
              AND evidence_index_encrypted IS NOT NULL
        )
        """,
        (request.interview_id, current_user["user_id"], ANALYSIS_STAGE_VERSION),
        fetchone=True,
    )
    has_current_report = bool(interview[3] or interview[4]) and bool(canonical_row and canonical_row[0])
    decision = _analysis_trigger_decision(interview[2], has_current_report)
    if decision == "reject":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="End the interview before requesting its report.",
        )
    if decision == "ready":
        return {"job_id": interview[5], "status": interview[2], "report_ready": True}

    job_id = await enqueue_analysis(
        request.interview_id,
        current_user["user_id"],
        request.reason or "manual_trigger",
        force_canonical_rebuild=not has_current_report,
    )
    await async_execute(
        """
        UPDATE Interviews
        SET analysis_job_id = %s,
            status = CASE
                WHEN status IN ('completed', 'report_ready', 'partial', 'failed')
                     AND report_json IS NULL AND report_json_encrypted IS NULL
                THEN 'analysis_pending'
                ELSE status
            END
        WHERE interview_id = %s AND user_id = %s
          AND status IN ('analysis_pending', 'analysis_running', 'completed', 'report_ready', 'partial', 'failed')
        """,
        (job_id, request.interview_id, current_user["user_id"]),
    )
    return {"job_id": job_id, "status": "analysis_pending", "report_ready": False}
