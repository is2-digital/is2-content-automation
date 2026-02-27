# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Python rewrite of an n8n-based AI newsletter generation system (IS2-News → is2-content-automation / `ica`). The original n8n system lives in `_n8n-project/` as reference. The target newsletter is published at is2digital.com/newsletters for solopreneurs and SMB professionals interested in AI.

## Development Commands

All commands run inside Docker containers. Nothing is installed locally — never run Python, pytest, ruff, mypy, or any project tooling directly on the host machine.

**IMPORTANT: Read `SANDBOX-NOTES.md` before running any commands.** It contains sandbox constraints and the correct command patterns for running tests, linting, and other tooling from within the sandbox.

**Git commands must be single-line with no `$()`, `|`, `<`, `>`, heredocs, or other shell substitutions/redirections.** Multi-`-m` flags are fine for multi-paragraph commit messages. This ensures git operations can run without manual approval.

For human use outside the sandbox, run `make help` for the full list of make targets.

## Issue Tracking

This project uses **Beads** (`bd`) for issue tracking. Run `bd onboard` to get started.

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --status in_progress  # Claim work
bd close <id>         # Complete work
bd sync               # Sync with git
```

## Session Completion (Mandatory)

Work is NOT complete until `git push` succeeds. The critical steps:

```bash
git pull --rebase && bd sync && git push
git status  # Must show "up to date with origin"
```

## Architecture

### Package Structure

- `ica/config/` — Pydantic Settings (`settings.py`) + LLM model mapping (`llm_config.py`) + startup validation (`validation.py`). All config from env vars / `.env`.
- `ica/pipeline/` — Pipeline step implementations + orchestrator. Each step is a standalone module (e.g., `summarization.py`, `theme_generation.py`).
- `ica/pipeline/steps.py` — Adapter layer that wires step modules to `PipelineStep` protocol with service instantiation via lazy factory helpers (`_make_slack()`, `_make_docs()`, etc.) using deferred imports to avoid circular deps.
- `ica/pipeline/orchestrator.py` — Runs sequential then parallel steps, manages `PipelineContext` dataclass that accumulates state across the pipeline.
- `ica/services/` — External service clients: `llm.py` (LiteLLM wrapper), `slack.py` (Slack Bolt), `google_sheets.py`, `google_docs.py`, `google_search.py` (Google Custom Search), `web_fetcher.py` (httpx).
- `ica/llm_configs/` — 19 JSON process config files (`{process}-llm.json`) with model, system/instruction prompts, and metadata. Loaded via `loader.py` with file-mtime-invalidated cache. Schema in `schema.py` (`ProcessConfig` Pydantic model).
- `ica/prompts/` — LLM prompt builder functions. System/instruction text loaded from JSON via `ica.llm_configs.get_process_prompts()`. Python functions handle dynamic runtime interpolation (injecting feedback, validator errors, article content). One file per pipeline step.
- `ica/validators/` — Content validation (`character_count.py` for markdown section character counts).
- `ica/utils/` — `marker_parser.py` (`%XX_` marker parsing), `output_router.py`, `boolean_normalizer.py`, `date_parser.py`.
- `ica/db/` — SQLAlchemy 2.0 async models (`models.py`), CRUD functions (`crud.py`), session factory (`session.py`), Alembic migrations.
- `ica/app.py` — FastAPI application factory with `/trigger`, `/status`, `/health`, `/scheduler` endpoints.
- `ica/errors.py` — Exception hierarchy (`PipelineError` → `LLMError`, `FetchError`, `DatabaseError`, `ValidationError`, `PipelineStopError`) + Slack error notification + `ValidationLoopCounter`.
- `ica/logging.py` — Structured logging with async-safe context vars (`run_id`, `step`), JSON/text formatters, `bind_context` context manager.

### Pipeline Flow

```
Trigger → [1] Article Curation (Slack approval + Google Sheets)
        → [2] Summarization (per-article HTTP fetch + LLM + feedback loop)
        → [3] Theme Generation (LLM generates 2 themes, human selects, freshness check)
        → [4] Markdown Generation (LLM + 3-layer validation + retry loop)
        → [5] HTML Generation (markdown-to-HTML + LLM styling + Google Doc)
        → [6a-6d] Parallel: Alternates HTML, Email Subject, Social Media, LinkedIn Carousel
