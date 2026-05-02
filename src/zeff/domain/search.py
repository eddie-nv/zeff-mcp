"""Food search.

Combines exact / case-insensitive / prefix / trigram-similarity matches over
`pref_label` and `alt_labels_text` (the STORED generated column added in M0).

Scoring is the max of three signals so the strongest one wins:

  - 1.0 for case-insensitive exact match on pref_label
  - 0.95 for case-insensitive prefix on pref_label
  - 0.9 for token containment in alt_labels_text
  - similarity(pref_label, query) and similarity(alt_labels_text, query)
    from pg_trgm (clamped 0-1)

Excluded by default: `pending_review` and `deprecated` nodes.
"""

from __future__ import annotations

import re
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Float, String, bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from zeff.domain.nodes import NodeType

DEFAULT_LIMIT = 5
SIMILARITY_FLOOR = 0.18  # pg_trgm default is 0.3; lower = more recall, less precision

# A query is meaningful only if it has at least one alphanumeric character.
_HAS_TOKEN_RE = re.compile(r"[A-Za-z0-9]")


class SearchResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    node_id: str
    pref_label: str
    type: NodeType
    parents: Annotated[list[str], Field(default_factory=list)]
    score: float


# Recursive ancestor chain (closest parent first), assembled per row in the
# main query via a LATERAL CTE.
_SEARCH_SQL = text(
    """
    WITH RECURSIVE ancestors AS (
        SELECT id, parent_id, 0 AS depth
        FROM nodes
        UNION ALL
        SELECT a.id, n.parent_id, a.depth + 1
        FROM ancestors a
        JOIN nodes n ON n.id = a.parent_id
        WHERE a.parent_id IS NOT NULL
    ),
    parents_for AS (
        SELECT
            id AS node_id,
            array_agg(parent_id ORDER BY depth) FILTER (WHERE parent_id IS NOT NULL) AS parents
        FROM ancestors
        GROUP BY id
    ),
    scored AS (
        SELECT
            n.id,
            n.pref_label,
            n.type,
            GREATEST(
                CASE WHEN lower(n.pref_label) = lower(:q) THEN 1.0 ELSE 0 END,
                CASE WHEN lower(n.pref_label) LIKE lower(:q_prefix) THEN 0.95 ELSE 0 END,
                CASE
                    WHEN n.alt_labels_text IS NOT NULL
                         AND lower(n.alt_labels_text) LIKE lower(:q_token)
                    THEN 0.9
                    ELSE 0
                END,
                similarity(n.pref_label, :q),
                COALESCE(similarity(n.alt_labels_text, :q), 0)
            ) AS score
        FROM nodes n
        WHERE n.status = 'active'
          AND (:type_filter IS NULL OR n.type = :type_filter)
          AND (
              similarity(n.pref_label, :q) >= :floor
              OR (n.alt_labels_text IS NOT NULL
                  AND similarity(n.alt_labels_text, :q) >= :floor)
              OR lower(n.pref_label) LIKE lower(:q_prefix)
              OR (n.alt_labels_text IS NOT NULL
                  AND lower(n.alt_labels_text) LIKE lower(:q_token))
          )
    )
    SELECT
        s.id AS node_id,
        s.pref_label,
        s.type,
        COALESCE(pf.parents, ARRAY[]::text[]) AS parents,
        s.score
    FROM scored s
    LEFT JOIN parents_for pf ON pf.node_id = s.id
    WHERE s.score >= :floor
    ORDER BY s.score DESC, length(s.pref_label) ASC, s.id ASC
    LIMIT :limit
    """
).bindparams(
    bindparam("q", type_=String()),
    bindparam("q_prefix", type_=String()),
    bindparam("q_token", type_=String()),
    bindparam("type_filter", type_=String()),
    bindparam("floor", type_=Float()),
    bindparam("limit"),
)


async def search_foods(
    session: AsyncSession,
    query: str,
    *,
    limit: int = DEFAULT_LIMIT,
    type_filter: NodeType | None = None,
) -> list[SearchResult]:
    """Search for food nodes by query.

    Returns up to `limit` results ranked by best-of-signals score. Returns an
    empty list for queries without any alphanumeric token.
    """
    q = query.strip()
    if not q or not _HAS_TOKEN_RE.search(q):
        return []

    effective_limit = limit if limit and limit > 0 else DEFAULT_LIMIT

    rows = (
        await session.execute(
            _SEARCH_SQL,
            {
                "q": q,
                "q_prefix": f"{q}%",
                "q_token": f"%{q}%",
                "type_filter": type_filter.value if type_filter else None,
                "floor": SIMILARITY_FLOOR,
                "limit": effective_limit,
            },
        )
    ).all()

    return [
        SearchResult(
            node_id=row.node_id,
            pref_label=row.pref_label,
            type=NodeType(row.type),
            parents=list(row.parents) if row.parents else [],
            score=float(row.score),
        )
        for row in rows
    ]
