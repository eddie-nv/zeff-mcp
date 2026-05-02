"""Spawn the zeff-mcp server over stdio, run an initialize + tools/list +
tools/call(search_foods) sequence, print the server's responses."""

import asyncio
import json
import os
import sys

from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


async def main():
    env = {**os.environ, "DATABASE_URL": "postgresql+psycopg://zeff:zeff@localhost:5432/zeff"}
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "zeff.mcp.server"],
        env=env,
    )
    async with stdio_client(params) as (read, write), ClientSession(read, write) as s:
        init = await s.initialize()
        print(
            "INIT server:",
            init.serverInfo.name,
            "instructions:",
            init.instructions[:60] if init.instructions else "",
        )
        tools = await s.list_tools()
        print("TOOLS:", [t.name for t in tools.tools])
        for q in ["honeycrisp apple", "fish salmon", "celery", "no_match_query_xyz", "salt"]:
            res = await s.call_tool("search_foods", {"query": q, "limit": 3})
            payload = res.structuredContent or json.loads(res.content[0].text)
            ids = [r["node_id"] for r in payload.get("results", [])]
            print(f"  Q={q!r:40s} -> {ids}")


asyncio.run(main())
