"""SQLAlchemy ORM models for the v1 schema.

Mirrors the migration in alembic/versions/. The migration is the source of
truth for the database; these models are the Python view of it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import (
    UUID as PgUUID,  # noqa: N811 — pg-dialect type, not a constant
)
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
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'active'"))
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
            "facet_key IN ('decay','nova_group','dietary_flags','allergens','requires_cooking')",
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


class NodeComponent(Base):
    __tablename__ = "node_components"
    __table_args__ = (
        PrimaryKeyConstraint("composite_id", "component_id"),
        CheckConstraint(
            "grams_per_serving IS NULL OR grams_per_serving >= 0",
            name="node_components_grams_check",
        ),
    )

    composite_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("nodes.id", ondelete="CASCADE"),
        nullable=False,
    )
    component_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("nodes.id", ondelete="RESTRICT"),
        nullable=False,
    )
    grams_per_serving: Mapped[float | None] = mapped_column(Float, nullable=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))


class IngestRecord(Base):
    __tablename__ = "ingest_records"
    __table_args__ = (
        CheckConstraint(
            "quantity IS NULL OR quantity > 0",
            name="ingest_records_quantity_check",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    node_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("nodes.id", ondelete="RESTRICT"),
        nullable=False,
    )
    acquired_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    quantity: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
