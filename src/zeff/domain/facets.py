"""Facet domain model: typed values attached to nodes.

Five facets ship in v1: decay, nova_group, dietary_flags, allergens,
requires_cooking. See DESIGN.md "Facets" for the contract.

`validate_facet(key, value)` is the single entry point. It dispatches to a
per-key validator and returns a normalized JSONB-friendly value. Callers
that persist facets must always go through this function so the database
never sees an invalid value.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Any


class FacetKey(StrEnum):
    decay = "decay"
    nova_group = "nova_group"
    dietary_flags = "dietary_flags"
    allergens = "allergens"
    requires_cooking = "requires_cooking"


class InvalidFacetError(ValueError):
    """Raised when a facet value fails its per-key validator."""


# v1 known-value sets. Adding a flag is a follow-on PR + an eval case.
DIETARY_FLAG_VALUES: frozenset[str] = frozenset(
    {"vegan", "vegetarian", "pescatarian", "gluten_free"}
)

# FDA Big 9 allergens.
ALLERGEN_VALUES: frozenset[str] = frozenset(
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

DECAY_MODES: frozenset[str] = frozenset(
    {"refrigerated_days", "frozen_days", "pantry_days", "opened_days"}
)


def _validate_decay(value: Any) -> dict[str, int | None]:
    if not isinstance(value, Mapping):
        raise InvalidFacetError(f"decay must be an object, got {type(value).__name__}")

    unknown = set(value.keys()) - DECAY_MODES
    if unknown:
        raise InvalidFacetError(
            f"decay has unknown storage modes: {sorted(unknown)}; allowed: {sorted(DECAY_MODES)}"
        )

    out: dict[str, int | None] = {}
    has_non_null = False
    for key, raw in value.items():
        if raw is None:
            out[key] = None
            continue
        # Reject bool explicitly; bool is a subclass of int.
        if isinstance(raw, bool) or not isinstance(raw, int):
            raise InvalidFacetError(f"decay.{key} must be int or null, got {raw!r}")
        if raw < 0:
            raise InvalidFacetError(f"decay.{key} must be >= 0, got {raw}")
        out[key] = raw
        has_non_null = True

    if not has_non_null:
        raise InvalidFacetError(
            f"decay must have at least one non-null storage mode ({sorted(DECAY_MODES)})"
        )
    return out


def _validate_nova_group(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise InvalidFacetError(f"nova_group must be int 1-4, got {value!r}")
    narrowed: int = value
    if narrowed < 1 or narrowed > 4:
        raise InvalidFacetError(f"nova_group must be 1, 2, 3, or 4, got {narrowed}")
    return narrowed


def _validate_string_set(value: Any, allowed: frozenset[str], facet_name: str) -> list[str]:
    if not isinstance(value, list):
        raise InvalidFacetError(f"{facet_name} must be a list, got {type(value).__name__}")
    seen: set[str] = set()
    out: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise InvalidFacetError(f"{facet_name} entries must be strings, got {item!r}")
        if item not in allowed:
            raise InvalidFacetError(
                f"{facet_name} entry {item!r} not in allowed set {sorted(allowed)}"
            )
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _validate_dietary_flags(value: Any) -> list[str]:
    return _validate_string_set(value, DIETARY_FLAG_VALUES, "dietary_flags")


def _validate_allergens(value: Any) -> list[str]:
    return _validate_string_set(value, ALLERGEN_VALUES, "allergens")


def _validate_requires_cooking(value: Any) -> bool:
    if not isinstance(value, bool):
        raise InvalidFacetError(f"requires_cooking must be bool, got {value!r}")
    return value


_VALIDATORS: dict[FacetKey, Any] = {
    FacetKey.decay: _validate_decay,
    FacetKey.nova_group: _validate_nova_group,
    FacetKey.dietary_flags: _validate_dietary_flags,
    FacetKey.allergens: _validate_allergens,
    FacetKey.requires_cooking: _validate_requires_cooking,
}


def validate_facet(key: FacetKey, value: Any) -> Any:
    """Validate and normalize a facet value for the given key.

    Raises InvalidFacetError on any validation failure.
    """
    if not isinstance(key, FacetKey):
        try:
            key = FacetKey(key)
        except ValueError as exc:
            raise InvalidFacetError(
                f"unknown facet key {key!r}; allowed: {[k.value for k in FacetKey]}"
            ) from exc
    return _VALIDATORS[key](value)
