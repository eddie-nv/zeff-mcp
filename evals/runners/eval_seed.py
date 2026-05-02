"""Reference data for the v2 baseline search eval.

Seeds the 11 v1 reference foods from DESIGN.md plus the categories they
need as parents. Idempotent. Used by run_search_eval.py — not a
production seed (M3 USDA SR will replace this).
"""

from __future__ import annotations

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from zeff.db.models import Node
from zeff.seeds.canonical import seed_canonical

# Each entry: (id, pref_label, parent_id, [alt_labels])
REFERENCE_FOODS: list[tuple[str, str, str, list[str]]] = [
    ("apple", "Apple", "fruit", []),
    ("honeycrisp_apple", "Honeycrisp Apple", "apple", ["honeycrisp", "hc apple"]),
    ("fuji_apple", "Fuji Apple", "apple", ["fuji"]),
    ("spinach_raw", "Spinach (Raw)", "vegetable", ["spinach", "baby spinach", "spinach leaves"]),
    ("celery_raw", "Celery (Raw)", "vegetable", ["celery", "celery stalks", "celery sticks"]),
    ("potato_raw", "Potato (Raw)", "vegetable", ["potato", "potatoes", "white potato"]),
    (
        "chicken_breast_raw",
        "Chicken Breast (Raw)",
        "poultry",
        ["chicken breast", "boneless skinless chicken breast"],
    ),
    (
        "chicken_whole_raw",
        "Whole Chicken (Raw)",
        "poultry",
        ["whole chicken", "roaster", "fryer"],
    ),
    (
        "chicken_leg_raw",
        "Chicken Leg (Raw)",
        "poultry",
        ["chicken leg", "chicken legs", "chicken drumstick and thigh", "leg quarter"],
    ),
    (
        "salt",
        "Salt",
        "seasoning",
        ["table salt", "sodium chloride", "sea salt", "kosher salt"],
    ),
    (
        "salmon_raw",
        "Salmon (Raw)",
        "seafood",
        ["salmon", "salmon fillet", "fresh salmon"],
    ),
    (
        "ny_strip_steak_raw",
        "NY Strip Steak (Raw)",
        "red_meat",
        [
            "ny steak",
            "new york strip",
            "strip steak",
            "ambassador steak",
            "kansas city strip",
        ],
    ),
]


async def seed_reference_foods(session: AsyncSession) -> int:
    """Insert/upsert the 11 reference primitives + the `apple` parent.

    Assumes seed_canonical has already populated the category tree.
    """
    await seed_canonical(session)

    inserted = 0
    for node_id, label, parent_id, alts in REFERENCE_FOODS:
        # `apple` is a category (children: honeycrisp, fuji); the rest are primitives.
        type_ = "category" if node_id == "apple" else "primitive"
        stmt = insert(Node).values(
            id=node_id,
            type=type_,
            pref_label=label,
            alt_labels=alts or None,
            parent_id=parent_id,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[Node.id],
            set_={
                "pref_label": stmt.excluded.pref_label,
                "alt_labels": stmt.excluded.alt_labels,
                "parent_id": stmt.excluded.parent_id,
                "type": stmt.excluded.type,
            },
        )
        await session.execute(stmt)
        inserted += 1
    return inserted
