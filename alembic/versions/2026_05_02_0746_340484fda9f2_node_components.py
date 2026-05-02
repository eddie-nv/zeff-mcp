"""node_components: composite -> component edges

Revision ID: 340484fda9f2
Revises: a1f3c0d4e1b2
Create Date: 2026-05-02 07:46:00

A composite food (frozen pizza, lasagna, sandwich, soup) decomposes into
one or more primitive components, each with a gram weight per serving and
a position. `is_primary` flags the dominant component for stat rollups
(e.g., "primary protein in this dish is chicken").

CASCADE on the composite side so deleting a composite cleans up its
recipe; RESTRICT on the component side so a primitive cannot be removed
while a composite still references it (forces an explicit edit first).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "340484fda9f2"
down_revision: Union[str, None] = "a1f3c0d4e1b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "node_components",
        sa.Column(
            "composite_id",
            sa.Text(),
            sa.ForeignKey("nodes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "component_id",
            sa.Text(),
            sa.ForeignKey("nodes.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("grams_per_serving", sa.Float(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.PrimaryKeyConstraint("composite_id", "component_id"),
        sa.CheckConstraint(
            "grams_per_serving IS NULL OR grams_per_serving >= 0",
            name="node_components_grams_check",
        ),
    )
    op.create_index(
        "ix_node_components_component_id", "node_components", ["component_id"]
    )
    # Partial unique index: at most one is_primary=true per composite.
    op.execute(
        "CREATE UNIQUE INDEX ix_node_components_one_primary "
        "ON node_components (composite_id) WHERE is_primary"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_node_components_one_primary")
    op.drop_index("ix_node_components_component_id", table_name="node_components")
    op.drop_table("node_components")
