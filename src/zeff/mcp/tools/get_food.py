"""MCP `get_food` tool.

Returns the full record for a single node: labels, type, parent chain
(closest parent first), every facet, and external IDs.

Use after `search_foods` once the LLM has a candidate node_id.
"""

from __future__ import annotations

from typing import Annotated, Any

from mcp.server import FastMCP
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from zeff.db import connection as db_conn
from zeff.db.models import Node, NodeExternalId, NodeFacet
from zeff.domain.nodes import NodeType

TOOL_NAME = "get_food"
TOOL_TITLE = "Get food"
TOOL_DESCRIPTION = (
    "Fetch the full record for a single food node: labels, type, parent "
    "chain (closest first), every facet (nova_group, decay, dietary_flags, "
    "allergens, requires_cooking), and external IDs.\n"
    "\n"
    "Call this after `search_foods` once you have a candidate node_id. "
    "Raises an error if the node doesn't exist — search first if uncertain."
)


class FoodResult(BaseModel):
    """Structured response for the get_food tool."""

    model_config = ConfigDict(frozen=True)

    node_id: str
    pref_label: str
    alt_labels: list[str]
    type: NodeType
    parent_id: str | None
    parents: list[str] = Field(
        description="Ancestor chain from closest parent to root (excluding self)."
    )
    facets: dict[str, Any]
    external_ids: dict[str, str]


class FoodNotFoundError(LookupError):
    """Raised when get_food is called with an unknown node_id."""


# Single SQL: node + ancestor chain + facets + external IDs in one round trip.
_PARENTS_SQL = text(
    """
    WITH RECURSIVE chain AS (
        SELECT id, parent_id, 0 AS depth
        FROM nodes
        WHERE id = :node_id
        UNION ALL
        SELECT n.id, n.parent_id, c.depth + 1
        FROM chain c
        JOIN nodes n ON n.id = c.parent_id
        WHERE c.parent_id IS NOT NULL
    )
    SELECT id FROM chain WHERE depth > 0 ORDER BY depth ASC
    """
)


async def _load_food(session: AsyncSession, node_id: str) -> FoodResult:
    node = await session.get(Node, node_id)
    if node is None:
        raise FoodNotFoundError(f"node {node_id!r} not found")

    parents = [row.id for row in (await session.execute(_PARENTS_SQL, {"node_id": node_id})).all()]

    facet_rows = (
        await session.execute(
            select(NodeFacet.facet_key, NodeFacet.facet_value).where(NodeFacet.node_id == node_id)
        )
    ).all()
    facets = {r.facet_key: r.facet_value for r in facet_rows}

    ext_rows = (
        await session.execute(
            select(NodeExternalId.source, NodeExternalId.external_id).where(
                NodeExternalId.node_id == node_id
            )
        )
    ).all()
    external_ids = {r.source: r.external_id for r in ext_rows}

    return FoodResult(
        node_id=node.id,
        pref_label=node.pref_label,
        alt_labels=list(node.alt_labels or []),
        type=NodeType(node.type),
        parent_id=node.parent_id,
        parents=parents,
        facets=facets,
        external_ids=external_ids,
    )


def register(server: FastMCP) -> None:
    """Register the get_food tool on the given FastMCP server."""

    @server.tool(name=TOOL_NAME, title=TOOL_TITLE, description=TOOL_DESCRIPTION)
    async def get_food_tool(
        node_id: Annotated[
            str,
            Field(description="Slugified node id, e.g. 'honeycrisp_apple'."),
        ],
    ) -> FoodResult:
        async with db_conn.session_scope() as session:
            return await _load_food(session, node_id)
