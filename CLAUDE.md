# CLAUDE.md — Inferago IOI (3.0)

Internal opportunity-intelligence tool for Inferago Tech Services (sole proprietorship, Tamil Nadu,
India). Monorepo: `backend/` (FastAPI + SQLAlchemy 2 + Alembic + SQLite), `frontend/` (React + Vite + TS).

## IOI 3.0 at a glance

The active product is `backend/app/ioi3/` (API `/api/v3`) + the rebuilt `frontend/` (Tailwind, 6 sections).
Legacy modules/tables are kept as an archive; their discovery endpoints return 409 in Chennai scope.
Users run `./start.sh` / `./stop.sh` (Windows: `start.ps1` / `stop.ps1`).

## Commands

```bash
scripts/setup.sh                                  # install + migrate
scripts/dev.sh                                    # run backend :8000 + frontend :5173
scripts/test.sh                                   # all checks incl. Vitest + Playwright E2E (must pass before claiming done)
cd backend && uv run pytest -q                    # backend tests (no live network)
cd backend && uv run alembic revision --autogenerate -m "msg"   # after model changes
cd backend && uv run alembic check                # model/migration drift
cd frontend && npm run typecheck && npm run build
```

## Non-negotiable rules

- **Business profile is real** (`backend/app/profile.py`). Never add services, turnover, staff,
  certifications, projects or references. Services change only with owner approval.
- **Unknown ≠ satisfied.** Eligibility never treats a missing fact as met. Mandatory failures
  override all scores (`effective_total = 0`).
- **Geography is explicit only.** Never infer a country from a platform's domain.
- **No fabricated contacts.** Every `Contact` has `source_url`; never generate guessed emails.
- **Relationships need evidence** (URL + excerpt). Rule-extracted ones are hypotheses until a
  human confirms. Hypotheses never add score.
- **Human approval for all outbound.** Nothing is sent, called, bid or registered automatically.
- **AI is optional** (`IOI_OPENROUTER_*`; `IOI_ANTHROPIC_*` optional alternative). Every AI path has a
  deterministic fallback and Pydantic-validated output. AI facts/clauses are kept only with a verbatim
  quote found in the source. The AI review agent gives an eligibility *opinion*; the rule engine
  stays authoritative for mandatory gates and disagreements are flagged for the owner.
- **Compliance:** robots.txt, rate limits, no CAPTCHA/paywall bypass, no private channels,
  no LinkedIn/marketplace scraping. All outbound HTTP goes through `app/http_client.SafeHttp`.
- **Do not mark sources live unless a working, tested connector exists.**
- **Chennai-only scope (owner, 2026-11-23).** `IOI_DISCOVERY_SCOPE=chennai` is the default: nationwide
  discovery endpoints return 409 and are never scheduled. Category A needs a human-confirmed, dated
  (≤ 90 days) explicit need or operational problem; expansion/hiring is never software demand.
  A Chennai address is verified only from an official site or by the owner, never from a directory or 044 code.
- **Facts vs assumptions (3.0).** Every `ioi_facts` row has a state: source_verified / inferred / buyer_confirmed / unknown.
  Never store a guess as source_verified. Only recorded payments count as collected revenue.
- **SQLite + threads (3.1).** Never hold a transaction open across network or AI calls; write job progress with
  `fetch.short_write`, retry commits with `fetch.with_retry` (WAL snapshot conflicts fail instantly with "database is locked").
- **Agent rules.** Read-only typed tools, company's own domain only, every fact/person needs a verbatim quote from a page fetched
  in that session, hard limits, every step logged. Never add tools that send, submit or write outside IOI.
- Tests must not hit the live internet — use the `web` fixture (httpx.MockTransport).

## Layout (backend/app)

| Module | Responsibility |
|---|---|
| `models.py`, `enums.py`, `db.py` | ORM schema, vocabularies, engine/session |
| `connectors/` | Source connectors (hackernews, rss, reddit, gem) — yield `CollectedItem` |
| `ai/` | `claude.py` (Anthropic SDK provider), `openrouter.py`, `extraction.py` (locate-and-verify), `agent.py` (review agent: OpenRouter function-calling loop, or Claude tool runner, over fetch/record/add-requirement tools) |
| `pipeline.py` | ingest → dedupe → org resolution → evidence → requirements → evaluate; source runs |
| `classification.py` | deterministic category/service/signal/geography rules |
| `eligibility.py` | requirement extraction + deterministic evaluation against profile |
| `scoring.py` | three explainable 100-point scores + priority |
| `evaluation.py` | re-runs eligibility + scoring for an opportunity |
| `research.py`, `contacts.py`, `relationships.py` | selective research, contact routes, chain graph |
| `outreach.py` | drafts, approvals, call tasks, follow-ups |
| `prospects.py` | prospect finder: OSM/Overpass search, segments, gap scoring, website audit, pitch drafts (`api/prospects.py`) |
| `chennai.py`, `lead_rules.py`, `leads.py` | Chennai-only lead pipeline (default scope): city-limit geography, two-industry classification, signals, A–D category + sales difficulty, website verification, news signals (`api/leads.py`) |
| `ioi3/` | **IOI 3.0**: `models.py` (ioi_* tables), `core.py` (campaign, sources, evidence, identity, evaluate), `collect.py` (Overture/CSV/manual → ingest), `research.py` (website + news), `qualify.py` (gates, P0–P3, score, friction, solution), `engine.py` (persistent jobs, worker thread, lock-safe progress), `fetch.py` (page cache, error classes, SQLite lock retry), `agent.py` (bounded tool-calling research agent, audited in ioi_agent_events), `solutions.py` (existing-software fit), `sales.py` (outreach, pipeline, payments), `api.py` |
| `reset.py` | backup / preview / guarded execute of the old-data reset (CLI only; rows only, never tables) |
| `documents.py`, `imports.py` | PDF/DOCX tender analysis, manual URL/doc import |
| `http_client.py` | SSRF-safe fetcher (timeouts, size limits, robots, rate limit) |
| `jobs.py` | bounded thread pool + opt-in APScheduler |
| `api/` | REST routers; `deps.py` holds auth + pagination |

Keep `docs/BUILD_STATUS.md` current when features change.
