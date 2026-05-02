#!/usr/bin/env bash
# Fetch the USDA SR Legacy bulk CSV from FoodData Central into data/raw/sr_legacy/.
# Idempotent: re-runs only download if the zip is missing.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RAW="$ROOT/data/raw/sr_legacy"
URL="https://fdc.nal.usda.gov/fdc-datasets/FoodData_Central_sr_legacy_food_csv_2018-04.zip"
ZIP="$RAW/sr_legacy.zip"

mkdir -p "$RAW"

if [[ -f "$ZIP" ]]; then
  echo "[fetch_usda_sr] $ZIP already present; skipping download"
else
  echo "[fetch_usda_sr] downloading $URL"
  curl -fL --retry 3 --retry-delay 2 -o "$ZIP" "$URL"
fi

if [[ ! -f "$RAW/food.csv" || ! -f "$RAW/food_category.csv" ]]; then
  echo "[fetch_usda_sr] unzipping into $RAW"
  unzip -o -q "$ZIP" -d "$RAW"
  # The zip nests files in a versioned subdir; flatten the CSVs we care about.
  NESTED="$(find "$RAW" -mindepth 1 -maxdepth 1 -type d -name 'FoodData_Central_*' | head -n 1)"
  if [[ -n "$NESTED" ]]; then
    for f in food.csv food_category.csv sr_legacy_food.csv; do
      [[ -f "$NESTED/$f" ]] && cp "$NESTED/$f" "$RAW/$f"
    done
  fi
fi

echo "[fetch_usda_sr] ready:"
ls -1 "$RAW"/*.csv 2>/dev/null | sed 's|.*/|  - |'
