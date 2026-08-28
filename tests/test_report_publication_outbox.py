import asyncio
import inspect
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

import analysis_pipeline
from security_utils import decrypt_data


ROOT = Path(__file__).resolve().parents[1]


class _PublicationCursor:
    def __init__(self, *, fail_on: str | None = None, manifest_is_current: bool = True):
        self.fail_on = fail_on
        self.manifest_is_current = manifest_is_current
        self.queries: list[tuple[str, object]] = []
        self.last_query = ""

    def execute(self, query, params=None):
        normalized = " ".join(query.split())
        self.last_query = normalized
        self.queries.append((normalized, params))
        if self.fail_on and self.fail_on in normalized:
            raise RuntimeError("simulated publication crash")

    def fetchone(self):
        if "FROM AnalysisJobs" in self.last_query:
            return ("running", "worker-1", "manifest-1", "manifest-evidence-1")
        if "FROM EvidenceManifests" in self.last_query:
            return (
                "manifest-evidence-1",
                self.manifest_is_current,
                analysis_pipeline.ANALYSIS_STAGE_VERSION,
            )
        if "FROM Interviews" in self.last_query:
            return ("analysis_running",)
        if "FROM SessionPerformanceAnalyses" in self.last_query:
            return (
                "staged",
                False,
                "canonical-evidence-1",
                analysis_pipeline.ANALYSIS_STAGE_VERSION,
                b"analysis",
                b"evidence-index",
                "mock",
            )
        if "FROM ReportArtifacts" in self.last_query:
            return ("staged", "manifest-evidence-1", "analysis-1", b"report")
        return None

    def close(self):
        return None


class _PublicationConnection:
    def __init__(self, cursor):
        self._cursor = cursor
        self.commit_count = 0
        self.rollback_count = 0

    def cursor(self):
        return self._cursor

    def commit(self):
        self.commit_count += 1

    def rollback(self):
        self.rollback_count += 1


def _publish(connection):
    with (
        patch("database.get_db_connection", return_value=connection),
        patch("database.return_db_connection"),
    ):
        return asyncio.run(analysis_pipeline._publish_staged_report(
            job_id="job-1",
            worker_id="worker-1",
            interview_id="interview-1",
            user_id="user-1",
            analysis_id="analysis-1",
            artifact_id="artifact-1",
            publication_key="report:analysis-1:candidate",
            final_status="completed",
            report={"overall_score": 78, "summary": "Evidence-backed result."},
            safe_report={"overall_score": 78, "summary": "Evidence-backed result."},
            report_encrypted=b"report",
            manifest_evidence_hash="manifest-evidence-1",
            canonical_evidence_hash="canonical-evidence-1",
            mode="mock",
            observations=[{
                "skill_key": "interview:ownership",
                "score": 62,
                "private_detail": "PRIVATE-OUTBOX-MARKER-29be7f",
            }],
            weak_topics=[],
        ))


def test_publication_commits_performance_artifact_history_job_and_outbox_once():
    cursor = _PublicationCursor()
    connection = _PublicationConnection(cursor)

    result = _publish(connection)

    statements = [query for query, _ in cursor.queries]
    assert connection.commit_count == 1
    assert connection.rollback_count == 0
    assert statements[0].strip() == "BEGIN IMMEDIATE"
    assert any("UPDATE SessionPerformanceAnalyses" in query and "is_current = TRUE" in query for query in statements)
    assert any("UPDATE ReportArtifacts" in query and "published_at" in query for query in statements)
    assert any("UPDATE Interviews" in query and "report_json_encrypted" in query for query in statements)
    assert any("INSERT INTO ReportSideEffectOutbox" in query and "ON CONFLICT" in query for query in statements)
    assert any("UPDATE AnalysisJobs" in query and "lease_owner = NULL" in query for query in statements)
    assert result["outbox_event_id"]
    outbox_params = next(
        params for query, params in cursor.queries if "INSERT INTO ReportSideEffectOutbox" in query
    )
    assert "PRIVATE-OUTBOX-MARKER-29be7f" not in str(outbox_params[6])
    assert b"PRIVATE-OUTBOX-MARKER-29be7f" not in outbox_params[7]
    assert json.loads(decrypt_data(outbox_params[7]))["observations"][0]["private_detail"].endswith("29be7f")
    interview_params = next(
        params for query, params in cursor.queries if "UPDATE Interviews SET status" in query
    )
    assert interview_params[2] == "Analysis completed."


