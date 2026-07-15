"""Persist full technical source for evidence-backed reports.

Revision ID: 003_technical_source_code
Revises: 002_improve_missions
Create Date: 2026-07-03
"""
from typing import Sequence, Union

from alembic import op


revision: str = "003_technical_source_code"
down_revision: Union[str, None] = "002_improve_missions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE TechnicalRunEvents ADD COLUMN IF NOT EXISTS source_code TEXT")
    op.execute("ALTER TABLE TechnicalCodeSnapshots ADD COLUMN IF NOT EXISTS source_code TEXT")
    op.execute("ALTER TABLE TechnicalSubmissions ADD COLUMN IF NOT EXISTS source_code TEXT")
    op.execute(
        "INSERT INTO SchemaMigrations (migration_id) "
        "VALUES ('003_technical_source_code') ON CONFLICT (migration_id) DO NOTHING"
    )


def downgrade() -> None:
    op.execute("DELETE FROM SchemaMigrations WHERE migration_id = '003_technical_source_code'")
    op.drop_column("TechnicalSubmissions", "source_code")
    op.drop_column("TechnicalCodeSnapshots", "source_code")
    op.drop_column("TechnicalRunEvents", "source_code")
