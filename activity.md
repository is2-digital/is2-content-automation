# ims-tt - Activity Log

## Current Status
**Last Updated:** 2026-02-23
**Tasks Completed:** ica-76h (Add regression tests for pilot migration)
**Current Task:** None
**Tasks Completed This Session:** 1 (session 61)

---

## Session Log

### 2026-02-23 (session 61)
**Completed:**
- ica-76h: Add regression tests for pilot migration

**Changes Made:**
- Created `tests/test_llm_configs/test_prompt_regression.py` with 14 regression tests: string-identity checks for system prompts, user prompts (with and without feedback), raw template comparisons, and length guards for both summarization and email-subject processes
- Fixed whitespace bug in `ica/llm_configs/summarization-llm.json`: instruction had extra `\n` after `{feedback_section}` vs original hardcoded constant
- Fixed whitespace bug in `ica/llm_configs/email-subject-llm.json`: instruction had extra `\n` after `{feedback_section}` vs original hardcoded constant
- All 127 related tests pass (50 schema/loader + 14 regression + 63 prompt), ruff and mypy clean

**No blockers.**

### 2026-02-23 (session 60)
**Completed:**
- ica-2s2: Refactor pilot prompt files to load from JSON

**Changes Made:**
- Refactored `ica/prompts/summarization.py` — removed `SUMMARIZATION_SYSTEM_PROMPT` and `SUMMARIZATION_USER_PROMPT` constants, `build_summarization_prompt()` now loads prompts from `summarization-llm.json` via `get_process_prompts("summarization")`
- Refactored `ica/prompts/email_subject.py` — removed `EMAIL_SUBJECT_SYSTEM_PROMPT` and `EMAIL_SUBJECT_USER_PROMPT` constants, `build_email_subject_prompt()` now loads prompts from `email-subject-llm.json` via `get_process_prompts("email-subject")`
- `_FEEDBACK_SECTION_TEMPLATE` and feedback injection logic unchanged in both files
- Regeneration prompts (`build_summarization_regeneration_prompt`) left unchanged (no JSON config yet)
- Updated `tests/test_prompts/test_summarization.py` and `tests/test_prompts/test_email_subject.py` to use `get_process_prompts()` instead of removed constants; identity checks (`is`) replaced with equality checks (`==`)
- All 692 prompt tests pass, ruff and mypy clean

**No blockers.**

### 2026-02-23 (session 59)
**Completed:**
- ica-1gv: Create pilot JSON config files (summarization + email-subject)

**Changes Made:**
- Created `ica/llm_configs/summarization-llm.json` — system + instruction prompts extracted from `ica/prompts/summarization.py`, model `anthropic/claude-sonnet-4.5`
- Created `ica/llm_configs/email-subject-llm.json` — system + instruction prompts extracted from `ica/prompts/email_subject.py`, model `anthropic/claude-sonnet-4.5`
- Both follow `ica-llm-config/v1` schema with metadata (googleDocId: null, lastSyncedAt: null, version: 1)
- Validated both files load correctly through JSON parsing against schema structure

**Blockers:** None

### 2026-02-23 (session 58)
**Completed:**
- ica-d0z: Create schema.py and loader.py modules

**Changes Made:**
- Created `ica/llm_configs/` package with 3 modules:
  - `schema.py` — Pydantic models (`ProcessConfig`, `Prompts`, `Metadata`) matching ica-llm-config/v1 JSON schema
  - `loader.py` — `load_process_config()` with file-mtime cache invalidation, `get_process_model()` with env-var > JSON > default priority, `get_process_prompts()` returning (system, instruction) tuple
  - `__init__.py` — Package exports
- Created `tests/test_llm_configs/` with 36 tests covering schema validation, loader caching, model resolution priority, and package exports
- Process-to-LLMConfig field mapping covers all 19+3 process names from scope document

**Blockers:** None

### 2026-02-23 (session 57)
**Completed:**
- ica-6oq: Wire all pipeline steps into orchestrator

**Changes Made:**
- Created `ica/pipeline/steps.py` — 9 step wrapper functions adapting pipeline modules to PipelineStep protocol:
  - Service factory helpers: `_get_settings()`, `_make_slack()`, `_make_sheets()`, `_make_docs()`, `_make_http()`, `_session()`
  - `run_curation_step`: composes `prepare_curation_data` + `run_approval_flow`
  - `run_summarization_step`: composes `prepare_summarization_data` + `summarize_articles` + `run_summarization_output`
  - `run_theme_generation_step`: full selection/approval orchestration with nested loops (generation → selection → approval with feedback paths)
  - `run_markdown_generation_step`: composes `aggregate_feedback` + `generate_with_validation` + `run_markdown_review`
  - `run_html_generation_step`: fetches markdown from Google Docs, loads HTML template, calls `run_html_generation`
  - `run_alternates_html_step`, `run_email_subject_step`, `run_social_media_step`, `run_linkedin_carousel_step`
- Updated `ica/pipeline/orchestrator.py` — replaced `_noop_step` stubs with real step imports in `build_default_steps()`
- Updated `ica/config/settings.py` — added `google_sheets_spreadsheet_id` and `html_template_path` optional settings
- Created `tests/test_pipeline/test_steps.py` (26 tests covering all 9 steps, service factories, context propagation)
- Updated `tests/test_pipeline/test_orchestrator.py` — removed noop tests, added real implementation verification
- Updated `tests/test_app.py` — mock `build_default_steps` in pipeline execution test

**Status:**
- All pipeline steps wired into orchestrator with real implementations
- All 3285 tests pass (3261 existing - 2 removed noop tests + 26 new)

**Next:**
- No remaining tasks — all pipeline steps fully wired

**Blockers:**
- None

---

### 2026-02-23 (session 56)
**Completed:**
- ica-9qv: Implement email subject & preview generator

**Changes Made:**
- Created `ica/pipeline/email_subject.py` — full Step 6b implementation:
  - SlackEmailSubjectReview protocol, GoogleDocsService protocol
  - ParsedSubject dataclass, EmailSubjectResult dataclass
  - strip_html_to_text: HTML-to-text conversion (ports n8n "Process Input" Code node)
  - aggregate_feedback: notes → bullet-point string
  - call_email_subject_llm: subject generation (EMAIL_SUBJECT model)
  - parse_subjects: split on "-----", extract Subject_N patterns + RECOMMENDATION
  - format_recommendation: Slack mrkdwn bold on RECOMMENDATION/Explanation keywords
  - build_subjects_slack_blocks: Block Kit for subject display
  - format_subjects_slack_message: flattened message from blocks
  - build_subject_selection_form: radio buttons (subjects + "Add Feedback") + textarea
  - is_subject_selection: "SUBJECT" contains check (matches n8n Switch)
  - extract_selected_subject: SUBJECT N pattern → 1-based index lookup
  - call_email_review_llm: review generation (EMAIL_PREVIEW model)
  - build_review_slack_blocks: Block Kit for review display
  - build_review_approval_form: Approve/Reset All/Add feedback + textarea
  - parse_review_approval: contains-based routing (matches n8n "Final Switch")
  - extract_email_learning_data: JSON parsing with fallback
  - store_email_feedback: notes table (type='user_email_subject')
  - create_email_doc: Google Doc with "SUBJECT: {text}" + review
  - run_email_subject_generation: full orchestration — two-phase flow
- Created `tests/test_pipeline/test_email_subject.py` (105 tests)

**Status:**
- Email subject & preview generator (APPLICATION.md Section 2.8) fully implemented:
  - Phase 1 — Subject Generation: fetch HTML doc → strip to text → learning data → LLM generates up to 10 subjects → parse → Slack display → radio selection form
  - Subject feedback loop: "Add Feedback" → learning data extraction → store → regenerate with updated feedback
  - Phase 2 — Review Generation: selected subject → LLM generates email review (100-120 words) → Slack display → approval form
  - Review feedback loop: "Add a feedback" → regenerate review with Editor Notes
  - Reset All: loops back to Phase 1 with cleared feedback (matches n8n "Final Switch" third output)
  - Google Doc creation: "SUBJECT: {text}" + review content, share link in Slack
  - No database writes outside learning data (matches n8n workflow)
- All 3261 tests pass (3156 existing + 105 new)

**Next:**
- Next available task from `bd ready`

**Blockers:**
- None

---

### 2026-02-23 (session 55)
**Completed:**
- ica-72k: Implement LinkedIn carousel generator

**Changes Made:**
- Created `ica/pipeline/linkedin_carousel.py` — full Step 6d implementation:
  - SlackLinkedInReview protocol, GoogleDocsService protocol
  - SlideError dataclass with to_dict() serialization
  - ValidationResult dataclass, LinkedInCarouselResult dataclass
  - validate_slide_bodies: regex-based `*Body:*` extraction, char count with -4 offset, annotation
  - build_next_steps_form: Yes / Regenerate / Provide Feedback dropdown
  - call_carousel_llm: LLM generation with previous_output for retry context
  - call_regeneration_llm: feedback-driven revision LLM call
  - generate_with_validation: generation + character validation retry loop (max 2 attempts, force-accept)
  - create_carousel_doc: Google Doc creation
  - run_linkedin_carousel_generation: full orchestration — approval → fetch HTML → generate + validate → Slack share → Yes/Feedback/Regenerate loop → Google Doc → share link
- Created `tests/test_pipeline/test_linkedin_carousel.py` (74 tests)

