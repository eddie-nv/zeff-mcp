"""Integration tests for the MCP get_food tool."""

from __future__ import annotations

import json

import pytest

from zeff.db import connection as db_conn
from zeff.db import queries
from zeff.domain.facets import FacetKey
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

    # Build a small chain: food -> fruit -> apple -> honeycrisp_apple
    await queries.create_node(
        db_session, Node(id="food", type=NodeType.category, pref_label="Food")
    )
    await queries.create_node(
        db_session, Node(id="fruit", type=NodeType.category, pref_label="Fruit", parent_id="food")
    )
    await queries.create_node(
        db_session, Node(id="apple", type=NodeType.category, pref_label="Apple", parent_id="fruit")
    )
    await queries.create_node(
        db_session,
        Node(
            id="honeycrisp_apple",
            type=NodeType.primitive,
            pref_label="Honeycrisp Apple",
            parent_id="apple",
            alt_labels=["honeycrisp", "hc apple"],
        ),
    )
    await queries.set_facet(db_session, "honeycrisp_apple", FacetKey.nova_group, 1)
    await queries.set_facet(
        db_session,
        "honeycrisp_apple",
        FacetKey.dietary_flags,
        ["gluten_free", "vegan", "vegetarian"],
    )
    await queries.set_facet(db_session, "honeycrisp_apple", FacetKey.allergens, [])
    await queries.set_facet(
        db_session, "honeycrisp_apple", FacetKey.decay, {"refrigerated_days": 60, "pantry_days": 14}
    )
    await queries.set_facet(db_session, "honeycrisp_apple", FacetKey.requires_cooking, False)
    await queries.add_external_id(db_session, "honeycrisp_apple", "usda_sr", "171688")
    await db_session.commit()

    return build_server()


class TestSchema:
    async def test_tool_listed(self, server_and_seed) -> None:
        names = [t.name for t in await server_and_seed.list_tools()]
        assert "get_food" in names

    async def test_input_schema_has_node_id(self, server_and_seed) -> None:
        tool = next(t for t in await server_and_seed.list_tools() if t.name == "get_food")
        assert "node_id" in tool.inputSchema["properties"]


class TestCallTool:
    async def test_returns_full_record(self, server_and_seed) -> None:
        payload = _decode(
            await server_and_seed.call_tool("get_food", {"node_id": "honeycrisp_apple"})
        )
        assert payload["node_id"] == "honeycrisp_apple"
        assert payload["pref_label"] == "Honeycrisp Apple"
        assert payload["type"] == "primitive"
        assert payload["parent_id"] == "apple"
        # Outermost-first chain.
        assert payload["parents"] == ["apple", "fruit", "food"]
        assert sorted(payload["alt_labels"]) == ["hc apple", "honeycrisp"]

    async def test_facets_returned(self, server_and_seed) -> None:
        payload = _decode(
            await server_and_seed.call_tool("get_food", {"node_id": "honeycrisp_apple"})
        )
        f = payload["facets"]
        assert f["nova_group"] == 1
        assert sorted(f["dietary_flags"]) == ["gluten_free", "vegan", "vegetarian"]
        assert f["requires_cooking"] is False
        assert f["decay"] == {"refrigerated_days": 60, "pantry_days": 14}

    async def test_external_ids_returned(self, server_and_seed) -> None:
        payload = _decode(
            await server_and_seed.call_tool("get_food", {"node_id": "honeycrisp_apple"})
        )
        assert payload["external_ids"] == {"usda_sr": "171688"}

    async def test_category_node_returns_no_facets(self, server_and_seed) -> None:
        payload = _decode(await server_and_seed.call_tool("get_food", {"node_id": "fruit"}))
        assert payload["type"] == "category"
        assert payload["facets"] == {}
        assert payload["parents"] == ["food"]

    async def test_root_node_has_empty_parent_chain(self, server_and_seed) -> None:
        payload = _decode(await server_and_seed.call_tool("get_food", {"node_id": "food"}))
        assert payload["parent_id"] is None
        assert payload["parents"] == []

    async def test_unknown_node_raises_tool_error(self, server_and_seed) -> None:
        from mcp.server.fastmcp.exceptions import ToolError

        with pytest.raises(ToolError, match="does_not_exist"):
            await server_and_seed.call_tool("get_food", {"node_id": "does_not_exist"})
