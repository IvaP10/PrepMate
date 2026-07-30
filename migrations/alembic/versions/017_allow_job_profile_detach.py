"""Allow saved job profiles to detach from immutable interview history.

Revision ID: 017_allow_job_profile_detach
Revises: 016_reusable_job_profiles
Create Date: 2026-07-16
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "017_allow_job_profile_detach"
down_revision: Union[str, None] = "016_reusable_job_profiles"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
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


def downgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION enforce_interview_context_immutability()
        RETURNS TRIGGER AS $$
        BEGIN
            IF OLD.resume_id IS NOT NULL AND NEW.resume_id IS DISTINCT FROM OLD.resume_id THEN
                RAISE EXCEPTION 'interview resume_id is immutable once assigned';
            END IF;
            IF OLD.job_profile_id IS NOT NULL AND NEW.job_profile_id IS DISTINCT FROM OLD.job_profile_id THEN
                RAISE EXCEPTION 'interview job_profile_id is immutable once assigned';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
