# Architecture

## Overview

```
                ┌──────────────── React + Vite + TS (13 screens) ────────────────┐
                │ Overview · Discover · Opportunities · Organisations · Vendor     │
                │ Eligibility · Chains · Evidence · Research · Outreach · Follow-ups│
                │ Sources · Settings                                               │
                └───────────────────────────────┬──────────────────────────────────┘
                                                │ /api (Vite proxy in dev)
┌───────────────────────────────────────────────▼──────────────────────────────────────┐
│ FastAPI  (auth boundary: bearer token or loopback-only)                               │
│  api/core · api/sources · api/opportunities · api/outreach                            │
├──────────────────────────────────────────────────────────────────────────────────────┤
│ jobs.py  bounded ThreadPool (2) + opt-in APScheduler                                  │
│ pipeline.py  run_source → connector.collect → ingest_item                             │
│   ├ classification.py   rules → category, pipeline, services, signals, geography     │
│   ├ dedupe              source id → canonical URL → content hash                      │
│   ├ resolve_organisation (exact normalised name, never across conflicting domains)    │
│   ├ Evidence, BuyingSignal, Contact (published routes), EligibilityRequirement        │
│   ├ relationships.py    hypotheses with evidence URL + excerpt                        │
│   └ evaluation.py       eligibility.py (2 scopes) → scoring.py (3 scores) → priority  │
│ research.py   shortlist → budgeted site visits → contacts/relationships → brief       │
│ outreach.py   draft → submit → human approve/reject → (human sends) → follow-ups      │
│ documents.py / imports.py   PDF/DOCX tender analysis with page refs                   │
│ ai/openrouter.py  optional, validated, with deterministic fallback                    │
│ http_client.SafeHttp  SSRF guard · timeouts · size cap · robots.txt · rate limit      │
├──────────────────────────────────────────────────────────────────────────────────────┤
│ SQLAlchemy 2 + Alembic → SQLite (WAL, FKs on)                                         │
└──────────────────────────────────────────────────────────────────────────────────────┘
```

## Data model (22 tables)

| Table | Purpose |
|---|---|
| `organisations` | Buyers/vendors/partners. `domain_verified` only after research confirms the name on the site. Partial unique index on verified domain. |
| `opportunities` | One per real opportunity. `dedupe_key` unique; `published_at` ≠ `retrieved_at`; `country` NULL unless explicitly stated (`geography_basis` records why); `priority`, `eligibility_outcome`, `merged_into_id`, `is_demo`. |
| `sources` | Registry: base URL, region, category, access method, auth, terms, frequency, rate limit, health, enabled/scheduled, coverage, connector status, config, incremental cursor. |
| `source_runs` | Per-run stats, request count, error, log lines. |
| `discovery_jobs` | Manual/scheduled runs across sources = search history. |
| `raw_records` | Raw collected text + payload, unique `(source_id, external_id)`. Never deleted on merge. |
| `evidence` | Excerpts linked to opportunity/organisation with URL, page reference, document name. |
| `contacts` | Public routes only; `source_url` NOT NULL; verified flag, method, date. |
| `buying_signals` | Typed signals with strength and excerpt. |
| `eligibility_requirements` | Extracted/manual/doc requirements with scope, mandatory flag, parameters, page ref, evidence id. |
| `eligibility_assessments` | History of assessments per scope (project / vendor registration). |
| `opportunity_scores` | One row per (opportunity, score type) with components JSON. |
| `organisation_relationships` | Graph edges: source org → target org / opportunity / label; evidence URL + excerpt NOT NULL; confidence; hypothesis/confirmed/rejected. |
| `opportunity_relationships` | Edges between opportunities (same buyer, repeat, related, cross-sell). |
| `research_tasks` | Budget, usage, input hash (skip unchanged), findings, brief. |
| `outreach_drafts`, `outreach_approvals` | Workspace content and immutable approval decisions. |
| `call_tasks`, `follow_up_tasks` | Human call tracking and generated follow-ups. |
| `action_items` | Owner to-do checklist shown on the dashboard ("This week"). |
| `activity_logs`, `ai_usage_logs`, `app_settings` | Audit trail, AI token/cost tracking, settings. |

## Key decisions

- **SQLite + plain SQL graph** (spec V1). Graph queries are simple joins; swap to Postgres by
  changing `IOI_DATABASE_URL` (migrations use batch mode for SQLite compatibility).
- **Rules first.** Classification, eligibility and scoring are deterministic and unit-tested.
  AI only drafts text (briefs, summaries, outreach) and is validated.
- **Idempotent ingestion.** Unique constraints + savepoint per item: one bad item never aborts a
  run; re-running a source never duplicates rows.
- **Conservative org matching.** Exact normalised name (legal suffixes stripped) or same domain.
  "Acme Systems" ≠ "Acme Solutions". Platform domains (github.com, lever.co…) never identify an org.
- **Priority ≠ score.** Priority = the pipeline's primary *effective* score + an explicit
  geography bonus (Tamil Nadu +15, India +8; configurable). Disqualified → 0.
- **No uncontrolled loops.** Background work uses a 2-worker pool; the scheduler is opt-in and
  uses `max_instances=1` plus DB-level duplicate-run protection.
