# Quality baselines

Append-only log. Each milestone that runs an eval records its numbers here.

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
