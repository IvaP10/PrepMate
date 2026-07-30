"""Allow saved job profiles to be removed without erasing interview history.

Revision ID: 016_reusable_job_profiles
Revises: 015_improve_graph_invariants
Create Date: 2026-07-15
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "016_reusable_job_profiles"
down_revision: Union[str, None] = "015_improve_graph_invariants"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_REFERENCES = (
    ("Interviews", "fk_interviews_job_profile"),
    ("InterviewBlueprints", "interviewblueprints_job_profile_id_fkey"),
    ("AttemptContextSnapshots", "attemptcontextsnapshots_job_profile_id_fkey"),
)


def _replace_constraints(delete_action: str) -> None:
    for table, constraint in _REFERENCES:
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {constraint}")
        op.execute(
            f"ALTER TABLE {table} ADD CONSTRAINT {constraint} "
            f"FOREIGN KEY (job_profile_id) REFERENCES JobProfiles(profile_id) ON DELETE {delete_action}"
        )


def upgrade() -> None:
    _replace_constraints("SET NULL")


def downgrade() -> None:
    _replace_constraints("RESTRICT")
