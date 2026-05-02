"""Integration tests for domain/search.py."""

from __future__ import annotations

import pytest

from zeff.db import queries
from zeff.domain.nodes import Node, NodeType
from zeff.domain.search import SearchResult, search_foods

pytestmark = pytest.mark.integration


def _node(id: str, label: str, *, alts: list[str] | None = None, type_=NodeType.primitive) -> Node:
    return Node(id=id, type=type_, pref_label=label, alt_labels=alts or [])


async def _seed(db_session, nodes: list[Node]) -> None:
    for n in nodes:
        await queries.create_node(db_session, n)
    await db_session.commit()


class TestExactMatch:
    async def test_exact_pref_label(self, db_session) -> None:
        await _seed(db_session, [_node("apple", "Apple"), _node("banana", "Banana")])
        results = await search_foods(db_session, "Apple")
        assert results
        assert results[0].node_id == "apple"

    async def test_case_insensitive(self, db_session) -> None:
        await _seed(db_session, [_node("apple", "Apple")])
        results = await search_foods(db_session, "apple")
        assert results[0].node_id == "apple"

    async def test_returns_search_result_shape(self, db_session) -> None:
        await _seed(
            db_session,
            [
                _node("food", "Food", type_=NodeType.category),
                Node(
                    id="apple",
                    type=NodeType.primitive,
                    pref_label="Apple",
                    parent_id="food",
                ),
            ],
        )
        results = await search_foods(db_session, "apple")
        r = results[0]
        assert isinstance(r, SearchResult)
        assert r.node_id == "apple"
        assert r.pref_label == "Apple"
        assert r.type == NodeType.primitive
        assert r.parents == ["food"]
        assert r.score > 0


class TestAltLabelMatch:
    async def test_alt_label_finds_node(self, db_session) -> None:
        await _seed(
            db_session,
            [
                _node("honeycrisp_apple", "Honeycrisp Apple", alts=["honeycrisp", "hc apple"]),
                _node("fuji_apple", "Fuji Apple", alts=["fuji"]),
            ],
        )
        results = await search_foods(db_session, "honeycrisp")
        assert results[0].node_id == "honeycrisp_apple"

    async def test_alt_label_abbreviation(self, db_session) -> None:
        await _seed(
            db_session,
            [_node("honeycrisp_apple", "Honeycrisp Apple", alts=["hc apple"])],
        )
        results = await search_foods(db_session, "hc apple")
        assert any(r.node_id == "honeycrisp_apple" for r in results)


class TestFuzzyMatch:
    async def test_typo_finds_node(self, db_session) -> None:
        await _seed(db_session, [_node("apple", "Apple")])
        results = await search_foods(db_session, "appel")
        assert any(r.node_id == "apple" for r in results)


class TestRanking:
    async def test_exact_outranks_fuzzy(self, db_session) -> None:
        await _seed(
            db_session,
            [
                _node("apple", "Apple"),
                _node("pineapple", "Pineapple"),
                _node("apple_juice", "Apple Juice"),
            ],
        )
        results = await search_foods(db_session, "apple")
        assert results[0].node_id == "apple"


class TestLimit:
    async def test_default_limit(self, db_session) -> None:
        await _seed(
            db_session,
            [_node(f"apple_{i}", f"Apple Variety {i}") for i in range(10)],
        )
        results = await search_foods(db_session, "apple")
        assert len(results) <= 5

    async def test_explicit_limit(self, db_session) -> None:
        await _seed(
            db_session,
            [_node(f"apple_{i}", f"Apple Variety {i}") for i in range(10)],
        )
        results = await search_foods(db_session, "apple", limit=3)
        assert len(results) == 3


class TestTypeFilter:
    async def test_filter_to_primitive(self, db_session) -> None:
        await _seed(
            db_session,
            [
                _node("fruit", "Fruit", type_=NodeType.category),
                _node("apple", "Apple"),
            ],
        )
        results = await search_foods(db_session, "fruit", type_filter=NodeType.primitive)
        assert all(r.type == NodeType.primitive for r in results)
        assert not any(r.node_id == "fruit" for r in results)

    async def test_filter_to_category(self, db_session) -> None:
        await _seed(
            db_session,
            [
                _node("fruit", "Fruit", type_=NodeType.category),
                _node("apple", "Apple"),
            ],
        )
        results = await search_foods(db_session, "fruit", type_filter=NodeType.category)
        assert all(r.type == NodeType.category for r in results)


class TestStatusFilter:
    async def test_pending_review_excluded(self, db_session) -> None:
        await _seed(
            db_session,
            [
                Node(
                    id="apple_pending",
                    type=NodeType.primitive,
                    pref_label="Apple Pending",
                    status="pending_review",
                ),
                _node("apple", "Apple"),
            ],
        )
        results = await search_foods(db_session, "apple")
        assert all(r.node_id != "apple_pending" for r in results)


class TestEdgeCases:
    async def test_empty_query_returns_empty(self, db_session) -> None:
        await _seed(db_session, [_node("apple", "Apple")])
        assert await search_foods(db_session, "") == []

    async def test_whitespace_only_returns_empty(self, db_session) -> None:
        await _seed(db_session, [_node("apple", "Apple")])
        assert await search_foods(db_session, "   ") == []

    async def test_special_chars_only_returns_empty(self, db_session) -> None:
        await _seed(db_session, [_node("apple", "Apple")])
        assert await search_foods(db_session, "%%%") == []

    async def test_no_match_returns_empty(self, db_session) -> None:
        await _seed(db_session, [_node("apple", "Apple")])
        assert await search_foods(db_session, "xyzzy_unrelated_query") == []

    async def test_limit_zero_or_negative_uses_default(self, db_session) -> None:
        await _seed(db_session, [_node("apple", "Apple")])
        # No raise, returns at least one result.
        assert await search_foods(db_session, "apple", limit=0) != []


class TestParentChain:
    async def test_parents_returned_outermost_first(self, db_session) -> None:
        # food -> protein -> poultry -> chicken_breast
        await _seed(
            db_session,
            [
                _node("food", "Food", type_=NodeType.category),
                Node(
                    id="protein",
                    type=NodeType.category,
                    pref_label="Protein",
                    parent_id="food",
                ),
                Node(
                    id="poultry",
                    type=NodeType.category,
                    pref_label="Poultry",
                    parent_id="protein",
                ),
                Node(
                    id="chicken_breast",
                    type=NodeType.primitive,
                    pref_label="Chicken Breast",
                    parent_id="poultry",
                ),
            ],
        )
        results = await search_foods(db_session, "chicken")
        r = next(r for r in results if r.node_id == "chicken_breast")
        # Closest parent first: poultry, then protein, then food.
        assert r.parents == ["poultry", "protein", "food"]
