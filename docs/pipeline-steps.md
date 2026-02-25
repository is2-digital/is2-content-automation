# ICA Technical Breakdown: Pipeline Steps & Content Generation

This document covers each of the 6 pipeline steps, the prompt builder system, validation layers, and the article collection job.

---

## Pipeline Execution Model

Steps 1-5 run sequentially. Step 6 branches into 4 parallel outputs (6a-6d). Each step:
- Receives the mutable `PipelineContext` dataclass
- Reads fields set by prior steps
- Writes its own fields to the context
- Returns the updated context

Sequential steps accumulate state. Parallel steps share the same context snapshot and write to `ctx.extra`.

---

## Step 1: Article Curation (`ica/pipeline/article_curation.py`)

**Purpose**: Surface unapproved articles in Google Sheets for human review, then collect approved selections.

### Functions

**`prepare_curation_data(session, sheets, *, spreadsheet_id, sheet_name)`**
- Fetches unapproved articles from PostgreSQL (`WHERE approved != TRUE OR approved IS NULL`)
- Formats for Google Sheet (dates as MM/DD/YYYY, booleans as "yes"/"")
- Clears sheet and appends rows

**`run_approval_flow(slack, slack_approval, sheets, *, spreadsheet_id, sheet_name, channel) -> ApprovalResult`**
- Sends Slack `sendAndWait` with link to curated-articles sheet
- Validation loop: reads sheet → checks at least 1 article has `approved=yes` AND `newsletter_id` → re-prompts if invalid
- Returns `ApprovalResult` with `articles: list[ApprovedArticle]` and `validation_attempts: int`

### Key Types

```python
@dataclass(frozen=True)
class ApprovedArticle:
    url: str
    title: str
    publish_date: str       # MM/DD/YYYY
    origin: str
    approved: bool          # always True
    newsletter_id: str
    industry_news: bool
```

### Context Writes

| Field | Value |
|---|---|
| `ctx.articles` | List of `ApprovedArticle` dicts |
| `ctx.newsletter_id` | From the first approved article |

### LLM Calls: None
### Human Interaction: Slack approval button + Google Sheets manual entry

---

## Step 2: Summarization (`ica/pipeline/summarization.py`)

**Purpose**: Fetch article content via HTTP, generate per-article summaries with LLM, user feedback loop.

### Functions

**`prepare_summarization_data(session, sheets, *, spreadsheet_id, sheet_name) -> SummarizationPrepResult`**
- Reads approved articles from Google Sheet
- Normalizes boolean fields and dates
- Upserts to PostgreSQL `articles` table with type='curated'

**`summarize_articles(articles, *, http, session, slack, model) -> SummarizationLoopResult`**
Per-article loop:
1. HTTP GET with browser headers → fetch page content
2. On failure (captcha, YouTube, error) → Slack fallback → manual content paste
3. Convert HTML to text via `strip_html_tags()`
4. Fetch learning data from `notes` table (last 40, type='user_summarization')
5. **LLM call** (`LLMPurpose.SUMMARY`): `build_summarization_prompt()` with article content + aggregated feedback
6. Parse output via regex: extract URL, Title, Summary, Business Relevance
7. Return list of `ArticleSummary`

**`run_summarization_output(summaries, *, slack, session, newsletter_id) -> SummarizationOutput`**
Feedback loop:
1. Format summaries as Slack mrkdwn + Block Kit, share in channel
2. Approval form: "Yes" / "Provide Feedback" / "Restart Chat"
3. **Yes** → return final output
4. **Provide Feedback** →
   - Collect feedback via `send_and_wait_freetext`
   - **LLM call** (`LLMPurpose.SUMMARY_REGENERATION`): regenerate with feedback
   - **LLM call** (`LLMPurpose.SUMMARY_LEARNING_DATA`): extract structured note
   - DB write: `add_note(type='user_summarization')`
   - Re-share and loop
5. **Restart Chat** → reset to original, re-share

### Context Writes

| Field | Value |
|---|---|
| `ctx.summaries` | List of `ArticleSummary` |
| `ctx.summaries_json` | JSON-serialized summaries string |

### LLM Calls

| Purpose | When |
|---|---|
| `SUMMARY` | Initial per-article summarization |
| `SUMMARY_REGENERATION` | Regenerate based on user feedback |
| `SUMMARY_LEARNING_DATA` | Extract learning note from feedback |

