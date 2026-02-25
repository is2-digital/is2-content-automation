# ICA Technical Breakdown: Architecture & Core Systems

This document covers the foundational layers of the ICA codebase: pipeline orchestration, configuration, database, error handling, logging, the FastAPI application, and the CLI.

---

## Pipeline Orchestrator (`ica/pipeline/orchestrator.py`)

The orchestrator manages the sequential-then-parallel execution of the 6-step pipeline.

### StepName Enum

Canonical identifiers for all pipeline steps:

```
CURATION, SUMMARIZATION, THEME_GENERATION, MARKDOWN_GENERATION, HTML_GENERATION,
ALTERNATES_HTML, EMAIL_SUBJECT, SOCIAL_MEDIA, LINKEDIN_CAROUSEL
```

### PipelineContext Dataclass

A mutable dataclass that accumulates state as it flows through each step. Every step receives it, mutates it, and returns it.

| Field Group | Fields | Set By |
|---|---|---|
| **Identity** | `run_id`, `trigger` | Created at pipeline start |
| **Step 1** | `newsletter_id`, `articles` | Article curation |
| **Step 2** | `summaries`, `summaries_json` | Summarization |
| **Step 3** | `formatted_theme`, `theme_name`, `theme_body`, `theme_summary` | Theme generation |
| **Step 4** | `markdown_doc_id` | Markdown generation |
| **Step 5** | `html_doc_id` | HTML generation |
| **Tracking** | `step_results: list[StepResult]` | Every step (via `run_step`) |
| **Overflow** | `extra: dict[str, Any]` | Parallel steps (6a-6d) for non-core outputs |

### StepResult (frozen dataclass)

Per-step execution record: `step`, `status` ("completed"/"failed"), `started_at`, `completed_at`, `error`. Property `duration_seconds` computes wall-clock time.

### PipelineStep Protocol

```python
class PipelineStep(Protocol):
    async def __call__(self, ctx: PipelineContext) -> PipelineContext: ...
```

All pipeline steps implement this interface, enabling type-safe composition and testing.

### Execution Functions

**`run_step(step_name, step_fn, ctx) -> PipelineContext`**
- Executes a single step with `bind_context(step=...)` for structured logging
- Catches `PipelineStopError` and generic `Exception`
- Records a `StepResult` on the context regardless of outcome
- Re-raises errors so the orchestrator can handle them

**`run_pipeline(ctx, sequential_steps, parallel_steps) -> PipelineContext`**
- Runs sequential steps in order — context accumulates across them
- Then runs parallel steps via `asyncio.gather` — each receives the same context snapshot
- `PipelineStopError` from a sequential step halts the pipeline immediately
- Parallel step failures are collected but don't cancel siblings
- Uses `bind_context(run_id=ctx.run_id)` for the entire run

**`build_default_steps() -> (sequential_steps, parallel_steps)`**
- Returns the wired list of step tuples
- Uses deferred imports from `ica.pipeline.steps` to avoid circular dependencies

---

## Step Adapter Layer (`ica/pipeline/steps.py`)

Bridges between pipeline step modules and the `PipelineStep` protocol. Contains 9 adapter functions and lazy service factory helpers.

### Service Factory Helpers

All services are instantiated lazily inside each step (no global singletons):

| Helper | Creates | Source |
|---|---|---|
| `_get_settings()` | `Settings` singleton | `ica.config.settings` |
| `_make_slack()` | `SlackService(token, channel)` | Settings |
| `_make_sheets()` | `GoogleSheetsService(credentials_path)` | Settings |
| `_make_docs()` | `GoogleDocsService(credentials_path)` | Settings |
| `_make_http()` | `WebFetcherService()` | Stateless |
| `_session()` | `AsyncSession` context manager | `ica.db.session` |

### Step Functions

Each wraps the corresponding pipeline module and wires in services:

1. **`run_curation_step`** — Calls `prepare_curation_data()` then `run_approval_flow()`. Converts approved articles to dicts, stores in `ctx.articles` and `ctx.newsletter_id`.

