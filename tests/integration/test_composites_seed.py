"""Integration tests for the composites seed."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import select

from zeff.db import queries
from zeff.db.models import Node, NodeComponent, NodeFacet
from zeff.domain.facets import FacetKey
from zeff.seeds.canonical import seed_canonical
from zeff.seeds.composites import seed_composites

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA = REPO_ROOT / "data" / "composites.json"


@pytest.fixture
def small_composites_json(tmp_path: Path) -> Path:
    """Tiny 2-composite subset to verify the parser end-to-end on a controlled slice."""
    payload = {
        "ensure_primitives": [
            {
                "id": "mini_cheese",
                "pref_label": "Mini Cheese",
                "parent_id": "cheese",
                "alt_labels": ["mc"],
            },
            {
                "id": "mini_bread",
                "pref_label": "Mini Bread",
                "parent_id": "refined_grain",
            },
            {
                "id": "mini_tomato",
                "pref_label": "Mini Tomato",
                "parent_id": "vegetable",
            },
        ],
        "composites": [
            {
                "id": "mini_cheese_sandwich",
                "pref_label": "Mini Cheese Sandwich",
                "parent_id": "food",
                "facets": {"nova_group": 3, "decay": {"refrigerated_days": 2}},
                "components": [
                    {"node_id": "mini_bread", "grams_per_serving": 50, "position": 0},
                    {
                        "node_id": "mini_cheese",
                        "grams_per_serving": 30,
                        "is_primary": True,
                        "position": 1,
                    },
                ],
            },
            {
                "id": "mini_caprese",
                "pref_label": "Mini Caprese",
                "parent_id": "food",
                "facets": {"nova_group": 1, "requires_cooking": False},
                "components": [
                    {
                        "node_id": "mini_tomato",
                        "grams_per_serving": 80,
                        "is_primary": True,
                        "position": 0,
                    },
                    {"node_id": "mini_cheese", "grams_per_serving": 60, "position": 1},
                ],
            },
        ],
    }
    p = tmp_path / "small.json"
    p.write_text(json.dumps(payload))
    return p


class TestSmallSubset:
    async def test_seeds_primitives_and_composites(self, db_session, small_composites_json) -> None:
        await seed_canonical(db_session)
        await db_session.commit()

        n_p, n_c, n_e = await seed_composites(db_session, small_composites_json)
        await db_session.commit()
        assert (n_p, n_c, n_e) == (3, 2, 4)

        node_ids = {r.id for r in (await db_session.execute(select(Node.id))).all()}
        assert "mini_cheese_sandwich" in node_ids
        assert "mini_caprese" in node_ids

    async def test_components_match_input(self, db_session, small_composites_json) -> None:
        await seed_canonical(db_session)
        await db_session.commit()
        await seed_composites(db_session, small_composites_json)
        await db_session.commit()

        comps = await queries.get_components(db_session, "mini_cheese_sandwich")
        ids = [c.component_id for c in comps]
        assert ids == ["mini_bread", "mini_cheese"]
        primary = next(c for c in comps if c.is_primary)
        assert primary.component_id == "mini_cheese"
        assert primary.grams_per_serving == 30.0

    async def test_composite_facets_seeded(self, db_session, small_composites_json) -> None:
        await seed_canonical(db_session)
        await db_session.commit()
        await seed_composites(db_session, small_composites_json)
        await db_session.commit()

        facets = (
            await db_session.execute(
                select(NodeFacet.facet_key, NodeFacet.facet_value).where(
                    NodeFacet.node_id == "mini_cheese_sandwich"
                )
            )
        ).all()
        by_key = {r.facet_key: r.facet_value for r in facets}
        assert by_key[FacetKey.nova_group.value] == 3
        assert by_key[FacetKey.decay.value] == {"refrigerated_days": 2}

    async def test_idempotent(self, db_session, small_composites_json) -> None:
        await seed_canonical(db_session)
        await db_session.commit()
        await seed_composites(db_session, small_composites_json)
        await db_session.commit()
        nodes_first = {r.id for r in (await db_session.execute(select(Node.id))).all()}
        edges_first = (await db_session.execute(select(NodeComponent))).all()

        await seed_composites(db_session, small_composites_json)
        await db_session.commit()
        nodes_second = {r.id for r in (await db_session.execute(select(Node.id))).all()}
        edges_second = (await db_session.execute(select(NodeComponent))).all()

        assert nodes_first == nodes_second
        assert len(edges_first) == len(edges_second)


class TestFullSeed:
    """Exercises the real data/composites.json against the canonical tree only."""

    async def test_full_seed(self, db_session) -> None:
        await seed_canonical(db_session)
        await db_session.commit()

        n_p, n_c, n_e = await seed_composites(db_session)
        await db_session.commit()
        # 29 ensure_primitives, 10 composites in the file.
        assert n_p == 29
        assert n_c == 10
        # Sum of components across all composites — keep this loose; the
        # important assertion is "non-trivial".
        assert n_e >= 30

        composites = (
            await db_session.execute(select(Node.id).where(Node.type == "composite"))
        ).all()
        ids = {r.id for r in composites}
        assert ids == {
            "frozen_cheese_pizza",
            "frozen_lasagna",
            "canned_chicken_soup",
            "cheese_sandwich",
            "peanut_butter_jelly_sandwich",
            "caesar_salad",
            "spaghetti_marinara",
            "tuna_melt",
            "chicken_quesadilla",
            "macaroni_and_cheese",
        }

    async def test_every_composite_has_one_primary(self, db_session) -> None:
        await seed_canonical(db_session)
        await db_session.commit()
        await seed_composites(db_session)
        await db_session.commit()

        composites = (
            await db_session.execute(select(Node.id).where(Node.type == "composite"))
        ).all()
        for r in composites:
            comps = await queries.get_components(db_session, r.id)
            primaries = [c for c in comps if c.is_primary]
            assert len(primaries) == 1, f"{r.id} has {len(primaries)} primary components"