---

## Step 3: Theme Generation (`ica/pipeline/theme_generation.py`)

**Purpose**: LLM arranges curated articles into a newsletter theme structure using `%XX_` markers.

### Functions

**`generate_themes(summaries_json, session, *, model) -> ThemeGenerationResult`**
1. Fetch learning data from `notes` table (last 40, type='user_newsletter_themes')
2. **LLM call** (`LLMPurpose.THEME`): `build_theme_generation_prompt()` with summaries JSON + feedback
3. Split output on `"-----"` delimiter via `split_themes()`
4. For each theme block: extract `%FA_`, `%M1_`, `%M2_`, `%Q1_-Q3_`, `%I1_-I2_`, `%RV_` markers via `parse_markers()`
5. Return `ThemeGenerationResult` with all themes + recommendation

### Marker System

The LLM outputs structured `%XX_FIELD: value` markers that get parsed into typed dataclasses:

```
%FA_TITLE: AI-Powered Code Review Tools Transform Developer Workflows
%FA_SOURCE: TechCrunch
%FA_URL: https://example.com/article
%FA_CATEGORY: AI Tools
%FA_WHY FEATURED: First comprehensive study...
%M1_TITLE: ...
%M1_SOURCE: ...
...
%Q1_TITLE: ...
%I1_TITLE: ...
%RV_2-2-2 Distribution Achieved: Yes
```

Article slots: 1 Featured Article, 2 Main Articles, 3 Quick Hits, 2 Industry Developments.

### Key Types

```python
@dataclass(frozen=True)
class GeneratedTheme:
    theme_name: str | None
    theme_description: str | None
    theme_body: str                   # raw text with markers
    formatted_theme: FormattedTheme   # parsed structured data

@dataclass(frozen=True)
class ThemeGenerationResult:
    themes: list[GeneratedTheme]
    recommendation: str
    raw_llm_output: str
    model: str
```

### Context Writes

| Field | Value |
|---|---|
| `ctx.formatted_theme` | Dict with article assignments (from `parse_markers`) |
| `ctx.theme_name` | Selected theme name |
| `ctx.theme_body` | Raw theme body text |
| `ctx.theme_summary` | Theme description |

### Theme Selection (in `steps.py`)

The step adapter in `steps.py` wraps `generate_themes()` with three nested interactive loops:

1. **Outer loop**: generate themes → share in Slack
2. **Selection loop**: Slack radio buttons, handle feedback (store, regenerate)
3. **Approval loop**: approve/reject/reset flows

After selection, runs freshness check via **`LLMPurpose.THEME_FRESHNESS_CHECK`** (`google/gemini-2.5-flash`) to compare against recent newsletters.

### LLM Calls

| Purpose | Model | When |
|---|---|---|
| `THEME` | Claude Sonnet 4.5 | Generate 2 themes with markers |
| `THEME_FRESHNESS_CHECK` | Gemini 2.5 Flash | Compare selected theme against recent newsletters |

---

## Step 4: Markdown Generation (`ica/pipeline/markdown_generation.py`)

**Purpose**: Generate full newsletter body in branded editorial voice with 3-layer validation.

### Functions

**`generate_with_validation(formatted_theme, *, aggregated_feedback, generation_model, validator_model, max_attempts=3) -> str`**

Validation loop (up to 3 attempts):
1. **LLM call** (`LLMPurpose.MARKDOWN`): generate markdown from formatted theme + feedback
2. **Layer 1** — Character count validation (code-based): `validate_character_counts()` → per-section errors
3. **Layer 2** — Structural validation (LLM): `run_structural_validation()` → merges Layer 1 errors
4. **Layer 3** — Voice validation (LLM): `run_voice_validation()` → merges all prior errors
5. If valid or attempts exhausted → return markdown
6. Else → feed merged errors back to LLM for correction

**`run_markdown_review(markdown, formatted_theme, *, slack, docs, session, newsletter_id) -> MarkdownGenerationResult`**

User feedback loop:
1. Share markdown in Slack
2. Approval form: "Yes" / "Provide Feedback" / "Restart Chat"
3. **Yes** → create Google Doc, share link, return
4. **Provide Feedback** → collect feedback → regenerate → extract learning note → store → re-share
5. **Restart Chat** → reset, re-share

### 3-Layer Validation System

