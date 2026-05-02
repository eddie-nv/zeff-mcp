"""Consumption history.

`get_consumption_history(user_id, time_range, group_by)` returns the
user's ingest events over a window, optionally aggregated. Operating
assumption per DESIGN.md: the user eats what they buy, so consumption
history == ingest history.

Group-by buckets:
  - `none`     — raw events (no aggregation)
  - `day`      — by calendar day in UTC
  - `category` — by the node's top-level canonical category (fruit,
                 vegetable, protein, dairy, ...)
  - `nova_group` — by NOVA group 1-4, plus "unknown" for un-facetted
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from zeff.db.models import IngestRecord, Node, NodeFacet
from zeff.domain.facets import FacetKey


class GroupBy(StrEnum):
    none = "none"
    day = "day"
    category = "category"
    nova_group = "nova_group"


_TIME_RANGE_RE = re.compile(r"^(?P<n>[1-9]\d*)d$")


def parse_time_range(spec: str) -> timedelta:
    """Parse a `<n>d` time-range string into a timedelta. Raises ValueError."""
    if not isinstance(spec, str):
        raise ValueError(f"time_range must be a string like '30d', got {spec!r}")
    m = _TIME_RANGE_RE.match(spec)
    if not m:
        raise ValueError(f"time_range must look like '<n>d' with n>=1, got {spec!r}")
    return timedelta(days=int(m.group("n")))


class HistoryEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    record_id: str
    node_id: str
    pref_label: str
    acquired_at: datetime
    quantity: float | None


class HistoryGroup(BaseModel):
    model_config = ConfigDict(frozen=True)

    key: str
    record_count: int
    total_quantity: float | None = Field(
        description="Sum of quantity across the bucket's records, or None if all are null."
    )


class HistoryResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    user_id: str
    time_range: str
    group_by: GroupBy
    as_of: datetime
    since: datetime
    total_records: int
    groups: list[HistoryGroup] = Field(default_factory=list)
    events: list[HistoryEvent] = Field(
        default_factory=list,
        description="Populated only when group_by='none'.",
    )


# Recursive ancestor chain → top-level category. Returns the child of 'food'
# in the chain (e.g. 'fruit', 'protein'). Nodes whose chain doesn't reach
# 'food' are absent from the result — callers default them to 'unknown'.
_TOP_LEVEL_SQL = text(
    """
    WITH RECURSIVE chain AS (
        SELECT id AS node_id, id AS cur, parent_id, 0 AS depth
        FROM nodes
        WHERE id = ANY(:ids)
        UNION ALL
        SELECT c.node_id, n.id, n.parent_id, c.depth + 1
        FROM chain c
        JOIN nodes n ON n.id = c.parent_id
        WHERE c.parent_id IS NOT NULL
    )
    SELECT node_id, cur AS top_level
    FROM chain
    WHERE parent_id = 'food'
    """
)


async def _top_level_for_nodes(session: AsyncSession, node_ids: list[str]) -> dict[str, str]:
    """Map each node_id to its child-of-`food` ancestor."""
    if not node_ids:
        return {}
    rows = (await session.execute(_TOP_LEVEL_SQL, {"ids": list(set(node_ids))})).all()
    out: dict[str, str] = {}
    for row in rows:
        out[row.node_id] = row.top_level
    return out


async def _nova_for_nodes(session: AsyncSession, node_ids: list[str]) -> dict[str, int]:
    if not node_ids:
        return {}
    rows = (
        await session.execute(
            select(NodeFacet.node_id, NodeFacet.facet_value).where(
                NodeFacet.node_id.in_(set(node_ids)),
                NodeFacet.facet_key == FacetKey.nova_group.value,
            )
        )
    ).all()
    return {r.node_id: int(r.facet_value) for r in rows if isinstance(r.facet_value, int)}


def _sum_quantity(records: list[Any]) -> float | None:
    quantities = [r.quantity for r in records if r.quantity is not None]
    return sum(quantities) if quantities else None


async def get_consumption_history(
    session: AsyncSession,
    user_id: str,
    *,
    time_range: str = "30d",
    group_by: GroupBy = GroupBy.category,
    as_of: datetime | None = None,
) -> HistoryResult:
    """Aggregate the user's ingest events over `time_range`."""
    when = as_of if as_of is not None else datetime.now(tz=UTC)
    delta = parse_time_range(time_range)
    since = when - delta

    rows = (
        await session.execute(
            select(
                IngestRecord.id,
                IngestRecord.node_id,
                IngestRecord.acquired_at,
                IngestRecord.quantity,
                Node.pref_label,
            )
            .join(Node, Node.id == IngestRecord.node_id)
            .where(
                IngestRecord.user_id == user_id,
                IngestRecord.acquired_at >= since,
                IngestRecord.acquired_at <= when,
            )
            .order_by(IngestRecord.acquired_at.desc(), IngestRecord.id)
        )
    ).all()

    total = len(rows)
    base = HistoryResult(
        user_id=user_id,
        time_range=time_range,
        group_by=group_by,
        as_of=when,
        since=since,
        total_records=total,
    )

    if group_by == GroupBy.none:
        events = [
            HistoryEvent(
                record_id=str(r.id),
                node_id=r.node_id,
                pref_label=r.pref_label,
                acquired_at=r.acquired_at,
                quantity=r.quantity,
            )
            for r in rows
        ]
        return base.model_copy(update={"events": events})

    if total == 0:
        return base

    # Aggregations
    buckets: dict[str, list[Any]] = {}
    if group_by == GroupBy.day:
        for r in rows:
            buckets.setdefault(r.acquired_at.date().isoformat(), []).append(r)
    elif group_by == GroupBy.category:
        node_ids = [r.node_id for r in rows]
        top_level = await _top_level_for_nodes(session, node_ids)
        for r in rows:
            buckets.setdefault(top_level.get(r.node_id, "unknown"), []).append(r)
    elif group_by == GroupBy.nova_group:
        node_ids = [r.node_id for r in rows]
        nova = await _nova_for_nodes(session, node_ids)
        for r in rows:
            value = nova.get(r.node_id)
            buckets.setdefault(str(value) if value is not None else "unknown", []).append(r)

    groups = sorted(
        (
            HistoryGroup(key=key, record_count=len(records), total_quantity=_sum_quantity(records))
            for key, records in buckets.items()
        ),
        key=lambda g: (-g.record_count, g.key),
    )
    return base.model_copy(update={"groups": groups})
