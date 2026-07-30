"""Keep technical round state consistent with terminal interview state.

Revision ID: 019_terminal_rounds
Revises: 018_performance_revisions
Create Date: 2026-07-16
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "019_terminal_rounds"
down_revision: Union[str, None] = "018_performance_revisions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE TechnicalInterviewRounds round
        SET status = CASE
                WHEN interview.status = 'cancelled' THEN 'cancelled'
                WHEN interview.completion_kind = 'deadline' THEN 'expired'
                ELSE 'completed'
            END,
            completed_at = COALESCE(
                round.completed_at,
                interview.completed_at,
                NOW()
            )
        FROM Interviews interview
        WHERE round.interview_id = interview.interview_id
          AND round.user_id = interview.user_id
          AND interview.status IN (
              'analysis_pending',
              'analysis_running',
              'completed',
              'partial',
              'failed',
              'cancelled'
          )
          AND round.status NOT IN (
              'submitted',
              'completed',
              'expired',
              'cancelled'
          )
        """
    )


def downgrade() -> None:
    # Terminal-round repair is intentionally irreversible: reopening historical
    # rounds would recreate an invalid parent/child lifecycle combination.
    pass
