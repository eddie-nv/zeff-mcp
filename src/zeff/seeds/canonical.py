"""Canonical category seed.

Creates the curated taxonomy tree from DESIGN.md "The category tree".
Idempotent: re-running upserts existing rows by id and inserts only what's
missing.

Run via the CLI:

    python -m zeff.seeds.canonical
"""

from __future__ import annotations

import asyncio
import logging
from typing import TypedDict

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from zeff.config import get_settings
from zeff.db import connection as db_conn
from zeff.db.models import Node

log = logging.getLogger(__name__)


class CategoryEntry(TypedDict):
    id: str
    pref_label: str
    parent_id: str | None
    type: str


# DESIGN.md "The category tree". Single synthetic root `food`, then 8 v1 top-level
# categories, then sub-levels for grain, protein, and dairy.
CANONICAL_TREE: list[CategoryEntry] = [
    {"id": "food", "pref_label": "Food", "parent_id": None, "type": "category"},
    # Top-level categories
    {"id": "fruit", "pref_label": "Fruit", "parent_id": "food", "type": "category"},
    {"id": "vegetable", "pref_label": "Vegetable", "parent_id": "food", "type": "category"},
    {"id": "grain", "pref_label": "Grain", "parent_id": "food", "type": "category"},
    {"id": "protein", "pref_label": "Protein", "parent_id": "food", "type": "category"},
    {"id": "dairy", "pref_label": "Dairy", "parent_id": "food", "type": "category"},
    {"id": "fat_and_oil", "pref_label": "Fat and Oil", "parent_id": "food", "type": "category"},
    {"id": "seasoning", "pref_label": "Seasoning", "parent_id": "food", "type": "category"},
    {"id": "beverage", "pref_label": "Beverage", "parent_id": "food", "type": "category"},
    # Grain sublevel
    {"id": "whole_grain", "pref_label": "Whole Grain", "parent_id": "grain", "type": "category"},
    {
        "id": "refined_grain",
        "pref_label": "Refined Grain",
        "parent_id": "grain",
        "type": "category",
    },
    # Protein sublevel
    {"id": "poultry", "pref_label": "Poultry", "parent_id": "protein", "type": "category"},
    {"id": "red_meat", "pref_label": "Red Meat", "parent_id": "protein", "type": "category"},
    {"id": "seafood", "pref_label": "Seafood", "parent_id": "protein", "type": "category"},
    {"id": "egg", "pref_label": "Egg", "parent_id": "protein", "type": "category"},
    {
        "id": "plant_protein",
        "pref_label": "Plant Protein",
        "parent_id": "protein",
        "type": "category",
    },
    # Dairy sublevel
    {
        "id": "milk_product",
        "pref_label": "Milk Product",
        "parent_id": "dairy",
        "type": "category",
    },
    {"id": "cheese", "pref_label": "Cheese", "parent_id": "dairy", "type": "category"},
    {
        "id": "cultured_dairy",
        "pref_label": "Cultured Dairy",
        "parent_id": "dairy",
        "type": "category",
    },
]


async def seed_canonical(session: AsyncSession) -> int:
    """Idempotently seed the canonical category tree.

    Returns the number of rows inserted (0 if everything was already present).
    Uses `INSERT ... ON CONFLICT (id) DO UPDATE` so a re-run also corrects
    drift in pref_label or parent_id.
    """
    # Insert in two passes so any FK to a not-yet-inserted parent is fine —
    # `food` first, then everything else. ON CONFLICT keeps the call cheap.
    sorted_entries = sorted(CANONICAL_TREE, key=lambda e: 0 if e["parent_id"] is None else 1)

    inserted = 0
    for entry in sorted_entries:
        before = await session.execute(select(Node.id).where(Node.id == entry["id"]))
        existed = before.scalar_one_or_none() is not None

        stmt = insert(Node).values(**entry)
        stmt = stmt.on_conflict_do_update(
            index_elements=[Node.id],
            set_={
                "pref_label": stmt.excluded.pref_label,
                "parent_id": stmt.excluded.parent_id,
                "type": stmt.excluded.type,
            },
        )
        await session.execute(stmt)
        if not existed:
            inserted += 1

    return inserted


async def _amain() -> int:
    logging.basicConfig(level=get_settings().log_level)
    db_conn.configure_engine(get_settings().database_url)
    async with db_conn.session_scope() as session:
        n = await seed_canonical(session)
    log.info("canonical seed complete: %d new node(s)", n)
    return 0


def main() -> int:
    return asyncio.run(_amain())


if __name__ == "__main__":
    raise SystemExit(main())
