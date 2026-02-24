# ICA — Master Development & Integration Roadmap

> **Status as of 2026-02-23:** The codebase is **feature-complete at the code level**. All 389 tracked implementation tasks are closed. Every pipeline step, service integration, and utility is implemented with unit tests.
> **Current Phase:** Moving from "Mocked Unit Testing" to "Real-World Integration and Production Readiness."

---

## 1. Executive Summary of Implementation

The system is fully written but has not yet "touched" the real internet. All 57 test files currently utilize mocks.

### Codebase Statistics

| Component | Files | Lines | Coverage / Status |
| --- | --- | --- | --- |
| **Pipeline & Orchestration** | 14 | 7,784 | 12 steps + adapter + Slack feedback loops |
| **Prompt Templates** | 13 | 3,256 | Ported from n8n; 21-model configuration |
| **Core Services** | 7 | 1,590 | Async Slack, Google, LLM, and Search clients |
| **Data & Config** | 11 | 903 | SQLAlchemy 2.0, Alembic, Pydantic Settings |
| **Utilities & Validators** | 7 | 805 | Marker parsing, character counting, routing |
| **App & Infra** | 14 | 1,343+ | FastAPI, CLI, Scheduler, Multi-stage Docker |
| **Tests** | **57** | **32,542** | **Unit tests pass (all modules covered via mocks)** |

---

## 2. Environment Setup & First Boot

**Goal:** Transition from a local mock environment to a functional "Live" dev environment.

* [ ] **Database:** Provision PostgreSQL 16 instance and execute `alembic upgrade head`.
* [ ] **Slack Integration:** Create Slack app (Socket Mode) with bot/app tokens as per `docs/credentials.md`.
* [ ] **Google Cloud:** Setup Service Account, enable Sheets/Docs APIs, and share target folders.
* [ ] **API Keys:** Secure OpenRouter (LLM) and SearchApi (Google News) credentials.
* [ ] **Secrets Management:** Populate `.env` file and verify `ica/config/settings.py` loads all 21 model overrides.
* [ ] **Service Health:** Run `python -m ica serve` and verify the `/health` endpoint and Slack Socket Mode handshake.

---

## 3. Integration & Pipeline Verification

**Goal:** Exercise the "Verification Plan" using real data and API responses.

### Phase A: Data Collection & Curation

* [ ] **Article Collection:** Run `collect-articles` CLI. Verify SearchApi results, deduplication, and PG storage.
* [ ] **Curation Loop:** Verify Google Sheet population and Slack approval triggers.

### Phase B: Content Processing

* [ ] **Summarization:** Test HTTP fetching (handling redirects/paywalls) and LLM summary JSON structure.
* [ ] **Theme Generation:** Validate `%XX_` marker parsing from real LLM output via `marker_parser.py`.
* [ ] **Freshness Check:** Confirm Gemini 2.5 Flash executes the "freshness" logic correctly.

### Phase C: Generation & Validation

* [ ] **Markdown Generation:** Execute the 3-layer validation (Structural LLM, Voice LLM, Character Count).
* [ ] **HTML & Google Docs:** Verify Markdown-to-HTML conversion and final document creation in Google Drive.
* [ ] **Parallel Outputs:** Run steps 6a-6d (Social, LinkedIn, etc.) via `asyncio.gather()` and verify concurrent Slack notifications.

### Phase D: The Learning System

* [ ] **Feedback Loop:** Run the pipeline twice; verify that feedback from Run 1 is injected into Run 2 prompts.

---

## 4. Prompt Tuning & Quality Assurance

**Goal:** Ensure LLM outputs match the specific formatting requirements of the legacy n8n system.

* [ ] **Marker Consistency:** Ensure the LLM doesn't deviate from the `%XX_` theme marker format.
* [ ] **Voice Calibration:** Test the ~4,000-word markdown prompt; verify character counts land in range *before* the retry loop kicks in.
* [ ] **Validation Reliability:** Ensure GPT-4.1 returns parseable JSON error arrays rather than conversational text.
* [ ] **LinkedIn Formatting:** Verify slide character validation catches violations and regenerates correctly.

---

## 5. Production & Operational Readiness

### Deployment

* [ ] **Docker:** Build and test `docker-compose.prod.yml`.
* [ ] **Supervision:** Configure Gunicorn workers and container restart policies.
* [ ] **Monitoring:** Set up log aggregation (JSON) and uptime monitoring for the `/health` endpoint.
* [ ] **Safety:** Configure OpenRouter/SearchApi billing alerts and spending limits.

### Hardening & Resilience

* [ ] **Rate Limiting:** Verify exponential backoff for 429 errors from LLM providers.
* [ ] **Persistence:** (Future) Implement pipeline state persistence to resume mid-step after a crash.
* [ ] **Graceful Shutdown:** Test handling of in-progress Slack interactions during container SIGTERM.
* [ ] **Backups:** Schedule automated backups for the PostgreSQL `notes` and `articles` tables.

---

## 6. Architecture Reference

### Technology Stack

* **Runtime:** Python 3.12+ (FastAPI / Typer CLI)
* **LLM Orchestration:** LiteLLM → OpenRouter (Claude 3.5 Sonnet, GPT-4.1, Gemini 2.5 Flash)
* **Database:** PostgreSQL 16 (SQLAlchemy 2.0 Async + Alembic)
* **Integrations:** Slack Bolt (Socket Mode), Google API Client, SearchApi, HTTPX

### Core Risk Table

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Prompt Drift | High | Ported n8n prompts may behave differently on new models; require iterative tuning. |
| Marker Parsing | Medium | `%XX_` markers are brittle; `marker_parser.py` needs real-world LLM stress testing. |
| Slack Timeouts | Low | Long-running pipelines might drop Socket Mode connections; check keep-alive logic. |
| API Quotas | Medium | Parallel steps (6a-6d) might spike Google/OpenRouter usage; implement circuit breakers. |

