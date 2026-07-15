"""Durable Improve missions, roadmap state, and attempt history.

Revision ID: 002_improve_missions
Revises: 001_baseline
Create Date: 2026-07-03
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "002_improve_missions"
down_revision: Union[str, None] = "001_baseline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())
    required_tables = {
        "improvementmissions",
        "improvementmissionskills",
        "improvementroadmapnodes",
        "improvementattemptsessions",
        "improvementmissionevents",
    }
    generated_columns = (
        {column["name"] for column in inspector.get_columns("generatedexercises")}
        if "generatedexercises" in existing_tables
        else set()
    )
    attempt_columns = (
        {column["name"] for column in inspector.get_columns("exerciseattempts")}
        if "exerciseattempts" in existing_tables
        else set()
    )
    if (
        required_tables.issubset(existing_tables)
        and {
            "mission_id", "mission_skill_id", "roadmap_node_id",
            "activity_type", "variation_group", "is_checkpoint",
            "activity_metadata",
        }.issubset(generated_columns)
        and {
            "attempt_session_id", "idempotency_key", "mission_id",
            "mission_skill_id", "roadmap_node_id", "activity_type",
            "is_checkpoint", "condition_results", "passed_conditions",
            "failed_conditions", "score_components",
        }.issubset(attempt_columns)
    ):
        op.execute(
            "INSERT INTO SchemaMigrations (migration_id) "
            "VALUES ('002_improve_missions') "
            "ON CONFLICT (migration_id) DO NOTHING"
        )
        return

    op.create_table(
        "improvementmissions",
        sa.Column("mission_id", sa.String(length=64), primary_key=True),
        sa.Column("user_id", sa.String(length=64), sa.ForeignKey("userinfo.user_id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_interview_id", sa.String(length=64), sa.ForeignKey("interviews.interview_id", ondelete="SET NULL"), nullable=True),
        sa.Column("mission_type", sa.String(length=80), nullable=False),
        sa.Column("title", sa.String(length=180), nullable=False),
        sa.Column("assignment_reason", sa.Text(), nullable=False),
        sa.Column("diagnosis_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("priority_score", sa.Numeric(5, 2), nullable=False, server_default="0"),
        sa.Column("priority_factors", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("baseline_readiness", sa.Numeric(5, 2), nullable=False, server_default="0"),
        sa.Column("current_readiness", sa.Numeric(5, 2), nullable=False, server_default="0"),
        sa.Column("target_readiness", sa.Numeric(5, 2), nullable=False, server_default="75"),
        sa.Column("progress_percent", sa.Numeric(5, 2), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
    )
    op.create_index("idx_improvement_missions_user_status", "improvementmissions", ["user_id", "status", "created_at"])
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_improvement_missions_one_active "
        "ON improvementmissions (user_id) WHERE status = 'active'"
    )

    op.create_table(
        "improvementmissionskills",
        sa.Column("mission_skill_id", sa.String(length=64), primary_key=True),
        sa.Column("mission_id", sa.String(length=64), sa.ForeignKey("improvementmissions.mission_id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.String(length=64), sa.ForeignKey("userinfo.user_id", ondelete="CASCADE"), nullable=False),
        sa.Column("skill_key", sa.String(length=120), nullable=False),
        sa.Column("label", sa.String(length=180), nullable=False),
        sa.Column("category", sa.String(length=50), nullable=False),
        sa.Column("baseline_score", sa.Numeric(5, 2), nullable=False, server_default="0"),
        sa.Column("latest_score", sa.Numeric(5, 2), nullable=False, server_default="0"),
        sa.Column("target_score", sa.Numeric(5, 2), nullable=False, server_default="75"),
        sa.Column("role_weight", sa.Numeric(5, 2), nullable=False, server_default="1"),
        sa.Column("mastery_status", sa.String(length=40), nullable=False, server_default="untrained"),
        sa.Column("evidence_summary", sa.Text(), nullable=True),
        sa.Column("criteria_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("verified_at", sa.DateTime(), nullable=True),
        sa.Column("needs_reinforcement_at", sa.DateTime(), nullable=True),
    )
    op.create_index("idx_improvement_skills_mission", "improvementmissionskills", ["mission_id", "skill_key"])
    op.create_index("idx_improvement_skills_user_status", "improvementmissionskills", ["user_id", "mastery_status", "updated_at"])

    op.create_table(
        "improvementroadmapnodes",
        sa.Column("roadmap_node_id", sa.String(length=64), primary_key=True),
        sa.Column("mission_id", sa.String(length=64), sa.ForeignKey("improvementmissions.mission_id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.String(length=64), sa.ForeignKey("userinfo.user_id", ondelete="CASCADE"), nullable=False),
        sa.Column("mission_skill_id", sa.String(length=64), sa.ForeignKey("improvementmissionskills.mission_skill_id", ondelete="CASCADE"), nullable=True),
        sa.Column("exercise_id", sa.String(length=64), sa.ForeignKey("generatedexercises.exercise_id", ondelete="SET NULL"), nullable=True),
        sa.Column("recovery_of_node_id", sa.String(length=64), nullable=True),
        sa.Column("order_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("title", sa.String(length=180), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("activity_type", sa.String(length=60), nullable=False),
        sa.Column("availability_status", sa.String(length=30), nullable=False, server_default="locked"),
        sa.Column("attempt_status", sa.String(length=30), nullable=False, server_default="draft"),
        sa.Column("result_status", sa.String(length=30), nullable=False, server_default="not_attempted"),
        sa.Column("mastery_status", sa.String(length=40), nullable=False, server_default="untrained"),
        sa.Column("estimated_minutes", sa.Integer(), nullable=False, server_default="4"),
        sa.Column("expected_result", sa.Text(), nullable=True),
        sa.Column("evidence_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
    )
    op.create_index("idx_improvement_nodes_mission_order", "improvementroadmapnodes", ["mission_id", "order_index"])
    op.create_index("idx_improvement_nodes_user_availability", "improvementroadmapnodes", ["user_id", "availability_status", "updated_at"])

    op.create_table(
        "improvementattemptsessions",
        sa.Column("attempt_session_id", sa.String(length=64), primary_key=True),
        sa.Column("user_id", sa.String(length=64), sa.ForeignKey("userinfo.user_id", ondelete="CASCADE"), nullable=False),
        sa.Column("mission_id", sa.String(length=64), sa.ForeignKey("improvementmissions.mission_id", ondelete="CASCADE"), nullable=False),
        sa.Column("roadmap_node_id", sa.String(length=64), sa.ForeignKey("improvementroadmapnodes.roadmap_node_id", ondelete="CASCADE"), nullable=False),
        sa.Column("exercise_id", sa.String(length=64), sa.ForeignKey("generatedexercises.exercise_id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="draft"),
        sa.Column("draft_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("idempotency_key", sa.String(length=120), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
    )
    op.create_index("idx_improvement_attempt_sessions_user", "improvementattemptsessions", ["user_id", "status", "updated_at"])
    op.create_unique_constraint("uq_improvement_attempt_session_idempotency", "improvementattemptsessions", ["user_id", "exercise_id", "idempotency_key"])

    op.create_table(
        "improvementmissionevents",
        sa.Column("event_id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.String(length=64), sa.ForeignKey("userinfo.user_id", ondelete="CASCADE"), nullable=False),
        sa.Column("mission_id", sa.String(length=64), sa.ForeignKey("improvementmissions.mission_id", ondelete="CASCADE"), nullable=True),
        sa.Column("roadmap_node_id", sa.String(length=64), nullable=True),
        sa.Column("exercise_id", sa.String(length=64), nullable=True),
        sa.Column("attempt_id", sa.String(length=64), nullable=True),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
    )
    op.create_index("idx_improvement_events_user_created", "improvementmissionevents", ["user_id", "created_at"])
    op.create_index("idx_improvement_events_mission_created", "improvementmissionevents", ["mission_id", "created_at"])

    op.add_column("generatedexercises", sa.Column("mission_id", sa.String(length=64), nullable=True))
    op.add_column("generatedexercises", sa.Column("mission_skill_id", sa.String(length=64), nullable=True))
    op.add_column("generatedexercises", sa.Column("roadmap_node_id", sa.String(length=64), nullable=True))
    op.add_column("generatedexercises", sa.Column("activity_type", sa.String(length=60), nullable=True))
    op.add_column("generatedexercises", sa.Column("variation_group", sa.String(length=80), nullable=True))
    op.add_column("generatedexercises", sa.Column("is_checkpoint", sa.Boolean(), nullable=False, server_default=sa.text("FALSE")))
    op.add_column("generatedexercises", sa.Column("activity_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")))
    op.create_index("idx_generated_exercises_mission", "generatedexercises", ["mission_id", "roadmap_node_id"])

    op.add_column("exerciseattempts", sa.Column("attempt_session_id", sa.String(length=64), nullable=True))
    op.add_column("exerciseattempts", sa.Column("idempotency_key", sa.String(length=120), nullable=True))
    op.add_column("exerciseattempts", sa.Column("mission_id", sa.String(length=64), nullable=True))
    op.add_column("exerciseattempts", sa.Column("mission_skill_id", sa.String(length=64), nullable=True))
    op.add_column("exerciseattempts", sa.Column("roadmap_node_id", sa.String(length=64), nullable=True))
    op.add_column("exerciseattempts", sa.Column("activity_type", sa.String(length=60), nullable=True))
    op.add_column("exerciseattempts", sa.Column("is_checkpoint", sa.Boolean(), nullable=False, server_default=sa.text("FALSE")))
    op.add_column("exerciseattempts", sa.Column("condition_results", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")))
    op.add_column("exerciseattempts", sa.Column("passed_conditions", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")))
    op.add_column("exerciseattempts", sa.Column("failed_conditions", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")))
    op.add_column("exerciseattempts", sa.Column("score_components", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")))
    op.create_index("idx_exercise_attempts_mission", "exerciseattempts", ["mission_id", "roadmap_node_id", "created_at"])
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_exercise_attempts_idempotency "
        "ON exerciseattempts (user_id, exercise_id, idempotency_key) WHERE idempotency_key IS NOT NULL"
    )

    op.execute(
        "INSERT INTO SchemaMigrations (migration_id) "
        "VALUES ('002_improve_missions') ON CONFLICT (migration_id) DO NOTHING"
    )


def downgrade() -> None:
    op.execute("DELETE FROM SchemaMigrations WHERE migration_id = '002_improve_missions'")
    op.execute("DROP INDEX IF EXISTS uq_exercise_attempts_idempotency")
    op.drop_index("idx_exercise_attempts_mission", table_name="exerciseattempts")
    for column in [
        "score_components",
        "failed_conditions",
        "passed_conditions",
        "condition_results",
        "is_checkpoint",
        "activity_type",
        "roadmap_node_id",
        "mission_skill_id",
        "mission_id",
        "idempotency_key",
        "attempt_session_id",
    ]:
        op.drop_column("exerciseattempts", column)

    op.drop_index("idx_generated_exercises_mission", table_name="generatedexercises")
    for column in [
        "activity_metadata",
        "is_checkpoint",
        "variation_group",
        "activity_type",
        "roadmap_node_id",
        "mission_skill_id",
        "mission_id",
    ]:
        op.drop_column("generatedexercises", column)

    op.drop_index("idx_improvement_events_mission_created", table_name="improvementmissionevents")
    op.drop_index("idx_improvement_events_user_created", table_name="improvementmissionevents")
    op.drop_table("improvementmissionevents")
    op.drop_constraint("uq_improvement_attempt_session_idempotency", "improvementattemptsessions", type_="unique")
    op.drop_index("idx_improvement_attempt_sessions_user", table_name="improvementattemptsessions")
    op.drop_table("improvementattemptsessions")
    op.drop_index("idx_improvement_nodes_user_availability", table_name="improvementroadmapnodes")
    op.drop_index("idx_improvement_nodes_mission_order", table_name="improvementroadmapnodes")
    op.drop_table("improvementroadmapnodes")
    op.drop_index("idx_improvement_skills_user_status", table_name="improvementmissionskills")
    op.drop_index("idx_improvement_skills_mission", table_name="improvementmissionskills")
    op.drop_table("improvementmissionskills")
    op.execute("DROP INDEX IF EXISTS idx_improvement_missions_one_active")
    op.drop_index("idx_improvement_missions_user_status", table_name="improvementmissions")
    op.drop_table("improvementmissions")
