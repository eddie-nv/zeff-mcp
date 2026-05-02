"""Integration tests for the MCP get_food_components tool."""

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

    # Build a small composite scene.
    await queries.create_node(
        db_session, Node(id="cheese", type=NodeType.category, pref_label="Cheese")
    )
    await queries.create_node(
        db_session, Node(id="vegetable", type=NodeType.category, pref_label="Vegetable")
    )
    await queries.create_node(
        db_session, Node(id="grain", type=NodeType.category, pref_label="Grain")
    )
    await queries.create_node(
        db_session,
        Node(id="mozzarella", type=NodeType.primitive, pref_label="Mozzarella", parent_id="cheese"),
    )
    await queries.create_node(
        db_session,
        Node(
            id="tomato_sauce",
            type=NodeType.primitive,
            pref_label="Tomato Sauce",
            parent_id="vegetable",
        ),
    )
    await queries.create_node(
        db_session,
        Node(
            id="pizza_dough", type=NodeType.primitive, pref_label="Pizza Dough", parent_id="grain"
        ),
    )
    await queries.create_node(
        db_session,
        Node(id="frozen_pizza", type=NodeType.composite, pref_label="Frozen Cheese Pizza"),
    )
    await queries.create_node(
        db_session,
        Node(id="apple", type=NodeType.primitive, pref_label="Apple", parent_id="vegetable"),
    )
    await queries.add_component(
        db_session,
        "frozen_pizza",
        "mozzarella",
        grams_per_serving=60.0,
        is_primary=True,
        position=0,
    )
    await queries.add_component(
        db_session, "frozen_pizza", "tomato_sauce", grams_per_serving=50.0, position=1
    )
    await queries.add_component(
        db_session, "frozen_pizza", "pizza_dough", grams_per_serving=110.0, position=2
    )
    await db_session.commit()

    return build_server()


class TestSchema:
    async def test_tool_listed(self, server_and_seed) -> None:
        names = [t.name for t in await server_and_seed.list_tools()]
        assert "get_food_components" in names

    async def test_input_schema(self, server_and_seed) -> None:
        tool = next(
            t for t in await server_and_seed.list_tools() if t.name == "get_food_components"
        )
        assert "node_id" in tool.inputSchema["properties"]


class TestCallTool:
    async def test_composite_returns_components(self, server_and_seed) -> None:
        payload = _decode(
            await server_and_seed.call_tool("get_food_components", {"node_id": "frozen_pizza"})
        )
        assert payload["is_composite"] is True
        comps = payload["components"]
        assert len(comps) == 3
        ids = [c["node_id"] for c in comps]
        assert ids == ["mozzarella", "tomato_sauce", "pizza_dough"]
        primary = next(c for c in comps if c["is_primary"])
        assert primary["node_id"] == "mozzarella"

    async def test_pref_label_resolved_for_each_component(self, server_and_seed) -> None:
        payload = _decode(
            await server_and_seed.call_tool("get_food_components", {"node_id": "frozen_pizza"})
        )
        labels = {c["node_id"]: c["pref_label"] for c in payload["components"]}
        assert labels["mozzarella"] == "Mozzarella"
        assert labels["tomato_sauce"] == "Tomato Sauce"

    async def test_grams_per_serving_returned(self, server_and_seed) -> None:
        payload = _decode(
            await server_and_seed.call_tool("get_food_components", {"node_id": "frozen_pizza"})
        )
        by_id = {c["node_id"]: c for c in payload["components"]}
        assert by_id["mozzarella"]["grams_per_serving"] == 60.0

    async def test_primitive_returns_empty(self, server_and_seed) -> None:
        payload = _decode(
            await server_and_seed.call_tool("get_food_components", {"node_id": "apple"})
        )
        assert payload["is_composite"] is False
        assert payload["components"] == []

    async def test_unknown_node_raises_error(self, server_and_seed) -> None:
        from mcp.server.fastmcp.exceptions import ToolError

        with pytest.raises(ToolError, match="does_not_exist"):
            await server_and_seed.call_tool("get_food_components", {"node_id": "does_not_exist"})
