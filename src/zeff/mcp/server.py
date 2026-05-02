"""MCP server entry point.

Wires the FastMCP server to our taxonomy tools and runs it over stdio.
Tools are registered in the `register_tools` function so tests can
construct a fresh server instance with the same tool surface.

Run via:

    zeff-mcp           # console-script entry point
    python -m zeff.mcp.server
"""

from __future__ import annotations

import asyncio
import logging

from mcp.server import FastMCP

from zeff.config import get_settings
from zeff.db import connection as db_conn

log = logging.getLogger(__name__)

SERVER_NAME = "zeff-taxonomy"
INSTRUCTIONS = (
    "Curated food taxonomy. Use search_foods to look up foods by name, "
    "abbreviation, or alt label; results include node_id, parents, and a "
    "score so you can disambiguate."
)


def build_server() -> FastMCP:
    """Create a fresh FastMCP instance with all tools registered.

    Tests use this to drive the same tool surface in-process.
    """
    server = FastMCP(name=SERVER_NAME, instructions=INSTRUCTIONS)
    register_tools(server)
    return server


def register_tools(server: FastMCP) -> None:
    """Register every taxonomy tool on the given server.

    Imports are lazy so a test that wants to register only a subset can
    easily fork this function.
    """
    from zeff.mcp.tools.get_food import register as register_get_food
    from zeff.mcp.tools.search_foods import register as register_search_foods

    register_search_foods(server)
    register_get_food(server)


async def _amain() -> None:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)
    db_conn.configure_engine(settings.database_url)
    server = build_server()
    log.info("starting %s over stdio", SERVER_NAME)
    await server.run_stdio_async()


def main() -> int:
    asyncio.run(_amain())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
