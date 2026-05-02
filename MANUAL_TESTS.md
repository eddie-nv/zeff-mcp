# Manual smoke tests

Quick stdio-transport sanity tests for the MCP server. These run against
the local docker-compose Postgres seeded via:

```bash
make db-up && make migrate && make seed
```

Then start the server (any MCP client works — examples below).

## Inspector (one-shot)

```bash
DATABASE_URL=postgresql+psycopg://zeff:zeff@localhost:5432/zeff \
  npx @modelcontextprotocol/inspector .venv/bin/python -m zeff.mcp.server
```

The Inspector UI lets you browse the tool list and invoke `search_foods`
interactively.

## Claude Desktop / Cursor

Add to the client's MCP config:

```json
{
  "mcpServers": {
    "zeff": {
      "command": "/abs/path/to/zeff-mcp/.venv/bin/python",
      "args": ["-m", "zeff.mcp.server"],
      "env": { "DATABASE_URL": "postgresql+psycopg://zeff:zeff@localhost:5432/zeff" }
    }
  }
}
```

## M5 — `search_foods` smoke checks (2026-05-02)

Run the script in `scripts/mcp_smoke.py` (or run the snippet inline). All
five queries below were verified against the M3+M4 seeded DB.

| Query                  | Top-3 expected to include  | Notes                                  |
|------------------------|----------------------------|----------------------------------------|
| `honeycrisp apple`     | `honeycrisp_apple`         | Exact label match, rank 1              |
| `fish salmon`          | `fish_salmon_*_raw`        | Compound query → all top-3 are salmon  |
| `celery`               | `celery_raw`               | Exact + adjacent fuzzy (celeriac, etc) |
| `no_match_query_xyz`   | `[]`                       | Empty result, no error                 |
| `salt`                 | `salt`                     | Exact match outranks `salt_table`      |

Last run: 2026-05-02. All 5 passed.

## Failure modes to watch

- **DB unavailable:** the server will start but every `search_foods` call
  will surface a connection error. Symptom: tool returns an MCP error
  with `psycopg.OperationalError`. Fix: `make db-up` and re-seed.
- **Schema drift after migration:** if `alt_labels_text` is missing the
  trigram index attaches to nothing → empty results for fuzzy queries.
  Fix: re-run `make migrate`.
- **Empty DB:** `search_foods` returns `[]` for every query. Fix:
  `make seed`.
