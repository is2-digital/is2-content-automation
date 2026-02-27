# Code Walkthrough for PHP Developers

A comprehensive tour of every source file in the `ica/` package, organized by
architectural layer. Each section explains what the code does, highlights
Python-specific concepts, and calls out the PHP equivalent where helpful.

Open this file alongside your IDE and follow along.

---

## Table of Contents

1. [Python for PHP Developers](#1-python-for-php-developers)
2. [Project Entry Points](#2-project-entry-points)
3. [Configuration Layer](#3-configuration-layer)
4. [LLM Config System](#4-llm-config-system)
5. [Services Layer](#5-services-layer)
6. [Pipeline Architecture](#6-pipeline-architecture)
7. [Prompt System](#7-prompt-system)
8. [Database Layer](#8-database-layer)
9. [Utilities & Validators](#9-utilities--validators)
10. [Error Handling & Logging](#10-error-handling--logging)
11. [Testing Patterns](#11-testing-patterns)
12. [Infrastructure](#12-infrastructure)

---

## 1. Python for PHP Developers

### Syntax Quick-Reference

| PHP | Python | Notes |
|-----|--------|-------|
| `$variable = "hello";` | `variable = "hello"` | No `$`, no semicolons |
| `function foo(string $x): int` | `def foo(x: str) -> int:` | Colon starts the body; hints are advisory (enforced by mypy) |
| `class Foo extends Bar` | `class Foo(Bar):` | Parentheses for inheritance |
| `class Foo implements Bar` | `class Foo(Bar):` (Protocol) | No `implements` keyword — structural typing via Protocol |
| `$this->method()` | `self.method()` | `self` is explicit in every method signature |
| `new Foo($a, $b)` | `Foo(a, b)` | No `new` keyword |
| `['key' => 'val']` | `{"key": "val"}` | Python dicts use `{}` |
| `[1, 2, 3]` | `[1, 2, 3]` | Identical for lists/arrays |
| `foreach ($arr as $k => $v)` | `for k, v in arr.items():` | `.items()` returns key-value pairs |
| `$arr[] = $item;` | `arr.append(item)` | No `[]` push syntax |
| `use App\Service;` | `from app.service import Service` | Modules, not namespaces |
| `try { } catch (E $e) { }` | `try: ... except E as e: ...` | Keywords differ, same semantics |
| `$x ?? $default` | `x if x is not None else default` | Or use `x or default` for falsy |
| `match ($x) { ... }` | `match x: ...` (3.10+) | Structural pattern matching |
| `fn($x) => $x * 2` | `lambda x: x * 2` | Single-expression only |
| `array_map(fn, $arr)` | `[fn(x) for x in arr]` | List comprehension (preferred) |
| `str_contains($h, $n)` | `needle in haystack` | `in` operator works on strings, lists, dicts |

### Key Concepts

**Indentation is syntax.** Python uses indentation (4 spaces) instead of braces.
There are no `{}` blocks — the indentation level *is* the block.

**Modules, not namespaces.** Each `.py` file is a module. Directories with
`__init__.py` are packages. `from ica.services.llm import completion` imports
the `completion` function from `ica/services/llm.py`.

**Type hints are advisory.** Python does not enforce types at runtime. The
`mypy` tool checks them statically. This project uses `mypy --strict` so every
function must have full type annotations.

**`async`/`await` is a language feature.** Python 3.5+ has native async
support via `asyncio`. All I/O-bound code in this project is async. There is no
PHP equivalent in the standard library (closest: Swoole coroutines or ReactPHP).

**Decorators (`@something`).** A decorator wraps a function or class at
definition time. `@dataclass` auto-generates `__init__` and `__repr__`.
`@app.command()` registers a CLI command. PHP 8 Attributes are similar but do
not auto-execute.

**Context managers (`with`).** `with open("f") as f:` guarantees cleanup (like
`try/finally`). `async with` is the async version. Used everywhere for database
sessions, HTTP clients, and logging context.

**Dunder methods (`__init__`, `__call__`, `__enter__`).** Special methods that
Python calls automatically. `__init__` = constructor, `__call__` = make an
object callable like a function, `__enter__`/`__exit__` = context manager
protocol.

**`@dataclass` vs regular classes.** `@dataclass` auto-generates boilerplate
from field annotations. `@dataclass(frozen=True)` makes instances immutable
(like PHP `readonly` properties). This project uses dataclasses extensively for
DTOs and value objects.

**Pydantic models.** Like dataclasses but with runtime type validation and
coercion. `BaseModel` validates on construction. `BaseSettings` reads from
environment variables. This is the closest Python equivalent to Laravel's
validated request objects.

---

## 2. Project Entry Points

Three files define where execution starts.

### `ica/__main__.py` (256 lines)

The CLI entry point, invoked via `python -m ica`. Uses **Typer**, a modern CLI
framework that builds commands from function signatures.

```python
import typer

app = typer.Typer(help="IS2 Content Automation CLI")

@app.command()
def serve(
    host: str = typer.Option("0.0.0.0", help="Bind address"),
    port: int = typer.Option(8000, help="Port"),
    reload: bool = typer.Option(False, help="Enable hot reload"),
) -> None:
    """Start the FastAPI server."""
    uvicorn.run("ica.app:create_app", host=host, port=port, reload=reload, factory=True)
```

**For PHP devs:** This replaces Symfony Console's verbose command registration.
Typer reads the function's type hints and `typer.Option()` defaults to
auto-generate `--help` text, validate types, and parse arguments. No
`InputInterface`/`OutputInterface` boilerplate.

Four commands are defined:

| Command | Purpose | Line |
|---------|---------|------|
| `serve` | Start the FastAPI web server | 34 |
| `run` | Trigger a pipeline run via HTTP POST | 52 |
| `status` | Check pipeline run status | 83 |
| `collect-articles` | Manually harvest articles from Google Custom Search | 169 |

**Key pattern — `asyncio.run()`** (lines 57, 88, 181): Bridges sync CLI code
to async application code. Creates a new event loop, runs the coroutine, and
shuts down. PHP has no equivalent — it is inherently synchronous.

### `ica/app.py` (315 lines)

The **FastAPI application factory**. Defines REST endpoints and manages the
application lifecycle.

```python
def create_app(*, include_slack: bool = True, include_scheduler: bool = True) -> FastAPI:
    """Build and configure the FastAPI application."""
    app = FastAPI(title="ICA Pipeline", lifespan=lifespan)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/trigger")
    async def trigger(request: Request) -> dict[str, str]:
        run_id = uuid.uuid4().hex[:12]
        run = PipelineRun(run_id=run_id, trigger=trigger_label)
        _runs[run_id] = run
        asyncio.create_task(_run_pipeline(run))  # Fire & forget
        return {"run_id": run_id, "status": run.status.value}

    return app
```

**Key concepts:**

| Concept | What it does | PHP equivalent |
|---------|-------------|----------------|
| `create_app()` factory | Builds app with configurable features | Laravel `AppServiceProvider::boot()` |
| `@app.post("/trigger")` | Route decorator | `Route::post('/trigger', ...)` |
| `async def trigger(request: Request)` | Async endpoint handler | `public function trigger(Request $request)` |
| `asyncio.create_task()` | Spawn background coroutine | `dispatch(new PipelineJob(...))` |
| `@asynccontextmanager lifespan()` | App startup/shutdown hooks | Service provider `boot()`/`terminate()` |
| `PipelineRun` dataclass | In-memory run state | Eloquent model or DTO |
| `RunStatus(str, Enum)` | Enum whose members are strings | `enum RunStatus: string` (PHP 8.1) |

**The lifespan pattern** (line 102): An async context manager that runs startup
logic, `yield`s (app runs), then runs shutdown logic. This replaces the older
`@app.on_event("startup")` pattern.

```python
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info("Starting up")
    scheduler = create_scheduler(...)
    scheduler.start()
    yield                    # App runs here
    scheduler.shutdown()     # Cleanup after app stops
    logger.info("Shut down")
```

### `ica/scheduler.py` (242 lines)

Configures **APScheduler** (AsyncIO scheduler) with cron triggers for automated
article collection and optional pipeline triggering.

```python
def create_scheduler(
    *,                         # Forces all args to be keyword-only
    timezone: str,
    enable_article_collection: bool,
    enable_pipeline_trigger: bool,
    article_daily_hour: int = 6,
) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=timezone)
    if enable_article_collection:
        scheduler.add_job(
            run_article_collection,
            trigger=CronTrigger(hour=article_daily_hour, minute=0),
            kwargs={"schedule": "daily"},
            name="daily-article-collection",
        )
    return scheduler
```

**Scheduled jobs:**

| Job | Trigger | What it does |
|-----|---------|-------------|
| Daily article collection | Cron, 6 AM | Google CSE sorted by date, 3 keywords |
| Every-2-days collection | Interval, 48h | Google CSE relevance ranking, 5 keywords |
| Pipeline trigger | Cron, every 5 days (optional) | HTTP POST to `/trigger` |

**For PHP devs:** APScheduler runs in-process (same event loop as FastAPI).
No external cron daemon needed. The PHP equivalent is Laravel's scheduler
(`$schedule->call(...)->dailyAt('06:00')`) but that requires
`php artisan schedule:run` in an external cron.

**Keyword-only arguments** (`*` in the signature): The `*` forces callers to
use named parameters: `create_scheduler(timezone="...", enable_article_collection=True)`.
Prevents positional argument errors. PHP has no equivalent — you'd use an
options array or named arguments (PHP 8.0+).

---

## 3. Configuration Layer

Three files in `ica/config/` manage all application settings.

### `ica/config/settings.py` (91 lines)

Centralized config using **Pydantic Settings**. Every setting comes from an
environment variable or `.env` file.

```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",          # Ignore unknown env vars
    )

    # Database (all have defaults for Docker dev)
    postgres_host: str = "postgres"
    postgres_port: int = 5432
    postgres_user: str = "ica"
    postgres_password: str         # REQUIRED — no default

    # External services
    openrouter_api_key: str        # REQUIRED
    slack_bot_token: str           # REQUIRED
    slack_app_token: str           # REQUIRED
    google_cse_api_key: str        # REQUIRED
    google_cse_cx: str             # REQUIRED

    @computed_field
    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )
```

**For PHP devs:** Pydantic Settings replaces `env()` + `config()` from Laravel.
Key differences:

- Fields without defaults are **required** — app fails at startup if missing.
- Type coercion is automatic: `POSTGRES_PORT=5432` (string in env) becomes
  `int(5432)` in Python.
- `@computed_field` + `@property` creates a derived value accessible as
  `settings.database_url` (no parentheses). Like a PHP getter but cleaner.
- `@lru_cache(maxsize=1)` on `get_settings()` makes it a singleton. First call
  creates `Settings()`, subsequent calls return the cached instance.

```python
@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
```

### `ica/config/llm_config.py` (191 lines)

Maps **LLM purposes** to model identifiers using a 3-tier resolution system.

```python
class LLMPurpose(StrEnum):
    """21 distinct purposes for LLM calls across the pipeline."""
    SUMMARY = "llm_summary_model"
    SUMMARY_REGEN = "llm_summary_regen_model"
    THEME_GENERATION = "llm_theme_generation_model"
    MARKDOWN = "llm_markdown_model"
    MARKDOWN_STRUCTURAL_VALIDATION = "llm_markdown_structural_validation_model"
    # ... 16 more
```

The `get_model()` function resolves a purpose to a model string:

```
Tier 1 (highest): Environment variable override
    e.g. LLM_SUMMARY_MODEL=openai/gpt-4.1

Tier 2 (middle): JSON config file
    e.g. ica/llm_configs/summarization-llm.json → { "model": "anthropic/claude-sonnet-4.5" }

Tier 3 (lowest): Hardcoded class default
    e.g. LLMConfig.llm_summary_model = "anthropic/claude-sonnet-4.5"
```

**For PHP devs:** This is a sophisticated config overlay system. Most PHP apps
use either env vars OR config files. This uses both with a clear priority chain.
Production can override any model with a single env var; teams can tune per-step
via JSON; safe defaults exist for development.

The mapping from purpose → JSON process name is in `_PURPOSE_TO_PROCESS` (dict
at module level). `getattr(config, field_name)` does dynamic property access
(like PHP's `$config->{$fieldName}`).

### `ica/config/validation.py` (77 lines)

**Startup validation** that checks all config before the app runs.

```python
@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    errors: tuple[str, ...] = field(default=())

def validate_config() -> ValidationResult:
    errors: list[str] = []

    # 1. Validate all env vars via Pydantic
    try:
        settings = Settings(_env_file=None)
    except PydanticValidationError as exc:
        for err in exc.errors():
            loc = ".".join(str(p) for p in err["loc"])
            errors.append(f"Settings: {loc} — {err['msg']}")

    # 2. Validate TIMEZONE is valid IANA
    try:
        ZoneInfo(settings.timezone)
    except (KeyError, ZoneInfoNotFoundError):
        errors.append(f"Invalid timezone: {settings.timezone}")

    # 3. Validate all LLM models are provider/model format
    for purpose in LLMPurpose:
        model = get_model(purpose)
        if "/" not in model:
            errors.append(f"Model for {purpose.name} missing provider prefix: {model}")

    return ValidationResult(valid=not errors, errors=tuple(errors))
```

**For PHP devs:** Pydantic's `ValidationError` collects **all** validation
errors at once (not fail-fast). `exc.errors()` returns a list of dicts with
`loc` (field path), `msg` (human message), and `type` (error code). This is
far more structured than PHP's `InvalidArgumentException`.

---

## 4. LLM Config System

The `ica/llm_configs/` directory contains 19 JSON config files and a Python
loader. This is the "prompt database" — all LLM prompts, model assignments,
and metadata live here.

### `ica/llm_configs/schema.py` (53 lines)

Three nested Pydantic models define the JSON structure:

```python
class Prompts(BaseModel):
    system: str = Field(min_length=1)      # System prompt
    instruction: str = Field(min_length=1)  # User instruction template

class Metadata(BaseModel):
    google_doc_id: str | None = Field(default=None, alias="googleDocId")
    last_synced_at: str | None = Field(default=None, alias="lastSyncedAt")
    version: str | None = None

class ProcessConfig(BaseModel):
    model_config = {"populate_by_name": True}

    schema_version: str | None = Field(default=None, alias="$schema")
    process_name: str = Field(alias="processName")
    description: str = ""
    model: str = Field(min_length=1)
    prompts: Prompts
    metadata: Metadata | None = None
```

**For PHP devs:**

- `Field(alias="processName")` maps a camelCase JSON key to a snake_case Python
  field. Like defining a JSON key mapping in a Laravel Resource.
- `Field(min_length=1)` validates on construction — no manual `if empty throw`.
- `model_config = {"populate_by_name": True}` allows construction by either
  the alias or the field name.

### `ica/llm_configs/loader.py` (201 lines)

Loads JSON config files with **file-mtime caching**:

```python
# Module-level cache: process_name → (mtime, ProcessConfig)
_cache: dict[str, tuple[float, ProcessConfig]] = {}

def load_process_config(process_name: str) -> ProcessConfig:
    path = _CONFIG_DIR / f"{process_name}-llm.json"
    mtime = path.stat().st_mtime
    cached = _cache.get(process_name)
    if cached is not None and cached[0] == mtime:
        return cached[1]           # Return cached if file unchanged
    raw = json.loads(path.read_text())
    config = ProcessConfig(**raw)   # Pydantic validates
    _cache[process_name] = (mtime, config)
    return config
```

**Cache invalidation:** Compares file modification time on every call. If the
JSON file is edited, the next call picks up the change automatically. No
restart needed.

**Public API functions:**

```python
def get_process_prompts(process_name: str) -> tuple[str, str]:
    """Return (system_prompt, instruction_template) from JSON."""
    config = load_process_config(process_name)
    return config.prompts.system, config.prompts.instruction

def get_process_model(process_name: str) -> str:
    """Return the model identifier from JSON."""
    return load_process_config(process_name).model
```

### The 19 JSON Config Files

Each file follows the same schema. Example (`summarization-llm.json`):

```json
{
  "$schema": "ica-llm-config/v1",
  "processName": "summarization",
  "description": "Article summarization for newsletter content",
  "model": "anthropic/claude-sonnet-4.5",
  "prompts": {
    "system": "You are a professional AI research editor...",
    "instruction": "{feedback_section}\n## Output Format...\n{article_content}"
  },
  "metadata": {
    "googleDocId": null,
    "lastSyncedAt": null,
    "version": "1.0"
  }
}
```

Template variables in `instruction` (like `{feedback_section}`,
`{article_content}`) are filled at runtime by the prompt builder functions in
`ica/prompts/`. The JSON defines the static template; Python handles the dynamic
interpolation.

**All 19 config files:**

| File | LLM Purpose |
|------|-------------|
| `summarization-llm.json` | Article summarization |
| `summarization-regen-llm.json` | Summary regeneration after feedback |
| `theme-generation-llm.json` | Generate 2 newsletter themes |
| `theme-generation-regen-llm.json` | Regenerate themes after feedback |
| `freshness-check-llm.json` | Check theme freshness vs recent issues |
| `markdown-generation-llm.json` | Generate ~4000-word newsletter markdown |
| `markdown-generation-regen-llm.json` | Regenerate markdown after validation |
| `markdown-structural-validation-llm.json` | Structural format checking |
| `markdown-voice-validation-llm.json` | Tone/voice consistency checking |
| `html-generation-llm.json` | Convert markdown to email HTML |
| `html-generation-regen-llm.json` | Regenerate HTML after feedback |
| `email-subject-llm.json` | Generate 10 email subject options |
| `email-review-llm.json` | Generate email intro paragraph |
| `social-media-post-llm.json` | Generate 12 social media post concepts |
| `social-media-caption-llm.json` | Generate captions for selected posts |
| `social-media-regen-llm.json` | Regenerate social media after feedback |
| `linkedin-carousel-llm.json` | Generate carousel copy + 10 slides |
| `linkedin-carousel-regen-llm.json` | Regenerate carousel after feedback |
| `learning-data-extraction-llm.json` | Extract structured learning from feedback |

---

## 5. Services Layer

Six service modules in `ica/services/` wrap external APIs. All are async.

### `ica/services/llm.py` (206 lines)

The **LLM gateway** — all AI calls go through this single function.

```python
@dataclass(frozen=True)
class LLMResponse:
    text: str
    model: str
    purpose: LLMPurpose | None = None
    usage: dict[str, int] | None = None

async def completion(
    *,
    purpose: LLMPurpose | None = None,
    model: str | None = None,
    system_prompt: str,
    user_prompt: str,
    max_retries: int = DEFAULT_MAX_RETRIES,
    **litellm_kwargs: Any,
) -> LLMResponse:
```

**Three responsibilities:**

1. **Model routing** — resolves `purpose` to a model string via `get_model()`,
   or uses an explicit `model` parameter.
2. **Retry with exponential backoff** — retries on `RateLimitError`,
   `ServiceUnavailableError`, `Timeout`, `InternalServerError`,
   `APIConnectionError`. Formula: `base_delay * 2^attempt`, capped at
   `max_delay`.
3. **Error mapping** — catches LiteLLM exceptions and wraps them in the
   project's `LLMError` type.

**For PHP devs:**

- `**litellm_kwargs` is like PHP's `...$args` (variadic) but for named
  parameters. Passes extra keyword arguments through to the underlying library.
- `@dataclass(frozen=True)` makes `LLMResponse` immutable — you cannot reassign
  `response.text = "new"` after creation.
- The function validates the response: if `content` is empty or whitespace-only,
  it raises `LLMError` rather than returning garbage.

### `ica/services/slack.py` (584 lines)

The largest service. Wraps **Slack Bolt** for interactive messaging.

**Core primitive — `send_and_wait`:**

```python
async def send_and_wait(
    self,
    channel: str,
    text: str,
    *,
    approve_label: str = "Proceed to next steps",
) -> None:
    callback_id = uuid.uuid4().hex[:12]
    pending = _PendingInteraction(interaction_type="approval")
    self._pending[callback_id] = pending

    # Post message with button
    await self._client.chat_postMessage(channel=channel, blocks=blocks)

    # Block until user clicks the button
    await pending.event.wait()
```

This is the **human-in-the-loop** primitive. The function posts a Slack message
with a button, then suspends (via `asyncio.Event.wait()`) until a human clicks
it. The handler callback (registered separately) calls `event.set()` to wake
the waiting coroutine.

**Three interaction types:**

| Type | Flow | Return |
|------|------|--------|
| Approval | Click button → resolve | `None` |
| Form | Click → modal opens → submit → resolve | `dict` of field values |
| Freetext | Click → modal opens → type text → submit → resolve | `str` |

**For PHP devs:** `asyncio.Event` is a synchronization primitive. `event.wait()`
blocks the current coroutine (not the thread). `event.set()` wakes it up. This
is like a `Promise` that resolves when the callback fires. PHP would need
ReactPHP Promises or a queue-based polling approach.

**Block Kit helpers** build Slack JSON payloads:
- `_text_block()` — section with mrkdwn text
- `_button_block()` — actions block with interactive button
- `_build_modal_blocks()` — input blocks from form definitions
- `_build_selection_form()` — radio button forms for theme selection

### `ica/services/google_sheets.py` (241 lines)

Wraps the Google Sheets API v4. Uses service account credentials.

```python
async def read_rows(self, spreadsheet_id: str, sheet_name: str) -> list[dict[str, str]]:
    """Read all rows. First row = headers; subsequent rows become dicts."""
    data = await asyncio.to_thread(
        self._service.spreadsheets().values()
            .get(spreadsheetId=spreadsheet_id, range=f"{sheet_name}!A:Z")
            .execute
    )
    headers = rows[0]
    return [dict(zip(headers, row)) for row in rows[1:]]
```

**Key pattern — `asyncio.to_thread()`**: The Google API client is synchronous.
This function runs the sync call in a thread pool, keeping the event loop free.
In PHP you would just call the sync API directly (PHP is single-threaded anyway).

**Note:** `.execute` is passed as a callable reference (no parentheses). It is
called by the thread pool, not by the current coroutine.

Other methods:
- `append_rows()` — write rows to sheet (headers from first dict's keys)
- `clear_sheet()` — clear all values in A:Z range

### `ica/services/google_docs.py` (213 lines)

Wraps the Google Docs API v1. Creates documents and manages content.

```python
async def create_document(self, title: str) -> str:
    """Create a new Google Doc. Returns the document ID."""
    doc = await asyncio.to_thread(
        self._service.documents().create(body={"title": title}).execute
    )
    return doc["documentId"]

async def insert_content(self, document_id: str, text: str) -> None:
    """Insert text at the beginning of a document."""
    requests = [{"insertText": {"location": {"index": 1}, "text": text}}]
    await asyncio.to_thread(
        self._service.documents()
            .batchUpdate(documentId=document_id, body={"requests": requests})
            .execute
    )
```

**Text extraction** traverses the nested Google Docs JSON structure:
`body → content[] → paragraph → elements[] → textRun → content`. The helper
`_extract_text()` walks this tree with safe `.get()` calls (no crashes on
missing keys).

### `ica/services/google_search.py` (200 lines)

Wraps the **Google Custom Search JSON API** for article discovery. Uses a
**Protocol** for HTTP dependency injection.

```python
class HttpClient(Protocol):
    """Minimal interface for the HTTP client."""
    async def get(self, url: str, *, params: dict[str, Any]) -> dict[str, Any]: ...

@dataclass(frozen=True)
class SearchResult:
    url: str
    title: str
    date: str | None     # ISO-8601 from page metatags
    origin: str          # "daily" or "every_2_days"
```

**For PHP devs:** `Protocol` is Python's version of an interface, but
structural (duck typing). Any class with a matching `async def get(...)` method
automatically satisfies the protocol — no `implements` declaration needed. This
makes testing trivial: pass any object with a `get` method.

Methods:
- `search(keyword, *, num, date_restrict, sort_by_date)` — single keyword search, auto-paginates
- `search_keywords(keywords: list[str])` — aggregate results across keywords
- `_parse_results()` — extract `items[].{link, title}` + date from `pagemap.metatags`

### `ica/services/web_fetcher.py` (216 lines)

Async HTTP client for fetching article content. Includes HTML-to-text
conversion and failure detection.

```python
@dataclass(frozen=True)
class FetchResult:
    content: str | None     # Body on success
    error: str | None       # Error message on failure

def is_fetch_failure(result: FetchResult, url: str) -> bool:
    """Detect fetch failures: HTTP error, captcha, or YouTube."""
    if result.error is not None:
        return True
    if result.content and "sgcaptcha" in result.content:
        return True
    if "youtube.com" in url:
        return True
    return False
```

**HTML stripping** (`strip_html_tags`):
1. Remove `<script>` and `<style>` elements entirely
2. Replace block tags (`<p>`, `<div>`, etc.) with newlines
3. Strip remaining HTML tags
4. Unescape HTML entities (`&nbsp;` → space)
5. Normalize whitespace

**Resource ownership pattern:**

```python
class WebFetcherService:
    def __init__(self, client: httpx.AsyncClient | None = None, *, timeout: float = 30.0):
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=timeout)

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> WebFetcherService:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()
```

**For PHP devs:** The `_owns_client` flag tracks whether this service created
the HTTP client. If yes, it cleans up on close. If the caller injected a client,
the caller is responsible for cleanup. `__aenter__`/`__aexit__` make the service
usable with `async with WebFetcherService() as fetcher:`.

### `ica/services/prompt_editor.py` (215 lines)

Enables **editing LLM prompts via Google Docs**, triggered from Slack. This
is the Phase 3 "prompt tuning" workflow.

```python
class PromptEditorService:
    def __init__(self, docs_service: GoogleDocsService) -> None:
        self._docs = docs_service

    async def start_edit(self, process_name: str, field: str) -> str:
        """Open a Google Doc pre-filled with the current prompt content."""
        config = load_process_config(process_name)
        doc_id = await self._docs.create_document(f"[ICA Prompt] {process_name} — {field}")
        header = _build_edit_header(process_name, field, config.metadata.version)
        await self._docs.insert_content(doc_id, header + prompt_content)
        config.metadata.google_doc_id = doc_id
        save_process_config(process_name, config)
        return f"https://docs.google.com/document/d/{doc_id}/edit"

    async def sync_from_doc(self, process_name: str) -> ProcessConfig:
        """Pull edited prompt from Google Doc back to JSON config."""
        content = await self._docs.get_content(config.metadata.google_doc_id)
        field, prompt_text = _parse_doc_content(content)
        setattr(config.prompts, field, prompt_text)
        config.metadata.version += 1
        save_process_config(process_name, config)
        return config

    def get_config_summary(self, process_name: str) -> str:
        """Format config info for Slack display (model, prompt lengths, version)."""
```

**The editing flow:**

1. `start_edit("summarization", "system")` → creates a Google Doc with a header
   block + current prompt content, stores `google_doc_id` in metadata
2. User edits the prompt text in Google Docs
3. `sync_from_doc("summarization")` → reads the doc, parses the header to find
   which field was edited, updates the JSON config, bumps the version, clears
   the `google_doc_id`

**The doc header** (inserted at the top, not to be edited by users):
```
--- ICA PROMPT EDITOR ---
Process: summarization
Field: system
Version: 3

Edit the prompt content below. Do not modify this header.
--- END HEADER ---
```

`_parse_doc_content()` splits on `--- END HEADER ---` to separate the header
metadata from the edited prompt text.

**For PHP devs:** `setattr(config.prompts, field, prompt_text)` is dynamic
property assignment — `$config->prompts->{$field} = $promptText` in PHP.
`getattr()` is the read equivalent. This allows the same code to handle both
"system" and "instruction" fields without branching.

---

## 6. Pipeline Architecture

The heart of the application. The pipeline orchestrator runs sequential then
parallel steps, passing a mutable context object through each one.

### `ica/pipeline/orchestrator.py` (357 lines)

**PipelineStep Protocol** (line 131):

```python
class PipelineStep(Protocol):
    """Any async callable that takes and returns PipelineContext."""
    async def __call__(self, ctx: PipelineContext) -> PipelineContext: ...
```

**For PHP devs:** This is like `interface PipelineStep { public function __invoke(PipelineContext $ctx): PipelineContext; }`.
Any async function or callable object with the right signature works. No
`implements` needed.

**PipelineContext** (line 57):

```python
@dataclass
class PipelineContext:
    """Accumulated pipeline state passed between steps."""
    run_id: str = ""
    trigger: str = "manual"

    # Step 1: Curation
    newsletter_id: str | None = None
    articles: list[dict[str, Any]] = field(default_factory=list)

    # Step 2: Summarization
    summaries: list[dict[str, Any]] = field(default_factory=list)
    summaries_json: str = ""

    # Step 3: Theme
    formatted_theme: dict[str, Any] = field(default_factory=dict)
    theme_name: str = ""
    theme_body: str = ""
    theme_summary: str | None = None

    # Step 4: Markdown
    markdown_doc_id: str | None = None

    # Step 5: HTML
    html_doc_id: str | None = None

    # Tracking
    step_results: list[StepResult] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)
```

**For PHP devs:** Think of this as Laravel's `Request` flowing through
middleware. Each step reads what it needs, adds its output, and passes it along.
`extra` is the escape hatch for step-specific data that doesn't warrant a
dedicated field. `field(default_factory=list)` avoids the "mutable default
argument" bug (a common Python gotcha where all instances would share the same
list).

**Execution — `run_pipeline()`** (line 217):

```python
async def run_pipeline(
    ctx: PipelineContext,
    *,
    sequential_steps: list[tuple[str, PipelineStep]] | None = None,
    parallel_steps: list[tuple[str, PipelineStep]] | None = None,
) -> PipelineContext:
    async with bind_context(run_id=ctx.run_id):
        # --- Sequential: one by one ---
        for step_name, step_fn in sequential_steps:
            ctx = await run_step(step_name, step_fn, ctx)

        # --- Parallel: all at once ---
        if parallel_steps:
            errors = await _run_parallel_steps(ctx, parallel_steps)
    return ctx
```

**Sequential steps** receive and return the same context object. Each step's
mutations are visible to subsequent steps.

**Parallel steps** (line 270) all receive the **same context snapshot**. They
run concurrently via `asyncio.gather()`. Failures are caught and logged but
do not cancel sibling steps.

```python
async def _run_parallel_steps(ctx, steps):
    errors: list[tuple[str, Exception]] = []

    async def _safe_run(name, fn):
        try:
            await fn(ctx)
        except Exception as exc:
            errors.append((name, exc))
            # Continue — don't cancel siblings

    await asyncio.gather(*[_safe_run(n, f) for n, f in steps])
    return errors
```

**For PHP devs:** Sequential = middleware pipeline. Parallel = Laravel job
batch where each job runs independently. `asyncio.gather()` is like
`Promise.all()` in JavaScript.

**Step timing** — `StepResult` (line 32):

```python
@dataclass(frozen=True)
class StepResult:
    step: str
    status: str              # "completed" or "failed"
    started_at: datetime
    completed_at: datetime
    error: str | None = None

    @property
    def duration_seconds(self) -> float:
        return (self.completed_at - self.started_at).total_seconds()
```

Every step's timing is recorded in `ctx.step_results`.

### `ica/pipeline/steps.py` (553 lines)

The **adapter layer** — wires each step module to the `PipelineStep` protocol.

```python
async def run_curation_step(ctx: PipelineContext) -> PipelineContext:
    """Adapter: article_curation module → PipelineStep."""
    slack = _make_slack()
    sheets = _make_sheets()
    async with _session() as session:
        result = await run_article_curation(session, slack, sheets, ...)
    ctx.articles = [asdict(a) for a in result.articles]
    ctx.newsletter_id = result.newsletter_id
    return ctx
```

**Lazy factory helpers:**

```python
def _make_slack() -> SlackService:
    from ica.services.slack import SlackService   # Deferred import
    settings = _get_settings()
    return SlackService(token=settings.slack_bot_token, ...)

def _make_sheets() -> GoogleSheetsService:
    from ica.services.google_sheets import GoogleSheetsService
    return GoogleSheetsService(credentials_path=...)
```

**Why deferred imports?** Avoids circular dependencies. The orchestrator imports
`steps.py`, which would import all modules, which might import the orchestrator.
Deferred imports break the cycle. This is a common Python pattern — PHP does not
have this issue because `use` statements are resolved lazily.

### Step Modules (9 files)

Each step module follows the same structure:
1. Protocol definitions (for dependency injection)
2. Data classes (structured inputs/outputs)
3. Helper functions (parsing, formatting, validation)
4. LLM calls (via `ica.services.llm.completion()`)
5. Database operations (via async session)
6. Main orchestration function

**Step 1: Article Curation** (`article_curation.py`, 441 lines)

```
Flow: Fetch unapproved articles from DB
  → Write to Google Sheet for review
  → [HUMAN APPROVES IN SHEET]
  → Read approved rows back
  → Validate (at least 1 approved + newsletter_id)
  → Parse into ApprovedArticle objects
```

Uses `send_and_wait` (approval type) for the initial go-ahead, then reads
the Google Sheet for the actual approval data. The validation loop retries
if the sheet data is incomplete.

**Step 2: Summarization** (`summarization.py`, 1146 lines — the largest)

```
Phase 1 (Prep):
  Read approved articles from sheet
  → Normalize rows → Upsert to DB (type='curated')

Phase 2 (Per-article):
  FOR EACH article:
    HTTP fetch article URL
    IF failure (captcha / YouTube / error):
      Slack modal for manual content paste
    LLM summarization → parse output
    Build summary objects

Phase 3 (Review):
  Format summaries for Slack (mrkdwn + Block Kit)
  send_and_wait_form: Yes / Feedback / Restart
  IF Feedback:
    Regeneration LLM → extract learning data
    Store feedback (type='user_summarization')
    LOOP back to Phase 3
```

**Learning data pattern:** The LLM extracts structured learning from raw user
feedback, which is stored in the `notes` table. The last 40 entries are loaded
and injected into future prompts, creating a feedback loop that improves over
time.

**Step 3: Theme Generation + Selection** (two files)

`theme_generation.py` (249 lines) generates 2 themes from summaries.
`theme_selection.py` (687 lines) handles the interactive selection flow.

```
OUTER LOOP:
  Generate 2 themes (with %XX_ markers)
  → Post to Slack

  SELECTION LOOP:
    Form: Pick Theme 1, Theme 2, or "Add Feedback"
    IF feedback → store, regenerate (outer loop)
    IF selected:
      Parse markers → Run freshness check (Gemini)
      → Format selected theme body

      APPROVAL LOOP:
        Form: Approve / Reset / Feedback
        IF approve → save to DB, return
        IF reset → regenerate (outer loop)
        IF feedback → store, regenerate
```

**`%XX_` markers** are structured tokens in the LLM output:

| Prefix | Meaning | Fields |
|--------|---------|--------|
| `%FA_` | Featured Article | TITLE, SOURCE, URL, CATEGORY, WHY_FEATURED |
| `%M1_`, `%M2_` | Main Articles 1 & 2 | TITLE, SOURCE, URL, CALLOUT |
| `%Q1_`–`%Q3_` | Quick Hits 1–3 | TITLE, SOURCE, URL |
| `%I1_`, `%I2_` | Industry News 1 & 2 | TITLE, SOURCE, URL |
| `%RV_` | Requirements Verified | Distribution check |

**Step 4: Markdown Generation** (`markdown_generation.py`)

Three-layer validation:

```
Layer 1: Code-based character count (ica/validators/)
  → Check section lengths against preset ranges

Layer 2: LLM structural validation (openai/gpt-4.1)
  → Check markdown structure, headers, formatting

Layer 3: LLM voice validation (openai/gpt-4.1)
  → Check tone, consistency, readability

IF any errors AND attempts < 3:
  Merge all errors → Regeneration LLM
  LOOP

IF attempts == 3:
  Force-accept (log warning)
```

**Step 5: HTML Generation** (`html_generation.py`)

```
Read markdown from Google Doc
→ Load HTML email template
→ LLM: convert markdown to template-styled HTML
→ Create Google Doc with HTML
→ Slack review loop (Yes / Feedback)
```

**Steps 6a–6d: Parallel Output** (run concurrently after HTML)

| Step | File | What it produces |
|------|------|-----------------|
| 6a | `alternates_html.py` (105 lines) | Identifies unused articles (not in theme) |
| 6b | `email_subject.py` | 10 subject line options → human selects → review paragraph |
| 6c | `social_media.py` | 12 post concepts → human selects → captions per post |
| 6d | `linkedin_carousel.py` | Carousel copy + 10 slides with character validation |

All follow the same pattern: LLM generation → Slack review → Google Doc output.
Failures in one do not cancel the others.

### `ica/pipeline/article_collection.py` (190 lines)

A **standalone utility** (not a pipeline step) that runs on the scheduler for
automated article discovery.

```python
DAILY_KEYWORDS = ["Artificial General Intelligence", "Automation", "Artificial Intelligence"]
EVERY_2_DAYS_KEYWORDS = ["AI breakthrough", "AI latest", "AI tutorial", "AI case study", "AI research"]

async def collect_articles(
    client: GoogleSearchClient,
    repository: ArticleRepository,
    *,
    schedule: str = "daily",
) -> CollectionResult:
    """
    1. Query Google CSE for each keyword
    2. Deduplicate results by URL
    3. Parse relative dates ('3 days ago' → calendar date)
    4. Upsert to database
    """
```

**Two schedules:**

| Schedule | Engine | Keywords | Results per keyword |
|----------|--------|----------|---------------------|
| `daily` | `sort_by_date=True` | 3 | 10 |
| `every_2_days` | `sort_by_date=False` | 5 | 10 |

**Key types:**

- `ArticleRecord` (frozen dataclass) — url, title, origin, publish_date
- `ArticleRepository` (Protocol) — interface for DB persistence
- `CollectionResult` — tracks raw_results → deduplicated → articles → rows_affected

**For PHP devs:** The `ArticleRepository` Protocol is the interface; the
concrete implementation (`SqlArticleRepository`) lives in `ica/db/repository.py`.
This separation allows testing with a fake repository.

---

## 7. Prompt System

The `ica/prompts/` directory contains 13 files (~1100 lines total). Each file
is a **prompt builder** — a pure function that returns
`tuple[str, str]` (system prompt, user prompt).

### Pattern

All prompt builders follow the same structure:

```python
from ica.llm_configs import get_process_prompts

def build_summarization_prompt(
    article_content: str,
    feedback: str | None = None,
) -> tuple[str, str]:
    """Build prompt for article summarization."""
    system, instruction = get_process_prompts("summarization")

    feedback_section = ""
    if feedback:
        feedback_section = f"## Previous Feedback\n{feedback}\n"

    user_prompt = instruction.format(
        feedback_section=feedback_section,
        article_content=article_content,
    )
    return system, user_prompt
```

**For PHP devs:** This is a **prompt compiler** layer. The static template text
lives in JSON files; the Python functions handle dynamic variable injection.
`str.format()` is like PHP's `sprintf()` or `str_replace()`. No template engine
(Twig/Blade) is needed — pure string interpolation.

### Files

| File | Lines | Builds prompts for |
|------|-------|--------------------|
| `summarization.py` | 141 | Article summary + regeneration with feedback |
| `theme_generation.py` | 70 | 2-theme generation with marker format |
| `markdown_generation.py` | 140 | Newsletter markdown + regeneration with validation errors |
| `html_generation.py` | 114 | Markdown-to-HTML + regeneration |
| `email_subject.py` | 70 | Subject line generation (max 7 words, 10 options) |
| `email_review.py` | 70 | Email intro paragraph (100–120 words) |
| `social_media.py` | 132 | Post concepts → captions → regeneration |
| `linkedin_carousel.py` | 90 | Carousel copy + 10 slides |
| `learning_data_extraction.py` | 55 | Convert raw feedback to structured learning |
| `freshness_check.py` | 42 | Theme vs. recent newsletters |
| `markdown_structural_validation.py` | 49 | Structural format checking |
| `markdown_voice_validation.py` | 48 | Voice/tone checking |

### Key Pattern: Generation vs. Regeneration

Most steps have two separate builder functions:

```python
def build_summarization_prompt(article_content, feedback=None):
    """First-pass generation."""
    ...

def build_summarization_regeneration_prompt(original_summary, feedback, article_content):
    """Regeneration after user feedback or validation failure."""
    ...
```

The regeneration prompt includes the original output, the user's feedback (or
validator errors), and the original source material. This gives the LLM full
context for targeted improvements.

---

## 8. Database Layer

PostgreSQL via **SQLAlchemy 2.0** (async). Three tables, minimal schema.

### `ica/db/models.py` (109 lines)

```python
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

class Base(DeclarativeBase):
    pass

class Article(Base):
    __tablename__ = "articles"

    url: Mapped[str] = mapped_column(Text, primary_key=True)
    title: Mapped[str | None] = mapped_column(Text)
    origin: Mapped[str | None] = mapped_column(Text)
    publish_date: Mapped[date | None] = mapped_column(Date)
    approved: Mapped[bool | None] = mapped_column(Boolean)
    industry_news: Mapped[bool | None] = mapped_column(Boolean)
    newsletter_id: Mapped[str | None] = mapped_column(Text)
    type: Mapped[str] = mapped_column(String(50), nullable=False, server_default="curated")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

class Theme(Base):
    __tablename__ = "themes"
    theme: Mapped[str] = mapped_column(Text, primary_key=True)
    # ... similar fields

class Note(Base):
    __tablename__ = "notes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
```

**For PHP devs:**

- `Mapped[str]` is SQLAlchemy 2.0's type annotation syntax. It replaces the
  older `Column(String)` pattern and integrates with mypy for type checking.
- `server_default=func.now()` generates a SQL `DEFAULT NOW()` clause — the
  default is set by PostgreSQL, not Python.
- The `type` column on each table acts as a **discriminator** for single-table
  inheritance. Instead of separate tables per feedback type, the `notes` table
  stores all types (`user_summarization`, `user_markdowngenerator`, etc.) with
  a `type` column.
- **No foreign keys or relationships.** Data is denormalized.
  `newsletter_id` is a text field for grouping, not an FK.

### `ica/db/session.py` (67 lines)

```python
from contextlib import asynccontextmanager

@asynccontextmanager
async def get_session(
    factory: async_sessionmaker[AsyncSession] | None = None,
) -> AsyncGenerator[AsyncSession, None]:
    factory = factory or get_session_factory()
    session = factory()
    try:
        yield session            # Caller uses session here
        await session.commit()   # Auto-commit on success
    except Exception:
        await session.rollback() # Rollback on failure
        raise
    finally:
        await session.close()    # Always clean up
```

**For PHP devs:** This is Python's transaction management pattern. The
`async with get_session() as session:` block auto-commits on success and
rolls back on exception. The `yield` statement is the key — it pauses the
function, lets the caller do work, then resumes for cleanup. PHP would use
explicit `try { $pdo->commit(); } catch { $pdo->rollback(); }`.

### `ica/db/crud.py` (183 lines)

Three categories of operations:

**1. Article upserts (PostgreSQL ON CONFLICT):**

```python
async def upsert_articles(session: AsyncSession, articles: list[dict]) -> int:
    stmt = pg_insert(Article).values(articles)
    stmt = stmt.on_conflict_do_update(
        index_elements=["url"],
        set_={
            "title": stmt.excluded.title,
            "origin": stmt.excluded.origin,
            "type": stmt.excluded.type,
        },
    )
    result = await session.execute(stmt)
    return result.rowcount
```

**For PHP devs:** This is `INSERT ... ON CONFLICT (url) DO UPDATE SET ...` —
a single atomic operation. MySQL equivalent: `ON DUPLICATE KEY UPDATE`.
`stmt.excluded` refers to the values that would have been inserted (the
"excluded" row in PostgreSQL terminology).

**2. Article queries:**

```python
async def get_articles(
    session: AsyncSession,
    *,
    approved: bool | None = None,
    newsletter_id: str | None = None,
    article_type: str | None = None,
) -> list[Article]:
    query = select(Article)
    if approved is not None:
        query = query.where(Article.approved == approved)
    if newsletter_id is not None:
        query = query.where(Article.newsletter_id == newsletter_id)
    result = await session.execute(query)
    return list(result.scalars().all())
```

Optional filters are applied conditionally. `result.scalars().all()` extracts
the ORM objects from the result set.

**3. Notes (feedback storage):**

```python
async def insert_note(session: AsyncSession, note_type: str, content: str) -> Note:
    note = Note(type=note_type, content=content)
    session.add(note)
    await session.flush()
    return note

async def get_recent_notes(
    session: AsyncSession,
    note_type: str,
    limit: int = 40,
) -> list[Note]:
    query = (
        select(Note)
        .where(Note.type == note_type)
        .order_by(Note.created_at.desc())
        .limit(limit)
    )
    result = await session.execute(query)
    return list(result.scalars().all())
```

**The "last 40 entries" pattern:** `get_recent_notes()` retrieves the most
recent 40 feedback entries of a given type. These are formatted as bullet points
and injected into LLM prompts, creating a learning loop.

### `ica/db/repository.py` (24 lines)

Concrete repository implementation that satisfies the `ArticleRepository`
Protocol from `article_collection.py`.

```python
class SqlArticleRepository:
    """Database-backed ArticleRepository.

    Wraps an AsyncSession and delegates to crud functions.
    The caller is responsible for session lifecycle (commit/rollback).
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert_articles(self, articles: list[ArticleRecord]) -> int:
        return await crud.upsert_articles(self._session, articles)
```

**For PHP devs:** This is the **Repository pattern** — a thin adapter between
the Protocol interface and the raw CRUD functions. It holds the session
reference so callers don't need to pass it explicitly. In Laravel terms, this
is like an Eloquent Repository that wraps query builder calls.

The separation exists so that `article_collection.py` (in the pipeline layer)
depends only on the `ArticleRepository` Protocol, not on SQLAlchemy. Tests can
substitute a fake repository without touching the database.

---

## 9. Utilities & Validators

### `ica/utils/marker_parser.py` (318 lines)

The core of theme parsing. Extracts `%XX_` markers from LLM output into
structured dataclasses.

```python
@dataclass(frozen=True)
class FeaturedArticle:
    title: str | None = None
    source: str | None = None
    origin: str | None = None
    url: str | None = None
    category: str | None = None
    why_featured: str | None = None

@dataclass(frozen=True)
class FormattedTheme:
    name: str | None = None
    featured: FeaturedArticle | None = None
    main_1: MainArticle | None = None
    main_2: MainArticle | None = None
    quick_1: QuickHit | None = None
    quick_2: QuickHit | None = None
    quick_3: QuickHit | None = None
    industry_1: IndustryItem | None = None
    industry_2: IndustryItem | None = None
    requirements_verified: str | None = None
```

**Helper functions:**

```python
def _extract(pattern: str, text: str) -> str | None:
    """Return first capture group, trimmed, or None."""
    m = re.search(pattern, text)
    return m.group(1).strip() if m else None

def parse_markers(theme_body: str, theme_title: str | None = None) -> FormattedTheme:
    featured = FeaturedArticle(
        title=_extract(r"%FA_TITLE:[ \t]*(.+)", theme_body),
        source=_extract(r"%FA_SOURCE:[ \t]*(.+)", theme_body),
        url=_extract(r"%FA_URL:[ \t]*(.+)", theme_body),
        # ...
    )
    return FormattedTheme(name=theme_title, featured=featured, ...)

def split_themes(raw_output: str) -> tuple[list[str], str | None]:
    """Split LLM output on '-----' delimiter into theme blocks + recommendation."""
    parts = re.split(r"-{5,}", raw_output)
    # ...
```

**For PHP devs:** This is a regex-based parser for a custom DSL. Each `%XX_`
prefix maps to a nested dataclass field. The `_extract()` helper is like:
```php
preg_match('/%FA_TITLE:\s*(.+)/', $body, $m);
$title = trim($m[1] ?? '');
```

### `ica/utils/output_router.py` (118 lines)

Conditional logic ported from n8n's "Conditional output" node.

```python
class UserChoice(str, Enum):
    YES = "yes"
    PROVIDE_FEEDBACK = "provide feedback"
    RESTART = "restart chat"

@dataclass(frozen=True)
class RouterResult:
    output_text: str
    feedback_text: str | None = None
    action: str = "continue"       # "continue" or "restart"

def conditional_output_router(
    switch_value: str | None,
    original_text: str,
    re_generated_text: str | None = None,
    content_valid: bool = True,
) -> RouterResult:
```

Three paths:
- **"yes"** → use regenerated text (if exists), else original → continue
- **"provide feedback"** → use original → store feedback → continue
- **"restart"** → store current text → restart loop

### `ica/utils/boolean_normalizer.py` (42 lines)

Type coercion for Google Sheets exports:

```python
def normalize_boolean(value: str | bool | None) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    cleaned = str(value).strip().lower()
    return cleaned == "yes"
```

**Only `"yes"` is truthy.** `"true"`, `"1"`, `"on"` all return `False`. This
matches Google Sheets export behavior where checkboxes become `"yes"`/`"no"`.

### `ica/utils/date_parser.py` (97 lines)

Two parsers:

```python
def parse_relative_date(date_string: str | None) -> date:
    """Parse '3 days ago' from search results."""
    match = _RELATIVE_DATE_RE.search(date_string)    # r"(\d+)\s*(day|days|...)\s*ago"
    value = int(match.group(1))
    unit = match.group(2).lower()
    return reference - timedelta(days=value)

def parse_date_mmddyyyy(date_string: str | None) -> date | None:
    """Parse '02/26/2026' from Google Sheets."""
    return datetime.strptime(date_string.strip(), "%m/%d/%Y").date()
```

### `ica/validators/character_count.py` (251 lines)

Code-based character count validation for markdown sections. Part of the
3-layer validation system (this is layer 1).

```python
@dataclass(frozen=True)
class CharacterCountError:
    section: str        # "Featured Article"
    field: str          # "Paragraph 1"
    current: int        # 250
    target_min: int     # 300
    target_max: int     # 400
    delta: int          # -50 (too short by 50 chars)
```

**Validation ranges:**

| Section | Field | Min | Max |
|---------|-------|-----|-----|
| Quick Highlights | Each bullet | 150 | 190 |
| Featured Article | Paragraph 1 | 300 | 400 |
| Featured Article | Paragraph 2 | 300 | 400 |
| Featured Article | Key Insight | 300 | 370 |
| Main Articles | Callout | 180 | 250 |
| Main Articles | Content | — | 750 |

**Section extraction** uses regex to find markdown headings and capture content
between them:

```python
def extract_section(raw: str, title: str) -> str:
    pattern = re.compile(
        rf"#\s*\*?{re.escape(title)}\*?\s*\n([\s\S]*?)(?=\n#\s*\*?|$)",
        re.IGNORECASE,
    )
```

Helper functions:
- `_extract_bullets()` — splits on `•` or `-` prefixes
- `_find_callout()` — finds `**Label:**` pattern
- `_extract_cta()` — finds CTA line (contains `→`)
- `_strip_source_links()` — removes `[Source](url)` markdown

---

## 10. Error Handling & Logging

### `ica/errors.py` (282 lines)

A typed exception hierarchy:

```
PipelineError (base)
├── LLMError          — LLM call failed
├── FetchError        — HTTP fetch failed
├── DatabaseError     — DB operation failed
├── ValidationError   — Content validation failed
└── PipelineStopError — Halt pipeline execution
```

Each exception takes `step` and `detail` and formats as `[step] detail`:

```python
class PipelineError(Exception):
    def __init__(self, step: str, detail: str) -> None:
        self.step = step
        self.detail = detail
        super().__init__(f"[{step}] {detail}")
```

**Slack error notification:**

```python
async def notify_error(
    notifier: SlackErrorNotifier | None,
    step: str,
    error: str,
) -> None:
    if notifier is None:
        return
    message = format_error_slack_message(step, error)
    await notifier.send_channel_message(channel, message)
```

The error message template matches n8n's original Slack node templates.

**ValidationLoopCounter:**

```python
@dataclass
class ValidationLoopCounter:
    max_attempts: int = 3
    _count: int = field(default=0, init=False, repr=False)

    @property
    def exhausted(self) -> bool:
        return self._count >= self.max_attempts

    def increment(self) -> None:
        self._count += 1
```

Caps validation retry loops at 3 attempts. After that, markdown is
force-accepted even if validators find errors. `init=False` means `_count`
is not a constructor parameter — it always starts at 0.

### `ica/logging.py` (259 lines)

Structured logging with **async-safe context propagation**.

**Context variables:**

```python
import contextvars

run_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("run_id", default=None)
step_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("step", default=None)
```

**For PHP devs:** `contextvars` is async-local storage. Unlike thread-local
storage (which breaks with `await`), context vars survive across `await`
boundaries within the same task. There is no PHP equivalent because PHP is
single-threaded. You would use dependency injection or a global registry.

**ContextFilter** injects run_id and step into every log record:

```python
class ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.run_id = run_id_var.get()
        record.step = step_var.get()
        return True
```

**bind_context** sets context vars with automatic restoration:

```python
class bind_context:
    def __init__(self, *, run_id: str | None = None, step: str | None = None):
        self._run_id = run_id
        self._step = step
        self._tokens: list[contextvars.Token] = []

    def __enter__(self):
        if self._run_id is not None:
            self._tokens.append(run_id_var.set(self._run_id))
        if self._step is not None:
            self._tokens.append(step_var.set(self._step))
        return self

    def __exit__(self, *exc):
        for token in reversed(self._tokens):
            token.var.reset(token)    # Restore previous value
```

**Usage (nesting supported):**

```python
with bind_context(run_id="abc123"):
    logger.info("Outer")                  # run_id=abc123
    with bind_context(step="summarization"):
        logger.info("Inner")              # run_id=abc123, step=summarization
    logger.info("Back")                   # run_id=abc123, step=None
```

**Two formatters:**

- **JsonFormatter** — JSON lines for production:
  ```json
  {"timestamp": "...", "level": "INFO", "logger": "ica.pipeline", "message": "...", "run_id": "abc123", "step": "summarization"}
  ```
- **TextFormatter** — human-readable for development:
  ```
  2026-02-26 14:30:00 INFO [ica.pipeline] [run=abc123 step=summarization] Starting pipeline
  ```

---

## 11. Testing Patterns

55 test files mirror the source layout. All tests run inside Docker via
`make test`.

### Directory Structure

```
tests/
├── test_pipeline/          # 10 files — step modules + orchestrator
├── test_services/          # 5 files  — LLM, Slack, Sheets, Docs, fetcher
├── test_prompts/           # 10 files — prompt builders
├── test_llm_configs/       # 4 files  — config loading & validation
├── test_config/            # 3 files  — settings, validation
├── test_validators/        # 3 files  — character count
├── test_utils/             # 5 files  — parsers, routers
├── test_app.py             # FastAPI factory
├── test_cli.py             # CLI commands
├── test_scheduler.py       # Scheduler jobs
├── test_logging.py         # Structured logging
└── test_errors.py          # Error hierarchy
```

### Key Configuration

```toml
# pyproject.toml
[tool.pytest.ini_options]
asyncio_mode = "auto"       # All async tests run automatically
testpaths = ["tests"]
```

`asyncio_mode = "auto"` means you can write `async def test_something():`
without needing `@pytest.mark.asyncio` on every test. Pytest detects `async def`
and wraps it automatically.

### No conftest.py

This project has **no conftest.py**. All fixtures are defined inline within
test files as helper functions and fake classes. This keeps test context
localized and readable.

### Class-Based Organization

Tests are grouped into classes by concept:

```python
class TestLLMResponse:
    """Tests for the LLMResponse frozen dataclass."""

    def test_basic_fields(self) -> None:
        r = LLMResponse(text="hi", model="m1")
        assert r.text == "hi"
        assert r.model == "m1"

    def test_frozen(self) -> None:
        r = LLMResponse(text="hi", model="m1")
        with pytest.raises(AttributeError):
            r.text = "bye"    # type: ignore[misc]

class TestCompletionBasic:
    """Tests for the completion() function."""

    async def test_returns_llm_response(self) -> None:
        # ...
```

**For PHP devs:** This is like PHPUnit test classes, but without `extends TestCase`.
Pytest discovers any class starting with `Test` and any method starting with
`test_`.

### Mocking Patterns

**AsyncMock** for async functions:

```python
from unittest.mock import AsyncMock, MagicMock, patch

async def test_returns_response(self) -> None:
    with patch("ica.services.llm.litellm") as mock_litellm:
        mock_litellm.acompletion = AsyncMock(return_value=mock_response)
        result = await completion(purpose=LLMPurpose.SUMMARY, ...)
    assert result.text == "Hello!"
```

**For PHP devs:**

| PHP (PHPUnit/Mockery) | Python (unittest.mock) |
|------------------------|----------------------|
| `$this->createMock(Foo::class)` | `MagicMock()` or `AsyncMock()` |
| `$mock->expects($this->once())` | `mock.assert_called_once()` |
| `$mock->method('foo')->willReturn('bar')` | `mock.foo.return_value = "bar"` |
| `$mock->method('foo')->willThrowException(...)` | `mock.foo.side_effect = Exception(...)` |
| Mockery `$mock->shouldReceive('foo')->once()` | `mock.foo.assert_called_once()` |

**`side_effect` for sequences** — simulate retry scenarios:

```python
mock_litellm.acompletion = AsyncMock(
    side_effect=[RateLimitError("rate limited"), mock_response]
)
# First call raises, second call succeeds
result = await completion(...)
assert mock_litellm.acompletion.await_count == 2
```

**`patch.dict` for environment variables:**

```python
with patch.dict("os.environ", {"POSTGRES_PORT": "5433"}, clear=False):
    settings = Settings(_env_file=None)
assert settings.postgres_port == 5433
```

### Inline Fake Classes

```python
class FakeSheetReader:
    """Records calls and returns preset data."""
    def __init__(self, rows=None):
        self.rows = rows or []
        self.calls: list[tuple[str, str]] = []

    async def read_rows(self, spreadsheet_id, sheet_name):
        self.calls.append((spreadsheet_id, sheet_name))
        return self.rows
```

These satisfy Protocol contracts without `implements`. Any object with the
right method signatures works — structural typing.

### Parametrized Tests

```python
@pytest.mark.parametrize("field", list(REQUIRED_ENV.keys()))
def test_missing_required_field_raises(self, field: str) -> None:
    env = {k: v for k, v in REQUIRED_ENV.items() if k != field}
    with patch.dict("os.environ", env, clear=False):
        with pytest.raises(ValidationError):
            Settings(_env_file=None)
```

**For PHP devs:** `@pytest.mark.parametrize` is like PHPUnit's `@dataProvider`.
Each parameter set runs as a separate test case with its own pass/fail status.

### Exception Testing

```python
with pytest.raises(LLMError, match="empty response"):
    await completion(model="test", system_prompt=SYSTEM, user_prompt=USER)
```

`match="pattern"` checks the exception message against a regex. The `as`
clause gives access to the exception object:

```python
with pytest.raises(LLMError) as exc_info:
    await completion(...)
assert exc_info.value.step == "Theme Generation"
assert exc_info.value.__cause__ is original_exception
```

---

## 12. Infrastructure

### Dockerfile (multi-stage)

```dockerfile
FROM python:3.12-slim AS base
WORKDIR /app
COPY pyproject.toml .

FROM base AS dev
ENV ENVIRONMENT=development
COPY . .
RUN pip install -e ".[dev]"
CMD ["uvicorn", "ica.app:create_app", "--factory", "--host", "0.0.0.0", "--reload"]

FROM base AS prod
COPY . .
RUN pip install .
RUN useradd -r ica && chown -R ica:ica /app
USER ica
CMD ["gunicorn", "ica.app:create_app()", "-k", "uvicorn.UvicornWorker", "--bind", "0.0.0.0:8000"]
```

**Two build targets:**
- `dev` — editable install (`-e`), hot reload, runs as root
- `prod` — normal install, non-root user, gunicorn (production ASGI server)

### Docker Compose

```yaml
# docker-compose.yml (base)
services:
  app:
    build:
      context: .
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    env_file: .env

  postgres:
    image: postgres:16-alpine
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ica"]

  redis:
    image: redis:7-alpine
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
```

```yaml
# docker-compose.dev.yml (overlay)
services:
  app:
    build:
      target: dev
    ports:
      - "8000:8000"         # FastAPI
      - "5678:5678"         # debugpy remote attach
    volumes:
      - .:/app              # Source mount for hot reload
```

`make dev` runs both files together:
```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d
```

### Makefile

Key targets:

```makefile
COMPOSE = docker compose -f docker-compose.yml -f docker-compose.dev.yml

dev:                    ## Start dev environment
	$(COMPOSE) up -d --build

down:                   ## Stop all containers
	$(COMPOSE) down

test:                   ## Run tests (usage: make test ARGS="-k test_name")
	$(COMPOSE) exec app pytest $(ARGS)

lint:                   ## Run ruff linter
	$(COMPOSE) exec app ruff check . $(ARGS)

format:                 ## Run ruff formatter
	$(COMPOSE) exec app ruff format . $(ARGS)

typecheck:              ## Run mypy type checker
	$(COMPOSE) exec app mypy ica $(ARGS)

migrate:                ## Run Alembic migrations
	$(COMPOSE) exec app alembic upgrade head

migration:              ## Create new migration
	$(COMPOSE) exec app alembic revision --autogenerate -m "$(msg)"

shell:                  ## Bash inside app container
	$(COMPOSE) exec app bash

db-shell:               ## psql inside postgres container
	$(COMPOSE) exec postgres psql -U ica -d n8n_custom_data
```

**For PHP devs:** The Makefile replaces scripts like `composer test`,
`php artisan migrate`, and Docker wrappers. All commands execute inside
containers — there is no local/bare-metal development path.

### pyproject.toml (Tool Configuration)

```toml
[tool.ruff]
target-version = "py312"
line-length = 99

[tool.ruff.lint]
select = ["E", "F", "I", "N", "UP", "B", "SIM", "RUF"]
```

| Rule | What it checks |
|------|---------------|
| E | PEP 8 style (whitespace, indentation) |
| F | PyFlakes (undefined names, unused imports) |
| I | Import sorting |
| N | Naming conventions |
| UP | Python modernization (use newer syntax) |
| B | Bugbear (common bugs and anti-patterns) |
| SIM | Simplification (unnecessary complexity) |
| RUF | Ruff-specific best practices |

```toml
[tool.mypy]
python_version = "3.12"
strict = true                      # All strict checks enabled
plugins = ["pydantic.mypy"]        # Pydantic-aware type checking
```

`strict = true` enables every mypy strictness flag. Every function must have
full type annotations. Every return type must be specified. No implicit `Any`.

---

## Quick Reference: File Index

### Entry Points
| File | Lines | Purpose |
|------|-------|---------|
| `ica/__main__.py` | 256 | CLI (Typer): serve, run, status, collect-articles |
| `ica/app.py` | 315 | FastAPI factory: /health, /trigger, /status, /scheduler |
| `ica/scheduler.py` | 242 | APScheduler: cron + interval jobs |

### Configuration
| File | Lines | Purpose |
|------|-------|---------|
| `ica/config/settings.py` | 91 | Pydantic Settings: env vars → typed config |
| `ica/config/llm_config.py` | 191 | LLMPurpose enum + 3-tier model resolution |
| `ica/config/validation.py` | 77 | Startup validation: env + timezone + models |

### LLM Configs
| File | Lines | Purpose |
|------|-------|---------|
| `ica/llm_configs/schema.py` | 53 | Pydantic models for JSON config structure |
| `ica/llm_configs/loader.py` | 201 | File-mtime cached config loader + public API |
| `ica/llm_configs/*.json` | 19 files | Per-process model + prompt configs |

### Services
| File | Lines | Purpose |
|------|-------|---------|
| `ica/services/llm.py` | 206 | LiteLLM wrapper: retry, routing, error mapping |
| `ica/services/slack.py` | 584 | Slack Bolt: send_and_wait, forms, modals |
| `ica/services/google_sheets.py` | 241 | Sheets API v4: read/write/clear rows |
| `ica/services/google_docs.py` | 213 | Docs API v1: create/read/write documents |
| `ica/services/google_search.py` | 200 | Google CSE: keyword search + result parsing |
| `ica/services/web_fetcher.py` | 216 | httpx: fetch URLs, strip HTML, detect failures |
| `ica/services/prompt_editor.py` | 215 | Edit LLM prompts via Google Docs |

### Pipeline
| File | Lines | Purpose |
|------|-------|---------|
| `ica/pipeline/orchestrator.py` | 357 | PipelineContext, PipelineStep, run_pipeline |
| `ica/pipeline/steps.py` | 553 | Adapter layer: lazy factories, step wrappers |
| `ica/pipeline/article_curation.py` | 441 | Step 1: DB → Sheet → Slack approval |
| `ica/pipeline/summarization.py` | 1146 | Step 2: HTTP fetch → LLM → feedback loop |
| `ica/pipeline/theme_generation.py` | 249 | Step 3a: generate 2 themes with markers |
| `ica/pipeline/theme_selection.py` | 687 | Step 3b: interactive selection + approval |
| `ica/pipeline/markdown_generation.py` | ~200 | Step 4: 3-layer validation + retry |
| `ica/pipeline/html_generation.py` | ~150 | Step 5: markdown → HTML email |
| `ica/pipeline/alternates_html.py` | 105 | Step 6a: identify unused articles |
| `ica/pipeline/email_subject.py` | ~120 | Step 6b: subject lines + review |
| `ica/pipeline/social_media.py` | ~120 | Step 6c: post concepts + captions |
| `ica/pipeline/linkedin_carousel.py` | ~120 | Step 6d: carousel slides + validation |
| `ica/pipeline/article_collection.py` | 190 | Scheduled article discovery utility |

### Prompts
| File | Lines | Purpose |
|------|-------|---------|
| `ica/prompts/summarization.py` | 141 | Article summary + regeneration |
| `ica/prompts/theme_generation.py` | 70 | Theme generation with markers |
| `ica/prompts/markdown_generation.py` | 140 | Newsletter markdown + regen |
| `ica/prompts/html_generation.py` | 114 | Markdown → HTML + regen |
| `ica/prompts/email_subject.py` | 70 | Subject line generation |
| `ica/prompts/email_review.py` | 70 | Email intro paragraph |
| `ica/prompts/social_media.py` | 132 | Posts → captions → regen |
| `ica/prompts/linkedin_carousel.py` | 90 | Carousel copy + slides |
| `ica/prompts/learning_data_extraction.py` | 55 | Feedback → structured learning |
| `ica/prompts/freshness_check.py` | 42 | Theme freshness |
| `ica/prompts/markdown_structural_validation.py` | 49 | Structural validation |
| `ica/prompts/markdown_voice_validation.py` | 48 | Voice/tone validation |

### Database
| File | Lines | Purpose |
|------|-------|---------|
| `ica/db/models.py` | 109 | SQLAlchemy 2.0: Article, Theme, Note |
| `ica/db/session.py` | 67 | Async session factory + context manager |
| `ica/db/crud.py` | 183 | Upserts, queries, note storage |
| `ica/db/repository.py` | 24 | SqlArticleRepository (Protocol impl) |

### Utilities & Validators
| File | Lines | Purpose |
|------|-------|---------|
| `ica/utils/marker_parser.py` | 318 | %XX_ marker extraction → dataclasses |
| `ica/utils/output_router.py` | 118 | 3-way conditional routing |
| `ica/utils/boolean_normalizer.py` | 42 | "yes" → True coercion |
| `ica/utils/date_parser.py` | 97 | Relative + MM/DD/YYYY parsing |
| `ica/validators/character_count.py` | 251 | Section character count validation |

### Error Handling & Logging
| File | Lines | Purpose |
|------|-------|---------|
| `ica/errors.py` | 282 | Exception hierarchy + Slack notification |
| `ica/logging.py` | 259 | Structured logging + async context vars |
