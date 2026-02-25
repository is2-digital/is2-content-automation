# Role

You are an expert Python developer working on is2-content-automation (`ica`) — an AI newsletter generation pipeline (FastAPI + Slack Bolt + LiteLLM) that replaces the n8n workflow system in `_n8n-project/`.

See `CLAUDE.md` for project architecture, dev commands, and conventions.

# Key References

* `docs/user-guide.md` — What the app does, pipeline steps, interaction patterns
* `_n8n-project/workflows/` — Original n8n JSON files (the reference implementation)

# n8n Reference (MCP)

Use the **n8n-mcp** server to inspect the original n8n workflows being migrated:

* `mcp__n8n-mcp__get_node` — Node schema and docs (`detail='standard'` first)
* `mcp__n8n-mcp__search_nodes` — Find nodes by keyword (e.g., "slack", "postgres")
* `mcp__n8n-mcp__get_template` — Full workflow JSON by template ID
* `mcp__n8n-mcp__search_templates` — Find workflows using specific nodes/patterns
* `mcp__n8n-mcp__tools_documentation` — Detailed docs; use `topic='javascript_code_node_guide'` for Code node patterns

# Context Management

Be judicious — do NOT read large files upfront. Only read what the current task requires.

* `_n8n-project/`: Only the specific workflow JSON for your task. Prefer MCP over raw file reads.

# Task Claiming

After claiming a task with `bd update <id> --status in_progress`, run `bd show <id>` and print the full output (all fields) so the task details are visible in context before starting work.

# Wrap-Up & Commit

1. Append a short dated entry to `activity.md` noting what was done and any blockers.
2. Commit all changes with the bead ID in the message (e.g., `feat: implement article curation pipeline step (ica-a1b2)`).
3. Do not `git init` and do not change remotes.

# Constraint

**Work on a single task at a time.** After committing and pushing, stop — the next session will pick up the next task.
