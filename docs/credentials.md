# Credentials Setup

All credentials are loaded via environment variables (or `.env` file in the project root). Never commit secrets to git.

## 1. PostgreSQL

| Env Var | Default |
|---|---|
| `POSTGRES_HOST` | `localhost` |
| `POSTGRES_PORT` | `5432` |
| `POSTGRES_DB` | `n8n_custom_data` |
| `POSTGRES_USER` | `ica` |
| `POSTGRES_PASSWORD` | *(required)* |

**Setup:** Create a dedicated user with permissions scoped to the `n8n_custom_data` database only.

```sql
CREATE USER ica WITH PASSWORD 'your-strong-password';
CREATE DATABASE n8n_custom_data OWNER ica;
```

**Security notes:**
- Use a strong, unique password (not shared with other services).
- Restrict the user to this database only — don't use a superuser account.
- In production, use SSL connections (`?sslmode=require` in the connection string).
- The password appears in the computed `database_url`, so protect `.env` file permissions (`chmod 600`).

## 2. OpenRouter (LLM)

| Env Var |
|---|
| `OPENROUTER_API_KEY` |

**Setup:** [openrouter.ai/keys](https://openrouter.ai/keys) — create an API key.

**Security notes:**
- Set a monthly spending limit on your OpenRouter account.
- This single key grants access to all models (Claude, GPT-4.1, Gemini). If compromised, an attacker can run up your bill quickly.
- OpenRouter supports per-key rate limits — use them.

## 3. Slack App

| Env Var | Format |
|---|---|
| `SLACK_BOT_TOKEN` | `xoxb-...` |
| `SLACK_APP_TOKEN` | `xapp-...` |
| `SLACK_CHANNEL` | Channel ID or name |

**Setup:**

1. Go to [api.slack.com/apps](https://api.slack.com/apps) → **Create New App** → **From scratch**.
2. **Socket Mode** (left sidebar) → Enable. This generates the `xapp-` app token.
3. **OAuth & Permissions** → Add bot scopes: `chat:write`, `channels:read`, `groups:read`, `im:read`, `mpim:read`.
4. **Install to Workspace** → Copy the `xoxb-` bot token.
5. **Interactivity** → Enable (required for `sendAndWait` button callbacks).
6. Invite the bot to your target channel (`/invite @your-bot-name` in `#n8n-is2`).

**Security notes:**
- Socket Mode is preferred over HTTP webhooks — no public endpoint needed, smaller attack surface.
- The bot token can post messages to any channel it's invited to. Limit scope by only inviting it to the one channel.
- App tokens (`xapp-`) have broad connection-level access. Store them as carefully as the bot token.

## 4. Google APIs (Sheets + Docs)

| Env Var | Value |
|---|---|
| `GOOGLE_SHEETS_CREDENTIALS_PATH` | Path to JSON key file |
| `GOOGLE_DOCS_CREDENTIALS_PATH` | Path to JSON key file |
| `GOOGLE_SHEETS_SPREADSHEET_ID` | Spreadsheet ID from URL |

You can use one service account for both, pointing both env vars to the same file.

**Setup:**

1. Go to [console.cloud.google.com](https://console.cloud.google.com) → create or select a project.
2. **APIs & Services** → Enable **Google Sheets API** and **Google Docs API**.
3. **Credentials** → **Create Credentials** → **Service Account**.
4. On the service account page → **Keys** tab → **Add Key** → **JSON**. Download the file.
5. Share your Google Sheet and output Docs folder with the service account email (`...@...iam.gserviceaccount.com`) as **Editor**.

**Security notes:**
- Service accounts are preferable to OAuth2 user credentials — no refresh token expiry, no browser flow.
- The JSON key file is a bearer credential with no expiry. Protect it: `chmod 600`, don't commit it, don't put it in Docker images.
- Scope access by only sharing specific Sheets/Docs with the service account — it can't access anything else in your Google Drive.
- Consider using Workload Identity Federation instead of key files in cloud deployments (eliminates long-lived keys entirely).

## 5. SearchApi

| Env Var |
|---|
| `SEARCHAPI_API_KEY` |

**Setup:** [searchapi.io](https://www.searchapi.io/) → sign up → copy API key from dashboard.

**Security notes:**
- SearchApi charges per query. Set billing alerts to catch unexpected usage.
- The key only provides read access to search results — low blast radius if leaked, but still costs money.

## `.env` Template

```bash
# PostgreSQL
POSTGRES_PASSWORD=
# POSTGRES_HOST=localhost
# POSTGRES_PORT=5432

# LLM
OPENROUTER_API_KEY=

# Slack
SLACK_BOT_TOKEN=xoxb-
SLACK_APP_TOKEN=xapp-
SLACK_CHANNEL=

# Google APIs (can be the same file for both)
GOOGLE_SHEETS_CREDENTIALS_PATH=./credentials/google-service-account.json
GOOGLE_DOCS_CREDENTIALS_PATH=./credentials/google-service-account.json
GOOGLE_SHEETS_SPREADSHEET_ID=

# SearchApi
SEARCHAPI_API_KEY=
```

## General Security Practices

- **Never commit `.env` or credential JSON files.** Verify `.gitignore` includes both.
- **Rotate keys** if you suspect a leak. OpenRouter and SearchApi keys can be regenerated instantly; Slack tokens require re-install; Google service account keys can be added/revoked without re-sharing.
- **Least privilege:** every credential above is scoped to exactly what the app needs — keep it that way.
- **In production:** use a secrets manager (e.g., AWS Secrets Manager, GCP Secret Manager, HashiCorp Vault) instead of `.env` files.