def test_publication_crash_rolls_back_every_visibility_change():
    cursor = _PublicationCursor(fail_on="UPDATE Interviews SET status")
    connection = _PublicationConnection(cursor)

    with pytest.raises(RuntimeError, match="simulated publication crash"):
        _publish(connection)

    assert connection.commit_count == 0
    assert connection.rollback_count == 1


def test_delayed_worker_cannot_publish_after_its_manifest_is_superseded():
    cursor = _PublicationCursor(manifest_is_current=False)
    connection = _PublicationConnection(cursor)

    result = _publish(connection)

    statements = [query for query, _ in cursor.queries]
    assert result["superseded"] is True
    assert connection.commit_count == 1
    assert connection.rollback_count == 0
    assert any(
        "UPDATE SessionPerformanceAnalyses" in query
        and "status = 'superseded'" in query
        for query in statements
    )
    assert any(
        "UPDATE ReportArtifacts" in query and "status = 'superseded'" in query
        for query in statements
    )
    assert not any("UPDATE Interviews SET status" in query for query in statements)
    assert not any("INSERT INTO ReportSideEffectOutbox" in query for query in statements)


def test_report_is_validated_then_staged_before_atomic_publication():
    source = inspect.getsource(analysis_pipeline.run_analysis_job)

    assert source.index("_validate_report_for_publication") < source.index("_stage_canonical_performance")
    assert source.index("_stage_canonical_performance") < source.index("_stage_candidate_report_artifact")
    assert source.index("_stage_candidate_report_artifact") < source.index("_publish_staged_report")

    stage_source = inspect.getsource(analysis_pipeline._stage_canonical_performance)
    assert "'staged'" in stage_source
    assert "FALSE" in stage_source
    assert "SET is_current = FALSE" not in stage_source
    assert "WHERE analysis_id = ? AND status = 'staged'" in stage_source
    assert "analysis_json_encrypted = ?" in stage_source

    publication_source = inspect.getsource(analysis_pipeline._publish_staged_report)
    assert 'cursor.execute("BEGIN IMMEDIATE")' in publication_source
    assert "FROM EvidenceManifests" in publication_source
    assert "superseded_by_newer_evidence" in publication_source


def test_outbox_claim_uses_atomic_sqlite_claim_and_expired_lease_recovery():
    event = (
        "event-1", "improve_sync", "analysis-1", "interview-1", "user-1",
        None, {}, 1, 8,
    )
    execute = AsyncMock(return_value=event)
    with patch.object(analysis_pipeline, "async_execute", execute):
        claimed = asyncio.run(analysis_pipeline.claim_report_side_effect("worker-1"))

    query, params = execute.await_args.args[:2]
    assert claimed == event
    assert "UPDATE ReportSideEffectOutbox" in query
    assert "WHERE event_id = (" in query
    assert "SELECT event_id" in query
    assert "FOR UPDATE" not in query
    assert "SKIP LOCKED" not in query
    assert "status = 'processing'" in query
    assert "lease_expires_at < CURRENT_TIMESTAMP" in query
    assert "attempt_count = attempt_count + 1" in query
    assert params == ("worker-1", analysis_pipeline.REPORT_SIDE_EFFECT_LEASE_SECONDS)


def test_outbox_delivery_fence_uses_sqlite_write_transaction_for_crash_safe_release():
    acquire_source = inspect.getsource(analysis_pipeline._acquire_report_side_effect_fence)
    release_source = inspect.getsource(analysis_pipeline._release_report_side_effect_fence)

    assert 'cursor.execute("BEGIN IMMEDIATE")' in acquire_source
    assert "pg_advisory" not in acquire_source
    assert "conn.commit()" in release_source
    assert "conn.rollback()" in release_source


def test_outbox_failure_requeues_then_dead_letters_at_bounded_attempts():
    execute = AsyncMock(return_value=("dead_letter",))
    with patch.object(analysis_pipeline, "async_execute", execute):
        state = asyncio.run(analysis_pipeline._fail_report_side_effect(
            "event-1",
            "worker-1",
            RuntimeError("secret provider detail"),
        ))

    query, params = execute.await_args.args[:2]
    assert state == "dead_letter"
    assert "attempt_count >= max_attempts" in query
    assert "dead_letter_at" in query
    assert "1 <<" in query
    assert params[0] == "RuntimeError:report_side_effect_failed"
    assert "secret provider detail" not in str(params)


