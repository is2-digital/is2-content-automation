# is2-content-automation

This project's purpose is to rebuild the n8n project (is2-news) as a standalone Python application that replicates the full behavior of the n8n system.

_n8n-project is currently an n8n-based workflow automation platform for AI newsletter generation. It consists of 12 interconnected workflows (1 main orchestrator, 8 subworkflows, 2 utilities, 1 article curation scheduler) totaling ~151 nodes across ~500KB of JSON. The system uses human-in-the-loop approvals via Slack, AI content generation via OpenRouter, data persistence in PostgreSQL, and document management via Google Docs/Sheets.

