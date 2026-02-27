# ICA User Guide

ICA (is2-content-automation) automates the end-to-end production of the weekly AI newsletter published at [is2digital.com/newsletters](https://www.is2digital.com/newsletters). It replaces a 12-workflow n8n system with a standalone Python application designed for solopreneurs and SMB professionals interested in AI, automation, and business strategy.

---

## System Architecture & Modes

ICA operates in two primary modes:

### 1. Article Collection (Automatic)

A background job discovers AI-related articles on independent schedules:

* **Daily**: Searches Google News for 3 broad keywords: *AGI, Automation, Artificial Intelligence*. (Up to 15 results each, filtered to the last week, US location).
* **Every 2 days**: Searches the web for 5 specific keywords: *AI breakthrough, AI latest, AI tutorial, AI case study, AI research*. (Up to 10 results each).

**Processing**: Results are deduplicated by URL, dates are parsed from relative formats (e.g., "3 days ago"), and all records are upserted into the PostgreSQL database to populate the article pool.

### 2. Newsletter Pipeline (Manual or Scheduled)

Triggered on demand or every 5 days. It runs 6 sequential steps, with the final steps branching into parallel outputs.

---

## The 6-Step Pipeline

### Step 1: Article Curation

Surfaces up to 30 unapproved articles in a **Google Sheet**. You review the sheet, mark articles as `approved=yes`, and assign a `newsletter_id`. The pipeline blocks on a Slack approval form until you click "Proceed." It validates that at least one article is approved with a ID before continuing.

### Step 2: Summarization

For each approved article:

* **Fetching**: Fetches full page content via HTTP with browser-like headers. If fetching fails (captcha, YouTube, etc.), you are prompted in Slack to paste the content manually.
* **Generation**: Calls **Claude Sonnet 4.5** to produce a 3-4 sentence factual summary and 2-3 sentences of business relevance commentary.
* **Review**: Summaries appear in Slack. You can approve, provide feedback (triggers regeneration), or restart the step.

### Step 3: Theme Generation

* **Candidates**: LLM generates 2 candidate themes, assigning articles into positions: *Featured Article, 2 Main Articles, 3 Quick Hits, and 2 Industry Developments*.
* **Freshness Check**: After you select a theme via Slack radio buttons, **Gemini Flash** compares it against recent newsletters to flag repetitive content.

### Step 4: Markdown Generation

Produces the full newsletter body in a branded editorial voice. It uses a **3-layer validation system**:

| Layer | Method | What It Checks |
| --- | --- | --- |
| **1. Character Counts** | Code-based | Ensures sections hit targets (e.g., Quick Hits: 150-190 chars). |
| **2. Structural** | GPT-4.1 | Verifies headings, formatting, and CTA patterns. |
| **3. Voice** | GPT-4.1 | Verifies tone, contractions, authority, and humor. |

Errors are fed back to the LLM for correction (up to 3 attempts). Once passed, a **Google Doc** is created for final human edits.

### Step 5: HTML Generation

Fetches the approved markdown from the Google Doc (incorporating your manual edits). **Claude Sonnet 4.5** converts it into a responsive, inline-CSS email template, saved as a new Google Doc.

### Step 6: Parallel Outputs

Once the main HTML is generated, four processes run concurrently:

* **6a. Alternates HTML**: Generates an A/B email variant from unused articles.
* **6b. Email Subject**: Generates 3-5 subject line + preview text options for selection.
* **6c. Social Media**: Generates 12 post concepts (6 "Did You Know" + 6 "Industry Take"), followed by detailed captions (150-300 chars) for selections.
* **6d. LinkedIn Carousel**: Generates multi-slide content (265-315 chars per slide) and 3 post copy versions.

---

## Human-in-the-Loop & Learning

All editorial decisions happen in the `#n8n-is2` Slack channel. The system uses three interaction patterns: **Approve/Feedback**, **Radio Button Selection**, and **Manual Data Entry**.

### The Learning Loop

Every time you provide feedback, ICA:

1. Regenerates the content immediately.
2. Uses an LLM to distill your feedback into 2-3 sentence actionable insights.
3. Stores these insights in the database.
4. **Injects the last 40 feedback entries** into future LLM prompts to ensure your editorial preferences compound over time.

---

## Running the Application

All commands run inside Docker containers via `make` targets. There is no local/bare-metal install path.

### Commands

| Command | What It Does |
|---|---|
| `make dev` | Start the dev environment (app + PostgreSQL + Redis) |
| `make run-pipeline` | Trigger a pipeline run via the API |
| `make pipeline-status` | Show pipeline run status |
| `make collect` | Manually trigger article collection |
| `make migrate` | Run database migrations to latest |
| `make logs` | Tail container logs |
| `make down` | Stop all containers |

For direct CLI access inside the container, use `make shell` to open a bash session in the app container.

### External Services

* **LLMs**: Claude Sonnet 4.5 (Primary), GPT-4.1 (Validation), Gemini Flash (Freshness).
* **Storage**: PostgreSQL (Data), Google Sheets (Curation), Google Docs (Outputs).
* **Search**: Google Custom Search (Article discovery).

