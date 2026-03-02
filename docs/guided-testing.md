# Guided Pipeline Testing

Run the full newsletter pipeline step-by-step with operator checkpoints. Each step pauses for your approval before proceeding, and all outputs are tracked in a reviewable artifact ledger.

---

## Prerequisites

### 1. Running Services

Start the dev environment so PostgreSQL, Redis, and the app container are available:

```bash
make dev
```

### 2. Slack Configuration

The guided flow uses real Slack interactions for approvals and feedback. You need:

| Env Var | Purpose |
|---|---|
| `SLACK_BOT_TOKEN` | `xoxb-...` bot token |
| `SLACK_APP_TOKEN` | `xapp-...` socket mode token |
| `SLACK_CHANNEL` | Channel ID for the test run |

The bot must be invited to the channel and have interactivity enabled. See [credentials.md](credentials.md) for full Slack setup instructions.

**Tip:** Use a dedicated test channel (e.g., `#ica-testing`) to keep test messages separate from production.

### 3. Google Services Configuration

Steps that create Google Docs or write to Google Sheets need test-specific targets so production resources are not modified:

| Env Var | Required By | Purpose |
|---|---|---|
| `GUIDED_TEST_SPREADSHEET_ID` | Curation, Summarization | A Google Sheet reserved for test data |
| `GUIDED_TEST_DRIVE_FOLDER_ID` | Markdown/HTML generation, Email, Social, Carousel | A Drive folder where test docs are created |

Add these to your `.env` file. The service account must have edit access to both resources. If these are not set, the guided runner will show an error at startup listing exactly which variables are missing and which steps need them.

### 4. Other Required Services

- **OpenRouter API key** (`OPENROUTER_API_KEY`) — for LLM calls
- **Brave Search API key** (`BRAVE_API_KEY`) — for article collection (step 1)
- **Google service account** — JSON key at `credentials/google-service-account.json`

---

## Running a Guided Test

### Full Run (Start to Finish)

```bash
make shell
python -m ica guided
```

This creates a new run, generates a short run ID (e.g., `a3f1b2c9`), and begins at step 1 (Article Curation). You will be prompted at each checkpoint.

### Full Run with Fixture Data

Use `--seed` to auto-provision deterministic test data (10 articles, summaries, themes) so you don't need to wait for real article collection:

```bash
python -m ica guided --seed 42
```

The same seed always produces identical fixture data, making runs reproducible.

### Start from a Specific Step

Skip earlier steps by combining `--seed` with `--step`. All prerequisite data is auto-provisioned:

```bash
python -m ica guided --seed 42 --step theme_generation
```

Valid step names: `curation`, `summarization`, `theme_generation`, `markdown_generation`, `html_generation`, `alternates_html`, `email_subject`, `social_media`, `linkedin_carousel`.

### Adjust Slack Timeout

By default, each Slack interaction waits up to 300 seconds. Override this for longer review periods:

```bash
python -m ica guided --slack-timeout 600   # 10 minutes
python -m ica guided --slack-timeout 0     # Wait indefinitely
```

### Pin an HTML Template Version

```bash
python -m ica guided --template-name default --template-version 1.0.0
```

---

## Operator Checkpoints

After each step completes (or fails), the runner pauses and shows the step result along with any artifacts (Google Doc URLs, article counts, etc.). You choose one of three actions:

| Action | Key | Effect |
|---|---|---|
| **Continue** | `c` | Advance to the next step |
| **Redo** | `r` | Re-run the current step (increments attempt counter) |
| **Stop** | `s` | Save state and exit |

If a step **failed**, only Redo and Stop are available — you cannot continue past a failed step.

### Redo Behavior

- **Google Docs steps** — redo creates a *new* document. The previous document remains on Drive and its ID is preserved in the artifact history, so you can compare attempts side by side.
- **Google Sheets steps** — redo appends new rows tagged with the attempt number. Data from all attempts remains visible in the same spreadsheet.
- **Slack messages** — redo messages include `(attempt N)` in the tag so you can distinguish them in the channel.

---

## Resuming a Run

State is persisted to `.guided-runs/` as JSON after every step. If you stop (or the process is interrupted), resume with:

```bash
python -m ica guided --run-id <run-id>
```

### List Existing Runs

```bash
python -m ica guided --list
```

Output shows each run's ID, phase (running/checkpoint/completed/aborted), and current step position.

---

## Reviewing Artifacts

Every output and external interaction is recorded in an append-only artifact ledger (`<run-id>-artifacts.json`).

### View All Artifacts for a Run

```bash
python -m ica guided artifacts <run-id>
```

### Filter by Step

```bash
python -m ica guided artifacts <run-id> --step html_generation
```

### Filter by Artifact Type

