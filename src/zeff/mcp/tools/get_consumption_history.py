"""MCP `get_consumption_history` tool.

Returns the user's ingest events over a time window, optionally aggregated.
Operating assumption: the user eats what they buy (DESIGN.md), so this is
a consumption summary derived from ingest records.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from mcp.server import FastMCP
from pydantic import Field

from zeff.db import connection as db_conn
from zeff.domain.history import (
    GroupBy,
    HistoryResult,
    get_consumption_history,
)

TOOL_NAME = "get_consumption_history"
TOOL_TITLE = "Get consumption history"
TOOL_DESCRIPTION = (
    "Aggregate the user's food intake over a time window. Returns either "
    "raw events (group_by='none') or per-bucket counts and quantities for "
    "the chosen grouping.\n"
    "\n"
    "Use this for questions like 'how much red meat have I eaten this "
    "month?' (group_by='category'), 'am I eating too much processed food?' "
    "(group_by='nova_group'), or 'what did I eat each day?' "
    "(group_by='day').\n"
    "\n"
    "time_range is a string like '7d', '30d', '90d'. Returns empty for "
    "unknown users."
)


def register(server: FastMCP) -> None:
    """Register the get_consumption_history tool on the given FastMCP server."""

    @server.tool(name=TOOL_NAME, title=TOOL_TITLE, description=TOOL_DESCRIPTION)
    async def get_consumption_history_tool(
        user_id: Annotated[
            str,
            Field(description="User identifier whose history to compute."),
        ],
        time_range: Annotated[
            str,
            Field(
                default="30d",
                description="Window expressed as '<n>d', e.g. '7d', '30d', '90d'.",
            ),
        ] = "30d",
        group_by: Annotated[
            GroupBy,
            Field(
                default=GroupBy.category,
                description=(
                    "How to bucket results: 'category' (top-level food category), "
                    "'nova_group' (1-4 + unknown), 'day' (UTC calendar), or "
                    "'none' (return raw events)."
                ),
            ),
        ] = GroupBy.category,
        as_of: Annotated[
            datetime | None,
            Field(
                default=None,
                description="ISO 8601 timestamp; defaults to the current time.",
            ),
        ] = None,
    ) -> HistoryResult:
        async with db_conn.session_scope() as session:
            return await get_consumption_history(
                session,
                user_id,
                time_range=time_range,
                group_by=group_by,
                as_of=as_of,
            )
