# ICA Technical Breakdown: Services & Integrations

This document covers the external service clients, LLM configuration system, and utility modules.

---

## LLM Service (`ica/services/llm.py`)

Unified wrapper around LiteLLM providing model routing, retry with exponential backoff, and structured error handling.

### LLMResponse (frozen dataclass)

```python
@dataclass(frozen=True)
class LLMResponse:
    text: str                          # extracted and stripped from API response
    model: str                         # model identifier used
    purpose: LLMPurpose | None = None  # if provided
    usage: dict[str, int] | None = None  # token counts (prompt_tokens, completion_tokens, total_tokens)
```

### completion()

```python
async def completion(
    *,
    purpose: LLMPurpose | None = None,
    model: str | None = None,           # overrides purpose-based resolution
    system_prompt: str,
    user_prompt: str,
    max_retries: int = 3,
    retry_base_delay: float = 1.0,
    retry_max_delay: float = 30.0,
    step: str = "LLM",                  # for error attribution
    **litellm_kwargs: Any,              # temperature, max_tokens, etc.
) -> LLMResponse
```

**Model resolution**: Explicit `model` param wins. Otherwise calls `get_model(purpose)` for 3-tier resolution. If neither provided, raises `ValueError`.

**Retry logic**: Exponential backoff `delay = min(base * 2^attempt, max_delay)`. Retryable errors: `RateLimitError`, `ServiceUnavailableError`, `Timeout`, `InternalServerError`, `APIConnectionError`. Non-retryable exceptions re-raised immediately.

**Error handling**: Empty response → `LLMError`. All unexpected exceptions wrapped in `LLMError` with step context.

---

## Slack Service (`ica/services/slack.py`)

Human-in-the-loop engine implementing the n8n `sendAndWait` blocking pattern for approvals, forms, and freetext feedback.

### Core Concept: sendAndWait

The fundamental interaction pattern, used by every content step:

1. Generate unique `callback_id` (UUID hex)
2. Create `_PendingInteraction` with `asyncio.Event`
3. Store in `self._pending[callback_id]`
4. Post Slack message with button (callback_id embedded in action_id)
5. **Await `pending.event.wait()`** — blocks the coroutine
6. User clicks button → Slack Bolt routes to handler → `pending.event.set()`
7. Coroutine resumes, pending entry cleaned up in `finally` block

For forms/freetext: button click opens a modal; modal submission triggers `_handle_view_submission()` which sets the event.

### Public API

| Method | Returns | Pattern |
|---|---|---|
| `send_message(channel, text)` | None | Plain-text post. Satisfies `SlackNotifier` protocol |
| `send_channel_message(text, *, blocks=None)` | None | Message + Block Kit to default channel |
| `send_error(message)` | None | Error notification. Satisfies `SlackErrorNotifier` protocol |
| `send_and_wait(channel, text, *, approve_label)` | None | Post approval button, block until clicked |
| `send_and_wait_form(message, *, form_fields, button_label, form_title, form_description)` | `dict[str, str]` | Post form trigger, block until modal submitted. Returns field label → value mapping |
| `send_and_wait_freetext(message, *, button_label, form_title, form_description)` | `str` | Post freetext trigger, block until text submitted |
| `register_handlers(bolt_app)` | None | Register Slack Bolt action/view handlers (called once at startup) |

### Block Kit Abstractions

**Approval blocks**: Text section + primary-style button with action_id `ica_approve_{callback_id}`

**Trigger blocks**: Text section + button with action_id `ica_trigger_{callback_id}`

**Form modal**: Input blocks per field. Supports:
- `text` — single-line `plain_text_input`
- `textarea` — multiline `plain_text_input`
- `dropdown` — `static_select` with options from `fieldOptions`

Block IDs: `field_0`, `field_1`, etc.

**Freetext modal**: Optional description + single multiline input.

### n8n Form Field Spec

```python
{
    "fieldLabel": str,           # displayed label
    "fieldType": str,            # "dropdown" | "text" | "textarea"
    "fieldOptions": list[dict],  # for dropdowns: [{"option": "value"}, ...]
    "requiredField": bool        # default True
}
```

