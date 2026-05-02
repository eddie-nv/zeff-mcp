# Quality baselines

Append-only log. Each milestone that runs an eval records its numbers here.

## M9 — Consumption history (2026-05-02)

No new eval runner — coverage is exclusively via integration tests:
20 unit-of-record tests on `domain.history.get_consumption_history`
and 9 MCP-wrapper tests. All four `group_by` paths (none, day, category,
nova_group), time-range parsing, user isolation, and invalid input
handled.

All 6 v1 MCP tools live: search_foods, get_food, browse_category,
get_food_components, get_pantry_state, get_consumption_history.

---

**Dataset:** `evals/datasets/pantry_scenarios.jsonl` (16 hand-crafted scenarios)
**Run:** `python -m evals.runners.run_pantry_eval`

| Metric    | Value | Threshold |
|-----------|------:|----------:|
| Pass rate | 1.000 |     ≥0.95 |

Scenarios cover: not-yet-expired, just-expired, no-decay (long-lived),
default storage mode picks (refrigerated > pantry > frozen), multiple
acquisitions of the same food, mixed baskets, user isolation, empty
pantry, and shelf-life differences (fuji vs honeycrisp).

---

## M7 — Taxonomy with composites (2026-05-02)

**Dataset:** 126 entries (116 primitives + 10 composites)
**DB:** 19 categories + 515 primitives + 10 composites + 38 component edges + 5 facets per node
**Run:** `make eval` or `python -m evals.runners.run_taxonomy_eval`

| Metric            | Value | Threshold |
|-------------------|------:|----------:|
| Parent accuracy   | 1.000 |     1.000 |
| Mean facet acc.   | 1.000 |    ≥0.950 |

By facet: nova_group 126/126, requires_cooking 126/126, dietary_flags
116/116, allergens 116/116, decay 21/21 (11 reference primitives + 10
composites). Composite facets are hand-curated in `data/composites.json`.

The taxonomy runner now pre-seeds reference foods + re-runs facets
so the eval is self-contained vs the live DB after `make seed`.

---

## M4 — Taxonomy correctness (2026-05-02)

**Dataset:** `evals/datasets/taxonomy_truth.jsonl` (116 hand-curated entries)
**DB:** 20 categories + 499 primitives + 5 facets per primitive (2,495 facet rows)
**Run:** `python -m evals.runners.run_taxonomy_eval`

| Metric            | Value | Threshold |
|-------------------|------:|----------:|
| Parent accuracy   | 1.000 |     1.000 |
| Mean facet acc.   | 1.000 |    ≥0.950 |

By facet (across 116 entries):

| Facet            | Correct | Total | Accuracy |
|------------------|--------:|------:|---------:|
| nova_group       |     116 |   116 |    1.000 |
| dietary_flags    |     116 |   116 |    1.000 |
| allergens        |     116 |   116 |    1.000 |
| requires_cooking |     116 |   116 |    1.000 |
| decay            |      11 |    11 |    1.000 |

Approach: pure-function rules in `seeds/facet_rules.py` with hand-curated
overrides (`DECAY_BY_NODE`, `ALLERGEN_OVERRIDES_BY_NODE`,
`NEEDS_COOKING_NODE_IDS`). 71 unit tests guard the rules. Iterated from
0% → 95.4% → 99.4% → 100% across three rule fixes:
1. Recursive parent resolution for dietary_flags (apple → fruit chain)
2. NOVA-3 token expansion (fried, noodles, couscous, eggnog) + NOVA-2 flour
3. requires_cooking: red_meat default→needs cook (steak override),
   plant_protein nut allowlist, grain default→needs cook (flour/bran override),
   "uncooked" no longer matches "cooked" prefix

---

## M3.6 — Search after adding 20 USDA-derived cases (2026-05-02)

**Dataset:** 62 cases (42 original + 20 drawn from the seeded USDA data)
**DB:** unchanged from M3 (20 categories + 499 primitives)
**Run:** `python -m evals.runners.run_search_eval --no-seed`

| Metric          | Value | Threshold |
|-----------------|------:|----------:|
| Pass rate       | 0.935 |       —   |
| Mean Recall@k   | 0.941 |     ≥0.85 |
| MRR             | 0.884 |       —   |

USDA-tagged breakdown:

