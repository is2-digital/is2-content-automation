# PRD: IS2-News Python Application

## Context

IS2-News is currently an n8n-based workflow automation platform for AI newsletter generation. It consists of 12 interconnected workflows (1 main orchestrator, 8 subworkflows, 2 utilities, 1 article curation scheduler) totaling ~151 nodes across ~500KB of JSON. The system uses human-in-the-loop approvals via Slack, AI content generation via OpenRouter, data persistence in PostgreSQL, and document management via Google Docs/Sheets.

This PRD captures every functional detail needed to rebuild IS2-News as a standalone Python application that replicates the full behavior of the n8n system.

---

## 1. System Overview

### 1.1 Purpose
Automated AI newsletter generation pipeline with human editorial oversight. Produces a weekly newsletter including HTML email, markdown document, email subject/preview text, social media posts, and LinkedIn carousel content.

### 1.2 Execution Flow
```
Trigger (Manual or Scheduled every 5 days)
    │
    ▼
[1] Article Curation (human approval via Slack + Google Sheets)
    │
    ▼
[2] Summarization (LLM-powered, per-article, with feedback loop)
    │
    ▼
[3] Theme Generation (2 themes generated, human selects, freshness check)
    │
    ▼
[4] Markdown Generation (LLM + automated validation + 3-attempt retry loop)
    │
    ▼
[5] HTML Generation (markdown-to-HTML conversion, human review)
    │
    ├──▶ [6a] Alternates HTML (A/B variant)
    ├──▶ [6b] Email Subject & Preview (subject line + preview text)
    ├──▶ [6c] Social Media Posts (graphics + captions)
    └──▶ [6d] LinkedIn Carousel (multi-slide format)
```

Steps 6a-6d run **in parallel** after HTML generation completes.

### 1.3 Background: Article Collection Utility
A separate scheduled job runs independently:
- **Daily**: Searches SearchApi (google_news engine) for keywords: "Artificial General Intelligence", "Automation", "Artificial Intelligence"
- **Every 2 days**: Searches SearchApi (default engine) for keywords: "AI breakthrough", "AI latest", "AI tutorial", "AI case study", "AI research"
- Results are deduplicated by URL, date-parsed from relative formats ("3 days ago"), and inserted into `curated_articles` table

---

## 2. External Services & Integrations

### 2.1 SearchApi (searchapi.io)
- **Purpose**: Article discovery for curation
- **Engines**: `google_news` (daily) and default search (every 2 days)
- **Parameters**: `time_period=last_week`, `num=10-15`, `location=United States`
- **Cost**: ~$40/month (1000 queries/month)
- **Response format**: `organic_results[]` array with `link`, `title`, `date` fields

### 2.2 PostgreSQL
- **Database**: `n8n_custom_data`
- **User**: `n8n_custom_data_user`
- **Tables** (7 total):
  ```sql
  curated_articles (
    url TEXT PRIMARY KEY,
    title TEXT,
    origin TEXT,
    publish_date DATE,
    approved BOOLEAN,
    industry_news BOOLEAN,
    newsletter_id TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
  )

  summarization_user_feedback (
    id SERIAL PRIMARY KEY,
    feedback_text TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
  )

  newsletter_themes (
    theme TEXT PRIMARY KEY,
    theme_body TEXT,
    theme_summary TEXT,
    newsletter_id TEXT,
    approved BOOLEAN,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
  )

  newsletter_themes_user_feedback (
    id SERIAL PRIMARY KEY,
    feedback_text TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    newsletter_id TEXT
  )

  markdowngenerator_user_feedback (
    id SERIAL PRIMARY KEY,
    feedback_text TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
  )

  htmlgenerator_user_feedback (
    id SERIAL PRIMARY KEY,
    feedback_text TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
  )

  newsletter_email_subject_feedback (
    id SERIAL PRIMARY KEY,
    feedback_text TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    newsletter_id TEXT
  )
  ```

### 2.3 Google Sheets
- **Spreadsheet**: `Newsletter Curated Articles` (ID: `1TPHgLaLUJjL92V5k7uI7P4_mou3-wzoclFhxnCeBMP8`)
- **Sheet**: `Sheet1` (gid=0)
- **Columns**: url, title, publish_date, origin, approved, newsletter_id, industry_news
- **Operations**: Clear all rows, append/update rows, fetch rows with filter (approved=yes)
- **Auth**: OAuth2 (`googleSheetsOAuth2Api`)

### 2.4 Google Docs
- **Purpose**: Store generated content for human editing and sharing
- **Documents created**: Markdown newsletter, HTML newsletter, alternative HTML, email subjects, social media posts, LinkedIn carousel
- **Operations**: Create document, insert content, fetch document content
- **Auth**: OAuth2 (`googleDocsOAuth2Api`)

### 2.5 Slack
- **Channel**: `#n8n-is2`
- **Operations**:
  - `sendAndWait` — blocking messages that pause workflow until user responds (forms, approvals, free-text feedback)
  - `message` — non-blocking notifications and content sharing
- **Form types**: Dropdown selects, radio buttons, free-text areas, approve/deny buttons
- **Auth**: Slack API token (`slackApi`)