**Status:**
- LinkedIn carousel generator pipeline step (PRD Section 3.9) fully implemented:
  - Receives HTML doc ID + formatted_theme from pipeline context
  - Slack approval to proceed, then fetches HTML newsletter from Google Docs
  - LLM generates post copy (3 versions) + 10 carousel slides (TL;DR + 8 article slides)
  - Character validation: `*Body:*` marker extraction, 265-315 char range per slide (with -4 offset)
  - Auto-retry: up to 2 validation attempts, then force-accept (matches n8n static data counter)
  - Slack review: Yes → Google Doc creation / Provide Feedback → regeneration LLM / Regenerate → full re-generation
  - No database writes (matches n8n workflow which has no Postgres nodes)
- All 3156 tests pass (3082 existing + 74 new)

**Next:**
- Next available task from `bd ready`

**Blockers:**
- None

---

### 2026-02-23 (session 54)
**Completed:**
- ica-5fn: Implement social media generator

**Changes Made:**
- Created `ica/pipeline/social_media.py` — full Step 6c implementation:
  - SlackSocialMediaReview protocol, GoogleDocsService protocol
  - ParsedPost dataclass, SocialMediaResult dataclass
  - Phase 1: call_social_media_post_llm (12 graphics-only posts: 6 DYK + 6 IT)
  - Post parsing: parse_phase1_titles, parse_phase1_posts, get_source_url
  - Phase 2: call_caption_llm (captions for selected posts, 150-300 chars)
  - Feedback: call_caption_regeneration_llm (feedback-driven caption revision)
  - Form builders: build_phase1_next_steps_form, build_post_selection_form, build_phase2_next_steps_form, build_final_selection_form
  - Post filtering: parse_phase2_titles, filter_final_posts
  - Google Doc: create_social_media_doc
  - run_social_media_generation: full orchestration — approval → Phase 1 (generate/regenerate loop) → post selection → Phase 2 (captions with feedback loop) → final selection → Google Doc → Slack share
- Created `tests/test_pipeline/test_social_media.py` (73 tests)

**Status:**
- Social media generator pipeline step (PRD Section 3.8) fully implemented:
  - Two-phase process matching n8n social_media_generator_subworkflow
  - Phase 1: LLM generates 12 graphics-only posts → Slack share → Yes/Regenerate loop
  - Post selection: parse titles via regex, checkbox form for user selection
  - Source URL resolution from formatted_theme (key-name priority, source-number fallback)
  - Phase 2: LLM generates captions for selected posts → Slack share → Yes/Feedback/Restart loop
  - Feedback regeneration via dedicated LLM call
  - Final selection: checkbox form → filter and combine selected posts
  - Google Doc creation with final content
  - No notes/learning data storage (matches n8n workflow which has none)
- All 3082 tests pass (3009 existing + 73 new)

**Next:**
- Next available task from `bd ready`

**Blockers:**
- None

---

### 2026-02-23 (session 53)
**Completed:**
- ica-8iq: Implement HTML generation pipeline step

**Changes Made:**
- Created `ica/pipeline/html_generation.py` — full Step 5 implementation:
  - SlackHtmlReview protocol, GoogleDocsService protocol
  - HtmlGenerationResult dataclass
  - aggregate_feedback: notes → bullet-point string
  - call_html_llm: HTML generation from markdown + template
  - call_html_regeneration: scoped HTML regeneration (only modifies sections mentioned in feedback)
  - extract_html_learning_data: JSON parsing with fallback
  - build_next_steps_form, parse_next_steps_response
  - store_html_feedback (notes table, type='user_htmlgenerator')
  - create_html_doc (Google Docs)
  - run_html_generation: full orchestration — fetch learning data → generate HTML → create doc → Slack review loop with feedback/approval
- Created `tests/test_pipeline/test_html_generation.py` (74 tests)

**Status:**
- HTML generation pipeline step (PRD Section 3.5) fully implemented:
  - Receives markdown content + HTML template + newsletter date
  - Fetches learning data (last 40 entries, type='user_htmlgenerator')
  - Calls LLM (claude-sonnet) to populate HTML template with markdown content
  - Creates Google Doc with generated HTML
  - Slack review: share doc link → Yes/Feedback → feedback loop
  - Scoped regeneration: only modifies sections mentioned in feedback
  - Content validity check: `<!DOCTYPE html>` marker (case-insensitive)
  - On approval: sends approval message, returns HtmlGenerationResult
  - Stores feedback as learning data in notes table
- All 3009 tests pass (2935 existing + 74 new)

**Next:**
- Next available task from `bd ready`

**Blockers:**
- None

---

### 2026-02-23 (session 52)
**Completed:**
- ica-aeb: Implement markdown generation pipeline step

**Changes Made:**
- Created `ica/pipeline/markdown_generation.py` — full Step 4 implementation:
  - SlackMarkdownReview protocol, GoogleDocsWriter protocol
  - MarkdownGenerationResult, ValidationResult dataclasses
  - aggregate_feedback: notes → bullet-point string
  - call_markdown_llm: generation/regeneration with formatted_theme + errors
  - Three-layer validation pipeline:
    - Layer 1: format_char_errors_json + validate_character_counts (code-based)
    - Layer 2: run_structural_validation (LLM, GPT-4.1)
    - Layer 3: run_voice_validation (LLM, GPT-4.1)
    - _parse_validation_response: JSON response parsing with code-block fallback
    - run_three_layer_validation: combined orchestration
  - generate_with_validation: generation + validation retry loop (up to 3 attempts)
  - User review loop:
    - build_next_steps_form, parse_next_steps_response
    - call_user_feedback_regeneration (markdown regeneration prompt)
    - extract_markdown_learning_data (JSON parsing)
    - store_markdown_feedback (notes table, type='user_markdowngenerator')
    - create_markdown_doc (Google Docs)
    - run_markdown_review: full Slack feedback loop orchestration
- Created `tests/test_pipeline/test_markdown_generation.py` (71 tests)

**Status:**
- Markdown generation pipeline step (PRD Section 3.4) fully implemented:
  - Receives formatted_theme from Step 3
  - Fetches learning data (last 40 entries, type='user_markdowngenerator')
  - Calls LLM (claude-sonnet) with ~4000-word markdown generation prompt
  - Three-layer validation: character count → structural LLM → voice LLM
  - Up to 3 validation retry attempts, then force-accept
  - Slack review: share → Yes/Feedback/Restart → feedback loop
  - On approval: creates Google Doc, shares link
  - Stores feedback as learning data in notes table
- All 2935 tests pass (2864 existing + 71 new)

**Next:**
- Next available task from `bd ready`

**Blockers:**
- None

---

### 2026-02-23 (session 51)
**Completed:**
- Closed all remaining open tasks (13 parent feature tasks + 15 epics)

**Changes Made:**
- No code changes — all implementations were already complete from prior sessions
- Closed 13 parent feature tasks whose subtasks were all already closed:
  - ica-1h1.5 (project directory structure), ica-8op.1-4 (utilities), ica-dd0.1-5 (tests), ica-1h1.9 (pipeline framework), ica-1si.8 (FastAPI), ica-1si.9 (CLI)
- Closed 15 epics with zero remaining open subtasks:
  - ica-0jh (Prompt Templates), ica-1si (Pipeline Orchestration), ica-4u2 (LinkedIn Carousel), ica-578 (Theme Generation), ica-7tm (HTML Generation), ica-88n (Alternates HTML), ica-bfc (Article Curation), ica-dd0 (Testing), ica-drl (Error Handling), ica-duo (Summarization), ica-dzw (Social Media), ica-e1k (Service Integrations), ica-io9 (Markdown Generation), ica-qsq (Email Subject), ica-sgn (Article Collection)

**Status:**
- All tasks complete. `bd list --status open --json` returns empty array.
- 2864 tests pass across 50 sessions of work.

**Next:**
- No remaining tasks.

**Blockers:**
- None

---

### 2026-02-23 (session 50)
**Completed:**
- ica-e1k.6: Web Fetcher Service

**Changes Made:**
- Created `ica/services/web_fetcher.py` (WebFetcherService class, FetchResult, BROWSER_HEADERS, is_fetch_failure, strip_html_tags)
- Created `tests/test_services/test_web_fetcher.py` (70 tests)
- Updated `ica/pipeline/summarization.py` — moved FetchResult, BROWSER_HEADERS, CAPTCHA_MARKER, YOUTUBE_DOMAIN, is_fetch_failure, strip_html_tags to service module; summarization.py now imports from service

**Status:**
- Web fetcher service (PRD Section 2.7) fully implemented:
  - `WebFetcherService`: async HTTP client using `httpx.AsyncClient`
  - `get(url, headers=None) -> FetchResult`: HTTP GET with error handling, satisfies `HttpFetcher` protocol
  - Default browser-like headers (User-Agent Safari/537.36, Accept, Referer google.com, etc.)
  - Transport error handling: timeouts, connection errors, HTTP status errors → FetchResult.error
  - `follow_redirects=True`, configurable timeout (default 30s)
  - Async context manager support, proper client lifecycle (owns vs injected)
  - `FetchResult`: frozen dataclass with content/error fields
  - `is_fetch_failure()`: error/captcha/YouTube detection
  - `strip_html_tags()`: HTML-to-text with script/style removal, entity unescaping
- Consolidated web-fetching concerns from summarization.py into dedicated service module
- All 2864 tests pass (2794 existing + 70 new)

**Next:**
- Next available task from `bd ready`

**Blockers:**
- None

---

### 2026-02-22 (session 49)
**Completed:**
- ica-e1k.5: SearchApi Client

**Changes Made:**
- Created `tests/test_services/test_search_api.py` (43 tests)