| Layer | Method | Model | Checks |
|---|---|---|---|
| 1. Character Counts | `validate_character_counts()` (code) | None | Section-specific char ranges (see below) |
| 2. Structural | `run_structural_validation()` | GPT-4.1 | Headings, formatting, CTA patterns |
| 3. Voice | `run_voice_validation()` | GPT-4.1 | Tone, contractions, authority, humor |

Errors from all layers are merged before feeding back to the generation LLM.

### Character Count Rules (`ica/validators/character_count.py`)

**Quick Highlights**: 3 bullets, each 150-190 chars

**Featured Article**: Paragraph 1: 300-400, Paragraph 2: 300-400, Key Insight (bold-start): 300-370

**Main Article 1 & 2**: Callout (bold-label `**Label:**`): 180-250, Content paragraph: max 750

`validate_character_counts(raw) -> list[CharacterCountError]`:
- Extracts sections via regex: `#\s*\*?{SECTION_NAME}\*?\s*\n(content)(?=\n#\s*\*?|$)`
- Strips subheadings (`##\s+...`)
- Extracts CTA lines (containing `→`)
- Splits paragraphs on blank lines
- Finds callout via bold-label pattern (`^(\*\*|\*)[^*]+:\1`)

Error format: `"{section} – {field} – current={N} – target={MIN}–{MAX} – delta={±D}"`

### Context Writes

| Field | Value |
|---|---|
| `ctx.markdown_doc_id` | Google Doc ID |

### LLM Calls

| Purpose | Model | When |
|---|---|---|
| `MARKDOWN` | Claude Sonnet 4.5 | Generate/regenerate markdown |
| `MARKDOWN_VALIDATOR` | GPT-4.1 | Structural & voice validation |
| `MARKDOWN_REGENERATION` | Claude Sonnet 4.5 | User feedback regeneration |
| `MARKDOWN_LEARNING_DATA` | Claude Sonnet 4.5 | Extract learning note |

---

## Step 5: HTML Generation (`ica/pipeline/html_generation.py`)

**Purpose**: Convert approved markdown to responsive, inline-CSS email HTML.

### Function

**`run_html_generation(markdown_content, html_template, newsletter_date, *, slack, docs, session, newsletter_id) -> HtmlGenerationResult`**

1. Fetch learning data from `notes` table (last 40, type='user_htmlgenerator')
2. **LLM call** (`LLMPurpose.HTML`): `build_html_generation_prompt()` with markdown + template + date + feedback
3. Create Google Doc with HTML output
4. User review loop:
   - Share Google Doc link in Slack
   - **Yes** → return result
   - **Provide Feedback** →
     - **LLM call** (`LLMPurpose.HTML_REGENERATION`): scoped rewrite (only mentioned sections)
     - **LLM call** (`LLMPurpose.HTML_LEARNING_DATA`): extract note
     - DB write, update Google Doc, re-share

### Context Writes

| Field | Value |
|---|---|
| `ctx.html_doc_id` | Google Doc ID |

### Data Source

Fetches markdown content from Google Doc using `ctx.markdown_doc_id` (from Step 4). This means manual edits made in the Google Doc are incorporated.

### LLM Calls

| Purpose | When |
|---|---|
| `HTML` | Generate HTML from markdown + template |
| `HTML_REGENERATION` | Scoped regeneration on feedback |
| `HTML_LEARNING_DATA` | Extract learning note |

---

## Step 6a: Alternates HTML (`ica/pipeline/alternates_html.py`)

**Purpose**: Identify unused articles for an A/B email variant.

### Function

**`filter_unused_articles(formatted_theme, summaries) -> FilterResult`**

1. Extract all URLs from `formatted_theme` via recursive walk (case-insensitive "URL" key matching)
2. Filter `summaries` to those whose URL is not in the extracted set
3. Return `FilterResult` with unused summaries and URLs in theme

```python
@dataclass
class FilterResult:
    formatted_theme: dict[str, Any]
    unused_summaries: list[dict[str, Any]]
    urls_in_theme: list[str]
```

### LLM Calls: None
### Human Interaction: None (automated filtering)

---

## Step 6b: Email Subject & Preview (`ica/pipeline/email_subject.py`)

**Purpose**: Generate email subject options, select one, generate preview text.

### Function

**`run_email_subject_generation(html_doc_id, *, slack, docs, session, newsletter_id) -> EmailSubjectResult`**

