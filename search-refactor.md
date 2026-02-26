# Replace SearchApi with Google Custom Search JSON API

SearchApi no longer has a free tier. Google Custom Search JSON API provides 100 free queries/day (we use ~8).

## Architecture

The swap is clean. `article_collection.py` depends on `SearchResult` dataclass and `SearchApiClient` — both defined in `ica/services/search_api.py`. The pipeline logic (dedup, date parsing, DB upsert) is untouched.

**Google CSE requires 2 credentials:** API key + Custom Search Engine ID (cx)

## Tasks

### 1. Update settings (ica/config/settings.py)
- Remove `SEARCHAPI_API_KEY`
- Add `GOOGLE_CSE_API_KEY` and `GOOGLE_CSE_CX`

### 2. Rewrite search service (ica/services/search_api.py)
- Rename file to `ica/services/google_search.py`
- Rename class `SearchApiClient` → `GoogleSearchClient`
- Change `base_url` to `https://www.googleapis.com/customsearch/v1`
- Update `search()` params: `key`, `cx`, `q`, `num`, `dateRestrict` (replaces `time_period`), `gl` (replaces `location`)
- Update `_parse_results()`: Google returns `items[]` with `link`, `title`, `snippet`; date comes from `pagemap.metatags[0].article:published_time` or similar
- Keep `SearchResult` dataclass unchanged (url, title, date, origin)
- Map engine concept: daily schedule uses `&sort=date` for news recency; every-2-days uses default relevance

### 3. Update imports in consumers
- `ica/pipeline/article_collection.py` — update import path and class name
- `ica/scheduler.py` — update client instantiation
- `ica/__main__.py` — update client instantiation
- `ica/pipeline/steps.py` — check for any search client wiring

### 4. Update tests
- `tests/test_services/test_search_api.py` — rewrite mocks for Google CSE response shape
- `tests/test_pipeline/test_article_collection_e2e.py` — update mock client references
- `tests/test_scheduler.py` — update any SearchApiClient mocks
- `tests/test_config/test_settings.py` — update REQUIRED_ENV dict

### 5. Update docs & config
- `docs/credentials.md` — replace SearchApi setup with Google CSE setup instructions
- `docs/services.md` — update search service description
- `.env.example` — replace `SEARCHAPI_API_KEY` with `GOOGLE_CSE_API_KEY` and `GOOGLE_CSE_CX`
- `CLAUDE.md` — update any SearchApi references

### 6. Integration test
- Add `scripts/test_google_search.py` — live test that runs a single query and prints results
- Verify date parsing still works with Google's date format

## Notes

- Google CSE `num` max is 10 per request (vs SearchApi's 15). Daily schedule currently requests 15 — needs adjustment or pagination.
- `dateRestrict=w1` replaces `time_period=last_week`
- No `engine` parameter needed — Google CSE is one engine. The `origin` field on SearchResult can be set to `"google_cse"` for both schedules.
- Google doesn't have a `google_news` engine equivalent built in, but the CSE can be configured to search news sites via the CX settings in the Google console.
