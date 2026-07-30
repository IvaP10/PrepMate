"""Allow resume versions to be removed without erasing interview evidence.

Revision ID: 020_resume_version_detach
Revises: 019_terminal_rounds
Create Date: 2026-07-18
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "020_resume_version_detach"
down_revision: Union[str, None] = "019_terminal_rounds"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_RESUME_REFERENCES = (
    ("Interviews", "fk_interviews_resume_version"),
    ("InterviewBlueprints", "interviewblueprints_resume_id_fkey"),
    ("AttemptContextSnapshots", "attemptcontextsnapshots_resume_id_fkey"),
)


def _replace_constraints(delete_action: str) -> None:
    for table, constraint in _RESUME_REFERENCES:
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {constraint}")
        op.execute(
            f"ALTER TABLE {table} ADD CONSTRAINT {constraint} "
            f"FOREIGN KEY (resume_id) REFERENCES ResumeVersions(resume_id) ON DELETE {delete_action}"
        )


def upgrade() -> None:
    # The encrypted snapshot payload remains the durable historical evidence;
    # resume_id becomes an optional pointer to the user's current saved asset.
    op.execute("ALTER TABLE AttemptContextSnapshots ALTER COLUMN resume_id DROP NOT NULL")
    _replace_constraints("SET NULL")
    op.execute(
        """
        CREATE OR REPLACE FUNCTION enforce_interview_context_immutability()
        RETURNS TRIGGER AS $$
        BEGIN
            IF OLD.resume_id IS NOT NULL
               AND NEW.resume_id IS NOT NULL
               AND NEW.resume_id IS DISTINCT FROM OLD.resume_id THEN
                RAISE EXCEPTION 'interview resume_id is immutable once assigned';
            END IF;
            IF OLD.job_profile_id IS NOT NULL
               AND NEW.job_profile_id IS NOT NULL
               AND NEW.job_profile_id IS DISTINCT FROM OLD.job_profile_id THEN
                RAISE EXCEPTION 'interview job_profile_id is immutable once assigned';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )


def downgrade() -> None:
    _replace_constraints("RESTRICT")
    op.execute(
        """
        CREATE OR REPLACE FUNCTION enforce_interview_context_immutability()
        RETURNS TRIGGER AS $$
        BEGIN
            IF OLD.resume_id IS NOT NULL AND NEW.resume_id IS DISTINCT FROM OLD.resume_id THEN
                RAISE EXCEPTION 'interview resume_id is immutable once assigned';
            END IF;
            IF OLD.job_profile_id IS NOT NULL
               AND NEW.job_profile_id IS NOT NULL
               AND NEW.job_profile_id IS DISTINCT FROM OLD.job_profile_id THEN
                RAISE EXCEPTION 'interview job_profile_id is immutable once assigned';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    # Keep the snapshot column nullable on downgrade because resume rows deleted
    # while this revision was active cannot be reconstructed safely.
