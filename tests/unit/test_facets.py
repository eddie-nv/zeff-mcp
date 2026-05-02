"""Unit tests for the Facet domain model and per-facet validators.

Each v1 facet gets a happy path and at least one failure path. The validator
function `validate_facet(key, value)` is the public surface; it dispatches to
the per-key validator and returns a normalized JSONB-friendly value.
"""

from __future__ import annotations

import pytest

from zeff.domain.facets import (
    ALLERGEN_VALUES,
    DIETARY_FLAG_VALUES,
    FacetKey,
    InvalidFacetError,
    validate_facet,
)


class TestFacetKey:
    def test_v1_keys(self) -> None:
        assert {k.value for k in FacetKey} == {
            "decay",
            "nova_group",
            "dietary_flags",
            "allergens",
            "requires_cooking",
        }


class TestDecay:
    def test_refrigerated_only_ok(self) -> None:
        out = validate_facet(FacetKey.decay, {"refrigerated_days": 7})
        assert out == {"refrigerated_days": 7}

    def test_all_modes_ok(self) -> None:
        v = {
            "refrigerated_days": 7,
            "frozen_days": 240,
            "pantry_days": None,
            "opened_days": 3,
        }
        assert validate_facet(FacetKey.decay, v) == v

    def test_must_have_at_least_one_mode(self) -> None:
        with pytest.raises(InvalidFacetError):
            validate_facet(FacetKey.decay, {})

    def test_all_null_modes_rejected(self) -> None:
        with pytest.raises(InvalidFacetError):
            validate_facet(
                FacetKey.decay,
                {
                    "refrigerated_days": None,
                    "frozen_days": None,
                    "pantry_days": None,
                    "opened_days": None,
                },
            )

    def test_negative_days_rejected(self) -> None:
        with pytest.raises(InvalidFacetError):
            validate_facet(FacetKey.decay, {"refrigerated_days": -1})

    def test_unknown_storage_mode_rejected(self) -> None:
        with pytest.raises(InvalidFacetError):
            validate_facet(FacetKey.decay, {"refrigerated_days": 7, "fridge": 10})

    def test_non_dict_rejected(self) -> None:
        with pytest.raises(InvalidFacetError):
            validate_facet(FacetKey.decay, [7])


class TestNovaGroup:
    @pytest.mark.parametrize("value", [1, 2, 3, 4])
    def test_valid_values(self, value: int) -> None:
        assert validate_facet(FacetKey.nova_group, value) == value

    @pytest.mark.parametrize("value", [0, 5, -1])
    def test_out_of_range_rejected(self, value: int) -> None:
        with pytest.raises(InvalidFacetError):
            validate_facet(FacetKey.nova_group, value)

    def test_non_int_rejected(self) -> None:
        with pytest.raises(InvalidFacetError):
            validate_facet(FacetKey.nova_group, "1")

    def test_bool_rejected(self) -> None:
        # bool is a subclass of int; explicitly reject
        with pytest.raises(InvalidFacetError):
            validate_facet(FacetKey.nova_group, True)


class TestDietaryFlags:
    def test_known_flags_ok(self) -> None:
        out = validate_facet(FacetKey.dietary_flags, ["vegan", "vegetarian"])
        assert out == ["vegan", "vegetarian"]

    def test_empty_list_ok(self) -> None:
        assert validate_facet(FacetKey.dietary_flags, []) == []

    def test_v1_value_set(self) -> None:
        assert (
            frozenset({"vegan", "vegetarian", "pescatarian", "gluten_free"}) == DIETARY_FLAG_VALUES
        )

    def test_unknown_flag_rejected(self) -> None:
        with pytest.raises(InvalidFacetError):
            validate_facet(FacetKey.dietary_flags, ["vegan", "kosher"])

    def test_duplicates_deduped(self) -> None:
        out = validate_facet(FacetKey.dietary_flags, ["vegan", "vegan"])
        assert out == ["vegan"]

    def test_non_list_rejected(self) -> None:
        with pytest.raises(InvalidFacetError):
            validate_facet(FacetKey.dietary_flags, "vegan")


class TestAllergens:
    def test_fda_big_9(self) -> None:
        assert (
            frozenset(
                {
                    "milk",
                    "egg",
                    "fish",
                    "shellfish",
                    "tree_nuts",
                    "peanuts",
                    "wheat",
                    "soy",
                    "sesame",
                }
            )
            == ALLERGEN_VALUES
        )

    def test_known_allergens_ok(self) -> None:
        out = validate_facet(FacetKey.allergens, ["fish", "shellfish"])
        assert out == ["fish", "shellfish"]

    def test_empty_ok(self) -> None:
        assert validate_facet(FacetKey.allergens, []) == []

    def test_unknown_allergen_rejected(self) -> None:
        with pytest.raises(InvalidFacetError):
            validate_facet(FacetKey.allergens, ["gluten"])

    def test_duplicates_deduped(self) -> None:
        out = validate_facet(FacetKey.allergens, ["fish", "fish"])
        assert out == ["fish"]


class TestRequiresCooking:
    @pytest.mark.parametrize("value", [True, False])
    def test_bool_ok(self, value: bool) -> None:
        assert validate_facet(FacetKey.requires_cooking, value) is value

    @pytest.mark.parametrize("value", [0, 1, "true", "false", None])
    def test_non_bool_rejected(self, value: object) -> None:
        with pytest.raises(InvalidFacetError):
            validate_facet(FacetKey.requires_cooking, value)


class TestUnknownFacetKey:
    def test_string_key_not_in_enum_rejected(self) -> None:
        with pytest.raises(InvalidFacetError):
            validate_facet("nova-group", 1)  # type: ignore[arg-type]
