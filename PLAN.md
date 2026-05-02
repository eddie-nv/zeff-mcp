# Zeff Food Taxonomy MCP — Implementation Plan

## Project context

Building a curated food taxonomy exposed as an MCP server. Stack: Python 3.11+, FastMCP (or the official MCP Python SDK), Postgres, pytest.

Three core tables (`nodes`, `node_facets`, `node_external_ids`), six MCP tools (`search_foods`, `get_food`, `get_food_components`, `browse_category`, `get_pantry_state`, `get_consumption_history`).

V1 scope is the shared taxonomy layer (4 tools). Personal layer (2 tools) is M5+.

## Working principles

- Test-driven, eval-driven. No code without a failing test. No tool ships without an eval set.
- Commit often. Every passing test or eval improvement = a commit. Small, atomic commits with clear messages.
- No mocked data in prod path. Tests use fixtures, evals use real seeded data. The two never mix.
- Skill files first. Before writing code in any milestone, check `.claude/skills/` for relevant skills and read them. Skills referenced in this plan live there.
- Defer aggressively. If something isn't required for the milestone's exit criteria, don't build it.

## Configured Claude tooling (in `.claude/`)

This repo ships with curated skills, agents, rules, and commands selected for the stack (Python + Postgres + MCP + eval-driven). Use them — don't recreate.

**Skills** (`.claude/skills/`): `python-patterns`, `python-testing`, `postgres-patterns`, `database-migrations`, `mcp-server-patterns`, `eval-harness`, `agent-eval`, `tdd-workflow`, `search-first`, `prompt-optimizer`, `context-budget`, `repo-scan`, `verification-loop`, `deep-research`, `api-design`, `deployment-patterns`, `docker-patterns`, `github-ops`, `hexagonal-architecture`, `backend-patterns`, `coding-standards`.

**Agents** (`.claude/agents/`): `planner`, `architect`, `tdd-guide`, `code-reviewer`, `python-reviewer`, `security-reviewer`, `database-reviewer`, `build-error-resolver`, `refactor-cleaner`, `doc-updater`, `e2e-runner`, `code-explorer`, `comment-analyzer`, `performance-optimizer`, `silent-failure-hunter`, `docs-lookup`, `type-design-analyzer`.

**Rules** (`.claude/rules/`): `common/{coding-style, testing, code-review, development-workflow, git-workflow, security, agents, patterns}.md`, `python/{coding-style, hooks, patterns, security, testing}.md`. These auto-load.

**Commands** (`.claude/commands/`): `/plan`, `/feature-dev`, `/code-review`, `/python-review`, `/test-coverage`, `/build-fix`, `/refactor-clean`, `/update-docs`, `/quality-gate`, `/learn`, `/save-session`, `/resume-session`, `/prp-prd`, `/prp-plan`, `/prp-implement`, `/skill-create`, `/update-codemaps`.

**Routine for every milestone:**

1. Re-read this section's "Skills/Agents/Commands to use" callout.
2. Open the named SKILL.md files before coding.
3. Use named agents proactively (they exist for a reason).
4. Run `/quality-gate` before tagging the milestone complete.

## Repository layout

```
zeff-taxonomy/
├── pyproject.toml
├── README.md
├── .env.example
├── alembic/
│   └── versions/
├── src/
│   └── zeff/
│       ├── __init__.py
│       ├── db/
│       │   ├── connection.py
│       │   ├── models.py
│       │   └── queries.py
│       ├── domain/
│       │   ├── nodes.py
│       │   ├── facets.py
│       │   └── search.py
│       ├── seeds/
│       │   ├── usda_sr.py
│       │   └── canonical.py
│       └── mcp/
│           ├── server.py
│           └── tools/
│               ├── search_foods.py
│               ├── get_food.py
│               ├── get_food_components.py
│               └── browse_category.py
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/
└── evals/
    ├── datasets/
    │   ├── search_queries.jsonl
    │   └── taxonomy_truth.jsonl
    ├── runners/
    │   ├── run_search_eval.py
    │   └── run_taxonomy_eval.py
    └── reports/
```

