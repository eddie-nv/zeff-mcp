# Zeff Food Taxonomy MCP

Curated food taxonomy exposed as an MCP server. See [`DESIGN.md`](DESIGN.md) for the
full design and [`PLAN.md`](PLAN.md) for the milestone-by-milestone implementation plan.

## Status

Pre-v1. Currently building Milestone 0 (Foundation).

## Requirements

- Python 3.11+
- Docker (for local Postgres)

## Quickstart

```bash
# 1. Install
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# 2. Configure
cp .env.example .env

# 3. Start Postgres
docker compose up -d

# 4. Apply migrations
make migrate

# 5. Run tests
make test
```

## Environment

Copy `.env.example` to `.env` and adjust as needed.

| Variable       | Required | Default | Purpose                                                              |
|----------------|----------|---------|----------------------------------------------------------------------|
| `DATABASE_URL` | yes      | —       | Postgres DSN, e.g. `postgresql+psycopg://zeff:zeff@localhost:5432/zeff` |
| `LOG_LEVEL`    | no       | `INFO`  | Standard Python log level                                            |

## Local Postgres (Docker Compose)

```bash
docker compose up -d        # start in background
docker compose ps           # check status
docker compose logs -f db   # follow logs
docker compose down         # stop
docker compose down -v      # stop AND wipe data volume
```

The compose stack runs Postgres 16 with the `pg_trgm` extension pre-installed
(the migration in M2 enables it).

## Make targets

| Target            | Purpose                                |
|-------------------|----------------------------------------|
| `make test`       | Run pytest (unit + integration)        |
| `make lint`       | Ruff lint check                        |
| `make typecheck`  | mypy strict check                      |
| `make migrate`    | Apply Alembic migrations               |
| `make seed`       | Run canonical seed (M1+)               |
| `make eval`       | Run all eval runners (M2+)             |

## Layout

See [`DESIGN.md`](DESIGN.md) for the full repo layout. The `src/zeff/` package
holds the domain, db, seeds, and MCP server modules.

## Claude tooling

This repo ships with a curated `.claude/` toolkit (skills, agents, rules,
commands) selected for the stack. See `PLAN.md`'s "Configured Claude tooling"
section for what's available and when to use it.
