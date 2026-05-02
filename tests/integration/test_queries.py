"""Integration tests for db/queries.py against a real Postgres."""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

from zeff.db import queries
from zeff.db.models import Node, NodeExternalId, NodeFacet
from zeff.domain.facets import FacetKey, InvalidFacetError
from zeff.domain.nodes import Node as NodeModel
from zeff.domain.nodes import NodeType

pytestmark = pytest.mark.integration


def _node(node_id: str, **overrides: object) -> NodeModel:
    base = {
        "id": node_id,
        "type": NodeType.primitive,
        "pref_label": node_id.replace("_", " ").title(),
    }
    base.update(overrides)
    return NodeModel(**base)  # type: ignore[arg-type]


class TestCreateNode:
    async def test_creates_and_returns_id(self, db_session) -> None:
        n = _node("apple")
        await queries.create_node(db_session, n)
        await db_session.commit()

        fetched = await db_session.get(Node, "apple")
        assert fetched is not None
        assert fetched.pref_label == "Apple"
        assert fetched.type == "primitive"

    async def test_creates_with_alt_labels(self, db_session) -> None:
        n = _node("honeycrisp_apple", alt_labels=["honeycrisp", "hc apple"])
        await queries.create_node(db_session, n)
        await db_session.commit()

        fetched = await db_session.get(Node, "honeycrisp_apple")
        assert fetched is not None
        assert fetched.alt_labels == ["honeycrisp", "hc apple"]

    async def test_duplicate_id_raises(self, db_session) -> None:
        await queries.create_node(db_session, _node("dup"))
        await db_session.commit()
        await queries.create_node(db_session, _node("dup"))
        with pytest.raises(IntegrityError):
            await db_session.commit()


class TestGetNode:
    async def test_returns_existing(self, db_session) -> None:
        await queries.create_node(db_session, _node("celery"))
        await db_session.commit()
        got = await queries.get_node(db_session, "celery")
        assert got is not None
        assert got.id == "celery"

    async def test_returns_none_for_missing(self, db_session) -> None:
        assert await queries.get_node(db_session, "does_not_exist") is None


class TestSetParent:
    async def test_sets_parent(self, db_session) -> None:
        await queries.create_node(db_session, _node("fruit", type=NodeType.category))
        await queries.create_node(db_session, _node("apple"))
        await db_session.commit()

        await queries.set_parent(db_session, "apple", "fruit")
        await db_session.commit()

        got = await queries.get_node(db_session, "apple")
        assert got is not None
        assert got.parent_id == "fruit"

    async def test_clear_parent(self, db_session) -> None:
        await queries.create_node(db_session, _node("fruit", type=NodeType.category))
        await queries.create_node(db_session, _node("apple", parent_id="fruit"))
        await db_session.commit()

        await queries.set_parent(db_session, "apple", None)
        await db_session.commit()
        got = await queries.get_node(db_session, "apple")
        assert got is not None
        assert got.parent_id is None

    async def test_unknown_parent_raises_fk(self, db_session) -> None:
        await queries.create_node(db_session, _node("apple"))
        await db_session.commit()
        await queries.set_parent(db_session, "apple", "does_not_exist")
        with pytest.raises(IntegrityError):
            await db_session.commit()


class TestSetFacet:
    async def test_set_then_get(self, db_session) -> None:
        await queries.create_node(db_session, _node("apple"))
        await db_session.commit()

        await queries.set_facet(db_session, "apple", FacetKey.nova_group, 1)
        await queries.set_facet(
            db_session, "apple", FacetKey.dietary_flags, ["vegan", "gluten_free"]
        )
        await db_session.commit()

        facets = await queries.get_facets(db_session, "apple")
        assert facets[FacetKey.nova_group] == 1
        assert facets[FacetKey.dietary_flags] == ["vegan", "gluten_free"]

    async def test_set_overwrites_same_key(self, db_session) -> None:
        await queries.create_node(db_session, _node("apple"))
        await queries.set_facet(db_session, "apple", FacetKey.nova_group, 1)
        await db_session.commit()
        await queries.set_facet(db_session, "apple", FacetKey.nova_group, 2)
        await db_session.commit()

        facets = await queries.get_facets(db_session, "apple")
        assert facets[FacetKey.nova_group] == 2

    async def test_invalid_facet_value_raises(self, db_session) -> None:
        await queries.create_node(db_session, _node("apple"))
        await db_session.commit()
        with pytest.raises(InvalidFacetError):
            await queries.set_facet(db_session, "apple", FacetKey.nova_group, 99)

    async def test_get_facets_empty(self, db_session) -> None:
        await queries.create_node(db_session, _node("apple"))
        await db_session.commit()
        assert await queries.get_facets(db_session, "apple") == {}


class TestAddExternalId:
    async def test_add_and_lookup(self, db_session) -> None:
        await queries.create_node(db_session, _node("apple"))
        await db_session.commit()
        await queries.add_external_id(db_session, "apple", "usda_sr", "171688")
        await db_session.commit()

        rows = (
            await db_session.execute(
                NodeExternalId.__table__.select().where(NodeExternalId.node_id == "apple")
            )
        ).all()
        assert len(rows) == 1
        assert rows[0].source == "usda_sr"
        assert rows[0].external_id == "171688"

    async def test_duplicate_source_external_id_raises(self, db_session) -> None:
        await queries.create_node(db_session, _node("apple"))
        await db_session.commit()
        await queries.add_external_id(db_session, "apple", "usda_sr", "171688")
        await db_session.commit()
        await queries.create_node(db_session, _node("apple_two"))
        await db_session.commit()
        # Same (source, external_id) collides with the existing PK.
        await queries.add_external_id(db_session, "apple_two", "usda_sr", "171688")
        with pytest.raises(IntegrityError):
            await db_session.commit()


class TestCascade:
    async def test_deleting_node_cascades_facets_and_externals(self, db_session) -> None:
        await queries.create_node(db_session, _node("apple"))
        await queries.set_facet(db_session, "apple", FacetKey.nova_group, 1)
        await queries.add_external_id(db_session, "apple", "usda_sr", "171688")
        await db_session.commit()

        node = await db_session.get(Node, "apple")
        assert node is not None
        await db_session.delete(node)
        await db_session.commit()

        # Both child rows must be gone.
        facets = (await db_session.execute(NodeFacet.__table__.select())).all()
        externals = (await db_session.execute(NodeExternalId.__table__.select())).all()
        assert facets == []
        assert externals == []
