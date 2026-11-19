---
name: add-connector
description: Add a new IOI source connector (API or RSS-like feed) honestly and safely — use when asked to integrate a new opportunity source.
---

# Adding a source connector to Inferago IOI

1. **Check permission first.** Read the source's terms / robots.txt / API policy. If access needs
   credentials, it is `credential_gated`. If it needs CAPTCHA or login scraping, do NOT build it —
   leave it `planned` and recommend manual document/URL import.
2. Create `backend/app/connectors/<name>.py` with a class exposing `key` and
   `collect(self, ctx: CollectContext) -> Iterator[CollectedItem]`.
   - Use only `ctx.http.get(...)` (SafeHttp: SSRF guard, timeouts, size cap, robots, rate limit).
     Pass `check_robots=False` only for documented programmatic APIs.
   - Respect `ctx.max_items`; keep incremental state in `ctx.cursor` (only persisted on success).
   - Yield buyers/requests only — skip self-promotion (people offering services).
   - Set `published_at` from the source; never guess geography or organisations.
   - Only add `contact_routes` that the poster actually published, with the post URL as source.
   - Raise `ConnectorUnavailable(setup_instructions)` when credentials are missing.
3. Register it in `pipeline.CONNECTORS` and add a `SEED_SOURCES` entry in `source_registry.py`
   with an honest `connector_status`, terms notes, rate limit and coverage.
4. Tests in `backend/tests/` using the `web` fixture (httpx.MockTransport) — never the live
   internet: happy path, skipped items, incremental cursor, HTTP failure → run `failed`.
5. Update `docs/SOURCES.md` and `docs/BUILD_STATUS.md`. Run `scripts/test.sh`.
