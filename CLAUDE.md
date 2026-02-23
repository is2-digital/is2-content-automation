# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a green-field Python rewrite of an n8n-based AI newsletter generation system previously called IS2-News. The original n8n system lives in `_n8n-project/` as reference; the goal is to rebuild it as a standalone Python application with a new name (is2-content-automation, or ica for short). **No Python source code exists yet** — the repo is currently in the design/bootstrapping phase with ~350 pre-loaded implementation tasks.

The target newsletter is published at is2digital.com/newsletters for solopreneurs and SMB professionals interested in AI.

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

## Key Reference Files

| File | What it contains |
|---|---|
| `_context/PRD.md` | Complete functional spec for the Python rewrite (~1128 lines) |
| `_context/project-details.md` | Technical analysis of all 12 n8n workflows: every node, code block, prompt, SQL query (~1397 lines) |
| `_context/tasks.csv` | 350 granular implementation tasks with parent/child relationships |
| `_n8n-project/workflows/` | Source n8n JSON files (the reference implementation to port from) |

## Pipeline Architecture

The newsletter pipeline has sequential steps with a parallel fan-out at the end:

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

## Target Tech Stack

FastAPI + CLI (Click/Typer), LiteLLM (unified LLM via OpenRouter), SQLAlchemy + Alembic + asyncpg (PostgreSQL), Slack Bolt (human-in-the-loop), google-api-python-client (Sheets/Docs), httpx (async HTTP), APScheduler, Pydantic Settings.

## Implementation Phases

1. **Foundation** — scaffolding, DB models, LiteLLM, Slack Bolt, Google APIs, SearchApi, CLI skeleton
2. **Core Pipeline** — article collection utility, curation, summarization, theme generation
3. **Content Generation** — markdown generation (3-layer validation + retry), HTML generation
4. **Parallel Outputs** — alternates HTML, email subject, social media (2-phase), LinkedIn carousel
5. **Polish** — end-to-end tests, error handling, scheduler, CLI, observability

## Domain-Specific Patterns

- **`%XX_` markers** (e.g., `%FA_TITLE`, `%M1_SOURCE`): Used in theme generation step for structured content parsing. See PRD Section 3.3 and `project-details.md` Section 6.
- **Slack `sendAndWait`**: Core human-in-the-loop primitive — implemented via `asyncio.Event` blocking.
- **Feedback tables**: All 5 feedback tables use the same "last 40 entries" pattern for injecting learning data into LLM prompts.
- **Markdown validation**: 3-layer approach — (1) character count code-based, (2) structural LLM, (3) voice LLM — results merged before retry.
- **LLM models**: Primarily `anthropic/claude-sonnet-4.5` via OpenRouter, plus `openai/gpt-4.1` for markdown validation and `google/gemini-2.5-flash` for freshness checks.

## Database

PostgreSQL database `n8n_custom_data` with 7 tables: `articles` (with type discriminator), `themes` (with type discriminator), `summarization_user_feedback`, `newsletter_themes_user_feedback`, `markdowngenerator_user_feedback`, `htmlgenerator_user_feedback`, `newsletter_email_subject_feedback`. Schema details in PRD Section 2.2.