### 2.6 OpenRouter (LLM Provider)
- **API**: OpenRouter API for LLM access
- **Models used** (configurable via global config):
  ```
  LLM_SUMMARY_MODEL: anthropic/claude-sonnet-4.5
  LLM_SUMMARY_REGENERATION_MODEL: anthropic/claude-sonnet-4.5
  LLM_SUMMARY_LEARNING_DATA_MODEL: anthropic/claude-sonnet-4.5
  LLM_MARKDOWN_MODEL: anthropic/claude-sonnet-4.5
  LLM_MARKDOWN_VALIDATOR_MODEL: openai/gpt-4.1
  LLM_MARKDOWN_REGENERATION_MODEL: anthropic/claude-sonnet-4.5
  LLM_MARKDOWN_LEARNING_DATA_MODEL: anthropic/claude-sonnet-4.5
  LLM_HTML_MODEL: anthropic/claude-sonnet-4.5
  LLM_HTML_REGENERATION_MODEL: anthropic/claude-sonnet-4.5
  LLM_HTML_LEARNING_DATA_MODEL: anthropic/claude-sonnet-4.5
  LLM_THEME_MODEL: anthropic/claude-sonnet-4.5
  LLM_THEME_LEARNING_DATA_MODEL: anthropic/claude-sonnet-4.5
  LLM_THEME_FRESHNESS_CHECK_MODEL: google/gemini-2.5-flash
  LLM_SOCIAL_MEDIA_MODEL: anthropic/claude-sonnet-4.5
  LLM_SOCIAL_POST_CAPTION_MODEL: anthropic/claude-sonnet-4.5
  LLM_SOCIAL_MEDIA_REGENERATION_MODEL: anthropic/claude-sonnet-4.5
  LLM_LINKEDIN_MODEL: anthropic/claude-sonnet-4.5
  LLM_LINKEDIN_REGENERATION_MODEL: anthropic/claude-sonnet-4.5
  LLM_EMAIL_SUBJECT_MODEL: anthropic/claude-sonnet-4.5
  LLM_EMAIL_SUBJECT_REGENERATION_MODEL: anthropic/claude-sonnet-4.5
  LLM_EMAIL_PREVIEW_MODEL: anthropic/claude-sonnet-4.5
  ```
- **Auth**: OpenRouter API key

### 2.7 HTTP Web Fetching
- **Purpose**: Fetch article page content for summarization
- **Headers**: User-Agent (Safari/537.36), Accept (text/html), Accept-Language (en-US), Referer (google.com), Connection (keep-alive)
- **Skip conditions**: Error response, captcha detected (`sgcaptcha` in body), YouTube URLs

---

## 3. Detailed Step Specifications

### 3.1 Step 1: Article Curation Subworkflow

**Trigger**: Called by main orchestrator (passthrough mode)

**Process**:
1. Send Slack notification: "Looking into articles now and starting summarization..."
2. Clear Google Sheet (all existing rows)
3. Fetch unapproved articles from PostgreSQL: `SELECT * FROM curated_articles WHERE approved = false`
4. Process dates to `MM/DD/YYYY` format; normalize `approved` field (false -> empty string for display)
5. Append all articles to Google Sheet
6. Send Slack approval request (sendAndWait) to `#n8n-is2`: "Please review and approve articles for newsletter"
7. After user responds, fetch articles from Google Sheet where `approved = "yes"`
8. Validate: Check that at least one article has `approved=yes` AND `newsletter_id` is non-empty
9. **If valid**: Proceed to next step
10. **If invalid**: Send Slack re-validation message and loop back to step 7

**Output data**: Array of article objects:
```json
{
  "url": "string",
  "title": "string",
  "publish_date": "MM/DD/YYYY",
  "origin": "string",
  "approved": true,
  "newsletter_id": "string",
  "industry_news": true
}
```

### 3.2 Step 2: Summarization Subworkflow

**Trigger**: Receives approved articles from Step 1

**Process**:
1. Call LLM Global Config utility to get model names
2. Fetch approved articles from Google Sheet (filter: approved=yes)
3. Map fields (normalize `approved` and `industry_news` to boolean)
4. Build SQL INSERT/UPSERT into `curated_articles` table
5. Create tables if not exist (`curated_articles`, `summarization_user_feedback`)
6. **Loop over each article** (one at a time via splitInBatches):
   a. Fetch page content via HTTP GET with browser-like headers
   b. **If fetch fails** (error, captcha, YouTube): Send Slack form asking user to paste article content manually
   c. Convert HTML to markdown text
   d. Fetch previous learning data from `summarization_user_feedback` table (last 40 entries)
   e. Aggregate feedback into bullet-point list
   f. Call LLM with summarization prompt (see Section 4.1) using model `LLM_SUMMARY_MODEL`
   g. Collect result and continue loop
7. Aggregate all summaries
8. Format output as Slack Block Kit structure with article summaries
9. Share summaries in Slack channel
10. Send Slack form: "Ready to proceed to next step?" with options: Yes / Provide Feedback / Restart Chat

**Feedback Loop** (if user selects "Provide Feedback"):
1. Send Slack free-text form: "Please provide feedback to improve summarized content"
2. Call LLM with regeneration prompt (model: `LLM_SUMMARY_REGENERATION_MODEL`) incorporating user feedback
3. Extract learning data from feedback via LLM (model: `LLM_SUMMARY_LEARNING_DATA_MODEL`)
4. Store learning feedback in `summarization_user_feedback` table
5. Return to step 9 (re-share and ask again)

**Output data**:
```json
{
  "articles": [
    {
      "URL": "string",
      "Title": "string",
      "Summary": "3-4 sentences",
      "BusinessRelevance": "2-3 sentences",
      "order": 1,
      "newsletter_id": "string",
      "industry_news": true
    }
  ]
}
```

### 3.3 Step 3: Theme Generation Subworkflow

**Trigger**: Receives summarized articles from Step 2

**Process**:
1. Call LLM Global Config utility
2. Create `newsletter_themes_user_feedback` table if not exists
3. Fetch learning data (last 40 entries from `newsletter_themes_user_feedback`)
4. Process user feedback: aggregate database feedback + any fresh Slack feedback
5. Call LLM with theme generation prompt (see Section 4.2) using model `LLM_THEME_MODEL`
   - Input: JSON array of summarized articles
   - Output: 2 themes with structured article assignments + recommendation
6. Parse LLM output: split by "-----" separator, extract theme title, summary, and body for each theme
7. Format themes for Slack display (convert `%FA_TITLE`, `%M1_SOURCE` etc. markers to readable format)
8. Build Slack form with radio buttons for theme selection + "Add Feedback" option + textarea for editor feedback
9. Share formatted themes in Slack channel
10. Send Slack form for theme selection

