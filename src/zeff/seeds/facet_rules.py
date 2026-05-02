"""Pure functions that derive each v1 facet from a node's id, parent, label,
and alt_labels. No DB access. Used by `seeds.facets`.

Strategy is rule-based with hand-curated overrides where the rule is wrong
or unknowable from text alone. Each rule has its own unit tests.

DESIGN.md says: "Hand-curate or rule-based ... LLMs can suggest, but
humans review before write." These rules ARE the human review encoded.
"""

from __future__ import annotations

from typing import Any

# ---- nova_group ----------------------------------------------------------

NOVA_2_PARENTS: frozenset[str] = frozenset({"fat_and_oil", "seasoning"})
NOVA_3_PARENTS: frozenset[str] = frozenset({"cheese", "cultured_dairy"})
NOVA_3_TOKENS: frozenset[str] = frozenset(
    {
        "cured",
        "smoked",
        "canned",
        "candied",
        "frozen",
        "imitation",
        "instant",
        "luncheon",
        "processed",
        "fried",
        "noodles",
        "couscous",
        "tapioca",
        "cornstarch",
        "eggnog",
    }
)


NOVA_2_TOKENS: frozenset[str] = frozenset({"flour"})


def assign_nova_group(node_id: str, parent_id: str, pref_label: str, alt_labels: list[str]) -> int:
    """Return NOVA group 1-4 by parent + content tokens."""
    if parent_id in NOVA_2_PARENTS:
        return 2
    if parent_id in NOVA_3_PARENTS:
        return 3

    haystack = " ".join([node_id, pref_label, *alt_labels]).lower()
    if any(tok in haystack for tok in NOVA_3_TOKENS):
        return 3
    if any(tok in haystack for tok in NOVA_2_TOKENS):
        return 2

    # Defaults: raw produce + raw meat = 1; "cooked" prepared meat = 1 too
    # since "cooked" alone isn't a NOVA-3 marker.
    return 1


# ---- requires_cooking ----------------------------------------------------

# Parents whose raw form is unsafe to eat without cooking.
COOK_PARENTS: frozenset[str] = frozenset({"poultry"})
# Specific node ids that override the parent-default.
NEEDS_COOKING_NODE_IDS: frozenset[str] = frozenset(
    {
        "potato_raw",
        "mollusks_snail_raw",
        "frog_legs_raw",
    }
)
# Tokens in the id/label that imply needs cooking even if parent doesn't.
NEEDS_COOKING_TOKENS: frozenset[str] = frozenset(
    {
        "raw",  # for grains, legumes, certain veg
        "uncooked",
        "dry",  # dry pasta, dry beans
        "dried",  # only when not "dried fruit"; we narrow below
    }
)
# Fruits/vegetables/etc. where "raw" doesn't imply cooking is required.
NO_COOK_PARENTS_RAW_OK: frozenset[str] = frozenset(
    {
        "fruit",
        "vegetable",
        "milk_product",
        "cultured_dairy",
        "cheese",
        "fat_and_oil",
        "seasoning",
        "beverage",
        "egg",  # eggnog and other prepared-egg products in our seed
        "seafood",  # raw seafood is consumable; overrides exist for snail/frog
    }
)


def assign_requires_cooking(
    node_id: str, parent_id: str, pref_label: str, alt_labels: list[str]
) -> bool:
    """Return whether the node should not be eaten in its current form."""
    haystack = " ".join([node_id, pref_label, *alt_labels]).lower()

    # Use word-boundary-ish matches; "uncooked" contains "cooked" but should not
    # short-circuit to False.
    haystack_tokens = set(haystack.replace("_", " ").replace("-", " ").split())
    if "uncooked" not in haystack_tokens and (
        "cooked" in haystack_tokens or "boiled" in haystack_tokens or "roasted" in haystack_tokens
    ):
        return False
    if node_id in NEEDS_COOKING_NODE_IDS:
        return True
    if parent_id in COOK_PARENTS:
        return True
    # Red meat: default = needs cooking, except for steak / carpaccio cuts.
    # "Steak tartare" is the exception, not the rule (veal organs, ground beef,
    # game meat, etc. all need cooking).
    if parent_id == "red_meat":
        return not ("steak" in haystack or "carpaccio" in haystack)
    # Plant protein nuts/legumes: most nuts can be eaten raw.
    if parent_id == "plant_protein":
        if any(
            tok in haystack
            for tok in (
                "nut",
                "nuts",
                "peanut",
                "peanuts",
                "almond",
                "cashew",
                "pistachio",
                "walnut",
                "hazelnut",
                "pecan",
            )
        ):
            return False
        # Beans/lentils/soybeans/tofu raw or dry need cooking
        return any(tok in haystack for tok in ("raw", "uncooked", "dry"))
    # Grains: default = needs cooking unless explicitly cooked or it's a flour/bran/starch.
    if parent_id in {"grain", "whole_grain", "refined_grain"}:
        # Flours and bran are ingredients used in cooking, not eaten as-is;
        # they don't "require cooking" in the unsafe sense.
        return not any(tok in haystack for tok in ("flour", "bran", "starch"))
    if parent_id in NO_COOK_PARENTS_RAW_OK:
        return False
    return any(tok in haystack for tok in ("raw", "uncooked", "dry"))