**Phase 1 — Subject Generation:**
1. Fetch HTML from Google Doc, strip to plain text via `strip_html_to_text()`
2. Fetch learning data (last 40, type='user_email_subject')
3. **LLM call** (`LLMPurpose.EMAIL_SUBJECT`): generate subject options
4. Parse via `parse_subjects()` → extract Subject_N patterns + recommendation
5. Display in Slack with Block Kit
6. Selection form: radio buttons (Subject 1-N) + optional feedback textarea
7. If "Add Feedback" → extract learning note → store → regenerate → loop
8. If subject selected → proceed to Phase 2

**Phase 2 — Review Generation:**
1. **LLM call** (`LLMPurpose.EMAIL_PREVIEW`): generate email review/preview text
2. Display in Slack
3. Approval form: Approve / Reset All / Add Feedback
4. **Approve** → create Google Doc, return
5. **Add Feedback** → regenerate review with notes → loop
6. **Reset All** → clear feedback, restart Phase 1

### Context Writes (via `ctx.extra`)

| Key | Value |
|---|---|
| `email_subject` | Selected subject line |
| `email_review` | Preview text |
| `email_subject_doc_id` | Google Doc ID |

### LLM Calls

| Purpose | When |
|---|---|
| `EMAIL_SUBJECT` | Generate subject options |
| `EMAIL_PREVIEW` | Generate review/preview text |
| `EMAIL_SUBJECT_REGENERATION` | Extract learning note from feedback |

---

## Step 6c: Social Media (`ica/pipeline/social_media.py`)

**Purpose**: Generate 12 graphics-only social posts, select subset, generate captions.

### Function

**`run_social_media_generation(html_doc_id, formatted_theme, *, slack, docs) -> SocialMediaResult`**

**Phase 1 — Post Generation:**
1. Slack `send_and_wait` approval to proceed
2. Fetch HTML from Google Doc
3. **LLM call** (`LLMPurpose.SOCIAL_MEDIA`): generate 12 posts (6 "Did You Know" + 6 "Industry Take")
4. Share in Slack
5. "Yes" / "Regenerate" form → regenerate loops back
6. Post selection: checkbox form to pick posts to develop
7. Parse selected posts: extract title, source, graphic info, emphasis, graphic text
8. Resolve source URLs from `formatted_theme` via `get_source_url()`

**Phase 2 — Caption Generation:**
1. **LLM call** (`LLMPurpose.SOCIAL_POST_CAPTION`): generate captions (150-300 chars per post)
2. Share in Slack
3. "Yes" / "Provide Feedback" / "Restart Chat" form
4. **Provide Feedback** → **LLM call** (`LLMPurpose.SOCIAL_MEDIA_REGENERATION`) → loop
5. **Restart Chat** → re-fetch HTML, restart from Phase 2

**Final Selection:**
1. Checkbox form to select final posts
2. Filter caption output to selected posts
3. Create Google Doc, share link

### Key Types

```python
@dataclass(frozen=True)
class ParsedPost:
    title: str           # "DYK #1 — Headline"
    post_type: str       # "DYK" or "IT"
    number: int
    headline: str
    source: str
    source_url: str
    graphic_info: str
    emphasis: str
    graphic_text: str
```

### LLM Calls

| Purpose | When |
|---|---|
| `SOCIAL_MEDIA` | Generate 12 posts |
| `SOCIAL_POST_CAPTION` | Generate captions for selected posts |
| `SOCIAL_MEDIA_REGENERATION` | Regenerate captions on feedback |

---

## Step 6d: LinkedIn Carousel (`ica/pipeline/linkedin_carousel.py`)

**Purpose**: Generate carousel content (post copy + ~10 slides) with character validation.

### Function

**`run_linkedin_carousel_generation(html_doc_id, formatted_theme, *, slack, docs) -> LinkedInCarouselResult`**

1. Slack `send_and_wait` approval to proceed
2. Fetch HTML from Google Doc

**Generation + Validation Loop (max 2 attempts):**
3. **LLM call** (`LLMPurpose.LINKEDIN`): generate carousel markdown
4. Character validation: `validate_slide_bodies()` — parse `*Body:*` sections, count chars (with -4 offset), check 265-315 range per slide
5. Annotate output with `*Character count: N characters*` after each body
6. If valid → proceed. If exhausted → force-accept. Else → inject error JSON → retry