**Theme Selection** (if user selects a theme):
1. Extract selected theme data
2. Parse theme body into structured `formatted_theme` object:
   ```json
   {
     "THEME": "theme title",
     "FEATURED ARTICLE": { "Title": "...", "Source": "...", "URL": "...", "Category": "...", "Why Featured": "..." },
     "MAIN ARTICLE 1": { "Title": "...", "Source": "...", "URL": "...", "Category": "..." },
     "MAIN ARTICLE 2": { "Title": "...", "Source": "...", "URL": "...", "Category": "..." },
     "QUICK HIT 1": { "Title": "...", "Source": "...", "URL": "...", "Category": "..." },
     "QUICK HIT 2": { "Title": "...", "Source": "...", "URL": "...", "Category": "..." },
     "QUICK HIT 3": { "Title": "...", "Source": "...", "URL": "...", "Category": "..." },
     "INDUSTRY DEVELOPMENT 1": { "Title": "...", "Source": "...", "URL": "...", "Major AI Player": "..." },
     "INDUSTRY DEVELOPMENT 2": { "Title": "...", "Source": "...", "URL": "...", "Major AI Player": "..." },
     "REQUIREMENTS VERIFIED": { "2-2-2 Distribution": "...", "Source mix": "...", "Technical complexity": "...", "Major AI player coverage": "..." }
   }
   ```
3. Run freshness check: Call LLM (model: `LLM_THEME_FRESHNESS_CHECK_MODEL`) to compare theme against recent newsletters at is2digital.com/newsletters
4. Format and share selected theme + freshness report in Slack
5. Send final approval form: Approve / Reset Articles / Add Feedback

**Final Approval**:
- **Approve**: Save theme to `newsletter_themes` table, output `formatted_theme` to next step
- **Add Feedback**: Call LLM to edit theme based on feedback, then loop back to approval
- **Reset Articles**: Clear feedback and regenerate themes from scratch

**Feedback Loop** (if user selects "Add Feedback" from theme selection):
1. Process feedback via LLM (model: `LLM_THEME_LEARNING_DATA_MODEL`)
2. Store in `newsletter_themes_user_feedback` table
3. Regenerate themes with feedback incorporated

### 3.4 Step 4: Markdown Generation Subworkflow

**Trigger**: Receives `formatted_theme` from Step 3

**Process**:
1. Extract `formatted_theme` from input
2. Create `markdowngenerator_user_feedback` table if not exists
3. Call LLM Global Config utility
4. Fetch learning data (last 40 entries from `markdowngenerator_user_feedback`)
5. Aggregate feedback
6. Call LLM with markdown generation prompt (see Section 4.3) using model `LLM_MARKDOWN_MODEL`

**Validation Loop** (up to 3 attempts):
1. **Character Count Validation** (code-based, not LLM):
   - Quick Highlights: 3 bullets, 150-190 chars each
   - Featured Article Paragraph 1: 300-400 chars
   - Featured Article Paragraph 2: 300-400 chars
   - Featured Article Key Insight: 300-370 chars
   - Main Article Callout: 180-250 chars each
   - Main Article Content: max 750 chars each
   - Industry Developments: 200-280 chars each
   - Footer paragraphs: 200-550 chars each
   - Produces error array with `delta` values showing how many chars to add/remove

2. **Structural/Content Validation** (LLM, model: `LLM_MARKDOWN_VALIDATOR_MODEL`):
   - Quick Highlights: exactly 3 bullets, correct order (Featured -> Main 1 -> Main 2), data points, bold terms
   - Featured Article: clickable headline, separate paragraphs, key insight with bold label, CTA on own line ending with ->
   - Main Articles: one content + one callout paragraph, proper labels ("Strategic Take-away" or "Actionable Steps")
   - Industry Developments: exactly 2 items, clickable links, at least one major AI player
   - Footer: exact opening line "Alright, that's a wrap for the week!", exact closing "Thoughts?"

3. **Voice Validation** (LLM, model: `LLM_MARKDOWN_VALIDATOR_MODEL`):
   - Kevin's voice patterns (precision, direct authority, conversational, intellectual honesty, practical grounding, dry humor, strategic synthesis, bold formatting, directive language patterns)
   - Merges all errors from character count + structural + voice

4. **Format Error Output**: Parse combined errors, increment attempt counter
5. **If valid OR attempt >= 3**: Proceed to user review
6. **If invalid AND attempt < 3**: Feed errors back into LLM for targeted regeneration

**User Review**:
1. Share generated markdown in Slack (Block Kit format)
2. Send form: Yes / Provide Feedback / Restart Chat
3. **If Yes**: Create Google Doc, insert markdown content, share doc link in Slack, wait for user to finish editing, proceed
4. **If Provide Feedback**: Collect feedback, regenerate via LLM, extract learning data, store in DB, re-share
5. **If Restart Chat**: Loop back to beginning

**Output data**: Google Doc document ID + formatted_theme + summaries

### 3.5 Step 5: HTML Generation Subworkflow

**Trigger**: Receives markdown document ID + formatted_theme from Step 4

**Process**:
1. Extract document ID from input (recursive object traversal)
2. Fetch markdown content from Google Doc
3. Convert markdown to HTML
4. Call LLM (model: `LLM_HTML_MODEL`) to generate email HTML template from markdown
   - Must preserve email-compatible HTML structure
   - Inline CSS styling
   - Responsive design considerations
5. Create Google Doc with generated HTML
6. Share HTML preview in Slack
7. Send approval form: Yes / Provide Feedback

**Feedback Loop**: Same pattern as markdown (feedback -> regeneration -> learning data -> DB storage)

**Output data**: HTML document ID + formatted_theme + summaries (passed to all 4 parallel subworkflows)

### 3.6 Step 6a: Alternates HTML Generator (Parallel)

**Trigger**: Receives HTML document ID + formatted_theme

**Process**:
1. Fetch markdown document content
2. Convert to HTML
3. Modify HTML design/structure for A/B variant
4. Create Google Doc with alternative HTML
5. Notify user in Slack

