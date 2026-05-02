# Zeff Food Taxonomy — Design Document

This document captures the design decisions behind the Zeff food taxonomy and MCP server. Read this before starting on the implementation plan. When in doubt during implementation, defer to this document. When this document is silent, default to the simplest reasonable choice.

## What we're building

A curated, machine-readable food taxonomy exposed as an MCP server. The taxonomy unifies entries across authoritative food databases (USDA SR Legacy, FNDDS, Open Food Facts) and adds shelf-life, NOVA classification, dietary, and allergen facets. An LLM agent calls MCP tools against the taxonomy to answer questions about food, nutrition, and a user's pantry.

Two layers:

1. **Shared layer** — the curated taxonomy. Same data for everyone.
2. **Personal layer** — per-user ingest records that drive pantry state and consumption history.

V1 ships both layers but with minimal personal-layer surface (just enough to demo the use cases).

## What we are not building

- Receipt OCR. We assume normalized food strings come in from elsewhere. For demo purposes, ingest records are inserted directly via fixtures.
- Consumption tracking with explicit "I ate this" logging. Operating assumption: the user eats what they buy. Pantry state is computed from ingest records minus expired items.
- Nutrition data tables. Defer to post-v1. Tools that would need nutrition (e.g., `get_nutrition`, `get_nutrient_gaps`) are deferred.
- Recipe instances or substitution graphs. Deferred to post-v1.
- Crowdsourced entries. The taxonomy is curated, not user-generated. This is a deliberate quality decision based on the MyFitnessPal failure mode.

## Core taxonomy concepts

### Three node types

- **`primitive`** — a basic food that exists independently in a pantry with its own shelf life. Examples: honeycrisp apple, raw chicken breast, salt, mozzarella. We do not decompose primitives further. Mozzarella is a primitive even though it derives from milk; the user buys it as a unit and tracks it as a unit.

- **`composite`** — an assembled food made of multiple primitives, treated as a single pantry unit but decomposable for stats. Examples: frozen cheese pizza, frozen lasagna, canned soup. Composites have a `node_components` recipe that breaks them down into primitives with gram weights.

- **`category`** — non-leaf taxonomy nodes used for hierarchy and rollup queries. Examples: `fruit`, `protein`, `cheese`. Categories have no decay or NOVA on themselves but can carry inherited dietary flags.

### The stopping rule for primitives

A primitive is anything with **independent pantry existence and its own shelf life**. This rule resolves the recursion problem. Mozzarella is a primitive (it sits in a pantry, decays on its own). Milk-as-an-input-to-mozzarella is not a primitive (it doesn't independently exist in the user's pantry). Wheat-as-an-input-to-flour is not a primitive. Flour is, if the user buys flour.

### When to decompose composites

Decompose composites when **the components carry stats the user cares about**. A frozen lasagna gets decomposed because the user wants to know "how much cheese am I eating, including in lasagna." A whole chicken does not get decomposed even though it has anatomical parts, because chicken breast and chicken thigh don't carry meaningfully different health stats.

### How we handle "the same food from different stores"

A pizza from Brand A and a pizza from Brand B are different composites with different recipes. Do not unify them as one node. Use a `pizza_cheese` category node so rollup queries work, and let each branded pizza live as its own composite under that category.

For v1, we don't seed branded composites. We seed a small set of generic composites and primitives. Branded ingestion is a post-v1 concern.

## The schema

Three tables for v1.

```sql
CREATE TABLE nodes (
  id              TEXT PRIMARY KEY,
  type            TEXT NOT NULL,
  pref_label      TEXT NOT NULL,
  alt_labels      TEXT[],
  parent_id       TEXT REFERENCES nodes(id),
  status          TEXT DEFAULT 'active',
  created_at      TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE node_facets (
  node_id         TEXT REFERENCES nodes(id),
  facet_key       TEXT NOT NULL,
  facet_value     JSONB NOT NULL,
  PRIMARY KEY (node_id, facet_key)
);

CREATE TABLE node_external_ids (
  node_id         TEXT REFERENCES nodes(id),
  source          TEXT NOT NULL,
  external_id     TEXT NOT NULL,
  PRIMARY KEY (source, external_id)
);
```

Added in M7:

```sql
CREATE TABLE node_components (
  composite_id    TEXT REFERENCES nodes(id),
  component_id    TEXT REFERENCES nodes(id),
  grams_per_serving REAL,
  position        INT,
  is_primary      BOOLEAN DEFAULT false,
  PRIMARY KEY (composite_id, component_id)
);
```

