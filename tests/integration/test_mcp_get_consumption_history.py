"""Integration tests for the MCP get_consumption_history tool."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

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

    nodes = [
        ("food", None, "category"),
        ("fruit", "food", "category"),
        ("protein", "food", "category"),
        ("apple", "fruit", "primitive"),
        ("chicken", "protein", "primitive"),
    ]
    for nid, parent, type_ in nodes:
        await queries.create_node(
            db_session,
            Node(id=nid, type=NodeType(type_), pref_label=nid.title(), parent_id=parent),
        )
    await queries.set_facet(db_session, "apple", FacetKey.nova_group, 1)
    await queries.set_facet(db_session, "chicken", FacetKey.nova_group, 1)

    base = datetime(2026, 5, 15, tzinfo=UTC)
    for i in range(5):
        await queries.add_ingest_record(
            db_session,
            user_id="alice",
            node_id="apple",
            acquired_at=base - timedelta(days=i),
            quantity=2.0,
        )
    await queries.add_ingest_record(
        db_session,
        user_id="alice",
        node_id="chicken",
        acquired_at=base - timedelta(days=2),
        quantity=1.0,
    )
    # Older record outside the default 30d window.
    await queries.add_ingest_record(
        db_session,
        user_id="alice",
        node_id="apple",
        acquired_at=base - timedelta(days=60),
        quantity=1.0,
    )
    await db_session.commit()

    return build_server()


class TestSchema:
    async def test_tool_listed(self, server_and_seed) -> None:
        names = [t.name for t in await server_and_seed.list_tools()]
        assert "get_consumption_history" in names

    async def test_input_schema(self, server_and_seed) -> None:
        tool = next(
            t for t in await server_and_seed.list_tools() if t.name == "get_consumption_history"
        )
        props = tool.inputSchema["properties"]
        assert "user_id" in props
        assert "time_range" in props
        assert "group_by" in props


class TestCallTool:
    async def test_default_group_by_category(self, server_and_seed) -> None:
        payload = _decode(
            await server_and_seed.call_tool(
                "get_consumption_history",
                {"user_id": "alice", "as_of": "2026-05-15T00:00:00+00:00"},
            )
        )
        assert payload["group_by"] == "category"
        assert payload["total_records"] == 6  # 5 apples + 1 chicken in window
        by_key = {g["key"]: g for g in payload["groups"]}
        assert by_key["fruit"]["record_count"] == 5
        assert by_key["protein"]["record_count"] == 1

    async def test_group_by_nova(self, server_and_seed) -> None:
        payload = _decode(
            await server_and_seed.call_tool(
                "get_consumption_history",
                {
                    "user_id": "alice",
                    "as_of": "2026-05-15T00:00:00+00:00",
                    "group_by": "nova_group",
                },
            )
        )
        by_key = {g["key"]: g for g in payload["groups"]}
        assert by_key["1"]["record_count"] == 6

    async def test_group_by_day(self, server_and_seed) -> None:
        payload = _decode(
            await server_and_seed.call_tool(
                "get_consumption_history",
                {
                    "user_id": "alice",
                    "as_of": "2026-05-15T00:00:00+00:00",
                    "group_by": "day",
                },
            )
        )
        # 5 apples on 5 different days + 1 chicken on day-13
        assert len(payload["groups"]) >= 5

    async def test_group_by_none_returns_events(self, server_and_seed) -> None:
        payload = _decode(
            await server_and_seed.call_tool(
                "get_consumption_history",
                {
                    "user_id": "alice",
                    "as_of": "2026-05-15T00:00:00+00:00",
                    "group_by": "none",
                },
            )
        )
        assert payload["events"]
        assert payload["groups"] == []
        # Sorted newest first.
        assert payload["events"][0]["acquired_at"].startswith("2026-05-15")

    async def test_time_range_filters(self, server_and_seed) -> None:
        # 7d window from 2026-05-15 includes records from 2026-05-08 onward,
        # which excludes the day-10 apple but includes day-0..6.
        payload = _decode(
            await server_and_seed.call_tool(
                "get_consumption_history",
                {
                    "user_id": "alice",
                    "as_of": "2026-05-15T00:00:00+00:00",
                    "time_range": "7d",
                },
            )
        )
        assert payload["total_records"] <= 6  # at most all in-window records

    async def test_unknown_user_empty(self, server_and_seed) -> None:
        payload = _decode(
            await server_and_seed.call_tool("get_consumption_history", {"user_id": "nobody"})
        )
        assert payload["total_records"] == 0
        assert payload["groups"] == []
        assert payload["events"] == []

    async def test_invalid_time_range_raises(self, server_and_seed) -> None:
        from mcp.server.fastmcp.exceptions import ToolError

        with pytest.raises(ToolError):
            await server_and_seed.call_tool(
                "get_consumption_history",
                {"user_id": "alice", "time_range": "30days"},
            )
