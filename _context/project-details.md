# IS2-News: Complete Project Analysis

This document contains the full technical analysis of the to be rebuilt IS2-News n8n workflow system, including every node, connection, code block, prompt, database query, and integration detail extracted from the source workflow JSON files.

---

## Table of Contents

1. [High-Level Architecture](#1-high-level-architecture)
2. [Main Orchestrator Workflow](#2-main-orchestrator-workflow)
3. [Curated AI Articles Utility](#3-curated-ai-articles-utility)
4. [Curated Articles Subworkflow](#4-curated-articles-subworkflow)
5. [Summarization Subworkflow](#5-summarization-subworkflow)
6. [Theme Generation Subworkflow](#6-theme-generation-subworkflow)
7. [Markdown Generator Subworkflow](#7-markdown-generator-subworkflow)
8. [HTML Generator Subworkflow](#8-html-generator-subworkflow)
9. [Alternates HTML Generator Subworkflow](#9-alternates-html-generator-subworkflow)
10. [Email Subject & Preview Subworkflow](#10-email-subject--preview-subworkflow)
11. [Social Media Generator Subworkflow](#11-social-media-generator-subworkflow)
12. [LinkedIn Carousel Generator Subworkflow](#12-linkedin-carousel-generator-subworkflow)
13. [LLM Global Config Utility](#13-llm-global-config-utility)
14. [Database Schema Details](#14-database-schema-details)
15. [Credential & Authentication Details](#15-credential--authentication-details)
16. [Docker & Infrastructure](#16-docker--infrastructure)
17. [Environment Variables](#17-environment-variables)
18. [Cross-Workflow Data Passing Patterns](#18-cross-workflow-data-passing-patterns)
19. [Node Type Inventory](#19-node-type-inventory)

---

## 1. High-Level Architecture

### Workflow Inventory

| # | File | Name | ID | Nodes | Purpose |
|---|------|------|----|-------|---------|
| 1 | `workflows/MAIN/newsletter_workflow.json` | Newsletter [workflow] | — | 10 | Primary orchestrator |
| 2 | `workflows/UTIL/curated_ai_articles_utility.json` | curated-ai-articles [UTIL] | dIT9HiTREUm0an1a | 11 | Scheduled article fetching |
| 3 | `workflows/UTIL/llm_global_config_utility.json` | LLM Global Config [UTIL] | O5I7T1oioeIBv0j4 | 3 | Centralized LLM model config |
| 4 | `workflows/SUB/curatedarticles_subworkflow.json` | Curated-Articles [sub-workflow] | BGCgCliQbEcIHT2r | 14 | Article curation + approval |
| 5 | `workflows/SUB/summarization_subworkflow.json` | Summarization [sub-workflow] | ScFeCWBc1yqWBUsD | 38 | AI article summarization |
| 6 | `workflows/SUB/theme_generation_subworkflow.json` | Theme Generation & Selection [Sub-Workflow] | GsUsHGEbssqrS05W | 38 | Theme creation + selection |
| 7 | `workflows/SUB/markdown_generator_subworkflow.json` | Markdown-Generator [sub-workflow] | U583j2cn35q0rJKj | 38 | Markdown newsletter generation |
| 8 | `workflows/SUB/html_generator_subworkflow.json` | HTML-Generator [sub-workflow] | vMlTglzV1nIWkLb7 | 30 | HTML email generation |
| 9 | `workflows/SUB/alternates_html_generator_subworkflow.json` | Alternates-HTML-Document-Generator [sub-workflow] | EPeLUlkCeqE0fqgu | 12 | A/B HTML variant |
| 10 | `workflows/SUB/email_subject_and_preview_subworkflow.json` | Email-Subject-and-Preview [sub-workflow] | YgZ0Tu39jiwmvlJ5 | 37 | Email subject lines |
| 11 | `workflows/SUB/social_media_generator_subworkflow.json` | Social-Media-Generator [sub-workflow] | Lu0F1bNEv2JVoPqH | 28 | Social media posts |
| 12 | `workflows/SUB/linkedin_carousel_generator_subworkflow.json` | Linkedin-Carousel-Generator [sub-workflow] | kLcefT7KAtrwYAH1 | 22 | LinkedIn carousel |

**Total: ~281 nodes across 12 workflows**

### Execution Flow Diagram

```
                    ┌─────────────────────────┐
                    │  curated-ai-articles     │
                    │  [UTIL] (Scheduled)      │
                    │  Daily + Every 2 days    │
                    └──────────┬──────────────┘
                               │ populates DB
                               ▼
┌──────────────────────────────────────────────────────────┐
│               Newsletter [Main Workflow]                  │
│                                                          │
│  Manual Trigger ──┐                                      │
│  Schedule (5d) ───┤                                      │
│                   ▼                                      │
│  [1] Curated-Articles ──► [2] Summarization              │
│                                    │                     │
│                                    ▼                     │
│                           [3] Theme Generation           │
│                                    │                     │
│                                    ▼                     │
│                           [4] Markdown Generator         │
│                                    │                     │
│                                    ▼                     │
│                           [5] HTML Generator             │
│                                    │                     │
│                    ┌───────┬───────┼───────┐             │
│                    ▼       ▼       ▼       ▼             │
│               [6a] Alt  [6b]    [6c]    [6d]             │
│               HTML   Email   Social  LinkedIn            │
│                      Subj   Media   Carousel             │
└──────────────────────────────────────────────────────────┘
```

Each subworkflow also calls the **LLM Global Config [UTIL]** to retrieve model names.

---

## 2. Main Orchestrator Workflow

**File**: `workflows/MAIN/newsletter_workflow.json`

### Nodes (10 total)

| Node Name | Type | Purpose |
|-----------|------|---------|
| Execute workflow | `manualTrigger` | Manual trigger |
| Schedule Trigger | `scheduleTrigger` | Every 5 days |
| Curated-Articles | `executeWorkflow` | Calls curatedarticles_subworkflow |
| Summarization | `executeWorkflow` | Calls summarization_subworkflow |
| Theme Generation | `executeWorkflow` | Calls theme_generation_subworkflow |
| Markdown | `executeWorkflow` | Calls markdown_generator_subworkflow |
| HTML | `executeWorkflow` | Calls html_generator_subworkflow |
| Alternates HTML Document Generator | `executeWorkflow` | Calls alternates_html_generator_subworkflow |
| Email Subject and Preview | `executeWorkflow` | Calls email_subject_and_preview_subworkflow |
| Social Media Generator | `executeWorkflow` | Calls social_media_generator_subworkflow |
| Linkedin Carousel Generator | `executeWorkflow` | Calls linkedin_carousel_generator_subworkflow |

### Connection Flow

```
Execute workflow ──► Curated-Articles
Schedule Trigger ──► Curated-Articles
Curated-Articles ──► Summarization
Summarization ──► Theme Generation
Theme Generation ──► Markdown
Markdown ──► HTML
HTML ──► Alternates HTML Document Generator
HTML ──► Email Subject and Preview
HTML ──► Social Media Generator
HTML ──► Linkedin Carousel Generator
```

### Key Configuration
- All `executeWorkflow` nodes have `waitForSubWorkflow: true`
- Most nodes have `alwaysOutputData: true`
- Schedule trigger: interval of 5 days

---

## 3. Curated AI Articles Utility

**File**: `workflows/UTIL/curated_ai_articles_utility.json`
**ID**: `dIT9HiTREUm0an1a`
**Purpose**: Automatically fetches AI-related articles on a schedule

### Nodes (11 total)

| Node Name | Type | Purpose |
|-----------|------|---------|
| Schedule, once in a day | `scheduleTrigger` | Daily trigger |
| Schedule, once in 2 days | `scheduleTrigger` | Every-2-days trigger |
| Query for Search News API | `code` | Generates keyword list for daily search |
| Query for Search API | `code` | Generates keyword list for 2-day search |
| Search News API | `httpRequest` | SearchApi google_news engine |
| Search API | `searchApi` | SearchApi default engine |
| Process Input | `code` | Parses results, deduplicates |
| Structure SQL Insert Query | `code` | Builds INSERT SQL |
| Create table | `postgres` | Creates curated_articles table |
| Insert into table | `postgres` | Inserts articles |
| Sticky Note | `stickyNote` | Documentation |

### Connection Flow

```
Schedule (daily) ──► Query for Search News API ──► Search News API ──► Process Input
Schedule (2 days) ──► Query for Search API ──► Search API ──► Process Input
Process Input ──► Structure SQL Insert Query ──► Create table ──► Insert into table
```

### Code: Query for Search News API
```javascript
const list = [
  "Artificial General Intelligence",
  "Automation",
  "Artificial Intelligence",
];

const result = [];
for (const keyword of list) {
  result.push({ json: { keyword } });
}
return result;
```

### Code: Query for Search API
```javascript
const list = [
  "AI breakthrough",
  "AI latest",
  "AI tutorial",
  "AI case study",
  "AI research"
];

const result = [];
for (const keyword of list) {
  result.push({ json: { keyword } });
}
return result;
```

### Search News API Configuration
- URL: `https://www.searchapi.io/api/v1/search`
- Engine: `google_news`
- Parameters: `time_period=last_week`, `num=15`, `location=United States`
- Credentials: `searchApi` (id: `gFbL0UENq7J8DJrA`)

### Search API Configuration
- Uses `@searchapi/n8n-nodes-searchapi.searchApi` node
- Parameters: `time_period=last_week`, `num=10`
- Credentials: `searchApi` (id: `gFbL0UENq7J8DJrA`)

### Code: Process Input (full)
```javascript
const organic_links = [];

for (const item of $input.all()) {
  const searchSource = item.json.search_parameters.engine;

  if (item.json.organic_results && Array.isArray(item.json.organic_results)) {
    for (const linkObj of item.json.organic_results) {
      const date = new Date();
      if (linkObj.date !== undefined) {
        const regex = /(\d+)\s*(day|days|week|weeks)\s*ago/i;
        const match = linkObj.date.match(regex);

        if (match) {
          const value = parseInt(match[1], 10);
          const unit = match[2].toLowerCase();

          switch (unit) {
            case 'day':
            case 'days':
              date.setDate(date.getDate() - value);
            break;
            case 'week':
            case 'weeks':
              date.setDate(date.getDate() - value * 7);
            break;
          }
        }
      }
      organic_links.push({
        json: {
          url: linkObj.link,
          title: linkObj.title,
          origin: searchSource,
          date: date.toLocaleDateString('en-US'),
        },
      });
    }
  }
}

// Deduplicate by URL
const uniqueMap = new Map();
organic_links.forEach(item => {
  const url = item.json.url;
  if (!uniqueMap.has(url)) {
    uniqueMap.set(url, item);
  }
});

return Array.from(uniqueMap.values());
```

### Code: Structure SQL Insert Query
```javascript
const values = items.map(item => {
  const url = item.json.url.replace(/'/g, "''");
  const date = item.json.date;
  const title = item.json.title.replace(/'/g, "");
  const origin = item.json.origin;
  const approved = 'FALSE';
  const industry_news = 'FALSE';
  const newsletter_id = '';

  return `('${url}', TO_DATE('${date}', 'MM/DD/YYYY'), '${title}', '${origin}', ${approved}, ${industry_news}, '${newsletter_id}', CURRENT_TIMESTAMP)`;
});

const query = `
INSERT INTO curated_articles (url, publish_date, title, origin, approved, industry_news, newsletter_id, created_at)
VALUES
  ${values.join(',\n')}
ON CONFLICT (url)
DO UPDATE SET
  title = EXCLUDED.title,
  origin = EXCLUDED.origin,
  publish_date = EXCLUDED.publish_date,
  approved = EXCLUDED.approved,
  industry_news = EXCLUDED.industry_news,
  created_at = CURRENT_TIMESTAMP;
`;

return [{ json: { query: query.trim() } }];
```

### SQL: Create Table
```sql
CREATE TABLE IF NOT EXISTS curated_articles (
  url TEXT PRIMARY KEY,
  title TEXT,
  origin TEXT,
  publish_date DATE,
  approved BOOLEAN,
  industry_news BOOLEAN,
  newsletter_id TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

## 4. Curated Articles Subworkflow

**File**: `workflows/SUB/curatedarticles_subworkflow.json`
**ID**: `BGCgCliQbEcIHT2r`

### Nodes (14 total)

| Node Name | Type | Purpose |
|-----------|------|---------|
| Workflow Initiated | `executeWorkflowTrigger` | Passthrough trigger |
| Manually Initiated | `manualTrigger` | Manual (disabled) |
| Clear sheet | `googleSheets` | Clears Google Sheet |
| Fetch data | `postgres` | Gets unapproved articles |
| Process Input | `code` | Date formatting, field normalization |
| Append or update rows | `googleSheets` | Updates Sheet |
| User approval | `slack` (sendAndWait) | Slack approval form |
| Fetch Data from Sheet | `googleSheets` | Gets approved articles |
| Validate data for required fields | `code` | Checks approved + newsletter_id |
| If | `if` | Branch on validation |
| Status Message | `slack` | Success notification |
| User re-validation message | `slack` | Re-validation request |

### Connection Flow
```
Workflow Initiated ──► Clear sheet ──► Fetch data ──► Process Input
──► Append or update rows ──► User approval ──► Fetch Data from Sheet
──► Validate data ──► If
  ├─ true ──► Status Message (proceed)
  └─ false ──► User re-validation message (loop back)
```

### Code: Process Input
```javascript
if (data.publish_date) {
  const d = new Date(data.publish_date);
  const mm = String(d.getUTCMonth() + 1).padStart(2, '0');
  const dd = String(d.getUTCDate()).padStart(2, '0');
  const yyyy = d.getUTCFullYear();
  data.publish_date = `${mm}/${dd}/${yyyy}`;
}
if (data.approved === false) {
  data.approved = "";
}
```

### Code: Validate data for required fields
```javascript
let overallStatus = false;
for (const item of $input.all()) {
  const approved = item.json['approved'];
  const newsletterId = item.json['newsletter_id'];
  if (approved && approved.toString().trim().toLowerCase() === 'yes' && newsletterId) {
    overallStatus = true;
    break;
  }
}
return [{ json: { status: overallStatus } }];
```

### Google Sheets Configuration
- Spreadsheet ID: `1TPHgLaLUJjL92V5k7uI7P4_mou3-wzoclFhxnCeBMP8`
- Sheet: `Sheet1` (gid=0)
- Credentials: `googleSheetsOAuth2Api` (id: `mdEXXhycQbVgTPQQ`)

### Slack: User Approval
- Operation: `sendAndWait`
- Channel: `#n8n-is2`
- Message: Approval request for article curation
- Credentials: `slackApi` (id: `PLxXtzwELhFOLjM0`)

---

## 5. Summarization Subworkflow

**File**: `workflows/SUB/summarization_subworkflow.json`
**ID**: `ScFeCWBc1yqWBUsD`

### Nodes (38 total)

| Node Name | Type | Purpose |
|-----------|------|---------|
| Workflow Initiated | `executeWorkflowTrigger` | Passthrough trigger |
| Manually Initiated | `manualTrigger` | Manual (disabled) |
| LLM Global Config | `executeWorkflow` | Fetches model config |
| User Update | `slack` | "Looking into articles..." notification |
| Fetch Data from Sheet | `googleSheets` | Gets approved articles |
| Field Mapping | `set` | Normalizes fields |
| Structure SQL Insert Query | `code` | Builds SQL upsert |
| Create table | `postgres` | Creates tables |
| Insert into table | `postgres` | Inserts articles |
| Check DB Insert status | `if` | Validates DB insert |
| Loop Over Items | `splitInBatches` | Processes articles one-by-one |
| Fetch Page Content | `httpRequest` | Gets article HTML |
| If | `if` | Validates fetch (no error, no captcha, not YouTube) |
| Manual Article Content | `slack` (sendAndWait) | Asks user to paste content |
| Markdown | `markdown` | Converts HTML to text |
| Fetch learning data | `postgres` | Gets last 40 feedback entries |
| Aggregate Feedback | `code` | Combines feedback into bullets |
| Generate Data using LLM | `informationExtractor` | Summarizes article |
| OpenRouter content generator model | `lmChatOpenRouter` | LLM model |
| Aggregate | `aggregate` | Collects all summaries |
| Format output | `code` | Formats Slack Block Kit |
| Conditional output | `code` | Routes original vs regenerated |
| Share summarized content | `slack` | Shows summaries |
| Next steps selection | `slack` (sendAndWait) | Yes/Feedback/Restart form |
| Switch | `switch` | Routes user choice |
| Feedback form | `slack` (sendAndWait) | Free-text feedback |
| Re-Generate Data using LLM | `informationExtractor` | Regenerates with feedback |
| OpenRouter feedback update generator model | `lmChatOpenRouter` | Regeneration model |
| Learning data extractor | `informationExtractor` | Extracts learning data |
| Learning data process model | `lmChatOpenRouter` | Learning model |
| Insert user feedback | `postgres` | Stores feedback |
| Final summarized content | `code` | Formats final output |
| Error Output | `slack` | Error notification |
| Stop and Error | `stopAndError` | Terminates on error |
| Update rows in a table | `postgres` | Updates article status |

### Connection Flow
```
Workflow Initiated ──► LLM Global Config ──► User Update ──► Fetch Data from Sheet
──► Field Mapping ──► Loop Over Items + Structure SQL Insert Query
                      │
                      ├──► (batch done) Aggregate ──► Format output ──► Conditional output
                      │    ──► Share summarized content ──► Next steps selection ──► Switch
                      │         ├─ Yes ──► Final summarized content (output)
                      │         ├─ Feedback ──► Feedback form ──► Re-Generate ──► Learning data
                      │         │    ──► Insert user feedback ──► Conditional output (loop)
                      │         └─ Restart ──► Conditional output (loop)
                      │
                      └──► (each item) Fetch Page Content ──► If
                           ├─ valid ──► Markdown ──► Fetch learning data ──► Aggregate Feedback
                           │    ──► Generate Data using LLM ──► Loop Over Items (continue)
                           └─ invalid ──► Manual Article Content ──► Markdown (continue)

Structure SQL Insert Query ──► Create table ──► Insert into table ──► Check DB Insert status
```

### Code: Field Mapping (Set node assignments)
```
url = {{ $json.url }}
publish_date = {{ $json.publish_date }}
approved = {{ $json.approved && $json.approved.toString().toLowerCase() === 'yes' }}
title = {{ $json.title }}
origin = {{ $json.origin }}
newsletter_id = {{ $json.newsletter_id }}
industry_news = {{ $json.industry_news && $json.industry_news.toString().toLowerCase() === 'yes' }}
```

### Code: Structure SQL Insert Query
```javascript
const values = items.map(item => {
  const url = item.json.url.replace(/'/g, "''");
  const date = item.json.publish_date;
  const approved = item.json.approved ? 'TRUE' : 'FALSE';
  const title = item.json.title;
  const origin = item.json.origin;
  const newsletter_id = item.json.newsletter_id;

  return `('${url}', TO_DATE('${date}', 'MM/DD/YYYY'), ${approved}, '${title}', '${origin}', '${newsletter_id}', CURRENT_TIMESTAMP)`;
});

const query = `
INSERT INTO curated_articles (url, publish_date, approved, title, origin, newsletter_id, created_at)
VALUES
  ${values.join(',\n')}
ON CONFLICT (url)
DO UPDATE SET
  publish_date = EXCLUDED.publish_date,
  approved = EXCLUDED.approved,
  title = EXCLUDED.title,
  origin = EXCLUDED.origin,
  newsletter_id = EXCLUDED.newsletter_id,
  created_at = CURRENT_TIMESTAMP;
`;

return [{ json: { query: query.trim() } }];
```

### HTTP Request: Fetch Page Content
- URL: `{{ $json.url }}`
- Headers:
  - User-Agent: `Safari/537.36`
  - Accept: `text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8`
  - Accept-Language: `en-US,en;q=0.9`
  - Referer: `https://www.google.com/`
  - Connection: `keep-alive`
- Response format: text
- Error handling: `continueRegularOutput`

### If Conditions (fetch validation)
All must be true (AND):
1. `$json.error.message` does NOT exist
2. `$json.data` does NOT contain `sgcaptcha`
3. `$('Loop Over Items').item.json.url` does NOT contain `youtube.com`

### Markdown Node
- Input: `{{ $('Field Mapping').item.json.url }} {{ $('Field Mapping').item.json.title }} {{ $json.data?.text ?? $json.data }}`
- Output key: `chatInput`

### Code: Aggregate Feedback
```javascript
const markdownNode = $('Markdown').first();
const chatInput = markdownNode?.json?.chatInput || '';

const feedbackArray = $input.all()
  .map(item => item.json.feedback_text)
  .filter(f => f && f.trim() !== '');

const aggregatedFeedback = feedbackArray.length
  ? feedbackArray.map(f => `• ${f}`).join('\n')
  : '';

return [{ json: { aggregatedFeedback, chatInput } }];
```

### LLM Prompt: Generate Data using LLM (Summarization)

```
You are a professional AI research editor and content analyst. Your task is to process news or blog articles that may be provided in **HTML**, **Markdown**, or **plain text** format according to strict editorial and data integrity standards.

Follow these protocols EXACTLY:

---

## Accuracy Control Protocol (MANDATORY)
1. Do NOT search for alternative sources.
2. Do NOT summarize partial or unavailable content.
3. Do NOT generate or infer missing details.

---

## Article Summary Standards
**Summary Specifications:**
- 3–4 sentences per article
- Focus strictly on factual content, key findings, and main conclusions
- Avoid editorial opinions or speculative tone
- Include specific statistics, methodologies, or technical details when mentioned

**Business Relevance Specifications:**
- 2–3 sentences per article
- Explain the broad business or strategic relevance across industries
- Consider an audience of solopreneurs and SMB professionals (without naming them)
- Emphasize practical implications for decision-making, operations, or strategy
- Avoid technical or industry-specific jargon

---

## Data Integrity Standards
- Extract only verified information directly from the article
- Quote or cite exact statistics or claims when possible
- Flag unverifiable data explicitly (e.g., "Statistic requires verification")
- Do NOT fabricate, infer, or supplement from external knowledge
- Well-established general knowledge does NOT require verification

---

{{ $json.aggregatedFeedback
  ? "## Editorial Improvement Context (From Prior Feedback)\nThe following editorial preferences and improvement notes should guide your tone, structure, and summarization style in this and future outputs:\n\n" + $json.aggregatedFeedback + "\n\nUse this feedback to adjust language, flow, and focus — without altering factual accuracy or deviating from the core standards above.\n"
  : "" }}

---

## Output Format (MANDATORY)
Return clean plain text output (no markdown or bullet points) in this format:

URL: [article URL]
Title: [article title]
Summary: [3–4 sentence factual summary following Article Summary Standards]
Business Relevance: [2–3 sentence business relevance commentary following the same standards]

---

Now process the following content accordingly. The input may be **HTML**, **Markdown**, or **plain text** — automatically detect the format. If the content cannot be fully accessed, follow the Accuracy Control Protocol.

keep the output format consistent as plain text and not JSON object.

Input:
{{ $json.chatInput }}
```

- LLM Model: `{{ $('LLM Global Config').first().json.LLM_SUMMARY_MODEL }}`
- Extraction attribute: `data` - "Fetch blog data from page HTML"

### LLM Prompt: Re-Generate Data using LLM (Feedback)

```
You are a professional content editor AI.
The original content is below:
{{ $('Format output').item.json.text }}

The user has provided feedback as follows:
{{ $json.data.text }}

Please revise the content to incorporate the feedback. Maintain the formatting of the original content.

Maintain these protocols EXACTLY:

## Accuracy Control Protocol (MANDATORY)
1. Do NOT search for alternative sources.
2. Do NOT summarize partial or unavailable content.
3. Do NOT generate or infer missing details.
4. Incorporate ONLY the requested feedback. Do NOT rewrite, expand, or regenerate other sections unless the feedback directly requires it.

## Article Summary Standards
(same specifications as above)

## Data Integrity Standards
(same specifications as above)
```

- LLM Model: `{{ $('LLM Global Config').first().json.LLM_SUMMARY_REGENERATION_MODEL }}`

### LLM Prompt: Learning data extractor

```
You are an AI assistant that converts raw user feedback into a short, structured summary
that can be stored as learning data for future content improvement.

You will be given:
- The original *input text* (the content or article summary prompt),
- The *model output* that was generated,
- The *user's feedback*.

Your goal:
1. Summarize the key points of the user's feedback into clear, actionable insights.
2. Keep the summary short (2–3 sentences max).
3. Focus on what should be improved next time (e.g., tone, accuracy, length, structure, detail).
4. If feedback is unclear or generic (like "good" or "bad"), infer the likely intent from the input and output context.

---

### Feedback Data
**User Feedback:**
{{ $('Feedback form').item.json.data.text }}

**Input Provided:**
{{ $('Format output').item.json.text }}

**Model Output:**
{{ $json.output.data }}

---

### Expected Output
Return only a concise structured learning note in JSON format like this:

{
  "learning_feedback": "Future responses should provide shorter, more focused summaries emphasizing factual accuracy and concise language."
}
```

- LLM Model: `{{ $('LLM Global Config').first().json.LLM_SUMMARY_LEARNING_DATA_MODEL }}`

### Code: Format output (Slack Block Kit builder)
```javascript
const input = $('Aggregate').first().json;
const newsletter = $('Field Mapping').first().json.newsletter_id;
const fieldMappingItems = $('Field Mapping').all().map(i => i.json);

if (!input.data || !Array.isArray(input.data) || input.data.length === 0) {
  throw new Error("No valid data array found in input.");
}

const industryNewsByUrl = fieldMappingItems.reduce((acc, item) => {
  const url = item.url?.trim();
  if (!url) return acc;
  acc[url] = Boolean(item.industry_news);
  return acc;
}, {});

const articles = input.data.map((entry, index) => {
  const urlMatch = entry.match(/URL:\s*(.+)/);
  const titleMatch = entry.match(/Title:\s*(.+)/);
  const summaryMatch = entry.match(/Summary:\s*([\s\S]*?)Business Relevance:/);
  const businessMatch = entry.match(/Business Relevance:\s*([\s\S]*)$/);

  const url = urlMatch ? urlMatch[1].trim() : "N/A";
  const title = titleMatch ? titleMatch[1].trim() : "Untitled";
  const summary = summaryMatch ? summaryMatch[1].trim() : "No summary available.";
  const business = businessMatch ? businessMatch[1].trim() : "No business relevance available.";
  const order = index + 1;
  const newsletter_id = newsletter;

  const formattedSlack = `*${index + 1}. ${title}*\n` +
    `*URL:* ${url}\n\n` +
    `*Summary:*\n${summary}\n\n` +
    `*Business Relevance:*\n${business}\n` +
    `──────────────────────────────\n\n`;

  return {
    URL: url, Title: title, Summary: summary, BusinessRelevance: business,
    formattedSlack, order, newsletter_id,
    industry_news: industryNewsByUrl[url] ?? false
  };
});

const combinedText = `*Article Summaries for Review*\n\n_Total Articles:_ ${articles.length}\n\n${articles.map(a => a.formattedSlack).join('\n\n')}`;

const blocks = [
  { type: "section", text: { type: "mrkdwn", text: `*Article Summaries for Review*\n\n_Total Articles:_ ${articles.length}` } },
  { type: "divider" },
  ...articles.flatMap((a, index) => [
    { type: "section", text: { type: "mrkdwn", text: `*${index + 1}. ${a.Title}*\n*URL:* ${a.URL}\n\n*Summary:*\n${a.Summary}\n\n*Business Relevance:*\n${a.BusinessRelevance}` } },
    { type: "divider" }
  ])
];

const message = blocks.map(b => b.text?.text || '').filter(Boolean).join('\n──────────────────────────────\n\n');

return [{ json: { articleCount: articles.length, articles, text: combinedText, blocks, message } }];
```

### Code: Conditional output
```javascript
let original_text = null;
let re_generated_text = null;
let switch_value = null;
let hasIntroduction = null;
let feedback = null;

try { original_text = $('Format output').first().json.text; } catch (e) {}
try {
  re_generated_text = $('Re-Generate Data using LLM').first().json.output.data;
  hasIntroduction = re_generated_text.includes('Article Summaries for Review');
} catch (e) {}
try { switch_value = $('Switch').first().json.data["Ready to proceed to next step ?"]; } catch (e) {}

let text;
if (switch_value && String(switch_value).trim().toLowerCase() !== 'yes' && String(switch_value).trim().toLowerCase() !== 'provide feedback') {
  text = original_text;
} else {
  text = re_generated_text ?? original_text;
}

if (re_generated_text && !hasIntroduction) {
  feedback = re_generated_text;
  text = original_text;
} else {
  feedback = text;
}

if (switch_value && String(switch_value).trim().toLowerCase() === 'restart chat') {
  feedback = text;
}

return [{ json: { text, feedback } }];
```

### Code: Final summarized content
```javascript
let input = '';
const newsletter = $('Field Mapping').first().json.newsletter_id;
const fieldMappingItems = $('Field Mapping').all().map(i => i.json);

try {
  const nodeData = $('Re-Generate Data using LLM').first();
  input = nodeData?.json?.output?.data || '';
} catch (error) {
  input = '';
}

const industryNewsByUrl = fieldMappingItems.reduce((acc, item) => {
  const url = item.url?.trim();
  if (!url) return acc;
  acc[url] = Boolean(item.industry_news);
  return acc;
}, {});

if (input) {
  const articleRegex = /\*(\d+)\.\s(.+?)\*\n\*URL:\*\s(https?:\/\/\S+)\n\n\*Summary:\*\n([\s\S]*?)\n\n\*Business Relevance:\*\n([\s\S]*?)(?=\n──────────────────────────────|\n*$)/g;

  const articles = [];
  let match;
  while ((match = articleRegex.exec(input)) !== null) {
    const [, index, title, url, summary, business] = match;
    articles.push({
      URL: url, Title: title, Summary: summary, BusinessRelevance: business,
      formattedSlack: `*${index}. ${title}*\n*URL:* ${url}\n\n*Summary:*\n${summary}\n\n*Business Relevance:*\n${business}\n──────────────────────────────\n\n`,
      order: index, newsletter_id: newsletter,
      industry_news: industryNewsByUrl[url] ?? false
    });
  }
  return [{ json: { articles } }];
}

const articles = $('Format output').first().json.articles;
return articles.map(article => ({ json: article }));
```

### Slack: Next steps selection form
```
Message: "All articles have been successfully summarized."
Form fields:
  - "Ready to proceed to next step?" (dropdown): Yes / Provide Feedback / Restart Chat
Button label: "Proceed to Next Steps"
```

### SQL: Create tables
```sql
CREATE TABLE IF NOT EXISTS curated_articles (
  url TEXT PRIMARY KEY,
  publish_date DATE,
  approved BOOLEAN,
  title TEXT,
  origin TEXT,
  newsletter_id TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS summarization_user_feedback (
  id SERIAL PRIMARY KEY,
  feedback_text TEXT NOT NULL,
  created_at TIMESTAMP DEFAULT NOW()
);
```

### Postgres: Fetch learning data
- Table: `summarization_user_feedback`
- Limit: 40
- Sort: `created_at DESC`
- Output columns: `feedback_text`

---

## 6. Theme Generation Subworkflow

**File**: `workflows/SUB/theme_generation_subworkflow.json`
**ID**: `GsUsHGEbssqrS05W`
**Nodes**: 38

This is one of the most complex workflows. Key aspects are covered in the PRD (Section 3.3 and 4.3). The full theme generation prompt, theme parser code, and Slack formatting code are extensive (1000+ lines of JavaScript across multiple Code nodes).

### Key Code Nodes

**Process User Feedback**: Aggregates feedback from database + fresh Slack input + reset handling
**Prepare AI generated themes**: Splits LLM output by "-----", extracts theme/summary/body
**Format output**: Converts `%XX_` markers to Slack `*bold*` format (100+ regex replacements)
**Conditional output**: Builds dynamic Slack form with theme radio buttons
**Format theme output**: Extracts selected theme, parses into structured object
**Selected Theme output**: Parses theme body into `formatted_theme` JSON using regex extraction of all `%FA_`, `%M1_`, `%Q1_`, `%I1_` etc. markers
**Format output - Selected Theme**: Formats selected theme + freshness report for Slack display

### LLM Models Used
- Theme generation: `LLM_THEME_MODEL`
- Freshness check: `LLM_THEME_FRESHNESS_CHECK_MODEL`
- Feedback learning: `LLM_THEME_LEARNING_DATA_MODEL`
- Theme editing: `LLM_THEME_LEARNING_DATA_MODEL`

---

## 7. Markdown Generator Subworkflow

**File**: `workflows/SUB/markdown_generator_subworkflow.json`
**ID**: `U583j2cn35q0rJKj`
**Nodes**: 38

This workflow contains the most sophisticated validation system. Full details are in the PRD (Section 3.4, 4.4, 4.5, 4.6).

### Key Code Nodes

**Code (extract theme)**: Extracts `formatted_theme` from workflow input or chat input
**Aggregate Feedback**: Combines DB feedback with theme input
**Validation Character count**: JavaScript character counting for all sections with delta calculations
**Format Error Output**: Parses validator JSON, tracks attempt counter (max 3), force-accepts after limit
**Re-generator Input**: Prepares error context for targeted LLM regeneration
**Conditional output**: Routes original vs regenerated content
**Markdown document ID**: Extracts Google Doc ID after creation

### LLM Models Used
- Markdown generation: `LLM_MARKDOWN_MODEL`
- Structural validation: `LLM_MARKDOWN_VALIDATOR_MODEL` (openai/gpt-4.1)
- Voice validation: `LLM_MARKDOWN_VALIDATOR_MODEL` (openai/gpt-4.1)
- Regeneration: `LLM_MARKDOWN_REGENERATION_MODEL`
- Learning data: `LLM_MARKDOWN_LEARNING_DATA_MODEL`

### Validation Character Count Code (full)
```javascript
const raw = $input.first().json.output.data;
const countChars = s => (s || "").length;
const errors = [];

function rangeError(section, field, current, min, max) {
  if (current < min) {
    errors.push(`${section} – ${field} – current=${current} – target=${min}–${max} – delta=${current - min}`);
  } else if (current > max) {
    errors.push(`${section} – ${field} – current=${current} – target=${min}–${max} – delta=+${current - max}`);
  }
}

function extractSection(title) {
  const pattern = new RegExp(`#\\s*\\*?${title}\\*?\\s*\\n([\\s\\S]*?)(?=\\n#\\s*\\*?|$)`, "i");
  const match = raw.match(pattern);
  return match ? match[1].trim() : "";
}

// QUICK HIGHLIGHTS
const quick = extractSection("QUICK HIGHLIGHTS");
const quickBullets = quick.split("\n").filter(l => l.startsWith("• ") || l.startsWith("- ")).map(l => l.replace(/^• |^- /, "").trim());
if (quickBullets.length === 3) {
  quickBullets.forEach((b, i) => rangeError("Quick Highlights", `Bullet ${i + 1}`, countChars(b), 150, 190));
}

// FEATURED ARTICLE
const featured = extractSection("FEATURED ARTICLE");
const featuredBody = featured.replace(/^##\s+.*$/m, "").trim();
const ctaMatch = featuredBody.match(/^.*→.*$/m);
const cta = ctaMatch ? ctaMatch[0] : "";
const featuredNoCTA = cta ? featuredBody.replace(cta, "").trim() : featuredBody;
const paras = featuredNoCTA.split(/\n\s*\n/).map(p => p.trim()).filter(Boolean);
const p1 = paras[0] || "";
const p2 = paras[1] || "";
const insight = paras.find(p => p.startsWith("**")) || "";
rangeError("Featured Article", "Paragraph 1", countChars(p1), 300, 400);
rangeError("Featured Article", "Paragraph 2", countChars(p2), 300, 400);
rangeError("Featured Article", "Key Insight paragraph", countChars(insight), 300, 370);

// MAIN ARTICLES
function parseMain(title, index) {
  const sec = extractSection(title).replace(/^##\s+.*$/m, "").replace(/^\[.*→\]\(.*?\)$/gm, "").trim();
  const paras = sec.split(/\n\s*\n/).map(p => p.trim()).filter(Boolean);
  const callout = paras.find(p => /^(\*\*|\*)[^*]+:\1/.test(p)) || "";
  const content = paras.find(p => p !== callout) || "";
  rangeError(`Main Article ${index}`, "Callout Paragraph", countChars(callout), 180, 250);
  if (countChars(content) > 750) {
    errors.push(`Main Article ${index} – Content Paragraph – current=${countChars(content)} – target=max 750 – delta=+${countChars(content) - 750}`);
  }
}
parseMain("MAIN ARTICLE 1", 1);
parseMain("MAIN ARTICLE 2", 2);

// INDUSTRY DEVELOPMENTS
const industry = extractSection("INDUSTRY DEVELOPMENTS").split("\n").map(l => l.trim()).filter(l => l.startsWith("[")).slice(0, 2);
industry.forEach((item, i) => rangeError("Industry Developments", `Industry ${i + 1}`, countChars(item), 200, 280));

// FOOTER
const footerLines = extractSection("FOOTER").split("\n").map(l => l.trim()).filter(Boolean);
rangeError("Footer", "Paragraph 2", countChars(footerLines[1] || ""), 200, 550);
rangeError("Footer", "Paragraph 3", countChars(footerLines[2] || ""), 200, 550);

return { charErrors: errors };
```

### Format Error Output Code (with loop breaker)
```javascript
const raw = $input.first().json.output.output;
const markdown = $('Generate Markdown using LLM').first().json.output.data;

const staticData = $getWorkflowStaticData('node');
const execId = $execution.id;
if (!staticData[execId]) { staticData[execId] = 0; }
staticData[execId] += 1;

let parsed;
if (raw && typeof raw === "object") {
  parsed = raw;
} else {
  try { parsed = JSON.parse(raw); }
  catch (e) { parsed = { error: "Invalid JSON returned by validator", raw }; }
}

// HARD LOOP BREAKER — force accept after 3 attempts
const MAX_ATTEMPTS = 3;
if (staticData[execId] >= MAX_ATTEMPTS) {
  parsed.isValid = true;
}

return [{ json: { parsed, markdown, runCount: staticData[execId] } }];
```

---

## 8. HTML Generator Subworkflow

**File**: `workflows/SUB/html_generator_subworkflow.json`
**ID**: `vMlTglzV1nIWkLb7`
**Nodes**: 30

### Key Operations
1. Extracts document ID from previous workflow output (recursive object traversal)
2. Fetches markdown from Google Doc
3. Converts markdown to HTML
4. Calls LLM to generate email HTML template
5. Creates Google Doc with HTML
6. Shares preview in Slack
7. Handles feedback loop with learning data

### LLM Models Used
- HTML generation: `LLM_HTML_MODEL`
- Regeneration: `LLM_HTML_REGENERATION_MODEL`
- Learning data: `LLM_HTML_LEARNING_DATA_MODEL`

### Database
- Creates `htmlgenerator_user_feedback` table
- Stores feedback for learning

---

## 9. Alternates HTML Generator Subworkflow

**File**: `workflows/SUB/alternates_html_generator_subworkflow.json`
**ID**: `EPeLUlkCeqE0fqgu`
**Nodes**: 12

### Key Operations
1. Fetches markdown document content
2. Converts to alternative HTML variant
3. Creates Google Doc
4. Shares with user in Slack

This is a simpler workflow focused on creating a design variant for A/B testing.

---

## 10. Email Subject & Preview Subworkflow

**File**: `workflows/SUB/email_subject_and_preview_subworkflow.json`
**ID**: `YgZ0Tu39jiwmvlJ5`
**Nodes**: 37

### Key Operations
1. Fetches learning data from `newsletter_email_subject_feedback` table
2. Fetches document content from Google Docs
3. Calls LLM to generate 3-5 subject line options with preview text
4. Parses options into selectable Slack form
5. User selects preferred subject + preview
6. Handles feedback and regeneration loop
7. Creates Google Doc with final selection

### LLM Models Used
- Subject generation: `LLM_EMAIL_SUBJECT_MODEL`
- Regeneration: `LLM_EMAIL_SUBJECT_REGENERATION_MODEL`
- Preview: `LLM_EMAIL_PREVIEW_MODEL`

---

## 11. Social Media Generator Subworkflow

**File**: `workflows/SUB/social_media_generator_subworkflow.json`
**ID**: `Lu0F1bNEv2JVoPqH`
**Nodes**: 28

### Key Operations
1. Fetches HTML document content
2. **Phase 1**: Generates 12 social posts (6 DYK + 6 IT)
3. Shares options in Slack for selection
4. **Phase 2**: Generates detailed captions for selected posts (150-300 chars)
5. Handles feedback and regeneration
6. Creates Google Doc with final posts

### LLM Models Used
- Post generation: `LLM_SOCIAL_MEDIA_MODEL`
- Caption generation: `LLM_SOCIAL_POST_CAPTION_MODEL`
- Regeneration: `LLM_SOCIAL_MEDIA_REGENERATION_MODEL`

---

## 12. LinkedIn Carousel Generator Subworkflow

**File**: `workflows/SUB/linkedin_carousel_generator_subworkflow.json`
**ID**: `kLcefT7KAtrwYAH1`
**Nodes**: 22

### Key Operations
1. Fetches HTML document content
2. Generates carousel slides via LLM
3. Validates character counts (265-315 per slide body)
4. Generates 3 LinkedIn post copy versions
5. Creates Google Doc
6. Shares in Slack for approval

### Character Validation Code
```javascript
const bodyRegex = /(\*Body:\*\n)([\s\S]*?)(?=\n\n---|\n\n\*Slide|\s*$)/g;
const updatedText = rawText.replace(bodyRegex, (match, bodyLabel, bodyContent) => {
  const charCount = (bodyContent.length) - 4;
  if (charCount < 265 || charCount > 315) {
    errors.push({
      slide_body: bodyContent,
      type: "CHARACTER_LIMIT_VIOLATION",
      actualCharacters: charCount,
      requiredRange: "265-315",
      instruction: "Rewrite slide body to be 265–315 characters"
    });
  }
  return `${bodyLabel}${cleanedBody}\n\n*Character count:* ${charCount} characters`;
});
```

### Article Order (must be preserved)
1. Featured Article
2. Main Article 1
3. Main Article 2
4. Quick Hit 1
5. Quick Hit 2
6. Quick Hit 3
7. Industry Development 1
8. Industry Development 2

### LLM Models Used
- Carousel generation: `LLM_LINKEDIN_MODEL`
- Regeneration: `LLM_LINKEDIN_REGENERATION_MODEL`

---

## 13. LLM Global Config Utility

**File**: `workflows/UTIL/llm_global_config_utility.json`
**ID**: `O5I7T1oioeIBv0j4`
**Nodes**: 3

### Full Model Mapping
```javascript
return {
  "LLM_SUMMARY_MODEL": "anthropic/claude-sonnet-4.5",
  "LLM_SUMMARY_REGENERATION_MODEL": "anthropic/claude-sonnet-4.5",
  "LLM_SUMMARY_LEARNING_DATA_MODEL": "anthropic/claude-sonnet-4.5",
  "LLM_MARKDOWN_MODEL": "anthropic/claude-sonnet-4.5",
  "LLM_MARKDOWN_VALIDATOR_MODEL": "openai/gpt-4.1",
  "LLM_MARKDOWN_REGENERATION_MODEL": "anthropic/claude-sonnet-4.5",
  "LLM_MARKDOWN_LEARNING_DATA_MODEL": "anthropic/claude-sonnet-4.5",
  "LLM_HTML_MODEL": "anthropic/claude-sonnet-4.5",
  "LLM_HTML_REGENERATION_MODEL": "anthropic/claude-sonnet-4.5",
  "LLM_HTML_LEARNING_DATA_MODEL": "anthropic/claude-sonnet-4.5",
  "LLM_THEME_MODEL": "anthropic/claude-sonnet-4.5",
  "LLM_THEME_LEARNING_DATA_MODEL": "anthropic/claude-sonnet-4.5",
  "LLM_THEME_FRESHNESS_CHECK_MODEL": "google/gemini-2.5-flash",
  "LLM_SOCIAL_MEDIA_MODEL": "anthropic/claude-sonnet-4.5",
  "LLM_SOCIAL_POST_CAPTION_MODEL": "anthropic/claude-sonnet-4.5",
  "LLM_SOCIAL_MEDIA_REGENERATION_MODEL": "anthropic/claude-sonnet-4.5",
  "LLM_LINKEDIN_MODEL": "anthropic/claude-sonnet-4.5",
  "LLM_LINKEDIN_REGENERATION_MODEL": "anthropic/claude-sonnet-4.5",
  "LLM_EMAIL_SUBJECT_MODEL": "anthropic/claude-sonnet-4.5",
  "LLM_EMAIL_SUBJECT_REGENERATION_MODEL": "anthropic/claude-sonnet-4.5",
  "LLM_EMAIL_PREVIEW_MODEL": "anthropic/claude-sonnet-4.5"
}
```

---

## 14. Database Schema Details

### Table: curated_articles
```sql
CREATE TABLE IF NOT EXISTS curated_articles (
  url TEXT PRIMARY KEY,
  title TEXT,
  origin TEXT,
  publish_date DATE,
  approved BOOLEAN,
  industry_news BOOLEAN,
  newsletter_id TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### Table: summarization_user_feedback
```sql
CREATE TABLE IF NOT EXISTS summarization_user_feedback (
  id SERIAL PRIMARY KEY,
  feedback_text TEXT NOT NULL,
  created_at TIMESTAMP DEFAULT NOW()
);
```

### Table: newsletter_themes
```sql
CREATE TABLE IF NOT EXISTS newsletter_themes (
  theme TEXT PRIMARY KEY,
  theme_body TEXT,
  theme_summary TEXT,
  newsletter_id TEXT,
  approved BOOLEAN,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### Table: newsletter_themes_user_feedback
```sql
CREATE TABLE IF NOT EXISTS newsletter_themes_user_feedback (
  id SERIAL PRIMARY KEY,
  feedback_text TEXT NOT NULL,
  created_at TIMESTAMP DEFAULT NOW(),
  newsletter_id TEXT
);
```

### Table: markdowngenerator_user_feedback
```sql
CREATE TABLE IF NOT EXISTS markdowngenerator_user_feedback (
  id SERIAL PRIMARY KEY,
  feedback_text TEXT NOT NULL,
  created_at TIMESTAMP DEFAULT NOW()
);
```

### Table: htmlgenerator_user_feedback
```sql
CREATE TABLE IF NOT EXISTS htmlgenerator_user_feedback (
  id SERIAL PRIMARY KEY,
  feedback_text TEXT NOT NULL,
  created_at TIMESTAMP DEFAULT NOW()
);
```

### Table: newsletter_email_subject_feedback
```sql
CREATE TABLE IF NOT EXISTS newsletter_email_subject_feedback (
  id SERIAL PRIMARY KEY,
  feedback_text TEXT NOT NULL,
  created_at TIMESTAMP DEFAULT NOW(),
  newsletter_id TEXT
);
```

### Common Query Patterns

**Upsert pattern** (used everywhere):
```sql
INSERT INTO table_name (columns...)
VALUES (values...)
ON CONFLICT (primary_key)
DO UPDATE SET
  column = EXCLUDED.column,
  ...;
```

**Fetch learning data** (used in every subworkflow):
```sql
SELECT feedback_text
FROM {feedback_table}
ORDER BY created_at DESC
LIMIT 40;
```

---

## 15. Credential & Authentication Details

| Credential Name | Type | ID | Used By |
|-----------------|------|----|---------|
| Google Sheets account | `googleSheetsOAuth2Api` | `mdEXXhycQbVgTPQQ` | Article curation, summarization |
| Slack account | `slackApi` | `PLxXtzwELhFOLjM0` | All workflows |
| SearchApi account | `searchApi` | `gFbL0UENq7J8DJrA` | Article utility |
| Postgres account | `postgres` | `6V2an8hBVnEqwCBR` | All workflows |
| OpenRouter account | `openRouterApi` | `tzbBPaBEj7ESKv6l` | All LLM workflows |
| Google Docs account | `googleDocsOAuth2Api` | `tPcixMkQp2s2Gk4e` | Markdown, HTML, parallel outputs |

---

## 16. Docker & Infrastructure

### docker-compose.local.yml

**Services**:

1. **PostgreSQL 15-alpine**
   - Container: `n8n-postgres`
   - Image: `postgres:15-alpine`
   - Volumes: `postgres_data` (named volume)
   - Health checks enabled
   - Two databases: `n8n_app` (internal), `n8n_custom_data` (workflow data)

2. **n8n 2.4.6** (local development)
   - Container: `n8n`
   - Image: `docker.n8n.io/n8nio/n8n:2.4.6`
   - Port: `5678:5678`
   - Volumes: `n8n_data`, `./workflows`, `./credentials`
   - Depends on PostgreSQL health check

### Database Initialization (init-users.sh)
Creates two separate PostgreSQL users and databases:
- `n8n_app_user` owns `n8n_app` (n8n internal, do NOT modify)
- `n8n_custom_data_user` owns `n8n_custom_data` (workflow data, safe to modify)

### Production (Dockerfile)
- Pins n8n 2.0.3 for Digital Ocean App Platform
- Uses managed PostgreSQL (not containerized)

---

## 17. Environment Variables

```
# Database
POSTGRES_PASSWORD=<secure>
N8N_APP_PASSWORD=<secure>
N8N_CUSTOM_DATA_PASSWORD=<secure>

# Timezone
TIMEZONE=America/Los_Angeles

# n8n Core
N8N_PROTOCOL=http
N8N_HOST=localhost
N8N_LOG_LEVEL=info
N8N_DETAILED_ERROR_OUTPUT=true
N8N_ENFORCE_SETTINGS_FILE_PERMISSIONS=true
N8N_RUNNERS_ENABLED=true
DB_POOL_SIZE=2

# Security (production)
N8N_BASIC_AUTH_ACTIVE=false
N8N_BASIC_AUTH_USER=admin
N8N_BASIC_AUTH_PASSWORD=<secure>

# Privacy
N8N_DIAGNOSTICS_ENABLED=false
N8N_VERSION_NOTIFICATIONS_ENABLED=false
N8N_ANONYMOUS_TELEMETRY=false
N8N_METRICS=false
```

---

## 18. Cross-Workflow Data Passing Patterns

### n8n Expression Patterns Used

| Pattern | Purpose |
|---------|---------|
| `$('Node Name').first().json.field` | Access first item from a specific node |
| `$('Node Name').all()` | Get all items from a node |
| `$('Node Name').item.json.field` | Access current batch item from a node |
| `$input.first()` / `$input.all()` | Current node's input data |
| `$json.field` | Current item's field |
| `$now` | Current timestamp (Luxon DateTime) |
| `$execution.id` | Current execution ID |
| `$getWorkflowStaticData('node')` | Persistent state across executions |

### Data Transformation Patterns

**Boolean normalization**:
```javascript
approved = item.json.approved && item.json.approved.toString().toLowerCase() === 'yes'
```

**SQL string escaping**:
```javascript
url.replace(/'/g, "''")
title.replace(/'/g, "")
```

**Date formatting**:
```javascript
`TO_DATE('${date}', 'MM/DD/YYYY')`
```

**Relative date parsing**:
```javascript
const regex = /(\d+)\s*(day|days|week|weeks)\s*ago/i;
```

### Feedback Aggregation Pattern (shared across workflows)
```javascript
const feedbackArray = $input.all()
  .map(item => item.json.feedback_text)
  .filter(f => f && f.trim() !== '');

const aggregatedFeedback = feedbackArray.length
  ? feedbackArray.map(f => `• ${f}`).join('\n')
  : '';
```

---

## 19. Node Type Inventory

| Node Type | Count | Purpose |
|-----------|-------|---------|
| `n8n-nodes-base.code` | ~55 | JavaScript data processing |
| `n8n-nodes-base.slack` | ~45 | User communication |
| `@n8n/n8n-nodes-langchain.informationExtractor` | ~23 | LLM-based data extraction |
| `@n8n/n8n-nodes-langchain.lmChatOpenRouter` | ~23 | OpenRouter LLM models |
| `n8n-nodes-base.postgres` | ~22 | Database operations |
| `n8n-nodes-base.googleDocs` | ~17 | Document operations |
| `n8n-nodes-base.googleSheets` | ~12 | Spreadsheet operations |
| `n8n-nodes-base.executeWorkflow` | ~10 | Subworkflow calls |
| `n8n-nodes-base.if` / `switch` | ~10 | Conditional branching |
| `n8n-nodes-base.executeWorkflowTrigger` | ~10 | Workflow triggers |
| `n8n-nodes-base.manualTrigger` | ~5 | Manual triggers |
| `n8n-nodes-base.scheduleTrigger` | ~3 | Scheduled triggers |
| `n8n-nodes-base.httpRequest` | ~2 | HTTP fetching |
| `@searchapi/n8n-nodes-searchapi.searchApi` | 1 | SearchApi integration |
| `n8n-nodes-base.markdown` | ~2 | HTML-to-markdown |
| `n8n-nodes-base.html` | ~4 | Markdown-to-HTML |
| `n8n-nodes-base.aggregate` | ~2 | Data aggregation |
| `n8n-nodes-base.splitInBatches` | ~1 | Batch processing |
| `n8n-nodes-base.set` | ~2 | Field mapping |
| `n8n-nodes-base.stopAndError` | ~5 | Error termination |
| `n8n-nodes-base.stickyNote` | ~10 | Documentation |
| `@n8n/n8n-nodes-langchain.chatTrigger` | ~5 | Chat interface triggers |
