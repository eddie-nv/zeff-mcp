"""ingest_records: per-user food acquisition events

Revision ID: d2c69ebcdc9b
Revises: 340484fda9f2
Create Date: 2026-05-02 08:01:00

A single ingest record represents the user acquiring some quantity of a
food at a point in time (typically receipt-derived; for v1 these are
inserted directly via fixtures).

Index on (user_id, acquired_at DESC) covers the pantry computation and
consumption history queries that drive M8 / M9.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d2c69ebcdc9b"
down_revision: Union[str, None] = "340484fda9f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # gen_random_uuid() lives in pgcrypto on Postgres < 13. Postgres 13+
    # has it built-in but creating the extension is safe and idempotent.
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.create_table(
        "ingest_records",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column(
            "node_id",
            sa.Text(),
            sa.ForeignKey("nodes.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("acquired_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("quantity", sa.Float(), nullable=True),
        sa.Column("source", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "quantity IS NULL OR quantity > 0",
            name="ingest_records_quantity_check",
        ),
    )
    op.create_index(
        "ix_ingest_records_user_acquired",
        "ingest_records",
        ["user_id", sa.text("acquired_at DESC")],
    )
    op.create_index("ix_ingest_records_node_id", "ingest_records", ["node_id"])


def downgrade() -> None:
    op.drop_index("ix_ingest_records_node_id", table_name="ingest_records")
    op.drop_index("ix_ingest_records_user_acquired", table_name="ingest_records")
    op.drop_table("ingest_records")