### 3.7 Step 6b: Email Subject & Preview Generator (Parallel)

**Trigger**: Receives formatted_theme + newsletter content

**Process**:
1. Fetch learning data from `newsletter_email_subject_feedback` table
2. Fetch document content from Google Docs
3. Call LLM (model: `LLM_EMAIL_SUBJECT_MODEL`) to generate 3-5 subject line options with preview text
4. Parse output into selectable options
5. Share options in Slack
6. Send selection form (radio buttons for each option)
7. User selects preferred subject + preview
8. Store selection

**Feedback Loop**: Similar pattern with regeneration and learning data storage

### 3.8 Step 6c: Social Media Generator (Parallel)

**Trigger**: Receives HTML document ID + formatted_theme

**Process**:
1. Fetch HTML document content
2. **Phase 1**: Call LLM (model: `LLM_SOCIAL_MEDIA_MODEL`) to generate social media posts
   - 12 posts total: 6 "Did You Know" (DYK) + 6 "Industry Take" (IT)
   - Graphics-only format initially
3. Share options in Slack
4. User selects which posts to develop
5. **Phase 2**: Call LLM (model: `LLM_SOCIAL_POST_CAPTION_MODEL`) to generate detailed captions
   - Character limits: 150-300 chars per caption
6. Share captions in Slack for review

**Feedback Loop**: Feedback -> regeneration via `LLM_SOCIAL_MEDIA_REGENERATION_MODEL`

### 3.9 Step 6d: LinkedIn Carousel Generator (Parallel)

**Trigger**: Receives HTML document ID + formatted_theme

**Process**:
1. Fetch HTML document content
2. Send Slack notification
3. Call LLM (model: `LLM_LINKEDIN_MODEL`) for initial generation
4. Parse and validate output
5. **Character Validation** (code-based):
   - Article slide body: 265-315 chars total
   - Two paragraphs: P1 120-150 chars, P2 130-150 chars
   - TL;DR bullets: 8 total, ~50 chars each
6. **If errors**: Regenerate with error details (model: `LLM_LINKEDIN_REGENERATION_MODEL`)
7. Generate 3 LinkedIn post copy versions:
   - Opening hook: "*Feeling behind on AI?*" or variation
   - One sentence connecting to theme
   - Links + newsletter CTA
   - Brand CTA mentioning iS2 Digital
8. Create Google Doc with carousel content
9. Share in Slack for approval

**Article order** (must be preserved):
1. Featured Article -> 2. Main Article 1 -> 3. Main Article 2 -> 4-6. Quick Hits 1-3 -> 7-8. Industry Developments 1-2

---

## 4. LLM Prompts (Complete)

### 4.1 Summarization Prompt

```
You are a professional AI research editor and content analyst. Your task is to process news or blog articles that may be provided in HTML, Markdown, or plain text format according to strict editorial and data integrity standards.

Follow these protocols EXACTLY:

## Accuracy Control Protocol (MANDATORY)
1. Do NOT search for alternative sources.
2. Do NOT summarize partial or unavailable content.
3. Do NOT generate or infer missing details.

## Article Summary Standards
Summary Specifications:
- 3-4 sentences per article
- Focus strictly on factual content, key findings, and main conclusions
- Avoid editorial opinions or speculative tone
- Include specific statistics, methodologies, or technical details when mentioned

Business Relevance Specifications:
- 2-3 sentences per article
- Explain the broad business or strategic relevance across industries
- Consider an audience of solopreneurs and SMB professionals (without naming them)
- Emphasize practical implications for decision-making, operations, or strategy
- Avoid technical or industry-specific jargon

## Data Integrity Standards
- Extract only verified information directly from the article
- Quote or cite exact statistics or claims when possible
- Flag unverifiable data explicitly (e.g., "Statistic requires verification")
- Do NOT fabricate, infer, or supplement from external knowledge
- Well-established general knowledge does NOT require verification

{aggregated_feedback_section if feedback exists:
## Editorial Improvement Context (From Prior Feedback)
The following editorial preferences and improvement notes should guide your tone, structure, and summarization style:
{feedback}
Use this feedback to adjust language, flow, and focus - without altering factual accuracy or deviating from the core standards above.
}

## Output Format (MANDATORY)
Return clean plain text output (no markdown or bullet points) in this format:

URL: [article URL]
Title: [article title]
Summary: [3-4 sentence factual summary following Article Summary Standards]
Business Relevance: [2-3 sentence business relevance commentary following the same standards]

Now process the following content accordingly. The input may be HTML, Markdown, or plain text - automatically detect the format. If the content cannot be fully accessed, follow the Accuracy Control Protocol.

keep the output format consistent as plain text and not JSON object.

Input:
{article_content}
```

### 4.2 Summarization Regeneration Prompt

```
You are a professional content editor AI.
The original content is below:
{original_content}

The user has provided feedback as follows:
{user_feedback}

Please revise the content to incorporate the feedback. Maintain the formatting of the original content.

Maintain these protocols EXACTLY:

## Accuracy Control Protocol (MANDATORY)
1. Do NOT search for alternative sources.
2. Do NOT summarize partial or unavailable content.
3. Do NOT generate or infer missing details.
4. Incorporate ONLY the requested feedback. Do NOT rewrite, expand, or regenerate other sections unless the feedback directly requires it.

## Article Summary Standards
(same as above)

## Data Integrity Standards
(same as above)
```

### 4.3 Theme Generation Prompt

