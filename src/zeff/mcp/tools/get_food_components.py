"""MCP `get_food_components` tool.

Returns the recipe for a composite food. Primitives return
`is_composite=false` with an empty components list — call this whenever
you need to know "what's in" a food, regardless of type.
"""

from __future__ import annotations

from typing import Annotated

from mcp.server import FastMCP
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from zeff.db import connection as db_conn
from zeff.db.models import Node, NodeComponent

TOOL_NAME = "get_food_components"
TOOL_TITLE = "Get food components"
TOOL_DESCRIPTION = (
    "Return the recipe (component breakdown) for a composite food. Each "
    "component is a primitive node with grams_per_serving and an is_primary "
    "flag. Components are returned in the curated order (position).\n"
    "\n"
    "If the node is a primitive (or has no components), returns "
    "`is_composite=false` and an empty list. Raises an error for unknown ids."
)


class Component(BaseModel):
    model_config = ConfigDict(frozen=True)

    node_id: str
    pref_label: str
    grams_per_serving: float | None
    is_primary: bool


class ComponentsResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    node_id: str
    is_composite: bool
    components: list[Component] = Field(default_factory=list)


class NodeNotFoundError(LookupError):
    """Raised when get_food_components is called with an unknown node_id."""


async def _load_components(session: AsyncSession, node_id: str) -> ComponentsResult:
    node = await session.get(Node, node_id)
    if node is None:
        raise NodeNotFoundError(f"node {node_id!r} not found")

    rows = (
        await session.execute(
            select(
                NodeComponent.component_id,
                NodeComponent.grams_per_serving,
                NodeComponent.is_primary,
                Node.pref_label,
            )
            .join(Node, Node.id == NodeComponent.component_id)
            .where(NodeComponent.composite_id == node_id)
            .order_by(NodeComponent.position, NodeComponent.component_id)
        )
    ).all()
    components = [
        Component(
            node_id=row.component_id,
            pref_label=row.pref_label,
            grams_per_serving=row.grams_per_serving,
            is_primary=row.is_primary,
        )
        for row in rows
    ]
    return ComponentsResult(
        node_id=node_id,
        is_composite=node.type == "composite",
        components=components,
    )


def register(server: FastMCP) -> None:
    """Register the get_food_components tool on the given FastMCP server."""

    @server.tool(name=TOOL_NAME, title=TOOL_TITLE, description=TOOL_DESCRIPTION)
    async def get_food_components_tool(
        node_id: Annotated[
            str,
            Field(
                description="Slugified node id, typically a composite like 'frozen_cheese_pizza'."
            ),
        ],
    ) -> ComponentsResult:
        async with db_conn.session_scope() as session:
            return await _load_components(session, node_id)
