"""Unit tests for the facet-assignment rules used by seeds.facets."""

from __future__ import annotations

import pytest

from zeff.seeds.facet_rules import (
    assign_allergens,
    assign_decay,
    assign_dietary_flags,
    assign_nova_group,
    assign_requires_cooking,
)


class TestNovaGroup:
    @pytest.mark.parametrize(
        "node_id,parent_id,expected",
        [
            ("apple_raw", "fruit", 1),
            ("spinach_raw", "vegetable", 1),
            ("chicken_breast_raw", "poultry", 1),
            ("salmon_raw", "seafood", 1),
            ("ny_strip_steak_raw", "red_meat", 1),
            ("yogurt_plain_low_fat", "cultured_dairy", 3),
            ("cheese_cheshire", "cheese", 3),
            ("salt", "seasoning", 2),
            ("oil_canola", "fat_and_oil", 2),
            ("lard", "fat_and_oil", 2),
            ("candied_fruit", "fruit", 3),  # processed
            ("beef_cured_corned_beef_brisket_cooked", "red_meat", 3),  # cured
            ("pork_cured_bacon_cooked_baked", "red_meat", 3),  # cured
        ],
    )
    def test_nova(self, node_id: str, parent_id: str, expected: int) -> None:
        assert assign_nova_group(node_id, parent_id, "", []) == expected


class TestRequiresCooking:
    @pytest.mark.parametrize(
        "node_id,parent_id,expected",
        [
            ("apple_raw", "fruit", False),
            ("spinach_raw", "vegetable", False),
            ("potato_raw", "vegetable", True),  # override
            ("chicken_breast_raw", "poultry", True),
            ("salmon_raw", "seafood", False),
            ("ny_strip_steak_raw", "red_meat", False),
            ("eggnog", "egg", False),  # already prepared
            ("rice_brown_long_grain_raw", "whole_grain", True),
            ("quinoa_cooked", "whole_grain", False),
            ("salt", "seasoning", False),
            ("mollusks_snail_raw", "seafood", True),  # override
            ("frog_legs_raw", "seafood", True),  # override
            ("game_meat_antelope_cooked_roasted", "red_meat", False),
        ],
    )
    def test_requires_cooking(self, node_id: str, parent_id: str, expected: bool) -> None:
        assert assign_requires_cooking(node_id, parent_id, "", []) == expected


class TestAllergens:
    @pytest.mark.parametrize(
        "node_id,parent_id,expected",
        [
            ("apple_raw", "fruit", []),
            ("spinach_raw", "vegetable", []),
            ("chicken_breast_raw", "poultry", []),
            ("ny_strip_steak_raw", "red_meat", []),
            ("salt", "seasoning", []),
            ("salmon_raw", "seafood", ["fish"]),
            ("fish_butterfish_raw", "seafood", ["fish"]),
            ("mollusks_snail_raw", "seafood", ["shellfish"]),
            ("yogurt_plain_low_fat", "cultured_dairy", ["milk"]),
            ("cheese_cheshire", "cheese", ["milk"]),
            ("milk_whole_3_25_fat", "milk_product", ["milk"]),
            ("eggnog", "egg", ["egg", "milk"]),
            ("nuts_almonds", "plant_protein", ["tree_nuts"]),
            ("peanuts_virginia_raw", "plant_protein", ["peanuts"]),
            ("tofu_fried", "plant_protein", ["soy"]),
            ("soy_flour_low_fat", "plant_protein", ["soy"]),
            ("oil_walnut", "fat_and_oil", ["tree_nuts"]),
            ("oil_almond", "fat_and_oil", ["tree_nuts"]),
            ("fish_oil_salmon", "fat_and_oil", ["fish"]),
            ("wheat_durum", "refined_grain", ["wheat"]),
            ("bulgur_dry", "whole_grain", ["wheat"]),
            ("couscous_cooked", "refined_grain", ["wheat"]),
        ],
    )
    def test_allergens(self, node_id: str, parent_id: str, expected: list[str]) -> None:
        assert sorted(assign_allergens(node_id, parent_id, "", [])) == sorted(expected)


class TestDietaryFlags:
    @pytest.mark.parametrize(
        "node_id,parent_id,allergens,expected",
        [
            ("apple_raw", "fruit", [], ["gluten_free", "vegan", "vegetarian"]),
            ("spinach_raw", "vegetable", [], ["gluten_free", "vegan", "vegetarian"]),
            ("oil_canola", "fat_and_oil", [], ["gluten_free", "vegan", "vegetarian"]),
            ("salt", "seasoning", [], ["gluten_free", "vegan", "vegetarian"]),
            ("yogurt_plain_low_fat", "cultured_dairy", ["milk"], ["gluten_free", "vegetarian"]),
            ("cheese_cheshire", "cheese", ["milk"], ["gluten_free", "vegetarian"]),
            ("eggnog", "egg", ["egg", "milk"], ["gluten_free", "vegetarian"]),
            ("salmon_raw", "seafood", ["fish"], ["gluten_free", "pescatarian"]),
            ("fish_oil_salmon", "fat_and_oil", ["fish"], ["gluten_free", "pescatarian"]),
            ("chicken_breast_raw", "poultry", [], ["gluten_free"]),
            ("ny_strip_steak_raw", "red_meat", [], ["gluten_free"]),
            ("lard", "fat_and_oil", [], ["gluten_free"]),  # animal-derived
            ("fat_chicken", "fat_and_oil", [], ["gluten_free"]),
            # Wheat allergen → no gluten_free
            ("wheat_durum", "refined_grain", ["wheat"], ["vegan", "vegetarian"]),
            ("bulgur_dry", "whole_grain", ["wheat"], ["vegan", "vegetarian"]),
            ("couscous_cooked", "refined_grain", ["wheat"], ["vegan", "vegetarian"]),
            # Walnut oil: tree nuts but still vegan + gluten_free
            ("oil_walnut", "fat_and_oil", ["tree_nuts"], ["gluten_free", "vegan", "vegetarian"]),
            (
                "nuts_almonds",
                "plant_protein",
                ["tree_nuts"],
                ["gluten_free", "vegan", "vegetarian"],
            ),
            ("tofu_fried", "plant_protein", ["soy"], ["gluten_free", "vegan", "vegetarian"]),
        ],
    )
    def test_dietary_flags(
        self, node_id: str, parent_id: str, allergens: list[str], expected: list[str]
    ) -> None:
        out = assign_dietary_flags(node_id, parent_id, allergens)
        assert sorted(out) == sorted(expected)


class TestDecay:
    def test_curated_node_overrides_default(self) -> None:
        d = assign_decay("salt", "seasoning", "", [])
        assert d["pantry_days"] == 1825

    def test_parent_default_used_when_no_curated_entry(self) -> None:
        d = assign_decay("blueberries_raw", "fruit", "", [])
        # fruit default has refrigerated_days
        assert "refrigerated_days" in d

    def test_includes_at_least_one_storage_mode(self) -> None:
        d = assign_decay("oil_canola", "fat_and_oil", "", [])
        assert any(v is not None for v in d.values())

    def test_unknown_parent_returns_pantry_default(self) -> None:
        d = assign_decay("mystery_food", "unknown_parent", "", [])
        # Falls back to a generous pantry default so we always satisfy the
        # decay validator's "at least one non-null mode" rule.
        assert any(v is not None for v in d.values())
