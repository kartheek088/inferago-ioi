# Inferago Opportunity Intelligence (IOI)

Internal, locally-run tool for **Inferago Tech Services** that discovers, collects, deduplicates,
classifies, checks eligibility for, scores, researches and prepares outreach for software
development opportunities — with a human approving every outbound action.

```
Discover → Collect → Deduplicate → Classify → Filter → Research selectively → Verify
→ Evaluate eligibility → Score → Discover connected opportunities → Find contact routes
→ Prepare outreach → Human approval → Follow-up
```

It also finds **prospects**: local businesses, independent professionals and bigger firms that have
no website, a weak website, or could use CRM, AI or ERP/SAP, even though they have not asked.
Go to **Prospects**, then **Find prospects**, then **Business directory (best)**. Download India's listings once (about 10 minutes),
then click **Find prospects**. There is also a **Map** view.

Not SaaS. V1 never sends email, places calls, submits bids, registers as a vendor or signs anything.

## Stack

| Layer | Tech |
|---|---|
| Backend | Python 3.11+, FastAPI, SQLAlchemy 2.x, Alembic, SQLite, Pydantic v2, httpx, APScheduler 3 |
| Documents | pypdf, python-docx |
| Frontend | React 18 + Vite 5 + TypeScript (no UI framework) |
| AI (optional) | OpenRouter adapter — app runs fully without it |

## Quick start

Prerequisites: [uv](https://docs.astral.sh/uv/), Node 18+ and npm.

```bash
cd inferago-ioi
scripts/setup.sh        # creates .env from .env.example, installs deps, runs migrations
scripts/dev.sh          # backend on http://127.0.0.1:8000, UI on http://127.0.0.1:5173
```

Open http://127.0.0.1:5173 → **Discover** → tick *Hacker News* → **Run discovery**.

Manual equivalents:

```bash
# backend
cd backend
uv sync
uv run alembic upgrade head
uv run python -m app.main            # also applies migrations; binds 127.0.0.1:8000

# frontend (second terminal)
cd frontend
npm install
npm run dev                          # proxies /api → 127.0.0.1:8000
```

API docs (OpenAPI): http://127.0.0.1:8000/docs

Single port (no Vite): `cd frontend && npm run build`, then run the backend and open http://127.0.0.1:8000.
Researched partner programmes: `cd backend && uv run python ../scripts/seed_partner_programmes.py`.

## Tests

```bash
scripts/test.sh                      # everything below
cd backend && uv run pytest -q       # 179 backend tests, no live network
cd frontend && npm run typecheck && npm run build
```

## Integration status (honest)

| Source | Status |
|---|---|
| Hacker News — Seeking-Freelancer thread, contract roles in Who-is-hiring, keyword search | **Live** (public APIs, no key) |
| n8n community "Jobs" + Make community "Hire a Pro" (public RSS) | **Live** (enabled by default) |
| Generic RSS/Atom feed | **Live** once you set a permitted `feed_url` |
| OpenStreetMap prospects (Overpass mirror: private.coffee / kumi.systems / mail.ru) | **Live**: public open data (ODbL), robots.txt respected |
| Manual URL import | **Manual** (owner-submitted, SSRF-protected, robots.txt respected) |
| Tender / procurement document import (PDF, DOCX) | **Manual** |
| Official company websites (selective research) | **Manual**, used by research workflow |
| Reddit | **Credential-gated** — disabled until `IOI_REDDIT_*` set |
| TN e-Procurement, CPPP, GeM, GePNIC, PSU, international portals | **Planned** — no connector; download docs manually and import |
| Discord, Indie Hackers, Product Hunt, directories | **Planned** |
| LinkedIn, freelance marketplaces | **Not automated by design** (platform restrictions are not bypassed) |

Full details: [docs/SOURCES.md](docs/SOURCES.md). Current status and known limitations:
[docs/BUILD_STATUS.md](docs/BUILD_STATUS.md).

## Documentation

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — modules, data model, pipeline
- [docs/SETUP.md](docs/SETUP.md) — install, configure, run
- [docs/SOURCES.md](docs/SOURCES.md) — source registry, connectors, adding feeds
- [docs/ELIGIBILITY.md](docs/ELIGIBILITY.md) — deterministic eligibility engine
- [docs/SCORING.md](docs/SCORING.md) — the three scoring algorithms
- [docs/SECURITY.md](docs/SECURITY.md) — access control, SSRF, compliance
- [docs/OPERATIONS.md](docs/OPERATIONS.md) — day-to-day use, scheduler, backups
- [docs/DEPLOY.md](docs/DEPLOY.md) — local vs hosting (Tailscale, VPS + Caddy)
- [docs/ROADMAP.md](docs/ROADMAP.md)
- [docs/BUILD_STATUS.md](docs/BUILD_STATUS.md)
