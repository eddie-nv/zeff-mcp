"""Run the search eval and emit a JSON report.

Reads `evals/datasets/search_queries.jsonl` and runs each query through
`search_foods` against the configured database. Computes Recall@k and MRR.

Per case:
  - Recall@k = 1 if all expected_top_k IDs appear in top-k results, else
    proportional partial credit (matched / len(expected)).
  - For "no_match" cases (empty expected_top_k), success = empty results.
  - Reciprocal rank uses the FIRST expected ID's position (1-indexed).

CLI:
    python -m evals.runners.run_search_eval
    python -m evals.runners.run_search_eval --no-seed   # skip eval seed
    python -m evals.runners.run_search_eval --via-mcp   # call through MCP tool layer
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict

from evals.runners.eval_seed import seed_reference_foods
from zeff.config import get_settings
from zeff.db import connection as db_conn
from zeff.domain.search import search_foods

REPO_ROOT = Path(__file__).resolve().parents[2]
DATASET = REPO_ROOT / "evals" / "datasets" / "search_queries.jsonl"
REPORT_DIR = REPO_ROOT / "evals" / "reports"

log = logging.getLogger(__name__)


class EvalCase(TypedDict):
    query: str
    expected_top_k: list[str]
    k: int
    tag: str


def _load_dataset(path: Path) -> list[EvalCase]:
    cases: list[EvalCase] = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        cases.append(json.loads(line))
    return cases


def _recall_at_k(expected: list[str], got: list[str]) -> float:
    if not expected:
        return 1.0 if not got else 0.0
    hits = sum(1 for eid in expected if eid in got)
    return hits / len(expected)


def _reciprocal_rank(expected: list[str], got: list[str]) -> float:
    if not expected:
        return 1.0 if not got else 0.0
    target = expected[0]
    for i, gid in enumerate(got, start=1):
        if gid == target:
            return 1.0 / i
    return 0.0


async def _run_one(session, case: EvalCase) -> dict:
    k = case["k"]
    results = await search_foods(session, case["query"], limit=k)
    got_ids = [r.node_id for r in results]
    return {
        "query": case["query"],
        "tag": case["tag"],
        "expected": case["expected_top_k"],
        "got": got_ids,
        "recall_at_k": _recall_at_k(case["expected_top_k"], got_ids),
        "reciprocal_rank": _reciprocal_rank(case["expected_top_k"], got_ids),
        "passed": _recall_at_k(case["expected_top_k"], got_ids) == 1.0,
    }


async def _run_one_via_mcp(server, case: EvalCase) -> dict:
    """Same as _run_one but goes through the MCP tool wrapper."""
    import json as _json

    k = case["k"]
    envelope = await server.call_tool(
        "search_foods", {"query": case["query"], "limit": k}
    )
    payload: dict | None = None
    if isinstance(envelope, tuple):
        for part in reversed(envelope):
            if isinstance(part, dict):
                payload = part
                break
            if isinstance(part, list) and part and hasattr(part[0], "text"):
                payload = _json.loads(part[0].text)
                break
    elif isinstance(envelope, dict):
        payload = envelope
    if payload is None:
        raise AssertionError(f"unrecognized MCP envelope shape: {envelope!r}")

    got_ids = [r["node_id"] for r in payload.get("results", [])]
    return {
        "query": case["query"],
        "tag": case["tag"],
        "expected": case["expected_top_k"],
        "got": got_ids,
        "recall_at_k": _recall_at_k(case["expected_top_k"], got_ids),
        "reciprocal_rank": _reciprocal_rank(case["expected_top_k"], got_ids),
        "passed": _recall_at_k(case["expected_top_k"], got_ids) == 1.0,
    }


async def _amain(seed: bool, via_mcp: bool) -> int:
    logging.basicConfig(level="INFO")
    db_conn.configure_engine(get_settings().database_url)

    cases = _load_dataset(DATASET)
    log.info("loaded %d eval cases", len(cases))

    if seed:
        async with db_conn.session_scope() as session:
            await seed_reference_foods(session)
        log.info("eval seed applied")

    per_case: list[dict] = []
    if via_mcp:
        from zeff.mcp.server import build_server

        server = build_server()
        for case in cases:
            per_case.append(await _run_one_via_mcp(server, case))
    else:
        async with db_conn.session_scope() as session:
            for case in cases:
                per_case.append(await _run_one(session, case))

    n = len(per_case)
    pass_count = sum(1 for r in per_case if r["passed"])
    recall_at_k = sum(r["recall_at_k"] for r in per_case) / n
    mrr = sum(r["reciprocal_rank"] for r in per_case) / n

    by_tag: dict[str, list[dict]] = defaultdict(list)
    for r in per_case:
        by_tag[r["tag"]].append(r)
    tag_summary = {
        tag: {
            "count": len(rs),
            "pass_rate": sum(1 for r in rs if r["passed"]) / len(rs),
            "recall": sum(r["recall_at_k"] for r in rs) / len(rs),
        }
        for tag, rs in sorted(by_tag.items())
    }

    report = {
        "timestamp": datetime.now(tz=UTC).isoformat(),
        "n_cases": n,
        "pass_count": pass_count,
        "pass_rate": pass_count / n,
        "mean_recall_at_k": recall_at_k,
        "mrr": mrr,
        "by_tag": tag_summary,
        "cases": per_case,
    }

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = REPORT_DIR / f"search_{datetime.now(tz=UTC).strftime('%Y-%m-%d_%H%M%S')}.json"
    out_path.write_text(json.dumps(report, indent=2))

    log.info("=" * 60)
    log.info(
        "RESULTS  n=%d  pass_rate=%.3f  recall@k=%.3f  mrr=%.3f",
        n,
        pass_count / n,
        recall_at_k,
        mrr,
    )
    log.info("by_tag:")
    for tag, s in tag_summary.items():
        log.info(
            "  %-22s n=%-2d pass=%.2f recall=%.2f", tag, s["count"], s["pass_rate"], s["recall"]
        )
    log.info("report: %s", out_path.relative_to(REPO_ROOT))
    log.info("=" * 60)

    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-seed", dest="seed", action="store_false", default=True)
    parser.add_argument(
        "--via-mcp",
        dest="via_mcp",
        action="store_true",
        default=False,
        help="Call search through the MCP tool wrapper (parity check).",
    )
    args = parser.parse_args()
    return asyncio.run(_amain(seed=args.seed, via_mcp=args.via_mcp))


if __name__ == "__main__":
    raise SystemExit(main())
