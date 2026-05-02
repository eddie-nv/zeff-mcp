"""Integration tests for ingest_record CRUD."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError

from zeff.db import queries
from zeff.domain.nodes import Node, NodeType

pytestmark = pytest.mark.integration


async def _seed_apple(db_session) -> None:
    await queries.create_node(
        db_session, Node(id="fruit", type=NodeType.category, pref_label="Fruit")
    )
    await queries.create_node(
        db_session, Node(id="apple", type=NodeType.primitive, pref_label="Apple", parent_id="fruit")
    )
    await db_session.commit()


class TestAddIngestRecord:
    async def test_inserts_with_server_generated_id(self, db_session) -> None:
        await _seed_apple(db_session)
        row = await queries.add_ingest_record(
            db_session,
            user_id="alice",
            node_id="apple",
            acquired_at=datetime(2026, 5, 1, 10, 0, tzinfo=UTC),
            quantity=3.0,
            source="receipt:foo",
        )
        await db_session.commit()
        assert row.id is not None
        assert row.user_id == "alice"
        assert row.node_id == "apple"
        assert row.quantity == 3.0
        assert row.source == "receipt:foo"
        assert row.created_at is not None

    async def test_quantity_zero_rejected(self, db_session) -> None:
        await _seed_apple(db_session)
        await queries.add_ingest_record(
            db_session,
            user_id="alice",
            node_id="apple",
            acquired_at=datetime(2026, 5, 1, tzinfo=UTC),
            quantity=0.0,
        )
        with pytest.raises(IntegrityError):
            await db_session.commit()

    async def test_negative_quantity_rejected(self, db_session) -> None:
        await _seed_apple(db_session)
        await queries.add_ingest_record(
            db_session,
            user_id="alice",
            node_id="apple",
            acquired_at=datetime(2026, 5, 1, tzinfo=UTC),
            quantity=-1.0,
        )
        with pytest.raises(IntegrityError):
            await db_session.commit()

    async def test_unknown_node_rejected(self, db_session) -> None:
        await _seed_apple(db_session)
        await queries.add_ingest_record(
            db_session,
            user_id="alice",
            node_id="does_not_exist",
            acquired_at=datetime(2026, 5, 1, tzinfo=UTC),
        )
        with pytest.raises(IntegrityError):
            await db_session.commit()

    async def test_null_quantity_allowed(self, db_session) -> None:
        await _seed_apple(db_session)
        row = await queries.add_ingest_record(
            db_session,
            user_id="alice",
            node_id="apple",
            acquired_at=datetime(2026, 5, 1, tzinfo=UTC),
        )
        await db_session.commit()
        assert row.quantity is None


class TestListIngestRecords:
    async def test_filters_by_user_id(self, db_session) -> None:
        await _seed_apple(db_session)
        for user, n in [("alice", 3), ("bob", 2)]:
            for i in range(n):
                await queries.add_ingest_record(
                    db_session,
                    user_id=user,
                    node_id="apple",
                    acquired_at=datetime(2026, 5, i + 1, tzinfo=UTC),
                )
        await db_session.commit()

        alice_rows = await queries.list_ingest_records(db_session, "alice")
        assert len(alice_rows) == 3
        assert all(r.user_id == "alice" for r in alice_rows)

    async def test_returns_newest_first(self, db_session) -> None:
        await _seed_apple(db_session)
        for i in range(1, 4):
            await queries.add_ingest_record(
                db_session,
                user_id="alice",
                node_id="apple",
                acquired_at=datetime(2026, 5, i, tzinfo=UTC),
            )
        await db_session.commit()

        rows = await queries.list_ingest_records(db_session, "alice")
        dates = [r.acquired_at.day for r in rows]
        assert dates == [3, 2, 1]

    async def test_since_until_bounds(self, db_session) -> None:
        await _seed_apple(db_session)
        base = datetime(2026, 5, 1, tzinfo=UTC)
        for i in range(7):
            await queries.add_ingest_record(
                db_session,
                user_id="alice",
                node_id="apple",
                acquired_at=base + timedelta(days=i),
            )
        await db_session.commit()

        rows = await queries.list_ingest_records(
            db_session,
            "alice",
            since=base + timedelta(days=2),
            until=base + timedelta(days=4),
        )
        assert len(rows) == 3  # day 2, 3, 4

    async def test_unknown_user_returns_empty(self, db_session) -> None:
        await _seed_apple(db_session)
        assert await queries.list_ingest_records(db_session, "nobody") == []
