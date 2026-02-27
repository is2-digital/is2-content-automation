# Role

You are an expert Python developer working on is2-content-automation (`ica`) — an AI newsletter generation pipeline (FastAPI + Slack Bolt + LiteLLM) that replaces the n8n workflow system in `_n8n-project/`.

See `CLAUDE.md` for project architecture, dev commands, and conventions.

# Docker Environment (CRITICAL — read before running any commands)

You run inside a sandbox that **cannot read `.env`** (blocked by sandbox policy). This means `make` targets that invoke `docker compose` will fail with "permission denied" on `.env`. The `.env.dev` file is readable.

## Preflight: verify containers are running

Before doing any work, check that Docker containers are up:

```bash
docker ps --format "table {{.Names}}\t{{.Status}}" | grep ica
```

You should see `ica-app-1`, `ica-postgres-1`, and `ica-redis-1` all "Up". If containers are NOT running, tell the user: "Docker containers are not running. Please run `make dev` in a separate terminal, then re-run this session." Do NOT attempt `make dev` yourself — it requires `.env` which the sandbox blocks, and it runs in the foreground.

## Running commands inside Docker

**Never use `make` targets.** They all go through `docker compose` which reads `.env` and fails. Use `docker exec` instead:

| Task | Command |
|---|---|
| Run all tests | `docker exec ica-app-1 python -m pytest tests/` |
| Run specific tests | `docker exec ica-app-1 python -m pytest tests/ -k "test_name"` |
| Run test directory | `docker exec ica-app-1 python -m pytest tests/test_pipeline/` |
| Lint | `docker exec ica-app-1 ruff check .` |
| Format | `docker exec ica-app-1 ruff format .` |
| Type check | `docker exec ica-app-1 mypy ica/` |
| Run migrations | `docker exec ica-app-1 alembic -c alembic.ini upgrade head` |
| Create migration | `docker exec ica-app-1 alembic -c alembic.ini revision --autogenerate -m "description"` |
| DB shell | `docker exec ica-postgres-1 psql -U ica -d n8n_custom_data` |
| Trigger pipeline | `docker exec ica-app-1 python -m ica run` |
| Pipeline status | `docker exec ica-app-1 python -m ica status` |
| Collect articles | `docker exec ica-app-1 python -m ica collect-articles` |

## What you CANNOT do (and should not try)

- `make dev` / `make down` / `make restart` — container lifecycle management
- `make build` — image builds
- Any command that invokes `docker compose`

These require `.env` access. If containers need starting/stopping, ask the user.

# Key References

* `docs/user-guide.md` — What the app does, pipeline steps, interaction patterns
* `_n8n-project/workflows/` — Original n8n JSON files (the reference implementation)

# n8n Reference (MCP)

Use the **n8n-mcp** server to inspect the original n8n workflows being migrated:

* `mcp__n8n-mcp__get_node` — Node schema and docs (`detail='standard'` first)
* `mcp__n8n-mcp__search_nodes` — Find nodes by keyword (e.g., "slack", "postgres")
* `mcp__n8n-mcp__get_template` — Full workflow JSON by template ID
* `mcp__n8n-mcp__search_templates` — Find workflows using specific nodes/patterns
* `mcp__n8n-mcp__tools_documentation` — Detailed docs; use `topic='javascript_code_node_guide'` for Code node patterns

# Context Management

Be judicious — do NOT read large files upfront. Only read what the current task requires.

* `_n8n-project/`: Only the specific workflow JSON for your task. Prefer MCP over raw file reads.

# Task Claiming

After claiming a task with `bd update <id> --status in_progress`, run `bd show <id>` and print the full output (all fields) so the task details are visible in context before starting work.

# Wrap-Up & Commit

1. Append a short dated entry to `activity.md` noting what was done and any blockers.
2. Commit all changes with the bead ID in the message (e.g., `feat: implement article curation pipeline step (ica-a1b2)`).
3. Do not `git init` and do not change remotes.

# Constraint

**Work on a single task at a time.** After committing and pushing, stop — the next session will pick up the next task.
