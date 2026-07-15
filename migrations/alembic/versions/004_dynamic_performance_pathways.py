"""Dynamic performance analyses and mode-specific improve missions.

Revision ID: 004_dynamic_performance_pathways
Revises: 003_technical_source_code
Create Date: 2026-07-05
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "004_dynamic_performance_pathways"
down_revision: Union[str, None] = "003_technical_source_code"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())
    mission_columns = (
        {column["name"] for column in inspector.get_columns("improvementmissions")}
        if "improvementmissions" in existing_tables
        else set()
    )
    if (
        {"sessionperformanceanalyses", "technicalreasoningevidence"}.issubset(existing_tables)
        and {
            "mode", "source_analysis_id", "weakness_key", "weakness_type",
            "prediction_json", "validation_status",
            "validated_by_interview_id",
        }.issubset(mission_columns)
    ):
        op.execute(
            "INSERT INTO SchemaMigrations (migration_id) "
            "VALUES ('004_dynamic_performance_pathways') "
            "ON CONFLICT (migration_id) DO NOTHING"
        )
        return

    op.create_table(
        "sessionperformanceanalyses",
        sa.Column("analysis_id", sa.String(length=64), primary_key=True),
        sa.Column("user_id", sa.String(length=64), sa.ForeignKey("userinfo.user_id", ondelete="CASCADE"), nullable=False),
        sa.Column("interview_id", sa.String(length=64), sa.ForeignKey("interviews.interview_id", ondelete="CASCADE"), nullable=False),
        sa.Column("mode", sa.String(length=20), nullable=False),
        sa.Column("schema_version", sa.String(length=40), nullable=False),
        sa.Column("evidence_hash", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="ready"),
        sa.Column("model", sa.String(length=80), nullable=True),
        sa.Column("analysis_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("evidence_index_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("overall_score", sa.Numeric(5, 2), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cached_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("estimated_cost", sa.Numeric(10, 6), nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
    )
    op.create_index("idx_session_perf_user_mode", "sessionperformanceanalyses", ["user_id", "mode", "created_at"])
    op.create_unique_constraint(
        "uq_session_perf_interview_mode_schema",
        "sessionperformanceanalyses",
        ["interview_id", "mode", "schema_version"],
    )

    op.create_table(
        "technicalreasoningevidence",
        sa.Column("evidence_id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.String(length=64), sa.ForeignKey("userinfo.user_id", ondelete="CASCADE"), nullable=False),
        sa.Column("interview_id", sa.String(length=64), sa.ForeignKey("interviews.interview_id", ondelete="CASCADE"), nullable=False),
        sa.Column("round_id", sa.String(length=64), sa.ForeignKey("technicalinterviewrounds.round_id", ondelete="CASCADE"), nullable=True),
        sa.Column("evidence_type", sa.String(length=50), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
    )
    op.create_index("idx_technical_reasoning_round", "technicalreasoningevidence", ["round_id", "created_at"])
    op.create_index("idx_technical_reasoning_user", "technicalreasoningevidence", ["user_id", "created_at"])

    op.add_column("improvementmissions", sa.Column("mode", sa.String(length=20), nullable=False, server_default="mock"))
    op.add_column("improvementmissions", sa.Column("source_analysis_id", sa.String(length=64), nullable=True))
    op.add_column("improvementmissions", sa.Column("weakness_key", sa.String(length=160), nullable=True))
    op.add_column("improvementmissions", sa.Column("weakness_type", sa.String(length=80), nullable=True))
    op.add_column("improvementmissions", sa.Column("prediction_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")))
    op.add_column("improvementmissions", sa.Column("validation_status", sa.String(length=40), nullable=False, server_default="pending"))
    op.add_column("improvementmissions", sa.Column("validated_by_interview_id", sa.String(length=64), nullable=True))
    op.execute("DROP INDEX IF EXISTS idx_improvement_missions_one_active")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_improvement_missions_one_active_per_mode "
        "ON improvementmissions (user_id, mode) WHERE status = 'active'"
    )
    op.create_index("idx_improvement_missions_user_mode_status", "improvementmissions", ["user_id", "mode", "status", "created_at"])

    op.execute(
        "INSERT INTO SchemaMigrations (migration_id) "
        "VALUES ('004_dynamic_performance_pathways') ON CONFLICT (migration_id) DO NOTHING"
    )


def downgrade() -> None:
    op.execute("DELETE FROM SchemaMigrations WHERE migration_id = '004_dynamic_performance_pathways'")
    op.drop_index("idx_improvement_missions_user_mode_status", table_name="improvementmissions")
    op.execute("DROP INDEX IF EXISTS idx_improvement_missions_one_active_per_mode")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_improvement_missions_one_active "
        "ON improvementmissions (user_id) WHERE status = 'active'"
    )
    for column in [
        "validated_by_interview_id",
        "validation_status",
        "prediction_json",
        "weakness_type",
        "weakness_key",
        "source_analysis_id",
        "mode",
    ]:
        op.drop_column("improvementmissions", column)
    op.drop_index("idx_technical_reasoning_user", table_name="technicalreasoningevidence")
    op.drop_index("idx_technical_reasoning_round", table_name="technicalreasoningevidence")
    op.drop_table("technicalreasoningevidence")
    op.drop_constraint("uq_session_perf_interview_mode_schema", "sessionperformanceanalyses", type_="unique")
    op.drop_index("idx_session_perf_user_mode", table_name="sessionperformanceanalyses")
    op.drop_table("sessionperformanceanalyses")
