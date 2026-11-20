# CLAUDE.md — Inferago IOI

Internal opportunity-intelligence tool for Inferago Tech Services (sole proprietorship, Tamil Nadu,
India). Monorepo: `backend/` (FastAPI + SQLAlchemy 2 + Alembic + SQLite), `frontend/` (React + Vite + TS).

## Commands

```bash
scripts/setup.sh                                  # install + migrate
scripts/dev.sh                                    # run backend :8000 + frontend :5173
scripts/test.sh                                   # all checks (must pass before claiming done)
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
- **AI is optional** (`IOI_OPENROUTER_*`). Every AI path has a deterministic fallback, output is
  Pydantic-validated, and AI never decides mandatory legal eligibility.
- **Compliance:** robots.txt, rate limits, no CAPTCHA/paywall bypass, no private channels,
  no LinkedIn/marketplace scraping. All outbound HTTP goes through `app/http_client.SafeHttp`.
- **Do not mark sources live unless a working, tested connector exists.**
- Tests must not hit the live internet — use the `web` fixture (httpx.MockTransport).

## Layout (backend/app)

| Module | Responsibility |
|---|---|
| `models.py`, `enums.py`, `db.py` | ORM schema, vocabularies, engine/session |
| `connectors/` | Source connectors (hackernews, rss, reddit, gem) — yield `CollectedItem` |
| `ai/` | OpenRouter adapter; `extraction.py` = AI locate-and-verify helpers (quotes must match source) |
| `pipeline.py` | ingest → dedupe → org resolution → evidence → requirements → evaluate; source runs |
| `classification.py` | deterministic category/service/signal/geography rules |
| `eligibility.py` | requirement extraction + deterministic evaluation against profile |
| `scoring.py` | three explainable 100-point scores + priority |
| `evaluation.py` | re-runs eligibility + scoring for an opportunity |
| `research.py`, `contacts.py`, `relationships.py` | selective research, contact routes, chain graph |
| `outreach.py` | drafts, approvals, call tasks, follow-ups |
| `documents.py`, `imports.py` | PDF/DOCX tender analysis, manual URL/doc import |
| `http_client.py` | SSRF-safe fetcher (timeouts, size limits, robots, rate limit) |
| `jobs.py` | bounded thread pool + opt-in APScheduler |
| `api/` | REST routers; `deps.py` holds auth + pagination |

Keep `docs/BUILD_STATUS.md` current when features change.