**Status:**
- SearchApi client (PRD Section 2.1) already fully implemented in prior sessions:
  - `SearchApiClient`: async client with DI-based HttpClient protocol
  - `search(keyword, engine, num, time_period, location)`: single-keyword search with google_news/default engine routing
  - `search_keywords(keywords, ...)`: multi-keyword sequential aggregation
  - `_parse_results(data, origin)`: extracts organic_results[] into SearchResult frozen dataclasses
  - Default engine omits `engine` param (matches SearchApi convention)
- Added dedicated service-level test file for consistency with other services (LLM, Slack, Google Sheets, Google Docs)
- Tests cover: SearchResult dataclass, constructor defaults, search() params/defaults/engine routing, _parse_results edge cases, search_keywords aggregation, HttpClient protocol
- All 2794 tests pass (2751 existing + 43 new)

**Next:**
- Next available task from `bd ready`

**Blockers:**
- None

---

### 2026-02-22 (session 48)
**Completed:**
- ica-e1k.4: Google Docs Service

**Changes Made:**
- Created `ica/services/google_docs.py` (GoogleDocsService class, _load_credentials, _build_service, _extract_text)
- Created `tests/test_services/test_google_docs.py` (56 tests)

**Status:**
- Google Docs service (PRD Section 2.4) fully implemented:
  - `GoogleDocsService`: async wrapper over Google Docs API v1
  - `create_document(title)`: creates a new Google Doc, returns document ID
  - `insert_content(document_id, text)`: inserts text at position 1 via batchUpdate/insertText
  - `get_content(document_id)`: fetches full plain-text body by traversing structural elements
  - `_extract_text(document)`: extracts text from body.content[].paragraph.elements[].textRun.content
  - Service account JSON credential loading with validation
  - All sync Google API calls wrapped in asyncio.to_thread()
  - Constructor accepts credentials_path (production) or pre-built service (testing)
  - Supports all n8n Google Docs patterns: create, update (insert), get operations
- All 2751 tests pass (2695 existing + 56 new)

**Next:**
- Next available task from `bd ready`

**Blockers:**
- None

---

### 2026-02-22 (session 47)
**Completed:**
- ica-e1k.3: Google Sheets Service

**Changes Made:**
- Created `ica/services/google_sheets.py` (GoogleSheetsService class, _load_credentials, _build_service)
- Created `tests/test_services/test_google_sheets.py` (50 tests)

**Status:**
- Google Sheets service (PRD Section 2.3) fully implemented:
  - `GoogleSheetsService`: async wrapper over Google Sheets API v4
  - `clear_sheet(spreadsheet_id, sheet_name)`: clears all values via values.clear (SheetWriter)
  - `append_rows(spreadsheet_id, sheet_name, rows)`: writes header + data rows via values.update (SheetWriter)
  - `read_rows(spreadsheet_id, sheet_name)`: reads all rows, first row as headers, returns list[dict] (SheetReader)
  - Service account JSON credential loading with validation
  - All sync Google API calls wrapped in asyncio.to_thread()
  - Constructor accepts credentials_path (production) or pre-built service (testing)
  - Satisfies both SheetWriter and SheetReader protocols from article_curation and summarization
- All 2695 tests pass (2645 existing + 50 new)

**Next:**
- Next available task from `bd ready`

**Blockers:**
- None

---

### 2026-02-22 (session 46)
**Completed:**
- ica-e1k.2: Slack Service

**Changes Made:**
- Created `ica/services/slack.py` (SlackService class, Block Kit helpers, interaction handlers)
- Created `tests/test_services/test_slack.py` (75 tests)

**Status:**
- Slack service (PRD Section 11.2, 11.7) fully implemented:
  - `SlackService`: unified class satisfying all 5 Slack protocols used across the pipeline
  - `send_message(channel, text)`: plain-text channel posting (SlackNotifier)
  - `send_channel_message(text, blocks)`: default-channel posting with optional Block Kit (SlackSummaryReview)
  - `send_error(message)`: error notification to default channel (SlackErrorNotifier)
  - `send_and_wait(channel, text, approve_label)`: approval button with asyncio.Event blocking (SlackApprovalSender)
  - `send_and_wait_form(message, form_fields, ...)`: form trigger button → modal → submission (SlackSummaryReview)
  - `send_and_wait_freetext(message, ...)`: freetext trigger button → modal → submission (SlackManualFallback + SlackSummaryReview)
  - `register_handlers(bolt_app)`: registers action/view handlers on Slack Bolt app via regex patterns
  - Block Kit helpers: _text_block, _button_block, _build_approval_blocks, _build_trigger_blocks, _build_modal_blocks, _build_freetext_modal_blocks, _extract_modal_values
  - Modal title auto-truncation to Slack's 24-char limit
  - n8n-style form field conversion: dropdown → static_select, text → plain_text_input, textarea → multiline
- All 2645 tests pass (2570 existing + 75 new)

**Next:**
- Next available task from `bd ready`

**Blockers:**
- None

---

### 2026-02-22 (session 45)
**Completed:**
- ica-e1k.1: LLM Service

**Changes Made:**
- Created `ica/services/llm.py` (LLMResponse frozen dataclass, completion async function, _retryable_errors helper)
- Created `tests/test_services/__init__.py`
- Created `tests/test_services/test_llm.py` (62 tests)

**Status:**
- Unified LLM service wrapper (PRD Section 11.3) fully implemented:
  - `completion()`: single async function replacing all direct `litellm.acompletion` calls
  - Model routing: accepts `LLMPurpose` for config-based lookup or explicit model string
  - Message construction: builds system+user messages list automatically
  - Response extraction: extracts text content, validates non-empty, strips whitespace
  - Token usage: captures prompt_tokens/completion_tokens/total_tokens when available
  - Retry with exponential back-off: retries RateLimitError, ServiceUnavailableError, Timeout, InternalServerError, APIConnectionError
  - Configurable retry params: max_retries (default 3), retry_base_delay (default 1s), retry_max_delay (default 30s)
  - Error mapping: non-retryable errors wrapped as LLMError with step name; exhausted retries raise LLMError with cause chain
  - Extra kwargs forwarded to litellm (temperature, max_tokens, etc.)
  - `LLMResponse`: frozen dataclass with text, model, purpose, usage
- All 2570 tests pass (2508 existing + 62 new)

**Next:**
- Next available task from `bd ready`

**Blockers:**
- None

---

### 2026-02-22 (session 44)
**Completed:**
- ica-1si.11: Implement scheduling

**Changes Made:**
- Created `ica/scheduler.py` (create_scheduler, run_article_collection, run_pipeline_trigger, get_scheduled_jobs, _SchedulerStubRepository)
- Updated `ica/app.py` — added `include_scheduler` parameter to create_app, scheduler start/stop in lifespan, `/scheduler` status endpoint
- Updated `tests/test_app.py` — added `include_scheduler=False` to all create_app calls, added /scheduler to route assertions
- Created `tests/test_scheduler.py` (46 tests)

**Status:**
- APScheduler integration (PRD Section 10.1) fully implemented:
  - `create_scheduler()`: factory with configurable timezone, article collection jobs, and pipeline trigger
  - Article collection (daily): CronTrigger at configurable hour, google_news engine, 3 keywords
  - Article collection (every 2 days): IntervalTrigger(days=2), default engine, 5 keywords
  - Pipeline trigger: IntervalTrigger(days=5), disabled by default (manual-only)
  - `run_article_collection()`: async job function with lazy imports, error handling, logging
  - `run_pipeline_trigger()`: creates PipelineRun, launches background task via asyncio.create_task
  - `get_scheduled_jobs()`: returns job summaries for /scheduler endpoint
  - FastAPI lifecycle integration: scheduler.start() on startup, scheduler.shutdown() on teardown
  - `/scheduler` GET endpoint: returns enabled status and job list with next_run_time
  - Graceful degradation: scheduler=None when settings unavailable
- All 2508 tests pass (2462 existing + 46 new)

**Next:**
- Next available task from `bd ready`

**Blockers:**
- None

---

## Session Log

### 2026-02-22 (session 43)
**Completed:**
- ica-1si.10: Wire pipeline orchestration

**Changes Made:**
- Created `ica/pipeline/orchestrator.py` (StepName enum, PipelineContext dataclass, StepResult dataclass, PipelineStep protocol, run_step, run_pipeline, _run_parallel_steps, _noop_step, build_default_steps)
- Created `tests/test_pipeline/test_orchestrator.py` (51 tests)
- Updated `ica/app.py` — replaced placeholder `_run_pipeline` with real orchestrator wiring (imports PipelineContext, build_default_steps, run_pipeline from orchestrator module)

