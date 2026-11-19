# Build status

_Last updated: 2026-11-20_

## Verification (all run locally)

| Check | Result |
|---|---|
| Backend tests `uv run pytest` | **110 passed** (unit, API integration, mocked connectors, dedupe, eligibility hard gates, score arithmetic, source failures, missing evidence, relationship provenance, outreach approval, migrations, SSRF/auth, documents, AI fallback, end-to-end) |
| Alembic `upgrade head` + `alembic check` | Pass — no drift between models and migration |
| Migration upgrade → downgrade → upgrade | Pass (test) |
| Frontend `tsc` type check | Pass |
| Frontend production build | Pass (≈251 kB JS, 75 kB gzip) |
| Backend starts (`python -m app.main`) | Pass — applies migrations, seeds 23 sources |
| Frontend dev server + `/api` proxy | Pass |
| Live Hacker News run (real network) | Pass — Nov 2026 threads: 15 fetched, 11 opportunities, 4 rejected; re-run: 0 new / all duplicates |
| UI rendering with real data | Checked via headless Chrome screenshots (Overview, Opportunities, Detail, Sources) |

`scripts/test.sh` runs the full suite.

## Implemented

- Monorepo, config via env, SQLite + SQLAlchemy 2 + Alembic (21 tables, indexes, FKs, unique and check constraints).
- Source registry with honest statuses (23 sources: 4 live, 3 manual, 1 credential-gated, 15 planned); enable/schedule/config from UI; per-source health, failure counts, run logs.
- Live Hacker News connector (freelancer thread buyers, contract roles, incremental keyword search).
- Generic RSS/Atom connector (term and title filters); owner can add feeds at runtime. Live n8n Jobs and Make Hire-a-Pro feeds.
- Manual URL import and procurement document import (PDF/DOCX) with page-referenced field extraction and scanned-PDF manual-review flag.
- Ingestion pipeline: raw evidence preservation, per-item savepoints, idempotent re-runs, cross-source dedupe (source id → canonical URL → content hash) with provenance, conservative organisation resolution, duplicate-run protection, stale-run recovery.
- Deterministic classification (10 categories, 3 pipelines, 5 approved services, buying signals, explicit-only geography, budget, remote).
- Deterministic eligibility engine (22 requirement types, 6 outcomes, separate vendor-registration scope, clarifications, next action, disclaimer).
- Three explainable scores with known/unknown components; mandatory disqualification override; priority with explicit-geography bonus.
- Selective research with budgets (shortlist, deep-research count, requests/task, AI calls, tokens, time), re-research skipping, official-site contact discovery (published only, verified with source and date), domain verification, vendor-page detection.
- Opportunity-chain graph in SQL tables (org→org/opportunity/label, opportunity→opportunity) with evidence, confidence, hypothesis/confirmed/rejected, same-buyer linking; only confirmed edges score.
- Outreach workspace (all 11 required fields), edit/submit/approve/reject with recorded approver, approval invalidated on edit, mark-sent-manually, call tasks gated on approval, all 9 call outcomes with generated follow-ups.
- Optional OpenRouter adapter (timeouts, retries, usage/token/cost logging, Pydantic validation, deterministic fallback, prompt-injection guard). App runs without a key.
- Opt-in APScheduler, bounded job pool, graceful shutdown.
- REST API for all 18 required areas with Pydantic schemas, pagination, filtering, validation; OpenAPI at `/docs`.
- Security: loopback-only default, bearer token, refuse public bind without token, SSRF guard (incl. redirects), timeouts, size caps, robots.txt, rate limits.
- React + Vite + TS dashboard: all 13 screens on real backend data; search/filters, country/pipeline filters, score sorting, evidence inspection, eligibility badges, research status, source health, run controls, relationship exploration, approval controls, responsive layout, DEMO labelling.
- Owner "This week" action checklist on the dashboard (seeded once, editable).
- 30 researched vendor/partner programmes importable into Vendor Intelligence with requirement-level eligibility.
- Backend serves the built UI (single port); proxied requests require the API token. Hosting guide in DEPLOY.md.
- Optional AI verified live via OpenRouter (`openrouter/auto`).
- Docs (README + 11 docs), CLAUDE.md, two project skills, setup/dev/test/demo scripts.

## Partially implemented

- **Reddit connector** — OAuth app-only flow and listing parser implemented; disabled without credentials. Not tested against live Reddit (no credentials available); unit-tested only for the disabled path.
- **AI features** — adapter and fallbacks are unit-tested with a mocked OpenRouter and verified once live (openrouter/auto, one summary call). AI is used for research briefs, document summaries and outreach drafts; AI classification refinement and AI requirement extraction are not wired in (rules only).
- **Relationship discovery** — regex-based extraction from posts/pages produces hypotheses; precision is modest; human confirmation is the intended workflow.
- **Organisation enrichment** — website only when present in the post; Hacker News posts often link to job boards (filtered as platforms), so many organisations have no website and research falls back to "public thread is the only contact route".
- **Document field extraction** — regex-based; works on conventionally labelled Indian tender documents; unusual layouts will leave fields empty (never fabricated).

## Blocked / not implemented (by design or environment)

- Government portals (TN e-Procurement, CPPP, GeM, GePNIC, PSU): CAPTCHA/login-protected (CPPP and TN listings verified CAPTCHA-gated, Nov 2026) — no automated connector; manual document import instead.
- Discord, Indie Hackers, Product Hunt, n8n/Make (beyond generic RSS), directories, chambers of commerce: planned only.
- LinkedIn and freelance marketplaces: intentionally not automated.
- Automatic sending/calling/bidding/registration: intentionally not implemented.

## Known limitations

- Cross-posted forum posts (same post on n8n and Make) are not merged unless text is identical.

- Hacker News buyer volume is low (recent Seeking-Freelancer threads had no buyer posts); most HN leads are contract roles at startups, many outside India.
- DNS-rebinding window between validation and connection in SafeHttp (local single-user tool; see SECURITY.md).
- Single shared API token; no per-user accounts.
- SQLite: fine for one user; concurrent heavy writes would need Postgres.
- Search uses SQL `LIKE`, not full-text search.
- Frontend has no automated UI tests (type check + build + manual screenshot verification only).

## Continuation checkpoint

Nothing outstanding from the build plan. Suggested next steps are in `ROADMAP.md`.
Commands: `scripts/setup.sh`, `scripts/dev.sh`, `scripts/test.sh`.