Added in M8:

```sql
CREATE TABLE ingest_records (
  id              UUID PRIMARY KEY,
  user_id         TEXT NOT NULL,
  node_id         TEXT REFERENCES nodes(id),
  acquired_at     TIMESTAMPTZ NOT NULL,
  quantity        REAL,
  source          TEXT
);
```

Indexes:

- `nodes.parent_id` for tree traversal
- `nodes.pref_label` and `nodes.alt_labels` with GIN trigram for search
- `node_facets.facet_value` GIN for facet queries
- `ingest_records (user_id, acquired_at)` for pantry computation

Schema rules:

- IDs are slugified strings, not integers. Human-readable and stable across imports.
- `status` is `active`, `pending_review`, or `deprecated`. New entries from non-curated sources go to `pending_review` and are excluded from search until promoted.
- Categories live in the same `nodes` table as primitives and composites with `type='category'`. This means recursive tree queries work uniformly.

## The category tree

8 top-level categories. Three of them have a single sub-level. Everything else is flat.

```
food
├── fruit
├── vegetable
├── grain
│   ├── whole_grain
│   └── refined_grain
├── protein
│   ├── poultry
│   ├── red_meat
│   ├── seafood
│   ├── egg
│   └── plant_protein
├── dairy
│   ├── milk_product
│   ├── cheese
│   └── cultured_dairy
├── fat_and_oil
├── seasoning
└── beverage
```

Why these subdivisions specifically:
- **Protein** because dietary identity questions (red meat, plant protein) are common
- **Grain** because whole vs refined is one of the most meaningful health distinctions
- **Dairy** because cheese and yogurt have very different shelf lives and stats roles

Why no subdivisions on fruit/vegetable: the user thinks "fruit" and "vegetable." If a query like "leafy greens" becomes important, a facet handles it without restructuring.

## Facets

Five facets for v1. Each is a typed value stored as JSONB.

### `decay`

```json
{
  "refrigerated_days": 7,
  "frozen_days": 240,
  "pantry_days": null,
  "opened_days": 3
}
```

At least one storage mode is non-null. Null means "don't store this way," not zero. Spinach has no `pantry_days`. Salt has no `refrigerated_days`. Composites inherit decay as `min(component decay)` but for v1 we hand-curate composite decay too.

### `nova_group`

Integer 1-4 from the NOVA classification:
- 1 = unprocessed/minimally processed (raw produce, raw meat)
- 2 = culinary ingredients (oil, salt, sugar)
- 3 = processed foods (cheese, cured meats, canned vegetables in brine)
- 4 = ultra-processed (most branded snacks, frozen meals, sodas)

### `dietary_flags`

Array of strings drawn from a known set:
- `vegan`
- `vegetarian`
- `pescatarian`
- `gluten_free`

For v1, only these four. Add `dairy_free`, `nut_free`, `kosher`, `halal` later when there's a query that needs them.

### `allergens`

Array of strings drawn from the FDA Big 9:
- `milk`, `egg`, `fish`, `shellfish`, `tree_nuts`, `peanuts`, `wheat`, `soy`, `sesame`

Most primitives have zero or one allergen. Composites inherit allergens from components.

### `requires_cooking`

Boolean. True for foods that should not be eaten raw (raw chicken, raw potato, raw eggs in most contexts). False for foods that can be eaten raw (apple, salmon for sashimi, lettuce, mozzarella).

## Facets we are NOT including in v1

These were considered and deferred:

- `cultivar`, `animal_part`, `preparation_grade` — too granular, no v1 query needs them
- `is_whole_animal` — covered by category position
- `track_in_pantry` — needed eventually for salt/oil, hardcode the exclusion list for now
- `culinary_ingredient` — redundant with `nova_group=2`
- `omega_3_rich` and similar nutrient flags — defer to nutrition layer
- `category` as a facet — redundant with tree position

## Example nodes (v1 reference data)

These 11 examples drive the integration test in M3. Every one of them must exist in the seeded DB with these specific facets.

### honeycrisp_apple
```
type: primitive
parent: apple (which has parent: fruit)
alt_labels: [honeycrisp, hc apple]
facets:
  decay: {refrigerated_days: 60, pantry_days: 14}
  nova_group: 1
  dietary_flags: [vegan, vegetarian, gluten_free]
  allergens: []
  requires_cooking: false
external_ids:
  usda_sr: 171688
```