# ---- allergens -----------------------------------------------------------

# parent → default allergen list (overridden by per-node tokens below).
ALLERGENS_BY_PARENT_DEFAULT: dict[str, list[str]] = {
    "milk_product": ["milk"],
    "cheese": ["milk"],
    "cultured_dairy": ["milk"],
    "egg": ["egg"],
}

ALLERGEN_TOKEN_MAP: list[tuple[frozenset[str], str]] = [
    # Fish: covers fish-oil and other fish-derived products outside parent=seafood.
    (
        frozenset(
            {
                "fish",
                "salmon",
                "tuna",
                "anchovy",
                "anchovies",
                "sardine",
                "sardines",
                "herring",
                "mackerel",
                "menhaden",
                "cod",
                "halibut",
            }
        ),
        "fish",
    ),
    (frozenset({"peanut", "peanuts"}), "peanuts"),
    (
        frozenset(
            {
                "almond",
                "almonds",
                "cashew",
                "cashews",
                "walnut",
                "walnuts",
                "pecan",
                "pecans",
                "hazelnut",
                "hazelnuts",
                "pistachio",
                "pistachios",
                "macadamia",
                "brazil",  # Brazil nut
                "pine",  # pine nut
            }
        ),
        "tree_nuts",
    ),
    (frozenset({"soy", "soybean", "soybeans", "tofu", "edamame"}), "soy"),
    (
        frozenset(
            {
                "wheat",
                "bulgur",
                "couscous",
                "spelt",
                "triticale",
                "semolina",
                "farro",
            }
        ),
        "wheat",
    ),
    (frozenset({"sesame"}), "sesame"),
    (
        frozenset(
            {
                "shrimp",
                "crab",
                "lobster",
                "mussel",
                "mussels",
                "oyster",
                "oysters",
                "scallop",
                "scallops",
                "clam",
                "clams",
                "snail",
                "snails",
                "mollusk",
                "mollusks",
                "octopus",
                "squid",
            }
        ),
        "shellfish",
    ),
]

# Seafood that isn't fish (frog, alligator) — block default fish allergen.
SEAFOOD_NOT_FISH_TOKENS: frozenset[str] = frozenset({"frog", "alligator", "turtle"})

# Per-node allergen overrides where the token rule misses something.
ALLERGEN_OVERRIDES_BY_NODE: dict[str, list[str]] = {
    # Eggnog has both egg (parent default) and milk (not in tokens).
    "eggnog": ["egg", "milk"],
}


def assign_allergens(
    node_id: str, parent_id: str, pref_label: str, alt_labels: list[str]
) -> list[str]:
    if node_id in ALLERGEN_OVERRIDES_BY_NODE:
        return sorted(ALLERGEN_OVERRIDES_BY_NODE[node_id])

    haystack_tokens = set(
        " ".join([node_id, pref_label, *alt_labels])
        .lower()
        .replace("-", " ")
        .replace("_", " ")
        .split()
    )

    out: set[str] = set(ALLERGENS_BY_PARENT_DEFAULT.get(parent_id, []))

    # Seafood default: fish, unless tokens say otherwise.
    if parent_id == "seafood":
        non_fish = haystack_tokens & SEAFOOD_NOT_FISH_TOKENS
        if not non_fish:
            out.add("fish")

    for tokens, allergen in ALLERGEN_TOKEN_MAP:
        if haystack_tokens & tokens:
            out.add(allergen)

    # Suppress default fish for seafood with shellfish allergen present.
    if parent_id == "seafood" and "shellfish" in out:
        out.discard("fish")

    return sorted(out)


# ---- dietary_flags -------------------------------------------------------

PLANT_PARENTS: frozenset[str] = frozenset(
    {
        "fruit",
        "vegetable",
        "grain",
        "whole_grain",
        "refined_grain",
        "plant_protein",
        "seasoning",
        "beverage",
    }
)
DAIRY_PARENTS: frozenset[str] = frozenset(
    {"dairy", "milk_product", "cheese", "cultured_dairy", "egg"}
)
MEAT_PARENTS: frozenset[str] = frozenset({"poultry", "red_meat"})
SEAFOOD_PARENTS: frozenset[str] = frozenset({"seafood"})

# Parent values for fat_and_oil are decided per-node since they may be
# plant- (oil_canola), dairy- (butter), or animal-derived (lard, fat_chicken).
ANIMAL_FAT_TOKENS: frozenset[str] = frozenset(
    {"lard", "tallow", "bacon", "chicken", "goose", "turkey", "duck", "fish"}
)


