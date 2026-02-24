# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Python rewrite of an n8n-based AI newsletter generation system (IS2-News → is2-content-automation / `ica`). The original n8n system lives in `_n8n-project/` as reference. The target newsletter is published at is2digital.com/newsletters for solopreneurs and SMB professionals interested in AI.

## Development Commands

```bash
# Install (uses hatch build system, Python 3.12+)
pip install -e ".[dev]"

# Tests
pytest                                    # Run all tests
pytest tests/test_pipeline/               # Run one test directory
pytest tests/test_services/test_llm.py    # Run one test file
pytest -k "test_successful_step"          # Run tests matching name
pytest --asyncio-mode=auto                # (configured in pyproject.toml)

# Linting & type checking
ruff check .                              # Lint (E, F, I, N, UP, B, SIM, RUF rules)
ruff format --check .                     # Format check
ruff format .                             # Auto-format
mypy ica                                  # Type check (strict mode, pydantic plugin)

# Run the app
python -m ica serve                       # Start FastAPI server
python -m ica run                         # Trigger pipeline via API
python -m ica status                      # Show pipeline run status
python -m ica collect-articles            # Manual article collection

# Docker / Makefile
make dev                                  # Start dev environment
make migrate                              # Run Alembic migrations
make db-shell                             # psql shell in postgres container
make help                                 # Show all targets

# Alembic migrations
alembic -c alembic.ini upgrade head
alembic -c alembic.ini revision --autogenerate -m "description"
```

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

Work is NOT complete until `git push` succeeds. See `AGENTS.md` for the full mandatory workflow. The critical steps:

```bash
git pull --rebase && bd sync && git push
git status  # Must show "up to date with origin"
```

## Architecture

### Package Structure

- `ica/config/` — Pydantic Settings (`settings.py`) + LLM model mapping (`llm_config.py`) + startup validation (`validation.py`). All config from env vars / `.env`.
- `ica/pipeline/` — Pipeline step implementations + orchestrator. Each step is a standalone module (e.g., `summarization.py`, `theme_generation.py`).
- `ica/pipeline/steps.py` — Adapter layer that wires step modules to `PipelineStep` protocol with service instantiation.
- `ica/pipeline/orchestrator.py` — Runs sequential then parallel steps, manages `PipelineContext` dataclass that accumulates state across the pipeline.
- `ica/services/` — External service clients: `llm.py` (LiteLLM wrapper), `slack.py` (Slack Bolt), `google_sheets.py`, `google_docs.py`, `search_api.py` (SearchApi), `web_fetcher.py` (httpx).
- `ica/prompts/` — LLM prompt templates as pure functions returning strings. One file per pipeline step.
- `ica/validators/` — Content validation (character counts for markdown sections).
- `ica/utils/` — Small utilities: `marker_parser.py` (`%XX_` marker parsing), `output_router.py`, `boolean_normalizer.py`, `date_parser.py`.
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
- Daily: SearchApi (google_news engine) for 3 keywords
- Every 2 days: SearchApi (default engine) for 5 keywords

### Key Patterns

- **`PipelineContext`** dataclass flows through all steps, accumulating state. Sequential steps mutate and return it; parallel steps share the same snapshot.
- **`PipelineStep` protocol**: `async def __call__(self, ctx: PipelineContext) -> PipelineContext`. Steps in `steps.py` adapt each pipeline module to this protocol.
- **Service instantiation**: `steps.py` uses lazy factory helpers (`_make_slack()`, `_make_docs()`, etc.) with deferred imports to avoid circular deps.
- **LLM calls**: All go through `ica.services.llm.completion()` which handles model routing via `LLMPurpose` enum, retry with exponential backoff, and error mapping to `LLMError`.
- **LLM model config**: `ica/config/llm_config.py` centralizes all model identifiers (OpenRouter `provider/model` format). Each can be overridden via env var. Defaults: `anthropic/claude-sonnet-4.5` primary, `openai/gpt-4.1` for markdown validation, `google/gemini-2.5-flash` for freshness checks.
- **`%XX_` markers** (e.g., `%FA_TITLE`, `%M1_SOURCE`): Structured content tokens in theme generation output, parsed by `utils/marker_parser.py`.
- **Slack `sendAndWait`**: Core human-in-the-loop primitive for approvals and feedback.
- **Notes table**: Consolidated feedback table with type discriminator. Uses "last 40 entries" pattern for injecting learning data into LLM prompts.
- **Markdown validation**: 3-layer approach — (1) character count code-based, (2) structural LLM, (3) voice LLM — results merged before retry. `ValidationLoopCounter` caps attempts at 3.
- **Structured logging**: `bind_context(run_id=..., step=...)` sets async-safe context vars that appear in all log output.
- **Tests**: Mirror source layout (`tests/test_pipeline/`, `tests/test_services/`, etc.). Use `pytest-asyncio` with `asyncio_mode = "auto"`. No conftest.py — tests use inline fixtures and mocks.

### Database

PostgreSQL `n8n_custom_data` with 3 tables: `articles` (PK: `url`), `themes` (PK: `theme`), `notes` (PK: `id`, auto-increment). All use `type` column as discriminator. CRUD in `db/crud.py` uses PostgreSQL `ON CONFLICT DO UPDATE` for upserts. Async sessions via `db/session.py`.

## Key Reference Files

| File | What it contains |
|---|---|
| `_context/PRD.md` | Complete functional spec for the Python rewrite (~1128 lines) |
| `_context/project-details.md` | Technical analysis of all 12 n8n workflows: every node, code block, prompt, SQL query (~1397 lines) |
| `_context/tasks.csv` | 350 granular implementation tasks with parent/child relationships |
| `_n8n-project/workflows/` | Source n8n JSON files (the reference implementation to port from) |

## Tool Configuration

- **Ruff**: line-length 99, target Python 3.12, rules: E, F, I, N, UP, B, SIM, RUF
- **mypy**: strict mode with pydantic plugin
- **pytest**: `asyncio_mode = "auto"`, testpaths = `["tests"]`
