# CLAUDE.md — Inferago IOI (3.0)

Internal opportunity-intelligence tool for Inferago Tech Services (sole proprietorship, Tamil Nadu,
India). Monorepo: `backend/` (FastAPI + SQLAlchemy 2 + Alembic + SQLite), `frontend/` (React + Vite + TS).

## IOI 3.0 at a glance

The active product is `backend/app/ioi3/` (API `/api/v3`) + the rebuilt `frontend/` (Tailwind, 9 sections incl. Website Recovery).
Legacy modules/tables are kept as an archive; their discovery endpoints return 409 in Chennai scope.
Users run `./start.sh` / `./stop.sh` (Windows: `start.ps1` / `stop.ps1`).

**Two acquisition channels.** Every shared row carries `channel` = `b2b` | `social_commerce`
(`ioi_companies`, `ioi_campaigns`, `ioi_jobs`), and each channel has its own campaign, discovery jobs,
rules and qualification engine (B2B: P0-P3; social: S0-S3). They share identity, contacts, evidence,
outreach approval, the sales pipeline and payments. `ioi3/core.evaluate()` is the single choke point that
routes a company to its channel's engine — never add channel checks to callers.
See `docs/SOCIAL_COMMERCE.md`.

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
- **Social commerce (channel `social_commerce`).** Instagram, Facebook and WhatsApp profile pages are
  NEVER fetched: they need a sign-in and their robots.txt restricts automated access. The agent refuses
  those hosts *by name* (`agent._REFUSED_HOSTS`), so never add them to an allow-list. No DMs, chats,
  groups, group members or follower lists, ever. A published WhatsApp number is a contact route, not
  permission to send bulk messages.
- **Followers are never an input.** A follower count may be recorded when a public profile states it, but
  it must never reach scoring, qualification or maturity. There is deliberately no follower field on
  `social.qualify.Snapshot`.
- **Weak location evidence never counts.** A hashtag, caption language, a follower or a customer comment
  can never raise a seller's geographic confidence (`social.geo.BASES`). Only `verified_chennai` passes
  the location gate.
- **S0 needs a human.** A keyword that looks like a request for help stays a hypothesis until the owner
  confirms it. Order complexity is an indicator a tool *might* help — never a confirmed problem.
- **Never promise a Meta API integration.** No app, business account or approved permissions exist;
  `meta_api` is seeded `needs_setup` and every offer carries that caveat.
- **Website Recovery (`ioi3/website_recovery.py`).** One GET per site via `SafeHttp`; never scan ports or paths, log
  in or bypass a challenge. One observation is only `unhealthy_suspected`; `unhealthy_confirmed` needs the same failure
  again ≥ 24 h later. 403/429/bot challenges are `access_restricted`, never an outage. Generic words like "captcha"
  count only on near-empty pages (working contact forms contain them). Never store page HTML. A broken website is not
  buying intent. Activity (`ioi3/recovery_intel.py`) needs dated evidence; undated listings never count; owner records
  (`method=manual`) stay apart from automatic facts. Directory mobiles / free-mail contacts never pass the contact gate
  until the owner approves them. R1 needs every gate; R0 only from an owner-recorded confirmed need.
- **Cheapest option first.** Configure what a seller already pays for, or give them a free form, before
  offering to build. Never replace a working checkout or ask for a domain transfer for a workflow job.

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
| `ioi3/social/` | **Social commerce channel**: `platforms.py` (public profile links; refuses posts, groups, private sites), `geo.py` (Chennai confidence from evidence *basis*), `categories.py` (product categories, order complexity, activity vs demand, sales setup), `qualify.py` (gates, S0-S3, 100-point score, maturity), `solutions.py` (4 offers, cheapest-first), `core.py` (campaign, sources, evidence, evaluate), `collect.py` (profile/CSV/market-page ingestion), `search.py` (authorised search API, honest when absent), `research.py` (readable pages + `record_observation`, the human route for Instagram), `agent.py` (bounded agent, own-domain only), `outreach.py` (draft for a one-person seller), `engine.py` (`SocialRunner`), `api.py` (`/api/v3/social`) |
| `ioi3/` | **IOI 3.0**: `models.py` (ioi_* tables), `core.py` (campaign, sources, evidence, identity, evaluate), `collect.py` (Overture/CSV/manual → ingest), `research.py` (website + news), `qualify.py` (gates, P0–P3, score, friction, solution), `engine.py` (persistent jobs, worker thread, lock-safe progress), `fetch.py` (page cache, error classes, SQLite lock retry), `agent.py` (bounded tool-calling research agent, audited in ioi_agent_events), `solutions.py` (existing-software fit), `sales.py` (outreach, pipeline, payments), `api.py` |
| `reset.py` | backup / preview / guarded execute of the old-data reset (CLI only; rows only, never tables) |
| `documents.py`, `imports.py` | PDF/DOCX tender analysis, manual URL/doc import |
| `http_client.py` | SSRF-safe fetcher (timeouts, size limits, robots, rate limit) |
| `jobs.py` | bounded thread pool + opt-in APScheduler |
| `api/` | REST routers; `deps.py` holds auth + pagination |

Keep `docs/BUILD_STATUS.md` current when features change.