### fuji_apple
```
type: primitive
parent: apple
alt_labels: [fuji]
facets:
  decay: {refrigerated_days: 90, pantry_days: 21}
  nova_group: 1
  dietary_flags: [vegan, vegetarian, gluten_free]
  allergens: []
  requires_cooking: false
```

### spinach_raw
```
type: primitive
parent: vegetable
alt_labels: [baby spinach, spinach leaves]
facets:
  decay: {refrigerated_days: 7, frozen_days: 240}
  nova_group: 1
  dietary_flags: [vegan, vegetarian, gluten_free]
  allergens: []
  requires_cooking: false
external_ids:
  usda_sr: 168462
```

### celery_raw
```
type: primitive
parent: vegetable
alt_labels: [celery stalks, celery sticks]
facets:
  decay: {refrigerated_days: 14, frozen_days: 365}
  nova_group: 1
  dietary_flags: [vegan, vegetarian, gluten_free]
  allergens: []
  requires_cooking: false
external_ids:
  usda_sr: 169988
```

### potato_raw
```
type: primitive
parent: vegetable
alt_labels: [potatoes, white potato]
facets:
  decay: {pantry_days: 30, refrigerated_days: 90}
  nova_group: 1
  dietary_flags: [vegan, vegetarian, gluten_free]
  allergens: []
  requires_cooking: true
external_ids:
  usda_sr: 170026
```

### chicken_breast_raw
```
type: primitive
parent: poultry (which has parent: protein)
alt_labels: [boneless skinless chicken breast, chicken breast]
facets:
  decay: {refrigerated_days: 2, frozen_days: 270}
  nova_group: 1
  dietary_flags: [gluten_free]
  allergens: []
  requires_cooking: true
external_ids:
  usda_sr: 171477
```

### chicken_whole_raw
```
type: primitive
parent: poultry
alt_labels: [whole chicken, roaster, fryer]
facets:
  decay: {refrigerated_days: 2, frozen_days: 365}
  nova_group: 1
  dietary_flags: [gluten_free]
  allergens: []
  requires_cooking: true
external_ids:
  usda_sr: 171464
```

### chicken_leg_raw
```
type: primitive
parent: poultry
alt_labels: [chicken legs, chicken drumstick and thigh, leg quarter]
facets:
  decay: {refrigerated_days: 2, frozen_days: 270}
  nova_group: 1
  dietary_flags: [gluten_free]
  allergens: []
  requires_cooking: true
external_ids:
  usda_sr: 171121
```

### salt
```
type: primitive
parent: seasoning
alt_labels: [table salt, sodium chloride, sea salt, kosher salt]
facets:
  decay: {pantry_days: 1825}
  nova_group: 2
  dietary_flags: [vegan, vegetarian, gluten_free]
  allergens: []
  requires_cooking: false
external_ids:
  usda_sr: 173468
```

### salmon_raw
```
type: primitive
parent: seafood (which has parent: protein)
alt_labels: [salmon fillet, fresh salmon]
facets:
  decay: {refrigerated_days: 2, frozen_days: 90}
  nova_group: 1
  dietary_flags: [pescatarian, gluten_free]
  allergens: [fish]
  requires_cooking: false
external_ids:
  usda_sr: 175167
```

### ny_strip_steak_raw
```
type: primitive
parent: red_meat (which has parent: protein)
alt_labels: [ny steak, new york strip, strip steak, ambassador steak, kansas city strip]
facets:
  decay: {refrigerated_days: 4, frozen_days: 365}
  nova_group: 1
  dietary_flags: [gluten_free]
  allergens: []
  requires_cooking: false
external_ids:
  usda_sr: 169433
```

## MCP tool surface (v1)

Six tools. Four shared, two personal.

### Shared layer

**`search_foods(query: str, limit: int = 5, type_filter: str | None = None) -> list[SearchResult]`**

The entry point. Searches `pref_label` and `alt_labels` with combined exact, prefix, and trigram matching. Returns ranked results with enough metadata to disambiguate.

```
SearchResult: { node_id, pref_label, type, parents: list[str], score: float }
```

**`get_food(node_id: str) -> Food`**

Returns the full record minus components.

```
Food: {
  node_id, pref_label, alt_labels, type, parent_id, parents: list[str],
  facets: dict[str, Any], external_ids: dict[str, str]
}
```

**`get_food_components(node_id: str) -> ComponentResult`**

Returns the recipe for composites. Empty for primitives.

