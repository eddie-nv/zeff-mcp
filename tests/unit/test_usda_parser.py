"""Unit tests for the USDA SR Legacy parser (no DB)."""

from __future__ import annotations

from pathlib import Path

import pytest

from zeff.seeds.usda_sr import (
    SKIPPED_CATEGORY_IDS,
    USDA_CATEGORY_MAP,
    ParsedFood,
    derive_alt_labels,
    derive_pref_label,
    parse_categories,
    parse_foods,
    pick_canonical_parent,
    slugify_description,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


class TestSlugify:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("Apples, raw, with skin", "apples_raw_with_skin"),
            ("Spinach, raw", "spinach_raw"),
            ("Salt, table, iodized", "salt_table_iodized"),
            ("Beverages, water, tap, drinking", "beverages_water_tap_drinking"),
            # Apostrophes / dashes drop
            ("McDonald's burger", "mcdonald_s_burger"),
            ("Cheddar - sharp", "cheddar_sharp"),
            # Quote chars stripped
            ('Beef trimmed to 1/8" fat', "beef_trimmed_to_1_8_fat"),
            # Multiple commas / spaces collapse
            ("Beef,,, raw   ", "beef_raw"),
        ],
    )
    def test_slugs(self, raw: str, expected: str) -> None:
        assert slugify_description(raw) == expected

    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError):
            slugify_description("")

    def test_punctuation_only_raises(self) -> None:
        with pytest.raises(ValueError):
            slugify_description("---,,,")

    def test_leading_digit_gets_letter_prefix(self) -> None:
        assert slugify_description("100% beef") == "x_100_beef"


class TestDerivePrefLabel:
    @pytest.mark.parametrize(
        "desc,expected",
        [
            ("Apples, raw, with skin", "Apples"),
            ("Spinach, raw", "Spinach"),
            ("Salt, table, iodized", "Salt"),
            # Generic heads combine with next token
            ("Fish, salmon, Atlantic, wild, raw", "Fish Salmon"),
            ("Cream, sour, cultured", "Cream Sour"),
            ("Beverages, water, tap, drinking", "Beverages Water"),
            ("Nuts, almonds", "Nuts Almonds"),
            ("Cheese, mozzarella, low moisture, part-skim", "Cheese Mozzarella"),
            ("Chicken, broilers or fryers, breast, meat only, raw", "Chicken Broilers Or Fryers"),
            ("Beef, short loin, top loin steak, boneless", "Beef Short Loin"),
            # Solo words
            ("Eggnog", "Eggnog"),
        ],
    )
    def test_pref_label(self, desc: str, expected: str) -> None:
        assert derive_pref_label(desc) == expected


class TestDeriveAltLabels:
    def test_first_token_is_dropped_others_kept(self) -> None:
        # "Apples, raw, with skin" → primary is "apples", alts capture variants
        alts = derive_alt_labels("Apples, raw, with skin")
        assert "raw" in alts
        assert "with skin" in alts
        assert "apples" not in alts  # the leading token is the pref_label

    def test_dedupes_and_strips(self) -> None:
        alts = derive_alt_labels("Beef, raw,  raw  , trimmed")
        assert alts.count("raw") == 1
        assert "trimmed" in alts

    def test_singleton_label_no_alts(self) -> None:
        assert derive_alt_labels("Salt") == []


