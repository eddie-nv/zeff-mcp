# Quality baselines

Append-only log. Each milestone that runs an eval records its numbers here.

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