```
ComponentResult: {
  is_composite: bool,
  components: list[{ node_id, pref_label, grams_per_serving, is_primary }]
}
```

**`browse_category(category_node_id: str, max_depth: int = 2) -> CategoryView`**

Tree navigation.

```
CategoryView: {
  category: { node_id, pref_label },
  children: list[{ node_id, pref_label, type, child_count }]
}
```

### Personal layer

**`get_pantry_state(user_id: str, as_of: datetime | None = None) -> list[PantryItem]`**

Computes pantry from ingest records minus expired.

```
PantryItem: {
  node_id, pref_label, acquired_at, estimated_expiration,
  days_until_expiration, storage_mode, quantity
}
```

**`get_consumption_history(user_id: str, time_range: str = "30d", group_by: str = "category") -> dict`**

Aggregates ingest records. Supported `group_by`: `category`, `nova_group`, `day`, `none` (raw events).

## Tools we are NOT building in v1

Listed for completeness, deferred:

- `get_nutrition` — deferred until nutrition data is seeded
- `suggest_recipes` — LLM does this itself by combining `get_pantry_state` with its own knowledge
- `get_substitutes` — needs `node_relations` table which is also deferred
- `add_food` / `update_food` — write operations should never be public
- `log_consumption` — defer until explicit consumption UX exists
- `get_nutrient_gaps` — needs nutrition data first
- `compare_foods` — cheap to add later

## Quality bars

These are the non-negotiable thresholds for v1.

### Search

- Recall@3 ≥ 0.85 on the curated search eval set
- The 11 reference foods must be findable by all of: their pref_label, every alt_label, and at least one common abbreviation (e.g., "hc apple" finds honeycrisp_apple)

### Taxonomy correctness

- ≥ 95% facet accuracy on the curated taxonomy truth set
- 100% parent correctness on the truth set

### End-to-end

- ≥ 80% task completion on the curated E2E eval (LLM calling MCP tools to answer realistic user questions)

If any of these aren't hit, do not ship. Either fix the implementation or document why the threshold should be revised (and lower it explicitly with justification, don't just ignore it).

## Anti-patterns to avoid

These are explicitly forbidden in v1:

1. **Crowdsourced entries.** No code path that lets external users add or edit taxonomy nodes without curator review. This is the MyFitnessPal failure mode.

2. **LLM-generated facet data without validation.** Hand-curate or rule-generate the v1 facets. LLMs can suggest, but humans review before write. Eval scaffolding must catch errors before LLM-assisted seeding is allowed.

3. **Auto-promoting `pending_review` nodes to `active`.** Always requires explicit human action.

4. **Building receipt OCR.** Use Claude Vision or a B2B receipt API when ingestion is needed. Don't compete with Fetch.

5. **Mixing test data and seed data.** Tests use ephemeral fixtures. Seeds are reproducible from authoritative sources. They never overlap.

6. **Adding a facet, tool, or table without a corresponding eval case.** Every capability needs a way to verify it's correct.

7. **Skipping the stop-and-verify checkpoints in the implementation plan.** They exist because earlier mistakes compound.

## Glossary

- **Primitive** — a food that independently exists in a pantry with its own shelf life
- **Composite** — an assembled food with a recipe of primitives
- **Category** — a non-leaf taxonomy node for hierarchy and rollup
- **Facet** — a cross-cutting property attached to a node (NOVA, decay, allergens)
- **Polyhierarchy** — a node having multiple parents. Deferred for v1; the schema supports it but we use single-parent for simplicity.
- **NOVA** — Brazilian framework classifying foods by processing level (1-4)
- **FNDDS** — USDA Food and Nutrient Database for Dietary Studies (composite recipes)
- **SR Legacy** — USDA Standard Reference (primitive food nutrients)
- **OFF** — Open Food Facts (crowdsourced branded product database)
- **MCP** — Model Context Protocol (Anthropic's standard for AI agent tool integration)
- **Eval** — a dataset + runner that measures system quality on specific dimensions

## Decisions explicitly deferred

When these come up during implementation, push them to post-v1:

- Polyhierarchy (multiple parents per node)
- Typed relations (`derives_from`, `substitute_for`, etc.)
- Nutrition data
- Recipe instances (user-made foods)
- Branded composite ingestion
- LLM-assisted facet generation
- Receipt OCR
- Authentication and multi-tenancy
- Caching layer
- Public API access (B2B)

The schema and architecture are designed so each of these can be added later without breaking what exists.
