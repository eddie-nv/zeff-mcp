"""Hand-curated composite seed.

Reads `data/composites.json` and idempotently upserts:
  - any "ensure_primitives" referenced by composites that aren't in the USDA
    seed (e.g., 'mozzarella_part_skim', 'bread_white' — these are common
    pantry items the per-parent caps cut from the USDA pass)
  - each composite as a `type='composite'` node
  - each composite's per-component edge in node_components
  - each composite's hand-curated facets (nova_group, decay, requires_cooking)

After this seed, run `seed_facets` again so the new ensure_primitives get
their rule-derived facets.

CLI:
    python -m zeff.seeds.composites
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, TypedDict

from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from zeff.config import get_settings
from zeff.db import connection as db_conn
from zeff.db.models import Node, NodeComponent, NodeFacet
from zeff.domain.facets import FacetKey, validate_facet

log = logging.getLogger(__name__)

DEFAULT_DATA = Path(__file__).resolve().parents[3] / "data" / "composites.json"


class _PrimitiveEntry(TypedDict, total=False):
    id: str
    pref_label: str
    parent_id: str
    alt_labels: list[str]


class _ComponentEntry(TypedDict, total=False):
    node_id: str
    grams_per_serving: float
    position: int
    is_primary: bool


class _CompositeEntry(TypedDict, total=False):
    id: str
    pref_label: str
    parent_id: str
    alt_labels: list[str]
    facets: dict[str, Any]
    components: list[_ComponentEntry]


def _load(path: Path) -> tuple[list[_PrimitiveEntry], list[_CompositeEntry]]:
    raw = json.loads(path.read_text())
    return raw.get("ensure_primitives", []), raw.get("composites", [])


async def _upsert_primitive(session: AsyncSession, p: _PrimitiveEntry) -> None:
    stmt = insert(Node).values(
        id=p["id"],
        type="primitive",
        pref_label=p["pref_label"],
        alt_labels=p.get("alt_labels") or None,
        parent_id=p["parent_id"],
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


async def _upsert_composite(session: AsyncSession, c: _CompositeEntry) -> None:
    stmt = insert(Node).values(
        id=c["id"],
        type="composite",
        pref_label=c["pref_label"],
        alt_labels=c.get("alt_labels") or None,
        parent_id=c["parent_id"],
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


async def _replace_components(
    session: AsyncSession, composite_id: str, components: list[_ComponentEntry]
) -> None:
    """Delete-then-insert components so a re-run reflects edits exactly."""
    await session.execute(delete(NodeComponent).where(NodeComponent.composite_id == composite_id))
    for entry in components:
        session.add(
            NodeComponent(
                composite_id=composite_id,
                component_id=entry["node_id"],
                grams_per_serving=entry.get("grams_per_serving"),
                position=entry.get("position", 0),
                is_primary=entry.get("is_primary", False),
            )
        )


async def _upsert_composite_facets(
    session: AsyncSession, composite_id: str, facets: dict[str, Any]
) -> None:
    for key_str, value in facets.items():
        key = FacetKey(key_str)
        normalized = validate_facet(key, value)
        stmt = insert(NodeFacet).values(
            node_id=composite_id, facet_key=key.value, facet_value=normalized
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[NodeFacet.node_id, NodeFacet.facet_key],
            set_={"facet_value": stmt.excluded.facet_value},
        )
        await session.execute(stmt)


async def seed_composites(
    session: AsyncSession, data_path: Path = DEFAULT_DATA
) -> tuple[int, int, int]:
    """Idempotent seed. Returns (n_primitives_upserted, n_composites, n_components)."""
    primitives, composites = _load(data_path)

    for p in primitives:
        await _upsert_primitive(session, p)

    n_components = 0
    for c in composites:
        await _upsert_composite(session, c)
        await _replace_components(session, c["id"], c.get("components", []))
        n_components += len(c.get("components", []))
        if c.get("facets"):
            await _upsert_composite_facets(session, c["id"], c["facets"])

    return len(primitives), len(composites), n_components


async def _amain() -> int:
    logging.basicConfig(level=get_settings().log_level)
    db_conn.configure_engine(get_settings().database_url)
    async with db_conn.session_scope() as session:
        n_p, n_c, n_e = await seed_composites(session)
    log.info(
        "composites seed complete: %d primitives, %d composites, %d component edges",
        n_p,
        n_c,
        n_e,
    )
    return 0


def main() -> int:
    return asyncio.run(_amain())


if __name__ == "__main__":
    raise SystemExit(main())