**User Review Loop:**
7. Share in Slack
8. "Yes" / "Regenerate" / "Provide Feedback" form
9. **Yes** → create Google Doc, return
10. **Regenerate** → re-fetch HTML, restart validation loop
11. **Provide Feedback** → **LLM call** (`LLMPurpose.LINKEDIN_REGENERATION`) without validation → loop

### Slide Validation

```python
@dataclass(frozen=True)
class SlideError:
    slide_body: str
    actual_characters: int
    required_range: str = "265-315"
    error_type: str = "CHARACTER_LIMIT_VIOLATION"
    severity: str = "ERROR"
```

Error details formatted as JSON dict for injection into retry prompt.

### LLM Calls

| Purpose | When |
|---|---|
| `LINKEDIN` | Generate carousel |
| `LINKEDIN_REGENERATION` | Regenerate on user feedback |

---

## Article Collection (`ica/pipeline/article_collection.py`)

**Purpose**: Scheduled job for article discovery via SearchApi. Runs independently of the pipeline.

### Function

**`collect_articles(client, repository, *, schedule="daily", reference_date=None) -> CollectionResult`**

1. **Keyword selection** by schedule:

| Schedule | Engine | Keywords | Results/Keyword |
|---|---|---|---|
| `daily` | `google_news` | AGI, Automation, Artificial Intelligence | 15 |
| `every_2_days` | `default` | AI breakthrough, AI latest, AI tutorial, AI case study, AI research | 10 |

2. Search via `SearchApiClient.search_keywords()` → collect raw results
3. Deduplicate by URL (first occurrence wins)
4. Parse relative dates ("2 days ago") via `parse_relative_date()`
5. Upsert `ArticleRecord` objects to PostgreSQL

```python
@dataclass
class CollectionResult:
    raw_results: list[SearchResult]
    deduplicated: list[SearchResult]
    articles: list[ArticleRecord]
    rows_affected: int
```

### LLM Calls: None
### Human Interaction: None (scheduled, automated)

---

## Prompt Builder System (`ica/prompts/`)

All prompt builders follow the same pattern:

1. Call `get_process_prompts("{process_name}")` → load system + instruction from JSON config
2. Inject runtime parameters into instruction template via `.format()`
3. Return `(system_prompt, user_prompt)` tuple

### Feedback Injection Pattern

Steps with feedback support use a `{feedback_section}` placeholder in the instruction template:

```python
if aggregated_feedback:
    feedback_section = f"## Editorial Improvement Context\n{aggregated_feedback}\n..."
else:
    feedback_section = ""
user_prompt = instruction.format(feedback_section=feedback_section, ...)
```

The `aggregated_feedback` string comes from `get_recent_notes(session, type_string, limit=40)` — the last 40 feedback entries for that step, formatted as bullet points.

### Complete Builder Inventory

| Process | File | Function | Runtime Inputs |
|---|---|---|---|
| Summarization | `summarization.py` | `build_summarization_prompt()` | article_content, aggregated_feedback |
| Summarization Regen | `summarization.py` | `build_summarization_regeneration_prompt()` | original_text, user_feedback |
| Theme Generation | `theme_generation.py` | `build_theme_generation_prompt()` | summaries_json, aggregated_feedback |
| Markdown Generation | `markdown_generation.py` | `build_markdown_generation_prompt()` | formatted_theme, aggregated_feedback, previous_markdown, validator_errors |
| Markdown Regen | `markdown_generation.py` | `build_markdown_regeneration_prompt()` | original_markdown, user_feedback |
| Structural Validation | `markdown_structural_validation.py` | `build_structural_validation_prompt()` | markdown_content, char_errors (JSON) |
| Voice Validation | `markdown_voice_validation.py` | `build_voice_validation_prompt()` | markdown_content, prior_errors_json |
| HTML Generation | `html_generation.py` | `build_html_generation_prompt()` | markdown_content, html_template, newsletter_date, aggregated_feedback |
| HTML Regen | `html_generation.py` | `build_html_regeneration_prompt()` | previous_html, markdown_content, html_template, user_feedback, newsletter_date |
| Email Subject | `email_subject.py` | `build_email_subject_prompt()` | newsletter_text, aggregated_feedback |
| Email Review | `email_review.py` | `build_email_review_prompt()` | newsletter_text, user_review_feedback |
| Social Media Posts | `social_media.py` | `build_social_media_post_prompt()` | newsletter_content, formatted_theme JSON |
| Social Media Captions | `social_media.py` | `build_social_media_caption_prompt()` | posts_json, featured/main/quick/industry article JSONs |
| Social Media Regen | `social_media.py` | `build_social_media_regeneration_prompt()` | feedback_text, previous_captions |
| LinkedIn Carousel | `linkedin_carousel.py` | `build_linkedin_carousel_prompt()` | formatted_theme JSON, newsletter_content, previous_output |
| LinkedIn Regen | `linkedin_carousel.py` | `build_linkedin_regeneration_prompt()` | previous_output, feedback_text, formatted_theme JSON, newsletter_content |
| Learning Data | `learning_data_extraction.py` | `build_learning_data_extraction_prompt()` | feedback, input_text, model_output |
| Freshness Check | `freshness_check.py` | `build_freshness_check_prompt()` | selected_theme, recent_themes |

