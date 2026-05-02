"""Integration tests for the MCP browse_category tool."""

from __future__ import annotations

import json

import pytest

from zeff.db import connection as db_conn
from zeff.db import queries
from zeff.domain.nodes import Node, NodeType
from zeff.mcp.server import build_server

pytestmark = pytest.mark.integration


def _decode(envelope) -> dict:
    if isinstance(envelope, tuple):
        for part in reversed(envelope):
            if isinstance(part, dict):
                return part
            if isinstance(part, list) and part and hasattr(part[0], "text"):
                return json.loads(part[0].text)
        raise AssertionError(f"unrecognized tuple shape: {envelope!r}")
    if isinstance(envelope, dict):
        return envelope
    raise AssertionError(f"unrecognized envelope: {envelope!r}")


@pytest.fixture
async def server_and_seed(db_session, _migrated_dsn):
    _, async_dsn = _migrated_dsn
    db_conn.configure_engine(async_dsn)

    # food -> {fruit, vegetable}
    # fruit -> {apple, banana}
    # apple -> {honeycrisp_apple, fuji_apple}
    # banana -> (no children)
    # vegetable -> {spinach}
    await queries.create_node(
        db_session, Node(id="food", type=NodeType.category, pref_label="Food")
    )
    await queries.create_node(
        db_session, Node(id="fruit", type=NodeType.category, pref_label="Fruit", parent_id="food")
    )
    await queries.create_node(
        db_session,
        Node(id="vegetable", type=NodeType.category, pref_label="Vegetable", parent_id="food"),
    )
    await queries.create_node(
        db_session, Node(id="apple", type=NodeType.category, pref_label="Apple", parent_id="fruit")
    )
    await queries.create_node(
        db_session,
        Node(id="banana", type=NodeType.category, pref_label="Banana", parent_id="fruit"),
    )
    await queries.create_node(
        db_session,
        Node(
            id="honeycrisp_apple",
            type=NodeType.primitive,
            pref_label="Honeycrisp Apple",
            parent_id="apple",
        ),
    )
    await queries.create_node(
        db_session,
        Node(
            id="fuji_apple",
            type=NodeType.primitive,
            pref_label="Fuji Apple",
            parent_id="apple",
        ),
    )
    await queries.create_node(
        db_session,
        Node(
            id="spinach",
            type=NodeType.primitive,
            pref_label="Spinach",
            parent_id="vegetable",
        ),
    )
    await db_session.commit()

    return build_server()


class TestSchema:
    async def test_tool_listed(self, server_and_seed) -> None:
        names = [t.name for t in await server_and_seed.list_tools()]
        assert "browse_category" in names

    async def test_input_schema(self, server_and_seed) -> None:
        tool = next(t for t in await server_and_seed.list_tools() if t.name == "browse_category")
        props = tool.inputSchema["properties"]
        assert "node_id" in props
        # max_depth was removed in M6 cross-tool review (was accepted but ignored).
        assert "max_depth" not in props


class TestCallTool:
    async def test_lists_immediate_children(self, server_and_seed) -> None:
        payload = _decode(
            await server_and_seed.call_tool("browse_category", {"node_id": "food"})
        )
        assert payload["category"]["node_id"] == "food"
        assert payload["category"]["pref_label"] == "Food"
        ids = sorted(c["node_id"] for c in payload["children"])
        assert ids == ["fruit", "vegetable"]

    async def test_child_count_reflects_direct_children(self, server_and_seed) -> None:
        # child_count is each child's own direct-child count.
        payload = _decode(await server_and_seed.call_tool("browse_category", {"node_id": "food"}))
        by_id = {c["node_id"]: c for c in payload["children"]}
        assert by_id["fruit"]["child_count"] == 2  # apple, banana
        assert by_id["vegetable"]["child_count"] == 1  # spinach

    async def test_leaf_category_returns_empty_children(self, server_and_seed) -> None:
        payload = _decode(
            await server_and_seed.call_tool("browse_category", {"node_id": "banana"})
        )
        assert payload["children"] == []

    async def test_returns_type_per_child(self, server_and_seed) -> None:
        payload = _decode(
            await server_and_seed.call_tool("browse_category", {"node_id": "apple"})
        )
        for c in payload["children"]:
            assert c["type"] == "primitive"

    async def test_unknown_category_raises_error(self, server_and_seed) -> None:
        from mcp.server.fastmcp.exceptions import ToolError

        with pytest.raises(ToolError, match="does_not_exist"):
            await server_and_seed.call_tool(
                "browse_category", {"node_id": "does_not_exist"}
            )

    async def test_non_category_node_works(self, server_and_seed) -> None:
        # Browsing a primitive node returns it with empty children.
        payload = _decode(
            await server_and_seed.call_tool("browse_category", {"node_id": "spinach"})
        )
        assert payload["category"]["node_id"] == "spinach"
        assert payload["children"] == []
