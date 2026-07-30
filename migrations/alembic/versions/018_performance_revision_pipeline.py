"""Add revision-safe evidence manifests and canonical performance analyses.

Revision ID: 018_performance_revisions
Revises: 017_allow_job_profile_detach
Create Date: 2026-07-16
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "018_performance_revisions"
down_revision: Union[str, None] = "017_allow_job_profile_detach"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for statement in (
        "ALTER TABLE EvidenceManifests ADD COLUMN IF NOT EXISTS revision_no INTEGER NOT NULL DEFAULT 1",
        "ALTER TABLE EvidenceManifests ADD COLUMN IF NOT EXISTS is_current BOOLEAN NOT NULL DEFAULT TRUE",
        "ALTER TABLE EvidenceManifests ADD COLUMN IF NOT EXISTS supersedes_manifest_id VARCHAR(64)",
        "ALTER TABLE EvidenceManifests ADD COLUMN IF NOT EXISTS producer_version VARCHAR(80) NOT NULL DEFAULT 'evidence-v3'",
        "ALTER TABLE SessionPerformanceAnalyses ADD COLUMN IF NOT EXISTS revision_no INTEGER NOT NULL DEFAULT 1",
        "ALTER TABLE SessionPerformanceAnalyses ADD COLUMN IF NOT EXISTS is_current BOOLEAN NOT NULL DEFAULT TRUE",
        "ALTER TABLE SessionPerformanceAnalyses ADD COLUMN IF NOT EXISTS supersedes_analysis_id VARCHAR(64)",
        "ALTER TABLE SessionPerformanceAnalyses ADD COLUMN IF NOT EXISTS producer_version VARCHAR(80) NOT NULL DEFAULT 'evidence-v3'",
        "ALTER TABLE AnalysisJobs ADD COLUMN IF NOT EXISTS producer_version VARCHAR(80) NOT NULL DEFAULT 'evidence-v3'",
    ):
        op.execute(statement)

    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'fk_evidence_manifest_supersedes'
            ) THEN
                ALTER TABLE EvidenceManifests
                    ADD CONSTRAINT fk_evidence_manifest_supersedes
                    FOREIGN KEY (supersedes_manifest_id)
                    REFERENCES EvidenceManifests(manifest_id)
                    ON DELETE SET NULL;
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'fk_session_performance_supersedes'
            ) THEN
                ALTER TABLE SessionPerformanceAnalyses
                    ADD CONSTRAINT fk_session_performance_supersedes
                    FOREIGN KEY (supersedes_analysis_id)
                    REFERENCES SessionPerformanceAnalyses(analysis_id)
                    ON DELETE SET NULL;
            END IF;
        END $$
        """
    )

    # EvidenceManifests originally had an inline UNIQUE(interview_id).
    op.execute(
        """
        DO $$
        DECLARE constraint_name TEXT;
        BEGIN
            FOR constraint_name IN
                SELECT con.conname
                FROM pg_constraint con
                JOIN pg_class rel ON rel.oid = con.conrelid
                WHERE rel.relname = 'evidencemanifests'
                  AND con.contype = 'u'
                  AND pg_get_constraintdef(con.oid) = 'UNIQUE (interview_id)'
            LOOP
                EXECUTE format('ALTER TABLE EvidenceManifests DROP CONSTRAINT %I', constraint_name);
            END LOOP;
        END $$
        """
    )

    # SessionPerformanceAnalyses originally allowed only one row per
    # interview/mode/schema. Revisions retain immutable history instead.
    op.execute(
        """
        DO $$
        DECLARE constraint_name TEXT;
        BEGIN
            FOR constraint_name IN
                SELECT con.conname
                FROM pg_constraint con
                JOIN pg_class rel ON rel.oid = con.conrelid
                WHERE rel.relname = 'sessionperformanceanalyses'
                  AND con.contype = 'u'
                  AND pg_get_constraintdef(con.oid)
                      = 'UNIQUE (interview_id, mode, schema_version)'
            LOOP
                EXECUTE format(
                    'ALTER TABLE SessionPerformanceAnalyses DROP CONSTRAINT %I',
                    constraint_name
                );
            END LOOP;
        END $$
        """
    )
    op.execute(
        "ALTER TABLE SessionPerformanceAnalyses "
        "DROP CONSTRAINT IF EXISTS uq_session_perf_interview_mode_schema"
    )

    op.execute(
        """
        WITH ranked AS (
            SELECT manifest_id,
                   ROW_NUMBER() OVER (
                       PARTITION BY interview_id
                       ORDER BY sealed_at DESC, created_at DESC, manifest_id DESC
                   ) AS revision_no,
                   ROW_NUMBER() OVER (
                       PARTITION BY interview_id
                       ORDER BY sealed_at DESC, created_at DESC, manifest_id DESC
                   ) = 1 AS is_current
            FROM EvidenceManifests
        )
        UPDATE EvidenceManifests manifest
        SET revision_no = ranked.revision_no,
            is_current = ranked.is_current
        FROM ranked
        WHERE manifest.manifest_id = ranked.manifest_id
        """
    )
    op.execute(
        """
        WITH ranked AS (
            SELECT analysis_id,
                   ROW_NUMBER() OVER (
                       PARTITION BY interview_id, mode, schema_version
                       ORDER BY created_at DESC, analysis_id DESC
                   ) AS revision_no,
                   ROW_NUMBER() OVER (
                       PARTITION BY interview_id, mode, schema_version
                       ORDER BY created_at DESC, analysis_id DESC
                   ) = 1 AS is_current
            FROM SessionPerformanceAnalyses
        )
        UPDATE SessionPerformanceAnalyses analysis
        SET revision_no = ranked.revision_no,
            is_current = ranked.is_current
        FROM ranked
        WHERE analysis.analysis_id = ranked.analysis_id
        """
    )

    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS "
        "uq_evidence_manifest_current "
        "ON EvidenceManifests (interview_id) WHERE is_current"
    )
    op.execute("DROP INDEX IF EXISTS uq_evidence_manifest_hash")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS "
        "uq_evidence_manifest_hash_producer "
        "ON EvidenceManifests (interview_id, evidence_hash, producer_version)"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS "
        "uq_evidence_manifest_revision "
        "ON EvidenceManifests (interview_id, revision_no)"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS "
        "uq_session_performance_current "
        "ON SessionPerformanceAnalyses (interview_id, mode, schema_version) "
        "WHERE is_current"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS "
        "uq_session_performance_revision "
        "ON SessionPerformanceAnalyses "
        "(interview_id, mode, schema_version, revision_no)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_evidence_manifest_hash_producer")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_evidence_manifest_hash "
        "ON EvidenceManifests (interview_id, evidence_hash)"
    )
    op.execute("DROP INDEX IF EXISTS uq_session_performance_revision")
    op.execute("DROP INDEX IF EXISTS uq_session_performance_current")
    op.execute("DROP INDEX IF EXISTS uq_evidence_manifest_revision")
    op.execute("DROP INDEX IF EXISTS uq_evidence_manifest_current")
    op.execute(
        """
        DELETE FROM SessionPerformanceAnalyses analysis
        USING SessionPerformanceAnalyses newer
        WHERE analysis.interview_id = newer.interview_id
          AND analysis.mode = newer.mode
          AND analysis.schema_version = newer.schema_version
          AND analysis.revision_no < newer.revision_no
        """
    )
    op.execute(
        """
        DELETE FROM EvidenceManifests manifest
        USING EvidenceManifests newer
        WHERE manifest.interview_id = newer.interview_id
          AND manifest.revision_no < newer.revision_no
        """
    )
    op.execute(
        "ALTER TABLE SessionPerformanceAnalyses "
        "ADD CONSTRAINT uq_session_perf_interview_mode_schema "
        "UNIQUE (interview_id, mode, schema_version)"
    )
    op.execute("ALTER TABLE EvidenceManifests ADD CONSTRAINT uq_evidence_manifest_interview UNIQUE (interview_id)")
    op.execute("ALTER TABLE SessionPerformanceAnalyses DROP CONSTRAINT IF EXISTS fk_session_performance_supersedes")
    op.execute("ALTER TABLE EvidenceManifests DROP CONSTRAINT IF EXISTS fk_evidence_manifest_supersedes")
    for table, column in (
        ("AnalysisJobs", "producer_version"),
        ("SessionPerformanceAnalyses", "producer_version"),
        ("SessionPerformanceAnalyses", "supersedes_analysis_id"),
        ("SessionPerformanceAnalyses", "is_current"),
        ("SessionPerformanceAnalyses", "revision_no"),
        ("EvidenceManifests", "producer_version"),
        ("EvidenceManifests", "supersedes_manifest_id"),
        ("EvidenceManifests", "is_current"),
        ("EvidenceManifests", "revision_no"),
    ):
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS {column}")