```

A **separate scheduled job** runs independently for article collection:
- Daily: Google CSE sorted by date, 3 keywords (10 results each)
- Every 2 days: Google CSE relevance ranking, 5 keywords (10 results each)

### Key Patterns

- **`PipelineContext`** dataclass flows through all steps, accumulating state (articles, summaries, theme, markdown/html doc IDs, step results, extras). Sequential steps mutate and return it; parallel steps share the same snapshot.
- **`PipelineStep` protocol**: `async def __call__(self, ctx: PipelineContext) -> PipelineContext`. Steps in `steps.py` adapt each pipeline module to this protocol.
- **LLM calls**: All go through `ica.services.llm.completion()` which takes a `LLMPurpose` enum (21 variants), handles model routing, retry with exponential backoff, and error mapping to `LLMError`.
- **LLM model config**: 3-tier resolution in `get_model()` (`ica/config/llm_config.py`): (1) env var override (e.g., `LLM_SUMMARY_MODEL`), (2) JSON config from `ica/llm_configs/{process}-llm.json`, (3) hardcoded class default on `LLMConfig`. All use OpenRouter `provider/model` format. Defaults: `anthropic/claude-sonnet-4.5` primary, `openai/gpt-4.1` for markdown validation, `google/gemini-2.5-flash` for freshness checks.
- **`%XX_` markers** (e.g., `%FA_TITLE`, `%M1_SOURCE`): Structured content tokens in theme generation output, parsed by `utils/marker_parser.py`. Prefixes: FA (featured), M1/M2 (main), Q1-Q3 (quick hits), I1/I2 (industry), RV (verified).
- **Slack `sendAndWait`**: Core human-in-the-loop primitive for approvals and feedback.
- **Notes table**: Consolidated feedback table with type discriminator. Uses "last 40 entries" pattern for injecting learning data into LLM prompts.
- **Markdown validation**: 3-layer approach — (1) character count code-based, (2) structural LLM, (3) voice LLM — results merged before retry. `ValidationLoopCounter` caps attempts at 3.
- **Structured logging**: `bind_context(run_id=..., step=...)` sets async-safe context vars that appear in all log output.
- **Tests**: Mirror source layout (`tests/test_pipeline/`, `tests/test_services/`, `tests/test_prompts/`, `tests/test_llm_configs/`, etc.). Use `pytest-asyncio` with `asyncio_mode = "auto"`. No conftest.py — tests use inline fixtures and `unittest.mock` (AsyncMock, patch, MagicMock). Tests organized into class-based groups.

### Database

PostgreSQL `n8n_custom_data` with 3 tables: `articles` (PK: `url`), `themes` (PK: `theme`), `notes` (PK: `id`, auto-increment). All use `type` column as discriminator. CRUD in `db/crud.py` uses PostgreSQL `ON CONFLICT DO UPDATE` for upserts. Async sessions via `db/session.py`.

### Docker / Infrastructure

Docker is the **only supported development workflow** — there is no local/bare-metal install path. All `make` targets execute inside containers.

- Multi-stage `Dockerfile`: `dev` target (uvicorn --reload) and `prod` target (gunicorn + UvicornWorker, non-root user).
- `docker-compose.yml` base services: `app`, `postgres:16-alpine`, `redis:7-alpine`. Overlays: `docker-compose.dev.yml`, `docker-compose.stage.yml`, `docker-compose.prod.yml`.
- `make dev` runs both base + dev compose files together.

## Project Status

All 389 implementation tasks are closed. The codebase is **feature-complete at the code level** — every pipeline step, service, prompt, validator, and database layer is implemented with unit tests. Remaining work is integration testing with real services, end-to-end pipeline validation, and production deployment. Tracked via beads (`bd ready`).

## Key Reference Files

| File | What it contains |
|---|---|
| `docs/user-guide.md` | User-facing guide: what the app does, pipeline steps, interaction patterns |
| `docs/credentials.md` | Credential setup for all 5 external services |
| `.env-example` | Template for all required environment variables |
| `_n8n-project/workflows/` | Source n8n JSON files (the reference implementation ported from) |

## Tool Configuration

- **Ruff**: line-length 99, target Python 3.12, rules: E, F, I, N, UP, B, SIM, RUF
- **mypy**: strict mode with pydantic plugin
- **pytest**: `asyncio_mode = "auto"`, testpaths = `["tests"]`
