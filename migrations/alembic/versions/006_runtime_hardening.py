"""Forward repairs for encryption, idempotency, and blueprint reuse.

Revision ID: 006_runtime_hardening
Revises: 005_evidence_pipeline
Create Date: 2026-07-11
"""

from typing import Sequence, Union

from alembic import op


revision: str = "006_runtime_hardening"
down_revision: Union[str, None] = "005_evidence_pipeline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Content hashes support deterministic reuse, but a consumed/expired
    # blueprint must not block compiling the same immutable inputs again.
    op.execute(
        "ALTER TABLE InterviewBlueprints DROP CONSTRAINT IF EXISTS uq_blueprint_owner_hash"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_blueprints_owner_hash "
        "ON InterviewBlueprints (user_id, blueprint_hash, created_at DESC)"
    )

    for statement in (
        "ALTER TABLE AnalysisStageOutputs ADD COLUMN IF NOT EXISTS output_encrypted BYTEA",
        "ALTER TABLE SessionPerformanceAnalyses ADD COLUMN IF NOT EXISTS analysis_json_encrypted BYTEA",
        "ALTER TABLE SessionPerformanceAnalyses ADD COLUMN IF NOT EXISTS evidence_index_encrypted BYTEA",
    ):
        op.execute(statement)

    for statement in (
        "ALTER TABLE MissionValidationEvidence ADD COLUMN IF NOT EXISTS source_key VARCHAR(180)",
        "ALTER TABLE MissionValidationEvidence ADD COLUMN IF NOT EXISTS evidence_hash VARCHAR(128)",
    ):
        op.execute(statement)
    op.execute(
        """
        UPDATE MissionValidationEvidence
        SET source_key = COALESCE(
                source_key,
                CONCAT_WS(':', evidence_type, analysis_id, interview_id, roadmap_node_id, validation_id)
            ),
            evidence_hash = COALESCE(evidence_hash, MD5(evidence_json::text))
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_mission_validation_idempotency "
        "ON MissionValidationEvidence (mission_id, source_key, evidence_hash)"
    )

    op.execute(
        "INSERT INTO SchemaMigrations (migration_id) "
        "VALUES ('006_runtime_hardening') ON CONFLICT (migration_id) DO NOTHING"
    )


def downgrade() -> None:
    op.execute("DELETE FROM SchemaMigrations WHERE migration_id = '006_runtime_hardening'")
    op.execute("DROP INDEX IF EXISTS uq_mission_validation_idempotency")
    op.execute("ALTER TABLE MissionValidationEvidence DROP COLUMN IF EXISTS evidence_hash")
    op.execute("ALTER TABLE MissionValidationEvidence DROP COLUMN IF EXISTS source_key")
    op.execute("ALTER TABLE SessionPerformanceAnalyses DROP COLUMN IF EXISTS evidence_index_encrypted")
    op.execute("ALTER TABLE SessionPerformanceAnalyses DROP COLUMN IF EXISTS analysis_json_encrypted")
    op.execute("ALTER TABLE AnalysisStageOutputs DROP COLUMN IF EXISTS output_encrypted")
    op.execute("DROP INDEX IF EXISTS idx_blueprints_owner_hash")
    op.execute(
        "ALTER TABLE InterviewBlueprints "
        "ADD CONSTRAINT uq_blueprint_owner_hash UNIQUE (user_id, blueprint_hash)"
    )
