"""USDA SR Legacy ingest pipeline.

Parses food.csv + food_category.csv from FoodData Central's SR Legacy bulk
download, filters to ~500 useful primitives, slugifies ids, populates
alt_labels from description tokens, maps to a canonical taxonomy parent,
and records the `usda_sr` external id.

USDA categories that map cleanly to v1 leaves are kept; composite-heavy
or branded categories (Baby Foods, Fast Foods, Restaurant Foods, etc.)
are skipped — see `SKIPPED_CATEGORY_IDS` for the rationale.

CLI:

    python -m zeff.seeds.usda_sr [--csv-dir PATH] [--cap-total N]
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from zeff.config import get_settings
from zeff.db import connection as db_conn
from zeff.db.models import Node, NodeExternalId
from zeff.seeds.canonical import seed_canonical

log = logging.getLogger(__name__)

DEFAULT_CSV_DIR = Path("data/raw/sr_legacy")
EXTERNAL_SOURCE = "usda_sr"

# USDA category id (string from CSV) → canonical leaf id.
# Pork, lamb, veal, and game all roll up under red_meat for v1.
USDA_CATEGORY_MAP: dict[str, str] = {
    "1": "dairy",  # Dairy and Egg Products — refined per-row by pick_canonical_parent
    "2": "seasoning",  # Spices and Herbs
    "4": "fat_and_oil",  # Fats and Oils
    "5": "poultry",  # Poultry Products
    "9": "fruit",  # Fruits and Fruit Juices
    "10": "red_meat",  # Pork Products
    "11": "vegetable",  # Vegetables and Vegetable Products
    "12": "plant_protein",  # Nut and Seed Products
    "13": "red_meat",  # Beef Products
    "14": "beverage",  # Beverages
    "15": "seafood",  # Finfish and Shellfish Products
    "16": "plant_protein",  # Legumes and Legume Products
    "17": "red_meat",  # Lamb, Veal, and Game Products
    "20": "grain",  # Cereal Grains and Pasta — splits into whole/refined per-row
}

# Categories we skip outright. Each is composite-heavy, branded, or out-of-scope
# for v1 primitives.
SKIPPED_CATEGORY_IDS: frozenset[str] = frozenset(
    {
        "3",  # Baby Foods
        "6",  # Soups, Sauces, and Gravies (composites)
        "7",  # Sausages and Luncheon Meats (composites)
        "8",  # Breakfast Cereals (mostly branded)
        "18",  # Baked Products (composites)
        "19",  # Sweets (mostly processed)
        "21",  # Fast Foods
        "22",  # Meals, Entrees, and Side Dishes
        "23",  # Snacks
        "24",  # American Indian/Alaska Native Foods (regional cuisine)
        "25",  # Restaurant Foods
        "26",  # Branded Food Products Database
        "27",  # Quality Control Materials
        "28",  # Alcoholic Beverages (out of scope for v1)
    }
)

# Per-canonical-parent caps so we land near ~500 total without one category
# (e.g., beef, with 954 USDA rows) drowning the rest.
PARENT_CAPS: dict[str, int] = {
    "vegetable": 80,
    "fruit": 50,
    "red_meat": 80,
    "poultry": 40,
    "seafood": 40,
    "milk_product": 20,
    "cheese": 25,
    "cultured_dairy": 10,
    "egg": 5,
    "plant_protein": 35,
    "grain": 20,
    "whole_grain": 15,
    "refined_grain": 15,
    "fat_and_oil": 25,
    "seasoning": 25,
    "beverage": 25,
}

_WHOLE_GRAIN_TOKENS = {
    "whole",
    "brown",
    "wild",
    "barley",
    "oat",
    "oats",
    "quinoa",
    "millet",
    "buckwheat",
    "bulgur",
    "spelt",
    "rye",
}
_SLUG_RE = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class ParsedFood:
    node_id: str
    pref_label: str
    alt_labels: list[str] = field(default_factory=list)
    parent_id: str = ""
    fdc_id: str = ""
    usda_category_id: str = ""


def slugify_description(desc: str) -> str:
    """Lowercase, replace non-alphanumeric runs with `_`, strip ends.

    Raises ValueError if the result would be empty. If the result starts
    with a digit (Node id rule forbids leading digits), prepends `x_`.
    """
    s = _SLUG_RE.sub("_", desc.lower()).strip("_")
    if not s:
        raise ValueError(f"description {desc!r} produced an empty slug")
    if not s[0].isalpha():
        s = f"x_{s}"
    return s


def derive_alt_labels(desc: str) -> list[str]:
    """Split a description on commas; the first chunk is the pref, rest are alts.

    Strips, dedupes, drops empties.
    """
    parts = [p.strip() for p in desc.split(",")]
    parts = [p for p in parts if p]
    if len(parts) <= 1:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for p in parts[1:]:
        low = p.lower()
        if low in seen:
            continue
        seen.add(low)
        out.append(p)
    return out


def _is_whole_grain(desc: str) -> bool:
    tokens = set(re.findall(r"[a-z]+", desc.lower()))
    return bool(tokens & _WHOLE_GRAIN_TOKENS)


def pick_canonical_parent(
    *,
    description: str,
    usda_category_id: str,
    categories: dict[str, str],
) -> str | None:
    """Return the canonical-tree leaf id for a USDA row, or None to skip."""
    if usda_category_id in SKIPPED_CATEGORY_IDS:
        return None

    base = USDA_CATEGORY_MAP.get(usda_category_id)
    if base is None:
        return None

    desc_low = description.lower()

    # Refine "Dairy and Egg Products" into egg / cheese / cultured_dairy / milk_product.
    if usda_category_id == "1":
        if desc_low.startswith("egg"):
            return "egg"
        if desc_low.startswith("cheese"):
            return "cheese"
        if desc_low.startswith(("yogurt", "kefir", "buttermilk", "sour cream")):
            return "cultured_dairy"
        return "milk_product"

    # Refine grain into whole vs refined.
    if usda_category_id == "20":
        return "whole_grain" if _is_whole_grain(desc_low) else "refined_grain"

    return base


def parse_categories(path: Path) -> dict[str, str]:
    """Load food_category.csv → { category_id: description }."""
    out: dict[str, str] = {}
    with path.open(newline="") as fh:
        for row in csv.DictReader(fh):
            out[row["id"]] = row["description"]
    return out


def parse_foods(
    food_csv: Path,
    categories: dict[str, str],
    *,
    cap_total: int | None = None,
    parent_caps: dict[str, int] | None = None,
) -> list[ParsedFood]:
    """Stream food.csv, return filtered ParsedFood list with per-parent caps applied.

    Within each parent we sort by description length (shorter ≈ more general)
    so generic entries get in first when caps bite.
    """
    caps = parent_caps if parent_caps is not None else PARENT_CAPS

    # First pass: gather everything mapped, then apply caps.
    by_parent: dict[str, list[ParsedFood]] = defaultdict(list)
    used_ids: set[str] = set()

    with food_csv.open(newline="") as fh:
        for row in csv.DictReader(fh):
            cat = row.get("food_category_id", "")
            desc = (row.get("description") or "").strip()
            fdc_id = (row.get("fdc_id") or "").strip()
            if not desc or not fdc_id:
                continue
            parent = pick_canonical_parent(
                description=desc,
                usda_category_id=cat,
                categories=categories,
            )
            if parent is None:
                continue

            base_id = slugify_description(desc)
            node_id = base_id
            counter = 2
            while node_id in used_ids:
                node_id = f"{base_id}_{counter}"
                counter += 1
            used_ids.add(node_id)

            pref_label = desc.split(",", 1)[0].strip().title() or desc
            by_parent[parent].append(
                ParsedFood(
                    node_id=node_id,
                    pref_label=pref_label,
                    alt_labels=derive_alt_labels(desc),
                    parent_id=parent,
                    fdc_id=fdc_id,
                    usda_category_id=cat,
                )
            )

    # Sort each parent bucket by (description length, alphabetical) and apply cap.
    out: list[ParsedFood] = []
    for parent, items in by_parent.items():
        items.sort(key=lambda f: (len(f.pref_label) + sum(len(a) for a in f.alt_labels), f.node_id))
        cap = caps.get(parent)
        out.extend(items[:cap] if cap else items)

    if cap_total is not None and len(out) > cap_total:
        # Final hard cap, preserving per-parent ordering.
        out.sort(key=lambda f: (f.parent_id, f.node_id))
        out = out[:cap_total]

    return out


# ---- DB write path -------------------------------------------------------


async def upsert_foods(session: AsyncSession, foods: list[ParsedFood]) -> tuple[int, int]:
    """Idempotent upsert of nodes + external IDs.

    Returns (n_node_upserts, n_external_id_upserts).
    """
    n_nodes = 0
    n_extids = 0
    for f in foods:
        node_stmt = insert(Node).values(
            id=f.node_id,
            type="primitive",
            pref_label=f.pref_label,
            alt_labels=f.alt_labels or None,
            parent_id=f.parent_id,
        )
        node_stmt = node_stmt.on_conflict_do_update(
            index_elements=[Node.id],
            set_={
                "pref_label": node_stmt.excluded.pref_label,
                "alt_labels": node_stmt.excluded.alt_labels,
                "parent_id": node_stmt.excluded.parent_id,
                "type": node_stmt.excluded.type,
            },
        )
        await session.execute(node_stmt)
        n_nodes += 1

        ext_stmt = insert(NodeExternalId).values(
            node_id=f.node_id,
            source=EXTERNAL_SOURCE,
            external_id=f.fdc_id,
        )
        # PK is (source, external_id); on conflict we leave the existing row.
        ext_stmt = ext_stmt.on_conflict_do_nothing(
            index_elements=[NodeExternalId.source, NodeExternalId.external_id]
        )
        await session.execute(ext_stmt)
        n_extids += 1
    return n_nodes, n_extids


async def seed_usda_sr(
    session: AsyncSession,
    csv_dir: Path = DEFAULT_CSV_DIR,
    *,
    cap_total: int | None = None,
) -> tuple[int, int]:
    """Run the full seed: categories first, then ingest mapped foods."""
    await seed_canonical(session)

    cats = parse_categories(csv_dir / "food_category.csv")
    foods = parse_foods(csv_dir / "food.csv", cats, cap_total=cap_total)
    log.info("USDA: parsed %d foods (cap_total=%s)", len(foods), cap_total)

    n_nodes, n_ext = await upsert_foods(session, foods)
    log.info("USDA: upserted %d nodes / %d external_ids", n_nodes, n_ext)
    return n_nodes, n_ext


async def _amain(csv_dir: Path, cap_total: int | None) -> int:
    logging.basicConfig(level=get_settings().log_level)
    db_conn.configure_engine(get_settings().database_url)
    async with db_conn.session_scope() as session:
        await seed_usda_sr(session, csv_dir, cap_total=cap_total)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--csv-dir",
        type=Path,
        default=DEFAULT_CSV_DIR,
        help="Directory containing food.csv and food_category.csv",
    )
    ap.add_argument("--cap-total", type=int, default=None, help="Hard cap on total foods seeded")
    args = ap.parse_args()
    return asyncio.run(_amain(args.csv_dir, args.cap_total))


if __name__ == "__main__":
    raise SystemExit(main())
