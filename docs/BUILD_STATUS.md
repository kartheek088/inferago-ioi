# Build status

_Last updated: 2026-11-21_

## Verification (all run locally)

| Check | Result |
|---|---|
| Backend tests `uv run pytest` | **172 passed** (unit, GeM connector (mocked), AI quote verification, API integration, mocked connectors, dedupe, eligibility hard gates, score arithmetic, source failures, missing evidence, relationship provenance, outreach approval, migrations, SSRF/auth, documents, AI fallback, end-to-end) |
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

- **Prospects (2026-11-21).** Finds businesses and independent professionals with potential but weak or no
  online presence, using OpenStreetMap via a public Overpass mirror (overpass-api.de is skipped because its
  robots.txt disallows /api/). Three segments: small businesses, independent professionals, and bigger
  companies (factories and Pvt Ltd firms, the ERP/SAP/CRM potential). Chains (brand-tagged), government offices and
  unnamed places are skipped; a Facebook/Instagram link is never counted as a website. A deterministic
  0–100 score has a reason for every point. An optional homepage check (robots.txt respected) finds gaps:
  no HTTPS, not mobile-friendly, no title or meta description, no analytics, no chat or WhatsApp, no enquiry form,
  basic builder, or an outdated copyright year. Each prospect gets a draft pitch with call, WhatsApp, email and map links;
  nothing is sent automatically. There is a contact log with outcomes, auto follow-up dates and CSV export.
  Areas: 17 Tamil Nadu cities, 12 other Indian cities and 22 international cities, plus custom `Name@lat,lon`.
