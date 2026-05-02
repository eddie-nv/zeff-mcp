"""Repository functions: thin async wrappers over the ORM models.

Each function takes an `AsyncSession` so callers control transaction scope.
None of these commit OR flush; commit at the use-case boundary. This means
constraint violations surface at commit() (or at the next read that triggers
autoflush), not inside the query function.

Facet writes always go through `validate_facet`, so the database never sees
an invalid value even if a caller bypasses pydantic.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from zeff.db.models import Node as NodeRow
from zeff.db.models import NodeExternalId as ExternalIdRow
from zeff.db.models import NodeFacet as FacetRow
from zeff.domain.facets import FacetKey, validate_facet
from zeff.domain.nodes import Node


async def create_node(session: AsyncSession, node: Node) -> None:
    """Insert a new node. Caller commits."""
    row = NodeRow(
        id=node.id,
        type=node.type.value,
        pref_label=node.pref_label,
        alt_labels=list(node.alt_labels) if node.alt_labels else None,
        parent_id=node.parent_id,
        status=node.status,
    )
    session.add(row)


async def get_node(session: AsyncSession, node_id: str) -> NodeRow | None:
    return await session.get(NodeRow, node_id)


async def set_parent(session: AsyncSession, node_id: str, parent_id: str | None) -> None:
    """Set or clear a node's parent. The FK enforces parent existence at commit."""
    row = await session.get(NodeRow, node_id)
    if row is None:
        raise LookupError(f"node {node_id!r} not found")
    row.parent_id = parent_id


async def set_facet(session: AsyncSession, node_id: str, key: FacetKey, value: Any) -> None:
    """Upsert a single facet. Validates value before writing."""
    normalized = validate_facet(key, value)
    existing = await session.get(FacetRow, (node_id, key.value))
    if existing is None:
        session.add(FacetRow(node_id=node_id, facet_key=key.value, facet_value=normalized))
    else:
        existing.facet_value = normalized


async def get_facets(session: AsyncSession, node_id: str) -> dict[FacetKey, Any]:
    """Return all facets for a node, keyed by FacetKey enum."""
    rows = (
        await session.execute(
            select(FacetRow.facet_key, FacetRow.facet_value).where(FacetRow.node_id == node_id)
        )
    ).all()
    return {FacetKey(row.facet_key): row.facet_value for row in rows}


async def add_external_id(
    session: AsyncSession, node_id: str, source: str, external_id: str
) -> None:
    session.add(ExternalIdRow(node_id=node_id, source=source, external_id=external_id))


async def delete_node(session: AsyncSession, node_id: str) -> None:
    """Delete a node. CASCADE removes facets and external IDs."""
    await session.execute(delete(NodeRow).where(NodeRow.id == node_id))