```
You are a professional AI research editor and content analyst. Your task is to process the summaries of articles that may be provided in JSON format.

Start by reviewing the article summaries, reading "Title", "Summary", "BusinessRelevance", "Order" fields for each item in json

Based on that data create and output viable two themes that meet all content distribution and source mix requirements and specifications listed next.

## Accuracy Control Protocol (MANDATORY)
1. Do NOT search for alternative sources.
2. Do NOT generate or infer missing details.
3. Use ONLY provided data in the json format.
4. If in the json source, items have field "industry_news" equal to "true" use that items to fill %I1 and %I2 fields

{aggregated_feedback if exists}

## Output Format (MANDATORY)
Return clean plain text output (no markdown or bullet points or colon) in this format for each created theme, do not duplicate titles for themes, do not rename THEME: subjects

THEME: [theme main title]
Theme Description: [1-3 sentence factual summary following core narrative]

Articles that fit.
FEATURED ARTICLE:
%FA_TITLE: [title from json source]
%FA_SOURCE: [order number from json]
%FA_ORIGIN: [author/source name]
%FA_URL: [url from json]
%FA_CATEGORY: [category based on summary]
%FA_WHY FEATURED: [rationale]

%M1_TITLE: / %M1_SOURCE: / %M1_ORIGIN: / %M1_URL: / %M1_CATEGORY: / %M1_RATIONALE:
%M2_TITLE: / %M2_SOURCE: / %M2_ORIGIN: / %M2_URL: / %M2_CATEGORY: / %M2_RATIONALE:
%Q1_TITLE: / %Q1_SOURCE: / %Q1_ORIGIN: / %Q1_URL: / %Q1_CATEGORY:
%Q2_TITLE: / %Q2_SOURCE: / %Q2_ORIGIN: / %Q2_URL: / %Q2_CATEGORY:
%Q3_TITLE: / %Q3_SOURCE: / %Q3_ORIGIN: / %Q3_URL: / %Q3_CATEGORY:
%I1_TITLE: / %I1_SOURCE: / %I1_ORIGIN: / %I1_URL: / %I1_Major AI Player:
%I2_TITLE: / %I2_SOURCE: / %I2_ORIGIN: / %I2_URL: / %I2_Major AI Player:

2-2-2 Distribution:
%222_tactical:% (Source N) [short description], (Source N) [short description]
%222_educational:% (Source N) [short description], (Source N) [short description]
%222_forward-thinking:% (Source N) [short description], (Source N) [short description]

Source mix:
%SM_smaller_publisher:% [publisher names + source numbers]
%SM_major_ai_player_coverage:% [title + source number]

REQUIREMENTS VERIFIED:
%RV_2-2-2 Distribution Achieved:% [verification]
%RV_Source mix:% [verification]
%RV_Technical complexity:% [verification]
%RV_Major AI player coverage:% [verification]

Put a separator string "-----" after each created theme.

RECOMMENDATION: Theme [number] - [theme name]
Rationale:
[5 section recommendations with explanations]
[3-4 sentences why this theme should be picked]

Input:
{articles_json}
```

### 4.4 Markdown Generation Prompt

The full markdown generation prompt is ~4000 words. Key sections:

**Voice Calibration - Kevin's Writing Patterns:**
1. **Precision as Principle** - Pushes back on imprecise terminology. Example: "But I want to **strongly caution** us in the language being used"
2. **Direct Authority Without Arrogance** - Declarative statements. Example: "The organizations successfully leveraging AI aren't deploying better models, they're building better frameworks"
3. **Conversational But Not Casual** - Contractions, professional authority. Uses "isn't", "aren't", "don't", "we're" freely
4. **Intellectual Honesty & Nuance** - Multiple perspectives. Uses "but" to introduce complexity
5. **Practical Grounding** - Concrete business outcomes, specific numbers, real examples
6. **Dry Humor & Memorable Observations** - Subtle, intelligent humor from technology observations
7. **Strategic Synthesis** - Thematic framing, not disconnected summaries
8. **Bold Formatting** - 2-4 times per section for key concepts
9. **Directive Language Patterns**:
   - Pattern A (PRIMARY): Declarative - "[Reality] isn't [misconception]. It's [insight]."
   - Pattern B: Evidence-Based - Show concrete examples without commands
   - Pattern C (CALLOUT ONLY): Recommendations grounded in evidence

**Required Markdown Structure:**
```
# *INTRODUCTION*
- Conversational opening paragraph
- *Italic theme summary* with business implications and *bold* emphasis

# *QUICK HIGHLIGHTS*
- 3 bullets, 150-190 chars each, 1-2 sentences, at least one *bold* term

# *FEATURED ARTICLE*
- Clickable link headline (REAL URL)
- Paragraph 1: 300-400 chars
- Paragraph 2: 300-400 chars
- Key Insight: bold two-word label, 300-370 chars
- CTA: own line, 2-4 words, ends with arrow

# *MAIN ARTICLE 1* / # *MAIN ARTICLE 2*
- Headline, content paragraph (max 750 chars)
- Callout (180-250 chars) with *Strategic Take-away:* or *Actionable Steps:*
- Source link (REAL URL)

# *QUICK HITS*
- 3 items, headline as link, 1-2 sentence summaries

# *INDUSTRY DEVELOPMENTS*
- 2 items, headline as link, 1-2 sentences, at least one major AI company

# *FOOTER*
- Reflective paragraph, tie back to theme, invite engagement
```

**Hard Constraints:**
- Use ONLY URLs from JSON input - never invent links
- If URL missing, omit link entirely
- Do not reference content not in input
- All sections must appear with exact headings

**Validator Error Handling:**
- When validator errors include `delta` values, adjust EXACTLY by that many characters
- Apply deltas mechanically, not stylistically
- Fix order: Featured P1 -> P2 -> Key Insight -> Main Articles -> Industry -> Footer
- Max 3 regeneration attempts before force-accepting

### 4.5 Markdown Structural Validation Prompt