### Constraints

- Modal title capped at 24 chars (Slack API limitation)
- Action IDs use regex matching via `re.compile()`
- Stale callback_ids logged as warnings (no crash)

---

## Google Sheets Service (`ica/services/google_sheets.py`)

Async wrapper around Google Sheets API v4.

### Methods

| Method | Signature | Notes |
|---|---|---|
| `__init__` | `(credentials_path=None, *, service=None)` | Load JSON key file OR accept pre-built service (testing) |
| `clear_sheet` | `(spreadsheet_id, sheet_name) -> None` | Clears range "SheetName!A:Z" |
| `append_rows` | `(spreadsheet_id, sheet_name, rows: list[dict]) -> int` | First row = headers. Returns data row count |
| `read_rows` | `(spreadsheet_id, sheet_name) -> list[dict[str, str]]` | First row = headers, rest mapped to dicts. Missing cells padded with "" |

### Threading Model

Google API client is synchronous. All API calls wrapped in `asyncio.to_thread()` to avoid blocking the event loop. Credentials loaded synchronously at init.

### Scopes

`["https://www.googleapis.com/auth/spreadsheets"]`

---

## Google Docs Service (`ica/services/google_docs.py`)

Async wrapper around Google Docs API v1.

### Methods

| Method | Signature | Notes |
|---|---|---|
| `__init__` | `(credentials_path=None, *, service=None)` | Same pattern as Sheets |
| `create_document` | `(title) -> str` | Returns `documentId` |
| `insert_content` | `(document_id, text) -> None` | Inserts at position 1 (beginning). No-op if empty |
| `get_content` | `(document_id) -> str` | Traverses `body.content[].paragraph.elements[].textRun.content` |

### Text Extraction

`_extract_text(document)` traverses the nested Google Docs structure:
```
document.body.content[].paragraph.elements[].textRun.content
```
Concatenates all text runs into a single string.

### Scopes

`["https://www.googleapis.com/auth/documents", "https://www.googleapis.com/auth/drive.file"]`

---

## Google Custom Search Service (`ica/services/google_search.py`)