2. **`run_summarization_step`** — Three phases: prepare data, summarize articles (per-article HTTP fetch + LLM), output with feedback loop. Stores summaries as both list and JSON string.

3. **`run_theme_generation_step`** — Most complex. Three nested interactive loops: generate themes → Slack selection → approve/reject/reset. Parses `%XX_` markers, runs freshness check. Sets `formatted_theme`, `theme_name`, `theme_body`, `theme_summary`.

4. **`run_markdown_generation_step`** — Fetches aggregated feedback, calls `generate_with_validation()` (3-layer validation, up to 3 attempts), user review loop via Slack. Sets `ctx.markdown_doc_id`.

5. **`run_html_generation_step`** — Fetches markdown from Google Doc, loads HTML template, computes newsletter date. Sets `ctx.html_doc_id`.

6. **`run_alternates_html_step`** — Calls `filter_unused_articles()` on formatted theme and summaries. Stores unused articles/URLs in `ctx.extra`.

7. **`run_email_subject_step`** — Generates email subjects with user selection. Stores subject, review text, and doc ID in `ctx.extra`.

8. **`run_social_media_step`** — Generates social media posts. Stores doc ID in `ctx.extra`.

9. **`run_linkedin_carousel_step`** — Generates LinkedIn carousel slides with character validation. Stores doc ID in `ctx.extra`.

### Design Patterns

- **Lazy service instantiation** within each step avoids circular deps
- **Session management** per CRUD operation (acquire → execute → commit/rollback)
- **Multi-phase composition** (prepare → process → output) for complex steps
- **`ctx.extra` dict** used by parallel steps for non-core outputs (doc IDs, subject lines, etc.)

---

## Error Handling (`ica/errors.py`)

### Exception Hierarchy

All inherit from `PipelineError(Exception)`:

| Exception | Use Case |
|---|---|
| `PipelineError` | Base. Constructor: `(step: str, detail: str)`. Message: `"[{step}] {detail}"` |
| `LLMError` | LLM API call failures (from litellm) |
| `FetchError` | HTTP page fetch failures (captcha, un-fetchable URL) |
| `DatabaseError` | DB operation failures |
| `ValidationError` | Content validation failures (character count, LLM validators) |
| `PipelineStopError` | Intentional halt (equivalent to n8n `stopAndError`) |

### Slack Error Notification

- `format_error_slack_message(step, error)` — Produces: `"*Execution Stopped at {step}...*"`
- `format_llm_error_slack_message(error)` — Shorter LLM-specific format
- `SlackErrorNotifier` (Protocol) — `async send_error(message: str) -> None`
- `notify_error(notifier, step, error)` — Logs error + sends Slack notification (handles Slack failures gracefully)
- `handle_step_error(error, step, notifier=None)` — Logs + notifies + re-raises as `PipelineStopError`

### ValidationLoopCounter

```python
@dataclass
class ValidationLoopCounter:
    max_attempts: int = 3
    _count: int = field(init=False, default=0)
```

Properties: `count`, `exhausted` (count >= max), `remaining`. Methods: `increment()`, `reset()`. Prevents infinite retry loops by force-accepting output after N attempts.

---

## Structured Logging (`ica/logging.py`)

### Context Variables (async-safe)

```python
run_id_var: contextvars.ContextVar[str | None]  # pipeline run ID
step_var: contextvars.ContextVar[str | None]     # current step name
```

Uses `contextvars` (not thread locals) for correct propagation across `await`.

### Components

| Component | Purpose |
|---|---|
| `ContextFilter` | Injects `run_id` and `step` from context vars into every log record |
| `JsonFormatter` | JSON-lines output for production. Fields: timestamp, level, logger, message, run_id, step, exception |
| `TextFormatter` | Human-readable output for dev. Prepends `[run=X step=Y]` tag when context is bound |

### Configuration

- `configure_logging(level="INFO", log_format="text")` — One-call setup, clears existing handlers, attaches `ContextFilter` + formatter
- `get_logger(name)` — Convenience wrapper, adds `ContextFilter` idempotently