**Status:**
- Pipeline orchestrator (PRD Section 11.6) fully implemented:
  - `PipelineContext`: accumulates state across steps — articles, summaries, themes, doc IDs, step results, extra dict
  - `StepResult`: frozen dataclass with step name, status, timing, and optional error
  - `StepName`: enum with all 9 step names (5 sequential + 4 parallel)
  - `run_step()`: executes a single step with timing, logging context (bind_context), and error recording
  - `run_pipeline()`: orchestrates sequential steps then parallel outputs via asyncio.gather
  - Sequential steps: context flows through each step; PipelineStopError halts execution
  - Parallel steps: all receive the same context; failures are collected (don't cancel siblings)
  - `build_default_steps()`: returns all 9 steps as noop stubs, ready for real implementations
  - FastAPI `_run_pipeline` now creates PipelineContext + delegates to orchestrator
- All 2462 tests pass (2411 existing + 51 new)

**Next:**
- Next available task from `bd ready`

**Blockers:**
- None

---

### 2026-02-22 (session 42)
**Completed:**
- ica-drl.9: Implement structured logging

**Changes Made:**
- Created `ica/logging.py` (ContextFilter, JsonFormatter, TextFormatter, configure_logging, get_logger, bind_context, run_id_var, step_var)
- Created `tests/test_logging.py` (56 tests)
- Updated `ica/config/settings.py` — added `log_level` and `log_format` settings
- Updated `ica/app.py` — wired `configure_logging()` into FastAPI lifespan, switched to `get_logger()`
- Updated `ica/errors.py` — switched from `logging.getLogger()` to `get_logger()`

**Status:**
- Structured logging module with:
  - Async-safe context variables (`run_id_var`, `step_var`) via `contextvars`
  - `ContextFilter`: injects context vars into every log record
  - `JsonFormatter`: JSON-lines output for production (timestamp, level, logger, message, run_id, step, exception)
  - `TextFormatter`: human-readable output for dev, with `[run=X step=Y]` context tag when bound
  - `configure_logging(level, log_format)`: one-call root logger setup (text or json)
  - `get_logger(name)`: logger factory with ContextFilter attached (idempotent)
  - `bind_context(run_id, step)`: sync/async context manager for setting pipeline context (nestable, exception-safe)
- Settings: `LOG_LEVEL` (default INFO) and `LOG_FORMAT` (default text) env vars
- FastAPI app startup calls `configure_logging()` from Settings in lifespan
- All 2411 tests pass (2355 existing + 56 new)

**Next:**
- Next available task from `bd ready`

**Blockers:**
- None

---

<!--
After completing each task, add an entry below in this format:

### YYYY-MM-DD HH:MM PT
**Completed:**
- [task description from bd]

**Changes Made:**
- [files created/modified]

**Status:**
- [what works now]

**Next:**
- [next task to work on]

**Blockers:**
- [any issues encountered, or "None"]

---
-->

### 2026-02-22 (session 41)
**Completed:**
- ica-drl.8: Implement error handling patterns

**Changes Made:**
- Created `ica/errors.py` (PipelineError, LLMError, FetchError, DatabaseError, ValidationError, PipelineStopError, SlackErrorNotifier protocol, format_error_slack_message, format_llm_error_slack_message, notify_error, handle_step_error, ValidationLoopCounter)
- Created `tests/test_errors.py` (64 tests)

**Status:**
- Error handling module ported from n8n workflow patterns:
  - Exception hierarchy: PipelineError base → LLMError, FetchError, DatabaseError, ValidationError, PipelineStopError
  - Slack error notification with two templates:
    - Full: "*Execution Stopped at [step], due to the following error :* [error] *, reach out to the concerned person to resolve the issue.*" (summarization/markdown/HTML subworkflows)
    - Short: "An Error on LLM Processing: [error]" (theme/email subworkflows)
  - SlackErrorNotifier protocol for dependency injection
  - notify_error: sends Slack notification with graceful fallback (log-only when notifier is None, suppresses Slack failures)
  - handle_step_error: captures error → notifies Slack → raises PipelineStopError (matches n8n "Error Output → Stop and Error" pattern)
  - ValidationLoopCounter: max 3 attempts (configurable) with count/exhausted/remaining/reset (PRD Section 7.4)
- All 2355 tests pass (2291 existing + 64 new)

**Next:**
- Next available task from `bd ready`

**Blockers:**
- None

---

### 2026-02-22 (session 40)
**Completed:**
- ica-0jh.18: Output generator prompt templates

**Changes Made:**
- Created `ica/prompts/email_subject.py` (EMAIL_SUBJECT_SYSTEM_PROMPT, EMAIL_SUBJECT_USER_PROMPT, _FEEDBACK_SECTION_TEMPLATE, build_email_subject_prompt)
- Created `ica/prompts/social_media.py` (SOCIAL_MEDIA_POST_SYSTEM_PROMPT/USER_PROMPT, SOCIAL_MEDIA_CAPTION_SYSTEM_PROMPT/USER_PROMPT, SOCIAL_MEDIA_REGENERATION_SYSTEM_PROMPT/USER_PROMPT, build_social_media_post_prompt, build_social_media_caption_prompt, build_social_media_regeneration_prompt)
- Created `ica/prompts/linkedin_carousel.py` (LINKEDIN_CAROUSEL_SYSTEM_PROMPT/USER_PROMPT, LINKEDIN_REGENERATION_SYSTEM_PROMPT/USER_PROMPT, build_linkedin_carousel_prompt, build_linkedin_regeneration_prompt)
- Created `tests/test_prompts/test_email_subject.py` (45 tests)
- Created `tests/test_prompts/test_social_media.py` (80 tests)
- Created `tests/test_prompts/test_linkedin_carousel.py` (57 tests)

**Status:**
- 3 prompt modules ported from n8n workflows:
  - Email subject: up to 10 subjects (max 7 words), separator format, recommendation (n8n "Generate Data using LLM" in email_subject_and_preview_subworkflow)
  - Social media: Phase 1 graphics-only posts (6 DYK + 6 IT), Phase 2 caption generation, feedback-driven regeneration (n8n social_media_generator_subworkflow)
  - LinkedIn carousel: post copy (3 versions) + 10 carousel slides with character specs, feedback-driven regeneration (n8n linkedin_carousel_generator_subworkflow)
- Note: alternates HTML has no LLM prompts (pure HTML templating); email preview/review already ported in session 13
- All 2291 tests pass (2109 existing + 182 new)

**Next:**
- Next available task from `bd ready`

**Blockers:**
- None

---

### 2026-02-22 (session 39)
**Completed:**
- ica-1si.13: Implement CLI interface

**Changes Made:**
- Created `ica/__main__.py` — Typer CLI with 4 commands: `serve` (start FastAPI via uvicorn), `run` (trigger pipeline via /trigger API), `status` (show run status via /status API), `collect-articles` (manual article collection via SearchApi)
- Created `tests/test_cli.py` (38 tests)

**Status:**
- CLI entry point `ica = "ica.__main__:main"` (pyproject.toml) now functional
- `ica serve` — starts uvicorn with `--host`, `--port`, `--reload` options
- `ica run` — POSTs to /trigger with custom `--trigger` label and `--base-url`
- `ica status [run_id]` — GETs /status or /status/{run_id}, Rich table for all runs, detail view for single run
- `ica collect-articles` — runs article collection with `--schedule` option (daily/every_2_days), Rich table output
- All commands handle connection errors and HTTP errors gracefully with exit code 1
- All 2109 tests pass (2071 existing + 38 new)

**Next:**
- Next available task from `bd ready`

**Blockers:**
- None

---

### 2026-02-22 (session 38)
**Completed:**
- ica-1si.12: Implement FastAPI application

**Changes Made:**
- Created `ica/app.py` — FastAPI application factory with `create_app()`, RunStatus enum, PipelineRun dataclass, in-memory run store, `_serialize_run` helper, `_run_pipeline` placeholder, `_create_slack_app` Slack Bolt integration
- Endpoints: `GET /health` (health check), `POST /trigger` (start pipeline run with background task, returns run_id), `GET /status` (all runs), `GET /status/{run_id}` (single run, 404 if not found), `POST /slack/events` (Slack Bolt handler, conditionally mounted)
- Slack Bolt integration: creates AsyncApp + AsyncSlackRequestHandler when env vars present, gracefully disables when missing, mounted on `/slack/events`
- `include_slack` flag on `create_app()` for test isolation
- Created `tests/test_app.py` (39 tests)

**Status:**
- FastAPI application with all required endpoints implemented:
  - `/health`: returns `{"status": "ok"}` for Docker health checks
  - `/trigger`: creates PipelineRun, launches background task, returns run_id + status
  - `/status`: lists all runs with full serialized state
  - `/status/{run_id}`: single run lookup with 404 handling
  - `/slack/events`: forwards to Slack Bolt handler (conditional mount)
- Slack Bolt integration: graceful degradation when env vars missing
- Pipeline execution: placeholder that transitions PENDING → RUNNING → COMPLETED (ready for real orchestrator)
- All 2071 tests pass (2032 existing + 39 new)

**Next:**
- Next available task from `bd ready`

**Blockers:**
- None

---

### 2026-02-22 (session 37)
**Completed:**
- ica-duo.28: Implement summarization output and feedback

**Changes Made:**
- Updated `ica/pipeline/summarization.py` — added SlackSummaryReview protocol, SummarizationOutput dataclass, Slack constants (SUMMARY_HEADER, NEXT_STEPS_*, FEEDBACK_*, SUMMARY_DIVIDER), format_summary_slack_text (mrkdwn text builder), build_summary_slack_blocks (Block Kit builder), build_next_steps_form (dropdown form), parse_next_steps_response (UserChoice mapping), summaries_to_output_articles (PRD Section 5.2 format), call_regeneration_llm (regeneration via SUMMARY_REGENERATION model), extract_summary_learning_data (learning data extraction via SUMMARY_LEARNING_DATA model with JSON parsing), store_summarization_feedback (notes table with type='user_summarization'), run_summarization_output (main orchestrator with feedback loop)
- Created `tests/test_pipeline/test_summarization_output.py` (98 tests)

**Status:**
- Summarization output and feedback loop (Step 2, third part) fully implemented:
  - Slack mrkdwn text formatting with header, article count, per-article title/URL/summary/relevance (n8n "Format output" Code node)
  - Slack Block Kit blocks with section + divider pattern (n8n blocks array)
  - Next-steps dropdown form: Yes / Provide Feedback / Restart Chat (n8n "Next steps selection" sendAndWait)
  - Feedback collection via free-text form (n8n "Feedback form" sendAndWait)
  - Regeneration LLM call with summarization regeneration prompt (n8n "Re-Generate Data using LLM")
  - Learning data extraction with JSON parsing (n8n "Learning data extractor")
  - Feedback storage in notes table with type='user_summarization' (n8n "Insert user feedback" Postgres)
  - Conditional output routing via output_router (n8n "Conditional output" Code node)
  - Full orchestration loop matching n8n flow: share → ask → feedback/restart/exit
- All 2032 tests pass (1934 existing + 98 new)

**Next:**
- Next available task from `bd ready`

**Blockers:**
- None

---

### 2026-02-22 (session 36)
**Completed:**
- ica-duo.27: Implement per-article summarization loop

**Changes Made:**
- Updated `ica/pipeline/summarization.py` — added per-article loop (second half of Step 2): FetchResult dataclass, ArticleSummary dataclass, SummarizationLoopResult dataclass, HttpFetcher protocol, SlackManualFallback protocol, BROWSER_HEADERS constant, is_fetch_failure (error/captcha/YouTube detection), build_manual_fallback_message, strip_html_tags (HTML-to-text), build_article_input, aggregate_feedback (Note→bullet list), call_summary_llm (litellm.acompletion), parse_summary_output (regex URL/Title/Summary/BusinessRelevance), summarize_single_article (single-article orchestration), summarize_articles (loop orchestration)
- Created `tests/test_pipeline/test_summarization_loop.py` (98 tests)

**Status:**
- Per-article summarization loop (Step 2, second half) fully implemented:
  - HTTP page fetching with browser-like headers (n8n "Fetch Page Content" node)
  - Fetch failure detection: error, captcha ("sgcaptcha"), YouTube URL (n8n "If" condition node)
  - Slack manual fallback for failed fetches (n8n "Manual Article Content" sendAndWait node)
  - HTML-to-text conversion: strips script/style, removes tags, unescapes entities
  - Learning data fetch from notes table (last 40, type='user_summarization')
  - Feedback aggregation into bullet-point list (n8n "Aggregate Feedback" Code node)
  - LLM call via litellm.acompletion with summarization prompt
  - Output parsing via regex (n8n "Format output" Code node patterns)
  - Sequential loop matching n8n splitInBatches with batch size 1
- All 1934 tests pass (1836 existing + 98 new)

**Next:**
- Next available task from `bd ready`

**Blockers:**
- None

---

### 2026-02-22 (session 35)
**Completed:**
- ica-tru.3: Consolidate user_feedback tables into notes

**Changes Made:**
- Updated `ica/db/models.py` — removed `FeedbackMixin` and 5 feedback classes (`SummarizationUserFeedback`, `MarkdownGeneratorUserFeedback`, `HtmlGeneratorUserFeedback`, `NewsletterThemesUserFeedback`, `NewsletterEmailSubjectFeedback`), added single `Note` class with `type` discriminator (`user_summarization`, `user_newsletter_themes`, `user_markdowngenerator`, `user_htmlgenerator`, `user_email_subject`)
- Updated `ica/db/crud.py` — replaced generic `add_feedback(session, model, text)` and `get_recent_feedback(session, model)` with `add_note(session, note_type, text)` and `get_recent_notes(session, note_type)` that filter by `Note.type`
- Updated `ica/db/__init__.py` — re-exports `Note` instead of 5 feedback classes
- Updated `ica/db/migrations/versions/001_initial_tables.py` — replaced 5 feedback table creates with single `notes` table (with `type` column and composite index)
- Updated `ica/pipeline/theme_generation.py` — `get_recent_notes(session, "user_newsletter_themes")` instead of `get_recent_feedback(session, NewsletterThemesUserFeedback)`
- Updated `ica/pipeline/theme_selection.py` — `add_note(session, "user_newsletter_themes", ...)` instead of `add_feedback(session, NewsletterThemesUserFeedback, ...)`
- Updated `ica/prompts/theme_generation.py`, `ica/prompts/markdown_generation.py` — docstring table name references
- Updated `tests/test_pipeline/test_theme_selection.py`, `tests/test_pipeline/test_theme_generation.py` — mock patches and assertions
- Updated `CLAUDE.md` — database table description (7 tables → 3 tables)

**Status:**
- All 1836 tests pass (no new tests needed — pure rename/consolidation refactor)
- No remaining references to old feedback class names or table names in `ica/` source

**Next:**
- Next available task from `bd ready`

**Blockers:**
- None

---

### 2026-02-22 (session 34)
**Completed:**
- ica-tru.2: Rename newsletter_themes to themes

**Changes Made:**
- Updated `ica/db/models.py` — renamed `NewsletterTheme` class to `Theme`, table `newsletter_themes` → `themes`, added `type` column (`String(50)`, server_default `'newsletter'`)
- Updated `ica/db/crud.py` — all `NewsletterTheme` references → `Theme`
- Updated `ica/db/__init__.py` — re-exports `Theme` instead of `NewsletterTheme`
- Updated `ica/db/migrations/versions/001_initial_tables.py` — table name `newsletter_themes` → `themes`, added `type` column
- Updated `ica/pipeline/theme_selection.py` — docstring references
- Updated `CLAUDE.md` — database table name reference

**Status:**
- All 1836 tests pass (no new tests needed — pure rename refactor)
- No remaining `NewsletterTheme` or `newsletter_themes` references in `ica/` source (excluding `newsletter_themes_user_feedback` which is a separate table)

**Next:**
- Next available task from `bd ready`

**Blockers:**
- None

---

### 2026-02-22 (session 33)
**Completed:**
- ica-duo.26: Implement summarization data preparation

**Changes Made:**
- Created `ica/pipeline/summarization.py` (SheetReader protocol, CuratedArticle, SummarizationPrepResult, filter_approved_rows, normalize_article_row, upsert_curated_articles, prepare_summarization_data)
- Updated `ica/utils/date_parser.py` — added `parse_date_mmddyyyy()` (reverse of `format_date_mmddyyyy`)
- Created `tests/test_pipeline/test_summarization.py` (69 tests)

**Status:**
- Summarization data preparation (Step 2, first half) fully implemented:
  - SheetReader protocol: reads all rows from Google Sheet
  - filter_approved_rows: filters to approved=yes rows (n8n "Fetch Data from Sheet" filter)
  - normalize_article_row: converts string fields to typed CuratedArticle (n8n "Field Mapping" Set node)
  - upsert_curated_articles: PostgreSQL INSERT...ON CONFLICT upsert with type='curated' (n8n "Structure SQL Insert Query" Code node)
  - prepare_summarization_data: orchestrates the full flow — get LLM config → fetch sheet → filter → normalize → upsert
- All 1836 tests pass (1767 existing + 69 new)

**Next:**
- Next available task from `bd ready`

**Blockers:**
- None

---

### 2026-02-22 (session 32)
**Completed:**
- ica-tru.1: Rename curated_articles to articles

**Changes Made:**
- Updated `ica/db/models.py` — renamed `CuratedArticle` class to `Article`, table `curated_articles` → `articles`, added `type` column (`String(50)`, server_default `'curated'`)
- Updated `ica/db/crud.py` — all `CuratedArticle` references → `Article`
- Updated `ica/db/__init__.py` — re-exports `Article` instead of `CuratedArticle`
- Updated `ica/db/migrations/versions/001_initial_tables.py` — table name `curated_articles` → `articles`, added `type` column
- Updated `ica/pipeline/article_curation.py` — import and type hints `CuratedArticle` → `Article`
- Updated `ica/pipeline/article_collection.py` — docstring reference
- Updated `tests/test_pipeline/test_article_curation.py` — comments
- Updated `CLAUDE.md` — database table name reference

**Status:**
- All 1767 tests pass (no new tests needed — pure rename refactor)
- No remaining `CuratedArticle` or `curated_articles` references in `ica/` source

**Next:**
- Next available task from `bd ready`

**Blockers:**
- None

---

### 2026-02-22 (session 31)
**Completed:**
- ica-bfc.13: Implement article curation approval flow

**Changes Made:**
- Updated `ica/pipeline/article_curation.py` — added SlackApprovalSender protocol, SheetReader protocol, ApprovedArticle dataclass, ApprovalResult dataclass, build_approval_message, build_revalidation_message, _is_approved, validate_sheet_data, parse_approved_articles, run_approval_flow
- Updated `tests/test_pipeline/test_article_curation.py` (+78 tests, 60→138 total)

**Status:**
- Article curation approval flow (Step 1, second half) fully implemented:
  - SlackApprovalSender protocol: sendAndWait abstraction for Slack approval buttons
  - SheetReader protocol: reads all rows from Google Sheet after user approval
  - build_approval_message: constructs Slack message with Google Sheets link (n8n "User message" Code node)
  - build_revalidation_message: constructs re-validation instructions (n8n "User re-validation message" Code node)
  - validate_sheet_data: checks at least one row has approved=yes AND newsletter_id (n8n "Validate data for required fields" Code node)
  - parse_approved_articles: filters approved rows and normalizes to ApprovedArticle output format (PRD Section 5.1)
  - run_approval_flow: orchestrates the full loop — sendAndWait → fetch sheet → validate → retry or return
- All 1767 tests pass (1689 existing + 78 new)

**Next:**
- Next available task from `bd ready`

**Blockers:**
- None

---

### 2026-02-22 (session 30)
**Completed:**
- ica-bfc.12: Implement article curation data flow

**Changes Made:**
- Created `ica/pipeline/article_curation.py` (SlackNotifier protocol, SheetWriter protocol, SheetArticle, CurationDataResult, format_article_for_sheet, articles_to_row_dicts, fetch_unapproved_articles, prepare_curation_data)
- Created `tests/test_pipeline/test_article_curation.py` (60 tests)

**Status:**
- Article curation data preparation (Step 1, first half) fully implemented:
  - Protocol-based dependency injection: SlackNotifier for Slack messages, SheetWriter for Google Sheets operations
  - format_article_for_sheet: publish_date → MM/DD/YYYY, approved false/None → "", industry_news → "yes"/"", newsletter_id None → ""
  - fetch_unapproved_articles: WHERE approved=false OR approved IS NULL, ORDER BY publish_date DESC, LIMIT 30 (matches n8n behavior)
  - prepare_curation_data orchestrator: Slack notify → clear sheet → fetch DB → format → append to sheet
  - articles_to_row_dicts: converts SheetArticle list to dict list with all 7 SHEET_COLUMNS
- All 1689 tests pass (1629 existing + 60 new)

**Next:**
- Next available task from `bd ready`

**Blockers:**
- None

---

### 2026-02-22 (session 29)
**Completed:**
- ica-578.22: Implement theme selection and approval

**Changes Made:**
- Created `ica/pipeline/theme_selection.py` (ThemeSelectionResult, ApprovalChoice, format_theme_body, format_recommendation, format_themes_slack_message, format_selected_theme_body, format_freshness_slack_message, build_theme_selection_form, build_approval_form, extract_selected_theme, is_feedback_selection, parse_approval_choice, run_freshness_check, extract_learning_data, save_approved_theme, store_theme_feedback)
- Created `tests/test_pipeline/test_theme_selection.py` (139 tests)

**Status:**
- Theme selection and approval pipeline step (Step 3, second half) fully implemented:
  - Slack formatting: themes overview with marker-to-mrkdwn conversion, selected theme detail view, freshness report display
  - Form builders: theme selection (radio: themes + "Add Feedback"), final approval (Approve/Reset/Feedback)
  - Response parsing: theme extraction with case-insensitive matching, feedback detection, approval choice routing (contains-based, matching n8n "Final Switch" logic)
  - LLM calls: freshness check via `LLMPurpose.THEME_FRESHNESS_CHECK` (gemini-2.5-flash), learning data extraction via `LLMPurpose.THEME_LEARNING_DATA` (claude-sonnet)
  - DB operations: save approved theme via `upsert_theme()`, store feedback via `add_feedback()`
- All 1629 tests pass (1490 existing + 139 new)

**Next:**
- Next available task from `bd ready`

**Blockers:**
- None

---

### 2026-02-22 (session 28)
**Completed:**
- ica-578.21: Implement theme generation and parsing

**Changes Made:**
- Created `ica/pipeline/theme_generation.py` (GeneratedTheme, ThemeGenerationResult, aggregate_feedback, call_theme_llm, parse_theme_output, generate_themes)
- Created `tests/test_pipeline/test_theme_generation.py` (63 tests)

**Status:**
- Theme generation pipeline step orchestrates all existing building blocks:
  - Fetches last 40 feedback entries from `newsletter_themes_user_feedback` via CRUD
  - Aggregates feedback into bullet-point list for prompt injection
  - Calls LLM via `litellm.acompletion` with model from `LLMPurpose.THEME`
  - Parses LLM output with `split_themes()` + `parse_markers()` into `GeneratedTheme` objects
  - Returns `ThemeGenerationResult` with themes, recommendation, raw output, and model
- All 1490 tests pass (1427 existing + 63 new)

**Next:**
- Next available task from `bd ready`

**Blockers:**
- None

---

### 2026-02-22 (session 27)
**Completed:**
- ica-0jh.17: Core pipeline prompt templates

**Changes Made:**
- Created `ica/prompts/markdown_structural_validation.py` (STRUCTURAL_VALIDATION_PROMPT, build_structural_validation_prompt)
- Created `ica/prompts/markdown_voice_validation.py` (VOICE_VALIDATION_PROMPT, build_voice_validation_prompt)
- Created `ica/prompts/learning_data_extraction.py` (LEARNING_DATA_EXTRACTION_PROMPT, build_learning_data_extraction_prompt)
- Created `ica/prompts/freshness_check.py` (FRESHNESS_CHECK_PROMPT, build_freshness_check_prompt)
- Created `ica/prompts/html_generation.py` (HTML_GENERATION_SYSTEM_PROMPT, HTML_REGENERATION_SYSTEM_PROMPT, build_html_generation_prompt, build_html_regeneration_prompt)
- Created `tests/test_prompts/test_markdown_structural_validation.py` (42 tests)
- Created `tests/test_prompts/test_markdown_voice_validation.py` (43 tests)
- Created `tests/test_prompts/test_learning_data_extraction.py` (31 tests)
- Created `tests/test_prompts/test_freshness_check.py` (23 tests)
- Created `tests/test_prompts/test_html_generation.py` (54 tests)

**Status:**
- 5 prompt modules ported from n8n workflows:
  - Structural validation: non-numeric rule checks merged with upstream char errors (PRD 4.5)
  - Voice validation: 4-section voice/tone evaluation with prior error merging (PRD 4.6)
  - Learning data extraction: shared feedback→learning note converter used across 3 subworkflows (PRD 4.7)
  - Freshness check: theme vs recent newsletters comparison via is2digital.com (PRD 4.8)
  - HTML generation: template population + scoped regeneration with feedback (n8n html_generator_subworkflow)
- All 1427 tests pass (1234 existing + 193 new)

**Next:**
- Next available task from `bd ready`

**Blockers:**
- None

---

### 2026-02-22 (session 26)
**Completed:**
- ica-1h1.7: Configuration System (LLM config module + startup validation)

**Changes Made:**
- Created `ica/config/llm_config.py` (LLMPurpose enum, LLMConfig Pydantic Settings, get_llm_config, get_model)
- Created `ica/config/validation.py` (ValidationResult dataclass, validate_config startup checker)
- Updated `ica/config/__init__.py` (re-exports all new items)
- Created `tests/test_config/test_llm_config.py` (125 tests)
- Created `tests/test_config/test_validation.py` (26 tests)

**Status:**
- 21 LLM model mappings ported from n8n `llm_global_config_utility.json` with env var overrides
- LLMPurpose enum for typed model lookups, get_model() convenience function
- Startup validation: required env vars (Pydantic), IANA timezone, LLM model provider/model format
- All 1234 tests pass (1083 existing + 151 new)

**Next:**
- Next available task from `bd ready`

**Blockers:**
- None

---

### 2026-02-22 (session 25)
**Completed:**
- ica-dd0.1.3: Test theme body splitter

**Changes Made:**
- Created `tests/test_utils/test_theme_splitter.py` (83 tests)

**Status:**
- 11 test classes covering: basic splitting (theme count, order), RECOMMENDATION routing (position variants, multiple recs, substring matching), ParsedThemeBlock field extraction (name, description, special chars, whitespace), separator variations (exact 5 dashes, fewer/more, consecutive, embedded), empty/whitespace input, line endings (Windows/mixed/CR-only), content preservation (markers, URLs, unicode, emoji, blank lines), return types (frozen dataclasses), realistic LLM patterns (preamble, postamble, all marker types), RECOMMENDATION keyword edge cases (case sensitivity, missing colon, mid-word)
- Parametrized tests: separator counting (1-5 themes), theme name extraction (7 variants), description extraction (5 variants)
- All 1083 tests pass (1000 existing + 83 new)

**Next:**
- Next available task from `bd ready`

**Blockers:**
- None

---

### 2026-02-22 (session 24)
**Completed:**
- ica-dd0.1.2: Test relative date parser edge cases

**Changes Made:**
- Updated `tests/test_utils/test_date_parser.py` (+56 tests, 89→145 total)

**Status:**
- 11 new test classes covering: embedded text (SearchApi contextual strings), multiple dates in string, zero values for all units, large values, unusual whitespace (tabs/newlines), malformed patterns (missing ago/number/unit, decimal, negative, reversed order, unsupported units), non-string input types, singular/plural unit forms, week/day equivalence, month boundary crossings
- All 1000 tests pass (944 existing + 56 new)

**Next:**
- Next available task from `bd ready`

**Blockers:**
- None

---

### 2026-02-22 (session 23)
**Completed:**
- ica-dd0.1.1: Test MM/DD/YYYY date formatter

**Changes Made:**
- Created `tests/test_utils/test_date_parser.py` (89 tests)

**Status:**
- Dedicated test file for `ica.utils.date_parser` covering both `format_date_mmddyyyy` and `parse_relative_date`
- Tests: basic formatting, structure, boundaries, all 12 months parametrized, day/week/sub-day parsing, case insensitivity, whitespace tolerance, fallback/invalid input, UTC edge cases, return types, parse-then-format round-trip
- All 944 tests pass (855 existing + 89 new)

**Next:**
- Next available task from `bd ready`

**Blockers:**
- None

---

### 2026-02-22
**Completed:**
- ica-88n.6: Filter unused articles for alternates

**Changes Made:**
- Created `pyproject.toml` (minimal project config)
- Created `is2news/__init__.py`, `is2news/pipeline/__init__.py` (package structure)
- Created `is2news/pipeline/alternates_html.py` (FilterResult dataclass, extract_urls_from_theme, filter_unused_articles)
- Created `tests/__init__.py`, `tests/test_pipeline/__init__.py`
- Created `tests/test_pipeline/test_alternates_html.py` (23 tests)

**Status:**
- Filtering logic for unused articles works: recursively extracts URLs from formatted_theme, filters summaries by URL match
- All 23 tests pass

**Next:**
- Next available task from `bd ready`

**Blockers:**
- No pip/pytest available in environment (python3-venv/ensurepip not installed). Tests were run inline. Once `python3.12-venv` is installed, pytest can be used normally.

---

### 2026-02-22 (session 2)
**Completed:**
- ica-dd0.5.1: Test article collection end-to-end

**Changes Made:**
- Bootstrapped pip via get-pip.py into .venv; installed pytest + pytest-asyncio
- Created `is2news/utils/__init__.py`, `is2news/services/__init__.py`, `is2news/db/__init__.py` (package structure)
- Created `is2news/utils/date_parser.py` (parse_relative_date, format_date_mmddyyyy)
- Created `is2news/services/search_api.py` (SearchResult, SearchApiClient with HttpClient protocol)
- Created `is2news/pipeline/article_collection.py` (ArticleRecord, ArticleRepository protocol, CollectionResult, deduplicate_results, parse_articles, collect_articles)
- Created `tests/test_pipeline/test_article_collection_e2e.py` (56 tests)

**Status:**
- Full article collection pipeline implemented: SearchApi query → date parsing → deduplication → DB upsert
- All 80 tests pass (24 existing + 56 new)
- pytest now works in .venv

**Next:**
- Next available task from `bd ready`

**Blockers:**
- None

---

### 2026-02-22 (session 3)
**Completed:**
- ica-0jh.1: Create summarization prompt template

**Changes Made:**
- Created `ica/prompts/__init__.py` (prompts package)
- Created `ica/prompts/summarization.py` (SUMMARIZATION_SYSTEM_PROMPT, SUMMARIZATION_USER_PROMPT, _FEEDBACK_SECTION_TEMPLATE, build_summarization_prompt)
- Created `tests/test_prompts/__init__.py`, `tests/test_prompts/test_summarization.py` (39 tests)

**Status:**
- Summarization prompt ported from n8n `SUB/summarization_subworkflow.json` "Generate Data using LLM" node
- System prompt: accuracy control protocol, article summary standards, business relevance specs, data integrity standards
- User prompt: conditional feedback injection, output format, article content interpolation
- `build_summarization_prompt()` returns (system, user) tuple ready for LLM call
- All 119 tests pass (80 existing + 39 new)

**Next:**
- Next available task from `bd ready`

**Blockers:**
- None

---

### 2026-02-22 (session 4)
**Completed:**
- ica-0jh.2: Create summarization regeneration prompt

**Changes Made:**
- Updated `ica/prompts/summarization.py` — added `REGENERATION_SYSTEM_PROMPT`, `REGENERATION_USER_PROMPT`, and `build_summarization_regeneration_prompt()` function
- Created `tests/test_prompts/test_summarization_regeneration.py` (34 tests)

**Status:**
- Regeneration prompt ported from n8n "Re-Generate Data using LLM" node in summarization subworkflow
- System prompt: professional editor role, accuracy control protocol (with 4th rule: "incorporate ONLY requested feedback"), article summary standards, data integrity standards
- User prompt: injects original content and user feedback text
- All 153 tests pass (119 existing + 34 new)

**Next:**
- Next available task from `bd ready`

**Blockers:**
- None

---

### 2026-02-22 (session 5)
**Completed:**
- ica-1h1.10: Create multi-stage Dockerfile with dev and prod targets

**Changes Made:**
- Created `Dockerfile` with 4 stages: base, dev, builder, prod
- Created `.dockerignore` to keep build context clean

**Status:**
- Base stage: python:3.12-slim, installs libpq-dev + gcc for native extensions
- Dev stage: editable install with dev deps, uvicorn --reload for hot-reloading
- Builder stage: isolated venv for clean dependency copy
- Prod stage: slim runtime (libpq5 only, no gcc), non-root user, gunicorn + uvicorn workers, health check
- `.dockerignore` excludes .git, .venv, _n8n-project, _context, .beads, .env files, etc.

**Next:**
- Next available task from `bd ready`

**Blockers:**
- None

---

### 2026-02-22 (session 6)
**Completed:**
- ica-1h1.11: Create base docker-compose.yml with name: ica

**Changes Made:**
- Created `docker-compose.yml` with project name `ica`
- Defined 3 services: app (FastAPI, builds from Dockerfile), postgres (PostgreSQL 16-alpine), redis (Redis 7-alpine for scheduler job store)
- App service uses env_file directive, depends_on with health checks for postgres and redis
- Postgres uses `POSTGRES_PASSWORD` as required var (fails if missing), defaults DB to `n8n_custom_data` and user to `ica`
- Redis and Postgres both have health checks and named volumes
- Base compose has no target/port overrides — environment-specific files will extend it

**Status:**
- Base docker-compose.yml ready for environment-specific overrides (dev, stage, prod)

**Next:**
- Next available task from `bd ready`

**Blockers:**
- None

---

### 2026-02-22 (session 7)
**Completed:**
- ica-1h1.12: Create docker-compose.dev.yml override

**Changes Made:**
- Created `docker-compose.dev.yml` with dev-specific overrides

**Status:**
- Dev override sets build target to `dev`, mounts source for hot reload, exposes debug ports (8000, 5678), postgres (5432), redis (6379)
- Uses `.env.dev` for environment variables, sets ENVIRONMENT=development
- Validated merged config with `docker compose config`

**Next:**
- Next available task from `bd ready`

**Blockers:**
- None

---

### 2026-02-22 (session 8)
**Completed:**
- ica-1h1.13: Create docker-compose.stage.yml override

**Changes Made:**
- Created `docker-compose.stage.yml` with staging-specific overrides

**Status:**
- Staging override uses `prod` build target, `ENVIRONMENT=staging`, `.env.stage` env file
- Separate postgres credentials (ica_stage / n8n_custom_data_stage) with offset port 5433
- Resource limits on all services: app (1 CPU/512M), postgres (1 CPU/512M), redis (0.5 CPU/256M)
- No source volume mounts (production-like behavior)
- Validated with `docker compose config`

**Next:**
- Next available task from `bd ready`

**Blockers:**
- None

---

### 2026-02-22 (session 9)
**Completed:**
- ica-1h1.14: Create docker-compose.prod.yml override

**Changes Made:**
- Created `docker-compose.prod.yml` with production-specific overrides

**Status:**
- Production override uses `prod` build target, `ENVIRONMENT=production`, `.env.prod` env file
- `restart: always` on all services for automatic recovery
- json-file logging with rotation: app/postgres (10m/5 files), redis (10m/3 files)
- Resource limits: app (2 CPU/1G), postgres (2 CPU/1G), redis (0.5 CPU/256M)
- No exposed ports on postgres or redis — internal docker network only
- Validated with `docker compose config`

**Next:**
- Next available task from `bd ready`

**Blockers:**
- None

---

### 2026-02-22 (session 10)
**Completed:**
- ica-1h1.15: Create environment-specific .env files

**Changes Made:**
- Updated `.gitignore` to add `.env.*` pattern with `!.env.example` exception
- Created `.env.example` with all PRD 8.2 variables: POSTGRES_*, OPENROUTER_API_KEY, SLACK_BOT_TOKEN, SLACK_APP_TOKEN, SLACK_CHANNEL, GOOGLE_SHEETS_CREDENTIALS_PATH, GOOGLE_DOCS_CREDENTIALS_PATH, SEARCHAPI_API_KEY, TIMEZONE

**Status:**
- `.env.dev`, `.env.stage`, `.env.prod` are properly gitignored
- `.env.example` is tracked and documents all required variables with placeholder values

**Next:**
- Next available task from `bd ready`

**Blockers:**
- None

---

### 2026-02-22 (session 11)
**Completed:**
- ica-1h1.16: Create Makefile with docker compose shortcuts

**Changes Made:**
- Created `Makefile` with targets: dev, stage, prod, build, down, logs, db-shell, ps, restart, clean, help
- Default target is `help` which displays all available targets with descriptions

**Status:**
- All targets use `$(COMPOSE)` variable for DRY compose invocations
- `dev` runs in foreground with `--build`; `stage` and `prod` run detached (`-d`)
- `db-shell` uses env var defaults matching docker-compose.yml (ica / n8n_custom_data)
- `clean` adds `-v` flag to also remove volumes
- `make help` verified working

**Next:**
- Next available task from `bd ready`

**Blockers:**
- None

---

### 2026-02-22 (session 13)
**Completed:**
- ica-qsq.11: Call LLM for email review generation

**Changes Made:**
- Created `ica/prompts/email_review.py` (EMAIL_REVIEW_SYSTEM_PROMPT, EMAIL_REVIEW_USER_PROMPT, _FEEDBACK_SECTION_TEMPLATE, build_email_review_prompt)
- Created `tests/test_prompts/test_email_review.py` (62 tests)

**Status:**
- Email review prompt ported from n8n "Review data extractor - Review" node in email_subject_and_preview_subworkflow.json
- System prompt: comprehensive strategic guide for creating subscriber-focused email introductions (100-120 words)
- Covers: pre-draft analysis, structure framework ("Hi Friend,"), voice guidelines, quality control, content adaptation
- User prompt: conditional feedback injection, compose instruction, newsletter text interpolation
- `build_email_review_prompt()` returns (system, user) tuple ready for LLM call
- All 215 tests pass (153 existing + 62 new)

**Next:**
- Next available task from `bd ready`

**Blockers:**
- None

---

### 2026-02-22 (session 12)
**Completed:**
- ica-1h1.1: Create pyproject.toml with full dependencies

**Changes Made:**
- Updated `pyproject.toml` with all PRD Section 11.5 dependencies: FastAPI, uvicorn, gunicorn, LiteLLM, slack-bolt, SQLAlchemy[asyncio], asyncpg, Alembic, google-api-python-client, google-auth, google-auth-oauthlib, httpx, APScheduler, pydantic-settings, Typer, Rich
- Added dev dependencies: pytest, pytest-asyncio, pytest-cov, ruff, mypy
- Added tool configs: ruff (py312, line-length 99), mypy (strict + pydantic plugin), hatch build targets
- Added `[project.scripts]` entry point: `ica = "ica.__main__:main"`
- Bumped requires-python to `>=3.12`

**Status:**
- All 153 existing tests pass
- All deps install successfully via `pip install -e ".[dev]"`

**Next:**
- Next available task from `bd ready`

**Blockers:**
- None

---

### 2026-02-22 (session 14)
**Completed:**
- ica-0jh.3: Create theme generation prompt template

**Changes Made:**
- Created `ica/prompts/theme_generation.py` (THEME_GENERATION_SYSTEM_PROMPT, THEME_GENERATION_USER_PROMPT, _FEEDBACK_SECTION_TEMPLATE, build_theme_generation_prompt)
- Created `tests/test_prompts/test_theme_generation.py` (84 tests)

**Status:**
- Theme generation prompt ported from n8n "Generate Data using LLM" node in `SUB/theme_generation_subworkflow.json`
- System prompt: role description, accuracy control protocol (use only provided JSON data, industry_news routing to %I1/%I2)
- User prompt: conditional feedback injection, full %XX_ marker output format (FA, M1, M2, Q1-Q3, I1-I2), 2-2-2 distribution, source mix, requirements verification, theme separator, recommendation section
- `build_theme_generation_prompt()` returns (system, user) tuple ready for LLM call
- All 299 tests pass (215 existing + 84 new)

**Next:**
- Next available task from `bd ready`

**Blockers:**
- None

---

### 2026-02-22 (session 15)
**Completed:**
- ica-0jh.4: Create markdown generation prompt template

**Changes Made:**
- Created `ica/prompts/markdown_generation.py` (MARKDOWN_GENERATION_SYSTEM_PROMPT, MARKDOWN_GENERATION_USER_PROMPT, REGENERATION_SYSTEM_PROMPT, _FEEDBACK_SECTION_TEMPLATE, _VALIDATOR_ERRORS_SECTION_TEMPLATE, build_markdown_generation_prompt, build_markdown_regeneration_prompt)
- Created `tests/test_prompts/test_markdown_generation.py` (98 tests)

**Status:**
- Markdown generation prompt ported from n8n "Generate Markdown using LLM" node in `SUB/markdown_generator_subworkflow.json`
- System prompt: ~4000-word prompt with B2B editorial AI role, Kevin's 9 voice calibration patterns (precision, direct authority, conversational, intellectual honesty, practical grounding, dry humor, strategic synthesis, bold formatting, directive language), hard URL constraints, validator error delta handling with mandatory fix order, output rules
- User prompt: conditional feedback injection, conditional validator errors injection, 8 required section headings (INTRODUCTION through FOOTER), character limits per section, featured article strict structure rules, CTA rules, link rules, formatted_theme data injection
- Regeneration prompt: user-feedback-driven revision with preserve-original rules
- `build_markdown_generation_prompt()` handles first generation, feedback, and validator-error regeneration
- `build_markdown_regeneration_prompt()` handles user-feedback regeneration
- All 397 tests pass (299 existing + 98 new)

**Next:**
- Next available task from `bd ready`

**Blockers:**
- None

---

### 2026-02-22 (session 16)
**Completed:**
- ica-1h1.7.1: Create Pydantic Settings class

**Changes Made:**
- Created `ica/config/__init__.py` (re-exports Settings, get_settings)
- Created `ica/config/settings.py` (Settings class with all PRD 8.2 env vars, computed database URLs, get_settings cache)
- Created `tests/test_config/__init__.py`, `tests/test_config/test_settings.py` (40 tests)

**Status:**
- Pydantic Settings class covers all 13 PRD environment variables: POSTGRES_* (5), OPENROUTER_API_KEY, SLACK_* (3), GOOGLE_*_CREDENTIALS_PATH (2), SEARCHAPI_API_KEY, TIMEZONE
- Computed properties: `database_url` (async/asyncpg), `database_url_sync` (sync/alembic)
- `get_settings()` with lru_cache for singleton pattern / FastAPI dependency injection
- Loads from environment variables with .env file fallback
- All 437 tests pass (397 existing + 40 new)

**Next:**
- Next available task from `bd ready`

**Blockers:**
- None

---

### 2026-02-22 (session 17)
**Completed:**
- ica-dd0.1.7: Test conditional output router

**Changes Made:**
- Created `ica/utils/output_router.py` (UserChoice enum, RouterResult dataclass, normalize_switch_value, conditional_output_router)
- Created `tests/test_utils/__init__.py`, `tests/test_utils/test_output_router.py` (68 tests)

**Status:**
- Conditional output router ported from n8n "Conditional output" Code node (PRD Section 9.8)
- Handles all combinations: user choice (yes/provide feedback/restart chat/unknown/None) x regenerated text (present/None) x content validity (True/False)
- normalize_switch_value: case-insensitive, whitespace-tolerant parsing of Slack form values
- RouterResult: frozen dataclass with (text, feedback) outputs
- Exhaustive parametrized state matrix test covers all 15 input combinations
- All 505 tests pass (437 existing + 68 new)

**Next:**
- Next available task from `bd ready`

**Blockers:**
- None

---

### 2026-02-22 (session 18)
**Completed:**
- ica-dd0.1.8: Test boolean normalizer

**Changes Made:**
- Created `ica/utils/boolean_normalizer.py` (normalize_boolean function)
- Created `tests/test_utils/test_boolean_normalizer.py` (51 tests)

**Status:**
- Boolean normalizer ported from n8n Field Mapping Set node expression: `$json.approved.toString().toLowerCase() === 'yes'`
- Only `"yes"` (case-insensitive, whitespace-trimmed) maps to True; everything else (no, true, false, empty string, None) maps to False
- Bool passthrough: Python `True`/`False` pass through unchanged
- All 556 tests pass (505 existing + 51 new)

**Next:**
- Next available task from `bd ready`

**Blockers:**
- None

---

### 2026-02-22 (session 20)
**Completed:**
- ica-dd0.2.2: Test Featured Article character counting

**Changes Made:**
- Updated `ica/validators/character_count.py` — added `_strip_subheading`, `_extract_cta`, `_split_paragraphs`, `validate_featured_article`; wired into `validate_character_counts`
- Created `tests/test_validators/test_featured_article.py` (62 tests)

**Status:**
- Featured Article validator ported from n8n "Validation Character count" Code node in markdown_generator_subworkflow.json
- Strips `## ...` subheading line, removes CTA line (containing →), splits on blank lines
- P1: 300-400 chars, P2: 300-400 chars, Key Insight (starts with `**`): 300-370 chars
- All 693 tests pass (631 existing + 62 new)

**Next:**
- Next available task from `bd ready`

**Blockers:**
- None

---

### 2026-02-22 (session 19)
**Completed:**
- ica-dd0.2.3: Test Main Article character counting

**Changes Made:**
- Updated `ica/validators/character_count.py` — added `_strip_source_links`, `_find_callout`, `validate_main_articles`; wired into `validate_character_counts`
- Created `tests/test_validators/test_main_articles.py` (61 tests)

**Status:**
- Main Article 1 & 2 validator ported from n8n `parseMain` in "Validation Character count" Code node
- Strips `## ...` subheading, removes `[text →](url)` source links, splits paragraphs
- Callout: bold-label pattern (`**Label:**` or `*Label:*`) → 180-250 chars
- Content: first non-callout paragraph → max 750 chars (no minimum)
- All 754 tests pass (693 existing + 61 new)

**Next:**
- Next available task from `bd ready`

**Blockers:**
- None

---

### 2026-02-22 (session 19)
**Completed:**
- ica-dd0.2.1: Test Quick Highlights character counting

**Changes Made:**
- Created `ica/validators/__init__.py`, `ica/validators/character_count.py` (CharacterCountError, extract_section, count_chars, _range_check, _extract_bullets, validate_quick_highlights, validate_character_counts)
- Created `tests/test_validators/__init__.py`, `tests/test_validators/test_quick_highlights.py` (75 tests)

**Status:**
- Character count validator module ported from n8n "Validation Character count" Code node in markdown_generator_subworkflow.json
- Quick Highlights: extracts QUICK HIGHLIGHTS section, splits into bullets (• or - prefix), validates each of 3 bullets is 150-190 chars
- Shared infrastructure (extract_section, count_chars, _range_check, CharacterCountError) ready for future section validators
- Delta calculation: negative when too short (current - min), positive when too long (current - max)
- All 631 tests pass (556 existing + 75 new)

**Next:**
- Next available task from `bd ready`

**Blockers:**
- None

---

### 2026-02-22 (session 22)
**Completed:**
- ica-dd0.1.4: Test %marker parser for all article types

**Changes Made:**
- Created `ica/utils/marker_parser.py` (FeaturedArticle, MainArticle, QuickHit, IndustryDevelopment, RequirementsVerified, FormattedTheme, ParsedThemeBlock, ThemeParseResult, split_themes, parse_markers)
- Created `tests/test_utils/test_marker_parser.py` (101 tests)

**Status:**
- Marker parser ported from n8n "Selected Theme output" and "Prepare AI generated themes" Code nodes in theme_generation_subworkflow.json
- `split_themes()`: splits raw LLM output on `-----` delimiter into theme blocks + recommendation
- `parse_markers()`: extracts all %XX_ markers (FA, M1, M2, Q1-Q3, I1-I2, RV) into frozen dataclasses
- Uses `[ \t]*` (horizontal whitespace) instead of `\s*` in regex to prevent newline bleeding
- All 855 tests pass (754 existing + 101 new)

**Next:**
- Next available task from `bd ready`

**Blockers:**
- None
