"""Run the pantry eval and emit a JSON report.

Each scenario gets a dedicated user_id (`eval_<scenario>`) so we can run
them all against the same DB without interference. For each scenario:

    1. Pre-seed reference foods + facets (idempotent).
    2. Insert the scenario's ingest records under a scoped user_id.
    3. Call compute_pantry_state(user_id, as_of).
    4. Compare returned multiset of node_ids against expected_pantry.
       (We compare multisets — multiple acquisitions of the same food
       must each appear.)

Threshold: pass rate >= 95%.

CLI:
    python -m evals.runners.run_pantry_eval
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypedDict
from uuid import uuid4

from sqlalchemy import delete

from evals.runners.eval_seed import seed_reference_foods
from zeff.config import get_settings
from zeff.db import connection as db_conn
from zeff.db import queries
from zeff.db.models import IngestRecord
from zeff.domain.pantry import compute_pantry_state
from zeff.seeds.facets import seed_facets

REPO_ROOT = Path(__file__).resolve().parents[2]
DATASET = REPO_ROOT / "evals" / "datasets" / "pantry_scenarios.jsonl"
REPORT_DIR = REPO_ROOT / "evals" / "reports"

PASS_THRESHOLD = 0.95

log = logging.getLogger(__name__)


class _Ingest(TypedDict, total=False):
    node_id: str
    acquired_at: str
    quantity: float


class _Expected(TypedDict, total=False):
    node_id: str
    quantity: float


class Scenario(TypedDict):
    name: str
    ingests: list[_Ingest]
    as_of: str
    expected_pantry: list[_Expected]


def _load(path: Path) -> list[Scenario]:
    out: list[Scenario] = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        out.append(json.loads(line))
    return out


def _multiset(items: list[Any], key: str = "node_id") -> Counter:
    return Counter(getattr(it, key) if hasattr(it, key) else it[key] for it in items)


async def _run_one(session, scenario: Scenario) -> dict:
    user_id = f"eval_{scenario['name']}_{uuid4().hex[:8]}"

    for ingest in scenario["ingests"]:
        await queries.add_ingest_record(
            session,
            user_id=user_id,
            node_id=ingest["node_id"],
            acquired_at=datetime.fromisoformat(ingest["acquired_at"]),
            quantity=ingest.get("quantity"),
        )
    await session.commit()

    as_of = datetime.fromisoformat(scenario["as_of"])
    actual = await compute_pantry_state(session, user_id, as_of=as_of)

    actual_multiset = _multiset(actual)
    expected_multiset = _multiset(scenario["expected_pantry"])
    passed = actual_multiset == expected_multiset

    # Cleanup: remove records for this scoped user.
    await session.execute(delete(IngestRecord).where(IngestRecord.user_id == user_id))
    await session.commit()

    return {
        "name": scenario["name"],
        "expected": dict(expected_multiset),
        "actual": dict(actual_multiset),
        "passed": passed,
    }


async def _amain() -> int:
    logging.basicConfig(level="INFO")
    db_conn.configure_engine(get_settings().database_url)

    scenarios = _load(DATASET)
    log.info("loaded %d scenarios", len(scenarios))

    # Self-contained: ensure reference foods + facets exist.
    async with db_conn.session_scope() as session:
        await seed_reference_foods(session)
        await seed_facets(session)

    per_case: list[dict] = []
    async with db_conn.session_scope() as session:
        for scenario in scenarios:
            per_case.append(await _run_one(session, scenario))

    n = len(per_case)
    pass_count = sum(1 for r in per_case if r["passed"])
    pass_rate = pass_count / n if n else 0.0

    report = {
        "timestamp": datetime.now(tz=UTC).isoformat(),
        "n_scenarios": n,
        "pass_count": pass_count,
        "pass_rate": pass_rate,
        "thresholds": {"pass_rate": PASS_THRESHOLD},
        "cases": per_case,
    }

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = REPORT_DIR / f"pantry_{datetime.now(tz=UTC).strftime('%Y-%m-%d_%H%M%S')}.json"
    out_path.write_text(json.dumps(report, indent=2))

    log.info("=" * 60)
    log.info("RESULTS  n=%d  pass_rate=%.3f", n, pass_rate)
    for case in per_case:
        flag = "PASS" if case["passed"] else "FAIL"
        log.info("  %-50s %s", case["name"], flag)
        if not case["passed"]:
            log.info("    expected=%s", case["expected"])
            log.info("    actual=%s", case["actual"])
    log.info("report: %s", out_path.relative_to(REPO_ROOT))
    log.info("=" * 60)

    return 0 if pass_rate >= PASS_THRESHOLD else 1


def main() -> int:
    return asyncio.run(_amain())


if __name__ == "__main__":
    raise SystemExit(main())
