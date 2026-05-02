"""initial schema: nodes, node_facets, node_external_ids

Revision ID: a1f3c0d4e1b2
Revises:
Create Date: 2026-05-02 00:00:00

Creates the v1 taxonomy tables described in DESIGN.md, plus the indexes the
search and facet-query paths will use:

  - btree on nodes.parent_id (tree traversal)
  - GIN trigram on nodes.pref_label (fuzzy + exact lookup)
  - GIN trigram on a STORED generated column joining alt_labels to text
  - GIN on node_facets.facet_value (JSONB containment queries)

The pg_trgm extension is created here so the trigram indexes can attach.

facet_key is constrained to the v1 facet set; expanding it is a one-line
migration, but tightening it after typos pollute the table is painful.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a1f3c0d4e1b2"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.create_table(
        "nodes",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("pref_label", sa.Text(), nullable=False),
        sa.Column("alt_labels", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column(
            "parent_id",
            sa.Text(),
            sa.ForeignKey("nodes.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'active'")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "type IN ('primitive', 'composite', 'category')",
            name="nodes_type_check",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'pending_review', 'deprecated')",
            name="nodes_status_check",
        ),
    )

    # Stored generated column for trigram search across array elements.
    # M2 search must query this column directly, not array_to_string(alt_labels, ' ').
    op.execute(
        "ALTER TABLE nodes "
        "ADD COLUMN alt_labels_text TEXT "
        "GENERATED ALWAYS AS (array_to_string(alt_labels, ' ')) STORED"
    )

    # Trigger to keep updated_at in sync on every row update.
    op.execute(
        """
        CREATE FUNCTION set_updated_at() RETURNS trigger AS $$
        BEGIN
          NEW.updated_at = now();
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER nodes_set_updated_at "
        "BEFORE UPDATE ON nodes "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
    )

    op.create_index("ix_nodes_parent_id", "nodes", ["parent_id"])
    # GIN trigram serves both fuzzy and exact lookups; no separate btree on pref_label.
    op.execute(
        "CREATE INDEX ix_nodes_pref_label_trgm "
        "ON nodes USING gin (pref_label gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX ix_nodes_alt_labels_trgm "
        "ON nodes USING gin (alt_labels_text gin_trgm_ops)"
    )

    op.create_table(
        "node_facets",
        sa.Column(
            "node_id",
            sa.Text(),
            sa.ForeignKey("nodes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("facet_key", sa.Text(), nullable=False),
        sa.Column("facet_value", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("node_id", "facet_key"),
        sa.CheckConstraint(
            "facet_key IN ("
            "'decay','nova_group','dietary_flags','allergens','requires_cooking'"
            ")",
            name="node_facets_key_check",
        ),
    )
    op.create_index(
        "ix_node_facets_value_gin",
        "node_facets",
        ["facet_value"],
        postgresql_using="gin",
    )

    op.create_table(
        "node_external_ids",
        sa.Column(
            "node_id",
            sa.Text(),
            sa.ForeignKey("nodes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("source", "external_id"),
    )
    op.create_index("ix_node_external_ids_node_id", "node_external_ids", ["node_id"])


def downgrade() -> None:
    op.drop_index("ix_node_external_ids_node_id", table_name="node_external_ids")
    op.drop_table("node_external_ids")

    op.drop_index("ix_node_facets_value_gin", table_name="node_facets")
    op.drop_table("node_facets")

    op.execute("DROP INDEX IF EXISTS ix_nodes_alt_labels_trgm")
    op.execute("DROP INDEX IF EXISTS ix_nodes_pref_label_trgm")
    op.drop_index("ix_nodes_parent_id", table_name="nodes")
    op.execute("DROP TRIGGER IF EXISTS nodes_set_updated_at ON nodes")
    op.execute("DROP FUNCTION IF EXISTS set_updated_at()")
    op.drop_table("nodes")
