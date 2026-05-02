"""SQLAlchemy ORM models for the v1 schema.

Mirrors the migration in alembic/versions/. The migration is the source of
truth for the database; these models are the Python view of it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    ARRAY,
    CheckConstraint,
    DateTime,
    ForeignKey,
    PrimaryKeyConstraint,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Common declarative base."""


class Node(Base):
    __tablename__ = "nodes"
    __table_args__ = (
        CheckConstraint(
            "type IN ('primitive', 'composite', 'category')",
            name="nodes_type_check",
        ),
        CheckConstraint(
            "status IN ('active', 'pending_review', 'deprecated')",
            name="nodes_status_check",
        ),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    type: Mapped[str] = mapped_column(Text, nullable=False)
    pref_label: Mapped[str] = mapped_column(Text, nullable=False)
    alt_labels: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    parent_id: Mapped[str | None] = mapped_column(
        Text,
        ForeignKey("nodes.id", ondelete="RESTRICT"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'active'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class NodeFacet(Base):
    __tablename__ = "node_facets"
    __table_args__ = (
        PrimaryKeyConstraint("node_id", "facet_key"),
        CheckConstraint(
            "facet_key IN ("
            "'decay','nova_group','dietary_flags','allergens','requires_cooking'"
            ")",
            name="node_facets_key_check",
        ),
    )

    node_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("nodes.id", ondelete="CASCADE"),
        nullable=False,
    )
    facet_key: Mapped[str] = mapped_column(Text, nullable=False)
    facet_value: Mapped[Any] = mapped_column(JSONB, nullable=False)


class NodeExternalId(Base):
    __tablename__ = "node_external_ids"
    __table_args__ = (PrimaryKeyConstraint("source", "external_id"),)

    node_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("nodes.id", ondelete="CASCADE"),
        nullable=False,
    )
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    external_id: Mapped[str] = mapped_column(Text, nullable=False)
