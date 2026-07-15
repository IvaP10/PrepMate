"""Reject late inserts and edits to sealed candidate evidence.

Revision ID: 014_sealed_evidence_guards
Revises: 013_report_retry_state
Create Date: 2026-07-14
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "014_sealed_evidence_guards"
down_revision: Union[str, None] = "013_report_retry_state"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


DIRECT_TABLES = (
    "InterviewQuestions",
    "InterviewResponses",
    "ResponseAssessments",
    "TechnicalSubmissions",
    "TechnicalCodeSnapshots",
    "TechnicalReasoningEvidence",
    "AttemptIntegrityEvents",
    "AntiCheatEvents",
    "ClientBodyLanguageMetrics",
    "ProctoringFlags",
)


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION reject_sealed_evidence_mutation()
        RETURNS TRIGGER AS $$
        DECLARE
            target_interview_id VARCHAR(64);
        BEGIN
            target_interview_id := COALESCE(
                to_jsonb(NEW)->>'interview_id',
                to_jsonb(OLD)->>'interview_id'
            );
            IF target_interview_id IS NULL AND TG_TABLE_NAME = 'technicalrunevents' THEN
                SELECT interview_id INTO target_interview_id
                FROM TechnicalInterviewRounds
                WHERE round_id = COALESCE(NEW.round_id, OLD.round_id);
            END IF;
            IF target_interview_id IS NOT NULL AND EXISTS (
                SELECT 1 FROM Interviews
                WHERE interview_id = target_interview_id AND evidence_sealed_at IS NOT NULL
            ) THEN
                RAISE EXCEPTION 'candidate evidence is sealed for interview %', target_interview_id
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    for table in DIRECT_TABLES:
        trigger = f"trg_reject_sealed_{table.lower()}"
        op.execute(f"DROP TRIGGER IF EXISTS {trigger} ON {table}")
        op.execute(
            f"CREATE TRIGGER {trigger} BEFORE INSERT OR UPDATE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION reject_sealed_evidence_mutation()"
        )
    op.execute("DROP TRIGGER IF EXISTS trg_reject_sealed_technicalrunevents ON TechnicalRunEvents")
    op.execute(
        "CREATE TRIGGER trg_reject_sealed_technicalrunevents "
        "BEFORE INSERT OR UPDATE ON TechnicalRunEvents "
        "FOR EACH ROW EXECUTE FUNCTION reject_sealed_evidence_mutation()"
    )


def downgrade() -> None:
    for table in (*DIRECT_TABLES, "TechnicalRunEvents"):
        op.execute(f"DROP TRIGGER IF EXISTS trg_reject_sealed_{table.lower()} ON {table}")
    op.execute("DROP FUNCTION IF EXISTS reject_sealed_evidence_mutation()")