Client for the [Google Custom Search JSON API](https://developers.google.com/custom-search/v1/overview) for article discovery.

### SearchResult (frozen dataclass)

```python
@dataclass(frozen=True)
class SearchResult:
    url: str
    title: str
    date: str | None   # ISO-8601 from page metatags (article:published_time, og:updated_time, etc.)
    origin: str        # "daily" | "every_2_days"
```

### HttpClient Protocol

```python
class HttpClient(Protocol):
    async def get(self, url: str, *, params: dict[str, Any]) -> dict[str, Any]: ...
```

Dependency injection point — `WebFetcherService` implements this in production; tests use mocks.

### GoogleSearchClient

```python
@dataclass
class GoogleSearchClient:
    api_key: str          # GOOGLE_CSE_API_KEY
    cx: str               # GOOGLE_CSE_CX (Search Engine ID)
    http_client: HttpClient
    base_url: str = "https://www.googleapis.com/customsearch/v1"
```

### Methods

| Method | Purpose |
|---|---|
| `search(keyword, *, num, date_restrict, gl, sort_by_date)` | Single keyword query. Auto-paginates when `num` > 10. Parses `items[].{link, title}` + date from `pagemap.metatags` |
| `search_keywords(keywords, *, num, date_restrict, gl, sort_by_date)` | Multiple keywords sequential, aggregates results |

### Date Extraction

Dates are extracted from `item.pagemap.metatags[0]` using these meta tag keys (in priority order): `article:published_time`, `og:updated_time`, `date`, `publishdate`, `datePublished`, `dc.date`.

### Search Schedules

| Schedule | Mode | Keywords | Results Per Keyword |
|---|---|---|---|
| Daily | `sort_by_date=True` | 3 broad (AGI, Automation, AI) | 10 |
| Every 2 days | `sort_by_date=False` (relevance) | 5 specific (AI breakthrough, AI latest, etc.) | 10 |

### Pricing

100 free queries/day (we use ~8). Additional queries cost $5/1,000 if billing is enabled.

---

## Web Fetcher Service (`ica/services/web_fetcher.py`)

Async HTTP client for fetching article page content.

### FetchResult (frozen dataclass)

```python
@dataclass(frozen=True)
class FetchResult:
    content: str | None  # HTML on success, None on failure
    error: str | None    # None on success, description on failure
```

### Failure Detection

```python
def is_fetch_failure(result: FetchResult, url: str) -> bool:
    # True if ANY of:
    # 1. result.error is not None (HTTP error)
    # 2. result.content contains "sgcaptcha" (captcha challenge)
    # 3. URL contains "youtube.com"
```

### HTML Stripping

`strip_html_tags(html) -> str`:
1. Remove `<script>` and `<style>` elements entirely
2. Replace block tags (`p`, `div`, `h1-6`, `li`, `tr`) with newlines
3. Replace `<br/>` with newline
4. Strip all remaining tags
5. Unescape HTML entities
6. Normalize whitespace (collapse spaces, preserve newlines, collapse blank lines)

### WebFetcherService

| Method | Notes |
|---|---|
| `__init__(client=None, *, timeout=30.0)` | Creates `httpx.AsyncClient` if not provided. Tracks ownership for `close()` |
| `get(url, *, headers=None) -> FetchResult` | GET with browser-like headers. Catches all httpx exceptions → returns as `error` string, never raises |
| `close()` | Closes client if owned |
| `__aenter__/__aexit__` | Context manager |

Browser headers include User-Agent (Safari), Accept, Accept-Language, Referer (google.com), Connection.

httpx config: `follow_redirects=True`, configurable timeout.

---

## LLM Configuration System

Three modules work together for model and prompt management.

### LLMPurpose Enum & LLMConfig (`ica/config/llm_config.py`)

**LLMPurpose** (StrEnum, 21 variants) — each value is the field name on `LLMConfig`:

| Purpose | Field Name | Default Model |
|---|---|---|
| `SUMMARY` | `llm_summary_model` | `anthropic/claude-sonnet-4.5` |
| `SUMMARY_REGENERATION` | `llm_summary_regeneration_model` | `anthropic/claude-sonnet-4.5` |
| `SUMMARY_LEARNING_DATA` | `llm_summary_learning_data_model` | `anthropic/claude-sonnet-4.5` |
| `MARKDOWN` | `llm_markdown_model` | `anthropic/claude-sonnet-4.5` |
| `MARKDOWN_VALIDATOR` | `llm_markdown_validator_model` | `openai/gpt-4.1` |
| `MARKDOWN_REGENERATION` | `llm_markdown_regeneration_model` | `anthropic/claude-sonnet-4.5` |
| `MARKDOWN_LEARNING_DATA` | `llm_markdown_learning_data_model` | `anthropic/claude-sonnet-4.5` |
| `HTML` | `llm_html_model` | `anthropic/claude-sonnet-4.5` |
| `HTML_REGENERATION` | `llm_html_regeneration_model` | `anthropic/claude-sonnet-4.5` |
| `HTML_LEARNING_DATA` | `llm_html_learning_data_model` | `anthropic/claude-sonnet-4.5` |
| `THEME` | `llm_theme_model` | `anthropic/claude-sonnet-4.5` |
| `THEME_LEARNING_DATA` | `llm_theme_learning_data_model` | `anthropic/claude-sonnet-4.5` |
| `THEME_FRESHNESS_CHECK` | `llm_theme_freshness_check_model` | `google/gemini-2.5-flash` |
| `SOCIAL_MEDIA` | `llm_social_media_model` | `anthropic/claude-sonnet-4.5` |
| `SOCIAL_POST_CAPTION` | `llm_social_post_caption_model` | `anthropic/claude-sonnet-4.5` |
| `SOCIAL_MEDIA_REGENERATION` | `llm_social_media_regeneration_model` | `anthropic/claude-sonnet-4.5` |
| `LINKEDIN` | `llm_linkedin_model` | `anthropic/claude-sonnet-4.5` |
| `LINKEDIN_REGENERATION` | `llm_linkedin_regeneration_model` | `anthropic/claude-sonnet-4.5` |
| `EMAIL_SUBJECT` | `llm_email_subject_model` | `anthropic/claude-sonnet-4.5` |
| `EMAIL_SUBJECT_REGENERATION` | `llm_email_subject_regeneration_model` | `anthropic/claude-sonnet-4.5` |
| `EMAIL_PREVIEW` | `llm_email_preview_model` | `anthropic/claude-sonnet-4.5` |

**LLMConfig** is a Pydantic `BaseSettings` — each field maps to an env var (e.g., `LLM_SUMMARY_MODEL`).

### 3-Tier Model Resolution (`get_model`)

```
Priority 1: Environment variable override (field value != class default)
Priority 2: JSON config file (ica/llm_configs/{process}-llm.json → config.model)
Priority 3: Hardcoded class default on LLMConfig
```

`_PURPOSE_TO_PROCESS` maps 18 of 21 `LLMPurpose` field names to JSON process names (kebab-case). Three learning-data purposes have no JSON config and fall back to env/default.

### JSON Config Schema (`ica/llm_configs/schema.py`)

```python
class ProcessConfig(BaseModel):
    schema_version: str = Field(alias="$schema")       # "ica-llm-config/v1"
    process_name: str = Field(alias="processName")      # e.g., "summarization"
    description: str = ""
    model: str = Field(min_length=1)                    # e.g., "anthropic/claude-sonnet-4.5"
    prompts: Prompts                                    # system + instruction (both required, non-empty)
    metadata: Metadata = Field(default_factory=Metadata)  # googleDocId, lastSyncedAt, version

class Prompts(BaseModel):
    system: str = Field(min_length=1)
    instruction: str = Field(min_length=1)

class Metadata(BaseModel):
    google_doc_id: str | None = Field(default=None, alias="googleDocId")
    last_synced_at: str | None = Field(default=None, alias="lastSyncedAt")
    version: int = Field(default=1, ge=1)
```

Alias strategy: camelCase in JSON, snake_case in Python. `populate_by_name=True` accepts both.

### JSON Config Loader (`ica/llm_configs/loader.py`)

| Function | Purpose |
|---|---|
| `load_process_config(process_name)` | Loads `{process_name}-llm.json`, validates via Pydantic, caches with file-mtime invalidation |
| `get_process_model(process_name)` | Resolves model: env var override → JSON config → default |
| `get_process_prompts(process_name)` | Returns `(system_prompt, instruction_prompt)` tuple |

**Cache**: Module-level dict `_cache: dict[str, tuple[float, ProcessConfig]]`. Key = process name, value = (mtime, config). On load: check mtime → return cached if unchanged → otherwise reload and re-validate.

19 JSON config files exist in `ica/llm_configs/`, one per process.

---

## Utility Modules

### Marker Parser (`ica/utils/marker_parser.py`)

Parses structured `%XX_FIELD:` markers from LLM theme-generation output.

**Marker prefixes and their dataclasses:**

| Prefix | Dataclass | Fields |
|---|---|---|
| `%FA_` | `FeaturedArticle` | title, source, origin, url, category, why_featured |
| `%M1_`, `%M2_` | `MainArticle` | title, source, origin, url, category, rationale |
| `%Q1_`, `%Q2_`, `%Q3_` | `QuickHit` | title, source, origin, url, category |
| `%I1_`, `%I2_` | `IndustryDevelopment` | title, source, origin, url, major_ai_player |
| `%RV_` | `RequirementsVerified` | distribution_achieved, source_mix, technical_complexity, major_ai_player_coverage |

**`FormattedTheme`** aggregates all article slots + theme name into one structured object.

**Key functions:**

- `split_themes(raw_output) -> ThemeParseResult` — Splits on `"-----"` delimiter. Blocks with `"RECOMMENDATION:"` become the recommendation field. Others become `ParsedThemeBlock` entries (extracts `THEME:` and `Theme Description:`).

- `parse_markers(theme_body, theme_title=None) -> FormattedTheme` — For each prefix, regex-searches for `%PREFIX_FIELD:\s*(.+)` and assembles the structured result.

### Output Router (`ica/utils/output_router.py`)

Routes between original and regenerated content based on user feedback.

**UserChoice** enum: `YES`, `PROVIDE_FEEDBACK`, `RESTART`

**`conditional_output_router(switch_value, original_text, re_generated_text, content_valid) -> RouterResult`**:

| Condition | text | feedback |
|---|---|---|
| Unrecognized switch | original | original |
| Regen available + valid | regen | regen |
| Regen available + invalid | original | regen (stored for learning) |
| No regen | original | original |
| RESTART choice | (selected) | (selected, stored for learning) |

### Boolean Normalizer (`ica/utils/boolean_normalizer.py`)

`normalize_boolean(value) -> bool` — Converts Google Sheets cell values:
- `"yes"` (case-insensitive) → `True`
- Everything else (`"no"`, `"true"`, `""`, `None`) → `False`
- `bool` passthrough

Mirrors n8n expression: `$json.approved.toString().toLowerCase() === 'yes'`

### Date Parser (`ica/utils/date_parser.py`)

| Function | Input | Output |
|---|---|---|
| `parse_relative_date(date_string, *, reference=None)` | `"3 days ago"`, `"1 week ago"` | `date` (reference - timedelta). Hours/minutes return reference (no sub-day precision) |
| `parse_date_mmddyyyy(date_string)` | `"12/25/2024"` | `date \| None` |
| `format_date_mmddyyyy(d)` | `date` | `"MM/DD/YYYY"` string |

Relative date regex: `(\d+)\s*(day|days|week|weeks|hour|hours|minute|minutes)\s*ago`

---

## Service Dependency Map

```
Pipeline Steps
├── LLM Service (llm.py)
│   ├── uses: LLMPurpose enum (llm_config.py)
│   ├── calls: get_model() for 3-tier resolution
│   └── wraps: litellm.acompletion()
│
├── Slack Service (slack.py)
│   ├── wraps: AsyncWebClient (slack_sdk)
│   ├── uses: asyncio.Event for sendAndWait
│   └── satisfies: SlackNotifier, SlackApprovalSender, SlackErrorNotifier protocols
│
├── Google Sheets Service (google_sheets.py)
│   ├── wraps: google-api-python-client (sync, via asyncio.to_thread)
│   └── satisfies: SheetReader, SheetWriter protocols
│
├── Google Docs Service (google_docs.py)
│   ├── wraps: google-api-python-client (sync, via asyncio.to_thread)
│   └── satisfies: GoogleDocsWriter protocol
│
├── Google Search Client (google_search.py)
│   ├── depends on: HttpClient protocol (implemented by WebFetcherService)
│   └── returns: list[SearchResult]
│
└── Web Fetcher Service (web_fetcher.py)
    ├── wraps: httpx.AsyncClient
    ├── implements: HttpClient protocol
    └── satisfies: HttpFetcher protocol

LLM Config Resolution
├── llm_config.py: LLMPurpose → LLMConfig field → env var check
├── loader.py: process name → JSON file → ProcessConfig → model/prompts
└── schema.py: Pydantic validation of JSON structure
```

### Testing Patterns

- **Dependency injection**: All services accept optional `client`/`service` in `__init__` for test mocks
- **Protocols**: `HttpClient`, `SlackNotifier`, `SlackApprovalSender`, `SheetReader`, `SheetWriter`, etc.
- **Frozen dataclasses**: `SearchResult`, `FetchResult`, `LLMResponse` for immutability
- **Async-first**: All methods are `async def`, Google API calls wrapped in `asyncio.to_thread()`
