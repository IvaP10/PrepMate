"""Persist Improve attempt deadlines and paused time.

Revision ID: 008_improve_attempt_deadlines
Revises: 007_schema_contract_repairs
Create Date: 2026-07-12
"""

from typing import Sequence, Union

from alembic import op


revision: str = "008_improve_attempt_deadlines"
down_revision: Union[str, None] = "007_schema_contract_repairs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE ImprovementMissions "
        "ALTER COLUMN validation_status SET DEFAULT 'active'"
    )
    op.execute(
        "UPDATE ImprovementMissions SET validation_status = 'active' "
        "WHERE status = 'active' AND validation_status = 'pending'"
    )
    op.execute(
        "ALTER TABLE ImprovementAttemptSessions "
        "ADD COLUMN IF NOT EXISTS deadline_at TIMESTAMP"
    )
    op.execute(
        "ALTER TABLE ImprovementAttemptSessions "
        "ADD COLUMN IF NOT EXISTS remaining_seconds INTEGER"
    )
    op.execute(
        """
        UPDATE ImprovementAttemptSessions session
        SET remaining_seconds = GREATEST(
            0,
            COALESCE(
                exercise.timer_seconds,
                CASE
                    WHEN exercise.prompt->>'timer_seconds' ~ '^[0-9]+$'
                    THEN (exercise.prompt->>'timer_seconds')::INTEGER
                    ELSE NULL
                END,
                node.estimated_minutes * 60
            )
        )
        FROM GeneratedExercises exercise
        JOIN ImprovementRoadmapNodes node
          ON node.roadmap_node_id = exercise.roadmap_node_id
        WHERE session.exercise_id = exercise.exercise_id
          AND session.remaining_seconds IS NULL
        """
    )
    op.execute(
        """
        UPDATE ImprovementAttemptSessions
        SET deadline_at = LEAST(
                COALESCE(expires_at, NOW() + INTERVAL '24 hours'),
                COALESCE(updated_at, created_at, NOW())
                    + (COALESCE(remaining_seconds, 0) * INTERVAL '1 second')
            )
        WHERE status = 'in_progress'
          AND deadline_at IS NULL
          AND remaining_seconds IS NOT NULL
        """
    )
    op.execute(
        """
        UPDATE ImprovementAttemptSessions
        SET remaining_seconds = GREATEST(
                0,
                CEIL(EXTRACT(EPOCH FROM (deadline_at - NOW())))::INTEGER
            ),
            status = CASE WHEN deadline_at <= NOW() THEN 'abandoned' ELSE status END,
            deadline_at = CASE WHEN deadline_at <= NOW() THEN NULL ELSE deadline_at END
        WHERE deadline_at IS NOT NULL
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_improve_attempt_sessions_deadline "
        "ON ImprovementAttemptSessions (user_id, status, expires_at, deadline_at)"
    )
    op.execute(
        "INSERT INTO SchemaMigrations (migration_id) "
        "VALUES ('008_improve_attempt_deadlines') ON CONFLICT (migration_id) DO NOTHING"
    )


def downgrade() -> None:
    op.execute("DELETE FROM SchemaMigrations WHERE migration_id = '008_improve_attempt_deadlines'")
    op.execute("DROP INDEX IF EXISTS idx_improve_attempt_sessions_deadline")
    op.execute("ALTER TABLE ImprovementAttemptSessions DROP COLUMN IF EXISTS remaining_seconds")
    op.execute("ALTER TABLE ImprovementAttemptSessions DROP COLUMN IF EXISTS deadline_at")
    op.execute(
        "ALTER TABLE ImprovementMissions "
        "ALTER COLUMN validation_status SET DEFAULT 'pending'"
    )
