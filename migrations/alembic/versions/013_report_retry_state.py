"""Track bounded operator retries for immutable analysis jobs.

Revision ID: 013_report_retry_state
Revises: 012_report_evidence_truth
Create Date: 2026-07-14
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "013_report_retry_state"
down_revision: Union[str, None] = "012_report_evidence_truth"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE AnalysisJobs ADD COLUMN IF NOT EXISTS manual_retry_count INTEGER NOT NULL DEFAULT 0")


def downgrade() -> None:
    op.execute("ALTER TABLE AnalysisJobs DROP COLUMN IF EXISTS manual_retry_count")
