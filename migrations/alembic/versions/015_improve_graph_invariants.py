"""Enforce a single current node for each Improve mission.

Revision ID: 015_improve_graph_invariants
Revises: 014_sealed_evidence_guards
Create Date: 2026-07-14
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "015_improve_graph_invariants"
down_revision: Union[str, None] = "014_sealed_evidence_guards"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Preserve the earliest current action if historical data predates the
    # invariant. Later duplicates remain durable but return to the locked state.
    op.execute(
        """
        WITH ranked AS (
            SELECT roadmap_node_id,
                   ROW_NUMBER() OVER (
                       PARTITION BY mission_id
                       ORDER BY order_index, created_at, roadmap_node_id
                   ) AS current_rank
            FROM ImprovementRoadmapNodes
            WHERE availability_status = 'current'
        )
        UPDATE ImprovementRoadmapNodes node
        SET availability_status = 'locked', updated_at = NOW()
        FROM ranked
        WHERE node.roadmap_node_id = ranked.roadmap_node_id
          AND ranked.current_rank > 1
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS "
        "uq_improvement_nodes_one_current_per_mission "
        "ON ImprovementRoadmapNodes (mission_id) "
        "WHERE availability_status = 'current'"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_improvement_nodes_one_current_per_mission")
