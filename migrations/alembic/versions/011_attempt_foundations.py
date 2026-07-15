"""Add immutable attempt context, persisted preflight, and split lifecycle state.

Revision ID: 011_attempt_foundations
Revises: 010_privacy_retention_backfill
Create Date: 2026-07-14
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "011_attempt_foundations"
down_revision: Union[str, None] = "010_privacy_retention_backfill"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for statement in (
        "ALTER TABLE ResumeVersions ADD COLUMN IF NOT EXISTS parent_resume_id VARCHAR(64)",
        "ALTER TABLE ResumeVersions ADD COLUMN IF NOT EXISTS superseded_at TIMESTAMP",
        "ALTER TABLE ResumeVersions ADD COLUMN IF NOT EXISTS immutable_at TIMESTAMP",
        "ALTER TABLE Interviews ADD COLUMN IF NOT EXISTS attempt_status VARCHAR(30)",
        "ALTER TABLE Interviews ADD COLUMN IF NOT EXISTS analysis_status VARCHAR(30)",
        "ALTER TABLE Interviews ADD COLUMN IF NOT EXISTS integrity_status VARCHAR(30)",
        "ALTER TABLE Interviews ADD COLUMN IF NOT EXISTS lifecycle_revision INTEGER NOT NULL DEFAULT 1",
        "ALTER TABLE Interviews ADD COLUMN IF NOT EXISTS recovery_deadline_at TIMESTAMP",
        "ALTER TABLE Interviews ADD COLUMN IF NOT EXISTS evidence_sealed_at TIMESTAMP",
        "ALTER TABLE Interviews ADD COLUMN IF NOT EXISTS evidence_hash VARCHAR(128)",
        "ALTER TABLE Interviews ADD COLUMN IF NOT EXISTS completion_kind VARCHAR(40)",
        "ALTER TABLE Interviews ADD COLUMN IF NOT EXISTS context_snapshot_id VARCHAR(64)",
    ):
        op.execute(statement)

    op.execute(
        """
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_resume_parent_version') THEN
                ALTER TABLE ResumeVersions ADD CONSTRAINT fk_resume_parent_version
                FOREIGN KEY (parent_resume_id) REFERENCES ResumeVersions(resume_id) ON DELETE SET NULL;
            END IF;
        END $$
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS AttemptPreflightChecks (
            preflight_id VARCHAR(64) PRIMARY KEY,
            user_id VARCHAR(64) NOT NULL REFERENCES UserInfo(user_id) ON DELETE CASCADE,
            blueprint_id VARCHAR(64) NOT NULL REFERENCES InterviewBlueprints(blueprint_id) ON DELETE CASCADE,
            flow VARCHAR(20) NOT NULL CHECK (flow IN ('interview', 'technical')),
            camera_ready BOOLEAN NOT NULL,
            microphone_ready BOOLEAN NOT NULL,
            microphone_level_detected BOOLEAN NOT NULL,
            screen_share_ready BOOLEAN NOT NULL,
            network_ready BOOLEAN NOT NULL,
            backend_ready BOOLEAN NOT NULL,
            openai_ready BOOLEAN NOT NULL,
            sandbox_ready BOOLEAN NOT NULL DEFAULT FALSE,
            worker_ready BOOLEAN NOT NULL,
            error_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
            created_at TIMESTAMP NOT NULL DEFAULT NOW(),
            expires_at TIMESTAMP NOT NULL,
            consumed_at TIMESTAMP,
            consumed_by_interview_id VARCHAR(64) REFERENCES Interviews(interview_id) ON DELETE SET NULL
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_attempt_preflight_owner_expiry ON AttemptPreflightChecks (user_id, blueprint_id, expires_at)")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS AttemptContextSnapshots (
            snapshot_id VARCHAR(64) PRIMARY KEY,
            interview_id VARCHAR(64) NOT NULL UNIQUE REFERENCES Interviews(interview_id) ON DELETE CASCADE,
            user_id VARCHAR(64) NOT NULL REFERENCES UserInfo(user_id) ON DELETE CASCADE,
            resume_id VARCHAR(64) NOT NULL REFERENCES ResumeVersions(resume_id) ON DELETE RESTRICT,
            job_profile_id INTEGER REFERENCES JobProfiles(profile_id) ON DELETE RESTRICT,
            blueprint_id VARCHAR(64) NOT NULL REFERENCES InterviewBlueprints(blueprint_id) ON DELETE RESTRICT,
            profile_type VARCHAR(32) NOT NULL,
            profile_config_version VARCHAR(40) NOT NULL,
            role VARCHAR(255) NOT NULL,
            company_hash VARCHAR(128) NOT NULL,
            context_hash VARCHAR(128) NOT NULL,
            resume_payload_encrypted BYTEA NOT NULL,
            job_context_encrypted BYTEA NOT NULL,
            blueprint_context_encrypted BYTEA NOT NULL,
            evaluator_version VARCHAR(80) NOT NULL,
            taxonomy_version VARCHAR(40) NOT NULL,
            rubric_version VARCHAR(40) NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_attempt_context_hash ON AttemptContextSnapshots (interview_id, context_hash)")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS AttemptIntegrityEvents (
            event_id VARCHAR(64) PRIMARY KEY,
            interview_id VARCHAR(64) NOT NULL REFERENCES Interviews(interview_id) ON DELETE CASCADE,
            user_id VARCHAR(64) NOT NULL REFERENCES UserInfo(user_id) ON DELETE CASCADE,
            client_session_id VARCHAR(64) NOT NULL,
            sequence BIGINT NOT NULL,
            event_type VARCHAR(80) NOT NULL,
            severity VARCHAR(20) NOT NULL DEFAULT 'info',
            source VARCHAR(30) NOT NULL DEFAULT 'browser',
            observed_at TIMESTAMP NOT NULL,
            received_at TIMESTAMP NOT NULL DEFAULT NOW(),
            payload_encrypted BYTEA,
            payload_hash VARCHAR(128) NOT NULL,
            idempotency_key VARCHAR(120),
            UNIQUE(interview_id, client_session_id, sequence)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_attempt_integrity_interview_time ON AttemptIntegrityEvents (interview_id, observed_at)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_attempt_integrity_user_time ON AttemptIntegrityEvents (user_id, received_at)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_attempt_integrity_severity ON AttemptIntegrityEvents (interview_id, severity, observed_at)")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_attempt_integrity_idempotency ON AttemptIntegrityEvents (interview_id, idempotency_key) WHERE idempotency_key IS NOT NULL")

    op.execute(
        """
        UPDATE Interviews SET
            attempt_status = CASE
                WHEN status IN ('in_progress', 'uploading') THEN 'active'
                WHEN status = 'recovering' THEN 'recovering'
                WHEN status = 'cancelled' THEN 'incomplete'
                WHEN status IN ('analysis_pending', 'analysis_running', 'completed', 'partial', 'failed') THEN 'completed'
                ELSE 'active' END,
            analysis_status = CASE
                WHEN status = 'analysis_pending' THEN 'queued'
                WHEN status = 'analysis_running' THEN 'running'
                WHEN status IN ('completed', 'partial') THEN 'ready'
                WHEN status = 'failed' THEN 'failed'
                ELSE 'not_requested' END,
            integrity_status = COALESCE(integrity_status, 'clean')
        WHERE attempt_status IS NULL OR analysis_status IS NULL OR integrity_status IS NULL
        """
    )
    for statement in (
        "ALTER TABLE Interviews ALTER COLUMN attempt_status SET DEFAULT 'active'",
        "ALTER TABLE Interviews ALTER COLUMN analysis_status SET DEFAULT 'not_requested'",
        "ALTER TABLE Interviews ALTER COLUMN integrity_status SET DEFAULT 'clean'",
        "ALTER TABLE Interviews ALTER COLUMN attempt_status SET NOT NULL",
        "ALTER TABLE Interviews ALTER COLUMN analysis_status SET NOT NULL",
        "ALTER TABLE Interviews ALTER COLUMN integrity_status SET NOT NULL",
    ):
        op.execute(statement)
    op.execute(
        """
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_interview_context_snapshot') THEN
                ALTER TABLE Interviews ADD CONSTRAINT fk_interview_context_snapshot
                FOREIGN KEY (context_snapshot_id) REFERENCES AttemptContextSnapshots(snapshot_id) ON DELETE RESTRICT;
            END IF;
        END $$
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION enforce_referenced_resume_immutability()
        RETURNS TRIGGER AS $$
        BEGIN
            IF OLD.immutable_at IS NOT NULL AND (
                NEW.resume_text_encrypted IS DISTINCT FROM OLD.resume_text_encrypted OR
                NEW.resume_payload_encrypted IS DISTINCT FROM OLD.resume_payload_encrypted OR
                NEW.facts_encrypted IS DISTINCT FROM OLD.facts_encrypted OR
                NEW.derived_taxonomy IS DISTINCT FROM OLD.derived_taxonomy OR
                NEW.resume_json IS DISTINCT FROM OLD.resume_json
            ) THEN RAISE EXCEPTION 'referenced resume version is immutable'; END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute("DROP TRIGGER IF EXISTS trg_referenced_resume_immutable ON ResumeVersions")
    op.execute("CREATE TRIGGER trg_referenced_resume_immutable BEFORE UPDATE ON ResumeVersions FOR EACH ROW EXECUTE FUNCTION enforce_referenced_resume_immutability()")
    op.execute(
        """
        UPDATE ResumeVersions rv SET immutable_at = COALESCE(rv.immutable_at, NOW())
        WHERE EXISTS (SELECT 1 FROM Interviews i WHERE i.resume_id = rv.resume_id)
           OR EXISTS (SELECT 1 FROM InterviewBlueprints b WHERE b.resume_id = rv.resume_id AND b.status = 'consumed')
        """
    )
    op.execute("INSERT INTO SchemaMigrations (migration_id) VALUES ('011_attempt_foundations') ON CONFLICT (migration_id) DO NOTHING")


def downgrade() -> None:
    op.execute("DELETE FROM SchemaMigrations WHERE migration_id = '011_attempt_foundations'")
    op.execute("ALTER TABLE Interviews DROP CONSTRAINT IF EXISTS fk_interview_context_snapshot")
    op.execute("DROP TABLE IF EXISTS AttemptIntegrityEvents")
    op.execute("DROP TABLE IF EXISTS AttemptContextSnapshots")
    op.execute("DROP TABLE IF EXISTS AttemptPreflightChecks")
    op.execute("DROP TRIGGER IF EXISTS trg_referenced_resume_immutable ON ResumeVersions")
    op.execute("DROP FUNCTION IF EXISTS enforce_referenced_resume_immutability")
    for column in ("context_snapshot_id", "completion_kind", "evidence_hash", "evidence_sealed_at", "recovery_deadline_at", "lifecycle_revision", "integrity_status", "analysis_status", "attempt_status"):
        op.execute(f"ALTER TABLE Interviews DROP COLUMN IF EXISTS {column}")
    op.execute("ALTER TABLE ResumeVersions DROP CONSTRAINT IF EXISTS fk_resume_parent_version")
    for column in ("immutable_at", "superseded_at", "parent_resume_id"):
        op.execute(f"ALTER TABLE ResumeVersions DROP COLUMN IF EXISTS {column}")
