"""Integration tests for the MCP get_pantry_state tool."""

from __future__ import annotations

import json
from datetime import UTC, datetime

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

    await queries.create_node(
        db_session, Node(id="vegetable", type=NodeType.category, pref_label="Vegetable")
    )
    await queries.create_node(
        db_session, Node(id="seasoning", type=NodeType.category, pref_label="Seasoning")
    )
    await queries.create_node(
        db_session,
        Node(
            id="spinach_raw", type=NodeType.primitive, pref_label="Spinach", parent_id="vegetable"
        ),
    )
    await queries.create_node(
        db_session,
        Node(id="salt", type=NodeType.primitive, pref_label="Salt", parent_id="seasoning"),
    )
    await queries.set_facet(db_session, "spinach_raw", FacetKey.decay, {"refrigerated_days": 7})
    await queries.set_facet(db_session, "salt", FacetKey.decay, {"pantry_days": 1825})

    await queries.add_ingest_record(
        db_session,
        user_id="alice",
        node_id="spinach_raw",
        acquired_at=datetime(2026, 5, 1, tzinfo=UTC),
        quantity=1.0,
    )
    await queries.add_ingest_record(
        db_session,
        user_id="alice",
        node_id="salt",
        acquired_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    await queries.add_ingest_record(
        db_session,
        user_id="bob",
        node_id="spinach_raw",
        acquired_at=datetime(2026, 5, 1, tzinfo=UTC),
    )
    await db_session.commit()

    return build_server()


class TestSchema:
    async def test_tool_listed(self, server_and_seed) -> None:
        names = [t.name for t in await server_and_seed.list_tools()]
        assert "get_pantry_state" in names

    async def test_input_schema(self, server_and_seed) -> None:
        tool = next(t for t in await server_and_seed.list_tools() if t.name == "get_pantry_state")
        props = tool.inputSchema["properties"]
        assert "user_id" in props
        assert "as_of" in props


class TestCallTool:
    async def test_returns_pantry_for_user(self, server_and_seed) -> None:
        payload = _decode(
            await server_and_seed.call_tool(
                "get_pantry_state",
                {"user_id": "alice", "as_of": "2026-05-05T00:00:00+00:00"},
            )
        )
        assert payload["user_id"] == "alice"
        ids = sorted(i["node_id"] for i in payload["items"])
        assert ids == ["salt", "spinach_raw"]

    async def test_excludes_expired_items(self, server_and_seed) -> None:
        # spinach expires 2026-05-08; querying 2026-05-09 should drop it.
        payload = _decode(
            await server_and_seed.call_tool(
                "get_pantry_state",
                {"user_id": "alice", "as_of": "2026-05-09T00:00:00+00:00"},
            )
        )
        ids = [i["node_id"] for i in payload["items"]]
        assert "spinach_raw" not in ids
        assert "salt" in ids

    async def test_user_isolation(self, server_and_seed) -> None:
        payload = _decode(
            await server_and_seed.call_tool(
                "get_pantry_state",
                {"user_id": "bob", "as_of": "2026-05-05T00:00:00+00:00"},
            )
        )
        ids = [i["node_id"] for i in payload["items"]]
        assert ids == ["spinach_raw"]

    async def test_unknown_user_returns_empty(self, server_and_seed) -> None:
        payload = _decode(
            await server_and_seed.call_tool("get_pantry_state", {"user_id": "nobody"})
        )
        assert payload["items"] == []

    async def test_item_shape(self, server_and_seed) -> None:
        payload = _decode(
            await server_and_seed.call_tool(
                "get_pantry_state",
                {"user_id": "alice", "as_of": "2026-05-05T00:00:00+00:00"},
            )
        )
        for item in payload["items"]:
            assert {
                "record_id",
                "node_id",
                "pref_label",
                "acquired_at",
                "quantity",
                "storage_mode",
                "estimated_expiration",
                "days_until_expiration",
            } <= set(item.keys())

    async def test_default_as_of_is_now(self, server_and_seed) -> None:
        # No as_of: salt was acquired 2026-01-01 and lasts 5 years; today is 2026-05-02.
        payload = _decode(await server_and_seed.call_tool("get_pantry_state", {"user_id": "alice"}))
        ids = [i["node_id"] for i in payload["items"]]
        assert "salt" in ids
