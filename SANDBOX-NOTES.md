# Sandbox Notes

This file documents constraints and workarounds for running Claude Code in a sandboxed environment (e.g., via `ralph-claude.sh`).

## Why `make` targets fail

The sandbox **cannot read `.env`** (blocked by policy). All `make` targets invoke `docker compose`, which reads `.env` for variable interpolation — so they fail with "permission denied". This is expected and by design.

## Preflight: verify containers are running

Before doing any work, check that Docker containers are up:

```bash
docker ps --format "table {{.Names}}\t{{.Status}}" | grep ica
```

You must see `ica-app-1`, `ica-postgres-1`, and `ica-redis-1` all "Up". If containers are NOT running, tell the user: _"Docker containers are not running. Please run `make dev` in a separate terminal, then re-run this session."_ Do NOT attempt `make dev` yourself.

## docker exec commands (use these, not make targets)

`docker exec` talks directly to the running containers and does not read `.env`.

```bash
# Tests
docker exec ica-app-1 python -m pytest tests/                    # Run all tests
docker exec ica-app-1 python -m pytest tests/test_pipeline/      # Run one test directory
docker exec ica-app-1 python -m pytest tests/ -k test_name       # Run tests matching name

# Linting & type checking
docker exec ica-app-1 ruff check .                               # Ruff linter
docker exec ica-app-1 ruff format .                              # Ruff auto-format
docker exec ica-app-1 mypy ica/                                  # mypy (strict mode)

# Run the app
docker exec ica-app-1 python -m ica run                          # Trigger pipeline
docker exec ica-app-1 python -m ica status                       # Pipeline run status
docker exec ica-app-1 python -m ica collect-articles              # Manual article collection

# Database
docker exec ica-app-1 alembic -c alembic.ini upgrade head        # Run migrations
docker exec ica-app-1 alembic -c alembic.ini revision --autogenerate -m "description"  # New migration
docker exec ica-postgres-1 psql -U ica -d n8n_custom_data        # psql shell
```

## What you CANNOT do from the sandbox

- `make dev` / `make down` / `make restart` / `make build` — container lifecycle
- Any command that invokes `docker compose` (reads `.env`)

If containers need starting, stopping, or rebuilding, ask the user.