```
You are a strict newsletter validator.

IMPORTANT (NON-NEGOTIABLE):
- ALL character length validation has already been computed upstream.
- You MUST NOT re-count characters or recalculate deltas.
- You MUST treat provided character errors as authoritative and final.

Your role is to:
1. Accept provided character errors exactly as-is
2. Validate all remaining non-numeric rules
3. Merge both into a single errors array

PROVIDED CHARACTER ERRORS (DO NOT MODIFY):
{charErrors}

YOUR VALIDATION SCOPE (NON-NUMERIC RULES ONLY):

QUICK HIGHLIGHTS:
- Exactly 3 bullets
- Order: Featured -> Main 1 -> Main 2
- Each starts with data point or factual claim
- Each contains at least one bolded key term

FEATURED ARTICLE:
- Headline must be clickable Markdown link
- Paragraphs must be separate
- Key Insight starts with bolded two-word label
- CTA on own line, 2-4 words, ends with arrow, no trailing punctuation

MAIN ARTICLES (1 & 2):
- One content paragraph + one callout paragraph
- Callout label: "Strategic Take-away" or "Actionable Steps"
- Clickable headline + source link

INDUSTRY DEVELOPMENTS:
- Exactly 2 items, single paragraph each
- Clickable link headlines, no arrows
- At least one major AI player (OpenAI, Google, Microsoft, Meta, Anthropic, Amazon)

FOOTER:
- Line 1: "Alright, that's a wrap for the week!"
- Final line: "Thoughts?"

OUTPUT: { "output": { "isValid": boolean, "errors": [] } }
```

### 4.6 Markdown Voice Validation Prompt

Evaluates voice consistency by section:
- **Introduction**: Striking opening, declarative language, 2-3 bold terms, contractions
- **Featured Article**: Active voice, specific data/numbers, bold 2-3 times, business implications
- **Main Articles**: Focused points, callout translation to action/implications, contractions
- **Overall**: Consistent contractions, direct reader address, professional authority, precision in terminology, concrete business outcomes, no generic "should/must" statements

### 4.7 Learning Data Extraction Prompt (shared across all subworkflows)

```
You are an AI assistant that converts raw user feedback into a short, structured summary
that can be stored as learning data for future content improvement.

You will be given:
- The original input text (the content or article summary prompt)
- The model output that was generated
- The user's feedback

Your goal:
1. Summarize the key points of the user's feedback into clear, actionable insights.
2. Keep the summary short (2-3 sentences max).
3. Focus on what should be improved next time (tone, accuracy, length, structure, detail).
4. If feedback is unclear or generic, infer the likely intent from context.

Feedback Data:
User Feedback: {feedback}
Input Provided: {input}
Model Output: {output}

Expected Output:
{ "learning_feedback": "Future responses should..." }
```

### 4.8 Freshness Check Prompt

```
I have created a text theme for my new newsletter,
please, check editorial freshness and if it's not repetitive to last newsletters,

I will provide the text theme text and a link to site where you can find recent newsletters

The text theme:
{theme_body}

Links to my site, on that page, you can find links to recent newsletters, one 3 most recent, and check against them:
https://www.is2digital.com/newsletters

As final output - give your results for this task as a structured output, and tell what to change if needed, try to explain why
```

---

## 5. Data Flow Between Steps

### 5.1 Step 1 -> Step 2
Articles array: `[{ url, title, publish_date, origin, approved, newsletter_id, industry_news }]`

### 5.2 Step 2 -> Step 3
Summarized articles: `[{ URL, Title, Summary, BusinessRelevance, order, newsletter_id, industry_news }]`

### 5.3 Step 3 -> Step 4
```json
{
  "selected_theme_title": "THEME: ...",
  "selected_theme": { "theme": "...", "theme_summary": "...", "theme_body": "..." },
  "summaries": ["..."],
  "formatted_theme": {
    "THEME": "...",
    "FEATURED ARTICLE": { "Title": "...", "Source": "...", "URL": "...", "Category": "...", "Why Featured": "..." },
    "MAIN ARTICLE 1": { "Title": "...", "Source": "...", "URL": "...", "Category": "..." },
    "MAIN ARTICLE 2": { "Title": "...", "Source": "...", "URL": "...", "Category": "..." },
    "QUICK HIT 1": { "Title": "...", "Source": "...", "URL": "...", "Category": "..." },
    "QUICK HIT 2": { "Title": "...", "Source": "...", "URL": "...", "Category": "..." },
    "QUICK HIT 3": { "Title": "...", "Source": "...", "URL": "...", "Category": "..." },
    "INDUSTRY DEVELOPMENT 1": { "Title": "...", "Source": "...", "URL": "...", "Major AI Player": "..." },
    "INDUSTRY DEVELOPMENT 2": { "Title": "...", "Source": "...", "URL": "...", "Major AI Player": "..." },
    "REQUIREMENTS VERIFIED": { "...": "..." }
  }
}
```

### 5.4 Step 4 -> Step 5
Google Doc document ID + all previous data (formatted_theme, summaries)

### 5.5 Step 5 -> Steps 6a-6d (all receive same data)
HTML Google Doc document ID + formatted_theme + summaries

---

## 6. Human-in-the-Loop Interactions

Every step has a consistent interaction pattern:

### 6.1 Pattern: Share -> Approve/Feedback
1. Share generated content in Slack
2. Present form with options (typically: Yes / Provide Feedback / Restart)
3. **Yes**: Proceed to next step
4. **Provide Feedback**: Collect free-text feedback -> regenerate -> extract learning data -> store in DB -> re-share
5. **Restart**: Clear state and regenerate from scratch

### 6.2 Pattern: Selection
Used in theme selection, email subject selection, social media post selection:
1. Share multiple options in Slack
2. Present radio-button form
3. User selects preferred option
4. Optionally: second approval step with feedback option

### 6.3 Pattern: Manual Data Entry
Used when article content cannot be fetched:
1. Send Slack form with article URL
2. User pastes article content manually
3. Continue with pasted content

### 6.4 Slack Message Formatting
- Uses Slack Block Kit for structured messages
- `mrkdwn` format with `*bold*`, `_italic_`
- Dividers between sections
- Forms use `sendAndWait` (blocking until user responds)

---

## 7. Error Handling

### 7.1 LLM Errors
- All LLM calls have error handling that routes errors to dedicated output
- Error message sent to Slack: "Execution Stopped at [step], due to the following error: [error], reach out to the concerned person to resolve the issue."
- Step terminates with descriptive error message