def test_outbox_delivery_is_replay_safe_and_completes_only_after_all_steps():
    event = (
        "event-1",
        "improve_sync",
        "analysis-1",
        "interview-1",
        "user-1",
        analysis_pipeline._encrypted_bytes({
            "analysis_id": "analysis-1",
            "mode": "mock",
            "observations": [{"skill_key": "interview:ownership", "score": 62}],
            "weak_topics": [],
        }),
        {"encrypted": True},
        1,
        8,
    )
    execute = AsyncMock(return_value=(True, "ready", analysis_pipeline.ANALYSIS_STAGE_VERSION))
    dummy_lock = (object(), object())
    with (
        patch.object(analysis_pipeline, "async_execute", execute),
        patch.object(analysis_pipeline, "_acquire_report_side_effect_fence", return_value=dummy_lock),
        patch.object(analysis_pipeline, "_release_report_side_effect_fence"),
        patch.object(analysis_pipeline, "retire_superseded_analysis_evidence", new=AsyncMock()) as retire,
        patch.object(analysis_pipeline, "persist_weakness_states", new=AsyncMock()) as persist,
        patch.object(analysis_pipeline, "validate_mission_with_analysis", new=AsyncMock()) as validate,
        patch.object(analysis_pipeline, "_queue_learning_from_analysis", new=AsyncMock()) as learning,
        patch.object(analysis_pipeline, "ensure_mission_from_weakness", new=AsyncMock()) as mission,
        patch.object(analysis_pipeline, "_renew_report_side_effect_lease", new=AsyncMock()) as renew,
        patch.object(analysis_pipeline, "_complete_report_side_effect", new=AsyncMock()) as complete,
        patch.object(analysis_pipeline, "_fail_report_side_effect", new=AsyncMock()) as fail,
    ):
        asyncio.run(analysis_pipeline.process_report_side_effect(event, "worker-1"))

    retire.assert_awaited_once_with("interview-1", "analysis-1")
    persist.assert_awaited_once()
    validate.assert_awaited_once()
    learning.assert_awaited_once_with("interview-1", "user-1", suppress_errors=False)
    mission.assert_awaited_once()
    assert renew.await_count == 4
    complete.assert_awaited_once_with("event-1", "worker-1")
    fail.assert_not_awaited()


def test_outbox_does_not_create_improve_for_insufficient_canonical_evidence():
    event = (
        "event-insufficient",
        "improve_sync",
        "analysis-insufficient",
        "interview-insufficient",
        "user-1",
        None,
        {"analysis_id": "analysis-insufficient", "mode": "mock"},
        1,
        8,
    )
    execute = AsyncMock(return_value=(True, "ready", analysis_pipeline.ANALYSIS_STAGE_VERSION, "insufficient_evidence", None))
    dummy_lock = (object(), object())
    with (
        patch.object(analysis_pipeline, "async_execute", execute),
        patch.object(analysis_pipeline, "_acquire_report_side_effect_fence", return_value=dummy_lock),
        patch.object(analysis_pipeline, "_release_report_side_effect_fence"),
        patch.object(analysis_pipeline, "persist_weakness_states", new=AsyncMock()) as persist,
        patch.object(analysis_pipeline, "_queue_learning_from_analysis", new=AsyncMock()) as learning,
        patch.object(analysis_pipeline, "ensure_mission_from_weakness", new=AsyncMock()) as mission,
        patch.object(analysis_pipeline, "_complete_report_side_effect", new=AsyncMock()) as complete,
        patch.object(analysis_pipeline, "_fail_report_side_effect", new=AsyncMock()) as fail,
    ):
        asyncio.run(analysis_pipeline.process_report_side_effect(event, "worker-1"))

    persist.assert_not_awaited()
    learning.assert_not_awaited()
    mission.assert_not_awaited()
    complete.assert_awaited_once_with(
        "event-insufficient",
        "worker-1",
        delivery_note="improve_not_available_for_insufficient_evidence",
    )
    fail.assert_not_awaited()


def test_local_schema_defines_deduplicated_durable_outbox():
    schema = (ROOT / "local_schema.sql").read_text()

    assert "ReportSideEffectOutbox" in schema
    assert "idempotency_key" in schema
    assert "lease_expires_at" in schema
    assert "dead_letter" in schema
    assert "publication_key" in schema
    assert "uq_session_performance_staged_identity" in schema