### Context Binding

```python
class bind_context:
    """Both sync and async context manager."""
    def __init__(self, *, run_id=None, step=None): ...
```

Supports nesting — tracks tokens for proper restoration:

```python
async with bind_context(run_id="abc123"):
    logger.info("outer")  # includes run_id
    async with bind_context(step="summarization"):
        logger.info("inner")  # includes run_id + step
    logger.info("back")  # run_id only, step reset
```

---

## Database Layer

### Models (`ica/db/models.py`)

Three tables, all with `type` column as discriminator and `created_at` server-side timestamp:

**Article** (PK: `url`)
- `url: Text`, `title: Text | None`, `origin: Text | None`, `publish_date: Date | None`
- `approved: bool | None`, `industry_news: bool | None`, `newsletter_id: Text | None`
- `type: String(50)` — default "curated"

**Theme** (PK: `theme`)
- `theme: Text`, `theme_body: Text | None`, `theme_summary: Text | None`
- `newsletter_id: Text | None`, `approved: bool | None`
- `type: String(50)` — default "newsletter"

**Note** (PK: `id`, auto-increment)
- `feedback_text: Text` (required), `type: String(50)` (required), `newsletter_id: Text | None`
- Type values: `user_summarization`, `user_newsletter_themes`, `user_markdowngenerator`, `user_htmlgenerator`, `user_email_subject`
- Indexes: `ix_notes_created_at`, `ix_notes_type_created_at`

### CRUD (`ica/db/crud.py`)

| Function | Pattern | Notes |
|---|---|---|
| `upsert_articles(session, articles)` | PostgreSQL `ON CONFLICT DO UPDATE` on `url` PK | Updates title, origin, publish_date on conflict. Returns rowcount |
| `get_articles(session, approved?, newsletter_id?)` | Filtered query | Ordered by `created_at DESC` |
| `add_note(session, note_type, text, newsletter_id?)` | Insert + flush | Returns Note object before commit |
| `get_recent_notes(session, note_type, limit=40)` | Filtered + limited | Default 40 matches "last 40 entries" prompt injection pattern |
| `upsert_theme(session, theme, ...)` | PostgreSQL `ON CONFLICT DO UPDATE` on `theme` PK | Updates all provided fields |
| `get_themes(session, newsletter_id?, approved?)` | Filtered query | Ordered by `created_at DESC` |

Caller manages transactions — no auto-commit in CRUD functions.

### Session Factory (`ica/db/session.py`)

```python
get_engine(url=None) -> AsyncEngine          # defaults to Settings.database_url
get_session_factory(engine=None) -> async_sessionmaker[AsyncSession]
get_session(factory=None) -> AsyncGenerator[AsyncSession, None]  # @asynccontextmanager
```

`get_session()` auto-commits on success, auto-rollbacks on exception, always closes. Sets `expire_on_commit=False`.

---

## Configuration

### Settings (`ica/config/settings.py`)

Pydantic `BaseSettings` loading from env vars / `.env` file.

| Group | Fields | Notes |
|---|---|---|
| **Database** | `postgres_host` (localhost), `postgres_port` (5432), `postgres_db` (n8n_custom_data), `postgres_user`, `postgres_password` (required) | |
| **API Keys** | `openrouter_api_key` (required), `searchapi_api_key` (required) | |
| **Slack** | `slack_bot_token` (required), `slack_app_token` (required), `slack_channel` (required) | |
| **Google** | `google_sheets_credentials_path: Path`, `google_docs_credentials_path: Path` | Both required |
| **Optional** | `google_sheets_spreadsheet_id`, `html_template_path`, `timezone` (America/Los_Angeles), `log_level` (INFO), `log_format` (text) | |
| **Computed** | `database_url` (asyncpg), `database_url_sync` (for Alembic) | Derived from postgres fields |

Singleton: `get_settings()` with `@lru_cache(maxsize=1)`.

