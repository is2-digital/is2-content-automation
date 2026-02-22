# SERP & Search API Integrations

This document provides a comparison of 3rd-party search services evaluated for data retrieval and AI grounding.

## Quick list:
- **SearchApi**: Multi-engine support Best for budget-conscious scaling. (https://www.searchapi.io/) (google)
- **SerpApi**: Best for high-reliability scraping. (https://serpapi.com/) (google)
- **Brave**: Independent index Best for AI/LLM grounding. (https://brave.com/search/api/) (custom index & most likely google related)
- **Custom Search JSON API**: Programmable Search Engine.

--
## Currently in use: **SearchApi**
--

## Suggested switch to: **SerpApi**
to Free plan (250 q/m)
or
Custom Search JSON API 5$/1000q

## Pricing
- **SearchApi**: $40 / month (1000 queries/m)
- **SerpApi**: $25 / month (1000 queries/m) !!! - exist free plan 250(1000 queries/m) - non commerce use.
- **Brave**: $5.00 per 1,000 requests  
- **Custom Search JSON API**: Programmable Search Engine.  ($5 per 1000 ad-free search element queries)

## Compatibility & Integration Notes
All listed services have been fully tested for compatibility and integrate seamlessly with the n8n HTTP Request node (GET).

- **Data Consistency**: The JSON response structures from SerpApi and SearchApi are ~90% identical.
- **Ease of Adaptation**: Switching between these two providers requires minimal edits to your workflow logic or data mapping.
- **Reliability**: Both services handle automated retries and proxy rotation, making them more stable than custom-built scrapers for n8n workflows.

## Example query SerpApi

```bash
curl --get https://serpapi.com/search.json \
 -d q="AI News" \
 -d hl="en" \
 -d gl="us" \
 -d google_domain="google.com" \
 -d api_key="920dde68c078fb739c5f4609acb920dde68c078fb73a023cb920dde68c078fb73fdc2029"
 ```