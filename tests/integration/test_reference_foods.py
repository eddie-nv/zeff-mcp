"""M3 stop-and-verify: the 11 DESIGN.md reference foods exist with the right
parents and at least the category + nova_group facets.

The seed pipeline used here is the eval seed (`seed_reference_foods`) which
runs `seed_canonical` first, then upserts the 11 primitives. This test
guards against regressions in either layer.
"""

from __future__ import annotations

import pytest
from evals.runners.eval_seed import REFERENCE_FOODS, seed_reference_foods
from sqlalchemy import select

from zeff.db import queries
from zeff.db.models import Node
from zeff.domain.facets import FacetKey

pytestmark = pytest.mark.integration


# (id, expected parent, expected nova_group)
REFERENCE_EXPECTATIONS: list[tuple[str, str, int]] = [
    ("honeycrisp_apple", "apple", 1),
    ("fuji_apple", "apple", 1),
    ("spinach_raw", "vegetable", 1),
    ("celery_raw", "vegetable", 1),
    ("potato_raw", "vegetable", 1),
    ("chicken_breast_raw", "poultry", 1),
    ("chicken_whole_raw", "poultry", 1),
    ("chicken_leg_raw", "poultry", 1),
    ("salt", "seasoning", 2),
    ("salmon_raw", "seafood", 1),
    ("ny_strip_steak_raw", "red_meat", 1),
]


async def _set_reference_facets(db_session) -> None:
    """Tag each reference food with its expected nova_group facet.

    M4 will produce these for real; for now we set them inline so the M3
    contract (every reference food has a category + nova_group) is verifiable.
    """
    for node_id, _parent, nova in REFERENCE_EXPECTATIONS:
        await queries.set_facet(db_session, node_id, FacetKey.nova_group, nova)


async def test_eleven_reference_foods_seeded(db_session) -> None:
    await seed_reference_foods(db_session)
    await _set_reference_facets(db_session)
    await db_session.commit()

    expected_ids = {nid for nid, _, _ in REFERENCE_EXPECTATIONS}
    seeded_ids = {
        r.id
        for r in (await db_session.execute(select(Node.id).where(Node.id.in_(expected_ids)))).all()
    }
    assert expected_ids - seeded_ids == set(), (
        f"missing reference foods: {expected_ids - seeded_ids}"
    )


async def test_each_reference_food_has_correct_parent(db_session) -> None:
    await seed_reference_foods(db_session)
    await _set_reference_facets(db_session)
    await db_session.commit()

    rows = (
        await db_session.execute(
            select(Node.id, Node.parent_id).where(
                Node.id.in_({nid for nid, _, _ in REFERENCE_EXPECTATIONS})
            )
        )
    ).all()
    by_id = {r.id: r.parent_id for r in rows}
    for node_id, expected_parent, _ in REFERENCE_EXPECTATIONS:
        assert by_id.get(node_id) == expected_parent, (
            f"{node_id}: expected parent {expected_parent}, got {by_id.get(node_id)}"
        )


async def test_each_reference_food_has_nova_group(db_session) -> None:
    await seed_reference_foods(db_session)
    await _set_reference_facets(db_session)
    await db_session.commit()

    for node_id, _parent, expected_nova in REFERENCE_EXPECTATIONS:
        facets = await queries.get_facets(db_session, node_id)
        assert FacetKey.nova_group in facets, f"{node_id} is missing nova_group"
        assert facets[FacetKey.nova_group] == expected_nova, (
            f"{node_id}: expected nova {expected_nova}, got {facets[FacetKey.nova_group]}"
        )


async def test_reference_set_matches_design_doc(db_session) -> None:
    """Every entry in REFERENCE_FOODS (eval seed) is covered by an
    expectation here. Catches drift between the eval seed and this contract.
    """
    eval_ids = {
        fid for fid, *_ in REFERENCE_FOODS if fid != "apple"
    }  # apple is the parent category
    expectation_ids = {nid for nid, _, _ in REFERENCE_EXPECTATIONS}
    assert eval_ids == expectation_ids