### Startup Validation (`ica/config/validation.py`)

`validate_config() -> ValidationResult` performs three-layer validation:

1. **Settings validation** — Attempts `Settings` instantiation, collects Pydantic `ValidationError` messages
2. **Timezone validation** — Checks against IANA zoneinfo database
3. **LLM model config validation** — Iterates all `LLMPurpose` variants, checks each model is non-empty and contains `/` separator (OpenRouter `provider/model` format)

Returns `ValidationResult(ok: bool, errors: tuple[str, ...])` — accumulates all errors (not fail-fast).

---

## FastAPI Application (`ica/app.py`)

### Run Tracking

- `RunStatus` enum: `PENDING`, `RUNNING`, `COMPLETED`, `FAILED`
- `PipelineRun` dataclass: `run_id` (12-char hex UUID), `status`, `trigger`, `started_at`, `completed_at`, `current_step`, `error`
- `_runs: dict[str, PipelineRun]` — in-memory store (not persisted)

### Application Factory

```python
create_app(include_slack=True, include_scheduler=True) -> FastAPI
```

Creates FastAPI app with lifespan context manager that:
- On startup: loads settings, configures logging, starts scheduler
- On shutdown: gracefully shuts down scheduler

Optionally mounts Slack Bolt handler and APScheduler.

### Endpoints

| Endpoint | Method | Purpose |
|---|---|---|
| `/health` | GET | Liveness check: `{"status": "ok"}` |
| `/trigger` | POST | Launches pipeline in background via `asyncio.create_task`. Accepts optional `trigger` label. Returns `run_id` + status immediately |
| `/status` | GET | Returns all pipeline runs |
| `/status/{run_id}` | GET | Returns single run (404 if not found) |
| `/scheduler` | GET | Scheduler status and job list |
| `/slack/events` | POST | Routes Slack events to Bolt handler (if configured) |

### Pipeline Execution

`_run_pipeline(run)` updates run status through PENDING → RUNNING → COMPLETED/FAILED. Creates `PipelineContext`, builds default steps via `build_default_steps()`, calls `run_pipeline()`. All within `bind_context(run_id)`.

---

## CLI (`ica/__main__.py`)

Built with Typer + Rich for terminal UI.

| Command | What It Does |
|---|---|
| `ica serve [--host] [--port] [--reload]` | Starts FastAPI via `uvicorn.run` with factory pattern |
| `ica run [--trigger cli] [--base-url]` | POSTs to `/trigger` endpoint, displays run_id and status |
| `ica status [run_id] [--base-url]` | GETs `/status`, displays as Rich table or pretty-printed single run with color-coded status |
| `ica collect-articles [--schedule daily\|every_2_days]` | Manual article collection via SearchApi. Displays stats and sample articles |

Status colors: pending (yellow), running (cyan), completed (green), failed (red).

Uses `_StubRepository` inner class for CLI dry-runs without a database.

---

## Cross-Module Data Flow

```
CLI (ica/__main__.py)
├── serve → FastAPI app (ica/app.py)
├── run  → POST /trigger
└── status → GET /status

FastAPI App
├── Lifespan: configure_logging() [logging.py], start scheduler
├── /trigger → asyncio.create_task(_run_pipeline)
│   └── _run_pipeline(run)
│       ├── Creates PipelineContext
│       └── bind_context(run_id)
│           └── run_pipeline() [orchestrator.py]
│               ├── Sequential: run_step() per step
│               │   └── steps.py adapter → pipeline module
│               │       ├── Service factory: _make_slack(), _make_docs()...
│               │       ├── Session factory: async with _session()
│               │       │   └── CRUD ops [crud.py] → ORM models [models.py]
│               │       └── On error: handle_step_error() → PipelineStopError
│               └── Parallel: _run_parallel_steps() via asyncio.gather
└── /status → serialize PipelineRun

Settings (config/settings.py)
├── @lru_cache get_settings()
├── Loaded from .env
├── Computed: database_url, database_url_sync
└── Used by all services
```
