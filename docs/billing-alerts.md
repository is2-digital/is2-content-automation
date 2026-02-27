# API Billing Alerts and Spending Limits

Cost controls for the two paid external APIs: OpenRouter (LLM) and Google Custom Search Engine (article collection).

## Cost Estimates Per Newsletter Run

### Model Pricing (OpenRouter, Feb 2026)

| Model | Used For | Input/1M | Output/1M |
|---|---|---|---|
| `anthropic/claude-sonnet-4.5` | Summarization, theme, markdown, HTML, email, social, LinkedIn | $3.00 | $15.00 |
| `openai/gpt-4.1` | Markdown structural + voice validation | $2.00 | $8.00 |
| `google/gemini-2.5-flash` | Theme freshness check | $0.30 | $2.50 |

OpenRouter passes through provider pricing with no markup.

### LLM Calls Per Pipeline Run

| Step | Best Case | Typical | Worst Case | Primary Model |
|---|---|---|---|---|
| 2. Summarization (8 articles) | 8 | 12-16 | 24 | Claude Sonnet 4.5 |
| 3. Theme Generation | 1 | 2 | 3 | Claude Sonnet 4.5 + Gemini Flash |
| 4. Markdown Generation | 3 | 7-9 | 13+ | Claude Sonnet 4.5 + GPT-4.1 |
| 5. HTML Generation | 1 | 2 | 3 | Claude Sonnet 4.5 |
| 6a. Alternates HTML | 0 | 0 | 0 | N/A (filtering only) |
| 6b. Email Subject + Preview | 2 | 3 | 5 | Claude Sonnet 4.5 |
| 6c. Social Media | 2 | 3 | 4 | Claude Sonnet 4.5 |
| 6d. LinkedIn Carousel | 1 | 2 | 3 | Claude Sonnet 4.5 |
| **Total** | **18** | **31-37** | **55+** | |

### Estimated Cost Per Newsletter

| Scenario | Claude Sonnet 4.5 | GPT-4.1 | Gemini Flash | Total |
|---|---|---|---|---|
| Best case (no feedback, validation passes) | $0.40 | $0.05 | < $0.01 | ~$0.45 |
| **Typical (some feedback, 1-2 retries)** | **$0.75** | **$0.07** | **< $0.01** | **~$0.82** |
| Worst case (heavy feedback, max retries) | $1.30 | $0.12 | < $0.01 | ~$1.42 |

Assumptions: ~8 articles, ~2500 avg input tokens/call, ~1000 avg output tokens/call. Actual costs depend on article length and prompt complexity.

### Monthly Projections

| Frequency | Typical Monthly Cost | Worst Case Monthly |
|---|---|---|
| Weekly newsletter (4/month) | $3.30 | $5.70 |
| Biweekly newsletter (2/month) | $1.65 | $2.85 |

### Parallel Steps Spike (Steps 6a-6d)

Steps 6a through 6d run concurrently. While this doesn't increase total cost, it creates a burst of 4-12 LLM calls in a short window. This is the peak request rate during a pipeline run. OpenRouter per-key rate limits (see below) should accommodate this burst.

### Google Custom Search (Article Collection)

| Schedule | Frequency | Keywords | API Calls/Run | Weekly Total |
|---|---|---|---|---|
| Daily (date-sorted) | Every day | 3 | 3 | 21 |
| Every 2 days (relevance) | Every 2 days | 5 | 5 | ~18 |
| **Combined** | | | | **~39/week** |

**Pricing:** 100 free queries/day. We use ~8/day average, well within the free tier. Additional queries cost $5/1,000 only if billing is enabled in Google Cloud Console.

**Monthly cost under normal operation: $0.**

---

## OpenRouter: Billing Alerts and Limits

### Account-Level Spending Limit

1. Go to [openrouter.ai/settings/billing](https://openrouter.ai/settings/billing).
2. Under **Credit limit**, set a monthly budget. Recommended: **$25/month** (provides ~30x headroom over typical usage for experimentation and reruns).
3. When the limit is reached, API calls return HTTP 402 and the pipeline will raise `LLMError`.

### Per-Key Rate Limits

1. Go to [openrouter.ai/keys](https://openrouter.ai/keys).
2. Click on your API key.
3. Set **requests per minute** rate limit. Recommended: **30 requests/minute** (accommodates the parallel steps burst while capping runaway loops).
4. Set **credit limit per key** if running multiple projects on one account.

### Monitoring Usage

- **Dashboard:** [openrouter.ai/activity](https://openrouter.ai/activity) shows per-model token usage and cost over time.
- **API:** `GET https://openrouter.ai/api/v1/auth/key` returns remaining credits and current usage for the active key.

### Recommended Limits

| Setting | Value | Rationale |
|---|---|---|
| Monthly credit limit | $25 | ~30x typical weekly cost; allows reruns and testing |
| Per-key rate limit | 30 req/min | Handles parallel steps burst, blocks runaway loops |
| Alert threshold | Review at $5/month | Any bill over $5 warrants investigation |

---

## Google Cloud: Billing Alerts (Custom Search API)

The free tier (100 queries/day) is sufficient for normal operation. Alerts protect against bugs or configuration errors that might send excessive queries.

### Enable Billing Alerts

1. Go to [console.cloud.google.com/billing](https://console.cloud.google.com/billing).
2. Select the project linked to your CSE API key.
3. **Budgets & alerts** (left sidebar) → **Create budget**.
4. Set budget amount: **$5/month** (enough to catch anomalies while staying low).
5. Set alert thresholds at **50%**, **90%**, and **100%**.
6. Enable **email notifications** to billing admins.

### API Quota Restrictions

1. Go to [console.cloud.google.com/apis/api/customsearch.googleapis.com/quotas](https://console.cloud.google.com/apis/api/customsearch.googleapis.com/quotas).
2. The default quota is 100 queries/day (free). Do not increase this unless you specifically need more results.
3. If billing is enabled on the project, consider setting a **per-day query cap** at 100 to stay within the free tier.

### API Key Restrictions

1. Go to [console.cloud.google.com/apis/credentials](https://console.cloud.google.com/apis/credentials).
2. Click on your CSE API key → **Restrict key**.
3. Under **API restrictions**, select **Restrict key** and choose only **Custom Search API**.
4. This prevents a leaked key from accessing other Google APIs.

---

## When to Investigate

| Signal | Possible Cause |
|---|---|
| OpenRouter bill > $5/month | Excessive retries, validation loop not terminating, feedback loops compounding |
| Google CSE charges appearing | Billing enabled + query quota exceeded (should be $0 under normal use) |
| Rate limit errors (HTTP 429) | Parallel steps exceeding per-key limit, or external rate limit from provider |
| Credit exhausted (HTTP 402) | Monthly limit reached — raise the limit or investigate unusual usage |

## Cost Optimization Notes

- **Markdown validation** is the biggest cost multiplier: each attempt requires 1 generation + 2 validation calls. The `ValidationLoopCounter` caps retries at 3 to bound this.
- **Claude Sonnet 4.5** accounts for ~90% of LLM spend. Switching high-volume, lower-complexity calls (learning data extraction, freshness checks) to cheaper models reduces costs. Gemini Flash is already used for freshness checks.
- **Model overrides** via env vars (e.g., `LLM_SUMMARY_MODEL=google/gemini-2.5-flash`) allow per-purpose cost optimization without code changes.
