"""Integration tests for domain.history.get_consumption_history."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from zeff.db import queries
from zeff.domain.facets import FacetKey
from zeff.domain.history import GroupBy, get_consumption_history, parse_time_range
from zeff.domain.nodes import Node, NodeType

pytestmark = pytest.mark.integration


async def _seed_tree(db_session) -> None:
    """food → fruit, vegetable, protein → poultry → chicken_breast_raw."""
    nodes = [
        ("food", None, "category"),
        ("fruit", "food", "category"),
        ("vegetable", "food", "category"),
        ("protein", "food", "category"),
        ("poultry", "protein", "category"),
        ("apple", "fruit", "primitive"),
        ("spinach", "vegetable", "primitive"),
        ("chicken_breast_raw", "poultry", "primitive"),
    ]
    for nid, parent, type_ in nodes:
        await queries.create_node(
            db_session,
            Node(id=nid, type=NodeType(type_), pref_label=nid.title(), parent_id=parent),
        )
    # NOVA: apple=1, spinach=1, chicken=1.
    for nid in ("apple", "spinach", "chicken_breast_raw"):
        await queries.set_facet(db_session, nid, FacetKey.nova_group, 1)
    await db_session.commit()


async def _ingest(db_session, *records: tuple[str, str, datetime, float]) -> None:
    for user, nid, when, qty in records:
        await queries.add_ingest_record(
            db_session, user_id=user, node_id=nid, acquired_at=when, quantity=qty
        )
    await db_session.commit()


class TestParseTimeRange:
    @pytest.mark.parametrize(
        "spec,days",
        [("7d", 7), ("30d", 30), ("90d", 90), ("365d", 365), ("1d", 1)],
    )
    def test_valid(self, spec: str, days: int) -> None:
        assert parse_time_range(spec) == timedelta(days=days)

    @pytest.mark.parametrize("spec", ["", "abc", "30", "30days", "-7d", "0d", "30h"])
    def test_invalid(self, spec: str) -> None:
        with pytest.raises(ValueError):
            parse_time_range(spec)


class TestGroupByNone:
    async def test_returns_raw_events(self, db_session) -> None:
        await _seed_tree(db_session)
        as_of = datetime(2026, 5, 15, tzinfo=UTC)
        await _ingest(
            db_session,
            ("alice", "apple", as_of - timedelta(days=2), 3.0),
            ("alice", "spinach", as_of - timedelta(days=5), 1.0),
            ("alice", "chicken_breast_raw", as_of - timedelta(days=10), 2.0),
        )

        result = await get_consumption_history(
            db_session, "alice", time_range="30d", group_by=GroupBy.none, as_of=as_of
        )
        assert len(result.events) == 3
        # Newest first
        assert result.events[0].node_id == "apple"
        assert result.groups == []
        assert result.total_records == 3

    async def test_time_range_excludes_old_events(self, db_session) -> None:
        await _seed_tree(db_session)
        as_of = datetime(2026, 5, 15, tzinfo=UTC)
        await _ingest(
            db_session,
            ("alice", "apple", as_of - timedelta(days=2), 1.0),
            ("alice", "apple", as_of - timedelta(days=40), 1.0),  # outside 30d
        )
        result = await get_consumption_history(
            db_session, "alice", time_range="30d", group_by=GroupBy.none, as_of=as_of
        )
        assert result.total_records == 1


class TestGroupByCategory:
    async def test_aggregates_by_top_level_category(self, db_session) -> None:
        await _seed_tree(db_session)
        as_of = datetime(2026, 5, 15, tzinfo=UTC)
        await _ingest(
            db_session,
            ("alice", "apple", as_of - timedelta(days=1), 2.0),
            ("alice", "apple", as_of - timedelta(days=2), 1.0),
            ("alice", "spinach", as_of - timedelta(days=3), 1.0),
            ("alice", "chicken_breast_raw", as_of - timedelta(days=4), 2.0),
        )
        result = await get_consumption_history(
            db_session, "alice", time_range="30d", group_by=GroupBy.category, as_of=as_of
        )
        by_key = {g.key: g for g in result.groups}
        assert sorted(by_key.keys()) == ["fruit", "protein", "vegetable"]
        assert by_key["fruit"].record_count == 2
        assert by_key["fruit"].total_quantity == 3.0
        assert by_key["protein"].record_count == 1
        assert by_key["vegetable"].record_count == 1


class TestGroupByNovaGroup:
    async def test_aggregates_by_nova(self, db_session) -> None:
        await _seed_tree(db_session)
        # Add a NOVA-3 food.
        await queries.create_node(
            db_session,
            Node(
                id="cheese_singles",
                type=NodeType.primitive,
                pref_label="Cheese Singles",
                parent_id="food",
            ),
        )
        await queries.set_facet(db_session, "cheese_singles", FacetKey.nova_group, 3)
        await db_session.commit()

        as_of = datetime(2026, 5, 15, tzinfo=UTC)
        await _ingest(
            db_session,
            ("alice", "apple", as_of - timedelta(days=1), 1.0),
            ("alice", "spinach", as_of - timedelta(days=2), 1.0),
            ("alice", "cheese_singles", as_of - timedelta(days=3), 5.0),
        )
        result = await get_consumption_history(
            db_session, "alice", time_range="30d", group_by=GroupBy.nova_group, as_of=as_of
        )
        by_key = {g.key: g for g in result.groups}
        assert by_key["1"].record_count == 2
        assert by_key["3"].record_count == 1
        assert by_key["3"].total_quantity == 5.0

    async def test_unknown_nova_bucketed_as_unknown(self, db_session) -> None:
        await _seed_tree(db_session)
        # Node with no nova_group facet.
        await queries.create_node(
            db_session,
            Node(id="mystery", type=NodeType.primitive, pref_label="Mystery", parent_id="food"),
        )
        await db_session.commit()
        as_of = datetime(2026, 5, 15, tzinfo=UTC)
        await _ingest(db_session, ("alice", "mystery", as_of - timedelta(days=1), 1.0))
        result = await get_consumption_history(
            db_session, "alice", time_range="30d", group_by=GroupBy.nova_group, as_of=as_of
        )
        keys = {g.key for g in result.groups}
        assert "unknown" in keys


class TestGroupByDay:
    async def test_buckets_by_calendar_day(self, db_session) -> None:
        await _seed_tree(db_session)
        as_of = datetime(2026, 5, 15, 23, 0, tzinfo=UTC)
        await _ingest(
            db_session,
            ("alice", "apple", datetime(2026, 5, 14, 9, tzinfo=UTC), 1.0),
            ("alice", "apple", datetime(2026, 5, 14, 18, tzinfo=UTC), 1.0),
            ("alice", "spinach", datetime(2026, 5, 13, 12, tzinfo=UTC), 1.0),
        )
        result = await get_consumption_history(
            db_session, "alice", time_range="30d", group_by=GroupBy.day, as_of=as_of
        )
        by_key = {g.key: g for g in result.groups}
        assert by_key["2026-05-14"].record_count == 2
        assert by_key["2026-05-13"].record_count == 1


class TestUserIsolation:
    async def test_only_returns_target_user(self, db_session) -> None:
        await _seed_tree(db_session)
        as_of = datetime(2026, 5, 15, tzinfo=UTC)
        await _ingest(
            db_session,
            ("alice", "apple", as_of - timedelta(days=1), 1.0),
            ("bob", "apple", as_of - timedelta(days=1), 5.0),
        )
        result = await get_consumption_history(
            db_session, "alice", time_range="30d", group_by=GroupBy.none, as_of=as_of
        )
        assert result.total_records == 1
        assert result.events[0].quantity == 1.0


class TestEmpty:
    async def test_no_records(self, db_session) -> None:
        await _seed_tree(db_session)
        result = await get_consumption_history(
            db_session,
            "alice",
            time_range="30d",
            group_by=GroupBy.category,
            as_of=datetime(2026, 5, 15, tzinfo=UTC),
        )
        assert result.total_records == 0
        assert result.groups == []
        assert result.events == []
