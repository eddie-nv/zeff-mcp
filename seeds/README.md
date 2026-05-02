# Seed sources

## USDA SR Legacy (FoodData Central)

**Source:** https://fdc.nal.usda.gov/fdc-datasets/FoodData_Central_sr_legacy_food_csv_2018-04.zip
**Version:** SR Legacy 2018-04 (April 2018, minor revision July 2018)
**Status:** Final release — no further updates from USDA.
**Row count:** ~7,793 foods; we filter to ~500.

The bulk download is a ZIP containing several CSVs in the unified FoodData
Central schema. We use:

- `food.csv` — columns `fdc_id`, `description`, `food_category_id`, …
- `food_category.csv` — columns `id`, `code`, `description`

### Fetch

```bash
./scripts/fetch_usda_sr.sh
```

This downloads + unzips into `data/raw/sr_legacy/`. The directory is in
`.gitignore`; raw data is never committed.

### Run the seed

```bash
make migrate
make seed-canonical    # category tree first
make seed-usda         # ~500 primitives
```

The seed is idempotent: re-running upserts existing rows by id and inserts
only what's missing.

### Mapping USDA → canonical taxonomy

USDA SR Legacy uses a flat 4-digit food group code (e.g. `0100 Dairy and
Egg Products`). We hand-map each USDA category to a leaf in our canonical
tree (`src/zeff/seeds/usda_sr.py::USDA_CATEGORY_MAP`). Categories without
a mapping are skipped — see the SKIPPED constant for the rationale.