| Tag             |   n | Pass rate | Recall |
|-----------------|----:|----------:|-------:|
| usda_exact      |   7 |      0.86 |   0.86 |
| usda_compound   |   6 |      1.00 |   1.00 |
| usda_alt        |   5 |      0.80 |   0.80 |
| usda_partial    |   1 |      1.00 |   1.00 |
| usda_word_order |   1 |      1.00 |   1.00 |

---

## M3 — Search after USDA SR seed (2026-05-02)

**Dataset:** `evals/datasets/search_queries.jsonl` (42 cases — unchanged from M2)
**DB:** 19 canonical categories + 490 USDA SR Legacy primitives + 11 reference foods
   = 519 nodes total (some categories overlap, actual: 20 categories + 499 primitives)
**Run:** `python -m evals.runners.run_search_eval`

| Metric          | Value | Threshold | M2 baseline | Δ      |
|-----------------|------:|----------:|------------:|-------:|
| Pass rate       | 0.952 |       —   |       1.000 | -0.048 |
| Mean Recall@k   | 0.960 |     ≥0.85 |       1.000 | -0.040 |
| MRR             | 0.901 |       —   |       0.964 | -0.063 |

### By tag

| Tag                     |   n | Pass rate | Recall |
|-------------------------|----:|----------:|-------:|
| exact_label             |   9 |      1.00 |   1.00 |
| exact_case_insensitive  |   1 |      1.00 |   1.00 |
| alt_label               |  20 |      1.00 |   1.00 |
| alt_label_partial       |   1 |      1.00 |   1.00 |
| alt_label_scientific    |   1 |      1.00 |   1.00 |
| abbreviation            |   1 |      1.00 |   1.00 |
| typo                    |   2 |      0.50 |   0.50 |
| plural                  |   1 |      1.00 |   1.00 |
| qualifier_word          |   1 |      1.00 |   1.00 |
| regional_name           |   2 |      1.00 |   1.00 |
| ambiguous               |   2 |      0.50 |   0.67 |
| no_match                |   1 |      1.00 |   1.00 |

### Notes on regressions

- **Ambiguous queries** (`apple`, `chicken`): the per-tag pass rate drops from
  1.00 → 0.50 because USDA introduces ~20 chicken variants and ~5 apple
  variants that crowd the top-k. The `apple` query still finds
  `honeycrisp_apple` but the second expected (`fuji_apple`) gets bumped out
  of top-3 by USDA's `apples_raw_with_skin`.
- **Typo `spinch`** drops because USDA's spinach variants change the trigram
  ranking distribution.

Both are realistic with the larger corpus and stay above the milestone
threshold. M3.6 will add USDA-derived eval cases.

---

## M2 — Search baseline (2026-05-02)

**Dataset:** `evals/datasets/search_queries.jsonl` (41 + 1 no_match = 42 cases)
**Reference data:** the 11 v1 reference primitives from DESIGN.md, seeded by `evals/runners/eval_seed.py` (replaced by USDA SR import in M3)
**Run:** `python -m evals.runners.run_search_eval`

| Metric          | Value | Threshold | Status |
|-----------------|------:|----------:|--------|
| Pass rate       | 1.000 |       —   | ✅     |
| Mean Recall@k   | 1.000 |     ≥0.85 | ✅     |
| MRR             | 0.964 |       —   | ✅     |

### By tag

| Tag                     |   n | Pass rate | Recall |
|-------------------------|----:|----------:|-------:|
| exact_label             |   9 |      1.00 |   1.00 |
| exact_case_insensitive  |   1 |      1.00 |   1.00 |
| alt_label               |  20 |      1.00 |   1.00 |
| alt_label_partial       |   1 |      1.00 |   1.00 |
| alt_label_scientific    |   1 |      1.00 |   1.00 |
| abbreviation            |   1 |      1.00 |   1.00 |
| typo                    |   2 |      1.00 |   1.00 |
| plural                  |   1 |      1.00 |   1.00 |
| qualifier_word          |   1 |      1.00 |   1.00 |
| regional_name           |   2 |      1.00 |   1.00 |
| ambiguous               |   2 |      1.00 |   1.00 |
| no_match                |   1 |      1.00 |   1.00 |

### Notes

- The MRR < 1.0 reflects ambiguous queries ("apple", "chicken") where the
  expected primary hit is not always at rank 1 — by design (these are
  queries the user hasn't disambiguated yet).
- Eval is run against the 11-foods reference set. M3 re-runs against the
  full ~500-food USDA seed; expect MRR to dip and require iteration.
- The dataset will grow in M3 (+20 cases drawn from the seeded data).
