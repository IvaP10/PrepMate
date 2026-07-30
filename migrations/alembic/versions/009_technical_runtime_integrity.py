"""Harden technical evidence, workflow, and problem version lineage.

Revision ID: 009_technical_runtime_integrity
Revises: 008_improve_attempt_deadlines
Create Date: 2026-07-12

The content backfill is intentionally performed in the migration transaction so
an existing deployment never spends a compatibility release with candidate code
or reasoning left in plaintext.
"""

from __future__ import annotations

import json
from typing import Any, Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "009_technical_runtime_integrity"
down_revision: Union[str, None] = "008_improve_attempt_deadlines"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _json_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value if value is not None else {}, separators=(",", ":"), ensure_ascii=False, default=str)


def _encrypt_data(value: str) -> str:
    # Keep Alembic metadata commands independent of the application import
    # path. The application crypto module is only required when this migration
    # actually performs its data backfill.
    from security_utils import encrypt_data

    return encrypt_data(value)


def _encrypted_bytes(value: Any) -> bytes:
    return _encrypt_data(_json_text(value)).encode("utf-8")


def _backfill_legacy_code(bind: Any, table: str, id_column: str) -> None:
    rows = bind.execute(sa.text(
        f"""
        SELECT {id_column} AS row_id, source_code, source_excerpt
        FROM {table}
        WHERE source_code_encrypted IS NULL
          AND (
              (source_code IS NOT NULL AND source_code <> '' AND source_code <> '[encrypted]')
              OR (source_excerpt IS NOT NULL AND source_excerpt <> '' AND source_excerpt <> '[encrypted]')
          )
        """
    )).mappings()
    for row in rows:
        source = row["source_code"] or row["source_excerpt"] or ""
        bind.execute(
            sa.text(
                f"""
                UPDATE {table}
                SET source_code_encrypted = :encrypted,
                    source_code = '[encrypted]',
                    source_excerpt = '[encrypted]'
                WHERE {id_column} = :row_id
                """
            ),
            {"encrypted": _encrypt_data(str(source)).encode("utf-8"), "row_id": row["row_id"]},
        )


def _backfill_sensitive_technical_evidence(bind: Any) -> None:
    reasoning_rows = bind.execute(sa.text(
        """
        SELECT evidence_id, content, payload
        FROM TechnicalReasoningEvidence
        WHERE content_encrypted IS NULL
          AND (content IS NOT NULL OR payload <> '{}'::jsonb)
        """
    )).mappings()
    for row in reasoning_rows:
        full_payload = {"content": row["content"], "payload": row["payload"] or {}}
        bind.execute(
            sa.text(
                """
                UPDATE TechnicalReasoningEvidence
                SET content = '[encrypted]', payload = CAST(:marker AS JSONB),
                    content_encrypted = :encrypted
                WHERE evidence_id = :row_id
                """
            ),
            {"encrypted": _encrypted_bytes(full_payload), "marker": json.dumps({"encrypted": True}), "row_id": row["evidence_id"]},
        )

    telemetry_rows = bind.execute(sa.text(
        """
        SELECT event_id, payload
        FROM TechnicalTelemetryEvents
        WHERE payload_encrypted IS NULL AND payload <> '{}'::jsonb
        """
    )).mappings()
    for row in telemetry_rows:
        bind.execute(
            sa.text(
                """
                UPDATE TechnicalTelemetryEvents
                SET payload = CAST(:marker AS JSONB),
                    payload_encrypted = :encrypted
                WHERE event_id = :row_id
                """
            ),
            {"encrypted": _encrypted_bytes(row["payload"]), "marker": json.dumps({"encrypted": True}), "row_id": row["event_id"]},
        )

    whiteboard_rows = bind.execute(sa.text(
        """
        SELECT round_id, whiteboard_json
        FROM TechnicalInterviewRounds
        WHERE whiteboard_encrypted IS NULL
          AND whiteboard_json IS NOT NULL
          AND whiteboard_json <> '{}'::jsonb
        """
    )).mappings()
    for row in whiteboard_rows:
        bind.execute(
            sa.text(
                """
                UPDATE TechnicalInterviewRounds
                SET whiteboard_json = CAST(:marker AS JSONB),
                    whiteboard_encrypted = :encrypted
                WHERE round_id = :round_id
                """
            ),
            {"encrypted": _encrypted_bytes(row["whiteboard_json"]), "marker": json.dumps({"encrypted": True}), "round_id": row["round_id"]},
        )

    transcript_rows = bind.execute(sa.text(
        """
        SELECT interview_id, full_transcript
        FROM Interviews
        WHERE transcript_encrypted IS NULL
          AND full_transcript IS NOT NULL
          AND full_transcript <> '{}'::jsonb
          AND COALESCE(full_transcript->>'encrypted', 'false') <> 'true'
        """
    )).mappings()
    for row in transcript_rows:
        transcript = row["full_transcript"]
        turn_count = len(transcript) if isinstance(transcript, list) else 0
        bind.execute(
            sa.text(
                """
                UPDATE Interviews
                SET full_transcript = CAST(:marker AS jsonb),
                    transcript_encrypted = :encrypted
                WHERE interview_id = :interview_id
                """
            ),
            {
                "marker": json.dumps({"encrypted": True, "turn_count": turn_count, "captured": True}),
                "encrypted": _encrypted_bytes(transcript),
                "interview_id": row["interview_id"],
            },
        )