def assign_dietary_flags(
    node_id: str, parent_id: str, allergens: list[str], *, ancestors: list[str] | None = None
) -> list[str]:
    flags: set[str] = set()

    # If parent_id isn't a known dietary bucket, walk up ancestors to find one.
    # (e.g., honeycrisp_apple -> apple -> fruit; "apple" itself isn't in any set.)
    chain = [parent_id, *(ancestors or [])]
    diet_parent = next(
        (
            p
            for p in chain
            if p
            in (PLANT_PARENTS | DAIRY_PARENTS | MEAT_PARENTS | SEAFOOD_PARENTS | {"fat_and_oil"})
        ),
        parent_id,
    )

    # Diet category
    if diet_parent in PLANT_PARENTS:
        if "milk" in allergens or "egg" in allergens:
            flags.add("vegetarian")
        else:
            flags.add("vegan")
            flags.add("vegetarian")
    elif diet_parent in DAIRY_PARENTS:
        flags.add("vegetarian")
    elif diet_parent in SEAFOOD_PARENTS:
        # Seafood that's actually frog/alligator/turtle gets no pescatarian flag.
        haystack_tokens = node_id.lower().split("_")
        if not (set(haystack_tokens) & SEAFOOD_NOT_FISH_TOKENS):
            flags.add("pescatarian")
    elif diet_parent == "fat_and_oil":
        haystack = node_id.lower()
        if "fish" in allergens:
            flags.add("pescatarian")
        elif any(tok in haystack for tok in ANIMAL_FAT_TOKENS):
            # animal-derived (lard, chicken fat, ...): no diet flag
            pass
        else:
            flags.add("vegan")
            flags.add("vegetarian")
    # MEAT_PARENTS get no diet flag (omnivore-only)

    # Gluten-free unless wheat/barley/rye allergen present
    # (barley contains gluten too — no FDA Big 9 entry for it.)
    if "wheat" not in allergens and not any(tok in node_id.lower() for tok in ("barley", "rye")):
        flags.add("gluten_free")

    return sorted(flags)


# ---- decay ---------------------------------------------------------------

# Hand-curated per-node decay (sourced from USDA FoodKeeper / StillTasty).
DECAY_BY_NODE: dict[str, dict[str, Any]] = {
    "salt": {"pantry_days": 1825},
    "honeycrisp_apple": {"refrigerated_days": 60, "pantry_days": 14},
    "fuji_apple": {"refrigerated_days": 90, "pantry_days": 21},
    "spinach_raw": {"refrigerated_days": 7, "frozen_days": 240},
    "celery_raw": {"refrigerated_days": 14, "frozen_days": 365},
    "potato_raw": {"pantry_days": 30, "refrigerated_days": 90},
    "chicken_breast_raw": {"refrigerated_days": 2, "frozen_days": 270},
    "chicken_whole_raw": {"refrigerated_days": 2, "frozen_days": 365},
    "chicken_leg_raw": {"refrigerated_days": 2, "frozen_days": 270},
    "salmon_raw": {"refrigerated_days": 2, "frozen_days": 90},
    "ny_strip_steak_raw": {"refrigerated_days": 4, "frozen_days": 365},
}

# Per-parent fallback when no per-node entry exists.
DECAY_BY_PARENT: dict[str, dict[str, Any]] = {
    "fruit": {"refrigerated_days": 14, "pantry_days": 5},
    "vegetable": {"refrigerated_days": 7, "frozen_days": 240},
    "cheese": {"refrigerated_days": 30, "frozen_days": 180, "opened_days": 14},
    "milk_product": {"refrigerated_days": 7, "opened_days": 5},
    "cultured_dairy": {"refrigerated_days": 14, "opened_days": 7},
    "egg": {"refrigerated_days": 21},
    "poultry": {"refrigerated_days": 2, "frozen_days": 270},
    "red_meat": {"refrigerated_days": 4, "frozen_days": 365},
    "seafood": {"refrigerated_days": 2, "frozen_days": 90},
    "fat_and_oil": {"pantry_days": 730, "opened_days": 180},
    "seasoning": {"pantry_days": 1095},
    "beverage": {"refrigerated_days": 14, "opened_days": 7, "pantry_days": 365},
    "plant_protein": {"pantry_days": 365, "refrigerated_days": 14},
    "whole_grain": {"pantry_days": 365},
    "refined_grain": {"pantry_days": 730},
    "grain": {"pantry_days": 365},
}

DECAY_DEFAULT: dict[str, Any] = {"pantry_days": 365}


def assign_decay(
    node_id: str, parent_id: str, pref_label: str, alt_labels: list[str]
) -> dict[str, Any]:
    if node_id in DECAY_BY_NODE:
        return dict(DECAY_BY_NODE[node_id])
    if parent_id in DECAY_BY_PARENT:
        return dict(DECAY_BY_PARENT[parent_id])
    return dict(DECAY_DEFAULT)
