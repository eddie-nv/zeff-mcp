"""MCP `browse_category` tool.

Returns a category node and its immediate children, with each child's own
direct child count. Used by an LLM to walk the taxonomy when the user
asks for "what kinds of X are there".
"""

from __future__ import annotations

from typing import Annotated

from mcp.server import FastMCP
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from zeff.db import connection as db_conn
from zeff.db.models import Node
from zeff.domain.nodes import NodeType

TOOL_NAME = "browse_category"
TOOL_TITLE = "Browse category"
TOOL_DESCRIPTION = (
    "List the immediate children of a category node, plus each child's own "
    "direct child count. Use this to walk the taxonomy — e.g. 'what kinds "
    "of vegetable are there?' or 'what's under protein?'.\n"
    "\n"
    "If `category_node_id` is a leaf primitive (no children), returns the "
    "node with an empty children list. Raises an error for unknown ids."
)


class CategoryHeader(BaseModel):
    model_config = ConfigDict(frozen=True)

    node_id: str
    pref_label: str


class CategoryChild(BaseModel):
    model_config = ConfigDict(frozen=True)

    node_id: str
    pref_label: str
    type: NodeType
    child_count: int = Field(description="Number of direct children of this child.")


class CategoryView(BaseModel):
    model_config = ConfigDict(frozen=True)

    category: CategoryHeader
    children: list[CategoryChild]


class CategoryNotFoundError(LookupError):
    """Raised when browse_category is called with an unknown node_id."""


async def _browse(session: AsyncSession, node_id: str) -> CategoryView:
    node = await session.get(Node, node_id)
    if node is None:
        raise CategoryNotFoundError(f"node {node_id!r} not found")

    # One join: children of node + count of grandchildren per child.
    child_alias = Node.__table__.alias("child")
    grand_alias = Node.__table__.alias("grand")
    stmt = (
        select(
            child_alias.c.id,
            child_alias.c.pref_label,
            child_alias.c.type,
            func.count(grand_alias.c.id).label("child_count"),
        )
        .select_from(
            child_alias.outerjoin(grand_alias, grand_alias.c.parent_id == child_alias.c.id)
        )
        .where(child_alias.c.parent_id == node_id)
        .group_by(child_alias.c.id, child_alias.c.pref_label, child_alias.c.type)
        .order_by(child_alias.c.pref_label)
    )
    rows = (await session.execute(stmt)).all()
    children = [
        CategoryChild(
            node_id=row.id,
            pref_label=row.pref_label,
            type=NodeType(row.type),
            child_count=int(row.child_count),
        )
        for row in rows
    ]
    return CategoryView(
        category=CategoryHeader(node_id=node.id, pref_label=node.pref_label),
        children=children,
    )


def register(server: FastMCP) -> None:
    """Register the browse_category tool on the given FastMCP server."""

    @server.tool(name=TOOL_NAME, title=TOOL_TITLE, description=TOOL_DESCRIPTION)
    async def browse_category_tool(
        node_id: Annotated[
            str,
            Field(
                description=(
                    "Slugified node id, typically a category like 'fruit' or "
                    "'protein'. Passing a primitive returns it with empty children."
                )
            ),
        ],
    ) -> CategoryView:
        async with db_conn.session_scope() as session:
            return await _browse(session, node_id)
