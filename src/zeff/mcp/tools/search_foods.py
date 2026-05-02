"""MCP `search_foods` tool.

Wraps `zeff.domain.search.search_foods` for the MCP transport. Inputs are
validated by Pydantic via the FastMCP signature; the output is a typed
SearchFoodsResult model so the tool description carries an unambiguous
shape into the LLM's view of the schema.
"""

from __future__ import annotations

from typing import Annotated

from mcp.server import FastMCP
from pydantic import BaseModel, ConfigDict, Field

from zeff.db import connection as db_conn
from zeff.domain.nodes import NodeType
from zeff.domain.search import DEFAULT_LIMIT, SearchResult, search_foods

TOOL_NAME = "search_foods"
TOOL_TITLE = "Search foods"
TOOL_DESCRIPTION = (
    "Search the curated food taxonomy by name, abbreviation, or alt label.\n"
    "\n"
    "Use this when you need to locate a food by name and don't already have "
    "its node_id. Results are ranked: rank-1 is the system's best guess. "
    "Each result includes the node's parent chain so you can confirm category.\n"
    "\n"
    "Pass type_filter='primitive' to exclude category nodes from results, "
    "or 'category' to find taxonomy categories specifically."
)


class SearchFoodsResult(BaseModel):
    """Structured response for the search_foods tool."""

    model_config = ConfigDict(frozen=True)

    query: str
    results: list[SearchResult]


def register(server: FastMCP) -> None:
    """Register the search_foods tool on the given FastMCP server."""

    @server.tool(name=TOOL_NAME, title=TOOL_TITLE, description=TOOL_DESCRIPTION)
    async def search_foods_tool(
        query: Annotated[
            str, Field(description="Free-text food name, abbreviation, or alt label.")
        ],
        limit: Annotated[
            int,
            Field(
                default=DEFAULT_LIMIT,
                ge=1,
                le=50,
                description="Maximum number of results to return (1-50).",
            ),
        ] = DEFAULT_LIMIT,
        type_filter: Annotated[
            NodeType | None,
            Field(
                default=None,
                description="Restrict to a node type: primitive, composite, or category.",
            ),
        ] = None,
    ) -> SearchFoodsResult:
        async with db_conn.session_scope() as session:
            results = await search_foods(session, query, limit=limit, type_filter=type_filter)
        return SearchFoodsResult(query=query, results=results)
