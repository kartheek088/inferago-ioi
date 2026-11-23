# IOI 3.1 — Research engine, branch audit and dark UI

_Date: 2026-11-23 · Branch: `ioi-3.1-research` (from verified baseline `ioi-3.0` @ 4aa3b0d)_

## 1. Branch audit (Phase 0)

`git fetch --all --prune`, `git branch -avv`, `git log --all --graph`, `git merge-base`, `git rev-list A..B`, `git diff --stat`.

| Branch | SHA | Purpose | Unique vs. previous | Tests at tip |
|---|---|---|---|---|
| `main` (default) | 53dc98c | v1: opportunity pipeline, GeM, review agent | — | (not re-run; superseded) |
| `prospects-and-big-projects` (PR #1) | 2d73d21 | All-India prospects, Overture, big projects, call list | +6 commits over `main`, 43 files | 179 at the time |
| `ioi-3.0` (PR #2) | 4aa3b0d | Chennai IOI 3.0: new `ioi_*` schema, engine, new UI | +4 over PR #1 (incl. `chennai-refocus` 7d932d3), 91 files | **267 backend + 12 frontend + 1 E2E passed** (re-run 2026-11-23) |

- History is **linear**: `main` ⊂ `prospects-and-big-projects` ⊂ `ioi-3.0`. No divergence → no merge conflicts.
  (`chennai-refocus` is a local branch equal to tag `v2.5-chennai`, an ancestor of `ioi-3.0`.)
- The running app (`systemd --user` service `ioi`, cwd `backend/`, `uv run python -m app.main`) was on `ioi-3.0` with DB
  migration `0011_ioi3` — code and schema matched. The built UI in `frontend/dist` came from the same commit.
- Only uncommitted change: `frontend/tsconfig.tsbuildinfo` (build artifact) → stashed (`git stash list`), not discarded.
- **Baseline:** `ioi-3.0` @ 4aa3b0d, tagged `baseline-3.0-4aa3b0d`. Work happens on `ioi-3.1-research`.
- Nothing was reset, force-pushed, deleted or merged. PRs #1 and #2 are untouched.

**Recommended integration order (needs your approval):** merge PR #2 (`ioi-3.0` → `main`, which also contains PR #1, so #1
can then be closed), then open `ioi-3.1-research` → `main`. Each is a fast-forward of the previous.

## 2. Discovery engine diagnosis (Phase 1)

### Run #3 failed — root cause (from persisted evidence)
`ioi_jobs.error`: `OperationalError: database is locked` on `UPDATE ioi_jobs SET stage=… WHERE id=3` at 21:35:40.594, 74 ms after
the job started. `activity_logs`: `onboarding_completed` written at 21:35:40.528 — the onboarding wizard starts the first run and
then immediately saves "onboarding done". In SQLite WAL mode a transaction that **read** before another connection **committed**
fails its first write immediately with `SQLITE_BUSY` ("database is locked"); `busy_timeout` does not apply to that case. The worker's
session read the job row, the API committed, the worker's write failed, and the whole job was marked failed.
The same race could hit any long research step if the UI wrote anything meanwhile.

**Fix:** job progress is written in its own short, retried transactions (`fetch.short_write` / `with_retry`); the work session never
keeps a transaction open across network I/O (`research_many` commits before fetching; `scan_news` fetches all feeds first); every
company/ingest commit is retried on lock conflicts. Regression test: `test_concurrent_research_survives_concurrent_writes`.

### What the numbers meant (Run #4: "50 checked · 49 added · 123 rejected · 86 needing checking")
| Shown | Actually was | Problem |
|---|---|---|
| 50 checked / 49 added | this run's reviewed / newly inserted | ok |
| **123 rejected** | 95 outside-city + 28 chain outlets **across the whole directory file**, recounted identically every run (they're filtered before ingestion, so never marked "seen") | not per-run; same number every run |
| **86 needing checking** | campaign-wide count of P2 companies | campaign total shown next to per-run numbers |

**Fix:** metrics now come in three labelled groups — **This run** (reviewed, added, duplicates, researched, research failed, newly
qualified, AI calls) · **Directory file** (relevant not yet reviewed, outside city, chain outlets) · **Campaign totals** (businesses,
need verification, pass every check, ready to review). Plus elapsed time and "last successful step".

### Other findings fixed
- AI **was** used in Deep Run #4 (8 calls, ~$0.002, 7 quote-checked facts) but nothing in the UI showed it → AI status, usage and an
  auditable agent trace are now visible.
- No page caching; websites researched one after another → page cache + 4 concurrent fetchers (per-host rate limit unchanged).
- SafeHttp treated `304 Not Modified` as a redirect ("Redirect without location") → fixed.
- Stale "running" jobs were only recovered at restart → also detected live (no heartbeat for 3 min → interrupted).
- Failed websites: retryable (timeouts/5xx: retry after 1 day) vs permanent (DNS gone, 403, 404, robots: 30 days).
- Failing news feeds back off 1 h → 2 h → … → 24 h.

## 3. Performance (Phase 3) — measured, reproducible

`backend/scripts/bench_research.py`: 12 synthetic company sites served locally (127.0.0.2–13:8080), 4 pages each, fixed 250 ms
latency, throwaway DB, real SafeHttp (rate limit 20/min per host, robots.txt). Same harness run on the baseline code (git worktree of
`baseline-3.0-4aa3b0d`) and on 3.1.

| | Baseline 3.0 | 3.1 | Change |
|---|---|---|---|
| Cold run, 12 companies | **147.6 s** | **38.1 s** | 3.9× faster |
| Warm re-run (unchanged sites) | 147.5 s | **0.48 s** | page cache |
| HTTP requests (cold / warm) | 60 / 60 | 60 / **0** | |
| Time to first qualified prospect | 12.4 s | 12.5 s | unchanged (polite 3 s spacing per site) |
| Companies OK / sales-ready | 12 / 12 | 12 / 12 | same results |
| AI calls | 0 | 0 | (benchmark is AI-free) |

## 4. Security (Phase 6) — tested

| Threat | Control | Test |
|---|---|---|
| SSRF via agent (metadata IP, other hosts) | agent may only fetch the company's own domain; SafeHttp blocks private/metadata IPs incl. after redirects | `test_agent_ignores_prompt_injection_and_blocks_other_hosts`, `tests/test_security.py` |
| Prompt injection in page text | content wrapped as untrusted; system rule; tools can't act outside their checks | same test: injected "fetch 169.254.169.254" is refused, never requested |
| Fabricated claims | every fact/person needs a verbatim quote found on a page fetched in that session | `test_agent_researches_with_verified_quotes_and_audit_trail` |
| Arbitrary tools / code | fixed typed tool set; unknown tools refused | same (`run_shell` refused) |
| Runaway loops / cost | limits: 6 AI calls, 14 tools, 6 pages, 40k tokens, 150 s, $0.03, 3 consecutive failures | `test_agent_limits_stop_endless_loops` |
| AI outage | "AI unavailable — rule-based research active"; no AI fields claimed | `test_agent_unavailable_falls_back_honestly` |
| Secrets / personal data in logs | tool args redacted (emails, phones); API never returns keys | agent tests; settings test |
| Outreach | no tool or endpoint sends anything | by design |

## 5. Sources and limitations

Working: Overture places (local open-data file), official company websites (cached), Chennai business news RSS, CSV import,
manual entry, optional OpenRouter AI. **Not available** (no permitted access): Google Maps/Reviews, LinkedIn, Facebook/Instagram,
JustDial, IndiaMART, web search APIs (none configured). So "public reputation" is limited to what companies publish on their own
sites (labelled *company-published*) and news. Owner/management contacts come only from the company's own pages.

## 6. Database migration and rollback

- `0012_research_engine` is additive: new tables `ioi_page_cache`, `ioi_people`, `ioi_agent_events`; new columns on `ioi_companies`
  and `ioi_facts` with server defaults. Tested on a copy of live data: upgrade → downgrade → upgrade, no drift.
- Backup before upgrading: `backend/data/backups/ioi-20261123-031854.db` (integrity ok).
- Roll back code: `git checkout baseline-3.0-4aa3b0d`; roll back schema: `cd backend && uv run alembic downgrade 0011_ioi3`
  (drops only the 3.1 tables/columns), or stop IOI and restore the backup file.

## 7. Real-world validation (live app, real sources, 2026-11-23)

Deep runs #5–#8 on the live campaign (Overture places + official websites + news RSS + OpenRouter `openrouter/auto`).

| | Result |
|---|---|
| Businesses in campaign | 118 Chennai candidates (directory: 985 relevant listings still unreviewed; 95 outside city, 28 chain outlets never added) |
| Researched on their official website without error | **30** |
| Chennai-city address verified on the official site | 14 |
| Pass every mandatory check → *Ready to approach* | **2**: Stroke Equipments India Pvt Ltd (Parrys), FitnessOne Equipment Store (Nanganallur/Velachery) |
| Strong operational fit, one check open (mostly "recent activity" — no dated content on their site) | e.g. Intech Systems (Guindy), S.K. Power Systems, Air-O-Matic Systems (Adyar), Qmax Test Equipments (Sholinganallur), ABS Instruments (Guindy) |
| Size check opened (public limited) | TAFE, Sindu Building Equipments Ltd — moved to *Needs verification*, not silently accepted |
| AI agent | Intech Systems: 5 quote-verified facts (Guindy HQ address, after-sales service line + service-request form, 5-state support network, stated 180+ staff / 35+ years); 1 malformed claim rejected |
| AI usage so far | 21 calls · 76k tokens · **$0.009** (Settings → AI) |
| P0 / P1 | **0** — no dated buying signal was found; news feeds had no relevant Chennai items. No leads were fabricated. |

### Incidents found during validation (all fixed, with regression tests)
1. **Flaky DNS on this computer** (`[Errno -3] Temporary failure in name resolution`; a probe showed ~1 in 3 lookups failing via
   systemd-resolved → router 192.168.1.1). IOI had classified every failure as "domain doesn't exist" (30-day back-off).
   Fixes: keep the DNS error code; EAI_AGAIN is retryable (15-min back-off) and retried 3× in the resolver; true NXDOMAIN stays
   permanent; ≥3 network failures with no success stop the research stage with a plain message and skip AI; OpenRouter retries
   back off. The 15 wrongly backed-off companies were reset.
2. **Agent "database is locked"** (Run #7): the AI-usage log session read, tools wrote the page cache, then the next usage write
   failed. Fix: end the read before each AI call. Regression test fails without the fix, passes with it.
3. **Snippet-as-address**: a page window was stored as the company address. Fix: `clean_address` (door/plot no. → PIN, stops at
   contact details; blank if no clean address). Also: older facts lacked `source_type` (backfilled; migration 0012 includes it),
   shortlisted companies that no longer pass a gate now leave *Ready to approach*, job log times are local.

### Known limitations
- `openrouter/auto` sometimes routes to a model that rejects tool calls (`HTTP 404: No models satisfy the decisions policy`).
  Setting `IOI_OPENROUTER_MODEL` to a specific tool-capable model would make the agent more reliable (owner's choice; not changed).
- Public reputation is limited to company-published pages and news (no permitted access to Google reviews, social platforms,
  JustDial/IndiaMART, or a search API). Management contacts appear only when the company's own site publishes them.
- Many small Chennai firms show no dated content on their sites, so "current activity" often needs a 1-minute phone check
  (Prospect → Correct details → "I confirmed they're operating now").
- Agent token budget (40k) is reached after ~5 AI calls because page text accumulates in the conversation.

Screenshots of the running app (live data; kept local, not committed because they show real business contacts):
`frontend/e2e/live-screens.mjs <out-dir> [company-id]` regenerates them read-only.