---

## Learning Feedback System

Every content step (2-6) participates in a learning loop:

```
User feedback → LLM extracts structured note → Stored in notes table
                                                     ↓
Future runs ← Last 40 notes injected into prompts ←─┘
```

### Database Flow

1. **Read**: `get_recent_notes(session, note_type, limit=40)` — fetches most recent 40 notes of given type
2. **Format**: Aggregated as bullet-point string for prompt injection via `{feedback_section}`
3. **On feedback**:
   - LLM call with `LLMPurpose.*_LEARNING_DATA` to distill feedback into 2-3 sentence actionable insight
   - `add_note(session, note_type, text, newsletter_id)` to persist

### Note Types

| Type Discriminator | Step |
|---|---|
| `user_summarization` | Step 2 |
| `user_newsletter_themes` | Step 3 |
| `user_markdowngenerator` | Step 4 |
| `user_htmlgenerator` | Step 5 |
| `user_email_subject` | Step 6b |

---

## Slack Interaction Patterns

Three patterns used across all steps:

### 1. Approval (sendAndWait)
Post button → block until clicked → return nothing. Used for: Step 1 article approval, Steps 6c/6d initial proceed.

### 2. Form (sendAndWait_form)
Post trigger button → open modal with fields → block until submitted → return field values dict. Used for: Steps 2/4/5 feedback dropdown, Step 6b subject selection radio + textarea, Step 6c/6d action selection.

### 3. Freetext (sendAndWait_freetext)
Post trigger button → open modal with textarea → block until submitted → return text string. Used for: all feedback collection.

---

## Google Docs Workflow

| Step | Action | Doc Stored In |
|---|---|---|
| Step 4 | Create markdown doc | `ctx.markdown_doc_id` |
| Step 5 | Fetch markdown doc, create HTML doc | `ctx.html_doc_id` |
| Step 6b | Fetch HTML doc, create subject/review doc | `ctx.extra["email_subject_doc_id"]` |
| Step 6c | Fetch HTML doc, create social media doc | `ctx.extra["social_media_doc_id"]` |
| Step 6d | Fetch HTML doc, create carousel doc | `ctx.extra["linkedin_carousel_doc_id"]` |

Google Doc links are shared in Slack after creation. Manual edits in the Google Doc (especially Step 4 → Step 5) are incorporated when fetched.

---

## Error & Retry Summary

| Step | Retry Mechanism | Max Attempts |
|---|---|---|
| Step 1 | Sheet validation re-prompt | Unlimited (until valid) |
| Step 2 | User feedback regeneration | Unlimited (until "Yes") |
| Step 3 | Theme regeneration on feedback | Unlimited (until approved) |
| Step 4 | Validation retry loop | 3 (then force-accept) |
| Step 4 | User feedback regeneration | Unlimited (until "Yes") |
| Step 5 | User feedback regeneration | Unlimited (until "Yes") |
| Step 6b | Subject regeneration | Unlimited (feedback or reset) |
| Step 6c | Post regeneration (Phase 1) | Unlimited ("Regenerate" loops) |
| Step 6c | Caption regeneration (Phase 2) | Unlimited (feedback or restart) |
| Step 6d | Slide character validation | 2 (then force-accept) |
| Step 6d | User feedback regeneration | Unlimited ("Provide Feedback" loops) |

All retry loops except code-based validation use `ValidationLoopCounter` or equivalent loop-breaker patterns to prevent runaway LLM calls.
