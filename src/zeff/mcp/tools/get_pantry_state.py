"""MCP `get_pantry_state` tool.

Returns the user's current pantry: ingest records minus items whose
estimated expiration is at or before `as_of`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from mcp.server import FastMCP
from pydantic import BaseModel, ConfigDict, Field

from zeff.db import connection as db_conn
from zeff.domain.pantry import PantryItem, compute_pantry_state

TOOL_NAME = "get_pantry_state"
TOOL_TITLE = "Get pantry state"
TOOL_DESCRIPTION = (
    "Return the user's current pantry — every food they've acquired that "
    "hasn't yet expired. Each item carries the estimated expiration and a "
    "days_until_expiration so you can prioritize what to eat next.\n"
    "\n"
    "If `as_of` is omitted, defaults to the current time. Items without "
    "decay data are kept indefinitely (storage_mode and estimated_expiration "
    "will be null). Returns an empty list for unknown users."
)


class PantryStateResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    user_id: str
    as_of: datetime
    items: list[PantryItem] = Field(default_factory=list)


def register(server: FastMCP) -> None:
    """Register the get_pantry_state tool on the given FastMCP server."""

    @server.tool(name=TOOL_NAME, title=TOOL_TITLE, description=TOOL_DESCRIPTION)
    async def get_pantry_state_tool(
        user_id: Annotated[
            str,
            Field(description="User identifier whose pantry to compute."),
        ],
        as_of: Annotated[
            datetime | None,
            Field(
                default=None,
                description="ISO 8601 timestamp; defaults to the current time.",
            ),
        ] = None,
    ) -> PantryStateResult:
        async with db_conn.session_scope() as session:
            items = await compute_pantry_state(session, user_id, as_of=as_of)
        from datetime import UTC

        return PantryStateResult(
            user_id=user_id,
            as_of=as_of if as_of is not None else datetime.now(tz=UTC),
            items=items,
        )