---

## Milestone 0: Foundation

**Exit criteria:** repo runs locally, CI passes, Postgres schema matches design doc, every test command works.

**Skills to read first:** `python-patterns`, `python-testing`, `postgres-patterns`, `database-migrations`, `docker-patterns`, `coding-standards`, `repo-scan`.
**Agents to use:** `architect` (validate initial layout), `database-reviewer` (review the migration before commit), `build-error-resolver` (when CI fails).
**Commands:** `/plan` to flesh out any sub-task, `/quality-gate` before declaring M0 complete.

### Steps

1. Initialize repo with `pyproject.toml`. Dependencies: `fastapi` (for any health endpoints later), `mcp`, `psycopg[binary]`, `sqlalchemy`, `alembic`, `pydantic`, `pytest`, `pytest-asyncio`, `pytest-postgresql`, `ruff`, `mypy`. Commit.
2. Create `.env.example` with `DATABASE_URL`, `LOG_LEVEL`. Document required env in README. Commit.
3. Set up Postgres locally via Docker Compose. Document the start/stop commands in README. (Use the `docker-patterns` skill.) Commit.
4. Set up Alembic. Generate the initial migration creating three tables: `nodes`, `node_facets`, `node_external_ids` with the schema from the design doc. Add the necessary indexes (`pref_label`, `parent_id`, GIN on `alt_labels`, GIN on facet `facet_value` JSONB). Pass the migration through the `database-reviewer` agent before commit. Commit migration.
5. Write `db/models.py` as SQLAlchemy ORM models matching the migration. Commit.
6. Write `db/connection.py` with async session factory and a context manager. Commit.
7. Write a smoke test: `tests/integration/test_db_connection.py` that opens a session, inserts a node, reads it back, deletes it. Use `pytest-postgresql` for an isolated test database. Confirm it passes. Commit.
8. Add `Makefile` or `justfile` with targets: `make test`, `make lint`, `make typecheck`, `make migrate`, `make seed`, `make eval`. Commit.
9. Set up GitHub Actions (or equivalent CI) to run lint + typecheck + test on every push. (Use `github-ops` skill for action structure.) Confirm green. Commit.

**Stop and verify:** all of the above run cleanly before moving on. Don't proceed if CI is yellow. Run `/quality-gate`.

---

## Milestone 1: Domain layer with TDD

**Exit criteria:** core domain operations (create node, add facet, set parent, find by id) are covered by unit tests with >90% coverage. No MCP code yet.

**Skills to read first:** `tdd-workflow`, `python-patterns`, `python-testing`, `hexagonal-architecture` (domain-first thinking), `backend-patterns`.
**Agents to use:** `tdd-guide` (proactive, drives every step), `python-reviewer` (after each function), `type-design-analyzer` (when defining Pydantic models / enums).
**Commands:** `/feature-dev` for the iteration loop, `/test-coverage` after the milestone to validate the >90% threshold.

### Steps

1. Define Pydantic models for the domain in `domain/nodes.py`: `NodeType` enum (`primitive`, `composite`, `category`), `Node`, `Facet`. Write unit tests for validation rules (id format, label non-empty, parent must exist for non-root). Commit per failing-then-passing test. (Drive via `tdd-guide`.)
2. Write `domain/facets.py` with `FacetKey` enum for the v1 facets (`decay`, `nova_group`, `dietary_flags`, `allergens`, `requires_cooking`). Add validators per facet type:
   - `decay` must be a JSON object with at least one of `refrigerated_days`, `frozen_days`, `pantry_days`, `opened_days`
   - `nova_group` must be int in `[1, 4]`
   - `dietary_flags` must be a list of known strings
   - `allergens` must be a list drawn from FDA Big 9
   - `requires_cooking` must be bool

   Write a unit test for each validator's happy path and at least one failure path. Commit per facet validator.
