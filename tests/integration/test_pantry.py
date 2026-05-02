"""Integration tests for domain.pantry.compute_pantry_state."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from zeff.db import queries
from zeff.domain.facets import FacetKey
from zeff.domain.nodes import Node, NodeType
from zeff.domain.pantry import StorageMode, compute_pantry_state

pytestmark = pytest.mark.integration


async def _seed(db_session, *foods: tuple[str, str, dict | None]) -> None:
    """Seed (id, parent, decay) tuples. parent='vegetable' or similar."""
    seen_parents: set[str] = set()
    for _, parent, _ in foods:
        if parent in seen_parents:
            continue
        seen_parents.add(parent)
        await queries.create_node(
            db_session, Node(id=parent, type=NodeType.category, pref_label=parent.title())
        )
    for nid, parent, decay in foods:
        await queries.create_node(
            db_session,
            Node(id=nid, type=NodeType.primitive, pref_label=nid.replace("_", " ").title(), parent_id=parent),
        )
        if decay is not None:
            await queries.set_facet(db_session, nid, FacetKey.decay, decay)
    await db_session.commit()


class TestSingleItem:
    async def test_not_yet_expired(self, db_session) -> None:
        await _seed(db_session, ("spinach_raw", "vegetable", {"refrigerated_days": 7}))
        await queries.add_ingest_record(
            db_session,
            user_id="alice",
            node_id="spinach_raw",
            acquired_at=datetime(2026, 5, 1, tzinfo=UTC),
        )
        await db_session.commit()

        items = await compute_pantry_state(db_session, "alice", as_of=datetime(2026, 5, 5, tzinfo=UTC))
        assert len(items) == 1
        item = items[0]
        assert item.node_id == "spinach_raw"
        assert item.estimated_expiration == datetime(2026, 5, 8, tzinfo=UTC)
        assert item.days_until_expiration == 3
        assert item.storage_mode == StorageMode.refrigerated

    async def test_just_expired_excluded(self, db_session) -> None:
        await _seed(db_session, ("spinach_raw", "vegetable", {"refrigerated_days": 7}))
        await queries.add_ingest_record(
            db_session,
            user_id="alice",
            node_id="spinach_raw",
            acquired_at=datetime(2026, 5, 1, tzinfo=UTC),
        )
        await db_session.commit()
        items = await compute_pantry_state(db_session, "alice", as_of=datetime(2026, 5, 9, tzinfo=UTC))
        assert items == []

    async def test_no_decay_treated_as_long_lived(self, db_session) -> None:
        # Items with no decay facet stay in the pantry indefinitely.
        await _seed(db_session, ("mystery_food", "vegetable", None))
        await queries.add_ingest_record(
            db_session,
            user_id="alice",
            node_id="mystery_food",
            acquired_at=datetime(2026, 5, 1, tzinfo=UTC),
        )
        await db_session.commit()
        items = await compute_pantry_state(db_session, "alice", as_of=datetime(2027, 5, 1, tzinfo=UTC))
        assert len(items) == 1
        assert items[0].estimated_expiration is None
        assert items[0].storage_mode is None

    async def test_default_storage_mode_picks_longest_available(self, db_session) -> None:
        # Multiple modes available — pick the longest (frozen > refrigerated > pantry).
        # No, per DESIGN: default storage mode assumed = refrigerated. So when both
        # refrigerated and frozen are present we pick refrigerated unless told otherwise.
        await _seed(
            db_session,
            ("salmon_raw", "seafood", {"refrigerated_days": 2, "frozen_days": 90}),
        )
        await queries.add_ingest_record(
            db_session,
            user_id="alice",
            node_id="salmon_raw",
            acquired_at=datetime(2026, 5, 1, tzinfo=UTC),
        )
        await db_session.commit()
        items = await compute_pantry_state(db_session, "alice", as_of=datetime(2026, 5, 2, tzinfo=UTC))
        assert items[0].storage_mode == StorageMode.refrigerated
        assert items[0].estimated_expiration == datetime(2026, 5, 3, tzinfo=UTC)

    async def test_falls_back_to_only_available_mode(self, db_session) -> None:
        # Salt has only pantry_days — no refrigerated. Use pantry.
        await _seed(db_session, ("salt", "seasoning", {"pantry_days": 1825}))
        await queries.add_ingest_record(
            db_session,
            user_id="alice",
            node_id="salt",
            acquired_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        await db_session.commit()
        items = await compute_pantry_state(db_session, "alice", as_of=datetime(2026, 5, 1, tzinfo=UTC))
        assert items[0].storage_mode == StorageMode.pantry
        assert items[0].days_until_expiration > 1000


class TestMultipleAcquisitions:
    async def test_each_record_is_its_own_pantry_item(self, db_session) -> None:
        await _seed(db_session, ("apple", "fruit", {"refrigerated_days": 30}))
        for day in (1, 5, 10):
            await queries.add_ingest_record(
                db_session,
                user_id="alice",
                node_id="apple",
                acquired_at=datetime(2026, 5, day, tzinfo=UTC),
                quantity=2.0,
            )
        await db_session.commit()

        items = await compute_pantry_state(db_session, "alice", as_of=datetime(2026, 5, 15, tzinfo=UTC))
        assert len(items) == 3
        assert all(i.node_id == "apple" for i in items)
        assert all(i.quantity == 2.0 for i in items)


class TestUserIsolation:
    async def test_alice_does_not_see_bobs_pantry(self, db_session) -> None:
        await _seed(db_session, ("apple", "fruit", {"refrigerated_days": 30}))
        await queries.add_ingest_record(
            db_session, user_id="alice", node_id="apple", acquired_at=datetime(2026, 5, 1, tzinfo=UTC)
        )
        await queries.add_ingest_record(
            db_session, user_id="bob", node_id="apple", acquired_at=datetime(2026, 5, 1, tzinfo=UTC)
        )
        await db_session.commit()

        items = await compute_pantry_state(db_session, "alice", as_of=datetime(2026, 5, 5, tzinfo=UTC))
        assert len(items) == 1


class TestAsOfDefault:
    async def test_default_as_of_is_now(self, db_session) -> None:
        await _seed(db_session, ("apple", "fruit", {"refrigerated_days": 30}))
        await queries.add_ingest_record(
            db_session,
            user_id="alice",
            node_id="apple",
            acquired_at=datetime.now(tz=UTC) - timedelta(days=2),
        )
        await db_session.commit()
        items = await compute_pantry_state(db_session, "alice")
        assert len(items) == 1
        assert items[0].days_until_expiration > 0