### 7.2 HTTP Fetch Errors
- Skip conditions: error response, captcha (`sgcaptcha`), YouTube URLs
- Fallback: Manual content entry via Slack form

### 7.3 Database Errors
- `ON CONFLICT (url) DO UPDATE` -- upsert pattern prevents duplicate key errors
- DB insert failures trigger retry of SQL generation

### 7.4 Validation Loop Breaker
- Markdown validation: max 3 attempts before force-accepting output
- Counter tracked per pipeline execution

---

## 8. Configuration System

### 8.1 LLM Global Config
Centralized model mapping returned as JSON object. Each pipeline step reads this config to get model names dynamically. This allows changing models in one place.

### 8.2 Environment Variables
```
POSTGRES_PASSWORD
POSTGRES_HOST
POSTGRES_PORT
POSTGRES_DB
POSTGRES_USER
OPENROUTER_API_KEY
SLACK_BOT_TOKEN
SLACK_APP_TOKEN
SLACK_CHANNEL
GOOGLE_SHEETS_CREDENTIALS_PATH
GOOGLE_DOCS_CREDENTIALS_PATH
SEARCHAPI_API_KEY
TIMEZONE=America/Los_Angeles
```

### 8.3 Credential References
- Google Sheets OAuth2
- Google Docs OAuth2
- Slack Bot token + App token (for Socket Mode)
- SearchApi API key
- OpenRouter API key (or direct provider keys via LiteLLM)
- PostgreSQL connection string

---

## 9. Key Business Logic

### 9.1 Date Processing
Convert dates to `MM/DD/YYYY` format for Google Sheets display. Parse relative dates from SearchApi ("3 days ago", "1 week ago") to actual calendar dates.

### 9.2 Theme Body Parser
Regex-based extraction of structured theme data from LLM plain-text output using `%FA_TITLE:`, `%M1_SOURCE:`, `%I2_Major AI Player:` etc. markers into a structured JSON object.

### 9.3 Markdown Section Extractor
Regex pattern to extract content between markdown headings:
```
Pattern: #\s*\*?{SECTION_NAME}\*?\s*\n(content)(?=\n#\s*\*?|$)
```

### 9.4 Character Count Validation
Section-by-section character counting with delta calculations (`current - target`) for targeted LLM corrections. Each error includes section name, field, current count, target range, and exact delta.

### 9.5 LinkedIn Carousel Slide Validation
Validates each slide body is 265-315 characters with two paragraphs (P1: 120-150, P2: 130-150). Produces error array with `CHARACTER_LIMIT_VIOLATION` type and instructions for the LLM.

### 9.6 Slack Block Kit Builder
Constructs structured Slack messages with sections, dividers, and formatted text blocks. Converts internal data structures to Slack `mrkdwn` format.

### 9.7 Theme Formatting for Slack Display
Complex regex-based replacement transforming `%XX_` markers to human-readable Slack format with bold labels, bullet points, and organized sections.

### 9.8 Conditional Output Routing
Determines whether to use original or regenerated content based on: user's form selection (switch_value), content validity check (e.g., `hasIntroduction`), and feedback processing status.

---

## 10. Non-Functional Requirements

### 10.1 Timing
- Main pipeline triggered manually or every 5 days
- Article collection: daily + every 2 days (separate scheduled job)
- Each step waits for human input (no hard timeouts)

### 10.2 Data Persistence
- All feedback stored in PostgreSQL for continuous learning
- Google Docs/Sheets for collaborative editing
- Theme and article data preserved across runs

### 10.3 Observability
- Slack notifications at each step
- Error messages with step identification
- Execution state tracked per run

---

## 11. Python Application Architecture

### 11.1 Application Type
**Primary**: Long-running service (FastAPI) with built-in scheduler, background task workers, and REST API for triggering/monitoring pipeline runs.
**Secondary**: CLI interface (`python -m is2news run`, `python -m is2news status`, etc.) for on-demand interaction and debugging.

### 11.2 Slack Integration
Keep Slack Bot API with interactive messages and Block Kit forms, matching current n8n behavior exactly. Use Slack Bolt for Python (slack-bolt) for:
- Sending messages and Block Kit structures
- `sendAndWait` equivalent: post message with interactive components, register callback handler, use asyncio.Event to block pipeline step until response received
- Forms: radio buttons, dropdowns, free-text via modals/message actions
- Channel: `#n8n-is2` (configurable)

### 11.3 LLM Integration
**Phase 1**: LiteLLM abstraction layer -- provides a unified interface to OpenRouter, direct Anthropic API, OpenAI, Google, and 100+ providers. Single `completion()` call regardless of backend.
**Phase 2**: If needed, add LangChain or custom orchestration for more complex prompt chaining, structured output parsing, and tool use.

The global LLM config (model mapping) becomes a Python config file/env vars that LiteLLM routes to the appropriate provider.