```bash
python -m ica guided artifacts <run-id> --type google_doc
```

Valid types: `slack_decision`, `google_doc`, `google_sheet`, `llm_output`, `validation_result`, `fixture_data`.

### Show Full Values

By default, long values are truncated to 80 characters. Use `--verbose` to see everything:

```bash
python -m ica guided artifacts <run-id> -v
```

### Machine-Readable Output

```bash
python -m ica guided artifacts <run-id> --json
```

---

## Pipeline Steps Reference

The guided flow runs all 9 steps sequentially (the 4 normally-parallel output steps are flattened):

| # | Step | Slack Interactions | Google Resources |
|---|---|---|---|
| 1 | **Curation** | Approval form | Writes to Sheets |
| 2 | **Summarization** | Per-article review + feedback | Writes to Sheets |
| 3 | **Theme Generation** | Theme selection (radio buttons) | — |
| 4 | **Markdown Generation** | — | Creates Doc |
| 5 | **HTML Generation** | — | Creates Doc |
| 6 | **Alternates HTML** | — | — |
| 7 | **Email Subject** | Subject line selection | Creates Doc |
| 8 | **Social Media** | Post selection | Creates Doc |
| 9 | **LinkedIn Carousel** | — | Creates Doc |

---

## Troubleshooting

### "Missing guided-mode Google settings"

The runner validates Google settings at startup. If you see this error, set the indicated environment variables in your `.env` file:

```
GUIDED_TEST_SPREADSHEET_ID=<your-test-spreadsheet-id>
GUIDED_TEST_DRIVE_FOLDER_ID=<your-test-drive-folder-id>
```

Then restart the guided run.

### Slack Timeout

If a step fails with `Slack timeout: ...`, the operator did not respond within the configured timeout. Options:

- Increase the timeout: `--slack-timeout 600`
- Disable the timeout entirely: `--slack-timeout 0`
- Redo the step at the checkpoint prompt

### Step Fails with "Slack API error"

Check that:
1. The bot is invited to the target channel.
2. Socket Mode is enabled for the Slack app.
3. `SLACK_BOT_TOKEN` and `SLACK_APP_TOKEN` are valid (tokens can expire if the app is reinstalled).

### Google Docs/Sheets Errors

Check that:
1. The service account JSON key exists at the expected path.
2. The service account email has **edit** access to the test spreadsheet and Drive folder.
3. The Google Drive API, Sheets API, and Docs API are enabled in the Cloud project.

### Process Interrupted Mid-Step

The run state is saved automatically. Resume with `--run-id`. The interrupted step will be retried from scratch (attempt counter increments) since a partially-executed step cannot be trusted.

### "Run not found" on Resume

List available runs with `--list` and verify the run ID. State files are stored in `.guided-runs/` by default; if you used `--store-dir`, pass the same directory on resume.

---

## Cleanup

### Remove Fixture Test Runs Only

Deletes state files whose run ID starts with `fixture-` (from `--seed` runs):

```bash
python -m ica guided --cleanup
```

### Manual Cleanup

State files live in `.guided-runs/`:
- `<run-id>.json` — run state (phase, steps, decisions, context snapshot)
- `<run-id>-artifacts.json` — artifact ledger

Delete specific run files to remove them from `--list`.

### Google Resources

The guided runner creates Google Docs and writes to Sheets during test runs. These are **not** automatically deleted. To clean up:

1. Check the artifact ledger for document URLs: `python -m ica guided artifacts <run-id> --type google_doc`
2. Open each URL and delete or move to trash.
3. For Sheets, delete test rows from the guided test spreadsheet.

**Safety note:** The service account cannot delete files from Shared Drives. A Drive member with Manager permissions must delete them.

---

## CLI Reference

```
python -m ica guided [OPTIONS]
```

| Option | Default | Description |
|---|---|---|
| `--run-id, -r` | | Resume an existing run |
| `--store-dir` | `.guided-runs` | Directory for persisted state |
| `--list, -l` | | List existing runs |
| `--seed, -s` | | Auto-provision fixture data with this seed |
| `--step` | | Start from a specific step (requires `--seed`) |
| `--cleanup` | | Remove fixture-generated state files |
| `--slack-timeout` | `0` | Timeout in seconds for Slack calls (0 = no timeout) |
| `--template-name` | `default` | HTML template name |
| `--template-version` | | Pin a specific template version |

```
python -m ica guided artifacts <run-id> [OPTIONS]
```

| Option | Default | Description |
|---|---|---|
| `--store-dir` | `.guided-runs` | Directory for persisted state |
| `--step` | | Filter by pipeline step name |
| `--type` | | Filter by artifact type |
| `--verbose, -v` | | Show full artifact values |
| `--json` | | Output as JSON |
