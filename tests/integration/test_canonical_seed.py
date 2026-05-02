"""Integration tests for the canonical category seed."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from zeff.db.models import Node
from zeff.seeds.canonical import CANONICAL_TREE, seed_canonical

pytestmark = pytest.mark.integration


async def _all_node_ids(db_session) -> set[str]:
    rows = (await db_session.execute(select(Node.id))).all()
    return {row[0] for row in rows}


class TestCanonicalTreeShape:
    def test_top_level_categories(self) -> None:
        top = {entry["id"] for entry in CANONICAL_TREE if entry["parent_id"] is None}
        # All v1 top-level categories from DESIGN.md, plus the synthetic root.
        assert top == {
            "food",
        }

    def test_root_food_has_8_children(self) -> None:
        children = {entry["id"] for entry in CANONICAL_TREE if entry["parent_id"] == "food"}
        assert children == {
            "fruit",
            "vegetable",
            "grain",
            "protein",
            "dairy",
            "fat_and_oil",
            "seasoning",
            "beverage",
        }

    def test_protein_subcategories(self) -> None:
        children = {entry["id"] for entry in CANONICAL_TREE if entry["parent_id"] == "protein"}
        assert children == {"poultry", "red_meat", "seafood", "egg", "plant_protein"}

    def test_grain_subcategories(self) -> None:
        children = {entry["id"] for entry in CANONICAL_TREE if entry["parent_id"] == "grain"}
        assert children == {"whole_grain", "refined_grain"}

    def test_dairy_subcategories(self) -> None:
        children = {entry["id"] for entry in CANONICAL_TREE if entry["parent_id"] == "dairy"}
        assert children == {"milk_product", "cheese", "cultured_dairy"}

    def test_all_entries_are_categories(self) -> None:
        assert all(entry["type"] == "category" for entry in CANONICAL_TREE)

    def test_parent_ids_resolve(self) -> None:
        ids = {entry["id"] for entry in CANONICAL_TREE}
        for entry in CANONICAL_TREE:
            parent = entry["parent_id"]
            if parent is not None:
                assert parent in ids, f"{entry['id']} -> unknown parent {parent}"


class TestSeedExecution:
    async def test_seed_creates_all_nodes(self, db_session) -> None:
        await seed_canonical(db_session)
        await db_session.commit()
        ids = await _all_node_ids(db_session)
        expected = {entry["id"] for entry in CANONICAL_TREE}
        assert ids == expected

    async def test_seed_is_idempotent(self, db_session) -> None:
        await seed_canonical(db_session)
        await db_session.commit()
        first = await _all_node_ids(db_session)

        await seed_canonical(db_session)
        await db_session.commit()
        second = await _all_node_ids(db_session)

        assert first == second
        # No duplicate-PK errors and no extra rows.

    async def test_parents_are_set(self, db_session) -> None:
        await seed_canonical(db_session)
        await db_session.commit()

        rows = (await db_session.execute(select(Node.id, Node.parent_id))).all()
        by_id = {r.id: r.parent_id for r in rows}
        assert by_id["food"] is None
        assert by_id["fruit"] == "food"
        assert by_id["poultry"] == "protein"
        assert by_id["whole_grain"] == "grain"
        assert by_id["cheese"] == "dairy"
