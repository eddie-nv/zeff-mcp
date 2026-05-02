"""Integration tests for component CRUD in db/queries.py."""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

from zeff.db import queries
from zeff.domain.nodes import Node, NodeType

pytestmark = pytest.mark.integration


async def _seed_minimal(db_session) -> None:
    await queries.create_node(
        db_session, Node(id="cheese", type=NodeType.category, pref_label="Cheese")
    )
    await queries.create_node(
        db_session, Node(id="vegetable", type=NodeType.category, pref_label="Vegetable")
    )
    await queries.create_node(
        db_session,
        Node(
            id="frozen_pizza",
            type=NodeType.composite,
            pref_label="Frozen Cheese Pizza",
            parent_id=None,
        ),
    )
    await queries.create_node(
        db_session,
        Node(id="mozzarella", type=NodeType.primitive, pref_label="Mozzarella", parent_id="cheese"),
    )
    await queries.create_node(
        db_session,
        Node(id="tomato_raw", type=NodeType.primitive, pref_label="Tomato", parent_id="vegetable"),
    )
    await db_session.commit()


class TestAddComponent:
    async def test_add_and_list(self, db_session) -> None:
        await _seed_minimal(db_session)
        await queries.add_component(
            db_session,
            "frozen_pizza",
            "mozzarella",
            grams_per_serving=40.0,
            position=0,
            is_primary=True,
        )
        await queries.add_component(
            db_session, "frozen_pizza", "tomato_raw", grams_per_serving=25.0, position=1
        )
        await db_session.commit()

        comps = await queries.get_components(db_session, "frozen_pizza")
        assert len(comps) == 2
        assert comps[0].component_id == "mozzarella"
        assert comps[0].is_primary is True
        assert comps[0].grams_per_serving == 40.0
        assert comps[1].component_id == "tomato_raw"
        assert comps[1].is_primary is False

    async def test_unknown_composite_raises_fk(self, db_session) -> None:
        await _seed_minimal(db_session)
        await queries.add_component(db_session, "no_such_composite", "mozzarella")
        with pytest.raises(IntegrityError):
            await db_session.commit()

    async def test_unknown_component_raises_fk(self, db_session) -> None:
        await _seed_minimal(db_session)
        await queries.add_component(db_session, "frozen_pizza", "no_such_component")
        with pytest.raises(IntegrityError):
            await db_session.commit()

    async def test_duplicate_edge_raises(self, db_session) -> None:
        await _seed_minimal(db_session)
        await queries.add_component(db_session, "frozen_pizza", "mozzarella")
        await db_session.commit()
        await queries.add_component(db_session, "frozen_pizza", "mozzarella")
        with pytest.raises(IntegrityError):
            await db_session.commit()

    async def test_negative_grams_rejected(self, db_session) -> None:
        await _seed_minimal(db_session)
        await queries.add_component(
            db_session, "frozen_pizza", "mozzarella", grams_per_serving=-5.0
        )
        with pytest.raises(IntegrityError):
            await db_session.commit()

    async def test_only_one_primary_per_composite(self, db_session) -> None:
        await _seed_minimal(db_session)
        await queries.add_component(db_session, "frozen_pizza", "mozzarella", is_primary=True)
        await db_session.commit()
        await queries.add_component(db_session, "frozen_pizza", "tomato_raw", is_primary=True)
        with pytest.raises(IntegrityError):
            await db_session.commit()


class TestCascade:
    async def test_deleting_composite_cascades_components(self, db_session) -> None:
        await _seed_minimal(db_session)
        await queries.add_component(db_session, "frozen_pizza", "mozzarella")
        await db_session.commit()

        await queries.delete_node(db_session, "frozen_pizza")
        await db_session.commit()

        comps = await queries.get_components(db_session, "frozen_pizza")
        assert comps == []

    async def test_deleting_component_in_use_blocked(self, db_session) -> None:
        await _seed_minimal(db_session)
        await queries.add_component(db_session, "frozen_pizza", "mozzarella")
        await db_session.commit()

        # delete_node issues DELETE immediately, so the FK violation surfaces
        # at the call (not at the next commit).
        with pytest.raises(IntegrityError):
            await queries.delete_node(db_session, "mozzarella")


class TestGetComponentsEmpty:
    async def test_returns_empty_list_for_no_components(self, db_session) -> None:
        await _seed_minimal(db_session)
        assert await queries.get_components(db_session, "frozen_pizza") == []

    async def test_returns_empty_for_unknown_composite(self, db_session) -> None:
        # No FK on the read side; just returns empty.
        assert await queries.get_components(db_session, "does_not_exist") == []
