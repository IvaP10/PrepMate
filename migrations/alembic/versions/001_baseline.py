"""Create the reproducible pre-feature baseline or adopt a legacy database.

Fresh databases are created from the frozen ``base_schema.sql`` snapshot.  A
legacy database that already contains the core tables is adopted in place and
then upgraded by the later additive revisions.  Production never depends on
runtime DDL.

Revision ID: 001_baseline
Revises: None
Create Date: 2026-06-24
"""
from typing import Sequence, Union
from pathlib import Path

from alembic import op
import sqlalchemy as sa

revision: str = "001_baseline"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    login_table = bind.execute(sa.text("SELECT to_regclass('public.login')")).scalar()
    if login_table is None:
        schema_path = Path(__file__).resolve().parents[1] / "base_schema.sql"
        script = schema_path.read_text(encoding="utf-8")
        raw_connection = bind.connection
        cursor = raw_connection.cursor()
        try:
            cursor.execute(script)
        finally:
            cursor.close()

    op.execute(
        "CREATE TABLE IF NOT EXISTS SchemaMigrations ("
        "migration_id VARCHAR(120) PRIMARY KEY, "
        "applied_at TIMESTAMP NOT NULL DEFAULT NOW())"
    )
    op.execute(
        "ALTER TABLE Interviews ADD COLUMN IF NOT EXISTS llm_cost_usd "
        "NUMERIC(10,6) NOT NULL DEFAULT 0"
    )
    op.execute(
        "INSERT INTO SchemaMigrations (migration_id) VALUES "
        "('001_baseline_alembic'), ('001_launch_config') "
        "ON CONFLICT (migration_id) DO NOTHING"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE Interviews DROP COLUMN IF EXISTS llm_cost_usd")
    op.execute("DELETE FROM SchemaMigrations WHERE migration_id = '001_baseline_alembic'")