class TestCategoryMapping:
    def test_v1_mapped_categories_resolve_to_canonical(self) -> None:
        # Every value in the mapping must be a canonical-tree id.
        from zeff.seeds.canonical import CANONICAL_TREE

        canonical_ids = {entry["id"] for entry in CANONICAL_TREE}
        for usda_cat, parent_id in USDA_CATEGORY_MAP.items():
            assert parent_id in canonical_ids, (
                f"USDA category {usda_cat!r} mapped to {parent_id!r} "
                "which is not a canonical category"
            )

    def test_skipped_categories_not_in_map(self) -> None:
        for sid in SKIPPED_CATEGORY_IDS:
            assert sid not in USDA_CATEGORY_MAP

    def test_pick_egg_under_egg_not_dairy(self) -> None:
        # USDA category 1 is "Dairy and Egg Products" — eggs route to `egg`.
        parent = pick_canonical_parent(
            description="Egg, whole, raw, fresh",
            usda_category_id="1",
            categories={"1": "Dairy and Egg Products"},
        )
        assert parent == "egg"

    def test_pick_cheese_under_cheese(self) -> None:
        parent = pick_canonical_parent(
            description="Cheese, mozzarella, low moisture, part-skim",
            usda_category_id="1",
            categories={"1": "Dairy and Egg Products"},
        )
        assert parent == "cheese"

    def test_pick_milk_under_milk_product(self) -> None:
        parent = pick_canonical_parent(
            description="Milk, whole, 3.25% milkfat, with added vitamin D",
            usda_category_id="1",
            categories={"1": "Dairy and Egg Products"},
        )
        assert parent == "milk_product"

    def test_pick_yogurt_under_cultured_dairy(self) -> None:
        parent = pick_canonical_parent(
            description="Yogurt, plain, whole milk, 8 grams of protein per 8 oz",
            usda_category_id="1",
            categories={"1": "Dairy and Egg Products"},
        )
        assert parent == "cultured_dairy"

    def test_pick_skipped_category_returns_none(self) -> None:
        assert (
            pick_canonical_parent(
                description="Babyfood, cereal, mixed",
                usda_category_id="3",
                categories={"3": "Baby Foods"},
            )
            is None
        )


class TestParseCategories:
    def test_loads_fixture(self) -> None:
        cats = parse_categories(FIXTURES / "usda_food_category.csv")
        assert cats["1"] == "Dairy and Egg Products"
        assert cats["13"] == "Beef Products"


class TestParseFoods:
    def test_includes_only_mapped_categories(self) -> None:
        cats = parse_categories(FIXTURES / "usda_food_category.csv")
        foods = parse_foods(FIXTURES / "usda_food.csv", cats)
        cat_ids = {f.usda_category_id for f in foods}
        # Skipped: Baby Foods (3), Fast Foods (21), Meals (22), AI/AN Foods (24)
        assert "3" not in cat_ids
        assert "21" not in cat_ids
        assert "22" not in cat_ids
        assert "24" not in cat_ids

    def test_yields_parsed_food_with_required_fields(self) -> None:
        cats = parse_categories(FIXTURES / "usda_food_category.csv")
        foods = parse_foods(FIXTURES / "usda_food.csv", cats)
        for f in foods:
            assert isinstance(f, ParsedFood)
            assert f.node_id and f.node_id == f.node_id.lower()
            assert f.pref_label
            assert f.parent_id
            assert f.fdc_id
            assert f.usda_category_id

    def test_dedupes_collisions_with_suffix(self) -> None:
        # Construct a temporary CSV with two foods that slug to the same id.
        import csv
        import tempfile

        cats = parse_categories(FIXTURES / "usda_food_category.csv")
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as tf:
            w = csv.writer(tf)
            w.writerow(
                ["fdc_id", "data_type", "description", "food_category_id", "publication_date"]
            )
            w.writerow(["1", "sr_legacy_food", "Apples, raw", "9", "2019-04-01"])
            w.writerow(["2", "sr_legacy_food", "Apples raw", "9", "2019-04-01"])
            path = Path(tf.name)
        foods = parse_foods(path, cats)
        ids = [f.node_id for f in foods]
        assert len(ids) == len(set(ids)), f"duplicate ids: {ids}"

    def test_alt_labels_populated_from_description(self) -> None:
        cats = parse_categories(FIXTURES / "usda_food_category.csv")
        foods = parse_foods(FIXTURES / "usda_food.csv", cats)
        apples = next(f for f in foods if "apple" in f.node_id)
        assert "raw" in apples.alt_labels or "with skin" in apples.alt_labels
