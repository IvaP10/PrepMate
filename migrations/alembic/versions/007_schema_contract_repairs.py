"""Repair columns required by the durable analysis contract.

Revision ID: 007_schema_contract_repairs
Revises: 006_runtime_hardening
Create Date: 2026-07-11
"""

from typing import Sequence, Union

from alembic import op


revision: str = "007_schema_contract_repairs"
down_revision: Union[str, None] = "006_runtime_hardening"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE Interviews ADD COLUMN IF NOT EXISTS analysis_job_id VARCHAR(64)")
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'fk_interviews_analysis_job'
            ) THEN
                ALTER TABLE Interviews
                    ADD CONSTRAINT fk_interviews_analysis_job
                    FOREIGN KEY (analysis_job_id)
                    REFERENCES AnalysisJobs(job_id) ON DELETE SET NULL;
            END IF;
        END $$
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_interviews_analysis_job ON Interviews (analysis_job_id)"
    )
    op.execute(
        "INSERT INTO SchemaMigrations (migration_id) "
        "VALUES ('007_schema_contract_repairs') ON CONFLICT (migration_id) DO NOTHING"
    )


def downgrade() -> None:
    op.execute("DELETE FROM SchemaMigrations WHERE migration_id = '007_schema_contract_repairs'")
    op.execute("DROP INDEX IF EXISTS idx_interviews_analysis_job")
    op.execute("ALTER TABLE Interviews DROP CONSTRAINT IF EXISTS fk_interviews_analysis_job")
    op.execute("ALTER TABLE Interviews DROP COLUMN IF EXISTS analysis_job_id")

