"""Integration tests for the MCP search_foods tool.

Drives a freshly-built FastMCP server in-process via `call_tool`, which is
the same surface the stdio transport hits. This catches bugs in the tool
wrapper (schema drift, parameter names, response shape) that would not
show up in the underlying domain tests.
"""

from __future__ import annotations

import json

import pytest

from zeff.db import connection as db_conn
from zeff.db import queries
from zeff.domain.nodes import Node, NodeType
from zeff.mcp.server import build_server

pytestmark = pytest.mark.integration


@pytest.fixture
async def server_and_seed(db_session, _migrated_dsn):
    """Build a server bound to the migrated test DB, with a small seed."""
    _, async_dsn = _migrated_dsn
    db_conn.configure_engine(async_dsn)

    await queries.create_node(
        db_session, Node(id="food", type=NodeType.category, pref_label="Food")
    )
    await queries.create_node(
        db_session,
        Node(id="fruit", type=NodeType.category, pref_label="Fruit", parent_id="food"),
    )
    await queries.create_node(
        db_session,
        Node(
            id="apple",
            type=NodeType.primitive,
            pref_label="Apple",
            parent_id="fruit",
            alt_labels=["red apple"],
        ),
    )
    await queries.create_node(
        db_session,
        Node(
            id="honeycrisp_apple",
            type=NodeType.primitive,
            pref_label="Honeycrisp Apple",
            parent_id="fruit",
            alt_labels=["honeycrisp", "hc apple"],
        ),
    )
    await db_session.commit()

    server = build_server()
    return server


def _decode(envelope) -> dict:
    """FastMCP returns a Sequence[ContentBlock] | dict[str, Any].

    For tools with a structured return, recent FastMCP versions return both
    a content blocks tuple AND a structured dict — newer SDK calls return
    the dict directly. Normalize to a dict for assertions.
    """
    # 1.27 returns (content_list, structured_dict) tuple from call_tool.
    if isinstance(envelope, tuple):
        for part in reversed(envelope):
            if isinstance(part, dict):
                return part
            if isinstance(part, list) and part:
                # Fall back: parse text content as JSON.
                first = part[0]
                if hasattr(first, "text"):
                    return json.loads(first.text)
        raise AssertionError(f"unrecognized tuple shape: {envelope!r}")
    if isinstance(envelope, dict):
        return envelope
    if isinstance(envelope, list):
        # Sequence of ContentBlock — first text block is the structured payload.
        first = envelope[0]
        if hasattr(first, "text"):
            return json.loads(first.text)
    raise AssertionError(f"unrecognized envelope: {envelope!r}")


class TestSchema:
    async def test_tool_listed(self, server_and_seed) -> None:
        server = server_and_seed
        tools = await server.list_tools()
        names = [t.name for t in tools]
        assert "search_foods" in names

    async def test_input_schema_has_required_args(self, server_and_seed) -> None:
        server = server_and_seed
        tool = next(t for t in await server.list_tools() if t.name == "search_foods")
        props = tool.inputSchema["properties"]
        assert "query" in props
        assert "limit" in props
        assert "type_filter" in props


class TestCallTool:
    async def test_finds_seeded_node(self, server_and_seed) -> None:
        server = server_and_seed
        envelope = await server.call_tool("search_foods", {"query": "apple"})
        payload = _decode(envelope)
        assert payload["query"] == "apple"
        results = payload["results"]
        assert results
        assert results[0]["node_id"] == "apple"
        assert results[0]["pref_label"] == "Apple"

    async def test_alt_label_match(self, server_and_seed) -> None:
        payload = _decode(await server_and_seed.call_tool("search_foods", {"query": "honeycrisp"}))
        ids = [r["node_id"] for r in payload["results"]]
        assert "honeycrisp_apple" in ids

    async def test_abbreviation_match(self, server_and_seed) -> None:
        payload = _decode(await server_and_seed.call_tool("search_foods", {"query": "hc apple"}))
        ids = [r["node_id"] for r in payload["results"]]
        assert "honeycrisp_apple" in ids

    async def test_limit_respected(self, server_and_seed) -> None:
        payload = _decode(
            await server_and_seed.call_tool("search_foods", {"query": "apple", "limit": 1})
        )
        assert len(payload["results"]) == 1

    async def test_type_filter_excludes_categories(self, server_and_seed) -> None:
        payload = _decode(
            await server_and_seed.call_tool(
                "search_foods", {"query": "fruit", "type_filter": "primitive"}
            )
        )
        assert all(r["type"] == "primitive" for r in payload["results"])
        assert not any(r["node_id"] == "fruit" for r in payload["results"])

    async def test_empty_query_returns_empty_results(self, server_and_seed) -> None:
        payload = _decode(await server_and_seed.call_tool("search_foods", {"query": ""}))
        assert payload["results"] == []

    async def test_response_shape(self, server_and_seed) -> None:
        payload = _decode(await server_and_seed.call_tool("search_foods", {"query": "apple"}))
        assert set(payload.keys()) >= {"query", "results"}
        for r in payload["results"]:
            assert {"node_id", "pref_label", "type", "parents", "score"} <= set(r.keys())


class TestParity:
    """The MCP wrapper must produce the same ranking as the direct domain call."""

    async def test_top_result_matches_domain(self, server_and_seed, db_session) -> None:
        from zeff.domain.search import search_foods as domain_search

        payload = _decode(
            await server_and_seed.call_tool("search_foods", {"query": "honeycrisp", "limit": 5})
        )
        wrapper_ids = [r["node_id"] for r in payload["results"]]

        async with db_conn.session_scope() as s:
            domain_results = await domain_search(s, "honeycrisp", limit=5)
        domain_ids = [r.node_id for r in domain_results]

        assert wrapper_ids == domain_ids
