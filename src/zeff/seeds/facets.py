"""Apply facet rules to every primitive node in the DB.

Streams nodes (where type='primitive'), runs the per-facet rules, and
upserts the five v1 facets into node_facets. Always validates via
validate_facet so the DB never sees an invalid value.

CLI:
    python -m zeff.seeds.facets
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from zeff.config import get_settings
from zeff.db import connection as db_conn
from zeff.db.models import Node, NodeFacet
from zeff.domain.facets import FacetKey, validate_facet
from zeff.seeds.facet_rules import (
    assign_allergens,
    assign_decay,
    assign_dietary_flags,
    assign_nova_group,
    assign_requires_cooking,
)

log = logging.getLogger(__name__)


async def _build_parent_chain_index(session: AsyncSession) -> dict[str, list[str]]:
    """For each node, return the chain of ancestor ids (closest first, root last)."""
    rows = (await session.execute(select(Node.id, Node.parent_id))).all()
    parent_of = {r.id: r.parent_id for r in rows}
    chains: dict[str, list[str]] = {}
    for nid in parent_of:
        chain: list[str] = []
        cur = parent_of.get(nid)
        # Bound depth to avoid pathological cycles.
        for _ in range(20):
            if not cur:
                break
            chain.append(cur)
            cur = parent_of.get(cur)
        chains[nid] = chain
    return chains


async def seed_facets(session: AsyncSession) -> dict[str, int]:
    """Compute and upsert facets for every primitive node.

    Returns a count per facet of upserted rows.
    """
    parent_chains = await _build_parent_chain_index(session)
    rows = (
        await session.execute(
            select(Node.id, Node.parent_id, Node.pref_label, Node.alt_labels).where(
                Node.type == "primitive"
            )
        )
    ).all()

    counts: dict[str, int] = {fk.value: 0 for fk in FacetKey}

    for row in rows:
        node_id = row.id
        parent_id = row.parent_id or ""
        pref_label = row.pref_label or ""
        alts = list(row.alt_labels or [])

        # Compute facets in this order: nova first (cheap), then allergens
        # (needed by dietary_flags), then dietary_flags, decay, requires_cooking.
        ancestors = parent_chains.get(node_id, [])
        nova = assign_nova_group(node_id, parent_id, pref_label, alts)
        allergens = assign_allergens(node_id, parent_id, pref_label, alts)
        dietary = assign_dietary_flags(node_id, parent_id, allergens, ancestors=ancestors[1:])
        decay = assign_decay(node_id, parent_id, pref_label, alts)
        cooks = assign_requires_cooking(node_id, parent_id, pref_label, alts)

        facet_values: dict[FacetKey, Any] = {
            FacetKey.nova_group: nova,
            FacetKey.allergens: allergens,
            FacetKey.dietary_flags: dietary,
            FacetKey.decay: decay,
            FacetKey.requires_cooking: cooks,
        }
        for key, value in facet_values.items():
            normalized = validate_facet(key, value)
            stmt = insert(NodeFacet).values(
                node_id=node_id, facet_key=key.value, facet_value=normalized
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=[NodeFacet.node_id, NodeFacet.facet_key],
                set_={"facet_value": stmt.excluded.facet_value},
            )
            await session.execute(stmt)
            counts[key.value] += 1

    return counts


async def _amain() -> int:
    logging.basicConfig(level=get_settings().log_level)
    db_conn.configure_engine(get_settings().database_url)
    async with db_conn.session_scope() as session:
        counts = await seed_facets(session)
    log.info("facets seeded: %s", counts)
    return 0


def main() -> int:
    return asyncio.run(_amain())


if __name__ == "__main__":
    raise SystemExit(main())