### 11.4 Proposed Project Structure
```
is2news/
├── pyproject.toml
├── .env.example
├── config/
│   ├── settings.py          # Pydantic Settings (env vars, DB, API keys)
│   └── llm_config.py        # LLM model mapping (replaces LLM Global Config utility)
├── is2news/
│   ├── __init__.py
│   ├── __main__.py           # CLI entry point
│   ├── app.py                # FastAPI application
│   ├── scheduler.py          # APScheduler for timed triggers
│   ├── pipeline/
│   │   ├── __init__.py
│   │   ├── orchestrator.py   # Main pipeline runner (sequential + parallel)
│   │   ├── article_curation.py
│   │   ├── summarization.py
│   │   ├── theme_generation.py
│   │   ├── markdown_generation.py
│   │   ├── html_generation.py
│   │   ├── alternates_html.py
│   │   ├── email_subject.py
│   │   ├── social_media.py
│   │   └── linkedin_carousel.py
│   ├── services/
│   │   ├── __init__.py
│   │   ├── llm.py            # LiteLLM wrapper with config
│   │   ├── slack.py          # Slack Bolt integration
│   │   ├── google_sheets.py  # Google Sheets API client
│   │   ├── google_docs.py    # Google Docs API client
│   │   ├── search_api.py     # SearchApi client
│   │   └── web_fetcher.py    # HTTP article content fetcher
│   ├── db/
│   │   ├── __init__.py
│   │   ├── models.py         # SQLAlchemy models (7 tables)
│   │   ├── session.py        # Database session management
│   │   └── migrations/       # Alembic migrations
│   ├── prompts/
│   │   ├── __init__.py
│   │   ├── summarization.py
│   │   ├── theme_generation.py
│   │   ├── markdown_generation.py
│   │   ├── markdown_validation.py
│   │   ├── voice_validation.py
│   │   ├── html_generation.py
│   │   ├── email_subject.py
│   │   ├── social_media.py
│   │   ├── linkedin_carousel.py
│   │   └── learning_data.py
│   ├── validators/
│   │   ├── __init__.py
│   │   ├── character_count.py  # Port of JS character validation
│   │   ├── markdown_structure.py
│   │   └── linkedin_slides.py
│   └── utils/
│       ├── __init__.py
│       ├── date_parser.py
│       ├── theme_parser.py   # Parse %FA_TITLE etc. markers
│       ├── slack_formatter.py # Block Kit builders
│       └── html_converter.py
├── tests/
│   ├── test_pipeline/
│   ├── test_services/
│   ├── test_validators/
│   └── fixtures/
└── docker-compose.yml        # PostgreSQL + app
```

### 11.5 Key Python Libraries
- **FastAPI** -- REST API + service framework
- **Slack Bolt** -- Slack Bot integration with interactive message handling
- **LiteLLM** -- Unified LLM interface (OpenRouter, Anthropic, OpenAI, etc.)
- **SQLAlchemy + Alembic** -- ORM + migrations for PostgreSQL
- **asyncpg** -- Async PostgreSQL driver
- **google-api-python-client + google-auth** -- Google Sheets/Docs
- **httpx** -- Async HTTP client for article fetching and SearchApi
- **APScheduler** -- Built-in scheduler for article collection and pipeline triggers
- **Pydantic Settings** -- Configuration management from env vars
- **Rich** -- CLI output formatting
- **Click or Typer** -- CLI framework

### 11.6 Pipeline Execution Model
Each pipeline step is an async function that:
1. Receives a `PipelineContext` object (accumulated state from previous steps)
2. Performs its work (LLM calls, DB operations, HTTP fetches)
3. Interacts with user via Slack (blocking on `asyncio.Event` until Slack callback fires)
4. Returns updated `PipelineContext` with its outputs

The orchestrator runs steps sequentially, then launches steps 6a-6d concurrently via `asyncio.gather()`.

```python
async def run_pipeline(trigger: str = "manual"):
    ctx = PipelineContext(trigger=trigger)
    ctx = await article_curation(ctx)
    ctx = await summarization(ctx)
    ctx = await theme_generation(ctx)
    ctx = await markdown_generation(ctx)
    ctx = await html_generation(ctx)
    # Parallel outputs
    await asyncio.gather(
        alternates_html(ctx),
        email_subject(ctx),
        social_media(ctx),
        linkedin_carousel(ctx),
    )
```

### 11.7 Slack Blocking Pattern
```python
# Equivalent to n8n's sendAndWait
async def send_and_wait(channel, message, form_config):
    event = asyncio.Event()
    response_data = {}

    # Register callback for this interaction
    callback_id = generate_id()
    pending_interactions[callback_id] = (event, response_data)

    # Send Slack message with interactive components
    await slack_client.chat_postMessage(
        channel=channel,
        blocks=build_blocks(message, form_config, callback_id)
    )

    # Block until user responds
    await event.wait()
    return response_data
```

---

## 12. Implementation Phases

### Phase 1: Foundation
- Project scaffolding (pyproject.toml, settings, Docker)
- PostgreSQL models + migrations (all 7 tables)
- LiteLLM wrapper with global config
- Slack Bolt integration with send/sendAndWait patterns
- Google Sheets and Google Docs service clients
- SearchApi and web fetcher clients
- CLI entry point + FastAPI skeleton

### Phase 2: Core Pipeline (Sequential)
- Article collection utility (scheduled job)
- Article curation step (Sheets + Slack + DB)
- Summarization step (HTTP fetch + LLM + feedback loop)
- Theme generation step (LLM + parsing + selection + freshness check)

### Phase 3: Content Generation
- Markdown generation step (LLM + 3-layer validation + retry loop)
- HTML generation step (markdown-to-HTML + LLM styling)
- Port all validation logic (character counts, structure, voice)
- Google Doc creation and sharing

### Phase 4: Parallel Outputs
- Alternates HTML generator
- Email subject & preview generator
- Social media generator (2-phase)
- LinkedIn carousel generator (with character validation)
- Concurrent execution via asyncio.gather

### Phase 5: Polish
- End-to-end testing
- Error handling and recovery
- Scheduler integration (APScheduler)
- CLI commands for status, manual trigger, restart at step
- Logging and observability

---

## 13. Verification Plan

After building the Python application:

1. **Article Collection**: Verify SearchApi integration returns articles, deduplication works, DB insertion succeeds
2. **Article Curation**: Verify Google Sheets sync, Slack approval flow, validation logic
3. **Summarization**: Verify per-article HTTP fetch, LLM calls, feedback storage, output format
4. **Theme Generation**: Verify theme parsing, structured output, freshness check, approval flow
5. **Markdown Generation**: Verify character count validation, structural validation, voice validation, 3-attempt loop, Google Doc creation
6. **HTML Generation**: Verify markdown-to-HTML conversion, LLM styling, Google Doc output
7. **Parallel outputs**: Verify all 4 run concurrently, each produces correct output
8. **End-to-end**: Run full pipeline with test articles, verify all Slack interactions, all documents created, all feedback loops functional
9. **Learning system**: Verify feedback is stored and incorporated in subsequent runs
