"""Run the taxonomy correctness eval and emit a JSON report.

Loads `evals/datasets/taxonomy_truth.jsonl` and for each entry:
  - asserts the node exists with the expected parent
  - asserts each expected facet is present and matches

Reports: parent accuracy, per-facet accuracy, missing-node count, JSON
report under evals/reports/.

Threshold: parent accuracy must be 100%, facet accuracy ≥ 95%.

CLI:
    python -m evals.runners.run_taxonomy_eval
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypedDict

from sqlalchemy import select

from evals.runners.eval_seed import seed_reference_foods
from zeff.config import get_settings
from zeff.db import connection as db_conn
from zeff.db.models import Node, NodeFacet
from zeff.seeds.facets import seed_facets

REPO_ROOT = Path(__file__).resolve().parents[2]
DATASET = REPO_ROOT / "evals" / "datasets" / "taxonomy_truth.jsonl"
REPORT_DIR = REPO_ROOT / "evals" / "reports"

PARENT_THRESHOLD = 1.0
FACET_THRESHOLD = 0.95

log = logging.getLogger(__name__)


class TruthEntry(TypedDict):
    node_id: str
    expected_parent: str
    expected_facets: dict[str, Any]


def _load_dataset(path: Path) -> list[TruthEntry]:
    out: list[TruthEntry] = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        out.append(json.loads(line))
    return out


def _normalize(facet_key: str, value: Any) -> Any:
    """Normalize values so dietary_flags and allergens compare as sorted lists."""
    if facet_key in ("dietary_flags", "allergens") and isinstance(value, list):
        return sorted(value)
    return value


async def _evaluate(session, entries: list[TruthEntry]) -> dict:
    # Bulk-load nodes and facets up-front; eval set is small but this lets us
    # report missing-node cases in one shot.
    ids = [e["node_id"] for e in entries]
    node_rows = (
        await session.execute(select(Node.id, Node.parent_id).where(Node.id.in_(ids)))
    ).all()
    nodes_by_id = {r.id: r.parent_id for r in node_rows}

    facet_rows = (
        await session.execute(
            select(NodeFacet.node_id, NodeFacet.facet_key, NodeFacet.facet_value).where(
                NodeFacet.node_id.in_(ids)
            )
        )
    ).all()
    facets_by_id: dict[str, dict[str, Any]] = defaultdict(dict)
    for r in facet_rows:
        facets_by_id[r.node_id][r.facet_key] = r.facet_value

    per_case: list[dict] = []
    parent_total = parent_correct = 0
    facet_total = facet_correct = 0
    facet_breakdown: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "correct": 0})

    for entry in entries:
        nid = entry["node_id"]
        expected_parent = entry["expected_parent"]
        expected_facets = entry["expected_facets"]

        case: dict[str, Any] = {
            "node_id": nid,
            "expected_parent": expected_parent,
            "missing": nid not in nodes_by_id,
            "parent_ok": False,
            "actual_parent": nodes_by_id.get(nid),
            "facet_results": {},
        }
        parent_total += 1
        if not case["missing"]:
            case["parent_ok"] = nodes_by_id[nid] == expected_parent
            if case["parent_ok"]:
                parent_correct += 1

        for fkey, fval in expected_facets.items():
            facet_total += 1
            facet_breakdown[fkey]["total"] += 1
            if case["missing"]:
                case["facet_results"][fkey] = {"ok": False, "reason": "node missing"}
                continue
            actual = facets_by_id.get(nid, {}).get(fkey)
            ok = _normalize(fkey, actual) == _normalize(fkey, fval)
            case["facet_results"][fkey] = {
                "ok": ok,
                "expected": fval,
                "actual": actual,
            }
            if ok:
                facet_correct += 1
                facet_breakdown[fkey]["correct"] += 1

        per_case.append(case)

    return {
        "n_entries": len(entries),
        "parent_total": parent_total,
        "parent_correct": parent_correct,
        "parent_accuracy": parent_correct / parent_total if parent_total else 0.0,
        "facet_total": facet_total,
        "facet_correct": facet_correct,
        "facet_accuracy": facet_correct / facet_total if facet_total else 0.0,
        "facet_breakdown": {
            k: {
                **v,
                "accuracy": v["correct"] / v["total"] if v["total"] else 0.0,
            }
            for k, v in sorted(facet_breakdown.items())
        },
        "missing_nodes": sorted(c["node_id"] for c in per_case if c["missing"]),
        "parent_failures": sorted(
            (c["node_id"], c["actual_parent"], c["expected_parent"])
            for c in per_case
            if not c["missing"] and not c["parent_ok"]
        ),
        "cases": per_case,
    }


async def _amain() -> int:
    logging.basicConfig(level="INFO")
    db_conn.configure_engine(get_settings().database_url)
    entries = _load_dataset(DATASET)
    log.info("loaded %d truth entries", len(entries))

    # Reference foods (the 11 from DESIGN.md) are part of the eval baseline
    # but aren't in `make seed`. Upsert them + re-derive facets so the eval
    # always runs against a complete-enough DB.
    async with db_conn.session_scope() as session:
        await seed_reference_foods(session)
        await seed_facets(session)
    log.info("eval seed (reference foods + facets) applied")

    async with db_conn.session_scope() as session:
        report = await _evaluate(session, entries)

    report["timestamp"] = datetime.now(tz=UTC).isoformat()
    report["thresholds"] = {"parent": PARENT_THRESHOLD, "facet": FACET_THRESHOLD}
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = REPORT_DIR / f"taxonomy_{datetime.now(tz=UTC).strftime('%Y-%m-%d_%H%M%S')}.json"
    out_path.write_text(json.dumps(report, indent=2))

    parent_pct = report["parent_accuracy"]
    facet_pct = report["facet_accuracy"]
    log.info("=" * 60)
    log.info(
        "RESULTS  n=%d  parent=%.3f (%d/%d)  facet=%.3f (%d/%d)",
        report["n_entries"],
        parent_pct,
        report["parent_correct"],
        report["parent_total"],
        facet_pct,
        report["facet_correct"],
        report["facet_total"],
    )
    log.info("by_facet:")
    for fk, s in report["facet_breakdown"].items():
        log.info("  %-20s %3d/%-3d  acc=%.3f", fk, s["correct"], s["total"], s["accuracy"])
    if report["missing_nodes"]:
        log.warning("MISSING NODES (%d): %s", len(report["missing_nodes"]), report["missing_nodes"])
    if report["parent_failures"]:
        log.warning("PARENT FAILURES (%d):", len(report["parent_failures"]))
        for nid, actual, expected in report["parent_failures"]:
            log.warning("  %s actual=%s expected=%s", nid, actual, expected)
    log.info("report: %s", out_path.relative_to(REPO_ROOT))
    log.info("=" * 60)

    return 0 if parent_pct >= PARENT_THRESHOLD and facet_pct >= FACET_THRESHOLD else 1


def main() -> int:
    return asyncio.run(_amain())


if __name__ == "__main__":
    raise SystemExit(main())
