import asyncio
import importlib
import os
from unittest.mock import AsyncMock, patch

os.environ.setdefault("ENVIRONMENT", "test")

import analysis_pipeline
import local_maintenance
import technical_worker


class FakeCursor:
    def __init__(self, rows):
        self.rows = list(rows)
        self.calls = []

    def execute(self, query, params=None):
        self.calls.append((" ".join(str(query).split()), params))

    def fetchone(self):
        return self.rows.pop(0) if self.rows else None

    def close(self):
        return None


class FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor
        self.committed = False
        self.rolled_back = False

    def cursor(self):
        return self._cursor

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


def test_deferred_technical_finalization_commits_completed_analysis_lifecycle():
    cursor = FakeCursor([
        (
            "user-1",
            "in_progress",
            {
                "technical_finalize_requested": True,
                "technical_finalize_reason": "rest_end",
            },
        ),
        (0,),
    ])
    connection = FakeConnection(cursor)
    with (
        patch.object(technical_worker, "get_db_connection", return_value=connection),
        patch.object(technical_worker, "return_db_connection"),
    ):
        user_id = technical_worker._mark_finalize_requested_if_drained_sync("interview-1")

    update_sql = next(query for query, _ in cursor.calls if query.startswith("UPDATE Interviews"))
    round_update_sql = next(
        query for query, _ in cursor.calls
        if query.startswith("UPDATE TechnicalInterviewRounds AS round")
    )
    assert user_id == "user-1"
    assert connection.committed is True
    assert "status = 'analysis_pending'" in update_sql
    assert "attempt_status = 'completed'" in update_sql
    assert "analysis_status = 'queued'" in update_sql
    assert "recovery_deadline_at = NULL" in update_sql
    assert "interview.completion_kind = 'deadline'" in round_update_sql
    assert "'submitted', 'completed', 'expired', 'cancelled'" in round_update_sql


def test_deferred_technical_finalization_enqueues_and_links_analysis_job():
    enqueue = AsyncMock(return_value="analysis-job-1")
    execute = AsyncMock(return_value=None)
    current_analysis_pipeline = importlib.import_module("analysis_pipeline")
    current_database = importlib.import_module("database")
    with (
        patch.object(technical_worker, "_mark_finalize_requested_if_drained_sync", return_value="user-1"),
        patch.object(current_analysis_pipeline, "enqueue_analysis", enqueue),
        patch.object(current_database, "async_execute", execute),
    ):
        job_id = asyncio.run(technical_worker.finalize_requested_interview_if_drained("interview-1"))

    assert job_id == "analysis-job-1"
    enqueue.assert_awaited_once_with("interview-1", "user-1", "technical_execution_drained")
    assert execute.await_args.args[1] == ("analysis-job-1", "interview-1", "user-1")


def test_deferred_technical_finalization_marks_queue_failure_for_recovery():
    enqueue = AsyncMock(side_effect=RuntimeError("database unavailable"))
    execute = AsyncMock(return_value=None)
    current_analysis_pipeline = importlib.import_module("analysis_pipeline")
    current_database = importlib.import_module("database")
    with (
        patch.object(technical_worker, "_mark_finalize_requested_if_drained_sync", return_value="user-1"),
        patch.object(current_analysis_pipeline, "enqueue_analysis", enqueue),
        patch.object(current_database, "async_execute", execute),
    ):
        job_id = asyncio.run(technical_worker.finalize_requested_interview_if_drained("interview-1"))

    assert job_id is None
    assert "analysis_status = 'failed'" in execute.await_args.args[0]
    assert execute.await_args.args[1] == ("interview-1", "user-1")


def test_orphaned_completed_attempt_is_requeued_without_touching_failed_jobs():
    execute = AsyncMock(side_effect=[
        [("interview-1", "user-1")],
        None,
    ])
    enqueue = AsyncMock(return_value={
        "job_id": "analysis-job-1",
        "state": "queued",
        "reason": None,
    })
    current_analysis_pipeline = importlib.import_module("analysis_pipeline")
    current_database = importlib.import_module("database")
    with (
        patch.object(current_analysis_pipeline, "enqueue_analysis_result", enqueue),
        patch.object(current_database, "async_execute", execute),
    ):
        asyncio.run(local_maintenance.recover_orphaned_analysis_attempts())

    enqueue.assert_awaited_once_with(
        "interview-1",
        "user-1",
        "orphaned_analysis_recovery",
        force_canonical_rebuild=True,
    )
    selection_sql = execute.await_args_list[0].args[0]
    assert "job.producer_version = ?" in selection_sql
    assert "job.status IN ('queued', 'running')" in selection_sql
    assert "FROM ReportArtifacts artifact" in selection_sql
    assert "FROM ReportSideEffectOutbox side_effect" in selection_sql
    assert "job.status = 'failed'" not in selection_sql
    assert execute.await_args_list[1].args[1][0] == "analysis-job-1"


def test_enqueue_repairs_legacy_pending_attempt_before_creating_job():
    cursor = FakeCursor([
        ("analysis_pending", None, None, None, None, "active"),
        None,
    ])
    connection = FakeConnection(cursor)
    current_database = importlib.import_module("database")
    with (
        patch.object(current_database, "get_db_connection", return_value=connection),
        patch.object(current_database, "return_db_connection"),
        patch.object(analysis_pipeline, "_seal_evidence_manifest", return_value=("manifest-1", "evidence-1")),
        patch.object(analysis_pipeline.uuid, "uuid4", return_value="analysis-job-1"),
    ):
        job_id = asyncio.run(analysis_pipeline.enqueue_analysis("interview-1", "user-1", "status_poll"))

    executed_sql = "\n".join(query for query, _ in cursor.calls)
    assert job_id == "analysis-job-1"
    assert connection.committed is True
    assert "SET attempt_status = 'completed'" in executed_sql
    assert "INSERT INTO AnalysisJobs" in executed_sql
    assert "UPDATE Interviews SET analysis_job_id" in executed_sql