def upgrade() -> None:
    for statement in (
        "ALTER TABLE TechnicalProblemBank ADD COLUMN IF NOT EXISTS problem_family_id VARCHAR(64)",
        "ALTER TABLE TechnicalInterviewRounds ADD COLUMN IF NOT EXISTS problem_version INTEGER",
        "ALTER TABLE TechnicalInterviewRounds ADD COLUMN IF NOT EXISTS workflow_state JSONB NOT NULL DEFAULT '{}'::jsonb",
        "ALTER TABLE TechnicalInterviewRounds ADD COLUMN IF NOT EXISTS started_at TIMESTAMP",
        "ALTER TABLE TechnicalInterviewRounds ADD COLUMN IF NOT EXISTS whiteboard_encrypted BYTEA",
        "ALTER TABLE TechnicalReasoningEvidence ADD COLUMN IF NOT EXISTS content_encrypted BYTEA",
        "ALTER TABLE TechnicalReasoningEvidence ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(120)",
        "ALTER TABLE TechnicalReasoningEvidence ADD COLUMN IF NOT EXISTS evidence_hash VARCHAR(128)",
        "ALTER TABLE TechnicalTelemetryEvents ADD COLUMN IF NOT EXISTS payload_encrypted BYTEA",
        "ALTER TABLE TechnicalTelemetryEvents ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(120)",
        "ALTER TABLE TechnicalSubmissions ADD COLUMN IF NOT EXISTS execution_job_id VARCHAR(64)",
    ):
        op.execute(statement)

    op.execute(
        "UPDATE TechnicalProblemBank SET problem_family_id = COALESCE(problem_family_id, problem_id)"
    )
    op.execute(
        "ALTER TABLE TechnicalProblemBank ALTER COLUMN problem_family_id SET NOT NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_problem_family_version "
        "ON TechnicalProblemBank (problem_family_id, version)"
    )
    op.execute(
        """
        UPDATE TechnicalInterviewRounds round
        SET problem_version = bank.version
        FROM TechnicalProblemBank bank
        WHERE round.problem_id = bank.problem_id
          AND round.problem_version IS NULL
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_technical_round_problem_version "
        "ON TechnicalInterviewRounds (problem_id, problem_version)"
    )
    op.execute(
        "UPDATE TechnicalInterviewRounds SET started_at = COALESCE(started_at, created_at) "
        "WHERE status <> 'pending'"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_technical_reasoning_idempotency "
        "ON TechnicalReasoningEvidence (user_id, round_id, idempotency_key) "
        "WHERE idempotency_key IS NOT NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_technical_telemetry_idempotency "
        "ON TechnicalTelemetryEvents (user_id, round_id, idempotency_key) "
        "WHERE idempotency_key IS NOT NULL"
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'fk_technical_submission_execution_job'
            ) THEN
                ALTER TABLE TechnicalSubmissions
                    ADD CONSTRAINT fk_technical_submission_execution_job
                    FOREIGN KEY (execution_job_id)
                    REFERENCES TechnicalExecutionJobs(job_id) ON DELETE SET NULL;
            END IF;
        END $$
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_technical_submission_execution_job "
        "ON TechnicalSubmissions (execution_job_id) WHERE execution_job_id IS NOT NULL"
    )

    bind = op.get_bind()
    for table, id_column in (
        ("TechnicalRunEvents", "run_id"),
        ("TechnicalCodeSnapshots", "snapshot_id"),
        ("TechnicalSubmissions", "submission_id"),
    ):
        _backfill_legacy_code(bind, table, id_column)
    _backfill_sensitive_technical_evidence(bind)

    op.execute(
        "INSERT INTO SchemaMigrations (migration_id) "
        "VALUES ('009_technical_runtime_integrity') ON CONFLICT (migration_id) DO NOTHING"
    )


def downgrade() -> None:
    # Encryption/redaction is deliberately irreversible. A downgrade may remove
    # new indexes and lineage fields, but never restores sensitive plaintext.
    op.execute("DELETE FROM SchemaMigrations WHERE migration_id = '009_technical_runtime_integrity'")
    op.execute("DROP INDEX IF EXISTS uq_technical_submission_execution_job")
    op.execute("ALTER TABLE TechnicalSubmissions DROP CONSTRAINT IF EXISTS fk_technical_submission_execution_job")
    op.execute("DROP INDEX IF EXISTS uq_technical_telemetry_idempotency")
    op.execute("DROP INDEX IF EXISTS uq_technical_reasoning_idempotency")
    op.execute("DROP INDEX IF EXISTS idx_technical_round_problem_version")
    op.execute("DROP INDEX IF EXISTS uq_problem_family_version")
    op.execute("ALTER TABLE TechnicalSubmissions DROP COLUMN IF EXISTS execution_job_id")
    op.execute("ALTER TABLE TechnicalTelemetryEvents DROP COLUMN IF EXISTS idempotency_key")
    op.execute("ALTER TABLE TechnicalReasoningEvidence DROP COLUMN IF EXISTS evidence_hash")
    op.execute("ALTER TABLE TechnicalReasoningEvidence DROP COLUMN IF EXISTS idempotency_key")
    op.execute("ALTER TABLE TechnicalInterviewRounds DROP COLUMN IF EXISTS workflow_state")
    op.execute("ALTER TABLE TechnicalInterviewRounds DROP COLUMN IF EXISTS started_at")
    op.execute("ALTER TABLE TechnicalInterviewRounds DROP COLUMN IF EXISTS problem_version")
    op.execute("ALTER TABLE TechnicalProblemBank DROP COLUMN IF EXISTS problem_family_id")
