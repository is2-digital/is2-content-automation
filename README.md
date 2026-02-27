# ICA (is2-content-automation)

Automated AI newsletter generation pipeline for [is2digital.com/newsletters](https://is2digital.com/newsletters). This application is a high-performance Python replacement for a legacy 12-workflow n8n system (originally 281 nodes).

ICA discovers articles via web search, curates them through Slack-based editorial review, generates content using multiple LLMs via OpenRouter, validates it automatically, and produces all deliverables with human approval at every step.

## Project Status (February 2026)

* **Core Development:** Complete. All 389 tracked tasks are closed with zero TODOs in the codebase.
* **Testing:** Comprehensive mock-based test suite covering all pipeline steps, services, prompts, and configs.
* **Next Steps:** Transitioning from mock environments to live integration with external credentials (Slack, Google, OpenRouter, etc.).

---

## How It Works

The system consists of two independent processes:

### 1. Article Collector (Automated)

* **Daily:** Searches Google News for AGI, Automation, and AI (15 results each).
* **Every 2 Days:** Searches the web for 5 specific AI keywords (10 results each).
* **Processing:** Deduplicates, parses dates, and upserts into PostgreSQL.

### 2. Newsletter Pipeline (Manual or Every 5 Days)

| Step | Process | User Interaction (Slack/Google) |
| --- | --- | --- |
| **1. Curation** | Articles synced to Google Sheet | Mark approved & click **Proceed** in Slack |
| **2. Summarization** | HTTP fetch + LLM summary + feedback loop | Approve or provide feedback |
| **3. Theme Gen** | LLM proposes 2 themes via radio buttons | Pick one theme via Slack |
| **4. Markdown** | LLM writes body; 3-layer auto-validation | Approve or edit in Google Docs |
| **5. HTML** | Markdown converted to email-ready HTML | Review final layout in Slack |
| **6. Parallel** | Alt HTML, Subjects, Social Posts, LinkedIn Carousel | Select/approve each deliverable |

---

## Tech Stack

| Component | Technology |
| --- | --- |
| **Runtime** | Python 3.12+ |
| **Web Framework** | FastAPI + Uvicorn |
| **CLI** | Typer + Rich |
| **Database** | PostgreSQL 16 + SQLAlchemy 2.0 (Async) + Alembic |
| **LLMs** | LiteLLM via OpenRouter (Claude Sonnet 4.5, GPT-4.1, Gemini 2.5 Flash) |
| **Slack** | Slack Bolt (Socket Mode) |
| **Google APIs** | Sheets + Docs via Service Account |
| **Cache** | Redis 7 |
| **Scheduler** | APScheduler |

---

## The Validation System (Step 4)

The newsletter generation uses a rigorous 3-layer validation check before presenting the draft to the user:

1. **Character Counting:** Python logic ensures sections (e.g., "Quick Highlights") hit specific target ranges.
2. **Structural Validation (GPT-4.1):** Checks heading order, link formatting, and CTA patterns.
3. **Voice Validation (GPT-4.1):** Enforces tone, contractions, authority, and formatting frequency.

*Note: If errors are found, the system attempts up to 3 regenerations before force-accepting.*

---

## Project Structure

```text
ica/
├── config/          Settings, LLM model mapping, startup validation
├── pipeline/        12 pipeline steps + orchestrator + step adapter
├── services/        Slack, LLM, Google Sheets/Docs, SearchApi, web fetcher
├── llm_configs/     19 JSON process configs (model + prompts per LLM task)
├── prompts/         Prompt builder functions (dynamic interpolation over JSON configs)
├── validators/      Character count and structural validation logic
├── db/              SQLAlchemy models (Articles, Themes, Notes), CRUD, Alembic
├── utils/           Date parsing, marker parsing, boolean normalization
├── app.py           FastAPI (Endpoints: /trigger, /status, /health)
├── scheduler.py     APScheduler for collection and pipeline triggers
├── errors.py        Exception hierarchy + Slack error notifications
└── logging.py       Structured logging with async context vars

```

---

## Quick Start

### Prerequisites

* Docker & Docker Compose
* API Keys: OpenRouter, Slack (Bot + App tokens), Google Service Account, Google Custom Search

### Setup

```bash
# Configure environment
cp .env-example .env
# Edit .env with your credentials (see docs/credentials.md)

# Copy your Google service account JSON key into the credentials directory
cp ~/path-to-downloaded-key.json credentials/google-service-account.json

# Start the dev environment (app + PostgreSQL + Redis)
make dev

# In a separate terminal, run database migrations
make migrate
```

### Running the Application

```bash
make run-pipeline                # Trigger a pipeline run
make pipeline-status             # Show pipeline run status
make collect                     # Run article collection manually
```

Run `make help` to see all available targets.

---

## Development & Testing

All commands run inside Docker containers via `make` targets.

```bash
make test                        # Run all tests (mock-based)
make test ARGS="-k test_name"    # Run tests matching name
make lint                        # Ruff linter
make format                      # Ruff auto-format
make typecheck                   # mypy type checking
```

---

## Documentation

* `docs/credentials.md` — Detailed setup for external services.
* `docs/user-guide.md` — End-user functionality guide.