3. Write repository functions in `db/queries.py`:
   - `create_node(node)`
   - `get_node(node_id)`
   - `set_facet(node_id, key, value)`
   - `get_facets(node_id)`
   - `set_parent(node_id, parent_id)`
   - `add_external_id(node_id, source, external_id)`

   Each function gets an integration test using a real test Postgres. Commit per function. Run `python-reviewer` after every 2-3 functions.
4. Write a small CLI in `seeds/canonical.py` that creates the top-level category nodes from the design (`fruit`, `vegetable`, `grain`, `protein`, `dairy`, `fat_and_oil`, `seasoning`, `beverage`) plus second-level categories (`poultry`, `red_meat`, `seafood`, `egg`, `plant_protein`, `whole_grain`, `refined_grain`, `milk_product`, `cheese`, `cultured_dairy`). Make it idempotent — re-running shouldn't duplicate. Test idempotency. Commit.

**Stop and verify:** run `make seed-canonical` and inspect the DB. The category tree should match the design doc. Run `/test-coverage` and confirm ≥90% on the domain layer.

---

## Milestone 2: Search infrastructure

**Exit criteria:** search returns ranked results from Postgres with both lexical and trigram similarity. Eval dataset exists for search quality. Baseline metrics recorded.

**Skills to read first:** `postgres-patterns` (trigram + GIN), `eval-harness` (eval scaffold structure), `agent-eval` (metric design), `search-first` (don't reinvent), `prompt-optimizer` (later, for query rewriting).
**Agents to use:** `database-reviewer` (review the trigram migration + index choices), `python-reviewer` (search.py), `performance-optimizer` (when iterating search quality / latency).
**Commands:** `/feature-dev` per iteration, `/quality-gate` before exit.

### Steps

1. Add the `pg_trgm` extension to the migration. Add a GIN index on `pref_label` and `alt_labels` using trigram ops. Commit migration.
2. Write `domain/search.py` with `search_foods(query, limit, type_filter)`. Implementation: lexical match on `pref_label` (exact, prefix, trigram similarity) plus a check against `alt_labels`. Return ranked `[{node_id, pref_label, type, parents, score}]`. Commit.
3. Build the search eval scaffold first, before optimizing the function. Use the **`eval-harness`** skill for the structure:
   - Create `evals/datasets/search_queries.jsonl` with 30-50 hand-curated examples: `{"query": "hc apple", "expected_top_k": ["honeycrisp_apple"], "k": 3}`. Cover abbreviations, typos, formal names, partial names, regional names.
   - Write `evals/runners/run_search_eval.py` that loads the dataset, runs each query, computes Recall@k and MRR.
   - Output a JSON report in `evals/reports/search_YYYY-MM-DD.json`.

   Commit the eval scaffold separately from the search implementation.
4. Run the eval against the basic search. Record baseline numbers in the README. Commit a `BASELINE.md` with the numbers.
5. Write unit tests for search edge cases: empty query, query with only special characters, query that matches nothing, type_filter behavior. Commit.
6. Iterate on search quality. Each change is: (a) write a failing test or new eval case that captures the failure mode, (b) implement, (c) re-run eval, (d) commit if metrics improve. Use `performance-optimizer` if latency degrades. Examples of iterations:
   - Boost exact label matches over trigram matches
   - Tokenize query and search per-token
   - Handle plural/singular variants
   - Search across `alt_labels` with same scoring

   Commit after each iteration with the eval delta in the commit message.

**Stop and verify:** Recall@3 ≥ 0.85 on the eval set before proceeding. If you can't hit it, the eval set is probably the problem (too hard or testing the wrong thing) — adjust and document why.

---

## Milestone 3: USDA SR Legacy seeding

**Exit criteria:** ~500 most-common foods seeded as primitive nodes from USDA SR Legacy with external IDs. Search eval re-run with real data showing improved or maintained metrics.

**Skills to read first:** `python-patterns`, `database-migrations` (idempotent seeds), `eval-harness`, `repo-scan` (audit the seeded data quickly).
**Agents to use:** `python-reviewer` (parser code), `database-reviewer` (bulk insert strategy), `silent-failure-hunter` (after the seed run — catches dropped rows / silent skips), `code-explorer` (when reviewing the generated data).
**Commands:** `/feature-dev`, `/quality-gate`.

### Steps

1. Download USDA FoodData Central SR Legacy CSV bulk download. Document the source and version in `seeds/README.md`. Commit the download script (not the data — that goes in `.gitignore` and is fetched on first run).
2. Write `seeds/usda_sr.py` that:
   - Parses the CSV
   - Filters to ~500 most relevant foods (curate by category coverage, common pantry items)
   - For each, creates a node with `id = slugified pref_label`, `type='primitive'`, populates `alt_labels` from USDA's description tokens
   - Links to a parent category (best-effort mapping based on USDA food group)
   - Records `usda_sr` external ID

   Make it idempotent. Test the parser on a small fixture CSV first (commit). Then test the full pipeline on a 10-row subset (commit). Then run the full seed and verify count (commit). Run `silent-failure-hunter` over the import script before the full run.
3. Manually review the seeded data. Open the DB, spot-check 50 random nodes. Look for: bad slug IDs, missing parents, garbage `alt_labels`. Document fixes needed in a `SEED_REVIEW.md`. Commit fixes one at a time.
4. Re-run the search eval against the now-populated DB. Update `BASELINE.md` with new numbers. Commit.
5. Update the search eval dataset with 20 more examples drawn from the actually-seeded data. Re-run, commit.

**Stop and verify:** the 11 example foods from the earlier conversation (honeycrisp apple, fuji apple, spinach, celery, potato, raw chicken breast, raw whole chicken, raw chicken leg, salt, salmon, NY steak) all exist in the DB with correct parents and at least the category and `nova_group` facets. Write a single integration test asserting this. Commit.

---

## Milestone 4: Facet seeding and taxonomy eval

**Exit criteria:** every primitive has at minimum `nova_group`, `decay`, `dietary_flags`, `allergens`, `requires_cooking` facets. Taxonomy correctness eval exists and passes thresholds.

**Skills to read first:** `eval-harness`, `agent-eval`, `verification-loop` (the iterate-against-eval pattern), `deep-research` (sourcing decay/allergen ground truth), `python-testing`.
**Agents to use:** `tdd-guide` (each rule gets a test), `python-reviewer` (rule files), `silent-failure-hunter` (after each seed pass — facets that should exist but don't).
**Commands:** `/feature-dev`, `/quality-gate`. Resist `claude-api`-driven facet population; this milestone is hand-curation by design.

### Steps

1. Build the taxonomy truth dataset:
   - `evals/datasets/taxonomy_truth.jsonl` with 100+ examples: `{"node_id": "salmon_raw", "expected_facets": {"nova_group": 1, "allergens": ["fish"], "requires_cooking": false, ...}, "expected_parent": "seafood"}`
   - Cover all category branches and edge cases (foods that require cooking, foods with allergens, foods that don't need refrigeration)
   - Hand-curated, not LLM-generated. This is your ground truth.

   Commit.
2. Write `evals/runners/run_taxonomy_eval.py` that loads the truth set, queries each node, and reports per-facet accuracy + parent correctness. Commit.
3. Write a facet-seeding pipeline. **Important:** this is where you'll be tempted to use an LLM. Resist for v1 facets.
   - `nova_group`: hand-curate or rule-based (raw produce = 1, oil/salt/sugar = 2, simple processed = 3, ultra-processed brand items = 4). Most primitives are 1-2.
   - `decay`: hand-curate from authoritative sources (USDA FoodKeeper, StillTasty). Build a JSON file in `seeds/decay_data.json` with `{node_id: {refrigerated_days, frozen_days, pantry_days}}`. Commit.
   - `dietary_flags`: rule-based from category + allergen data (vegan = no animal-derived parent, vegetarian = no meat parent, etc).
   - `allergens`: hand-curate against FDA Big 9. Most primitives have zero or one. Commit a `seeds/allergen_data.json`.
   - `requires_cooking`: rule-based by category (raw poultry/pork/eggs = true, raw beef/fish = false, all produce = false except potato/eggplant).

   Each rule or seed file gets unit tests. Commit per facet type.
4. Run the seeding pipeline. Run the taxonomy eval. Commit results.
5. Iterate. Each gap in the eval is either a fix to the seed data or a fix to the rule. Commit per fix with the eval delta in the message. Use the `verification-loop` skill's pattern.

**Stop and verify:** taxonomy eval shows ≥95% accuracy on facets and 100% on parent correctness for the 100+ truth set. Lower thresholds are not acceptable — this is your data quality moat.

---

## Milestone 5: MCP server skeleton with first tool

**Exit criteria:** MCP server runs locally, `search_foods` tool works end-to-end via an MCP client, integration tests pass.

**Skills to read first:** `mcp-server-patterns` (READ FIRST — required), `api-design` (tool schema design), `python-testing`, `docs-lookup` pattern via Context7 for MCP SDK current version.
**Agents to use:** `docs-lookup` (resolve current MCP Python SDK API), `architect` (server module layout), `python-reviewer`, `tdd-guide`, `silent-failure-hunter` (transport-level errors are easy to swallow).
**Commands:** `/feature-dev`, `/quality-gate`.

### Steps

1. Read the official MCP Python SDK docs (use `docs-lookup` agent → Context7). Document the chosen library version in README. Commit.
2. Write `mcp/server.py` with the bare minimum: server initialization, registration hook for tools, stdio transport. No tools registered yet. Confirm it starts. Commit.
3. Write `mcp/tools/search_foods.py` as a single function with a Pydantic input schema and a typed return. Wire it into the server. Commit.
4. Write integration tests that boot the MCP server in-process, call `search_foods` via the SDK's test client, assert the response shape. Commit.
5. Manual smoke test: run the server, connect it to Claude Desktop or `mcp-inspector`, call `search_foods` with 5 different queries, confirm responses look right. Document the smoke test in `MANUAL_TESTS.md`. Commit.
6. Re-run the search eval through the MCP tool layer. Confirm metrics match the direct domain-layer eval. Any divergence means a bug in the tool wrapper. Commit fixes.

**Stop and verify:** `search_foods` works through the MCP transport, integration tests are green, smoke test is documented.

---

## Milestone 6: Remaining shared-layer tools

**Exit criteria:** `get_food`, `get_food_components`, `browse_category` all implemented, tested, eval'd, smoke-tested.

**Skills to read first:** `mcp-server-patterns`, `api-design`, `eval-harness`, `python-testing`.
**Agents to use:** `tdd-guide` (per tool), `python-reviewer` (per tool), `code-reviewer` (cross-tool consistency), `comment-analyzer` (tool descriptions are LLM-facing prompts — they matter).
**Commands:** `/feature-dev` per tool, `/code-review` after the third tool, `/quality-gate` at end.

### Steps

For each of the three tools, repeat this loop (commit after each):

1. Write the input/output Pydantic schemas. Commit.
2. Write the failing integration test for the tool (with a fixture node in the DB). Commit.
3. Implement the tool. Confirm the test passes. Commit.
4. Add 5+ smoke test cases to `MANUAL_TESTS.md`. Commit.
5. Add tool-specific eval cases:
   - `get_food`: assert that calling it on truth-set node IDs returns the expected facets (re-uses `taxonomy_truth.jsonl`)
   - `get_food_components`: defer until M8 (no composites yet)
   - `browse_category`: assert known children appear under known parents
6. Run all evals end-to-end. Commit results.

**Stop and verify:** all four shared-layer tools work, all evals pass, manual smoke tests documented.

---

## Milestone 7: Composites support

**Exit criteria:** the `node_components` table exists, a small set of composite foods is seeded, `get_food_components` returns correct decompositions.

**Skills to read first:** `database-migrations`, `postgres-patterns`, `eval-harness`.
**Agents to use:** `database-reviewer` (foreign key + cascade rules on the new table), `tdd-guide`, `python-reviewer`, `silent-failure-hunter` (composite seed pipeline can drop rows quietly).
**Commands:** `/feature-dev`, `/quality-gate`.

### Steps

1. Write the migration adding `node_components (composite_id, component_id, grams_per_serving, position, is_primary)`. Commit.
2. Update `db/models.py` and `db/queries.py` with component CRUD. Unit tests. Commit.
3. Hand-curate 10 composite foods (frozen cheese pizza, frozen lasagna, canned chicken soup, cheese sandwich, etc.) in `seeds/composites.json`. Each has component references to existing primitive node IDs. Commit.
4. Write the seeding pipeline. Test it on a 2-item subset. Then run full. Commit.
5. Add eval cases to `taxonomy_truth.jsonl` for composites: expected components, expected primary component, expected NOVA group (usually higher than primitives). Commit.
6. Wire up `get_food_components` MCP tool. Add integration tests. Re-run all evals. Commit.

**Stop and verify:** composite eval passes, smoke test confirms LLM can ask "what's in frozen cheese pizza" and get a sensible answer.

---

## Milestone 8: Personal layer foundation

**Exit criteria:** `ingest_records` table exists, sample data can be inserted, `get_pantry_state` computes correctly from records + decay facets.

**Skills to read first:** `database-migrations`, `postgres-patterns`, `eval-harness`, `verification-loop`, `tdd-workflow`.
**Agents to use:** `tdd-guide`, `python-reviewer`, `database-reviewer` (schema choice — partitioning by user_id later?), `silent-failure-hunter` (decay-missing edge cases).
**Commands:** `/feature-dev`, `/quality-gate`.

### Steps

1. Write the migration: `ingest_records (id, user_id, node_id, acquired_at, quantity, source)`. Commit.
2. Write CRUD + repository tests. Commit.
3. Write `domain/pantry.py` with `compute_pantry_state(user_id, as_of)`. Logic: for each ingest record, look up decay facet, compute estimated expiration based on storage mode assumed (default refrigerated), filter to records where `as_of < estimated_expiration`. Unit tests with fixtures covering: not yet expired, just expired, no decay data, multiple records of same food. Commit per case.
4. Build a personal-layer eval dataset: `evals/datasets/pantry_scenarios.jsonl` with hand-crafted scenarios (`{"ingests": [...], "as_of": "...", "expected_pantry": [...]}`). Cover edge cases: expired items excluded, items with no decay data handled gracefully, multiple acquisitions of same food. Commit.
5. Write the eval runner. Run it. Commit baseline.
6. Wire up `get_pantry_state` MCP tool. Integration tests. Smoke tests with a fake `user_id`. Commit.

**Stop and verify:** pantry state computes correctly across all eval scenarios.

---

## Milestone 9: Consumption history tool

**Exit criteria:** `get_consumption_history` returns aggregations over ingest records; supports the documented `group_by` options.

**Skills to read first:** `postgres-patterns` (aggregation query plans), `eval-harness`, `python-testing`.
**Agents to use:** `tdd-guide`, `python-reviewer`, `database-reviewer` (aggregation indexes), `performance-optimizer` (group-by latency at scale).
**Commands:** `/feature-dev`, `/quality-gate`.

### Steps

1. Write `domain/history.py` with `get_consumption_history(user_id, time_range, group_by)`. Support `group_by` values: `category`, `nova_group`, `day`, `none` (raw events).
2. Each `group_by` is its own function with its own unit tests. Commit per `group_by`.
3. Add eval cases: insert known fixture data, assert aggregations match expected counts. Commit.
4. Wire up the MCP tool. Integration tests. Smoke test with realistic queries the LLM would make. Commit.

**Stop and verify:** all six tools are now live, all evals pass, manual smoke tests cover realistic LLM usage patterns.

---

## Milestone 10: End-to-end LLM eval

**Exit criteria:** an LLM (via the MCP server) can answer a curated set of realistic user questions correctly, with documented accuracy.

**Skills to read first:** `agent-eval` (LLM-as-judge patterns), `eval-harness`, `prompt-optimizer` (iterate tool descriptions), `verification-loop`, `mcp-server-patterns`.
**Agents to use:** `e2e-runner` (drive the harness), `comment-analyzer` (tool descriptions and docstrings are the LLM's interface — review them), `python-reviewer`.
**Commands:** `/feature-dev`, `/quality-gate`.

### Steps

1. Build `evals/datasets/end_to_end.jsonl` with 30+ realistic user questions: "what should I eat tonight," "am I eating too much processed food," "what's about to expire," "how much chicken did I have this week." For each, document the expected behavior (which tools should be called, what ballpark answer is correct).
2. Write `evals/runners/run_e2e_eval.py` that:
   - Boots the MCP server
   - Connects an LLM (Claude via API) to it
   - Sends each question, captures the conversation
   - Scores: did the LLM call the right tools? Was the final answer factually correct? (This last one likely requires LLM-as-judge with another model — see `agent-eval`.)
3. Run the eval. Document baseline numbers in `BASELINE.md`. Commit.
4. Iterate on tool descriptions, response formats, and prompt scaffolding to improve E2E accuracy. Use `prompt-optimizer` skill explicitly here. Each iteration: change, re-run eval, commit if metrics improve.

**Stop and verify:** E2E eval shows meaningful task completion (≥80% on the curated questions).

---

## Milestone 11: Documentation and packaging

**Exit criteria:** repo is publishable, has a clean README, MCP server is installable.

**Skills to read first:** `deployment-patterns`, `docker-patterns`, `github-ops`.
**Agents to use:** `doc-updater` (drives README + docs/), `code-reviewer` (final pass), `security-reviewer` (final pass before public release), `refactor-cleaner` (last sweep).
**Commands:** `/update-docs`, `/update-codemaps`, `/code-review`, `/quality-gate`.

### Steps

1. Write `README.md` covering: what it is, who it's for, installation, quickstart, tool reference, how to seed, how to run evals. Commit.
2. Write `docs/TOOLS.md` with full schema reference for all six tools, including example invocations and responses. Commit.
3. Write `docs/EVALS.md` explaining the eval philosophy, how to add cases, how to run. Commit.
4. Add a Dockerfile for the MCP server. Commit.
5. Tag `v0.1.0`. Commit.

---

## Ongoing rules across all milestones

- **Commit cadence.** Each commit message starts with the milestone (e.g. `M2: add trigram index for search`). Aim for 5-15 commits per milestone. If a milestone has fewer than 5, you're probably not committing often enough.
- **Test cadence.** Write the test before the code. If you find yourself writing code without a test, stop and write the test first. The `tdd-guide` agent enforces this.
- **Eval cadence.** When a bug is found, add it to the eval dataset before fixing it. The eval grows with the system.
- **Skill check.** Before starting any milestone, re-read the "Skills to read first" callout for that milestone, then open the named SKILL.md files in `.claude/skills/`. If working with files (CSVs, JSON seed data), check the file-reading skill.
- **Agent invocation.** Use the named agents. They exist for a reason. Don't reinvent their job in-line.
- **Quality gate.** Run `/quality-gate` at the end of every milestone. Don't tag milestone complete with failing tests, evals, or lint.
- **Don't proceed past a stop-and-verify point with failing tests or evals.** Either fix them or revise the threshold with documented justification.
- **Each milestone produces at least one commit on `main`** tagged with the milestone number (e.g. `M3-complete`).
