"""Seal canonical evidence and version report-stage provenance.

Revision ID: 012_report_evidence_truth
Revises: 011_attempt_foundations
Create Date: 2026-07-14
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "012_report_evidence_truth"
down_revision: Union[str, None] = "011_attempt_foundations"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS EvidenceManifests (
            manifest_id VARCHAR(64) PRIMARY KEY,
            interview_id VARCHAR(64) NOT NULL UNIQUE REFERENCES Interviews(interview_id) ON DELETE CASCADE,
            user_id VARCHAR(64) NOT NULL REFERENCES UserInfo(user_id) ON DELETE CASCADE,
            schema_version VARCHAR(40) NOT NULL,
            evidence_hash VARCHAR(128) NOT NULL,
            item_count INTEGER NOT NULL DEFAULT 0,
            manifest_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            manifest_encrypted BYTEA NOT NULL,
            sealed_at TIMESTAMP NOT NULL DEFAULT NOW(),
            created_at TIMESTAMP NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_evidence_manifest_hash ON EvidenceManifests (interview_id, evidence_hash)")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS EvidenceCorrections (
            correction_id VARCHAR(64) PRIMARY KEY,
            manifest_id VARCHAR(64) NOT NULL REFERENCES EvidenceManifests(manifest_id) ON DELETE CASCADE,
            interview_id VARCHAR(64) NOT NULL REFERENCES Interviews(interview_id) ON DELETE CASCADE,
            user_id VARCHAR(64) NOT NULL REFERENCES UserInfo(user_id) ON DELETE CASCADE,
            supersedes_evidence_type VARCHAR(80) NOT NULL,
            supersedes_evidence_id VARCHAR(160) NOT NULL,
            reason TEXT NOT NULL,
            correction_hash VARCHAR(128) NOT NULL,
            payload_encrypted BYTEA NOT NULL,
            actor_id VARCHAR(64),
            created_at TIMESTAMP NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_evidence_corrections_manifest ON EvidenceCorrections (manifest_id, created_at)")

    for statement in (
        "ALTER TABLE AnalysisJobs ADD COLUMN IF NOT EXISTS manifest_id VARCHAR(64)",
        "ALTER TABLE AnalysisStageOutputs ADD COLUMN IF NOT EXISTS input_hash VARCHAR(128)",
        "ALTER TABLE AnalysisStageOutputs ADD COLUMN IF NOT EXISTS model VARCHAR(160)",
        "ALTER TABLE AnalysisStageOutputs ADD COLUMN IF NOT EXISTS prompt_version VARCHAR(120)",
        "ALTER TABLE AnalysisStageOutputs ADD COLUMN IF NOT EXISTS provenance_json JSONB NOT NULL DEFAULT '{}'::jsonb",
        "ALTER TABLE ReportArtifacts ADD COLUMN IF NOT EXISTS evidence_hash VARCHAR(128)",
        "ALTER TABLE ReportArtifacts ADD COLUMN IF NOT EXISTS status VARCHAR(30) NOT NULL DEFAULT 'ready'",
        "ALTER TABLE ReportArtifacts ADD COLUMN IF NOT EXISTS provenance_json JSONB NOT NULL DEFAULT '{}'::jsonb",
        "ALTER TABLE ReportArtifacts ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP NOT NULL DEFAULT NOW()",
    ):
        op.execute(statement)
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_analysis_job_manifest') THEN
                ALTER TABLE AnalysisJobs
                    ADD CONSTRAINT fk_analysis_job_manifest
                    FOREIGN KEY (manifest_id) REFERENCES EvidenceManifests(manifest_id) ON DELETE RESTRICT;
            END IF;
        END $$
        """
    )
    op.execute("DROP INDEX IF EXISTS uq_analysis_stage_outputs_version")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_analysis_stage_outputs_evidence "
        "ON AnalysisStageOutputs (job_id, stage_name, stage_version, evidence_hash)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_analysis_stage_outputs_evidence")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_analysis_stage_outputs_version "
        "ON AnalysisStageOutputs (job_id, stage_name, stage_version)"
    )
    op.execute("ALTER TABLE AnalysisJobs DROP CONSTRAINT IF EXISTS fk_analysis_job_manifest")
    for table, column in (
        ("ReportArtifacts", "updated_at"),
        ("ReportArtifacts", "provenance_json"),
        ("ReportArtifacts", "status"),
        ("ReportArtifacts", "evidence_hash"),
        ("AnalysisStageOutputs", "provenance_json"),
        ("AnalysisStageOutputs", "prompt_version"),
        ("AnalysisStageOutputs", "model"),
        ("AnalysisStageOutputs", "input_hash"),
        ("AnalysisJobs", "manifest_id"),
    ):
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS {column}")
    op.execute("DROP TABLE IF EXISTS EvidenceCorrections")
    op.execute("DROP TABLE IF EXISTS EvidenceManifests")
