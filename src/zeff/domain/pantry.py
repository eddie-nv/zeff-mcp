"""Pantry-state computation: ingest records minus expired items.

For each ingest record, look up the node's `decay` facet, pick the
default storage mode (refrigerated > pantry > frozen — i.e., the
shortest-shelf-life mode that's actually defined, since the user is
assumed to keep things fresh, not frozen, by default), compute the
estimated expiration as `acquired_at + days`, and exclude records where
`as_of >= estimated_expiration`.

Items with no decay facet are treated as long-lived and never expire.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from zeff.db.models import IngestRecord, Node, NodeFacet
from zeff.domain.facets import FacetKey


class StorageMode(StrEnum):
    refrigerated = "refrigerated"
    pantry = "pantry"
    frozen = "frozen"
    opened = "opened"


# Order matters: the first key whose value is non-null wins.
# Refrigerated first because that's the everyday default per DESIGN.md.
_MODE_PREFERENCE: list[tuple[StorageMode, str]] = [
    (StorageMode.refrigerated, "refrigerated_days"),
    (StorageMode.pantry, "pantry_days"),
    (StorageMode.frozen, "frozen_days"),
    (StorageMode.opened, "opened_days"),
]


class PantryItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    record_id: str
    node_id: str
    pref_label: str
    acquired_at: datetime
    quantity: float | None
    storage_mode: StorageMode | None = Field(
        description="The decay mode used to compute expiration; None if no decay data."
    )
    estimated_expiration: datetime | None = Field(
        description="When the item is estimated to spoil; None if no decay data."
    )
    days_until_expiration: int | None = Field(
        description="Whole days from as_of to expiration; None if no decay data."
    )


def _pick_mode(decay: dict[str, Any] | None) -> tuple[StorageMode, int] | None:
    """Pick (mode, days) from a decay dict, or None if nothing applicable."""
    if not decay:
        return None
    for mode, key in _MODE_PREFERENCE:
        value = decay.get(key)
        if isinstance(value, int) and value > 0:
            return (mode, value)
    return None


async def compute_pantry_state(
    session: AsyncSession,
    user_id: str,
    *,
    as_of: datetime | None = None,
) -> Annotated[list[PantryItem], "Pantry items, newest acquisition first"]:
    """Compute the user's current pantry as of `as_of` (default: now)."""
    when = as_of if as_of is not None else datetime.now(tz=UTC)

    # Pull every ingest + the node's pref_label + the decay facet (if any) in
    # a single round trip.
    stmt = (
        select(
            IngestRecord.id,
            IngestRecord.node_id,
            IngestRecord.acquired_at,
            IngestRecord.quantity,
            Node.pref_label,
            NodeFacet.facet_value,
        )
        .join(Node, Node.id == IngestRecord.node_id)
        .outerjoin(
            NodeFacet,
            (NodeFacet.node_id == IngestRecord.node_id)
            & (NodeFacet.facet_key == FacetKey.decay.value),
        )
        .where(IngestRecord.user_id == user_id)
        .order_by(IngestRecord.acquired_at.desc(), IngestRecord.id)
    )
    rows = (await session.execute(stmt)).all()

    out: list[PantryItem] = []
    for row in rows:
        decay = row.facet_value if isinstance(row.facet_value, dict) else None
        picked = _pick_mode(decay)

        if picked is None:
            # No decay info: keep indefinitely (cannot expire).
            out.append(
                PantryItem(
                    record_id=str(row.id),
                    node_id=row.node_id,
                    pref_label=row.pref_label,
                    acquired_at=row.acquired_at,
                    quantity=row.quantity,
                    storage_mode=None,
                    estimated_expiration=None,
                    days_until_expiration=None,
                )
            )
            continue

        mode, days = picked
        expiration = row.acquired_at + timedelta(days=days)
        if when >= expiration:
            continue
        days_left = (expiration - when).days
        out.append(
            PantryItem(
                record_id=str(row.id),
                node_id=row.node_id,
                pref_label=row.pref_label,
                acquired_at=row.acquired_at,
                quantity=row.quantity,
                storage_mode=mode,
                estimated_expiration=expiration,
                days_until_expiration=days_left,
            )
        )
    return out