- **Prospects from an offline map file (2026-11-21).** The owner downloads a Geofabrik `.osm.pbf` once in a browser
  (Geofabrik's robots.txt blocks bots from .pbf files, so IOI never downloads it itself). IOI scans it locally with pyosmium:
  all of Tamil Nadu, around chosen cities, or the whole file. It keeps the best N and assigns each prospect to the nearest
  listed city within 40 km. Files are read only from `backend/data/maps/` or `~/Downloads/`, never from an arbitrary path.
  First real run (2026-11-22, all-India file, 1.7 GB): 77 seconds. 18,646 prospects kept (11,100 "definite"); skipped
  11,158 with a website and 1,545 without a usable phone. The area list now has 101 cities (63 outside Tamil Nadu in India).
  Places more than 40 km from a listed city use the listing's own town tag; 2,114 had none and are labelled "Other".
- **No-website + phone rules (2026-11-22).** New searches (live or map file) keep only businesses without a website
  that list a usable phone number (settings `prospect_only_no_website`, `prospect_require_phone`). Existing prospects
  are kept. Phones get a format check: Indian mobile, landline or toll-free, normalised to +91, or "looks wrong".
  "Number works" is set only by a human: the confirm button, or a call/WhatsApp logged as interested, not interested or won.
  WhatsApp links are offered only for mobile numbers. Map files over 300 MB use a temporary disk index instead of RAM;
  a file still being written (modified in the last 2 minutes) cannot be scanned.
- **Call list, qualification, quality, states, upgrades, colleges, multi-branch (2026-11-22).**
  - *Call list* (`/call`): one prospect at a time from `/api/prospects/next`. Due follow-ups come first, then the best new one
    for the chosen group (no website / website upgrade / colleges), state and quality. There are tel: and wa.me buttons and a call script.
    Outcomes are one keypress: no answer (retry tomorrow), call back (preset or chosen time), not interested, interested
    (opens qualification: needs, budget, decision maker, timeline, current setup → "qualified" when all fit), wrong number,
    and skip. A daily counter tracks the target of 30. Nothing is dialled or sent automatically.
  - *Quality* (`quality_level` established / good / small) comes only from listing facts: business type value, address, email,
    social page, hours, website, confirmed phone and Overture confidence; small-ticket types (kiosks, grocery, mobile shops…) score lower.
    Lists and the call list show "good and established" by default.
  - *States*: from the listing's ISO region (Overture), `addr:state`, or a listed city within 40 km; otherwise unknown.
  - *Website upgrade*: Overture scan mode `upgrade` keeps businesses that have a real website (need level `check_site`).
    "Check websites" audits homepages in the background (robots.txt respected) and marks broken or weak ones (3+ gaps) `upgrade`.
  - *Colleges* are listed again as their own segment, kept even with a website; government colleges stay out (tenders).
  - *Multi-branch businesses* (`/multi-branch`, `app/chains.py`): Overture listings grouped by normalised name; 3–40 separate
    locations (about 1 km apart), at most 2 states, no brand field. Evidence is either branches sharing a phone or social page,
    or the same name and category in one state. Banks, government, IT and national chains are excluded.
  - *Big projects* reworked: private projects where our services fit (healthcare, hospitality, retail, real estate, education,
    wellness, manufacturing). Tenders, government, PSU and infrastructure news and IT companies are dropped. Projects have a state,
    a "how we fit" line, connected companies read from the article (builder, architect, partner, supplier, each with its quote,
    unconfirmed until the owner confirms), a contact log with follow-ups, and CSV export. City and sector feeds were added.
- **Overture Maps business directory (2026-11-22).** Overture "places" is open data (CDLA-Permissive-2.0) from Meta, Microsoft,
  Foursquare and others. It is far richer than OSM for India; one 5×5 km area of Coimbatore has 14,442 places, 6,025 of them with a
  phone and no website, nearly all with a Facebook page. DuckDB copies India's places that have a phone from the public S3 release
  into `data/maps/overture-india-<release>.parquet` once; scans then run locally. The same rules apply (no website — a Facebook link in
  "websites" is not a website; a valid +91 phone, which also keeps out neighbouring countries; chains, colleges, IT and government
  skipped; dealers kept), plus Overture confidence ≥ 0.3, not closed, and country = IN (the download box also covers neighbouring
  countries). Businesses with social pages come first. `source_url` links to the Overture explorer at the place's location.
  First real run (2026-11-22, release 2026-11-18.0): download 9 min (4.1M listings with a phone, 345 MB). Scan about 5 min: 1,459,604 Indian
  listings with a phone, 1,227,636 meet the criteria, the best 200,000 kept. Extra name checks (government, colleges, IT, banks) skipped
  3,492 that Overture categories missed. Existing prospects are re-checked at startup only when `RULES_VERSION` changes.
- **Map view (2026-11-22).** Prospects → Map uses Leaflet with free OpenStreetMap tiles. It shows the best 3,000 in the visible area
  with the current filters, coloured by need level; click a dot to open the prospect. `?view=map` opens it directly.
  Points are spread over a 60×60 grid of the visible area (best few per cell), so a zoomed-out map covers the whole country.
- **Who does NOT need us (2026-11-22).** Prospects are skipped if they are chains or partner-run (brand/franchise tags,
  OYO/Treebo and other hotel networks, food, pharmacy and retail chains, bank branches, vehicle dealers), colleges or
  universities, IT/software companies, or government bodies. Older records are auto-marked "Auto-skipped: reason".
- **Need level.** Each prospect is rated "definite", "likely" or "maybe", with reasons. Definite means no website, a usable
  phone, signs of being active (hours, address, social or email), and a business type that wins customers online.
  The Prospects list shows "Definitely needs us" by default.
- **Social media = potential (2026-11-22).** No website + usable phone + social pages counts as "definite": they already
  market themselves online but likely have no team or know-how. IOI does not read social sites. The owner opens the page
  and marks it Very active, Some posts or Inactive, which changes the score and the need level. Independent dealers (cars, bikes,
  tyres, electronics, appliances, hardware…) are no longer skipped for carrying a brand tag; company-owned chains still are.
  Records auto-skipped by a rule that was later relaxed are restored at startup.
- **Big projects (2026-11-22).** Public business-news RSS feeds (The Hindu, BusinessLine, ET, ET Infra; robots.txt
  checked) are matched for contracts won, new plants/facilities, investments/expansions and MoUs. Each lead records the
  amount, place and company exactly as stated in the headline (for "X awards contract to Y", the company is Y). IT firms
  and political/market noise are skipped. Leads come with a vendor-approach draft and links to find the company's contact;
  nothing is sent. Runs on demand and every 12 hours when the scheduler is on. First live run: 350 articles, 23 projects.
- **Services expanded with owner approval (2026-11-21).** Website design, SEO and digital marketing, CRM, AI solutions,
  ERP/SAP implementation, and digital strategy. SEO is no longer treated as out of scope.
- **Simplified UI (2026-11-21).** The main menu now has Today, Prospects, Projects & tenders, Messages and Follow-ups,
  and everything else is under "More tools". There is a new "Today" page with four steps and a visual refresh.

- Monorepo, config via env, SQLite + SQLAlchemy 2 + Alembic (21 tables, indexes, FKs, unique and check constraints).
- Source registry with honest statuses (23 sources: 5 live, 3 manual, 1 credential-gated, 14 planned); enable/schedule/config from UI; per-source health, failure counts, run logs.
- Live GeM public bid connector (read-only; service bids only; bid PDF parsed to labelled fields with page refs; structured eligibility incl. MSE/startup relaxation). Disabled by default.
- AI extraction with verbatim-quote verification: document field filling, requirement-clause location (rules still classify/evaluate), classification refinement for uncertain items (≤10 calls/run). Toggles in Settings.
- AI review agent — OpenRouter function calling by default (Anthropic SDK tool runner with `claude-opus-5-5` if `IOI_ANTHROPIC_API_KEY` is ever set): fetches source pages via SafeHttp, records only verbatim-quoted facts, submits clauses to the rule engine, returns a structured eligibility opinion compared with the rules (disagreements flagged). Manual ("AI review" tab), batch, and automatic after discovery (top N, default 3).
- Local browser on the laptop (direct 127.0.0.1, no proxy headers) works without the token; tunnel/LAN/proxied requests always need it. Other devices get a sign-in box on 401.
- Public HTTPS link via Cloudflare quick tunnel (`scripts/public-tunnel.sh`).
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
- **AI features** — used for research briefs, document summaries, outreach drafts, document field extraction, requirement-clause location and classification refinement. Every AI value must match a verbatim quote in the source or it is discarded; eligibility outcomes remain rule-decided. Verification logic is unit-tested with a fake client; agent tools, verification and both provider loops are tested with scripted fake clients.
- **GeM connector** — verified manually once against the live site (search + one bid PDF); a full automated run has not been executed yet. Label parsing is tuned on one bid layout; other layouts may leave fields empty (never invented).
- **Relationship discovery** — regex-based extraction from posts/pages produces hypotheses; precision is modest; human confirmation is the intended workflow.
- **Organisation enrichment** — website only when present in the post; Hacker News posts often link to job boards (filtered as platforms), so many organisations have no website and research falls back to "public thread is the only contact route".
- **Document field extraction** — regex-based; works on conventionally labelled Indian tender documents; unusual layouts will leave fields empty (never fabricated).

## Blocked / not implemented (by design or environment)

- Government portals (TN e-Procurement, CPPP, GePNIC, PSU): CAPTCHA/login-protected (CPPP and TN listings verified CAPTCHA-gated, Nov 2026) — no automated connector; manual document import instead.
- Discord, Indie Hackers, Product Hunt, n8n/Make (beyond generic RSS), directories, chambers of commerce: planned only.
- LinkedIn and freelance marketplaces: intentionally not automated.
- Automatic sending/calling/bidding/registration: intentionally not implemented.

## Known limitations

- **Prospect search depends on free public Overpass mirrors.** On 2026-11-21 one test query succeeded (about 6 s), then all
  three mirrors timed out or returned 504 for the rest of the day, even on tiny queries. The full live path is verified only
  with mocked responses. Progress is now saved after each city. A mirror that fails is skipped for the rest of the run,
  and the run ends early once every mirror has failed (about 2–3 minutes, not hours). There is a Stop button.

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
