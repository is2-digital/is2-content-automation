# Credentials Setup

All credentials are loaded via environment variables (or `.env` file in the project root). Never commit secrets to git.

## 1. PostgreSQL

| Env Var | Default |
|---|---|
| `POSTGRES_HOST` | `postgres` |
| `POSTGRES_PORT` | `5432` |
| `POSTGRES_DB` | `n8n_custom_data` |
| `POSTGRES_USER` | `ica` |
| `POSTGRES_PASSWORD` | *(required)* |

**Setup:** Docker provisions the database automatically — the `postgres` service in `docker-compose.yml` creates the user and database from the `POSTGRES_*` env vars on first start. No manual SQL required.

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
| `GOOGLE_SHEETS_SPREADSHEET_ID` | Spreadsheet ID from URL |
| `GOOGLE_SHARED_DRIVE_ID` | Shared Drive ID (optional — auto-discovered if blank) |

The service account JSON key file defaults to `credentials/google-service-account.json` (one file for both Sheets and Docs). Override with `GOOGLE_SERVICE_ACCOUNT_CREDENTIALS_PATH` env var if needed.

**Setup:**

1. Go to [console.cloud.google.com](https://console.cloud.google.com) → create or select a project.
2. **APIs & Services** → Enable **Google Drive API**, **Google Sheets API**, and **Google Docs API**.
3. **Credentials** → **Create Credentials** → **Service Account**.
4. On the service account page → **Keys** tab → **Add Key** → **JSON**. Download the file.
5. Copy the downloaded file to `credentials/google-service-account.json` (see `credentials/google-service-account.example.json` for the expected format).
6. Create a **Shared Drive** in Google Drive and add the service account email (`...@...iam.gserviceaccount.com`) as a **Content Manager**. All files (Docs, Sheets) are created inside this Shared Drive because the service account has no Drive storage quota of its own.
7. (Optional) Set `GOOGLE_SHARED_DRIVE_ID` in `.env` to the Shared Drive ID. If left blank, the app auto-discovers the first accessible Shared Drive.

**Important:** The service account **cannot delete files** from the Shared Drive. Files must be deleted manually by a Drive member with Manager permissions. This is by design — the Content Manager role allows create/edit but not delete.

**Security notes:**
- Service accounts are preferable to OAuth2 user credentials — no refresh token expiry, no browser flow.
- The JSON key file is a bearer credential with no expiry. Protect it: `chmod 600`, don't commit it, don't put it in Docker images.
- Scope access by only sharing specific Sheets/Docs with the service account — it can't access anything else in your Google Drive.
- Consider using Workload Identity Federation instead of key files in cloud deployments (eliminates long-lived keys entirely).

## 5. Google Custom Search (Article Collection)

| Env Var | Value |
|---|---|
| `GOOGLE_CSE_API_KEY` | API key from Google Cloud Console |
| `GOOGLE_CSE_CX` | Search Engine ID from Programmable Search Engine |

**Setup:**

1. Go to [console.cloud.google.com](https://console.cloud.google.com) → use the same project as your Sheets/Docs service account.
2. **APIs & Services** → **Library** → search for **Custom Search API** → **Enable**.
3. **Credentials** → **Create Credentials** → **API Key**. Copy the key — this is `GOOGLE_CSE_API_KEY`.
4. (Recommended) Click **Restrict Key** → under **API restrictions**, select **Custom Search API** only.
5. Go to [programmablesearchengine.google.com/controlpanel/all](https://programmablesearchengine.google.com/controlpanel/all) → **Add** a new search engine.
6. Under **What to search**, select **Search the entire web**.
7. Give it a name (e.g., `ica-news`) → **Create**.
8. On the **Overview** page, copy the **Search engine ID** — this is `GOOGLE_CSE_CX`.

**Pricing:** 100 free queries/day (we use ~8). Additional queries cost $5/1,000 if billing is enabled.

**Security notes:**
- Restrict the API key to the Custom Search API only — this limits blast radius if leaked.
- The key provides read-only search access. Low risk, but still costs money if billing is enabled.
- Set billing alerts in Google Cloud Console to catch unexpected usage.

## `.env` Template

```bash
# PostgreSQL
POSTGRES_PASSWORD=
# POSTGRES_HOST=postgres
# POSTGRES_PORT=5432

# LLM
OPENROUTER_API_KEY=

# Slack
SLACK_BOT_TOKEN=xoxb-
SLACK_APP_TOKEN=xapp-
SLACK_CHANNEL=

# Google APIs
# Service account key: copy to credentials/google-service-account.json
GOOGLE_SHEETS_SPREADSHEET_ID=
GOOGLE_SHARED_DRIVE_ID=

# Google Custom Search
GOOGLE_CSE_API_KEY=
GOOGLE_CSE_CX=
```

## General Security Practices

- **Never commit `.env` or credential JSON files.** Verify `.gitignore` includes both.
- **Rotate keys** if you suspect a leak. OpenRouter and Google CSE keys can be regenerated instantly; Slack tokens require re-install; Google service account keys can be added/revoked without re-sharing.
- **Least privilege:** every credential above is scoped to exactly what the app needs — keep it that way.
- **In production:** use a secrets manager (e.g., AWS Secrets Manager, GCP Secret Manager, HashiCorp Vault) instead of `.env` files.
