# Seed review log

Manual spot-check of 50 random nodes from the M3 USDA seed.

## Issues found

### 1. `pref_label` collapses to the generic head token

USDA descriptions go broad → specific (`Fish, salmon, Atlantic, wild, raw`).
Our v0 parser uses the first comma-token as `pref_label`, so rows headed
by a category word ("Fish", "Cream", "Beverages", "Nuts", "Chicken",
"Beef", "Fat", "Oil", "Game Meat", "Cheese", "Yogurt") all share an
unhelpful pref_label.

**Examples seen in the spot-check:**

- `fish_swordfish_raw` → "Fish"
- `cream_sour_cultured` → "Cream"
- `beverages_water_tap_well` → "Beverages"
- `nuts_almonds` → "Nuts"
- `chicken_capons_giblets_raw` → "Chicken"
- `game_meat_horse_raw` → "Game Meat"
- `fat_goose` → "Fat"

**Why it matters:** the M2 search ranking gives the highest score to exact
case-insensitive match on `pref_label`. With a generic label, the search
must fall back to trigram on `alt_labels_text` — works but ranks lower
and is more sensitive to the similarity floor.

**Fix:** when the first comma-token is in a known generic-head set,
combine with the second token. So `Fish, salmon, Atlantic, ...` becomes
`Fish Salmon` and `Cream, sour, cultured` becomes `Cream Sour`.

**Status:** fixed in commit M3: improve pref_label for generic-headed rows.

### 2. `eggnog` is parented under `egg`

The `desc.startswith("egg")` rule routes "Eggnog, prepared with..." to
the `egg` parent. Eggnog is functionally `cultured_dairy` / `beverage`.

**Status:** acknowledged, not fixed for v1. Will get caught by the
taxonomy eval in M4 if it matters; one outlier doesn't justify a more
elaborate parent picker.

### 3. `frog_legs_raw` is under `seafood`

USDA puts frog in category 1500 (Finfish and Shellfish), so the parser
inherits. Frog isn't seafood by any common usage.

**Status:** acknowledged, not fixed for v1. Same justification as #2.

### 4. `bacon_meatless` under `plant_protein`

USDA puts bacon substitutes in category 1200 (Nut and Seed Products).
Inherits correctly per the source data.

**Status:** correct, no action.
