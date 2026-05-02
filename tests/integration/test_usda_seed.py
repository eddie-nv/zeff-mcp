"""Integration tests for the USDA SR Legacy ingest pipeline.

Runs the full pipeline on the small fixture CSV under tests/fixtures.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select

from zeff.db.models import Node, NodeExternalId
from zeff.seeds.usda_sr import EXTERNAL_SOURCE, seed_usda_sr

pytestmark = pytest.mark.integration

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


# Build a parallel fixture dir so seed_usda_sr can find both csvs by canonical
# names. The tests/fixtures dir already has them named with usda_ prefixes —
# create a temp symlink dir per test session.
@pytest.fixture
def usda_fixture_dir(tmp_path: Path) -> Path:
    target = tmp_path / "sr_legacy"
    target.mkdir()
    (target / "food.csv").write_bytes((FIXTURES / "usda_food.csv").read_bytes())
    (target / "food_category.csv").write_bytes((FIXTURES / "usda_food_category.csv").read_bytes())
    return target


class TestEndToEndSeed:
    async def test_seeds_all_mapped_rows(self, db_session, usda_fixture_dir) -> None:
        n_nodes, n_ext = await seed_usda_sr(db_session, usda_fixture_dir)
        await db_session.commit()
        # 22 rows in fixture, 4 skipped (Baby/Fast/Meals/AI/AN) → 18 nodes.
        assert n_nodes == 18
        assert n_ext == 18

        rows = (await db_session.execute(select(Node).where(Node.type == "primitive"))).all()
        assert len(rows) == 18

    async def test_external_ids_recorded(self, db_session, usda_fixture_dir) -> None:
        await seed_usda_sr(db_session, usda_fixture_dir)
        await db_session.commit()
        ext_rows = (
            await db_session.execute(
                select(NodeExternalId.node_id, NodeExternalId.external_id).where(
                    NodeExternalId.source == EXTERNAL_SOURCE
                )
            )
        ).all()
        # FDC ids from the fixture must show up.
        ext_ids = {r.external_id for r in ext_rows}
        assert "171688" in ext_ids  # apples
        assert "168462" in ext_ids  # spinach
        assert "175167" in ext_ids  # salmon

    async def test_canonical_categories_seeded_first(self, db_session, usda_fixture_dir) -> None:
        await seed_usda_sr(db_session, usda_fixture_dir)
        await db_session.commit()
        # The 19 canonical categories must exist.
        cats = (await db_session.execute(select(Node.id).where(Node.type == "category"))).all()
        ids = {r.id for r in cats}
        for required in (
            "food",
            "fruit",
            "vegetable",
            "poultry",
            "red_meat",
            "seafood",
            "egg",
            "cheese",
        ):
            assert required in ids

    async def test_dairy_egg_split_works(self, db_session, usda_fixture_dir) -> None:
        await seed_usda_sr(db_session, usda_fixture_dir)
        await db_session.commit()
        rows = (
            await db_session.execute(
                select(Node.id, Node.parent_id).where(Node.type == "primitive")
            )
        ).all()
        by_id = {r.id: r.parent_id for r in rows}
        # Egg row goes under egg, not dairy.
        egg_ids = [nid for nid in by_id if nid.startswith("egg_")]
        assert egg_ids
        for eid in egg_ids:
            assert by_id[eid] == "egg"
        # Cheese row under cheese.
        cheese_ids = [nid for nid in by_id if nid.startswith("cheese_")]
        assert cheese_ids
        for cid in cheese_ids:
            assert by_id[cid] == "cheese"

    async def test_skipped_categories_excluded(self, db_session, usda_fixture_dir) -> None:
        await seed_usda_sr(db_session, usda_fixture_dir)
        await db_session.commit()
        rows = (await db_session.execute(select(Node.pref_label))).all()
        labels = {r.pref_label for r in rows}
        # No baby food / fast food / Indian frybread.
        assert not any("Babyfood" in label for label in labels)
        assert not any("Fast Foods" in label for label in labels)
        assert not any(label == "Indian frybread" for label in labels)

    async def test_idempotent(self, db_session, usda_fixture_dir) -> None:
        await seed_usda_sr(db_session, usda_fixture_dir)
        await db_session.commit()
        first = (await db_session.execute(select(Node.id))).all()
        first_ids = {r.id for r in first}

        await seed_usda_sr(db_session, usda_fixture_dir)
        await db_session.commit()
        second = (await db_session.execute(select(Node.id))).all()
        second_ids = {r.id for r in second}

        assert first_ids == second_ids
